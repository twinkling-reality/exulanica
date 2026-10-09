"""A workspace erases a creature drafted from a person's words, whole, and its own erasure reaches
every container its looks namespace holds (migration 0172).

What is shown, against PostgreSQL, as the deployed writer (the runtime role) unless said:

*   erasing a creature removes at once its kind, its drafted plan and recipe, every look drawn on
    that plan with their withdrawals, and nothing of another creature; the erasure names the kind
    by digest and the `creature` tombstone written beside it, and holds nothing a person wrote; a
    creature kept again after its erasure is erased again;
*   the rows go only through an erasure: the runtime role holds no delete, the table owner, whom
    row-level security does not hold, is refused by the append-only trigger, and only the definer
    owner may delete;
*   a plan another kind still names, and a recipe another plan still names, stay, and a recipe
    holds no digest of anyone's words;
*   a kind the workspace does not hold, another workspace's, or one somebody else drafted is
    refused by name, with no row deleted and no tombstone written; the same creature kept in
    another workspace is untouched; the erasure waits for the workspace's lock;
*   the erased looks' containers are enqueued on the creature tombstone and destroyed by the
    purge, which completes that tombstone; a container a look still held names (the same creature
    kept again, or another drafted to the same file) stays, its job waiting unclaimed, or skipped
    when the look arrives while the purger waits for the container's lock;
*   a creature tombstone reaches nothing a capture or workspace tombstone reaches: no capture,
    photograph, artefact or other creature, and no purge job but its creature's containers; a
    capture tombstone erases no creature, and an erasure naming one is refused by name; an erasure
    naming a tombstone not yet held is refused unless a restore's replay carries it, and then
    deletes and enqueues nothing;
*   a keep records its container and commits before its bytes, under the container's lock, so
    the purge of a container recorded just before a workspace tombstone waits for its bytes; a
    keep that dies after recording leaves a record the workspace's erasure reaches; containers
    kept before the inventory are recorded by the migration's own backfill; the table refuses a
    record once the workspace's tombstone is effective, whoever writes it; a keep asked inside an
    open transaction is refused before it records anything, and a look admitted on a plan erased
    meanwhile is refused by name;
*   a workspace tombstone erases every creature's rows at once, and enqueues every recorded
    container, an erased creature's and an admitted look's among them, as a look purge job; the
    purge role destroys them and marks them purged, and the tombstone's purge is complete only
    then: a worker without the looks namespaces, or a job marked done over an object still
    recorded unpurged, leaves it open, as it leaves a creature tombstone open by that job's own
    clause; a capture tombstone may not destroy a look's bytes, and the
    purge command's worker destroys them; a database without the look question claims everything
    else; once the tombstone is effective, keeping a creature is refused by name; a restore's
    replay naming looks' containers is refused before it begins when no looks store is given.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import threading
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.db.session import set_workspace
from exulanica.deletion import queue
from exulanica.deletion.restore import RestoreRefused, checkpoint, prepare_restore, replay
from exulanica.deletion.worker import HELD_BY_A_LIVE_RECORD, PurgeWorker
from exulanica.evidence.blob import BlobId
from exulanica.orchestration.restore import WRITERS
from exulanica.store.configured import local_content_stores
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import LocalWorkspaceStores, look_lock_key
from exulanica.things.authored import container_of
from exulanica.world.thing_store import ThingStore, ThingStoreRefused, admitted_look_by_digest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from conftest import scratch_role_database
from test_purge import _APP_PASSWORD, _APP_ROLE, _PURGE_PASSWORD, _PURGE_ROLE
from test_purge import purged as purged
from test_thing_store_admission import _imported
from test_thing_store_postgres import ACTOR, _admit_any, _counts, _creature

pytestmark = pytest.mark.postgres

MIGRATION = next(
    (Path(__file__).parents[1] / "exulanica" / "migrations").glob(
        "*_a_drafted_creature_is_erased_whole.sql"
    )
)

#: What a creature tombstone states as its reason: the erasure's own words, never a person's.
REASON = "a creature drafted from a person's words was erased"


def _runtime(spine_schema, workspace_id):
    return scratch_role_database(spine_schema[1], RUNTIME_ROLE).session(workspace_id)


@pytest.fixture
def provisioned(repository):
    provision_runtime_role(repository.connection)
    repository.connection.commit()
    return repository


def _store(connection, workspace_id, root: Path) -> ThingStore:
    return ThingStore(connection, workspace_id, LocalContentAddressedStore(root))


def _held(connection, table: str, column: str, value: str) -> bool:
    row = connection.execute(
        f"select exists (select 1 from {table} where {column} = %s) as held", (value,)
    ).fetchone()
    return bool(row["held"])


def _container(creature) -> str:
    return creature.sketch.document["container"]["sha256"]


def _owned(provisioned, workspace_id, sql: str, *params) -> list[dict]:
    """Rows the runtime role may not read (the purge queue), read as the owner."""
    owner = provisioned.connection
    set_workspace(owner, workspace_id)
    rows = owner.execute(sql, params).fetchall()
    owner.commit()
    return rows


def _creature_tombstones(connection) -> list[dict]:
    with connection.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            "select tombstone_id, requested_by, reason, capture_id, track_key, interval_ns, "
            "entity_id, assertion_id, blocklist_hash from tombstone "
            "where scope::text = 'creature' order by requested_at"
        ).fetchall()


def test_an_erasure_removes_the_creature_whole_and_nothing_else(
    provisioned, spine_schema, tmp_path
):
    erased, kept = _creature(), _creature("store dragon", "dragon")
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        store = _store(connection, workspace_id, tmp_path)
        store.keep_creature(erased, created_by=ACTOR)
        store.keep_creature(kept, created_by=ACTOR)
        store.withdraw_look(erased.sketch.look, 1, "no longer worn", withdrawn_by=ACTOR)
        before = _counts(connection)
        erasure = store.erase_creature(erased.kind.sha256, erased_by=ACTOR)
        assert _counts(connection) == {
            "body_recipe_version": before["body_recipe_version"] - 1,
            "body_plan_version": before["body_plan_version"] - 1,
            "thing_kind_version": before["thing_kind_version"] - 1,
            "look_version": before["look_version"] - 1,
            "look_withdrawal": 0,
        }
        for table, column, value in (
            ("thing_kind_version", "sha256", erased.kind.sha256),
            ("body_plan_version", "sha256", erased.plan.sha256),
            ("body_recipe_version", "sha256", erased.recipe_sha256),
            ("look_version", "sha256", erased.sketch.sha256),
        ):
            assert not _held(connection, table, column, value), table
        for table, column, value in (
            ("thing_kind_version", "sha256", kept.kind.sha256),
            ("body_plan_version", "sha256", kept.plan.sha256),
            ("body_recipe_version", "sha256", kept.recipe_sha256),
            ("look_version", "sha256", kept.sketch.sha256),
        ):
            assert _held(connection, table, column, value), table
        # The erasure names the kind by digest and its tombstone, and holds nothing a person wrote.
        row = connection.execute("select * from thing_erasure").fetchone()
        assert set(row) == {
            "workspace_id",
            "erasure_id",
            "sha256",
            "tombstone_id",
            "erased_by",
            "erased_at",
        }
        assert (row["erasure_id"], row["sha256"], row["erased_by"]) == (
            erasure,
            erased.kind.sha256,
            ACTOR,
        )
        # The tombstone beside it names who asked and why, and no subject of another scope.
        [tombstone] = _creature_tombstones(connection)
        assert tombstone["tombstone_id"] == row["tombstone_id"]
        assert (tombstone["requested_by"], tombstone["reason"]) == (ACTOR, REASON)
        assert not tombstone["blocklist_hash"]
        assert all(
            tombstone[column] is None
            for column in ("capture_id", "track_key", "interval_ns", "entity_id", "assertion_id")
        )
        # Its look's container is enqueued on that tombstone and nothing reads a look naming it.
        assert store.looks is not None and store.looks.exists(BlobId.from_hex(_container(erased)))
        assert store.look_by_digest(erased.sketch.sha256, include_withdrawn=True) is None
        assert admitted_look_by_digest(connection, workspace_id, erased.sketch.sha256) is None
        assert store.kind_by_digest(erased.kind.sha256) is None
        with pytest.raises(ThingStoreRefused) as refused:
            store.erase_creature(erased.kind.sha256, erased_by=ACTOR)
        assert refused.value.code == "kind_unknown"
    jobs = _owned(
        provisioned,
        workspace_id,
        "select tombstone_id, target_kind, target_ref, state from purge_job",
    )
    assert [(job["tombstone_id"], job["target_kind"], job["target_ref"]) for job in jobs] == [
        (row["tombstone_id"], "look", _container(erased))
    ]


def test_rows_go_only_through_an_erasure(provisioned, spine_schema, tmp_path):
    creature = _creature()
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        _store(connection, workspace_id, tmp_path).keep_creature(creature, created_by=ACTOR)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("delete from thing_kind_version")
    owner = provisioned.connection
    set_workspace(owner, workspace_id)
    owner.commit()
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        owner.execute("delete from look_version")
    owner.rollback()
    # The one exception: the definer owner, whose two erasing bodies are the only ones that run
    # as it and delete these tables.
    with owner.transaction():
        owner.execute("set local role exulanica_definer")
        deleted = owner.execute(
            "delete from thing_kind_version where sha256 = %s", (creature.kind.sha256,)
        ).rowcount
        assert deleted == 1
        raise psycopg.Rollback()
    with _runtime(spine_schema, workspace_id) as connection:
        assert _counts(connection)["thing_kind_version"] == 1


def test_a_plan_or_recipe_another_names_stays(provisioned, spine_schema, tmp_path):
    creature = _creature()
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        store = _store(connection, workspace_id, tmp_path)
        store.keep_creature(creature, created_by=ACTOR)
        # A second version of the kind on the same drafted plan.
        second = copy.deepcopy(dict(creature.kind.document))
        second["version"] = 2
        connection.execute(
            "insert into thing_kind_version (workspace_id,key,version,sha256,document,plan,"
            "plan_sha256,created_by) values (current_workspace(),%s,2,%s,%s,%s,%s,%s)",
            (
                creature.kind.kind,
                "e" * 64,
                Jsonb(second),
                creature.plan.name,
                creature.plan.sha256,
                ACTOR,
            ),
        )
        store.erase_creature(creature.kind.sha256, erased_by=ACTOR)
        assert _counts(connection)["thing_kind_version"] == 1
        assert _held(connection, "body_plan_version", "sha256", creature.plan.sha256)
        assert _held(connection, "look_version", "sha256", creature.sketch.sha256)
        # Another plan built from the same recipe keeps the recipe when the creature goes.
        other = {**creature.plan_document, "key": "other_plan", "version": 1}
        connection.execute(
            "insert into body_plan_version (workspace_id,key,version,sha256,document,"
            "recipe_sha256,created_by) values (current_workspace(),'other_plan',1,%s,%s,%s,%s)",
            ("f" * 64, Jsonb(other), creature.recipe_sha256, ACTOR),
        )
        store.erase_creature("e" * 64, erased_by=ACTOR)
        assert not _held(connection, "body_plan_version", "sha256", creature.plan.sha256)
        assert not _held(connection, "look_version", "sha256", creature.sketch.sha256)
        assert _held(connection, "body_recipe_version", "sha256", creature.recipe_sha256)


def test_a_recipe_two_creatures_share_holds_no_digest_of_their_words(
    provisioned, spine_schema, tmp_path
):
    # Two drafts of the same figures, colours and appearance under different labels: one recipe.
    first, second = _creature("store ten legs"), _creature("store many legs")
    assert first.recipe_sha256 == second.recipe_sha256
    assert first.kind.sha256 != second.kind.sha256
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        store = _store(connection, workspace_id, tmp_path)
        store.keep_creature(first, created_by=ACTOR)
        store.keep_creature(second, created_by=ACTOR)
        store.erase_creature(first.kind.sha256, erased_by=ACTOR)
        [recipe] = connection.execute("select * from body_recipe_version").fetchall()
        assert recipe["sha256"] == first.recipe_sha256
        assert recipe["words_sha256"] is None
        assert "words" not in str(recipe["document"])
        # The column is held empty: no writer may put a digest of anyone's words there again.
        with (
            pytest.raises(
                psycopg.errors.CheckViolation, match="body_recipe_version_holds_no_words"
            ),
            connection.transaction(),
        ):
            connection.execute(
                "insert into body_recipe_version (workspace_id, sha256, document, words_sha256, "
                "created_by) values (%s, %s, %s, %s, %s)",
                (
                    workspace_id,
                    "c" * 64,
                    Jsonb({"profile": "exulanica.body-recipe/v1"}),
                    "b" * 64,
                    ACTOR,
                ),
            )
        # The words' digest is held only in the kept creature's own plan and kind.
        [kind] = connection.execute("select document from thing_kind_version").fetchall()
        assert (
            kind["document"]["origin"]["by"]["words_sha256"]
            == (second.kind.document["origin"]["by"]["words_sha256"])
        )


def test_an_unknown_or_foreign_kind_is_refused_with_nothing_deleted(
    provisioned, spine_schema, tmp_path
):
    creature = _creature()
    mine, theirs = provisioned.workspace_id, uuid.uuid4()
    with _runtime(spine_schema, mine) as connection:
        _store(connection, mine, tmp_path / "mine").keep_creature(creature, created_by=ACTOR)
        before = _counts(connection)
    with _runtime(spine_schema, theirs) as connection:
        other = _store(connection, theirs, tmp_path / "theirs")
        for digest in (creature.kind.sha256, "d" * 64):
            with pytest.raises(ThingStoreRefused) as refused:
                other.erase_creature(digest, erased_by=ACTOR)
            assert refused.value.code == "kind_unknown"
        assert connection.execute("select count(*) as n from thing_erasure").fetchone()["n"] == 0
        assert not _creature_tombstones(connection)
    with _runtime(spine_schema, mine) as connection:
        assert _counts(connection) == before
        assert not _creature_tombstones(connection)


def test_the_same_creature_in_another_workspace_is_untouched(provisioned, spine_schema, tmp_path):
    creature = _creature()
    mine, theirs = provisioned.workspace_id, uuid.uuid4()
    for workspace in (mine, theirs):
        with _runtime(spine_schema, workspace) as connection:
            _store(connection, workspace, tmp_path / str(workspace)).keep_creature(
                creature, created_by=ACTOR
            )
    with _runtime(spine_schema, mine) as connection:
        _store(connection, mine, tmp_path / str(mine)).erase_creature(
            creature.kind.sha256, erased_by=ACTOR
        )
        assert set(_counts(connection).values()) == {0}
    with _runtime(spine_schema, theirs) as connection:
        store = _store(connection, theirs, tmp_path / str(theirs))
        assert store.kind_by_digest(creature.kind.sha256) is not None
        assert _counts(connection)["look_version"] == 1
        assert not _creature_tombstones(connection)
    jobs = _owned(provisioned, theirs, "select 1 from purge_job where workspace_id = %s", theirs)
    assert not jobs


def test_only_the_drafter_or_an_owner_erases_with_nothing_deleted_otherwise(
    provisioned, spine_schema, tmp_path
):
    creature = _creature()
    workspace = provisioned.workspace_id
    with _runtime(spine_schema, workspace) as connection:
        store = _store(connection, workspace, tmp_path / "looks")
        store.keep_creature(creature, created_by=ACTOR)
        before = _counts(connection)
        with pytest.raises(ThingStoreRefused) as refused:
            store.erase_creature(creature.kind.sha256, erased_by=uuid.uuid4())
        assert refused.value.code == "kind_not_yours"
        assert _counts(connection) == before
        assert connection.execute("select count(*) as n from thing_erasure").fetchone()["n"] == 0
        assert not _creature_tombstones(connection)
        # An owner of the workspace erases a creature somebody else drafted.
        store.erase_creature(creature.kind.sha256, erased_by=uuid.uuid4(), by_owner=True)
        assert not _held(connection, "thing_kind_version", "sha256", creature.kind.sha256)


def test_an_erasure_waits_for_the_workspace_s_lock(provisioned, spine_schema, tmp_path):
    """The erasure takes the workspace's lock before it reads the kind, as a keep does, so it
    waits for a transaction holding it rather than being refused at its tombstone (0137)."""
    creature = _creature()
    workspace = provisioned.workspace_id
    with _runtime(spine_schema, workspace) as connection:
        _store(connection, workspace, tmp_path).keep_creature(creature, created_by=ACTOR)
    with (
        _runtime(spine_schema, workspace) as holder,
        _runtime(spine_schema, workspace) as connection,
    ):
        with holder.transaction():
            holder.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s::text, 880024))",
                (str(workspace),),
            )
            connection.execute("set lock_timeout = '300ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                _store(connection, workspace, tmp_path).erase_creature(
                    creature.kind.sha256, erased_by=ACTOR
                )
        connection.execute("reset lock_timeout")
        assert _counts(connection)["thing_kind_version"] == 1
        assert not _creature_tombstones(connection)
        _store(connection, workspace, tmp_path).erase_creature(
            creature.kind.sha256, erased_by=ACTOR
        )
        assert _counts(connection)["thing_kind_version"] == 0


def test_a_capture_tombstone_erases_no_creature(looks):
    looks.store.keep_creature(_creature(), created_by=ACTOR)
    before = _counts(looks.connection)
    [capture] = looks.purged.rows("select capture_id from capture")
    looks.purged.tombstone_the_capture(capture["capture_id"])
    assert _counts(looks.connection) == before
    assert not looks.rows("select 1 from look_object where purged_at is not null")


def _write_erasure(looks: Looks, creature, tombstone_id: uuid.UUID) -> None:
    """An erasure row naming ``tombstone_id``, written as the runtime writes one."""
    with looks.connection.transaction():
        looks.connection.execute(
            "insert into thing_erasure (workspace_id, sha256, tombstone_id, erased_by) "
            "values (%s,%s,%s,%s)",
            (looks.workspace_id, creature.kind.sha256, tombstone_id, ACTOR),
        )


def test_an_erasure_names_a_creature_tombstone_of_its_own_workspace_or_none_held(looks):
    """The erasure's trigger reads the tombstone it names. A capture tombstone of this workspace is
    refused by name, with nothing deleted and nothing enqueued, and so is a tombstone not held while
    no restore replays. A tombstone not held while a restore's replay is under way, as when it
    carries an erasure before it replays the tombstone, deletes the creature and enqueues nothing:
    the replayed tombstone enqueues its own targets."""
    creature = _creature()
    looks.store.keep_creature(creature, created_by=ACTOR)
    before = _counts(looks.connection)
    assert set(before.values()) != {0}, "the positive control: the creature is kept"
    [capture] = looks.purged.rows("select capture_id from capture")
    capture_tombstone = looks.purged.tombstone_the_capture(capture["capture_id"])
    queued = looks.purged.rows("select purge_id from purge_job order by purge_id")
    with pytest.raises(psycopg.errors.CheckViolation, match="a creature tombstone of its own"):
        _write_erasure(looks, creature, capture_tombstone)
    assert _counts(looks.connection) == before
    assert not looks.rows("select 1 from thing_erasure")
    assert looks.purged.rows("select purge_id from purge_job order by purge_id") == queued

    with pytest.raises(psycopg.errors.CheckViolation, match="unless a restore's replay carries it"):
        _write_erasure(looks, creature, uuid.uuid4())
    assert _counts(looks.connection) == before
    assert not looks.rows("select 1 from thing_erasure")

    owner = looks.purged.repository.connection
    owner.execute(
        "insert into restore_control (checkpoint_id, checkpoint_sha256, state, restore_id) "
        "values (%s, %s, 'replaying', %s)",
        (uuid.uuid4(), "a" * 64, uuid.uuid4()),
    )
    owner.commit()
    try:
        _write_erasure(looks, creature, uuid.uuid4())
    finally:
        owner.execute("delete from restore_control")
        owner.commit()
    assert set(_counts(looks.connection).values()) == {0}
    assert looks.purged.rows("select purge_id from purge_job order by purge_id") == queued
    assert looks.in_namespace(_container(creature))


# -- the purge -------------------------------------------------------------------------------


class Looks:
    """Creatures kept and erased in the ``purged`` fixture's workspace, and its purge."""

    def __init__(self, purged, tmp_path: Path) -> None:
        self.purged = purged
        self.workspace_id = purged.workspace_id
        self.stores = LocalWorkspaceStores(tmp_path / "looks")
        self._sessions = contextlib.ExitStack()
        self.runtime = purged.database(role=_APP_ROLE, password=_APP_PASSWORD)
        self.connection = self._sessions.enter_context(self.runtime.session(self.workspace_id))
        self.store = ThingStore(
            self.connection, self.workspace_id, self.stores.for_workspace(self.workspace_id)
        )

    def close(self) -> None:
        self._sessions.close()

    def rows(self, sql: str, *params):
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(sql, params).fetchall()

    def in_namespace(self, digest: str) -> bool:
        return self.stores.for_workspace(self.workspace_id).exists(BlobId.from_hex(digest))

    def purge_worker(self, *, with_namespaces: bool = True) -> PurgeWorker:
        return PurgeWorker(
            self.purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD),
            self.purged.store,
            frozenset({self.workspace_id}),
            name="test-look-purge",
            look_stores=self.stores if with_namespaces else None,
        )

    def erase_workspace(self) -> uuid.UUID:
        return self.purged.repository.insert_tombstone(
            scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
        )

    def anchor(self, erasure: uuid.UUID) -> uuid.UUID:
        [row] = self.rows("select tombstone_id from thing_erasure where erasure_id = %s", erasure)
        return row["tombstone_id"]

    def jobs(self, tombstone: uuid.UUID) -> list[dict]:
        return self.purged.rows(
            "select target_kind, target_ref, state, last_error from purge_job "
            "where tombstone_id = %s order by target_ref",
            tombstone,
        )

    def completed(self, tombstone: uuid.UUID) -> bool:
        [row] = self.purged.rows(
            "select purge_completed_at from tombstone where tombstone_id = %s", tombstone
        )
        return row["purge_completed_at"] is not None


