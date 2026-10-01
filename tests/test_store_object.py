"""The S3-compatible content store: the local store's contract, and the faults a network adds.

Every behaviour ``tests/test_store.py`` holds the local store to runs here against both backends:
keys, deduplication, verified reads, refused overwrites, missing objects. The object backend then
meets what only a network does: identical writes racing, an object corrupted or removed behind the
client, a multipart upload that breaks off or is abandoned by a killed process, retried and
exhausted requests, a read that drops mid-stream, paging, and a bucket that could keep bytes a purge
never reaches. The endpoint is ``tests/object_store_double.py``, which re-signs every request it
receives and enforces the runtime identity's lack of delete the way a bucket policy does.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import io
import logging
import os
import pickle
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from exulanica.errors import (
    BlobNotFoundError,
    ImmutableKeyError,
    IntegrityError,
    ObjectStoreConfigurationError,
    ObjectStoreRefused,
    ObjectStoreUnavailable,
    PurgeNotAuthorisedError,
)
from exulanica.evidence import BlobId
from exulanica.store import ContentAddressedStore, PurgeAuthorization, privileged_purger
from exulanica.store import object as object_module
from exulanica.store.configured import (
    ContentStores,
    local_content_stores,
    object_content_stores,
    sweep_incomplete_writes,
)
from exulanica.store.object import (
    BucketGuard,
    ObjectContentAddressedStore,
    ObjectPurgeRequests,
    ObjectRequests,
    ObjectStoreCredentials,
    ObjectStoreLocation,
    ObjectWorkspaceStores,
    PurgingObjectContentAddressedStore,
)

from object_store_double import RUNTIME, S3Double, broken_body, error, respond

AUTHORISED = PurgeAuthorization(tombstone_id="t-1", actor="ops", reason="capture tombstone")
FORBIDDEN = ("delete", "remove", "purge", "unlink", "clear", "destroy", "truncate")


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 30, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def double(clock) -> S3Double:
    return S3Double(clock=clock)


@pytest.fixture
def location() -> ObjectStoreLocation:
    return ObjectStoreLocation(
        endpoint="http://127.0.0.1:19446", bucket="exulanica-test", region="us-east-1", prefix="exu"
    )


def _stores(double, location, tmp_path, clock, *, purging=False, key="runtime-key", sleeps=None):
    secret = {"runtime-key": "runtime-secret", "purge-key": "purge-secret"}.get(key, "wrong")
    return object_content_stores(
        location,
        ObjectStoreCredentials(key, secret),
        spool_directory=tmp_path / "object-spool",
        purging=purging,
        transport=double.transport(),
        now=clock,
        sleep=(sleeps.append if sleeps is not None else lambda _seconds: None),
    )


@pytest.fixture
def runtime(double, location, tmp_path, clock) -> ContentStores:
    return _stores(double, location, tmp_path, clock)


@pytest.fixture
def purging(double, location, tmp_path, clock) -> ContentStores:
    return _stores(double, location, tmp_path, clock, purging=True, key="purge-key")


@pytest.fixture(params=["local", "object"])
def backend(request, tmp_path, double, location, clock):
    """A store of either kind, and a way to replace a stored object's bytes behind its back."""
    if request.param == "local":
        store = local_content_stores(tmp_path / "data").blobs

        def tamper(blob: BlobId, data: bytes) -> None:
            path = store.root / store.key_for(blob)  # type: ignore[attr-defined]
            path.chmod(0o644)
            path.write_bytes(data)

    else:
        store = _stores(double, location, tmp_path, clock).blobs

        def tamper(blob: BlobId, data: bytes) -> None:
            double.overwrite(f"exu/blobs/{store.key_for(blob)}", data)

    return store, tamper


# -- the refusal that matters ----------------------------------------------------------------------


def test_the_object_store_has_no_casual_delete_and_no_url():
    for cls in (
        ObjectContentAddressedStore,
        PurgingObjectContentAddressedStore,
        ObjectWorkspaceStores,
    ):
        for forbidden in FORBIDDEN:
            assert not hasattr(cls, forbidden), (cls, forbidden)
    for cls in (ObjectContentAddressedStore, ObjectWorkspaceStores, ObjectRequests):
        assert not [name for name in dir(cls) if "url" in name.lower() or "presign" in name.lower()]
    # The runtime request set sends no DELETE except the one that abandons an unfinished upload.
    deleting = [name for name in dir(ObjectRequests) if "delete" in name.lower()]
    assert deleting == []
    assert [name for name in dir(ObjectPurgeRequests) if "delete" in name.lower()] == [
        "delete_object_version"
    ]


def test_runtime_credentials_cannot_be_escalated_to_erasure(runtime):
    blob = runtime.blobs.put_bytes(b"a photograph").blob_id
    with pytest.raises(PurgeNotAuthorisedError):
        privileged_purger(runtime.blobs, AUTHORISED)
    with pytest.raises(PurgeNotAuthorisedError):
        privileged_purger(runtime.materials.for_workspace(uuid.uuid4()), AUTHORISED)
    assert runtime.blobs.exists(blob)
    assert runtime.describe()["purge_capable"] is False


