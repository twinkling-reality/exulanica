"""The frontier dry run refuses a reference connection that is not a superuser, before it makes a
schema: the definer migration creates a server-wide role and hands it the definer functions, which
only a superuser may do, so a non-superuser would fail part way through the migrations instead."""

from __future__ import annotations

import pytest
from exulanica.orchestration import dry_run
from exulanica.orchestration.demonstration import FrontierDemonstrationError


class _Owner:
    def __init__(self, superuser: str) -> None:
        self.superuser = superuser
        self.statements: list[str] = []
        self.info = type("Info", (), {"dbname": dry_run.COPY_DATABASE, "server_version": 180004})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, *args):
        text = str(statement)
        self.statements.append(text)
        if "pg_extension" in text:
            rows = [(name,) for name in dry_run._REQUIRED_EXTENSIONS]
        elif "is_superuser" in text:
            rows = [(self.superuser,)]
        else:
            rows = []
        return type("Result", (), {"fetchall": lambda _: rows, "fetchone": lambda _: rows[0]})()


def test_a_reference_connection_that_is_not_a_superuser_is_refused_before_any_schema(monkeypatch):
    owner = _Owner("off")
    monkeypatch.setattr(dry_run, "writable_reference_url", lambda: "postgresql://reference")
    monkeypatch.setattr(dry_run.psycopg, "connect", lambda *args, **kwargs: owner)
    with (
        pytest.raises(FrontierDemonstrationError, match="superuser"),
        dry_run._scratch_database(),
    ):
        pass
    assert not any("create schema" in statement.lower() for statement in owner.statements)
