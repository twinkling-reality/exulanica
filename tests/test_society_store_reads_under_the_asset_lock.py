"""A saved world's society reads nothing from the object store while the asset read lock is held.

Every path a person or the playback host reaches authorizes one or more of a society's inputs in
one transaction: bringing inhabitants in, a minute, a history replayed, everyone sent away, a
playback round, the small square placed in an inhabited world, a model's decision asked and read,
and a chosen person's model asked at a choice point. Each authorization takes the global asset
read lock and holds it until the transaction commits (``docs/asset-read-currency.md``), so every
stored byte a transaction's inputs depend on is read once, before the first of them takes the
lock. Each request runs through the application connected as a runtime role, the recorder is shown
to see a read under a held lock before an empty record is trusted, and each test shows that the
society did read its objects' bytes, before the lock.
"""

from __future__ import annotations

import contextlib
import gc
import json
import logging
import threading
import time
import uuid
from decimal import Decimal

import psycopg
import pytest
from exulanica.api.society_control_worker import SocietyControlWorker
from exulanica.api.society_person_decisions import world_hour
from exulanica.api.society_runtime import NOT_ANNOUNCED, SocietyRuntime, _ReadFirst
from exulanica.db.read_check import lock_asset_reads_until_commit
from exulanica.env import env_get
from exulanica.selection.validation import Session
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world.society import (
    RETRIES_AFTER_A_RACE,
    SocietyBytesNotRead,
    UnavailableSocietyInput,
    inputs_ahead,
)
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_repository import SocietyRepository
from fastapi.testclient import TestClient

import test_society_authored_world_postgres as helpers
import test_society_person_decisions_postgres as person_decisions
import test_society_runtime as district
import test_society_saved_world_api as saved_api
import test_society_social_postgres as social_helpers
import test_society_stay_requests_api as stays
import test_world_arrangements as arrangements
from asset_lock_support import recorded_store_reads
from tests_support_api import EVERY_PERMISSION, scratch_database

pytestmark = pytest.mark.postgres
saved_world = helpers.saved_world
runtime_app = arrangements.runtime_app
app = stays.app
runtime_world = district.runtime_world
#: The ground a saved world is made on today; the older one composes the same inputs.
CURRENT_GROUND = pytest.mark.parametrize(
    "saved_world", [helpers.AUTHORED_GROUND_MODULE_VERSION], indirect=True
)
PURPOSEFUL = saved_api.V2
SOCIAL = "exulanica-society/v3"


def _reads(world, client, monkeypatch, *, shared=False):
    return recorded_store_reads(
        world["connection"],
        client.app.state.services.database,
        world["workspace"],
        world["store"],
        monkeypatch,
        planted=world["plate"].content_sha256,
        shared=shared,
    )


def _society_read_its_bytes(reads) -> bool:
    """Whether the society's runtime read any stored bytes at all: what it read before the lock."""
    return any("api/society_runtime.py" in where for _, where in reads.every)


def _furnished(client, world) -> None:
    """Two objects of two kinds, so an input names two assets and one licence."""
    saved_api.place(client, world, "object:cushion", 3_000, 5_000)
    saved_api.place(client, world, "object:second", -3_000, 5_000, asset="pillar")


def _inhabited(client, world, profile=PURPOSEFUL) -> dict:
    _furnished(client, world)
    brought = saved_api.bring_inhabitants(client, world, profile=profile)
    assert brought.status_code in (200, 201), brought.text
    return brought.json()


def _state(client, world) -> dict:
    scope, _, society = saved_api.routes(world)
    read = client.get(society, headers=saved_api.OWNER, params=scope)
    assert read.status_code == 200, read.text
    return read.json()


def _remove(client, world, object_id: str) -> None:
    """Remove a placed object, so the inputs after it name one asset fewer than those before."""
    scope, version, _ = saved_api.routes(world)
    base = client.get(version, headers=saved_api.OWNER, params=scope).json()["state_sha256"]
    removed = client.post(
        f"{version}/objects/{object_id}/remove",
        headers=saved_api.OWNER,
        params=scope,
        json={"base_state_sha256": base},
    )
    assert removed.status_code == 200, removed.text


def _step(client, world) -> dict:
    scope, _, society = saved_api.routes(world)
    state = _state(client, world)
    stepped = client.post(
        society + "/steps",
        headers=saved_api.OWNER,
        params=scope,
        json={"base_tick": state["current_tick"], "base_state_sha256": state["state_sha256"]},
    )
    assert stepped.status_code == 200, stepped.text
    return stepped.json()


@CURRENT_GROUND
def test_bringing_inhabitants_in_reads_nothing_under_the_lock(runtime_app, monkeypatch):
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        _furnished(client, world)
        reads = _reads(world, client, monkeypatch, shared=True)
        brought = saved_api.bring_inhabitants(client, world)
    assert brought.status_code in (200, 201), brought.text
    assert reads.under_the_lock == []
    assert reads.while_shared == [], "nothing is read while the place's write holds the lock"
    assert _society_read_its_bytes(reads)


