"""The warm session and its queue, served from a directory standing in for the bucket mount, with
the stub backend and a clock the test drives.

Expected values come from the queue's layout as its module states it, and from digests recomputed
here with hashlib; a batch's milliseconds come from the test's clock, a quarter second a reading.
"""

from __future__ import annotations

import itertools
import json
import shutil
import subprocess
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
    build_withdrawn,
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
#: The entry each job was last queued as, so a test names an entry by its job.
ENTRIES: dict[str, str] = {}
_ENTRY_NUMBERS = itertools.count()


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
    components: str = "5a" * 32,
):
    budgets = read_budgets(repository)
    requests = [
        build_request(pack=STUB_PACK, variants=2, route="S", budgets=budgets, **spec)
        for spec in specs
    ]
    job = build_job(
        route="S",
        components_sha256=components,
        requests=requests,
        code_sha256=code,
        container="stub",
        estimate_seconds=estimate,
        budgets=budgets,
        cutouts={(sha256_hex(requests[0]), 0): "cc" * 32} if cutout else None,
    )
    return job, requests


def _session_raw(idle: int = 20, stop: int = 600) -> bytes:
    """The record ``_serve`` starts its session from, by default."""
    return build_session(route="S", code_sha256=CODE, idle_seconds=idle, stop_seconds=stop)


def _enqueue(
    root: Path,
    job: bytes,
    requests: list[bytes],
    queued_at: datetime = START,
    not_after: datetime | None = None,
    session: bytes | None = None,
) -> Path:
    # A fresh id for every entry, as the product's batch ids are: identical jobs are two entries.
    entry = sha256_hex(f"{next(_ENTRY_NUMBERS)}:{root}:{sha256_hex(job)}".encode())[:32]
    ENTRIES[sha256_hex(job)] = entry
    directory = root / "queue" / entry
    for name, data in entry_files(job, requests).items():
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(data)
    (directory / "ready.json").write_bytes(
        build_ready(
            entry,
            job,
            requests,
            session_sha256=sha256_hex(session or _session_raw()),
            queued_at=queued_at,
            not_after=not_after or queued_at + timedelta(hours=1),
        )
    )
    return directory


def _entry(job: bytes) -> str:
    return ENTRIES[sha256_hex(job)]


def _serve(
    repository: Path,
    root: Path,
    backend: Any = None,
    on_publish: Any = None,
    **session: Any,
) -> dict[str, Any]:
    raw = _session_raw(session.get("idle", 20), session.get("stop", 600))
    work = root.parent / "work"
    return serve(
        root=root,
        session_raw=raw,
        code_sha256=CODE,
        components_sha256="5a" * 32,
        backend=backend or StubBackend(),
        repository=repository,
        work=work,
        publish=on_publish or (lambda: publish(work, root / "out", root.parent / "published.txt")),
        clock=FakeClock(),
        beat_seconds=10_000,
    )


def _done(root: Path, job: bytes) -> dict[str, Any]:
    return read_done((root / "done" / f"{_entry(job)}.json").read_bytes())


def test_a_session_record_holds_its_stops_to_root_s_bounds() -> None:
    raw = build_session(route="A", code_sha256=CODE, stop_seconds=3600)
    assert read_session(raw)["idle_seconds"] == 600
    # A nonce keeps two sessions with the same settings apart; a record without one still reads.
    first = build_session(route="A", code_sha256=CODE, stop_seconds=3600, nonce="1" * 32)
    second = build_session(route="A", code_sha256=CODE, stop_seconds=3600, nonce="2" * 32)
    assert len({sha256_hex(raw), sha256_hex(first), sha256_hex(second)}) == 3
    assert "nonce" not in read_session(raw)
    with pytest.raises(Refused, match="nonce"):
        read_session(canonical_bytes(dict(json.loads(raw), nonce="x")))
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
    done_path = root / "done" / f"{_entry(job)}.json"
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
    claim = json.loads((root / "claimed" / f"{_entry(job)}.json").read_bytes())
    assert (claim["session_sha256"], claim["entry_id"], claim["job_sha256"]) == (
        result["session_sha256"],
        _entry(job),
        sha256_hex(job),
    )
    # The outputs were published before the batch was marked done, and the marker names them.
    published_receipts = sorted(p.stem for p in (root / "out" / "receipts").glob("*.json"))
    assert len(published_receipts) == 4
    assert served["receipts"] == published_receipts
    assert served["entry_id"] == _entry(job)
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
    assert not (root / "claimed" / f"{_entry(unready)}.json").exists()


