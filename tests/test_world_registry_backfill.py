"""Migration 0099 over a schema that already holds worlds nobody registered.

A schema is migrated to the migration before 0099 and filled through the repositories that write
world rows without a registry: a personal world with a composed topology and a structural
snapshot, an authored starter committed by the starter composer, a world that holds only
interaction settings, a package export whose structure, style and interaction pointers are all
null (so no foreign key it had checked its world), a training dataset export whose ``world_id``
holds its dataset package id (0039), and a workspace already holding two personal-source worlds.
0099 then runs, as the bootstrap superuser the test servers use and as a table owner that is
neither superuser nor BYPASSRLS, under which a read through FORCE row-level security would see
nothing.

Every world is registered once with the kind its stored rows state and no dataset package is
registered as a world, every world table gains its key, FORCE row-level security is restored on
exactly the tables that had it, and a workspace over the count policy keeps its worlds and cannot
create another.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.db.session import Database
from exulanica.env import env_get
from exulanica.migrations import migrations
from exulanica.world import TopologyContract, WorldStyleRepository
from exulanica.world.interaction_repository import WorldInteractionPolicyRepository
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.starter import authored_starter_candidate
from exulanica.world.structure_repository import WorldStructureRepository
from exulanica.world.worlds import PERSONAL_SOURCE, WorldLimitReached, register_world
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

import pg_harness
from test_interaction_policy_postgres import apply_patch
from world_structure_fixtures import structural_candidate

pytestmark = pytest.mark.postgres

_OWNER = "exulanica_world_registry_backfill_owner"
_MIGRATION = "0099"


def _database(scratch: str) -> Database:
    base = env_get("TEST_DATABASE_URL")
    assert base is not None
    return Database(url=make_conninfo(base, options=f"-csearch_path={scratch},public"))


def _apply(structures: WorldStructureRepository, candidate, actor: uuid.UUID):
    preview = structures.preview(candidate, proposed_by=actor)
    return structures.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=actor,
    )


def _world_tables(admin, scratch: str) -> dict[str, bool]:
    rows = admin.execute(
        "select c.relname, c.relforcerowsecurity from pg_class c "
        "join pg_namespace n on n.oid=c.relnamespace "
        "where n.nspname=%s and c.relkind='r' and c.relname<>'world_identity' and exists ("
        "select 1 from pg_attribute a where a.attrelid=c.oid and a.attname='world_id' "
        "and a.attnum>0 and not a.attisdropped)",
        (scratch,),
    ).fetchall()
    return {name: forced for name, forced in rows}


@pytest.mark.parametrize("owner", ["bootstrap superuser", "non-superuser owner"])
def test_0099_registers_every_world_a_populated_schema_held(owner, spine_schema, monkeypatch):
    owned = owner == "non-superuser owner"
    everything = list(migrations())
    by_version = {migration.version: migration for migration in everything}
    actor = uuid.uuid4()
    personal, crowded, settings_only = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    starter_world = "world:authored:backfill-starter"
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness, "migrations", lambda: iter(m for m in everything if m.version < _MIGRATION)
        )
        with pg_harness.migrated_schema() as (_psycopg, admin):
            scratch = admin.execute("select current_schema()").fetchone()[0]
            database = _database(scratch)

            # A personal world: a composed topology, a structural snapshot and a version.
            with database.session(personal) as connection:
                WorldStyleRepository(
                    connection, personal, world_id="atlas:default"
                ).register_topology(
                    TopologyContract("personal-topology", ("region-a",), world_id="atlas:default")
                )
                structures = WorldStructureRepository(
                    connection, personal, world_id="atlas:default"
                )
                snapshot = _apply(structures, structural_candidate(), actor)
                WorldObjectRepository(
                    connection, personal, world_id="atlas:default"
                ).create_version(
                    source_snapshot_id=snapshot.snapshot_id, title="Mine", created_by=actor
                )
                # An authored starter in the same workspace, committed by the starter composer.
                _apply(
                    WorldStructureRepository(connection, personal, world_id=starter_world),
                    authored_starter_candidate(starter_world),
                    actor,
                )
                WorldObjectRepository(connection, personal, world_id=starter_world).create_version(
                    source_snapshot_id=WorldStructureRepository(
                        connection, personal, world_id=starter_world
                    )
                    .current()
                    .snapshot_id,
                    title="My world",
                    style_version_id=WorldStyleRepository(
                        connection, personal, world_id=starter_world
                    )
                    .current()
                    .version_id,
                    created_by=actor,
                )

            # A world that holds interaction settings and nothing else, an export of a world
            # whose three pointers are all null, and a training dataset export, whose world_id
            # holds its dataset package id and names no world.
            with database.session(settings_only) as connection:
                apply_patch(
                    WorldInteractionPolicyRepository(
                        connection, settings_only, world_id="atlas:default"
                    ),
                    {"comfort.vignette": "strong"},
                )
                for package_id, profile, training_terms in (
                    ("world:export-only", "exulanica-wmp-1.0", None),
                    ("dataset:backfill-sample", "exulanica-wmp-training-1.1", Jsonb({})),
                ):
                    connection.execute(
                        "insert into world_package_export (export_id,workspace_id,world_id,"
                        "profile_version,merkle_root_sha256,manifest_sha256,signature_algorithm,"
                        "signing_public_key_sha256,export_policy,actor,training_terms) "
                        "values (%s,%s,%s,%s,%s,%s,'Ed25519',%s,'{}',%s,%s)",
                        (
                            uuid.uuid4(),
                            settings_only,
                            package_id,
                            profile,
                            "a" * 64,
                            "b" * 64,
                            "c" * 64,
                            actor,
                            training_terms,
                        ),
                    )

            # A workspace already holding two personal-source worlds.
            with database.session(crowded) as connection:
                for world in ("atlas:default", "world:personal:second"):
                    WorldStyleRepository(connection, crowded, world_id=world).register_topology(
                        TopologyContract(f"{world}-topology", ("region-a",), world_id=world)
                    )
            admin.commit()

            before = _world_tables(admin, scratch)
            assert len(before) > 30
            if owned:
                if not admin.execute(
                    "select 1 from pg_roles where rolname=%s", (_OWNER,)
                ).fetchone():
                    admin.execute(
                        sql.SQL("create role {} nologin nosuperuser nobypassrls").format(
                            sql.Identifier(_OWNER)
                        )
                    )
                admin.execute(
                    sql.SQL("grant usage, create on schema {} to {}").format(
                        sql.Identifier(scratch), sql.Identifier(_OWNER)
                    )
                )
                for table in before:
                    admin.execute(
                        sql.SQL("alter table {} owner to {}").format(
                            sql.Identifier(table), sql.Identifier(_OWNER)
                        )
                    )
                admin.commit()
                admin.execute(sql.SQL("set role {}").format(sql.Identifier(_OWNER)))
            admin.execute(by_version[_MIGRATION].sql)
            admin.execute("reset role")
            admin.commit()

            registered = {
                (row[0], row[1]): (row[2], row[3], row[4], row[5])
                for row in admin.execute(
                    "select workspace_id, world_id, kind, provenance->>'origin', "
                    "provenance->>'kind_from', created_by from world_identity"
                ).fetchall()
            }
            from_starter = "structural snapshot composer authored-starter-world"
            no_starter = "no snapshot committed by the authored starter composer"
            assert registered == {
                (personal, "atlas:default"): (PERSONAL_SOURCE, "backfill", no_starter, None),
                (personal, starter_world): ("authored-starter", "backfill", from_starter, None),
                (settings_only, "atlas:default"): (
                    PERSONAL_SOURCE,
                    "backfill",
                    no_starter,
                    None,
                ),
                (settings_only, "world:export-only"): (
                    PERSONAL_SOURCE,
                    "backfill",
                    no_starter,
                    None,
                ),
                (crowded, "atlas:default"): (PERSONAL_SOURCE, "backfill", no_starter, None),
                (crowded, "world:personal:second"): (
                    PERSONAL_SOURCE,
                    "backfill",
                    no_starter,
                    None,
                ),
            }

            # FORCE is back on exactly the tables that had it, and nowhere else.
            assert _world_tables(admin, scratch) == before
            assert admin.execute(
                "select column_default from information_schema.columns where table_schema=%s "
                "and table_name='world_topology_contract' and column_name='world_id'",
                (scratch,),
            ).fetchone() == (None,)
            keyed = {
                row[0]
                for row in admin.execute(
                    "select conrelid::regclass::text from pg_constraint "
                    "where contype='f' and confrelid='world_identity'::regclass"
                ).fetchall()
            }
            assert keyed == set(before)

            # The crowded workspace keeps both worlds and may not create a third.
            with database.session(crowded) as connection, pytest.raises(WorldLimitReached):
                register_world(
                    connection,
                    crowded,
                    world_id="world:personal:third",
                    kind=PERSONAL_SOURCE,
                    created_by=actor,
                    reason="over the limit",
                )
            admin.commit()