@CURRENT_GROUND
@pytest.mark.parametrize("profile", [PURPOSEFUL, SOCIAL], ids=["purposeful", "social"])
def test_a_minute_over_a_queued_input_reads_nothing_under_the_lock(
    runtime_app, monkeypatch, profile
):
    """The minute authorizes the input it consumed and the one queued after it, and a social
    society every input its people remember, all in one transaction. The queued input names one
    asset fewer than the one consumed, so reading only the first authorized is not enough."""
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        _inhabited(client, world, profile)
        _step(client, world)
        _remove(client, world, "object:second")
        reads = _reads(world, client, monkeypatch)
        stepped = _step(client, world)
    assert stepped["input_seq"] == 2, "the minute consumed the queued input"
    assert reads.under_the_lock == []
    assert _society_read_its_bytes(reads)


@CURRENT_GROUND
def test_replaying_a_history_reads_nothing_under_the_lock(runtime_app, monkeypatch):
    """The first input names one asset fewer than the second: every input is read first."""
    world, make_app = runtime_app
    scope, _, society = saved_api.routes(world)
    with TestClient(make_app()) as client:
        saved_api.place(client, world, "object:cushion", 3_000, 5_000)
        brought = saved_api.bring_inhabitants(client, world)
        assert brought.status_code in (200, 201), brought.text
        _step(client, world)
        saved_api.place(client, world, "object:second", -3_000, 5_000, asset="pillar")
        _step(client, world)
        reads = _reads(world, client, monkeypatch)
        replayed = client.get(society + "/replay", headers=saved_api.OWNER, params=scope)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True
    assert reads.under_the_lock == []
    assert _society_read_its_bytes(reads)


@CURRENT_GROUND
def test_sending_everyone_away_reads_nothing_under_the_lock(runtime_app, monkeypatch):
    world, make_app = runtime_app
    scope, _, society = saved_api.routes(world)
    with TestClient(make_app()) as client:
        _inhabited(client, world)
        state = _step(client, world)
        reads = _reads(world, client, monkeypatch)
        away = client.post(
            society + "/presence",
            headers=saved_api.OWNER,
            params=scope,
            json={
                "base_tick": state["current_tick"],
                "base_state_sha256": state["state_sha256"],
                "idempotency_key": str(uuid.uuid4()),
                "presence": "away",
            },
        )
    assert away.status_code == 200, away.text
    assert reads.under_the_lock == []
    assert _society_read_its_bytes(reads)


@CURRENT_GROUND
def test_a_playback_round_of_several_minutes_reads_nothing_under_the_lock(runtime_app, monkeypatch):
    """The round checks the society is ready and advances every minute due in one transaction."""
    world, make_app = runtime_app
    scope, _, society = saved_api.routes(world)
    control_route = society + "/control"
    with TestClient(make_app()) as client:
        _inhabited(client, world)
        control = client.get(control_route, headers=saved_api.OWNER, params=scope).json()
        playing = client.put(
            control_route,
            headers=saved_api.OWNER,
            params=scope,
            json={"base_revision": control["revision"], "mode": "playing", "speed": 1},
        )
        assert playing.status_code == 200, playing.text
        # Three minutes due: the interval is the control's own, read back rather than restated.
        interval_ms = playing.json()["base_tick_interval_ms"] // playing.json()["speed"]
        world["connection"].execute(
            "update world_society_control set "
            "next_due_at=clock_timestamp()-make_interval(secs => %s) where workspace_id=%s",
            (interval_ms * 2.5 / 1000, world["workspace"]),
        )
        world["connection"].commit()
        services = client.app.state.services
        worker = SocietyControlWorker(
            services.database, runtime=services.society_runtime, workspaces=[world["workspace"]]
        )
        reads = _reads(world, client, monkeypatch)
        result = worker.run_once(world["workspace"])
    assert result is not None and result["receipt"]["kind"] == "advanced", result
    assert result["receipt"]["executed_ticks"] >= 2, "the round advanced several minutes"
    assert reads.under_the_lock == []
    assert _society_read_its_bytes(reads)


@CURRENT_GROUND
def test_the_small_square_in_an_inhabited_world_reads_nothing_under_the_lock(
    runtime_app, monkeypatch
):
    """Every addition records a society input over every object placed so far, the square's
    kinds included, after the first addition has taken the lock."""
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        saved_api.place(client, world, "object:cushion", 9_000, 6_000)
        brought = saved_api.bring_inhabitants(client, world)
        assert brought.status_code in (200, 201), brought.text
        reads = _reads(world, client, monkeypatch)
        scope, version, body = arrangements._body(client, world)
        applied = client.post(
            version + "/arrangements/apply", headers=saved_api.OWNER, params=scope, json=body
        )
    assert applied.status_code == 201, applied.text
    assert len(applied.json()["added_object_ids"]) > 1, "several additions in one transaction"
    assert reads.under_the_lock == []
    assert _society_read_its_bytes(reads)


