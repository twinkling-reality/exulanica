"""Run the S3-compatible content store's contract against a real endpoint and record what held.

    uv run python scripts/verify_object_store.py \\
        --endpoint http://127.0.0.1:19446 --region us-east-1 \\
        --credentials <directory> --provider "<name and version>" \\
        --provider-sha256 <digest of the binary or image> \\
        --scratch <directory> --report <file.json>

``--credentials`` names a directory holding ``runtime.json``, ``purge.json`` and ``admin.json``,
each ``{"access_key_id": ..., "secret_access_key": ...}``: three identities the endpoint already
knows. Credentials never travel as arguments, and none reaches the report or the output.

The endpoint must be an isolated one made for this run. The admin identity creates the buckets the
checks need (``exulanica-verify``, and ``-versioned``, ``-locked``, ``-lifecycle`` beside it), sets
their configuration, and writes under a fresh run prefix; nothing else is touched. Bounded: one
object of ``--large-mib`` MiB (default 70, so it crosses the multipart threshold), 1,050 small
objects for paging, and a few dozen more; about 160 MB in all on the default settings.

Each check records ``passed``, ``failed`` or ``not_supported`` (the endpoint does not implement what
the check needs), with the facts it measured. A provider is compatible only for what passed here.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from exulanica.errors import (
    BlobNotFoundError,
    ImmutableKeyError,
    IntegrityError,
    ObjectStoreError,
    ObjectStoreRefused,
)
from exulanica.evidence.blob import BlobId
from exulanica.store.base import PurgeAuthorization, privileged_purger
from exulanica.store.configured import (
    ContentStores,
    local_content_stores,
    object_content_stores,
    sweep_incomplete_writes,
)
from exulanica.store.object import (
    ObjectPurgeRequests,
    ObjectRequests,
    ObjectStoreCredentials,
    ObjectStoreLocation,
)
from exulanica.store.sigv4 import RequestSigner

PROFILE = "exulanica.object-store-verification/v1"
BUCKET = "exulanica-verify"
AUTHORISED = PurgeAuthorization(
    tombstone_id="verify", actor="verify_object_store", reason="cleanup"
)


class Admin:
    """Signed setup requests the product never sends: buckets and their configuration."""

    def __init__(self, endpoint: str, region: str, credentials: dict[str, str]) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._host = httpx.URL(self._endpoint).netloc.decode()
        self._signer = RequestSigner(
            credentials["access_key_id"], credentials["secret_access_key"], region=region
        )
        self._client = httpx.Client(trust_env=False, timeout=60.0)

    def send(
        self,
        method: str,
        path: str,
        *,
        query: list[tuple[str, str]] | None = None,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        from exulanica.store.sigv4 import canonical_query, s3_canonical_uri

        query = query or []
        when = datetime.now(UTC)
        payload = hashlib.sha256(body).hexdigest()
        signed = [
            ("host", self._host),
            ("x-amz-date", when.strftime("%Y%m%dT%H%M%SZ")),
            ("x-amz-content-sha256", payload),
            *sorted((headers or {}).items()),
        ]
        uri = s3_canonical_uri(path)
        authorization = self._signer.sign(method, uri, query, signed, payload, when)
        url = self._endpoint + uri + (f"?{canonical_query(query)}" if query else "")
        sent = {**dict(signed), "authorization": authorization.authorization}
        return self._client.request(method, url, headers=sent, content=body)

    def create_bucket(self, name: str, *, object_lock: bool = False) -> int:
        headers = {"x-amz-bucket-object-lock-enabled": "true"} if object_lock else {}
        return self.send("PUT", f"/{name}", headers=headers).status_code

    def configure(self, bucket: str, subresource: str, document: str) -> int:
        body = document.encode()
        md5 = base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode()
        return self.send(
            "PUT", f"/{bucket}", query=[(subresource, "")], body=body, headers={"content-md5": md5}
        ).status_code

    def delete_marker(self, bucket: str, key: str) -> int:
        return self.send("DELETE", f"/{bucket}/{key}").status_code


class Run:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.identities = {
            name: json.loads((args.credentials / f"{name}.json").read_text(encoding="utf-8"))
            for name in ("runtime", "purge", "admin")
        }
        self.admin = Admin(args.endpoint, args.region, self.identities["admin"])
        self.prefix = f"verify/{uuid.uuid4().hex[:12]}"
        self.scratch = args.scratch
        self.results: list[dict[str, Any]] = []

    def credentials(self, name: str) -> ObjectStoreCredentials:
        identity = self.identities[name]
        return ObjectStoreCredentials(identity["access_key_id"], identity["secret_access_key"])

    def location(self, bucket: str = BUCKET, prefix: str | None = None) -> ObjectStoreLocation:
        return ObjectStoreLocation(
            endpoint=self.args.endpoint,
            bucket=bucket,
            region=self.args.region,
            prefix=self.prefix if prefix is None else prefix,
        )

    def stores(self, identity: str = "runtime", **location: Any) -> ContentStores:
        return object_content_stores(
            self.location(**location),
            self.credentials(identity),
            spool_directory=self.scratch / "spool",
            purging=identity == "purge",
        )

    def environment(self, directory: Path, identity: str = "runtime") -> dict[str, str]:
        credentials = self.identities[identity]
        prefix = "EXULANICA_OBJECT_STORE_" + ("PURGE_" if identity == "purge" else "")
        return {
            "PATH": os.environ["PATH"],
            "HOME": str(directory),
            "EXULANICA_DATA_DIR": str(directory),
            "EXULANICA_STORE_KIND": "object",
            "EXULANICA_OBJECT_STORE_ENDPOINT": self.args.endpoint,
            "EXULANICA_OBJECT_STORE_BUCKET": BUCKET,
            "EXULANICA_OBJECT_STORE_REGION": self.args.region,
            "EXULANICA_OBJECT_STORE_PREFIX": self.prefix,
            f"{prefix}ACCESS_KEY_ID": credentials["access_key_id"],
            f"{prefix}SECRET_ACCESS_KEY": credentials["secret_access_key"],
        }

    def check(self, name: str, function: Callable[[], dict[str, Any] | None]) -> None:
        started = time.monotonic()
        record: dict[str, Any] = {"check": name}
        try:
            detail = function() or {}
            record["outcome"] = detail.pop("outcome", "passed")
            record["detail"] = detail
        except NotSupported as missing:
            record["outcome"] = "not_supported"
            record["detail"] = {"why": str(missing)}
        except Exception as error:
            record["outcome"] = "failed"
            record["detail"] = {
                "error": type(error).__name__,
                "code": getattr(error, "code", None),
                "message": str(error)[:400],
                "at": traceback.extract_tb(error.__traceback__)[-1].lineno,
            }
        record["seconds"] = round(time.monotonic() - started, 3)
        self.results.append(record)
        print(f"{record['outcome']:>13}  {name}  {record['seconds']}s", flush=True)


class NotSupported(Exception):
    """The endpoint does not implement what this check needs."""


# -- the checks ---------------------------------------------------------------------------------


def bucket_check(run: Run) -> dict[str, Any]:
    stores = run.stores()
    stores.blobs.exists(BlobId(b"\x00" * 32))
    described = stores.describe()
    assert described["bucket_check"]["state"] == "verified", described
    return {"describe": described}


def contract(run: Run) -> dict[str, Any]:
    store = run.stores().blobs
    payload = os.urandom(4096)
    first, second = store.put_bytes(payload), store.put_bytes(payload)
    assert (first.created, second.created) == (True, False)
    assert store.get(first.blob_id) == payload and store.size(first.blob_id) == len(payload)
    with store.open(first.blob_id) as handle:
        assert handle.read() == payload
    streamed = store.put_stream(io.BytesIO(payload * 3))
    empty = store.put_bytes(b"")
    listed = set(store.iter_blob_ids())
    assert {first.blob_id, streamed.blob_id, empty.blob_id} <= listed
    assert store.get(empty.blob_id) == b""
    return {"objects": len(listed)}


def key_parity(run: Run) -> dict[str, Any]:
    stores = run.stores(prefix=f"{run.prefix}/parity")
    local_root = run.scratch / "parity"
    local = local_content_stores(local_root)
    workspace = uuid.uuid4()
    for target in (stores, local):
        target.blobs.put_bytes(b"parity photograph")
        target.materials.for_workspace(workspace).put_bytes(b"parity bake")
        target.tiles.put_bytes(b"parity tile")
    local_keys = sorted(
        p.relative_to(local_root).as_posix() for p in local_root.rglob("*") if p.is_file()
    )
    requests = ObjectRequests(run.location(), run.credentials("runtime"))
    object_keys = sorted(
        key.removeprefix(f"{run.prefix}/parity/")
        for key, _size in requests.iter_keys(f"{run.prefix}/parity/")
    )
    assert object_keys == local_keys, (object_keys, local_keys)
    assert list(stores.materials.iter_workspace_ids()) == [workspace]
    return {"keys": len(object_keys)}


def concurrent_identical_puts(run: Run) -> dict[str, Any]:
    store = run.stores().blobs
    payload = os.urandom(2 << 20)
    barrier = threading.Barrier(8)
    results: list[Any] = [None] * 8

    def write(index: int) -> None:
        barrier.wait()
        writer = store.put_stream if index % 2 else None
        results[index] = writer(io.BytesIO(payload)) if writer else store.put_bytes(payload)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    blob = BlobId.of_bytes(payload)
    assert {result.blob_id for result in results} == {blob}
    assert store.get(blob) == payload
    return {"writers": 8, "created": sum(result.created for result in results)}


_CHILD = """
import hashlib, json, os, sys
from exulanica.evidence.blob import BlobId
from exulanica.store.configured import content_stores
stores = content_stores()
action, value = sys.argv[1], sys.argv[2]
if action == "put":
    print(stores.blobs.put_bytes(value.encode()).blob_id.hex)
