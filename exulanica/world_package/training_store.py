"""Durable training decisions and export history, separate from memory projection.

The package lock is shared with the receipt INSERT trigger. An export takes it before reading
consent, so a withdrawal committed before that lock cannot be lost to a stale snapshot. Files
are staged privately and published only while the export transaction owns the lock.
"""

from __future__ import annotations

import datetime as dt
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

import psycopg
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.consent.training import TrainingReceipt, TrainingTerms, training_is_granted
from exulanica.ingest.repository import IngestRepository
from exulanica.world_package.package import PackageError, verify_package

PACKAGE_OWNER = "package-owner"


def _withdrawn_subject(repository: IngestRepository, subject: str) -> bool:
    try:
        identity = uuid.UUID(subject)
    except ValueError:
        return False
    with repository.connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "select person_subject_is_withdrawn(%s, %s) as withdrawn",
            (repository.workspace_id, identity),
        )
        return bool(cursor.fetchone()["withdrawn"])


def _withdrawn_capture(repository: IngestRepository, capture: str) -> bool:
    with repository.connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "select capture_id from capture where workspace_id=%s and capture_id=%s "
            "and deleted_at is null and not tombstone_blocks_capture(workspace_id,capture_id)",
            (repository.workspace_id, uuid.UUID(capture)),
        )
        return cursor.fetchone() is None


def _lock(connection: psycopg.Connection, workspace_id: uuid.UUID, package_id: str) -> None:
    connection.execute(
        "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"{workspace_id}:{package_id}",),
    )


def record_training_decision(
    repository: IngestRepository,
    *,
    subject_id: str,
    terms: TrainingTerms,
    decision: str,
    actor: uuid.UUID,
) -> TrainingReceipt:
    """Record an account-holder attestation, never impersonating a photographed subject."""
    connection = repository.connection
    with connection.transaction():
        _lock(connection, repository.workspace_id, terms.package_id)
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "select coalesce(max(sequence), -1) + 1 as next_sequence "
                "from training_use_consent where workspace_id=%s and package_id=%s "
                "and licensee=%s and subject_id=%s",
                (repository.workspace_id, terms.package_id, terms.licensee, subject_id),
            )
            sequence = cursor.fetchone()["next_sequence"]
            receipt = TrainingReceipt(
                subject_id, terms, decision, str(actor), sequence, dt.datetime.now(dt.UTC)
            )
            cursor.execute(
                "insert into training_use_consent "
                "(receipt_id, workspace_id, subject_id, package_id, licensee, sequence, "
                "decision, terms_digest, receipt_record, receipt_canonical, receipt_digest, "
                "actor, decided_at) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    uuid.uuid4(),
                    repository.workspace_id,
                    subject_id,
                    terms.package_id,
                    terms.licensee,
                    sequence,
                    decision,
                    bytes.fromhex(terms.digest),
                    Jsonb(receipt.as_dict()),
                    receipt.canonical,
                    bytes.fromhex(receipt.digest),
                    actor,
                    receipt.decided_at,
                ),
            )
    return receipt


def training_receipts(
    repository: IngestRepository, terms: TrainingTerms
) -> tuple[TrainingReceipt, ...]:
    """Read the whole relationship, including withdrawals under earlier terms."""
    with repository.connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "select receipt_record, receipt_canonical, receipt_digest, terms_digest "
            "from training_use_consent where workspace_id=%s and package_id=%s "
            "and licensee=%s order by subject_id, sequence",
            (repository.workspace_id, terms.package_id, terms.licensee),
        )
        receipts = []
        for row in cursor.fetchall():
            receipt = TrainingReceipt.from_dict(row["receipt_record"])
            if (
                receipt.canonical != bytes(row["receipt_canonical"])
                or receipt.digest != bytes(row["receipt_digest"]).hex()
                or receipt.terms.digest != bytes(row["terms_digest"]).hex()
            ):
                raise PackageError("stored training receipt does not match its canonical digests")
            receipts.append(receipt)
    return tuple(receipts)


