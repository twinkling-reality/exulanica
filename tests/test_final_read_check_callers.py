"""The final read check, held at each entry point that decides whether something may leave.

Seven entry points answer, at one instant, whether bytes or a name may be handed over:
``final_check`` in :mod:`exulanica.graph.asset_read_policy` for an asset delivery,
``require_model_right`` before a photograph reaches a model, ``require_scene_training`` before a
trainer reads its photographs, ``require_artifact_training_right`` before a trained artefact is
read, ``released_place_names`` before a place's name goes to a model,
``MaterialRepository.read_bake`` before a material bake is served and ``BakedTileRepository.serve``
before a tile is. Each takes the same steps on the caller's connection. This file holds each entry
point to them from outside and names no helper, so it holds whichever way a module reaches the
steps:

* **statement order.** A read-only transaction opens, the global asset read lock (migration 0041)
  is taken, the evaluation instant is read in a separate statement, the entry point's own read
  runs, and the transaction commits before the entry point returns. Recorded on the caller's
  connection, statement by statement.
* **lock order against a writer, probed from a second connection.** While the read runs, the
  reader holds the asset read lock exclusively and no other advisory lock, inside a read-only
  transaction, and a guarded write from another connection is refused with 40001 rather than
  waiting. A write already in flight is waited for inside the read-only transaction, and it is
  seen once it commits, because the instant is read after the wait. Held locks are probed rather
  than inferred from outcomes: an outcome can come out right in the wrong order.
* **refusals.** A connection already inside a transaction is refused with ``ValueError``, in the
  entry point's own words, before the lock is asked for. A busy lock, when the caller's session
  will not wait for it, is refused with ``LockNotAvailable``, and the read-only transaction is
  rolled back with nothing read.

The material bake and the tile delivery read the evaluation instant and do not use it: the steps
are one sequence for every caller, and an unused instant costs one statement.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
import pytest
from exulanica.api.quotas import declare_tile_quota
from exulanica.consent.place_name_rights import released_place_names, withdraw_place_name
from exulanica.graph.asset_read_policy import final_check
from exulanica.ingest.model_rights import (
    ModelRightRefused,
    require_model_right,
    withdraw_model_right,
)
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.training_rights import (
    TrainingRightRefused,
    require_artifact_training_right,
    require_scene_training,
    withdraw_training_right,
)
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import tile_store
from exulanica.world.baked_tiles import BakedTileFaulted, BakedTileRepository
from exulanica.world.material_recipes import MaterialWithdrawn
from psycopg.pq import TransactionStatus

from conftest import photo_bytes
from test_corridor_tile_store import _record as record_tile
from test_material_recipes import _small as small_recipe
from test_material_recipes import materials as imported_materials  # noqa: F401
from test_personal_model_right import ACCOUNT, HOSTED, admit_personal, grant_all
from test_place_name_rights import MANIFEST, SEARCH, USES
from test_place_name_rights import _grant as grant_place_name
from test_place_name_rights import named as imported_named  # noqa: F401
from test_purge import purged as imported_purged  # noqa: F401
from test_scene_training_right import _grant as grant_training_right
from test_scene_training_right import _publish, _queue, _scene_of

pytestmark = pytest.mark.postgres

#: What the check sends from opening its transaction to its first read, in order.
OPENING = (
    "BEGIN",
    "set transaction read only",
    "select asset_read_lock()",
    "select statement_timestamp() as at",
)

#: The session lock timeout a caller sets when it will not wait for a busy lock. Any positive
#: value refuses here, because the holder keeps the lock until the refusal has been asserted.
WILL_NOT_WAIT = "10ms"

#: How long a probe waits for the other thread to reach the lock, as long as a loaded machine needs.
PATIENCE_SECONDS = 30


@pytest.fixture(name="named")
def _named_alias(request):
    return request.getfixturevalue("imported_named")


@pytest.fixture(name="purged")
def _purged_alias(request):
    return request.getfixturevalue("imported_purged")


@pytest.fixture(name="materials")
def _materials_alias(request):
    return request.getfixturevalue("imported_materials")


@pytest.fixture
def store(tmp_path) -> LocalContentAddressedStore:
    return LocalContentAddressedStore(tmp_path / "blobs")


class Recording:
    """A caller's connection that records each statement and transaction boundary it is asked for.

    ``before(recording, statement)`` runs on the calling thread before a statement is sent, so a
    probe can look at the server at exactly that point of the check. A transaction is recorded as
    ``BEGIN`` and ``COMMIT`` or ``ROLLBACK`` when it is the outermost one, and the probes confirm
    from the server's side that one is really open, and really read only, while the check reads.
    """

    def __init__(self, connection: psycopg.Connection, before=None) -> None:
        object.__setattr__(self, "_connection", connection)
        object.__setattr__(self, "statements", [])
        object.__setattr__(self, "before", before)

    def execute(self, query, params=None, **kwargs):
        text = " ".join(str(query).split())
        if self.before is not None:
            self.before(self, text)
        self.statements.append(text)
        return self._connection.execute(query, params, **kwargs)

    @contextmanager
    def transaction(self, *args, **kwargs) -> Iterator[object]:
        outermost = self._connection.info.transaction_status == TransactionStatus.IDLE
        self.statements.append("BEGIN" if outermost else "SAVEPOINT")
        ended = "ROLLBACK" if outermost else "ROLLBACK TO SAVEPOINT"
        try:
            with self._connection.transaction(*args, **kwargs) as transaction:
                yield transaction
            ended = "COMMIT" if outermost else "RELEASE SAVEPOINT"
        finally:
            self.statements.append(ended)

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __setattr__(self, name, value):
        setattr(self._connection, name, value)


@dataclass(frozen=True)
class Reader:
    """One entry point's final read check: how to call it, and what a writer does to its answer."""

    connection: psycopg.Connection
    #: The entry point on a connection, answered as an outcome word.
    read: Callable[[psycopg.Connection], str]
    #: A fragment of the one statement the entry point reads under the lock.
    marker: str
    #: The entry point's refusal of a connection already inside a transaction, verbatim.
    not_idle: str
    #: A guarded write, on another connection, that takes the permission away.
    withdraw: Callable[[IngestRepository], None]
    #: The outcome while the permission stands, and once the write has committed.
    permitted: str
    withdrawn: str