else:
    data = stores.blobs.get(BlobId.from_hex(value))
    print(hashlib.sha256(data).hexdigest(), stores.blobs.put_bytes(data + b" seen").blob_id.hex)
local = [n for n in ("blobs", "materials", "tiles") if os.path.exists(n)]
assert not local, local
"""


def two_processes(run: Run) -> dict[str, Any]:
    """One process writes, a second with its own data directory reads it and writes back."""
    directory_a, directory_b = run.scratch / "process-a", run.scratch / "process-b"
    for directory in (directory_a, directory_b):
        directory.mkdir(parents=True, exist_ok=True)
    text = f"written by one process {uuid.uuid4()}"
    written = subprocess.run(
        [sys.executable, "-c", _CHILD, "put", text],
        cwd=directory_a,
        env=run.environment(directory_a),
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    ).stdout.strip()
    read = subprocess.run(
        [sys.executable, "-c", _CHILD, "get", written],
        cwd=directory_b,
        env=run.environment(directory_b),
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    ).stdout.split()
    assert read[0] == written
    assert run.stores().blobs.get(BlobId.from_hex(read[1])) == text.encode() + b" seen"
    return {"processes": 2}


def corrupted_object(run: Run) -> dict[str, Any]:
    store = run.stores().blobs
    original = os.urandom(1024)
    blob = store.put_bytes(original).blob_id
    other = os.urandom(1024)
    requests = ObjectRequests(run.location(), run.credentials("runtime"))
    key = f"{run.prefix}/blobs/{store.key_for(blob)}"
    requests.put(
        key,
        other,
        len(other),
        base64.b64encode(hashlib.md5(other, usedforsecurity=False).digest()).decode(),
        hashlib.sha256(other).hexdigest(),
    )
    try:
        store.get(blob)
        raise AssertionError("a read returned bytes that do not hash to their key")
    except IntegrityError:
        pass
    try:
        store.put_bytes(original)
        raise AssertionError("a write absorbed different stored content")
    except ImmutableKeyError:
        pass
    return {"overwritten_by": "runtime identity", "detected_on": ["get", "put"]}


def missing_object(run: Run) -> dict[str, Any]:
    store = run.stores().blobs
    absent = BlobId.of_bytes(uuid.uuid4().bytes)
    assert store.exists(absent) is False
    for operation in (store.get, store.size):
        try:
            operation(absent)
            raise AssertionError(f"{operation.__name__} of an absent key returned")
        except BlobNotFoundError:
            pass
    return {}


def endpoint_checks_digests(run: Run) -> dict[str, Any]:
    requests = ObjectRequests(run.location(), run.credentials("runtime"))
    body = os.urandom(512)
    key = f"{run.prefix}/digest-probe/{uuid.uuid4().hex}"
    wrong_md5 = base64.b64encode(hashlib.md5(b"other", usedforsecurity=False).digest()).decode()
    outcomes = {}
    for label, md5, sha in (
        ("content_md5", wrong_md5, hashlib.sha256(body).hexdigest()),
        (
            "payload_sha256",
            base64.b64encode(hashlib.md5(body, usedforsecurity=False).digest()).decode(),
            hashlib.sha256(b"other").hexdigest(),
        ),
    ):
        try:
            requests.put(key, body, len(body), md5, sha)
            outcomes[label] = "accepted"
        except (IntegrityError, ObjectStoreError) as refused:
            outcomes[label] = f"refused:{getattr(refused, 'code', type(refused).__name__)}"
    # The store sends both on every body; the claim is that the endpoint checks what it keeps,
    # which one enforced digest makes true. Which ones it enforces is recorded either way.
    enforced = any(value.startswith("refused") for value in outcomes.values())
    return {"outcome": "passed" if enforced else "failed", **outcomes}


def large_multipart(run: Run) -> dict[str, Any]:
    store = run.stores().blobs
    size = run.args.large_mib << 20
    source = run.scratch / "large.bin"
    digest = hashlib.sha256()
    with source.open("wb") as out:
        block = os.urandom(1 << 20)
        for index in range(run.args.large_mib):
            chunk = hashlib.sha256(block + index.to_bytes(4, "big")).digest() * (1 << 15)
            digest.update(chunk)
            out.write(chunk)
    result = store.put_file(source)
    assert result.blob_id.digest == digest.digest() and result.byte_size == size
    hasher = hashlib.sha256()
    with store.open(result.blob_id) as handle:
        while chunk := handle.read(1 << 20):
            hasher.update(chunk)
    assert hasher.digest() == digest.digest()
    source.unlink()
    return {"bytes": size}


#: A process that starts an upload, sends one part and is killed, as a crash would leave it. It
#: reaches the store's request set directly, since the store itself always completes or abandons.
_KILLED = """
import base64, hashlib, os, signal
from exulanica.store.configured import content_stores
stores = content_stores()
requests = stores.blobs._requests
key = stores.blobs.namespace + "/sha-256/00/00/" + "00" * 32
upload = requests.create_upload(key)
body = b"part of a photograph" * 1000
requests.upload_part(key, upload, 1, lambda: iter([body]), len(body),
    base64.b64encode(hashlib.md5(body).digest()).decode(), hashlib.sha256(body).hexdigest())
