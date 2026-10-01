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
"""

from __future__ import annotations

import base64
import contextlib
import functools
import hashlib
import io
import ipaddress
import os
import random
import re
import ssl
import tempfile
import threading
import time
import urllib.parse
import uuid
import weakref
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Final
from xml.sax.saxutils import escape

import httpx

from exulanica.errors import (
    BlobNotFoundError,
    ImmutableKeyError,
    IntegrityError,
    ObjectStoreConfigurationError,
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
from exulanica.store.namespaces import WorkspaceStores
from exulanica.store.sigv4 import (
    EMPTY_PAYLOAD_SHA256,
    RequestSigner,
    canonical_query,
    s3_canonical_uri,
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

#: Every request is tried at most this many times; only transient failures are retried.
ATTEMPTS: Final = 4
_BACKOFF_SECONDS: Final = 0.25
_BACKOFF_CAP_SECONDS: Final = 5.0
_CONNECT_TIMEOUT_SECONDS: Final = 10.0
#: Per read or write on the socket, not per request: a slow transfer that keeps moving continues.
_IO_TIMEOUT_SECONDS: Final = 60.0
#: Objects up to this size go up in one request; larger ones in parts.
MULTIPART_THRESHOLD: Final = 64 << 20
#: Part size, raised in whole MiB when an object would need more than ``_MAX_PARTS`` parts.
PART_SIZE: Final = 16 << 20
_MAX_PARTS: Final = 10_000
_CHUNK: Final = 1 << 20
_LIST_PAGE: Final = 1000
#: A listing of 1,000 keys is about a third of a megabyte; nothing a store answers is near this.
_MAX_DOCUMENT_BYTES: Final = 8 << 20
_MAX_ERROR_BYTES: Final = 64 << 10
_RETRIED_STATUS: Final = frozenset({408, 429, 500, 502, 503, 504})
_RETRIED_CODES: Final = frozenset(
    {
        "SlowDown",
        "InternalError",
        "RequestTimeout",
        "ServiceUnavailable",
        "Throttling",
        "ThrottlingException",
        # The endpoint recomputed a body's digest and it differed: a transit fault, since every
        # body sent here is hashed from bytes this process holds or spooled itself.
        "BadDigest",
        "XAmzContentSHA256Mismatch",
    }
)
_DENIED_CODES: Final = frozenset(
    {
        "AccessDenied",
        "Forbidden",
        "SignatureDoesNotMatch",
        "InvalidAccessKeyId",
        "AllAccessDisabled",
    }
)
_KEY_SHAPE: Final = re.compile(r"^sha-256/([0-9a-f]{2})/([0-9a-f]{2})/([0-9a-f]{64})$")
_BUCKET: Final = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_PREFIX: Final = re.compile(r"^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*$")
_REGION: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")
_SPOOL_PREFIX: Final = "put-"


def _trust(ca_file: str | None) -> ssl.SSLContext:
    """Who the endpoint's certificate must chain to: the named CA file, else certifi's bundle.

    Chosen here rather than left to the environment, so a variable in the operator's shell cannot
    widen what this process trusts.
    """
    import certifi

    return ssl.create_default_context(cafile=ca_file or certifi.where())


def _refuse_setting(message: str) -> ObjectStoreConfigurationError:
    return ObjectStoreConfigurationError("object_store_misconfigured", message)


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class ObjectStoreLocation:
    """Where the store lives: an endpoint origin, a bucket, a region and an optional key prefix.

    Holds no secret. Plain ``http`` is accepted only for a loopback host, or for an isolated
    container network when ``plaintext_network`` says so: Signature Version 4 authenticates a
    request, and it does not hide the photographs the request carries.
    """

    endpoint: str
    bucket: str
    region: str
    prefix: str = ""
    addressing: str = "path"
    ca_file: str | None = None
    plaintext_network: bool = False

    def __post_init__(self) -> None:
        parts = urllib.parse.urlsplit(self.endpoint)
        if parts.scheme not in ("https", "http"):
            raise _refuse_setting("the object store endpoint must be an https:// origin")
        if "@" in parts.netloc:
            raise _refuse_setting("the object store endpoint must not carry userinfo")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            raise _refuse_setting(
                "the object store endpoint is an origin: no path, query or fragment"
            )
        host = parts.hostname
        if not host:
            raise _refuse_setting("the object store endpoint names no host")
        try:
            _port = parts.port
        except ValueError:
            raise _refuse_setting("the object store endpoint's port is not a port") from None
        if parts.scheme == "http" and not (_loopback(host) or self.plaintext_network):
            raise _refuse_setting(
                "plain http reaches the object store only on a loopback host, or on an isolated "
                "network acknowledged with EXULANICA_OBJECT_STORE_PLAINTEXT=private-network"
            )
        if not _BUCKET.match(self.bucket) or ".." in self.bucket:
            raise _refuse_setting("the object store bucket is not a valid S3 bucket name")
        if not _REGION.match(self.region):
            raise _refuse_setting("the object store region is missing or malformed")
        if self.prefix and (not _PREFIX.match(self.prefix) or len(self.prefix) > 200):
            raise _refuse_setting(
                "the object store prefix is lower-case segments of letters, digits, '.', '_' and "
                "'-' separated by '/', with no leading or trailing '/'"
            )
        if self.addressing not in ("path", "virtual"):
            raise _refuse_setting("object store addressing is 'path' or 'virtual'")
        if self.addressing == "virtual" and (_is_address(host) or "." in self.bucket):
            raise _refuse_setting(
                "virtual-hosted addressing needs a DNS endpoint and a bucket name without dots"
            )
        if self.ca_file is not None and not Path(self.ca_file).is_file():
            raise _refuse_setting("the object store CA file does not exist")
        object.__setattr__(self, "endpoint", f"{parts.scheme}://{parts.netloc}")

    @property
    def transport(self) -> str:
        """``https``, ``http_loopback`` or ``http_private_network``: a fact, not a value."""
        parts = urllib.parse.urlsplit(self.endpoint)
        if parts.scheme == "https":
            return "https"
        return "http_loopback" if _loopback(parts.hostname or "") else "http_private_network"

    def namespace(self, name: str) -> str:
        return f"{self.prefix}/{name}" if self.prefix else name

    @property
    def identity(self) -> tuple[str, str, str]:
        """The origin with its host lower-cased and a default port dropped, the bucket and the
        prefix: what decides whether two locations are the same store. The addressing style,
        CA file and plaintext acknowledgement do not."""
        parts = urllib.parse.urlsplit(self.endpoint)
        host = (parts.hostname or "").lower()
        if ":" in host:
            host = f"[{host}]"
        default = {"https": 443, "http": 80}[parts.scheme]
        port = "" if parts.port in (None, default) else f":{parts.port}"
        return (f"{parts.scheme}://{host}{port}", self.bucket, self.prefix)


def _is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class ObjectStoreCredentials:
    """An access key id and its secret. Neither is ever printed, pickled into a log or compared
    in an error message."""

    __slots__ = ("_secret", "access_key_id")

    def __init__(self, access_key_id: str, secret_access_key: str) -> None:
        for value in (access_key_id, secret_access_key):
            if not isinstance(value, str) or not value or any(c.isspace() for c in value):
                raise _refuse_setting("an object store credential is empty or contains whitespace")
        self.access_key_id = access_key_id
        self._secret = secret_access_key

    def __repr__(self) -> str:
        return "ObjectStoreCredentials(<redacted>)"

    def __reduce__(self) -> Any:
        raise TypeError("object store credentials are not serialisable")

    def signer(self, region: str) -> RequestSigner:
        return RequestSigner(self.access_key_id, self._secret, region=region)


@dataclass(frozen=True, slots=True)
class _Head:
    size: int
    etag: str | None


@dataclass(slots=True)
class _Reply:
    status: int
    code: str | None
    headers: httpx.Headers
    content: bytes
    response: httpx.Response | None = None


@dataclass(frozen=True, slots=True)
class _Listing:
    keys: tuple[tuple[str, int], ...]
    prefixes: tuple[str, ...]
    next_token: str | None


@dataclass(frozen=True, slots=True)
class _Upload:
    key: str
    upload_id: str
    initiated: datetime


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    for child in element:
        if _local(child.tag) == name:
            return child
    return None


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if _local(child.tag) == name]


def _text(element: ET.Element, name: str) -> str | None:
    child = _child(element, name)
    return None if child is None else (child.text or "")


def _malformed(operation: str, why: str) -> ObjectStoreRefused:
    return ObjectStoreRefused("object_store_response_malformed", f"{operation}: {why}")


def _parseable(content: bytes) -> bytes | None:
    """The response as UTF-8 XML the parser may read, or None.

    Leading whitespace is dropped, because an endpoint may send it to keep a long request alive
    before the document (S3 does so before a CompleteMultipartUpload error). A document type
    declaration, and any byte that is not plain UTF-8 XML (a NUL is how a UTF-16 document would
    slip past a byte search), is refused outright rather than trusted to the parser.
    """
    stripped = content.lstrip()
    if not stripped.startswith(b"<") or b"\x00" in stripped:
        return None
    if b"<!DOCTYPE" in stripped or b"<!ENTITY" in stripped:
        return None
    return stripped


def _document(content: bytes, root: str, operation: str) -> ET.Element:
    """Parse a response the endpoint sent, refusing anything an S3 answer never needs."""
    if len(content) > _MAX_DOCUMENT_BYTES:
        raise _malformed(operation, "the response is larger than any answer this store expects")
    document = _parseable(content)
    if document is None:
        raise _malformed(operation, "the response is not plain XML without a document type")
    try:
        element = ET.fromstring(document)
    except ET.ParseError:
        raise _malformed(operation, "the response is not XML") from None
    if _local(element.tag) != root:
        raise _malformed(operation, f"expected {root}, got {_local(element.tag)}")
    return element


def _error_code(content: bytes) -> str | None:
    document = _parseable(content)
    if document is None:
        return None
    try:
        element = ET.fromstring(document)
    except ET.ParseError:
        return None
    if _local(element.tag) != "Error":
        return None
    return _text(element, "Code")


def _status_name(status: int) -> str:
    return {
        301: "PermanentRedirect",
        307: "TemporaryRedirect",
        403: "Forbidden",
        404: "NotFound",
        412: "PreconditionFailed",
        416: "InvalidRange",
        501: "NotImplemented",
    }.get(status, f"HTTP{status}")


def _read_bounded(response: httpx.Response, limit: int) -> bytes:
    received = bytearray()
    for chunk in response.iter_raw(_CHUNK):
        received += chunk
        if len(received) > limit:
            raise _malformed(response.request.method, "the response body exceeds its bound")
    return bytes(received)


#: Objects holding a lock another thread might hold at the moment of a fork; a forked child
#: replaces each, so it never waits on a lock whose holder did not come with it.
_FORK_SENSITIVE: weakref.WeakSet[Any] = weakref.WeakSet()


def _reset_in_child() -> None:
    for item in list(_FORK_SENSITIVE):
        item._reset_after_fork()


os.register_at_fork(after_in_child=_reset_in_child)


class ObjectRequests:
    """The signed S3 requests a runtime identity may send: read, write, list, and nothing that
    deletes an object or a version.

    One pooled ``httpx.Client`` per process, rebuilt after a fork. It follows no redirect, reads
    no proxy or credential from the environment, and asks for bytes without content encoding,
    so what is hashed is what was stored.
    """

    def __init__(
        self,
        location: ObjectStoreLocation,
        credentials: ObjectStoreCredentials,
        *,
        transport: httpx.BaseTransport | None = None,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        self.location = location
        self._signer = credentials.signer(location.region)
        self._transport = transport
        self._now = now or (lambda: datetime.now(UTC))
        self._sleep = sleep or time.sleep
        self._jitter = jitter or random.random
        self._client: httpx.Client | None = None
        self._client_pid: int | None = None
        self._client_lock = threading.Lock()
        _FORK_SENSITIVE.add(self)
        parts = urllib.parse.urlsplit(location.endpoint)
        self._scheme = parts.scheme
        if location.addressing == "path":
            self._host = parts.netloc
        else:
            self._host = f"{location.bucket}.{parts.netloc}"

    def __repr__(self) -> str:
        return f"{type(self).__name__}(transport={self.location.transport!r})"

    def _reset_after_fork(self) -> None:
        self._client_lock = threading.Lock()
        self._signer.reset_after_fork()

    # -- the client ---------------------------------------------------------------------

    def _http(self) -> httpx.Client:
        pid = os.getpid()
        with self._client_lock:
            if self._client is None or self._client_pid != pid:
                transport = self._transport
                if transport is None:
                    transport = httpx.HTTPTransport(
                        verify=_trust(self.location.ca_file),
                        # Not SSL_CERT_FILE or SSL_CERT_DIR either: trust is a setting, or certifi.
                        trust_env=False,
                        retries=0,
                        limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
                    )
                self._client = httpx.Client(
                    transport=transport,
                    timeout=httpx.Timeout(_IO_TIMEOUT_SECONDS, connect=_CONNECT_TIMEOUT_SECONDS),
                    follow_redirects=False,
                    trust_env=False,
                    headers={"accept-encoding": "identity", "user-agent": "exulanica-store"},
                )
                self._client_pid = pid
            return self._client

    def close(self) -> None:
        with self._client_lock:
            if self._client is not None and self._client_pid == os.getpid():
                self._client.close()
            self._client = None

    # -- one exchange -------------------------------------------------------------------

    def _subject(self, key: str | None) -> str:
        """How an error names the object: the key without the installation's prefix, which is
        configuration rather than anything about the request."""
        if key is None:
            return "bucket"
        prefix = f"{self.location.prefix}/" if self.location.prefix else ""
        return key.removeprefix(prefix)

    def _path(self, key: str | None) -> str:
        if self.location.addressing == "path":
            return f"/{self.location.bucket}" + (f"/{key}" if key is not None else "")
        return f"/{key}" if key is not None else "/"

    def _request(
        self,
        method: str,
        key: str | None,
        query: Sequence[tuple[str, str]],
        headers: Sequence[tuple[str, str]],
        content: bytes | Iterator[bytes] | None,
        length: int,
        payload_sha256: str,
        *,
        signed: bool = True,
    ) -> httpx.Request:
        canonical_uri = s3_canonical_uri(self._path(key))
        query_string = canonical_query(query)
        url = f"{self._scheme}://{self._host}{canonical_uri}" + (
            f"?{query_string}" if query_string else ""
        )
        sent: dict[str, str] = {"host": self._host}
        if signed:
            when = self._now()
            amz_date = when.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
            to_sign = [
                ("host", self._host),
                ("x-amz-date", amz_date),
                ("x-amz-content-sha256", payload_sha256),
                *headers,
            ]
            signature = self._signer.sign(
                method, canonical_uri, query, to_sign, payload_sha256, when
            )
            sent.update(to_sign)
            sent["authorization"] = signature.authorization
        if content is not None:
            sent["content-length"] = str(length)
        return self._http().build_request(method, url, headers=sent, content=content)

    def _pause(self, attempt: int) -> None:
        delay = min(_BACKOFF_CAP_SECONDS, _BACKOFF_SECONDS * 2 ** (attempt - 1))
        self._sleep(delay * (0.5 + self._jitter() / 2))

    def _exchange(
        self,
        operation: str,
        method: str,
        key: str | None,
        *,
        query: Sequence[tuple[str, str]] = (),
        headers: Sequence[tuple[str, str]] = (),
        body: bytes | Callable[[], Iterator[bytes]] | None = None,
        length: int = 0,
        payload_sha256: str = EMPTY_PAYLOAD_SHA256,
        tolerate: Iterable[int] = (),
        stream: bool = False,
        error_in_body: bool = False,
    ) -> _Reply:
        """Send one logical request, retrying transient failures within ``ATTEMPTS``.

        ``tolerate`` names statuses the caller interprets itself (404 for a missing key, for
        instance); every other failure raises a coded :class:`ObjectStoreRefused` or
        :class:`ObjectStoreUnavailable`. ``body`` is bytes or a factory of chunk iterators, called
        again for each attempt so a retry resends the same bytes.
        """
        tolerated = frozenset(tolerate)
        subject = self._subject(key)
        for attempt in range(1, ATTEMPTS + 1):
            content = body() if callable(body) else body
            request = self._request(method, key, query, headers, content, length, payload_sha256)
            try:
                response = self._http().send(request, stream=True)
            except httpx.TransportError as error:
                if attempt == ATTEMPTS:
                    raise ObjectStoreUnavailable(
                        "object_store_unreachable",
                        f"{operation} {subject}: {type(error).__name__} after {ATTEMPTS} attempts",
                    ) from None
                self._pause(attempt)
                continue
            status = response.status_code
            if 200 <= status < 300 and stream:
                return _Reply(status, None, response.headers, b"", response)
            try:
                limit = _MAX_DOCUMENT_BYTES if 200 <= status < 300 else _MAX_ERROR_BYTES
                content_bytes = _read_bounded(response, limit)
            except httpx.TransportError:
                if attempt == ATTEMPTS:
                    raise ObjectStoreUnavailable(
                        "object_store_unreachable",
                        f"{operation} {subject}: the response broke off after {ATTEMPTS} attempts",
                    ) from None
                self._pause(attempt)
                continue
            finally:
                response.close()
            code = _error_code(content_bytes)
            if 200 <= status < 300 and not (error_in_body and code is not None):
                return _Reply(status, None, response.headers, content_bytes)
            code = code or _status_name(status)
            if status in tolerated:
                return _Reply(status, code, response.headers, content_bytes)
            retryable = status in _RETRIED_STATUS or code in _RETRIED_CODES
            if retryable and attempt < ATTEMPTS:
                self._pause(attempt)
                continue
            raise _refusal(operation, subject, status, code, retried=retryable)
        raise AssertionError("unreachable")  # pragma: no cover

    # -- objects ------------------------------------------------------------------------

    def head(self, key: str) -> _Head | None:
        reply = self._exchange("HEAD", "HEAD", key, tolerate=(404,))
        if reply.status == 404:
            return None
        try:
            size = int(reply.headers["content-length"])
        except (KeyError, ValueError):
            raise _malformed("HEAD", f"{key} was answered without a length") from None
        return _Head(size=size, etag=reply.headers.get("etag"))

    def get(
        self, key: str, *, start: int = 0, if_match: str | None = None
    ) -> httpx.Response | None:
        """A streaming GET the caller closes, or None when the key is absent."""
        headers: list[tuple[str, str]] = []
        if start:
            headers.append(("range", f"bytes={start}-"))
        if if_match is not None:
            headers.append(("if-match", if_match))
        reply = self._exchange("GET", "GET", key, headers=headers, tolerate=(404, 412), stream=True)
        if reply.status == 404:
            return None
        if reply.status == 412:
            raise IntegrityError(f"{self._subject(key)} changed while it was being read")
        assert reply.response is not None
        return reply.response

    def put(
        self,
        key: str,
        body: bytes | Callable[[], Iterator[bytes]],
        length: int,
        md5_base64: str,
        sha256_hex: str,
    ) -> None:
        self._exchange(
            "PUT",
            "PUT",
            key,
            headers=[("content-md5", md5_base64)],
            body=body,
            length=length,
            payload_sha256=sha256_hex,
        )

    def list_page(
        self,
        prefix: str,
        *,
        delimiter: str | None = None,
        token: str | None = None,
        limit: int = _LIST_PAGE,
    ) -> _Listing:
        query = [("list-type", "2"), ("prefix", prefix), ("max-keys", str(limit))]
        if delimiter is not None:
            query.append(("delimiter", delimiter))
        if token is not None:
            query.append(("continuation-token", token))
        reply = self._exchange("LIST", "GET", None, query=query)
        root = _document(reply.content, "ListBucketResult", "LIST")
        keys = []
        for entry in _children(root, "Contents"):
            key, size = _text(entry, "Key"), _text(entry, "Size")
            if key is None or size is None or not size.isdigit():
                raise _malformed("LIST", "an entry has no key or size")
            keys.append((key, int(size)))
        prefixes = tuple(
            text for entry in _children(root, "CommonPrefixes") if (text := _text(entry, "Prefix"))
        )
        next_token = None
        if _text(root, "IsTruncated") == "true":
            next_token = _text(root, "NextContinuationToken")
            if not next_token:
                raise _malformed("LIST", "a truncated listing carried no continuation token")
        return _Listing(tuple(keys), prefixes, next_token)

    def _pages(self, prefix: str, delimiter: str | None) -> Iterator[_Listing]:
        token: str | None = None
        while True:
            page = self.list_page(prefix, delimiter=delimiter, token=token)
            yield page
            if page.next_token is None:
                return
            if page.next_token == token:
                raise _malformed("LIST", "the listing repeated its continuation token")
            token = page.next_token

    def iter_keys(self, prefix: str) -> Iterator[tuple[str, int]]:
        """Every key under ``prefix`` with its size, one page of 1,000 in memory at a time."""
        for page in self._pages(prefix, None):
            yield from page.keys

    def iter_prefixes(self, prefix: str) -> Iterator[str]:
        """The next path level under ``prefix``, as ``CommonPrefixes`` with a ``/`` delimiter."""
        for page in self._pages(prefix, "/"):
            yield from page.prefixes

    # -- multipart ----------------------------------------------------------------------

    def create_upload(self, key: str) -> str:
        reply = self._exchange("CREATE_UPLOAD", "POST", key, query=[("uploads", "")], body=b"")
        upload_id = _text(
            _document(reply.content, "InitiateMultipartUploadResult", "CREATE_UPLOAD"), "UploadId"
        )
        if not upload_id:
            raise _malformed("CREATE_UPLOAD", f"{key} was given no upload id")
        return upload_id

    def upload_part(
        self,
        key: str,
        upload_id: str,
        number: int,
        body: Callable[[], Iterator[bytes]],
        length: int,
        md5_base64: str,
        sha256_hex: str,
    ) -> str:
        reply = self._exchange(
            "UPLOAD_PART",
            "PUT",
            key,
            query=[("partNumber", str(number)), ("uploadId", upload_id)],
            headers=[("content-md5", md5_base64)],
            body=body,
            length=length,
            payload_sha256=sha256_hex,
        )
        etag = reply.headers.get("etag")
        if not etag:
            raise _malformed(
                "UPLOAD_PART", f"part {number} of {key} was acknowledged without an ETag"
            )
        return etag

    def complete_upload(self, key: str, upload_id: str, parts: Sequence[tuple[int, str]]) -> bool:
        """Complete an upload. False when the endpoint no longer knows it, which after a lost
        response means an earlier attempt completed it; the caller checks the key."""
        document = (
            "<CompleteMultipartUpload>"
            + "".join(
                f"<Part><PartNumber>{number}</PartNumber><ETag>{escape(etag)}</ETag></Part>"
                for number, etag in parts
            )
            + "</CompleteMultipartUpload>"
        )
        payload = document.encode("utf-8")
        reply = self._exchange(
            "COMPLETE_UPLOAD",
            "POST",
            key,
            query=[("uploadId", upload_id)],
            body=payload,
            length=len(payload),
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            tolerate=(404,),
            error_in_body=True,
        )
        return reply.status != 404

    def abort_upload(self, key: str, upload_id: str) -> None:
        """Abandon an unfinished upload and its parts; it holds no object, so this is no erasure."""
        self._exchange(
            "ABORT_UPLOAD", "DELETE", key, query=[("uploadId", upload_id)], tolerate=(404,)
        )

    def iter_uploads(self, prefix: str) -> Iterator[_Upload]:
        key_marker: str | None = None
        upload_marker: str | None = None
        while True:
            query = [("uploads", ""), ("prefix", prefix), ("max-uploads", str(_LIST_PAGE))]
            if key_marker is not None:
                query.append(("key-marker", key_marker))
            if upload_marker is not None:
                query.append(("upload-id-marker", upload_marker))
            reply = self._exchange("LIST_UPLOADS", "GET", None, query=query)
            root = _document(reply.content, "ListMultipartUploadsResult", "LIST_UPLOADS")
            for entry in _children(root, "Upload"):
                key, upload_id, initiated = (
                    _text(entry, "Key"),
                    _text(entry, "UploadId"),
                    _text(entry, "Initiated"),
                )
                if not key or not upload_id or not initiated:
                    raise _malformed("LIST_UPLOADS", "an upload has no key, id or start time")
                try:
                    started = datetime.fromisoformat(initiated)
                except ValueError:
                    raise _malformed(
                        "LIST_UPLOADS", "an upload's start time is not ISO 8601"
                    ) from None
                if started.tzinfo is None:
                    raise _malformed("LIST_UPLOADS", "an upload's start time names no time zone")
                yield _Upload(key, upload_id, started)
            if _text(root, "IsTruncated") != "true":
                return
            next_key, next_upload = _text(root, "NextKeyMarker"), _text(root, "NextUploadIdMarker")
            if (next_key, next_upload) == (key_marker, upload_marker) or not next_key:
                raise _malformed("LIST_UPLOADS", "a truncated listing did not advance")
            key_marker, upload_marker = next_key, next_upload

    # -- the bucket ---------------------------------------------------------------------

    def bucket_document(self, subresource: str) -> tuple[str, bytes]:
        """``present`` with the document, ``absent``, ``not_exposed`` or ``denied``."""
        operation = f"GET_BUCKET_{subresource.upper().replace('-', '_')}"
        reply = self._exchange(
            operation, "GET", None, query=[(subresource, "")], tolerate=(400, 403, 404, 405, 501)
        )
        if 200 <= reply.status < 300:
            return "present", reply.content
        if reply.code == "NoSuchBucket":
            raise _refusal(operation, "bucket", reply.status, reply.code, retried=False)
        if reply.status == 404:
            return "absent", b""
        if reply.status == 403 and reply.code in ("AccessDenied", "Forbidden"):
            return "denied", b""
        if reply.status in (405, 501) or reply.code in ("NotImplemented", "MethodNotAllowed"):
            return "not_exposed", b""
        raise _refusal(operation, "bucket", reply.status, reply.code or "", retried=False)

    def anonymous_listing_refused(self, prefix: str) -> bool:
        """Whether an unsigned listing of the prefix is refused, as it must be."""
        query = [("list-type", "2"), ("max-keys", "1"), ("prefix", prefix)]
        for attempt in range(1, ATTEMPTS + 1):
            request = self._request(
                "GET", None, query, (), None, 0, EMPTY_PAYLOAD_SHA256, signed=False
            )
            try:
                response = self._http().send(request)
            except httpx.TransportError as error:
                if attempt == ATTEMPTS:
                    raise ObjectStoreUnavailable(
                        "object_store_unreachable",
                        f"ANONYMOUS_LIST bucket: {type(error).__name__} after {ATTEMPTS} attempts",
                    ) from None
                self._pause(attempt)
                continue
            if response.status_code in _RETRIED_STATUS:
                if attempt < ATTEMPTS:
                    self._pause(attempt)
                    continue
                raise ObjectStoreUnavailable(
                    "object_store_unreachable",
                    f"ANONYMOUS_LIST bucket: HTTP {response.status_code} after {ATTEMPTS} attempts",
                )
            return not 200 <= response.status_code < 300
        raise AssertionError("unreachable")  # pragma: no cover

    def anonymous_read_refused(self, key: str) -> bool:
        """Whether an unsigned HEAD of a stored object is refused, as it must be."""
        for attempt in range(1, ATTEMPTS + 1):
            request = self._request(
                "HEAD", key, (), (), None, 0, EMPTY_PAYLOAD_SHA256, signed=False
            )
            try:
                response = self._http().send(request)
            except httpx.TransportError as error:
                if attempt == ATTEMPTS:
                    raise ObjectStoreUnavailable(
                        "object_store_unreachable",
                        f"ANONYMOUS_HEAD {self._subject(key)}: {type(error).__name__} after "
                        f"{ATTEMPTS} attempts",
                    ) from None
                self._pause(attempt)
                continue
            if response.status_code in _RETRIED_STATUS:
                if attempt < ATTEMPTS:
                    self._pause(attempt)
                    continue
                raise ObjectStoreUnavailable(
                    "object_store_unreachable",
                    f"ANONYMOUS_HEAD {self._subject(key)}: HTTP {response.status_code} after "
                    f"{ATTEMPTS} attempts",
                )
            return not 200 <= response.status_code < 300
        raise AssertionError("unreachable")  # pragma: no cover


class ObjectPurgeRequests(ObjectRequests):
    """The purge identity's requests: everything the runtime may send, plus version listing and
    deletion. Built only from the separate purge credentials."""

    def versions_of(self, key: str) -> list[tuple[str | None, bool]] | None:
        """Every version and delete marker of exactly ``key`` as ``(version id, is marker)``, or
        None when the endpoint exposes no version listing."""
        found: list[tuple[str | None, bool]] = []
        key_marker: str | None = None
        version_marker: str | None = None
        while True:
            query = [("versions", ""), ("prefix", key), ("max-keys", str(_LIST_PAGE))]
            if key_marker is not None:
                query.append(("key-marker", key_marker))
            if version_marker is not None:
                query.append(("version-id-marker", version_marker))
            reply = self._exchange("LIST_VERSIONS", "GET", None, query=query, tolerate=(405, 501))
            if reply.status in (405, 501):
                return None
            root = _document(reply.content, "ListVersionsResult", "LIST_VERSIONS")
            for entry in root:
                kind = _local(entry.tag)
                if kind in ("Version", "DeleteMarker") and _text(entry, "Key") == key:
                    found.append((_text(entry, "VersionId"), kind == "DeleteMarker"))
            if _text(root, "IsTruncated") != "true":
                return found
            next_key = _text(root, "NextKeyMarker")
            next_version = _text(root, "NextVersionIdMarker")
            if (next_key, next_version) == (key_marker, version_marker) or not next_key:
                raise _malformed("LIST_VERSIONS", "a truncated listing did not advance")
            key_marker, version_marker = next_key, next_version

    def delete_object_version(self, key: str, version_id: str | None) -> None:
        query = [("versionId", version_id)] if version_id is not None else []
        self._exchange("DELETE_OBJECT", "DELETE", key, query=query, tolerate=(404,))


def _refusal(
    operation: str, subject: str, status: int, code: str, *, retried: bool
) -> ObjectStoreRefused | ObjectStoreUnavailable | IntegrityError:
    text = f"{operation} {subject}: HTTP {status} {code}"
    if retried and code in ("BadDigest", "XAmzContentSHA256Mismatch"):
        return IntegrityError(f"{text}: the endpoint kept refusing the body's digest")
    if retried:
        return ObjectStoreUnavailable(
            "object_store_unreachable", f"{text} after {ATTEMPTS} attempts"
        )
    if status == 501 or code == "NotImplemented":
        return ObjectStoreRefused("object_store_not_implemented", text)
    if status >= 500:
        return ObjectStoreUnavailable("object_store_unreachable", text)
    if code == "RequestTimeTooSkewed":
        return ObjectStoreRefused("object_store_clock_skewed", text)
    if code in _DENIED_CODES or status == 403:
        return ObjectStoreRefused("object_store_access_denied", text)
    if code == "NoSuchBucket":
        return ObjectStoreRefused("object_store_bucket_missing", text)
    if 300 <= status < 400:
        return ObjectStoreRefused(
            "object_store_redirected",
            f"{text}: the endpoint, region or addressing style does not match the bucket",
        )
    return ObjectStoreRefused("object_store_request_refused", text)


# -- the bucket check ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Finding:
    """One reason the bucket cannot be trusted, and whether it also stops erasure."""

    code: str
    message: str
    blocks_erasure: bool


@dataclass(frozen=True, slots=True)
class BucketCheck:
    """What the bucket check found, as codes a readiness report can carry."""

    versioning: str
    object_lock: str
    replication: str
    lifecycle: str
    anonymous_listing: str
    anonymous_read: str
    findings: tuple[_Finding, ...] = ()

    def document(self) -> dict[str, Any]:
        return {
            "versioning": self.versioning,
            "object_lock": self.object_lock,
            "replication": self.replication,
            "lifecycle": self.lifecycle,
            "anonymous_listing": self.anonymous_listing,
            "anonymous_read": self.anonymous_read,
            "codes": [finding.code for finding in self.findings],
        }


def _moving_rules(document: bytes, prefix: str) -> list[str]:
    """Enabled lifecycle rules that expire or transition current objects this store may hold."""
    root = _document(document, "LifecycleConfiguration", "GET_BUCKET_LIFECYCLE")
    ours = f"{prefix}/" if prefix else ""
    moving = []
    for rule in _children(root, "Rule"):
        if _text(rule, "Status") != "Enabled":
            continue
        expiration = _child(rule, "Expiration")
        expires = expiration is not None and (
            _child(expiration, "Days") is not None or _child(expiration, "Date") is not None
        )
        if not expires and _child(rule, "Transition") is None:
            continue
        scope = _child(rule, "Filter")
        if scope is not None and (conjunction := _child(scope, "And")) is not None:
            scope = conjunction
        if scope is not None and _child(scope, "Tag") is not None:
            continue  # no object this store writes carries a tag
        rule_prefix = (_text(scope, "Prefix") if scope is not None else _text(rule, "Prefix")) or ""
        if ours.startswith(rule_prefix) or rule_prefix.startswith(ours):
            moving.append(_text(rule, "ID") or "(unnamed)")
    return moving


class BucketGuard:
    """Runs the bucket check before a process's first request, again every few minutes, and
    before every purge.

    Every finding is collected rather than the first one raised, so readiness shows the whole
    picture. A request refuses on any finding. A purge refuses only on a finding that makes
    erasure incomplete or impossible (an enabled object lock, a replication configuration, one
    that cannot be read), because deleting from a bucket that is wrongly public, or that a
    lifecycle rule expires, still removes the bytes. An unreachable endpoint is remembered for a
    few seconds, so callers waiting behind one check do not each wait out their own.
    """

    VERIFIED_SECONDS: Final = 300.0
    REFUSED_SECONDS: Final = 30.0
    UNAVAILABLE_SECONDS: Final = 5.0

    def __init__(
        self,
        requests: ObjectRequests,
        prefix: str,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._requests = requests
        self._prefix = prefix
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._result: BucketCheck | None = None
        self._unavailable: str | None = None
        self._until = 0.0
        _FORK_SENSITIVE.add(self)

    def _reset_after_fork(self) -> None:
        self._lock = threading.Lock()

    def require(self, *, fresh: bool = False, erasing: bool = False) -> BucketCheck:
        with self._lock:
            now = self._monotonic()
            if fresh or now >= self._until:
                try:
                    checked = self._check()
                except ObjectStoreUnavailable as unavailable:
                    self._result, self._unavailable = None, str(unavailable)
                    self._until = now + self.UNAVAILABLE_SECONDS
                    raise
                self._result, self._unavailable = checked, None
                self._until = now + (
                    self.REFUSED_SECONDS if checked.findings else self.VERIFIED_SECONDS
                )
            elif self._unavailable is not None:
                raise ObjectStoreUnavailable("object_store_unreachable", self._unavailable)
            result = self._result
            assert result is not None
        blocking = [f for f in result.findings if f.blocks_erasure or not erasing]
        if blocking:
            raise ObjectStoreRefused(blocking[0].code, blocking[0].message)
        return result

    def describe(self) -> dict[str, Any]:
        with self._lock:
            if self._unavailable is not None:
                return {"state": "unreachable", "code": "object_store_unreachable"}
            if self._result is None:
                return {"state": "unchecked", "code": None}
            findings = self._result.findings
            return {
                "state": "refused" if findings else "verified",
                "code": findings[0].code if findings else None,
                **self._result.document(),
            }

    def _check(self) -> BucketCheck:
        requests = self._requests
        findings: list[_Finding] = []

        def unreadable(what: str, *, blocks_erasure: bool) -> None:
            findings.append(
                _Finding(
                    "object_store_bucket_unverified",
                    f"the bucket's {what} could not be read; the store's identity must be allowed "
                    "to read it",
                    blocks_erasure,
                )
            )

        state, body = requests.bucket_document("object-lock")
        # An identity may be refused this one read (some endpoints reserve it for an
        # administrator) without anything being unsafe: a lock shows up anyway, as a purge that
        # fails because a version remains, never as a purge reported complete. So an unreadable
        # lock is recorded, not refused.
        if state == "present":
            root = _document(body, "ObjectLockConfiguration", "GET_BUCKET_OBJECT_LOCK")
            if _text(root, "ObjectLockEnabled") == "Enabled":
                findings.append(
                    _Finding(
                        "object_store_object_lock_enabled",
                        "the bucket has object lock, so a locked version could not be erased",
                        True,
                    )
                )
        object_lock = {"not_exposed": "not_exposed", "denied": "unverified"}.get(state, "off")
        if object_lock == "off" and findings:
            object_lock = "enabled"

        state, body = requests.bucket_document("versioning")
        versioning = {"not_exposed": "not_exposed", "denied": "unverified"}.get(state, "off")
        if state == "denied":
            unreadable("versioning configuration", blocks_erasure=False)
        if state == "present":
            status = _text(
                _document(body, "VersioningConfiguration", "GET_BUCKET_VERSIONING"), "Status"
            )
            versioning = {"": "off", "Enabled": "enabled", "Suspended": "suspended"}.get(
                status or "", "unknown"
            )

        state, _ = requests.bucket_document("replication")
        replication = {"not_exposed": "not_exposed", "denied": "unverified"}.get(state, "off")
        if state == "denied":
            unreadable("replication configuration", blocks_erasure=True)
        if state == "present":
            replication = "configured"
            findings.append(
                _Finding(
                    "object_store_replication_configured",
                    "the bucket replicates objects, and a replica is a copy no purge here reaches",
                    True,
                )
            )

        state, body = requests.bucket_document("lifecycle")
        lifecycle = {"absent": "off", "not_exposed": "not_exposed", "denied": "unverified"}.get(
            state, "no_matching_rule"
        )
        if state == "denied":
            unreadable("lifecycle configuration", blocks_erasure=False)
        if state == "present" and (rules := _moving_rules(body, self._prefix)):
            lifecycle = "moves_content"
            findings.append(
                _Finding(
                    "object_store_lifecycle_moves_content",
                    f"lifecycle rule(s) {', '.join(rules)} expire or move current objects under "
                    "the store's prefix",
                    False,
                )
            )

        listing_prefix = f"{self._prefix}/" if self._prefix else ""
        anonymous_listing = "refused"
        if not requests.anonymous_listing_refused(listing_prefix):
            anonymous_listing = "allowed"
            findings.append(
                _Finding(
                    "object_store_publicly_listable",
                    "anyone can list the bucket, so the digests citations carry would open its "
                    "bytes",
                    False,
                )
            )
        # One stored object, read without credentials, must be refused too: a bucket policy can
        # open reads without opening listings.
        anonymous_read = "unchecked"
        sample = requests.list_page(listing_prefix, limit=1).keys
        if sample:
            anonymous_read = "refused"
            if not requests.anonymous_read_refused(sample[0][0]):
                anonymous_read = "allowed"
                findings.append(
                    _Finding(
                        "object_store_publicly_readable",
                        "anyone can read the bucket's objects, so a digest would open its bytes "
                        "without the application's checks",
                        False,
                    )
                )
        return BucketCheck(
            versioning,
            object_lock,
            replication,
            lifecycle,
            anonymous_listing,
            anonymous_read,
            tuple(findings),
        )


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
        self._guard.require()
        base = f"{self._namespace}/"
        for key, _size in self._requests.iter_keys(f"{base}sha-256/"):
            match = _KEY_SHAPE.match(key[len(base) :])
            if match and match[3][:2] == match[1] and match[3][2:4] == match[2]:
                yield BlobId.from_hex(match[3])


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
    ``prefix`` are touched; anything else in the bucket is somebody else's. Returns how many were
    abandoned.
    """
    shape = re.compile(
        re.escape(prefix)
        + r"(?:blobs|tiles|materials/[0-9a-f]{32})/sha-256/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}"
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
