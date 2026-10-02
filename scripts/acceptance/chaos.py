#!/usr/bin/env python3
"""The J2 acceptance driver: the formation stream and the derivative queue under faults.

    python3 scripts/acceptance/chaos.py run --worktree PATH --out DIR

``run`` checks row J2 against the stack ``launch.py up`` started for ``--worktree`` with
``--workspaces 2`` and its in-process derivative worker. Every fault is made from outside the
product, as an operator or a network would make it:

- a stream read to its end, then resumed from every event id it sent, from its terminal id and by
  ``Last-Event-ID``; a token it never sent, by shape or by value, refused 422 before a stream opens;
- another workspace asking for the batch, its stream or its job: 404 ``unknown_reference``, and
  nothing of the first workspace in its own capacity read;
- a table lock the stream's reads wait on, held briefly (the stream carries on) and past the poll
  bound (the stream ends with ``retry:`` and no terminal event, and resuming completes it);
- a client that leaves abruptly, and an upload cancelled part way: each place is given back;
- the derivative worker killed while it holds a job, by restarting the API it runs in mid-stream:
  the job is reclaimed when its lease lapses and the resumed stream reaches the same terminal
  phase, with no event id twice and no duplicated output;
- R1's lane tests at ``-n 2`` on a private PostgreSQL server.

- on a stack started with ``--database-latency``, a batch uploaded and read to its end while the
  latency proxy holds every chunk between the API and PostgreSQL ``LATENCY_MS`` each way: the
  same terminal phase as the reference, no id twice and as many outputs. On a stack without the
  proxy the row says this arm is not exercised.

Nothing here makes a timing claim; durations are recorded as this fixture's.

The lock is an evidence-side operation through the owner URL the launcher recorded for evidence
reads, and so are the counts of batches and artifacts. Outputs under ``--out``: ``results.json``,
``evidence/`` and ``manifest.json``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses look their module up by name while the class is made.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


FOUNDATION = _load("exulanica_acceptance_foundation", HERE / "foundation.py")
LAUNCH = FOUNDATION.LAUNCH
Row = FOUNDATION.Row
Stack = FOUNDATION.Stack
DRIVER_SHA256_AT_START = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
STATES = ("passed", "failed", "blocked")

#: The table whose reads every formation poll makes and whose writes intake and the worker make.
LEDGER = "pipeline_event"
#: Shorter than a poll's statement bound (5 s): the poll waits and then succeeds.
BRIEF_LOCK_SECONDS = 3
#: Longer than three polls failing at that bound, so the stream gives up and says "retry".
LONG_LOCK_SECONDS = 30
STREAM_SECONDS = 90
#: The worker's lease with no model client is 60 s (exulanica.ingest.worker), then reclaimed.
RECLAIM_SECONDS = 240
WORKER_ATTEMPTS = 3
R1_TESTS = (
    "tests/test_api_admission.py",
    "tests/test_decode_bound.py",
    "tests/test_formation_delivery.py",
    "tests/test_intake_capacity.py",
    "tests/test_intake_upload.py",
    "tests/test_route_permissions.py",
)
#: The artifacts made from one batch's photographs: a job run twice would make more.
OUTPUTS = (
    "select count(*) from artifact a join capture c on c.blob_sha256 = a.source_blob_sha256 "
    "and c.workspace_id = a.workspace_id "
    "where c.capture_id in (select capture_id from pipeline_run where batch_id = %s)"
)
NOT_EXERCISED = (
    "added latency on the database connection: the stack has no proxy between the API and "
    "PostgreSQL to add it (launch.py up --database-latency)"
)
#: The delay the latency arm adds to every chunk in each direction between the API and
#: PostgreSQL, so every query's round trip takes at least twice it; and how long its stream may
#: take, beyond the plain stream's bound, since every one of its polls is slower.
LATENCY_MS = 50
LATENCY_STREAM_SECONDS = 600


# -- the client ------------------------------------------------------------------------------------


class Api:
    def __init__(self, stack: Any, token_file: str) -> None:
        self.port = stack.state["ports"]["api"]
        self.token = stack.token_file(token_file).read_text()

    def connection(self, timeout: float = 30) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)

    def call(self, method: str, path: str) -> tuple[int, Any]:
        connection = self.connection()
        try:
            connection.request(method, path, headers=self.headers())
            response = connection.getresponse()
            raw = response.read()
        finally:
            connection.close()
        try:
            return response.status, json.loads(raw or b"null")
        except json.JSONDecodeError:
            return response.status, raw[:200].decode(errors="replace")

    def headers(self, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json", **extra}

    def upload(self, photo: bytes) -> tuple[int, Any]:
        body, boundary = multipart(photo)
        connection = self.connection(120)
        try:
            connection.request(
                "POST",
                "/intake",
                body=body,
                headers=self.headers(
                    **{"Content-Type": f"multipart/form-data; boundary={boundary}"}
                ),
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read() or b"null")
        finally:
            connection.close()

    def capacity(self) -> dict[str, Any]:
        status, body = self.call("GET", "/operations/capacity")
        return body if status == 200 and isinstance(body, dict) else {}


def multipart(photo: bytes) -> tuple[bytes, str]:
    boundary = f"q10-{uuid.uuid4().hex}"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="j2.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        + photo
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return body, boundary


def photograph(seed: int) -> bytes:
    """A small synthetic JPEG of its own size: development data, no person, no place."""
    from PIL import Image

    image = Image.new("RGB", (96 + seed, 64), ((seed * 41) % 256, 120, (seed * 89) % 256))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


class Stream:
    """One formation stream read line by line, so a test can leave it at any moment."""

    def __init__(self, api: Api, batch: str, *, since: str | None = None, last: str | None = None):
        self.api, self.batch, self.since, self.last = api, batch, since, last
        self.status: int | None = None
        self.body: Any = None
        self.ids: list[str] = []
        self.phases: list[str] = []
        self.retry = False
        self.ended = False
        self.error: str | None = None
        self.connection: http.client.HTTPConnection | None = None
        self.opened = threading.Event()

    def read(self, seconds: float = STREAM_SECONDS) -> Stream:
        path = f"/formation/{self.batch}" + (f"?since={self.since}" if self.since else "")
        headers = self.api.headers(Accept="text/event-stream")
        if self.last is not None:
            headers["Last-Event-ID"] = self.last
        self.connection = self.api.connection(seconds)
        try:
            self.connection.request("GET", path, headers=headers)
            response = self.connection.getresponse()
            self.status = response.status
            self.opened.set()
            if response.status != 200:
                self.body = json.loads(response.read() or b"null")
                return self
            event_id = None
            while True:
                raw = response.fp.readline()
                if not raw:
                    self.ended = True
                    return self
                line = raw.decode().rstrip("\r\n")
                if line.startswith("id: "):
                    event_id = line[4:]
                elif line.startswith("data: ") and event_id is not None:
                    self.ids.append(event_id)
                    self.phases.append(json.loads(line[6:]).get("phase"))
                    event_id = None
                elif line.startswith("retry:"):
                    self.retry = True
        except (OSError, http.client.HTTPException, ValueError) as failed:
            self.error = type(failed).__name__
            self.opened.set()
            return self

    def leave(self) -> None:
        """Close the socket under the reader, as a client that goes away does."""
        if self.connection is not None and self.connection.sock is not None:
            self.connection.sock.shutdown(2)
            self.connection.sock.close()

    def background(self, seconds: float = STREAM_SECONDS) -> threading.Thread:
        thread = threading.Thread(target=self.read, args=(seconds,), daemon=True)
        thread.start()
        return thread

    @property
    def terminal(self) -> str | None:
        return self.ids[-1] if self.ids and self.ids[-1].startswith("batch:") else None


# -- evidence-side operations ----------------------------------------------------------------------


class Owner:
    """The owner connection the launcher records for evidence reads, and the locks made with it."""

    def __init__(self, stack: Any) -> None:
        import psycopg

        self.url = stack.state["database"]["owner_url_for_evidence_reads"]
        self.locked = psycopg.connect(self.url)

    def lock(self, mode: str = "access exclusive") -> float:
        """Lock the ledger; seconds it took. ``access exclusive`` makes its readers wait (a
        stream's polls); ``share`` makes only its writers wait (intake and the worker's stages)."""
        started = time.monotonic()
        self.locked.execute(f"lock table {LEDGER} in {mode} mode")
        return time.monotonic() - started

    def release(self) -> None:
        self.locked.commit()

    def count(self, statement: str, *values: object) -> int:
        import psycopg

        with psycopg.connect(self.url) as connection:
            row = connection.execute(statement, values).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        self.locked.rollback()
        self.locked.close()


def until(condition: Callable[[], bool], seconds: float, step: float = 0.5) -> bool:
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        if condition():
            return True
        time.sleep(step)
    return False


def kill_api(stack: Any) -> dict[str, Any]:
    """SIGKILL the API this run started: only its recorded process, checked by its marker and
    port, never anything else (as foundation.kill_second_api does for the second API)."""
    pid = stack.state["pids"]["api"]
    command = LAUNCH.command_of(pid)
    if LAUNCH.API_MARKER not in command or str(stack.state["ports"]["api"]) not in command:
        raise SystemExit(f"pid {pid} is not this run's API: {command[:120]}")
    os.killpg(pid, signal.SIGKILL)
    return {"pid": pid, "signal": "SIGKILL", "at": dt.datetime.now(dt.UTC).isoformat()}


def in_flight(api: Api, kind: str) -> int:
    return int(api.capacity().get("classes", {}).get(kind, {}).get("in_flight", -1))


# -- the checks ------------------------------------------------------------------------------------


def reference(api: Api, out: Path) -> dict[str, Any]:
    """One batch read whole: what every later check compares with."""
    status, answer = api.upload(photograph(1))
    batch = answer.get("batch_id") if isinstance(answer, dict) else None
    stream = Stream(api, batch).read() if batch else None
    return {
        "upload": status,
        "batch": batch,
        "job": answer.get("queued_job_id") if isinstance(answer, dict) else None,
        "ids": stream.ids if stream else [],
        "phases": stream.phases if stream else [],
        "terminal": stream.terminal if stream else None,
        "retry": stream.retry if stream else None,
    }


def resumes(row: Row, api: Api, first: dict[str, Any]) -> None:
    ids, batch = first["ids"], first["batch"]
    split = []
    for index, event in enumerate(ids[:-1]):
        resumed = Stream(api, batch, since=event).read()
        split.append([event, resumed.status, resumed.ids == ids[index + 1 :]])
    terminal = Stream(api, batch, since=first["terminal"]).read()
    header = Stream(api, batch, last=ids[0]).read() if ids else None
    shaped = Stream(api, batch, since="not-a-token").read()
    unissued = Stream(api, batch, since=str(uuid.uuid4())).read()
    row.observed["resume"] = {
        "from_each_id": split,
        "from_terminal": [terminal.status, terminal.ids, terminal.ended],
        "last_event_id": [header.status, header.ids == ids[1:]] if header else None,
        "not_a_token": [shaped.status, (shaped.body or {}).get("code")],
        "unissued_uuid": [unissued.status, unissued.ids],
    }
    row.expect(all(status == 200 and same for _, status, same in split), "a resume differed")
    row.expect(terminal.status == 200 and not terminal.ids, "the terminal id resumed to events")
    row.expect(bool(header) and header.status == 200 and header.ids == ids[1:], "Last-Event-ID")
    row.expect(
        shaped.status == 422 and (shaped.body or {}).get("code") == "invalid_resume_token",
        f"a malformed token answered {shaped.status}",
    )
    # An event id the stream never sent is a position, not a refusal (R1's
    # test_a_token_that_cannot_be_a_position_is_refused_before_a_stream_opens): whatever follows.
    row.expect(
        unissued.status == 200
        and set(unissued.ids) <= set(ids)
        and len(unissued.ids) == len(set(unissued.ids)),
        f"an unissued id answered {unissued.status} with {unissued.ids}",
    )


def other_workspace(row: Row, api: Api, other: Api, first: dict[str, Any]) -> None:
    batch, job = first["batch"], first["job"]
    plain = Stream(other, batch).read()
    resumed = Stream(other, batch, since=first["terminal"]).read()
    job_status, job_body = other.call("GET", f"/operations/derivative-jobs/{job}")
    capacity = json.dumps(other.capacity())
    row.observed["other_workspace"] = {
        "stream": [plain.status, (plain.body or {}).get("code")],
        "resumed": [resumed.status, (resumed.body or {}).get("code")],
        "job": [job_status, (job_body or {}).get("code") if isinstance(job_body, dict) else None],
        "first_workspace_ids_in_its_capacity": batch in capacity or job in capacity,
    }
    for name, (status, code) in (
        ("stream", row.observed["other_workspace"]["stream"]),
        ("resumed stream", row.observed["other_workspace"]["resumed"]),
        ("job", row.observed["other_workspace"]["job"]),
    ):
        row.expect(status == 404 and code == "unknown_reference", f"the other {name}: {status}")
    row.expect(not row.observed["other_workspace"]["first_workspace_ids_in_its_capacity"], "leak")


def held_lock(row: Row, api: Api, owner: Owner, first: dict[str, Any]) -> None:
    ids, batch = first["ids"], first["batch"]
    failures_before = api.capacity().get("stream_poll_failures", 0)
    owner.lock()
    brief = Stream(api, batch)
    thread = brief.background()
    time.sleep(BRIEF_LOCK_SECONDS)
    owner.release()
    thread.join(STREAM_SECONDS)
    owner.lock()
    started = time.monotonic()
    long = Stream(api, batch, since=ids[0])
    long_thread = long.background()
    long_thread.join(LONG_LOCK_SECONDS)
    ended_after = round(time.monotonic() - started, 1)
    owner.release()
    rest = Stream(api, batch, since=(long.ids or ids[:1])[-1]).read()
    failures_after = api.capacity().get("stream_poll_failures", 0)
    row.observed["held_lock"] = {
        "brief": {"ids_equal": brief.ids == ids, "retry": brief.retry},
        "long": {
            "ended_within_lock": not long_thread.is_alive(),
            "seconds_this_fixture": ended_after,
            "retry": long.retry,
            "terminal": long.terminal,
            "ids": long.ids,
        },
        "resumed_after_release": rest.ids,
        "poll_failures": [failures_before, failures_after],
    }
    row.expect(brief.ids == ids and not brief.retry, "a brief lock changed what the stream sent")
    row.expect(
        not long_thread.is_alive() and long.retry and long.terminal is None,
        "a lock past the poll bound did not end the stream with retry and no terminal",
    )
    whole = long.ids + rest.ids
    row.expect(
        [ids[0], *whole] == ids or whole == ids,
        f"resuming after the lock told another story {whole}",
    )
    row.expect(failures_after > failures_before, "no failed poll was counted")


def leaving(row: Row, api: Api, owner: Owner, first: dict[str, Any]) -> None:
    """A client that leaves while its stream waits gives its place back."""
    before = in_flight(api, "streams")
    owner.lock()
    stream = Stream(api, first["batch"])
    stream.background()
    held = until(lambda: in_flight(api, "streams") > before, 10)
    stream.leave()
    given_back = until(lambda: in_flight(api, "streams") == before, 15)
    owner.release()
    row.observed["leaving"] = {"held": held, "given_back": given_back, "baseline": before}
    row.expect(held and given_back, "a stream's place was not given back after its client left")


def cancelled_upload(row: Row, api: Api, owner: Owner) -> None:
    batches = "select count(*) from intake_batch"
    before = owner.count(batches)
    body, boundary = multipart(photograph(2))
    connection = api.connection(30)
    connection.putrequest("POST", "/intake")
    for key, value in api.headers(
        **{"Content-Type": f"multipart/form-data; boundary={boundary}"}
    ).items():
        connection.putheader(key, value)
    connection.putheader("Content-Length", str(len(body)))
    connection.endheaders()
    connection.send(body[: len(body) // 3])
    held = until(lambda: in_flight(api, "uploads") > 0, 10)
    connection.sock.shutdown(2)
    connection.close()
    given_back = until(lambda: in_flight(api, "uploads") == 0, 30)
    after = owner.count(batches)
    status, _ = api.upload(photograph(3))
    row.observed["cancelled_upload"] = {
        "held": held,
        "given_back": given_back,
        "batches": [before, after],
        "next_upload": status,
    }
    row.expect(given_back, "a cancelled upload kept its place")
    row.expect(after == before, "a cancelled upload opened a batch")
    row.expect(status == 202, f"the next upload answered {status}")


def large_photograph(seed: int) -> bytes:
    """A 2400x1600 JPEG of noise, so the derivative job takes long enough to be stopped in."""
    import random

    from PIL import Image

    generator = random.Random(seed)
    image = Image.frombytes("RGB", (2400, 1600), generator.randbytes(2400 * 1600 * 3))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=95)
    return buffer.getvalue()


def worker_killed(row: Row, stack: Any, api: Api, owner: Owner, first: dict[str, Any]) -> None:
    """Restart the API, and the in-process worker with it, while that worker holds a job.

    A graceful stop lets the worker finish its job, so the API this run started is killed
    (SIGKILL, its recorded process alone, checked by marker and port) as soon as the job is
    claimed, then started again by the launcher. The job read afterwards says whether the worker
    was stopped in it: claimed once, not done. A job finished first is tried again.
    """
    attempt: dict[str, Any] = {}
    for seed in range(10, 10 + WORKER_ATTEMPTS):
        status, answer = api.upload(large_photograph(seed))
        job, batch = answer.get("queued_job_id"), answer.get("batch_id")
        stream = Stream(api, batch)
        stream_thread = stream.background()
        stream.opened.wait(10)
        claimed = until(lambda job=job: _job(api, job).get("attempts", 0) >= 1, 5, step=0.05)
        killed = kill_api(stack) if claimed else None
        restarted = stack.restart_api()
        stream_thread.join(30)
        state = _job(api, job)
        attempt = {
            "upload": status,
            "job": job,
            "batch": batch,
            "killed": killed,
            "restart": {k: restarted.get(k) for k in ("at", "pid", "healthz")},
            "job_after_restart": state,
            "stream_before_restart": {"ids": stream.ids, "error": stream.error},
            "tries": seed - 9,
        }
        if state.get("attempts") == 1 and state.get("state") != "done":
            break
    else:
        row.failures.append("no restart landed while the worker held a job")
        row.observed["worker_killed"] = attempt
        return
    done = until(lambda: _job(api, attempt["job"]).get("state") == "done", RECLAIM_SECONDS)
    final = _job(api, attempt["job"])
    before = attempt["stream_before_restart"]["ids"]
    resumed = Stream(api, attempt["batch"], since=before[-1] if before else None).read()
    whole = before + resumed.ids
    outputs = owner.count(OUTPUTS, attempt["batch"])
    reference_outputs = owner.count(OUTPUTS, first["batch"])
    attempt |= {
        "job_after": final,
        "resumed_ids": resumed.ids,
        "phases": resumed.phases,
        "outputs": [outputs, reference_outputs],
    }
    row.observed["worker_killed"] = attempt
    row.expect(done and final.get("attempts", 0) >= 2, f"the job was not reclaimed: {final}")
    row.expect(len(whole) == len(set(whole)), "an event id came twice across the restart")
    row.expect(
        resumed.terminal is not None and resumed.phases[-1:] == first["phases"][-1:],
        "the resumed stream did not reach the reference's terminal phase",
    )
    row.expect(outputs == reference_outputs, f"outputs {outputs} against {reference_outputs}")


def added_latency(row: Row, stack: Any, api: Api, owner: Owner, first: dict[str, Any]) -> None:
    """With the API's database connections through the latency proxy, a batch uploaded while
    every chunk is held ``LATENCY_MS`` reads to the reference's terminal phase, with no id twice
    and as many outputs as the reference; the delay is then taken off again."""
    proxy = stack.state["database_latency"]
    delay_file = Path(proxy["delay_file"])
    log = Path(stack.state["run_dir"]) / "logs" / "latency-proxy.log"
    delay_file.write_text(str(LATENCY_MS))
    try:
        until(lambda: f'"milliseconds": {LATENCY_MS}' in log.read_text(errors="replace"), 30)
        started = time.monotonic()
        status, answer = api.upload(photograph(40))
        batch = answer.get("batch_id") if isinstance(answer, dict) else None
        stream = Stream(api, batch).read(LATENCY_STREAM_SECONDS) if batch else None
        seconds = round(time.monotonic() - started, 1)
    finally:
        delay_file.write_text("0")
    applied = f'"milliseconds": {LATENCY_MS}' in log.read_text(errors="replace")
    ids = stream.ids if stream else []
    outputs = owner.count(OUTPUTS, batch) if batch else -1
    reference_outputs = owner.count(OUTPUTS, first["batch"])
    row.expect(applied, f"the proxy never applied {LATENCY_MS} ms")
    row.expect(status == 202, f"the upload under latency answered {status}")
    row.expect(
        stream is not None
        and stream.terminal is not None
        and stream.phases[-1:] == first["phases"][-1:],
        f"under latency the stream ended in phase {stream.phases[-1:] if stream else None}, the "
        f"reference in {first['phases'][-1:]}",
    )
    row.expect(len(ids) == len(set(ids)), "under latency the stream sent an id twice")
    row.expect(
        outputs == reference_outputs,
        f"under latency the batch made {outputs} outputs, the reference {reference_outputs}",
    )
    row.observed["added_latency"] = {
        "milliseconds_each_way_per_chunk": LATENCY_MS,
        "applied": applied,
        "upload": status,
        "batch": batch,
        "terminal": stream.terminal if stream else None,
        "phase": stream.phases[-1:] if stream else None,
        "retry": stream.retry if stream else None,
        "events": len(ids),
        "outputs": [outputs, reference_outputs],
        "fixture_seconds": seconds,
    }


def _job(api: Api, job: str) -> dict[str, Any]:
    status, body = api.call("GET", f"/operations/derivative-jobs/{job}")
    return body if status == 200 and isinstance(body, dict) else {}


def lane_tests(row: Row, out: Path, worktree: Path) -> None:
    completed = subprocess.run(
        [
            str(worktree / ".venv" / "bin" / "python"), "-m", "pytest", "-p",
            "no:cacheprovider", "-n", "2", *R1_TESTS,
        ],
        cwd=worktree,
        env={
            **LAUNCH.clean_environment(),
            "EXULANICA_TEST_POSTGRES": "private",
            "EXULANICA_REQUIRE_POSTGRES": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    (out / "evidence" / "r1-lane-tests.txt").write_text(completed.stdout + completed.stderr)
    counts = [
        line for line in completed.stdout.splitlines() if " passed" in line or " failed" in line
    ]
    tail = counts[-1:] or [""]
    row.observed["lane_tests"] = {
        "files": list(R1_TESTS),
        "exit": completed.returncode,
        "summary": tail[0],
    }
    row.expect(completed.returncode == 0, f"R1's lane tests exited {completed.returncode}")


# -- the command -----------------------------------------------------------------------------------


def run(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if (
        stack.state.get("derivative_worker") != "in-process"
        or not stack.token_file("token-2").exists()
    ):
        raise SystemExit(
            "J2 needs a stack with its in-process derivative worker and --workspaces 2"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    latency = isinstance(stack.state.get("database_latency"), dict)
    row = Row(
        "J2",
        "load.chaos",
        "The stream resumes exactly from every id it sent and to nothing from its terminal id, "
        "refuses a malformed token with 422 invalid_resume_token before a stream opens and treats "
        "an unknown event id as a position, "
        "and is 404 unknown_reference to another workspace; a lock its reads wait on delays it "
        "briefly without change, and past the poll bound ends it with retry and no terminal, after "
        "which resuming completes it; a client that leaves and a cancelled upload give their "
        "places back with no batch; a worker killed mid-job by an API restart is reclaimed after "
        "its lease and the resumed stream reaches the same terminal phase with no id twice and no "
        "duplicated output; R1's lane tests pass. "
        + (
            f"With every chunk between the API and PostgreSQL held {LATENCY_MS} ms each way, a "
            "batch reads to the reference's terminal phase with no id twice and as many outputs."
            if latency
            else "Added database latency is not exercised."
        ),
    )
    api, other = Api(stack, "token"), Api(stack, "token-2")
    owner = Owner(stack)
    try:
        first = reference(api, out)
        row.observed["reference"] = first
        if row.expect(first["terminal"] is not None, "the reference stream reached no terminal"):
            resumes(row, api, first)
            other_workspace(row, api, other, first)
            held_lock(row, api, owner, first)
            leaving(row, api, owner, first)
            cancelled_upload(row, api, owner)
            worker_killed(row, stack, Api(stack, "token"), owner, first)
            if latency:
                added_latency(row, stack, Api(stack, "token"), owner, first)
    finally:
        owner.close()
    lane_tests(row, out, worktree)
    row.observed["not_exercised"] = [] if latency else [NOT_EXERCISED]
    row.close()
    results = {
        "profile": "q10-chaos-acceptance-results/v1",
        "candidate": stack.state["tree"],
        "launcher_run": stack.state["run_id"],
        "started_at": started,
        "finished_at": dt.datetime.now(dt.UTC).isoformat(),
        "timing_claims": False,
        "rows": [row.document()],
        "counts": {state: int(row.status == state) for state in STATES},
    }
    (out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True, default=str))
    manifest = {
        "driver": str(Path(__file__).resolve().relative_to(REPOSITORY)),
        "driver_sha256": DRIVER_SHA256_AT_START,
        "driver_changed_during_run": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        != DRIVER_SHA256_AT_START,
        "foundation_sha256": hashlib.sha256((HERE / "foundation.py").read_bytes()).hexdigest(),
        "launcher_sha256": hashlib.sha256((HERE / "launch.py").read_bytes()).hexdigest(),
        "command": ["chaos.py", *sys.argv[1:]],
        "launcher_state": {k: v for k, v in stack.state.items() if k != "database"},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str))
    print(f"{row.row:6} {row.status:8} {'; '.join(row.failures or row.blocked_by)}")
    return 0 if row.status != "failed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    started = commands.add_parser("run", help="row J2 against the checkout's running stack")
    started.add_argument("--worktree", required=True)
    started.add_argument("--out", required=True)
    started.set_defaults(handler=run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
