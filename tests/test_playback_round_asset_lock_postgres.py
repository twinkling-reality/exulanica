"""A playback round holds migration 0041's asset read lock from its authorization to its commit.

A round computes and writes its minutes holding the workspace lock, then authorizes every input
the minutes read, once, under the global asset read lock, and holds that lock until it commits
(``SocietyControlRepository.execute``, ``docs/asset-read-currency.md``). Each test runs the round
on a connection of its own and probes from another, as the derivative worker or an upload would:

* while the round computes, a guarded write commits;
* a withdrawal committed while the round computes is accepted, and the round's minutes roll back
  and the society pauses, so no minute commits over an input that stopped being permitted;
* a tombstone written while the round computes is refused at once rather than wait for the
  workspace lock the round holds (migration 0137), and the round commits; without the refusal,
  the round's asset read lock and the waiting tombstone deadlock;
* between the authorization and the commit, a guarded write is refused, so nothing a minute read
  can change before the minute commits;
* the pause a refusal writes is, byte for byte, the receipt a refusal before the minutes writes.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from dataclasses import replace

import psycopg
import pytest
from exulanica.canonical import canonical_json
from exulanica.environment.repository import EnvironmentRepository
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.society_repository import SocietyRepository

import test_society_runtime as helpers
from test_society_controls_postgres import controls, create, expire, overdue, save, take_claim
from test_tombstone_workspace_lock_postgres import (
    REFUSAL,
    DeletionInFlight,
    connection_in,
    deadlocks,
    refusal_planted_out,
    write_tombstone,
    written,
)
from tests_support_api import scratch_database

runtime_world = helpers.runtime_world
pytestmark = pytest.mark.postgres

COMMITTED, BUSY = "committed", "busy"


def _guarded_write(database, workspace: uuid.UUID) -> str:
    """One write migration 0041's barrier guards, from a connection of its own: a new place."""
    with database.session(workspace) as other:
        try:
            other.execute(
                "insert into place(workspace_id, place_id) values (%s, %s)",
                (workspace, uuid.uuid4()),
            )
        except psycopg.errors.SerializationFailure:
            return BUSY
    return COMMITTED


def _playing_round(w, spine_schema):
    """A society due three minutes, its claim, and a database to run the round and probe on."""
    before = create(w)
    save(w)
    overdue(w)
    return before, take_claim(w), scratch_database(spine_schema[1])


def test_a_guarded_write_made_while_a_round_computes_commits(
    runtime_world, spine_schema, monkeypatch
):
    w = runtime_world
    _before, claim, database = _playing_round(w, spine_schema)
    probes: list[str] = []
    advance = SocietyRepository.advance

    def probing(self, *args, **kwargs):
        probes.append(_guarded_write(database, w["workspace"]))
        return advance(self, *args, **kwargs)

    monkeypatch.setattr(SocietyRepository, "advance", probing)
    with database.session(w["workspace"]) as connection:
        result = controls(w, connection).execute(claim)
    assert result["receipt"]["kind"] == "advanced"
    assert result["receipt"]["executed_ticks"] == 3
    assert probes == [COMMITTED] * 3


def test_a_withdrawal_committed_while_a_round_computes_rolls_the_round_back_and_pauses(
    runtime_world, spine_schema, monkeypatch
):
    w = runtime_world
    before, claim, database = _playing_round(w, spine_schema)
    withdrawals: list[str] = []
    advance = SocietyRepository.advance

    def withdrawing(self, *args, **kwargs):
        if not withdrawals:
            with database.session(w["workspace"]) as other:
                EnvironmentRepository(other, w["workspace"], w["store"]).withdraw(
                    "source", w["binding"].sources[0].admission_id
                )
            withdrawals.append(COMMITTED)
        return advance(self, *args, **kwargs)

    monkeypatch.setattr(SocietyRepository, "advance", withdrawing)
    with database.session(w["workspace"]) as connection:
        result = controls(w, connection).execute(claim)
    assert withdrawals == [COMMITTED]
    assert result["control"]["mode"] == "paused"
    assert result["control"]["reason"] == "source_unavailable"
    assert result["receipt"]["kind"] == "paused_due_to_error"
    assert result["receipt"]["executed_ticks"] == 0
    owner = w["connection"]
    stored = owner.execute(
        "select current_tick, state_sha256 from world_society where workspace_id=%s "
        "and version_id=%s",
        (w["workspace"], w["binding"].version_id),
    ).fetchone()
    assert (stored["current_tick"], stored["state_sha256"]) == (
        before["current_tick"],
        before["state_sha256"],
    )
    transitions = owner.execute(
        "select count(*) as n from world_society_transition where workspace_id=%s",
        (w["workspace"],),
    ).fetchone()
    assert transitions["n"] == 0


