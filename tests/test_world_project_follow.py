"""Following a world: project folders kept current on their own, against a fake World API.

The world is synthetic, served on this machine by a fake that answers GET and refuses every other
method. Project folders are plain local git and time is a fake clock. Nothing reaches GitHub.
"""

import json
import re
import subprocess
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from exulanica.world_package.projects.__main__ import main
from exulanica.world_package.projects.capture import WorldReader, capture
from exulanica.world_package.projects.checkpoint import ProjectError
from exulanica.world_package.projects.follow import (
    FOLLOW_FILE,
    Follower,
    due_session,
    follow_document,
    policy_of,
    read_follow,
)
from exulanica.world_package.projects.history import history_read
from exulanica.world_package.projects.repository import Project, published_part
from exulanica.world_package.projects.watch import Policy

from test_world_project_capture import TOKEN, VERSION, WORLD, World

#: Sessions opened from this instant on are recorded; earlier ones are history.
SINCE = "2026-10-14T00:00:00Z"
SESSIONS = f"/world/versions/{VERSION}/society/control/sessions"
A = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5a"
B = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
OLD = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a50"
LIMITS = {"wall_seconds": 600, "minutes": 60, "decisions": 50, "usd": "0.05", "calls": 100}


class Clock:
    """A fixed day long before the follow commands' own commits, so only checkpoints count."""

    def __init__(self):
        self.now = 1_760_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def world():
    fake = World()
    # The society exists and has had no living session yet: its models are read.
    fake.routes[SESSIONS] = {"sessions": []}
    fake.broken = False

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = fake.answer(self)
            if fake.broken:
                status, body = 500, {"code": "broken"}
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def refuse(self):
            fake.requests.append((self.command, self.path, None))
            self.send_response(405)
            self.end_headers()

        do_POST = do_PUT = do_PATCH = do_DELETE = refuse

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake.url = f"http://localhost:{server.server_address[1]}"
    yield fake
    server.shutdown()
    server.server_close()


@pytest.fixture
def token(tmp_path):
    path = tmp_path / "token"
    path.write_text(TOKEN + "\n", encoding="utf-8")
    return path


def follow(world, token, folder, *extra, expect=0):
    """The person's one command: follow a world into a project folder."""
    arguments = ["follow", str(folder), "--api", world.url, "--token-file", str(token)]
    arguments += ["--world", WORLD, "--version", VERSION, "--project-id", "project:demo", *extra]
    assert main(arguments) == expect
    return folder


def commits(folder):
    return [entry["message"] for entry in Project(folder).history()]


def move(world, x_mm, index=1):
    """Move a placed thing of the fake version (index 1 is the knight, 0 the bench)."""
    things = world.routes[f"/world/versions/{VERSION}"]["things"]
    thing = next(t for t in things if t["thing_id"] == ("bench:1", "knight:1")[index])
    thing["transform"]["x_mm"] = x_mm


def poll(follower, clock, seconds=15):
    clock.now += seconds
    return {outcome["project"]: outcome for outcome in follower.round()}


def session(world, session_id, *, opened_at, start, end=None, asked=()):
    """One living session as the society's list and its read serve it."""
    view = {
        "profile": "exulanica.society-session/v1",
        "session_id": session_id,
        "state": "open" if end is None else "closed",
        "opened": {
            "event_seq": 1,
            "request_id": "11111111-1111-1111-1111-111111111111",
            "reason": "opened_by_person",
            "opened_by": "22222222-2222-2222-2222-222222222222",
            "limits": dict(LIMITS),
            "start_tick": start,
            "start_state_sha256": "a" * 64,
            "opened_at": opened_at,
            "ends_by": opened_at,
        },
        "closed": None
        if end is None
        else {
            "event_seq": 2,
            "reason": "session_minutes",
            "closed_by": None,
            "end_tick": end,
            "end_state_sha256": "b" * 64,
            "closed_at": opened_at,
            "words": "The session played all the minutes it was given.",
        },
    }
    listed = [
        {
            "request_id": request_id,
            "decision_seq": n,
            "role": "society_decision",
            "subject_id": world.knight,
            "decider": "model",
            "base_tick": world.records[request_id]["request"]["base_tick"],
            "consumed_tick": world.records[request_id]["request"]["base_tick"] + 1,
            "status": "accepted",
            "reason": "validated_choice",
        }
        for n, request_id in enumerate(asked, start=1)
    ]
    read = {
        **view,
        "used": {
            "wall_seconds": 30,
            "minutes": 2,
            "decisions": len(listed),
            "usd": "0.0001",
            "calls": len(listed),
            "unresolved": {"count": 0, "usd": "0"},
        },
        "bounds": [],
        "decisions": listed,
        "decisions_read": {"counted": len(listed), "maximum": 2000, "total": len(listed)},
        "measures": {},
        "by_model": [],
    }
    return view, read


