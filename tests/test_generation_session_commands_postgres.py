"""The operator's session commands against a migrated database, and who may write the register.

The session is warm session 1's own record (``ml/appearance/evidence/generated-assets-session-1``)
with a manifest built for it from its job's components and container. The commands run as the
command line does, from ``EXULANICA_DATABASE_URL`` (the administrative URL); the runtime role reads
the register and writes none of it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.generation.__main__ import main
from exulanica_pieces.canonical import canonical_bytes, sha256_hex
from exulanica_pieces.queue import build_session, build_session_manifest
from exulanica_pieces.records import read_job

from conftest import scratch_role_database

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
SESSION_1 = ROOT / "ml/appearance/evidence/generated-assets-session-1"
COMPUTE_KEY = "nebius-ai-cloud-rtx-pro-6000"


def _record_with_nonce() -> bytes:
    """Session 1's record as the tooling now writes it: the same settings and a fresh nonce."""
    first = json.loads((SESSION_1 / "session.json").read_bytes())
    return build_session(
        route=first["route"],
        code_sha256=first["code_sha256"],
        idle_seconds=first["idle_seconds"],
        stop_seconds=first["stop_seconds"],
        nonce="1f" * 16,
    )


@pytest.fixture
def files(tmp_path):
    session_raw = _record_with_nonce()
    job = read_job(min((SESSION_1 / "jobs").glob("*.json")).read_bytes())
    session = tmp_path / "session.json"
    session.write_bytes(session_raw)
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(
        build_session_manifest(
            session_raw, components_sha256=job["components_sha256"], container=job["container"]
        )
    )
    return session, manifest, sha256_hex(session_raw)


def _run(capsys, *argv: str) -> tuple[int, dict]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, json.loads(captured.out if code == 0 else captured.err)


def _open(capsys, session: Path, manifest: Path, *, key=COMPUTE_KEY, by="ops", hours="2"):
    return _run(
        capsys,
        "session",
        "open",
        "--session",
        str(session),
        "--manifest",
        str(manifest),
        "--compute-key",
        key,
        "--job-id",
        "aijob-test",
        "--by",
        by,
        "--window-hours",
        hours,
    )


def test_a_session_is_opened_listed_and_closed_once(cli_database, files, capsys, tmp_path) -> None:
    session, manifest, session_sha256 = files
    code, opened = _open(capsys, session, manifest)
    assert code == 0 and opened["session_sha256"] == session_sha256
    code, status = _run(capsys, "session", "status")
    assert code == 0
    assert [row["generation_session_id"] for row in status["open"]] == [
        opened["generation_session_id"]
    ]
    assert status["open"][0]["compute_key"] == COMPUTE_KEY
    gpu_run = tmp_path / "gpu-run.json"
    gpu_run.write_bytes(b'{"record":"a gpu run"}')
    code, closed = _run(
        capsys,
        "session",
        "close",
        "--id",
        opened["generation_session_id"],
        "--reason",
        "idle",
        "--gpu-run",
        str(gpu_run),
    )
    assert code == 0 and closed["generation_session_id"] == opened["generation_session_id"]
    assert _run(capsys, "session", "status") == (0, {"open": []})
    code, refused = _run(
        capsys, "session", "close", "--id", opened["generation_session_id"], "--reason", "idle"
    )
    assert code == 2 and refused == {"refused": "no open session has that id"}
    with psycopg.connect(_url(), autocommit=True) as connection:
        row = connection.execute(
            "select close_reason, gpu_run_sha256, window_ends_at - opened_at "
            "from generation_session where generation_session_id = %s",
            (uuid.UUID(opened["generation_session_id"]),),
        ).fetchone()
    assert row[0] == "idle"
    assert row[1] == hashlib.sha256(gpu_run.read_bytes()).hexdigest()
    assert row[2].total_seconds() == 2 * 3600


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        ({"key": "a-gpu-nobody-measured"}, "is not a GPU the piece compute catalog names"),
        ({"by": "Ops Person <ops@example.org>"}, "--by is a label"),
        ({"hours": "0"}, "at most 24 hours"),
        ({"hours": "25"}, "at most 24 hours"),
    ],
)
def test_an_open_the_register_cannot_hold_is_refused_and_writes_nothing(
    cli_database, files, capsys, change, refusal
) -> None:
    session, manifest, _ = files
    code, refused = _open(capsys, session, manifest, **change)
    assert code == 2 and refusal in refused["refused"]
    assert _run(capsys, "session", "status") == (0, {"open": []})


