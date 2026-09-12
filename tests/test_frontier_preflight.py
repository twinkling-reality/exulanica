"""The preflight must expose independent blockers without doing the run's writes."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.orchestration.cli import main
from exulanica.orchestration.preflight import permitted_database_url, run_frontier_preflight

from test_frontier_manifest import _document


def _inputs(root: Path):
    photos = root / "photos"
    photos.mkdir()
    (photos / "a.jpg").write_bytes(b"generated-a")
    (photos / "b.jpg").write_bytes(b"generated-b")
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(_document(photos)))
    key = root / "key.pem"
    key.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key.chmod(0o600)
    return dict(
        manifest_path=manifest,
        photo_dir=photos,
        data_dir=root / "data",
        output=root / "output",
        private_key=key,
    )


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _argv(inputs, command="preflight"):
    args = [command]
    for key, value in inputs.items():
        args.extend(["--" + key.replace("manifest_path", "manifest").replace("_", "-"), str(value)])
    return args


def test_preflight_reports_all_independent_failures_without_writing(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    inputs["private_key"].write_bytes(b"not a signing key")
    (inputs["photo_dir"] / "a.jpg").unlink()
    inputs["output"].mkdir()
    (inputs["output"] / "sentinel").write_bytes(b"preserve")
    monkeypatch.delenv("EXULANICA_DATABASE_URL", raising=False)
    before = _snapshot(tmp_path)
    result = run_frontier_preflight(**inputs)
    failed = {item["check"] for item in result["checks"] if item["status"] == "failed"}
    assert failed >= {"photos", "signing_key", "write_boundary", "database_environment"}
    assert all(item["action"] for item in result["checks"] if item["status"] == "failed")
    assert _snapshot(tmp_path) == before
    assert not inputs["data_dir"].exists()


@pytest.mark.postgres
def test_preflight_checks_real_schema_without_ingesting_or_creating_outputs(cli_database, tmp_path):
    inputs = _inputs(tmp_path)
    before = _snapshot(tmp_path)
    stream = io.StringIO()
    assert main(_argv(inputs), stream=stream) == 0
    report = json.loads(stream.getvalue())
    assert report["read_only"] and report["status"] == "passed"
    schema = next(c for c in report["checks"] if c["check"] == "database_schema_and_screening")
    assert schema["detail"]["schema"] != "public"
    assert schema["detail"]["migration_count"] >= 38
    assert _snapshot(tmp_path) == before
    assert not inputs["data_dir"].exists() and not inputs["output"].exists()


def test_demonstrate_refusal_never_adds_terminal_file_to_existing_output(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    inputs["output"].mkdir()
    (inputs["output"] / "sentinel").write_bytes(b"existing export")
    before = _snapshot(tmp_path)
    monkeypatch.delenv("EXULANICA_DATABASE_URL", raising=False)
    assert main([*_argv(inputs, "demonstrate"), "--confirm-source-deletion"]) == 1
    assert _snapshot(tmp_path) == before


def test_hosted_vision_needs_per_run_authority_before_setup_or_writes(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    document = json.loads(inputs["manifest_path"].read_text())
    document["pipeline"]["vision"] = "configured"
    inputs["manifest_path"].write_text(json.dumps(document))
    from exulanica.orchestration import cli

    monkeypatch.setattr(cli, "_vision_model", lambda *args: pytest.fail("hosted setup ran"))
    before = _snapshot(tmp_path)
    assert main([*_argv(inputs, "demonstrate"), "--confirm-source-deletion"]) == 1
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "url",
    [
        None,
        "postgresql://localhost:5433/orimera",
        "postgresql://localhost:5432/exulanica_spine_test",
        "postgresql://remote:5433/exulanica_spine_test",
        "host=localhost hostaddr=192.0.2.1 port=5433 dbname=exulanica_spine_test",
    ],
)
def test_wrong_database_is_refused_before_connection(url):
    with pytest.raises(ValueError):
        permitted_database_url(url)


def test_preflight_refuses_writes_beneath_photo_directory(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    inputs["data_dir"] = inputs["photo_dir"] / "data"
    monkeypatch.delenv("EXULANICA_DATABASE_URL", raising=False)
    report = run_frontier_preflight(**inputs)
    assert any(c["check"] == "write_boundary" and c["status"] == "failed" for c in report["checks"])
    assert not inputs["data_dir"].exists()


def test_preflight_checks_capacity_without_reserving_or_writing_space(tmp_path, monkeypatch):
    from collections import namedtuple

    from exulanica.orchestration import preflight

    inputs = _inputs(tmp_path)
    monkeypatch.delenv("EXULANICA_DATABASE_URL", raising=False)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda path: usage(100, 99, 1))
    report = run_frontier_preflight(**inputs)
    assert any(c["check"] == "disk_headroom" and c["status"] == "failed" for c in report["checks"])
    assert not inputs["output"].exists()


def test_preflight_rejects_store_symlink_into_original_photos(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    inputs["data_dir"].mkdir()
    (inputs["data_dir"] / "blobs").symlink_to(inputs["photo_dir"], target_is_directory=True)
    monkeypatch.delenv("EXULANICA_DATABASE_URL", raising=False)
    before = _snapshot(inputs["photo_dir"])
    report = run_frontier_preflight(**inputs)
    assert any(c["check"] == "write_boundary" and c["status"] == "failed" for c in report["checks"])
    assert _snapshot(inputs["photo_dir"]) == before


@pytest.mark.parametrize("name", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"])
def test_libpq_environment_cannot_redirect_the_permitted_database(name, monkeypatch):
    monkeypatch.setenv(name, "unexpected-route")
    with pytest.raises(ValueError, match="Unset"):
        permitted_database_url("postgresql://localhost:5433/exulanica_inspect_test")


def test_pinned_database_configuration_can_be_checked_again(monkeypatch):
    monkeypatch.setenv(
        "EXULANICA_REFERENCE_DATABASE_URL", "postgresql://localhost:5433/exulanica_inspect_test"
    )
    for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
        monkeypatch.delenv(name, raising=False)
    pinned = permitted_database_url("postgresql://localhost:5433/exulanica_inspect_test")
    from psycopg.conninfo import conninfo_to_dict

    assert conninfo_to_dict(permitted_database_url(pinned)) == conninfo_to_dict(pinned)