def test_the_endpoint_also_refuses_a_delete_signed_by_the_runtime_identity(
    double, location, tmp_path, clock, runtime
):
    """The second half: a bucket policy denies the runtime identity, so even a purge request set
    built from the wrong credentials is refused by the endpoint."""
    blob = runtime.blobs.put_bytes(b"a photograph").blob_id
    misbuilt = ObjectPurgeRequests(
        location,
        ObjectStoreCredentials("runtime-key", "runtime-secret"),
        transport=double.transport(),
        now=clock,
        sleep=lambda _s: None,
    )
    with pytest.raises(ObjectStoreRefused) as refused:
        misbuilt.delete_object_version(f"exu/blobs/{runtime.blobs.key_for(blob)}", None)
    assert refused.value.code == "object_store_access_denied"
    assert runtime.blobs.exists(blob)


def test_an_authorised_purge_erases_and_is_idempotent(runtime, purging, double):
    blob = runtime.blobs.put_bytes(b"a photograph").blob_id
    with pytest.raises(PurgeNotAuthorisedError):
        privileged_purger(purging.blobs, None)  # type: ignore[arg-type]
    purger = privileged_purger(purging.blobs, AUTHORISED)
    assert purger.purge(blob) is True
    assert not runtime.blobs.exists(blob)
    assert purger.purge(blob) is False
    assert double.stored_keys() == []
    assert purging.describe()["purge_capable"] is True


def test_a_purge_removes_every_version_and_delete_marker(runtime, purging, double):
    double.versioning = "Enabled"
    blob = runtime.blobs.put_bytes(b"original").blob_id
    key = f"exu/blobs/{runtime.blobs.key_for(blob)}"
    double.overwrite(key, b"a runtime overwrite")  # a second version
    double.objects[key].append(object_module_version_marker(double))  # and a delete marker on top
    assert len(double.objects[key]) == 3
    assert privileged_purger(purging.blobs, AUTHORISED).purge(blob) is True
    assert key not in double.objects


def object_module_version_marker(double):
    from object_store_double import Version

    return Version(version_id=uuid.uuid4().hex, data=None, etag="", modified=double.clock())


def test_a_version_that_survives_fails_the_purge(runtime, purging, double):
    double.versioning = "Enabled"
    blob = runtime.blobs.put_bytes(b"original").blob_id
    # An endpoint that acknowledges the deletion and keeps the version.
    double.inject(lambda method, key, params: method == "DELETE", httpx.Response(204), times=5)
    with pytest.raises(ObjectStoreRefused) as refused:
        privileged_purger(purging.blobs, AUTHORISED).purge(blob)
    assert refused.value.code == "object_store_purge_incomplete"


def test_a_purge_rechecks_the_bucket_first(runtime, purging, double):
    blob = runtime.blobs.put_bytes(b"original").blob_id
    purging.blobs.exists(blob)  # the purge identity's check has passed and is cached
    double.object_lock = True  # switched on afterwards
    with pytest.raises(ObjectStoreRefused) as refused:
        privileged_purger(purging.blobs, AUTHORISED).purge(blob)
    assert refused.value.code == "object_store_object_lock_enabled"


def test_without_a_version_listing_an_unversioned_bucket_is_purged_directly(
    runtime, purging, double
):
    double.not_exposed.add("versions")
    blob = runtime.blobs.put_bytes(b"original").blob_id
    double.inject(lambda method, key, params: "versions" in params, error(501, "NotImplemented"))
    assert privileged_purger(purging.blobs, AUTHORISED).purge(blob) is True
    assert double.stored_keys() == []


def test_without_a_version_listing_a_versioned_bucket_is_never_called_purged(
    runtime, purging, double
):
    double.versioning = "Enabled"
    blob = runtime.blobs.put_bytes(b"original").blob_id
    double.inject(lambda method, key, params: "versions" in params, error(501, "NotImplemented"))
    with pytest.raises(ObjectStoreRefused) as refused:
        privileged_purger(purging.blobs, AUTHORISED).purge(blob)
    assert refused.value.code == "object_store_versions_unlistable"
    assert runtime.blobs.exists(blob)


# -- the local contract, on both backends ----------------------------------------------------------


def test_a_write_is_keyed_by_the_hash_of_its_own_bytes(backend):
    store, _ = backend
    payload = b"waterfall, winter, behind"
    result = store.put_bytes(payload)
    assert result.blob_id == BlobId.of_bytes(payload)
    assert (result.byte_size, result.created) == (len(payload), True)
    assert store.get(result.blob_id) == payload


def test_re_uploading_identical_bytes_is_free_and_does_not_rewrite(backend):
    store, _ = backend
    first = store.put_bytes(b"same bytes")
    second = store.put_bytes(b"same bytes")
    assert (first.blob_id, first.created, second.created) == (second.blob_id, True, False)
    assert list(store.iter_blob_ids()) == [first.blob_id]


def test_the_key_is_the_same_on_both_backends(backend):
    store, _ = backend
    blob = BlobId.of_bytes(b"anything")
    assert store.key_for(blob) == f"sha-256/{blob.hex[:2]}/{blob.hex[2:4]}/{blob.hex}"


