"""A person's database holding a creature kept before the erasure migration is upgraded across it,
and the creature is then erased whole.

The migration empties the recipe row's words digest column and holds it empty, records every
container its looks name in the new inventory, and adds the erasure. Kept as the store kept a
creature before it (the recipe row carrying the digest of the words), through
``exulanica-local-db upgrade``, which backs the database up before and after and rehearses the
migration first:

*   the backup taken before the upgrade, whose recipe row holds the words' digest, restores;
*   the recipe keeps its document and the digest bound to it, and its row no longer holds the
    words' digest; the inventory holds the creature's container, recorded by the migration's
    backfill;
*   the creature is erased whole, and its container enqueued on the erasure's own tombstone;
*   a workspace erased before the migration loses its store rows, a withdrawn look's among them,
    its containers are enqueued on its tombstone and that tombstone's purge completion is cleared
    until the purge destroys them, while a workspace not erased keeps its creature.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.db.local.backup import verify_backup
from exulanica.db.roles import PURGE_ROLE
from exulanica.db.session import Database, set_workspace
from exulanica.deletion.worker import PurgeWorker
from exulanica.evidence.blob import BlobId
from exulanica.migrations import migrations
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import LocalWorkspaceStores
from exulanica.world.thing_store import ThingStore
from psycopg.types.json import Jsonb

from test_local_database_postgres import _init, _only_backup, cli, migration_files
from test_local_database_postgres import module_machine as module_machine
from test_local_database_postgres import servers as servers
from test_thing_store_postgres import ACTOR, TABLES, _creature

pytestmark = pytest.mark.postgres

#: The erasure's migration, by its name: its number is assigned at landing.
ERASURE = next(
    migration
    for migration in migrations()
    if migration.path.name.endswith("_a_drafted_creature_is_erased_whole.sql")
)


def _keep_as_before(connection, workspace_id: uuid.UUID, creature) -> None:
    """The four rows the store wrote before the erasure migration, the recipe's words digest
    among them, written as the owner in the workspace's session."""
    words = creature.kind.document["origin"]["by"]["words_sha256"]
    with connection.transaction():
        set_workspace(connection, workspace_id)
        connection.execute(
            "insert into body_recipe_version (workspace_id,sha256,document,words_sha256,"
            "created_by) values (%s,%s,%s,%s,%s)",
            (workspace_id, creature.recipe_sha256, Jsonb(dict(creature.recipe)), words, ACTOR),
        )
        connection.execute(
            "insert into body_plan_version (workspace_id,key,version,sha256,document,"
            "recipe_sha256,created_by) values (%s,%s,%s,%s,%s,%s,%s)",
            (
                workspace_id,
                creature.plan.key,
                creature.plan.version,
                creature.plan.sha256,
                Jsonb(dict(creature.plan_document)),
                creature.recipe_sha256,
                ACTOR,
            ),
        )
        connection.execute(
            "insert into look_version (workspace_id,key,version,sha256,document,plan_sha256,"
            "container_profile,admission,created_by) values (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                workspace_id,
                creature.sketch.look,
                creature.sketch.version,
                creature.sketch.sha256,
                Jsonb(dict(creature.sketch.document)),
                creature.plan.sha256,
                "exulanica.static-glb/v1",
                Jsonb({}),
                ACTOR,
            ),
        )
        connection.execute(
            "insert into thing_kind_version (workspace_id,key,version,sha256,document,plan,"
            "plan_sha256,created_by) values (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                workspace_id,
                creature.kind.kind,
                creature.kind.version,
                creature.kind.sha256,
                Jsonb(dict(creature.kind.document)),
                creature.plan.name,
                creature.plan.sha256,
                ACTOR,
            ),
        )


def test_a_creature_kept_before_the_erasure_migration_is_upgraded_and_erased_whole(
    servers, module_machine, tmp_path
):
    creature = _creature()
    words = creature.kind.document["origin"]["by"]["words_sha256"]
    assert words, "the positive control: the creature carries a digest of its words"
    container = creature.sketch.document["container"]
    workspace_id = uuid.uuid4()
    after = sum(1 for migration in migrations() if migration.version >= ERASURE.version)
    with migration_files(tmp_path / "older-code", drop_last=after) as versions:
        assert versions[-1] < ERASURE.version, versions[-1]
        database = _init(servers, tmp_path / "database")
        with database.connect(database.cluster.running_port()) as connection:
            _keep_as_before(connection, workspace_id, creature)
            [held] = connection.execute(
                "select words_sha256 from body_recipe_version where sha256 = %s",
                (creature.recipe_sha256,),
            ).fetchall()
            assert held["words_sha256"] == words

    upgraded = cli("upgrade", "--directory", database.root)
    assert upgraded.status == 0, upgraded.err
    before = _only_backup(database, "before-upgrade")
    assert before.migrations[-1] == versions[-1]
    assert before.row_counts["public.body_recipe_version"] == 1
    assert verify_backup(before) == before.row_counts

    with database.connect(database.cluster.running_port()) as connection:
        set_workspace(connection, workspace_id)
        [recipe] = connection.execute(
            "select sha256, document, words_sha256 from body_recipe_version"
        ).fetchall()
        assert recipe["words_sha256"] is None
        assert recipe["sha256"] == creature.recipe_sha256
        assert sha256_of_canonical(recipe["document"]).hex() == recipe["sha256"]
        assert words not in str(recipe["document"])
        recorded = connection.execute(
            "select content_sha256, byte_size, purged_at from look_object"
        ).fetchall()
        assert [tuple(row.values()) for row in recorded] == [
            (container["sha256"], container["bytes"], None)
        ]

        erasure = ThingStore(connection, workspace_id, None).erase_creature(
            creature.kind.sha256, erased_by=ACTOR
        )
        for table in TABLES:
            [row] = connection.execute(f"select count(*) as n from {table}").fetchall()
            assert row["n"] == 0, table
        jobs = connection.execute(
            "select pj.target_kind, pj.target_ref from purge_job pj "
            "join thing_erasure e on e.tombstone_id = pj.tombstone_id where e.erasure_id = %s",
            (erasure,),
        ).fetchall()
        assert [(job["target_kind"], job["target_ref"]) for job in jobs] == [
            ("look", container["sha256"])
        ]


