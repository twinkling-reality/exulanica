"""S3-compatible content-addressed storage, so processes on separate hosts share one store.

**The same keys and the same guarantees.** An object's key is the prefix, the namespace and
``key_for``, exactly as :class:`~exulanica.store.local.LocalContentAddressedStore` lays a path out
under the data directory: ``<prefix>/blobs/sha-256/<aa>/<bb>/<hex>``. A row's ``storage_key``
therefore means the same thing on either backend, and moving a store from one to the other is a
key-for-key copy. A write to an existing key re-hashes what is stored and a read re-hashes what it
returns; neither ever absorbs a difference.

**Runtime credentials cannot erase.** :class:`ObjectRequests`, the request set built from runtime
credentials, has no request that deletes an object or a version (its one ``DELETE`` abandons an
unfinished multipart upload, which holds no object), and :class:`ObjectContentAddressedStore` has
no ``_privileged_purger``, so ``privileged_purger`` refuses it. Erasure is
:class:`PurgingObjectContentAddressedStore`, built only from separate purge credentials. It deletes
every version and delete marker of a key and then lists the key again: a version still there fails
the purge, so a tombstone is never completed over bytes that can still be retrieved, whether or not
the bucket keeps versions and whenever versioning was switched on. The bucket policy that denies the
runtime identity ``DeleteObject`` and ``DeleteObjectVersion`` is the other half, and it is the
operator's to set (docs/deployment.md section 4).

**Delivery stays mediated.** Nothing here returns a URL, presigned or otherwise. Bytes leave through
the API's own reads, after its permission and withdrawal checks, because holding a digest is not
authority. For the same reason a process's first request runs a bucket check, repeated every few
minutes and before every purge, which refuses a bucket anyone can list, a bucket with object lock
(locked versions cannot be erased), a replication configuration (a replica is a copy no purge sees)
and a lifecycle rule that expires or moves current objects under the prefix.

**Bounded memory.** A stream is spooled to a host-local file while it is hashed, because the key is
the hash of the whole and is known only at the end. An object above ``MULTIPART_THRESHOLD`` goes up
in parts; every body carries a signed SHA-256 and a Content-MD5, so the endpoint checks the bytes it
keeps, and a multipart object's SHA-256 is compared with its key before the upload is completed.
Reads stream, and a dropped connection resumes with a range request pinned to the object's ETag.

Credentials never appear in a repr, an exception or a log record. Errors name the operation, the
HTTP status, the endpoint's error code and the object key.

The signed requests and where they go are :mod:`exulanica.store.object_requests`'s, and the bucket
check is :mod:`exulanica.store.object_bucket`'s.
"""

from __future__ import annotations

import base64
import contextlib
import functools
import hashlib
import io
import os
import re
import tempfile
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Final

import httpx

from exulanica.errors import (
    BlobNotFoundError,
    ImmutableKeyError,
    IntegrityError,
    ObjectStoreRefused,
    ObjectStoreUnavailable,
)
from exulanica.evidence.blob import BlobId
from exulanica.store.base import (
    ContentAddressedStore,
    PrivilegedPurger,
    PurgeAuthorization,
    PutResult,
)
from exulanica.store.namespaces import SHARED_NAMESPACES, WORKSPACE_NAMESPACES, WorkspaceStores
from exulanica.store.object_bucket import BucketCheck, BucketGuard
from exulanica.store.object_requests import (
    _CHUNK,
    ATTEMPTS,
    ObjectPurgeRequests,
    ObjectRequests,
    ObjectStoreCredentials,
    ObjectStoreLocation,
    _Head,
    _malformed,
)

__all__ = [
    "ATTEMPTS",
    "MULTIPART_THRESHOLD",
    "PART_SIZE",
    "BucketCheck",
    "BucketGuard",
    "ObjectContentAddressedStore",
    "ObjectPurgeRequests",
    "ObjectRequests",
    "ObjectStoreCredentials",
    "ObjectStoreLocation",
    "ObjectWorkspaceStores",
    "PurgingObjectContentAddressedStore",
    "abort_stale_uploads",
]