def test_two_identical_jobs_are_two_entries_each_run_and_marked_once(
    repository: Path, tmp_path: Path
) -> None:
    root = tmp_path / "bucket"
    job, requests = _job(repository, BENCH)
    first = _enqueue(root, job, requests, START - timedelta(minutes=1)).name
    second = _enqueue(root, job, requests, START).name
    result = _serve(repository, root)
    assert [done["entry_id"] for done in result["served"]] == [first, second]
    for entry in (first, second):
        assert read_done((root / "done" / f"{entry}.json").read_bytes())["job_sha256"] == (
            sha256_hex(job)
        )


def test_an_entry_queued_for_another_session_on_the_bucket_is_never_taken(
    repository: Path, tmp_path: Path
) -> None:
    # Two sessions started from one tree differ by their records; each entry names its own.
    root = tmp_path / "bucket"
    job, requests = _job(repository, BENCH)
    other = build_session(
        route="S", code_sha256=CODE, idle_seconds=20, stop_seconds=600, nonce="0f" * 16
    )
    theirs = _enqueue(root, job, requests, START - timedelta(minutes=1), session=other).name
    mine = _enqueue(root, job, requests, START).name
    backend = CountingBackend()
    result = _serve(repository, root, backend)
    assert [done["entry_id"] for done in result["served"]] == [mine]
    assert not (root / "claimed" / f"{theirs}.json").exists()


def test_an_entry_past_its_not_after_is_never_claimed_or_run(
    repository: Path, tmp_path: Path
) -> None:
    root = tmp_path / "bucket"
    job, requests = _job(repository, BENCH)
    entry = _enqueue(
        root, job, requests, START - timedelta(hours=1), START - timedelta(seconds=1)
    ).name
    backend = CountingBackend()
    result = _serve(repository, root, backend)
    assert (result["reason"], result["served"], backend.meshes) == ("idle", [], 0)
    assert not (root / "claimed" / f"{entry}.json").exists()
    assert not (root / "done" / f"{entry}.json").exists()


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
                build_ready(
                    d.name,
                    job,
                    reqs[:1],
                    session_sha256=sha256_hex(_session_raw()),
                    queued_at=START,
                    not_after=START + timedelta(hours=1),
                )
            ),
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


def test_an_entry_that_cannot_be_shown_to_be_this_session_s_is_never_claimed(
    repository: Path, tmp_path: Path
) -> None:
    # A ready.json that does not read, a directory not named as an entry, and a withdrawn entry:
    # none is claimed (claiming could take another session's entry) and none is run.
    root = tmp_path / "bucket"
    job, requests = _job(repository, BENCH)
    spoiled = _enqueue(root, job, requests)
    (spoiled / "ready.json").write_bytes(
        canonical_bytes(
            dict(
                json.loads((spoiled / "ready.json").read_bytes()),
                files={"job.json": sha256_hex(job), "../../runs/x/job.sh": "ab" * 32},
            )
        )
    )
    misnamed = root / "queue" / sha256_hex(job)
    _enqueue(root, job, requests).rename(misnamed)
    withdrawn = _enqueue(root, job, requests).name
    (root / "withdrawn").mkdir()
    (root / "withdrawn" / f"{withdrawn}.json").write_bytes(build_withdrawn(withdrawn, START))
    backend = CountingBackend()
    result = _serve(repository, root, backend)
    assert (result["served"], backend.meshes) == ([], 0)
    assert not (root / "claimed").exists()


def test_a_withdrawn_entry_does_not_hold_back_the_entries_queued_after_it(
    repository: Path, tmp_path: Path
) -> None:
    # The listing passes over a withdrawn entry; were it chosen and then dropped by the claim's
    # re-check, it would stay first in line until its not_after, and so would every entry behind it.
    root = tmp_path / "bucket"
    job, requests = _job(repository, BENCH)
    until = START + timedelta(minutes=10)
    withdrawn = _enqueue(root, job, requests, queued_at=START, not_after=until).name
    (root / "withdrawn").mkdir()
    (root / "withdrawn" / f"{withdrawn}.json").write_bytes(build_withdrawn(withdrawn, START))
    later, later_requests = _job(repository, LANTERN)
    kept = _enqueue(
        root, later, later_requests, queued_at=START + timedelta(seconds=1), not_after=until
    ).name
    result = _serve(repository, root)
    assert [entry["entry_id"] for entry in result["served"]] == [kept]
    assert not (root / "claimed" / f"{withdrawn}.json").exists()


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


