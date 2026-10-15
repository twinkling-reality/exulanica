"""Capture against a fake World API on this machine; synthetic world, GET only."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
from exulanica.canonical import canonical_json
from exulanica.world.decision_roles import decision_roles
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import PlacedThing, named_kind, placed_thing_document
from exulanica.world_package.projects.capture import (
    WorldReader,
    capture,
    read_token,
    subject_id,
)
from exulanica.world_package.projects.checkpoint import ProjectError, digest, inspect, playback

WORLD = "world:synthetic"
VERSION = "version-fixture"
TOKEN = "synthetic-bearer-not-a-secret"
SNAPSHOT = "e" * 64


def placed(thing_id, kind, x_mm=0):
    return placed_thing_document(
        PlacedThing(
            thing_id,
            named_kind(kind, 2),
            "region:one",
            Transform(x_mm, 0, 0, 0, 1000),
            ObjectOrigin("authored", "fictional"),
        )
    )


def option(label, action, target_id=None):
    return {
        "kind": "person",
        "label": label,
        "action": action,
        "walk_mm": None,
        "activity": None,
        "target_id": target_id,
    }


def context(tick):
    return {
        "tick": tick,
        "being": {"kind": "knight", "summary": "A knight in plain armour."},
        "doing": {"kind": "resting", "reason": "routine", "status": "active"},
        "under_way": False,
        "need_milli": 400,
        "rest_at_need_milli": 750,
        "last_activity": None,
        "options": [option("wait here a minute", "wait"), option("bench, 3 m away", "go", "b:1")],
    }


def record(request_id, subject, tick, chosen, *, model="synthetic-model"):
    return {
        "status": "completed",
        "request": {
            "request_id": request_id,
            "subject_id": subject,
            "base_tick": tick,
            "context": context(tick),
            "context_sha256": digest(f"context:{request_id}".encode()),
            "provider_config": {"provider": "synthetic", "model_id": model},
        },
        "decision": {
            "status": "accepted",
            "reason": "validated_choice",
            "document_sha256": digest(f"receipt:{request_id}".encode()),
            "proposal": {"label": chosen, "line": "Time to sit."},
            "provider": {
                "served_model_id": "synthetic-model-rev-1",
                "latency_ms": 120,
                "prompt_tokens": 300,
                "completion_tokens": 9,
                "cost_usd": "0.00001",
                "cost_known": True,
            },
        },
    }


def event(request_id, subject, tick, disposition, *, model=True, seq=1):
    return {
        "event_id": f"event:{request_id}",
        "tick": tick + 1,
        "event_kind": "decision_applied",
        "subject_id": subject,
        "document": {
            "request_id": request_id,
            "decision_seq": seq,
            "disposition": disposition,
            "reason": "option_no_longer_offered" if disposition != "applied" else "applied",
            "model": {"provider": "synthetic", "model_id": "synthetic-model"} if model else None,
        },
    }


class World:
    """A fake World API: GET handlers over fixed synthetic documents, refusing everything else."""

    def __init__(self):
        role = decision_roles().role("society_decision")
        self.contract = role.contract(role.contract_versions).binding()
        self.knight = subject_id(WORLD, "knight:1")
        self.bench = subject_id(WORLD, "bench:1")
        self.records = {
            "r1": record("r1", self.knight, 4, "bench, 3 m away"),
            "r2": record("r2", self.knight, 5, "wait here a minute"),
            "r3": record("r3", self.knight, 6, "bench, 3 m away"),
            "old": record("old", self.knight, 2, "wait here a minute", model="earlier-model"),
            "bench": record("bench", self.bench, 4, "wait here a minute"),
        }
        newest = [
            event("r3", self.knight, 6, "superseded", seq=4),
            event("r2", self.knight, 5, "rejected", seq=3),
            event("routine", self.knight, 5, "applied", model=False, seq=9),
        ]
        oldest = [
            event("r1", self.knight, 4, "applied", seq=2),
            event("bench", self.bench, 4, "applied", seq=2),
            event("old", self.knight, 2, "applied", seq=1),
        ]
        self.routes = {
            f"/world/versions/{VERSION}": {
                "world_id": WORLD,
                "version_id": VERSION,
                "source_snapshot_id": "snapshot-fixture",
                "source_invalidated": False,
                "state_sha256": "a" * 64,
                "title": "PRIVATE TITLE",
                "created_by": "PRIVATE ACTOR",
                "things": [placed("knight:1", "knight"), placed("bench:1", "bench", 3000)],
            },
            "/world-entries": [
                {
                    "world_id": WORLD,
                    "source_snapshot_id": "snapshot-fixture",
                    "source_snapshot_sha256": SNAPSHOT,
                    "title": "PRIVATE TITLE",
                }
            ],
            f"/world/versions/{VERSION}/society/models": {
                "contract": {**self.contract, "model_people_maximum": 4},
                "choices": [
                    {
                        "subject_id": self.knight,
                        "choice_seq": 2,
                        "decider": {
                            "kind": "model",
                            "provider": "synthetic",
                            "model_id": "synthetic-model",
                        },
                    },
                    {"subject_id": self.bench, "choice_seq": 1, "decider": {"kind": "routine"}},
                ],
            },
            ("events", None): {"events": newest, "next": "cursor-2"},
            ("events", "cursor-2"): {"events": oldest, "next": None},
        }
        self.requests = []
        #: Paths the fake answers with a refusal: path to (status, body).
        self.refusals = {}

    def answer(self, handler):
        parts = urlsplit(handler.path)
        query = parse_qs(parts.query)
        self.requests.append((handler.command, handler.path, handler.headers.get("Authorization")))
        if handler.headers.get("Authorization") != f"Bearer {TOKEN}":
            return 401, {"code": "unauthorized"}
        if parts.path != "/world-entries" and query.get("world_id") != [WORLD]:
            return 422, {"code": "world_id"}
        if parts.path in self.refusals:
            return self.refusals[parts.path]
        if parts.path.endswith("/society/events"):
            return 200, self.routes[("events", query.get("before", [None])[0])]
        prefix = f"/world/versions/{VERSION}/society/decisions/"
        if parts.path.startswith(prefix):
            return 200, self.records[parts.path.removeprefix(prefix)]
        if parts.path in self.routes:
            return 200, self.routes[parts.path]
        return 404, {"code": "not_found"}


@pytest.fixture
def world():
    fake = World()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = fake.answer(self)
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


def test_capture_selects_one_being_its_model_and_consumed_decisions(world):
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        result = capture(
            reader, version_id=VERSION, project_id="project:demo", thing_ids=["knight:1"]
        )
    project = result.checkpoint
    assert [t["thing_id"] for t in project["things"]] == ["knight:1"]
    assert project["source"]["snapshot_sha256"] == SNAPSHOT
    assert [(m["thing_id"], m["model_id"], m["revision"]) for m in project["models"]] == [
        ("knight:1", "synthetic-model", "synthetic-model-rev-1")
    ]
    outcomes = {d["record_id"]: (d["outcome"], d["chosen_option_id"]) for d in project["decisions"]}
    assert outcomes == {
        "request:r1": ("applied", "option:2"),
        "request:r2": ("refused", "option:1"),
        "request:r3": ("not-applied", "option:2"),
    }
    assert result.report["skipped_decisions"] == {"asked under another assignment or unanswered": 1}
    assert result.report["world_writes"] == 0
    text = canonical_json(project).decode()
    for private in ("PRIVATE", "bench:1", "Time to sit", "wait here a minute", TOKEN):
        assert private not in text
    assert all(d.get("readable") is None for d in project["decisions"])
    assert {method for method, _, _ in world.requests} == {"GET"}
    assert all(TOKEN not in path for _, path, _ in world.requests)
    report = inspect(project, dependencies=result.dependencies)
    assert report["missing_dependencies"] == [SNAPSHOT]
    assert report["unsupported"] == [] and report["invalid_dependencies"] == []
    assert [r["record_id"] for r in playback(project)["records"]] == [
        "request:r1",
        "request:r2",
        "request:r3",
    ]


def test_readable_records_are_opt_in(world):
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        result = capture(
            reader,
            version_id=VERSION,
            project_id="project:demo",
            thing_ids=["knight:1"],
            readable=True,
        )
    first = next(d for d in result.checkpoint["decisions"] if d["record_id"] == "request:r1")
    assert first["readable"]["options"] == ["wait here a minute", "bench, 3 m away"]
    assert first["readable"]["choice"] == "bench, 3 m away"
    assert first["readable"]["line"] == "Time to sit."
    assert first["readable"]["situation"].startswith("You are a knight: a knight in plain armour.")
    assert first["readable"]["consumed_tick"] == 5
    assert first["readable"]["cost_known"] is True


def test_capture_refuses_wrong_bearer_unknown_things_and_unsafe_destinations(world, tmp_path):
    with (
        WorldReader(world.url, "wrong-bearer", WORLD) as reader,
        pytest.raises(ProjectError, match="status 401") as refused,
    ):
        capture(reader, version_id=VERSION, project_id="project:demo", thing_ids=["knight:1"])
    assert "wrong-bearer" not in str(refused.value)
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        with pytest.raises(ProjectError, match="present in the version"):
            capture(reader, version_id=VERSION, project_id="project:demo", thing_ids=["ghost:1"])
        with pytest.raises(ProjectError, match="unsupported form"):
            capture(reader, version_id="../admin", project_id="project:demo", thing_ids=["x"])
    for url in (
        "http://example.invalid:8080",
        "https://user:pass@example.invalid",
        "http://localhost:1/?token=x",
        "http://localhost:1/api",
        "http://127.0.0.1:1",
        "https://192.0.2.1",
        "file:///etc/passwd",
    ):
        with pytest.raises(ProjectError):
            WorldReader(url, TOKEN, WORLD)
    token = tmp_path / "token"
    token.write_text(TOKEN + "\n")
    assert read_token(token) == TOKEN
    link = tmp_path / "link"
    link.symlink_to(token)
    with pytest.raises(ProjectError):
        read_token(link)
    token.write_text("two words\n")
    with pytest.raises(ProjectError):
        read_token(token)


def test_a_session_capture_puts_decisions_beside_the_world(world):
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        result = capture(
            reader,
            version_id=VERSION,
            project_id="project:demo",
            thing_ids=["knight:1"],
            session_id="session:one",
        )
    assert result.checkpoint["decisions"] == []
    assert result.checkpoint["models"] == result.evidence["models"]
    assert [d["record_id"] for d in result.evidence["decisions"]] == [
        "request:r1",
        "request:r2",
        "request:r3",
    ]
    assert result.report["decisions_in"] == "evidence"


def test_capture_command_reads_a_token_file_and_saves_privately(world, tmp_path, capsys):
    from exulanica.world_package.projects.__main__ import main

    token = tmp_path / "token"
    token.write_text(TOKEN, encoding="utf-8")
    output, evidence = tmp_path / "checkpoint.json", tmp_path / "evidence.json"
    arguments = [
        "capture",
        "--api",
        world.url,
        "--token-file",
        str(token),
        "--world",
        WORLD,
        "--version",
        VERSION,
        "--thing",
        "knight:1",
        "--project-id",
        "project:demo",
        "--session",
        "session:one",
        "--output",
        str(output),
        "--evidence-output",
        str(evidence),
    ]
    assert main(arguments) == 0
    printed = capsys.readouterr().out
    assert TOKEN not in printed
    assert json.loads(printed)["report"]["decisions"] == 3
    assert output.stat().st_mode & 0o777 == 0o600
    assert evidence.stat().st_mode & 0o777 == 0o600
    assert TOKEN not in output.read_text() + evidence.read_text()


def test_a_session_capture_records_receipts_coverage_and_its_time(world):
    from datetime import UTC, datetime

    with WorldReader(world.url, TOKEN, WORLD) as reader:
        result = capture(
            reader,
            version_id=VERSION,
            project_id="project:demo",
            thing_ids=["knight:1"],
            session_id="session:one",
            now=lambda: datetime(2026, 10, 14, 1, 2, 3, tzinfo=UTC),
        )
    evidence = result.evidence
    assert evidence["coverage"] == {"decisions": "consumed"}
    assert evidence["captured_at"] == "2026-10-14T01:02:03Z"
    receipts = {d["record_id"]: d["receipt"] for d in evidence["decisions"]}
    assert receipts["request:r1"] == {
        "status": "accepted",
        "reason": "validated_choice",
        "disposition": "applied",
        "disposition_reason": "applied",
        "consumed_tick": 5,
        "served_model_id": "synthetic-model-rev-1",
        "cost_usd": "0.00001",
        "cost_known": True,
    }
    assert receipts["request:r2"]["disposition"] == "rejected"
    assert receipts["request:r2"]["disposition_reason"] == "option_no_longer_offered"
    assert receipts["request:r3"]["disposition"] == "superseded"
    # Receipts carry no words: nothing readable unless asked for.
    assert all("readable" not in d for d in evidence["decisions"])


SESSION_ID = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"


def with_session(world, *, counted=7, maximum=2000, total=None, reason="session_minutes"):
    """Give the fake world one closed living session from minute 3, with a timed-out request."""
    timed_out = record("r9", world.knight, 7, "wait here a minute")
    timed_out["decision"].update(status="unavailable", reason="model_timed_out", proposal=None)
    timed_out["decision"]["provider"].update(
        latency_ms=20000, prompt_tokens=None, completion_tokens=None, cost_known=False
    )
    world.records["r9"] = timed_out
    # Asked of the same model, but at minute 2, before the session opened at minute 3.
    world.records["early"] = record("early", world.knight, 2, "wait here a minute")
    # Asked of a model for a being the capture did not select.
    world.records["bench"]["request"]["provider_config"] = {"provider": "synthetic"}
    # Each entry as the session read serves it (synthetic-society-contract.md, the session read's
    # `decisions`): the decider is a word, and how its ask ended is beside it.
    listed = [
        {
            "request_id": rid,
            "decision_seq": n,
            "role": "society_decision",
            "subject_id": world.knight if rid != "bench" else world.bench,
            "decider": "model",
            "base_tick": tick,
            "consumed_tick": None if rid == "r9" else tick + 1,
            "status": "unavailable" if rid == "r9" else "accepted",
            "reason": "model_timed_out" if rid == "r9" else "validated_choice",
        }
        for n, (rid, tick) in enumerate(
            [("early", 2), ("r1", 4), ("r2", 5), ("r3", 6), ("r9", 7), ("bench", 4)], start=1
        )
    ]
    view = {
        "profile": "exulanica.society-session/v1",
        "session_id": SESSION_ID,
        "state": "closed",
        "opened": {
            "event_seq": 10,
            "request_id": "11111111-1111-1111-1111-111111111111",
            "reason": "owner",
            "opened_by": "22222222-2222-2222-2222-222222222222",
            "limits": {
                "wall_seconds": 3600,
                "minutes": 60,
                "decisions": 500,
                "usd": "0.5",
                "calls": 600,
            },
            "start_tick": 3,
            "start_state_sha256": "a" * 64,
            "opened_at": "2026-10-14T01:00:00+00:00",
            "ends_by": "2026-10-14T02:00:00+00:00",
        },
        "closed": {
            "event_seq": 90,
            "reason": reason,
            "closed_by": None,
            "end_tick": 63,
            "end_state_sha256": "b" * 64,
            "closed_at": "2026-10-14T01:20:00.250000+00:00",
        },
    }
    read = {
        **view,
        "used": {
            "wall_seconds": 1200,
            "minutes": 60,
            "decisions": 4,
            "usd": "0.0003",
            "calls": 4,
            "unresolved": {"count": 0, "usd": "0"},
        },
        "bounds": [
            {
                "provider": "synthetic",
                "bound_id": "33333333-3333-3333-3333-333333333333",
                "state": "closed",
                "ceiling_usd": "0.5",
                "max_calls": 600,
                "valid_until": "2026-10-14T02:00:00+00:00",
                "committed_usd": "0.0003",
                "committed_calls": 4,
                "in_flight_usd": "0",
                "unresolved": {"count": 0, "usd": "0"},
                "known_usage_usd": "0.0001",
                "reconciled_usd": "0",
            }
        ],
        "decisions": listed,
        "decisions_read": {
            "counted": counted,
            "maximum": maximum,
            "total": counted if total is None else total,
        },
        "measures": {},
        "by_model": [],
    }
    base = f"/world/versions/{VERSION}/society/control/sessions"
    world.routes[base] = {"sessions": [view]}
    world.routes[f"{base}/{SESSION_ID}"] = read


def test_a_living_session_is_captured_with_every_request_it_asked(world):
    with_session(world)
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        result = capture(
            reader,
            version_id=VERSION,
            project_id="project:demo",
            thing_ids=["knight:1"],
            living_session="latest",
            readable=True,
        )
    evidence = result.evidence
    assert evidence["session_id"] == f"session:{SESSION_ID}"
    assert evidence["coverage"] == {"decisions": "all"}
    by_id = {d["record_id"]: d for d in evidence["decisions"]}
    # Minute 2's request came before the session opened: not its evidence.
    assert sorted(by_id) == ["request:r1", "request:r2", "request:r3", "request:r9"]
    timed_out = by_id["request:r9"]
    assert timed_out["receipt"]["status"] == "unavailable"
    assert timed_out["receipt"]["reason"] == "model_timed_out"
    assert timed_out["receipt"]["consumed_tick"] is None
    assert timed_out["outcome"] == "not-applied" and timed_out["chosen_option_id"] is None
    assert "readable" not in timed_out and "readable" in by_id["request:r1"]
    living = evidence["living_session"]
    assert living["state"] == "closed"
    assert living["opened"] == {
        "tick": 3,
        "at": "2026-10-14T01:00:00Z",
        "state_sha256": "a" * 64,
        "limits": {
            "wall_seconds": 3600,
            "minutes": 60,
            "decisions": 500,
            "usd": "0.5",
            "calls": 600,
        },
    }
    assert living["closed"] == {
        "tick": 63,
        "at": "2026-10-14T01:20:00Z",
        "state_sha256": "b" * 64,
        "reason": "session_minutes",
        "by": "system",
    }
    assert living["spending"]["bounds"] == [
        {
            "provider": "synthetic",
            "state": "closed",
            "ceiling_usd": "0.5",
            "committed_usd": "0.0003",
            "committed_calls": 4,
            "known_usage_usd": "0.0001",
            "unresolved_count": 0,
            "unresolved_usd": "0",
            "reconciled_usd": "0",
        }
    ]
    # A being the capture did not select has none of its records read.
    assert not any(path.split("?")[0].endswith("/decisions/bench") for _, path, _ in world.requests)
    text = json.dumps(evidence)
    for private in ("22222222", "11111111", "33333333"):
        assert private not in text  # no actor, request or bound identities


def test_a_capped_session_list_falls_back_to_the_decisions_minutes_took_up(world):
    with_session(world, counted=2000, maximum=2000, total=2001)
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        result = capture(
            reader,
            version_id=VERSION,
            project_id="project:demo",
            thing_ids=["knight:1"],
            living_session=SESSION_ID,
        )
    assert result.evidence["coverage"] == {"decisions": "consumed"}
    assert sorted(d["record_id"] for d in result.evidence["decisions"]) == [
        "request:r1",
        "request:r2",
        "request:r3",
    ]


def test_a_session_a_person_stopped_says_so(world):
    with_session(world, reason="stopped_by_person")
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        result = capture(
            reader,
            version_id=VERSION,
            project_id="project:demo",
            thing_ids=["knight:1"],
            living_session=SESSION_ID,
        )
    closed = result.evidence["living_session"]["closed"]
    assert (closed["reason"], closed["by"]) == ("stopped_by_person", "person")


def test_a_session_of_exactly_the_listing_cap_is_complete(world):
    # The list is complete exactly when it holds every decision of the session, cap or not.
    with_session(world, counted=2000, maximum=2000, total=2000)
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        result = capture(
            reader,
            version_id=VERSION,
            project_id="project:demo",
            thing_ids=["knight:1"],
            living_session=SESSION_ID,
        )
    assert result.evidence["coverage"] == {"decisions": "all"}
    assert "request:r9" in {d["record_id"] for d in result.evidence["decisions"]}


def test_a_run_keeps_the_decisions_asked_under_an_earlier_model_under_that_model(world):
    with_session(world)
    # Minute 5 was asked of the knight's earlier model; the knight's model now is another.
    earlier = record("r2", world.knight, 5, "wait here a minute", model="earlier-model")
    earlier["decision"]["provider"]["served_model_id"] = "earlier-model-rev-7"
    world.records["r2"] = earlier
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        result = capture(
            reader,
            version_id=VERSION,
            project_id="project:demo",
            thing_ids=["knight:1"],
            living_session="latest",
        )
    evidence = result.evidence
    bindings = {
        digest(canonical_json(m)): (m["model_id"], m["revision"]) for m in evidence["models"]
    }
    held = {d["record_id"]: bindings[d["binding_sha256"]] for d in evidence["decisions"]}
    assert held == {
        "request:r1": ("synthetic-model", "synthetic-model-rev-1"),
        "request:r2": ("earlier-model", "earlier-model-rev-7"),
        "request:r3": ("synthetic-model", "synthetic-model-rev-1"),
        "request:r9": ("synthetic-model", "synthetic-model-rev-1"),
    }
    assert result.report["skipped_decisions"] == {}
    # The world keeps only the model chosen now, its revision from its own records alone.
    assert [(m["model_id"], m["revision"]) for m in result.checkpoint["models"]] == [
        ("synthetic-model", "synthetic-model-rev-1")
    ]


def card(world, character, revision=3):
    world.routes[f"/world/versions/{VERSION}/society/things/{world.knight}"] = {
        "profile": "exulanica.thing-card/v1",
        "label": "Sir Pip",
        "character": {
            "revision": revision,
            "character": character,
            "written_at": "2026-10-14T01:00:00Z",
            "shown": True,
        },
    }


@pytest.mark.parametrize("readable", [True, False])
def test_who_a_being_is_and_the_world_s_name_are_kept_only_with_readable_text(world, readable):
    card(world, {"name": "Sir Pip", "about": "Guards the well at night."})
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        result = capture(
            reader,
            version_id=VERSION,
            project_id="project:demo",
            thing_ids=None,
            include_decisions=False,
            readable=readable,
        )
    project = result.checkpoint
    if readable:
        assert project["title"] == "PRIVATE TITLE"
        assert project["characters"] == [
            {
                "thing_id": "knight:1",
                "revision": 3,
                "words": {"name": "Sir Pip", "about": "Guards the well at night."},
            }
        ]
    else:
        # The record's revision alone: a change is seen, and no word is kept.
        assert "title" not in project
        assert project["characters"] == [{"thing_id": "knight:1", "revision": 3}]
        text = canonical_json(project).decode()
        assert "Sir Pip" not in text and "Guards" not in text and "PRIVATE" not in text
    # The bench is an object, which has no character: its card is never read.
    cards = [p for _, p, _ in world.requests if "/society/things/" in p]
    assert len(cards) == 1 and world.knight in cards[0]
    assert {method for method, _, _ in world.requests} == {"GET"}


def test_a_cleared_character_keeps_its_revision_and_a_being_without_one_keeps_none(world):
    card(world, None, revision=4)
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        cleared = capture(
            reader,
            version_id=VERSION,
            project_id="project:demo",
            thing_ids=["knight:1"],
            include_decisions=False,
            readable=True,
        ).checkpoint
    assert cleared["characters"] == [
        {"thing_id": "knight:1", "revision": 4, "words": {"name": None, "about": None}}
    ]
    del world.routes[f"/world/versions/{VERSION}/society/things/{world.knight}"]
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        none = capture(
            reader,
            version_id=VERSION,
            project_id="project:demo",
            thing_ids=["knight:1"],
            include_decisions=False,
            readable=True,
        ).checkpoint
    assert "characters" not in none


def test_one_read_of_the_version_s_characters_replaces_the_cards(world):
    world.routes[f"/world/versions/{VERSION}/things/characters"] = {
        "profile": "exulanica.thing-characters/v1",
        "version_id": VERSION,
        "characters": [
            {
                "placed_id": "knight:1",
                "revision": 5,
                "character": {"name": "Sir Pip", "about": "Guards the well at night."},
                "written_at": "2026-10-14T01:00:00Z",
            }
        ],
        "society": "runs_characters",
    }
    card(world, {"name": "an older card", "about": "never read"}, revision=1)
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        project = capture(
            reader,
            version_id=VERSION,
            project_id="project:demo",
            thing_ids=None,
            include_decisions=False,
            readable=True,
        ).checkpoint
    assert project["characters"] == [
        {
            "thing_id": "knight:1",
            "revision": 5,
            "words": {"name": "Sir Pip", "about": "Guards the well at night."},
        }
    ]
    paths = [path.split("?")[0] for _, path, _ in world.requests]
    assert paths.count(f"/world/versions/{VERSION}/things/characters") == 1
    assert not any("/society/things/" in path for path in paths)


PARTS = f"/world/versions/{VERSION}/parts"


def made(world, *, removed=()):
    """A site world's parts read: a building, a fixture and an area, and the removed ones."""
    standing = [
        ("0190a1b2-c3d4-4e5f-8a9b-000000000001", "building", "Tea house", (12_000, 8_000), 0),
        ("0190a1b2-c3d4-4e5f-8a9b-000000000002", "fixture", "Bench", (3_000, 4_000), 1),
        ("0190a1b2-c3d4-4e5f-8a9b-000000000003", "area", "Lower pools", (20_000, 2_000), 0),
    ]
    world.routes[PARTS] = {
        "profile": "exulanica.site-parts/v1",
        "world_id": WORLD,
        "version_id": VERSION,
        "parts": [
            {
                "part_id": part_id,
                "kind": kind,
                "part_key": label.lower().replace(" ", "_"),
                "label": label,
                "zone_id": "0190a1b2-c3d4-4e5f-8a9b-0000000000ff",
                "zone_label": "Garden",
                "centre_mm": list(centre),
                "size_mm": [2_000, 1_000],
                "quarter_turns": turns,
            }
            | ({"storeys": 2} if kind == "building" else {"storeys": None})
            for part_id, kind, label, centre, turns in standing
            if part_id not in removed
        ],
        "changes": [
            {"identity": part_id, "removed": True, "centre_mm": None, "quarter_turns": 0}
            for part_id in removed
        ],
    }


