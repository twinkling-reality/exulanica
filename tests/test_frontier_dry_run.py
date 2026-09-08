from __future__ import annotations

import hashlib
import json
import stat

import psycopg
import pytest
from exulanica.env import env_get
from exulanica.orchestration.demonstration import FrontierDemonstrationError
from exulanica.orchestration.dry_run import PERMITTED_DATABASE_URL, run_dry_run
from exulanica.world_package import verify_package
from exulanica.world_package.package import load_private_key

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not env_get("TEST_DATABASE_URL"), reason="requires permitted test database"),
]


def _public_state():
    # Observe retained rows without writing fixtures into public. The scratch lifecycle must
    # leave their exact values unchanged, including deletion state and screening authority.
    with psycopg.connect(PERMITTED_DATABASE_URL) as connection:
        connection.execute("set transaction read only")
        result = {}
        for table in (
            "capture",
            "artifact",
            "tombstone",
            "capture_reconstruction_authorization",
            "reconstruction_privacy_screening",
            "schema_migrations",
        ):
            rows = connection.execute(
                f"select row_to_json(t)::text from public.{table} t order by row_to_json(t)::text"
            ).fetchall()
            result[table] = hashlib.sha256(repr(rows).encode()).hexdigest()
        return result


def test_dry_run_keeps_public_and_sources_and_emits_three_verifiable_packages(tmp_path):
    before = _public_state()
    output = tmp_path / "rehearsal"
    result = run_dry_run(output)
    assert _public_state() == before
    assert result["isolated_schema_removed"] is True
    with psycopg.connect(PERMITTED_DATABASE_URL) as connection:
        assert (
            connection.execute(
                "select 1 from pg_namespace where nspname=%s", (result["isolated_schema"],)
            ).fetchone()
            is None
        )
    assert result["hosted_model_calls"] == 0
    key = output / "throwaway-key.pem"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    load_private_key(key)
    manifest = json.loads((output / "frontier-build.json").read_bytes())
    for source in manifest["sources"]:
        data = (output / "photos" / source["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == source["sha256"]
        assert len(data) == source["bytes"]
    receipt = json.loads((output / "run" / "frontier-receipt.json").read_bytes())
    assert receipt["repeat"]["ingest"]["stages_run"] == []
    assert receipt["repeat"]["ingest"]["model_calls"] == 0
    assert receipt["deletion"]["remaining_regions"] == 1
    assert receipt["deletion"]["original_photo_file_deleted"] is False
    for name in ("initial", "repeat", "after-deletion"):
        package = output / "run" / f"package-{name}"
        assert verify_package(package).merkle_root_sha256
        assert not list(package.rglob("*.pem"))
    key_before = key.read_bytes()
    with pytest.raises(FrontierDemonstrationError, match="output_boundary"):
        run_dry_run(output)
    assert key.read_bytes() == key_before


def test_failed_rehearsal_drops_only_its_owned_schema(tmp_path, monkeypatch):
    import exulanica.orchestration.dry_run as dry_run

    before = _public_state()
    schema = None

    def fail(connection, **kwargs):
        nonlocal schema
        schema = connection.execute("select current_schema() name").fetchone()["name"]
        raise RuntimeError("deliberate failure after synthetic intake")

    monkeypatch.setattr(dry_run, "run_frontier_demonstration", fail)
    output = tmp_path / "failed-rehearsal"
    with pytest.raises(RuntimeError, match="deliberate failure"):
        run_dry_run(output)
    assert schema and schema.startswith("exulanica_frontier_dry_")
    with psycopg.connect(PERMITTED_DATABASE_URL) as connection:
        assert (
            connection.execute("select 1 from pg_namespace where nspname=%s", (schema,)).fetchone()
            is None
        )
    assert _public_state() == before
    assert not (output / "dry-run-receipt.json").exists()
