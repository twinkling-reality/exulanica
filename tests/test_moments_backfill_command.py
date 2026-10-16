"""The moments back-fill command's own checks, with a stand-in database and replay (no PostgreSQL).

Before it reads anything it checks the schema, the role and a restore, and refuses by name, writing
nothing. ``--version`` back-fills that version's society alone and names a version the workspace has
no society for. A database error in one society is that society's refusal: its transaction rolls
back and the run goes on to the next, ending as refused rather than as a failure to start.
"""

from __future__ import annotations

import contextlib
import io
import json
import uuid
from types import SimpleNamespace

import psycopg
import pytest
from exulanica.api import moments_backfill
from exulanica.db import migrate, roles
from exulanica.deletion import restore

WORKSPACE = uuid.UUID("11111111-1111-4111-8111-111111111111")
FIRST, SECOND = uuid.UUID(int=1), uuid.UUID(int=2)
THINGS = "exulanica-society/v7"


class _Rows:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict]:
        return self.rows

    def fetchone(self) -> dict | None:
        return self.rows[0] if self.rows else None


class _Connection:
    """The two reads the command makes, and a transaction that rolls back on psycopg.Rollback."""

    def __init__(self) -> None:
        self.moments = 0
        self.societies = [
            {
                "society_id": uuid.UUID(int=10 + n),
                "world_id": f"world:{n}",
                "version_id": version,
                "engine_version": THINGS,
                "current_tick": 4,
            }
            for n, version in enumerate((FIRST, SECOND))
        ]

    def execute(self, sql: str, _params: tuple = ()) -> _Rows:
        if "from world_society where" in sql:
            return _Rows(self.societies)
        if "count(*) as moments" in sql:
            return _Rows([{"moments": self.moments}])
        raise AssertionError(sql)

    @contextlib.contextmanager
    def transaction(self):
        kept = self.moments
        try:
            yield
        except psycopg.Rollback:
            self.moments = kept


class _Database:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    @contextlib.contextmanager
    def session(self, _workspace: uuid.UUID):
        yield self.connection

    @contextlib.contextmanager
    def unscoped(self):
        yield self.connection


@pytest.fixture
def stand_in(monkeypatch):
    connection = _Connection()
    checked: list[str] = []
    monkeypatch.setattr(migrate, "verify_schema", lambda _database: checked.append("schema"))
    monkeypatch.setattr(roles, "assert_runtime_role", lambda _connection: checked.append("role"))
    monkeypatch.setattr(restore, "verify_restore", lambda *_args: checked.append("restore"))
    replayed: list[uuid.UUID] = []

    def backfill(_replay, held, _workspace, society, version):
        replayed.append(version)
        held.moments += 3
        return society["current_tick"]

    monkeypatch.setattr(moments_backfill, "backfill", backfill)
    services = SimpleNamespace(
        database=_Database(connection), society_runtime=object(), restore_state_path=None
    )
    return SimpleNamespace(services=services, checked=checked, replayed=replayed)


def _run(services, *arguments: str) -> tuple[int, list[dict]]:
    output = io.StringIO()
    code = moments_backfill.main(
        ["--workspace", str(WORKSPACE), *arguments], services=services, stream=output
    )
    return code, [json.loads(line) for line in output.getvalue().splitlines()]


def test_every_society_is_back_filled_after_the_schema_role_and_restore_are_checked(stand_in):
    code, lines = _run(stand_in.services, "--apply")
    assert code == 0, lines
    assert stand_in.checked == ["schema", "role", "restore"]
    assert stand_in.replayed == [FIRST, SECOND]
    assert [line["outcome"] for line in lines if line["event"] == "society"] == ["written"] * 2
    assert lines[-1]["event"] == "finished" and lines[-1]["moments"] == 6


@pytest.mark.parametrize("refused", ["schema", "role", "restore"])
def test_a_check_that_refuses_writes_nothing_and_says_it_did_not_start(
    stand_in, monkeypatch, refused
):
    def refuse(*_args):
        raise RuntimeError(f"{refused} refused")

    target = {
        "schema": (migrate, "verify_schema"),
        "role": (roles, "assert_runtime_role"),
        "restore": (restore, "verify_restore"),
    }[refused]
    monkeypatch.setattr(*target, refuse)
    code, lines = _run(stand_in.services, "--apply")
    assert (code, [line["event"] for line in lines]) == (1, ["startup_failed"])
    assert lines[0]["message"] == f"{refused} refused"
    assert stand_in.replayed == []


def test_a_named_version_alone_is_back_filled_and_an_unknown_one_is_named(stand_in):
    missing = uuid.UUID(int=99)
    code, lines = _run(
        stand_in.services, "--apply", "--version", str(SECOND), "--version", str(missing)
    )
    societies = [line for line in lines if line["event"] == "society"]
    assert stand_in.replayed == [SECOND]
    assert [(line["version_id"], line["outcome"]) for line in societies] == [
        (str(SECOND), "written"),
        (str(missing), "refused"),
    ]
    assert societies[1]["reason"] == "no_society_for_version"
    assert code == 1, "a named version with no society is a refusal"


def test_a_database_error_in_one_society_refuses_it_and_the_others_are_back_filled(
    stand_in, monkeypatch
):
    def backfill(_replay, held, _workspace, society, version):
        if version == FIRST:
            raise psycopg.errors.InFailedSqlTransaction("the society's statements were refused")
        held.moments += 3
        return society["current_tick"]

    monkeypatch.setattr(moments_backfill, "backfill", backfill)
    code, lines = _run(stand_in.services, "--apply")
    societies = [line for line in lines if line["event"] == "society"]
    assert [(line["version_id"], line["outcome"]) for line in societies] == [
        (str(FIRST), "refused"),
        (str(SECOND), "written"),
    ]
    assert societies[0]["reason"] == "InFailedSqlTransaction"
    assert (code, lines[-1]["event"], lines[-1]["refused"]) == (1, "finished", 1)


def test_a_dry_run_rolls_every_society_back(stand_in):
    code, lines = _run(stand_in.services)
    assert code == 0
    assert [line["outcome"] for line in lines if line["event"] == "society"] == ["would_write"] * 2
    assert stand_in.services.database.connection.moments == 0, "nothing kept"