@pytest.fixture
def looks(purged, tmp_path):
    made = Looks(purged, tmp_path)
    yield made
    made.close()


def _another_look_on(looks: Looks, creature, payload: bytes) -> str:
    """A second look drawn on ``creature``'s drafted plan, with ``payload`` as its file, recorded
    and written as the store records and writes one. Its row is written as the owner: the look's
    reader is not what these tests are about."""
    digest = hashlib.sha256(payload).hexdigest()
    document = copy.deepcopy(dict(creature.sketch.document))
    document["look"] = f"{creature.sketch.look}-second"
    document["container"] = {**document["container"], "sha256": digest, "bytes": len(payload)}
    owner = looks.purged.repository.connection
    set_workspace(owner, looks.workspace_id)
    with owner.transaction():
        owner.execute(
            "insert into look_object (workspace_id, content_sha256, byte_size) values (%s,%s,%s)",
            (looks.workspace_id, digest, len(payload)),
        )
        owner.execute(
            "insert into look_version (workspace_id,key,version,sha256,document,plan_sha256,"
            "container_profile,admission,created_by) values (%s,%s,1,%s,%s,%s,%s,'{}',%s)",
            (
                looks.workspace_id,
                document["look"],
                sha256_of_canonical(document).hex(),
                Jsonb(document),
                creature.plan.sha256,
                "exulanica.static-glb/v1",
                ACTOR,
            ),
        )
    looks.stores.for_workspace(looks.workspace_id).put_bytes(payload)
    return digest