@CURRENT_GROUND
def test_a_decision_asked_and_read_reads_nothing_under_the_lock(
    runtime_app, monkeypatch, client, transport, manifest
):
    """Preparing a social decision authorizes the state's inputs, finishing it the request's
    context and the latest input, and reading it back the same, each in one transaction."""
    world, make_app = runtime_app
    scope, _, society = saved_api.routes(world)
    with TestClient(make_app()) as http:
        _inhabited(http, world, SOCIAL)
        _step(http, world)
        _remove(http, world, "object:second")
        state = _step(http, world)
        subject = state["state"]["social"]["cast_ids"][1]
        http.app.state.society_decision_provider = social_helpers.provider_for(
            client, transport, manifest
        )
        key = str(uuid.uuid4())
        reads = _reads(world, http, monkeypatch)
        answered = http.post(
            society + "/decisions",
            headers=saved_api.OWNER,
            params=scope,
            json={
                "idempotency_key": key,
                "subject_id": subject,
                "base_tick": state["current_tick"],
                "base_state_sha256": state["state_sha256"],
            },
        )
        read = http.get(society + "/decisions/" + key, headers=saved_api.OWNER, params=scope)
    assert answered.status_code == 200, answered.text
    assert answered.json()["decision"] is not None, "the decision was finished"
    assert read.status_code == 200, read.text
    assert len(transport.requests) == 1
    assert reads.under_the_lock == []
    assert _society_read_its_bytes(reads)


@CURRENT_GROUND
def test_a_decision_finished_after_an_edit_reads_nothing_under_the_lock(runtime_app, monkeypatch):
    """The world changed while the model was asked: the latest input names an asset the request's
    input does not, and the finish authorizes both in one transaction."""
    world, make_app = runtime_app
    with TestClient(make_app()) as http:
        _inhabited(http, world, SOCIAL)
        _step(http, world)
        _remove(http, world, "object:second")
        state = _step(http, world)
        services = http.app.state.services
        runtime = services.society_runtime
        session = Session(workspace_id=world["workspace"], actor=world["session"].actor)
        version_id = world["binding"].version_id
        request_id = uuid.uuid4()

        def decisions(connection):
            return SocietyDecisionRepository(
                SocietyRepository(
                    connection,
                    world["workspace"],
                    world_id=world["binding"].world_id,
                    input_authorizer=lambda doc: runtime.authorize(connection, session, doc),
                )
            )

        with services.database.session(world["workspace"]) as connection:
            with connection.transaction():
                _, fresh = decisions(connection).prepare(
                    version_id,
                    request_id=request_id,
                    subject_id=uuid.UUID(state["state"]["social"]["cast_ids"][1]),
                    base_tick=state["current_tick"],
                    base_state_sha256=state["state_sha256"],
                    provider_config=None,
                )
            assert fresh
            saved_api.place(http, world, "object:again", -3_000, 5_000, asset="pillar")
            reads = _reads(world, http, monkeypatch)
            with connection.transaction():
                finished = decisions(connection).finish(
                    version_id,
                    request_id,
                    {"status": "unavailable", "reason": "provider_not_configured"}
                    | {"proposal": None, "provider": None},
                )
    assert finished["decision"]["reason"] == "decision_context_changed", "the edit was seen"
    assert reads.under_the_lock == []
    assert _society_read_its_bytes(reads)


@pytest.mark.parametrize("saved_world", [helpers.AUTHORED_GROUND_MODULE_VERSION], indirect=True)
def test_a_history_of_directed_requests_reads_nothing_under_the_lock(app, monkeypatch):
    """Newest first: the newest request's input names one asset fewer than the older one's."""
    world, client = app
    scope, _, society = saved_api.routes(world)
    snapshot = stays._step(world, client, stays._inhabited(world, client))

    def ask(snapshot, index):
        person = snapshot["state"]["inhabitants"][index]
        target = next(t["target_id"] for t in snapshot["places"]["targets"] if t["enabled"])
        asked = stays._ask(world, client, snapshot, person, target)
        assert asked.status_code == 200, asked.text

    ask(snapshot, 0)
    snapshot = stays._step(world, client, snapshot)
    _remove(client, world, "object:pillar")
    snapshot = stays._step(world, client, snapshot)
    ask(snapshot, 1)
    reads = _reads(world, client, monkeypatch)
    history = client.get(society + "/actions", headers=saved_api.OWNER, params=scope)
    assert history.status_code == 200, history.text
    assert len({e["request"]["input_seq"] for e in history.json()["events"]}) == 2
    assert reads.under_the_lock == []
    assert _society_read_its_bytes(reads)