def serve(world, *sessions):
    """The society's sessions, oldest given first; the list serves them newest first."""
    world.routes[SESSIONS] = {"sessions": [view for view, _ in reversed(sessions)]}
    for view, read in sessions:
        world.routes[f"{SESSIONS}/{view['session_id']}"] = read


def held(folder):
    """The living sessions a project's last commit holds: state and records."""
    return {
        s["living_session"]["session_id"]: (
            s["living_session"]["state"],
            sorted(d["record_id"] for d in s["decisions"]),
        )
        for s in Project(folder).sessions_at("HEAD").values()
    }


@pytest.fixture
def followed(world, token, tmp_path):
    """One followed folder in a projects directory and a follower over it, on a fake clock."""
    projects = tmp_path / "projects"
    folder = follow(world, token, projects / "demo", "--sessions-since", SINCE)
    clock = Clock()
    follower = Follower(projects, base_url=world.url, token=TOKEN, clock=clock)
    yield projects, folder, clock, follower
    follower.close()


# Settings and the session rule


def settings(**changes):
    return {
        "profile": "exulanica.world-project-follow/v1",
        "world_id": WORLD,
        "version_id": VERSION,
        "things": "every",
        "readable": False,
        "sessions": {"since": SINCE},
        **changes,
    }


def test_follow_settings_are_closed_data_whose_absent_limits_are_today_s():
    plain = follow_document(settings())
    assert plain == settings()
    assert policy_of(plain) == Policy()
    tuned = follow_document(settings(limits={"settle_seconds": 300, "daily_cap": 10}))
    assert policy_of(tuned) == Policy(settle_seconds=300, daily_cap=10)
    assert follow_document(settings(things=["knight:1"], sessions=None))["sessions"] is None
    for broken in (
        settings(extra=True),
        settings(things=[]),
        settings(things=["knight:1", "knight:1"]),
        settings(things="some"),
        settings(sessions={"since": "yesterday"}),
        settings(limits={"settle_seconds": 120.5}),
        settings(limits={"poll_seconds": 1}),
        settings(limits={"daily_cap": 0}),
        settings(world_id="/Users/someone/world"),
        settings(version_id="ghp_" + "a" * 36),
    ):
        with pytest.raises(ProjectError):
            follow_document(broken)


def test_the_session_due_is_a_held_open_one_then_the_oldest_since_the_follow_began():
    listing = [
        {"session_id": "c", "state": "open", "opened": {"opened_at": "2026-10-14T03:00:00+00:00"}},
        {"session_id": "b", "state": "closed", "opened": {"opened_at": "2026-10-14T02:00:00Z"}},
        {"session_id": "a", "state": "closed", "opened": {"opened_at": "2026-10-14T01:00:00Z"}},
        {"session_id": "z", "state": "closed", "opened": {"opened_at": "2026-10-13T23:00:00Z"}},
    ]
    assert due_session(listing, {}, SINCE) == "a"
    assert due_session(listing, {"a": "closed"}, SINCE) == "b"
    assert due_session(listing, {"a": "closed", "b": "open"}, SINCE) == "b"
    assert due_session(listing, {"a": "closed", "b": "closed"}, SINCE) == "c"
    assert due_session(listing, {"a": "closed", "b": "closed", "c": "open"}, SINCE) == "c"
    assert due_session(listing, {"a": "closed", "b": "closed", "c": "closed"}, SINCE) is None
    # Passed over: a closed session that left no evidence of a followed thing.
    assert due_session(listing, {}, SINCE, passed={"a"}) == "b"
    # A session from before the follow began is history, unless the project holds it open.
    assert due_session(listing, {}, "2026-10-14T04:00:00Z") is None
    assert due_session(listing, {"z": "open"}, "2026-10-14T04:00:00Z") == "z"
    assert due_session([], {}, SINCE) is None


