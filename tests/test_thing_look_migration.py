"""Migration 0156 over a database that already holds placed things.

A schema of this test's own is migrated with every migration below 0156 and given a placed thing in
a registered world, through the application's own repositories; then 0156 runs on it as deployed.
What is held:

*   before 0156 no placed thing can name an unregistered world: a placed thing is keyed to its
    version and a version to the world registry, both keys valid;
*   so 0156's new key on ``world_alternate_thing`` validates against every stored row: it is added
    valid at once over the stored placed thing, which stays as it was;
*   0156's look table names the registry too.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.db.session import Database
from exulanica.env import env_get
from exulanica.migrations import migrations
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import ThingPlacement, named_kind
from exulanica.world.structure_repository import WorldStructureRepository
from psycopg.conninfo import make_conninfo

import pg_harness
from world_structure_fixtures import structural_candidate
from world_support import registered_world

pytestmark = pytest.mark.postgres

_MIGRATION = "0156"


def _keys(admin, table: str, parent: str = "world_identity") -> dict[str, bool]:
    """Each foreign key of ``table`` naming ``parent``, by name, and whether it is valid."""
    return {
        name: valid
        for name, valid in admin.execute(
            "select conname, convalidated from pg_constraint where contype='f' "
            "and conrelid=%s::regclass and confrelid=%s::regclass",
            (table, parent),
        ).fetchall()
    }


def test_0156_keys_stored_placed_things_to_the_registry_they_already_name(monkeypatch):
    everything = list(migrations())
    by_version = {migration.version: migration for migration in everything}
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness, "migrations", lambda: iter(m for m in everything if m.version < _MIGRATION)
        )
        with pg_harness.migrated_schema() as (_psycopg, admin):
            scratch = admin.execute("select current_schema()").fetchone()[0]
            base = env_get("TEST_DATABASE_URL")
            assert base is not None
            database = Database(url=make_conninfo(base, options=f"-csearch_path={scratch},public"))
            # Before 0156 a placed thing is keyed to its version and a version to the registry, both
            # valid, so every stored placed thing already names a registered world.
            assert list(_keys(admin, "world_alternate_version").values()) == [True]
            assert list(
                _keys(admin, "world_alternate_thing", "world_alternate_version").values()
            ) == [True]
            assert _keys(admin, "world_alternate_thing") == {}
            with database.session(workspace) as connection:
                world = registered_world(connection, workspace)
                structures = WorldStructureRepository(connection, workspace, world_id=world)
                preview = structures.preview(structural_candidate(), proposed_by=actor)
                snapshot = structures.apply(
                    preview.preview_id,
                    base_snapshot_id=preview.base_snapshot_id,
                    base_graph_sha256=preview.base_graph_sha256,
                    base_reconstruction_sha256=preview.base_reconstruction_sha256,
                    committed_by=actor,
                )
                objects = WorldObjectRepository(connection, workspace, world_id=world)
                version = objects.create_version(
                    source_snapshot_id=snapshot.snapshot_id, title="Well", created_by=actor
                )
                placed = objects.add_thing(
                    version.version_id,
                    ThingPlacement(
                        thing_id="well",
                        kind=named_kind("well", 1),
                        region_id="region-a",
                        transform=Transform(0, 0, 0, 0, 1_000),
                        origin=ObjectOrigin("authored", "fictional"),
                    ),
                    base_state_sha256=version.state_sha256,
                    actor=actor,
                )
                assert [thing.thing_id for thing in placed.things] == ["well"]
            admin.execute(by_version[_MIGRATION].sql)
            admin.commit()
            assert _keys(admin, "world_alternate_thing") == {
                "world_alternate_thing_world_fkey": True
            }
            assert list(_keys(admin, "world_thing_look").values()) == [True]
            assert (
                admin.execute(
                    "select count(*) from world_alternate_thing where thing_id='well'"
                ).fetchone()[0]
                == 1
            )
