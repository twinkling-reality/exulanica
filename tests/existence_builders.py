"""How the existence sweep makes a real object of each id kind in the owner's workspace.

``tests/route_probes.py`` names each kind by its address and points at a function here. Each
function takes the sweep's owner context from ``tests/test_existence_oracle.py`` and returns the
id it made, or a mapping from address to id when making the object also made the object it lives
in: a society action request exists inside a version whose society can take one, so its builder
makes that version too and says so, and the sweep asks about the pair it made.

The owner context offers ``request`` (an HTTP call with the owner's token), ``real`` (another
kind's id, made once per test), ``repository`` (the owner's repository on an administrative
autocommit connection), ``workspace_id``, ``actor`` (the owner token's actor), ``store`` and
``tiles`` (the application's content and tile stores), ``photo_dir``, ``tmp_path``, ``app``,
``society_inputs`` (the society input the application's adapter hands a version) and ``memo``
(objects several builders share within one test). A builder goes through the API where the API
can make the object, and through the domain where only a worker or an operator can, and says
which.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Final

import pytest
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
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.evidence.blob import BlobId
from exulanica.identity import IdentityRepository, name_occurrence
from exulanica.ingest.batch import IntakeBatch
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.world import TopologyContract, TopologySourceSlot, WorldStyleRepository
from exulanica.world.assets import reviewed_assets
from exulanica.world.society_comparison_repository import SocietyComparisonRepository
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_experiments import DEVELOPMENT_SEEDS
from exulanica.world.society_repository import SocietyRepository

import comparison_support
import door_support
import things_society_support as things_support
from conftest import (
    DEFAULT_PAYLOAD,
    CountingVisionModel,
    ingest_observed,
    write_photo,
    write_point_map,
)
from retired_society_support import plant_retired_decision, plant_retired_society
from social_society_fixtures import social_input
from society_fixtures import SEED, society_input
from society_living_fixtures import grid_input
from static_glb_builder import cube
from test_material_recipes import _small
from thing_fixtures import kind_body, placeable_kind
from workspace_asset_support import declaration as workspace_asset_declaration
from world_support import FIXTURE_WORLD_ID, registered_world

ROOT = Path(__file__).resolve().parents[1]
#: The owner's world. The stranger's workspace holds a world by the same id, so a world route a
#: stranger is sent to reaches its own lookup rather than stopping at a world the stranger lacks.
WORLD = FIXTURE_WORLD_ID
#: The topology the owner's world is composed over, with one source slot so a source id exists.
TOPOLOGY = "existence-topology"
#: The region every authored thing in the owner's world is placed in.
REGION = "region-a"
#: A society profile each builder asks for by name, because what a society can do depends on it:
#: actions and a comparison of models need v2, a stored model proposal needs v3, which is retired
#: and so is planted as it was stored, and experiments need v4.
PURPOSEFUL = "exulanica-society/v2"
SOCIAL = "exulanica-society/v3"
LIVING = "exulanica-society/v4"
#: A society of things, whose card and look routes ask about a thing by the id the society gives it.
THINGS = "exulanica-society/v7"


def _ok(response, *expected: int) -> Any:
    assert response.status_code in expected, (response.status_code, response.text)
    return response.json() if response.content else None


def in_world(owner, method: str, path: str, **kwargs):
    """A request to a world route with the owner's token, in the owner's world (API)."""
    return owner.request(method, path, params={"world_id": WORLD}, **kwargs)


# -- the photograph and what ingest makes of it -----------------------------------------------


def photograph(owner) -> dict[str, Any]:
    """One ingested photograph with a person in it, made once per test (domain: ingest)."""
    if "photograph" not in owner.memo:
        payload = copy.deepcopy(DEFAULT_PAYLOAD)
        payload["objects"] = [
            {
                "label": "person",
                "salience": "primary",
                "confidence": "high",
                "box": {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.6},
            }
        ]
        pipeline = PhotoIngestPipeline(
            owner.repository, owner.store, vision=CountingVisionModel(payload=payload)
        )
        outcome = ingest_observed(
            pipeline, owner.repository, write_photo(owner.photo_dir, "existence.jpg")
        )
        assert outcome.error is None, outcome.error
        row = owner.repository.connection.execute(
            "select capture_id, blob_sha256 from capture where capture_id = %s",
            (outcome.capture_id,),
        ).fetchone()
        owner.memo["photograph"] = dict(row)
    return owner.memo["photograph"]


def capture(owner) -> uuid.UUID:
    return photograph(owner)["capture_id"]


def evidence_span(owner) -> uuid.UUID:
    row = owner.repository.connection.execute(
        "select span_id from evidence_span "
        "where workspace_id = %s and blob_sha256 = %s and modality = 'still_image' limit 1",
        (owner.workspace_id, photograph(owner)["blob_sha256"]),
    ).fetchone()
    return row["span_id"]


def point_map(owner) -> uuid.UUID:
    """A depth artifact of the photograph, written as the depth stage writes it (domain)."""
    artifact_id, _ = write_point_map(
        owner.repository, owner.store, BlobId(bytes(photograph(owner)["blob_sha256"]))
    )
    return artifact_id


def intake_batch(owner) -> uuid.UUID:
    """A closed batch: an open one would keep the formation stream waiting (domain)."""
    batch = IntakeBatch.open(owner.repository, label="existence")
    batch.declare_size(1)
    batch.close("succeeded")
    return batch.batch_id


# -- the owner's world --------------------------------------------------------------------------


def world(owner) -> dict[str, Any]:
    """The owner's composed world: a topology with one source slot, bootstrapped (API)."""
    if "world" not in owner.memo:
        source_id = uuid.uuid4()
        registered_world(owner.repository.connection, owner.workspace_id, WORLD, actor=owner.actor)
        WorldStyleRepository(
            owner.repository.connection, owner.workspace_id, world_id=WORLD
        ).register_topology(
            TopologyContract(
                TOPOLOGY,
                (REGION,),
                (
                    TopologySourceSlot(
                        source_id=source_id,
                        slot_key="hero-memory",
                        region_id=REGION,
                        evidence_span_id=None,
                        missing_reason="no evidence was recorded",
                    ),
                ),
                world_id=WORLD,
            )
        )
        booted = _ok(
            in_world(
                owner, "POST", "/world/versions/bootstrap", json={"base_topology_digest": TOPOLOGY}
            ),
            200,
        )
        owner.memo["world"] = {**booted, "source_id": source_id}
    return owner.memo["world"]


def _place(owner) -> uuid.UUID:
    place = uuid.uuid4()
    owner.repository.connection.execute(
        "insert into place(workspace_id, place_id) values (%s, %s)", (owner.workspace_id, place)
    )
    return place


def _version_with_society(owner, profile: str, document) -> dict[str, Any]:
    """A new version of the owner's world holding a society of ``profile`` (API)."""
    snapshot = world(owner)["snapshot_id"]
    version = _ok(
        in_world(
            owner,
            "POST",
            "/world/versions",
            json={"title": f"existence {profile}", "source_snapshot_id": snapshot},
        ),
        201,
    )
    version_id = uuid.UUID(version["version_id"])
    owner.society_inputs[version_id] = document(version_id)
    society = _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/society",
            json={"place_id": str(_place(owner)), "region_id": REGION, "profile": profile},
        ),
        200,
    )
    return {"version_id": version_id, "society": society}


def _plain_version(owner) -> uuid.UUID:
    """A new version of the owner's world with no society in it (API)."""
    version = _ok(
        in_world(
            owner,
            "POST",
            "/world/versions",
            json={"title": "existence", "source_snapshot_id": world(owner)["snapshot_id"]},
        ),
        201,
    )
    return uuid.UUID(version["version_id"])


def world_version(owner) -> uuid.UUID:
    """A version with a living society, the profile the most society routes can answer."""
    return _version_with_society(
        owner, LIVING, lambda version_id: grid_input(version_id=version_id)
    )["version_id"]


def source_media(owner) -> uuid.UUID:
    return world(owner)["source_id"]


def avatar(owner) -> uuid.UUID:
    """The owner's avatar, with one saved look (API).

    An avatar's subject id is the actor it belongs to. The look is saved so the owner's writes
    and resets are answered by its revision, which a stranger's never reach.
    """
    from character_appearance_fixtures import recipe

    version_id = owner.real("/world/versions/{version_id}")
    _ok(
        in_world(
            owner,
            "PUT",
            f"/world/versions/{version_id}/characters/avatar/{owner.actor}/appearance",
            json={"base_revision": 0, "recipe": recipe().model_dump(mode="json")},
        ),
        200,
    )
    return owner.actor


