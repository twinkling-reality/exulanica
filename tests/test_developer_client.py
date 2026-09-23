"""The developer client in ``clients/python``: standalone, discovering, narrow, proven end to end.

The client is the first milestone's developer proof: a program outside the application reads a
person's saved world, finds out from the server what it may do, edits it through the authenticated
API with a token granted only ``world.read`` and ``world.write``, and confirms the edit by reading
again. What it must not do matters as much: import the product, depend on anything outside the
standard library, send its credential anywhere but the server it was given, or record it.

The end-to-end test runs the client as a separate process with ``-S -s -E``, so no site-packages
directory is importable, against the real application served over a loopback socket, and then
checks the result from the repository rather than trusting the client's own report.
"""

from __future__ import annotations

import ast
import http.server
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = ROOT / "clients" / "python"
PACKAGE = CLIENT_ROOT / "exulanica_client"
CONTRACT = ROOT / "tests" / "snapshots" / "api-openapi.json"
CLIENT_GRANT = ["world.read", "world.write"]

sys.path.insert(0, str(CLIENT_ROOT))

from exulanica_client import (  # noqa: E402
    ClientError,
    WorldClient,
    reviewed_behaviours,
    version_edits,
)
from exulanica_client.walkthrough import PLACE_OBJECT, SET_BEHAVIOUR  # noqa: E402

# -- what the client is made of --------------------------------------------------------------------


def test_the_client_imports_only_the_standard_library_and_itself():
    sources = sorted(PACKAGE.glob("*.py"))
    assert len(sources) >= 4, sources
    outside: dict[str, set[str]] = {}
    for source in sources:
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = {node.module.split(".")[0]}
            else:
                continue
            if found := names - set(sys.stdlib_module_names):
                outside.setdefault(source.name, set()).update(found)
    assert outside == {}, f"imports outside the standard library: {outside}"


# -- discovery, against the reviewed contract ------------------------------------------------------


def test_discovery_finds_the_version_edits_in_the_committed_contract():
    """Run over tests/snapshots/api-openapi.json, the document the server is held to, so a change
    to the contract that hides an edit from a client fails here as well as in review."""
    edits = {(edit.method, edit.path) for edit in version_edits(json.loads(CONTRACT.read_text()))}
    assert {PLACE_OBJECT, SET_BEHAVIOUR} <= edits
    assert all(path.startswith("/world/versions/{version_id}/") for _method, path in edits)
    # Society steps and actions also carry a base_state_sha256, of the society's state, and a
    # preview answers with a verdict rather than a version; none of them is a version edit.
    for method, path in (
        ("POST", "/world/versions/{version_id}/society/control/steps"),
        ("POST", "/world/versions/{version_id}/society/actions"),
        ("POST", "/world/versions/{version_id}/compositions/preview"),
    ):
        assert (method, path) not in edits, path
    assert len(edits) >= 10, sorted(edits)


def test_a_behaviour_is_checked_in_the_registrys_own_terms():
    [behaviour] = reviewed_behaviours(
        [
            {
                "behaviour_key": "motion.bounded-path",
                "behaviour_version": 1,
                "parameters": {
                    "travel_mm": {
                        "kind": "integer",
                        "minimum": 100,
                        "maximum": 10000,
                        "default": 1000,
                    },
                    "axis": {"kind": "choice", "choices": ["x", "y", "z"], "default": "x"},
                    "loop": {"kind": "shape", "default": 0},
                },
            }
        ]
    )
    assert behaviour.identity == "motion.bounded-path@1"
    assert behaviour.problems({"travel_mm": 10001, "axis": "w", "loop": 0, "speed": 2}) == [
        "speed is not a parameter of motion.bounded-path@1",
        "travel_mm must be between 100 and 10000",
        "axis must be one of x, y, z",
        "loop has a kind this client does not know: 'shape'",
    ]


# -- the credential stays with the server it was given ---------------------------------------------


def test_plain_http_is_accepted_only_for_a_loopback_address():
    for address in ("http://127.0.0.1:8000", "http://localhost:8000", "http://[::1]:8000"):
        WorldClient(address, "token")
    for address in ("http://example.org", "http://10.0.0.5:8000", "ftp://127.0.0.1"):
        with pytest.raises(ClientError):
            WorldClient(address, "token")


class _Redirecting(http.server.BaseHTTPRequestHandler):
    seen: list[str | None]

    def do_GET(self) -> None:
        self.seen.append(self.headers.get("Authorization"))
        self.send_response(302)
        self.send_header("Location", "http://127.0.0.1:9/elsewhere")
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        pass