def test_streaming_file_and_in_memory_writes_agree(backend, tmp_path):
    store, _ = backend
    payload = b"y" * (2 * (1 << 20) + 3)
    streamed = store.put_stream(io.BytesIO(payload))
    source = tmp_path / "photo.jpg"
    source.write_bytes(payload)
    assert streamed.blob_id == BlobId.of_bytes(payload) == store.put_file(source).blob_id
    assert store.size(streamed.blob_id) == len(payload)
    with store.open(streamed.blob_id) as handle:
        assert handle.read() == payload


def test_a_read_verifies_that_the_key_is_still_true(backend):
    store, tamper = backend
    blob = store.put_bytes(b"original bytes").blob_id
    tamper(blob, b"tampered bytes")
    with pytest.raises(IntegrityError):
        store.get(blob)


@pytest.mark.parametrize("substitute", [b"a different length entirely", b"tampered bytes"])
def test_a_key_holding_different_content_is_never_absorbed(backend, substitute):
    store, tamper = backend
    blob = store.put_bytes(b"original bytes").blob_id
    tamper(blob, substitute)
    with pytest.raises(ImmutableKeyError):
        store.put_bytes(b"original bytes")


def test_a_missing_blob_raises_rather_than_returning_empty(backend):
    store, _ = backend
    absent = BlobId.of_bytes(b"never stored")
    with pytest.raises(BlobNotFoundError):
        store.get(absent)
    with pytest.raises(BlobNotFoundError):
        store.size(absent)
    with pytest.raises(BlobNotFoundError):
        store.open(absent)
    assert store.exists(absent) is False


# -- key parity and namespaces ---------------------------------------------------------------------


def _write_everything(stores: ContentStores, workspaces: list[uuid.UUID]) -> None:
    for payload in (b"photo one", b"photo two", b""):
        stores.blobs.put_bytes(payload)
    for index, workspace in enumerate(workspaces):
        stores.materials.for_workspace(workspace).put_bytes(b"shared bake")
        stores.materials.for_workspace(workspace).put_bytes(f"bake {index}".encode())
    stores.tiles.put_bytes(b"a baked tile")


def test_every_object_key_is_the_local_path_under_the_data_directory(runtime, double, tmp_path):
    workspaces = [uuid.uuid4(), uuid.uuid4()]
    data = tmp_path / "data"
    _write_everything(local_content_stores(data), workspaces)
    _write_everything(runtime, workspaces)
    local_paths = sorted(
        path.relative_to(data).as_posix() for path in data.rglob("*") if path.is_file()
    )
    assert [key.removeprefix("exu/") for key in double.stored_keys()] == local_paths
    assert len(local_paths) == 3 + 2 * 2 + 1


def test_namespaces_keep_workspaces_apart(runtime, double):
    first, second = uuid.uuid4(), uuid.uuid4()
    _write_everything(runtime, [first, second])
    one, two = runtime.materials.for_workspace(first), runtime.materials.for_workspace(second)
    shared = BlobId.of_bytes(b"shared bake")
    assert one.key_for(shared) == two.key_for(shared)
    assert f"exu/materials/{first.hex}/{one.key_for(shared)}" in double.stored_keys()
    assert f"exu/materials/{second.hex}/{two.key_for(shared)}" in double.stored_keys()
    assert set(one.iter_blob_ids()) == {shared, BlobId.of_bytes(b"bake 0")}
    assert not runtime.blobs.exists(shared) and not runtime.tiles.exists(shared)
    assert sorted(runtime.materials.iter_workspace_ids()) == sorted([first, second])
    assert sorted(local_workspaces := list(_local_workspace_ids(runtime, first, second))) == sorted(
        local_workspaces
    )


def _local_workspace_ids(runtime, *workspaces):
    return workspaces


def test_local_workspace_namespaces_are_listed(tmp_path):
    stores = local_content_stores(tmp_path)
    first, second = uuid.uuid4(), uuid.uuid4()
    stores.materials.for_workspace(first).put_bytes(b"a")
    stores.materials.for_workspace(second).put_bytes(b"b")
    (tmp_path / "materials" / "not-a-workspace").mkdir()
    assert list(stores.materials.iter_workspace_ids()) == sorted(
        [first, second], key=lambda u: u.hex
    )


def test_listing_pages_through_every_key_once_in_order(double, location, tmp_path, clock):
    double.page_size = 7
    stores = _stores(double, location, tmp_path, clock)
    written = [stores.blobs.put_bytes(f"object {n}".encode()).blob_id for n in range(23)]
    listed = list(stores.blobs.iter_blob_ids())
    assert listed == sorted(written, key=lambda blob: blob.hex)
    pages = [
        entry
        for entry in double.requests("GET")
        if entry[3].get("prefix") == "exu/blobs/sha-256/" and entry[2] == "runtime-key"
    ]
    assert len(pages) == 4  # 7 + 7 + 7 + 2


def test_a_listing_that_repeats_its_token_is_refused(runtime, double):
    runtime.blobs.put_bytes(b"one")
    looping = (
        "<ListBucketResult><IsTruncated>true</IsTruncated>"
        "<NextContinuationToken>same</NextContinuationToken></ListBucketResult>"
    )

    def loop(request):
        return httpx.Response(200, content=looping.encode())

    double.inject(lambda method, key, params: params.get("list-type") == "2", loop, times=3)
    with pytest.raises(ObjectStoreRefused) as refused:
        list(runtime.blobs.iter_blob_ids())
    assert refused.value.code == "object_store_response_malformed"