def test_a_tombstone_written_while_a_round_computes_is_refused_and_the_round_commits(
    runtime_world, spine_schema, monkeypatch
):
    w = runtime_world
    _before, claim, database = _playing_round(w, spine_schema)
    workspace, actor = w["workspace"], w["session"].actor
    observer = connection_in(spine_schema, workspace)
    paused: list[Callable[[], None]] = []
    advance = SocietyRepository.advance

    def pausing(self, *args, **kwargs):
        # The round holds its workspace's lock here and asks for the barrier only at its end.
        if paused:
            paused.pop()()
        return advance(self, *args, **kwargs)

    monkeypatch.setattr(SocietyRepository, "advance", pausing)
    try:
        # The control: the round's asset read lock closes the cycle with the waiting tombstone.
        with refusal_planted_out(w["connection"]):
            flight: list[DeletionInFlight] = []
            paused.append(
                lambda: flight.append(DeletionInFlight(spine_schema, workspace, actor, observer))
            )
            try:
                with database.session(workspace) as connection:
                    controls(w, connection).execute(claim)
                ran = None
            except psycopg.errors.DeadlockDetected as exc:
                ran = exc
            assert deadlocks(ran, flight[0].finish()) == 1, (ran, flight[0].error)

        # A round the deadlock ended leaves its lease to run out; one that committed released it.
        if ran is not None:
            expire(w)
        overdue(w)
        claim = take_claim(w)
        refused: list[BaseException] = []

        def refuse() -> None:
            deleter = connection_in(spine_schema, workspace)
            try:
                deleter.execute("set lock_timeout = '5s'")
                write_tombstone(deleter, workspace, actor)
            except psycopg.Error as exc:
                refused.append(exc)
            finally:
                deleter.close()

        before = written(observer, workspace)
        paused.append(refuse)
        with database.session(workspace) as connection:
            result = controls(w, connection).execute(claim)
        assert [type(exc) for exc in refused] == [psycopg.errors.SerializationFailure], refused
        assert refused[0].diag.message_primary == REFUSAL
        assert result["receipt"]["kind"] == "advanced"
        assert result["receipt"]["executed_ticks"] == 3
        assert written(observer, workspace) == before
    finally:
        observer.close()


def test_a_guarded_write_between_the_authorization_and_the_commit_is_refused(
    runtime_world, spine_schema, monkeypatch
):
    w = runtime_world
    _before, claim, database = _playing_round(w, spine_schema)
    probes: list[str] = []
    event = SocietyControlRepository._event

    def probing(self, society, kind, details):
        # The receipt is written after the round's authorization and before its commit.
        if kind == "advanced":
            probes.append(_guarded_write(database, w["workspace"]))
        return event(self, society, kind, details)

    monkeypatch.setattr(SocietyControlRepository, "_event", probing)
    with database.session(w["workspace"]) as connection:
        result = controls(w, connection).execute(claim)
    assert result["receipt"]["executed_ticks"] == 3
    assert probes == [BUSY]
    # Once the round has committed, the same write commits.
    assert _guarded_write(database, w["workspace"]) == COMMITTED


def test_the_pause_a_refusal_at_the_end_writes_is_the_pause_a_refusal_at_the_start_writes(
    runtime_world, spine_schema, monkeypatch
):
    """The round's refusal comes after its minutes now; its receipt is the one a refusal before
    them writes, byte for byte, read on one clock from the same state."""
    w = runtime_world
    _before, claim, database = _playing_round(w, spine_schema)
    w["admissions"].withdraw("source", w["binding"].sources[0].admission_id)
    w["connection"].commit()
    instant = w["connection"].execute("select clock_timestamp() as now").fetchone()["now"]
    monkeypatch.setattr(
        SocietyControlRepository, "_now", lambda _self: instant + dt.timedelta(milliseconds=1)
    )

    def receipt() -> dict:
        with (
            database.session(w["workspace"]) as connection,
            connection.transaction(force_rollback=True),
        ):
            return controls(w, connection).execute(claim)["receipt"]

    at_the_end = receipt()

    def at_once(self, actor=None):
        # Each authorization run where it is asked for, as every round ran before.
        return SocietyRepository(
            self.connection,
            self.workspace_id,
            world_id=self.world_id,
            input_authorizer=None
            if self.input_authorizer is None or actor is None
            else lambda doc: self.input_authorizer(actor, doc),
        )

    monkeypatch.setattr(SocietyControlRepository, "_society", at_once)
    at_the_start = receipt()
    assert at_the_end["kind"] == "paused_due_to_error"
    assert at_the_end["reason"] == "source_unavailable"
    assert canonical_json(at_the_end) == canonical_json(at_the_start)


def test_a_round_authorizes_each_input_once_and_refuses_two_documents_under_one_digest(
    runtime_world, spine_schema, monkeypatch
):
    """Every input the minutes read reaches the runtime's authorization, once; a document read
    twice under one digest with different contents is refused before the lock."""
    w = runtime_world
    _before, claim, database = _playing_round(w, spine_schema)
    asked: list[str] = []

    def counting(connection):
        authorize = w["runtime"].authorize

        def authorizer(actor, document):
            asked.append(document["document_sha256"])
            authorize(connection, replace(w["session"], actor=actor), document)

        return authorizer

    with database.session(w["workspace"]) as connection:
        repository = controls(w, connection)
        repository.input_authorizer = counting(connection)
        result = repository.execute(claim)
    assert result["receipt"]["executed_ticks"] == 3
    assert asked and len(asked) == len(set(asked))

    from exulanica.world.society_control_repository import _RoundInputs

    twice = _RoundInputs()
    document = {"document_sha256": "a" * 64, "input_seq": 1}
    twice.record(claim.actor, document)
    twice.record(claim.actor, {**document, "input_seq": 2})
    with pytest.raises(ValueError, match="two different society inputs under one digest"):
        twice.authorize(w["connection"], lambda _actor, _document: None)