def _asset_delivery(request) -> Reader:
    repository = request.getfixturevalue("repository")
    subject = admit_personal(repository, request.getfixturevalue("store"), photo_bytes(), "a.jpg")

    def read(connection) -> str:
        with final_check(connection) as at:
            live = connection.execute(
                "select asset_capture_live(%s,%s,%s) as live",
                (repository.workspace_id, subject.capture_id, at),
            ).fetchone()["live"]
        return "live" if live else "gone"

    def withdraw(other: IngestRepository) -> None:
        other.insert_tombstone(scope="capture", capture_id=subject.capture_id, requested_by=ACCOUNT)

    return Reader(
        repository.connection,
        read,
        "asset_capture_live(",
        "final asset authorization requires an idle connection",
        withdraw,
        "live",
        "gone",
    )


def _model_right(request) -> Reader:
    repository = request.getfixturevalue("repository")
    subject = admit_personal(repository, request.getfixturevalue("store"), photo_bytes(), "m.jpg")
    rights = grant_all(subject, HOSTED)

    def read(connection) -> str:
        try:
            require_model_right(
                IngestRepository(connection, repository.workspace_id),
                subject.capture_id,
                subject.detection_id,
                HOSTED,
            )
        except ModelRightRefused as refused:
            return refused.reason
        return "permitted"

    def withdraw(other: IngestRepository) -> None:
        withdraw_model_right(other, right_id=rights[0].right_id, withdrawn_by=ACCOUNT)

    return Reader(
        repository.connection,
        read,
        "asset_observation_allows(",
        "a model hand-over is authorized only on an idle connection",
        withdraw,
        "permitted",
        "withdrawn",
    )


def _training(request, *, artefact: bool) -> Reader:
    repository = request.getfixturevalue("repository")
    subject = admit_personal(repository, request.getfixturevalue("store"), photo_bytes(), "t.jpg")
    right = grant_training_right(subject)
    job_id = _queue(subject)
    if artefact:
        artifact_id = _publish(repository, _scene_of(repository, job_id), "scene_splat_delivery")

    def read(connection) -> str:
        reader = IngestRepository(connection, repository.workspace_id)
        try:
            if artefact:
                require_artifact_training_right(reader, artifact_id)
            else:
                require_scene_training(reader, job_id)
        except TrainingRightRefused as refused:
            return refused.reason
        return "permitted"

    def withdraw(other: IngestRepository) -> None:
        withdraw_training_right(other, right_id=right.right_id, withdrawn_by=ACCOUNT)

    return Reader(
        repository.connection,
        read,
        "scene_training_artifact_withdrawn(" if artefact else "scene_training_job_refusal(",
        "a training run is authorized only on an idle connection",
        withdraw,
        "permitted",
        "withdrawn",
    )


def _place_name(request) -> Reader:
    named = request.getfixturevalue("named")
    repository, _, _, actor, entities = named
    grant_place_name(named, "embedding")

    def read(connection) -> str:
        released = released_place_names(
            connection, repository.workspace_id, SEARCH, uses=USES, manifest=MANIFEST
        )
        return "released" if entities["place"] in released else "withheld"

    def withdraw(other: IngestRepository) -> None:
        withdraw_place_name(
            other.connection,
            other.workspace_id,
            entity_id=entities["place"],
            role="embedding",
            actor=actor,
        )

    return Reader(
        repository.connection,
        read,
        "place_name_right_last_decisions(",
        "a place name is released only on an idle connection",
        withdraw,
        "released",
        "withheld",
    )


