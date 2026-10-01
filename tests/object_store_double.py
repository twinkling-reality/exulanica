"""An S3-compatible endpoint in memory, for the object store's tests.

It is a test double with teeth rather than a stub. Every signed request is re-signed from the bytes
that arrived, with the identity's secret, and refused when the signature, the payload's SHA-256 or
its Content-MD5 disagree, so a client that signs one URL and sends another fails here as it would
against a real endpoint. Identities carry permissions the way a bucket policy does: the runtime
identity cannot delete an object or a version. Versioning, multipart uploads, paging and the
bucket configuration reads behave as S3 documents them, closely enough to test the client's
handling of each; they are not a claim about any provider, which the provider run in
``scripts/verify_object_store.py`` checks separately.

Use it as an ``httpx.MockTransport`` in-process (``double.transport()``), or over a loopback socket
for tests that need several processes (``serve(double)``).
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import re
import socketserver
import threading
import urllib.parse
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from exulanica.store.sigv4 import RequestSigner

RUNTIME = frozenset({"read", "write", "list", "multipart", "bucket-read"})
PURGE = RUNTIME | {"delete", "list-versions"}
ADMIN = PURGE | {"admin"}

_AUTHORIZATION = re.compile(
    r"^AWS4-HMAC-SHA256 Credential=(?P<key>[^/]+)/(?P<date>\d{8})/(?P<region>[^/]+)"
    r"/s3/aws4_request, "
    r"SignedHeaders=(?P<signed>[a-z0-9;-]+), Signature=(?P<signature>[0-9a-f]{64})$"
)


@dataclass
class Version:
    version_id: str
    data: bytes | None  # None is a delete marker
    etag: str
    modified: datetime


@dataclass
class Upload:
    key: str
    initiated: datetime
    parts: dict[int, tuple[str, bytes]] = field(default_factory=dict)


@dataclass
class Fault:
    """Answer requests that match ``when`` with ``outcome`` (a Response, an exception to raise, or
    a callable taking the request) for the next ``times`` matches."""

    when: Callable[[str, str | None, dict[str, str]], bool]
    outcome: Any
    times: int = 1


class _BrokenStream(httpx.SyncByteStream):
    """A response body that stops with a connection error after ``cut`` bytes."""

    def __init__(self, data: bytes, cut: int) -> None:
        self._data = data
        self._cut = cut

    def __iter__(self) -> Iterator[bytes]:
        yield self._data[: self._cut]
        raise httpx.ReadError("the connection was reset")


def broken_body(response_data: bytes, cut: int, headers: dict[str, str], status: int = 200):
    return httpx.Response(status, headers=headers, stream=_BrokenStream(response_data, cut))


class _DoubleTransport(httpx.BaseTransport):
    """Hands each request to the double as the client streams it, unlike ``httpx.MockTransport``,
    which reads the body first and so hides how the client chunks it."""

    def __init__(self, double: S3Double) -> None:
        self._double = double

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._double.handle(request)


def respond(
    status: int, content: bytes = b"", headers: dict[str, str] | None = None
) -> httpx.Response:
    """A response whose body streams, as one from a socket does."""
    return httpx.Response(
        status,
        headers={**(headers or {}), "content-length": str(len(content))},
        stream=httpx.ByteStream(content),
    )


class S3Double:
    def __init__(
        self,
        *,
        bucket: str = "exulanica-test",
        region: str = "us-east-1",
        identities: dict[str, tuple[str, frozenset[str]]] | None = None,
        page_size: int = 1000,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.bucket = bucket
        self.region = region
        self.identities = identities or {
            "runtime-key": ("runtime-secret", RUNTIME),
            "purge-key": ("purge-secret", PURGE),
            "admin-key": ("admin-secret", ADMIN),
        }
        self.page_size = page_size
        self.clock = clock or (lambda: datetime.now(UTC))
        self.objects: dict[str, list[Version]] = {}
        self.uploads: dict[str, Upload] = {}
        self.versioning = ""  # "", "Enabled" or "Suspended"
        self.object_lock = False
        self.replication = False
        self.lifecycle: bytes | None = None
        self.public_list = False
        self.public_read = False
        self.not_exposed: set[str] = set()
        self.denied: set[str] = set()
        self.faults: list[Fault] = []
        self.log: list[tuple[str, str | None, str | None, dict[str, str]]] = []
        self.largest_body_chunk = 0
        self._lock = threading.RLock()

    # -- helpers for tests --------------------------------------------------------------------

    def transport(self) -> httpx.BaseTransport:
        return _DoubleTransport(self)

    def inject(self, when, outcome, times: int = 1) -> None:
        self.faults.append(Fault(when, outcome, times))

    def current(self, key: str) -> bytes | None:
        versions = self.objects.get(key) or []
        return versions[-1].data if versions else None

    def overwrite(self, key: str, data: bytes) -> None:
        """Replace an object's bytes behind the client's back, as a fault or an attacker would."""
        self._put_version(key, data)

    def stored_keys(self) -> list[str]:
        return sorted(key for key in self.objects if self.current(key) is not None)

    def requests(self, method: str | None = None) -> list[tuple[str, str | None, str | None, dict]]:
        return [entry for entry in self.log if method is None or entry[0] == method]

    # -- the endpoint ---------------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = bytearray()
        for chunk in request.stream:  # type: ignore[union-attr]
            self.largest_body_chunk = max(self.largest_body_chunk, len(chunk))
            body += chunk
        raw_path = request.url.raw_path.split(b"?", 1)[0].decode("ascii")
        query = [
            (urllib.parse.unquote(name), urllib.parse.unquote(value))
            for name, _, value in (
                part.partition("=") for part in request.url.query.decode("ascii").split("&") if part
            )
        ]
        params = dict(query)
        bucket, _, key_part = urllib.parse.unquote(raw_path).lstrip("/").partition("/")
        key = key_part or None
        with self._lock:
            identity = self._authenticate(request, raw_path, query, bytes(body))
            if isinstance(identity, httpx.Response):
                self.log.append((request.method, key, None, params))
                return identity
            self.log.append((request.method, key, identity, params))
            for fault in list(self.faults):
                if fault.when(request.method, key, params):
                    fault.times -= 1
                    if fault.times <= 0:
                        self.faults.remove(fault)
                    outcome = fault.outcome
                    if isinstance(outcome, BaseException):
                        raise outcome
                    if callable(outcome):
                        outcome = outcome(request)
                    if isinstance(outcome, httpx.Response) and not isinstance(
                        outcome.stream, _BrokenStream
                    ):
                        # A fresh copy each time: a response body streams only once.
                        headers = {
                            k: v for k, v in outcome.headers.items() if k != "content-length"
                        }
                        outcome = respond(outcome.status_code, outcome.read(), headers)
                    if outcome is not None:
                        return outcome
            if bucket != self.bucket:
                return _error(404, "NoSuchBucket")
            return self._route(request.method, key, params, bytes(body), request, identity)

    def _authenticate(self, request, raw_path, query, body) -> str | httpx.Response | None:
        header = request.headers.get("authorization")
        if header is None:
            return None
        match = _AUTHORIZATION.match(header)
        if match is None or match["key"] not in self.identities:
            return _error(403, "InvalidAccessKeyId")
        secret, _permissions = self.identities[match["key"]]
        signed_names = match["signed"].split(";")
        headers = [
            (name, request.headers[name]) for name in signed_names if name in request.headers
        ]
        if len(headers) != len(signed_names) or "host" not in signed_names:
            return _error(403, "SignatureDoesNotMatch")
        payload = request.headers.get("x-amz-content-sha256", "")
        if payload != hashlib.sha256(body).hexdigest():
            return _error(400, "XAmzContentSHA256Mismatch")
        md5 = request.headers.get("content-md5")
        if md5 is not None and md5 != base64.b64encode(hashlib.md5(body).digest()).decode():
            return _error(400, "BadDigest")
        stated = datetime.strptime(request.headers["x-amz-date"], "%Y%m%dT%H%M%SZ").replace(
            tzinfo=UTC
        )
        if abs((stated - self.clock()).total_seconds()) > 900:
            return _error(403, "RequestTimeTooSkewed")
        signer = RequestSigner(match["key"], secret, region=match["region"])
        expected = signer.sign(request.method, raw_path, query, headers, payload, stated)
        if expected.authorization != header:
            return _error(403, "SignatureDoesNotMatch")
        return match["key"]

    def _allowed(self, identity: str | None, permission: str) -> bool:
        if identity is None:
            return (permission == "list" and self.public_list) or (
                permission == "read" and self.public_read
            )
        return permission in self.identities[identity][1]

    def _route(self, method, key, params, body, request, identity) -> httpx.Response:
        def need(permission: str) -> httpx.Response | None:
            return None if self._allowed(identity, permission) else _error(403, "AccessDenied")

        if key is None:
            for subresource in ("versioning", "object-lock", "replication", "lifecycle"):
                if subresource in params:
                    return need("bucket-read") or self._bucket_document(subresource)
            if "uploads" in params:
                return need("multipart") or self._list_uploads(params)
            if "versions" in params:
                return need("list-versions") or self._list_versions(params)
            if params.get("list-type") == "2":
                return need("list") or self._list(params)
            return _error(400, "InvalidRequest")
        if method in ("HEAD", "GET"):
            return need("read") or self._read(method, key, request)
        if method == "PUT" and "uploadId" in params:
            return need("multipart") or self._upload_part(key, params, body)
        if method == "PUT":
            return need("write") or self._put(key, body)
        if method == "POST" and "uploads" in params:
            return need("multipart") or self._create_upload(key)
        if method == "POST" and "uploadId" in params:
            return need("multipart") or self._complete(key, params, body)
        if method == "DELETE" and "uploadId" in params:
            return need("multipart") or self._abort(params)
        if method == "DELETE":
            return need("delete") or self._delete(key, params.get("versionId"))
        return _error(405, "MethodNotAllowed")

    # -- objects --------------------------------------------------------------------------------

    def _put_version(self, key: str, data: bytes, etag: str | None = None) -> Version:
        version = Version(
            version_id=uuid.uuid4().hex if self.versioning == "Enabled" else "null",
            data=data,
            etag=etag or f'"{hashlib.md5(data).hexdigest()}"',
            modified=self.clock(),
        )
        versions = self.objects.setdefault(key, [])
        if version.version_id == "null":
            versions[:] = [v for v in versions if v.version_id != "null"]
        versions.append(version)
        return version

    def _put(self, key: str, body: bytes) -> httpx.Response:
        version = self._put_version(key, body)
        return respond(200, headers={"etag": version.etag})

    def _read(self, method: str, key: str, request: httpx.Request) -> httpx.Response:
        versions = self.objects.get(key) or []
        if not versions or versions[-1].data is None:
            return _error(404, "NoSuchKey", head=method == "HEAD")
        latest = versions[-1]
        data = latest.data or b""
        if_match = request.headers.get("if-match")
        if if_match is not None and if_match != latest.etag:
            return _error(412, "PreconditionFailed", head=method == "HEAD")
        headers = {"etag": latest.etag, "content-length": str(len(data))}
        if method == "HEAD":
            return httpx.Response(200, headers=headers, stream=httpx.ByteStream(b""))
        status = 200
        byte_range = request.headers.get("range")
        if byte_range:
            start = int(byte_range.removeprefix("bytes=").rstrip("-"))
            if start >= len(data):
                return _error(416, "InvalidRange")
            headers["content-range"] = f"bytes {start}-{len(data) - 1}/{len(data)}"
            data = data[start:]
            headers["content-length"] = str(len(data))
            status = 206
        return httpx.Response(status, headers=headers, stream=httpx.ByteStream(data))

    def _delete(self, key: str, version_id: str | None) -> httpx.Response:
        versions = self.objects.get(key)
        if version_id is not None:
            if versions is not None:
                versions[:] = [v for v in versions if v.version_id != version_id]
                if not versions:
                    del self.objects[key]
            return respond(204)
        if self.versioning:
            marker = Version(
                version_id=uuid.uuid4().hex if self.versioning == "Enabled" else "null",
                data=None,
                etag="",
                modified=self.clock(),
            )
            chain = self.objects.setdefault(key, [])
            if marker.version_id == "null":
                chain[:] = [v for v in chain if v.version_id != "null"]
            chain.append(marker)
        else:
            self.objects.pop(key, None)
        return respond(204)

    # -- listings -------------------------------------------------------------------------------

    def _list(self, params: dict[str, str]) -> httpx.Response:
        prefix = params.get("prefix", "")
        delimiter = params.get("delimiter")
        limit = min(int(params.get("max-keys", "1000")), self.page_size)
        after = params.get("continuation-token")
        if after is not None:
            after = base64.urlsafe_b64decode(after.encode()).decode()
        entries: list[tuple[str, str]] = []  # (sort key, kind)
        seen_prefixes: set[str] = set()
        for key in sorted(self.objects):
            if not key.startswith(prefix) or self.current(key) is None:
                continue
            if delimiter and delimiter in key[len(prefix) :]:
                common = key[: len(prefix) + key[len(prefix) :].index(delimiter) + 1]
                if common in seen_prefixes:
                    continue
                seen_prefixes.add(common)
                entries.append((common, "prefix"))
            else:
                entries.append((key, "key"))
        entries = [entry for entry in entries if after is None or entry[0] > after]
        page, rest = entries[:limit], entries[limit:]
        parts = ['<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">']
        parts.append(f"<Name>{self.bucket}</Name><Prefix>{_x(prefix)}</Prefix>")
        parts.append(f"<KeyCount>{len(page)}</KeyCount><MaxKeys>{limit}</MaxKeys>")
        for name, kind in page:
            if kind == "key":
                data = self.current(name) or b""
                parts.append(f"<Contents><Key>{_x(name)}</Key><Size>{len(data)}</Size></Contents>")
            else:
                parts.append(f"<CommonPrefixes><Prefix>{_x(name)}</Prefix></CommonPrefixes>")
        if rest:
            token = base64.urlsafe_b64encode(page[-1][0].encode()).decode()
            parts.append(
                f"<IsTruncated>true</IsTruncated><NextContinuationToken>{token}</NextContinuationToken>"
            )
        else:
            parts.append("<IsTruncated>false</IsTruncated>")
        parts.append("</ListBucketResult>")
        return _xml("".join(parts))

    def _list_versions(self, params: dict[str, str]) -> httpx.Response:
        prefix = params.get("prefix", "")
        rows = []
        for key in sorted(self.objects):
            if key.startswith(prefix):
                for version in reversed(self.objects[key]):
                    rows.append((key, version))
        parts = ['<ListVersionsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">']
        for key, version in rows:
            tag = "Version" if version.data is not None else "DeleteMarker"
            parts.append(
                f"<{tag}><Key>{_x(key)}</Key><VersionId>{version.version_id}</VersionId></{tag}>"
            )
        parts.append("<IsTruncated>false</IsTruncated></ListVersionsResult>")
        return _xml("".join(parts))

    def _list_uploads(self, params: dict[str, str]) -> httpx.Response:
        prefix = params.get("prefix", "")
        parts = ['<ListMultipartUploadsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">']
        for upload_id, upload in sorted(
            self.uploads.items(), key=lambda item: (item[1].key, item[0])
        ):
            if upload.key.startswith(prefix):
                initiated = upload.initiated.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                parts.append(
                    f"<Upload><Key>{_x(upload.key)}</Key><UploadId>{upload_id}</UploadId>"
                    f"<Initiated>{initiated}</Initiated></Upload>"
                )
        parts.append("<IsTruncated>false</IsTruncated></ListMultipartUploadsResult>")
        return _xml("".join(parts))

    # -- multipart ------------------------------------------------------------------------------

    def _create_upload(self, key: str) -> httpx.Response:
        upload_id = uuid.uuid4().hex
        self.uploads[upload_id] = Upload(key=key, initiated=self.clock())
        return _xml(
            "<InitiateMultipartUploadResult><Bucket>b</Bucket>"
            f"<Key>{_x(key)}</Key><UploadId>{upload_id}</UploadId></InitiateMultipartUploadResult>"
        )

    def _upload_part(self, key: str, params: dict[str, str], body: bytes) -> httpx.Response:
        upload = self.uploads.get(params["uploadId"])
        if upload is None or upload.key != key:
            return _error(404, "NoSuchUpload")
        etag = f'"{hashlib.md5(body).hexdigest()}"'
        upload.parts[int(params["partNumber"])] = (etag, body)
        return respond(200, headers={"etag": etag})

    def _complete(self, key: str, params: dict[str, str], body: bytes) -> httpx.Response:
        upload = self.uploads.get(params["uploadId"])
        if upload is None or upload.key != key:
            return _error(404, "NoSuchUpload")
        listed = re.findall(rb"<PartNumber>(\d+)</PartNumber><ETag>([^<]+)</ETag>", body)
        chosen = [(int(number), etag.decode().replace("&quot;", '"')) for number, etag in listed]
        if [number for number, _ in chosen] != sorted(upload.parts) or any(
            upload.parts[number][0] != etag for number, etag in chosen
        ):
            return _error(400, "InvalidPart")
        data = b"".join(upload.parts[number][1] for number, _ in chosen)
        digests = b"".join(hashlib.md5(upload.parts[n][1]).digest() for n, _ in chosen)
        etag = f'"{hashlib.md5(digests).hexdigest()}-{len(chosen)}"'
        del self.uploads[params["uploadId"]]
        self._put_version(key, data, etag)
        return _xml(
            f"<CompleteMultipartUploadResult><Key>{_x(key)}</Key></CompleteMultipartUploadResult>"
        )

    def _abort(self, params: dict[str, str]) -> httpx.Response:
        if self.uploads.pop(params["uploadId"], None) is None:
            return _error(404, "NoSuchUpload")
        return respond(204)

    # -- bucket configuration -------------------------------------------------------------------

    def _bucket_document(self, subresource: str) -> httpx.Response:
        if subresource in self.not_exposed:
            return _error(501, "NotImplemented")
        if subresource in self.denied:
            return _error(403, "AccessDenied")
        if subresource == "versioning":
            status = f"<Status>{self.versioning}</Status>" if self.versioning else ""
            return _xml(f"<VersioningConfiguration>{status}</VersioningConfiguration>")
        if subresource == "object-lock":
            if not self.object_lock:
                return _error(404, "ObjectLockConfigurationNotFoundError")
            return _xml(
                "<ObjectLockConfiguration><ObjectLockEnabled>Enabled</ObjectLockEnabled>"
                "</ObjectLockConfiguration>"
            )
        if subresource == "replication":
            if not self.replication:
                return _error(404, "ReplicationConfigurationNotFoundError")
            return _xml("<ReplicationConfiguration><Role>r</Role></ReplicationConfiguration>")
        if self.lifecycle is None:
            return _error(404, "NoSuchLifecycleConfiguration")
        return respond(200, self.lifecycle)


def _x(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml(document: str) -> httpx.Response:
    return respond(200, document.encode(), {"content-type": "application/xml"})


def _error(status: int, code: str, *, head: bool = False) -> httpx.Response:
    if head:
        return httpx.Response(status, stream=httpx.ByteStream(b""))
    return respond(status, f"<Error><Code>{code}</Code><Message>{code}</Message></Error>".encode())


def error(status: int, code: str) -> httpx.Response:
    return _error(status, code)


# -- serving over a loopback socket --------------------------------------------------------------


@contextmanager
def serve(double: S3Double, *, port: int = 0) -> Iterator[str]:
    """Serve the double on 127.0.0.1 for as long as the block runs; yields the endpoint origin."""

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _any(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else b""
            host = self.headers.get("host", "")
            request = httpx.Request(
                self.command,
                f"http://{host}{self.path}",
                headers=[(k.lower(), v) for k, v in self.headers.items()],
                content=body,
            )
            try:
                response = double.handle(request)
            except httpx.TransportError:
                self.close_connection = True
                return
            content = response.read()
            self.send_response(response.status_code)
            for name, value in response.headers.items():
                if name.lower() not in ("content-length", "transfer-encoding", "connection"):
                    self.send_header(name, value)
            if self.command == "HEAD" and "content-length" in response.headers:
                self.send_header("content-length", response.headers["content-length"])
            else:
                self.send_header("content-length", str(len(content)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(content)

        do_GET = do_PUT = do_POST = do_DELETE = do_HEAD = _any

        def log_message(self, *args: Any) -> None:
            pass

    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = Server(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
