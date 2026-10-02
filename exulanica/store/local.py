"""Local filesystem content-addressed store.

The layout is chosen so an S3-compatible backend can serve the same keys without a migration:

    sha-256/<aa>/<bb>/<64 hex characters>

Two levels of two-hex-character fanout keeps any single directory under a few thousand entries
at corpus scale, and the same string is a perfectly ordinary object key with a prefix that
supports the listing patterns S3 offers.

Writes are atomic: bytes land in a temporary file in the same directory and are then moved into
place with ``os.replace``, so a crash mid-write never leaves a partial object under a key that
claims to be a hash of complete content. Written objects are then chmod'd read-only. That is a
speed bump, not a guarantee, and it is described as one: the process that wrote the file can
chmod it back. It exists to make an accidental overwrite fail loudly.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Final

from exulanica.errors import BlobNotFoundError, ImmutableKeyError, IntegrityError
from exulanica.evidence.blob import DIGEST_BYTES, BlobId
from exulanica.store.base import (
    ContentAddressedStore,
    PrivilegedPurger,
    PurgeAuthorization,
    PutResult,
)

__all__ = ["LocalContentAddressedStore"]

_PREFIX: Final = "sha-256"
_CHUNK: Final = 1 << 20
_READ_ONLY: Final = 0o444


class LocalContentAddressedStore(ContentAddressedStore):
    """A content-addressed store rooted at a directory on the local filesystem."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # -- keys ---------------------------------------------------------------------------

    def key_for(self, blob_id: BlobId) -> str:
        digest = blob_id.hex
        return f"{_PREFIX}/{digest[:2]}/{digest[2:4]}/{digest}"

    def _path_for(self, blob_id: BlobId) -> Path:
        return self._root / self.key_for(blob_id)

    # -- writes -------------------------------------------------------------------------

    def put_bytes(self, data: bytes) -> PutResult:
        if not isinstance(data, bytes | bytearray | memoryview):
            raise TypeError(f"put_bytes needs bytes, got {type(data).__name__}")
        payload = bytes(data)
        blob_id = BlobId.of_bytes(payload)
        return self._commit(blob_id, [payload], len(payload))

    def put_stream(self, stream: IO[bytes]) -> PutResult:
        # Streamed to a temporary file while hashing, so the source is read exactly once.
        target_dir = self._root / _PREFIX / "_incoming"
        target_dir.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        byte_size = 0
        handle, temp_name = tempfile.mkstemp(dir=target_dir, prefix="put-")
        temp_path = Path(temp_name)
        try:
            with os.fdopen(handle, "wb") as out:
                while chunk := stream.read(_CHUNK):
                    hasher.update(chunk)
                    byte_size += len(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            blob_id = BlobId(hasher.digest())
            return self._move_into_place(blob_id, temp_path, byte_size)
        finally:
            temp_path.unlink(missing_ok=True)

    def put_file(self, path: str | os.PathLike[str]) -> PutResult:
        with Path(path).open("rb") as handle:
            return self.put_stream(handle)

    def _commit(self, blob_id: BlobId, chunks: list[bytes], byte_size: int) -> PutResult:
        destination = self._path_for(blob_id)
        if destination.exists():
            return self._confirm_existing(blob_id, destination, byte_size)
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=destination.parent, prefix="put-")
        temp_path = Path(temp_name)
        try:
            with os.fdopen(handle, "wb") as out:
                for chunk in chunks:
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            return self._move_into_place(blob_id, temp_path, byte_size)
        finally:
            temp_path.unlink(missing_ok=True)

    def _move_into_place(self, blob_id: BlobId, temp_path: Path, byte_size: int) -> PutResult:
        destination = self._path_for(blob_id)
        if destination.exists():
            return self._confirm_existing(blob_id, destination, byte_size)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp_path, destination)
        os.chmod(destination, _READ_ONLY)
        return PutResult(blob_id=blob_id, byte_size=byte_size, created=True)

    def _confirm_existing(self, blob_id: BlobId, path: Path, byte_size: int) -> PutResult:
        """A key that already exists must already hold exactly these bytes.

        The stored object is re-hashed rather than merely size-checked. A same-length
        substitution is exactly the case a size check misses, and it is also the case where a
        citation would keep resolving while pointing at content nobody chose. Deduplication is
        the common path here, so this costs one read of a file that is about to be skipped, in
        return for the store's central claim being true rather than probable.
        """
        with path.open("rb") as handle:
            actual = BlobId.of_stream(handle)
        if actual != blob_id or path.stat().st_size != byte_size:
            raise ImmutableKeyError(
                f"key {self.key_for(blob_id)} already holds different content: stored bytes "
                f"hash to {actual.hex}. Under content addressing this is a collision or a "
                "corrupted store, and it is never absorbed as an overwrite."
            )
        return PutResult(blob_id=blob_id, byte_size=byte_size, created=False)

    # -- reads --------------------------------------------------------------------------

    def get(self, blob_id: BlobId) -> bytes:
        path = self._require(blob_id)
        data = path.read_bytes()
        actual = BlobId.of_bytes(data)
        if actual != blob_id:
            raise IntegrityError(
                f"stored bytes under {self.key_for(blob_id)} hash to {actual.hex}. The key is "
                "a claim about the content, and the claim is false."
            )
        return data

    def open(self, blob_id: BlobId) -> IO[bytes]:
        return self._require(blob_id).open("rb")

    def _spool_directory(self) -> Path:
        # The directory a streamed write lands in first: the store's own disk.
        incoming = self._root / _PREFIX / "_incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        return incoming

    def exists(self, blob_id: BlobId) -> bool:
        return self._path_for(blob_id).is_file()

    def size(self, blob_id: BlobId) -> int:
        return self._require(blob_id).stat().st_size

    def iter_blob_ids(self) -> Iterator[BlobId]:
        base = self._root / _PREFIX
        if not base.is_dir():
            return
        for path in sorted(base.glob("*/*/*")):
            name = path.name
            if path.is_file() and len(name) == DIGEST_BYTES * 2:
                try:
                    yield BlobId.from_hex(name)
                except ValueError:  # pragma: no cover - a stray file, not a blob
                    continue

    def _require(self, blob_id: BlobId) -> Path:
        path = self._path_for(blob_id)
        if not path.is_file():
            raise BlobNotFoundError(self.key_for(blob_id))
        return path

    # -- the privileged erasure path ----------------------------------------------------

    def _privileged_purger(self, authorization: PurgeAuthorization) -> PrivilegedPurger:
        """Not part of ``ContentAddressedStore``. Reached only via ``privileged_purger``."""
        return _LocalPurger(self, authorization)


@dataclass(frozen=True, slots=True)
class _LocalPurger(PrivilegedPurger):
    """Erasure for the local backend. Idempotent, so a resumed purge job is safe."""

    store: LocalContentAddressedStore
    authorization: PurgeAuthorization

    def purge(self, blob_id: BlobId) -> bool:
        path = self.store._path_for(blob_id)
        if not path.is_file():
            return False
        # The object was chmod'd read-only on write. Unlink needs the directory to be
        # writable, not the file, but restore write permission first so the behaviour is the
        # same on filesystems that check it.
        os.chmod(path, 0o644)
        path.unlink()
        return True