@pytest.mark.parametrize("saved_world", [helpers.AUTHORED_GROUND_MODULE_VERSION], indirect=True)
def test_asking_chosen_peoples_models_reads_nothing_under_the_lock(app, monkeypatch):
    """The host reserves every chosen person's request in one transaction and records each
    answer in its own, as it does before a claimed minute."""
    world, client = app
    services = client.app.state.services
    manifest, model_id = person_decisions._offered()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    person_decisions._choose(services, world, people, model, manifest=manifest)
    transport = person_decisions._Chooser()
    host = person_decisions._host(
        world, person_decisions._client(manifest, transport), services, manifest
    )
    reads = _reads(world, client, monkeypatch)
    for _ in range(30):
        assert host.before_minute(
            person_decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
        )
        if person_decisions._decisions(services, world, snapshot):
            break
        snapshot = stays._step(world, client, snapshot)
    else:
        raise AssertionError("nobody in the square reached a choice point in thirty minutes")
    assert transport.call_count >= 1, "a model was asked and its answer recorded"
    assert reads.under_the_lock == []
    assert _society_read_its_bytes(reads)


@pytest.mark.parametrize("saved_world", [helpers.AUTHORED_GROUND_MODULE_VERSION], indirect=True)
def test_every_chosen_persons_answer_is_recorded_when_its_finish_meets_the_race_every_time(
    app, monkeypatch
):
    """A finish that meets the race on every try is recorded as ``decision_sources_unavailable``
    on its last, so no request is left in progress under its key."""
    world, client = app
    services = client.app.state.services
    manifest, model_id = person_decisions._offered()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    person_decisions._choose(services, world, people, model, manifest=manifest)
    transport = person_decisions._Chooser()
    host = person_decisions._host(
        world, person_decisions._client(manifest, transport), services, manifest
    )
    finishes = {"tries": 0}

    def racing(self, request, documents):
        finishes["tries"] += 1
        raise SocietyBytesNotRead("a reviewed asset changed between the read and the lock")

    monkeypatch.setattr(SocietyDecisionRepository, "_authorize_context", racing)
    for _ in range(30):
        assert host.before_minute(
            person_decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
        )
        receipts = person_decisions._decisions(services, world, snapshot)
        if receipts:
            break
        snapshot = stays._step(world, client, snapshot)
    else:
        raise AssertionError("nobody in the square reached a choice point in thirty minutes")
    assert transport.call_count == len(receipts), "every model was asked once"
    assert finishes["tries"] == len(receipts) * (RETRIES_AFTER_A_RACE + 1)
    assert {(r["status"], r["reason"]) for r in receipts} == {
        ("unavailable", "decision_sources_unavailable")
    }
    # The calls that were made stay on the receipts, so the world's hourly bounds count them.
    assert all(r["provider"] is not None and r["provider"]["model_id"] for r in receipts)
    with services.database.session(world["workspace"]) as connection:
        asked, spent = world_hour(connection, world["workspace"], world["binding"].world_id)
    assert asked == len(receipts)
    assert spent == sum(Decimal(str(r["provider"]["cost_usd"])) for r in receipts)
    with services.database.session(world["workspace"]) as connection:
        open_requests = connection.execute(
            "select count(*) as n from world_society_decision_request r "
            "left join world_society_decision d using(workspace_id,society_id,request_id) "
            "where r.workspace_id=%s and d.request_id is null",
            (world["workspace"],),
        ).fetchone()["n"]
    assert open_requests == 0, "no request is left in progress"


# -- what a transaction read ahead ----------------------------------------------------------------


@CURRENT_GROUND
def test_what_a_transaction_read_ahead_is_its_own_and_goes_with_it(runtime_app):
    """One record per transaction: kept across its savepoints and in a read-only transaction,
    begun anew by the next transaction on the same connection and by each statement outside one,
    and gone with the connection."""
    world, make_app = runtime_app
    runtime = SocietyRuntime(
        store=world["store"], authored_bindings=[], reviewed_affordances=world["registry"]
    )
    with TestClient(make_app()) as client:
        database = client.app.state.services.database
    with database.session(world["workspace"]) as connection:
        with connection.transaction():
            first = runtime._transaction_read(connection)
            first.found[("a" * 64, None)] = None
            with connection.transaction():
                assert runtime._transaction_read(connection) is first, "a savepoint keeps it"
        with connection.transaction():
            second = runtime._transaction_read(connection)
            assert second is not first
            assert second == _ReadFirst(), "nothing is carried over to the next transaction"
        with connection.transaction():
            connection.execute("set transaction read only")
            read_only = runtime._transaction_read(connection)
            assert runtime._transaction_read(connection) is read_only
        # Outside a transaction each statement is its own, so nothing read is found again.
        assert runtime._transaction_read(connection) is not runtime._transaction_read(connection)
        assert len(runtime._transactions) == 1, "one entry for the connection"
    del connection
    gc.collect()
    assert len(runtime._transactions) == 0, "the entry goes with the connection"