def parts_read(world):
    return [path for _, path, _ in world.requests if path.split("?")[0] == PARTS]


def captured(world, *, readable=True, known=None):
    with WorldReader(world.url, TOKEN, WORLD) as reader:
        return capture(
            reader,
            version_id=VERSION,
            project_id="project:demo",
            thing_ids=["knight:1"],
            include_decisions=False,
            readable=readable,
            parts_known=known,
        ).checkpoint


def test_a_made_world_s_parts_are_kept_as_the_version_has_them(world):
    made(world, removed=("0190a1b2-c3d4-4e5f-8a9b-000000000003",))
    project = captured(world)
    assert project["parts"] == [
        {
            "part_id": "0190a1b2-c3d4-4e5f-8a9b-000000000001",
            "kind": "building",
            "centre_mm": [12_000, 8_000],
            "quarter_turns": 0,
            "removed": False,
            "label": "Tea house",
            "storeys": 2,
        },
        {
            "part_id": "0190a1b2-c3d4-4e5f-8a9b-000000000002",
            "kind": "fixture",
            "centre_mm": [3_000, 4_000],
            "quarter_turns": 1,
            "removed": False,
            "label": "Bench",
        },
        {
            "part_id": "0190a1b2-c3d4-4e5f-8a9b-000000000003",
            "kind": None,
            "centre_mm": None,
            "quarter_turns": 0,
            "removed": True,
        },
    ]
    # Without readable text no label is kept: a world made from words was worded from them.
    bare = captured(world, readable=False)
    assert all("label" not in part for part in bare["parts"])
    assert "Tea house" not in canonical_json(bare).decode()


def test_a_world_not_made_from_a_kind_keeps_no_parts_and_one_still_drawing_is_tried_again(world):
    world.refusals[PARTS] = (422, {"code": "parts_not_served", "detail": "not made from a kind"})
    assert "parts" not in captured(world)
    world.refusals[PARTS] = (503, {"code": "kind_work_busy", "detail": "still drawing"})
    with pytest.raises(ProjectError, match="503"):
        captured(world)


def test_parts_are_read_again_only_when_the_version_changed(world):
    made(world)
    first = captured(world)
    known = {"state_sha256": "a" * 64, "parts": first["parts"]}
    reads = len(parts_read(world))
    assert captured(world, known=known)["parts"] == first["parts"]
    assert len(parts_read(world)) == reads  # the same version state: the project's own parts
    # Another state, or the label setting changed: read again.
    captured(world, known={**known, "state_sha256": "b" * 64})
    captured(world, readable=False, known=known)
    assert len(parts_read(world)) == reads + 2