#: Objects up to this size go up in one request; larger ones in parts.
MULTIPART_THRESHOLD: Final = 64 << 20
#: Part size, raised in whole MiB when an object would need more than ``_MAX_PARTS`` parts.
PART_SIZE: Final = 16 << 20
_MAX_PARTS: Final = 10_000
_KEY_SHAPE: Final = re.compile(r"^sha-256/([0-9a-f]{2})/([0-9a-f]{2})/([0-9a-f]{64})$")
_SPOOL_PREFIX: Final = "put-"


# -- reading -------------------------------------------------------------------------------------


class _ObjectReader(io.RawIOBase):
    """A streaming GET that resumes where it stopped when the connection drops.

    A resumed request asks for the remaining range and names the first response's ETag, so bytes
    from a different object can never be spliced onto the ones already read.
    """

    def __init__(self, requests: ObjectRequests, key: str, missing: Exception) -> None:
        super().__init__()
        self._requests = requests
        self._key = key
        self._name = requests._subject(key)
        self._offset = 0
        self._size: int | None = None
        self._etag: str | None = None
        self._response: httpx.Response | None = None
        self._chunks: Iterator[bytes] | None = None
        self._pending = b""
        self._resumed = 0
        self._begin(missing)

    def _begin(self, missing: Exception | None = None) -> None:
        response = self._requests.get(
            self._key, start=self._offset, if_match=self._etag if self._offset else None
        )
        if response is None:
            if missing is not None:
                raise missing
            raise IntegrityError(f"{self._name} disappeared while it was being read")
        skip = 0
        if response.status_code == 206:
            if not response.headers.get("content-range", "").startswith(f"bytes {self._offset}-"):
                response.close()
                raise _malformed("GET", f"{self._name} was answered from another offset")
        elif self._offset:
            skip = self._offset  # the endpoint ignored the range: discard what was already read
        if self._offset == 0:
            try:
                self._size = int(response.headers["content-length"])
            except (KeyError, ValueError):
                response.close()
                raise _malformed("GET", f"{self._name} was answered without a length") from None
            self._etag = response.headers.get("etag")
        elif self._etag is not None and response.headers.get("etag") != self._etag:
            response.close()
            raise IntegrityError(f"{self._name} changed while it was being read")
        self._response = response
        self._chunks = self._skipping(response.iter_raw(_CHUNK), skip)

    @staticmethod
    def _skipping(chunks: Iterator[bytes], skip: int) -> Iterator[bytes]:
        for chunk in chunks:
            if skip >= len(chunk):
                skip -= len(chunk)
                continue
            yield chunk[skip:]
            skip = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        view = memoryview(buffer).cast("B")
        while not self._pending:
            if self._chunks is None:
                return 0
            try:
                self._pending = next(self._chunks)
            except StopIteration:
                self._end_of_response()
            except httpx.TransportError:
                self._resume()
        count = min(len(view), len(self._pending))
        view[:count] = self._pending[:count]
        self._pending = self._pending[count:]
        self._offset += count
        return count

    def _end_of_response(self) -> None:
        self._release()
        if self._size is not None and self._offset < self._size:
            self._resume()

    def _resume(self) -> None:
        self._release()
        self._resumed += 1
        if self._offset and self._etag is None:
            # Nothing would pin the rest to the same object, so the read stops rather than splice.
            raise ObjectStoreUnavailable(
                "object_store_unreachable",
                f"GET {self._name}: the read broke off and the endpoint gave no ETag to resume by",
            )
        if self._resumed >= ATTEMPTS:
            raise ObjectStoreUnavailable(
                "object_store_unreachable", f"GET {self._name}: the read broke off {ATTEMPTS} times"
            )
        self._requests._pause(self._resumed)
        if self._size is not None and self._offset >= self._size:
            return
        self._begin()

    def _release(self) -> None:
        if self._response is not None:
            self._response.close()
        self._response = None
        self._chunks = None

    def close(self) -> None:
        self._release()
        super().close()