def test_bytes_read_ahead_answer_and_a_row_changed_since_is_the_race(tmp_path, caplog):
    """The record answers what was read ahead; a reviewed row that names other bytes than when
    it was read is the race; bytes nobody announced are read now and logged by name."""
    store = LocalContentAddressedStore(tmp_path / "blobs")
    kept = store.put_bytes(b"licence text").blob_id.hex
    runtime = SocietyRuntime(store=store, reviewed_affordances={})
    view = ("a" * 64, 3, "c" * 64)
    read = _ReadFirst(
        found={("a" * 64, 3): None, ("b" * 64, None): "required exact asset bytes are unavailable"},
        rows={"cc0.thing": view},
        locked=True,
    )
    with caplog.at_level(logging.ERROR):
        assert runtime._answer(read, "a" * 64, 3, reviewed=("cc0.thing", view)) is None
        with pytest.raises(UnavailableSocietyInput, match="required exact asset bytes"):
            runtime._answer(read, "b" * 64, None)
        assert not caplog.records, "bytes read ahead are answered without reading"
        changed = ("a" * 64, 3, "d" * 64)
        with pytest.raises(SocietyBytesNotRead):
            runtime._answer(read, "d" * 64, None, reviewed=("cc0.thing", changed))
        assert not caplog.records, "the race is refused, not read"
        # Positive control: bytes no input announced are read under the lock and named.
        assert runtime._kept(read, kept) == b"licence text"
    assert [r.getMessage().split(":")[0] for r in caplog.records] == [NOT_ANNOUNCED]
    assert caplog.records[0].levelno == logging.ERROR
    # A race is not an unavailable input: nothing that records one, or pauses for one, takes it.
    assert not issubclass(SocietyBytesNotRead, (UnavailableSocietyInput, ValueError))


@CURRENT_GROUND
def test_an_input_nobody_announced_is_authorized_and_its_defect_named(
    runtime_app, monkeypatch, caplog
):
    """Two inputs authorized in one transaction with only the first read ahead: the second's
    new asset is read under the lock, the person is answered, and the defect is logged by name,
    which the recorder sees. Announced, the same two read nothing under the lock."""
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        saved_api.place(client, world, "object:cushion", 3_000, 5_000)
        brought = saved_api.bring_inhabitants(client, world)
        assert brought.status_code in (200, 201), brought.text
        saved_api.place(client, world, "object:second", -3_000, 5_000, asset="pillar")
        inputs = [
            row["document"]
            for row in world["connection"]
            .execute(
                "select document from world_society_input where workspace_id=%s order by input_seq",
                (world["workspace"],),
            )
            .fetchall()
        ]
        world["connection"].commit()
        assert len(inputs) == 2
        services = client.app.state.services
        runtime = services.society_runtime
        session = Session(workspace_id=world["workspace"], actor=world["session"].actor)
        reads = _reads(world, client, monkeypatch)
        with (
            caplog.at_level(logging.ERROR),
            services.database.session(world["workspace"]) as connection,
            connection.transaction(),
        ):
            for document in inputs:
                runtime.authorize(connection, session, document)
        named = [r.getMessage().split(":")[0] for r in caplog.records]
        assert named and set(named) == {NOT_ANNOUNCED}, named
        assert reads.under_the_lock, "the recorder sees the unannounced read"
        caplog.clear()
        reads.every.clear()
        reads.under_the_lock.clear()
        with (
            caplog.at_level(logging.ERROR),
            services.database.session(world["workspace"]) as connection,
            connection.transaction(),
            inputs_ahead(connection, inputs),
        ):
            for document in inputs:
                runtime.authorize(connection, session, document)
    assert caplog.records == []
    assert reads.under_the_lock == []
    assert _society_read_its_bytes(reads)


# -- bringing inhabitants in reads its first input, then takes the lock, then writes its place -----