def _waiting_on(connection, key: str) -> bool:
    """Whether a session waits for the advisory lock on ``key``, polled for up to 30 seconds. A
    bigint key's lock names its high half as classid and its low half as objid."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        row = connection.execute(
            "select count(*) as n from pg_locks where locktype = 'advisory' and not granted "
            "and objsubid = 1 and ((classid::bigint << 32) | objid::bigint) "
            "= hashtextextended(%s, 0)",
            (key,),
        ).fetchone()
        if row["n"]:
            return True
        time.sleep(0.02)
    return False


def _drain_in_the_background(looks: Looks) -> tuple[threading.Thread, dict]:
    outcome: dict = {}

    def drain() -> None:
        try:
            outcome["outcome"] = looks.purge_worker().drain()
        except Exception as error:  # the assertion below names it
            outcome["error"] = error

    thread = threading.Thread(target=drain)
    thread.start()
    return thread, outcome


def test_an_erased_creature_s_containers_are_destroyed_by_the_purge(looks):
    erased, kept = _creature(), _creature("store dragon", "dragon")
    looks.store.keep_creature(erased, created_by=ACTOR)
    looks.store.keep_creature(kept, created_by=ACTOR)
    admitted = looks.store.admit_look(
        _imported(), container_of("blocky-traveller"), created_by=ACTOR, admit=_admit_any
    )
    # A second look drawn on the erased creature's drafted plan with a file of its own, as a
    # sculpted look is, goes with it.
    second = _another_look_on(looks, erased, b"another file drawn on the same drafted plan")
    tombstone = looks.anchor(looks.store.erase_creature(erased.kind.sha256, erased_by=ACTOR))
    assert [(job["target_kind"], job["target_ref"]) for job in looks.jobs(tombstone)] == sorted(
        [("look", _container(erased)), ("look", second)]
    )
    assert not queue.is_purge_complete(looks.connection, tombstone)

    outcome = looks.purge_worker().drain()
    assert outcome.failed == 0 and outcome.blocked is None, outcome
    assert [job["state"] for job in looks.jobs(tombstone)] == ["done", "done"]
    assert not looks.in_namespace(_container(erased)) and not looks.in_namespace(second)
    assert looks.in_namespace(_container(kept)) and looks.in_namespace(admitted.container_sha256)
    assert queue.is_purge_complete(looks.connection, tombstone)
    assert tombstone in outcome.completed_tombstones and looks.completed(tombstone)
    purged = looks.rows(
        "select content_sha256 from look_object where purged_at is not null order by content_sha256"
    )
    assert [row["content_sha256"] for row in purged] == sorted([_container(erased), second])


def test_a_creature_tombstone_reaches_nothing_a_capture_or_workspace_tombstone_reaches(looks):
    erased, kept = _creature(), _creature("store dragon", "dragon")
    looks.store.keep_creature(erased, created_by=ACTOR)
    looks.store.keep_creature(kept, created_by=ACTOR)
    [capture] = looks.purged.rows("select capture_id, blob_sha256 from capture")
    objects = looks.purged.rows(
        "select 'blob' as kind, encode(blob_sha256, 'hex') as ref, purged_at from blob "
        "union all select 'artifact', encode(content_sha256, 'hex'), purged_at from artifact "
        "where content_sha256 is not null order by 1, 2"
    )
    assert objects and all(row["purged_at"] is None for row in objects)
    tombstone = looks.anchor(looks.store.erase_creature(erased.kind.sha256, erased_by=ACTOR))
    [answers] = looks.purged.rows(
        "select tombstone_blocks_capture(%s, %s) as capture, "
        "tombstone_blocks_derivative(%s, %s) as derivative, "
        "(select deleted_at from capture where capture_id = %s) as deleted_at",
        looks.workspace_id,
        capture["capture_id"],
        looks.workspace_id,
        capture["blob_sha256"],
        capture["capture_id"],
    )
    assert answers == {"capture": False, "derivative": False, "deleted_at": None}
    # The queue holds the creature's container and nothing else, of any tombstone.
    assert [
        (row["tombstone_id"], row["target_kind"], row["target_ref"])
        for row in looks.purged.rows("select tombstone_id, target_kind, target_ref from purge_job")
    ] == [(tombstone, "look", _container(erased))]
    looks.purge_worker().drain()
    after = looks.purged.rows(
        "select 'blob' as kind, encode(blob_sha256, 'hex') as ref, purged_at from blob "
        "union all select 'artifact', encode(content_sha256, 'hex'), purged_at from artifact "
        "where content_sha256 is not null order by 1, 2"
    )
    assert after == objects
    assert all(
        looks.purged.store.exists(BlobId.from_hex(row["ref"]))
        for row in objects
        if row["kind"] == "blob"
    )
    assert looks.in_namespace(_container(kept))
    assert looks.store.kind_by_digest(kept.kind.sha256) is not None
    assert not looks.in_namespace(_container(erased))


def test_a_creature_kept_again_holds_its_file_until_it_is_erased_again(looks):
    creature = _creature()
    looks.store.keep_creature(creature, created_by=ACTOR)
    first = looks.anchor(looks.store.erase_creature(creature.kind.sha256, erased_by=ACTOR))
    # The same document kept again names the same file, so the first erasure's job waits,
    # unclaimed and spending no attempt, while the look kept again holds it.
    looks.store.keep_creature(creature, created_by=ACTOR)
    outcome = looks.purge_worker().drain()
    assert (outcome.destroyed, outcome.failed, outcome.exhausted) == (0, 0, 0), outcome
    assert [(job["state"], job["target_ref"]) for job in looks.jobs(first)] == [
        ("queued", _container(creature))
    ]
    assert looks.in_namespace(_container(creature))
    assert not queue.is_purge_complete(looks.connection, first)
    # Erased again, by a second erasure and tombstone of its own; then both purges complete.
    second = looks.anchor(looks.store.erase_creature(creature.kind.sha256, erased_by=ACTOR))
    assert second != first
    assert len(looks.rows("select 1 from thing_erasure")) == 2
    assert set(_counts(looks.connection).values()) == {0}
    outcome = looks.purge_worker().drain()
    assert outcome.failed == 0, outcome
    assert not looks.in_namespace(_container(creature))
    assert looks.completed(first) and looks.completed(second)
    assert [
        row["purged_at"] is not None for row in looks.rows("select purged_at from look_object")
    ] == [True]


def test_a_container_another_creature_still_names_is_not_enqueued(looks):
    # Two creatures drafted to the same figures draw the same sketch file.
    first, second = _creature("store ten legs"), _creature("store many legs")
    assert _container(first) == _container(second)
    looks.store.keep_creature(first, created_by=ACTOR)
    looks.store.keep_creature(second, created_by=ACTOR)
    tombstone = looks.anchor(looks.store.erase_creature(first.kind.sha256, erased_by=ACTOR))
    assert not looks.jobs(tombstone)
    looks.purge_worker().drain()
    assert looks.in_namespace(_container(second))
    assert queue.is_purge_complete(looks.connection, tombstone)
    assert looks.store.look_by_digest(second.sketch.sha256) is not None


def test_a_look_kept_while_the_purger_waits_is_skipped_and_comes_back(looks):
    """The purger claims a job while no look names its container, then waits for the container's
    lock, which a keep of the same file holds; when the keep commits, the purger finds the look
    and skips the job as held, and the bytes stay."""
    creature = _creature()
    looks.store.keep_creature(creature, created_by=ACTOR)
    tombstone = looks.anchor(looks.store.erase_creature(creature.kind.sha256, erased_by=ACTOR))
    key = look_lock_key(looks.workspace_id, _container(creature))
    looks.connection.execute("select pg_advisory_lock(hashtextextended(%s, 0))", (key,))
    try:
        thread, outcome = _drain_in_the_background(looks)
        assert _waiting_on(looks.purged.repository.connection, key), outcome
        # The same session holds the container's lock, so the keep takes it again and commits.
        looks.store.keep_creature(creature, created_by=ACTOR)
    finally:
        looks.connection.execute("select pg_advisory_unlock(hashtextextended(%s, 0))", (key,))
    thread.join(timeout=30)
    assert "error" not in outcome, outcome
    assert outcome["outcome"].skipped == 1, outcome
    assert [(job["state"], job["last_error"]) for job in looks.jobs(tombstone)] == [
        ("skipped", HELD_BY_A_LIVE_RECORD)
    ]
    assert looks.in_namespace(_container(creature))
    assert not queue.is_purge_complete(looks.connection, tombstone)


def test_a_container_recorded_before_a_tombstone_is_destroyed_after_its_bytes_are_written(looks):
    """A keep records its container and commits before it writes the bytes, holding the
    container's lock; a workspace tombstone between the two enqueues the record, and its purge
    waits for the lock, so it destroys the bytes once they are written, never before."""
    creature = _creature()
    container = _container(creature)
    key = look_lock_key(looks.workspace_id, container)
    looks.connection.execute("select pg_advisory_lock(hashtextextended(%s, 0))", (key,))
    try:
        with looks.connection.transaction():
            looks.connection.execute(
                "insert into look_object (workspace_id, content_sha256, byte_size) "
                "values (%s, %s, %s)",
                (looks.workspace_id, container, len(creature.sketch_container)),
            )
        tombstone = looks.erase_workspace()
        thread, outcome = _drain_in_the_background(looks)
        assert _waiting_on(looks.purged.repository.connection, key), outcome
        looks.stores.for_workspace(looks.workspace_id).put_bytes(creature.sketch_container)
    finally:
        looks.connection.execute("select pg_advisory_unlock(hashtextextended(%s, 0))", (key,))
    thread.join(timeout=30)
    assert "error" not in outcome, outcome
    assert not looks.in_namespace(container)
    assert queue.is_purge_complete(looks.connection, tombstone)


def test_a_keep_that_dies_after_recording_leaves_a_record_the_workspace_erasure_reaches(
    looks, monkeypatch
):
    creature = _creature()

    def dies(_container: bytes):
        raise OSError("the store went away")

    monkeypatch.setattr(looks.store.looks, "put_bytes", dies)
    with pytest.raises(OSError, match="went away"):
        looks.store.keep_creature(creature, created_by=ACTOR)
    monkeypatch.undo()
    assert set(_counts(looks.connection).values()) == {0}
    [record] = looks.rows("select content_sha256, purged_at from look_object")
    assert (record["content_sha256"], record["purged_at"]) == (_container(creature), None)
    # Kept again, the live record is the one already there.
    looks.store.keep_creature(creature, created_by=ACTOR)
    assert len(looks.rows("select 1 from look_object")) == 1
    tombstone = looks.erase_workspace()
    looks.purge_worker().drain()
    assert not looks.in_namespace(_container(creature))
    assert queue.is_purge_complete(looks.connection, tombstone)


def test_the_inventory_refuses_a_record_once_the_workspace_s_tombstone_is_effective(looks):
    """The store asks first; the table refuses any writer that does not. A record written as the
    runtime role is accepted before the workspace's tombstone and refused by name after it."""

    def record(digest: str) -> None:
        with looks.connection.transaction():
            looks.connection.execute(
                "insert into look_object (workspace_id, content_sha256, byte_size) "
                "values (%s, %s, %s)",
                (looks.workspace_id, digest, 1),
            )

    record("b" * 64)
    looks.erase_workspace()
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="look_object"):
        record("a" * 64)
    assert [
        row["content_sha256"] for row in looks.rows("select content_sha256 from look_object")
    ] == ["b" * 64]


