"""Operational evidence for a person-scoped withdrawal over a synthetic scene.

This runner is intentionally narrow. It accepts only the campaign's exact local test database,
an Exulanica-owned object store, and a scene whose admitted members are all synthetic. It adds a
clearly simulated person occurrence to one already reconstructed synthetic member, applies the
normal user identity and entity tombstone paths, projects World Memory Packages on both sides,
and drains the normal separately privileged purge queue.

The simulation exercises withdrawal reachability. It is not a claim that the rendered pixels
contain a person, not a privacy screening result, and not evidence about personal media.
"""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import psycopg
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from exulanica.canonical import canonical_json
from exulanica.db.session import Database
from exulanica.deletion.worker import PurgeWorker
from exulanica.errors import TombstonedError
from exulanica.evidence import EvidenceAddress
from exulanica.evidence.blob import BlobId
from exulanica.graph import scene_rung_rows
from exulanica.graph.reconstruction_scenes import reconstruction_scene_rows
from exulanica.identity import IdentityRepository, name_occurrence, occurrence_identity_key
from exulanica.ingest.repository import IngestRepository
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world_package import project_world_package

__all__ = [
    "PersonWithdrawalExercise",
    "assert_exulanica_store_root",
    "assert_test_database_url",
    "exercise_synthetic_person_withdrawal",
]

_PROFILE: Final = "exulanica.person-withdrawal-evaluation/v1"
_ENVELOPE_PROFILE: Final = "exulanica.digest-bound-record/v1"
_SIMULATION_PROFILE: Final = "exulanica.synthetic-person-withdrawal-fixture/v1"
_EXPECTED_DATABASE: Final = "exulanica_spine_test"
_EXPECTED_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1"})
_EXPECTED_PORT: Final = 5433


@dataclass(frozen=True, slots=True)
class PersonWithdrawalExercise:
    """Exact target and output boundary for one irreversible synthetic exercise."""

    database_url: str
    purge_database_url: str
    store_root: Path
    workspace_id: uuid.UUID
    scene_id: uuid.UUID
    capture_id: uuid.UUID
    expected_current_job_id: uuid.UUID
    expected_source_manifest_sha256: str
    expected_source_sha256: str
    actor_id: uuid.UUID
    git_head: str
    output_directory: Path
    report_path: Path
    interrupted_run_git_head: str | None = None


@dataclass(frozen=True, slots=True)
class _SyntheticIdentity:
    entity_id: uuid.UUID
    link_id: uuid.UUID
    assertion_id: uuid.UUID


def assert_test_database_url(value: str) -> None:
    """Refuse any database other than the named local campaign test database."""
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or parsed.hostname not in _EXPECTED_HOSTS
        or parsed.port != _EXPECTED_PORT
        or parsed.path != f"/{_EXPECTED_DATABASE}"
    ):
        raise ValueError(
            "person withdrawal evaluation requires exactly the local "
            f"{_EXPECTED_DATABASE} database on port {_EXPECTED_PORT}"
        )


def assert_exulanica_store_root(value: Path) -> Path:
    """Keep the exercise out of historical Orimera state and arbitrary directories."""
    path = value.resolve()
    if ".orimera" in path.parts or ".exulanica" not in path.parts:
        raise ValueError("the evaluation store must be rooted under .exulanica, never .orimera")
    return path