@CURRENT_GROUND
def test_a_withdrawal_committed_before_the_creations_lock_refuses_it(runtime_app, monkeypatch):
    """The creation reads its first input's bytes, then takes the asset read lock, and only then
    writes the saved world's place. A withdrawal that commits between the read and the lock is
    seen under the lock as the race: the creation is refused as busy and leaves nothing, no place,
    no society and no input; asked again, it reads the withdrawal and is refused by it."""
    world, make_app = runtime_app
    key = world["plate"].asset_key
    connection = world["connection"]
    schema = connection.execute("select current_schema() as name").fetchone()["name"]
    licence = connection.execute(
        "select licence_sha256 from world_reviewed_asset where asset_key=%s", (key,)
    ).fetchone()["licence_sha256"]
    connection.commit()
    lock = SocietyRuntime._lock_assets
    committed = []

    def withdrawn_first(creation, read):
        if not committed:
            with psycopg.connect(env_get("TEST_DATABASE_URL"), autocommit=True) as other:
                other.execute(f'set search_path to "{schema}", public')
                other.execute(
                    "update world_reviewed_asset set licence_sha256=%s where asset_key=%s",
                    ("0" * 64, key),
                )
                committed.append(
                    other.execute(
                        "select licence_sha256 from world_reviewed_asset where asset_key=%s",
                        (key,),
                    ).fetchone()[0]
                )
        lock(creation, read)

    try:
        with TestClient(make_app()) as client:
            saved_api.place(client, world, "object:cushion", 3_000, 5_000)
            with monkeypatch.context() as patch:
                patch.setattr(SocietyRuntime, "_lock_assets", staticmethod(withdrawn_first))
                refused = saved_api.bring_inhabitants(client, world)
            assert committed == ["0" * 64], "the withdrawal committed before the creation's lock"
            assert refused.status_code == 409 and refused.json()["code"] == "busy", refused.text
            assert saved_api.held(world) == saved_api.NOTHING
            again = saved_api.bring_inhabitants(client, world)
            assert again.status_code == 422, again.text
            assert saved_api.held(world) == saved_api.NOTHING
            # Positive control: with the licence restored, the same request brings them in.
            connection.execute(
                "update world_reviewed_asset set licence_sha256=%s where asset_key=%s",
                (licence, key),
            )
            connection.commit()
            brought = saved_api.bring_inhabitants(client, world)
        assert brought.status_code in (200, 201), brought.text
    finally:
        connection.execute(
            "update world_reviewed_asset set licence_sha256=%s where asset_key=%s", (licence, key)
        )
        connection.commit()


# -- a district society --------------------------------------------------------------------------


def _district_reads(w, spine_schema, monkeypatch):
    return recorded_store_reads(
        w["connection"],
        scratch_database(spine_schema[1]),
        w["workspace"],
        w["store"],
        monkeypatch,
        planted=w["plate"].content_sha256,
    )


def test_a_district_society_reads_nothing_under_the_lock(runtime_world, spine_schema, monkeypatch):
    """Creation, an edit, one minute and three minutes in one transaction (as a playback round
    runs them), and a replay: a district's sources and artifacts and its objects' assets are
    read before the lock."""
    w = runtime_world
    reads = _district_reads(w, spine_schema, monkeypatch)
    with w["connection"].transaction():
        district.create(w)
    with w["connection"].transaction():
        district.add_plate(w)
    repository = district.society(w)
    version_id = w["binding"].version_id
    state = repository.snapshot(version_id)
    for minutes in (1, 3):
        with w["connection"].transaction():
            for _ in range(minutes):
                state = repository.advance(
                    version_id,
                    base_tick=state["current_tick"],
                    base_state_sha256=state["state_sha256"],
                )
    assert repository.replay(version_id)["replay_verified"] is True
    assert state["current_tick"] == 4 and state["input_seq"] == 2
    assert reads.under_the_lock == []
    assert _society_read_its_bytes(reads)


#: How long another connection holds the asset read lock while a creation arrives: long enough that
#: the creation's request starts while it is held (it starts as soon as the lock is taken).
HOLD_SECONDS = 1.0
#: How long each of two creations waits for the other at the point where, writing its place before
#: the lock, it would hold the lock's shared side; a creation that takes the lock first never
#: arrives while the other holds it, so the wait ends by this bound.
MEETING_SECONDS = 2.0


@CURRENT_GROUND
def test_a_creation_waits_for_a_held_lock_and_is_answered(runtime_app, monkeypatch):
    """Another connection holds the asset read lock (a delivery, a playback round) when
    inhabitants are asked for: the creation waits for it and brings them in, never a 500."""
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        _furnished(client, world)
        database = client.app.state.services.database
        held, released = threading.Event(), []

        def hold() -> None:
            with database.session(world["workspace"]) as other, other.transaction():
                lock_asset_reads_until_commit(other, outside="the test holds it in a write")
                held.set()
                time.sleep(HOLD_SECONDS)
                released.append(time.monotonic())

        # The recorder's planted controls take the lock themselves, so they run before it is held.
        reads = _reads(world, client, monkeypatch, shared=True)
        holder = threading.Thread(target=hold)
        holder.start()
        try:
            assert held.wait(10), "the other connection took the lock"
            brought = saved_api.bring_inhabitants(client, world)
            answered = time.monotonic()
        finally:
            holder.join()
    assert brought.status_code in (200, 201), brought.text
    assert released and answered >= released[0], "the creation waited for the held lock"
    # The creation read its bytes while the other connection held the lock, which the rule
    # allows: only a holder reads nothing. It held neither side itself while it read.
    assert reads.while_shared == []
    assert _society_read_its_bytes(reads)