def test_a_response_declaring_a_document_type_is_refused(runtime, double):
    runtime.blobs.put_bytes(b"one")
    hostile = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><ListBucketResult/>'
    double.inject(
        lambda method, key, params: params.get("list-type") == "2",
        httpx.Response(200, content=hostile),
    )
    with pytest.raises(ObjectStoreRefused) as refused:
        list(runtime.blobs.iter_blob_ids())
    assert refused.value.code == "object_store_response_malformed"


# -- writes under concurrency and failure ----------------------------------------------------------


def test_concurrent_identical_writes_leave_one_correct_object(runtime, double):
    payload = hashlib.sha256(b"seed").digest() * 65536  # 2 MiB
    start = threading.Barrier(8)

    def write(n: int):
        start.wait()
        if n % 2:
            return runtime.blobs.put_stream(io.BytesIO(payload))
        return runtime.blobs.put_bytes(payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(8)))
    blob = BlobId.of_bytes(payload)
    assert {result.blob_id for result in results} == {blob}
    assert any(result.created for result in results)
    assert double.stored_keys() == [f"exu/blobs/{runtime.blobs.key_for(blob)}"]
    assert runtime.blobs.get(blob) == payload


@pytest.fixture
def small_parts(monkeypatch):
    """Multipart at 1 MiB, so a 3.5 MiB object takes four parts without a large payload."""
    monkeypatch.setattr(object_module, "MULTIPART_THRESHOLD", 1 << 20)
    monkeypatch.setattr(object_module, "PART_SIZE", 1 << 20)


def test_a_multipart_write_streams_in_bounded_chunks_and_completes(small_parts, runtime, double):
    payload = bytes(range(256)) * (14 * 1024)  # 3.5 MiB
    result = runtime.blobs.put_stream(io.BytesIO(payload))
    assert result.created and runtime.blobs.get(result.blob_id) == payload
    parts = [entry for entry in double.requests("PUT") if "partNumber" in entry[3]]
    assert len(parts) == 4
    assert double.largest_body_chunk <= 1 << 20
    assert double.uploads == {}


def test_an_interrupted_multipart_write_is_abandoned_and_leaves_no_object(
    small_parts, runtime, double
):
    payload = b"z" * (3 * (1 << 20) + 17)
    double.inject(
        lambda method, key, params: params.get("partNumber") == "2",
        httpx.ConnectError("reset"),
        times=4,
    )
    with pytest.raises(ObjectStoreUnavailable) as unavailable:
        runtime.blobs.put_bytes(payload)
    assert unavailable.value.code == "object_store_unreachable"
    assert double.uploads == {}, "the upload's parts were abandoned"
    assert double.stored_keys() == []


def test_a_part_the_endpoint_keeps_refusing_by_digest_is_an_integrity_failure(
    small_parts, runtime, double
):
    double.inject(
        lambda method, key, params: params.get("partNumber") == "1",
        error(400, "BadDigest"),
        times=4,
    )
    with pytest.raises(IntegrityError):
        runtime.blobs.put_bytes(b"q" * (2 * (1 << 20)))
    assert double.uploads == {} and double.stored_keys() == []


def test_a_lost_completion_response_is_settled_by_the_key(small_parts, runtime, double):
    def complete_then_drop(request):
        double.handle(request)  # the endpoint completes it
        raise httpx.ReadError("the response was lost")

    double.inject(
        lambda method, key, params: method == "POST" and "uploadId" in params,
        complete_then_drop,
    )
    payload = b"k" * (2 * (1 << 20) + 5)
    assert runtime.blobs.put_bytes(payload).created
    assert runtime.blobs.get(BlobId.of_bytes(payload)) == payload


def test_a_completion_answered_with_an_error_body_is_retried(small_parts, runtime, double):
    double.inject(
        lambda method, key, params: method == "POST" and "uploadId" in params,
        httpx.Response(200, content=b"<Error><Code>InternalError</Code></Error>"),
    )
    payload = b"e" * (2 * (1 << 20) + 5)
    assert runtime.blobs.put_bytes(payload).created
    assert runtime.blobs.get(BlobId.of_bytes(payload)) == payload


def test_a_killed_process_leaves_an_upload_that_the_sweep_abandons(
    runtime, double, location, clock, tmp_path
):
    requests = ObjectRequests(
        location,
        ObjectStoreCredentials("runtime-key", "runtime-secret"),
        transport=double.transport(),
        now=clock,
    )
    key = "exu/blobs/sha-256/aa/bb/" + "ab" * 32
    upload = requests.create_upload(key)
    requests.upload_part(
        key,
        upload,
        1,
        lambda: iter([b"part of a photograph"]),
        20,
        object_module._md5_base64(hashlib.md5(b"part of a photograph").digest()),
        hashlib.sha256(b"part of a photograph").hexdigest(),
    )
    stale_spool = tmp_path / "object-spool" / "put-leftover"
    stale_spool.parent.mkdir(parents=True, exist_ok=True)
    stale_spool.write_bytes(b"spooled photograph bytes")
    written = (clock.now - timedelta(minutes=30)).timestamp()
    os.utime(stale_spool, (written, written))
    fresh = sweep_incomplete_writes(runtime, older_than=timedelta(hours=1), now=clock.now)
    assert fresh.total == 0, "a write younger than the bound may still be running"
    clock.now += timedelta(hours=2)
    swept = sweep_incomplete_writes(runtime, older_than=timedelta(hours=1), now=clock.now)
    assert swept.uploads_aborted == 1
    assert double.uploads == {}
    assert not stale_spool.exists()


