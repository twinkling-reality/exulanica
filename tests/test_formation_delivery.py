"""How the formation stream reaches a client: what it holds, when it lets go, and how it resumes.

What the projection means is :mod:`tests.test_formation_stream`'s subject. These hold the
delivery around it, over raw ASGI so several streams can be open at once:

*   **An open stream holds no request thread and no connection between polls**, so liveness, small
    reads and dozens of streams share one process.
*   **A client that leaves gives its place back** within one poll.
*   **A resume continues exactly**: split anywhere, the parts are the whole, with no id twice.
*   **Only a token the stream issued resumes it**; its terminal id resumes to nothing.
*   **A held lock delays events without ending the stream**, and persistent failure ends it with a
    reconnection hint rather than a terminal event.
"""

from __future__ import annotations

import uuid

import anyio
import anyio.to_thread
import pytest
from exulanica.api.admission import STREAMS
from exulanica.api.routes import formation

from asgi_requests import Exchange
from capacity_support import FIRST_TOKEN, SECOND_TOKEN, auth, serve

pytestmark = pytest.mark.postgres


@pytest.fixture
def served(tmp_path, repository, spine_schema, monkeypatch):
    return serve(tmp_path, repository, spine_schema, monkeypatch)


@pytest.fixture
def quick(monkeypatch):
    """Polls every 50 ms, so a test waits for a few polls rather than a few seconds."""
    monkeypatch.setattr(formation, "_POLL_SECONDS", 0.05)


def _stream(app, batch, *, token=FIRST_TOKEN, since=None, last_event_id=None) -> Exchange:
    headers = auth(token)
    if last_event_id is not None:
        headers.append((b"last-event-id", last_event_id.encode()))
    query = f"since={since}" if since is not None else ""
    return Exchange(app, "GET", f"/formation/{batch}", query=query, headers=headers)


async def _until(condition, timeout: float = 10.0) -> None:
    with anyio.fail_after(timeout):
        while not condition():
            await anyio.sleep(0.01)


# -- what an open stream holds ----------------------------------------------------------------


def test_open_streams_hold_no_request_thread_and_no_connection_between_polls(served, quick):
    app = served.app(streams=64, workspace_streams=64)
    batch = served.upload(app)["batch_id"]  # not drained: the batch is running, streams stay open
    streams = [_stream(app, batch) for _ in range(48)]
    small = Exchange(app, "GET", "/formation", headers=auth(FIRST_TOKEN))
    live = Exchange(app, "GET", "/healthz")
    seen: dict[str, list[int]] = {"borrowed": [], "backends": []}

    async def main() -> None:
        limiter = anyio.to_thread.current_default_thread_limiter()
        baseline = await anyio.to_thread.run_sync(served.backends)
        async with anyio.create_task_group() as group:
            for stream in streams:
                group.start_soon(stream.run)
            await _until(lambda: all(stream.started.is_set() for stream in streams))
            for _ in range(10):
                seen["borrowed"].append(limiter.borrowed_tokens)
                seen["backends"].append(await anyio.to_thread.run_sync(served.backends) - baseline)
                await anyio.sleep(0.03)
            with anyio.fail_after(5):
                await small.run()
                await live.run()
            for stream in streams:
                stream.leave()

    anyio.run(main)
    assert {stream.status for stream in streams} == {200}
    assert (small.status, live.status) == (200, 200)
    # 48 open streams: at most the pollers' connections at once, and no request thread held
    # (the one borrowed at a sample is the sampler's own backends count).
    assert max(seen["backends"]) <= formation.STREAM_POLLERS + 1, seen
    assert max(seen["borrowed"]) <= 1, seen
    assert app.state.admission.snapshot()["classes"][STREAMS]["in_flight"] == 0


def test_a_client_that_leaves_gives_its_place_back_within_one_poll(served, quick):
    app = served.app()
    batch = served.upload(app)["batch_id"]
    stream = _stream(app, batch)
    released_after: list[float] = []

    async def main() -> None:
        with anyio.fail_after(10):
            await watch()

    async def watch() -> None:
        async with anyio.create_task_group() as group:
            group.start_soon(stream.run)
            await stream.started.wait()
            counts = app.state.admission.snapshot
            assert counts()["classes"][STREAMS]["in_flight"] == 1
            started = anyio.current_time()
            stream.leave()
            await _until(lambda: counts()["classes"][STREAMS]["in_flight"] == 0)
            released_after.append(anyio.current_time() - started)

    anyio.run(main)
    assert released_after[0] < 1.0, released_after


# -- resuming ---------------------------------------------------------------------------------


def test_a_stream_resumed_anywhere_tells_the_same_story_with_no_id_twice(served):
    app = served.app()
    batch = served.upload(app, count=3)["batch_id"]
    served.drain()
    whole = _stream(app, batch)
    anyio.run(whole.run)
    frames = whole.frames()
    ids = [frame["eventId"] for frame in frames]
    assert len(ids) == len(set(ids)) >= 4
    assert frames[-1]["stageIndex"] == len(formation.FORMATION_STAGES)
    for cut in range(1, len(frames)):
        rest = _stream(app, batch, since=ids[cut - 1])
        anyio.run(rest.run)
        assert frames[:cut] + rest.frames() == frames, cut
    # The header an EventSource sends wins over the query, and resumes the same way.
    header = _stream(app, batch, since="received", last_event_id=ids[1])
    anyio.run(header.run)
    assert header.frames() == frames[2:]