_TRANSFORM = {"x_mm": 0, "y_mm": 0, "z_mm": 0, "yaw_microradians": 0, "scale_milli": 1000}
#: The reviewed asset an object is made of, read from the registry migration 0042 installs for
#: every workspace; an object names its asset by content digest.
CUBE = next(asset for asset in reviewed_assets() if asset.asset_key == "cc0.marker-cube")


def world_object(owner) -> dict[str, Any]:
    """An authored object placed in a version of its own, with no society (API).

    A version holding a living society takes an authored edit only through the society runtime's
    authored-input adapter, which this application is built without, so the object goes where an
    edit is an edit.
    """
    version_id = _plain_version(owner)
    current = _ok(in_world(owner, "GET", f"/world/versions/{version_id}"), 200)
    object_id = "object:existence"
    _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/objects",
            json={
                "base_state_sha256": current["state_sha256"],
                "object_id": object_id,
                "asset_sha256": CUBE.content_sha256,
                "region_id": REGION,
                "transform": _TRANSFORM,
                "origin_role": "fictional",
            },
        ),
        201,
    )
    return {
        "/world/versions/{version_id}": version_id,
        "/world/versions/{version_id}/objects/{object_id}": object_id,
    }


def invented_object() -> str:
    return f"object:{uuid.uuid4().hex}"


def placed_thing(owner) -> dict[str, Any]:
    """A thing placed by a shipped kind in a version of its own, with no society (API)."""
    version_id = _plain_version(owner)
    current = _ok(in_world(owner, "GET", f"/world/versions/{version_id}"), 200)
    thing_id = "thing:existence"
    _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/things",
            json={
                "base_state_sha256": current["state_sha256"],
                "thing_id": thing_id,
                "kind": kind_body(placeable_kind()),
                "region_id": REGION,
                "pose": {"x_mm": 0, "y_mm": 0, "z_mm": 0, "yaw_microradians": 0},
                "origin_role": "fictional",
            },
        ),
        201,
    )
    return {
        "/world/versions/{version_id}": version_id,
        "/world/versions/{version_id}/things/{thing_id}": thing_id,
    }


def invented_thing() -> str:
    return f"thing:{uuid.uuid4().hex}"


def society_thing(owner) -> dict[str, Any]:
    """A thing of a society of things, by the id the society gives it, in a version of its own:
    the small square with the first placeable kind placed in it, composed for that version, and
    the society made on the things engine, which the application then offers (API)."""
    owner.app.state.services = dataclasses.replace(
        owner.app.state.services, societies_of_things=True
    )
    snapshot = world(owner)["snapshot_id"]
    version = _ok(
        in_world(
            owner,
            "POST",
            "/world/versions",
            json={"title": "existence things", "source_snapshot_id": snapshot},
        ),
        201,
    )
    version_id = uuid.UUID(version["version_id"])
    kind = placeable_kind()
    owner.society_inputs[version_id] = things_support.compose(
        [things_support.thing("existence-thing", kind.kind, kind.version, 0, 0)],
        version_id=version_id,
        world_id=WORLD,
        source_snapshot_id=uuid.UUID(str(snapshot)),
    )
    society = _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/society",
            json={
                "place_id": str(_place(owner)),
                "region_id": "region:starter",
                "profile": THINGS,
            },
        ),
        200,
    )
    [thing] = [t for t in society["state"]["things"] if t["placed_id"] == "existence-thing"]
    # A being of the same society, by the id the play and people routes take.
    being = society["state"]["inhabitants"][0]["id"]
    return {
        "/world/versions/{version_id}": version_id,
        "/world/versions/{version_id}/society/things/{thing_id}": thing["id"],
        "/world/versions/{version_id}/society/people/{subject_id}": being,
        "/world/versions/{version_id}/society/play/{subject_id}": being,
    }


def selected_subject(owner) -> dict[str, Any]:
    """A real being's subject reference and its owning version, created through the API."""
    made = society_thing(owner)
    being = made["/world/versions/{version_id}/society/play/{subject_id}"]
    return {
        "/world/versions/{version_id}": made["/world/versions/{version_id}"],
        "/world/versions/{version_id}/subjects/{ref}": f"being:{being}",
    }


def invented_subject() -> str:
    return f"being:{uuid.uuid4()}"


# -- admitted environment sources --------------------------------------------------------------


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


def _rights() -> OperationRights:
    return OperationRights(
        display=True,
        extract=True,
        index=True,
        persist=True,
        modify=True,
        compose=True,
        export=False,
        model_processing=False,
    )


def environment(owner) -> dict[str, Any]:
    """An admitted source, a render derived from it and a published feature index (domain).

    Admission is an operator's act on a file already on the machine, so the domain makes it; the
    application's own store receives the bytes, which is what its routes read.
    """
    if "environment" not in owner.memo:
        repository = EnvironmentRepository(
            owner.repository.connection, owner.workspace_id, owner.store
        )
        source_bytes = b"existence sweep source"
        source_path = owner.tmp_path / "existence-source.bin"
        source_path.write_bytes(source_bytes)
        source = SourceAdmission(
            place_id=_place(owner),
            provider_key="nyc-open-data",
            provider_original_id="existence",
            provider_revision="2026-09-23",
            expected_sha256=hashlib.sha256(source_bytes).hexdigest(),
            expected_byte_size=len(source_bytes),
            source_path="fixture/existence-source.bin",
            media_type="application/octet-stream",
            geographic_frame=_frame(),
            geographic_bounds=_bounds(),
            operation_rights=_rights(),
            attribution="Synthetic fixture",
            modification_notice="Synthetic fixture is unchanged",
            local_path=source_path,
        )
        repository.admit_source(source, actor=owner.actor)
        render_bytes = b"existence sweep render"
        render_path = owner.tmp_path / "existence-render.glb"
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
            attribution="Synthetic fixture",
            modification_notice="Synthetic render fixture",
            local_path=render_path,
        )
        repository.register_derived(render, actor=owner.actor)
        repository.publish_feature_index(
            source.admission_id,
            FeatureIndexPublication(
                render_asset_id=render.asset_id,
                features=(
                    EnvironmentFeatureInput(
                        provider_feature_id="doitt_id:1",
                        kind="building",
                        bbox=(0, 0, 0, 100, 100, 100),
                        label="Fixture building",
                        render_batch_id=7,
                    ),
                ),
            ),
            actor=owner.actor,
        )
        owner.memo["environment"] = {
            "admission_id": source.admission_id,
            "render_asset_id": render.asset_id,
        }
    return owner.memo["environment"]


def environment_source(owner) -> uuid.UUID:
    return environment(owner)["admission_id"]


def place_declaration(caller, place_id: str | None = None) -> dict[str, Any]:
    """A request declaring a place's frame, under ``place_id`` when one is given.

    Each request states its frame in words of its own, so two requests are two different frames:
    a caller declaring an id it already declared is a conflict, never a retry of the same thing.
    """
    body: dict[str, Any] = {
        "provider_key": "nyc-open-data",
        "provider_frame_statement": (
            f"The provider publishes these bounds in this frame, statement {uuid.uuid4().hex}."
        ),
        "geographic_frame": _frame().model_dump(mode="json"),
        "geographic_bounds": _bounds().model_dump(mode="json"),
    }
    if place_id is not None:
        body["place_id"] = place_id
    return {"json": body}


def declared_place(owner) -> str:
    """A place whose frame a provider declared (API)."""
    made = _ok(
        owner.request("POST", "/environment-resources/places", **place_declaration(owner)), 201
    )
    return made["place_id"]


def environment_instance(owner) -> dict[str, Any]:
    """An admitted render placed whole in a version of its own, with no society (API)."""
    version_id = _plain_version(owner)
    current = _ok(in_world(owner, "GET", f"/world/versions/{version_id}"), 200)
    admitted = environment(owner)
    instance_id = "environment:existence"
    _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/environment-instances",
            json={
                "base_state_sha256": current["state_sha256"],
                "instance_id": instance_id,
                "admission_id": str(admitted["admission_id"]),
                "render_asset_id": str(admitted["render_asset_id"]),
                "publication_id": None,
                "selection": {"kind": "whole_asset"},
                "source_anchor": {
                    "frame_name": "nyc-grid",
                    "coordinate_scale": 1000,
                    "coordinates": [10, 20, 0],
                },
                "region_id": REGION,
                "transform": _TRANSFORM,
                "origin_role": "fictional",
            },
        ),
        201,
    )
    return {
        "/world/versions/{version_id}": version_id,
        "/world/versions/{version_id}/environment-instances/{instance_id}": instance_id,
    }


def invented_environment_instance() -> str:
    return f"environment:{uuid.uuid4().hex}"


# -- the owner's settings: interaction policy and style -----------------------------------------


