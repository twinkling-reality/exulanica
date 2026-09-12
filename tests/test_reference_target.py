"""Writable reference runs cannot fall back or redirect to retained data."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from exulanica.db.reference_target import (
    COPY_URL,
    REFERENCE_OVERRIDE,
    validate_reference_url,
    writable_reference_url,
)
from exulanica.orchestration.dry_run import run_dry_run
from psycopg.conninfo import conninfo_to_dict

RETAINED = "postgresql://localhost:5433/exulanica_spine_test"


@pytest.fixture(autouse=True)
def clean_routing(monkeypatch):
    for name in (REFERENCE_OVERRIDE, "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    "override", [None, RETAINED, "postgresql://remote:5433/exulanica_inspect_test"]
)
def test_unsafe_rehearsal_refuses_before_files_or_connection(override, tmp_path, monkeypatch):
    if override:
        monkeypatch.setenv(REFERENCE_OVERRIDE, override)
    import exulanica.orchestration.dry_run as dry_run

    monkeypatch.setattr(
        dry_run.psycopg, "connect", lambda *a, **k: pytest.fail("connection opened")
    )
    with pytest.raises(ValueError):
        run_dry_run(tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_retained_inspection_enforces_read_only_without_allowing_rehearsal(monkeypatch):
    parts = conninfo_to_dict(validate_reference_url(RETAINED, read_only=True))
    assert parts["dbname"] == "exulanica_spine_test"
    assert parts["hostaddr"] == "127.0.0.1"
    assert parts["options"].endswith("-cdefault_transaction_read_only=on")
    monkeypatch.setenv(REFERENCE_OVERRIDE, RETAINED)
    with pytest.raises(ValueError):
        writable_reference_url()


@pytest.mark.parametrize(
    "url",
    [
        RETAINED,
        "postgresql://localhost:5432/exulanica_inspect_test",
        "postgresql://remote:5433/exulanica_inspect_test",
        "host=localhost port=5433 dbname=exulanica_inspect_test hostaddr=192.0.2.1",
        "host=localhost port=5433 dbname=exulanica_inspect_test service=other",
        "postgresql://localhost:5433/exulanica_inspect_test?password=secret&invalid=value",
    ],
)
def test_explicit_copy_does_not_silently_retarget_an_unsafe_caller(url, monkeypatch):
    monkeypatch.setenv(REFERENCE_OVERRIDE, COPY_URL)
    with pytest.raises(ValueError) as exc:
        writable_reference_url(url)
    assert "secret" not in str(exc.value)


def test_copy_keeps_owned_schema_and_pins_host(monkeypatch):
    monkeypatch.setenv(REFERENCE_OVERRIDE, COPY_URL)
    url = COPY_URL + "?options=-csearch_path%3Dtest_owned%2Cpublic"
    parts = conninfo_to_dict(writable_reference_url(url))
    assert parts["options"] == "-csearch_path=test_owned,public"
    assert parts["hostaddr"] == "127.0.0.1"
    assert parts["dbname"] == "exulanica_inspect_test"


@pytest.mark.parametrize("name", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"])
def test_environment_redirect_is_refused(name, monkeypatch):
    monkeypatch.setenv(REFERENCE_OVERRIDE, COPY_URL)
    monkeypatch.setenv(name, "untrusted")
    with pytest.raises(ValueError, match="Unset"):
        writable_reference_url()


def test_reference_launcher_uses_shared_routing_and_preserves_read_role_options(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/reference_instance.py"
    spec = importlib.util.spec_from_file_location("reference_instance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(SystemExit):
        module.resolve_database()
    monkeypatch.setenv(REFERENCE_OVERRIDE, COPY_URL + "?options=-csearch_path%3Downed%2Cpublic")
    resolved = module.resolve_database()
    assert resolved == writable_reference_url()
    parts = conninfo_to_dict(module.readonly_url(resolved))
    assert parts["options"] == "-csearch_path=owned,public -crole=exulanica_ro"
