"""The generation worker's side of the bucket: entries, markers, heartbeats, outputs, the session's
state and settlement.

The bucket is the product's signed S3 client against the S3 double (``tests/object_store_double``),
so every byte goes through the real request path. What is written is read back with the session's
own strict reader (``exulanica_pieces.queue.read_entry``), the markers are the ones warm session 1
wrote (``ml/appearance/evidence/generated-assets-session-1``), and settlement is checked against the
charge lines both warm sessions' run records state.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from exulanica.generation import entries
from exulanica.generation.bucket import (
    MAX_OBJECT_BYTES,
    GenerationBucketRefused,
    SignedGenerationBucket,
    bucket_from_key_file,
)
from exulanica.generation.requests import GPU_PROVIDER, generation_catalogs
from exulanica.generation.session import session_state
from exulanica.store.object import ObjectRequests, ObjectStoreCredentials, ObjectStoreLocation
from exulanica_pieces.budgets import read_budgets
from exulanica_pieces.canonical import Refused, canonical_bytes, sha256_hex
from exulanica_pieces.queue import BEAT_PROFILE, read_entry, read_session
from exulanica_pieces.records import read_job, read_request

from object_store_double import S3Double

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "ml/appearance/evidence"
SESSION_1 = EVIDENCE / "generated-assets-session-1"
NOW = datetime(2026, 10, 8, 3, 0, tzinfo=UTC)


@pytest.fixture
def bucket() -> SignedGenerationBucket:
    double = S3Double(bucket="exulanica-gen", region="uk-south2", clock=lambda: NOW)
    location = ObjectStoreLocation(
        endpoint="http://127.0.0.1:19476", bucket="exulanica-gen", region="uk-south2"
    )
    requests = ObjectRequests(
        location,
        ObjectStoreCredentials("runtime-key", "runtime-secret"),
        transport=double.transport(),
        now=lambda: NOW,
    )
    return SignedGenerationBucket(requests)


def _session() -> tuple[bytes, dict]:
    raw = (SESSION_1 / "session.json").read_bytes()
    return raw, read_session(raw)


def _job() -> tuple[bytes, list[bytes]]:
    """Session 1's first entry: its job and the requests it held."""
    job_path = min((SESSION_1 / "jobs").glob("*.json"))
    job_raw = job_path.read_bytes()
    named = {item["request_sha256"] for item in read_job(job_raw)["items"]}
    requests = [(SESSION_1 / "requests" / f"{sha}.json").read_bytes() for sha in sorted(named)]
    return job_raw, requests


def test_an_entry_is_what_the_session_s_own_reader_takes(bucket, tmp_path) -> None:
    job_raw, requests = _job()
    _session_raw, session = _session()
    job_sha256 = entries.queue_entry(bucket, job_raw, requests, NOW)
    assert job_sha256 == sha256_hex(job_raw)
    # Lay the bucket's entry out as the session's mount does and read it as the session does.
    entry = tmp_path / "queue" / job_sha256
    for key in bucket.keys(f"queue/{job_sha256}/"):
        target = tmp_path / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bucket.get(key))
    read_job_raw, read_requests = read_entry(
        entry,
        route=session["route"],
        code_sha256=session["code_sha256"],
        budgets=read_budgets(ROOT),
    )
    assert read_job_raw == job_raw and sorted(read_requests) == sorted(requests)


def test_ready_is_written_last(bucket) -> None:
    written: list[str] = []
    put = bucket.put
    bucket.put = lambda key, data: (written.append(key), put(key, data))  # type: ignore[method-assign]
    job_raw, requests = _job()
    entries.queue_entry(bucket, job_raw, requests, NOW)
    assert written[-1].endswith("/ready.json") and len(written) == len(requests) + 2


def _copy(bucket, source: Path, key: str) -> bytes:
    raw = source.read_bytes()
    bucket.put(key, raw)
    return raw


