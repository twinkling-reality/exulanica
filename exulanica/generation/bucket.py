"""The generation bucket, as the product's worker reaches it: put, get and list, nothing that
deletes.

A warm session reads its queue from an object storage bucket in the operator's Nebius account and
publishes its outputs there (``exulanica_pieces.queue`` gives the layout). The worker writes queue
entries and reads markers, heartbeats, receipts and pieces through the bucket's S3 endpoint with the
product's own signed requests (:class:`exulanica.store.object.ObjectRequests`), whose request set
holds nothing that deletes an object: clearing the bucket after a session is the operator's, with
their own key.

The worker's key is one JSON file the operator creates for it (``aws_access_key_id``,
``aws_secret_access_key``, ``endpoint``, ``region``, ``bucket``), named by
``EXULANICA_GENERATION_BUCKET_KEY_FILE`` and read once in this process; its secret never reaches a
repr, an exception or a log line.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final, Protocol

from exulanica.store.object import ObjectRequests, ObjectStoreCredentials, ObjectStoreLocation

__all__ = [
    "KEY_FILE_VARIABLE",
    "MAX_OBJECT_BYTES",
    "ONCE_TIMEOUT_SECONDS",
    "GenerationBucket",
    "GenerationBucketRefused",
    "SignedGenerationBucket",
    "bucket_from_environment",
    "bucket_from_key_file",
]

KEY_FILE_VARIABLE: Final = "EXULANICA_GENERATION_BUCKET_KEY_FILE"
#: The largest object the worker reads: a piece is about 154 KB, a receipt a few; a mesh it never
#: reads is far larger, and a read of one is refused rather than held in memory.
MAX_OBJECT_BYTES: Final = 8 << 20
#: The bound on each connect, read and write of a write the worker makes under a workspace's lock:
#: one attempt, so a stalled endpoint holds the lock seconds rather than minutes.
ONCE_TIMEOUT_SECONDS: Final = 10.0
_KEY_FIELDS: Final = frozenset(
    {"aws_access_key_id", "aws_secret_access_key", "endpoint", "region", "bucket"}
)


class GenerationBucketRefused(ValueError):
    """The bucket's key file, or an object read from the bucket, is not what it must be."""


class GenerationBucket(Protocol):
    """What the worker does with the bucket."""

    def put(self, key: str, data: bytes) -> None: ...

    def put_once(self, key: str, data: bytes) -> None:
        """One attempt, bounded by :data:`ONCE_TIMEOUT_SECONDS` for each connect, read and write:
        a write made while a lock others wait on is held."""
        ...

    def get(self, key: str) -> bytes | None: ...

    def keys(self, prefix: str) -> list[str]: ...


class SignedGenerationBucket:
    """The bucket over signed S3 requests; every body carries its SHA-256 and MD5."""

    def __init__(self, requests: ObjectRequests) -> None:
        self._requests = requests

    def __repr__(self) -> str:
        return f"SignedGenerationBucket({self._requests!r})"

    def put(self, key: str, data: bytes) -> None:
        md5 = base64.b64encode(hashlib.md5(data, usedforsecurity=False).digest()).decode()
        self._requests.put(key, data, len(data), md5, hashlib.sha256(data).hexdigest())

    def put_once(self, key: str, data: bytes) -> None:
        md5 = base64.b64encode(hashlib.md5(data, usedforsecurity=False).digest()).decode()
        self._requests.put(
            key,
            data,
            len(data),
            md5,
            hashlib.sha256(data).hexdigest(),
            attempts=1,
            timeout=ONCE_TIMEOUT_SECONDS,
        )

    def get(self, key: str) -> bytes | None:
        response = self._requests.get(key)
        if response is None:
            return None
        try:
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_OBJECT_BYTES:
                    raise GenerationBucketRefused(f"{key} is larger than the worker reads")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()

    def keys(self, prefix: str) -> list[str]:
        return sorted(key for key, _size in self._requests.iter_keys(prefix))


def bucket_from_key_file(path: Path) -> SignedGenerationBucket:
    """The bucket a worker key file names, read strictly."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise GenerationBucketRefused("the generation bucket key file is not readable") from error
    except ValueError:
        # The parser's message may quote the file, and the file holds a secret.
        raise GenerationBucketRefused("the generation bucket key file is not JSON") from None
    if not isinstance(document, Mapping) or set(document) != _KEY_FIELDS:
        raise GenerationBucketRefused(
            "the generation bucket key file holds exactly " + ", ".join(sorted(_KEY_FIELDS))
        )
    if not all(isinstance(document[name], str) and document[name] for name in _KEY_FIELDS):
        raise GenerationBucketRefused("every field of the bucket key file is non-empty text")
    location = ObjectStoreLocation(
        endpoint=document["endpoint"], bucket=document["bucket"], region=document["region"]
    )
    credentials = ObjectStoreCredentials(
        document["aws_access_key_id"], document["aws_secret_access_key"]
    )
    return SignedGenerationBucket(ObjectRequests(location, credentials))


def bucket_from_environment(
    environ: Mapping[str, str] | None = None,
) -> SignedGenerationBucket | None:
    """The bucket the deployment names, or None when no key file is named (no generation here)."""
    named = (environ if environ is not None else os.environ).get(KEY_FILE_VARIABLE)
    return None if not named else bucket_from_key_file(Path(named))