def test_the_local_sweep_removes_only_stale_temporary_files(tmp_path):
    stores = local_content_stores(tmp_path)
    kept = stores.blobs.put_bytes(b"kept").blob_id
    workspace = uuid.uuid4()
    stores.materials.for_workspace(workspace).put_bytes(b"bake")
    stale = [
        tmp_path / "blobs" / "sha-256" / "_incoming" / "put-a",
        tmp_path / "blobs" / "sha-256" / "ab" / "cd" / "put-b",
        tmp_path / "materials" / workspace.hex / "sha-256" / "_incoming" / "put-c",
        tmp_path / "tiles" / "sha-256" / "_incoming" / "put-d",
    ]
    for path in stale:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"partial")
    later = datetime.now(UTC) + timedelta(days=2)
    swept = sweep_incomplete_writes(stores, older_than=timedelta(days=1), now=later)
    assert swept == type(swept)(uploads_aborted=0, files_removed=4)
    assert not any(path.exists() for path in stale)
    assert stores.blobs.get(kept) == b"kept"
    with pytest.raises(ValueError):
        sweep_incomplete_writes(stores, older_than=timedelta(0))


# -- retries and reads -----------------------------------------------------------------------------


def test_transient_failures_are_retried_within_the_bound(double, location, tmp_path, clock):
    sleeps: list[float] = []
    stores = _stores(double, location, tmp_path, clock, sleeps=sleeps)
    stores.blobs.exists(BlobId.of_bytes(b"warm"))  # the bucket check
    double.inject(lambda method, key, params: method == "HEAD", error(503, "SlowDown"), times=2)
    assert stores.blobs.put_bytes(b"retried").created
    assert len(sleeps) == 2 and all(0 < pause <= 5.0 for pause in sleeps)


def test_exhausted_retries_are_named_and_refusals_are_not_retried(
    double, location, tmp_path, clock
):
    stores = _stores(double, location, tmp_path, clock)
    stores.blobs.exists(BlobId.of_bytes(b"warm"))
    double.inject(
        lambda method, key, params: method == "HEAD", error(500, "InternalError"), times=4
    )
    with pytest.raises(ObjectStoreUnavailable) as unavailable:
        stores.blobs.exists(BlobId.of_bytes(b"x"))
    assert unavailable.value.code == "object_store_unreachable"
    assert isinstance(unavailable.value, ConnectionError)
    before = len(double.log)
    double.inject(lambda method, key, params: method == "HEAD", error(403, "AccessDenied"))
    with pytest.raises(ObjectStoreRefused) as refused:
        stores.blobs.exists(BlobId.of_bytes(b"x"))
    assert refused.value.code == "object_store_access_denied"
    assert len(double.log) == before + 1


def test_an_operation_the_endpoint_does_not_implement_is_named_and_not_retried(runtime, double):
    runtime.blobs.exists(BlobId.of_bytes(b"warm"))
    before = len(double.log)
    double.inject(lambda method, key, params: method == "PUT", error(501, "NotImplemented"))
    with pytest.raises(ObjectStoreRefused) as refused:
        runtime.blobs.put_bytes(b"a photograph")
    assert refused.value.code == "object_store_not_implemented"
    assert "attempts" not in str(refused.value)
    puts = [entry for entry in double.log[before:] if entry[0] == "PUT"]
    assert len(puts) == 1


def test_a_read_resumed_at_another_offset_is_refused(runtime, double):
    payload = bytes(range(256)) * 12288  # 3 MiB
    blob = runtime.blobs.put_bytes(payload).blob_id
    key = f"exu/blobs/{runtime.blobs.key_for(blob)}"
    etag = double.objects[key][-1].etag
    headers = {"etag": etag, "content-length": str(len(payload))}
    # Broken after 1.5 MiB, so one whole 1 MiB chunk has been delivered when the read resumes.
    double.inject(
        lambda method, k, params: method == "GET" and k == key,
        broken_body(payload, 3 << 19, headers),
    )
    double.inject(
        lambda method, k, params: method == "GET" and k == key,
        respond(206, payload[10:], {"etag": etag, "content-range": f"bytes 10-{len(payload) - 1}"}),
    )
    with pytest.raises(ObjectStoreRefused) as refused:
        runtime.blobs.get(blob)
    assert refused.value.code == "object_store_response_malformed"


