"""Migration 0136: a day's comparison run is sealed hour by hour, and completes only as a day.

A schema of this test's own is migrated with the migrations exactly as they are on disk, 0136
included, and given comparisons whose definitions' own foreign keys are left out of the
arrangement (the society a real definition binds is not what 0136 changes): one over a window of
three hours and one over an hour, a run of each, and receipts. Every other rule, the checks and
the triggers of runs, receipts, hours and outcomes, runs as deployed. What is held: a run's hours
are sealed in order from its first, only of a run whose window is longer than an hour and inside
it, only while it has no outcome, each holding exactly the receipts recorded since the hour before
it; the state an hour ended in is the one its last minute's digest names, by the database's own
digest, as the bytes it stores are; each names its own run, arm, seed and first minute; a
sealed hour is never changed; a completed day is admitted only with every hour of its
window sealed and its last holding every receipt, and an hour's completed outcome never for a
day's run.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import pg_harness

pytestmark = pytest.mark.postgres

WORKSPACE = uuid.UUID("0136a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a5b")
WORLD = "world:authored:0136-migration"
SEED = "0136" * 16
DIGEST = hashlib.sha256(SEED.encode()).hexdigest()
DEFINITION = "exulanica.society-comparison/v2"
HOUR = "exulanica.society-comparison-hour/v1"
DAY_RUN, HOUR_RUN = "exulanica.society-comparison-run/v3", "exulanica.society-comparison-run/v2"


@contextmanager
def _migrated() -> Iterator[psycopg.Connection]:
    with pg_harness.migrated_schema() as (_psycopg, admin):
        admin.commit()
        admin.autocommit = True
        admin.row_factory = dict_row
        admin.execute("select set_config('exulanica.workspace_id', %s, false)", (str(WORKSPACE),))
        admin.execute(
            "insert into world_identity(workspace_id,world_id,kind,provenance,created_by) "
            "values(%s,%s,'authored-starter',%s,%s)",
            (WORKSPACE, WORLD, Jsonb({"origin": "test"}), uuid.uuid4()),
        )
        yield admin


def _sealed(document: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in document.items() if key != "document_sha256"}
    return {**body, "document_sha256": hashlib.sha256(json.dumps(body).encode()).hexdigest()}


def _definition(admin: psycopg.Connection, window_ticks: int) -> tuple[uuid.UUID, str]:
    comparison_id = uuid.uuid4()
    document = _sealed(
        {
            "profile": DEFINITION,
            "world_id": WORLD,
            "version_id": str(uuid.uuid4()),
            "society_id": str(uuid.uuid4()),
            "input": {"input_seq": 1, "document_sha256": "1" * 64},
            "window_ticks": window_ticks,
            "phase": "development",
            "seeds": [DIGEST],
            "arms": {"model_a": {"role": "candidate"}},
            "group": {
                "people": [{"id": str(uuid.uuid4()), "name": "A"}],
                "source": {"kind": "named"},
            },
            "others": [],
            "preregistration": None,
        }
    )
    admin.execute("set session_replication_role = replica")
    try:
        admin.execute(
            "insert into society_comparison(workspace_id,world_id,comparison_id,version_id,"
            "society_id,input_seq,input_sha256,document,document_sha256,created_by) "
            "values(%s,%s,%s,%s,%s,1,%s,%s,%s,%s)",
            (
                WORKSPACE,
                WORLD,
                comparison_id,
                uuid.UUID(document["version_id"]),
                uuid.UUID(document["society_id"]),
                "1" * 64,
                Jsonb(document),
                document["document_sha256"],
                uuid.uuid4(),
            ),
        )
    finally:
        admin.execute("set session_replication_role = origin")
    return comparison_id, document["document_sha256"]


def _run(admin: psycopg.Connection, comparison_id: uuid.UUID) -> uuid.UUID:
    run_id = uuid.uuid4()
    admin.execute(
        "insert into society_comparison_run(workspace_id,world_id,comparison_id,run_id,arm,seed,"
        "seed_digest,created_by) values(%s,%s,%s,%s,'model_a',%s,%s,%s)",
        (WORKSPACE, WORLD, comparison_id, run_id, SEED, DIGEST, uuid.uuid4()),
    )
    return run_id


def _receipt(admin: psycopg.Connection, comparison_id: uuid.UUID, run_id: uuid.UUID, seq: int):
    request_id, subject = uuid.uuid4(), uuid.uuid4()
    request = {
        "profile": "exulanica.society-decision-request/v2",
        "request_id": str(request_id),
        "subject_id": str(subject),
        "base_tick": seq,
        "document_sha256": hashlib.sha256(f"request:{seq}".encode()).hexdigest(),
    }
    receipt = {
        "profile": "exulanica.society-decision/v2",
        "request_id": str(request_id),
        "decision_seq": seq,
        "request_sha256": request["document_sha256"],
        "document_sha256": hashlib.sha256(f"receipt:{seq}".encode()).hexdigest(),
    }
    admin.execute(
        "insert into society_comparison_decision(workspace_id,world_id,comparison_id,run_id,"
        "decision_seq,request_id,subject_id,base_tick,request,request_sha256,receipt,"
        "receipt_sha256) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            WORKSPACE,
            WORLD,
            comparison_id,
            run_id,
            seq,
            request_id,
            subject,
            seq,
            Jsonb(request),
            request["document_sha256"],
            Jsonb(receipt),
            receipt["document_sha256"],
        ),
    )


def _state(hour: int) -> bytes:
    return json.dumps({"tick": (hour + 1) * 60}, separators=(",", ":"), sort_keys=True).encode()


def _hour(
    admin: psycopg.Connection,
    comparison_id: uuid.UUID,
    definition_sha256: str,
    run_id: uuid.UUID,
    hour: int,
    *,
    first_sequence: int,
    count: int,
    state: bytes | None = None,
    digest: str | None = None,
    stored: str | None = None,
    first_tick: int | None = None,
) -> None:
    state = _state(hour) if state is None else state
    last = hashlib.sha256(_state(hour)).hexdigest() if digest is None else digest
    document = _sealed(
        {
            "profile": HOUR,
            "definition_sha256": definition_sha256,
            "run_id": str(run_id),
            "arm": "model_a",
            "seed_digest": DIGEST,
            "hour": hour,
            "first_tick": hour * 60 if first_tick is None else first_tick,
            "minutes": {"count": 60, "state_sha256": ["0" * 64] * 59 + [last]},
            "receipts": {"count": count, "first_sequence": first_sequence},
        }
    )
    admin.execute(
        "insert into society_comparison_hour(workspace_id,world_id,comparison_id,run_id,hour,"
        "decision_seq_end,document,document_sha256,end_state,end_state_sha256) "
        "values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            WORKSPACE,
            WORLD,
            comparison_id,
            run_id,
            hour,
            first_sequence + count,
            Jsonb(document),
            document["document_sha256"],
            state,
            hashlib.sha256(state).hexdigest() if stored is None else stored,
        ),
    )


def _outcome(
    admin: psycopg.Connection,
    comparison_id: uuid.UUID,
    definition_sha256: str,
    run_id: uuid.UUID,
    profile: str,
    receipts: int,
) -> None:
    document = _sealed(
        {
            "profile": profile,
            "status": "completed",
            "run_id": str(run_id),
            "definition_sha256": definition_sha256,
            "arm": "model_a",
            "seed_digest": DIGEST,
            "receipts": {"count": receipts, "sha256": "2" * 64},
        }
    )
    admin.execute(
        "insert into society_comparison_outcome(workspace_id,world_id,comparison_id,run_id,"
        "status,document,document_sha256) values(%s,%s,%s,%s,'completed',%s,%s)",
        (WORKSPACE, WORLD, comparison_id, run_id, Jsonb(document), document["document_sha256"]),
    )


def _failure(
    admin: psycopg.Connection, comparison_id: uuid.UUID, definition_sha256: str, run_id: uuid.UUID
) -> None:
    document = _sealed(
        {
            "profile": "exulanica.society-comparison-failure/v1",
            "status": "failed",
            "run_id": str(run_id),
            "definition_sha256": definition_sha256,
            "arm": "model_a",
            "seed_digest": DIGEST,
            "code": "interrupted",
        }
    )
    admin.execute(
        "insert into society_comparison_outcome(workspace_id,world_id,comparison_id,run_id,"
        "status,document,document_sha256) values(%s,%s,%s,%s,'failed',%s,%s)",
        (WORKSPACE, WORLD, comparison_id, run_id, Jsonb(document), document["document_sha256"]),
    )


def _refused(action, *, message: str | None = None, constraint: str | None = None) -> None:
    with pytest.raises(psycopg.errors.CheckViolation) as refused:
        action()
    if message is not None:
        assert message in str(refused.value)
    if constraint is not None:
        assert refused.value.diag.constraint_name == constraint


def test_a_days_run_is_sealed_hour_by_hour_in_order_holding_its_receipts():
    with _migrated() as admin:
        day, day_sha = _definition(admin, 180)
        run = _run(admin, day)
        _receipt(admin, day, run, 1)
        _receipt(admin, day, run, 2)
        # The positive control: the first hour, holding both receipts, is sealed.
        _hour(admin, day, day_sha, run, 0, first_sequence=0, count=2)
        # The next hour out of order, an hour that skips one, or an hour past the window.
        _refused(
            lambda: _hour(admin, day, day_sha, run, 2, first_sequence=2, count=0),
            message="sealed in order",
        )
        _refused(
            lambda: _hour(admin, day, day_sha, run, 0, first_sequence=0, count=2),
            message="sealed in order",
        )
        # An hour that holds other receipts than those recorded since the hour before it.
        _receipt(admin, day, run, 3)
        _refused(
            lambda: _hour(admin, day, day_sha, run, 1, first_sequence=2, count=0),
            message="exactly the receipts",
        )
        _refused(
            lambda: _hour(admin, day, day_sha, run, 1, first_sequence=1, count=2),
            message="exactly the receipts",
        )
        _hour(admin, day, day_sha, run, 1, first_sequence=2, count=1)
        # A state whose digest is not the hour's last minute's, bytes that are not the digest
        # they are stored under, and an hour that names another first minute than its own.
        _refused(
            lambda: _hour(admin, day, day_sha, run, 2, first_sequence=3, count=0, state=b"{}"),
            constraint="society_comparison_hour_state_is_its_last_minute",
        )
        _refused(
            lambda: _hour(
                admin,
                day,
                day_sha,
                run,
                2,
                first_sequence=3,
                count=0,
                state=b"{}",
                stored=hashlib.sha256(_state(2)).hexdigest(),
            ),
            constraint="society_comparison_hour_state_digest",
        )
        _refused(
            lambda: _hour(admin, day, day_sha, run, 2, first_sequence=3, count=0, first_tick=0),
            message="names its own run",
        )
        _hour(admin, day, day_sha, run, 2, first_sequence=3, count=0)
        # Past the window's three hours.
        _refused(
            lambda: _hour(admin, day, day_sha, run, 3, first_sequence=3, count=0),
            message="inside its window",
        )
        # A sealed hour is never changed.
        with pytest.raises(psycopg.errors.CheckViolation, match="appended, never changed"):
            admin.execute("update society_comparison_hour set recorded_at=now() where hour=0")
        with pytest.raises(psycopg.errors.CheckViolation, match="appended, never changed"):
            admin.execute("delete from society_comparison_hour where hour=0")


def test_only_a_days_run_seals_hours_and_a_day_completes_only_with_every_hour_sealed():
    with _migrated() as admin:
        hour_window, hour_sha = _definition(admin, 60)
        run_of_hour = _run(admin, hour_window)
        _refused(
            lambda: _hour(admin, hour_window, hour_sha, run_of_hour, 0, first_sequence=0, count=0),
            message="only of a day's run",
        )
        day, day_sha = _definition(admin, 120)
        run = _run(admin, day)
        _receipt(admin, day, run, 1)
        _hour(admin, day, day_sha, run, 0, first_sequence=0, count=1)
        # A day with an hour unsealed does not complete, nor does a day recorded as an hour's.
        _refused(
            lambda: _outcome(admin, day, day_sha, run, DAY_RUN, 1),
            message="outcome binding mismatch",
        )
        _hour(admin, day, day_sha, run, 1, first_sequence=1, count=0)
        _refused(
            lambda: _outcome(admin, day, day_sha, run, HOUR_RUN, 1),
            message="outcome binding mismatch",
        )
        # The positive control: every hour sealed, its last holding every receipt.
        _outcome(admin, day, day_sha, run, DAY_RUN, 1)
        # Once it has an outcome, a run seals no further hour and takes no further receipt.
        _refused(lambda: _receipt(admin, day, run, 2), message="takes no further receipts")
        # A run that failed part way seals no further hour.
        stopped, stopped_sha = _definition(admin, 120)
        failed = _run(admin, stopped)
        _hour(admin, stopped, stopped_sha, failed, 0, first_sequence=0, count=0)
        _failure(admin, stopped, stopped_sha, failed)
        _refused(
            lambda: _hour(admin, stopped, stopped_sha, failed, 1, first_sequence=0, count=0),
            message="seals no further hour",
        )
        # An hour's run never completes as a day.
        _refused(
            lambda: _outcome(admin, hour_window, hour_sha, run_of_hour, DAY_RUN, 0),
            message="outcome binding mismatch",
        )
        _outcome(admin, hour_window, hour_sha, run_of_hour, HOUR_RUN, 0)