def test_a_workspace_erased_before_the_migration_loses_its_store_rows_and_containers(
    servers, module_machine, tmp_path
):
    """A workspace tombstone written before this migration erased none of the store's rows. The
    migration erases them for every workspace with an effective workspace tombstone, a withdrawn
    look's withdrawal before its look, enqueues the containers their looks named on that tombstone
    and clears its purge completion, so it completes again only once the purge has destroyed them;
    a workspace not erased keeps its creature."""
    kept, erased = _creature(), _creature("store dragon", "dragon")
    kept_in, erased_in = uuid.uuid4(), uuid.uuid4()
    after = sum(1 for migration in migrations() if migration.version >= ERASURE.version)
    with migration_files(tmp_path / "older-code", drop_last=after):
        database = _init(servers, tmp_path / "database")
        with database.connect(database.cluster.running_port()) as connection:
            _keep_as_before(connection, kept_in, kept)
            _keep_as_before(connection, erased_in, erased)
            with connection.transaction():
                set_workspace(connection, erased_in)
                # A withdrawn look: its withdrawal names the look, so it must go first.
                connection.execute(
                    "insert into look_withdrawal (workspace_id,key,version,sha256,reason,"
                    "withdrawn_by) values (%s,%s,%s,%s,%s,%s)",
                    (
                        erased_in,
                        erased.sketch.look,
                        erased.sketch.version,
                        erased.sketch.sha256,
                        "no longer wanted",
                        ACTOR,
                    ),
                )
                [tombstone] = connection.execute(
                    "insert into tombstone (workspace_id, scope, requested_by, reason) "
                    "values (%s, 'workspace', %s, 'the person left') returning tombstone_id",
                    (erased_in, uuid.uuid4()),
                ).fetchall()
                # As the purge recorded it then: nothing it knew of was left.
                connection.execute(
                    "update tombstone set purge_completed_at = now() where tombstone_id = %s",
                    (tombstone["tombstone_id"],),
                )
            # The owner bypasses row security, so each count names its workspace.
            left = [
                connection.execute(
                    f"select count(*) as n from {table} where workspace_id = %s", (erased_in,)
                ).fetchall()[0]["n"]
                for table in ("look_version", "look_withdrawal")
            ]
            assert left == [1, 1], "the positive control: the old tombstone left the look rows"

    upgraded = cli("upgrade", "--directory", database.root)
    assert upgraded.status == 0, upgraded.err

    with database.connect(database.cluster.running_port()) as connection:
        for table in TABLES:
            [row] = connection.execute(
                f"select count(*) as n from {table} where workspace_id = %s", (erased_in,)
            ).fetchall()
            assert row["n"] == 0, table
        jobs = connection.execute(
            "select target_kind, target_ref, state from purge_job where tombstone_id = %s",
            (tombstone["tombstone_id"],),
        ).fetchall()
        assert [tuple(job.values()) for job in jobs] == [
            ("look", erased.sketch.document["container"]["sha256"], "queued")
        ]
        [marker] = connection.execute(
            "select purge_completed_at, tombstone_purge_is_complete(tombstone_id) as complete "
            "from tombstone where tombstone_id = %s",
            (tombstone["tombstone_id"],),
        ).fetchall()
        assert (marker["purge_completed_at"], marker["complete"]) == (None, False)
        counts = [
            connection.execute(
                f"select count(*) as n from {table} where workspace_id = %s", (kept_in,)
            ).fetchall()[0]["n"]
            for table in TABLES
        ]
        assert counts == [1, 1, 1, 1, 0]
        assert not connection.execute(
            "select 1 from purge_job where workspace_id = %s", (kept_in,)
        ).fetchall()

    # The purge command's role drains the job: the container's bytes, still in the namespace, are
    # destroyed, and the tombstone's purge is complete, and recorded so, once more.
    container = erased.sketch.document["container"]["sha256"]
    looks = LocalWorkspaceStores(tmp_path / "looks")
    looks.for_workspace(erased_in).put_bytes(erased.sketch_container)
    port = database.cluster.running_port()
    outcome = PurgeWorker(
        Database(database.role_url(port, PURGE_ROLE)),
        LocalContentAddressedStore(tmp_path / "blobs"),
        frozenset({erased_in}),
        look_stores=looks,
    ).drain()
    assert (outcome.destroyed, outcome.failed) == (1, 0), outcome
    assert not looks.for_workspace(erased_in).exists(BlobId.from_hex(container))
    with database.connect(port) as connection:
        [marker] = connection.execute(
            "select purge_completed_at, tombstone_purge_is_complete(tombstone_id) as complete "
            "from tombstone where tombstone_id = %s",
            (tombstone["tombstone_id"],),
        ).fetchall()
        assert marker["purge_completed_at"] is not None
        assert marker["complete"] is True
