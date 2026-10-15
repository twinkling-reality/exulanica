"""The signed S3 requests one identity may send, and where they go.

Where the store is (:class:`ObjectStoreLocation`) and who asks (:class:`ObjectStoreCredentials`),
the request set a runtime identity holds (:class:`ObjectRequests`: read, write, list, and nothing
that deletes an object or a version) and the one built from purge credentials
(:class:`ObjectPurgeRequests`), with their retries, timeouts, bounded reads and the refusals they
answer. A forked child replaces every client and lock it inherits. The store built on these
requests is :mod:`exulanica.store.object`'s.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import random
import re
import ssl
import threading
import time
import urllib.parse
import weakref
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from xml.sax.saxutils import escape

import httpx

from exulanica.errors import (
    IntegrityError,
    ObjectStoreConfigurationError,
    ObjectStoreRefused,
    ObjectStoreUnavailable,
)
from exulanica.store.sigv4 import (
    EMPTY_PAYLOAD_SHA256,
    RequestSigner,
    canonical_query,
    s3_canonical_uri,
)

#: Every request is tried at most this many times; only transient failures are retried.
ATTEMPTS: Final = 4

_BACKOFF_SECONDS: Final = 0.25

_BACKOFF_CAP_SECONDS: Final = 5.0

_CONNECT_TIMEOUT_SECONDS: Final = 10.0

#: Per read or write on the socket, not per request: a slow transfer that keeps moving continues.
_IO_TIMEOUT_SECONDS: Final = 60.0

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

_BUCKET: Final = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")

_PREFIX: Final = re.compile(r"^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*$")

_REGION: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")


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
        timeout: float | None = None,
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
        if timeout is None:
            return self._http().build_request(method, url, headers=sent, content=content)
        return self._http().build_request(
            method, url, headers=sent, content=content, timeout=httpx.Timeout(timeout)
        )

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
        attempts: int = ATTEMPTS,
        timeout: float | None = None,
    ) -> _Reply:
        """Send one logical request, retrying transient failures within ``attempts`` (``ATTEMPTS``
        unless the caller bounds it, with ``timeout`` seconds for each connect, read and write in
        place of the client's).

        ``tolerate`` names statuses the caller interprets itself (404 for a missing key, for
        instance); every other failure raises a coded :class:`ObjectStoreRefused` or
        :class:`ObjectStoreUnavailable`. ``body`` is bytes or a factory of chunk iterators, called
        again for each attempt so a retry resends the same bytes.
        """
        tolerated = frozenset(tolerate)
        subject = self._subject(key)
        for attempt in range(1, attempts + 1):
            content = body() if callable(body) else body
            request = self._request(
                method, key, query, headers, content, length, payload_sha256, timeout=timeout
            )
            try:
                response = self._http().send(request, stream=True)
            except httpx.TransportError as error:
                if attempt == attempts:
                    raise ObjectStoreUnavailable(
                        "object_store_unreachable",
                        f"{operation} {subject}: {type(error).__name__} after {attempts} attempts",
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
                if attempt == attempts:
                    raise ObjectStoreUnavailable(
                        "object_store_unreachable",
                        f"{operation} {subject}: the response broke off after {attempts} attempts",
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
            if retryable and attempt < attempts:
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
        *,
        attempts: int = ATTEMPTS,
        timeout: float | None = None,
    ) -> None:
        """Write ``key``; ``attempts`` and ``timeout`` bound a write a caller must not wait long
        for, as :meth:`_exchange` states."""
        self._exchange(
            "PUT",
            "PUT",
            key,
            headers=[("content-md5", md5_base64)],
            body=body,
            attempts=attempts,
            timeout=timeout,
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