def test_a_keep_refused_after_its_record_is_reached_by_the_workspace_s_erasure(looks, monkeypatch):
    creature = _creature()
    put_bytes = looks.store.looks.put_bytes

    def erased_meanwhile(container: bytes):
        looks.erase_workspace()
        return put_bytes(container)

    monkeypatch.setattr(looks.store.looks, "put_bytes", erased_meanwhile)
    with pytest.raises(ThingStoreRefused) as refused:
        looks.store.keep_creature(creature, created_by=ACTOR)
    assert refused.value.code == "workspace_erased"
    monkeypatch.undo()
    assert set(_counts(looks.connection).values()) == {0}
    looks.purge_worker().drain()
    assert not looks.in_namespace(_container(creature))


def test_containers_kept_before_the_inventory_are_recorded_by_the_migration_s_backfill(
    looks, monkeypatch
):
    """The migration records every container its looks name before its guard exists. Run here
    as the migration states it, over looks kept as the store kept them before the inventory: rows
    and bytes, and no record. Its table's FORCE is lifted around it too, as the migration runs it
    before the table's row-level security exists."""
    first, second = _creature(), _creature("store dragon", "dragon")
    monkeypatch.setattr(ThingStore, "_record_object", lambda self, container: None)
    looks.store.keep_creature(first, created_by=ACTOR)
    looks.store.keep_creature(second, created_by=ACTOR)
    monkeypatch.undo()
    assert not looks.rows("select 1 from look_object")
    text = MIGRATION.read_text(encoding="utf-8")
    # The backfill's own statements: the row-security lift around its insert, not the recipe's.
    insert = text.index(
        "insert into look_object (workspace_id, content_sha256, byte_size, recorded_at)"
    )
    backfill = text[
        text.rindex("set local row_security = off;", 0, insert) : text.index(
            "set local row_security = on;", insert
        )
        + len("set local row_security = on;")
    ]
    assert "insert into look_object" in backfill and "body_recipe_version" not in backfill
    owner = looks.purged.repository.connection
    with owner.transaction():
        set_workspace(owner, looks.workspace_id)
        owner.execute("alter table look_object no force row level security")
        owner.execute(backfill)
        owner.execute("alter table look_object force row level security")
    recorded = looks.rows(
        "select content_sha256, byte_size, purged_at from look_object order by content_sha256"
    )
    assert [
        (row["content_sha256"], row["byte_size"], row["purged_at"]) for row in recorded
    ] == sorted(
        (_container(creature), creature.sketch.document["container"]["bytes"], None)
        for creature in (first, second)
    )
    tombstone = looks.erase_workspace()
    looks.purge_worker().drain()
    assert not any(looks.in_namespace(_container(creature)) for creature in (first, second))
    assert queue.is_purge_complete(looks.connection, tombstone)


