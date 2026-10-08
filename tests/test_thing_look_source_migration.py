"""Migration 0167 over a database that already holds look choices.

A schema of this test's own is migrated with every migration below 0167 and given a placed thing
with an owner's choice of a shipped look for it, written as the code before 0167 wrote one (by key,
version and digest); then 0167 runs on it as deployed. What is held:

*   the stored choice reads as a shipped look (``source`` 'shipped'), and the new check that a
    choice names its look as its source does is added valid at once over it;
*   the version's looks read, as the code after 0167 reads it, wears that stored choice;
*   0167's index holds said events alone, by speaker and minute, and a speaker's lines are read
    through it rather than through the society's whole history.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.db.session import Database
from exulanica.env import env_get
from exulanica.migrations import migrations
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import ThingPlacement, named_kind, shipped_kind
from exulanica.world.society_repository import LINES_SAID_SQL
from exulanica.world.structure_repository import WorldStructureRepository
from exulanica.world.thing_looks import look_choices
from psycopg.conninfo import make_conninfo

import pg_harness
from world_structure_fixtures import structural_candidate
from world_support import registered_world

pytestmark = pytest.mark.postgres

_MIGRATION = "0167"
_INDEX = "world_society_event_said_by_speaker"


def test_0167_reads_stored_choices_as_shipped_and_indexes_said_events_by_speaker(monkeypatch):
    everything = list(migrations())
    by_version = {migration.version: migration for migration in everything}
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    well = shipped_kind(named_kind("well", 1))
    first = well.document["looks"][0]
    thing_id = uuid.uuid4()
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness, "migrations", lambda: iter(m for m in everything if m.version < _MIGRATION)
        )
        with pg_harness.migrated_schema() as (_psycopg, admin):
            scratch = admin.execute("select current_schema()").fetchone()[0]
            base = env_get("TEST_DATABASE_URL")
            assert base is not None
            database = Database(url=make_conninfo(base, options=f"-csearch_path={scratch},public"))
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
                objects.add_thing(
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
                # An owner's choice as the code before 0167 wrote one.
                connection.execute(
                    "insert into world_thing_look(workspace_id,world_id,version_id,thing_id,"
                    "placed_id,look,look_version,look_sha256,chosen_by,actor) "
                    "values (%s,%s,%s,%s,'well',%s,%s,%s,'owner',%s)",
                    (
                        workspace,
                        world,
                        version.version_id,
                        thing_id,
                        first["look"],
                        first["version"],
                        bytes.fromhex(first["sha256"]),
                        actor,
                    ),
                )
            admin.execute(by_version[_MIGRATION].sql)
            admin.commit()
            assert [row[0] for row in admin.execute("select source from world_thing_look")] == [
                "shipped"
            ]
            assert admin.execute(
                "select convalidated from pg_constraint "
                "where conname='world_thing_look_names_its_source'"
            ).fetchone() == (True,)
            with database.session(workspace) as connection:
                read = look_choices(connection, workspace, world, version.version_id)
            assert [(entry["thing_id"], entry["look"]) for entry in read["looks"]] == [
                (str(thing_id), {key: first[key] for key in ("look", "sha256", "version")})
            ]
            [definition] = admin.execute(
                "select indexdef from pg_indexes where indexname=%s", (_INDEX,)
            ).fetchone()
            assert "(workspace_id, society_id, subject_id, tick)" in definition
            assert definition.endswith("WHERE (event_kind = 'said'::text)")
            # A speaker's newest lines, as a card asks for them, read through the index.
            admin.execute("set local enable_seqscan = off")
            [[plan]] = admin.execute(
                "explain (format json) " + LINES_SAID_SQL,
                (workspace, uuid.uuid4(), uuid.uuid4(), 8),
            ).fetchall()
            assert _INDEX in json.dumps(plan)
            admin.rollback()