def _material_bake(request) -> Reader:
    materials = request.getfixturevalue("materials")
    recipe_id = materials.repository().create_recipe(small_recipe()).recipe_id
    materials.repository().request_bake(recipe_id)
    materials.record_synthetic_bake(recipe_id)

    def read(connection) -> str:
        try:
            materials.repository(connection).read_bake(recipe_id)
        except MaterialWithdrawn:
            return "withdrawn"
        return "permitted"

    def withdraw(other: IngestRepository) -> None:
        materials.repository(other.connection).withdraw_recipe(recipe_id)

    return Reader(
        materials.connection,
        read,
        "tombstone_blocks_material_bake(",
        "a final bake authorization needs an idle connection",
        withdraw,
        "permitted",
        "withdrawn",
    )


def _baked_tile(request) -> Reader:
    repository = request.getfixturevalue("repository")
    tiles = tile_store(request.getfixturevalue("tmp_path"))
    key = uuid.uuid4()
    record_tile(BakedTileRepository(repository.connection, tiles), key, b"container one")
    # One tile, charged the first time it is served however often it is served afterwards.
    declare_tile_quota(
        repository.connection, repository.workspace_id, tiles_limit=1, declared_by=ACCOUNT
    )

    def read(connection) -> str:
        try:
            BakedTileRepository(connection, tiles).serve(repository.workspace_id, key)
        except BakedTileFaulted:
            return "faulted"
        return "served"

    def withdraw(other: IngestRepository) -> None:
        # Different bytes under the same key: migration 0072 marks the tile nondeterministic.
        record_tile(BakedTileRepository(other.connection, tiles), key, b"container two")

    return Reader(
        repository.connection,
        read,
        "from baked_tile where baked_tile_id",
        "a baked tile is served only on an idle connection",
        withdraw,
        "served",
        "faulted",
    )


READERS: dict[str, Callable[..., Reader]] = {
    "asset-delivery": _asset_delivery,
    "model-right": _model_right,
    "training-run": lambda request: _training(request, artefact=False),
    "trained-artefact": lambda request: _training(request, artefact=True),
    "place-name": _place_name,
    "material-bake": _material_bake,
    "baked-tile": _baked_tile,
}


@pytest.fixture(params=sorted(READERS))
def reader(request) -> Reader:
    return READERS[request.param](request)


def asset_read_lock_key(connection: psycopg.Connection) -> int:
    """The advisory key ``asset_read_lock()`` takes, read from the function this schema holds."""
    source = connection.execute(
        "select p.prosrc from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
        "where p.proname = 'asset_read_lock' and n.nspname = current_schema()"
    ).fetchone()["prosrc"]
    (key,) = re.findall(r"pg_advisory_xact_lock\((\d+)\)", source)
    return int(key)


def advisory_locks(probe: psycopg.Connection, pid: int) -> list[tuple[int, int, int, str, bool]]:
    """Every advisory lock the backend ``pid`` holds or waits for, as the server reports it."""
    rows = probe.execute(
        "select classid::bigint as classid, objid::bigint as objid, objsubid, mode, granted "
        "from pg_locks where pid = %s and locktype = 'advisory' "
        "order by classid, objid, objsubid, mode",
        (pid,),
    ).fetchall()
    return [
        (row["classid"], row["objid"], row["objsubid"], row["mode"], row["granted"]) for row in rows
    ]


def the_read_lock(key: int, *, granted: bool) -> tuple[int, int, int, str, bool]:
    """The one advisory lock a final read check may hold: the asset read lock, exclusively."""
    return (key >> 32, key & 0xFFFFFFFF, 1, "ExclusiveLock", granted)


def refusal_chain(error: BaseException | None) -> str:
    """An exception and everything it was raised from, as one line a test can search."""
    links = []
    while error is not None:
        links.append(f"{type(error).__name__}: {error}")
        error = error.__cause__ or error.__context__
    return " <- ".join(links)


