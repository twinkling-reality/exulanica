"""Composition preview and apply against PostgreSQL and a real content-addressed store.

Everything a verdict depends on is created here as rows and bytes and then changed underneath the
request, so each assertion is about what the server read rather than about what a body claimed.
The environment cases use the synthetic admission fixture from
``test_world_environment_composition_postgres``: invented bytes under a fixture provider key, not
an admitted real place.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.routes.world import _object_problem
from exulanica.api.services import Services
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.environment import DerivedEnvironmentAsset, FeatureIndexPublication
from exulanica.evidence.blob import BlobId
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import (
    CompositionBlocked,
    CompositionPlacement,
    CompositionRequest,
    EnvironmentAdmissionSource,
    EnvironmentSelection,
    ObjectOrigin,
    ReviewedAssetSource,
    SourceAnchor,
    SourceAttachmentSource,
    Transform,
    UnavailableAsset,
    WorldObjectRepository,
    WorldStructureRepository,
    apply_composition,
    preview_composition,
    seed_reviewed_assets,
)
from exulanica.world.errors import InvalidObjectState
from exulanica.world.objects import AuthoredObject
from exulanica.world.society import UnavailableSocietyInput
from fastapi.testclient import TestClient

from test_saved_world_entries_api import (
    _appearance_preview,
    _attachment_body,
    _create_starter,
    _reviewed_source,
)
from test_society_runtime import create as create_society
from test_society_runtime import runtime_world as imported_runtime_world  # noqa: F401
from test_world_environment_composition_postgres import _bounds, _frame, _rights
from test_world_environment_composition_postgres import composed as imported_composed  # noqa: F401
from test_world_objects_api import CUBE, PARAMETERS, STRANGER_TOKEN, transform
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401
from test_world_objects_postgres import another_connection
from tests_support_api import EVERY_PERMISSION, scratch_database
from world_structure_fixtures import structural_candidate

pytestmark = pytest.mark.postgres

MOTION = {"behaviour_key": "motion.bounded-path", "behaviour_version": 1, "parameters": PARAMETERS}


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


@pytest.fixture(name="composed")
def _composed_alias(request):
    return request.getfixturevalue("imported_composed")


@pytest.fixture(name="runtime_world")
def _runtime_world_alias(request):
    return request.getfixturevalue("imported_runtime_world")


def placement(subject_id="object:lantern", region_id="region-a", **extra):
    return {
        "subject_id": subject_id,
        "region_id": region_id,
        "transform": transform(),
        "origin_role": "fictional",
        **extra,
    }


def reviewed(version, *, asset_key="cc0.marker-cube", place=None, base=None, **extra):
    return {
        "base_state_sha256": base or version["state_sha256"],
        "source": {"kind": "reviewed_asset", "asset_key": asset_key},
        "placement": placement() if place is None else place,
        **extra,
    }


def world_query(world_id):
    return "" if world_id is None else f"?world_id={world_id}"


def preview(api, version_id, body, world_id=None):
    return api.post(
        f"/world/versions/{version_id}/compositions/preview{world_query(world_id)}", body
    )


def apply(api, version_id, body, world_id=None):
    return api.post(f"/world/versions/{version_id}/compositions/apply{world_query(world_id)}", body)


def read(api, version_id, world_id=None):
    response = api.get(f"/world/versions/{version_id}{world_query(world_id)}")
    assert response.status_code == 200, response.text
    return response.json()


def after_document(repository, edit_id):
    return repository.connection.execute(
        "select after_document from world_alternate_version_edit "
        "where workspace_id=%s and edit_id=%s",
        (repository.workspace_id, uuid.UUID(edit_id)),
    ).fetchone()["after_document"]


def remove_blob(store: LocalContentAddressedStore, digest: str) -> None:
    (store.root / store.key_for(BlobId.from_hex(digest))).unlink()


def assert_refused(response, reason):
    assert response.status_code == 409, response.text
    assert response.json() == {"code": "composition_blocked", "detail": reason}


# -- reviewed asset: ready, apply, reopen, undo ------------------------------------------------


def test_a_ready_preview_names_stored_state_and_apply_stores_exactly_that_change(
    objects_api, repository
):
    version = objects_api.add(objects_api.version(), object_id="object:other").json()
    before = read(objects_api, version["version_id"])

    ready = preview(
        objects_api, version["version_id"], reviewed(before, place=placement(behaviour=MOTION))
    )
    assert ready.status_code == 200, ready.text
    verdict = ready.json()
    assert verdict["availability"] == "ready"
    assert verdict["blocked_reason"] is None
    assert verdict["source"] == {
        "kind": "reviewed_asset",
        "asset_key": "cc0.marker-cube",
        "content_sha256": CUBE,
        "bytes": "available",
    }
    assert verdict["version"] == {
        "authored_version_id": before["version_id"],
        "world_id": before["world_id"],
        "state_sha256": before["state_sha256"],
        "edit_seq": before["edit_seq"],
        "source_snapshot_id": before["source_snapshot_id"],
        "style_version_id": before["style_version_id"],
    }
    assert verdict["would_change"]["kind"] == "add_object"
    assert verdict["would_change"]["subject_id"] == "object:lantern"
    assert verdict["would_change"]["preserves"] == [
        "source_snapshot_id",
        "style_version_id",
        "other_subjects",
        "prior_edits",
    ]
    # Preview reads and writes nothing, down to the edit log.
    assert read(objects_api, version["version_id"]) == before

    applied = apply(
        objects_api, version["version_id"], reviewed(before, place=placement(behaviour=MOTION))
    )
    assert applied.status_code == 201, applied.text
    after = applied.json()
    new_edit = after["edits"][-1]
    assert new_edit["kind"] == "add_object"
    assert new_edit["base_state_sha256"] == before["state_sha256"]
    assert after_document(repository, new_edit["edit_id"]) == verdict["would_change"]["document"]

    # What preserves promises, checked against the stored version.
    assert after["source_snapshot_id"] == before["source_snapshot_id"]
    assert after["style_version_id"] == before["style_version_id"]
    assert [o for o in after["objects"] if o["object_id"] != "object:lantern"] == before["objects"]
    assert after["edits"][:-1] == before["edits"]
    assert after["edit_seq"] == before["edit_seq"] + 1


def test_a_starter_world_composes_reopens_and_undoes_through_its_saved_entry(objects_api):
    entry = _create_starter(objects_api)
    world_id = entry["world_id"]
    assert world_id.startswith("world:authored:")
    version_id = entry["authored_version_id"]
    before = read(objects_api, version_id, world_id)
    body = reviewed(before, place=placement(region_id="region:starter"))

    # Without the world, the starter's version is another world's version: not found.
    missing = preview(objects_api, version_id, body)
    assert missing.status_code == 404
    assert missing.json()["code"] == "unknown_reference"

    assert preview(objects_api, version_id, body, world_id).json()["availability"] == "ready"
    binding = {
        "entry_id": entry["entry_id"],
        "base_revision": entry["revision"],
        "authored_state_sha256": entry["authored_state_sha256"],
        "authored_edit_seq": entry["authored_edit_seq"],
    }
    applied = apply(objects_api, version_id, {**body, "saved_entry": binding}, world_id)
    assert applied.status_code == 201, applied.text
    placed = applied.json()

    reopened = read(objects_api, version_id, world_id)
    saved = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert reopened == placed
    assert saved["availability"] == "available"
    assert saved["revision"] == entry["revision"] + 1
    assert saved["authored_state_sha256"] == reopened["state_sha256"] == placed["state_sha256"]
    assert saved["authored_edit_seq"] == reopened["edit_seq"] == placed["edit_seq"]
    assert [o["object_id"] for o in reopened["objects"]] == ["object:lantern"]

    undone = objects_api.post(
        f"/world/versions/{version_id}/objects/undo?world_id={world_id}",
        {
            "base_state_sha256": placed["state_sha256"],
            "saved_entry": {
                "entry_id": saved["entry_id"],
                "base_revision": saved["revision"],
                "authored_state_sha256": saved["authored_state_sha256"],
                "authored_edit_seq": saved["authored_edit_seq"],
            },
        },
    )
    assert undone.status_code == 200, undone.text
    restored = read(objects_api, version_id, world_id)
    saved_again = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert restored["objects"] == before["objects"] == []
    assert restored["state_sha256"] == before["state_sha256"]
    assert [edit["kind"] for edit in restored["edits"]] == ["add_object", "undo"]
    assert saved_again["authored_state_sha256"] == restored["state_sha256"]
    assert saved_again["authored_edit_seq"] == restored["edit_seq"] == 2


def test_a_stale_saved_entry_refuses_apply_and_writes_nothing(objects_api):
    entry = _create_starter(objects_api)
    world_id = entry["world_id"]
    version_id = entry["authored_version_id"]
    before = read(objects_api, version_id, world_id)
    stale = {
        "entry_id": entry["entry_id"],
        "base_revision": entry["revision"] + 1,
        "authored_state_sha256": entry["authored_state_sha256"],
        "authored_edit_seq": entry["authored_edit_seq"],
    }
    body = reviewed(before, place=placement(region_id="region:starter"))
    saved_before = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    refused = apply(objects_api, version_id, {**body, "saved_entry": stale}, world_id)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "stale_saved_world_entry"
    assert read(objects_api, version_id, world_id) == before
    assert objects_api.get(f"/world-entries/{entry['entry_id']}").json() == saved_before


# -- one state, one verdict ------------------------------------------------------------------


def _stale_base(api, repository, version):
    moved = api.add(version, object_id="object:other").json()
    return reviewed(version), "stale_base", moved


def _stale_before_source(api, repository, version):
    moved = api.add(version, object_id="object:other").json()
    return reviewed(version, asset_key="cc0.invented"), "stale_base", moved


def _unknown_asset(api, repository, version):
    return reviewed(version, asset_key="cc0.invented"), "unknown_asset", version


def _missing_bytes(api, repository, version):
    remove_blob(api.store, CUBE)
    return reviewed(version), "asset_bytes_unavailable", version


def _duplicate(api, repository, version):
    added = api.add(version).json()
    return reviewed(added), "subject_already_present", added


def _unknown_region(api, repository, version):
    return reviewed(version, place=placement(region_id="region-z")), "invalid_placement", version


def _bad_behaviour(api, repository, version):
    body = reviewed(version, place=placement(behaviour={**MOTION, "parameters": {"travel_mm": 1}}))
    return body, "invalid_placement", version


def _bad_subject(api, repository, version):
    return (
        reviewed(version, place=placement(subject_id="Object Lantern")),
        "invalid_placement",
        (version),
    )


def _unknown_attachment(api, repository, version):
    body = {
        "base_state_sha256": version["state_sha256"],
        "source": {
            "kind": "source_attachment",
            "entry_id": str(uuid.uuid4()),
            "attachment_id": str(uuid.uuid4()),
        },
        "placement": placement(),
    }
    return body, "unknown_attachment", version


def _invalidated(api, repository, version):
    repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person deleted their world"
    )
    repository.connection.commit()
    return reviewed(version), "source_invalidated", version


@pytest.mark.parametrize(
    "arrange",
    [
        _stale_base,
        _stale_before_source,
        _unknown_asset,
        _missing_bytes,
        _duplicate,
        _unknown_region,
        _bad_behaviour,
        _bad_subject,
        _unknown_attachment,
        _invalidated,
    ],
)
def test_preview_and_apply_give_the_same_reason_for_one_stored_state(
    objects_api, repository, arrange
):
    version = objects_api.version()
    body, reason, current = arrange(objects_api, repository, version)
    stored = read(objects_api, version["version_id"])

    verdict = preview(objects_api, version["version_id"], body).json()
    assert verdict["availability"] == "blocked"
    assert verdict["blocked_reason"] == reason
    assert verdict["would_change"]["document"] is None
    assert verdict["version"]["state_sha256"] == current["state_sha256"] == stored["state_sha256"]

    assert_refused(apply(objects_api, version["version_id"], body), reason)
    assert read(objects_api, version["version_id"]) == stored


def test_a_preview_without_placement_reports_the_source_first(objects_api):
    version = objects_api.version()
    known = preview(objects_api, version["version_id"], reviewed(version) | {"placement": None})
    assert known.json()["blocked_reason"] == "placement_required"
    assert known.json()["source"]["bytes"] == "available"
    unknown = preview(
        objects_api,
        version["version_id"],
        reviewed(version, asset_key="cc0.invented") | {"placement": None},
    )
    assert unknown.json()["blocked_reason"] == "unknown_asset"
    assert unknown.json()["source"]["content_sha256"] is None
    # Apply names no placement-free form at all.
    missing = apply(objects_api, version["version_id"], reviewed(version) | {"placement": None})
    assert missing.status_code == 422


# -- identity of the addressed version -------------------------------------------------------


def test_absent_foreign_and_other_world_versions_answer_the_same_bytes(objects_api):
    version = objects_api.version()
    body = reviewed(version)
    for route in (preview, apply):
        absent = route(objects_api, uuid.uuid4(), body)
        other_world = route(objects_api, version["version_id"], body, "world:authored:elsewhere")
        foreign = objects_api.client.post(
            f"/world/versions/{version['version_id']}/compositions/"
            f"{'preview' if route is preview else 'apply'}",
            headers={"Authorization": f"Bearer {STRANGER_TOKEN}"},
            json=body,
        )
        assert absent.status_code == other_world.status_code == foreign.status_code == 404
        assert absent.content == other_world.content == foreign.content
        assert absent.json()["code"] == "unknown_reference"
    assert read(objects_api, version["version_id"]) == version


# -- the transport cannot carry readiness ----------------------------------------------------


def test_no_request_field_can_make_a_blocked_preview_ready(objects_api):
    version = objects_api.version()
    remove_blob(objects_api.store, CUBE)
    legacy = {
        "source": {
            "kind": "reviewed_asset",
            "source_id": "cc0.marker-cube",
            "content_sha256": CUBE,
        },
        "state_sha256": version["state_sha256"],
        "edit_seq": 0,
        "facts": {"intent": "classify", "world_id": version["world_id"]},
        "representation": {"present_content_digests": [CUBE], "produced": True},
        "resource": {"source_withdrawn": False},
        "existing_subject_ids": [],
        "subject_id": "object:lantern",
    }
    for route in (preview, apply):
        assert route(objects_api, version["version_id"], legacy).status_code == 422
    claims = {
        "availability": "ready",
        "compose_permitted": True,
        "geometry_availability": "available",
        "representation": {"present_content_digests": [CUBE]},
        "content_sha256": CUBE,
        "bytes": "available",
        "edit_seq": 0,
    }
    for name, value in claims.items():
        top = reviewed(version) | {name: value}
        in_source = reviewed(version)
        in_source["source"] = in_source["source"] | {name: value}
        in_placement = reviewed(version, place=placement() | {name: value})
        for body in (top, in_source, in_placement):
            for route in (preview, apply):
                assert route(objects_api, version["version_id"], body).status_code == 422, name

    # Every body the transport does accept for this state is blocked, and for the same reason.
    accepted = [
        reviewed(version),
        reviewed(version) | {"placement": None},
        reviewed(version, place=placement(behaviour=MOTION)),
        reviewed(version, place=placement(origin_role="personal")),
        reviewed(version, place=placement(subject_id="object:another", region_id="region-b")),
    ]
    for body in accepted:
        verdict = preview(objects_api, version["version_id"], body).json()
        assert verdict["availability"] == "blocked"
        assert verdict["blocked_reason"] == "asset_bytes_unavailable"
    # The positive control on the same axis: restore the bytes and the same request is ready.
    seed_reviewed_assets(objects_api.store)
    assert preview(objects_api, version["version_id"], accepted[0]).json()["availability"] == (
        "ready"
    )


# -- the durable byte rule, one for both routes -----------------------------------------------


def test_missing_bytes_refuse_the_object_route_and_composition_alike(objects_api):
    version = objects_api.version()
    remove_blob(objects_api.store, CUBE)
    listed = objects_api.get("/world/assets/cc0.marker-cube").json()
    assert listed["availability"] == "unavailable_asset"

    direct = objects_api.add(version)
    assert direct.status_code == 424, direct.text
    assert direct.json()["code"] == "unavailable_asset"
    # The same code and status the application-wide handler gives the byte route.
    assert objects_api.get("/world/assets/cc0.marker-cube/bytes").json()["code"] == (
        "unavailable_asset"
    )
    assert objects_api.get("/world/assets/cc0.marker-cube/bytes").status_code == 424

    verdict = preview(objects_api, version["version_id"], reviewed(version)).json()
    assert verdict["blocked_reason"] == "asset_bytes_unavailable"
    assert verdict["source"] == {
        "kind": "reviewed_asset",
        "asset_key": "cc0.marker-cube",
        "content_sha256": CUBE,
        "bytes": "unavailable",
    }
    assert_refused(
        apply(objects_api, version["version_id"], reviewed(version)), ("asset_bytes_unavailable")
    )
    assert read(objects_api, version["version_id"]) == version


def test_an_object_whose_bytes_went_missing_can_still_be_moved_removed_and_undone(objects_api):
    """The byte rule is for additions only; history stays correctable."""
    version = objects_api.add(objects_api.version()).json()
    remove_blob(objects_api.store, CUBE)
    path = f"/world/versions/{version['version_id']}/objects"
    moved = objects_api.post(
        f"{path}/object:lantern/move",
        {"base_state_sha256": version["state_sha256"], "transform": transform(x_mm=99)},
    )
    assert moved.status_code == 200, moved.text
    removed = objects_api.post(
        f"{path}/object:lantern/remove", {"base_state_sha256": moved.json()["state_sha256"]}
    )
    assert removed.status_code == 200, removed.text
    undone = objects_api.post(f"{path}/undo", {"base_state_sha256": removed.json()["state_sha256"]})
    assert undone.status_code == 200, undone.text
    assert undone.json()["objects"][0]["removed"] is False
    assert undone.json()["objects"][0]["asset"]["availability"] == "unavailable_asset"


def test_a_repository_without_a_store_refuses_to_add_an_object(repository, tmp_path):
    structures = WorldStructureRepository(repository.connection, repository.workspace_id)
    preview_candidate = structures.preview(structural_candidate(), proposed_by=uuid.uuid4())
    snapshot = structures.apply(
        preview_candidate.preview_id,
        base_snapshot_id=preview_candidate.base_snapshot_id,
        base_graph_sha256=preview_candidate.base_graph_sha256,
        base_reconstruction_sha256=preview_candidate.base_reconstruction_sha256,
        committed_by=uuid.uuid4(),
    )
    blind = WorldObjectRepository(repository.connection, repository.workspace_id)
    version = blind.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="No store", created_by=uuid.uuid4()
    )
    lantern = AuthoredObject(
        object_id="object:lantern",
        asset_sha256=CUBE,
        region_id="region-a",
        transform=Transform(0, 0, 0, 0, 1_000),
        origin=ObjectOrigin("authored", "fictional"),
    )
    for attempt in (
        lambda repo: repo.validate_object_placement(
            version.version_id, lantern, base_state_sha256=version.state_sha256
        ),
        lambda repo: repo.add_object(
            version.version_id, lantern, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
        ),
    ):
        with pytest.raises(UnavailableAsset, match="requires the content-addressed store"):
            attempt(blind)
    assert blind.version(version.version_id).edit_seq == 0

    store = LocalContentAddressedStore(tmp_path / "seeded")
    seed_reviewed_assets(store)
    seeing = WorldObjectRepository(repository.connection, repository.workspace_id, store=store)
    added = seeing.add_object(
        version.version_id, lantern, base_state_sha256=version.state_sha256, actor=uuid.uuid4()
    )
    assert [o.object_id for o in added.objects] == ["object:lantern"]


def test_the_object_route_and_composition_apply_store_identical_results(objects_api):
    left = objects_api.version("Left")
    right = objects_api.version("Right")
    assert left["state_sha256"] == right["state_sha256"]
    direct = objects_api.add(left, behaviour=MOTION, origin_role="personal")
    composed_result = apply(
        objects_api,
        right["version_id"],
        reviewed(right, place=placement(behaviour=MOTION, origin_role="personal")),
    )
    assert direct.status_code == composed_result.status_code == 201
    a, b = direct.json(), composed_result.json()
    for key in ("state_sha256", "edit_seq", "objects", "environment_instances", "schema_version"):
        assert a[key] == b[key], key
    shape = ("edit_seq", "kind", "object_id", "base_state_sha256", "result_state_sha256")
    assert [{k: e[k] for k in shape} for e in a["edits"]] == [
        {k: e[k] for k in shape} for e in b["edits"]
    ]


def test_a_version_whose_style_is_no_longer_live_composes_like_the_object_route(
    objects_api, repository
):
    """No style gate: the durable object route has none, so composition must not invent one."""
    initial = objects_api.get("/world/styles/current").json()
    historical = initial["current"]["version_id"]
    pinned = objects_api.post(
        "/world/versions",
        {
            "title": "Pinned appearance",
            "source_snapshot_id": str(objects_api.snapshot_id),
            "style_version_id": historical,
        },
    ).json()
    moved = _appearance_preview(objects_api, initial, vitality=0.25)
    assert moved.status_code == 201, moved.text
    applied_style = objects_api.post(
        f"/world/styles/previews/{moved.json()['preview_id']}/apply",
        {
            "base_style_version_id": initial["current"]["version_id"],
            "base_topology_digest": initial["current_topology_digest"],
        },
    )
    assert applied_style.status_code in {200, 201}, applied_style.text
    live = objects_api.get("/world/styles/current").json()["current"]["version_id"]
    assert live != historical

    assert (
        preview(objects_api, pinned["version_id"], reviewed(pinned)).json()["availability"]
        == "ready"
    )
    composed_result = apply(objects_api, pinned["version_id"], reviewed(pinned))
    assert composed_result.status_code == 201, composed_result.text
    assert composed_result.json()["style_version_id"] == historical
    twin = objects_api.post(
        "/world/versions",
        {
            "title": "Pinned twin",
            "source_snapshot_id": str(objects_api.snapshot_id),
            "style_version_id": historical,
        },
    ).json()
    assert objects_api.add(twin).status_code == 201


# -- saved-world attachments are membership ---------------------------------------------------


def test_an_attachment_resolves_and_is_never_composition(objects_api, repository):
    entry = _create_starter(objects_api)
    world_id = entry["world_id"]
    version_id = entry["authored_version_id"]
    fresh = _reviewed_source(repository, objects_api, minute=11)
    attached = objects_api.post(
        f"/world-entries/{entry['entry_id']}/source-attachments", _attachment_body(entry, fresh)
    )
    assert attached.status_code == 200, attached.text
    saved = attached.json()
    attachment_id = saved["source_attachments"][0]["attachment_id"]
    version = read(objects_api, version_id, world_id)
    body = {
        "base_state_sha256": version["state_sha256"],
        "source": {
            "kind": "source_attachment",
            "entry_id": entry["entry_id"],
            "attachment_id": attachment_id,
        },
        "placement": placement(region_id="region:starter"),
    }
    verdict = preview(objects_api, version_id, body | {"placement": None}, world_id).json()
    assert verdict["blocked_reason"] == "attachment_is_not_composition"
    assert verdict["would_change"] == {
        "kind": "none",
        "subject_id": None,
        "document": None,
        "preserves": [],
    }
    assert verdict["source"]["bytes"] == "not_applicable"
    assert_refused(apply(objects_api, version_id, body, world_id), "attachment_is_not_composition")
    # The entry id is part of the reference: the same attachment under another entry is unknown.
    elsewhere = body | {"source": body["source"] | {"entry_id": str(uuid.uuid4())}}
    assert preview(objects_api, version_id, elsewhere, world_id).json()["blocked_reason"] == (
        "unknown_attachment"
    )

    expiring = _reviewed_source(repository, objects_api, minute=12, valid_for_seconds=5)
    again = objects_api.post(
        f"/world-entries/{entry['entry_id']}/source-attachments",
        _attachment_body(saved, expiring),
    )
    assert again.status_code == 200, again.text
    expired_id = next(
        item["attachment_id"]
        for item in again.json()["source_attachments"]
        if item["capture_id"] == expiring["capture_id"]
    )
    expiry = repository.connection.execute(
        "select valid_until from capture_reconstruction_authorization "
        "where workspace_id=%s and authorization_id=%s",
        (repository.workspace_id, uuid.UUID(expiring["authorization_id"])),
    ).fetchone()["valid_until"]
    repository.connection.execute(
        "select pg_sleep(greatest(0,extract(epoch from (%s-clock_timestamp())))+0.05)",
        (expiry,),
    )
    repository.connection.commit()
    expired = body | {"source": body["source"] | {"attachment_id": expired_id}}
    assert preview(objects_api, version_id, expired, world_id).json()["blocked_reason"] == (
        "expired_source_not_composable"
    )
    assert_refused(
        apply(objects_api, version_id, expired, world_id), ("expired_source_not_composable")
    )
    assert read(objects_api, version_id, world_id) == version


# -- admitted environment (synthetic fixture) --------------------------------------------------


@pytest.fixture
def environment_api(composed, spine_schema, monkeypatch):
    token = "composition-environment-owner-token"
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                token: {
                    "workspace_id": str(composed.worlds.workspace_id),
                    "actor": str(uuid.uuid4()),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
    )
    composed.worlds.connection.commit()
    database = scratch_database(spine_schema[1])
    services = Services(
        database=database,
        readonly_database=database,
        store=composed.store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(services, verify=False)) as client:

        class Api:
            def post(self, path, body):
                return client.post(path, headers=headers, json=body)

            def get(self, path):
                return client.get(path, headers=headers)

        yield composed, Api()


def environment_body(composed, version, *, instance_id="environment:plaza", feature=False, **kw):
    source = {
        "kind": "environment_admission",
        "admission_id": str(composed.source.admission_id),
        "render_asset_id": str(composed.render.asset_id),
        "publication_id": str(composed.publication.publication_id) if feature else None,
        "selection": (
            {"kind": "feature", "feature_id": composed.feature_id, "render_batch_id": 7}
            if feature
            else {"kind": "whole_asset"}
        ),
    }
    source.update(kw.pop("source", {}))
    return {
        "base_state_sha256": version["state_sha256"],
        "source": source,
        "placement": {
            "subject_id": instance_id,
            "region_id": "region-a",
            "transform": transform(),
            "origin_role": "personal",
            "source_anchor": {
                "frame_name": "nyc-grid",
                "coordinate_scale": 1000,
                "coordinates": [10, 20, 0],
            },
        },
        **kw,
    }


def test_an_environment_composes_through_the_durable_environment_rules(environment_api, repository):
    composed, api = environment_api
    version_id = composed.version.version_id
    version = read(api, version_id)

    for feature in (False, True):
        instance = "environment:feature" if feature else "environment:plaza"
        body = environment_body(composed, version, instance_id=instance, feature=feature)
        verdict = preview(api, version_id, body).json()
        assert verdict["availability"] == "ready", verdict
        assert verdict["source"]["content_sha256"] == composed.render.expected_sha256
        assert verdict["source"]["bytes"] == "available"
        applied = apply(api, version_id, body)
        assert applied.status_code == 201, applied.text
        version = applied.json()
        edit = version["edits"][-1]
        assert edit["kind"] == "add_environment"
        assert after_document(repository, edit["edit_id"]) == verdict["would_change"]["document"]
        placed = {item["instance_id"]: item for item in version["environment_instances"]}
        assert placed[instance]["availability"] == "available"
        assert placed[instance]["origin"] == {"kind": "authored", "role": "personal"}

    duplicate = environment_body(composed, version)
    assert preview(api, version_id, duplicate).json()["blocked_reason"] == (
        "subject_already_present"
    )
    assert_refused(apply(api, version_id, duplicate), "subject_already_present")

    unknown = environment_body(
        composed,
        version,
        instance_id="environment:nowhere",
        source={"admission_id": str(uuid.uuid4())},
    )
    assert preview(api, version_id, unknown).json()["blocked_reason"] == (
        "environment_binding_unknown"
    )
    wrong_anchor = environment_body(composed, version, instance_id="environment:askew")
    wrong_anchor["placement"]["source_anchor"]["frame_name"] = "another-frame"
    assert preview(api, version_id, wrong_anchor).json()["blocked_reason"] == "invalid_placement"
    assert_refused(apply(api, version_id, wrong_anchor), "invalid_placement")
    assert read(api, version_id) == version


def test_rights_withdrawn_between_preview_and_apply_refuse_apply(environment_api):
    composed, api = environment_api
    version_id = composed.version.version_id
    version = read(api, version_id)
    body = environment_body(composed, version, instance_id="environment:later")
    assert preview(api, version_id, body).json()["availability"] == "ready"

    composed.environments.withdraw("asset", composed.render.asset_id)
    composed.environments.connection.commit()

    assert_refused(apply(api, version_id, body), "environment_withdrawn")
    assert preview(api, version_id, body).json()["blocked_reason"] == "environment_withdrawn"
    assert read(api, version_id) == version


def test_missing_bytes_and_a_superseded_publication_block_an_environment(environment_api):
    composed, api = environment_api
    version_id = composed.version.version_id
    version = read(api, version_id)
    feature = environment_body(composed, version, instance_id="environment:old", feature=True)
    composed.environments.publish_feature_index(
        composed.source.admission_id,
        FeatureIndexPublication(render_asset_id=composed.render.asset_id, features=()),
        actor=uuid.uuid4(),
    )
    composed.environments.connection.commit()
    assert preview(api, version_id, feature).json()["blocked_reason"] == (
        "environment_binding_drift"
    )
    assert_refused(apply(api, version_id, feature), "environment_binding_drift")

    remove_blob(composed.store, composed.render.expected_sha256)
    whole = environment_body(composed, version, instance_id="environment:gone")
    verdict = preview(api, version_id, whole).json()
    assert verdict["blocked_reason"] == "environment_bytes_unavailable"
    assert verdict["source"]["bytes"] == "unavailable"
    assert_refused(apply(api, version_id, whole), "environment_bytes_unavailable")
    assert read(api, version_id) == version


def test_a_render_asset_without_compose_rights_is_refused(environment_api, tmp_path):
    composed, api = environment_api
    denied_bytes = b"synthetic render without compose rights"
    denied_path = tmp_path / "denied.glb"
    denied_path.write_bytes(denied_bytes)
    denied = DerivedEnvironmentAsset(
        admission_id=composed.source.admission_id,
        expected_sha256=hashlib.sha256(denied_bytes).hexdigest(),
        expected_byte_size=len(denied_bytes),
        media_type="model/gltf-binary",
        derivation_kind="denied",
        derivation_lineage={
            "method": "fixture/v1",
            "input_sha256": [composed.source.expected_sha256],
        },
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(compose=False),
        attribution="Synthetic fixture",
        modification_notice="Synthetic render without compose rights",
        local_path=denied_path,
    )
    composed.environments.register_derived(denied, actor=uuid.uuid4())
    composed.environments.connection.commit()
    version_id = composed.version.version_id
    version = read(api, version_id)
    body = environment_body(
        composed,
        version,
        instance_id="environment:denied",
        source={"render_asset_id": str(denied.asset_id)},
    )
    assert preview(api, version_id, body).json()["blocked_reason"] == "compose_not_permitted"
    assert_refused(apply(api, version_id, body), "compose_not_permitted")
    assert read(api, version_id) == version


def test_a_withdrawal_inside_the_write_is_reported_as_the_same_reason(composed, monkeypatch):
    """Apply's own write repeats the rights check; a refusal there keeps the preview vocabulary."""
    worlds = composed.worlds
    request = CompositionRequest(
        base_state_sha256=composed.version.state_sha256,
        source=EnvironmentAdmissionSource(
            composed.source.admission_id,
            composed.render.asset_id,
            None,
            EnvironmentSelection("whole_asset"),
        ),
        placement=CompositionPlacement(
            subject_id="environment:race",
            region_id="region-a",
            transform=Transform(0, 0, 0, 0, 1_000),
            origin_role="fictional",
            source_anchor=SourceAnchor("nyc-grid", 1000, (10, 20, 0)),
        ),
    )
    assert preview_composition(worlds, composed.version.version_id, request).availability == (
        "ready"
    )
    original = worlds._final_environment_authorization

    def withdraw_first(instance) -> None:
        composed.environments.withdraw("asset", composed.render.asset_id)
        original(instance)

    monkeypatch.setattr(worlds, "_final_environment_authorization", withdraw_first)
    with pytest.raises(CompositionBlocked) as refused, worlds.connection.transaction():
        apply_composition(worlds, composed.version.version_id, request, actor=uuid.uuid4())
    assert str(refused.value) == "environment_withdrawn"
    unchanged = worlds.version(composed.version.version_id)
    assert unchanged.environment_instances == ()
    assert unchanged.edit_seq == 0