def exercise_synthetic_person_withdrawal(spec: PersonWithdrawalExercise) -> dict[str, Any]:
    """Exercise the real dependency cascade and return its digest-bound envelope."""
    assert_test_database_url(spec.database_url)
    assert_test_database_url(spec.purge_database_url)
    store_root = assert_exulanica_store_root(spec.store_root)
    output_directory = assert_exulanica_store_root(spec.output_directory)
    if len(spec.git_head) != 40 or any(char not in "0123456789abcdef" for char in spec.git_head):
        raise ValueError("git_head must be a full lowercase commit SHA")
    for field, value in (
        ("expected_source_manifest_sha256", spec.expected_source_manifest_sha256),
        ("expected_source_sha256", spec.expected_source_sha256),
    ):
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    if spec.report_path.exists():
        raise ValueError(f"refusing to overwrite retained report {spec.report_path}")
    output_directory.mkdir(parents=True, exist_ok=True)
    before_path = output_directory / "before-withdrawal.wmp"
    after_path = output_directory / "after-withdrawal.wmp"
    resuming = before_path.is_dir() and not after_path.exists()
    if before_path.exists() and not resuming:
        raise ValueError("refusing to overwrite a completed World Memory Package observation")
    if after_path.exists():
        raise ValueError("refusing to overwrite a completed World Memory Package observation")
    if resuming and spec.interrupted_run_git_head is None:
        raise ValueError("an interrupted exercise requires its original git head to resume")
    if not resuming and spec.interrupted_run_git_head is not None:
        raise ValueError("an original git head is valid only when resuming an interrupted exercise")

    store = LocalContentAddressedStore(store_root)
    owner_database = Database(spec.database_url)
    signing_key = Ed25519PrivateKey.generate()

    with owner_database.session(spec.workspace_id) as connection:
        repository = IngestRepository(connection, spec.workspace_id)
        target = _target(repository, spec, require_clean=not resuming)
        if resuming:
            occurrence_id, named, tombstone_id = _existing_simulated_identity(
                connection, spec
            )
        else:
            occurrence_id, named = _install_simulated_identity(repository, spec, target)
            tombstone_id = None
        dependencies = _dependencies(connection, spec.workspace_id, named.entity_id, store)
        if not any(
            item["target_kind"] == "artifact"
            and item.get("artifact_kind") == "point_map"
            and item["target_id"] == target["point_map_artifact_id"]
            for item in dependencies
        ):
            raise RuntimeError("the confirmed synthetic occurrence did not reach its point map")
        if not any(
            item["target_kind"] == "scene" and item["target_id"] == str(spec.scene_id)
            for item in dependencies
        ):
            raise RuntimeError("the confirmed synthetic occurrence did not reach its scene")

        retained_controls = _retained_controls(
            connection,
            spec,
            store,
            dependencies,
        )
        if resuming:
            before_package = _read_package(before_path)
            before_graph = _graph_from_package(before_path, spec)
        else:
            before_graph = _graph_state(connection, spec, store)
            before_package = _project_package(
                connection,
                spec,
                before_path,
                signing_key,
                parent=None,
            )
            tombstone_id = repository.insert_tombstone(
                scope="entity",
                entity_id=named.entity_id,
                requested_by=spec.actor_id,
                reason="synthetic evaluation subject withdrew from derivative use",
            )
        assert tombstone_id is not None
        withdrawal_receipt = _withdrawal_receipt(connection, tombstone_id)
        immediate_graph = _graph_state(connection, spec, store)
        late_publish_refusal = _late_publication_refusal(repository, spec.scene_id)
        after_package = _project_package(
            connection,
            spec,
            after_path,
            signing_key,
            parent=before_package["merkle_root_sha256"],
        )

    purge = PurgeWorker(
        Database(spec.purge_database_url),
        store,
        frozenset({spec.workspace_id}),
        name="synthetic-person-withdrawal-evaluation",
    ).drain()

    with owner_database.session(spec.workspace_id) as connection:
        final = _final_state(
            connection,
            spec,
            store,
            tombstone_id,
            dependencies,
            retained_controls,
        )

    _require_success(
        spec,
        before_graph,
        before_package,
        immediate_graph,
        after_package,
        late_publish_refusal,
        purge,
        final,
    )
    record = {
        "profile": _PROFILE,
        "notice": (
            "A simulated occurrence over an all-synthetic scene exercised production person "
            "withdrawal. It is not a claim that a person appears in the pixels, a personal-media "
            "result, or a consent event."
        ),
        "source_build": {
            "exercise_started_git_head": spec.interrupted_run_git_head or spec.git_head,
            "record_completed_git_head": spec.git_head,
            "interrupted_and_resumed": resuming,
            "repository_dirty": True,
            "measured_implementation_scope_dirty": False,
        },
        "target": target,
        "synthetic_subject": {
            "simulation_profile": _SIMULATION_PROFILE,
            "actor_id": str(spec.actor_id),
            "occurrence_id": str(occurrence_id),
            "entity_id": str(named.entity_id),
            "link_id": str(named.link_id),
            "naming_assertion_id": str(named.assertion_id),
            "display_name": "Synthetic Withdrawal Fixture Subject",
        },
        "durable_dependencies_before_withdrawal": dependencies,
        "before_withdrawal": {
            "graph": before_graph,
            "world_memory_package": before_package,
        },
        "withdrawal": {
            "tombstone_id": str(tombstone_id),
            "database_receipt": withdrawal_receipt,
            "immediate_graph": immediate_graph,
            "late_publication_refusal": late_publish_refusal,
            "world_memory_package": after_package,
        },
        "purge": {
            "database_role": purge.role,
            "destroyed": purge.destroyed,
            "already_absent": purge.already_absent,
            "skipped": purge.skipped,
            "failed": purge.failed,
            "exhausted": purge.exhausted,
            "blocked": purge.blocked,
            "completed_tombstone_ids": [str(value) for value in purge.completed_tombstones],
            "errors": purge.errors,
            "final": final,
        },
        "retention_boundary": retained_controls,
        "limitations": [
            "The occurrence and identity are explicit synthetic evaluation simulation records.",
            (
                "The exercise proves dependency reachability, serving withdrawal, package "
                "withdrawal, late-write refusal, and stored-byte purge on one actual synthetic "
                "production scene."
            ),
            (
                "It does not test a real person's identity, request, legal basis, or "
                "personal-media consent."
            ),
            (
                "Registered and unregistered members, concurrent workers, retries, shared bytes, "
                "and superseded builds remain covered by the PostgreSQL integration suite."
            ),
            (
                "The browser disappearance observation is retained separately after this "
                "database and object-store exercise."
            ),
            *(
                [
                    (
                        "The first evaluator process stopped after the tombstone commit when its "
                        "late-write probe caught the database exception below the repository's "
                        "domain-error boundary. No purge job ran before the corrected evaluator "
                        "resumed the durable tombstone and queue."
                    )
                ]
                if resuming
                else []
            ),
        ],
    }
    record_bytes = canonical_json(record)
    envelope = {
        "profile": _ENVELOPE_PROFILE,
        "record": record,
        "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
    }
    spec.report_path.parent.mkdir(parents=True, exist_ok=True)
    spec.report_path.write_bytes(canonical_json(envelope) + b"\n")
    return envelope