def test_every_placed_thing_is_every_one_a_checkpoint_can_hold(world):
    things = world.routes[f"/world/versions/{VERSION}"]["things"]
    gone, carried = deepcopy(things[0]), deepcopy(things[0])
    gone.update(thing_id="erased:1", gone=True)
    carried.update(thing_id="carried:1", support={"thing_id": "knight:1"})
    things += [gone, carried]
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        result = capture(reader, version_id=VERSION, project_id="project:demo", thing_ids=None)
        assert [t["thing_id"] for t in result.checkpoint["things"]] == ["bench:1", "knight:1"]
        assert result.report["things_not_held"] == 2
        assert [m["thing_id"] for m in result.checkpoint["models"]] == ["knight:1"]
        # Removed, while the society still lists the knight's model choice: it keeps none.
        next(t for t in things if t["thing_id"] == "knight:1")["removed"] = True
        removed = capture(reader, version_id=VERSION, project_id="project:demo", thing_ids=None)
    knight = next(t for t in removed.checkpoint["things"] if t["thing_id"] == "knight:1")
    assert knight["removed"] is True
    assert removed.checkpoint["models"] == []


# Following


def test_a_followed_world_is_kept_current_with_nobody_calling_anything(world, followed):
    _projects, folder, clock, follower = followed
    assert commits(folder) == ["Follow the world as it changes", "Start the project"]
    started = Project(folder).at("HEAD")
    assert [t["thing_id"] for t in started["things"]] == ["bench:1", "knight:1"]
    assert [m["thing_id"] for m in started["models"]] == ["knight:1"]
    assert read_follow(folder) == settings()

    assert poll(follower, clock, 0)["demo"]["state"] == "clean"
    move(world, 2000)
    assert poll(follower, clock)["demo"]["state"] == "settling"
    assert Project(folder).timeline()["pending"] == ["Moved the knight 2 m east"]
    for _ in range(7):
        assert poll(follower, clock).get("demo", {"state": "settling"})["state"] == "settling"
    recorded = poll(follower, clock)["demo"]
    assert recorded["state"] == "checkpointed"
    assert recorded["message"] == "Moved the knight 2 m east"
    assert commits(folder)[0] == "Moved the knight 2 m east"
    assert poll(follower, clock).get("demo", {"state": "clean"})["state"] == "clean"
    assert {method for method, _, _ in world.requests} == {"GET"}


def test_folders_are_followed_as_they_gain_change_and_lose_their_follow_file(
    world, token, tmp_path
):
    projects = tmp_path / "projects"
    projects.mkdir()
    clock = Clock()
    follower = Follower(projects, base_url=world.url, token=TOKEN, clock=clock)
    try:
        assert poll(follower, clock, 0) == {}
        follow(world, token, projects / "demo", "--sessions-since", SINCE)
        assert poll(follower, clock)["demo"]["state"] == "clean"
        assert follower.followed() == ["demo"]
        # The same command again with other settings: followed by its new settings.
        assert main(["follow", str(projects / "demo"), "--readable"]) == 0
        assert read_follow(projects / "demo")["readable"] is True
        # With readable text the project now keeps the world's name: a change to record.
        assert poll(follower, clock)["demo"]["state"] == "settling"
        assert main(["unfollow", str(projects / "demo")]) == 0
        assert read_follow(projects / "demo") is None
        assert poll(follower, clock)["demo"]["state"] == "left"
        assert follower.followed() == []
        assert commits(projects / "demo")[0] == "Stop following the world"
    finally:
        follower.close()