def test_markers_are_read_only_as_this_session_s_end_of_this_job(bucket) -> None:
    session_raw, _ = _session()
    session_sha256 = sha256_hex(session_raw)
    marker = min((SESSION_1 / "done").glob("*.json"))
    job_sha256 = marker.stem
    assert entries.done(bucket, job_sha256, session_sha256) is None
    assert not entries.claimed(bucket, job_sha256, session_sha256)
    _copy(bucket, marker, f"done/{job_sha256}.json")
    _copy(bucket, SESSION_1 / "claimed" / marker.name, f"claimed/{job_sha256}.json")
    document = entries.done(bucket, job_sha256, session_sha256)
    assert document is not None and document["items"]["total"] == 12
    assert entries.claimed(bucket, job_sha256, session_sha256)
    with pytest.raises(Refused, match="not this session"):
        entries.done(bucket, job_sha256, "0" * 64)
    with pytest.raises(Refused, match="not this session"):
        entries.claimed(bucket, job_sha256, "0" * 64)
    # A marker filed under another job's name is not that job's.
    bucket.put(f"done/{'1' * 64}.json", marker.read_bytes())
    with pytest.raises(Refused, match="not this session"):
        entries.done(bucket, "1" * 64, session_sha256)


def _beat(session_sha256: str, at: datetime, state: str) -> bytes:
    return canonical_bytes(
        {
            "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "job_sha256": None,
            "profile": BEAT_PROFILE,
            "served": 0,
            "session_sha256": session_sha256,
            "started_at": "2026-10-08T02:50:00Z",
            "state": state,
        }
    )


def test_the_latest_heartbeat_is_the_session_s_own(bucket) -> None:
    session = "a" * 64
    assert entries.latest_beat(bucket, session) is None
    bucket.put(f"session/{session}/beat-20261008T025900Z.json", _beat(session, NOW, "loading"))
    bucket.put(f"session/{session}/beat-20261008T025930Z.json", _beat(session, NOW, "idle"))
    assert entries.latest_beat(bucket, session)["state"] == "idle"
    bucket.put(f"session/{session}/beat-20261008T030000Z.json", _beat("b" * 64, NOW, "idle"))
    with pytest.raises(Refused, match="not this session"):
        entries.latest_beat(bucket, session)


@pytest.mark.parametrize(
    ("registered", "ends", "beat", "state"),
    [
        (False, NOW + timedelta(hours=1), None, "off"),
        (True, NOW, None, "off"),
        (True, NOW + timedelta(hours=1), None, "starting"),
        (True, NOW + timedelta(hours=1), (NOW - timedelta(seconds=10), "loading"), "starting"),
        (True, NOW + timedelta(hours=1), (NOW - timedelta(seconds=10), "idle"), "warm"),
        (True, NOW + timedelta(hours=1), (NOW - timedelta(seconds=90), "working"), "warm"),
        (True, NOW + timedelta(hours=1), (NOW - timedelta(seconds=91), "working"), "ended"),
        (True, NOW + timedelta(hours=1), (NOW - timedelta(seconds=10), "ended: idle"), "ended"),
    ],
)
def test_a_session_is_warm_only_while_its_heartbeat_is_fresh_and_its_window_open(
    registered, ends, beat, state
) -> None:
    document = None if beat is None else json.loads(_beat("a" * 64, beat[0], beat[1]))
    assert session_state(registered=registered, window_ends_at=ends, beat=document, now=NOW) == (
        state
    )


def _output_for(receipt_path: Path, piece: bytes) -> bytes:
    """A receipt of session 1, its output restated for ``piece`` (the size the receipt measured)."""
    document = json.loads(receipt_path.read_bytes())
    document["output"] = {"bytes": len(piece), "sha256": sha256_hex(piece)}
    return canonical_bytes(document)