def export_training_dataset(
    repository: IngestRepository,
    *,
    output: Path,
    files: dict[str, bytes],
    materials: list[dict[str, Any]],
    terms: TrainingTerms,
    actor: uuid.UUID,
    private_key: Ed25519PrivateKey,
    owner_opt_in: bool = False,
    attribution: str,
    payment: str,
) -> dict[str, Any]:
    """Validate durable source evidence, sign a dataset and append its licensing ledger entry.

    Refused material is removed only from a successor of a recorded export. A first export
    refuses outright, so a caller cannot confuse an incomplete initial delivery with consent.
    A successor names everything removed, and shared geometry is rejected by input validation.
    """
    from exulanica.world_package.dataset import write_dataset_package
    from exulanica.world_package.training_inputs import validate_dataset_inputs

    if owner_opt_in is not True:
        raise PackageError("training export is default off; explicit package opt-in is required")
    if not attribution.strip() or not payment.strip():
        raise PackageError("training export requires explicit attribution and payment terms")
    requested_paths = [a["path"] for m in materials for a in m["assets"]]
    if len(requested_paths) != len(set(requested_paths)) or set(files) != set(requested_paths):
        raise PackageError("training request contains shared, missing or unreferenced assets")
    connection = repository.connection
    if connection.info.transaction_status.name != "IDLE":
        raise PackageError("training export requires an idle connection")
    output = output.resolve()
    if output.exists():
        raise PackageError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    staged_package = staging / "package"
    published = False
    try:
        with connection.transaction():
            connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"training-source:{repository.workspace_id}",),
            )
            _lock(connection, repository.workspace_id, terms.package_id)
            # The lock is acquired in its own statement; READ COMMITTED now observes all prior
            # decisions. A caller's repeatable-read snapshot would defeat this guarantee.
            isolation = connection.execute("show transaction_isolation").fetchone()
            isolation_value = (
                next(iter(isolation.values())) if isinstance(isolation, dict) else isolation[0]
            )
            if isolation_value != "read committed":
                raise PackageError("training export requires read committed isolation")
            receipts = training_receipts(repository, terms)
            at = dt.datetime.now(dt.UTC)
            if not training_is_granted(receipts, subject_id=PACKAGE_OWNER, terms=terms, at=at):
                raise PackageError(
                    "training export requires an active recorded package-owner grant"
                )
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "select merkle_root_sha256, training_terms from world_package_export "
                    "where workspace_id=%s and world_id=%s "
                    "and training_terms->'terms'->>'licensee'=%s "
                    "order by exported_at desc, export_id desc limit 1",
                    (repository.workspace_id, terms.package_id, terms.licensee),
                )
                previous = cursor.fetchone()
                cursor.execute(
                    "select training_terms from world_package_export where workspace_id=%s "
                    "and world_id=%s and training_terms is not null",
                    (repository.workspace_id, terms.package_id),
                )
                history = cursor.fetchall()
            removed = []
            admitted = []
            for material in materials:
                denied = [
                    person["subject_id"]
                    for person in material["people"]
                    if _withdrawn_subject(repository, person["subject_id"])
                    or (
                        person.get("masked") is not True
                        and not training_is_granted(
                            receipts, subject_id=person["subject_id"], terms=terms, at=at
                        )
                    )
                ]
                withdrawn_capture = _withdrawn_capture(repository, material["capture_id"])
                if denied or withdrawn_capture:
                    if previous is None:
                        if withdrawn_capture:
                            raise PackageError(
                                "training export refused: capture is missing or withdrawn"
                            )
                        raise PackageError(
                            f"training export refused: unconsented unmasked person {denied[0]} "
                            f"in material {material['material_id']}"
                        )
                    removed.append(material["material_id"])
                else:
                    admitted.append(material)
            removed_scenes = {
                m["provenance"].get("scene_id")
                for m in materials
                if m["material_id"] in removed and m["provenance"].get("scene_id")
            }
            dependent = [m for m in admitted if m["provenance"].get("scene_id") in removed_scenes]
            removed.extend(m["material_id"] for m in dependent)
            admitted = [m for m in admitted if m not in dependent]
            current_ids = {m["material_id"] for m in admitted}
            if previous:
                removed.extend(set(previous["training_terms"]["material_ids"]) - current_ids)
            for historical in history:
                frozen = historical["training_terms"]["capture_splits"]
                if any(
                    m["capture_id"] in frozen and m["split"] != frozen[m["capture_id"]]
                    for m in admitted
                ):
                    raise PackageError("a successor export cannot change the frozen held-out split")
            removed = sorted(set(removed))
            admitted_paths = {a["path"] for m in admitted for a in m["assets"]}
            selected_files = {path: data for path, data in files.items() if path in admitted_paths}
            validate_dataset_inputs(repository, selected_files, admitted)
            parent_root = previous["merkle_root_sha256"] if previous else None
            write_dataset_package(
                staged_package,
                files=selected_files,
                materials=admitted,
                terms=terms,
                receipts=receipts,
                exported_at=at,
                private_key=private_key,
                owner_opt_in=True,
                parent_root=parent_root,
                removed_material_ids=removed,
                licensing={"attribution": attribution, "payment": payment},
            )
            report = verify_package(staged_package)
            export_id = uuid.uuid4()
            licensing = {
                "terms": terms.as_dict(),
                "attribution": attribution,
                "payment": payment,
                "material_ids": sorted(current_ids),
                "removed_material_ids": removed,
                "capture_splits": {m["capture_id"]: m["split"] for m in admitted},
                "capture_ids": sorted(m["capture_id"] for m in admitted),
                "subject_ids": sorted({p["subject_id"] for m in admitted for p in m["people"]}),
                "receipt_digests": sorted(r.digest for r in receipts),
                "actor_basis": "account-holder attestation; no subject identity verification",
            }
            connection.execute(
                "insert into world_package_export (export_id,workspace_id,world_id,profile_version,"
                "merkle_root_sha256,manifest_sha256,parent_merkle_root_sha256,signature_algorithm,"
                "signing_public_key_sha256,export_policy,actor,training_terms,exported_at) "
                "values (%s,%s,%s,%s,%s,%s,%s,'Ed25519',%s,%s,%s,%s,%s)",
                (
                    export_id,
                    repository.workspace_id,
                    terms.package_id,
                    report.profile_version,
                    report.merkle_root_sha256,
                    report.manifest_sha256,
                    parent_root,
                    report.signing_public_key_sha256,
                    Jsonb({"training_enabled": True, "profile": report.profile_version}),
                    actor,
                    Jsonb(licensing),
                    at,
                ),
            )
            staged_package.rename(output)
            published = True
        return {
            "export_id": str(export_id),
            "output": str(output),
            **report.as_dict(),
            "removed_material_ids": removed,
        }
    except BaseException:
        if published:
            shutil.rmtree(output)
        raise
    finally:
        shutil.rmtree(staging)


