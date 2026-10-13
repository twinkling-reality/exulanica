"""Populated upgrade, source carry refusal and real restore retain bounded support authority."""

from __future__ import annotations

import dataclasses
import json
import re
import uuid
from pathlib import Path

import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.world import WorldObjectRepository
from exulanica.world.errors import InvalidThingPlacement
from exulanica.world.structure_repository import WorldStructureRepository
from exulanica.world.world_erasure import erase_world
from exulanica.world_package.projector import project_world_package

from test_purge import purged as imported_purged  # noqa: F401
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _through_a_restore
from test_society_made_world import made as imported_made  # noqa: F401
from test_support_placement_postgres import request_body, supported_world
from test_world_objects_postgres import apply_candidate

pytestmark = pytest.mark.postgres
MIGRATIONS = Path(__file__).resolve().parents[1] / "exulanica/migrations"


@pytest.fixture(name="made")
def _made(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(name="purged")
def _purged(request):
    return request.getfixturevalue("imported_purged")


def test_populated_upgrade_keeps_unbound_document_and_kind_origin_guards(made):
    api = made
    entry, prefix, scope, drawing, initial = supported_world(api)
    body = request_body(entry, drawing, initial)
    unbound = api.post(
        prefix + "/things" + scope,
        {
            "base_state_sha256": body["base_state_sha256"],
            "thing_id": body["thing_id"],
            "kind": body["kind"],
            "region_id": body["region_id"],
            "origin_role": body["origin_role"],
            "pose": {"x_mm": 55000, "y_mm": 150, "z_mm": -8000, "yaw_microradians": 0},
        },
    )
    assert unbound.status_code == 201, unbound.text
    before = unbound.json()
    connection = api.repository.connection
    # Exercise the forward DDL on populated pre-0206 storage in this private scratch schema.
    # No data row or history document is changed to manufacture a supported placement.
    connection.execute(
        "alter table world_alternate_thing "
        "drop constraint world_alternate_thing_support_source_fkey, "
        "drop constraint world_alternate_thing_support_shape, "
        "drop column support_snapshot_id, drop column support_receipt_sha256, "
        "drop column support_network_sha256, drop column support_surface_id"
    )
    connection.execute(
        "alter table world_alternate_version "
        "drop constraint world_alternate_version_support_source_key"
    )
    old = (MIGRATIONS / "0152_a_thing_is_placed_by_its_kind.sql").read_text()
    function = re.search(r"create function tg_world_thing_binding\(\).*?end \$fn\$;", old, re.S)
    assert function is not None
    connection.execute(function.group().replace("create function", "create or replace function", 1))
    connection.execute((MIGRATIONS / "0206_a_placed_thing_names_its_support.sql").read_text())
    assert api.get(prefix + scope).json() == before
    keys = (
        api.repository.workspace_id,
        entry["world_id"],
        entry["authored_version_id"],
        body["thing_id"],
    )
    with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
        connection.execute(
            "update world_alternate_thing set origin_role='personal' "
            "where workspace_id=%s and world_id=%s and version_id=%s and thing_id=%s",
            keys,
        )
    with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
        connection.execute(
            "update world_alternate_thing set support_surface_id='deck' "
            "where workspace_id=%s and world_id=%s and version_id=%s and thing_id=%s",
            keys,
        )
    with pytest.raises(psycopg.errors.ForeignKeyViolation), connection.transaction():
        connection.execute(
            "update world_alternate_thing set support_snapshot_id=%s,"
            "support_receipt_sha256=%s,support_network_sha256=%s,support_surface_id='deck' "
            "where workspace_id=%s and world_id=%s and version_id=%s and thing_id=%s",
            (
                uuid.uuid4(),
                bytes.fromhex(drawing["receipt_sha256"]),
                bytes.fromhex(drawing["support"]["network"]["document_sha256"]),
                *keys,
            ),
        )
    assert api.get(prefix + scope).json() == before


def test_changed_source_carry_refuses_without_losing_affinity_or_creating_version(made):
    api = made
    entry, prefix, scope, drawing, initial = supported_world(api)
    placed = api.post(prefix + "/things/on-support" + scope, request_body(entry, drawing, initial))
    assert placed.status_code == 201, placed.text
    with api.database.session(api.repository.workspace_id) as connection:
        repository = WorldObjectRepository(
            connection, api.repository.workspace_id, world_id=entry["world_id"], store=api.store
        )
        structures = WorldStructureRepository(
            connection, api.repository.workspace_id, world_id=entry["world_id"]
        )
        plan = repository.carry_plan(uuid.UUID(entry["authored_version_id"]))
        candidate = structures._candidate_for_snapshot(uuid.UUID(entry["source_snapshot_id"]))
        candidate = dataclasses.replace(
            candidate,
            reconstruction_sha256=("0" if candidate.reconstruction_sha256 != "0" * 64 else "1")
            * 64,
        )
        successor = apply_candidate(structures, candidate, actor=api.actor)
        versions = repository.versions()
        with pytest.raises(InvalidThingPlacement, match="support_source_changed"):
            repository.carry_version(
                plan, source_snapshot_id=successor.snapshot_id, created_by=api.actor
            )
        assert repository.versions() == versions
        assert repository.version(plan.version_id).things[0].support is not None


def test_actual_export_withholds_support_bearing_version_instead_of_dropping_binding(
    made, tmp_path
):
    api = made
    entry, prefix, scope, drawing, initial = supported_world(api)
    placed = api.post(prefix + "/things/on-support" + scope, request_body(entry, drawing, initial))
    assert placed.status_code == 201, placed.text
    output = tmp_path / "supported-export"
    with api.database.session(api.repository.workspace_id) as connection:
        project_world_package(
            connection,
            workspace_id=api.repository.workspace_id,
            actor=api.actor,
            output=output,
            private_key=Ed25519PrivateKey.generate(),
            world_id=entry["world_id"],
            extensions=("authored-world-1.1",),
            store=api.store,
        )
    documents = [json.loads(p.read_text()) for p in output.rglob("*.json")]
    # A withheld version is explicit; no package may recover its pose while dropping affinity.
    texts = [json.dumps(d) for d in documents]
    assert any("edit_kind_not_admitted" in text or "section_not_carried" in text for text in texts)
    assert not any("exulanica.placed-thing/v2" in text for text in texts)


def test_removed_supported_world_cannot_return_from_real_backup(made, purged, commands, tmp_path):
    api = made
    assert api.repository.workspace_id == purged.workspace_id
    entry, prefix, scope, drawing, initial = supported_world(api)
    placed = api.post(prefix + "/things/on-support" + scope, request_body(entry, drawing, initial))
    assert placed.status_code == 201, placed.text

    def current():
        return bool(
            purged.rows(
                "select 1 from world_alternate_thing where workspace_id=%s and world_id=%s "
                "and support_snapshot_id is not null",
                purged.workspace_id,
                entry["world_id"],
            )
        )

    def remove():
        with purged.database().session(purged.workspace_id) as connection:
            erase_world(connection, purged.workspace_id, entry["world_id"], erased_by=api.actor)

    assert not _through_a_restore(purged, tmp_path, withdraw=remove, current=current)
    assert api.get(prefix + "/things/thing:supported-bench/support" + scope).status_code == 410
    assert (
        api.post(
            prefix + "/things/on-support" + scope, request_body(entry, drawing, initial)
        ).status_code
        == 410
    )