def interaction_preview_request(caller, proposal_id: str) -> dict[str, Any]:
    """A request previewing a field-of-view choice under ``proposal_id``, made against the
    caller's own current interaction policy and structural world."""
    base = _ok(
        caller.request("GET", "/world/interactions/current", params={"world_id": WORLD}), 200
    )
    return {
        "params": {"world_id": WORLD},
        "json": {
            "proposal_id": proposal_id,
            "origin": "settings",
            "origin_reference": "existence-panel",
            "base_policy_version_id": (base.get("current") or {}).get("version_id"),
            "base_structure_snapshot_id": base["base_structure_snapshot_id"],
            "base_topology_sha256": base["base_topology_sha256"],
            "capability_patch": {"comfort.field-of-view-degrees": 82},
            "proposal_input": {"control_ids": ["fieldOfView"]},
            "explanation": "Apply the field-of-view choice made in Settings.",
        },
    }


def _interaction_preview(owner) -> dict[str, Any]:
    if "interaction" not in owner.memo:
        world(owner)
        proposal_id = str(uuid.uuid4())
        preview = _ok(
            owner.request(
                "POST",
                "/world/interactions/previews",
                **interaction_preview_request(owner, proposal_id),
            ),
            201,
        )
        owner.memo["interaction"] = {
            "proposal_id": proposal_id,
            "preview_id": preview["preview_id"],
        }
    return owner.memo["interaction"]


def interaction_preview(owner) -> str:
    return _interaction_preview(owner)["preview_id"]


def interaction_proposal(owner) -> str:
    return _interaction_preview(owner)["proposal_id"]


def style_preview_request(caller, proposal_id: str) -> dict[str, Any]:
    """A request previewing a style under ``proposal_id``, made against the caller's own
    current style and topology."""
    current = _ok(caller.request("GET", "/world/styles/current", params={"world_id": WORLD}), 200)
    return {
        "params": {"world_id": WORLD},
        "json": {
            "proposal_id": proposal_id,
            "origin": "settings",
            "origin_reference": "appearance-panel",
            "scope": {"kind": "global"},
            "base_style_version_id": current["current"]["version_id"],
            "base_topology_digest": current["current_topology_digest"],
            "profile": {
                "profile_id": "origin-landscape",
                "profile_version": 1,
                "parameters": {"vitality": 0.25},
            },
        },
    }


def _style_preview(owner) -> dict[str, Any]:
    if "style" not in owner.memo:
        world(owner)
        proposal_id = str(uuid.uuid4())
        preview = _ok(
            owner.request(
                "POST", "/world/styles/previews", **style_preview_request(owner, proposal_id)
            ),
            201,
        )
        owner.memo["style"] = {"proposal_id": proposal_id, "preview_id": preview["preview_id"]}
    return owner.memo["style"]


def style_preview(owner) -> str:
    return _style_preview(owner)["preview_id"]


def style_proposal(owner) -> str:
    return _style_preview(owner)["proposal_id"]


# -- societies ----------------------------------------------------------------------------------


def action_request(owner) -> dict[str, Any]:
    """A user action in a purposeful society, with the version that holds it (API)."""
    made = _version_with_society(owner, PURPOSEFUL, society_input)
    version_id, state = made["version_id"], made["society"]
    targets = owner.society_inputs[version_id]["targets"]
    target = next(row for row in targets if row["affordance"] == "rest")
    action = _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/society/actions",
            json={
                "idempotency_key": str(uuid.uuid4()),
                "base_tick": state["current_tick"],
                "base_state_sha256": state["state_sha256"],
                "subject_id": state["state"]["inhabitants"][0]["id"],
                "intent": {"kind": "go_to", "target_id": target["target_id"]},
            },
        ),
        200,
        201,
    )
    return {
        "/world/versions/{version_id}": version_id,
        "/world/versions/{version_id}/society/actions/{request_id}": action["request"][
            "request_id"
        ],
    }


def living_session(owner) -> dict[str, Any]:
    """A living session of a purposeful society, opened over the API, with its version (API)."""
    made = _version_with_society(owner, PURPOSEFUL, society_input)
    version_id, state = made["version_id"], made["society"]
    session = _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/society/control/sessions",
            json={
                "request_id": str(uuid.uuid4()),
                "base_revision": 0,
                "base_tick": state["current_tick"],
                "base_state_sha256": state["state_sha256"],
                "limits": {
                    "wall_seconds": 60,
                    "minutes": 1,
                    "decisions": 1,
                    "usd": "0.01",
                    "calls": 1,
                },
            },
        ),
        201,
    )
    return {
        "/world/versions/{version_id}": version_id,
        "/world/versions/{version_id}/society/control/sessions/{session_id}": session["session_id"],
    }


def decision_request(owner) -> dict[str, Any]:
    """A stored model decision request in a social society, with its version (domain).

    The social engine and its proposal route are retired, so no request makes either one: the
    society is planted as its creation stored it, and the request as that route recorded one with
    no provider configured, which is how every such request was recorded. A stored one still reads.
    """
    snapshot = world(owner)["snapshot_id"]
    version = _ok(
        in_world(
            owner,
            "POST",
            "/world/versions",
            json={"title": f"existence {SOCIAL}", "source_snapshot_id": snapshot},
        ),
        201,
    )
    version_id = uuid.UUID(version["version_id"])
    document = social_input(version_id)
    owner.society_inputs[version_id] = document
    connection = owner.repository.connection
    society = SocietyRepository(
        connection, owner.workspace_id, world_id=WORLD, input_authorizer=lambda _document: None
    )
    state = plant_retired_society(
        society,
        version_id,
        place_id=_place(owner),
        region_id=REGION,
        seed=SEED,
        actor=owner.actor,
        profile=SOCIAL,
        initial_input=document,
    )
    key = uuid.uuid4()
    with connection.transaction():
        plant_retired_decision(
            SocietyDecisionRepository(society),
            version_id,
            request_id=key,
            subject_id=state["state"]["social"]["cast_ids"][0],
            result={
                "status": "unavailable",
                "reason": "provider_not_configured",
                "proposal": None,
                "provider": None,
            },
        )
    connection.commit()
    return {
        "/world/versions/{version_id}": version_id,
        "/world/versions/{version_id}/society/decisions/{request_id}": str(key),
    }


def _comparison(owner) -> dict[str, Any]:
    """A development comparison over a version's purposeful society (domain: only the local
    command defines one, and runs are reserved by its runner)."""
    if "comparison" not in owner.memo:
        made = _version_with_society(owner, PURPOSEFUL, society_input)
        version_id = made["version_id"]
        comparisons = SocietyComparisonRepository(
            SocietyRepository(
                owner.repository.connection,
                owner.workspace_id,
                world_id=WORLD,
                input_authorizer=lambda _document: None,
            )
        )
        # The district society holds more people than a saved world's, so the test catalogs
        # raise the bound as well as committing the tests' seeds.
        catalogs = comparison_support.seeded_catalogs(population_maximum=512)
        comparison_id = uuid.uuid4()
        comparisons.define(
            version_id,
            comparison_id=comparison_id,
            body=comparison_support.development_body(catalogs),
            created_by=owner.actor,
            role=comparison_support.PEOPLE_ROLE,
            catalogs=catalogs,
        )
        run_id = comparisons.reserve(
            comparison_id, arm="routine", seed=comparison_support.SEEDS[0], created_by=owner.actor
        )
        owner.memo["comparison"] = {
            "/world/versions/{version_id}": version_id,
            "/world/versions/{version_id}/society/comparisons/{comparison_id}": comparison_id,
            "/world/versions/{version_id}/society/comparisons/{comparison_id}/runs/{run_id}": (
                run_id
            ),
        }
    return owner.memo["comparison"]


def comparison(owner) -> dict[str, Any]:
    made = _comparison(owner)
    return {
        address: made[address]
        for address in (
            "/world/versions/{version_id}",
            "/world/versions/{version_id}/society/comparisons/{comparison_id}",
        )
    }


def comparison_run(owner) -> dict[str, Any]:
    return _comparison(owner)


def society_input_seq(owner) -> int:
    """The genesis input of the default version's living society: every society holds input 1."""
    owner.real("/world/versions/{version_id}")
    return 1


def invented_input_seq() -> str:
    """An input sequence no society reaches, inside the bound the route's path accepts."""
    return "2147483000"


def experiment(owner) -> str:
    """A no-op experiment over the default version's living society (API)."""
    version_id = owner.real("/world/versions/{version_id}")
    experiment_id = str(uuid.uuid4())
    _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/society/experiments",
            json={
                "experiment_id": experiment_id,
                "baseline_input_seq": 1,
                "treatment_input_seq": 1,
                "intervention": {"kind": "noop"},
                "population": 3,
                "warmup_ticks": 2,
                "followup_ticks": 3,
            },
        ),
        200,
        201,
    )
    return experiment_id


