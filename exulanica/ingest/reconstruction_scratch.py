"""Short-lived, deletion-safe scratch for multi-photograph pose recovery.

Original photographs are copied here only while a scene job is actively computing. Durable
receipts go to the content-addressed store. A root lock prevents the cleanup sweep from racing a
live worker, and every deletion target is reconstructed from two UUID path components rather
than accepted as an arbitrary path.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import logging
import os
import shutil
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from exulanica.evidence.blob import BlobId
from exulanica.store import ContentAddressedStore

__all__ = [
    "ScratchBusy",
    "ScratchSource",
    "active_scene_scratch",
    "cleanup_abandoned_scene_scratch",
    "cleanup_scene_scratch",
    "scene_scratch_key",
    "stage_scene_sources",
]


class ScratchBusy(RuntimeError):
    """Another process currently owns this scene scratch directory."""


@dataclass(frozen=True, slots=True)
class ScratchSource:
    filename: str
    blob_id: BlobId

    def __post_init__(self) -> None:
        if Path(self.filename).name != self.filename or self.filename in {"", ".", ".."}:
            raise ValueError("scratch source filenames must be non-empty basenames")


def scene_scratch_key(workspace_id: uuid.UUID, job_id: uuid.UUID) -> str:
    """The only relative key shape accepted by cleanup."""
    return f"{workspace_id}/{job_id}"


def _target(root: Path, key: str) -> Path:
    parts = Path(key).parts
    if len(parts) != 2:
        raise ValueError("a scene scratch key must contain workspace and job UUIDs")
    try:
        canonical = scene_scratch_key(uuid.UUID(parts[0]), uuid.UUID(parts[1]))
    except ValueError as error:
        raise ValueError("a scene scratch key must contain workspace and job UUIDs") from error
    if key != canonical:
        raise ValueError("a scene scratch key must use canonical UUID components")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = root / canonical
    if target.is_symlink():
        raise ValueError("a scene scratch directory cannot be a symbolic link")
    return target


@contextmanager
def active_scene_scratch(root: Path, key: str) -> Iterator[Path]:
    """Create and exclusively hold one job directory for its whole sensitive lifetime."""
    target = _target(root, key)
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.chmod(0o700)
    lock_path = target / ".active.lock"
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ScratchBusy(f"scene scratch {key} is active in another process") from error
        try:
            yield target
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _sha256(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.digest()


def stage_scene_sources(
    store: ContentAddressedStore,
    job_directory: Path,
    sources: Sequence[ScratchSource],
) -> Path:
    """Materialize the exact manifest source set, verifying reuse and refusing extra files."""
    if not sources or len({source.filename for source in sources}) != len(sources):
        raise ValueError("scratch sources must be non-empty with unique filenames")
    source_directory = job_directory / "source"
    if source_directory.is_symlink():
        raise ValueError("the scratch source directory cannot be a symbolic link")
    source_directory.mkdir(mode=0o700, exist_ok=True)
    expected = {source.filename for source in sources}
    actual = {path.name for path in source_directory.iterdir()}
    if actual - expected:
        raise ValueError("the scratch source directory contains undeclared files")

    for source in sources:
        destination = source_directory / source.filename
        if destination.is_symlink():
            raise ValueError("a staged source cannot be a symbolic link")
        if destination.exists():
            if not destination.is_file() or _sha256(destination) != source.blob_id.digest:
                raise ValueError(f"staged source bytes disagree with {source.filename}")
            continue
        data = store.get(source.blob_id)
        temporary = source_directory / f".{source.filename}.{os.getpid()}.tmp"
        with temporary.open("xb") as stream:
            os.chmod(temporary, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        if _sha256(destination) != source.blob_id.digest:
            raise ValueError(f"stored source bytes disagree with {source.filename}")
    return source_directory


def cleanup_scene_scratch(root: Path, key: str) -> bool:
    """Remove one inactive exact job directory. False means absent or still active."""
    target = _target(root, key)
    if not target.exists():
        return False
    lock_path = target / ".active.lock"
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        if any(target.rglob("container-cleanup-required.json")):
            logging.getLogger(__name__).warning(
                "scene scratch retained: external container termination is unconfirmed",
                extra={"scratch_key": key},
            )
            return False
        shutil.rmtree(target)
        with contextlib.suppress(OSError):
            workspace_directory = target.parent
            workspace_directory.rmdir()
        return True


def cleanup_abandoned_scene_scratch(
    root: Path,
    *,
    active_keys: frozenset[str],
    older_than_seconds: float,
    now: float | None = None,
) -> tuple[str, ...]:
    """Sweep only canonical inactive job directories older than the configured grace period."""
    if older_than_seconds < 0:
        raise ValueError("the abandoned scratch grace period cannot be negative")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    cutoff = (time.time() if now is None else now) - older_than_seconds
    removed: list[str] = []
    for workspace_directory in sorted(root.iterdir()):
        if not workspace_directory.is_dir() or workspace_directory.is_symlink():
            continue
        for job_directory in sorted(workspace_directory.iterdir()):
            if not job_directory.is_dir() or job_directory.is_symlink():
                continue
            key = f"{workspace_directory.name}/{job_directory.name}"
            try:
                _target(root, key)
            except ValueError:
                continue
            if key in active_keys or job_directory.stat().st_mtime > cutoff:
                continue
            if cleanup_scene_scratch(root, key):
                removed.append(key)
    return tuple(removed)