def test_a_redirect_is_refused_rather_than_followed_with_the_token():
    _Redirecting.seen = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _Redirecting)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = WorldClient(f"http://127.0.0.1:{server.server_port}", "secret-token")
        with pytest.raises(ClientError, match="not followed"):
            client.saved_worlds()
    finally:
        server.shutdown()
        thread.join()
    assert _Redirecting.seen == ["Bearer secret-token"], "exactly one request, to the server named"


# -- end to end, against the real application ------------------------------------------------------


@contextmanager
def _serving(app) -> Iterator[str]:
    """Serve ``app`` over a real loopback socket for as long as the block runs."""
    import uvicorn

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "the test server did not start"
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=30)


@pytest.fixture
def live_api(repository, spine_schema, tmp_path, monkeypatch):
    """The application over the test schema on a loopback port, with two tokens for one workspace:
    the person's, holding every permission, and the client's, holding world reads and writes."""
    from exulanica.api.app import create_app
    from exulanica.api.authorisation import load_token_directory
    from exulanica.api.services import Services
    from exulanica.store.local import LocalContentAddressedStore

    from tests_support_api import EVERY_PERMISSION, scratch_database

    _psycopg, scratch = spine_schema
    tokens = {"person": f"person-{uuid.uuid4().hex}", "client": f"client-{uuid.uuid4().hex}"}
    grants = {"person": EVERY_PERMISSION, "client": CLIENT_GRANT}
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                tokens[who]: {
                    "workspace_id": str(repository.workspace_id),
                    "actor": str(uuid.uuid4()),
                    "permissions": grants[who],
                }
                for who in tokens
            }
        ),
    )
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path / "blobs"),
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    with _serving(create_app(services, verify=False)) as url:
        yield url, tokens


def _call(url: str, token: str, method: str, path: str, body: object = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        url + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as refused:
        return refused.code, json.loads(refused.read())


@pytest.mark.postgres
def test_the_walkthrough_edits_a_saved_world_from_outside_the_application(
    live_api, repository, tmp_path
):
    from exulanica.world import SavedWorldEntryRepository, WorldObjectRepository

    url, tokens = live_api
    status, entry = _call(
        url, tokens["person"], "POST", "/world-entries/starter", {"title": "Home"}
    )
    assert status == 200, entry
    # The client's token is narrow: the library is not among what it may read.
    status, refused = _call(url, tokens["client"], "GET", "/graph")
    assert (status, refused["code"]) == (403, "not_authorised") and "library.read" in refused[
        "detail"
    ]

    transcript = tmp_path / "walkthrough.json"
    run = subprocess.run(
        [
            sys.executable,
            "-S",
            "-s",
            "-E",
            "-m",
            "exulanica_client",
            "walkthrough",
            "--base-url",
            url,
            "--asset-key",
            "cc0.marker-cube",
            "--origin-role",
            "fictional",
            "--place",
            "0,0,2000",
            "--object-id",
            "developer-client:lantern",
            "--transcript",
            str(transcript),
        ],
        cwd=CLIENT_ROOT,
        env={"EXULANICA_TOKEN": tokens["client"], "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    record = json.loads(transcript.read_text())
    assert record["result"] == "confirmed"
    assert all(check["holds"] for check in record["checks"]), record["checks"]
    assert record["refusal"]["status"] == 422
    assert record["refusal"]["code"] == "invalid_object_data"
    assert record["refusal"]["detail"] == "behaviour motion.bounded-path@2 is not reviewed"
    steps = [(e["step"], e["method"], e["status"]) for e in record["exchanges"]]
    assert ("place", "POST", 201) in steps and ("motion", "POST", 200) in steps
    assert ("unsupported", "POST", 422) in steps

    # Held against the repository, not the client's own account of what happened.
    stored = WorldObjectRepository(
        repository.connection, repository.workspace_id, world_id=entry["world_id"]
    ).version(uuid.UUID(entry["authored_version_id"]))
    [lantern] = stored.objects
    assert (lantern.object_id, lantern.origin.role, lantern.removed) == (
        "developer-client:lantern",
        "fictional",
        False,
    )
    assert (lantern.transform.x_mm, lantern.transform.y_mm, lantern.transform.z_mm) == (0, 0, 2000)
    assert lantern.behaviour is not None
    assert (lantern.behaviour.behaviour_key, lantern.behaviour.behaviour_version) == (
        "motion.bounded-path",
        1,
    )
    assert [edit.kind for edit in stored.edits] == ["add_object", "set_object_behaviour"]
    reopened = SavedWorldEntryRepository(repository.connection, repository.workspace_id).entry(
        uuid.UUID(entry["entry_id"])
    )
    assert (reopened.authored_state_sha256, reopened.authored_edit_seq) == (
        stored.state_sha256,
        stored.edit_seq,
    )

    everything = run.stdout + run.stderr + transcript.read_text()
    assert tokens["client"] not in everything and tokens["person"] not in everything
    assert '"actor"' not in everything and '"created_by"' not in everything