def experiment_attempt(owner) -> str:
    version_id = owner.real("/world/versions/{version_id}")
    experiment_id = owner.real("/world/versions/{version_id}/society/experiments/{experiment_id}")
    attempt_id = str(uuid.uuid4())
    _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/society/experiments/{experiment_id}/attempts",
            json={"attempt_id": attempt_id, "seed_sha256": DEVELOPMENT_SEEDS[0]},
        ),
        200,
        201,
        202,
    )
    return attempt_id


# -- materials and saved worlds ------------------------------------------------------------------


def material_recipe(owner) -> str:
    """A recipe varied from a published set (API)."""
    made = _ok(owner.request("POST", "/materials/recipes", json={"recipe": _small()}), 201)
    return made["recipe_id"]


def workspace_asset_request() -> dict[str, Any]:
    """The multipart request that admits a one-metre cube as the caller's own work."""
    payload = cube().build()
    return {
        "data": {"declaration": json.dumps(workspace_asset_declaration(payload))},
        "files": {"content": ("object.glb", payload, "model/gltf-binary")},
    }


def workspace_asset(owner) -> str:
    """A person's own admitted asset, not yet prepared (API)."""
    return _ok(owner.request("POST", "/workspace-assets", **workspace_asset_request()), 201)[
        "asset_id"
    ]


def workspace_style_pack_request() -> dict[str, Any]:
    """The multipart request that uploads a creator's own pack: the committed cozy pack, relabelled
    as theirs, with every file it lists as a part named by its path."""
    from style_pack_upload_support import upload

    made = upload()
    return {
        "data": {
            "declaration": made.declaration_bytes().decode(),
            "manifest": made.manifest_bytes.decode(),
        },
        "files": [(path, (path.rsplit("/", 1)[-1], data)) for path, data in made.files.items()],
    }


def _uploaded_style_pack(owner) -> dict[str, Any]:
    """The owner's upload of the creator's pack: 201 the first time, 200 when it is held."""
    response = owner.request("POST", "/workspace-style-packs", **workspace_style_pack_request())
    assert response.status_code in (200, 201), response.text
    return response.json()


def workspace_style_pack(owner) -> str:
    """A creator's own style pack version, admitted and not yet checked (API)."""
    return _uploaded_style_pack(owner)["manifest_sha256"]


def workspace_style_pack_file(owner) -> str:
    """A file the owner's style pack version lists, by its digest (API)."""
    from style_pack_upload_support import upload

    _uploaded_style_pack(owner)
    return upload().manifest["files"][0]["sha256"]


def door_grant(owner) -> str:
    """A grant handing one person of a purposeful society to the sweep's test bridge (API).

    A grant names visitors or things, and visitors arrive only in a version holding a society of
    things, so this grant names one of a society's people in the version that holds them.
    """
    made = _version_with_society(owner, PURPOSEFUL, society_input)
    person = made["society"]["state"]["inhabitants"][0]["id"]
    granted = _ok(
        in_world(
            owner,
            "POST",
            "/door/grants",
            json={
                "idempotency_key": "existence-sweep-grant",
                "bridge": "test-bridge",
                "things": [person],
                "version_id": str(made["version_id"]),
            },
        ),
        200,
        201,
    )
    return granted["grant"]["grant_id"]


def door_arrival(owner) -> str:
    """A visitor's arrival through the sweep's test bridge, by the id the bridge chose for it, into
    a society of things of the owner's world (API): a grant letting one player in, opened with an
    invite the bridge's server redeems (the bridge is listed, so its grants open no other way), the
    bridge's hello with its mapping, and the arrival, whose translation manifest the door keeps."""
    version_id = society_thing(owner)["/world/versions/{version_id}"]
    issued = _ok(
        in_world(
            owner,
            "POST",
            "/door/grants",
            json={
                "idempotency_key": "existence-sweep-visitors",
                "bridge": "test-bridge",
                "visitors_maximum": 1,
                "kinds": ["player"],
                "version_id": str(version_id),
            },
        ),
        201,
    )
    grant_id = issued["grant"]["grant_id"]
    invited = _ok(owner.request("POST", f"/door/grants/{grant_id}/invites"), 201)
    redeemed = _ok(
        owner.request(
            "POST",
            "/door/invites/redeem",
            headers={"Authorization": f"Bearer {door_support.BRIDGE_CREDENTIAL}"},
            json={"code": invited["code"], "requester": "a" * 64},
        ),
        201,
    )
    channel = {"Authorization": f"Bearer {redeemed['credential']}"}
    _ok(
        owner.request(
            "POST",
            "/door/channel/hello",
            headers=channel,
            json={
                "adapter_version": door_support.ADAPTER_VERSION,
                "mapping": door_support.mapping(),
                "reads": door_support.READS,
            },
        ),
        200,
    )
    arrival_id = str(uuid.uuid4())
    _ok(
        owner.request(
            "POST",
            "/door/channel/arrivals",
            headers=channel,
            json={
                "arrival_id": arrival_id,
                "game_type": "player",
                "look_key": "otherwise",
                "carried": [],
            },
        ),
        201,
    )
    return arrival_id


def world_entry(owner) -> str:
    """The workspace's starter world (API)."""
    return _ok(owner.request("POST", "/world-entries/starter", json={"title": "My world"}), 200)[
        "entry_id"
    ]


# -- the recorded library ------------------------------------------------------------------------


def named_place(owner) -> uuid.UUID:
    """The place the photograph's vision pass proposed, named by the owner's actor (domain).

    The actor matters: only the account holder who stated a place's name may allow it to go
    anywhere, so a place named by anybody else could not show the owner's answer on its routes.
    """
    occurrence = owner.repository.connection.execute(
        "select occurrence_id from occurrence where class = 'place' and capture_id = %s limit 1",
        (capture(owner),),
    ).fetchone()
    assert occurrence is not None, "the vision payload proposes a place"
    named = name_occurrence(
        IdentityRepository(owner.repository.connection, owner.workspace_id),
        AssertionWriter(owner.repository.connection, owner.workspace_id),
        occurrence_id=occurrence["occurrence_id"],
        display_name="Gullfoss",
        actor=owner.actor,
    )
    return named.entity_id


def place_bridge(owner) -> str:
    """A confirmed bridge from a canonical place to the owner's named place (API)."""
    made = _ok(
        owner.request(
            "POST",
            "/selection/place-bridges",
            json={
                "canonical_place_id": str(_place(owner)),
                "memory_place_entity_id": str(named_place(owner)),
            },
        ),
        201,
    )
    return made["decision_id"]


def world_read_place(owner) -> uuid.UUID:
    """A place with no anchor, which its owner is told about and a stranger is not (domain)."""
    return _place(owner)


def companion_answer(owner) -> str:
    """A remembered companion answer (API)."""
    made = _ok(
        owner.request(
            "POST",
            "/companion/memory/answers",
            json={
                "question": "When were these photographs taken?",
                "answer_text": "These photographs were taken on 2026-02-01.",
                "prompt_version": "selection-3",
                "latency_ms": 1,
                "composed": "none",
                "used_fallback": False,
                "unanswered_attempts": 0,
                "unanswered_cost_unknown": False,
            },
        ),
        201,
    )
    return made["answer_id"]


def person_subject(owner) -> str:
    """A person subject, the thing consent is recorded for (API)."""
    return _ok(owner.request("POST", "/person-subjects", json={}), 200, 201)["subject_id"]


def model_right(owner) -> uuid.UUID:
    """A hosted vision right over a personal photograph its account holder admitted (domain)."""
    from conftest import photo_bytes
    from test_personal_model_right import HOSTED, admit_personal, grant

    personal = admit_personal(owner.repository, owner.store, photo_bytes(), "personal.jpg")
    return grant(personal, HOSTED.identities[0], HOSTED.destination).right_id


def derivative_job(owner) -> uuid.UUID:
    """A queued derivative job a worker has claimed, which records its first event (domain)."""
    from exulanica.ingest import derivative_queue

    job_id = derivative_queue.enqueue(
        owner.repository.connection,
        owner.workspace_id,
        batch_id=intake_batch(owner),
        capture_ids=[capture(owner)],
    )
    claimed = derivative_queue.claim(
        owner.repository.connection, owner.workspace_id, worker="existence", lease_seconds=60
    )
    assert claimed is not None
    return job_id