def _target(
    repository: IngestRepository,
    spec: PersonWithdrawalExercise,
    *,
    require_clean: bool,
) -> dict[str, Any]:
    connection = repository.connection
    row = connection.execute(
        "select s.current_job_id,j.status,j.build_input_digest,j.build_inputs,"
        "j.privacy_admission_id,j.privacy_admission_digest,c.blob_sha256,c.deleted_at,"
        "b.registered,m.ordinal,a.corpus_class,a.evidence_digest,a.synthetic_manifest_digest,"
        "p.screening_method,p.eligibility_state,p.receipt_digest "
        "from reconstruction_scene s "
        "join reconstruction_scene_job j on j.workspace_id=s.workspace_id "
        "and j.job_id=s.current_job_id "
        "join reconstruction_scene_member m on m.workspace_id=s.workspace_id "
        "and m.scene_id=s.scene_id and m.capture_id=%s "
        "join reconstruction_scene_build_member b on b.workspace_id=s.workspace_id "
        "and b.job_id=j.job_id and b.capture_id=m.capture_id "
        "join capture c on c.workspace_id=m.workspace_id and c.capture_id=m.capture_id "
        "join reconstruction_privacy_admission_member am on am.workspace_id=j.workspace_id "
        "and am.admission_id=j.privacy_admission_id and am.capture_id=m.capture_id "
        "join capture_reconstruction_authorization a on a.workspace_id=am.workspace_id "
        "and a.authorization_id=am.authorization_id "
        "join reconstruction_privacy_screening p on p.workspace_id=am.workspace_id "
        "and p.screening_id=am.screening_id "
        "where s.workspace_id=%s and s.scene_id=%s",
        (spec.capture_id, spec.workspace_id, spec.scene_id),
    ).fetchone()
    if row is None:
        raise ValueError("the exact capture is not a member of the exact current scene build")
    if row["current_job_id"] != spec.expected_current_job_id or row["status"] != "succeeded":
        raise ValueError("the exact expected scene build is not current and succeeded")
    if row["deleted_at"] is not None:
        raise ValueError("the target capture is already deleted")
    if (
        row["corpus_class"] != "synthetic"
        or row["screening_method"] != "synthetic_exemption"
        or row["eligibility_state"] != "eligible"
    ):
        raise ValueError("the target is not an eligible synthetic-exempt capture")
    source_sha256 = bytes(row["blob_sha256"]).hex()
    manifest_sha256 = bytes(row["synthetic_manifest_digest"]).hex()
    if source_sha256 != spec.expected_source_sha256:
        raise ValueError("the target source digest differs from the operator-approved digest")
    if manifest_sha256 != spec.expected_source_manifest_sha256:
        raise ValueError("the synthetic manifest differs from the operator-approved digest")

    classes = connection.execute(
        "select array_agg(distinct a.corpus_class order by a.corpus_class) as classes,"
        "array_agg(distinct encode(a.synthetic_manifest_digest,'hex') "
        "order by encode(a.synthetic_manifest_digest,'hex')) as manifests "
        "from reconstruction_scene_member m "
        "join reconstruction_privacy_admission_member am on am.workspace_id=m.workspace_id "
        "and am.admission_id=%s and am.capture_id=m.capture_id "
        "join capture_reconstruction_authorization a on a.workspace_id=am.workspace_id "
        "and a.authorization_id=am.authorization_id "
        "where m.workspace_id=%s and m.scene_id=%s",
        (row["privacy_admission_id"], spec.workspace_id, spec.scene_id),
    ).fetchone()
    if classes is None or classes["classes"] != ["synthetic"]:
        raise ValueError("every scene member must be durably classified synthetic")
    if classes["manifests"] != [spec.expected_source_manifest_sha256]:
        raise ValueError("every scene member must bind the same approved synthetic manifest")
    existing = connection.execute(
        "select count(*) as n from occurrence where workspace_id=%s and capture_id=%s "
        "and class='person'",
        (spec.workspace_id, spec.capture_id),
    ).fetchone()
    if require_clean and (existing is None or int(existing["n"]) != 0):
        raise ValueError("the target already has a person occurrence and is not a clean fixture")

    point_maps = {
        value["capture_ref"]: value for value in row["build_inputs"]["point_maps"]
    }
    point_map = point_maps.get(str(spec.capture_id))
    if point_map is None:
        raise ValueError("the current build input does not bind the target point map")
    return {
        "corpus_class": "synthetic",
        "workspace_id": str(spec.workspace_id),
        "scene_id": str(spec.scene_id),
        "current_job_id": str(row["current_job_id"]),
        "capture_id": str(spec.capture_id),
        "capture_ordinal": int(row["ordinal"]),
        "registered": bool(row["registered"]),
        "source_sha256": source_sha256,
        "source_manifest_sha256": manifest_sha256,
        "build_input_sha256": bytes(row["build_input_digest"]).hex(),
        "privacy_admission_id": str(row["privacy_admission_id"]),
        "privacy_admission_sha256": bytes(row["privacy_admission_digest"]).hex(),
        "authorization_sha256": bytes(row["evidence_digest"]).hex(),
        "screening_sha256": bytes(row["receipt_digest"]).hex(),
        "point_map_artifact_id": point_map["artifact_ref"],
        "point_map_content_sha256": point_map["content_sha256"],
    }