def training_export_ledger(repository: IngestRepository) -> list[dict[str, Any]]:
    """Show past exports and subsequent decisions without rewriting any signed history."""
    with repository.connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "select export_id, world_id, merkle_root_sha256, parent_merkle_root_sha256, "
            "exported_at, training_terms from world_package_export "
            "where workspace_id=%s and training_terms is not null order by exported_at, export_id",
            (repository.workspace_id,),
        )
        rows = cursor.fetchall()
    ledger = []
    for row in rows:
        terms = TrainingTerms.from_dict(row["training_terms"]["terms"])
        receipts = training_receipts(repository, terms)
        subjects = set(row["training_terms"]["subject_ids"]) | {PACKAGE_OWNER}
        later = [
            r.as_dict()
            for r in receipts
            if r.subject_id in subjects
            and (
                r.decision == "withdrawn"
                or (r.decision == "revoked" and r.terms.digest == terms.digest)
            )
            and r.decided_at > row["exported_at"]
        ]
        ledger.append(
            {
                "export_id": str(row["export_id"]),
                "package_id": row["world_id"],
                "merkle_root_sha256": row["merkle_root_sha256"],
                "parent_merkle_root_sha256": row["parent_merkle_root_sha256"],
                "exported_at": row["exported_at"].isoformat(),
                "licensing": row["training_terms"],
                "subsequent_revocations": later,
                "current_source_withdrawals": {
                    "subject_ids": sorted(s for s in subjects if _withdrawn_subject(repository, s)),
                    "capture_ids": sorted(
                        c
                        for c in row["training_terms"]["capture_ids"]
                        if _withdrawn_capture(repository, c)
                    ),
                },
            }
        )
    return ledger
