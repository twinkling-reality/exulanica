"""One durable export, its offline receiver, and a withdrawal that removes its whole scene."""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.consent.training import TrainingTerms
from exulanica.ingest.person_review import (
    create_subject,
    record_consent,
    record_region_edits,
    review_list,
)
from exulanica.ingest.privacy import record_human_screening
from exulanica.world_package.package import PackageError, verify_package
from exulanica.world_package.training_store import (
    export_training_dataset,
    record_training_decision,
    training_export_ledger,
)

from test_training_inputs import scene_sample

pytestmark = pytest.mark.postgres
ACTOR = uuid.UUID("bbb32ec5-30e9-4b0b-a42f-6de2d111ea99")


def _terms():
    now = dt.datetime.now(dt.UTC)
    return TrainingTerms(
        "synthetic-sample",
        "sample-licensee",
        ("world-model",),
        now - dt.timedelta(days=1),
        now + dt.timedelta(days=30),
        "a" * 64,
    )


def _grant(repository, terms, subject="package-owner", decision="granted"):
    return record_training_decision(
        repository, subject_id=subject, terms=terms, decision=decision, actor=ACTOR
    )


def _person(repository, material):
    subject = create_subject(repository, actor=ACTOR)
    record_region_edits(
        repository,
        capture_id=uuid.UUID(material["capture_id"]),
        actor=ACTOR,
        edits=[
            {
                "action": "add",
                "region_key": "c" * 64,
                "subject_id": str(subject),
                "silhouette": {
                    "kind": "polygon",
                    "points": [[200000, 200000], [400000, 200000], [400000, 400000]],
                },
            }
        ],
    )
    record_consent(
        repository,
        subject_id=subject,
        actor=ACTOR,
        consent_scope="likeness",
        decision="granted",
        effective_at=dt.datetime.now(dt.UTC),
    )
    material["people"] = [{"subject_id": str(subject), "masked": False}]
    previous = repository.connection.execute(
        "select authorization_id from reconstruction_privacy_screening "
        "where workspace_id=%s and receipt_digest=%s",
        (repository.workspace_id, bytes.fromhex(material["screening"]["receipt_sha256"])),
    ).fetchone()
    screening = record_human_screening(
        repository,
        authorization_id=previous["authorization_id"],
        reviewed_by=ACTOR,
        sensitive_regions=review_list(repository, uuid.UUID(material["capture_id"])),
    )
    material["screening"]["receipt_sha256"] = screening.receipt_digest.hex()
    return str(subject)


def _export(repository, output, files, materials, terms, **kwargs):
    return export_training_dataset(
        repository,
        output=output,
        files=files,
        materials=materials,
        terms=terms,
        actor=ACTOR,
        private_key=Ed25519PrivateKey.generate(),
        attribution="Synthetic sample author",
        payment="No payment; evaluation fixture only",
        **kwargs,
    )


def test_durable_export_refuses_unconsented_person_and_withdrawal_removes_dependent_scene(
    repository, tmp_path
):
    files, materials = scene_sample(repository, tmp_path)
    subject = _person(repository, materials[0])
    terms = _terms()
    _grant(repository, terms)
    with pytest.raises(PackageError, match="unconsented unmasked person") as refused:
        _export(repository, tmp_path / "refused", files, materials, terms, owner_opt_in=True)
    assert not (tmp_path / "refused").exists()
    assert training_export_ledger(repository) == []
    _grant(repository, terms, subject)
    before = _export(repository, tmp_path / "sample", files, materials, terms, owner_opt_in=True)
    verified = verify_package(tmp_path / "sample")
    assert verified.merkle_root_sha256 == before["merkle_root_sha256"]
    assert (tmp_path / "sample/assets/trained.sog").is_file()
    assert {m["split"] for m in materials} == {"train", "held_out"}
    changed = copy.deepcopy(materials)
    changed[-1]["split"] = "train" if changed[-1]["split"] == "held_out" else "held_out"
    with pytest.raises(PackageError, match="frozen held-out split"):
        _export(repository, tmp_path / "changed", files, changed, terms, owner_opt_in=True)
    withdrawal = _grant(repository, terms, subject, "withdrawn")
    # A later grant cannot undo a withdrawal, including one written through a new connection.
    _grant(repository, terms, subject)
    after = _export(repository, tmp_path / "withdrawn", files, materials, terms, owner_opt_in=True)
    assert after["merkle_root_sha256"] != before["merkle_root_sha256"]
    assert after["removed_material_ids"] == sorted(m["material_id"] for m in materials)
    assert not (tmp_path / "withdrawn/assets").exists()
    lineage = json.loads((tmp_path / "withdrawn/provenance/dataset.json").read_bytes())
    assert lineage["parent_root"] == before["merkle_root_sha256"]
    ledger = training_export_ledger(repository)
    assert ledger[0]["subsequent_revocations"] == [withdrawal.as_dict()]
    assert ledger[1]["subsequent_revocations"] == []
    root = Path(__file__).resolve().parents[1]
    code = """import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from exulanica.world_package.package import verify_package
for path in sys.argv[2:]:
    print(verify_package(Path(path)).merkle_root_sha256)
assert 'exulanica.db' not in sys.modules
assert 'psycopg' not in sys.modules
"""
    clean = {key: value for key, value in os.environ.items() if not key.startswith("EXULANICA_")}
    checked = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            code,
            str(root),
            str(tmp_path / "sample"),
            str(tmp_path / "withdrawn"),
        ],
        env=clean,
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    assert checked.returncode == 0, checked.stderr
    assert checked.stdout.splitlines() == [
        before["merkle_root_sha256"],
        after["merkle_root_sha256"],
    ]
    (tmp_path / "acceptance.json").write_text(
        json.dumps(
            {
                "refusal": str(refused.value),
                "before_root": before["merkle_root_sha256"],
                "after_root": after["merkle_root_sha256"],
                "removed_material_ids": after["removed_material_ids"],
                "offline_process_exit": checked.returncode,
                "corpus_class": "synthetic",
                "pose_and_training": "scripted test doubles; no real CUDA or COLMAP",
            },
            indent=2,
        )
        + "\n"
    )


