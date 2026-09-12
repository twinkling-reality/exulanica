"""Read-only local prerequisites for the frontier command, with actionable failures.

Disk headroom is a declared planning allowance, not a prediction of model output size.
No key, receipt, directory, database row or model cache is created by this module.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path
from typing import Any

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from exulanica.db.migrate import applied_migrations
from exulanica.db.reference_target import (
    COPY_URL,
    validate_reference_url,
    writable_reference_url,
)
from exulanica.env import env_get
from exulanica.evidence.address import EvidenceAddress
from exulanica.evidence.blob import BlobId
from exulanica.ingest.repository import IngestRepository
from exulanica.migrations import migrations, verify_applied
from exulanica.models.credentials import api_key_from_env
from exulanica.models.manifest import load_manifest
from exulanica.orchestration.manifest import BuildManifest, load_build_manifest
from exulanica.world_package.package import load_private_key

PERMITTED_DATABASE = COPY_URL
_GIB = 1024**3


def permitted_database_url(url: str | None) -> str:
    """Validate the caller's writable destination against the explicit reference copy."""
    if not url:
        raise ValueError("Set EXULANICA_DATABASE_URL to the explicitly selected reference copy.")
    return writable_reference_url(url)


def validate_layout(
    photo_dir: Path,
    data_dir: Path,
    output: Path,
    private_key: Path | None = None,
) -> None:
    """Prevent writes beneath sources or a key, and mixed data/package directories."""
    roots = [photo_dir.resolve(), data_dir.resolve(), output.resolve()]
    for index, left in enumerate(roots):
        for right in roots[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise ValueError("Choose separate, non-nested photo, data and output directories.")
    if data_dir.exists():
        for path in data_dir.rglob("*"):
            if path.is_symlink():
                raise ValueError("Use a data directory without nested symbolic links.")
    if private_key is not None:
        key = private_key.resolve()
        if any(root == key or root in key.parents for root in roots):
            raise ValueError("Keep the signing key outside the photo, data and output directories.")
    if output.exists() or output.is_symlink():
        raise ValueError("Choose a new output directory; existing output is never overwritten.")


def _ancestor(path: Path) -> Path:
    while not path.exists():
        if path.is_symlink():
            raise ValueError("Replace the broken destination symbolic link with a directory.")
        path = path.parent
    if not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
        raise ValueError("Choose a destination whose nearest existing directory you can write.")
    return path


def inspect_database(url: str, manifest: BuildManifest | None) -> dict[str, Any]:
    """Verify schema history and authority without provisioning or applying migrations."""
    with psycopg.connect(
        validate_reference_url(url, read_only=True),
        row_factory=dict_row,
        connect_timeout=5,
        application_name="exulanica-frontier-preflight",
    ) as connection:
        connection.execute("set transaction read only")
        connection.execute("set local statement_timeout = '5s'")
        identity = connection.execute(
            "select current_database() name, inet_server_port() port, current_schema() schema"
        ).fetchone()
        if identity["name"] != conninfo_to_dict(url)["dbname"] or identity["port"] != 5433:
            raise ValueError("Connect to the permitted local reference database on port 5433.")
        known = applied_migrations(connection)
        verify_applied(known)
        pending = [
            migration.version for migration in migrations() if migration.version not in known
        ]
        if pending:
            raise ValueError(
                "Have the database operator review and apply pending migrations "
                + ", ".join(pending)
                + " before demonstrating; this command does not migrate."
            )
        authority = connection.execute(
            "select has_schema_privilege(current_schema(),'CREATE') can_create, "
            "(pg_has_role(current_user,c.relowner,'USAGE') or r.rolsuper) owns_embedding "
            "from pg_class c join pg_roles r on r.rolname=current_user "
            "where c.oid='embedding'::regclass"
        ).fetchone()
        if not authority["can_create"] or not authority["owns_embedding"]:
            raise ValueError(
                "Use the permitted database's provisioning role for this command; it must "
                "own embedding and be able to create the workspace partition in this schema."
            )
        result: dict[str, Any] = {"schema": identity["schema"], "migration_count": len(known)}
        if manifest:
            connection.execute(
                "select set_config('exulanica.workspace_id', %s, true)",
                (str(manifest.workspace_id),),
            )
            repository = IngestRepository(connection, manifest.workspace_id)
            for source in manifest.sources:
                blob = BlobId(bytes.fromhex(source.sha256))
                repository.refuse_ingest_if_tombstoned(EvidenceAddress.photograph(blob))
                withdrawn = connection.execute(
                    "select exists(select 1 from capture where workspace_id=%s "
                    "and blob_sha256=%s and deleted_at is not null) withdrawn",
                    (manifest.workspace_id, bytes.fromhex(source.sha256)),
                ).fetchone()["withdrawn"]
                if withdrawn:
                    raise ValueError(
                        "Choose a new authorized manifest/workspace: this one contains an "
                        "already withdrawn source: " + source.path
                    )
        if manifest and (
            manifest.pipeline.vision == "configured" or manifest.pipeline.depth == "moge"
        ):
            connection.execute(
                "select set_config('exulanica.workspace_id', %s, true)",
                (str(manifest.workspace_id),),
            )
            missing = []
            predicate = (
                "privacy_screening_allows_capture"
                if manifest.pipeline.depth == "moge"
                else "privacy_screening_allows_observation"
            )
            for source in manifest.sources:
                allowed = connection.execute(
                    "select exists (select 1 from capture c "
                    "join reconstruction_privacy_screening s "
                    "on s.workspace_id=c.workspace_id and s.capture_id=c.capture_id "
                    "where c.workspace_id=%s and c.blob_sha256=%s and c.deleted_at is null "
                    f"and {predicate}(c.workspace_id,c.capture_id,s.screening_id)) allowed",
                    (manifest.workspace_id, bytes.fromhex(source.sha256)),
                ).fetchone()["allowed"]
                if not allowed:
                    missing.append(source.path)
            if missing:
                raise ValueError(
                    "Intake and obtain valid authorization and screening for these exact sources "
                    "before enabling vision/depth: "
                    + ", ".join(missing)
                    + ". Alternatively explicitly select unavailable modes for a capture-only run."
                )
            result["screened_sources"] = len(manifest.sources)
        return result


def run_frontier_preflight(
    *,
    manifest_path: Path,
    photo_dir: Path,
    data_dir: Path,
    output: Path,
    private_key: Path,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, action: Any, remedy: str) -> Any:
        try:
            result = action()
        except Exception as error:
            # Database errors can contain connection strings and credentials. Never echo them.
            detail = remedy if isinstance(error, psycopg.Error) else f"{remedy} {error}"
            checks.append({"check": name, "status": "failed", "action": detail})
            return None
        checks.append({"check": name, "status": "passed", "detail": result})
        return result

    manifest = check(
        "manifest",
        lambda: load_build_manifest(manifest_path),
        "Correct the strict build manifest and its model-manifest digest.",
    )
    if manifest:
        checks[-1]["detail"] = {
            "sha256": manifest.canonical_sha256,
            "sources": len(manifest.sources),
        }

    def photos() -> dict[str, Any]:
        if (
            not photo_dir.is_dir()
            or photo_dir.is_symlink()
            or not os.access(photo_dir, os.R_OK | os.X_OK)
        ):
            raise ValueError("Supply a readable regular photo directory.")
        if manifest is None:
            return {"directory_readable": True, "inventory": "requires a valid manifest"}
        paths = manifest.validate_photo_directory(photo_dir)
        return {
            "files_verified": len(paths),
            "source_bytes": sum(s.bytes for s in manifest.sources),
        }

    check("photos", photos, "Restore the exact readable photo inventory named in the manifest.")

    def key() -> str:
        if private_key.is_symlink() or not private_key.is_file():
            raise ValueError("Supply a regular PEM key file, not a symbolic link.")
        load_private_key(private_key)
        if private_key.stat().st_mode & 0o077:
            raise ValueError("Restrict the private key to its owner with chmod 600.")
        return "Ed25519 PEM loaded; key material is never emitted."

    check("signing_key", key, "Create or select an owner-only Ed25519 signing key outside Git.")
    check(
        "write_boundary",
        lambda: validate_layout(photo_dir, data_dir, output, private_key),
        "Separate inputs, key, store and new output.",
    )
    check(
        "store_writable",
        lambda: str(_ancestor(data_dir / "blobs")),
        "Make the store directory writable, or choose a writable destination.",
    )
    check(
        "output_writable",
        lambda: str(_ancestor(output)),
        "Choose a writable parent for the new output directory.",
    )

    def disk() -> dict[str, Any]:
        source_bytes = sum(s.bytes for s in manifest.sources) if manifest else 0
        # Four copies allow for the store and three exports. The reserve covers metadata and
        # derivatives for a small development run; model output is explicitly not predictable.
        required = 4 * source_bytes + _GIB
        if manifest and manifest.pipeline.depth == "moge":
            required += 2 * _GIB
        volumes = {_ancestor(path).stat().st_dev: _ancestor(path) for path in (data_dir, output)}
        free = [shutil.disk_usage(path).free for path in volumes.values()]
        if any(value < required for value in free):
            raise ValueError(f"Free at least {required} bytes on each destination volume.")
        return {
            "required_bytes_per_volume": required,
            "free_bytes_per_volume": free,
            "basis": "4x source bytes + 1 GiB reserve (+2 GiB for depth); planning allowance only",
        }

    check("disk_headroom", disk, "Free disk space or choose another destination volume.")
    url = check(
        "database_environment",
        lambda: permitted_database_url(env_get("DATABASE_URL")),
        f"Set EXULANICA_DATABASE_URL={PERMITTED_DATABASE}.",
    )
    if url:
        checks[-1]["detail"] = PERMITTED_DATABASE
        check(
            "database_schema_and_screening",
            lambda: inspect_database(url, manifest),
            "Start the permitted PostgreSQL server and verify schema access and migration history.",
        )
    if manifest and manifest.pipeline.vision == "configured":

        def credential() -> str:
            name = load_manifest().api_key_env
            if not api_key_from_env(name).strip():
                raise ValueError(f"Set {name} to your model credential.")
            return "Configured credential is present; validity and live catalog are not checked."

        check("vision_credential", credential, "Set the configured provider credential.")
    if manifest and manifest.pipeline.depth == "moge":

        def depth() -> str:
            if any(importlib.util.find_spec(name) is None for name in ("torch", "moge")):
                raise ValueError(
                    "Install the reviewed reconstruction dependencies in this environment."
                )
            return (
                "Modules present; weights, inference and hardware capacity remain runtime checks."
            )

        check(
            "depth_dependencies", depth, "Install the reviewed depth runtime before enabling MoGe."
        )
    return {
        "profile": "exulanica-frontier-preflight/v1",
        "status": "passed" if all(c["status"] == "passed" for c in checks) else "blocked",
        "read_only": True,
        "checks": checks,
        "not_executed": [
            "model calls or live catalog",
            "weight downloads or inference",
            "ingest, migrations, signing, export or deletion",
        ],
    }
