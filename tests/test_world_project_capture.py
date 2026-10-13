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

    def answer(self, handler):
        parts = urlsplit(handler.path)
        query = parse_qs(parts.query)
        self.requests.append((handler.command, handler.path, handler.headers.get("Authorization")))
        if handler.headers.get("Authorization") != f"Bearer {TOKEN}":
            return 401, {"code": "unauthorized"}
        if parts.path != "/world-entries" and query.get("world_id") != [WORLD]:
            return 422, {"code": "world_id"}
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