# -- cases from the adversarial review -----------------------------------------------------------


def test_an_asset_key_the_registry_could_never_hold_is_422_on_both_routes(objects_api):
    """A NUL once reached the catalog query and escaped as a server error."""
    version = objects_api.version()
    for key in ("cc0.marker" + chr(0) + "cube", "CC0.Marker-Cube", "cc0 cube", "9cube"):
        body = reviewed(version, asset_key=key)
        for route in (preview, apply):
            response = route(objects_api, version["version_id"], body)
            assert response.status_code == 422, (key, response.status_code, response.text)
    assert read(objects_api, version["version_id"]) == version


def test_behaviour_version_must_be_a_json_integer_on_every_route_that_takes_one(objects_api):
    version = objects_api.version()
    for value in (1.0, "1"):
        behaviour = {**MOTION, "behaviour_version": value}
        body = reviewed(version, place=placement(behaviour=behaviour))
        for route in (preview, apply):
            assert route(objects_api, version["version_id"], body).status_code == 422, value
        assert objects_api.add(version, behaviour=behaviour).status_code == 422, value
    # The positive control on the same axis: the integer is accepted everywhere.
    body = reviewed(version, place=placement(behaviour=MOTION))
    assert preview(objects_api, version["version_id"], body).json()["availability"] == "ready"
    assert objects_api.add(version, behaviour=MOTION).status_code == 201


