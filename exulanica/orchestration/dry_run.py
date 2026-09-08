"""An owned synthetic rehearsal of the ordinary frontier output contract.

The schema is disposable, the retained files are not: a caller can inspect all three signed
packages after cleanup. No supplied photograph can enter the synthetic authorization path.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from psycopg.conninfo import make_conninfo

from exulanica.canonical import canonical_json
from exulanica.corpus import build_plan
from exulanica.corpus.photograph import compose, encode_jpeg
from exulanica.db import Database, apply_pending, provision_workspace
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import authorize_synthetic_capture, record_synthetic_exemption
from exulanica.ingest.repository import IngestRepository
from exulanica.models.manifest import MANIFEST_PATH
from exulanica.orchestration.demonstration import (
    FrontierDemonstrationError,
    run_frontier_demonstration,
)
from exulanica.orchestration.manifest import load_build_manifest
from exulanica.orchestration.preflight import permitted_database_url
from exulanica.store.local import LocalContentAddressedStore

PERMITTED_DATABASE_URL = "postgresql://localhost:5433/exulanica_spine_test"
_REQUIRED_EXTENSIONS = {"vector", "pgcrypto", "pg_trgm", "btree_gist"}


@contextmanager
def _scratch_database() -> Iterator[tuple[Database, str]]:
    """Create and remove exactly one schema; never use rollback to undo committed migrations.

    Extensions must already exist in public, because they are database-wide objects. A fresh
    workspace alone would not isolate globally derived artifact primary keys. The unique schema
    also prevents a rehearsal tombstone from reaching retained captures.
    """
    schema = f"exulanica_frontier_dry_{uuid.uuid4().hex}"
    url = permitted_database_url(PERMITTED_DATABASE_URL)
    with psycopg.connect(url, autocommit=True) as owner:
        if owner.info.dbname != "exulanica_spine_test" or owner.info.server_version < 180000:
            raise FrontierDemonstrationError(
                "dry_run_database", "Use the permitted PostgreSQL 18 reference database."
            )
        installed = {
            row[0]
            for row in owner.execute(
                "select e.extname from pg_extension e join pg_namespace n "
                "on n.oid=e.extnamespace where n.nspname='public'"
            ).fetchall()
        }
        if missing := _REQUIRED_EXTENSIONS - installed:
            raise FrontierDemonstrationError(
                "dry_run_database",
                "Have the database operator install the required extensions in public: "
                + ", ".join(sorted(missing)),
            )
        owner.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
        try:
            database = Database(make_conninfo(url, options=f"-csearch_path={schema},public"))
            with database.unscoped() as connection:
                actual = connection.execute("select current_schema() as name").fetchone()["name"]
                if actual != schema:
                    raise FrontierDemonstrationError(
                        "dry_run_database", "The isolated schema could not be selected."
                    )
            apply_pending(database)
            yield database, schema
        finally:
            owner.execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)))


def _write_key(path: Path) -> Ed25519PrivateKey:
    """Exclusive creation and restrictive permissions precede the first secret byte."""
    key = Ed25519PrivateKey.generate()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    return key


def run_dry_run(output: Path) -> dict[str, Any]:
    """Generate inputs locally and execute all ten gates without hosted models or real media."""
    if output.exists() or output.is_symlink():
        raise FrontierDemonstrationError(
            "output_boundary", "Choose a new output directory for this synthetic rehearsal."
        )
    output.mkdir(parents=True, mode=0o700)
    photos = output / "photos"
    photos.mkdir()
    data_dir = output / "data"
    sources = []
    generated: list[tuple[Path, bytes]] = []
    for frame in build_plan(seed=20260908, frames_per_trip=3)[:2]:
        data = encode_jpeg(frame, compose(frame))
        path = photos / frame.filename
        path.write_bytes(data)
        generated.append((path, data))
        sources.append(
            {"path": path.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        )
    sources.sort(key=lambda item: item["path"])
    workspace_id, actor_id = uuid.uuid4(), uuid.uuid4()
    document = {
        "profile": "exulanica-frontier-build/v1",
        "workspace_id": str(workspace_id),
        "actor_id": str(actor_id),
        "world_id": "atlas:frontier-dry-run",
        "sources": sources,
        "pipeline": {
            "vision": "unavailable",
            "depth": "unavailable",
            "model_manifest_sha256": hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
        },
        "precomputed_artifacts": [],
        "adaptation": {
            "profile_id": "origin-landscape",
            "profile_version": 1,
            "parameters": {"vitality": 1},
            "proposal_provenance": {
                "origin": "companion",
                "origin_reference": "fixture:frontier-dry-run",
                "model_id": "synthetic-fixture/no-model",
                "prompt_version": "fixture/v1",
                "reference_ids": ["fixture:generated-geometric-arrangement"],
            },
        },
        "deletion_demo": {"path": sources[0]["path"]},
    }
    manifest_path = output / "frontier-build.json"
    manifest_path.write_bytes(canonical_json(document))
    manifest = load_build_manifest(manifest_path)
    key = _write_key(output / "throwaway-key.pem")
    with (
        _scratch_database() as (database, schema),
        database.session(workspace_id) as connection,
    ):
        provision_workspace(connection, workspace_id)
        repository = IngestRepository(connection, workspace_id)
        store = LocalContentAddressedStore(data_dir / "blobs")
        pipeline = PhotoIngestPipeline(repository, store)
        # Authorization is about these freshly rendered bytes, not a caller's directory,
        # EXIF marker, boolean flag, or declaration that arbitrary media is synthetic.
        for path, data in generated:
            intake = pipeline.ingest_intake(data, filename=path.name)
            if intake.capture_id is None:
                raise FrontierDemonstrationError("dry_run_intake", str(intake.error))
            authorization = authorize_synthetic_capture(
                repository,
                capture_id=intake.capture_id,
                actor=actor_id,
                generator_manifest={
                    "profile": "exulanica.frontier-dry-run/v1",
                    "seed": 20260908,
                    "frames_per_trip": 3,
                    "notice": "GENERATED CORPUS, NO PERSON PARTICIPATED",
                },
                authorization_scope={"purpose": "synthetic frontier rehearsal"},
            )
            record_synthetic_exemption(repository, authorization_id=authorization.authorization_id)
        receipt = run_frontier_demonstration(
            connection,
            manifest=manifest,
            photo_dir=photos,
            data_dir=data_dir,
            output=output / "run",
            private_key=key,
            confirm_source_deletion=True,
        )
    # This record is only written after successful schema cleanup. The ordinary frontier
    # receipt remains inside run/ with precisely the same package layout as a personal run.
    result = {
        "profile": "exulanica-frontier-dry-run/v1",
        "status": receipt["status"],
        "receipt": str(output / "run" / "frontier-receipt.json"),
        "synthetic": True,
        "hosted_model_calls": 0,
        "isolated_schema": schema,
        "isolated_schema_removed": True,
        "database": PERMITTED_DATABASE_URL,
        "signing_key": "throwaway-key.pem",
        "production_signing_key": False,
    }
    (output / "dry-run-receipt.json").write_bytes(canonical_json(result))
    return result