def _ended_draft(owner, purpose: str) -> uuid.UUID:
    """A draft of ``purpose`` in the owner's workspace, ended (domain: a draft's job asks a model,
    so the sweep starts one in the application's own drafts whose job ends refused without
    asking)."""
    import threading

    ended = threading.Event()

    def job(draft, drafts) -> None:
        drafts.finish(
            draft,
            state="refused",
            refusal={"code": "kind_not_drafted", "detail": "made by the existence sweep"},
        )
        ended.set()

    made = owner.app.state.services.kind_drafts.start(
        owner.workspace_id, owner.actor, "a small farm", job, purpose=purpose
    )
    assert ended.wait(10), "the sweep's draft never ended"
    return made.draft_id


def kind_draft(owner) -> uuid.UUID:
    """A durable kind draft refused without inference, owned by this requester."""
    from exulanica.world.kind_draft_jobs import KindDraftRepository

    repo = KindDraftRepository(owner.repository.connection, owner.workspace_id)
    ident = repo.submit(
        actor=owner.actor,
        description="a small farm",
        guest=False,
        starts_maximum=100,
        workspace_maximum=1,
        deadline_seconds=600,
        manifest_sha256="a" * 64,
        prompt_version="private-fixture",
    )
    claimed = repo.claim()
    assert claimed is not None
    repo.finish(
        claimed,
        dict(
            state="refused",
            calls=[],
            model_id=None,
            refusal={"code": "kind_not_drafted", "detail": "No kind was drafted."},
        ),
    )
    return ident


def world_draft(owner) -> uuid.UUID:
    """A durable native world draft refused without inference, made through its repository."""
    from exulanica.world.world_draft_jobs import WorldDraftRepository, terms_sha256

    from test_world_draft_jobs_postgres import definition

    repository = WorldDraftRepository(owner.repository.connection, owner.workspace_id)
    words = "a small town"
    made = repository.submit(
        actor=owner.actor,
        request_id=uuid.uuid4(),
        description=words,
        terms_sha256=terms_sha256(words, None, None),
        definition=definition(),
        guest=False,
        starts_maximum=100,
    )
    repository.end_unstarted(owner.actor, made, "world_draft_funding_refused")
    return made


def reference_request(owner) -> uuid.UUID:
    """A queued reference request and its job (domain: the API asks for web notes only where an
    installation configures a source and lists the workspace)."""
    from exulanica.references import store
    from exulanica.references.drafting import reference_prompts

    made, _ = store.create_request(
        owner.repository.connection,
        owner.workspace_id,
        offered_to=(owner.workspace_id,),
        owner_actor_id=owner.actor,
        purpose="kind",
        web=True,
        description="a harbour town with whitewashed houses",
        withheld_words=(),
        prompts_sha256=reference_prompts().sha256,
    )
    return made.reference_id


def web_picture(owner) -> uuid.UUID:
    """A picture the owner kept from a picture search: its inventory and record, as a keep writes
    them (domain: the API keeps one only from a search's held pictures, which no sweep runs)."""
    connection = owner.repository.connection
    digest = "ab" * 32
    connection.execute(
        "insert into web_picture_object (workspace_id, content_sha256, byte_size) "
        "values (%s, %s, 1) on conflict (workspace_id, content_sha256) "
        "where purged_at is null do nothing",
        (owner.workspace_id, digest),
    )
    row = connection.execute(
        "insert into web_picture (workspace_id, content_sha256, fetched_sha256, media_type, "
        "byte_size, width, height, address, website, answer, answered_by) "
        "values (%s, %s, %s, 'image/png', 1, 1, 1, 'https://pictures.example/a.png', "
        "'pictures.example', 'private_world_only', %s) returning picture_id",
        (owner.workspace_id, digest, "cd" * 32, owner.actor),
    ).fetchone()
    return row["picture_id"]


def piece_request(owner) -> uuid.UUID:
    """A requested piece of the owner's world's look, a well in the default pack (domain: the
    API asks only within the workspace's GPU allowance)."""
    from exulanica.generation import store
    from exulanica.generation.requests import (
        GPU_PROVIDER,
        LookReference,
        generation_catalogs,
        plan_requests,
    )
    from exulanica.world.style_pack_library import style_pack_library

    world(owner)
    library = style_pack_library()
    pack = library.default_pack
    look = LookReference(pack.pack_id, pack.version, pack.manifest_sha256)
    planned = plan_requests([("well", 1)], look, library=library)
    compute = generation_catalogs().compute.for_provider(GPU_PROVIDER)
    made, _ = store.create_piece_requests(
        owner.repository.connection,
        owner.workspace_id,
        requested_by=owner.actor,
        world_id=WORLD,
        look=look,
        planned=planned,
        worst_cases=[compute.worst_case_usd(plan.variants) for plan in planned],
    )
    return made[0].piece_request_id


def reconstruction_job(owner) -> uuid.UUID:
    """A queued scene reconstruction over three admitted captures (domain)."""
    from test_reconstruction_scene_jobs import _captures, _enqueue

    job_id, _ = _enqueue(owner.repository, _captures(owner.repository))
    return job_id


def reconstruction_scene(owner) -> uuid.UUID:
    """A published scene every scene route can read for its owner (domain: the scene worker)."""
    from test_world_read_route import _scene_in

    return _scene_in(owner, owner.repository, owner.tmp_path)


def trained_scene(owner) -> str:
    """A trained Gaussian scene, its blobs copied into the application's store (domain)."""
    from exulanica.store.local import LocalContentAddressedStore

    from test_training_inputs import scene_sample

    root = owner.tmp_path / "trained"
    root.mkdir()
    _, materials = scene_sample(owner.repository, root)
    trained_store = LocalContentAddressedStore(root / "store")
    for blob in trained_store.iter_blob_ids():
        owner.store.put_bytes(trained_store.get(blob))
    return next(
        asset["artifact_id"]
        for material in materials
        for asset in material["assets"]
        if asset["role"] == "trained_geometry"
    )


def baked_tile(owner) -> str:
    """A tile an offline bake recorded, in the application's tile store (domain: the bake)."""
    from exulanica.world.baked_tiles import BakedTileRepository

    from test_corridor_tile_route import _record

    key = uuid.uuid4()
    _record(
        BakedTileRepository(connection=owner.repository.connection, store=owner.tiles),
        key,
        2,
        b"an existence sweep tile",
    )
    return str(key)


def reviewed_asset(owner) -> str:
    """The reviewed cube, which migration 0042 registers for every workspace."""
    return CUBE.asset_key


def character_catalog(owner) -> str:
    """A character catalog the host published (domain: host administration, owner connection).

    Written as the publication row alone: the read serves the document, and the containers a
    catalog names are the reviewed registry's concern, which this sweep leaves alone.
    """
    from exulanica.world.character_catalogs import layered_bundle, read_publication_document
    from psycopg.types.json import Jsonb

    characters = ROOT / "assets/characters"
    publication = read_publication_document(
        layered_bundle(
            json.loads((characters / "catalog.json").read_text()),
            json.loads((characters / "looks.json").read_text()),
        )
    )
    connection = owner.repository.connection
    connection.execute(
        "insert into character_catalog_publication"
        "(catalog_sha256,catalog_id,profile,kind,revision,document,producer) "
        "values(%s,%s,%s,%s,%s,%s,'existence sweep')",
        (
            publication.catalog_sha256,
            publication.catalog_id,
            publication.profile,
            publication.kind,
            publication.revision,
            Jsonb(publication.document),
        ),
    )
    connection.commit()
    return publication.catalog_sha256


def style_pack_content(owner) -> str:
    """A committed style pack's manifest, which the host serves every workspace by its digest."""
    from exulanica.world.style_pack_library import style_pack_library

    return style_pack_library().packs[0].manifest_sha256


def thing_library_content(owner) -> str:
    """A shipped thing kind, which the host serves every workspace by its digest."""
    from exulanica.world.thing_library import thing_library

    return thing_library().listing()["kinds"][0]["sha256"]


def invented_digest() -> str:
    return uuid.uuid4().hex * 2


def _held_creature(owner):
    """A creature drafted in the test fixtures and kept in the owner's own thing store, its sketch's
    container in the application's looks namespace (domain: the creature route comes later)."""
    if "held_creature" not in owner.memo:
        from exulanica.things.creatures import assemble_creature
        from exulanica.world.thing_store import ThingStore

        from test_creature_bodies import BY, _form, _recipe

        creature = assemble_creature(_form(_recipe("ten_legs"), label="swept ten legs"), by=BY)
        looks = owner.app.state.services.content_stores.looks.for_workspace(owner.workspace_id)
        ThingStore(owner.repository.connection, owner.workspace_id, looks).keep_creature(
            creature, created_by=owner.actor
        )
        owner.memo["held_creature"] = creature
    return owner.memo["held_creature"]


def held_look(owner) -> str:
    """The sketch look of a creature the owner's workspace holds, by its document's digest."""
    return _held_creature(owner).sketch.sha256


