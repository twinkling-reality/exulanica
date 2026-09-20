"""Durable personal-world entry, isolation, invalidation, and stale-save behavior."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
from queue import Queue
from time import monotonic, sleep

import psycopg
import pytest
from exulanica.world import (
    SavedWorldEntryRepository,
    StaleSavedWorldEntry,
    Transform,
    WorldObjectRepository,
    WorldStructureRepository,
    WorldStyleRepository,
)
from exulanica.world.starter import authored_starter_candidate

from test_world_objects_api import STRANGER_TOKEN, ObjectsApi
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


def _create_entry(api: ObjectsApi, repository):
    style = WorldStyleRepository(repository.connection, repository.workspace_id).current()
    version = api.version("My source-backed world")
    response = api.post(
        "/world-entries",
        {
            "world_id": version["world_id"],
            "title": "My source-backed world",
            "source_kind": "personal",
            "authored_version_id": version["version_id"],
            "style_version_id": str(style.version_id),
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), version, style


def _create_starter(api: ObjectsApi, title: str = "My world"):
    response = api.post("/world-entries/starter", {"title": title})
    assert response.status_code == 200, response.text
    return response.json()


def test_starter_creation_is_real_source_independent_and_exactly_idempotent(
    objects_api, repository
):
    entry = _create_starter(objects_api)
    assert entry["world_id"].startswith("world:authored:")
    assert entry["source_kind"] == "authored"
    assert entry["availability"] == "available"
    assert entry["source_snapshot_id"]
    assert len(entry["source_snapshot_sha256"]) == 64
    assert entry["authored_scene"] == {
        "schema_version": 1,
        "kind": "authored-starter",
        "region": {
            "region_id": "region:starter",
            "origin": "authored",
            "module": {"key": "region.authored-ground", "version": 1},
            "ground": {
                "kind": "flat",
                "half_width_mm": 12_000,
                "half_depth_mm": 12_000,
                "elevation_mm": 0,
            },
            "spawn": {
                "x_mm": 0,
                "y_mm": 0,
                "z_mm": 4_000,
                "yaw_microradians": 0,
            },
        },
    }
    assert objects_api.get("/world-entries").json() == [entry]
    assert _create_starter(objects_api) == entry

    sources = repository.connection.execute(
        "select count(*) as n from world_topology_source "
        "where workspace_id=%s and world_id=%s",
        (repository.workspace_id, entry["world_id"]),
    ).fetchone()
    assert sources["n"] == 0
    dependencies = repository.connection.execute(
        "select count(*) as n from world_structure_dependency "
        "where workspace_id=%s and world_id=%s and snapshot_id=%s",
        (
            repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["source_snapshot_id"]),
        ),
    ).fetchone()
    assert dependencies["n"] == 0

    conflicting = objects_api.post("/world-entries/starter", {"title": "A silent rename"})
    assert conflicting.status_code == 409
    assert conflicting.json()["code"] == "saved_world_conflict"
    assert objects_api.get(f"/world-entries/{entry['entry_id']}").json()["title"] == "My world"


def test_concurrent_starter_creation_returns_one_authority(objects_api):
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda _index: objects_api.post(
                    "/world-entries/starter", {"title": "Concurrent world"}
                ),
                range(2),
            )
        )
    assert [response.status_code for response in responses] == [200, 200]
    entries = [response.json() for response in responses]
    assert entries[0] == entries[1]
    assert objects_api.get("/world-entries").json() == [entries[0]]


def test_starter_rename_and_bound_object_edit_reopen_exactly(objects_api):
    entry = _create_starter(objects_api)
    renamed = objects_api.client.put(
        f"/world-entries/{entry['entry_id']}",
        headers=objects_api.headers,
        json={
            "base_revision": entry["revision"],
            "authored_version_id": entry["authored_version_id"],
            "expected_authored_state_sha256": entry["authored_state_sha256"],
            "expected_authored_edit_seq": entry["authored_edit_seq"],
            "style_version_id": entry["style_version_id"],
            "title": "Workshop",
        },
    )
    assert renamed.status_code == 200, renamed.text
    renamed_entry = renamed.json()
    assert renamed_entry["title"] == "Workshop"

    version = objects_api.get(
        f"/world/versions/{renamed_entry['authored_version_id']}"
        f"?world_id={renamed_entry['world_id']}"
    ).json()
    added = objects_api.post(
        f"/world/versions/{renamed_entry['authored_version_id']}/objects"
        f"?world_id={renamed_entry['world_id']}",
        {
            "base_state_sha256": version["state_sha256"],
            "object_id": "object:lantern",
            "asset_sha256": "b41289ac10548cf698d46a15206caa8e744b0b800f4ac29260c99f18d8b831d9",
            "region_id": "region:starter",
            "transform": {
                "x_mm": 1_200,
                "y_mm": 0,
                "z_mm": -450,
                "yaw_microradians": 785_398,
                "scale_milli": 1_000,
            },
            "origin_role": "fictional",
            "saved_entry": {
            "entry_id": renamed_entry["entry_id"],
            "base_revision": renamed_entry["revision"],
            "authored_state_sha256": renamed_entry["authored_state_sha256"],
            "authored_edit_seq": renamed_entry["authored_edit_seq"],
            },
        },
    )
    assert added.status_code == 201, added.text
    reopened = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert reopened["title"] == "Workshop"
    assert reopened["availability"] == "available"
    assert reopened["authored_state_sha256"] == added.json()["state_sha256"]
    assert reopened["source_snapshot_id"] == entry["source_snapshot_id"]
    assert reopened["source_snapshot_sha256"] == entry["source_snapshot_sha256"]


def test_starter_does_not_replace_a_personal_saved_world(objects_api, repository):
    personal, _version, _style = _create_entry(objects_api, repository)
    response = objects_api.post("/world-entries/starter", {"title": "Replacement"})
    assert response.status_code == 409
    assert objects_api.get("/world-entries").json() == [personal]


def test_authored_entry_refuses_a_spoofed_starter_snapshot_without_changing_its_cursor(
    objects_api, repository
):
    entry = _create_starter(objects_api)
    structures = WorldStructureRepository(
        repository.connection, repository.workspace_id, world_id=entry["world_id"]
    )
    current = structures.current()
    assert current is not None
    original = authored_starter_candidate(entry["world_id"])
    topology = deepcopy(original.topology)
    topology["elements"][0]["module"]["key"] = "region.spoofed-ground"
    candidate = replace(original, topology=topology)
    preview = structures.preview(candidate, proposed_by=objects_api.actor)
    snapshot = structures.apply(
        preview.preview_id,
        base_snapshot_id=current.snapshot_id,
        base_graph_sha256=current.candidate.graph_sha256,
        base_reconstruction_sha256=current.candidate.reconstruction_sha256,
        committed_by=objects_api.actor,
    )
    alternate = WorldObjectRepository(
        repository.connection, repository.workspace_id, world_id=entry["world_id"]
    ).create_version(
        source_snapshot_id=snapshot.snapshot_id,
        title="Wrong origin",
        style_version_id=uuid.UUID(entry["style_version_id"]),
        created_by=objects_api.actor,
    )
    repository.connection.commit()

    refused = objects_api.client.put(
        f"/world-entries/{entry['entry_id']}",
        headers=objects_api.headers,
        json={
            "base_revision": entry["revision"],
            "authored_version_id": str(alternate.version_id),
            "expected_authored_state_sha256": alternate.state_sha256,
            "expected_authored_edit_seq": alternate.edit_seq,
            "style_version_id": entry["style_version_id"],
        },
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "invalid_saved_world_entry"
    unchanged = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert unchanged["authored_version_id"] == entry["authored_version_id"]
    assert unchanged["revision"] == entry["revision"]


def test_entry_reopens_exact_versions_and_rejects_stale_save(objects_api, repository):
    entry, version, style = _create_entry(objects_api, repository)
    assert objects_api.get("/world-entries").json() == [entry]
    assert entry["authored_version_id"] == version["version_id"]
    assert entry["style_version_id"] == str(style.version_id)
    assert entry["availability"] == "available"

    update = {
        "base_revision": entry["revision"],
        "authored_version_id": version["version_id"],
        "expected_authored_state_sha256": version["state_sha256"],
        "expected_authored_edit_seq": version["edit_seq"],
        "style_version_id": str(style.version_id),
    }
    path = f"/world-entries/{entry['entry_id']}"
    first = objects_api.client.put(path, headers=objects_api.headers, json=update)
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == entry["revision"] + 1
    stale = objects_api.client.put(path, headers=objects_api.headers, json=update)
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_saved_world_entry"


def test_authored_edit_cursor_must_advance_before_reopen(objects_api, repository):
    entry, version, style = _create_entry(objects_api, repository)
    changed = objects_api.add(version)
    assert changed.status_code == 201, changed.text

    drifted = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert drifted["availability"] == "unavailable"
    assert drifted["unavailable_reason"] == "authored_version_changed"
    assert drifted["authored_state_sha256"] == version["state_sha256"]

    advanced = objects_api.client.put(
        f"/world-entries/{entry['entry_id']}",
        headers=objects_api.headers,
        json={
            "base_revision": entry["revision"],
            "authored_version_id": version["version_id"],
            "expected_authored_state_sha256": changed.json()["state_sha256"],
            "expected_authored_edit_seq": changed.json()["edit_seq"],
            "style_version_id": str(style.version_id),
        },
    )
    assert advanced.status_code == 200, advanced.text
    assert advanced.json()["availability"] == "available"
    assert advanced.json()["authored_state_sha256"] == changed.json()["state_sha256"]
    assert advanced.json()["authored_edit_seq"] == changed.json()["edit_seq"]


def test_entry_refuses_to_adopt_a_branch_state_newer_than_the_one_observed(objects_api, repository):
    entry, version, style = _create_entry(objects_api, repository)
    first = objects_api.add(version).json()
    observed = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert observed["current_authored_state_sha256"] == first["state_sha256"]

    second = objects_api.post(
        f"/world/versions/{version['version_id']}/objects/object:lantern/move",
        {
            "base_state_sha256": first["state_sha256"],
            "transform": {
                "x_mm": 2_400,
                "y_mm": 0,
                "z_mm": -450,
                "yaw_microradians": 785_398,
                "scale_milli": 1_000,
            },
        },
    )
    assert second.status_code == 200, second.text
    adoption = objects_api.client.put(
        f"/world-entries/{entry['entry_id']}",
        headers=objects_api.headers,
        json={
            "base_revision": entry["revision"],
            "authored_version_id": version["version_id"],
            "expected_authored_state_sha256": observed["current_authored_state_sha256"],
            "expected_authored_edit_seq": observed["current_authored_edit_seq"],
            "style_version_id": str(style.version_id),
        },
    )
    assert adoption.status_code == 409, adoption.text
    assert adoption.json()["code"] == "stale_saved_world_entry"
    unchanged = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert unchanged["authored_state_sha256"] == version["state_sha256"]


def test_bound_object_write_advances_entry_atomically_and_conflict_rolls_back(
    objects_api, repository
):
    entry, version, _style = _create_entry(objects_api, repository)
    binding = {
        "entry_id": entry["entry_id"],
        "base_revision": entry["revision"],
        "authored_state_sha256": entry["authored_state_sha256"],
        "authored_edit_seq": entry["authored_edit_seq"],
    }
    added = objects_api.add(version, saved_entry=binding)
    assert added.status_code == 201, added.text
    advanced = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert advanced["revision"] == entry["revision"] + 1
    assert advanced["authored_state_sha256"] == added.json()["state_sha256"]
    assert advanced["authored_edit_seq"] == added.json()["edit_seq"]

    stale = objects_api.post(
        f"/world/versions/{version['version_id']}/objects/object:lantern/move",
        {
            "base_state_sha256": added.json()["state_sha256"],
            "transform": {
                "x_mm": 9_000,
                "y_mm": 0,
                "z_mm": -450,
                "yaw_microradians": 785_398,
                "scale_milli": 1_000,
            },
            "saved_entry": binding,
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_saved_world_entry"
    reread = objects_api.get(f"/world/versions/{version['version_id']}").json()
    assert reread["state_sha256"] == added.json()["state_sha256"]
    assert reread["objects"][0]["transform"]["x_mm"] == 1_200


def test_bound_write_cannot_skip_reconciliation_after_an_unbound_branch_edit(
    objects_api, repository
):
    entry, version, _style = _create_entry(objects_api, repository)
    changed = objects_api.add(version)
    assert changed.status_code == 201, changed.text
    branch = changed.json()
    drifted = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert drifted["unavailable_reason"] == "authored_version_changed"

    bypass = objects_api.post(
        f"/world/versions/{version['version_id']}/objects/object:lantern/move",
        {
            "base_state_sha256": branch["state_sha256"],
            "transform": {
                "x_mm": 9_000,
                "y_mm": 0,
                "z_mm": -450,
                "yaw_microradians": 785_398,
                "scale_milli": 1_000,
            },
            "saved_entry": {
                "entry_id": entry["entry_id"],
                "base_revision": entry["revision"],
                "authored_state_sha256": entry["authored_state_sha256"],
                "authored_edit_seq": entry["authored_edit_seq"],
            },
        },
    )
    assert bypass.status_code == 409, bypass.text
    assert bypass.json()["code"] == "stale_saved_world_entry"

    unchanged_branch = objects_api.get(f"/world/versions/{version['version_id']}").json()
    unchanged_entry = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert unchanged_branch["state_sha256"] == branch["state_sha256"]
    assert unchanged_branch["edit_seq"] == branch["edit_seq"] == 1
    assert unchanged_branch["objects"][0]["transform"]["x_mm"] == 1_200
    assert unchanged_entry["authored_state_sha256"] == entry["authored_state_sha256"]
    assert unchanged_entry["availability"] == "unavailable"


def test_two_bound_writers_race_on_the_entry_lock_and_only_one_edit_commits(
    objects_api, repository
):
    entry, version, _style = _create_entry(objects_api, repository)
    binding = {
        "entry_id": entry["entry_id"],
        "base_revision": entry["revision"],
        "authored_state_sha256": entry["authored_state_sha256"],
        "authored_edit_seq": entry["authored_edit_seq"],
    }

    def write(object_id: str):
        return objects_api.add(version, object_id=object_id, saved_entry=binding)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(write, ("object:one", "object:two")))
    assert sorted(response.status_code for response in responses) == [201, 409]
    refused = next(response for response in responses if response.status_code == 409)
    assert refused.json()["code"] == "stale_saved_world_entry"

    saved = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    branch = objects_api.get(f"/world/versions/{version['version_id']}").json()
    assert saved["availability"] == "available"
    assert saved["authored_state_sha256"] == branch["state_sha256"]
    assert saved["authored_edit_seq"] == branch["edit_seq"] == 1
    assert len(branch["objects"]) == 1


def test_bound_and_unbound_edits_take_workspace_before_branch_lock(
    objects_api, repository, spine_schema
):
    entry, version, _style = _create_entry(objects_api, repository)
    first_binding = {
        "entry_id": entry["entry_id"],
        "base_revision": entry["revision"],
        "authored_state_sha256": entry["authored_state_sha256"],
        "authored_edit_seq": entry["authored_edit_seq"],
    }
    first = objects_api.add(version, saved_entry=first_binding)
    assert first.status_code == 201, first.text
    base = first.json()
    saved = objects_api.get(f"/world-entries/{entry['entry_id']}").json()

    _psycopg, scratch = spine_schema
    from tests_support_api import scratch_database

    database = scratch_database(scratch)
    backend_pids: Queue[int] = Queue()
    outcomes: Queue[str] = Queue()

    def bound_writer() -> None:
        with database.session(repository.workspace_id) as connection:
            backend_pids.put(connection.info.backend_pid)
            entries = SavedWorldEntryRepository(connection, repository.workspace_id)
            objects = WorldObjectRepository(connection, repository.workspace_id)
            try:
                with connection.transaction():
                    entries.lock_authored_advance_base(
                        uuid.UUID(saved["entry_id"]),
                        base_revision=saved["revision"],
                        world_id=saved["world_id"],
                        authored_version_id=uuid.UUID(saved["authored_version_id"]),
                        authored_state_sha256=saved["authored_state_sha256"],
                        authored_edit_seq=saved["authored_edit_seq"],
                        mutation_base_state_sha256=base["state_sha256"],
                    )
                    changed = objects.move_object(
                        uuid.UUID(base["version_id"]),
                        "object:lantern",
                        Transform(9_000, 0, -450, 785_398, 1_000),
                        base_state_sha256=base["state_sha256"],
                        actor=objects_api.actor,
                    )
                    entries.advance_authored_locked(
                        uuid.UUID(saved["entry_id"]),
                        base_revision=saved["revision"],
                        world_id=saved["world_id"],
                        authored_version_id=changed.version_id,
                        result_state_sha256=changed.state_sha256,
                        result_edit_seq=changed.edit_seq,
                    )
                outcomes.put("committed")
            except StaleSavedWorldEntry:
                outcomes.put("stale")
            except psycopg.errors.DeadlockDetected:
                outcomes.put("deadlock")

    with ExitStack() as stack:
        executor = stack.enter_context(ThreadPoolExecutor(max_workers=1))
        unbound_connection = stack.enter_context(database.session(repository.workspace_id))
        with unbound_connection.transaction():
            unbound_connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s::text,880024))",
                (repository.workspace_id,),
            )
            future = executor.submit(bound_writer)
            bound_pid = backend_pids.get(timeout=5)
            deadline = monotonic() + 5
            while monotonic() < deadline:
                wait = unbound_connection.execute(
                    "select wait_event from pg_stat_activity where pid=%s",
                    (bound_pid,),
                ).fetchone()
                if wait is not None and str(wait["wait_event"]).lower() == "advisory":
                    break
                sleep(0.01)
            else:
                raise AssertionError("bound writer did not wait on the workspace advisory lock")

            unbound = WorldObjectRepository(
                unbound_connection, repository.workspace_id
            ).move_object(
                uuid.UUID(base["version_id"]),
                "object:lantern",
                Transform(2_400, 0, -450, 785_398, 1_000),
                base_state_sha256=base["state_sha256"],
                actor=objects_api.actor,
            )
        future.result(timeout=5)

    assert outcomes.get(timeout=1) == "stale"
    branch = objects_api.get(f"/world/versions/{version['version_id']}").json()
    drifted = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert branch["state_sha256"] == unbound.state_sha256
    assert branch["objects"][0]["transform"]["x_mm"] == 2_400
    assert drifted["availability"] == "unavailable"


def test_foreign_entry_binding_rolls_back_the_authored_edit(objects_api, repository):
    _entry, version, _style = _create_entry(objects_api, repository)
    response = objects_api.add(
        version,
        saved_entry={
            "entry_id": str(uuid.uuid4()),
            "base_revision": 1,
            "authored_state_sha256": version["state_sha256"],
            "authored_edit_seq": version["edit_seq"],
        },
    )
    assert response.status_code == 404, response.text
    reread = objects_api.get(f"/world/versions/{version['version_id']}").json()
    assert reread["state_sha256"] == version["state_sha256"]
    assert reread["objects"] == []


def test_bound_style_write_and_entry_pointer_commit_or_rollback_together(objects_api, repository):
    entry, _version, _style = _create_entry(objects_api, repository)
    initial = objects_api.get("/world/styles/current").json()
    preview = objects_api.post(
        "/world/styles/previews",
        {
            "proposal_id": str(uuid.uuid4()),
            "origin": "settings",
            "origin_reference": "appearance-panel",
            "scope": {"kind": "global"},
            "base_style_version_id": initial["current"]["version_id"],
            "base_topology_digest": initial["current_topology_digest"],
            "profile": {
                "profile_id": "origin-landscape",
                "profile_version": 1,
                "parameters": {"vitality": 0.25},
            },
        },
    )
    assert preview.status_code == 201, preview.text
    binding = {
        "entry_id": entry["entry_id"],
        "base_revision": entry["revision"] + 1,
        "authored_state_sha256": entry["authored_state_sha256"],
        "authored_edit_seq": entry["authored_edit_seq"],
        "style_version_id": entry["style_version_id"],
    }
    refused = objects_api.post(
        f"/world/styles/previews/{preview.json()['preview_id']}/apply",
        {
            "base_style_version_id": initial["current"]["version_id"],
            "base_topology_digest": initial["current_topology_digest"],
            "saved_entry": binding,
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "stale_saved_world_entry"
    assert objects_api.get("/world/styles/current").json() == initial

    binding["base_revision"] = entry["revision"]
    applied = objects_api.post(
        f"/world/styles/previews/{preview.json()['preview_id']}/apply",
        {
            "base_style_version_id": initial["current"]["version_id"],
            "base_topology_digest": initial["current_topology_digest"],
            "saved_entry": binding,
        },
    )
    assert applied.status_code == 200, applied.text
    advanced = objects_api.get(f"/world-entries/{entry['entry_id']}").json()
    assert advanced["style_version_id"] == applied.json()["version_id"]
    assert advanced["revision"] == entry["revision"] + 1


def test_entry_is_not_an_existence_oracle_across_workspaces(objects_api, repository):
    entry, _version, _style = _create_entry(objects_api, repository)
    path = f"/world-entries/{entry['entry_id']}"
    response = objects_api.client.get(path, headers={"Authorization": f"Bearer {STRANGER_TOKEN}"})
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_reference"


def test_deleted_source_keeps_entry_but_blocks_opening(objects_api, repository):
    entry, _version, _style = _create_entry(objects_api, repository)
    repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person deleted their world"
    )
    repository.connection.commit()

    response = objects_api.get(f"/world-entries/{entry['entry_id']}")
    assert response.status_code == 200
    assert response.json()["availability"] == "unavailable"
    assert response.json()["unavailable_reason"] == "source_deleted"


def test_entry_rejects_cross_world_and_cross_workspace_versions(objects_api, repository):
    style = WorldStyleRepository(repository.connection, repository.workspace_id).current()
    version = objects_api.version("Existing in the default named world")
    response = objects_api.post(
        "/world-entries",
        {
            "world_id": "world:somewhere-else",
            "title": "Wrong world",
            "source_kind": "personal",
            "authored_version_id": version["version_id"],
            "style_version_id": str(style.version_id),
        },
    )
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_reference"

    stranger = objects_api.client.post(
        "/world-entries",
        headers={"Authorization": f"Bearer {STRANGER_TOKEN}"},
        json={
            "world_id": "atlas:default",
            "title": "Borrowed",
            "source_kind": "personal",
            "authored_version_id": version["version_id"],
            "style_version_id": str(style.version_id),
        },
    )
    assert stranger.status_code == 404
    assert stranger.json()["code"] == "unknown_reference"