def wait_until(predicate: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + PATIENCE_SECONDS
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_the_check_opens_read_only_takes_the_lock_reads_the_instant_then_reads(reader):
    recording = Recording(reader.connection)
    assert reader.read(recording) == reader.permitted
    statements = recording.statements
    # The lock is asked for once, and only as the third statement of the check's transaction.
    assert [s for s in statements if "asset_read_lock" in s] == [OPENING[2]], statements
    begin = statements.index(OPENING[2]) - 2
    commit = statements.index("COMMIT", begin)
    assert tuple(statements[begin : begin + len(OPENING)]) == OPENING, statements
    under_lock = statements[begin + len(OPENING) : commit]
    assert len(under_lock) == 1 and reader.marker in under_lock[0], statements


def test_while_it_reads_it_holds_only_the_lock_read_only_and_a_writer_is_refused(
    reader, ingest_spine
):
    _, open_another = ingest_spine
    writer, probe = open_another(), open_another()
    key = asset_read_lock_key(probe.connection)
    pid = reader.connection.info.backend_pid
    seen: dict[str, object] = {}

    def while_reading(recording: Recording, statement: str) -> None:
        if seen or tuple(recording.statements[-len(OPENING) :]) != OPENING:
            return
        seen["statement"] = statement
        seen["locks"] = advisory_locks(probe.connection, pid)
        seen["read_only"] = recording._connection.execute("show transaction_read_only").fetchone()[
            "transaction_read_only"
        ]
        try:
            with writer.connection.transaction():
                reader.withdraw(writer)
            seen["writer"] = "committed"
        except Exception as refused:  # the assertions below name it
            seen["writer"] = refusal_chain(refused)

    recording = Recording(reader.connection, before=while_reading)
    outcome = reader.read(recording)
    assert seen, f"no statement followed the lock and the instant: {recording.statements}"
    assert reader.marker in str(seen["statement"])
    assert seen["locks"] == [the_read_lock(key, granted=True)]
    assert seen["read_only"] == "on"
    assert "SerializationFailure: asset delivery in progress" in str(seen["writer"])
    # Released before the entry point returns, which is before anything is handed over.
    assert reader.connection.info.transaction_status == TransactionStatus.IDLE
    assert advisory_locks(probe.connection, pid) == []
    # The refused write changed nothing the reader answered.
    assert outcome == reader.permitted


def test_a_write_in_flight_is_waited_for_inside_the_read_only_transaction_and_then_seen(
    reader, ingest_spine
):
    _, open_another = ingest_spine
    writer, probe = open_another(), open_another()
    key = asset_read_lock_key(probe.connection)
    pid = reader.connection.info.backend_pid
    recording = Recording(reader.connection)
    outcome: dict[str, object] = {}

    def read() -> None:
        try:
            outcome["value"] = reader.read(recording)
        except Exception as error:  # the assertion below names it
            outcome["error"] = refusal_chain(error)

    with writer.connection.transaction():
        reader.withdraw(writer)
        thread = threading.Thread(target=read)
        thread.start()
        waited = wait_until(
            lambda: advisory_locks(probe.connection, pid) == [the_read_lock(key, granted=False)]
        )
        while_waiting = list(recording.statements)
    thread.join(timeout=PATIENCE_SECONDS)
    assert not thread.is_alive()
    assert waited, (advisory_locks(probe.connection, pid), while_waiting, outcome)
    # It waits inside its read-only transaction, having read nothing under it yet.
    assert tuple(while_waiting[-3:]) == OPENING[:3], while_waiting
    assert outcome == {"value": reader.withdrawn}


def test_a_busy_lock_is_refused_when_the_session_will_not_wait(reader, ingest_spine):
    _, open_another = ingest_spine
    holder = open_another()
    recording = Recording(reader.connection)
    reader.connection.execute(f"set lock_timeout = '{WILL_NOT_WAIT}'")
    try:
        with holder.connection.transaction():
            holder.connection.execute(OPENING[2])
            with pytest.raises(psycopg.errors.LockNotAvailable):
                reader.read(recording)
    finally:
        reader.connection.execute("reset lock_timeout")
    assert recording.statements[-4:] == [*OPENING[:3], "ROLLBACK"], recording.statements
    assert reader.connection.info.transaction_status == TransactionStatus.IDLE
    # The positive control: the same read on the same connection once the lock is free.
    assert reader.read(Recording(reader.connection)) == reader.permitted


def test_a_connection_inside_a_transaction_is_refused_before_the_lock(reader, ingest_spine):
    _, open_another = ingest_spine
    probe = open_another()
    key = asset_read_lock_key(probe.connection)
    recording = Recording(reader.connection)
    with reader.connection.transaction():
        with pytest.raises(ValueError) as refused:
            reader.read(recording)
        locks = advisory_locks(probe.connection, reader.connection.info.backend_pid)
    assert str(refused.value) == reader.not_idle
    assert not [s for s in recording.statements if "asset_read_lock" in s], recording.statements
    # Neither held nor queued for. What else the caller's own transaction holds is the caller's.
    asked = the_read_lock(key, granted=True)[:3]
    assert [lock for lock in locks if lock[:3] == asked] == [], locks