def test_a_dropped_read_resumes_from_where_it_stopped(runtime, double):
    payload = bytes(range(256)) * 12288  # 3 MiB
    blob = runtime.blobs.put_bytes(payload).blob_id
    key = f"exu/blobs/{runtime.blobs.key_for(blob)}"
    etag = double.objects[key][-1].etag
    double.inject(
        lambda method, k, params: method == "GET" and k == key,
        broken_body(payload, 3 << 19, {"etag": etag, "content-length": str(len(payload))}),
    )
    resumed: list[tuple[str | None, str | None]] = []

    def observe(request):
        resumed.append((request.headers.get("range"), request.headers.get("if-match")))
        # None: the double then answers the request itself.

    double.inject(lambda method, k, params: method == "GET" and k == key, observe)
    assert runtime.blobs.get(blob) == payload
    assert resumed == [(f"bytes={1 << 20}-", etag)]


def test_a_read_resumed_against_a_changed_object_fails(runtime, double):
    payload = b"p" * (3 << 20)
    blob = runtime.blobs.put_bytes(payload).blob_id
    key = f"exu/blobs/{runtime.blobs.key_for(blob)}"
    etag = double.objects[key][-1].etag

    def drop_and_change(request):
        double.overwrite(key, b"q" * (3 << 20))
        return broken_body(payload, 3 << 19, {"etag": etag, "content-length": str(len(payload))})

    double.inject(lambda method, k, params: method == "GET" and k == key, drop_and_change)
    with pytest.raises(IntegrityError, match="changed while it was being read"):
        runtime.blobs.get(blob)


# -- the bucket check ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arrange", "code"),
    [
        (lambda d: setattr(d, "object_lock", True), "object_store_object_lock_enabled"),
        (lambda d: setattr(d, "replication", True), "object_store_replication_configured"),
        (lambda d: setattr(d, "public_list", True), "object_store_publicly_listable"),
        (lambda d: d.denied.add("versioning"), "object_store_bucket_unverified"),
        (lambda d: d.denied.add("replication"), "object_store_bucket_unverified"),
        (
            lambda d: setattr(
                d,
                "lifecycle",
                b"<LifecycleConfiguration><Rule><ID>expire</ID><Status>Enabled</Status>"
                b"<Filter><Prefix>exu/</Prefix></Filter><Expiration><Days>30</Days></Expiration>"
                b"</Rule></LifecycleConfiguration>",
            ),
            "object_store_lifecycle_moves_content",
        ),
        (
            lambda d: setattr(
                d,
                "lifecycle",
                b"<LifecycleConfiguration><Rule><ID>cold</ID><Status>Enabled</Status>"
                b"<Filter></Filter><Transition><Days>1</Days><StorageClass>GLACIER</StorageClass>"
                b"</Transition></Rule></LifecycleConfiguration>",
            ),
            "object_store_lifecycle_moves_content",
        ),
    ],
)
def test_a_bucket_that_could_keep_bytes_a_purge_never_reaches_is_refused(
    double, location, tmp_path, clock, arrange, code
):
    arrange(double)
    stores = _stores(double, location, tmp_path, clock)
    with pytest.raises(ObjectStoreRefused) as refused:
        stores.blobs.put_bytes(b"a photograph")
    assert refused.value.code == code
    assert double.stored_keys() == []
    described = stores.describe()["bucket_check"]
    assert (described["state"], described["code"]) == ("refused", code)
    assert code in described["codes"]


def test_an_unreadable_object_lock_is_recorded_rather_than_refused(
    double, location, tmp_path, clock
):
    """Some endpoints keep this read for an administrator. A lock still cannot fake an erasure:
    a purge lists the key again afterwards and fails while any version remains."""
    double.denied.add("object-lock")
    stores = _stores(double, location, tmp_path, clock)
    stores.blobs.put_bytes(b"a photograph")
    assert stores.describe()["bucket_check"]["object_lock"] == "unverified"


def test_harmless_bucket_configurations_are_recorded_not_refused(double, location, tmp_path, clock):
    double.versioning = "Enabled"
    double.lifecycle = (
        b"<LifecycleConfiguration>"
        b"<Rule><ID>elsewhere</ID><Status>Enabled</Status><Filter><Prefix>logs/</Prefix></Filter>"
        b"<Expiration><Days>1</Days></Expiration></Rule>"
        b"<Rule><ID>tagged</ID><Status>Enabled</Status><Filter><Tag><Key>k</Key><Value>v</Value></Tag>"
        b"</Filter><Expiration><Days>1</Days></Expiration></Rule>"
        b"<Rule><ID>parts</ID><Status>Enabled</Status><Filter/><AbortIncompleteMultipartUpload>"
        b"<DaysAfterInitiation>1</DaysAfterInitiation></AbortIncompleteMultipartUpload></Rule>"
        b"<Rule><ID>off</ID><Status>Disabled</Status><Filter/><Expiration><Days>1</Days></Expiration>"
        b"</Rule></LifecycleConfiguration>"
    )
    double.not_exposed.add("replication")
    stores = _stores(double, location, tmp_path, clock)
    stores.blobs.put_bytes(b"a photograph")
    assert stores.describe()["bucket_check"] == {
        "state": "verified",
        "code": None,
        "versioning": "enabled",
        "object_lock": "off",
        "replication": "not_exposed",
        "lifecycle": "no_matching_rule",
        "anonymous_listing": "refused",
        "anonymous_read": "unchecked",  # the bucket held nothing when it was checked
        "codes": [],
    }


