"""The second client: standalone, honest about stale bases, and quiet about its credential.

``scripts/world_client_example.py`` is the developer proof, so what it must not do matters as
much as what it does. It must not import the product, it must not retry a refused edit blind,
and it must not print or record the bearer token. The live run against the reference copy is
retained in the evaluation record; these tests hold the same behaviour on every commit.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "world_client_example.py"
CUBE = "b41289ac10548cf698d46a15206caa8e744b0b800f4ac29260c99f18d8b831d9"
TOKEN = "client-example-token-long-enough-for-tests"
VERSION = "0191a6f0-0000-7000-8000-000000000001"


def _client_module() -> Any:
    spec = importlib.util.spec_from_file_location("world_client_example", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs: a dataclass resolves its string annotations through
    # sys.modules, and a module loaded from a path is otherwise not in it.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_client_imports_only_the_standard_library_and_httpx():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert "exulanica" not in imported
    assert imported - set(sys.stdlib_module_names) == {"httpx"}


# -- the stale-base path, against a scripted server ----------------------------------------------


def _transform(x: int) -> dict[str, Any]:
    return {
        "coordinate_space": "region_local",
        "coordinate_unit": "millimetre",
        "scale_milli": 1000,
        "x_mm": x,
        "y_mm": 0,
        "yaw_microradians": 0,
        "z_mm": -800,
    }


def _version(state: str, objects: list[dict[str, Any]], edits: int) -> dict[str, Any]:
    return {
        "created_at": "2026-09-11T10:00:00+00:00",
        "created_by": str(uuid.uuid4()),
        "edit_seq": edits,
        "edits": [
            {
                "actor": str(uuid.uuid4()),
                "base_state_sha256": "0" * 64,
                "edit_id": str(uuid.uuid4()),
                "edit_seq": seq,
                "element_id": None,
                "kind": "add_object" if seq == 1 else "move_object",
                "object_id": "object:probe",
                "recorded_at": "2026-09-11T10:00:00+00:00",
                "result_state_sha256": "1" * 64,
                "undone_edit_id": None,
            }
            for seq in range(1, edits + 1)
        ],
        "element_overrides": [],
        "objects": objects,
        "origin": "authored",
        "parent_version_id": None,
        "schema_version": 1,
        "source_invalidated": False,
        "source_snapshot_id": str(uuid.uuid4()),
        "state_sha256": state,
        "style_version_id": None,
        "title": "Scripted",
        "version_id": VERSION,
        "world_id": "atlas:default",
    }


def _object(x: int) -> dict[str, Any]:
    return {
        "asset": {
            "asset_key": "cc0.marker-cube",
            "availability": "available",
            "content_sha256": CUBE,
        },
        "behaviour": None,
        "object_id": "object:probe",
        "origin": {"kind": "authored", "role": "fictional"},
        "region_id": "region-a",
        "removed": False,
        "transform": _transform(x),
    }


class ScriptedServer:
    """Answers the client's requests in order, and counts the edits it was sent."""

    def __init__(self, *, moved_by_someone_else: bool) -> None:
        self.moved_by_someone_else = moved_by_someone_else
        self.moves: list[dict[str, Any]] = []
        self.reads = 0
        self.authorised = True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.authorised &= request.headers.get("Authorization") == f"Bearer {TOKEN}"
        path = request.url.path
        base = f"/world/versions/{VERSION}"
        if request.method == "GET" and path == "/world/assets":
            return httpx.Response(
                200,
                json=[
                    {
                        "asset_key": "cc0.marker-cube",
                        "availability": "available",
                        "content_sha256": CUBE,
                    }
                ],
            )
        if request.method == "GET" and path == base:
            self.reads += 1
            if self.reads == 1:
                return httpx.Response(200, json=_version("a" * 64, [], 0))
            if self.moved_by_someone_else:
                return httpx.Response(200, json=_version("c" * 64, [_object(9_000)], 2))
            if self.moves and len(self.moves) == 2:
                return httpx.Response(200, json=_version("d" * 64, [_object(2_250)], 2))
            return httpx.Response(200, json=_version("b" * 64, [_object(1_500)], 1))
        if request.method == "POST" and path == f"{base}/objects":
            return httpx.Response(201, json=_version("b" * 64, [_object(1_500)], 1))
        if request.method == "POST" and path.endswith("/move"):
            body = json.loads(request.content)
            self.moves.append(body)
            if body["base_state_sha256"] != "b" * 64 or self.moved_by_someone_else:
                return httpx.Response(
                    409, json={"code": "stale_object_base", "detail": "the base moved"}
                )
            return httpx.Response(200, json=_version("d" * 64, [_object(2_250)], 2))
        return httpx.Response(404, json={"code": "unknown_reference", "detail": path})