REMOVED_TOP = {
    "facts": {"intent": "classify", "world_id": "world:default"},
    "resource": {"source_withdrawn": False},
    "representation": {"present_content_digests": []},
    "existing_subject_ids": [],
    "edit_seq": 0,
    "state_sha256": "0" * 64,
    "source_snapshot_id": str(uuid.uuid4()),
    "style_version_id": str(uuid.uuid4()),
    "subject_id": "object:lantern",
    "object": {},
    "environment": {},
    "compose_permitted": True,
    "geometry_availability": "available",
}


def test_every_removed_and_nested_unknown_field_is_422(objects_api):
    version = objects_api.version()
    vid = version["version_id"]
    for name, value in REMOVED_TOP.items():
        for route in (preview, apply):
            assert route(objects_api, vid, reviewed(version) | {name: value}).status_code == 422
    for name in ("source_id", "content_sha256", "compose_permitted", "bytes"):
        body = reviewed(version)
        body["source"] = body["source"] | {name: "x"}
        for route in (preview, apply):
            assert route(objects_api, vid, body).status_code == 422, name
    nested = [
        placement(transform={**placement()["transform"], "extra": 1}),
        placement(behaviour={**MOTION, "extra": 1}),
    ]
    for place in nested:
        for route in (preview, apply):
            assert route(objects_api, vid, reviewed(version, place=place)).status_code == 422
    binding = {
        "entry_id": str(uuid.uuid4()),
        "base_revision": 1,
        "authored_state_sha256": version["state_sha256"],
        "authored_edit_seq": 0,
        "extra": True,
    }
    assert apply(objects_api, vid, reviewed(version) | {"saved_entry": binding}).status_code == 422
    binding.pop("extra")
    assert preview(objects_api, vid, reviewed(version) | {"saved_entry": binding}).status_code == (
        422
    )