def test_training_stays_off_without_both_explicit_flag_and_durable_owner_grant(
    repository, tmp_path
):
    terms = _terms()
    with pytest.raises(PackageError, match="default off"):
        _export(repository, tmp_path / "off", {}, [], terms)
    with pytest.raises(PackageError, match="active recorded package-owner grant"):
        _export(repository, tmp_path / "no-grant", {}, [], terms, owner_opt_in=True)
    _grant(repository, terms)
    _grant(repository, terms, decision="revoked")
    with pytest.raises(PackageError, match="active recorded package-owner grant"):
        _export(repository, tmp_path / "revoked", {}, [], terms, owner_opt_in=True)
    assert training_export_ledger(repository) == []


def test_presentation_withdrawal_also_removes_prior_training_scene(repository, tmp_path):
    files, materials = scene_sample(repository, tmp_path)
    subject = _person(repository, materials[0])
    terms = _terms()
    _grant(repository, terms)
    _grant(repository, terms, subject)
    _export(repository, tmp_path / "before", files, materials, terms, owner_opt_in=True)
    record_consent(
        repository,
        subject_id=uuid.UUID(subject),
        actor=ACTOR,
        consent_scope="likeness",
        decision="withdrawn",
        effective_at=dt.datetime.now(dt.UTC),
    )
    result = _export(repository, tmp_path / "after", files, materials, terms, owner_opt_in=True)
    assert result["removed_material_ids"] == sorted(m["material_id"] for m in materials)
    assert training_export_ledger(repository)[0]["current_source_withdrawals"]["subject_ids"] == [
        subject
    ]


def test_cli_records_opt_in_exports_exact_assets_and_reads_user_ledger(
    cli_database, repository, tmp_path, capsys
):
    from cryptography.hazmat.primitives import serialization
    from exulanica.world_package.cli import main

    files, materials = scene_sample(repository, tmp_path)
    terms = _terms()
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "terms": terms.as_dict(),
                "materials": materials,
                "attribution": "Fixture author",
                "payment": "No payment",
            }
        )
    )
    terms_path = tmp_path / "terms.json"
    terms_path.write_text(json.dumps(terms.as_dict()))
    for relative, data in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    private = tmp_path / "key.pem"
    private.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    args = [
        "training-export",
        "--workspace",
        str(repository.workspace_id),
        "--actor",
        str(ACTOR),
        "--request",
        str(request),
        "--private-key",
        str(private),
        "--output",
        str(tmp_path / "cli"),
    ]
    assert main(args) == 1
    assert "--opt-in is required" in capsys.readouterr().err
    assert (
        main(
            [
                "training-consent",
                "--workspace",
                str(repository.workspace_id),
                "--actor",
                str(ACTOR),
                "--terms",
                str(terms_path),
                "--subject",
                "package-owner",
                "--decision",
                "granted",
            ]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["receipt"]["subject_id"] == "package-owner"
    assert main([*args, "--opt-in"]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert main(["training-ledger", "--workspace", str(repository.workspace_id)]) == 0
    ledger = json.loads(capsys.readouterr().out)
    assert ledger[0]["merkle_root_sha256"] == exported["merkle_root_sha256"]
    signed = json.loads((tmp_path / "cli/provenance/dataset.json").read_bytes())
    assert signed["licensing"] == {"attribution": "Fixture author", "payment": "No payment"}


def test_training_export_and_presentation_writer_share_a_lock_order(
    repository, ingest_spine, photo_dir, tmp_path, monkeypatch
):
    """Actual export/consent callers, paused after export's pre-existing source lock."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import exulanica.world_package.training_store as training_store
    import psycopg

    from test_training_inputs import image_sample

    files, materials = image_sample(repository, photo_dir, tmp_path)
    terms = _terms()
    _grant(repository, terms)
    subject = create_subject(repository, actor=ACTOR)
    _, open_another = ingest_spine
    exporter, writer = open_another(), open_another()
    held, resume = threading.Event(), threading.Event()
    original = training_store._lock

    def pause(connection, workspace, package):
        original(connection, workspace, package)
        held.set()
        assert resume.wait(5)

    monkeypatch.setattr(training_store, "_lock", pause)

    def export():
        try:
            _export(exporter, tmp_path / "concurrent", files, materials, terms, owner_opt_in=True)
            return "ok"
        except psycopg.Error as error:
            return error.sqlstate

    def consent():
        try:
            record_consent(
                writer,
                subject_id=subject,
                actor=ACTOR,
                consent_scope="likeness",
                decision="granted",
            )
            return "ok"
        except psycopg.Error as error:
            return error.sqlstate

    with ThreadPoolExecutor(max_workers=2) as pool:
        exporting = pool.submit(export)
        assert held.wait(5)
        consenting = pool.submit(consent)
        deadline = time.monotonic() + 3
        blocked = False
        while time.monotonic() < deadline:
            blocked = repository.connection.execute(
                "select %s=any(pg_blocking_pids(%s)) as waiting",
                (exporter.connection.info.backend_pid, writer.connection.info.backend_pid),
            ).fetchone()["waiting"]
            if blocked:
                break
            time.sleep(0.01)
        resume.set()
        assert blocked, "the actual consent writer must reach the export's held source lock"
        assert (exporting.result(timeout=5), consenting.result(timeout=5)) == ("ok", "ok")