def test_each_living_session_is_its_own_file_and_a_closed_one_is_recorded_at_once(world, followed):
    _projects, folder, clock, follower = followed
    old = session(world, OLD, opened_at="2026-10-13T20:00:00+00:00", start=1, end=3, asked=["r1"])
    opened = session(world, A, opened_at="2026-10-14T01:00:00+00:00", start=3, asked=["r1"])
    serve(world, old, opened)
    first = poll(follower, clock, 0)["demo"]
    assert first["state"] == "settling"  # an open session's evidence settles as world edits do
    # Between two polls, A closes, and B opens and closes.
    serve(
        world,
        old,
        session(world, A, opened_at="2026-10-14T01:00:00+00:00", start=3, end=5, asked=["r1"]),
        session(
            world, B, opened_at="2026-10-14T01:10:00+00:00", start=5, end=7, asked=["r2", "r3"]
        ),
    )
    assert poll(follower, clock)["demo"]["state"] == "checkpointed"
    assert held(folder) == {A: ("closed", ["request:r1"])}
    assert poll(follower, clock)["demo"]["state"] == "checkpointed"
    assert held(folder) == {
        A: ("closed", ["request:r1"]),
        B: ("closed", ["request:r2", "request:r3"]),
    }
    # The session from before the follow began is history; nothing more is due.
    assert poll(follower, clock).get("demo", {"state": "clean"})["state"] == "clean"
    assert OLD not in held(folder)


def test_a_closed_session_with_nothing_to_keep_is_passed_over_for_the_next(world, followed):
    _projects, folder, clock, follower = followed
    # A's one decision got no answer, so it leaves no evidence.
    world.records["silent"] = {**world.records["old"], "decision": None}
    serve(
        world,
        session(world, A, opened_at="2026-10-14T01:00:00+00:00", start=1, end=3, asked=["silent"]),
        session(world, B, opened_at="2026-10-14T01:10:00+00:00", start=3, end=5, asked=["r1"]),
    )
    poll(follower, clock, 0)
    assert held(folder) == {}
    assert poll(follower, clock)["demo"]["state"] == "checkpointed"
    assert held(folder) == {B: ("closed", ["request:r1"])}
    reads = [path for _, path, _ in world.requests if f"/sessions/{A}" in path]
    assert len(reads) == 1  # A was read once, then passed over


def test_a_binding_keeps_the_revision_the_project_recorded_between_sessions(world, followed):
    _projects, folder, clock, follower = followed
    serve(
        world,
        session(world, A, opened_at="2026-10-14T01:00:00+00:00", start=3, end=5, asked=["r1"]),
    )
    assert poll(follower, clock, 0)["demo"]["state"] == "checkpointed"
    revision = Project(folder).at("HEAD")["models"][0]["revision"]
    assert revision == "synthetic-model-rev-1"
    # No session is due now, so no record is read: the binding must not change.
    assert poll(follower, clock).get("demo", {"state": "clean"})["state"] == "clean"
    assert Project(folder).timeline()["pending"] == []


def test_a_world_without_a_society_is_followed_for_its_edits_alone(world, token, tmp_path):
    del world.routes[SESSIONS]
    del world.routes[f"/world/versions/{VERSION}/society/models"]
    projects = tmp_path / "projects"
    folder = follow(world, token, projects / "demo")
    assert Project(folder).at("HEAD")["models"] == []
    clock = Clock()
    follower = Follower(projects, base_url=world.url, token=TOKEN, clock=clock)
    try:
        poll(follower, clock, 0)
        move(world, 6000, index=0)
        assert poll(follower, clock)["demo"]["state"] == "settling"
        assert poll(follower, clock, 120)["demo"]["state"] == "checkpointed"
        assert commits(folder)[0] == "Moved the bench 3 m east"
    finally:
        follower.close()