def test_nested_unknown_fields_in_environment_bodies_are_422(environment_api):
    composed, api = environment_api
    version_id = composed.version.version_id
    version = read(api, version_id)
    for mutate in (
        lambda b: b["placement"]["source_anchor"].update(extra=1),
        lambda b: b["source"]["selection"].update(extra=1),
        lambda b: b["source"].update(content_sha256="0" * 64),
        lambda b: b["placement"].update(behaviour=MOTION),
        lambda b: b["source"].update(publication_id=str(uuid.uuid4())),
    ):
        body = environment_body(composed, version, instance_id="environment:probe")
        mutate(body)
        for route in (preview, apply):
            assert route(api, version_id, body).status_code == 422, body


def test_translation_beyond_the_world_is_a_blocked_reason_not_422(objects_api):
    version = objects_api.version()
    for x in (1_000_000_001, 10**30):
        body = reviewed(version, place=placement(transform={**placement()["transform"], "x_mm": x}))
        verdict = preview(objects_api, version["version_id"], body).json()
        assert verdict["blocked_reason"] == "invalid_placement"
        assert_refused(apply(objects_api, version["version_id"], body), "invalid_placement")


def test_an_attachment_of_another_world_is_unknown(objects_api, repository):
    starter = _create_starter(objects_api, "Starter")
    default_version = objects_api.version()
    assert starter["world_id"] != default_version["world_id"]
    fresh = _reviewed_source(repository, objects_api, minute=21)
    attached = objects_api.post(
        f"/world-entries/{starter['entry_id']}/source-attachments",
        _attachment_body(starter, fresh),
    )
    assert attached.status_code == 200, attached.text
    attachment_id = attached.json()["source_attachments"][0]["attachment_id"]
    source = {
        "kind": "source_attachment",
        "entry_id": starter["entry_id"],
        "attachment_id": attachment_id,
    }
    own = read(objects_api, starter["authored_version_id"], starter["world_id"])
    verdict = preview(
        objects_api,
        starter["authored_version_id"],
        {"base_state_sha256": own["state_sha256"], "source": source, "placement": None},
        starter["world_id"],
    ).json()
    assert verdict["blocked_reason"] == "attachment_is_not_composition"
    verdict = preview(
        objects_api,
        default_version["version_id"],
        {"base_state_sha256": default_version["state_sha256"], "source": source, "placement": None},
    ).json()
    assert verdict["blocked_reason"] == "unknown_attachment"
    assert_refused(
        apply(
            objects_api,
            default_version["version_id"],
            {
                "base_state_sha256": default_version["state_sha256"],
                "source": source,
                "placement": placement(),
            },
        ),
        "unknown_attachment",
    )