def held_kind(owner) -> str:
    """The kind of a creature the owner's workspace holds, by its document's digest."""
    return _held_creature(owner).kind.sha256


def held_world_kind(owner) -> str:
    """A checked library world-kind version (domain, without enabling model drafting)."""
    from exulanica.world.kinds.document import read_kind
    from exulanica.world.kinds.repository import WorkspaceKinds
    from exulanica.world.kinds.samples import check_samples

    from test_world_kinds_postgres import _uploaded

    kind = read_kind(_uploaded("farm"))
    WorkspaceKinds(owner.repository.connection, owner.workspace_id).append(
        kind, check_samples(kind), created_by=owner.actor
    )
    return kind.sha256


def creature_draft(owner) -> str:
    """A creature draft the owner asked for, queued and not yet played (domain: no worker runs in
    the sweep's application)."""
    from exulanica.selection.creature_drafts import create_draft

    made = create_draft(
        owner.repository.connection,
        owner.workspace_id,
        offered_to={owner.workspace_id},
        owner_actor_id=owner.actor,
        words="a creature asked for by the sweep",
        sent="a creature asked for by the sweep",
        placeholders={},
    )
    return str(made.draft_id)


def creature_look(owner) -> str:
    """A look job the owner asked for a creature their workspace holds, queued (domain: no
    operator's run takes it in the sweep's application)."""
    from exulanica.world.creature_look_jobs import ask_look

    made = ask_look(
        owner.repository.connection,
        owner.workspace_id,
        kind_sha256=held_kind(owner),
        requested_by=owner.actor,
    )
    return str(made.look_id)


def held_plan(owner) -> str:
    """The drafted body plan of a creature the owner's workspace holds, by its document's digest."""
    return _held_creature(owner).plan.sha256


def district_version(owner) -> uuid.UUID:
    """A version whose district the host registered over two admitted city sources (domain).

    A district is host configuration: an operator admits the committed Flatiron sources and
    registers the binding, which no request can do, so the society runtime is rebuilt with it.
    """
    from exulanica.api.society_runtime import SocietyRuntime, SocietyRuntimeBinding

    base = ROOT / "assets/owned-world/flatiron/flatiron-owned-district.json"
    reading = ROOT / "assets/owned-world/flatiron-interpretation-v1/district-interpretation.json"
    version_id = _plain_version(owner)
    version = _ok(in_world(owner, "GET", f"/world/versions/{version_id}"), 200)
    place = _place(owner)
    admissions = EnvironmentRepository(owner.repository.connection, owner.workspace_id, owner.store)
    sources = []
    for declaration in json.loads((base.parent / "admission-plan.json").read_bytes())["sources"]:
        source = SourceAdmission.model_validate(
            {
                **declaration,
                "admission_id": uuid.uuid4(),
                "place_id": place,
                "local_path": base.parent / declaration["local_path"],
            }
        )
        saved = admissions.admit_source(source, actor=owner.actor)
        sources.append(
            {
                "dataset_id": source.provider_original_id,
                "admission_id": source.admission_id,
                "source_sha256": source.expected_sha256,
                "receipt_sha256": saved.receipt_sha256,
            }
        )
    interpreted = json.loads(reading.read_bytes())
    binding = SocietyRuntimeBinding(
        binding_id="existence-district",
        workspace_id=owner.workspace_id,
        world_id=version["world_id"],
        version_id=version_id,
        source_snapshot_id=world(owner)["snapshot_id"],
        place_id=place,
        region_id=REGION,
        district_id=interpreted["district_id"],
        frame=interpreted["frame"],
        translation_mm=(0, 0, 0),
        yaw_microradians=0,
        scale_milli=1000,
        base_artifact_sha256=owner.store.put_file(base).blob_id.hex,
        interpretation_artifact_sha256=owner.store.put_file(reading).blob_id.hex,
        interpretation_document_sha256=interpreted["document_sha256"],
        sources=sources,
    )
    plate = next(asset for asset in reviewed_assets() if asset.asset_key == "cc0.marker-plate")
    registry = {
        plate.content_sha256: {
            "asset_key": plate.asset_key,
            "affordance": "rest",
            "duration_ticks": 3,
            "footprint_half_extents_mm": [500, 500],
            "blocks_navigation": False,
            "reach_mm": 1500,
        }
    }
    runtime = SocietyRuntime(store=owner.store, bindings=[binding], reviewed_affordances=registry)
    owner.app.state.services = dataclasses.replace(
        owner.app.state.services, society_runtime=runtime
    )
    return version_id


# -- world projects -------------------------------------------------------------------------------


def _world_project(owner) -> dict[str, Any]:
    """A project in the owner's world with one goal, the goal shared (API)."""
    if "world_project" not in owner.memo:
        version_id = _plain_version(owner)
        project = _ok(
            in_world(
                owner,
                "POST",
                "/world/projects",
                json={"title": "existence", "version_id": str(version_id)},
            ),
            201,
        )
        route = f"/world/projects/{project['project_id']}"
        item = _ok(
            in_world(
                owner,
                "POST",
                f"{route}/items",
                json={
                    "base_revision": project["revision"],
                    "kind": "goal",
                    "basis": "user_statement",
                    "text": "a quiet square",
                },
            ),
            201,
        )
        shared = _ok(
            in_world(
                owner,
                "POST",
                f"{route}/shares",
                json={"base_revision": item["project_revision"], "item_ids": [item["item_id"]]},
            ),
            200,
        )
        owner.memo["world_project"] = {
            "/world/projects/{project_id}": project["project_id"],
            "/world/projects/{project_id}/items/{item_id}": item["item_id"],
            "/world/projects/{project_id}/shares/{share_id}": shared["shares"][0]["share_id"],
        }
    return owner.memo["world_project"]


def world_project(owner) -> str:
    return _world_project(owner)["/world/projects/{project_id}"]


def world_project_item(owner) -> dict[str, Any]:
    made = _world_project(owner)
    return {
        "/world/projects/{project_id}": made["/world/projects/{project_id}"],
        "/world/projects/{project_id}/items/{item_id}": made[
            "/world/projects/{project_id}/items/{item_id}"
        ],
    }


def world_project_share(owner) -> dict[str, Any]:
    made = _world_project(owner)
    return {
        "/world/projects/{project_id}": made["/world/projects/{project_id}"],
        "/world/projects/{project_id}/shares/{share_id}": made[
            "/world/projects/{project_id}/shares/{share_id}"
        ],
    }


# -- requests made from the owner's own objects ----------------------------------------------------


def feature_index_request(owner) -> dict[str, Any]:
    """A publication naming the owner's own render, so the owner's answer turns on the source."""
    return {
        "json": {
            "render_asset_id": str(environment(owner)["render_asset_id"]),
            "features": [
                {"provider_feature_id": "feature", "kind": "terrain", "bbox": [0, 0, 10, 10]}
            ],
        }
    }


def _generated(owner) -> dict[str, Any]:
    """A world generated from the small-town recipe, made once per test (API)."""
    if "generated" not in owner.memo:
        owner.memo["generated"] = _ok(
            owner.request(
                "POST", "/worlds/generated", json={"recipe": "small_town", "title": "A town"}
            ),
            201,
        )
    return owner.memo["generated"]


def support_placement_probe() -> dict[str, Any]:
    """A complete rigid placement request, before its saved source and state are resolved."""
    from exulanica.things.kinds import shipped_thing_kinds

    return {
        "params": {"world_id": WORLD},
        "json": {
            "base_state_sha256": "0" * 64,
            "thing_id": "thing:support-probe",
            "kind": shipped_thing_kinds()[("lantern", 1)].reference(),
            "region_id": "region:generated",
            "position_mm": [50400, -5340],
            "yaw_microradians": 0,
            "origin_role": "fictional",
            "support": {
                "profile": "exulanica.support-reference/v1",
                "world_id": WORLD,
                "source_snapshot_id": "00000000-0000-0000-0000-000000000001",
                "receipt_sha256": "0" * 64,
                "network_sha256": "0" * 64,
                "region_id": "region:generated",
                "surface_id": "deck",
            },
        },
    }