def _install_simulated_identity(
    repository: IngestRepository,
    spec: PersonWithdrawalExercise,
    target: dict[str, Any],
) -> tuple[uuid.UUID, _SyntheticIdentity]:
    row = repository.connection.execute(
        "select s.span_id,r.run_id from capture c "
        "join evidence_span s on s.blob_sha256=c.blob_sha256 "
        "join lateral (select run_id from pipeline_run where workspace_id=c.workspace_id "
        "and capture_id=c.capture_id and status='succeeded' order by started_at desc limit 1) r "
        "on true where c.workspace_id=%s and c.capture_id=%s "
        "order by s.t_start_ns,s.span_id limit 1",
        (spec.workspace_id, spec.capture_id),
    ).fetchone()
    if row is None:
        raise RuntimeError("the synthetic target lacks an evidence span or succeeded ingest run")
    source = BlobId.from_hex(target["source_sha256"])
    with repository.transaction():
        occurrence_id = repository.insert_occurrence(
            capture_id=spec.capture_id,
            occurrence_class="person",
            primary_span_id=row["span_id"],
            span_ids=[row["span_id"]],
            presence=[(0, 1)],
            produced_by_run=row["run_id"],
            detector_version=_SIMULATION_PROFILE,
            identity_key=occurrence_identity_key(
                EvidenceAddress.photograph(source), "person"
            ),
            emit_key=f"evaluation:person-withdrawal:{spec.scene_id}:{spec.capture_id}",
            quality={
                "evaluation_fixture": True,
                "simulation_profile": _SIMULATION_PROFILE,
                "truth_status": "simulated-not-observed",
            },
        )
    if occurrence_id is None:
        raise RuntimeError("the synthetic occurrence emit key already exists")
    named = name_occurrence(
        IdentityRepository(repository.connection, spec.workspace_id),
        repository.assertions,
        occurrence_id=occurrence_id,
        display_name="Synthetic Withdrawal Fixture Subject",
        actor=spec.actor_id,
    )
    return occurrence_id, _SyntheticIdentity(
        entity_id=named.entity_id,
        link_id=named.link_id,
        assertion_id=named.assertion_id,
    )