def _lock_waiters(connection) -> int:
    return connection.execute(
        "select count(*) as n from pg_stat_activity "
        "where wait_event_type='Lock' and datname=current_database()"
    ).fetchone()["n"]


def _wait_for_a_lock_waiter(connection, seconds=20.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _lock_waiters(connection):
            return
        time.sleep(0.05)
    raise AssertionError("the second writer never waited on a lock")


def test_two_concurrent_applies_on_one_base_leave_one_winner(objects_api, repository, spine_schema):
    version = objects_api.version()
    vid = uuid.UUID(version["version_id"])
    a = another_connection(spine_schema, repository.workspace_id)
    b = another_connection(spine_schema, repository.workspace_id)
    watcher = another_connection(spine_schema, repository.workspace_id)
    try:
        repo_a = WorldObjectRepository(a, repository.workspace_id, store=objects_api.store)
        repo_b = WorldObjectRepository(b, repository.workspace_id, store=objects_api.store)

        def request(subject):
            return CompositionRequest(
                base_state_sha256=version["state_sha256"],
                source=ReviewedAssetSource("cc0.marker-cube"),
                placement=CompositionPlacement(
                    subject, "region-a", Transform(0, 0, 0, 0, 1_000), "fictional"
                ),
            )

        outcome: dict[str, object] = {}

        def second():
            try:
                with b.transaction():
                    outcome["b"] = apply_composition(
                        repo_b, vid, request("object:second"), actor=uuid.uuid4()
                    )
            except Exception as exc:
                outcome["b"] = exc

        with a.transaction():
            won = apply_composition(repo_a, vid, request("object:first"), actor=uuid.uuid4())
            thread = threading.Thread(target=second)
            thread.start()
            _wait_for_a_lock_waiter(watcher)
        thread.join(30)
        assert [o.object_id for o in won.objects] == ["object:first"]
        refused = outcome["b"]
        assert isinstance(refused, CompositionBlocked), refused
        assert refused.blocked_reason == "stale_base"
        final = repo_a.version(vid)
        assert [o.object_id for o in final.objects] == ["object:first"]
        assert final.edit_seq == 1
    finally:
        for connection in (a, b, watcher):
            connection.close()


def test_two_concurrent_http_applies_with_one_saved_entry(
    objects_api, repository, spine_schema, monkeypatch
):
    entry = _create_starter(objects_api)
    world_id = entry["world_id"]
    version_id = entry["authored_version_id"]
    before = read(objects_api, version_id, world_id)
    binding = {
        "entry_id": entry["entry_id"],
        "base_revision": entry["revision"],
        "authored_state_sha256": entry["authored_state_sha256"],
        "authored_edit_seq": entry["authored_edit_seq"],
    }
    holding, release = threading.Event(), threading.Event()
    original = WorldObjectRepository._append_edit
    calls = []

    def paused(self, row, **kwargs):
        calls.append(kwargs.get("object_id"))
        if len(calls) == 1:
            holding.set()
            assert release.wait(30)
        return original(self, row, **kwargs)

    monkeypatch.setattr(WorldObjectRepository, "_append_edit", paused)
    results = {}

    def run(name, subject):
        body = reviewed(before, place=placement(subject_id=subject, region_id="region:starter")) | {
            "saved_entry": binding
        }
        results[name] = apply(objects_api, version_id, body, world_id)

    first = threading.Thread(target=run, args=("first", "object:first"))
    first.start()
    assert holding.wait(30)
    second = threading.Thread(target=run, args=("second", "object:second"))
    second.start()
    watcher = another_connection(spine_schema, repository.workspace_id)
    try:
        _wait_for_a_lock_waiter(watcher)
    finally:
        watcher.close()
        release.set()
    first.join(30)
    second.join(30)
    assert results["first"].status_code == 201, results["first"].text
    assert results["second"].status_code == 409, results["second"].text
    assert results["second"].json()["code"] == "stale_saved_world_entry"
    after = read(objects_api, version_id, world_id)
    saved = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert [o["object_id"] for o in after["objects"]] == ["object:first"]
    assert after["edit_seq"] == before["edit_seq"] + 1
    assert saved["revision"] == entry["revision"] + 1
    assert saved["authored_state_sha256"] == after["state_sha256"]


def test_preview_names_one_snapshot_while_a_writer_commits_between_its_reads(
    objects_api, repository, spine_schema, monkeypatch
):
    """Preview once said stale_base beside a version block equal to the base."""
    version = objects_api.version()
    vid = uuid.UUID(version["version_id"])
    reader = another_connection(spine_schema, repository.workspace_id)
    writer = another_connection(spine_schema, repository.workspace_id)
    try:
        repo = WorldObjectRepository(reader, repository.workspace_id, store=objects_api.store)
        other = WorldObjectRepository(writer, repository.workspace_id, store=objects_api.store)
        original = WorldObjectRepository.validate_object_placement
        raced = []

        def racing(self, *args, **kwargs):
            if self is repo and not raced:
                raced.append(True)
                other.add_object(
                    vid,
                    AuthoredObject(
                        "object:racer",
                        CUBE,
                        "region-a",
                        Transform(0, 0, 0, 0, 1_000),
                        ObjectOrigin("authored", "fictional"),
                    ),
                    base_state_sha256=version["state_sha256"],
                    actor=uuid.uuid4(),
                )
            return original(self, *args, **kwargs)

        monkeypatch.setattr(WorldObjectRepository, "validate_object_placement", racing)
        request = CompositionRequest(
            base_state_sha256=version["state_sha256"],
            source=ReviewedAssetSource("cc0.marker-cube"),
            placement=CompositionPlacement(
                "object:lantern", "region-a", Transform(0, 0, 0, 0, 1_000), "fictional"
            ),
        )
        verdict = preview_composition(repo, vid, request).document()
        assert raced == [True]
        # One snapshot: the state it read is the base it compared, and nothing contradicts it.
        assert verdict["availability"] == "ready", verdict
        assert verdict["version"]["state_sha256"] == version["state_sha256"]
        # The writer did commit, so the next preview sees it, and so does apply.
        again = preview_composition(repo, vid, request).document()
        assert again["blocked_reason"] == "stale_base"
        assert again["version"]["state_sha256"] != version["state_sha256"]
        with pytest.raises(CompositionBlocked) as refused, reader.transaction():
            apply_composition(repo, vid, request, actor=uuid.uuid4())
        assert refused.value.blocked_reason == "stale_base"
    finally:
        reader.close()
        writer.close()


def _read_only(spine_schema, workspace_id):
    connection = another_connection(spine_schema, workspace_id)
    connection.execute("set default_transaction_read_only = on")
    return connection


def test_preview_runs_in_read_only_transactions(objects_api, repository, spine_schema):
    entry = _create_starter(objects_api)
    fresh = _reviewed_source(repository, objects_api, minute=35)
    attached = objects_api.post(
        f"/world-entries/{entry['entry_id']}/source-attachments", _attachment_body(entry, fresh)
    ).json()
    version = read(objects_api, entry["authored_version_id"], entry["world_id"])
    connection = _read_only(spine_schema, repository.workspace_id)
    try:
        repo = WorldObjectRepository(
            connection, repository.workspace_id, world_id=entry["world_id"], store=objects_api.store
        )
        vid = uuid.UUID(entry["authored_version_id"])
        ready = preview_composition(
            repo,
            vid,
            CompositionRequest(
                base_state_sha256=version["state_sha256"],
                source=ReviewedAssetSource("cc0.marker-cube"),
                placement=CompositionPlacement(
                    "object:ro", "region:starter", Transform(0, 0, 0, 0, 1_000), "fictional"
                ),
            ),
        )
        assert ready.availability == "ready", ready.blocked_detail
        blocked = preview_composition(
            repo,
            vid,
            CompositionRequest(
                base_state_sha256=version["state_sha256"],
                source=SourceAttachmentSource(
                    uuid.UUID(entry["entry_id"]),
                    uuid.UUID(attached["source_attachments"][0]["attachment_id"]),
                ),
            ),
        )
        assert blocked.blocked_reason == "attachment_is_not_composition"
    finally:
        connection.close()


def test_environment_preview_runs_in_read_only_transactions(composed, spine_schema):
    composed.worlds.connection.commit()
    connection = _read_only(spine_schema, composed.worlds.workspace_id)
    try:
        repo = WorldObjectRepository(connection, composed.worlds.workspace_id, store=composed.store)
        for feature in (False, True):
            request = CompositionRequest(
                base_state_sha256=composed.version.state_sha256,
                source=EnvironmentAdmissionSource(
                    composed.source.admission_id,
                    composed.render.asset_id,
                    composed.publication.publication_id if feature else None,
                    EnvironmentSelection("feature", composed.feature_id, 7)
                    if feature
                    else EnvironmentSelection("whole_asset"),
                ),
                placement=CompositionPlacement(
                    "environment:ro",
                    "region-a",
                    Transform(0, 0, 0, 0, 1_000),
                    "fictional",
                    source_anchor=SourceAnchor("nyc-grid", 1000, (10, 20, 0)),
                ),
            )
            verdict = preview_composition(repo, composed.version.version_id, request)
            assert verdict.availability == "ready", verdict.blocked_detail
    finally:
        connection.close()


def test_environment_binding_unknown_is_one_verdict_on_both_routes(environment_api):
    composed, api = environment_api
    version_id = composed.version.version_id
    version = read(api, version_id)
    feature = {"kind": "feature", "feature_id": composed.feature_id, "render_batch_id": 8}
    cases = [
        environment_body(
            composed,
            version,
            instance_id="environment:nowhere",
            source={"admission_id": str(uuid.uuid4())},
        ),
        environment_body(
            composed,
            version,
            instance_id="environment:norender",
            source={"render_asset_id": str(uuid.uuid4())},
        ),
        environment_body(
            composed,
            version,
            instance_id="environment:nofeature",
            feature=True,
            source={"selection": {"kind": "feature", "feature_id": "f" * 32, "render_batch_id": 7}},
        ),
        environment_body(
            composed,
            version,
            instance_id="environment:wrongbatch",
            feature=True,
            source={"selection": feature},
        ),
        environment_body(
            composed,
            version,
            instance_id="environment:nopublication",
            feature=True,
            source={"publication_id": str(uuid.uuid4())},
        ),
    ]
    for body in cases:
        verdict = preview(api, version_id, body).json()
        assert verdict["blocked_reason"] == "environment_binding_unknown", verdict
        assert_refused(apply(api, version_id, body), "environment_binding_unknown")
    assert read(api, version_id) == version


def test_a_blocked_apply_with_a_valid_saved_entry_advances_nothing(objects_api):
    entry = _create_starter(objects_api)
    world_id = entry["world_id"]
    version_id = entry["authored_version_id"]
    before = read(objects_api, version_id, world_id)
    saved_before = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    remove_blob(objects_api.store, CUBE)
    binding = {
        "entry_id": entry["entry_id"],
        "base_revision": entry["revision"],
        "authored_state_sha256": entry["authored_state_sha256"],
        "authored_edit_seq": entry["authored_edit_seq"],
    }
    body = reviewed(before, place=placement(region_id="region:starter")) | {"saved_entry": binding}
    assert_refused(apply(objects_api, version_id, body, world_id), "asset_bytes_unavailable")
    assert read(objects_api, version_id, world_id) == before
    assert objects_api.get(f"/world-entries/{entry['entry_id']}").json() == saved_before


def test_an_environment_preview_reads_each_pinned_blob_once(environment_api, monkeypatch):
    composed, api = environment_api
    version_id = composed.version.version_id
    reads: list[str] = []
    original = LocalContentAddressedStore.get

    def counting(self, blob_id):
        reads.append(blob_id.hex)
        return original(self, blob_id)

    monkeypatch.setattr(LocalContentAddressedStore, "get", counting)
    source, render = composed.source.expected_sha256, composed.render.expected_sha256
    index = bytes(
        composed.worlds.connection.execute(
            "select index_sha256 from environment_feature_index_publication "
            "where workspace_id=%s and publication_id=%s",
            (composed.worlds.workspace_id, composed.publication.publication_id),
        ).fetchone()["index_sha256"]
    ).hex()
    composed.worlds.connection.commit()

    version = read(api, version_id)
    reads.clear()
    assert (
        preview(api, version_id, environment_body(composed, version)).json()["availability"]
        == "ready"
    )
    assert sorted(reads) == sorted([source, render])

    reads.clear()
    applied = apply(api, version_id, environment_body(composed, version))
    assert applied.status_code == 201, applied.text
    # Once to resolve, once by the durable write under its lock, once for the returned body's
    # availability of the one instance the version then holds.
    assert reads.count(render) <= 3

    # An instance already in the version adds no reads to the next preview.
    version = applied.json()
    reads.clear()
    feature = environment_body(composed, version, instance_id="environment:f", feature=True)
    assert preview(api, version_id, feature).json()["availability"] == "ready"
    assert sorted(reads) == sorted([source, render, index])


def test_corrupt_environment_bytes_are_unavailable_bytes_not_a_server_error(environment_api):
    composed, api = environment_api
    version_id = composed.version.version_id
    version = read(api, version_id)
    path = composed.store.root / composed.store.key_for(
        BlobId.from_hex(composed.render.expected_sha256)
    )
    path.chmod(0o644)
    path.write_bytes(b"not the pinned render bytes")
    body = environment_body(composed, version, instance_id="environment:corrupt")
    verdict = preview(api, version_id, body).json()
    assert verdict["blocked_reason"] == "environment_bytes_unavailable"
    assert verdict["source"]["bytes"] == "unavailable"
    assert_refused(apply(api, version_id, body), "environment_bytes_unavailable")
    assert read(api, version_id) == version


# -- society refusals apply can meet and preview cannot see -----------------------------------


def test_a_society_input_refusal_answers_a_stable_code_on_both_object_routes(objects_api):
    def refuse(connection, session, version_id):
        raise UnavailableSocietyInput("society input history is unavailable")

    objects_api.client.app.state.society_authored_edit = refuse
    version = objects_api.version()
    # Preview does not run the hook, so it cannot know.
    assert (
        preview(objects_api, version["version_id"], reviewed(version)).json()["availability"]
        == "ready"
    )
    for response in (
        apply(objects_api, version["version_id"], reviewed(version)),
        objects_api.add(version),
    ):
        assert response.status_code == 424, response.text
        assert response.json()["code"] == "unavailable_society_input"
    assert read(objects_api, version["version_id"]) == version


def test_a_real_society_runtime_refusal_rolls_apply_back(runtime_world):
    w = runtime_world
    create_society(w)
    missing = SocietyRuntime(store=w["store"], bindings=[], reviewed_affordances=w["registry"])
    objects = WorldObjectRepository(
        w["connection"],
        w["workspace"],
        store=w["store"],
        on_edit=lambda vid: missing.authored_edit(w["connection"], w["session"], vid),
    )
    version = objects.version(w["binding"].version_id)
    request = CompositionRequest(
        base_state_sha256=version.state_sha256,
        source=ReviewedAssetSource("cc0.marker-plate"),
        placement=CompositionPlacement(
            "object:plate", "region-a", Transform(40_000, 0, 64_000, 0, 1_000), "fictional"
        ),
    )
    assert preview_composition(objects, version.version_id, request).availability == "ready"
    with pytest.raises(UnavailableSocietyInput) as refused, w["connection"].transaction():
        apply_composition(objects, version.version_id, request, actor=uuid.uuid4())
    problem = _object_problem(refused.value)
    assert problem is not None
    assert problem.status_code == 424
    assert json.loads(problem.body)["code"] == "unavailable_society_input"
    assert objects.version(version.version_id) == version


def test_a_purposeful_society_without_an_adapter_refuses_apply(runtime_world):
    w = runtime_world
    create_society(w)
    direct = WorldObjectRepository(w["connection"], w["workspace"], store=w["store"])
    version = direct.version(w["binding"].version_id)
    request = CompositionRequest(
        base_state_sha256=version.state_sha256,
        source=ReviewedAssetSource("cc0.marker-plate"),
        placement=CompositionPlacement(
            "object:plate", "region-a", Transform(40_000, 0, 64_000, 0, 1_000), "fictional"
        ),
    )
    assert preview_composition(direct, version.version_id, request).availability == "ready"
    adapter = "atomic authored-input adapter"
    with pytest.raises(InvalidObjectState, match=adapter) as refused, w["connection"].transaction():
        apply_composition(direct, version.version_id, request, actor=uuid.uuid4())
    problem = _object_problem(refused.value)
    assert problem is not None
    assert problem.status_code == 409
    assert json.loads(problem.body)["code"] == "invalid_object_state"
    assert direct.version(version.version_id) == version