def supported_version(owner) -> uuid.UUID:
    """A native farm and the retained 150 mm deck fixture (domain worker, saved authority).

    Its world id also exists in the stranger's workspace, so the requests reach the version
    lookup. Placement and preview use the ordinary API under the provisioned runtime role.
    """
    from exulanica.world.generated_worlds import create_kind_world_authorities
    from exulanica.world.kinds.document import read_kind
    from exulanica.world.kinds.worker import WorkerComposer

    from kind_briefs import fixture_kind
    from test_support_site import authoring, context

    if "supported_version" not in owner.memo:
        kind = read_kind(fixture_kind("farm"))
        composer = WorkerComposer(owner.workspace_id, support=authoring(context()["base_place"]))
        composed = composer(kind, kind.values(kind.presets[0][0]), WORLD)
        snapshot, _, version = create_kind_world_authorities(
            owner.repository.connection,
            workspace_id=owner.workspace_id,
            actor=owner.actor,
            title="Existence support fixture",
            kind=kind.kind,
            version=kind.version,
            composed=composed,
        )
        composer.keep()
        prefix = f"/world/versions/{version}"
        drawing = _ok(in_world(owner, "GET", prefix + "/site"), 200)
        held = _ok(in_world(owner, "GET", prefix), 200)
        request = support_placement_probe()
        request["json"]["base_state_sha256"] = held["state_sha256"]
        request["json"]["support"].update(
            source_snapshot_id=str(snapshot),
            receipt_sha256=drawing["receipt_sha256"],
            network_sha256=drawing["support"]["network"]["document_sha256"],
        )
        owner.memo["supported_version"] = version
        owner.memo["support_placement_request"] = request
    return owner.memo["supported_version"]


def support_placement_request(owner) -> dict[str, Any]:
    """Placement on the owner's exact saved deck, away from its actor corridor."""
    supported_version(owner)
    return copy.deepcopy(owner.memo["support_placement_request"])


def generated_tile(owner) -> dict[str, Any]:
    """A world generated from the small-town recipe (API), and the key its first tile's bake is
    stored under. No test bakes it, so the owner is answered that the world names no such baked
    tile, where a stranger is answered that the world does not exist."""
    from exulanica.grammar.grammars.city.catalogs import load_city_catalogs
    from exulanica.grammar.grammars.city.generation.tiles import tile_record
    from exulanica.grammar.grammars.specified import GENERATED_LOD
    from exulanica.ingest.stages import STAGES, baked_tile_id
    from exulanica.world.generated_worlds import generation_receipt

    entry = _generated(owner)
    _, receipt = generation_receipt(
        owner.repository.connection,
        owner.workspace_id,
        entry["world_id"],
        uuid.UUID(entry["source_snapshot_id"]),
    )
    tile_x, tile_y = receipt["tiles"][0]
    record = tile_record(
        seed=receipt["seed"],
        catalogs=load_city_catalogs(),
        tile_x=tile_x,
        tile_y=tile_y,
        lod=GENERATED_LOD,
    )
    return {
        "/world/versions/{version_id}": entry["authored_version_id"],
        "/world/versions/{version_id}/tiles/{baked_tile_id}": baked_tile_id(
            STAGES["baked_tile"], record
        ),
    }


def _made_farm(owner) -> dict[str, Any]:
    """A farm made from the fixture kind on level ground, in a world of its own (domain), and the
    barn it was made with, read through the parts route (API)."""
    from exulanica.world.generated_worlds import create_kind_world_authorities
    from exulanica.world.kinds.document import read_kind
    from exulanica.world.kinds.worker import WorkerComposer
    from exulanica.world.worlds import GENERATED, new_world_id

    from kind_briefs import fixture_kind

    if "made_farm" not in owner.memo:
        kind = read_kind(fixture_kind("farm"))
        world_id = new_world_id(GENERATED)
        composer = WorkerComposer(owner.workspace_id)
        composed = composer(kind, kind.values(kind.presets[0][0]), world_id)
        _, _, version = create_kind_world_authorities(
            owner.repository.connection,
            workspace_id=owner.workspace_id,
            actor=owner.actor,
            title="Existence parts fixture",
            kind=kind.kind,
            version=kind.version,
            composed=composed,
        )
        composer.keep()
        parts = _ok(
            owner.request("GET", f"/world/versions/{version}/parts", params={"world_id": world_id}),
            200,
        )
        barn = next(part for part in parts["parts"] if part["part_key"] == "barn")
        owner.memo["made_farm"] = {"world_id": world_id, "version_id": version, "barn": barn}
    return owner.memo["made_farm"]


def made_part(owner) -> dict[str, Any]:
    """A part a farm was made with (the barn), in that farm's version. Its world is the owner's
    alone, so every request about it names that world (:func:`made_part_request`)."""
    farm = _made_farm(owner)
    return {
        "/world/versions/{version_id}": farm["version_id"],
        "/world/versions/{version_id}/parts/{part_id}": farm["barn"]["part_id"],
    }


def made_part_request(owner) -> dict[str, Any]:
    """A removal (or its preview) in the farm's world against a base nobody holds: the owner is
    answered past the part's lookup, and nothing is changed."""
    return {
        "params": {"world_id": _made_farm(owner)["world_id"]},
        "json": {"base_state_sha256": "0" * 64},
    }


def made_part_storeys_request(owner) -> dict[str, Any]:
    """The barn standing the storeys it was made with (or its preview), as
    :func:`made_part_request`."""
    request = made_part_request(owner)
    request["json"]["storeys"] = _made_farm(owner)["barn"]["storeys"]
    return request


def made_part_move_request(owner) -> dict[str, Any]:
    """A move (or its preview) of the barn to where it stands, as :func:`made_part_request`."""
    farm = _made_farm(owner)
    east, north = farm["barn"]["centre_mm"]
    request = made_part_request(owner)
    request["json"]["pose"] = {"x_mm": east, "y_mm": 0, "z_mm": -north, "yaw_microradians": 0}
    return request


def generated_tile_request(owner) -> dict[str, Any]:
    """A request in the generated world the tile belongs to."""
    generated_tile(owner)
    return {"params": {"world_id": owner.memo["generated"]["world_id"]}}


#: The signal a fixture comparison's group names. No read of a comparison or its runs compiles the
#: roads, so the town need not be one whose roads the traffic drives.
_FIXTURE_SIGNAL: Final = {"signal_id": "fixture-signal", "junction_id": "fixture-junction"}


def _signal_comparison(owner) -> dict[str, Any]:
    """A development signal comparison over the generated town's roads, assembled as the runner
    assembles one over a fixture signal, with its fixed-timing run reserved (domain)."""
    from exulanica.api.signal_comparison_runner import SignalComparisonRunner
    from exulanica.api.society_comparison_runner import ComparisonArm
    from exulanica.models.manifest import load_manifest
    from exulanica.world.decision_roles import decision_roles
    from exulanica.world.signal_comparison_repository import SignalComparisonRepository

    if "signal_comparison" not in owner.memo:
        entry = _generated(owner)
        version_id = uuid.UUID(entry["authored_version_id"])
        repository = SignalComparisonRepository(
            owner.repository.connection, owner.workspace_id, entry["world_id"]
        )
        runner = SignalComparisonRunner(
            database=None,
            client=None,
            policy_for=lambda _workspace: None,
            manifest=load_manifest(),
            manifest_sha256="a" * 64,
            workspace_id=owner.workspace_id,
            world_id=entry["world_id"],
            actor=owner.actor,
        )
        model = load_manifest().offered_models(decision_roles().deciding_for("signal").chosen)[0]
        seed = runner.catalogs.development_seeds()[0]
        body = runner.body(
            [ComparisonArm(model.provider, model.model_id)], [seed], control=False, group=None
        )
        comparison_id = uuid.uuid4()
        repository.define(
            comparison_id,
            runner.definition(
                version_id, repository.roads(version_id), [_FIXTURE_SIGNAL], body=body
            ),
            created_by=owner.actor,
        )
        run_id = repository.reserve(comparison_id, arm="fixed", seed=seed, created_by=owner.actor)
        owner.repository.connection.commit()
        owner.memo["signal_comparison"] = {
            "/world/versions/{version_id}": str(version_id),
            "/world/versions/{version_id}/traffic/comparisons/{comparison_id}": comparison_id,
            "/world/versions/{version_id}/traffic/comparisons/{comparison_id}/runs/{run_id}": (
                run_id
            ),
        }
    return owner.memo["signal_comparison"]


def signal_comparison(owner) -> dict[str, Any]:
    made = _signal_comparison(owner)
    return {
        address: made[address]
        for address in (
            "/world/versions/{version_id}",
            "/world/versions/{version_id}/traffic/comparisons/{comparison_id}",
        )
    }


def signal_comparison_run(owner) -> dict[str, Any]:
    return _signal_comparison(owner)


def signal_comparison_request(owner) -> dict[str, Any]:
    """A request in the generated world the signal comparison belongs to."""
    _signal_comparison(owner)
    return {"params": {"world_id": owner.memo["generated"]["world_id"]}}