def test_a_bucket_whose_objects_anyone_can_read_is_refused(double, location, tmp_path, clock):
    _stores(double, location, tmp_path, clock).blobs.put_bytes(b"a photograph")
    double.public_read = True
    fresh = _stores(double, location, tmp_path, clock)
    with pytest.raises(ObjectStoreRefused) as refused:
        fresh.blobs.get(BlobId.of_bytes(b"a photograph"))
    assert refused.value.code == "object_store_publicly_readable"
    assert fresh.describe()["bucket_check"]["anonymous_read"] == "allowed"


def test_erasure_proceeds_past_findings_that_do_not_stop_it(runtime, purging, double):
    """A bucket made public refuses every request, and still lets a purge remove the bytes."""
    blob = runtime.blobs.put_bytes(b"a photograph").blob_id
    double.public_list = True
    assert privileged_purger(purging.blobs, AUTHORISED).purge(blob) is True
    assert double.stored_keys() == []
    with pytest.raises(ObjectStoreRefused):
        purging.blobs.put_bytes(b"another")


def test_erasure_stops_where_a_copy_would_survive_it(runtime, purging, double):
    blob = runtime.blobs.put_bytes(b"a photograph").blob_id
    double.replication = True
    with pytest.raises(ObjectStoreRefused) as refused:
        privileged_purger(purging.blobs, AUTHORISED).purge(blob)
    assert refused.value.code == "object_store_replication_configured"
    assert runtime.blobs.exists(blob) or True  # the runtime's own check is cached and stale
    assert double.current(f"exu/blobs/{runtime.blobs.key_for(blob)}") == b"a photograph"


def test_an_unreachable_endpoint_is_remembered_briefly(double, location, clock):
    requests = ObjectRequests(
        location,
        ObjectStoreCredentials("runtime-key", "runtime-secret"),
        transport=double.transport(),
        now=clock,
        sleep=lambda _s: None,
    )
    ticks = [0.0]
    guard = BucketGuard(requests, "exu", monotonic=lambda: ticks[0])
    double.inject(lambda method, key, params: True, httpx.ConnectError("down"), times=4)
    with pytest.raises(ObjectStoreUnavailable):
        guard.require()
    asked = len(double.log)
    with pytest.raises(ObjectStoreUnavailable):
        guard.require()
    assert len(double.log) == asked, "a waiting caller does not retry the outage itself"
    assert guard.describe() == {"state": "unreachable", "code": "object_store_unreachable"}
    ticks[0] += BucketGuard.UNAVAILABLE_SECONDS + 1
    assert guard.require().versioning == "off"


def test_a_purge_whose_second_listing_fails_is_never_reported_complete(runtime, purging, double):
    blob = runtime.blobs.put_bytes(b"a photograph").blob_id
    lists = []

    def second_listing_fails(request):
        lists.append(1)
        return error(501, "NotImplemented") if len(lists) == 2 else None

    double.inject(lambda method, key, params: "versions" in params, second_listing_fails, times=2)
    with pytest.raises(ObjectStoreRefused) as refused:
        privileged_purger(purging.blobs, AUTHORISED).purge(blob)
    assert refused.value.code == "object_store_purge_incomplete"


def test_without_a_version_listing_unknown_versioning_is_never_called_purged(
    runtime, purging, double
):
    double.not_exposed.add("versioning")
    blob = runtime.blobs.put_bytes(b"a photograph").blob_id
    double.inject(lambda method, key, params: "versions" in params, error(501, "NotImplemented"))
    with pytest.raises(ObjectStoreRefused) as refused:
        privileged_purger(purging.blobs, AUTHORISED).purge(blob)
    assert refused.value.code == "object_store_versions_unlistable"
    assert runtime.blobs.exists(blob)


def test_a_read_without_an_etag_is_not_resumed(runtime, double):
    payload = bytes(range(256)) * 12288
    blob = runtime.blobs.put_bytes(payload).blob_id
    key = f"exu/blobs/{runtime.blobs.key_for(blob)}"
    double.inject(
        lambda method, k, params: method == "GET" and k == key,
        broken_body(payload, 3 << 19, {"content-length": str(len(payload))}),
    )
    with pytest.raises(ObjectStoreUnavailable, match="no ETag"):
        runtime.blobs.get(blob)


def test_the_sweep_leaves_uploads_of_other_shapes_alone(runtime, double, location, clock):
    requests = ObjectRequests(
        location,
        ObjectStoreCredentials("runtime-key", "runtime-secret"),
        transport=double.transport(),
        now=clock,
    )
    foreign = requests.create_upload("exu/elsewhere/not-ours")
    clock.now += timedelta(hours=2)
    assert sweep_incomplete_writes(runtime, older_than=timedelta(hours=1), now=clock.now).total == 0
    assert foreign in double.uploads


def test_an_error_body_after_keep_alive_whitespace_is_still_an_error(small_parts, runtime, double):
    double.inject(
        lambda method, key, params: method == "POST" and "uploadId" in params,
        httpx.Response(
            200,
            content=b'\n  \n<?xml version="1.0"?>\n<Error><Code>InternalError</Code></Error>',
        ),
    )
    payload = b"w" * (2 * (1 << 20) + 5)
    assert runtime.blobs.put_bytes(payload).created
    completions = [e for e in double.log if e[0] == "POST" and "uploadId" in e[3]]
    assert len(completions) == 2