def _run(server: ScriptedServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple:
    monkeypatch.setenv("EXULANICA_TOKEN", TOKEN)
    transcript = tmp_path / "transcript.json"
    http = httpx.Client(base_url="http://scripted", transport=httpx.MockTransport(server))
    code = _client_module().main(
        [
            "--version",
            VERSION,
            "--origin-role",
            "fictional",
            "--object-id",
            "object:probe",
            "--region",
            "region-a",
            "--demonstrate-stale-base",
            "--transcript",
            str(transcript),
        ],
        http=http,
    )
    return code, json.loads(transcript.read_text(encoding="utf-8"))


def test_a_stale_base_is_re_read_and_the_edit_re_issued_once_when_it_still_applies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    server = ScriptedServer(moved_by_someone_else=False)
    code, transcript = _run(server, tmp_path, monkeypatch)
    assert code == 0
    assert server.authorised
    assert [move["base_state_sha256"] for move in server.moves] == ["a" * 64, "b" * 64]
    steps = [(entry["step"], entry["status"]) for entry in transcript["transcript"]]
    assert ("move", 409) in steps and steps[-2:] == [("move", 200), ("final", 200)]
    reread = next(entry for entry in transcript["transcript"] if entry["step"] == "reread")
    assert reread["note"].startswith("state is the one this client last saw")
    assert transcript["base_version"] == {"state_sha256": "a" * 64, "version_id": VERSION}
    [added] = transcript["changed"]["added"]
    assert added["transform"]["x_mm"] == 2_250, "net change: one object, where it ended up"
    add, move = transcript["this_client"]
    assert (add["at"]["x_mm"], move["from"]["x_mm"], move["to"]["x_mm"]) == (1_500, 1_500, 2_250)
    assert move["refused_first_with_stale_base"] is True
    assert move["base_state_sha256"] == add["result_state_sha256"] == "b" * 64
    printed = capsys.readouterr().out
    assert TOKEN not in printed and TOKEN not in json.dumps(transcript)
    assert "actor" not in json.dumps(transcript) and "created_by" not in json.dumps(transcript)


def test_a_stale_base_after_someone_else_moved_the_object_stops_rather_than_overwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    server = ScriptedServer(moved_by_someone_else=True)
    code, transcript = _run(server, tmp_path, monkeypatch)
    assert code == 1
    assert len(server.moves) == 1, "a refused edit must not be retried over another writer's"
    assert transcript["result"] == "stopped"
    assert "was moved by another edit" in transcript["reason"]
    assert "another writer edited the version" in capsys.readouterr().out


def test_the_client_refuses_to_run_without_a_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("EXULANICA_TOKEN", raising=False)
    assert _client_module().main(["--version", VERSION, "--origin-role", "fictional"]) == 2


# -- the real API ----------------------------------------------------------------------------------


@pytest.mark.postgres
def test_the_client_makes_an_accepted_change_through_the_real_api(
    repository,
    spine_schema,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    from exulanica.api.app import create_app
    from exulanica.api.authorisation import load_token_directory
    from exulanica.api.services import Services
    from exulanica.store.local import LocalContentAddressedStore
    from exulanica.world import WorldObjectRepository, WorldStructureRepository
    from fastapi.testclient import TestClient

    from tests_support_api import scratch_database
    from world_structure_fixtures import structural_candidate

    _psycopg, scratch = spine_schema
    actor = uuid.uuid4()
    structures = WorldStructureRepository(repository.connection, repository.workspace_id)
    preview = structures.preview(structural_candidate(), proposed_by=actor)
    snapshot = structures.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=actor,
    )
    version = WorldObjectRepository(repository.connection, repository.workspace_id).create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Second client", created_by=actor
    )
    repository.connection.commit()
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps({TOKEN: {"workspace_id": str(repository.workspace_id), "actor": str(actor)}}),
    )
    monkeypatch.setenv("EXULANICA_TOKEN", TOKEN)
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path / "blobs"),
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    transcript = tmp_path / "transcript.json"
    with TestClient(create_app(services, verify=False)) as http:
        code = _client_module().main(
            [
                "--title",
                "Second client",
                "--origin-role",
                "fictional",
                "--object-id",
                "second-client:marker",
                "--region",
                "region-a",
                "--motion",
                "travel_mm=600,period_milliseconds=3000,axis=x,easing=smooth",
                "--demonstrate-stale-base",
                "--transcript",
                str(transcript),
            ],
            http=http,
        )
    assert code == 0
    recorded = json.loads(transcript.read_text(encoding="utf-8"))
    statuses = [(e["step"], e["status"]) for e in recorded["transcript"]]
    assert ("add", 201) in statuses and ("move", 409) in statuses and ("move", 200) in statuses
    refused = next(e for e in recorded["transcript"] if e["status"] == 409)
    assert refused["problem"]["code"] == "stale_object_base"

    stored = WorldObjectRepository(repository.connection, repository.workspace_id).version(
        version.version_id
    )
    [obj] = stored.objects
    assert (obj.object_id, obj.transform.x_mm, obj.transform.z_mm) == (
        "second-client:marker",
        2_250,
        -800,
    )
    assert obj.behaviour is not None and obj.behaviour.parameters["travel_mm"] == 600
    assert [e.kind for e in stored.edits] == ["add_object", "move_object"]
    assert recorded["changed"]["state_sha256"]["after"] == stored.state_sha256
    everything = capsys.readouterr().out + transcript.read_text(encoding="utf-8")
    assert TOKEN not in everything and str(actor) not in everything