def _second_world(world, monkeypatch) -> dict:
    """A saved world in another workspace, and a token for its owner beside the first's."""
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    world_id = f"world:authored:{uuid.uuid4()}"
    with world["connection"].transaction():
        _snapshot, version_id = helpers.make_starter(
            world["connection"], workspace, actor, world_id, helpers.AUTHORED_GROUND_MODULE_VERSION
        )
    world["connection"].commit()
    token = "saved-world-inhabitants-second-owner-token-long-enough"
    grants = {
        saved_api.TOKEN: {
            "workspace_id": str(world["workspace"]),
            "actor": str(world["session"].actor),
            "permissions": EVERY_PERMISSION,
        },
        token: {
            "workspace_id": str(workspace),
            "actor": str(actor),
            "permissions": EVERY_PERMISSION,
        },
    }
    monkeypatch.setenv("EXULANICA_API_TOKENS", json.dumps(grants))
    version = f"/world/versions/{version_id}"
    return {
        "headers": {"Authorization": f"Bearer {token}"},
        "scope": {"world_id": world_id},
        "version": version,
        "society": version + "/society",
    }


def _place_in(client, other, world, object_id, x_mm, z_mm) -> None:
    base = client.get(other["version"], headers=other["headers"], params=other["scope"])
    placed = client.post(
        other["version"] + "/objects",
        headers=other["headers"],
        params=other["scope"],
        json={
            "base_state_sha256": base.json()["state_sha256"],
            "object_id": object_id,
            "asset_sha256": world["plate"].content_sha256,
            "region_id": world["binding"].region_id,
            "transform": {
                "x_mm": x_mm,
                "y_mm": 0,
                "z_mm": z_mm,
                "yaw_microradians": saved_api.FACING_THE_PERSON,
                "scale_milli": 1000,
            },
            "origin_role": "fictional",
        },
    )
    assert placed.status_code == 201, placed.text