def _existing_simulated_identity(
    connection: psycopg.Connection,
    spec: PersonWithdrawalExercise,
) -> tuple[uuid.UUID, _SyntheticIdentity, uuid.UUID]:
    row = connection.execute(
        "select o.occurrence_id,l.entity_id,l.link_id,a.assertion_id,t.tombstone_id "
        "from occurrence o join entity_link l on l.workspace_id=o.workspace_id "
        "and l.occurrence_id=o.occurrence_id and l.state='confirmed' "
        "join assertion a on a.workspace_id=o.workspace_id "
        "and a.subject_ref->>'type'='entity' "
        "and a.subject_ref->>'id'=l.entity_id::text "
        "join predicate p on p.predicate_id=a.predicate_id and p.key='name_is' "
        "join tombstone t on t.workspace_id=o.workspace_id and t.scope='entity' "
        "and t.entity_id=l.entity_id where o.workspace_id=%s and o.capture_id=%s "
        "and o.detector_version=%s order by t.effective_at desc limit 1",
        (spec.workspace_id, spec.capture_id, _SIMULATION_PROFILE),
    ).fetchone()
    if row is None:
        raise RuntimeError("the interrupted exercise has no durable simulated withdrawal state")
    return (
        row["occurrence_id"],
        _SyntheticIdentity(
            entity_id=row["entity_id"],
            link_id=row["link_id"],
            assertion_id=row["assertion_id"],
        ),
        row["tombstone_id"],
    )


def _dependencies(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    store: LocalContentAddressedStore,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "select d.target_kind,d.target_id,a.kind as artifact_kind,a.content_sha256 "
        "from person_derivative_dependency d left join artifact a "
        "on d.target_kind='artifact' and a.workspace_id=d.workspace_id "
        "and a.artifact_id=d.target_id where d.workspace_id=%s and d.entity_id=%s "
        "order by d.target_kind,d.target_id",
        (workspace_id, entity_id),
    ).fetchall()
    return [
        {
            "target_kind": row["target_kind"],
            "target_id": str(row["target_id"]),
            "artifact_kind": row["artifact_kind"],
            "content_sha256": (
                bytes(row["content_sha256"]).hex() if row["content_sha256"] is not None else None
            ),
            "stored_bytes_present": (
                store.exists(BlobId(bytes(row["content_sha256"])))
                if row["content_sha256"] is not None
                else None
            ),
        }
        for row in rows
    ]