# -- writing sources ------------------------------------------------------------------------------


class _Source:
    """Bytes to upload, readable as bounded chunks from any offset as often as a retry needs."""

    size: int

    def chunks(self, offset: int, length: int) -> Iterator[bytes]:  # pragma: no cover - abstract
        raise NotImplementedError


class _MemorySource(_Source):
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.size = len(payload)

    def chunks(self, offset: int, length: int) -> Iterator[bytes]:
        view = memoryview(self._payload)
        for start in range(offset, offset + length, _CHUNK):
            yield bytes(view[start : min(start + _CHUNK, offset + length)])


class _FileSource(_Source):
    def __init__(self, path: Path, size: int) -> None:
        self._path = path
        self.size = size

    def chunks(self, offset: int, length: int) -> Iterator[bytes]:
        with self._path.open("rb") as handle:
            handle.seek(offset)
            remaining = length
            while remaining:
                chunk = handle.read(min(_CHUNK, remaining))
                if not chunk:
                    raise IntegrityError(
                        "a spooled upload is shorter than it was when it was hashed"
                    )
                remaining -= len(chunk)
                yield chunk


def _md5_base64(digest: bytes) -> str:
    return base64.b64encode(digest).decode("ascii")


# -- the stores ------------------------------------------------------------------------------------


