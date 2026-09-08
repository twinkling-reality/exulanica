"""Strict operator inputs refuse ambiguity before a database or store write."""

import copy
import datetime as dt
import json
import uuid

import pytest
from exulanica.ingest.personal_admission import load_manifest, read_source
from exulanica.ingest.personal_admission_command import main


def document(data=b"generated"):
    import hashlib

    now = dt.datetime.now(dt.UTC)
    return {
        "profile": "exulanica.personal-admission/v1",
        "actor_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
        "purpose": "generated admission rehearsal",
        "source": {
            "path": "a.png",
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "capture_id": None,
        },
        "authority": {
            "account_authority_basis": "I generated these labelled test pixels",
            "authorized_at": (now - dt.timedelta(minutes=1)).isoformat(),
            "valid_until": (now + dt.timedelta(hours=1)).isoformat(),
        },
        "operation": "admit",
        "authorization_id": None,
        "screening_id": None,
        "recorded_at": now.isoformat(),
        "review": "not-reviewed",
        "edits": [],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"surprise": True},
        {"purpose": " "},
        {"actor_id": "unknown"},
        {"review": "no-person"},
        {"authority": None},
        {"recorded_at": "2020-01-01"},
    ],
)
def test_strict_manifest(tmp_path, change):
    doc = document()
    doc.update(change)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        load_manifest(path)


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":1.1}', '{"x":NaN}'])
def test_ambiguous_json(tmp_path, text):
    path = tmp_path / "manifest.json"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_manifest(path)


def test_expired_and_wrong_bytes(tmp_path):
    doc = document()
    path = tmp_path / "manifest.json"
    expired = copy.deepcopy(doc)
    expired["authority"]["valid_until"] = "2000-01-01T00:00:00Z"
    path.write_text(json.dumps(expired))
    with pytest.raises(ValueError, match="expired"):
        load_manifest(path)
    path.write_text(json.dumps(doc))
    (tmp_path / "a.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="source bytes"):
        read_source(load_manifest(path), tmp_path)


def test_public_is_never_a_command_target(tmp_path, capsys):
    assert (
        main(
            [
                "--schema",
                "public",
                "--manifest",
                str(tmp_path / "missing"),
                "--photo-dir",
                str(tmp_path),
                "--data-dir",
                str(tmp_path),
            ]
        )
        == 1
    )
    assert "public is refused" in capsys.readouterr().out


def test_empty_schema_refuses_migrated_fallback_without_writes(
    cli_database, tmp_path, monkeypatch, capsys
):
    """The imported migration reader qualifies the FIRST schema, never its fallback."""
    from exulanica.db import Database
    from exulanica.ingest import personal_admission_command as command
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    fallback = Database.from_env()
    empty = "exulanica_personal_empty_" + uuid.uuid4().hex
    with fallback.unscoped() as owner:
        fallback_schema = owner.execute("select current_schema() name").fetchone()["name"]
        owner.execute(sql.SQL("create schema {}").format(sql.Identifier(empty)))
        owner.commit()
        try:
            isolated = Database(
                make_conninfo(
                    fallback.url, options=f"-csearch_path={empty},{fallback_schema},public"
                )
            )
            with isolated.unscoped() as connection:
                # Establish the dangerous counterfactual: unqualified history really resolves.
                assert (
                    connection.execute("select count(*) n from schema_migrations").fetchone()["n"]
                    == 39
                )
                before = connection.execute(
                    "select (select count(*) from pg_inherits "
                    "where inhparent='embedding'::regclass) workspace_partitions, "
                    "(select count(*) from capture) captures"
                ).fetchone()
            monkeypatch.setattr(command, "Database", lambda url: isolated)
            photos = tmp_path / "photos"
            photos.mkdir()
            (photos / "a.png").write_bytes(b"generated")
            manifest = tmp_path / "manifest.json"
            manifest.write_text(json.dumps(document()))
            assert (
                command.main(
                    [
                        "--schema",
                        empty,
                        "--manifest",
                        str(manifest),
                        "--photo-dir",
                        str(photos),
                        "--data-dir",
                        str(tmp_path / "store"),
                    ]
                )
                == 1
            )
            assert "pending migrations: 0001" in capsys.readouterr().out
            assert not (tmp_path / "store").exists()
            with isolated.unscoped() as connection:
                after = connection.execute(
                    "select (select count(*) from pg_inherits "
                    "where inhparent='embedding'::regclass) workspace_partitions, "
                    "(select count(*) from capture) captures"
                ).fetchone()
                assert after == before
        finally:
            owner.execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(empty)))
            owner.commit()
