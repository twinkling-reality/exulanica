"""The comparison worker's own process checks its database before it claims anything.

``python -m exulanica.orchestration.comparison_worker`` builds the API's services and plays the
comparisons started from the application. Before it builds the worker that claims them, it verifies
the migrations the database records against the package's own and refuses a connection for which
row-level security is no boundary, as the API and the derivative workers do at their start. The
services are stood in for: what is held is that each check reads the services' own database, and
that a failure of either builds no worker, so nothing is claimed.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from exulanica.db.roles import RuntimeRoleUnsafe
from exulanica.orchestration import comparison_worker


class _Database:
    def __init__(self) -> None:
        self.connections: list[object] = []

    @contextmanager
    def unscoped(self) -> Iterator[object]:
        connection = object()
        self.connections.append(connection)
        yield connection


class _Worker:
    def __init__(self) -> None:
        self.played = 0

    def run(self, stop: Any) -> None:
        del stop
        self.played += 1


class _Services:
    def __init__(self) -> None:
        self.database = _Database()
        self.worker = _Worker()
        self.built = 0

    def build_comparison_worker(self, *, keeps_share: bool) -> _Worker:
        assert keeps_share is False
        self.built += 1
        return self.worker


def _started(
    monkeypatch: pytest.MonkeyPatch,
    *,
    schema: Exception | None = None,
    role: Exception | None = None,
) -> tuple[_Services, list[tuple[str, object]]]:
    services = _Services()
    checked: list[tuple[str, object]] = []

    def verify_schema(database: object) -> None:
        checked.append(("schema", database))
        if schema is not None:
            raise schema

    def assert_runtime_role(connection: object) -> None:
        checked.append(("role", connection))
        if role is not None:
            raise role

    monkeypatch.setattr(comparison_worker, "build_services", lambda **_: services)
    monkeypatch.setattr(comparison_worker, "verify_schema", verify_schema)
    monkeypatch.setattr(comparison_worker, "assert_runtime_role", assert_runtime_role)
    monkeypatch.setattr(comparison_worker.signal, "signal", lambda *_: None)
    return services, checked


def test_the_worker_plays_only_after_its_database_and_role_are_checked(monkeypatch):
    # The positive control: both checks hold, so the worker is built and plays.
    services, checked = _started(monkeypatch)
    assert comparison_worker.main([]) == 0
    assert checked == [("schema", services.database), ("role", services.database.connections[0])]
    assert (services.built, services.worker.played) == (1, 1)


@pytest.mark.parametrize(
    ("schema", "role"),
    [
        (RuntimeError("schema drift, refusing to start"), None),
        (None, RuntimeRoleUnsafe("database role owner is SUPERUSER")),
    ],
    ids=["schema-drift", "unsafe-role"],
)
def test_a_drifted_schema_or_an_unsafe_role_builds_no_worker(monkeypatch, schema, role):
    services, _checked = _started(monkeypatch, schema=schema, role=role)
    with pytest.raises(type(schema or role)):
        comparison_worker.main([])
    assert (services.built, services.worker.played) == (0, 0)