def test_a_job_s_outputs_are_its_receipts_and_their_pieces_checked(bucket) -> None:
    job_raw, requests = _job()
    job_sha256 = sha256_hex(job_raw)
    budgets = read_budgets(ROOT)
    by_digest = {sha256_hex(raw): read_request(raw, budgets) for raw in requests}
    mine = [
        path
        for path in sorted((SESSION_1 / "receipts").glob("*.json"))
        if json.loads(path.read_bytes())["job_sha256"] == job_sha256
    ]
    other = next(
        path
        for path in sorted((SESSION_1 / "receipts").glob("*.json"))
        if json.loads(path.read_bytes())["job_sha256"] != job_sha256
    )
    pieces = {}
    for path in [*mine, other]:
        size = json.loads(path.read_bytes())["measured"]["glb_bytes"]
        piece = path.stem.encode()[:1] * size
        raw = _output_for(path, piece)
        bucket.put(f"out/receipts/{sha256_hex(raw)}.json", raw)
        bucket.put(f"out/pieces/{sha256_hex(piece)}.glb", piece)
        pieces[sha256_hex(raw)] = piece
    found = entries.outputs(bucket, job_sha256, by_digest)
    # Every receipt of this job, none of the other job's, each with its piece's bytes.
    assert len(found) == len(mine) == 12
    assert {output.request_sha256 for output in found} == set(by_digest)
    for output in found:
        assert output.piece == pieces[output.receipt_sha256]
    # A piece whose bytes are not the digest its receipt states is refused.
    bucket.put(f"out/pieces/{found[0].piece_sha256}.glb", b"tampered")
    with pytest.raises(Refused, match="not its bytes"):
        entries.outputs(bucket, job_sha256, by_digest)


def test_a_receipt_naming_a_request_the_job_did_not_hold_is_refused(bucket) -> None:
    job_raw, _requests = _job()
    path = next(
        p
        for p in sorted((SESSION_1 / "receipts").glob("*.json"))
        if json.loads(p.read_bytes())["job_sha256"] == sha256_hex(job_raw)
    )
    raw = path.read_bytes()
    bucket.put(f"out/receipts/{sha256_hex(raw)}.json", raw)
    with pytest.raises(Refused, match="did not hold"):
        entries.outputs(bucket, sha256_hex(job_raw), {})


def test_a_request_settles_to_the_charge_its_run_record_states() -> None:
    compute = generation_catalogs().compute.for_provider(GPU_PROVIDER)
    checked = 0
    for record in (
        "gpu-run-aijob-e05cx0ergby4xfwt0r.json",
        "gpu-run-aijob-e05ff25ssmw6nk0ey7.json",
    ):
        for charge in json.loads((EVIDENCE / record).read_bytes())["charges"]:
            assert compute.usd_for_milliseconds(charge["milliseconds"]) == (
                Decimal(charge["cost_microdollars"]) / 1_000_000
            )
            checked += 1
    assert checked == 20


def test_an_object_larger_than_the_worker_reads_is_refused(bucket) -> None:
    bucket.put("out/meshes/large.glb", b"\0" * (MAX_OBJECT_BYTES + 1))
    with pytest.raises(GenerationBucketRefused, match="larger"):
        bucket.get("out/meshes/large.glb")
    assert bucket.get("out/pieces/absent.glb") is None


def test_the_worker_s_key_file_is_read_strictly_and_its_secret_kept(tmp_path) -> None:
    secret = "a-secret-the-file-holds"
    key = {
        "aws_access_key_id": "worker-key",
        "aws_secret_access_key": secret,
        "endpoint": "https://storage.uk-south2.nebius.cloud",
        "region": "uk-south2",
        "bucket": "exulanica-gen",
    }
    path = tmp_path / "key.json"
    path.write_text(json.dumps(key))
    assert secret not in repr(bucket_from_key_file(path))
    path.write_text(json.dumps({**key, "extra": "x"}))
    with pytest.raises(GenerationBucketRefused, match="exactly"):
        bucket_from_key_file(path)
    path.write_text("{" + secret)
    with pytest.raises(GenerationBucketRefused) as refused:
        bucket_from_key_file(path)
    assert secret not in str(refused.value)