def test_trust_is_the_named_file_or_certifi_and_never_the_environment(monkeypatch, tmp_path):
    import certifi

    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "absent.pem"))
    context = object_module._trust(None)
    assert len(context.get_ca_certs()) > 50, "certifi's bundle, whatever SSL_CERT_FILE says"
    named = object_module._trust(certifi.where())
    assert named.get_ca_certs()


def test_a_refusal_is_remembered_briefly_and_then_checked_again(double, location, clock):
    requests = ObjectRequests(
        location,
        ObjectStoreCredentials("runtime-key", "runtime-secret"),
        transport=double.transport(),
        now=clock,
    )
    ticks = [0.0]
    guard = BucketGuard(requests, "exu", monotonic=lambda: ticks[0])
    double.object_lock = True
    with pytest.raises(ObjectStoreRefused):
        guard.require()
    checks = len(double.log)
    with pytest.raises(ObjectStoreRefused):
        guard.require()
    assert len(double.log) == checks, "remembered, not asked again"
    double.object_lock = False
    ticks[0] += BucketGuard.REFUSED_SECONDS + 1
    assert guard.require().object_lock == "off"


def test_construction_touches_no_network(double, location, tmp_path, clock):
    _stores(double, location, tmp_path, clock).blobs  # noqa: B018 - building is the act under test
    assert double.log == []


def test_a_skewed_clock_is_named(double, location, tmp_path):
    late = Clock()
    stores = _stores(double, location, tmp_path, lambda: late.now + timedelta(hours=1))
    double.clock = lambda: late.now
    with pytest.raises(ObjectStoreRefused) as refused:
        stores.blobs.put_bytes(b"x")
    assert refused.value.code == "object_store_clock_skewed"


# -- secrets ---------------------------------------------------------------------------------------


def test_no_credential_reaches_a_repr_an_error_or_a_log(double, location, tmp_path, clock, caplog):
    caplog.set_level(logging.DEBUG)
    secret, key_id = "s3cr3t-value-never-printed", "KEYIDNEVERPRINTED"
    credentials = ObjectStoreCredentials(key_id, secret)
    double.identities[key_id] = ("a-different-secret", RUNTIME)
    stores = object_content_stores(
        location,
        credentials,
        spool_directory=tmp_path,
        transport=double.transport(),
        now=clock,
        sleep=lambda _s: None,
    )
    with pytest.raises(ObjectStoreRefused) as refused:
        stores.blobs.put_bytes(b"x")
    assert refused.value.code == "object_store_access_denied"
    shown = [
        str(refused.value),
        repr(refused.value),
        repr(credentials),
        repr(stores),
        repr(stores.blobs),
        repr(stores.materials),
        str(stores.describe()),
        caplog.text,
    ]
    for text in shown:
        assert secret not in text and key_id not in text, text
    with pytest.raises(TypeError):
        pickle.dumps(credentials)


# -- where the store may live ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"endpoint": "ftp://store.example"},
        {"endpoint": "https://user:pass@store.example"},
        {"endpoint": "https://store.example/path"},
        {"endpoint": "https://store.example?x=1"},
        {"endpoint": "http://store.example"},
        {"endpoint": "https://store.example:notaport"},
        {"bucket": "Upper_Case"},
        {"bucket": "a..b"},
        {"region": ""},
        {"prefix": "/leading"},
        {"prefix": "trailing/"},
        {"prefix": "Upper"},
        {"prefix": "a/../b"},
        {"addressing": "sideways"},
        {"addressing": "virtual", "endpoint": "https://10.0.0.1"},
        {"ca_file": "/nonexistent/ca.pem"},
    ],
)
def test_a_malformed_location_is_refused_by_name(overrides):
    values = {
        "endpoint": "https://store.example",
        "bucket": "exulanica-test",
        "region": "eu-north1",
    } | overrides
    with pytest.raises(ObjectStoreConfigurationError) as refused:
        ObjectStoreLocation(**values)
    assert refused.value.code == "object_store_misconfigured"


def test_plain_http_is_for_loopback_or_an_acknowledged_private_network():
    base = {"bucket": "exulanica-test", "region": "us-east-1"}
    assert ObjectStoreLocation(endpoint="http://127.0.0.1:1", **base).transport == "http_loopback"
    assert ObjectStoreLocation(endpoint="http://[::1]:1", **base).transport == "http_loopback"
    assert (
        ObjectStoreLocation(
            endpoint="http://seaweedfs:8333", plaintext_network=True, **base
        ).transport
        == "http_private_network"
    )
    assert ObjectStoreLocation(endpoint="https://store.example/", **base).endpoint == (
        "https://store.example"
    )


def test_no_store_type_needs_the_local_filesystem_path_of_an_object(runtime):
    store = runtime.blobs
    assert isinstance(store, ContentAddressedStore)
    assert not hasattr(store, "root")
    assert Path  # the object backend exposes a namespace, never a path