@CURRENT_GROUND
def test_two_creations_in_two_workspaces_at_once_both_bring_inhabitants_in(
    runtime_app, monkeypatch
):
    """Each creation takes the asset read lock before it writes its place, so neither holds the
    lock's shared side while asking for the other side: they take turns rather than deadlock."""
    world, make_app = runtime_app
    other = _second_world(world, monkeypatch)
    make_place = SocietyRuntime.saved_world_place
    meeting = threading.Barrier(2, timeout=MEETING_SECONDS)

    def then_meet(self, connection, session, version_id):
        place = make_place(self, connection, session, version_id)
        with contextlib.suppress(threading.BrokenBarrierError):
            meeting.wait()
        return place

    monkeypatch.setattr(SocietyRuntime, "saved_world_place", then_meet)
    with TestClient(make_app()) as first, TestClient(make_app()) as second:
        saved_api.place(first, world, "object:cushion", 3_000, 5_000)
        _place_in(second, other, world, "object:cushion", 3_000, 5_000)
        answers: dict[str, object] = {}

        def create(name, client, headers, scope, society) -> None:
            try:
                answers[name] = client.post(
                    society,
                    headers=headers,
                    params=scope,
                    json={
                        "region_id": world["binding"].region_id,
                        "seed": "7a" * 32,
                        "profile": PURPOSEFUL,
                    },
                )
            except Exception as failed:  # the answer, whatever it is, is what the test reads
                answers[name] = failed

        scope, _, society = saved_api.routes(world)
        threads = [
            threading.Thread(target=create, args=("first", first, saved_api.OWNER, scope, society)),
            threading.Thread(
                target=create,
                args=("second", second, other["headers"], other["scope"], other["society"]),
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    for name in ("first", "second"):
        answer = answers[name]
        assert not isinstance(answer, Exception), f"{name}: {answer!r}"
        assert answer.status_code in (200, 201), (name, answer.text)


@CURRENT_GROUND
def test_a_social_round_over_two_queued_inputs_reads_nothing_under_the_lock(
    runtime_app, monkeypatch, caplog
):
    """An object added and taken back before the next round: two inputs queued after the one
    consumed, the first naming an asset neither of the others does. The round checks the society
    is ready, then advances, in one transaction, and every queued input is read before the lock."""
    world, make_app = runtime_app
    scope, _, society = saved_api.routes(world)
    control_route = society + "/control"
    with TestClient(make_app()) as client:
        saved_api.place(client, world, "object:cushion", 3_000, 5_000)
        brought = saved_api.bring_inhabitants(client, world, profile=SOCIAL)
        assert brought.status_code in (200, 201), brought.text
        saved_api.place(client, world, "object:second", -3_000, 5_000, asset="pillar")
        _remove(client, world, "object:second")
        state = _state(client, world)
        assert (state["input_seq"], _latest_input(world)) == (1, 3), "two inputs are queued"
        control = client.get(control_route, headers=saved_api.OWNER, params=scope).json()
        playing = client.put(
            control_route,
            headers=saved_api.OWNER,
            params=scope,
            json={"base_revision": control["revision"], "mode": "playing", "speed": 1},
        )
        assert playing.status_code == 200, playing.text
        world["connection"].execute(
            "update world_society_control set next_due_at=clock_timestamp() where workspace_id=%s",
            (world["workspace"],),
        )
        world["connection"].commit()
        services = client.app.state.services
        worker = SocietyControlWorker(
            services.database, runtime=services.society_runtime, workspaces=[world["workspace"]]
        )
        reads = _reads(world, client, monkeypatch)
        with caplog.at_level(logging.ERROR):
            result = worker.run_once(world["workspace"])
    assert result is not None and result["receipt"]["kind"] == "advanced", result
    assert [r for r in caplog.records if r.getMessage().startswith(NOT_ANNOUNCED)] == []
    assert reads.under_the_lock == []
    assert _society_read_its_bytes(reads)


def _latest_input(world) -> int:
    latest = (
        world["connection"]
        .execute(
            "select max(input_seq) as seq from world_society_input where workspace_id=%s",
            (world["workspace"],),
        )
        .fetchone()["seq"]
    )
    world["connection"].commit()
    return latest


@CURRENT_GROUND
def test_a_malformed_input_announced_beside_another_does_not_fail_its_authorization(runtime_app):
    """Reading ahead skips an announced input it cannot read: that input is refused by its own
    authorization, and the other is authorized as if it stood alone."""
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        _inhabited(client, world)
        [document] = [
            row["document"]
            for row in world["connection"]
            .execute(
                "select document from world_society_input where workspace_id=%s",
                (world["workspace"],),
            )
            .fetchall()
        ]
        world["connection"].commit()
        malformed = {**document, "document_sha256": "e" * 64, "dependency_refs": None}
        services = client.app.state.services
        runtime = services.society_runtime
        session = Session(workspace_id=world["workspace"], actor=world["session"].actor)
        with (
            services.database.session(world["workspace"]) as connection,
            connection.transaction(),
            inputs_ahead(connection, [malformed, document]),
        ):
            runtime.authorize(connection, session, document)
        with pytest.raises(ValueError):
            runtime.authorize(connection, session, malformed)


def test_a_district_source_admitted_between_the_read_and_the_lock_is_the_race(
    runtime_world, monkeypatch, caplog
):
    """Each source is asked alone before the lock. One its rows refuse then and admit under the
    lock changed in between: the race, asked again, never a caller's defect read under the lock;
    the other source is still read ahead."""
    w = runtime_world
    document = district.initial(w)
    admitted = SocietyRuntime._admitted_source
    asked = {"times": 0}

    def admitted_later(self, *args):
        asked["times"] += 1
        if asked["times"] == 1:
            raise UnavailableSocietyInput("the source's right is not current yet")
        return admitted(self, *args)

    monkeypatch.setattr(SocietyRuntime, "_admitted_source", admitted_later)
    with caplog.at_level(logging.ERROR), pytest.raises(SocietyBytesNotRead):
        w["runtime"].authorize(w["connection"], w["session"], document)
    assert [r for r in caplog.records if r.getMessage().startswith(NOT_ANNOUNCED)] == []
    # Positive control: admitted both times, the same input is authorized.
    monkeypatch.setattr(SocietyRuntime, "_admitted_source", admitted)
    w["runtime"].authorize(w["connection"], w["session"], document)


@CURRENT_GROUND
def test_an_input_authorized_alone_reads_only_its_own_bytes(runtime_app, monkeypatch):
    """Outside a caller's transaction each authorization is its own, so it reads only its input's
    bytes, not those of inputs announced for the connection that no later authorization of that
    transaction asks: a read of a society's state costs what it did before inputs were read ahead.
    """
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        _inhabited(client, world)
        _remove(client, world, "object:second")
        rows = (
            world["connection"]
            .execute(
                "select document from world_society_input where workspace_id=%s order by input_seq",
                (world["workspace"],),
            )
            .fetchall()
        )
        world["connection"].commit()
        with_pillar, without = rows[0]["document"], rows[1]["document"]
        services = client.app.state.services
        runtime = services.society_runtime
        session = Session(workspace_id=world["workspace"], actor=world["session"].actor)
        read_digests: list[str] = []
        get = world["store"].get

        def getting(blob_id):
            read_digests.append(blob_id.hex)
            return get(blob_id)

        monkeypatch.setattr(world["store"], "get", getting)
        with (
            services.database.session(world["workspace"]) as connection,
            inputs_ahead(connection, [with_pillar, without]),
        ):
            runtime.authorize(connection, session, without)
            alone = list(read_digests)
            read_digests.clear()
            # Positive control: inside a caller's transaction the announced input is read too.
            with connection.transaction():
                runtime.authorize(connection, session, without)
    pillar, plate = world["pillar"].content_sha256, world["plate"].content_sha256
    assert plate in alone and pillar not in alone, alone
    assert pillar in read_digests, "the announced input's pillar is read in a caller's transaction"