def test_a_workspace_tombstone_destroys_every_looks_object_an_erased_creature_s_too(looks):
    erased, kept = _creature(), _creature("store dragon", "dragon")
    looks.store.keep_creature(erased, created_by=ACTOR)
    looks.store.keep_creature(kept, created_by=ACTOR)
    admitted = looks.store.admit_look(
        _imported(), container_of("blocky-traveller"), created_by=ACTOR, admit=_admit_any
    )
    looks.store.erase_creature(erased.kind.sha256, erased_by=ACTOR)
    objects = sorted(
        [_container(creature) for creature in (erased, kept)] + [admitted.container_sha256]
    )
    assert [
        row["content_sha256"]
        for row in looks.rows("select content_sha256 from look_object order by content_sha256")
    ] == objects
    tombstone = looks.erase_workspace()
    # The workspace's erasure removes every creature's rows at once, the kept one's too.
    assert set(_counts(looks.connection).values()) == {0}
    jobs = looks.rows(
        "select target_ref from purge_job where tombstone_id = %s and target_kind = 'look' "
        "order by target_ref",
        tombstone,
    )
    assert [job["target_ref"] for job in jobs] == objects
    assert not queue.is_purge_complete(looks.connection, tombstone)

    outcome = looks.purge_worker().drain()
    assert outcome.failed == 0 and outcome.blocked is None, outcome
    done = looks.rows(
        "select state from purge_job where tombstone_id = %s and target_kind = 'look'", tombstone
    )
    assert [row["state"] for row in done] == ["done", "done", "done"]
    assert not any(looks.in_namespace(digest) for digest in objects)
    assert all(
        row["purged_at"] is not None for row in looks.rows("select purged_at from look_object")
    )
    assert queue.is_purge_complete(looks.connection, tombstone)
    assert tombstone in outcome.completed_tombstones

    # Once the workspace is erased, nothing more is kept in it: no record and no bytes.
    late = _creature("store sea serpent", "serpent")
    with pytest.raises(ThingStoreRefused) as refused:
        looks.store.keep_creature(late, created_by=ACTOR)
    assert refused.value.code == "workspace_erased"
    assert len(looks.rows("select 1 from look_object")) == 3
    assert not looks.in_namespace(_container(late))


