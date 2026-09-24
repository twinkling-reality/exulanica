"""The Companion's place-content answer, through the real renderer and the real route.

``POST /selection/ask`` answers a CONTENT plan from its rows. It needs no model: the plan comes
from a confirmed place bridge or from the caller, CONTENT refuses a semantic query, and
:func:`~exulanica.selection.question.render_content_answer` writes every sentence. These tests run
the route with ``model_client=None`` and check that a confirmed place answers with its rows, that
an unbridged place is refused in words, that anything which does need a model still answers 503,
and that no answer sentence carries an identifier in place of a description.

The fixture is built through repository calls, not product routes, because no product route
creates what a non-empty answer needs: a canonical ``place`` row (written only by
``place_alignment.establish_place``, which nothing in production calls), a derived render asset
(``EnvironmentRepository.register_derived`` has no route) and a place entity (proposed only by the
vision model during intake). So this is evidence of the answering mechanics, not of a reachable
browser flow.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.environment import (
    DerivedEnvironmentAsset,
    EnvironmentFeatureInput,
    EnvironmentRepository,
    FeatureIndexPublication,
    GeographicBounds,
    GeographicFrame,
    OperationRights,
    SourceAdmission,
)
from exulanica.environment.nyc_open_data import PROVIDER_KEY
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository, name_occurrence
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.repository import IngestRepository
from exulanica.selection import SelectionPlan, Session
from exulanica.selection.executor import SelectedContent
from exulanica.selection.question import answer_question, render_content_answer, requires_model
from exulanica.store.local import LocalContentAddressedStore
from fastapi.testclient import TestClient

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, write_photo
from tests_support_api import EVERY_PERMISSION, scratch_database
from world_support import registered_world

UUID_TEXT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TOKEN = "companion-content-surface-owner-token"


def _not_reached(capture_ids, handoff):
    """Each call below is refused before any query runs, so the right check is never reached."""
    raise AssertionError("the right check was reached on a path that runs no query")


def _row(kind: str, *, label: str | None, source_id: str) -> SelectedContent:
    place = uuid.uuid4()
    return SelectedContent(
        result_kind=kind,
        origin_kind="personal" if kind == "memory_capture" else "imported",
        content_kind="capture" if kind == "memory_capture" else "environment_feature",
        authored_role=None,
        place_relationship="captured_at" if kind == "memory_capture" else "admitted_for",
        match_reason="confirmed_memory_place",
        memory_place_entity_id=place,
        canonical_place_id=None,
        world_id=None,
        version_id=None,
        source_id=source_id,
        lineage_ids=(f"capture:{source_id}",),
        label=label,
        availability="available",
        personal_visit_evidence=kind == "memory_capture",
    )


def test_an_unlabelled_row_is_described_by_kind_never_by_its_identifier() -> None:
    capture = str(uuid.uuid4())
    feature = f"{uuid.uuid4()}:0123456789abcdef0123456789abcdef"
    answer = render_content_answer(
        (
            _row("memory_capture", label=None, source_id=capture),
            _row("admitted_environment_feature", label=None, source_id=feature),
            _row("admitted_environment_feature", label="Synthetic Hall", source_id=feature),
        )
    )
    texts = [clause.text for clause in answer.clauses]

    assert texts[0] == "Authorized memory evidence: a photograph in your library."
    assert texts[1] == "Source-derived feature: a feature derived from an admitted source."
    assert texts[2] == "Source-derived feature: Synthetic Hall."
    assert not any(capture in text or feature in text for text in texts)
    assert not any(UUID_TEXT.search(text) for text in texts)


def test_only_a_supplied_content_plan_answers_without_a_model() -> None:
    content = SelectionPlan.model_validate(
        {
            "intent": "content",
            "place": {"ids": [str(uuid.uuid4())]},
            "content": {"scope": "related"},
        }
    )
    capture = SelectionPlan.model_validate({"intent": "captures"})

    assert requires_model(None)
    assert requires_model(capture)
    assert not requires_model(content)
    # Refused before any query runs: the connection is never touched.
    with pytest.raises(ValueError, match="model client is required"):
        answer_question(
            object(),
            None,
            "What is here?",
            Session(uuid.uuid4(), uuid.uuid4()),
            world_id=None,
            before_compose=_not_reached,
        )
    with pytest.raises(ValueError, match="model client is required"):
        answer_question(
            object(),
            None,
            "Show me",
            Session(uuid.uuid4(), uuid.uuid4()),
            world_id=None,
            plan=capture,
            before_compose=_not_reached,
        )


# ---------------------------------------------------------------------------------------------
# The route, against PostgreSQL, with no model configured
# ---------------------------------------------------------------------------------------------


def _rights() -> OperationRights:
    return OperationRights.model_validate(
        {
            "display": True,
            "extract": True,
            "index": True,
            "persist": True,
            "modify": True,
            "compose": True,
            "export": False,
            "model_processing": False,
        }
    )


def _frame() -> GeographicFrame:
    return GeographicFrame(
        name="nyc-grid",
        crs="EPSG:6539",
        axis_order=("east", "north", "height"),
        horizontal_unit="metre",
        vertical_unit="metre",
        orientation="right-handed",
        altitude_reference="NAVD88",
    )


def _bounds() -> GeographicBounds:
    return GeographicBounds(
        kind="bbox",
        frame_name="nyc-grid",
        coordinate_scale=1000,
        coordinates=(0, 0, 0, 100_000, 100_000, 10_000),
    )


@pytest.fixture
def place_content(repository, tmp_path, photo_dir, spine_schema, monkeypatch):
    """One admitted NYC building, its canonical place and a named memory place with a photo."""
    actor = uuid.uuid4()
    connection = repository.connection
    place_id = uuid.uuid4()
    connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place_id),
    )
    store = LocalContentAddressedStore(tmp_path / "content-surface-store")
    environments = EnvironmentRepository(connection, repository.workspace_id, store)
    source_bytes = b"synthetic admitted NYC building source"
    source_path = tmp_path / "source.geojson"
    source_path.write_bytes(source_bytes)
    source = SourceAdmission(
        place_id=place_id,
        provider_key=PROVIDER_KEY,
        provider_original_id="synthetic-buildings",
        provider_revision="2026-09-22",
        expected_sha256=hashlib.sha256(source_bytes).hexdigest(),
        expected_byte_size=len(source_bytes),
        source_path="synthetic/source.geojson",
        media_type="application/geo+json",
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(),
        attribution="Synthetic building records",
        modification_notice="Synthetic fixture, unchanged",
        local_path=source_path,
    )
    environments.admit_source(source, actor=actor)
    render_bytes = b"synthetic render asset"
    render_path = tmp_path / "render.glb"
    render_path.write_bytes(render_bytes)
    render = DerivedEnvironmentAsset(
        admission_id=source.admission_id,
        expected_sha256=hashlib.sha256(render_bytes).hexdigest(),
        expected_byte_size=len(render_bytes),
        media_type="model/gltf-binary",
        derivation_kind="fixture-render",
        derivation_lineage={"method": "fixture/v1", "input_sha256": [source.expected_sha256]},
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(),
        attribution="Synthetic building records",
        modification_notice="Synthetic render fixture",
        local_path=render_path,
    )
    environments.register_derived(render, actor=actor)
    publication = environments.publish_feature_index(
        source.admission_id,
        FeatureIndexPublication(
            render_asset_id=render.asset_id,
            features=(
                EnvironmentFeatureInput(
                    provider_feature_id="doitt_id:1",
                    kind="building",
                    bbox=(0, 0, 0, 100, 100, 100),
                    label="Synthetic Hall",
                    render_batch_id=1,
                    semantic_properties={"name": "Synthetic Hall", "bin": "bin:1000001"},
                ),
            ),
        ),
        actor=actor,
    )

    ingest = IngestRepository(connection, repository.workspace_id)
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    payload["proposed_place"]["label"] = "Synthetic Hall"
    outcome = ingest_observed(
        PhotoIngestPipeline(ingest, store, vision=CountingVisionModel(payload=payload)),
        ingest,
        write_photo(photo_dir, "synthetic-hall.jpg", when="2026:09:20 10:00:00", size=(160, 100)),
    )
    assert outcome.error is None, outcome.error
    occurrence = connection.execute(
        "select occurrence_id from occurrence "
        "where workspace_id=%s and capture_id=%s and class='place'",
        (repository.workspace_id, outcome.capture_id),
    ).fetchone()
    named = name_occurrence(
        IdentityRepository(connection, repository.workspace_id),
        AssertionWriter(connection, repository.workspace_id),
        occurrence_id=occurrence["occurrence_id"],
        display_name="Synthetic Hall",
        actor=actor,
    )
    # The world the Companion is asked in; its content here is the workspace's own.
    world_id = registered_world(connection, repository.workspace_id)
    connection.commit()

    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(repository.workspace_id),
                    "actor": str(actor),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
    )
    _psycopg, scratch = spine_schema
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    return {
        "services": services,
        "city_context": {
            "admission_id": str(source.admission_id),
            "feature_id": publication.features[0]["id"],
        },
        "bridge": {
            "canonical_place_id": str(place_id),
            "memory_place_entity_id": str(named.entity_id),
            "reason": "Synthetic fixture: the account holder confirmed these are one place.",
        },
        "capture_id": str(outcome.capture_id),
        "entity_id": str(named.entity_id),
        "world_id": world_id,
    }


def _ask(client: TestClient, body: dict, world_id: str) -> dict:
    response = client.post(
        f"/selection/ask?world_id={world_id}",
        json=body,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    return {"status": response.status_code, "body": response.json()}


@pytest.mark.postgres
def test_a_confirmed_place_answers_with_its_content_and_no_model(place_content) -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(create_app(place_content["services"], verify=False)) as client:
        refused = _ask(
            client,
            {"question": "What is here?", "city_context": place_content["city_context"]},
            place_content["world_id"],
        )
        assert refused["status"] == 200, refused
        assert refused["body"]["plan"] is None and refused["body"]["selection"] is None
        assert "no confirmed memory-place bridge" in refused["body"]["answer"]["clauses"][1]["text"]

        created = client.post(
            "/selection/place-bridges", json=place_content["bridge"], headers=headers
        )
        assert created.status_code == 201, created.text

        answered = _ask(
            client,
            {"question": "What is here?", "city_context": place_content["city_context"]},
            place_content["world_id"],
        )

    assert answered["status"] == 200, answered
    body = answered["body"]
    assert body["deterministic"] is True
    assert body["abstained"] is None
    assert body["execution"]["calls"] == []
    assert body["plan"]["intent"] == "content"
    kinds = {row["result_kind"] for row in body["selection"]["content"]}
    assert kinds == {
        "memory_capture",
        "admitted_environment_source",
        "admitted_environment_feature",
    }
    memory = next(r for r in body["selection"]["content"] if r["result_kind"] == "memory_capture")
    assert memory["source_id"] == place_content["capture_id"]
    assert memory["personal_visit_evidence"] is True
    texts = [clause["text"] for clause in body["answer"]["clauses"]]
    assert "Authorized memory evidence: a photograph in your library." in texts
    assert "Source-derived feature: Synthetic Hall." in texts
    assert texts[-1].startswith("Only memory captures can support a personal visit.")
    # The city clause names official identifiers; no clause names a capture or database id.
    assert not any(UUID_TEXT.search(text) for text in texts)
    assert not any(place_content["capture_id"] in text for text in texts)


@pytest.mark.postgres
def test_a_supplied_content_plan_answers_without_a_model(place_content) -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    plan = {
        "intent": "content",
        "place": {"ids": [place_content["entity_id"]]},
        "content": {"scope": "memories_only"},
    }
    with TestClient(create_app(place_content["services"], verify=False)) as client:
        assert (
            client.post(
                "/selection/place-bridges", json=place_content["bridge"], headers=headers
            ).status_code
            == 201
        )
        answered = _ask(
            client, {"question": "My photographs here", "plan": plan}, place_content["world_id"]
        )

    assert answered["status"] == 200, answered
    assert answered["body"]["deterministic"] is True
    assert {row["result_kind"] for row in answered["body"]["selection"]["content"]} == {
        "memory_capture"
    }


@pytest.mark.postgres
def test_questions_that_need_a_model_still_answer_503_without_one(place_content) -> None:
    with TestClient(create_app(place_content["services"], verify=False)) as client:
        in_words = _ask(client, {"question": "What is in this place?"}, place_content["world_id"])
        capture_plan = _ask(
            client,
            {"question": "Photos", "plan": {"intent": "captures"}},
            place_content["world_id"],
        )

    for refused in (in_words, capture_plan):
        assert refused["status"] == 503, refused
        assert "no model credential is configured" in refused["body"]["detail"]