class ObjectContentAddressedStore(ContentAddressedStore):
    """One namespace of an S3-compatible bucket, with the local store's keys and guarantees.

    Built from runtime credentials it has no erasure path at all; see
    :class:`PurgingObjectContentAddressedStore`.
    """

    def __init__(
        self, requests: ObjectRequests, namespace: str, *, spool: Path, guard: BucketGuard
    ) -> None:
        if not namespace or namespace.startswith("/") or namespace.endswith("/"):
            raise ValueError(f"a namespace is a key prefix without edge slashes, got {namespace!r}")
        self._requests = requests
        self._namespace = namespace
        self._spool = spool
        self._guard = guard

    def __repr__(self) -> str:
        return f"{type(self).__name__}(namespace={self._namespace!r})"

    @property
    def namespace(self) -> str:
        return self._namespace

    # -- keys ---------------------------------------------------------------------------

    def key_for(self, blob_id: BlobId) -> str:
        digest = blob_id.hex
        return f"sha-256/{digest[:2]}/{digest[2:4]}/{digest}"

    def _object_key(self, blob_id: BlobId) -> str:
        return f"{self._namespace}/{self.key_for(blob_id)}"

    # -- writes -------------------------------------------------------------------------

    def put_bytes(self, data: bytes) -> PutResult:
        if not isinstance(data, bytes | bytearray | memoryview):
            raise TypeError(f"put_bytes needs bytes, got {type(data).__name__}")
        payload = bytes(data)
        return self._put(
            BlobId.of_bytes(payload),
            _md5_base64(hashlib.md5(payload, usedforsecurity=False).digest()),
            _MemorySource(payload),
            payload,
        )

    def put_stream(self, stream: IO[bytes]) -> PutResult:
        # Spooled to a private host-local file while hashing, so the source is read exactly once
        # and the bytes sent are the bytes hashed, however the source behaves afterwards.
        self._spool.mkdir(parents=True, exist_ok=True, mode=0o700)
        sha256 = hashlib.sha256()
        md5 = hashlib.md5(usedforsecurity=False)
        size = 0
        handle, name = tempfile.mkstemp(dir=self._spool, prefix=_SPOOL_PREFIX)
        path = Path(name)
        try:
            with os.fdopen(handle, "wb") as out:
                while chunk := stream.read(_CHUNK):
                    sha256.update(chunk)
                    md5.update(chunk)
                    size += len(chunk)
                    out.write(chunk)
            return self._put(
                BlobId(sha256.digest()), _md5_base64(md5.digest()), _FileSource(path, size), None
            )
        finally:
            path.unlink(missing_ok=True)

    def put_file(self, path: str | os.PathLike[str]) -> PutResult:
        with Path(path).open("rb") as handle:
            return self.put_stream(handle)

    def _put(
        self, blob_id: BlobId, md5_base64: str, source: _Source, payload: bytes | None
    ) -> PutResult:
        self._guard.require()
        key = self._object_key(blob_id)
        existing = self._requests.head(key)
        if existing is not None:
            confirmed = self._confirm_existing(blob_id, key, existing, source.size)
            if confirmed is not None:
                return confirmed
        if source.size <= MULTIPART_THRESHOLD:
            body: bytes | Callable[[], Iterator[bytes]] = (
                payload if payload is not None else lambda: source.chunks(0, source.size)
            )
            self._requests.put(key, body, source.size, md5_base64, blob_id.hex)
        else:
            self._put_parts(key, blob_id, source)
        written = self._requests.head(key)
        if written is None or written.size != source.size:
            raise IntegrityError(
                f"{self.key_for(blob_id)} was accepted but the store does not hold it at that size"
            )
        return PutResult(blob_id=blob_id, byte_size=source.size, created=True)

    def _put_parts(self, key: str, blob_id: BlobId, source: _Source) -> None:
        part_size = max(PART_SIZE, -(-source.size // _MAX_PARTS))
        part_size = -(-part_size // (1 << 20)) * (1 << 20)
        upload_id = self._requests.create_upload(key)
        try:
            whole = hashlib.sha256()
            parts: list[tuple[int, str]] = []
            for number, offset in enumerate(range(0, source.size, part_size), start=1):
                length = min(part_size, source.size - offset)
                part_sha256 = hashlib.sha256()
                part_md5 = hashlib.md5(usedforsecurity=False)
                for chunk in source.chunks(offset, length):
                    whole.update(chunk)
                    part_sha256.update(chunk)
                    part_md5.update(chunk)
                parts.append(
                    (
                        number,
                        self._requests.upload_part(
                            key,
                            upload_id,
                            number,
                            functools.partial(source.chunks, offset, length),
                            length,
                            _md5_base64(part_md5.digest()),
                            part_sha256.hexdigest(),
                        ),
                    )
                )
            if whole.digest() != blob_id.digest:
                raise IntegrityError(
                    f"the bytes for {self.key_for(blob_id)} changed while they were being stored"
                )
            # False when an earlier attempt completed it and its response was lost; the key decides.
            completed = self._requests.complete_upload(key, upload_id, parts)
            if not completed and self._requests.head(key) is None:
                raise IntegrityError(
                    f"{self.key_for(blob_id)}: the upload vanished before it was completed"
                )
        except BaseException:
            # Best effort: the sweep abandons it later, and the first error is the one that stands.
            with contextlib.suppress(Exception):
                self._requests.abort_upload(key, upload_id)
            raise

    def _confirm_existing(
        self, blob_id: BlobId, key: str, head: _Head, byte_size: int
    ) -> PutResult | None:
        """A key that already exists must already hold exactly these bytes.

        Re-hashed rather than size-checked, as the local store does, so a same-length substitution
        is refused. None when the object vanished between the two requests, which leaves the key
        free for this write.
        """
        if head.size != byte_size:
            raise ImmutableKeyError(
                f"key {self.key_for(blob_id)} already holds {head.size} bytes, not {byte_size}. "
                "Under content addressing this is a collision or a corrupted store, and it is "
                "never absorbed."
            )
        try:
            reader = _ObjectReader(self._requests, key, BlobNotFoundError(key))
        except BlobNotFoundError:
            return None
        hasher = hashlib.sha256()
        with reader:
            while chunk := reader.read(_CHUNK):
                hasher.update(chunk)
        if hasher.digest() != blob_id.digest:
            raise ImmutableKeyError(
                f"key {self.key_for(blob_id)} already holds different content: stored bytes "
                "hash to "
                f"{hasher.hexdigest()}. Under content addressing this is a collision or a "
                "corrupted store, and it is never absorbed as an overwrite."
            )
        return PutResult(blob_id=blob_id, byte_size=byte_size, created=False)

    # -- reads --------------------------------------------------------------------------

    def _reader(self, blob_id: BlobId) -> _ObjectReader:
        self._guard.require()
        return _ObjectReader(
            self._requests, self._object_key(blob_id), BlobNotFoundError(self.key_for(blob_id))
        )

    def get(self, blob_id: BlobId) -> bytes:
        received = bytearray()
        hasher = hashlib.sha256()
        with self._reader(blob_id) as reader:
            while chunk := reader.read(_CHUNK):
                hasher.update(chunk)
                received += chunk
        if hasher.digest() != blob_id.digest:
            raise IntegrityError(
                f"stored bytes under {self.key_for(blob_id)} hash to {hasher.hexdigest()}. The "
                "key is a claim about the content, and the claim is false."
            )
        return bytes(received)

    def open(self, blob_id: BlobId) -> IO[bytes]:
        return io.BufferedReader(self._reader(blob_id), buffer_size=_CHUNK)

    def _spool_directory(self) -> Path:
        # The host-local directory a stream is spooled to before it is uploaded.
        self._spool.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self._spool

    def exists(self, blob_id: BlobId) -> bool:
        self._guard.require()
        return self._requests.head(self._object_key(blob_id)) is not None

    def size(self, blob_id: BlobId) -> int:
        self._guard.require()
        head = self._requests.head(self._object_key(blob_id))
        if head is None:
            raise BlobNotFoundError(self.key_for(blob_id))
        return head.size

    def iter_blob_ids(self) -> Iterator[BlobId]:
        for blob_id, _size in self.iter_blob_sizes():
            yield blob_id

    def iter_blob_sizes(self) -> Iterator[tuple[BlobId, int]]:
        """Each object and its size as the listing states it: one request a thousand objects,
        where :meth:`size` asks once an object."""
        self._guard.require()
        base = f"{self._namespace}/"
        for key, size in self._requests.iter_keys(f"{base}sha-256/"):
            match = _KEY_SHAPE.match(key[len(base) :])
            if match and match[3][:2] == match[1] and match[3][2:4] == match[2]:
                yield BlobId.from_hex(match[3]), size


class PurgingObjectContentAddressedStore(ObjectContentAddressedStore):
    """The same namespace, built from the purge identity's credentials, with an erasure path."""

    def __init__(
        self, requests: ObjectPurgeRequests, namespace: str, *, spool: Path, guard: BucketGuard
    ) -> None:
        if not isinstance(requests, ObjectPurgeRequests):
            raise TypeError("a purging store is built only from the purge identity's requests")
        super().__init__(requests, namespace, spool=spool, guard=guard)
        self._purge_requests = requests

    def _privileged_purger(self, authorization: PurgeAuthorization) -> PrivilegedPurger:
        """Not part of ``ContentAddressedStore``. Reached only via ``privileged_purger``."""
        return _ObjectPurger(self, authorization)

    def _erase(self, blob_id: BlobId) -> bool:
        check = self._guard.require(fresh=True, erasing=True)
        key = self._object_key(blob_id)
        subject = self.key_for(blob_id)
        requests = self._purge_requests
        versions = requests.versions_of(key)
        if versions is None:
            # Without a version listing, a plain delete is erasure only where the bucket is known
            # never to keep versions; anywhere else a version could outlive it unseen.
            if check.versioning != "off":
                raise ObjectStoreRefused(
                    "object_store_versions_unlistable",
                    f"PURGE {subject}: the endpoint lists no versions and the bucket's versioning "
                    f"is {check.versioning}",
                )
            if requests.head(key) is None:
                return False
            requests.delete_object_version(key, None)
            if requests.head(key) is not None:
                raise ObjectStoreRefused(
                    "object_store_purge_incomplete", f"PURGE {subject}: the object is still there"
                )
            return True
        held_bytes = False
        for version_id, is_marker in versions:
            requests.delete_object_version(key, version_id)
            held_bytes = held_bytes or not is_marker
        remaining = requests.versions_of(key)
        if remaining is None or remaining:
            raise ObjectStoreRefused(
                "object_store_purge_incomplete",
                f"PURGE {subject}: "
                + (
                    "the versions could not be listed again"
                    if remaining is None
                    else f"{len(remaining)} version(s) remain after deletion"
                ),
            )
        if requests.head(key) is not None:
            raise ObjectStoreRefused(
                "object_store_purge_incomplete", f"PURGE {subject}: the object is still there"
            )
        return held_bytes


@dataclass(frozen=True, slots=True)
class _ObjectPurger(PrivilegedPurger):
    """Erasure for the object backend. Idempotent, so a resumed purge job is safe."""

    store: PurgingObjectContentAddressedStore
    authorization: PurgeAuthorization

    def purge(self, blob_id: BlobId) -> bool:
        return self.store._erase(blob_id)


class ObjectWorkspaceStores(WorkspaceStores):
    """Workspace namespaces as key prefixes under one namespace of the bucket."""

    def __init__(
        self,
        requests: ObjectRequests,
        namespace: str,
        *,
        spool: Path,
        guard: BucketGuard,
    ) -> None:
        self._requests = requests
        self._namespace = namespace
        self._spool = spool
        self._guard = guard

    def __repr__(self) -> str:
        return f"{type(self).__name__}(namespace={self._namespace!r})"

    def for_workspace(self, workspace_id: uuid.UUID) -> ObjectContentAddressedStore:
        if not isinstance(workspace_id, uuid.UUID):
            raise TypeError(
                f"a workspace namespace is named by a uuid, not {type(workspace_id).__name__}"
            )
        namespace = f"{self._namespace}/{workspace_id.hex}"
        if isinstance(self._requests, ObjectPurgeRequests):
            return PurgingObjectContentAddressedStore(
                self._requests, namespace, spool=self._spool, guard=self._guard
            )
        return ObjectContentAddressedStore(
            self._requests, namespace, spool=self._spool, guard=self._guard
        )

    def iter_workspace_ids(self) -> Iterator[uuid.UUID]:
        self._guard.require()
        base = f"{self._namespace}/"
        for common in self._requests.iter_prefixes(base):
            name = common[len(base) :].rstrip("/")
            try:
                workspace_id = uuid.UUID(hex=name)
            except ValueError:
                continue
            if workspace_id.hex == name:
                yield workspace_id


def abort_stale_uploads(requests: ObjectRequests, prefix: str, *, before: datetime) -> int:
    """Abandon every unfinished multipart upload of this store started before ``before``.

    A process killed mid-upload leaves its parts on the endpoint, and those parts are bytes of a
    photograph that no key names and no purge reaches. Only keys with this store's shape under
    ``prefix`` are touched: a registered namespace, with its workspace for a per-workspace one,
    then the layout ``key_for`` writes. Anything else in the bucket is somebody else's. Returns how
    many were abandoned.
    """
    namespaces = [re.escape(name) for name in SHARED_NAMESPACES] + [
        f"{re.escape(name)}/[0-9a-f]{{32}}" for name in WORKSPACE_NAMESPACES
    ]
    shape = re.compile(
        re.escape(prefix)
        + f"(?:{'|'.join(namespaces)})"
        + r"/sha-256/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}"
    )
    aborted = 0
    # Aborting while listing is safe: the next page starts after the markers of the last one.
    for upload in requests.iter_uploads(prefix):
        if not shape.fullmatch(upload.key):
            continue
        if upload.initiated.astimezone(UTC) < before.astimezone(UTC):
            requests.abort_upload(upload.key, upload.upload_id)
            aborted += 1
    return aborted