def test_nothing_placed_cannot_start_a_project_and_a_followed_one_waits(
    world, token, tmp_path, capsys
):
    view = world.routes[f"/world/versions/{VERSION}"]
    things = view["things"]
    view["things"] = []
    follow(world, token, tmp_path / "empty", expect=1)
    assert "no placed thing" in capsys.readouterr().out
    assert not (tmp_path / "empty").exists()
    view["things"] = things
    projects = tmp_path / "projects"
    folder = follow(world, token, projects / "demo")
    clock = Clock()
    follower = Follower(projects, base_url=world.url, token=TOKEN, clock=clock)
    try:
        view["things"] = []
        assert poll(follower, clock, 0)["demo"]["state"] == "waiting"
        assert len(commits(folder)) == 2
    finally:
        follower.close()


def test_the_daily_cap_holds_across_a_restart(world, token, tmp_path):
    projects = tmp_path / "projects"
    folder = follow(world, token, projects / "demo", "--daily-cap", "1")
    clock = Clock()
    follower = Follower(projects, base_url=world.url, token=TOKEN, clock=clock)
    poll(follower, clock, 0)
    move(world, 1000)
    poll(follower, clock)
    assert poll(follower, clock, 120)["demo"]["state"] == "checkpointed"
    follower.close()
    # A new process: the day's count is read from the project, not from memory.
    restarted = Follower(projects, base_url=world.url, token=TOKEN, clock=clock)
    try:
        poll(restarted, clock, 0)
        move(world, 2000)
        poll(restarted, clock)
        assert poll(restarted, clock, 120)["demo"]["state"] == "capped"
        assert commits(folder)[0] == "Moved the knight 1 m east"
        clock.now += 86_400
        assert poll(restarted, clock)["demo"]["state"] == "checkpointed"
    finally:
        restarted.close()


def test_sessions_the_cap_held_back_are_all_recorded_once_it_allows(world, token, tmp_path):
    projects = tmp_path / "projects"
    folder = follow(world, token, projects / "demo", "--sessions-since", SINCE, "--daily-cap", "1")
    clock = Clock()
    follower = Follower(projects, base_url=world.url, token=TOKEN, clock=clock)
    try:
        # The day's one checkpoint goes to a move.
        poll(follower, clock, 0)
        move(world, 1000)
        poll(follower, clock)
        assert poll(follower, clock, 120)["demo"]["state"] == "checkpointed"
        # Two sessions close the same day: the cap holds both back, pending in the folder, while
        # the second poll reads the second session.
        serve(
            world,
            session(world, A, opened_at="2026-10-14T01:00:00+00:00", start=3, end=5, asked=["r1"]),
            session(world, B, opened_at="2026-10-14T01:10:00+00:00", start=5, end=7, asked=["r2"]),
        )
        assert poll(follower, clock)["demo"]["state"] == "capped"
        poll(follower, clock)
        assert held(folder) == {}
        clock.now += 86_400
        assert poll(follower, clock)["demo"]["state"] == "checkpointed"
        assert held(folder) == {A: ("closed", ["request:r1"]), B: ("closed", ["request:r2"])}
        # The checkpoint's binding is the one the sessions' decisions were made under.
        assert Project(folder).reopen()["sessions"][0]["warning"] is None
        assert Project(folder).timeline()["pending_evidence"] == []
    finally:
        follower.close()


def test_an_unreadable_projects_directory_is_said_once_and_followed_folders_go_on(world, followed):
    projects, _folder, clock, follower = followed
    poll(follower, clock, 0)
    follower.directory = projects / "not-there"  # As a directory gone or unreadable reads.
    move(world, 1000)
    first = poll(follower, clock)
    assert first[None]["state"] == "unreadable"
    assert first["demo"]["state"] == "settling"
    assert None not in poll(follower, clock)


def test_one_unreachable_world_leaves_the_others_followed(world, token, tmp_path):
    projects = tmp_path / "projects"
    follow(world, token, projects / "demo")
    lost = follow(world, token, projects / "lost")
    # Pointed at a version the world does not serve: every read of it is refused.
    assert main(["follow", str(lost), "--version", "version-gone"]) == 0
    clock = Clock()
    follower = Follower(projects, base_url=world.url, token=TOKEN, clock=clock)
    try:
        first = poll(follower, clock, 0)
        assert first["lost"]["state"] == "unreachable"
        assert "status 404" in first["lost"]["error"]
        move(world, 1000)
        poll(follower, clock)
        assert poll(follower, clock, 120)["demo"]["state"] == "checkpointed"
    finally:
        follower.close()