def test_resuming_from_the_terminal_event_sends_nothing(served):
    app = served.app()
    batch = served.upload(app)["batch_id"]
    served.drain()
    whole = _stream(app, batch)
    anyio.run(whole.run)
    terminal = whole.frames()[-1]["eventId"]
    assert terminal.startswith(f"batch:{batch}:")
    after = _stream(app, batch, since=terminal)
    anyio.run(after.run)
    assert after.status == 200
    assert after.text == ""


@pytest.mark.parametrize(
    "token",
    [
        "not-a-token",
        "batch:{other}:succeeded",
        "batch:{batch}:partial",
        "batch:{batch}:running",
    ],
)
def test_a_token_the_stream_did_not_issue_is_refused_before_a_stream_opens(served, token):
    app = served.app()
    batch = served.upload(app)["batch_id"]
    served.drain()
    exchange = _stream(app, batch, since=token.format(batch=batch, other=uuid.uuid4()))
    anyio.run(exchange.run)
    assert exchange.status == 422
    assert exchange.json()["code"] == "invalid_resume_token"
    # An unknown event id is a position, not a refusal: whatever follows it.
    unknown = _stream(app, batch, since=str(uuid.uuid4()))
    anyio.run(unknown.run)
    assert unknown.status == 200


def test_a_batch_in_another_workspace_is_not_found_whatever_the_token(served):
    app = served.app()
    batch = served.upload(app)["batch_id"]
    served.drain()
    not_found = {"code": "unknown_reference", "detail": "no such intake batch"}
    for since in (None, "received", "not-a-token", f"batch:{batch}:succeeded"):
        exchange = _stream(app, batch, token=SECOND_TOKEN, since=since)
        anyio.run(exchange.run)
        # A malformed token is refused from the token alone, before the batch is looked up, so
        # the answer cannot depend on whether the batch exists.
        expected = 422 if since == "not-a-token" else 404
        assert exchange.status == expected, (since, exchange.text)
        if expected == 404:
            assert exchange.json() == not_found, since
    # A batch that never existed is answered exactly as another workspace's is.
    never = _stream(app, str(uuid.uuid4()))
    anyio.run(never.run)
    assert (never.status, never.json()) == (404, not_found)


# -- when the ledger cannot be read -----------------------------------------------------------


def test_a_held_lock_delays_events_and_the_stream_carries_on(served, quick, monkeypatch):
    monkeypatch.setattr(formation, "_POLL_TIMEOUT_MS", 150)
    app = served.app()
    batch = served.upload(app)["batch_id"]
    stream = _stream(app, batch)

    async def main() -> None:
        with anyio.fail_after(20):
            await watch()

    async def watch() -> None:
        async with anyio.create_task_group() as group:
            group.start_soon(stream.run)
            await _until(lambda: len(stream.frames()) >= 1)
            await anyio.to_thread.run_sync(_hold_lock, served, 0.25)
            await anyio.to_thread.run_sync(served.drain)
            await stream.done.wait()

    anyio.run(main)
    assert stream.frames()[-1]["stageIndex"] == len(formation.FORMATION_STAGES)
    assert app.state.admission.snapshot()["stream_poll_failures"] >= 1


def test_persistent_poll_failure_ends_the_stream_with_a_reconnection_hint(
    served, quick, monkeypatch
):
    monkeypatch.setattr(formation, "_POLL_TIMEOUT_MS", 100)
    app = served.app()
    batch = served.upload(app)["batch_id"]
    stream = _stream(app, batch)

    async def main() -> None:
        async with anyio.create_task_group() as group:
            group.start_soon(stream.run)
            await _until(lambda: len(stream.frames()) >= 1)
            group.start_soon(anyio.to_thread.run_sync, _hold_lock, served, 2.0)
            with anyio.fail_after(10):
                await stream.done.wait()

    anyio.run(main)
    assert stream.text.endswith("retry: 5000\n\n")
    assert all(frame["stageIndex"] < len(formation.FORMATION_STAGES) for frame in stream.frames())
    assert app.state.admission.snapshot()["stream_poll_failures"] >= formation.FAILED_POLLS


def test_a_stream_at_its_time_cap_ends_with_a_reconnection_hint(served, quick, monkeypatch):
    monkeypatch.setattr(formation, "_MAX_SECONDS", 0.2)
    app = served.app()
    batch = served.upload(app)["batch_id"]
    stream = _stream(app, batch)

    async def main() -> None:
        with anyio.fail_after(10):
            await stream.run()

    anyio.run(main)
    assert stream.status == 200
    assert stream.text.endswith("retry: 5000\n\n")


def _hold_lock(served, seconds: float) -> None:
    """Hold ``intake_batch`` exclusively for ``seconds``, as a long migration or repair would."""
    import time

    import psycopg

    with psycopg.connect(served.database.url) as connection, connection.transaction():
        connection.execute("lock table intake_batch in access exclusive mode")
        time.sleep(seconds)