os.kill(os.getpid(), signal.SIGKILL)
"""


def killed_multipart_is_swept(run: Run) -> dict[str, Any]:
    directory = run.scratch / "killed"
    directory.mkdir(parents=True, exist_ok=True)
    child = subprocess.run(
        [sys.executable, "-c", _KILLED],
        cwd=directory,
        env=run.environment(directory),
        capture_output=True,
        timeout=120,
    )
    assert child.returncode == -9, child.stderr
    requests = ObjectRequests(run.location(), run.credentials("runtime"))
    pending = [u for u in requests.iter_uploads(f"{run.prefix}/") if u.key.endswith("00" * 32)]
    assert len(pending) == 1, pending
    time.sleep(2)
    swept = sweep_incomplete_writes(run.stores(), older_than=timedelta(seconds=1))
    remaining = [u for u in requests.iter_uploads(f"{run.prefix}/") if u.key.endswith("00" * 32)]
    assert swept.uploads_aborted >= 1 and remaining == [], (swept, remaining)
    return {"aborted": swept.uploads_aborted}


def paging(run: Run) -> dict[str, Any]:
    store = run.stores(prefix=f"{run.prefix}/paging").blobs
    written = {store.put_bytes(f"page object {n}".encode()).blob_id for n in range(1050)}
    listed = list(store.iter_blob_ids())
    assert len(listed) == len(set(listed)) == 1050 and set(listed) == written
    assert listed == sorted(listed, key=lambda blob: blob.hex)
    return {"objects": 1050}


def runtime_cannot_delete(run: Run) -> dict[str, Any]:
    store = run.stores().blobs
    blob = store.put_bytes(os.urandom(64)).blob_id
    misbuilt = ObjectPurgeRequests(run.location(), run.credentials("runtime"))
    try:
        misbuilt.delete_object_version(f"{run.prefix}/blobs/{store.key_for(blob)}", None)
    except ObjectStoreRefused as refused:
        assert store.exists(blob)
        return {"refused": refused.code}
    return {
        "outcome": "failed",
        "finding": "the endpoint let the runtime identity delete; only the code holds the line",
        "still_exists": store.exists(blob),
    }


def authorised_purge(run: Run) -> dict[str, Any]:
    runtime, purging = run.stores(), run.stores("purge")
    blob = runtime.blobs.put_bytes(os.urandom(256)).blob_id
    purger = privileged_purger(purging.blobs, AUTHORISED)
    assert purger.purge(blob) is True and purger.purge(blob) is False
    assert not runtime.blobs.exists(blob)
    return {}


def versioned_purge(run: Run) -> dict[str, Any]:
    bucket = f"{BUCKET}-versioned"
    run.admin.create_bucket(bucket)
    status = run.admin.configure(
        bucket,
        "versioning",
        '<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        "<Status>Enabled</Status></VersioningConfiguration>",
    )
    if status >= 400:
        raise NotSupported(f"PutBucketVersioning answered {status}")
    runtime, purging = run.stores(bucket=bucket), run.stores("purge", bucket=bucket)
    payload = os.urandom(512)
    blob = runtime.blobs.put_bytes(payload).blob_id
    key = f"{run.prefix}/blobs/{runtime.blobs.key_for(blob)}"
    raw = ObjectRequests(run.location(bucket=bucket), run.credentials("runtime"))
    other = os.urandom(512)
    raw.put(
        key,
        other,
        len(other),
        base64.b64encode(hashlib.md5(other, usedforsecurity=False).digest()).decode(),
        hashlib.sha256(other).hexdigest(),
    )
    run.admin.delete_marker(bucket, key)
    requests = ObjectPurgeRequests(run.location(bucket=bucket), run.credentials("purge"))
    before = requests.versions_of(key)
    if before is None:
        raise NotSupported("ListObjectVersions is not implemented")
    purged = privileged_purger(purging.blobs, AUTHORISED).purge(blob)
    after = requests.versions_of(key)
    assert purged is True and after == [], after
    return {
        "versions_before": len(before),
        "versioning": runtime.describe()["bucket_check"].get("versioning"),
    }


def object_lock_cannot_fake_erasure(run: Run) -> dict[str, Any]:
    """Object lock is refused at first use when the identity can read it; when it cannot, a held
    version must make the purge fail rather than report the bytes erased."""
    bucket = f"{BUCKET}-locked"
    status = run.admin.create_bucket(bucket, object_lock=True)
    if status >= 400 and status != 409:
        raise NotSupported(f"CreateBucket with object lock answered {status}")
    runtime, purging = run.stores(bucket=bucket), run.stores("purge", bucket=bucket)
    try:
        blob = runtime.blobs.put_bytes(os.urandom(256)).blob_id
    except ObjectStoreRefused as refused:
        assert refused.code == "object_store_object_lock_enabled", refused.code
        return {"refused_at_first_use": refused.code}
    key = f"{run.prefix}/blobs/{runtime.blobs.key_for(blob)}"
    body = (
        '<LegalHold xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Status>ON</Status></LegalHold>'
    )
    held = run.admin.send(
        "PUT",
        f"/{bucket}/{key}",
        query=[("legal-hold", "")],
        body=body.encode(),
        headers={
            "content-md5": base64.b64encode(
                hashlib.md5(body.encode(), usedforsecurity=False).digest()
            ).decode()
        },
    ).status_code
    if held >= 400:
        raise NotSupported(f"PutObjectLegalHold answered {held}")
    try:
        erased = privileged_purger(purging.blobs, AUTHORISED).purge(blob)
    except (ObjectStoreError, IntegrityError) as refused:
        assert runtime.blobs.exists(blob)
        return {
            "object_lock": runtime.describe()["bucket_check"].get("object_lock"),
            "purge_refused": getattr(refused, "code", type(refused).__name__),
        }
    return {
        "outcome": "failed",
        "finding": "a purge reported a held version erased",
        "reported": erased,
        "still_exists": runtime.blobs.exists(blob),
    }


def lifecycle_refused(run: Run) -> dict[str, Any]:
    bucket = f"{BUCKET}-lifecycle"
    run.admin.create_bucket(bucket)
    status = run.admin.configure(
        bucket,
        "lifecycle",
        '<LifecycleConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Rule>'
        "<ID>expire</ID><Status>Enabled</Status><Filter><Prefix></Prefix></Filter>"
        "<Expiration><Days>30</Days></Expiration></Rule></LifecycleConfiguration>",
    )
    if status >= 400:
        raise NotSupported(f"PutBucketLifecycleConfiguration answered {status}")
    try:
        run.stores(bucket=bucket).blobs.put_bytes(b"x")
    except ObjectStoreRefused as refused:
        assert refused.code == "object_store_lifecycle_moves_content", refused.code
        return {"refused": refused.code}
    raise AssertionError("a bucket whose lifecycle expires content was trusted")


def describe_names_nothing(run: Run) -> dict[str, Any]:
    stores = run.stores()
    stores.blobs.exists(BlobId(b"\x00" * 32))
    text = json.dumps(stores.describe())
    for secret in run.identities.values():
        assert secret["access_key_id"] not in text and secret["secret_access_key"] not in text
    assert run.args.endpoint not in text and BUCKET not in text
    return {}


def cleanup(run: Run) -> dict[str, Any]:
    requests = ObjectPurgeRequests(run.location(), run.credentials("purge"))
    removed = 0
    for key, _size in list(requests.iter_keys(f"{run.prefix}/")):
        for version_id, _marker in requests.versions_of(key) or [(None, False)]:
            requests.delete_object_version(key, version_id)
            removed += 1
    return {"removed": removed}


CHECKS = (
    ("bucket_check", bucket_check),
    ("contract", contract),
    ("key_parity", key_parity),
    ("concurrent_identical_puts", concurrent_identical_puts),
    ("two_processes_share_the_store", two_processes),
    ("corrupted_object_detected", corrupted_object),
    ("missing_object_named", missing_object),
    ("endpoint_checks_body_digests", endpoint_checks_digests),
    ("large_object_in_parts", large_multipart),
    ("killed_multipart_is_swept", killed_multipart_is_swept),
    ("paging_past_one_page", paging),
    ("runtime_identity_cannot_delete", runtime_cannot_delete),
    ("authorised_purge", authorised_purge),
    ("versioned_bucket_purge", versioned_purge),
    ("object_lock_cannot_fake_erasure", object_lock_cannot_fake_erasure),
    ("lifecycle_expiration_refused", lifecycle_refused),
    ("describe_names_no_value", describe_names_nothing),
    ("cleanup", cleanup),
)


def _revision() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(root), "status", "--porcelain", "--", "exulanica"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {"head": head, "package_modified": bool(dirty)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--provider", required=True, help="the endpoint's name and version")
    parser.add_argument("--provider-sha256", default=None)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--large-mib", type=int, default=70)
    parser.add_argument(
        "--bucket-policy",
        type=Path,
        default=None,
        help="a bucket policy to apply before the checks, in the provider's own principal format; "
        "the one that denies the runtime identity DeleteObject and DeleteObjectVersion",
    )
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error("the report path exists; choose a fresh one")
    args.scratch.mkdir(parents=True, exist_ok=True)
    run = Run(args)
    created = run.admin.create_bucket(BUCKET)
    policy = None
    if args.bucket_policy is not None:
        policy = run.admin.configure(
            BUCKET, "policy", args.bucket_policy.read_text(encoding="utf-8")
        )
    started = datetime.now(UTC)
    for name, function in CHECKS:
        run.check(name, lambda function=function: function(run))
    report = {
        "profile": PROFILE,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "provider": args.provider,
        "provider_sha256": args.provider_sha256,
        "transport": run.location().transport,
        "code_revision": _revision(),
        "bucket_created": created,
        "bucket_policy_status": policy,
        "checks": run.results,
        "totals": {
            outcome: sum(1 for r in run.results if r["outcome"] == outcome)
            for outcome in ("passed", "failed", "not_supported")
        },
    }
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["totals"]))
    return 1 if report["totals"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