def test_an_entry_naming_other_models_than_the_session_loaded_is_refused(
    repository: Path, tmp_path: Path
) -> None:
    # A receipt copies the job's components digest, so a job naming other models would have the
    # session's pieces claim models that did not make them.
    root = tmp_path / "bucket"
    other, other_requests = _job(repository, BENCH, components="5b" * 32)
    _enqueue(root, other, other_requests)
    backend = CountingBackend()
    _serve(repository, root, backend)
    assert "other models than this session loaded" in _done(root, other)["refused"]
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
    assert not (root / "claimed" / f"{_entry(job)}.json").exists()


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
    # The staged job.sh runs only as the digest of this tree's own, pinned on the command.
    tree_script = sha256_hex(nebius.JOB_SCRIPT.read_bytes())
    assert f"JOB_SCRIPT_SHA256={tree_script}" in command
    assert command[command.index("--args") + 1] == f"-c '{nebius.loader_script(sha256_hex(raw))}'"
    with pytest.raises(Refused, match="worst case"):
        nebius.submit_arguments(bound_cents=179, **arguments)


def _loader_in(tmp_path: Path, run: str) -> str:
    """The container's loader script with its two machine paths moved under ``tmp_path``."""
    return (
        nebius.loader_script(run)
        .replace("/mnt/data", str(tmp_path / "mount"))
        .replace("/opt/job.sh", str(tmp_path / "disk" / "job.sh"))
    )


def test_the_container_runs_the_staged_job_script_only_as_the_pinned_digest(
    tmp_path: Path,
) -> None:
    run = "ab" * 32
    staged = tmp_path / "mount" / "runs" / run / "job.sh"
    staged.parent.mkdir(parents=True)
    (tmp_path / "disk").mkdir()
    ran = tmp_path / "ran"
    staged.write_text(f"echo ran > {ran}\n")
    digest = sha256_hex(staged.read_bytes())
    script = _loader_in(tmp_path, run)
    # The container's image has coreutils' sha256sum; a machine without it gets a stand-in that
    # prints the same "<digest>  <path>" line.
    path = "/usr/bin:/bin"
    if shutil.which("sha256sum", path=path) is None:
        shims = tmp_path / "shims"
        shims.mkdir()
        (shims / "sha256sum").write_text('#!/bin/sh\nexec shasum -a 256 "$@"\n')
        (shims / "sha256sum").chmod(0o755)
        path = f"{shims}:{path}"
    good = subprocess.run(
        ["sh", "-c", script], env={"JOB_SCRIPT_SHA256": digest, "PATH": path},
        capture_output=True, check=False,
    )  # fmt: skip
    assert good.returncode == 0 and ran.read_text() == "ran\n"
    ran.unlink()
    # Anyone who can write the bucket can rewrite the staged script; it is then never run.
    staged.write_text(f"echo other > {ran}\n")
    bad = subprocess.run(
        ["sh", "-c", script], env={"JOB_SCRIPT_SHA256": digest, "PATH": path},
        capture_output=True, check=False,
    )  # fmt: skip
    assert bad.returncode != 0 and not ran.exists()


def test_the_job_script_checks_and_uses_local_copies_of_what_it_trusts() -> None:
    lines = nebius.JOB_SCRIPT.read_text().splitlines()
    trusted = ('"$run/code.tar"', '"$run/session.json"', '"$run/job.json"')
    uses = [line.strip() for line in lines if any(name in line for name in trusted)]
    assert uses == [
        'cp "$run/code.tar" "$stage/code.tar"',
        'cp "$run/session.json" "$stage/session.json"',
        'cp "$run/job.json" "$stage/job.json"',
    ]
    assert 'test "$(sha256sum "$stage/job.json" | cut -c1-64)" = "$JOB"' in [
        line.strip() for line in lines
    ]
    assert 'test "$(sha256sum "$stage/code.tar" | cut -c1-64)" = "$CODE_SHA256"' in [
        line.strip() for line in lines
    ]
    assert 'test "$(sha256sum "$stage/session.json" | cut -c1-64)" = "$JOB"' in [
        line.strip() for line in lines
    ]