def test_a_manifest_of_another_session_is_refused(cli_database, files, capsys, tmp_path) -> None:
    session, manifest, _ = files
    other = tmp_path / "other-manifest.json"
    other.write_bytes(
        canonical_bytes({**json.loads(manifest.read_bytes()), "session_sha256": "0" * 64})
    )
    code, refused = _open(capsys, session, other)
    assert code == 2 and "another session record" in refused["refused"]


def test_a_session_of_a_route_no_piece_request_takes_is_refused(
    cli_database, capsys, tmp_path
) -> None:
    # Piece requests take route A (the recipes' object route); a route S session could build no
    # job of them, so every request would stay waiting behind it.
    job = read_job(min((SESSION_1 / "jobs").glob("*.json")).read_bytes())
    raw = build_session(
        route="S", code_sha256=job["code_sha256"], stop_seconds=1800, nonce="2f" * 16
    )
    session = tmp_path / "session-s.json"
    session.write_bytes(raw)
    other = tmp_path / "manifest-s.json"
    other.write_bytes(
        build_session_manifest(
            raw, components_sha256=job["components_sha256"], container=job["container"]
        )
    )
    code, refused = _open(capsys, session, other)
    assert code == 2 and "piece requests take route A" in refused["refused"]
    assert _run(capsys, "session", "status") == (0, {"open": []})


def test_a_session_record_without_a_nonce_is_refused(cli_database, capsys, tmp_path) -> None:
    # Session 1's own record carries none: two sessions with its settings would share a digest.
    raw = (SESSION_1 / "session.json").read_bytes()
    job = read_job(min((SESSION_1 / "jobs").glob("*.json")).read_bytes())
    session = tmp_path / "session-1.json"
    session.write_bytes(raw)
    manifest = tmp_path / "manifest-1.json"
    manifest.write_bytes(
        build_session_manifest(
            raw, components_sha256=job["components_sha256"], container=job["container"]
        )
    )
    code, refused = _open(capsys, session, manifest)
    assert code == 2 and "carries no nonce" in refused["refused"]
    assert _run(capsys, "session", "status") == (0, {"open": []})


def test_a_session_record_is_registered_once(cli_database, files, capsys) -> None:
    session, manifest, _ = files
    assert _open(capsys, session, manifest)[0] == 0
    code, refused = _open(capsys, session, manifest)
    assert code == 2 and "registered already" in refused["refused"]
    code, status = _run(capsys, "session", "status")
    assert code == 0 and len(status["open"]) == 1


def test_the_runtime_role_reads_the_register_and_writes_none_of_it(
    cli_database, spine_schema, files, capsys
) -> None:
    session, manifest, _ = files
    _, opened = _open(capsys, session, manifest)
    session_id = uuid.UUID(opened["generation_session_id"])
    with psycopg.connect(_url(), autocommit=True) as connection:
        provision_runtime_role(connection, role=RUNTIME_ROLE)
    runtime = scratch_role_database(spine_schema[1], RUNTIME_ROLE)
    with runtime.unscoped() as connection:
        [row] = connection.execute(
            "select generation_session_id from generation_session"
        ).fetchall()
        assert row["generation_session_id"] == session_id
    for statement, params in (
        ("update generation_session set close_reason = 'idle', closed_at = now()", ()),
        ("delete from generation_session", ()),
        (
            "insert into generation_session select * from generation_session "
            "where generation_session_id = %s",
            (session_id,),
        ),
    ):
        # The grant refuses first: the role registry withholds every write on the register.
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"),
            runtime.unscoped() as connection,
        ):
            connection.execute(statement, params)
    # The register's own trigger refuses a writer that is no member of its owner even when a
    # grant lets the statement through, so a widened grant still writes nothing.
    with psycopg.connect(_url(), autocommit=True) as connection:
        connection.execute(f"grant insert, update, delete on generation_session to {RUNTIME_ROLE}")
    try:
        for statement in (
            "update generation_session set close_reason = 'idle', closed_at = now()",
            "delete from generation_session",
        ):
            with (
                pytest.raises(
                    psycopg.errors.InsufficientPrivilege, match="written by the operator's command"
                ),
                runtime.unscoped() as connection,
            ):
                connection.execute(statement)
    finally:
        with psycopg.connect(_url(), autocommit=True) as connection:
            connection.execute(
                f"revoke insert, update, delete on generation_session from {RUNTIME_ROLE}"
            )


def _url() -> str:
    import os

    return os.environ["EXULANICA_DATABASE_URL"]