def test_a_worker_without_the_looks_namespaces_leaves_the_tombstone_open(looks):
    looks.store.keep_creature(_creature(), created_by=ACTOR)
    tombstone = looks.erase_workspace()
    looks.purge_worker(with_namespaces=False).drain()
    assert not queue.is_purge_complete(looks.connection, tombstone)
    looks.purge_worker().drain()
    assert queue.is_purge_complete(looks.connection, tombstone)


def test_a_capture_tombstone_may_not_destroy_a_look(looks):
    creature = _creature()
    looks.store.keep_creature(creature, created_by=ACTOR)
    container = _container(creature)
    [capture] = looks.purged.rows("select capture_id from capture")
    capture_tombstone = looks.purged.tombstone_the_capture(capture["capture_id"])
    assert not looks.rows(
        "select 1 from purge_job where target_kind = 'look' and tombstone_id = %s",
        capture_tombstone,
    )
    # A look job forged under the capture tombstone is never claimed, and the bytes stay.
    looks.purged.rows(
        "insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref) "
        "values (%s, %s, 'look', %s) returning purge_id",
        capture_tombstone,
        looks.workspace_id,
        container,
    )
    looks.purge_worker().drain()
    [forged] = looks.purged.rows(
        "select state from purge_job where tombstone_id = %s and target_kind = 'look'",
        capture_tombstone,
    )
    assert forged["state"] == "queued"
    assert looks.in_namespace(container)
    purger = looks.purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD)
    with purger.session(looks.workspace_id) as connection:
        for tombstone, allowed in ((capture_tombstone, False), (looks.erase_workspace(), True)):
            row = connection.execute(
                "select look_purge_is_authorized(%s, %s, %s) as allowed",
                (looks.workspace_id, tombstone, container),
            ).fetchone()
            assert row["allowed"] is allowed
    assert looks.in_namespace(container)