def test_stopping_records_what_is_pending_exactly_once(world, followed):
    _projects, folder, _clock, follower = followed
    move(world, 4000)
    stop = threading.Event()
    seen = []

    def tell(outcome):
        seen.append(outcome["state"])
        if outcome["state"] == "settling":
            stop.set()

    final = follower.run(stop, tell)
    assert seen[-2:] == ["settling", "checkpointed"]
    assert final == {"recorded": 1, "left_pending": 0}
    assert commits(folder)[0] == "Moved the knight 4 m east"
    assert len(commits(folder)) == 3


def test_nothing_the_follower_writes_or_says_carries_the_token(world, followed, tmp_path):
    _projects, folder, clock, follower = followed
    serve(
        world,
        session(world, A, opened_at="2026-10-14T01:00:00+00:00", start=3, end=5, asked=["r1"]),
    )
    said = list(follower.round())
    move(world, 9000)
    clock.now += 15
    said += follower.round()
    assert TOKEN not in json.dumps(said)
    assert str(tmp_path) not in json.dumps(said)
    log = subprocess.run(
        ["git", f"--git-dir={folder / '.git'}", "log", "-p", "--all"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert TOKEN not in log
    for path in folder.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            assert TOKEN not in path.read_text(encoding="utf-8")
    assert all(TOKEN not in request for _, request, _ in world.requests)
    assert {method for method, _, _ in world.requests} == {"GET"}


def test_one_follower_holds_a_projects_directory(world, followed):
    projects, _, clock, _ = followed
    with pytest.raises(ProjectError, match="another follower"):
        Follower(projects, base_url=world.url, token=TOKEN, clock=clock)


def test_the_follow_file_is_committed_beside_the_project_and_never_published(world, followed):
    projects, folder, clock, follower = followed
    project = Project(folder)
    assert FOLLOW_FILE not in published_part(project.published_files("HEAD"))
    assert (
        FOLLOW_FILE
        in subprocess.run(
            ["git", f"--git-dir={folder / '.git'}", "ls-files"], capture_output=True, text=True
        ).stdout.split()
    )
    read = history_read(project)
    assert [c["kind"] for c in read["checkpoints"]] == ["follow", "checkpoint"]
    assert read["follow"] == settings()
    # A folder that is not a project, or belongs to another world, is refused by name.
    (projects / "loose").mkdir()
    (projects / "loose" / FOLLOW_FILE).write_text(json.dumps(settings()), encoding="utf-8")
    outcomes = poll(follower, clock, 0)
    assert outcomes["loose"]["state"] == "refused"
    assert outcomes["demo"]["state"] == "clean"


def test_the_since_instant_is_written_from_the_clock_by_the_command(world, token, tmp_path):
    folder = follow(world, token, tmp_path / "demo")
    since = read_follow(folder)["sessions"]["since"]
    assert re.fullmatch(r"20[0-9]{2}-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z", since)
    assert main(["follow", str(folder), "--no-sessions"]) == 0
    assert read_follow(folder)["sessions"] is None
    # Only what a flag names changes: the things narrow, the rest stays as it was.
    assert main(["follow", str(folder), "--thing", "knight:1"]) == 0
    assert read_follow(folder)["things"] == ["knight:1"]
    assert read_follow(folder)["sessions"] is None
    assert main(["follow", str(folder), "--world", "world:other"]) == 1


def test_a_follower_follows_at_most_its_maximum_and_names_the_rest(world, token, tmp_path):
    projects = tmp_path / "projects"
    follow(world, token, projects / "first")
    follow(world, token, projects / "second")
    clock = Clock()
    follower = Follower(projects, base_url=world.url, token=TOKEN, clock=clock, maximum=1)
    try:
        outcomes = poll(follower, clock, 0)
        assert follower.followed() == ["first"]
        assert outcomes["second"] == {
            "project": "second",
            "state": "refused",
            "error": "this follower follows at most 1 folder",
        }
        assert "second" not in poll(follower, clock)  # said once
    finally:
        follower.close()
