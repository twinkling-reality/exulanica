"""Content-addressed, application write-once evaluation archives.

The archive refuses a dirty repository because a commit id would not identify the code that ran.
It retains the exact model-manifest bytes, reviewed stage definitions, and migration digests beside
the report and machine record.  ``verify_archive`` re-hashes every file without importing Exulanica
state.

This is not WORM storage.  Exclusive creation and read-only file modes prevent accidental rewrite;
an operating-system administrator can still replace bytes.  Verification against a separately
retained root digest makes that replacement detectable, but cannot make it impossible.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from exulanica.canonical import canonical_json
from exulanica.ingest.stages import KEY_FORMAT_VERSION, STAGES, pipeline_digest
from exulanica.migrations import migrations
from exulanica.models.manifest import MANIFEST_PATH, Role, load_manifest_from

__all__ = [
    "ARCHIVE_PROFILE",
    "RUN_PROFILE",
    "ArchiveError",
    "ArchiveReceipt",
    "create_archive",
    "migration_snapshot",
    "model_snapshot",
    "pipeline_snapshot",
    "repository_snapshot",
    "verify_archive",
]

ARCHIVE_PROFILE: Final = "exulanica.evaluation-archive/v1"
RUN_PROFILE: Final = "exulanica.evaluation-run/v1"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class ArchiveError(ValueError):
    """An evaluation archive is incomplete, changed, or cannot identify its inputs."""


@dataclass(frozen=True, slots=True)
class ArchiveReceipt:
    path: pathlib.Path
    run_id: str
    root_sha256: str
    files: int


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _run_git(repository: pathlib.Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArchiveError(f"cannot inspect repository at {repository}: {exc}") from exc
    return result.stdout.strip()


def repository_snapshot(repository: str | pathlib.Path) -> dict[str, object]:
    """Return the exact committed repository state, refusing uncommitted inputs."""
    root = pathlib.Path(repository).resolve()
    dirty = _run_git(root, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        changed = len(dirty.splitlines())
        raise ArchiveError(
            f"evaluation archives require a clean repository; found {changed} changed paths"
        )
    return {
        "commit": _run_git(root, "rev-parse", "HEAD"),
        "tree": _run_git(root, "rev-parse", "HEAD^{tree}"),
        "dirty": False,
    }


def model_snapshot(path: str | pathlib.Path = MANIFEST_PATH) -> tuple[dict[str, object], bytes]:
    """Return role bindings plus the exact manifest bytes retained by the archive."""
    manifest_path = pathlib.Path(path)
    raw = manifest_path.read_bytes()
    manifest = load_manifest_from(manifest_path)
    roles: dict[str, object] = {}
    # Every role the manifest binds to a model; a chosen role's model is a world's.
    for role in (role for role in Role if role in manifest.roles):
        binding = manifest[role]
        roles[role.value] = {
            "primary": {"model_id": binding.primary.model_id, "revision": None},
            "fallback": (
                None
                if binding.fallback is None
                else {"model_id": binding.fallback.model_id, "revision": None}
            ),
        }
    return (
        {
            "manifest_version": manifest.manifest_version,
            "pipeline_version": manifest.pipeline_version,
            "sha256": _sha256(raw),
            "roles": roles,
            "revision_availability": (
                "unavailable: the configured serverless provider exposes no model revision"
            ),
        },
        raw,
    )


def pipeline_snapshot(
    bindings: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, object]:
    """Serialize the reviewed stage registry and any exact run-time bindings supplied."""
    supplied = {key: dict(value) for key, value in (bindings or {}).items()}
    unknown = sorted(set(supplied) - set(STAGES))
    if unknown:
        raise ArchiveError(f"run-time bindings name unknown stages: {unknown}")
    stages = []
    for key, spec in sorted(STAGES.items()):
        stages.append(
            {
                "stage_key": key,
                "stage_version": spec.version,
                "params": spec.params,
                "params_sha256": spec.params_digest.hex(),
                "model_role": spec.model_role,
                "binding": supplied.get(key),
                "deterministic": spec.deterministic,
                "output_kind": spec.output_kind,
            }
        )
    return {
        "key_format_version": KEY_FORMAT_VERSION,
        "pipeline_sha256_short": pipeline_digest(supplied),
        "bindings_complete": all(
            spec.model_role is None or key in supplied for key, spec in STAGES.items()
        ),
        "stages": stages,
    }


def migration_snapshot() -> dict[str, object]:
    """Return every forward migration and its exact package checksum."""
    return {
        "migrations": [
            {
                "version": migration.version,
                "filename": migration.path.name,
                "sha256": migration.checksum.hex(),
            }
            for migration in migrations()
        ]
    }


def _safe_relative(raw: str) -> pathlib.PurePosixPath:
    path = pathlib.PurePosixPath(raw)
    if (
        not raw
        or "\\" in raw
        or not path.parts
        or path == pathlib.PurePosixPath(".")
        or path.is_absolute()
        or ".." in path.parts
        or path.name == "MANIFEST.json"
    ):
        raise ArchiveError(f"invalid archive member path: {raw!r}")
    return path


def _validate_member_names(names: list[str]) -> None:
    paths = [_safe_relative(name) for name in names]
    normalized = [path.as_posix() for path in paths]
    if len(set(normalized)) != len(normalized):
        raise ArchiveError("archive member paths must be unique")
    for path in paths:
        for parent in path.parents:
            if parent != pathlib.PurePosixPath(".") and parent.as_posix() in normalized:
                raise ArchiveError(
                    f"archive member {parent.as_posix()!r} is also used as a directory"
                )


def create_archive(
    parent: str | pathlib.Path,
    *,
    run_id: str,
    record: Mapping[str, object],
    report: str,
    snapshots: Mapping[str, bytes],
    completed_at: dt.datetime | None = None,
) -> ArchiveReceipt:
    """Create one new versioned archive and refuse every overwrite."""
    try:
        parsed_run_id = str(uuid.UUID(run_id))
    except ValueError as exc:
        raise ArchiveError("run_id must be a UUID") from exc
    if record.get("profile") != RUN_PROFILE:
        raise ArchiveError(f"record profile must be {RUN_PROFILE!r}")
    if record.get("run_id") != parsed_run_id:
        raise ArchiveError("record run_id differs from the archive run_id")

    members: dict[str, bytes] = {
        "record.json": _json_bytes(dict(record)),
        "report.txt": report.encode("utf-8"),
    }
    for name, payload in snapshots.items():
        relative = _safe_relative(name)
        normalized = relative.as_posix()
        if normalized in members:
            raise ArchiveError(f"duplicate archive member: {normalized}")
        if not isinstance(payload, bytes):
            raise ArchiveError(f"archive member {normalized} is not bytes")
        members[normalized] = payload
    _validate_member_names(list(members))

    root = pathlib.Path(parent).resolve() / parsed_run_id
    try:
        root.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise ArchiveError(f"archive already exists and will not be overwritten: {root}") from exc
    except FileNotFoundError as exc:
        raise ArchiveError(f"archive parent does not exist: {root.parent}") from exc

    inventory: list[dict[str, object]] = []
    for name, payload in sorted(members.items()):
        path = root.joinpath(*_safe_relative(name).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        inventory.append({"path": name, "sha256": _sha256(payload), "bytes": len(payload)})

    manifest_body = {
        "profile": ARCHIVE_PROFILE,
        "run_id": parsed_run_id,
        "completed_at": (completed_at or dt.datetime.now(dt.UTC)).isoformat(),
        "storage_guarantee": (
            "application write-once and digest-verifiable; ordinary filesystem, not WORM"
        ),
        "files": inventory,
    }
    manifest = {
        **manifest_body,
        "root_sha256": _sha256(canonical_json(manifest_body)),
    }
    manifest_path = root / "MANIFEST.json"
    with manifest_path.open("xb") as handle:
        handle.write(_json_bytes(manifest))
        handle.flush()
        os.fsync(handle.fileno())

    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)
    return ArchiveReceipt(
        path=root,
        run_id=parsed_run_id,
        root_sha256=str(manifest["root_sha256"]),
        files=len(inventory),
    )


def verify_archive(
    directory: str | pathlib.Path, *, expected_root_sha256: str | None = None
) -> ArchiveReceipt:
    """Verify the profile, exact inventory, every byte digest, and the inventory root."""
    root = pathlib.Path(directory).resolve()
    manifest_path = root / "MANIFEST.json"
    if manifest_path.is_symlink():
        raise ArchiveError("archive manifest must not be a symbolic link")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ArchiveError(f"archive manifest is missing or invalid: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("profile") != ARCHIVE_PROFILE:
        raise ArchiveError(f"archive profile must be {ARCHIVE_PROFILE!r}")
    try:
        run_id = str(uuid.UUID(str(manifest.get("run_id"))))
    except ValueError as exc:
        raise ArchiveError("archive manifest run_id is not a UUID") from exc
    if run_id != root.name:
        raise ArchiveError("archive directory name differs from manifest run_id")
    inventory = manifest.get("files")
    if not isinstance(inventory, list):
        raise ArchiveError("archive files inventory must be a list")

    declared: set[str] = set()
    for index, entry in enumerate(inventory):
        if not isinstance(entry, dict):
            raise ArchiveError(f"archive files[{index}] must be an object")
        name = _safe_relative(str(entry.get("path", ""))).as_posix()
        if name in declared:
            raise ArchiveError(f"duplicate archive member: {name}")
        wanted = entry.get("sha256")
        if not isinstance(wanted, str) or _HEX_64.fullmatch(wanted) is None:
            raise ArchiveError(f"archive files[{index}].sha256 is invalid")
        byte_size = entry.get("bytes")
        if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 0:
            raise ArchiveError(f"archive files[{index}].bytes is invalid")
        path = root.joinpath(*pathlib.PurePosixPath(name).parts)
        if path.is_symlink() or not path.is_file():
            raise ArchiveError(f"archive member is missing: {name}")
        payload = path.read_bytes()
        if len(payload) != byte_size:
            raise ArchiveError(f"archive member size changed: {name}")
        if _sha256(payload) != wanted:
            raise ArchiveError(f"archive member digest changed: {name}")
        declared.add(name)

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "MANIFEST.json"
    }
    if actual != declared:
        raise ArchiveError(
            f"archive inventory differs from files: missing={sorted(declared - actual)}, "
            f"extra={sorted(actual - declared)}"
        )
    manifest_body = {key: value for key, value in manifest.items() if key != "root_sha256"}
    root_sha256 = _sha256(canonical_json(manifest_body))
    if manifest.get("root_sha256") != root_sha256:
        raise ArchiveError("archive inventory root digest changed")
    if expected_root_sha256 is not None and _HEX_64.fullmatch(expected_root_sha256) is None:
        raise ArchiveError("expected archive root is not a SHA-256 digest")
    if expected_root_sha256 is not None and expected_root_sha256 != root_sha256:
        raise ArchiveError("archive root differs from the separately retained receipt")
    return ArchiveReceipt(
        path=root,
        run_id=run_id,
        root_sha256=root_sha256,
        files=len(inventory),
    )