def test_the_purge_command_s_worker_destroys_looks(looks, tmp_path):
    # exulanica-purge, restore replay and maintenance build their worker over every namespace.
    stores = local_content_stores(tmp_path / "data")
    creature = _creature()
    ThingStore(
        looks.connection, looks.workspace_id, stores.looks.for_workspace(looks.workspace_id)
    ).keep_creature(creature, created_by=ACTOR)
    tombstone = looks.erase_workspace()
    outcome = PurgeWorker.over(
        looks.purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD),
        stores,
        frozenset({looks.workspace_id}),
    ).drain()
    assert outcome.failed == 0, outcome
    held = stores.looks.for_workspace(looks.workspace_id)
    assert not held.exists(BlobId.from_hex(_container(creature)))
    assert queue.is_purge_complete(looks.connection, tombstone)


def test_a_database_without_the_look_question_claims_every_other_kind(looks):
    """A database one migration behind the code holds no look question; the claim leaves looks
    out rather than failing for every kind. The question is renamed inside a transaction that is
    rolled back."""
    [capture] = looks.purged.rows("select capture_id from capture")
    looks.purged.tombstone_the_capture(capture["capture_id"])
    owner = looks.purged.repository.connection
    with owner.transaction():
        owner.execute(
            "alter function look_purge_is_authorized(uuid, uuid, text) "
            "rename to look_purge_is_authorized_not_yet"
        )
        set_workspace(owner, looks.workspace_id)
        target = queue.claim_purge(owner, looks.workspace_id, queue.DESTROYABLE_KINDS)
        assert target is not None and target.target_kind != "look"
        raise psycopg.Rollback()