def _graph_state(
    connection: psycopg.Connection,
    spec: PersonWithdrawalExercise,
    store: LocalContentAddressedStore,
) -> dict[str, Any]:
    rungs = scene_rung_rows(connection, spec.workspace_id)
    scenes = reconstruction_scene_rows(connection, spec.workspace_id, store)
    return {
        "scene_ids": [str(row.scene_id) for row in scenes],
        "scene_count": len(scenes),
        "rung_scene_ids": [str(row.scene_id) for row in rungs],
        "rung_count": len(rungs),
        "target_scene_present": any(row.scene_id == spec.scene_id for row in scenes),
        "target_rung_present": any(row.scene_id == spec.scene_id for row in rungs),
    }


def _project_package(
    connection: psycopg.Connection,
    spec: PersonWithdrawalExercise,
    output: Path,
    key: Ed25519PrivateKey,
    *,
    parent: str | None,
) -> dict[str, Any]:
    result = project_world_package(
        connection,
        workspace_id=spec.workspace_id,
        actor=spec.actor_id,
        output=output,
        private_key=key,
        parent_merkle_root_sha256=parent,
    )
    reconstruction = json.loads((output / "reconstruction/artifacts.json").read_bytes())
    graph = json.loads((output / "memory/graph.json").read_bytes())
    return {
        "profile_version": "exulanica-wmp-1.0",
        "merkle_root_sha256": result.merkle_root_sha256,
        "manifest_sha256": result.manifest_sha256,
        "signing_public_key_sha256": result.signing_public_key_sha256,
        "scene_count": len(reconstruction["scenes"]),
        "scene_rung_claim_count": sum(
            item["predicate"] == "reconstruction_scene_rung_is"
            for item in graph["assertions"]
        ),
        "all_reconstruction_rung_claim_count": len(reconstruction["rung_claims"]),
        "artifact_descriptor_count": len(reconstruction["items"]),
        "local_output_name": output.name,
    }


