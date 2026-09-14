"""Resolved auth/application connections must reach the same database and effective schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from exulanica.api.account_repository import AccountUnavailable
from exulanica.api.account_runtime import AccountRuntime, GoogleAccountConfig, GoogleOIDCProvider
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from account_fixtures import account_role as account_role
from tests_support_api import scratch_database

pytestmark = pytest.mark.postgres


def _runtime(database_url: str) -> AccountRuntime:
    config = GoogleAccountConfig(
        client_id="binding-test-client",
        client_secret="binding-test-secret",
        callback_uri="https://account.test/auth/google/callback",
        return_uris=("https://account.test/world",),
        browser_origins=("https://account.test",),
    )
    return AccountRuntime(config, database_url, GoogleOIDCProvider(config))


def _service(path: Path, name: str, values: dict[str, str]) -> None:
    lines = [f"[{name}]"]
    for key in ("host", "hostaddr", "port", "dbname", "user", "password", "options"):
        if value := values.get(key):
            lines.append(f"{key}={value}")
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def test_distinct_service_names_are_resolved_before_database_binding(
    account_role: str, spine_schema, tmp_path, monkeypatch
) -> None:
    application_url = scratch_database(spine_schema[1]).url
    account = conninfo_to_dict(account_role)
    application = conninfo_to_dict(application_url)
    service_file = tmp_path / "pg_service.conf"
    _service(service_file, "account", account)
    _service(service_file, "application", application)
    monkeypatch.setenv("PGSERVICEFILE", str(service_file))

    runtime = _runtime("service=account")
    runtime.verify_database("service=application")

    # The DSNs still look like two opaque service names, but this one resolves a different schema.
    divergent = {**application, "options": "-csearch_path=public"}
    _service(service_file, "different_schema", divergent)
    with pytest.raises(AccountUnavailable, match="same database/schema"):
        runtime.verify_database("service=different_schema")


def test_direct_urls_with_different_effective_schema_are_rejected(
    account_role: str, spine_schema
) -> None:
    runtime = _runtime(account_role)
    application = conninfo_to_dict(scratch_database(spine_schema[1]).url)
    application["options"] = "-csearch_path=public"

    with pytest.raises(AccountUnavailable, match="same database/schema"):
        runtime.verify_database(make_conninfo(**application))