def test_a_looks_object_not_yet_purged_keeps_its_tombstone_open(looks):
    looks.store.keep_creature(_creature(), created_by=ACTOR)
    tombstone = looks.erase_workspace()
    # Everything else the tombstone asked for is destroyed; the look's job is then marked done
    # while its object is still recorded unpurged, as a worker that lost its write would leave it.
    looks.purge_worker(with_namespaces=False).drain()
    looks.purged.rows(
        "update purge_job set state = 'done', completed_at = now() "
        "where tombstone_id = %s and target_kind = 'look' returning purge_id",
        tombstone,
    )
    assert not queue.is_purge_complete(looks.connection, tombstone)


def test_a_creature_tombstone_whose_container_is_not_yet_purged_stays_open(looks):
    """A creature tombstone has no workspace-wide clause to fall back on: its one look job marked
    done over an object still recorded unpurged leaves it open by the job's own clause alone."""
    creature = _creature()
    looks.store.keep_creature(creature, created_by=ACTOR)
    tombstone = looks.anchor(looks.store.erase_creature(creature.kind.sha256, erased_by=ACTOR))
    [job] = looks.purged.rows(
        "update purge_job set state = 'done', completed_at = now() "
        "where tombstone_id = %s and target_kind = 'look' returning target_ref",
        tombstone,
    )
    assert job["target_ref"] == _container(creature)
    assert not queue.is_purge_complete(looks.connection, tombstone)


def test_a_keep_inside_an_open_transaction_records_nothing(looks):
    """Inside an open transaction the record would commit only with the rows, after the bytes, so
    the store refuses the keep before it records or writes anything; outside one it keeps."""
    creature = _creature()
    with looks.connection.transaction(), pytest.raises(ThingStoreRefused) as refused:
        looks.store.keep_creature(creature, created_by=ACTOR)
    assert refused.value.code == "keep_in_transaction"
    assert not looks.rows("select 1 from look_object")
    assert set(_counts(looks.connection).values()) == {0}
    assert not looks.in_namespace(_container(creature))
    looks.store.keep_creature(creature, created_by=ACTOR)
    assert looks.in_namespace(_container(creature))


def test_a_look_admitted_on_a_plan_erased_meanwhile_is_refused_by_name(looks, monkeypatch):
    """A look drawn on a drafted plan reads the plan before any lock; the creature's erasure may
    commit before the look's rows. The store reads the plan again under the workspace's lock and
    refuses by name, with nothing recorded and no row."""
    creature = _creature()
    looks.store.keep_creature(creature, created_by=ACTOR)
    document = copy.deepcopy(dict(creature.sketch.document))
    document["look"] = f"{creature.sketch.look}-again"
    keep = ThingStore._keep

    def erased_first(store, container, check, write):
        store.erase_creature(creature.kind.sha256, erased_by=ACTOR)
        return keep(store, container, check, write)

    monkeypatch.setattr(ThingStore, "_keep", erased_first)
    with pytest.raises(ThingStoreRefused) as refused:
        looks.store.admit_look(
            document, creature.sketch_container, created_by=ACTOR, admit=_admit_any
        )
    assert refused.value.code == "look_plan_gone"
    assert set(_counts(looks.connection).values()) == {0}
    recorded = looks.rows("select content_sha256 from look_object")
    assert [row["content_sha256"] for row in recorded] == [_container(creature)]


def test_a_replay_naming_looks_containers_without_their_stores_is_refused_before_it_begins(
    looks, tmp_path
):
    """A checkpoint naming a look's container is replayed only with the installation's stores,
    the one way to a workspace's looks namespace; without them it is refused before anything is
    replayed, as a checkpoint naming a bake is without the material stores."""
    looks.store.keep_creature(_creature(), created_by=ACTOR)
    looks.erase_workspace()
    looks.purge_worker().drain()
    owner = looks.purged.database()
    source, marker = tmp_path / "checkpoint.json", tmp_path / "restore.json"
    checkpoint(owner, source)
    prepare_restore(source, marker)
    with pytest.raises(RestoreRefused, match="no looks store"):
        replay(
            owner,
            looks.purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD),
            looks.purged.store,
            source,
            marker,
            writers=WRITERS,
        )
    # The checkpoint sealed the source; a replay that had begun would have marked it replaying.
    assert looks.purged.rows("select state, restore_id from restore_control") == [
        {"state": "sealed", "restore_id": None}
    ]
