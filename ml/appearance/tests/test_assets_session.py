"""The warm session and its queue, served from a directory standing in for the bucket mount, with
the stub backend and a clock the test drives.

Expected values come from the queue's layout as its module states it, and from digests recomputed
here with hashlib; a batch's milliseconds come from the test's clock, a quarter second a reading.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from exulanica_pieces.budgets import read_budgets
from exulanica_pieces.canonical import Refused, canonical_bytes, sha256_hex
from exulanica_pieces.geometry.postprocess import POSTPROCESS_VERSION
from exulanica_pieces.records import build_job, build_request

from exulanica_appearance.assets import nebius
from exulanica_appearance.assets.dryrun import STUB_PACK, StubBackend, dry_run
from exulanica_appearance.assets.queue import (
    build_ready,
    build_session,
    charges_from_done,
    entry_files,
    read_done,
    read_session,
    uncached_requests,
)
from exulanica_appearance.assets.remote import publish
from exulanica_appearance.assets.session import Clock, serve
from exulanica_appearance.canonical import Refused as RunRefused
from exulanica_appearance.gpu_run import build_gpu_run, read_gpu_run

CODE = "c0" * 32
BENCH = {"look_role": "prop.bench", "slot_mm": {"width": 1800, "height": 900, "depth": 700}}
LANTERN = {"look_role": "prop.lantern", "slot_mm": {"width": 180, "height": 300, "depth": 180}}
START = datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC)


class FakeClock(Clock):
    """Each monotonic reading is a quarter second after the last; a sleep moves time on."""

    def __init__(self) -> None:
        self.seconds = 0.0
        super().__init__(monotonic=self._tick, now=self._now, sleep=self._sleep)

    def _tick(self) -> float:
        self.seconds += 0.25
        return self.seconds

    def _now(self) -> datetime:
        return START + timedelta(seconds=self.seconds)

    def _sleep(self, seconds: float) -> None:
        self.seconds += seconds


class CountingBackend(StubBackend):
    def __init__(self) -> None:
        self.meshes = 0

    def mesh(self, cutout: bytes, seed: int, request: Any) -> Any:
        self.meshes += 1
        return super().mesh(cutout, seed, request)


def _job(
    repository: Path,
    *specs: dict[str, Any],
    code: str = CODE,
    estimate: int = 60,
    cutout: bool = False,
):
    budgets = read_budgets(repository)
    requests = [
        build_request(pack=STUB_PACK, variants=2, route="S", budgets=budgets, **spec)
        for spec in specs
    ]
    job = build_job(
        route="S",
        components_sha256="5a" * 32,
        requests=requests,
        code_sha256=code,
        container="stub",
        estimate_seconds=estimate,
        budgets=budgets,
        cutouts={(sha256_hex(requests[0]), 0): "cc" * 32} if cutout else None,
    )
    return job, requests


def _enqueue(root: Path, job: bytes, requests: list[bytes], queued_at: datetime = START) -> Path:
    directory = root / "queue" / sha256_hex(job)
    for name, data in entry_files(job, requests).items():
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(data)
    (directory / "ready.json").write_bytes(build_ready(job, requests, queued_at))
    return directory


def _serve(
    repository: Path,
    root: Path,
    backend: Any = None,
    on_publish: Any = None,
    **session: Any,
) -> dict[str, Any]:
    raw = build_session(
        route="S",
        code_sha256=CODE,
        idle_seconds=session.get("idle", 20),
        stop_seconds=session.get("stop", 600),
    )
    work = root.parent / "work"
    return serve(
        root=root,
        session_raw=raw,
        code_sha256=CODE,
        backend=backend or StubBackend(),
        repository=repository,
        work=work,
        publish=on_publish or (lambda: publish(work, root / "out", root.parent / "published.txt")),
        clock=FakeClock(),
        beat_seconds=10_000,
    )


def _done(root: Path, job: bytes) -> dict[str, Any]:
    return read_done((root / "done" / f"{sha256_hex(job)}.json").read_bytes())


def test_a_session_record_holds_its_stops_to_root_s_bounds() -> None:
    raw = build_session(route="A", code_sha256=CODE, stop_seconds=3600)
    assert read_session(raw)["idle_seconds"] == 600
    for changes, match in (
        ({"stop_seconds": 3601}, "hard stop"),
        ({"idle_seconds": 3700}, "idle stop"),
        ({"route": "B"}, "serves route"),
        ({"code_sha256": "c0"}, "code archive"),
    ):
        document = dict(json.loads(raw), **changes)
        with pytest.raises(Refused, match=match):
            read_session(canonical_bytes(document))


def test_a_session_serves_a_ready_batch_once_then_stops_when_idle(
    repository: Path, tmp_path: Path
) -> None:
    root = tmp_path / "bucket"
    job, requests = _job(repository, BENCH, LANTERN)
    _enqueue(root, job, requests)
    done_path = root / "done" / f"{sha256_hex(job)}.json"
    published = []

    def publish_first() -> None:
        assert not done_path.exists(), "a batch is marked done only after its outputs are published"
        publish(tmp_path / "work", root / "out", tmp_path / "published.txt")
        published.append(True)

    result = _serve(repository, root, on_publish=publish_first)
    assert published == [True]
    assert result["reason"] == "idle"
    [served] = result["served"]
    assert served == _done(root, job)
    assert served["items"] == {"made": 4, "total": 4, "within": 4}
    # Each item reads the clock twice, a quarter second apart; two variants a request.
    assert served["request_milliseconds"] == {sha256_hex(raw): 500 for raw in requests}
    claim = json.loads((root / "claimed" / f"{sha256_hex(job)}.json").read_bytes())
    assert claim["session_sha256"] == result["session_sha256"]
    # The outputs were published before the batch was marked done.
    assert len(list((root / "out" / "receipts").glob("*.json"))) == 4
    beats = sorted((root / "session" / result["session_sha256"]).glob("beat-*.json"))
    assert json.loads(beats[0].read_bytes())["state"] == "idle"
    assert json.loads(beats[-1].read_bytes())["state"] == "ended: idle"


def test_an_entry_is_taken_only_once_ready_and_oldest_first(
    repository: Path, tmp_path: Path
) -> None:
    root = tmp_path / "bucket"
    newer, newer_requests = _job(repository, BENCH)
    older, older_requests = _job(repository, LANTERN)
    _enqueue(root, newer, newer_requests, START)
    _enqueue(root, older, older_requests, START - timedelta(minutes=1))
    unready, unready_requests = _job(repository, BENCH, LANTERN)
    directory = _enqueue(root, unready, unready_requests)
    (directory / "ready.json").unlink()
    result = _serve(repository, root)
    assert [done["job_sha256"] for done in result["served"]] == [
        sha256_hex(older),
        sha256_hex(newer),
    ]
    assert not (root / "claimed" / f"{sha256_hex(unready)}.json").exists()


@pytest.mark.parametrize(
    ("spoil", "match"),
    [
        (lambda d, job, reqs: (d / "run.sh").write_text("rm -rf /"), "exactly the files"),
        (
            lambda d, job, reqs: (d / "requests" / "notes.json").write_text("{}"),
            "exactly the files",
        ),
        (
            lambda d, job, reqs: (d / f"requests/{sha256_hex(reqs[0])}.json").write_bytes(b"{}"),
            "not the file",
        ),
        (
            lambda d, job, reqs: (d / "ready.json").write_bytes(
                canonical_bytes(
                    dict(
                        json.loads(build_ready(job, reqs, START)),
                        files={"job.json": sha256_hex(job), "../../runs/x/job.sh": "ab" * 32},
                    )
                )
            ),
            "other than job.json",
        ),
        (
            lambda d, job, reqs: (d / "ready.json").write_bytes(build_ready(job, reqs[:1], START)),
            "exactly the files",
        ),
    ],
)
def test_an_entry_out_of_shape_is_refused_and_never_run(
    repository: Path, tmp_path: Path, spoil: Any, match: str
) -> None:
    root = tmp_path / "bucket"
    job, requests = _job(repository, BENCH, LANTERN)
    spoil(_enqueue(root, job, requests), job, requests)
    backend = CountingBackend()
    _serve(repository, root, backend)
    done = _done(root, job)
    assert match in done["refused"]
    assert backend.meshes == 0


def test_an_entry_holding_a_request_its_job_does_not_name_is_refused(
    repository: Path, tmp_path: Path
) -> None:
    root = tmp_path / "bucket"
    job, requests = _job(repository, BENCH)
    _, extra = _job(repository, LANTERN)
    _enqueue(root, job, requests + extra)
    backend = CountingBackend()
    _serve(repository, root, backend)
    assert "name each other exactly" in _done(root, job)["refused"]
    assert backend.meshes == 0


def test_an_entry_for_another_code_archive_or_from_a_cut_out_is_refused(
    repository: Path, tmp_path: Path
) -> None:
    root = tmp_path / "bucket"
    other, other_requests = _job(repository, BENCH, code="d1" * 32)
    _enqueue(root, other, other_requests)
    cut, cut_requests = _job(repository, LANTERN, cutout=True)
    _enqueue(root, cut, cut_requests)
    backend = CountingBackend()
    _serve(repository, root, backend)
    assert "another code archive" in _done(root, other)["refused"]
    assert "no item names a cut-out" in _done(root, cut)["refused"]
    assert backend.meshes == 0


def test_a_symlinked_file_in_an_entry_is_refused(repository: Path, tmp_path: Path) -> None:
    root = tmp_path / "bucket"
    job, requests = _job(repository, BENCH)
    directory = _enqueue(root, job, requests)
    target = tmp_path / "elsewhere.json"
    path = directory / f"requests/{sha256_hex(requests[0])}.json"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    _serve(repository, root)
    assert "plain file" in _done(root, job)["refused"]


def test_a_stop_marker_ends_the_session_before_the_next_batch(
    repository: Path, tmp_path: Path
) -> None:
    root = tmp_path / "bucket"
    job, requests = _job(repository, BENCH)
    _enqueue(root, job, requests)
    session = build_session(route="S", code_sha256=CODE, idle_seconds=20, stop_seconds=600)
    stop = root / "session" / sha256_hex(session) / "stop"
    stop.parent.mkdir(parents=True)
    stop.write_bytes(b"")
    result = _serve(repository, root)
    assert (result["reason"], result["served"]) == ("stop", [])


def test_a_batch_that_could_not_finish_before_the_hard_stop_waits(
    repository: Path, tmp_path: Path
) -> None:
    root = tmp_path / "bucket"
    # A job estimated at 300 s stops at 450 s, past a 400 s session.
    job, requests = _job(repository, BENCH, estimate=300)
    _enqueue(root, job, requests)
    result = _serve(repository, root, idle=60, stop=400)
    assert (result["reason"], result["served"]) == ("idle", [])
    assert not (root / "claimed" / f"{sha256_hex(job)}.json").exists()


def test_a_request_already_made_under_the_same_key_is_not_queued_again(
    repository: Path, tmp_path: Path
) -> None:
    dry_run(repository, tmp_path / "dry")
    receipts = {p.name: p.read_bytes() for p in (tmp_path / "dry" / "receipts").glob("*.json")}
    requests = [p.read_bytes() for p in sorted((tmp_path / "dry").glob("request-*.json"))]
    components = json.loads(next(iter(receipts.values())))["components_sha256"]
    assert uncached_requests(
        requests, components_sha256=components, postprocess_version=POSTPROCESS_VERSION,
        receipts=receipts,
    ) == []  # fmt: skip
    # Under other weights, or another post-process, every request is made again.
    assert len(
        uncached_requests(
            requests, components_sha256="ee" * 32, postprocess_version=POSTPROCESS_VERSION,
            receipts=receipts,
        )
    ) == len(requests)  # fmt: skip
    # A request missing one variant's receipt is kept.
    first = next(iter(receipts))
    fewer = {name: raw for name, raw in receipts.items() if name != first}
    kept = uncached_requests(
        requests, components_sha256=components, postprocess_version=POSTPROCESS_VERSION,
        receipts=fewer,
    )  # fmt: skip
    assert [sha256_hex(raw) for raw in kept] == [json.loads(receipts[first])["request_sha256"]]
    # A request of two variants with one made is kept; with both made, skipped.
    root = tmp_path / "bucket"
    job, two = _job(repository, BENCH)
    _enqueue(root, job, two)
    _serve(repository, root)
    made = {p.name: p.read_bytes() for p in (root / "out" / "receipts").glob("*.json")}
    assert len(made) == 2
    one = dict(list(made.items())[:1])
    arguments = {"components_sha256": "5a" * 32, "postprocess_version": POSTPROCESS_VERSION}
    assert uncached_requests(two, receipts=one, **arguments) == two
    assert uncached_requests(two, receipts=made, **arguments) == []


def test_each_request_s_charge_reaches_the_run_record(repository: Path, tmp_path: Path) -> None:
    root = tmp_path / "bucket"
    job, requests = _job(repository, BENCH, LANTERN)
    _enqueue(root, job, requests)
    result = _serve(repository, root)
    done = [p.read_bytes() for p in (root / "done").glob("*.json")]
    charges = charges_from_done(
        done, session_sha256=result["session_sha256"], account="GEN envelope"
    )
    assert [c["milliseconds"] for c in charges] == [500, 500]
    record = {
        "charges": charges,
        "deleted_at": "2026-10-07T12:30:00Z",
        "estimate_seconds": 2400,
        "generations": [],
        "gpu": "RTX PRO 6000 Blackwell Server Edition, 96 GB",
        "gpu_count": 1,
        "hard_deadline_at": "2026-10-07T13:00:00Z",
        "instance_name": "aijob-test",
        "instance_type": "gpu-rtx6000-a, preset 1gpu-24vcpu-218gb",
        "over_estimate_reason": "",
        "profile": "exulanica.appearance-gpu-run/v1",
        "provider": "Nebius AI Cloud, uk-south2, Serverless AI job",
        "purpose": "GEN session test",
        "rate_cents_per_hour": 180,
        "rate_source": "test",
        "started_at": "2026-10-07T12:00:00Z",
    }
    raw = build_gpu_run(record)
    run = read_gpu_run(raw)
    assert run["profile"] == "exulanica.appearance-gpu-run/v2"
    # 180 cents an hour for 500 ms: 1,800,000 micro-dollars an hour times 500 / 3,600,000, 250.
    assert [c["cost_microdollars"] for c in run["charges"]] == [250, 250]
    document = json.loads(raw)
    for change, words in (
        ({"cost_microdollars": 249}, "rate times"),
        ({"milliseconds": 1_800_001}, "fit inside"),
        ({"account": ""}, "account"),
    ):
        spoiled = dict(
            document, charges=[dict(document["charges"][0], **change), document["charges"][1]]
        )
        if "milliseconds" in change:
            spoiled["charges"][0]["cost_microdollars"] = 900_001
        with pytest.raises(RunRefused, match=words):
            read_gpu_run(canonical_bytes(spoiled))
    with pytest.raises(RunRefused, match="sorted"):
        read_gpu_run(canonical_bytes(dict(document, charges=document["charges"][::-1])))


def test_a_session_is_submitted_in_session_mode_within_its_bound() -> None:
    raw = build_session(route="A", code_sha256=CODE, stop_seconds=3600)
    arguments: dict[str, Any] = {
        "route": "A", "job_sha256": sha256_hex(raw), "code_sha256": CODE, "bucket_id": "b",
        "subnet_id": "s", "platform": "gpu-rtx6000-a", "preset": "1gpu-24vcpu-218gb",
        "timeout_seconds": 3600, "rate_cents_per_hour": 180, "profile": "p",
        "preemptible": False, "mode": "session",
    }  # fmt: skip
    command = nebius.submit_arguments(bound_cents=180, **arguments)
    assert "MODE=session" in command and "STOP_SECONDS=3600" in command
    assert f"exulanica-gen-session-a-{sha256_hex(raw)[:12]}" in command
    with pytest.raises(Refused, match="worst case"):
        nebius.submit_arguments(bound_cents=179, **arguments)