def _read_package(output: Path) -> dict[str, Any]:
    manifest_bytes = (output / "wmp/manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    signature = json.loads((output / "wmp/signature.json").read_bytes())
    reconstruction = json.loads((output / "reconstruction/artifacts.json").read_bytes())
    graph = json.loads((output / "memory/graph.json").read_bytes())
    public_key = base64.b64decode(signature["public_key_base64"])
    return {
        "profile_version": manifest["profile_version"],
        "merkle_root_sha256": manifest["merkle_root_sha256"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "signing_public_key_sha256": hashlib.sha256(public_key).hexdigest(),
        "scene_count": len(reconstruction["scenes"]),
        "scene_rung_claim_count": sum(
            item["predicate"] == "reconstruction_scene_rung_is"
            for item in graph["assertions"]
        ),
        "all_reconstruction_rung_claim_count": len(reconstruction["rung_claims"]),
        "artifact_descriptor_count": len(reconstruction["items"]),
        "local_output_name": output.name,
    }


def _graph_from_package(output: Path, spec: PersonWithdrawalExercise) -> dict[str, Any]:
    reconstruction = json.loads((output / "reconstruction/artifacts.json").read_bytes())
    graph = json.loads((output / "memory/graph.json").read_bytes())
    scene_rungs = sum(
        item["predicate"] == "reconstruction_scene_rung_is"
        for item in graph["assertions"]
    )
    if len(reconstruction["scenes"]) != 1 or scene_rungs != 1:
        raise RuntimeError(
            "the interrupted pre-withdrawal package is not the exact one-scene state"
        )
    return {
        "scene_ids": [str(spec.scene_id)],
        "scene_count": 1,
        "rung_scene_ids": [str(spec.scene_id)],
        "rung_count": 1,
        "target_scene_present": True,
        "target_rung_present": True,
        "recovered_from_signed_pre_withdrawal_package": True,
    }


def _retained_controls(
    connection: psycopg.Connection,
    spec: PersonWithdrawalExercise,
    store: LocalContentAddressedStore,
    dependencies: list[dict[str, Any]],
) -> dict[str, Any]:
    dependent_artifacts = {
        item["target_id"] for item in dependencies if item["target_kind"] == "artifact"
    }
    rows = connection.execute(
        "select a.artifact_id,a.content_sha256 from artifact a where a.workspace_id=%s "
        "and a.kind='point_map' and a.purged_at is null order by a.artifact_id",
        (spec.workspace_id,),
    ).fetchall()
    unrelated = [
        {
            "artifact_id": str(row["artifact_id"]),
            "content_sha256": bytes(row["content_sha256"]).hex(),
            "stored_bytes_present": store.exists(BlobId(bytes(row["content_sha256"]))),
        }
        for row in rows
        if str(row["artifact_id"]) not in dependent_artifacts
    ]
    source = BlobId.from_hex(spec.expected_source_sha256)
    captures = connection.execute(
        "select count(*) as n from capture where workspace_id=%s and deleted_at is null",
        (spec.workspace_id,),
    ).fetchone()
    return {
        "source_capture_policy": "retained",
        "source_capture_deleted": False,
        "source_object_present": store.exists(source),
        "live_capture_count": int(captures["n"]),
        "unrelated_point_maps": unrelated,
    }


def _withdrawal_receipt(
    connection: psycopg.Connection, tombstone_id: uuid.UUID
) -> dict[str, Any]:
    row = connection.execute(
        "select record,record_digest,created_at from person_withdrawal_receipt "
        "where tombstone_id=%s",
        (tombstone_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("the entity tombstone produced no person withdrawal receipt")
    return {
        "profile": row["record"]["profile"],
        "record_sha256": bytes(row["record_digest"]).hex(),
        "created_at": _iso(row["created_at"]),
        "dependency_count": int(row["record"]["dependency_count"]),
        "purge_job_count": int(row["record"]["purge_job_count"]),
        "cancelled_scene_job_count": int(row["record"]["cancelled_scene_job_count"]),
        "retracted_assertion_count": int(row["record"]["retracted_assertion_count"]),
        "source_capture_policy": row["record"]["source_capture_policy"],
    }


def _late_publication_refusal(
    repository: IngestRepository, scene_id: uuid.UUID
) -> dict[str, Any]:
    try:
        with repository.transaction():
            repository.insert_scene_artifact(
                artifact_id=uuid.uuid4(),
                kind="pose_receipt",
                scene_id=scene_id,
                stage_key="scene_pose",
                stage_version=1,
                params_digest=b"\x91" * 32,
                input_digest=b"\x92" * 32,
                idempotency_key=f"evaluation:late-person-withdrawal:{uuid.uuid4()}",
                content_sha256=b"\x93" * 32,
                storage_key="sha-256/93/93/" + "93" * 32,
                byte_size=1,
                produced_by_event=None,
            )
    except TombstonedError as error:
        cause = error.__cause__
        sqlstate = cause.sqlstate if isinstance(cause, psycopg.Error) else None
        return {
            "refused": True,
            "error_class": type(error).__name__,
            "sqlstate": sqlstate,
            "reason": str(error).splitlines()[0],
        }
    except psycopg.IntegrityError as error:
        return {
            "refused": True,
            "error_class": type(error).__name__,
            "sqlstate": error.sqlstate,
            "reason": error.diag.message_primary or str(error).splitlines()[0],
        }
    raise RuntimeError("a late scene artifact published after person withdrawal")


def _final_state(
    connection: psycopg.Connection,
    spec: PersonWithdrawalExercise,
    store: LocalContentAddressedStore,
    tombstone_id: uuid.UUID,
    dependencies: list[dict[str, Any]],
    retained_controls: dict[str, Any],
) -> dict[str, Any]:
    tombstone = connection.execute(
        "select purge_completed_at from tombstone where tombstone_id=%s", (tombstone_id,)
    ).fetchone()
    jobs = connection.execute(
        "select target_kind,state,count(*) as n from purge_job where tombstone_id=%s "
        "group by target_kind,state order by target_kind,state",
        (tombstone_id,),
    ).fetchall()
    artifact_ids = [
        uuid.UUID(item["target_id"])
        for item in dependencies
        if item["target_kind"] == "artifact"
    ]
    artifacts = connection.execute(
        "select artifact_id,purged_at,content_sha256 from artifact where workspace_id=%s "
        "and artifact_id=any(%s) order by artifact_id",
        (spec.workspace_id, artifact_ids),
    ).fetchall()
    source = connection.execute(
        "select deleted_at from capture where workspace_id=%s and capture_id=%s",
        (spec.workspace_id, spec.capture_id),
    ).fetchone()
    unrelated = []
    for control in retained_controls["unrelated_point_maps"]:
        row = connection.execute(
            "select purged_at from artifact where workspace_id=%s and artifact_id=%s",
            (spec.workspace_id, uuid.UUID(control["artifact_id"])),
        ).fetchone()
        digest = BlobId.from_hex(control["content_sha256"])
        unrelated.append(
            {
                "artifact_id": control["artifact_id"],
                "database_live": row is not None and row["purged_at"] is None,
                "stored_bytes_present": store.exists(digest),
            }
        )
    return {
        "tombstone_purge_complete": tombstone is not None
        and tombstone["purge_completed_at"] is not None,
        "purge_jobs": [
            {
                "target_kind": row["target_kind"],
                "state": row["state"],
                "count": int(row["n"]),
            }
            for row in jobs
        ],
        "dependent_artifacts": [
            {
                "artifact_id": str(row["artifact_id"]),
                "database_purged": row["purged_at"] is not None,
                "stored_bytes_present": store.exists(BlobId(bytes(row["content_sha256"]))),
            }
            for row in artifacts
        ],
        "source_capture_deleted": source is None or source["deleted_at"] is not None,
        "source_object_present": store.exists(BlobId.from_hex(spec.expected_source_sha256)),
        "unrelated_point_maps": unrelated,
    }


def _require_success(
    spec: PersonWithdrawalExercise,
    before_graph: dict[str, Any],
    before_package: dict[str, Any],
    immediate_graph: dict[str, Any],
    after_package: dict[str, Any],
    late_refusal: dict[str, Any],
    purge: Any,
    final: dict[str, Any],
) -> None:
    failures = []
    if not before_graph["target_scene_present"] or not before_graph["target_rung_present"]:
        failures.append("target scene or rung was absent before withdrawal")
    if before_package["scene_count"] < 1 or before_package["scene_rung_claim_count"] < 1:
        failures.append("World Memory Package lacked the live scene before withdrawal")
    if immediate_graph["target_scene_present"] or immediate_graph["target_rung_present"]:
        failures.append("graph or rung still served the withdrawn scene")
    if (
        after_package["scene_count"] != 0
        or after_package["scene_rung_claim_count"] != 0
    ):
        failures.append("World Memory Package retained the withdrawn scene")
    if not late_refusal["refused"] or "tombstoned" not in late_refusal["reason"]:
        failures.append("late publication was not refused by the tombstone guard")
    if purge.role != "exulanica_purge" or purge.blocked is not None:
        failures.append("purge did not run as the separately privileged production role")
    if purge.failed or purge.skipped or purge.exhausted:
        failures.append("purge did not complete every claimed target")
    if str(spec.workspace_id) in purge.errors:
        failures.append("purge error exposed workspace context")
    if not final["tombstone_purge_complete"]:
        failures.append("tombstone did not reach physical purge completion")
    if final["source_capture_deleted"] or not final["source_object_present"]:
        failures.append("entity withdrawal deleted the source photograph")
    if any(
        not item["database_purged"] or item["stored_bytes_present"]
        for item in final["dependent_artifacts"]
    ):
        failures.append("a dependent artifact survived physical purge")
    if any(
        not item["database_live"] or not item["stored_bytes_present"]
        for item in final["unrelated_point_maps"]
    ):
        failures.append("an unrelated point map was removed")
    if failures:
        raise RuntimeError("; ".join(failures))


def _iso(value: Any) -> str:
    return value.isoformat().replace("+00:00", "Z")
