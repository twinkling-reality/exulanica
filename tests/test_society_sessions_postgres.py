"""Living sessions against PostgreSQL: opened and closed as receipts of the playback history.

What is shown:

*   a session opens a paused society at the tick and state digest its caller read, and a playing
    one at the minute it is at, with no pause written and a minute in flight cancelled; opening
    sets the society playing in the same transaction, a ``configured`` receipt then a
    ``session_opened`` one;
*   one session is open at a time; the same request opens the same session once; a session that
    closed is never open again;
*   a person's pause closes it (``paused_by_person``), a stop closes it and pauses
    (``stopped_by_person``), and a pause the worker makes for an error closes it with that error's
    reason and no person;
*   the database refuses a session receipt that does not have the session's shape;
*   erasing the society erases its sessions' receipts with the rest of its playback history;
*   the routes open, stop and read sessions in the open world, and refuse a stranger.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.society import StaleSocietyState
from exulanica.world.society_controls import LeaseLost
from exulanica.world.society_erasure import erase_society
from exulanica.world.society_sessions import SessionRefused
from psycopg.errors import CheckViolation

import test_society_controls_postgres as control
from test_society_controls_api import control_api as control_api
from test_society_runtime import runtime_world as runtime_world

pytestmark = pytest.mark.postgres
__all__ = ["control_api", "runtime_world"]

LIMITS = {"wall_seconds": 600, "minutes": 30, "decisions": 10, "usd": "0.25", "calls": 100}


def _open(w, *, request_id=None, revision=0, limits=LIMITS, tick=None, digest=None):
    repo = control.controls(w)
    before = repo.read(w["binding"].version_id)
    return repo.open_session(
        w["binding"].version_id,
        actor=w["session"].actor,
        request_id=request_id or uuid.uuid4(),
        base_revision=revision,
        base_tick=before["current_tick"] if tick is None else tick,
        base_state_sha256=before["state_sha256"] if digest is None else digest,
        limits=limits,
    )


def _kinds(w) -> list[str]:
    return [event["kind"] for event in control.controls(w).events(w["binding"].version_id)][::-1]


def test_a_session_opens_a_paused_society_at_its_pins_and_plays_it_in_one_step(runtime_world):
    w = runtime_world
    control.create(w)
    with pytest.raises(StaleSocietyState):
        _open(w, tick=5)
    with pytest.raises(StaleSocietyState):
        _open(w, digest="0" * 64)
    assert _kinds(w) == []
    request = uuid.uuid4()
    opened = _open(w, request_id=request)
    assert opened["state"] == "open" and opened["closed"] is None
    assert opened["opened"]["limits"]["usd"] == "0.25000000"
    assert opened["opened"]["opened_by"] == str(w["session"].actor)
    assert control.controls(w).read(w["binding"].version_id)["mode"] == "playing"
    assert _kinds(w) == ["configured", "session_opened"]
    # The same request answers the same session; another is refused while one is open.
    assert _open(w, request_id=request, revision=1)["session_id"] == opened["session_id"]
    with pytest.raises(SessionRefused) as refused:
        _open(w, request_id=request, revision=1, limits={**LIMITS, "decisions": 11})
    assert refused.value.code == "session_request_reused"
    with pytest.raises(SessionRefused) as refused:
        _open(w, revision=1)
    assert refused.value.code == "session_already_open"
    assert _kinds(w) == ["configured", "session_opened"]


def test_a_playing_society_opens_at_the_minute_it_is_at_with_no_pause_written(runtime_world):
    w = runtime_world
    control.create(w)
    control.save(w)  # playing, with no session
    repo = control.controls(w)
    vid = w["binding"].version_id
    read = repo.read(vid)
    control.overdue(w)
    repo.execute(control.take_claim(w))  # a minute plays after the caller's read
    now = repo.read(vid)
    assert now["current_tick"] > read["current_tick"]
    count = len(_kinds(w))
    # Another revision is a change the person made in between (a pause, a speed): stale.
    with pytest.raises(StaleSocietyState):
        _open(w, revision=0)
    assert len(_kinds(w)) == count
    # The tick and digest read before that minute open the run at the minute it is at.
    opened = _open(w, revision=1, tick=read["current_tick"], digest=read["state_sha256"])
    assert opened["state"] == "open"
    assert opened["opened"]["start_tick"] == now["current_tick"]
    assert opened["opened"]["start_state_sha256"] == now["state_sha256"]
    assert repo.read(vid)["mode"] == "playing"
    events = repo.events(vid)
    assert [event["kind"] for event in events[:2][::-1]] == ["configured", "session_opened"]
    assert events[1]["mode"] == "playing" and len(events) == count + 2
    assert all(event.get("mode") != "paused" for event in events[:2])


def test_opening_a_playing_society_cancels_a_minute_in_flight(runtime_world):
    w = runtime_world
    control.create(w)
    control.save(w)
    repo = control.controls(w)
    vid = w["binding"].version_id
    before = repo.read(vid)
    control.overdue(w)
    claim = control.take_claim(w)  # a minute claimed and not yet run
    assert claim is not None
    opened = _open(w, revision=1)
    with pytest.raises(LeaseLost):
        repo.execute(claim)
    assert (
        opened["opened"]["start_tick"] == before["current_tick"] == repo.read(vid)["current_tick"]
    )
    assert opened["opened"]["start_state_sha256"] == repo.read(vid)["state_sha256"]


def test_a_stopped_session_stays_closed(runtime_world):
    w = runtime_world
    control.create(w)
    opened = _open(w)
    repo = control.controls(w)
    vid = w["binding"].version_id
    stopped = repo.stop_session(
        vid, actor=w["session"].actor, session_id=uuid.UUID(opened["session_id"])
    )
    assert stopped["state"] == "closed" and stopped["closed"]["reason"] == "stopped_by_person"
    assert stopped["closed"]["closed_by"] == str(w["session"].actor)
    assert repo.read(vid)["mode"] == "paused"
    # Stopping again answers the closed session and writes nothing.
    count = len(_kinds(w))
    again = repo.stop_session(
        vid, actor=w["session"].actor, session_id=uuid.UUID(opened["session_id"])
    )
    assert again == stopped and len(_kinds(w)) == count
    with pytest.raises(SessionRefused) as refused:
        repo.stop_session(vid, actor=w["session"].actor, session_id=uuid.uuid4())
    assert refused.value.code == "session_unknown"
    # A new stretch is a new session.
    later = _open(w, revision=repo.read(vid)["revision"])
    assert later["session_id"] != opened["session_id"]
    assert [one["state"] for one in repo.sessions(vid)] == ["open", "closed"]


def test_a_person_s_pause_closes_the_open_session(runtime_world):
    w = runtime_world
    control.create(w)
    opened = _open(w)
    control.save(w, revision=1, mode="playing", speed=2)  # another speed keeps it open
    assert (
        control.controls(w).session(w["binding"].version_id, uuid.UUID(opened["session_id"]))[
            "state"
        ]
        == "open"
    )
    control.save(w, revision=2, mode="paused")
    closed = control.controls(w).session(w["binding"].version_id, uuid.UUID(opened["session_id"]))
    assert closed["closed"]["reason"] == "paused_by_person"
    assert closed["closed"]["closed_by"] == str(w["session"].actor)
    assert _kinds(w)[-2:] == ["configured", "session_closed"]


def test_a_pause_for_an_error_closes_the_open_session_with_no_person(runtime_world):
    w = runtime_world
    control.create(w)
    opened = _open(w)
    control.overdue(w)
    for _ in range(3):
        assert control.take_claim(w) is not None
        control.expire(w)
    assert control.take_claim(w) is None
    repo = control.controls(w)
    assert repo.read(w["binding"].version_id)["reason"] == "lease_recovery_limit"
    closed = repo.session(w["binding"].version_id, uuid.UUID(opened["session_id"]))
    assert closed["closed"]["reason"] == "lease_recovery_limit"
    assert closed["closed"]["closed_by"] is None
    assert _kinds(w)[-2:] == ["lease_recovery_exhausted", "session_closed"]


def test_the_database_refuses_a_session_receipt_without_the_session_s_shape(runtime_world):
    w = runtime_world
    control.create(w)
    control.save(w, mode="paused")
    repo = control.controls(w)
    society = repo._scope(w["binding"].version_id)
    for kind, details in (
        ("session_opened", {"session_id": str(uuid.uuid4())}),
        ("session_closed", {"session_id": "not-a-uuid", "reason": "stopped_by_person"}),
        # Each field a closing states is held, not only its session's identity.
        (
            "session_closed",
            {"session_id": str(uuid.uuid4()), "end_tick": 1, "end_state_sha256": "0" * 64},
        ),
        (
            "session_closed",
            {"session_id": str(uuid.uuid4()), "reason": "stopped_by_person", "end_tick": 1},
        ),
        (
            "session_opened",
            {
                "session_id": str(uuid.uuid4()),
                "request_id": str(uuid.uuid4()),
                "start_tick": 0,
                "start_state_sha256": "0" * 64,
            },
        ),
        ("session_paused", {}),
    ):
        with pytest.raises(CheckViolation), w["connection"].transaction():
            repo._event(society, kind, details)


def test_erasing_the_society_erases_its_sessions_with_its_playback_history(runtime_world):
    w = runtime_world
    control.create(w)
    _open(w)
    control.save(w, revision=1, mode="paused")
    connection = w["connection"]
    held = connection.execute(
        "select count(*) as n from world_society_control_event where workspace_id=%s "
        "and document->>'kind' in ('session_opened','session_closed')",
        (w["workspace"],),
    ).fetchone()["n"]
    assert held == 2
    erase_society(
        connection,
        w["workspace"],
        w["version"].world_id,
        w["binding"].version_id,
        erased_by=w["session"].actor,
    )
    connection.commit()
    assert (
        connection.execute(
            "select count(*) as n from world_society_control_event where workspace_id=%s",
            (w["workspace"],),
        ).fetchone()["n"]
        == 0
    )


def test_the_routes_open_stop_and_read_sessions_in_the_open_world(runtime_world, control_api):
    w, api = runtime_world, control_api
    control.create(w)
    w["connection"].commit()
    api.client.app.state.society_input_authorizer = w["runtime"].authorize
    base = f"/world/versions/{w['binding'].version_id}/society/control"
    state = api.get(api.in_world(base)).json()
    sessions = api.in_world(base + "/sessions")
    body = {
        "request_id": str(uuid.uuid4()),
        "base_revision": 0,
        "base_tick": state["current_tick"],
        "base_state_sha256": state["state_sha256"],
        "limits": LIMITS,
    }
    opened = api.post(sessions, body)
    assert opened.status_code == 201, opened.text
    session_id = opened.json()["session_id"]
    assert (
        api.post(sessions, {**body, "request_id": str(uuid.uuid4()), "base_revision": 1}).json()[
            "code"
        ]
        == "session_already_open"
    )
    bad = api.post(sessions, {**body, "limits": {**LIMITS, "minutes": 0}})
    assert bad.status_code == 422
    listed = api.get(sessions).json()
    assert [one["session_id"] for one in listed["sessions"]] == [session_id]
    one = api.in_world(base + f"/sessions/{session_id}")
    assert api.get(one).json()["state"] == "open"
    assert api.stranger_get(one).status_code == 404
    stopped = api.post(api.in_world(base + f"/sessions/{session_id}/stop"), {})
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["closed"]["reason"] == "stopped_by_person"
    assert api.get(api.in_world(base)).json()["mode"] == "paused"
    missing = api.get(api.in_world(base + f"/sessions/{uuid.uuid4()}"))
    assert missing.status_code == 404 and missing.json()["code"] == "session_unknown"