def entry_update_request(owner) -> dict[str, Any]:
    """The owner's saved world, saved again at the cursor it was read at."""
    entry_id = owner.real("/world-entries/{entry_id}")
    entry = _ok(owner.request("GET", f"/world-entries/{entry_id}"), 200)
    return {
        "json": {
            "base_revision": entry["revision"],
            "authored_version_id": entry["authored_version_id"],
            "expected_authored_state_sha256": entry["current_authored_state_sha256"],
            "expected_authored_edit_seq": entry["current_authored_edit_seq"],
            "style_version_id": entry["style_version_id"],
        }
    }


def style_apply_request(owner) -> dict[str, Any]:
    """The owner's style preview applied over the style and topology it was made against."""
    style_preview(owner)
    current = _ok(in_world(owner, "GET", "/world/styles/current"), 200)
    return {
        "params": {"world_id": WORLD},
        "json": {
            "base_style_version_id": current["current"]["version_id"],
            "base_topology_digest": current["current_topology_digest"],
        },
    }


def character_preparation(owner) -> uuid.UUID:
    """A body the owner asked to prepare, still waiting for a preparer (domain: the queue).

    Requested as the character routes request one, and left requested: the sweep asks who may
    read and cancel a preparation, not what a preparer makes of it.
    """
    from exulanica.store.namespaces import LocalWorkspaceStores
    from exulanica.world.character_parametric import PREPARER_ID, PREPARER_VERSION
    from exulanica.world.workspace_preparations import WorkspacePreparationRepository

    queue = WorkspacePreparationRepository(
        owner.repository.connection,
        owner.workspace_id,
        owner.actor,
        stores=LocalWorkspaceStores(owner.tmp_path / "workspace-assets"),
    )
    zero = "0" * 64
    record = queue.request(
        input_kind="character_recipe",
        preparer_id=PREPARER_ID,
        preparer_version=PREPARER_VERSION,
        parameters={
            "family_id": "makehuman-parametric/v1",
            "family_sha256": zero,
            "values": {},
            "seed": 0,
        },
        inputs={"catalog_sha256": zero, "family": {}, "identity_sha256": zero},
    )
    return record.preparation_id


# -- model evidence and browser participation --------------------------------------------------


def _model_probe(owner):
    """Prepare a real probe through the API, using the suite's scripted provider transport."""
    if "model_probe" not in owner.memo:
        from decimal import Decimal

        from spending_support import spending_client
        from test_model_probes_postgres import ProbeTransport, _candidate

        bench = owner.fixture("bench")
        spending = bench.durable()
        transport = ProbeTransport()
        client = spending_client(spending, transport)
        owner.app.state.services = dataclasses.replace(
            owner.app.state.services,
            model_client=client,
            spending=spending,
            runs_model_probe_worker=True,
            model_probe_workspaces=(owner.workspace_id,),
            admits_workspace_models=True,
        )
        spec = _candidate()
        body = {
            "provider": spec.provider,
            "model_id": spec.model_id,
            "request_id": str(uuid.uuid4()),
        }
        _ok(owner.request("POST", "/models", json=body), 200)
        found = _ok(owner.request("POST", "/models/probes/prepare", json=body), 200)
        ceiling = Decimal(found["definition"]["operation_estimate"]["ceiling_usd"])
        authority = bench.issue(ceiling=ceiling * 2)
        bench.grant(authority, owner.workspace_id, ceiling=ceiling)
        owner.memo["model_probe"] = found
    return owner.memo["model_probe"]


def model_probe(owner) -> str:
    return _model_probe(owner)["probe_id"]


def model_probe_start_request(owner) -> dict[str, Any]:
    found = _model_probe(owner)
    return {
        "json": {
            "request_id": str(uuid.uuid4()),
            "definition_sha256": found["definition"]["document_sha256"],
            "ceiling_usd": found["definition"]["operation_estimate"]["ceiling_usd"],
        }
    }


def model_binding(owner) -> str:
    """Execute only scripted replies, then retain the normal proven execution snapshot."""
    from exulanica.world.model_probe_worker import ModelProbeWorker

    from spending_support import WorkspacePolicy

    found = _model_probe(owner)
    _ok(
        owner.request(
            "POST", f"/models/probes/{found['probe_id']}/start", **model_probe_start_request(owner)
        ),
        202,
    )
    services = owner.app.state.services
    worker = ModelProbeWorker(
        services.database,
        client=services.model_client,
        spending=services.spending,
        policy_for=WorkspacePolicy,
        workspaces=lambda: (owner.workspace_id,),
    )
    assert worker.turn(owner.workspace_id)
    source = services.workspace_execution_source(
        owner.workspace_id,
        found["definition"]["engine"],
        frozenset({found["definition"]["model_id"]}),
    )
    assert source is not None
    return source[2]


def removable_world(owner) -> str:
    return _generated(owner)["world_id"]


def _invited_world(owner):
    """A generated world, a kept creature and a real society, read by a bound browser."""
    if "invited_world" not in owner.memo:
        from datetime import UTC, datetime, timedelta

        from exulanica.api.participation import ParticipationRuntime
        from exulanica.api.society_making import SocietyHooks
        from exulanica.api.society_runtime import SocietyRuntime
        from exulanica.participation.contracts import notice_reference
        from exulanica.world.society_composition import reviewed_affordance_registry

        runtime = SocietyRuntime(
            store=owner.store,
            authored_bindings=[],
            reviewed_affordances=reviewed_affordance_registry(),
        )
        state = owner.app.state
        # Participation retains its own configured services and hooks. Other builders keep
        # the fixture adapter registered for their versions after this scoped construction.
        with pytest.MonkeyPatch.context() as configured:
            configured.setattr(
                state,
                "services",
                dataclasses.replace(
                    state.services, societies_of_things=True, society_runtime=runtime
                ),
            )
            configured.setattr(state, "society_initial_input", runtime.initial_input)
            configured.setattr(state, "society_input_authorizer", runtime.authorize)
            configured.setattr(state, "society_authored_edit", runtime.authored_edit, raising=False)
            entry = _generated(owner)
            version = entry["authored_version_id"]
            root = f"/world/versions/{version}"
            params = {"world_id": entry["world_id"]}
            base = _ok(owner.request("GET", root, params=params), 200)["state_sha256"]
            east, height, south = entry["generated_ground"]["arrival_mm"]
            kind = held_kind(owner)
            _ok(
                owner.request(
                    "POST",
                    root + "/things",
                    params=params,
                    json={
                        "base_state_sha256": base,
                        "thing_id": "existence-creature",
                        "kind": {"source": "workspace", "sha256": kind},
                        "region_id": "region:generated",
                        "pose": {
                            "x_mm": east,
                            "y_mm": height,
                            "z_mm": south,
                            "yaw_microradians": 0,
                        },
                        "origin_role": "fictional",
                    },
                ),
                201,
            )
            _ok(
                owner.request(
                    "POST",
                    root + "/society",
                    params=params,
                    json={"region_id": "region:generated", "profile": THINGS},
                ),
                200,
                201,
            )
            participation = ParticipationRuntime(state.services, SocietyHooks.of_app(owner.app))
            participation.verify()
            state.participation = participation
            invitation = _ok(
                owner.request(
                    "POST",
                    "/world/invitations",
                    params=params,
                    json={
                        "idempotency_key": str(uuid.uuid4()),
                        "version_id": version,
                        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                        "world_words": "A town to observe",
                    },
                ),
                200,
            )
            _ok(
                owner.request(
                    "POST",
                    "/participation/redeem",
                    json={
                        "invitation": invitation["invitation"],
                        "notice_sha256": notice_reference()["sha256"],
                    },
                ),
                200,
            )
            owner.memo["invited_world"] = {"entry": entry, "invitation": invitation}
    return owner.memo["invited_world"]


def invitation(owner) -> str:
    return _invited_world(owner)["invitation"]["grant_id"]


def participation_file(owner) -> dict[str, str]:
    grant = invitation(owner)
    body = _ok(owner.request("GET", f"/participation/{grant}/world"), 200)
    assert body["files"]
    return {
        "/participation/{grant_id}": grant,
        "/participation/{grant_id}/world/files/{sha256}": body["files"][0]["sha256"],
    }


def participation_tile(owner) -> dict[str, str]:
    from types import SimpleNamespace

    from test_generated_worlds import _baker

    grant = invitation(owner)
    api = SimpleNamespace(repository=owner.repository, database=owner.app.state.services.database)
    outcomes = _baker(api, owner.tiles, owner.tmp_path, owner.fixture("monkeypatch")).drain(
        [owner.workspace_id]
    )
    assert outcomes and all(outcome.status == "baked" for outcome in outcomes)
    body = _ok(owner.request("GET", f"/participation/{grant}/world"), 200)
    return {
        "/participation/{grant_id}": grant,
        "/participation/{grant_id}/world/tiles/{baked_tile_id}": body["tiles"][0]["baked_tile_id"],
    }
