#!/usr/bin/env python3
"""The foundation acceptance driver: a matrix's rows, checked against a running acceptance stack.

    python3 scripts/acceptance/foundation.py baseline --worktree PATH --out DIR
    python3 scripts/acceptance/foundation.py isolation-client --base-url URL --token-file FILE
                                                      --own OWN.json --foreign FOREIGN.json
                                                      --rounds N --out FILE

``baseline`` checks the rows that need no delivery beyond the candidate itself (world kinds, the
no-model mode, workspace isolation, the edit lifecycle and the observable half of the connected
journey) against the stack ``launch.py up`` started for ``--worktree``, which must have been started
with ``--workspaces 2 --read-only-token --tiles``. It restarts that stack's API with
``launch.py restart-api`` where a row needs a fresh process, and leaves the stack running.

Every row ends ``passed``, ``failed`` or ``blocked``; a row whose prerequisite is absent is blocked
with the missing prerequisite named, never passed. A row passes only when every outcome it lists was
observed. Nothing here makes a timing claim.

The driver is an independent client: it imports nothing from ``exulanica``, speaks HTTP through the
repository's standard-library developer client (``clients/python``), and holds no credential outside
the request header. Its only other reads are evidence reads, marked as such: the run database dumped
through the owner URL the launcher recorded, and the run's store directory listed, each used only to
show that an operation said to write nothing wrote nothing. Each such claim is preceded by a control
that shows the evidence method sees no change across a plain read.

``isolation-client`` is one workspace's client in the concurrent isolation check, run by ``baseline``
as a separate process for each workspace at once. It edits its own world and probes the other
workspace's identities, and writes what it saw.

Outputs under ``--out``: ``results.json`` (every row), ``transcripts/<client>.jsonl`` (every exchange
without a credential), ``evidence/`` (digests and command outputs) and ``manifest.json`` (the tree,
the driver's own digest and the launcher run it checked).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]
sys.path.insert(0, str(REPOSITORY / "clients" / "python"))

from exulanica_client.client import ClientError, Exchange, WorldClient  # noqa: E402


def _launcher() -> Any:
    spec = importlib.util.spec_from_file_location("exulanica_acceptance_launch", HERE / "launch.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LAUNCH = _launcher()
#: This file's digest as the run began. Child processes re-read the file, so a run records whether
#: it changed before the run ended, and a changed one is not evidence of the code it names.
DRIVER_SHA256_AT_START = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

#: The row states a result may take. There is no skipped state.
STATES = ("passed", "failed", "blocked")
#: The authored starter's one region, and the society engine a saved world creates.
STARTER_REGION = "region:starter"
SAVED_WORLD_SOCIETY = "exulanica-society/v2"
#: How many simulated minutes N1.d may advance before the response is declared not observed.
JOURNEY_MINUTES_MAXIMUM = 60
#: How many generated towns the count policy allows a workspace; the next is refused.
GENERATED_WORLDS_ALLOWED = 3
#: How long the tile worker may take to bake the towns' tiles before A2's bake outcome fails.
BAKE_SECONDS = 900
#: Rounds each isolation client edits and probes.
ISOLATION_ROUNDS = 5
#: The events route's own ceiling on one read.
EVENTS_LIMIT = 256
#: The approved synthetic source fixture (root, 2026-09-30): the rehearsal's drawn photographs by
#: file name and the digest the landed rehearsal record states for each. A drawn file with any other
#: digest blocks A3 rather than standing in for it.
SOURCE_FIXTURE = {
    "mireland-01-nameplate.jpg": "721e888c86b76f92d63e9569878e21a1ce668af8c0a8c55f72c859c369d712ae",
    "mireland-02-nameplate-tree.jpg": (
        "5d2d3d52cb9b6ea2702edc4367d8bc74169eb10dda598c65a070fcc8faf119d4"
    ),
    "mireland-04-no-text.jpg": "3b6ad01fc14cb3ff6b341fda7fc4ec281f729aaa7f75edb5603e9f54471c9946",
}
#: Who the A3 review names: a disclosed stand-in for synthetic fixtures, never a person.
STAND_IN_REVIEWER = "Q10 acceptance stand-in reviewer (synthetic fixture)"
#: How long the derivative worker may take to group the fixture's scenes.
GROUPING_SECONDS = 300
#: F1's reads (interface packet v1.2), by the path the server's OpenAPI document serves them under.
CAPABILITIES_ROUTE = "/worlds/capabilities"
VERSION_CAPABILITIES_ROUTE = "/world/versions/{version_id}/capabilities"
INPUT_PROVENANCE_ROUTE = "/world/versions/{version_id}/society/inputs/{input_seq}"
OBJECT_ADD = "POST /world/versions/{version_id}/objects"
MODEL_CHOICE = "POST /world/versions/{version_id}/models/{role_key}"
#: W7's clock coupling write, and the client-example digest W7 delivered (delivery 1, A-19).
CLOCK_ROUTE = "/world/versions/{version_id}/clock"
W7_CLIENT_SHA256 = "f20e98b7bbcef3c14afcd54b84fbe46833da7bc4ae39370327c2ed16597ab9da"
#: How long the driver waits for the host's traffic to follow the stepped people.
FOLLOW_SECONDS = 120
#: M7's project routes, the peer token the launcher writes, and the tests F3 and F4 re-run.
PROJECTS_ROUTE = "/world/projects"
PEER_TOKEN = "token-peer"
M7_LANE_TESTS = (
    "tests/test_developer_client_project_context.py",
    "tests/test_project_context_api.py",
    "tests/test_project_context_erasure.py",
)
F4_TESTS = (
    "tests/test_companion_memory_policy_boundary.py",
    "tests/test_project_context_policy_boundary.py",
)
F4_CONTRACT = "A world project's context cannot author policy, grant a permission or call a model"
#: A region no world lists, for the unlisted-region refusal.
UNLISTED_REGION = "region:q10-unlisted"
#: The restrict key every evidence dump is made with, so two dumps of one database are equal.
EVIDENCE_RESTRICT_KEY = "q10evidence"
#: A digest no state has, for stale-base refusals.
STALE_SHA256 = "0" * 64

#: Where each placed object stands: on the starter's ground plane (x, z), at the ground's height
#: (y is up), and one floating 3 m above it for the off-ground control.
PLACES = {
    "stall": (6000, 0, 0),
    "marker": (0, 0, -6000),
    "lamp": (-6000, 0, -4000),
    "bench": (-6000, 0, 4000),
    "bench_floating": (6000, 3000, 6000),
}


# -- records ---------------------------------------------------------------------------------------


@dataclass
class Row:
    """One matrix row's result, with what was expected and what was seen."""

    row: str
    check: str
    expected: str
    status: str = "blocked"
    observed: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)

    def expect(self, condition: bool, failure: str) -> bool:
        if not condition:
            self.failures.append(failure)
        return condition

    def close(self) -> Row:
        if self.blocked_by:
            self.status = "blocked"
        else:
            self.status = "failed" if self.failures else "passed"
        return self

    def document(self) -> dict[str, Any]:
        assert self.status in STATES
        return {
            "row": self.row,
            "check": self.check,
            "status": self.status,
            "expected": self.expected,
            "failures": self.failures,
            "blocked_by": self.blocked_by,
            "observed": self.observed,
        }


class Transcripts:
    """Every exchange of every client, by client name, as JSON lines. Never a credential."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def recorder(self, client: str, step: Callable[[], str]) -> Callable[[Exchange], None]:
        path = self.directory / f"{client}.jsonl"

        def record(exchange: Exchange) -> None:
            entry = {
                "at": dt.datetime.now(dt.UTC).isoformat(),
                "step": step(),
                "method": exchange.method,
                "path": exchange.path,
                "query": dict(exchange.query),
                "status": exchange.status,
                "request_body": exchange.request_body,
                "response_body": exchange.response_body,
            }
            with path.open("a") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")

        return record


@dataclass
class Client:
    """One workspace's HTTP client and the step it is on, for the transcript."""

    name: str
    http: WorldClient
    step: str = "start"

    def call(
        self,
        step: str,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: object = None,
    ) -> tuple[int, Any]:
        self.step = step
        return self.http.request(method, path, query=query, body=body)


# -- the stack -------------------------------------------------------------------------------------


@dataclass
class Stack:
    """The running acceptance stack ``launch.py`` recorded for one checkout."""

    worktree: Path
    state: dict[str, Any]

    @classmethod
    def read(cls, worktree: Path) -> Stack:
        state_file = LAUNCH.state_dir(worktree) / "state.json"
        if not state_file.exists():
            raise SystemExit(f"no acceptance stack is recorded for {worktree}: run launch.py up")
        return cls(worktree, json.loads(state_file.read_text()))

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.state['ports']['api']}"

    @property
    def run_dir(self) -> Path:
        return Path(self.state["run_dir"])

    def token_file(self, name: str) -> Path:
        return self.run_dir / name

    def restart_api(self, revoke: str | None = None, api: str = "primary") -> dict[str, Any]:
        command = [
            sys.executable,
            str(HERE / "launch.py"),
            "restart-api",
            "--worktree",
            str(self.worktree),
            "--api",
            api,
        ]
        if revoke is not None:
            command += ["--revoke", revoke]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise SystemExit(f"restart-api failed: {completed.stderr.strip()}")
        self.state = Stack.read(self.worktree).state
        return self.state["restarts"][-1]

    def evidence_digest(self) -> dict[str, str]:
        """An evidence read: the digest of the run database's data and of the store's listing."""
        database = self.state["database"]
        dump = subprocess.run(
            [
                str(Path(database["postgres_bin"]) / "pg_dump"),
                "--data-only",
                "--no-owner",
                "--no-privileges",
                # pg_dump 18 writes a random psql restrict key into every dump unless it is given
                # one; a fixed key keeps the digest a function of the data alone.
                f"--restrict-key={EVIDENCE_RESTRICT_KEY}",
                database["owner_url_for_evidence_reads"],
            ],
            capture_output=True,
            check=True,
        ).stdout
        listing = sorted(
            f"{path.relative_to(self.state['data_dir'])}\t{path.stat().st_size}"
            for path in Path(self.state["data_dir"]).rglob("*")
            if path.is_file()
        )
        return {
            "database_data_sha256": hashlib.sha256(dump).hexdigest(),
            "store_listing_sha256": hashlib.sha256("\n".join(listing).encode()).hexdigest(),
            "store_files": str(len(listing)),
        }

    def tile_bakes(self) -> list[dict[str, Any]]:
        log = self.run_dir / "logs" / "generated-tile-worker.log"
        return [event for event in LAUNCH.tile_worker_events(log) if event.get("event") == "bake"]


def client(stack: Stack, transcripts: Transcripts, name: str, token_file: str) -> Client:
    holder: dict[str, Client] = {}
    http = WorldClient(
        stack.base_url,
        stack.token_file(token_file).read_text(),
        on_exchange=transcripts.recorder(name, lambda: holder["client"].step),
    )
    holder["client"] = Client(name, http)
    return holder["client"]


# -- shared operations -----------------------------------------------------------------------------


def resume_point(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entry_id": entry["entry_id"],
        "base_revision": entry["revision"],
        "authored_state_sha256": entry["authored_state_sha256"],
        "authored_edit_seq": entry["authored_edit_seq"],
    }


def placement(asset_key: str, subject_id: str, where: str, base: str) -> dict[str, Any]:
    x, y, z = PLACES[where]
    return {
        "base_state_sha256": base,
        "source": {"kind": "reviewed_asset", "asset_key": asset_key},
        "placement": {
            "subject_id": subject_id,
            "region_id": STARTER_REGION,
            "transform": {
                "x_mm": x,
                "y_mm": y,
                "z_mm": z,
                "yaw_microradians": 0,
                "scale_milli": 1000,
            },
            "origin_role": "fictional",
        },
    }


def world_query(entry: Mapping[str, Any]) -> dict[str, str]:
    return {"world_id": entry["world_id"]}


def version_path(entry: Mapping[str, Any], suffix: str = "") -> str:
    return f"/world/versions/{entry['authored_version_id']}{suffix}"


def read_entry(c: Client, step: str, entry_id: str) -> dict[str, Any]:
    status, body = c.call(step, "GET", f"/world-entries/{entry_id}")
    if status != 200:
        raise RuntimeError(f"{c.name} could not read its saved world {entry_id}: {status} {body}")
    return body


def apply(c: Client, step: str, entry: Mapping[str, Any], asset: str, subject: str, where: str):
    body = placement(asset, subject, where, entry["authored_state_sha256"])
    body["saved_entry"] = resume_point(entry)
    return c.call(
        step,
        "POST",
        version_path(entry, "/compositions/apply"),
        query=world_query(entry),
        body=body,
    )


def problem_code(body: Any) -> str | None:
    return body.get("code") if isinstance(body, dict) else None


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def society(c: Client, step: str, entry: Mapping[str, Any], *, places: bool = False):
    query = world_query(entry)
    if places:
        query["places"] = "true"
    return c.call(step, "GET", version_path(entry, "/society"), query=query)


def advance(c: Client, step: str, entry: Mapping[str, Any], snapshot: Mapping[str, Any]):
    return c.call(
        step,
        "POST",
        version_path(entry, "/society/steps"),
        query=world_query(entry),
        body={"base_tick": snapshot["current_tick"], "base_state_sha256": snapshot["state_sha256"]},
    )


def served_paths(c: Client) -> set[str]:
    """The paths the server's own OpenAPI document serves: whether a candidate carries a read is
    decided from the server, never assumed from a lane's plan."""
    status, document = c.call("openapi", "GET", "/openapi.json")
    return set(document.get("paths", {})) if status == 200 and isinstance(document, dict) else set()


def descriptor(read: Mapping[str, Any], operation: str) -> dict[str, Any] | None:
    return next((d for d in read.get("operations", []) if d.get("operation") == operation), None)


def events_history(c: Client, step: str, entry: Mapping[str, Any]) -> tuple[list[dict], bool]:
    """Every event, newest first, through the ``before`` cursor when the server serves one; the
    flag says whether it did (without it only the newest page exists)."""
    query = {**world_query(entry), "limit": str(EVENTS_LIMIT)}
    status, body = c.call(step, "GET", version_path(entry, "/society/events"), query=query)
    if status != 200:
        raise RuntimeError(f"events read answered {status}: {body}")
    if "next" not in body:
        return body["events"], False
    everything = list(body["events"])
    while body.get("next"):
        status, body = c.call(
            step,
            "GET",
            version_path(entry, "/society/events"),
            query={**query, "before": body["next"]},
        )
        if status != 200:
            raise RuntimeError(f"events page answered {status}: {body}")
        everything += body["events"]
    return everything, True


def events(c: Client, step: str, entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    query = {**world_query(entry), "limit": str(EVENTS_LIMIT)}
    status, body = c.call(step, "GET", version_path(entry, "/society/events"), query=query)
    if status != 200:
        raise RuntimeError(f"events read answered {status}: {body}")
    return body["events"]


def stale_refusals(
    c: Client, step: str, entry: Mapping[str, Any], asset: str, subject: str, where: str
) -> dict[str, Any]:
    """Both stale-base refusals of one apply, and nothing written by either.

    An edit bound to the saved world whose base is not the world's resume point is refused
    ``stale_saved_world_entry`` (``world/saved_entries.py``, "does not start from the saved world
    resume point"); an unbound edit against a stale version state is refused
    ``composition_blocked`` with the blocked reason ``stale_base`` as its detail
    (``world/composition_preview.py``, ``api/world_edit.py``)."""
    bound = placement(asset, subject, where, STALE_SHA256)
    bound["saved_entry"] = resume_point(entry)
    status_bound, body_bound = c.call(
        step,
        "POST",
        version_path(entry, "/compositions/apply"),
        query=world_query(entry),
        body=bound,
    )
    status_free, body_free = c.call(
        step,
        "POST",
        version_path(entry, "/compositions/apply"),
        query=world_query(entry),
        body=placement(asset, subject, where, STALE_SHA256),
    )
    unchanged = read_entry(c, step, entry["entry_id"])
    failures = []
    if not (status_bound == 409 and problem_code(body_bound) == "stale_saved_world_entry"):
        failures.append(
            f"an entry-bound stale base answered {status_bound} {problem_code(body_bound)}"
        )
    if not (
        status_free == 409
        and problem_code(body_free) == "composition_blocked"
        and isinstance(body_free, dict)
        and body_free.get("detail") == "stale_base"
    ):
        failures.append(f"an unbound stale base answered {status_free} {problem_code(body_free)}")
    if unchanged["authored_edit_seq"] != entry["authored_edit_seq"]:
        failures.append("a refused stale edit advanced the saved world")
    return {
        "entry_bound": [status_bound, problem_code(body_bound)],
        "unbound": [status_free, problem_code(body_free)],
        "failures": failures,
    }


def advance_once(row: Row, c: Client, step: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    """One simulated minute from the society's current state. A society takes a newly recorded
    input when it next advances, so what an edit did to it is read after this minute."""
    _, current = society(c, step, entry)
    status, _ = advance(c, step, entry, current)
    row.expect(status == 200, f"a minute answered {status}")
    _, with_places = society(c, step, entry, places=True)
    return with_places


def no_write_control(stack: Stack, c: Client, entry: Mapping[str, Any]) -> tuple[bool, dict]:
    """The evidence method's control: a plain read between two digests must leave them equal."""
    before = stack.evidence_digest()
    c.call("evidence-control", "GET", version_path(entry), query=world_query(entry))
    after = stack.evidence_digest()
    return before == after, {"before": before, "after": after}


# -- rows ------------------------------------------------------------------------------------------


def row_a1_starter(w1: Client, w2: Client) -> tuple[Row, dict[str, Any], dict[str, Any]]:
    row = Row(
        "A1",
        "worlds.starter",
        "An empty workspace creates its starter; the same title again returns the same entry; a "
        "second starter under another title is refused 409 saved_world_conflict; each workspace "
        "lists only its own entry.",
    )
    status, first = w1.call("A1", "POST", "/world-entries/starter", body={"title": "Q10 starter"})
    row.expect(status == 200, f"first starter answered {status}")
    status_again, again = w1.call(
        "A1", "POST", "/world-entries/starter", body={"title": "Q10 starter"}
    )
    row.expect(
        status_again == 200 and again.get("entry_id") == first.get("entry_id"),
        "the same title did not return the same entry",
    )
    status_other, other = w1.call(
        "A1", "POST", "/world-entries/starter", body={"title": "Q10 second starter"}
    )
    row.expect(
        status_other == 409 and problem_code(other) == "saved_world_conflict",
        f"a second starter answered {status_other} {problem_code(other)}",
    )
    status_w2, second = w2.call(
        "A1", "POST", "/world-entries/starter", body={"title": "Q10 journey starter"}
    )
    row.expect(status_w2 == 200, f"the second workspace's starter answered {status_w2}")
    _, listed_w1 = w1.call("A1", "GET", "/world-entries")
    _, listed_w2 = w2.call("A1", "GET", "/world-entries")
    row.expect(
        [e["entry_id"] for e in listed_w1] == [first["entry_id"]],
        "workspace 1 does not list exactly its own starter",
    )
    row.expect(
        [e["entry_id"] for e in listed_w2] == [second["entry_id"]],
        "workspace 2 does not list exactly its own starter",
    )
    row.observed = {
        "w1_entry": first.get("entry_id"),
        "w2_entry": second.get("entry_id"),
        "repeat_status": status_again,
        "second_title": [status_other, problem_code(other)],
        "kind": first.get("authored_scene", {}).get("kind"),
    }
    return row.close(), first, second


def row_a2_generated(stack: Stack, w1: Client) -> tuple[Row, list[dict[str, Any]]]:
    row = Row(
        "A2",
        "worlds.generated",
        "A value outside the served range is refused 422 naming the key and writes nothing; three "
        "small towns are created; a fourth is refused 409 world_limit_reached; the separate tile "
        "worker bakes every queued tile; each town reads identically after an API restart.",
    )
    status, specification = w1.call("A2", "GET", "/worlds/specification")
    row.expect(status == 200, f"the specification answered {status}")
    high_streets = next(
        (v for v in specification.get("values", []) if v.get("key") == "high_street_count"), None
    )
    row.expect(high_streets is not None, "the specification offers no high_street_count")
    too_many = int(high_streets["maximum"]) + 1 if high_streets else 99
    _, before = w1.call("A2", "GET", "/world-entries")
    status_range, refused = w1.call(
        "A2",
        "POST",
        "/worlds/generated",
        body={
            "recipe": "small_town",
            "title": "Q10 out of range",
            "values": {"high_street_count": too_many},
        },
    )
    _, after = w1.call("A2", "GET", "/world-entries")
    row.expect(
        status_range == 422 and "high_street_count" in json.dumps(refused),
        f"an out-of-range value answered {status_range} without naming its key",
    )
    row.expect(len(before) == len(after), "the refused creation left an entry behind")
    towns = []
    for index in range(1, GENERATED_WORLDS_ALLOWED + 1):
        status_town, town = w1.call(
            "A2",
            "POST",
            "/worlds/generated",
            body={"recipe": "small_town", "title": f"Q10 town {index}"},
        )
        row.expect(status_town == 201, f"town {index} answered {status_town} {problem_code(town)}")
        if status_town == 201:
            towns.append(town)
    status_limit, limit = w1.call(
        "A2", "POST", "/worlds/generated", body={"recipe": "small_town", "title": "Q10 town 4"}
    )
    row.expect(
        status_limit == 409 and problem_code(limit) == "world_limit_reached",
        f"a fourth town answered {status_limit} {problem_code(limit)}",
    )
    deadline = time.monotonic() + BAKE_SECONDS
    bakes: list[dict[str, Any]] = []
    expected_tiles = len(towns) * 2
    while time.monotonic() < deadline:
        bakes = stack.tile_bakes()
        if len(bakes) >= expected_tiles:
            break
        time.sleep(5)
    baked = sum(event.get("status") == "baked" for event in bakes)
    row.expect(baked >= expected_tiles, f"{baked} of {expected_tiles} tiles baked in time")
    row.expect(
        all(event.get("status") == "baked" for event in bakes),
        "a tile bake did not end baked",
    )
    before_restart = {t["entry_id"]: read_entry(w1, "A2", t["entry_id"]) for t in towns}
    restart = stack.restart_api()
    after_restart = {t["entry_id"]: read_entry(w1, "A2", t["entry_id"]) for t in towns}
    row.expect(before_restart == after_restart, "a town read differently after the API restart")
    row.observed = {
        "out_of_range": [status_range, problem_code(refused), too_many],
        "towns": [
            {
                "entry_id": t["entry_id"],
                "world_id": t["world_id"],
                "generated_ground": t.get("generated_ground"),
            }
            for t in towns
        ],
        "fourth": [status_limit, problem_code(limit)],
        "tile_bakes": {"expected": expected_tiles, "baked": baked, "events": len(bakes)},
        "restart": restart,
        "entries_identical_after_restart": before_restart == after_restart,
    }
    return row.close(), towns


def upload(stack: Stack, token_file: str, paths: Sequence[Path]) -> tuple[int, Any]:
    """``POST /intake`` as multipart form data, one ``files`` part per photograph."""
    boundary = f"q10-{uuid.uuid4().hex}"
    parts = []
    for path in paths:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
            f'filename="{path.name}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
            + path.read_bytes()
            + b"\r\n"
        )
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{stack.base_url}/intake",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {stack.token_file(token_file).read_text()}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as refused:
        return refused.code, json.loads(refused.read() or b"null")


def fixture_photographs(stack: Stack, out: Path) -> tuple[list[Path], list[str]]:
    """Draw the approved synthetic photographs with the repository's own generator, from the
    recipe the rehearsal states, and refuse any whose bytes differ from the approved digests."""
    steps = json.loads((REPOSITORY / "scripts" / "rehearsal" / "steps.json").read_text())
    recipe = [
        entry
        for session in steps["sessions"]
        for entry in (session.get("inputs") or {}).get("photographs", [])
        if f"{entry['stem']}.jpg" in SOURCE_FIXTURE
    ]
    directory = out / "evidence" / "a3-fixture"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "recipe.json").write_text(json.dumps(recipe, indent=2))
    drawn = subprocess.run(
        [
            str(stack.worktree / ".venv" / "bin" / "python"),
            str(REPOSITORY / "scripts" / "rehearsal" / "photographs.py"),
            str(directory / "recipe.json"),
            str(directory / "photographs"),
        ],
        cwd=stack.worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    (directory / "generator.txt").write_text(drawn.stdout + drawn.stderr)
    problems = [] if drawn.returncode == 0 else [f"the generator exited {drawn.returncode}"]
    paths = []
    for name, expected in SOURCE_FIXTURE.items():
        path = directory / "photographs" / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        if actual != expected:
            problems.append(f"{name} is {actual}, not the approved {expected}")
        paths.append(path)
    return paths, problems


def human_attestation(stack: Stack) -> str:
    """The review attestation, read from the candidate's own source at run time: no route serves
    it, and a retyped copy would be a second source of the words."""
    return subprocess.run(
        [
            str(stack.worktree / ".venv" / "bin" / "python"),
            "-c",
            "from exulanica.ingest.personal_admission import HUMAN_ATTESTATION as a; print(a)",
        ],
        cwd=stack.worktree,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def row_a3_source(stack: Stack, w1: Client, w2: Client, out: Path) -> Row:
    row = Row(
        "A3",
        "worlds.source",
        "With no reviewed photographs the personal-source plan offers no world. The approved "
        "synthetic photographs are uploaded, given a disclosed stand-in review (no model right), "
        "grouped by the in-process derivative worker, and composed into a personal-source world "
        "that is saved, reads identically after an API restart and is invisible to the other "
        "workspace. A second composition is refused by name.",
    )
    row.observed["review"] = (
        f"disclosed stand-in: '{STAND_IN_REVIEWER}' on synthetic fixtures; satisfies the named "
        "reviewer and exact attestation gates mechanically; it is not a human review"
    )
    row.observed["unverified"] = ["point maps (no depth right)", "captions (no model right)"]
    if stack.state.get("derivative_worker") != "in-process":
        row.blocked_by.append("the stack runs no in-process derivative worker, which groups scenes")
        return row.close()
    status_plan, plan = w1.call("A3", "GET", "/worlds/personal-source")
    row.expect(
        status_plan == 200 and plan.get("action") != "create_world",
        f"with no photographs the plan answered {status_plan} {plan.get('action')}",
    )
    paths, problems = fixture_photographs(stack, out)
    if problems:
        row.blocked_by += problems
        return row.close()
    status_upload, uploaded = upload(stack, "token", paths)
    accepted = uploaded.get("accepted", []) if isinstance(uploaded, dict) else []
    row.expect(status_upload == 202, f"intake answered {status_upload}")
    row.expect(
        sorted(a["blob_sha256"] for a in accepted) == sorted(SOURCE_FIXTURE.values()),
        "intake did not accept exactly the fixture's bytes",
    )
    _, admission = w1.call("A3", "GET", "/personal-admission")
    served = admission.get("attestation") if isinstance(admission, dict) else None
    if served:
        attestation, row.observed["attestation_source"] = served, "GET /personal-admission"
    else:
        row.expect(
            CAPABILITIES_ROUTE not in served_paths(w1),
            "a candidate carrying F1's reads serves no attestation (packet 3.7)",
        )
        attestation = human_attestation(stack)
        row.observed["attestation_source"] = "candidate source (no route served it)"
    now = dt.datetime.now(dt.UTC)
    review = {
        "members": [
            {
                "capture_id": a["capture_id"],
                "sha256": a["blob_sha256"],
                "bytes": next(
                    p.stat().st_size
                    for p in paths
                    if hashlib.sha256(p.read_bytes()).hexdigest() == a["blob_sha256"]
                ),
                "review": "no-person",
            }
            for a in accepted
        ],
        "purpose": "Q10 acceptance: compose a source world from repository synthetic fixtures",
        "authority": {
            "account_authority_basis": "Synthetic fixture drawn by the repository; no person",
            "authorized_at": (now - dt.timedelta(minutes=1)).isoformat(),
            "valid_until": (now + dt.timedelta(hours=1)).isoformat(),
        },
        "recorded_at": (now - dt.timedelta(seconds=1)).isoformat(),
        "operation": "review",
        "reviewed_by_name": STAND_IN_REVIEWER,
        "attestation": attestation,
    }
    status_review, reviewed = w1.call("A3", "POST", "/personal-admission", body=review)
    row.expect(status_review == 202, f"review answered {status_review}")
    deadline = time.monotonic() + GROUPING_SECONDS
    offer: dict[str, Any] = {}
    while time.monotonic() < deadline:
        _, offer = w1.call("A3", "GET", "/worlds/personal-source")
        if offer.get("action") == "create_world":
            break
        time.sleep(3)
    row.expect(offer.get("action") == "create_world", f"the plan offers {offer.get('action')}")
    status_compose, composed = w1.call(
        "A3",
        "POST",
        "/worlds/personal-source",
        body={"topology_digest": offer.get("topology_digest")},
    )
    row.expect(
        status_compose == 200, f"composition answered {status_compose} {problem_code(composed)}"
    )
    world_id = composed.get("world_id") if isinstance(composed, dict) else None
    entry: dict[str, Any] = {}
    if world_id:
        _, style = w1.call("A3", "GET", "/world/styles/current", query={"world_id": world_id})
        status_boot, booted = w1.call(
            "A3",
            "POST",
            "/world/versions/bootstrap",
            query={"world_id": world_id},
            body={
                "base_topology_digest": style["current_topology_digest"],
                "title": "Q10 source world",
            },
        )
        row.expect(status_boot == 200, f"bootstrap answered {status_boot}")
        status_entry, entry = w1.call(
            "A3",
            "POST",
            "/world-entries",
            body={
                "world_id": world_id,
                "title": "Q10 source world",
                "source_kind": "personal",
                "authored_version_id": booted.get("version_id"),
                "style_version_id": style["current"]["version_id"],
            },
        )
        row.expect(status_entry == 201, f"saving the entry answered {status_entry}")
    status_again, again = w1.call(
        "A3",
        "POST",
        "/worlds/personal-source",
        body={"topology_digest": offer.get("topology_digest")},
    )
    row.expect(status_again == 409, f"a second composition answered {status_again}")
    reopened: dict[str, Any] = {}
    foreign_status = None
    if entry.get("entry_id"):
        restart = stack.restart_api()
        reopened = read_entry(w1, "A3", entry["entry_id"])
        row.expect(reopened == entry, "the source world read differently after the API restart")
        foreign_status, _ = w2.call("A3", "GET", f"/world-entries/{entry['entry_id']}")
        row.expect(foreign_status == 404, f"the other workspace's read answered {foreign_status}")
        row.observed["restart"] = restart
    row.observed.update(
        {
            "plan_before": {
                "status": status_plan,
                "action": plan.get("action"),
                "refusal": plan.get("refusal") or plan.get("reason"),
            },
            "fixture": SOURCE_FIXTURE,
            "intake": [status_upload, len(accepted)],
            "review": [status_review, reviewed if status_review != 202 else "receipts"],
            "offer": {k: offer.get(k) for k in ("action", "photographs", "topology_digest")},
            "compose": [status_compose, composed],
            "entry_id": entry.get("entry_id"),
            "second_compose": [status_again, problem_code(again)],
            "other_workspace_read": foreign_status,
        }
    )
    return row.close()


def row_a4_discovery(
    stack: Stack,
    w1: Client,
    w2: Client,
    read: Client,
    worlds: Mapping[str, Mapping[str, Any]],
    out: Path,
) -> Row:
    row = Row(
        "A4",
        "discover.per_kind",
        "GET /worlds/capabilities states each world kind with the workspace's held count, the "
        "policy limit and the creation state the creation route would give; each saved world's "
        "version capabilities list its regions, every listed region is accepted by object add and "
        "an unlisted one refused 422 invalid_object_data; the society effect of object add is "
        "authored_affordance_unreachable on a generated town and not on the starter; another "
        "workspace's version answers as an invented one does; a read-only grant is not permitted "
        "to write. F1's independent client runs as row A4-client, last, because its edits are not "
        "bound to the saved worlds.",
    )
    paths = served_paths(w1)
    if CAPABILITIES_ROUTE not in paths or VERSION_CAPABILITIES_ROUTE not in paths:
        row.blocked_by.append("F1 capability projection not in this candidate (routes not served)")
        return row.close()
    status, kinds = w1.call("A4", "GET", CAPABILITIES_ROUTE)
    row.expect(status == 200, f"{CAPABILITIES_ROUTE} answered {status}")
    by_kind = {k["kind"]: k for k in kinds.get("kinds", [])}
    row.expect(
        set(by_kind) == {"personal-source", "authored-starter", "generated"},
        f"kinds listed are {list(by_kind)}",
    )
    held = {
        "authored-starter": 1,
        "generated": len(worlds.get("towns", [])),
        "personal-source": 1 if worlds.get("source") else 0,
    }
    for kind, count in held.items():
        row.expect(
            by_kind.get(kind, {}).get("held") == count,
            f"{kind} held {by_kind.get(kind, {}).get('held')}, not {count}",
        )
    starter_create = (by_kind.get("authored-starter") or {}).get("create") or {}
    row.expect(
        (starter_create.get("state"), starter_create.get("code"))
        == ("unavailable", "saved_world_conflict"),
        f"starter creation is {starter_create.get('state')} {starter_create.get('code')}",
    )
    if held["generated"] >= GENERATED_WORLDS_ALLOWED:
        town_create = (by_kind.get("generated") or {}).get("create") or {}
        row.expect(
            (town_create.get("state"), town_create.get("code"))
            == ("unavailable", "world_limit_reached"),
            f"town creation is {town_create.get('state')} {town_create.get('code')}",
        )
    _, assets = w1.call("A4", "GET", "/world/assets")
    cube = next(a for a in assets if a["asset_key"] == "cc0.marker-cube")
    reads: dict[str, Any] = {}
    candidates = [("starter", worlds["starter"])]
    candidates += [("town", worlds["towns"][0])] if worlds.get("towns") else []
    candidates += [("source", worlds["source"])] if worlds.get("source") else []
    for label, entry in candidates:
        entry = read_entry(w1, "A4", entry["entry_id"])
        path = version_path(entry, "/capabilities")
        status, caps = w1.call("A4", "GET", path, query=world_query(entry))
        row.expect(status == 200, f"{label} capabilities answered {status}")
        regions = caps.get("regions") or {}
        listed = regions.get("region_ids") or []
        row.expect(regions.get("state") == "listed" and listed, f"{label} lists no region")
        add = descriptor(caps, OBJECT_ADD) or {}
        society_effect = next((e for e in add.get("effects", []) if e.get("on") == "society"), {})
        unreachable = society_effect.get("code") == "authored_affordance_unreachable"
        row.expect(
            unreachable == (label == "town"),
            f"{label} object add society effect is {society_effect}",
        )
        placed = {}
        for region in [*listed[:1], UNLISTED_REGION]:
            # Bound to the saved world, as a person's edit is, so the world's resume point
            # advances with it and later rows edit from where it now stands.
            current = read_entry(w1, "A4", entry["entry_id"])
            status_add, added = w1.call(
                "A4",
                "POST",
                version_path(entry, "/objects"),
                query=world_query(entry),
                body={
                    "base_state_sha256": current["authored_state_sha256"],
                    "saved_entry": resume_point(current),
                    "object_id": f"a4-{label}-{len(placed)}",
                    "asset_sha256": cube["content_sha256"],
                    "region_id": region,
                    "transform": {
                        "x_mm": 0,
                        "y_mm": 0,
                        "z_mm": 0,
                        "yaw_microradians": 0,
                        "scale_milli": 1000,
                    },
                    "origin_role": "fictional",
                },
            )
            placed[region] = [status_add, problem_code(added)]
        row.expect(
            placed[listed[0]][0] in (200, 201) if listed else False,
            f"{label} refused its listed region: {placed}",
        )
        row.expect(
            placed[UNLISTED_REGION] == [422, "invalid_object_data"],
            f"{label} answered an unlisted region {placed[UNLISTED_REGION]}",
        )
        reads[label] = {
            "kind": caps.get("kind"),
            "regions": regions,
            "operations": len(caps.get("operations", [])),
            "society_effect": society_effect,
            "placements": placed,
        }
    starter = read_entry(w1, "A4", worlds["starter"]["entry_id"])
    invented = {"authored_version_id": str(uuid.uuid4()), "world_id": starter["world_id"]}
    foreign_status, foreign = w2.call(
        "A4", "GET", version_path(starter, "/capabilities"), query=world_query(starter)
    )
    made_status, made = w2.call(
        "A4", "GET", version_path(invented, "/capabilities"), query=world_query(invented)
    )
    row.expect(
        foreign_status == made_status == 404
        and without_identities(foreign, {"entry_id": "-", **starter})
        == without_identities(made, {"entry_id": "-", **invented}),
        f"another workspace's version answered {foreign_status}, an invented one {made_status}",
    )
    status_read, read_caps = read.call(
        "A4", "GET", version_path(starter, "/capabilities"), query=world_query(starter)
    )
    read_add = descriptor(read_caps, OBJECT_ADD) or {}
    row.expect(
        status_read == 200 and read_add.get("permitted") is False,
        "a read-only grant is shown object add as permitted",
    )
    row.observed = {
        "kind_order": [k["kind"] for k in kinds.get("kinds", [])],
        "kinds": {
            k: {
                "held": v.get("held"),
                "limit": v.get("limit"),
                "create": {
                    "state": (v.get("create") or {}).get("state"),
                    "code": (v.get("create") or {}).get("code"),
                },
            }
            for k, v in by_kind.items()
        },
        "versions": reads,
        "foreign_vs_invented": [foreign_status, made_status],
        "read_only_object_add_permitted": read_add.get("permitted"),
    }
    return row.close()


def resume_points(c: Client, step: str) -> dict[str, dict[str, Any]]:
    """Each saved world's availability and resume point, by entry id."""
    _, entries = c.call(step, "GET", "/world-entries")
    return {
        e["entry_id"]: {
            key: e.get(key)
            for key in (
                "availability",
                "unavailable_reason",
                "revision",
                "authored_state_sha256",
                "authored_edit_seq",
            )
        }
        for e in entries
    }


def row_a4_client(
    stack: Stack, client_of: Client, token_file: str, out: Path, own_worlds_only: bool
) -> Row:
    """F1's independent client exercising every kind, in its own process. Run after every other
    row: its edits are not bound to the saved worlds, so each world it edits reads
    ``authored_version_changed`` afterwards and an entry-bound client is refused there until the
    person adopts the version (``docs/saved-world-entry.md``). That consequence is recorded."""
    row = Row(
        "A4-client",
        "exulanica_client capabilities --exercise --origin-role fictional",
        "F1's independent client, in a process of its own with no site packages, discovers each "
        "saved world's capabilities, makes and rereads the edit each read calls available and is "
        "refused by name against the replaced base; exit 0."
        + (
            " Every saved world that existed before it ran keeps its availability and resume "
            "point (root decision, amendment A-16)."
            if own_worlds_only
            else ""
        ),
    )
    if CAPABILITIES_ROUTE not in served_paths(client_of):
        row.blocked_by.append("F1 capability projection not in this candidate (routes not served)")
        return row.close()
    _, assets = client_of.call("A4-client", "GET", "/world/assets")
    if not [a for a in assets or [] if a.get("availability") == "available"]:
        row.blocked_by.append("no reviewed asset is available on this server (amendment A-18)")
        return row.close()
    before = resume_points(client_of, "A4-client")
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            "-s",
            "-E",
            "-m",
            "exulanica_client",
            "capabilities",
            "--base-url",
            stack.base_url,
            "--exercise",
            "--origin-role",
            "fictional",
            "--transcript",
            str(out / "evidence" / "a4-capabilities-client.json"),
        ],
        cwd=REPOSITORY / "clients" / "python",
        env={
            "EXULANICA_TOKEN": stack.token_file(token_file).read_text(),
            "PATH": os.environ.get("PATH", ""),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    (out / "evidence" / "a4-capabilities-client.txt").write_text(
        completed.stdout + completed.stderr
    )
    row.expect(completed.returncode == 0, f"F1's independent client exited {completed.returncode}")
    after = resume_points(client_of, "A4-client")
    transcript_path = out / "evidence" / "a4-capabilities-client.json"
    transcript = json.loads(transcript_path.read_text()) if transcript_path.exists() else {}
    moved = sorted(entry for entry, point in before.items() if after.get(entry) != point)
    if own_worlds_only:
        row.expect(moved == [], f"{len(moved)} pre-existing saved worlds changed: {moved}")
    _, entries = client_of.call("A4-client", "GET", "/world-entries")
    row.observed = {
        "client_exit": completed.returncode,
        "own_worlds_only_expected": own_worlds_only,
        "pre_existing_worlds_changed": moved,
        "workspace_token_file": token_file,
        "made": (transcript.get("made") if isinstance(transcript, dict) else None),
        "saved_worlds_after": [
            {
                "title": e.get("title"),
                "availability": e.get("availability"),
                "unavailable_reason": e.get("unavailable_reason"),
            }
            for e in entries
        ],
    }
    return row.close()


def row_g1_g3_clock(
    stack: Stack, w1: Client, towns: Sequence[Mapping[str, Any]], out: Path, client: Path | None
) -> list[Row]:
    """G1 and G3 by W7's procedure (amendment A-20): one coupling process, then two reading
    processes at once after traffic has followed, judged by their printed lines."""
    g1 = Row(
        "G1",
        "clock.pause_advance_reopen",
        "A paused town is coupled and stepped four minutes by one client; once traffic has "
        "followed, two clients started at once print the identical last sealed minute's frames "
        "digest and the same frames on a second read; traffic always follows.",
    )
    g3 = Row(
        "G3",
        "clock.replay_zero_call",
        "Every verify receipt reports model_client null and verified traffic and society replay, "
        "and the scripted transport made no call while the two reading clients ran verify.",
    )
    rows = [g1, g3]
    if CLOCK_ROUTE not in served_paths(w1):
        for row in rows:
            row.blocked_by.append("W7 clock routes not in this candidate")
        return [row.close() for row in rows]
    if client is None or not client.is_file():
        for row in rows:
            row.blocked_by.append("W7 client-example not supplied (--w7-client)")
        return [row.close() for row in rows]
    digest = hashlib.sha256(client.read_bytes()).hexdigest()
    if digest != W7_CLIENT_SHA256:
        for row in rows:
            row.blocked_by.append(f"W7 client-example digest {digest} is not the delivered one")
        return [row.close() for row in rows]
    if not stack.state.get("society_playback") or not towns:
        for row in rows:
            row.blocked_by.append("the stack lists no society-control workspace or holds no town")
        return [row.close() for row in rows]
    town = read_entry(w1, "G1", towns[0]["entry_id"])
    status, _ = w1.call(
        "G1",
        "POST",
        version_path(town, "/society"),
        query=world_query(town),
        body={"region_id": "region:generated", "profile": "exulanica-society/v5"},
    )
    g1.expect(status == 200, f"the town's living society answered {status}")
    scripted = stack.state.get("scripted_model")
    log = Path(scripted["log"]) if isinstance(scripted, Mapping) else None

    def calls() -> int | None:
        return len(log.read_text().splitlines()) if log and log.exists() else (0 if log else None)

    def command(minutes: int) -> list[str]:
        return [
            sys.executable,
            str(client),
            stack.base_url,
            town["world_id"],
            town["authored_version_id"],
            str(minutes),
        ]

    # The token travels in the environment, never on a command line.
    environment = {
        "EXULANICA_TOKEN": stack.token_file("token").read_text(),
        "PATH": os.environ.get("PATH", ""),
    }

    first = subprocess.run(command(4), env=environment, capture_output=True, text=True, check=False)
    (out / "evidence" / "g1-client-a.txt").write_text(first.stdout + first.stderr)
    g1.expect(first.returncode == 0, f"the coupling client exited {first.returncode}")
    g1.expect("traffic has not followed" not in first.stdout, "traffic did not follow the steps")
    deadline = time.monotonic() + FOLLOW_SECONDS
    clock: dict[str, Any] = {}
    while time.monotonic() < deadline:
        _, clock = w1.call("G1", "GET", version_path(town, "/clock"), query=world_query(town))
        if (clock.get("traffic") or {}).get("state") == "waiting_for_society":
            break
        time.sleep(1)
    g1.expect(
        (clock.get("traffic") or {}).get("state") == "waiting_for_society",
        f"traffic did not reach waiting_for_society: {clock.get('traffic')}",
    )
    # Counted across the two readers alone: the coupling client's steps may legitimately ask a
    # person's chosen model, while verify holds no model client (W7, A-20).
    before_calls = calls()
    readers = [
        subprocess.Popen(
            command(0), env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for _ in range(2)
    ]
    printed = [reader.communicate() for reader in readers]
    after_calls = calls()
    frames, verifies = [], []
    for index, ((stdout, stderr), reader) in enumerate(zip(printed, readers, strict=True)):
        (out / "evidence" / f"g1-client-{'bc'[index]}.txt").write_text(stdout + stderr)
        g1.expect(reader.returncode == 0, f"reader {'BC'[index]} exited {reader.returncode}")
        g1.expect(
            "same frames on a second read: True" in stdout,
            f"reader {'BC'[index]} saw different frames on a second read",
        )
        frame = re.findall(r"minute (\d+) frames (\w+)", stdout)
        frames.append(frame[-1] if frame else None)
        verifies += [line for line in stdout.splitlines() if line.startswith("verify:")]
    verifies += [line for line in first.stdout.splitlines() if line.startswith("verify:")]
    g1.expect(
        frames[0] is not None and frames[0] == frames[1],
        f"the two readers printed {frames}",
    )
    receipts = []
    for line in verifies:
        try:
            receipts.append(json.loads(line.split(" ", 2)[2]))
        except (IndexError, ValueError):
            g3.failures.append(f"an unreadable verify line: {line[:120]}")
    g3.expect(len(receipts) == 3, f"{len(receipts)} verify receipts printed, not 3")
    for receipt in receipts:
        g3.expect(
            "model_client" in receipt and receipt["model_client"] is None,
            "a verify receipt names a model client",
        )
        g3.expect(
            (receipt.get("traffic") or {}).get("verified") is True,
            "a verify receipt did not verify traffic",
        )
        g3.expect(
            (receipt.get("society") or {}).get("replayed") is True,
            "a verify receipt did not replay the society",
        )
    if before_calls is not None and after_calls is not None:
        g3.expect(
            after_calls == before_calls,
            f"the scripted transport was called {after_calls - before_calls} times",
        )
    g1.observed = {
        "town": town["world_id"],
        "clock": clock,
        "frames": frames,
        "client_sha256": digest,
    }
    g3.observed = {
        "receipts": receipts,
        "scripted_calls": [before_calls, after_calls],
        "model_client_on_stack": log is not None,
    }
    return [row.close() for row in rows]


def row_f3_context(
    stack: Stack,
    w1: Client,
    w2: Client,
    peer_of: Callable[[], Client],
    entry: Mapping[str, Any],
    out: Path,
) -> Row:
    """F3 by M7's delivery (amendment A-10): two client processes either side of an API restart,
    then what another actor, another workspace and a stale writer are told, and the raw tables."""
    row = Row(
        "F3",
        "context.continuity",
        "M7's client records a project on a saved world in one process and, after an API restart, "
        "resumes it in another: the decision still names the same edit, the goal is corrected, the "
        "question is deleted and absent from every read. Another actor in the workspace and "
        "another workspace are answered as for an invented project; a stale writer is refused "
        "409 stale_project_context; the deleted words are in no project table; a revoked token is "
        "refused 401. M7's lane tests pass on the candidate.",
    )
    if PROJECTS_ROUTE not in served_paths(w1):
        row.blocked_by.append("M7 project routes not in this candidate")
        return row.close()
    if "peer_token" not in stack.state:
        row.blocked_by.append("the stack was started without --peer-token")
        return row.close()
    note = out / "evidence" / "f3-note.json"
    question = f"Q10 continuity question {uuid.uuid4().hex}?"
    environment = {
        "EXULANICA_TOKEN": stack.token_file("token").read_text(),
        "PATH": os.environ.get("PATH", ""),
    }
    base = [sys.executable, "-S", "-s", "-E", "-m", "exulanica_client.project_context"]
    recorded = subprocess.run(
        [
            *base,
            "record",
            "--base-url",
            stack.base_url,
            "--note",
            str(note),
            "--entry-id",
            entry["entry_id"],
            "--question",
            question,
            "--transcript",
            str(out / "evidence" / "f3-record.json"),
        ],
        cwd=REPOSITORY / "clients" / "python",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    restart = stack.restart_api()
    resumed = subprocess.run(
        [
            *base,
            "resume",
            "--base-url",
            stack.base_url,
            "--note",
            str(note),
            "--transcript",
            str(out / "evidence" / "f3-resume.json"),
        ],
        cwd=REPOSITORY / "clients" / "python",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    (out / "evidence" / "f3-clients.txt").write_text(
        recorded.stdout + recorded.stderr + "\n----\n" + resumed.stdout + resumed.stderr
    )
    row.expect(recorded.returncode == 0, f"record exited {recorded.returncode}")
    row.expect(resumed.returncode == 0, f"resume exited {resumed.returncode}")
    kept = json.loads(note.read_text()) if note.exists() else {}
    project, world = kept.get("project_id"), kept.get("world_id") or entry["world_id"]
    query = {"world_id": world}
    peer = peer_of()
    invented = str(uuid.uuid4())
    _, peer_list = peer.call("F3", "GET", PROJECTS_ROUTE, query=query)
    peer_status, peer_body = peer.call("F3", "GET", f"{PROJECTS_ROUTE}/{project}", query=query)
    made_status, made_body = peer.call("F3", "GET", f"{PROJECTS_ROUTE}/{invented}", query=query)
    other_status, _ = w2.call("F3", "GET", f"{PROJECTS_ROUTE}/{project}", query=query)
    row.expect(peer_list == [], f"another actor lists {peer_list}")
    row.expect(
        peer_status == made_status == 404
        and json.dumps(peer_body).replace(str(project), "<id>")
        == json.dumps(made_body).replace(invented, "<id>"),
        f"another actor's read {peer_status}, an invented one {made_status}",
    )
    row.expect(other_status == 404, f"another workspace's read answered {other_status}")
    _, current = w1.call("F3", "GET", f"{PROJECTS_ROUTE}/{project}", query=query)
    stale_status, stale_body = w1.call(
        "F3",
        "PUT",
        f"{PROJECTS_ROUTE}/{project}",
        query=query,
        body={
            "base_revision": max(1, int(current.get("revision", 2)) - 1),
            "title": current.get("title", "Q10"),
            "version_id": (current.get("binding") or {}).get("version_id"),
        },
    )
    row.expect(
        stale_status == 409 and problem_code(stale_body) == "stale_project_context",
        f"a stale write answered {stale_status} {problem_code(stale_body)}",
    )
    database = stack.state["database"]
    tables = subprocess.run(
        [
            str(Path(database["postgres_bin"]) / "pg_dump"),
            "--data-only",
            "--no-owner",
            f"--restrict-key={EVIDENCE_RESTRICT_KEY}",
            "-t",
            "world_project*",
            database["owner_url_for_evidence_reads"],
        ],
        capture_output=True,
        check=True,
    ).stdout
    row.expect(question.encode() not in tables, "the deleted question survives in a table")
    revoked = stack.restart_api(revoke=PEER_TOKEN)
    revoked_status, _ = peer_of().call("F3", "GET", PROJECTS_ROUTE, query=query)
    restored = stack.restart_api()
    row.expect(revoked_status == 401, f"the revoked token answered {revoked_status}")
    lane = subprocess.run(
        [
            str(stack.worktree / ".venv" / "bin" / "python"),
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            *M7_LANE_TESTS,
        ],
        cwd=stack.worktree,
        env={
            **LAUNCH.clean_environment(),
            "EXULANICA_TEST_POSTGRES": "private",
            "EXULANICA_REQUIRE_POSTGRES": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    (out / "evidence" / "f3-lane-tests.txt").write_text(lane.stdout + lane.stderr)
    row.expect(lane.returncode == 0, f"M7's lane tests exited {lane.returncode}")
    row.observed = {
        "project": project,
        "record_exit": recorded.returncode,
        "resume_exit": resumed.returncode,
        "restart": restart,
        "peer": {"list": peer_list, "read": peer_status, "invented": made_status},
        "other_workspace": other_status,
        "stale": [stale_status, problem_code(stale_body)],
        "question_in_tables": question.encode() in tables,
        "revoked": revoked_status,
        "restarts": [revoked, restored],
        "lane_tests_exit": lane.returncode,
    }
    return row.close()


def row_f4_boundary(out: Path, worktree: Path) -> Row:
    """F4: the two policy-boundary tests and the import contract over the context modules."""
    row = Row(
        "F4",
        "context.policy_boundary",
        "The unchanged Companion memory boundary test, M7's project-context boundary test and the "
        "import contract that keeps project context from authoring policy pass on the candidate.",
    )
    tests = subprocess.run(
        [
            str(worktree / ".venv" / "bin" / "python"),
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            *F4_TESTS,
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
    )
    contracts = subprocess.run(
        [str(worktree / ".venv" / "bin" / "lint-imports")],
        cwd=worktree,
        env=LAUNCH.clean_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    (out / "evidence" / "f4.txt").write_text(
        tests.stdout + tests.stderr + "\n----\n" + contracts.stdout + contracts.stderr
    )
    # lint-imports wraps long contract names across lines; read it as one run of words.
    flowing = " ".join(contracts.stdout.split())
    kept = [f"{F4_CONTRACT} KEPT"] if f"{F4_CONTRACT} KEPT" in flowing else []
    row.expect(tests.returncode == 0, f"the boundary tests exited {tests.returncode}")
    row.expect(contracts.returncode == 0, f"lint-imports exited {contracts.returncode}")
    row.expect(any("KEPT" in line for line in kept), f"the project-context contract reads {kept}")
    row.observed = {"tests_exit": tests.returncode, "contract": kept}
    return row.close()


def row_b1_no_model(
    stack: Stack,
    w1: Client,
    starter: Mapping[str, Any],
    town: Mapping[str, Any] | None,
    w2: Client,
    peopled: Mapping[str, Any],
) -> Row:
    row = Row(
        "B1",
        "mode.no_model",
        "With no provider key the API serves; model routes answer a structured unavailable state "
        "(models_not_run_here or provider_credential_absent) and the Companion's model path "
        "refuses; direct edits still work (D1, N1).",
    )
    status_ready, ready = w1.call("B1", "GET", "/readyz")
    row.expect(status_ready == 200, f"/readyz answered {status_ready}")
    worlds = [("starter", starter)] + ([("town", town)] if town else [])
    models = {}
    for label, entry in worlds:
        status, body = w1.call(
            "B1", "GET", version_path(entry, "/models"), query=world_query(entry)
        )
        models[label] = {"status": status, "body": body}
        text = json.dumps(body)
        row.expect(status == 200, f"{label} models answered {status}")
        row.expect(
            "models_not_run_here" in text or "provider_credential_absent" in text,
            f"{label} models states no unavailable reason",
        )
    decisions: dict[str, Any] = {"served": VERSION_CAPABILITIES_ROUTE in served_paths(w1)}
    if decisions["served"]:
        # The decisions effect concerns people, so it is read on the world that holds a society.
        _, caps = w2.call(
            "B1", "GET", version_path(peopled, "/capabilities"), query=world_query(peopled)
        )
        choice = next(
            (
                d
                for d in caps.get("operations", [])
                if d.get("operation") == MODEL_CHOICE and d.get("subject") == "person"
            ),
            {},
        )
        effect = next((e for e in choice.get("effects", []) if e.get("on") == "decisions"), {})
        row.expect(choice.get("state") == "available", "the person model choice is not available")
        row.expect(
            effect.get("state") == "unavailable"
            and effect.get("code") in ("models_not_run_here", "provider_credential_absent"),
            f"the decisions effect is {effect}",
        )
        decisions |= {"choice_state": choice.get("state"), "decisions_effect": effect}
    status_ask, asked = w1.call(
        "B1",
        "POST",
        "/selection/ask",
        query=world_query(starter),
        body={"question": "What is in this world?"},
    )
    row.expect(status_ask == 503, f"a model question answered {status_ask}")
    row.observed = {
        "readyz_status": status_ready,
        "readyz": ready,
        "models": models,
        "ask": {"status": status_ask, "body": asked, "has_code": problem_code(asked) is not None},
        "launcher_model_flag": stack.state.get("model"),
        "decisions": decisions,
    }
    return row.close()


def row_c2_client(stack: Stack, w1_entry: Mapping[str, Any], out: Path, read: Client) -> Row:
    row = Row(
        "C2",
        "client.compat",
        "The unchanged developer client (python -S -s -E) discovers and completes its walkthrough "
        "against a starter (exit 0); a world.read token reads the world and is refused a write "
        "before it runs.",
    )
    environment = {
        "EXULANICA_TOKEN": stack.token_file("token").read_text(),
        "PATH": os.environ.get("PATH", ""),
    }
    base = [sys.executable, "-S", "-s", "-E", "-m", "exulanica_client"]
    runs = {}
    for name, arguments in (
        ("discover", ["discover", "--base-url", stack.base_url]),
        (
            "walkthrough",
            [
                "walkthrough",
                "--base-url",
                stack.base_url,
                "--origin-role",
                "fictional",
                "--place",
                ",".join(str(v) for v in PLACES["marker"]),
                "--asset-key",
                "cc0.marker-cube",
                "--entry",
                w1_entry["entry_id"],
                "--transcript",
                str(out / "evidence" / "developer-client-walkthrough.json"),
            ],
        ),
    ):
        completed = subprocess.run(
            base + arguments,
            cwd=REPOSITORY / "clients" / "python",
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        (out / "evidence" / f"developer-client-{name}.txt").write_text(
            completed.stdout + completed.stderr
        )
        runs[name] = completed.returncode
        row.expect(
            completed.returncode == 0,
            f"the unchanged client's {name} exited {completed.returncode}",
        )
    status_read, _ = read.call("C2", "GET", "/world-entries")
    entry = w1_entry
    body = placement("cc0.marker-pillar", "read-only-attempt", "stall", STALE_SHA256)
    status_write, refused = read.call(
        "C2",
        "POST",
        version_path(entry, "/compositions/apply"),
        query=world_query(entry),
        body=body,
    )
    row.expect(status_read == 200, f"the read-only token's read answered {status_read}")
    row.expect(status_write in (403, 404), f"the read-only token's write answered {status_write}")
    row.observed = {
        "exit_codes": runs,
        "read_only_read": status_read,
        "read_only_write": [status_write, problem_code(refused)],
    }
    return row.close()


def row_c3_revoke(
    stack: Stack, w1: Client, read_factory: Callable[[], Client], entry: Mapping[str, Any]
) -> Row:
    row = Row(
        "C3",
        "isolation.revoke",
        "After the API restarts without a token's grant, that token is refused 401 before any "
        "work; the owner's history stays readable; restoring the grant restores reads.",
    )
    _, history_before = w1.call("C3", "GET", version_path(entry), query=world_query(entry))
    revoked = stack.restart_api(revoke="token-read")
    status_revoked, body = read_factory().call("C3", "GET", "/world-entries")
    _, history_after = w1.call("C3", "GET", version_path(entry), query=world_query(entry))
    restored = stack.restart_api()
    status_restored, _ = read_factory().call("C3", "GET", "/world-entries")
    row.expect(status_revoked == 401, f"the revoked token answered {status_revoked}")
    row.expect(
        history_before.get("edits") == history_after.get("edits"),
        "the owner's edit history changed across the revocation",
    )
    row.expect(status_restored == 200, f"the restored token answered {status_restored}")
    row.observed = {
        "revoked_restart": revoked,
        "revoked_status": [status_revoked, problem_code(body)],
        "restored_restart": restored,
        "restored_status": status_restored,
        "edits_unchanged": history_before.get("edits") == history_after.get("edits"),
    }
    return row.close()


def row_d1_edit(stack: Stack, w1: Client, entry_id: str) -> Row:
    row = Row(
        "D1",
        "edit.place_preview_confirm_undo",
        "Preview writes nothing (after a no-op control); a stale base is refused (entry-bound: "
        "stale_saved_world_entry; unbound: composition_blocked stale_base) and writes nothing; apply advances "
        "the saved world; repeating the same apply does not "
        "duplicate; the object survives an API restart; undo removes it and that survives a "
        "restart.",
    )
    entry = read_entry(w1, "D1", entry_id)
    control_equal, control = no_write_control(stack, w1, entry)
    row.expect(control_equal, "the evidence method saw a change across a plain read")
    before = stack.evidence_digest()
    body = placement("cc0.marker-plate", "d1-plate", "stall", entry["authored_state_sha256"])
    status_preview, preview = w1.call(
        "D1",
        "POST",
        version_path(entry, "/compositions/preview"),
        query=world_query(entry),
        body=body,
    )
    after = stack.evidence_digest()
    row.expect(
        status_preview == 200 and preview.get("availability") == "ready",
        f"preview answered {status_preview} {preview.get('availability')}",
    )
    row.expect(before == after, "preview changed the database or store")
    stale = stale_refusals(w1, "D1", entry, "cc0.marker-plate", "d1-plate", "stall")
    for failure in stale["failures"]:
        row.failures.append(failure)
    status_apply, _ = apply(w1, "D1", entry, "cc0.marker-plate", "d1-plate", "stall")
    row.expect(status_apply in (200, 201), f"apply answered {status_apply}")
    advanced = read_entry(w1, "D1", entry_id)
    row.expect(
        advanced["authored_edit_seq"] == entry["authored_edit_seq"] + 1,
        "the saved world did not advance with the edit",
    )
    repeat = placement("cc0.marker-plate", "d1-plate", "stall", entry["authored_state_sha256"])
    repeat["saved_entry"] = resume_point(entry)
    status_repeat, repeated = w1.call(
        "D1",
        "POST",
        version_path(entry, "/compositions/apply"),
        query=world_query(entry),
        body=repeat,
    )
    _, version_now = w1.call("D1", "GET", version_path(entry), query=world_query(entry))
    plates = [o for o in version_now.get("objects", []) if o["object_id"] == "d1-plate"]
    row.expect(status_repeat >= 400, f"the repeated apply answered {status_repeat}")
    row.expect(len(plates) == 1, f"{len(plates)} objects named d1-plate after the repeat")
    restart = stack.restart_api()
    _, reopened = w1.call("D1", "GET", version_path(entry), query=world_query(entry))
    row.expect(reopened == version_now, "the version read differently after the API restart")
    current = read_entry(w1, "D1", entry_id)
    status_undo, undone = w1.call(
        "D1",
        "POST",
        version_path(entry, "/objects/undo"),
        query=world_query(entry),
        body={
            "base_state_sha256": current["authored_state_sha256"],
            "saved_entry": resume_point(current),
        },
    )
    row.expect(status_undo == 200, f"undo answered {status_undo} {problem_code(undone)}")
    stack.restart_api()
    _, after_undo = w1.call("D1", "GET", version_path(entry), query=world_query(entry))
    live = [
        o
        for o in after_undo.get("objects", [])
        if o["object_id"] == "d1-plate" and not o.get("removed")
    ]
    row.expect(live == [], "the undone object is still present after a restart")
    row.observed = {
        "control": control,
        "preview": {"status": status_preview, "digest_before": before, "digest_after": after},
        "stale": stale,
        "apply": status_apply,
        "edit_seq": [entry["authored_edit_seq"], advanced["authored_edit_seq"]],
        "repeat": [status_repeat, problem_code(repeated)],
        "restart": restart,
        "undo": [status_undo, problem_code(undone)],
        "undo_edits": [e["kind"] for e in after_undo.get("edits", [])],
    }
    return row.close()


def journey(stack: Stack, w2: Client, entry_id: str, out: Path) -> list[Row]:
    """N1: a bench on the authored starter, the lamp-post and floating-bench controls."""
    rows: list[Row] = []
    setup = Row(
        "N1.a",
        "journey.open",
        "Open the saved starter in its own client, place the one visit target a society needs to "
        "start (setup), bring in the saved-world society and read it.",
    )
    entry = read_entry(w2, "N1.a", entry_id)
    status_stall, _ = apply(w2, "N1.a", entry, "cc0.market-stall", "stall", "stall")
    setup.expect(status_stall in (200, 201), f"the setup stall answered {status_stall}")
    status_society, created = w2.call(
        "N1.a",
        "POST",
        version_path(entry, "/society"),
        query=world_query(entry),
        body={"region_id": STARTER_REGION, "profile": SAVED_WORLD_SOCIETY},
    )
    setup.expect(status_society == 200, f"society creation answered {status_society}")
    snapshot = created
    for _ in range(5):
        status_step, snapshot = advance(w2, "N1.a", entry, snapshot)
        setup.expect(status_step == 200, f"a warm-up minute answered {status_step}")
    setup.observed = {
        "population": created.get("population_size"),
        "engine": created.get("profile"),
        "warm_up_tick": snapshot.get("current_tick"),
        "input_seq": snapshot.get("input_seq"),
    }
    rows.append(setup.close())

    preview_row = Row(
        "N1.b",
        "journey.preview",
        "Previewing the bench writes nothing (after a no-op control) and would_change adds it.",
    )
    entry = read_entry(w2, "N1.b", entry_id)
    control_equal, control = no_write_control(stack, w2, entry)
    preview_row.expect(control_equal, "the evidence method saw a change across a plain read")
    before = stack.evidence_digest()
    status_preview, preview = w2.call(
        "N1.b",
        "POST",
        version_path(entry, "/compositions/preview"),
        query=world_query(entry),
        body=placement("cc0.bench", "bench", "bench", entry["authored_state_sha256"]),
    )
    after = stack.evidence_digest()
    would = preview.get("would_change") or {}
    preview_row.expect(status_preview == 200, f"preview answered {status_preview}")
    preview_row.expect(before == after, "preview changed the database or store")
    preview_row.expect(
        would.get("kind") == "add_object" and would.get("subject_id") == "bench",
        "would_change does not add the bench",
    )
    preview_row.observed = {"control": control, "before": before, "after": after, "would": would}
    rows.append(preview_row.close())

    control_row = Row(
        "N1-ctl",
        "journey.controls",
        "A lamp post (an obstacle with no activity) and a bench floating 3 m above the ground are "
        "never offered as targets, the floating bench is reported authored_object_off_ground, and "
        "no event in the run names either as its target.",
    )
    seen: dict[str, dict[str, Any]] = {}

    def gather(step: str) -> None:
        """Every event of the run, read after each minute; one minute of eight people stays far
        inside the events route's ceiling, so consecutive reads overlap and none is missed."""
        read = events(w2, step, entry)
        oldest = min((e["tick"] for e in read), default=0)
        newest_before = max((e["tick"] for e in seen.values()), default=0)
        if seen and oldest > newest_before:
            control_row.failures.append(f"event reads left a gap before tick {oldest}")
        for event in read:
            seen[event["event_id"]] = event

    held = advance_once(control_row, w2, "N1-ctl", entry)
    entry = read_entry(w2, "N1-ctl", entry_id)
    status_lamp, _ = apply(w2, "N1-ctl", entry, "cc0.lamp-post", "lamp", "lamp")
    after_lamp = advance_once(control_row, w2, "N1-ctl", entry)
    gather("N1-ctl")
    lamp_offered = [
        t
        for t in (after_lamp.get("places") or {}).get("targets", [])
        if t.get("object_id") == "lamp"
    ]
    control_row.expect(status_lamp in (200, 201), f"the lamp post answered {status_lamp}")
    control_row.expect(not lamp_offered, "the lamp post is offered as a target")
    entry = read_entry(w2, "N1-ctl", entry_id)
    status_float, _ = apply(w2, "N1-ctl", entry, "cc0.bench", "bench-floating", "bench_floating")
    with_places = advance_once(control_row, w2, "N1-ctl", entry)
    gather("N1-ctl")
    unavailable = (with_places.get("places") or {}).get("unavailable_affordances", [])
    floating = [u for u in unavailable if u.get("object_id") == "bench-floating"]
    offered = (with_places.get("places") or {}).get("targets", [])
    control_row.expect(status_float in (200, 201), f"the floating bench answered {status_float}")
    control_row.expect(
        [u.get("reason") for u in floating] == ["authored_object_off_ground"],
        "the floating bench is not reported off the ground",
    )
    control_row.expect(
        not [t for t in offered if t.get("object_id") == "bench-floating"],
        "the floating bench is offered as a target",
    )
    control_row.observed = {
        "lamp_input_seq": [held.get("input_seq"), after_lamp.get("input_seq")],
        "floating_input_seq": with_places.get("input_seq"),
        "floating": floating,
    }
    # Closed after the response window, once every event of the run has been read.
    rows.append(control_row)

    confirm = Row(
        "N1.c",
        "journey.confirm",
        "A stale base is refused (entry-bound: stale_saved_world_entry; unbound: "
        "composition_blocked stale_base) and writes nothing; the bench applies against the current base; the "
        "next minute takes exactly one new society input that offers it as one rest target.",
    )
    entry = read_entry(w2, "N1.c", entry_id)
    stale = stale_refusals(w2, "N1.c", entry, "cc0.bench", "bench", "bench")
    confirm.failures += stale["failures"]
    _, before_bench = society(w2, "N1.c", entry)
    status_bench, _ = apply(w2, "N1.c", entry, "cc0.bench", "bench", "bench")
    after_bench = advance_once(confirm, w2, "N1.c", entry)
    gather("N1.c")
    targets = (after_bench.get("places") or {}).get("targets", [])
    bench_targets = [t for t in targets if t.get("object_id") == "bench"]
    confirm.expect(status_bench in (200, 201), f"the bench answered {status_bench}")
    confirm.expect(
        (after_bench.get("input_seq") or 0) == (before_bench.get("input_seq") or 0) + 1,
        "the minute after the bench did not take exactly one new society input",
    )
    confirm.expect(
        [t.get("affordance") for t in bench_targets] == ["rest"],
        "the bench is not offered as one rest target",
    )
    bench_input = after_bench.get("input_seq")
    confirm.observed = {
        "stale": stale,
        "input_seq": [before_bench.get("input_seq"), bench_input],
        "bench_targets": bench_targets,
    }
    rows.append(confirm.close())

    response = Row(
        "N1.d",
        "journey.response",
        f"Within {JOURNEY_MINUTES_MAXIMUM} advanced minutes a person selects the bench as a goal "
        "and completes a rest at it, in events recorded under the bench's input or later.",
    )
    snapshot = after_bench
    found: dict[str, Any] = {}
    minutes = 0
    while minutes < JOURNEY_MINUTES_MAXIMUM:
        status_step, snapshot = advance(w2, "N1.d", entry, snapshot)
        minutes += 1
        if status_step != 200:
            response.failures.append(f"minute {minutes} answered {status_step}")
            break
        gather("N1.d")
        at_bench = [
            e
            for e in seen.values()
            if ((e["document"].get("target") or {}).get("object_id") == "bench")
        ]
        kinds = {e["event_kind"] for e in at_bench}
        if "goal_selected" in kinds and "action_completed" in kinds:
            completed = min(
                (e for e in at_bench if e["event_kind"] == "action_completed"),
                key=lambda e: (e["tick"], e["document"]["order"]),
            )
            found = {
                "minutes_advanced": minutes,
                "completed_event": completed["event_id"],
                "subject_id": completed["subject_id"],
                "tick": completed["tick"],
                "input_seq": completed["document"]["input_seq"],
                "activity": completed["document"]["target"].get("activity"),
                "action": completed["document"].get("action", {}).get("kind"),
                "summary": completed["document"].get("summary"),
            }
            break
    response.expect(bool(found), "no rest at the bench was completed in the bound")
    if found:
        response.expect(found["input_seq"] >= bench_input, "the rest predates the bench's input")
        response.expect(found["action"] == "rest", f"the completed action is {found['action']}")
    response.observed = found or {"minutes_advanced": minutes}
    history, cursor = events_history(w2, "N1.d", entry)
    response.observed["history_cursor"] = cursor
    if cursor:
        ids = {e["event_id"] for e in history}
        response.expect(set(seen) <= ids, "the paged history omits events read minute by minute")
        response.expect(len(ids) == len(history), "the paged history repeats an event")
        status_bad, bad = w2.call(
            "N1.d",
            "GET",
            version_path(entry, "/society/events"),
            query={**world_query(entry), "before": "q10-no-such-event"},
        )
        response.expect(
            status_bad == 422 and problem_code(bad) == "invalid_event_cursor",
            f"a cursor naming no event answered {status_bad} {problem_code(bad)}",
        )
        response.observed["history_events"] = len(history)
    rows.append(response.close())
    decoys = [
        e["event_id"]
        for e in seen.values()
        if (e["document"].get("target") or {}).get("object_id") in ("lamp", "bench-floating")
    ]
    control_row.expect(decoys == [], f"{len(decoys)} events name the lamp or floating bench")
    control_row.observed["events_read"] = len(seen)
    control_row.observed["events_naming_controls"] = decoys
    control_row.close()

    explain = Row(
        "N1.e",
        "journey.explain",
        "The Companion explains the person's rest from stored events, citing the bench and the "
        "edit.",
    )
    status_ask, asked = w2.call(
        "N1.e",
        "POST",
        "/selection/ask",
        query=world_query(entry),
        body={
            "question": "Why did this person go to the bench?",
            "society_context": {
                "version_id": entry["authored_version_id"],
                "inhabitant_id": found.get("subject_id"),
            },
        },
    )
    explain.observed = {"status": status_ask, "body": asked}
    explain.blocked_by += [
        "no-model answers 503; a scripted plan answering each request kind of the question path is not yet written",
        "N-G3 (M6/M7): citations lack object_id, input_seq and edit reference",
    ]
    rows.append(explain.close())

    cause = Row(
        "N1.f",
        "journey.cause",
        "From the cited event, reach the edit that added the bench through public reads.",
    )
    _, version = w2.call("N1.f", "GET", version_path(entry), query=world_query(entry))
    added = [
        e
        for e in version.get("edits", [])
        if e.get("object_id") == "bench" and e.get("undone_edit_id") is None
    ]
    cause.expect(len(added) >= 1, "no edit in the version history names the bench")
    cause.observed = {
        "edits_naming_bench": [
            {"edit_id": e["edit_id"], "edit_seq": e["edit_seq"], "kind": e["kind"]} for e in added
        ],
    }
    if INPUT_PROVENANCE_ROUTE not in served_paths(w2):
        cause.observed["join"] = "event.document.target.object_id -> version.edits[].object_id"
        cause.blocked_by.append(
            "N-G4 (F1): the candidate serves no input provenance read; joined by object_id only"
        )
    elif not found:
        cause.failures.append("no rest at the bench was observed to trace to its edit")
    else:
        path = version_path(entry, f"/society/inputs/{found['input_seq']}")
        status, provenance = w2.call("N1.f", "GET", path, query=world_query(entry))
        authored = (provenance or {}).get("authored_state") or {}
        matched = [e for e in version.get("edits", []) if e["edit_seq"] == authored.get("edit_seq")]
        status_none, none = w2.call(
            "N1.f", "GET", version_path(entry, "/society/inputs/999999"), query=world_query(entry)
        )
        cause.expect(status == 200, f"the input provenance read answered {status}")
        cause.expect("document" not in (provenance or {}), "the read served the input document")
        cause.expect(len(matched) == 1, "no single edit has the input's edit_seq")
        if len(matched) == 1:
            cause.expect(matched[0]["object_id"] == "bench", "the input's edit is not the bench's")
            cause.expect(
                matched[0]["result_state_sha256"] == authored.get("delta_sha256"),
                "the edit's result digest differs from the input's delta digest",
            )
        cause.expect(
            status_none == 404 and problem_code(none) == "unknown_reference",
            f"an unknown input answered {status_none} {problem_code(none)}",
        )
        cause.observed |= {
            "join": "event.input_seq -> inputs/{seq}.authored_state.edit_seq -> version.edits[]",
            "event": found.get("completed_event"),
            "provenance": provenance,
            "edit": matched[0] if len(matched) == 1 else None,
        }
    rows.append(cause.close())

    reopen = Row(
        "N1.g",
        "journey.reopen",
        "After an API restart a new client process reads the same saved world, version (bench "
        "included) and events.",
    )
    saved = read_entry(w2, "N1.g", entry_id)
    _, version_before = w2.call("N1.g", "GET", version_path(entry), query=world_query(entry))
    events_before = events(w2, "N1.g", entry)
    _, society_before = society(w2, "N1.g", entry)
    restart = stack.restart_api()
    reader = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "reopen-client",
            "--base-url",
            stack.base_url,
            "--token-file",
            str(stack.token_file("token-2")),
            "--entry",
            entry_id,
            "--out",
            str(out / "evidence" / "n1g-reopen.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    reopen.expect(reader.returncode == 0, f"the reopen client exited {reader.returncode}")
    reread = (
        json.loads((out / "evidence" / "n1g-reopen.json").read_text())
        if reader.returncode == 0
        else {}
    )
    reopen.expect(reread.get("entry") == saved, "the saved world read differently")
    reopen.expect(reread.get("version") == version_before, "the version read differently")
    reopen.expect(reread.get("events") == events_before, "the events read differently")
    reopen.expect(
        reread.get("society_state_sha256") == society_before.get("state_sha256"),
        "the society state differs",
    )
    reopen.observed = {
        "restart": restart,
        "entry_sha256": canonical_sha256(saved),
        "version_sha256": canonical_sha256(version_before),
        "events_sha256": canonical_sha256(events_before),
        "events_read": len(events_before),
        "society_state_sha256": society_before.get("state_sha256"),
        "reader_stderr": reader.stderr[-500:],
    }
    rows.append(reopen.close())

    # N1.h and N1.i run on scripted stacks of their own: `foundation.py alternative` (A-28) and
    # `foundation.py companion`.
    for identity, check, expected, blockers in (
        (
            "N1.j",
            "journey.browser",
            "The production browser performs preview, confirm, response and explanation.",
            ["the production browser step is not yet written"],
        ),
    ):
        pending = Row(identity, check, expected)
        pending.blocked_by += blockers
        rows.append(pending.close())
    return rows


def isolation(stack: Stack, out: Path, own: dict[str, dict], rounds: int) -> Row:
    """C1: two workspace clients, each its own OS process, at the same time."""
    row = Row(
        "C1",
        "isolation.cross_probe",
        "Two workspace clients run at once in separate processes. Each edits its own starter "
        f"{rounds} times, all accepted. Every probe of the other workspace's identities answers "
        "exactly as the same probe of an invented identity does.",
    )
    processes = {}
    for name, token_file, mine, theirs in (
        ("w1", "token", "w1", "w2"),
        ("w2", "token-2", "w2", "w1"),
    ):
        (out / "evidence" / f"isolation-{name}-own.json").write_text(json.dumps(own[mine]))
        (out / "evidence" / f"isolation-{name}-foreign.json").write_text(json.dumps(own[theirs]))
        processes[name] = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "isolation-client",
                "--base-url",
                stack.base_url,
                "--token-file",
                str(stack.token_file(token_file)),
                "--own",
                str(out / "evidence" / f"isolation-{name}-own.json"),
                "--foreign",
                str(out / "evidence" / f"isolation-{name}-foreign.json"),
                "--rounds",
                str(rounds),
                "--out",
                str(out / "evidence" / f"isolation-{name}.json"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    reports = {}
    for name, process in processes.items():
        _, stderr = process.communicate()
        row.expect(
            process.returncode == 0, f"client {name} exited {process.returncode}: {stderr[-300:]}"
        )
        path = out / "evidence" / f"isolation-{name}.json"
        reports[name] = json.loads(path.read_text()) if path.exists() else {}
    for name, report in reports.items():
        row.expect(
            report.get("edits_accepted") == rounds,
            f"client {name} had {report.get('edits_accepted')} of {rounds} edits accepted",
        )
        row.expect(
            report.get("mismatches") == [],
            f"client {name} saw foreign identities differ from invented ones",
        )
        row.expect(report.get("own_entry_listed") is True, f"client {name} did not list its entry")
        row.expect(
            report.get("foreign_entry_listed") is False, f"client {name} listed another's entry"
        )
    spans = [(r.get("started_epoch"), r.get("finished_epoch")) for r in reports.values()]
    overlap = (
        round(min(end for _, end in spans) - max(start for start, _ in spans), 3)
        if len(spans) == 2 and all(start and end for start, end in spans)
        else None
    )
    row.expect(
        overlap is not None and overlap > 0,
        f"the two clients' requests did not overlap in time (overlap {overlap} s)",
    )
    row.observed = {"overlap_seconds": overlap}
    row.observed |= {
        name: {
            k: report.get(k)
            for k in (
                "edits_accepted",
                "probes",
                "mismatches",
                "pid",
                "own_entry_listed",
                "foreign_entry_listed",
                "started_epoch",
                "finished_epoch",
            )
        }
        for name, report in reports.items()
    }
    return row.close()


def existing_tests(out: Path, worktree: Path) -> Row:
    row = Row(
        "C1-existing",
        "tests/test_existence_oracle.py tests/test_route_probes.py",
        "The existing existence-oracle and route-probe tests pass on the candidate against a "
        "private PostgreSQL server.",
    )
    completed = subprocess.run(
        [
            str(worktree / ".venv" / "bin" / "python"),
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/test_existence_oracle.py",
            "tests/test_route_probes.py",
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
    )
    (out / "evidence" / "existing-isolation-tests.txt").write_text(
        completed.stdout + completed.stderr
    )
    tail = completed.stdout.strip().splitlines()[-1:] or [""]
    row.expect(completed.returncode == 0, f"pytest exited {completed.returncode}: {tail[0]}")
    row.observed = {"exit": completed.returncode, "summary": tail[0]}
    return row.close()


# -- subcommands -----------------------------------------------------------------------------------


def without_identities(answer: Any, target: Mapping[str, Any]) -> str:
    """An answer with the probed identities replaced, so an echoed identifier is not a difference
    but anything else the server says about the resource is."""
    text = json.dumps(answer, sort_keys=True)
    for key in ("entry_id", "authored_version_id", "world_id"):
        text = text.replace(str(target[key]), f"<{key}>")
    return text


def isolation_client(arguments: argparse.Namespace) -> int:
    own = json.loads(Path(arguments.own).read_text())
    foreign = json.loads(Path(arguments.foreign).read_text())
    http = WorldClient(arguments.base_url, Path(arguments.token_file).read_text())
    started = time.time()
    accepted = 0
    mismatches: list[dict[str, Any]] = []
    probes = 0
    for index in range(arguments.rounds):
        _, entry = http.request("GET", f"/world-entries/{own['entry_id']}")
        body = placement(
            "cc0.marker-pillar",
            f"iso-{os.getpid()}-{index}",
            "marker",
            entry["authored_state_sha256"],
        )
        body["placement"]["transform"]["x_mm"] = 1000 * index
        body["saved_entry"] = resume_point(entry)
        status, _ = http.request(
            "POST",
            f"/world/versions/{entry['authored_version_id']}/compositions/apply",
            query={"world_id": entry["world_id"]},
            body=body,
        )
        accepted += status in (200, 201)
        invented = {
            "entry_id": str(uuid.uuid4()),
            "authored_version_id": str(uuid.uuid4()),
            "world_id": f"world:authored:{uuid.uuid4()}",
        }
        for target in (foreign, invented):
            target["_answers"] = []
            for method, path, query in (
                ("GET", f"/world-entries/{target['entry_id']}", None),
                (
                    "GET",
                    f"/world/versions/{target['authored_version_id']}",
                    {"world_id": target["world_id"]},
                ),
                (
                    "GET",
                    f"/world/versions/{target['authored_version_id']}/society",
                    {"world_id": target["world_id"]},
                ),
                (
                    "GET",
                    f"/world/versions/{target['authored_version_id']}/society/events",
                    {"world_id": target["world_id"]},
                ),
                (
                    "GET",
                    f"/world/versions/{target['authored_version_id']}/models",
                    {"world_id": target["world_id"]},
                ),
                (
                    "POST",
                    f"/world/versions/{target['authored_version_id']}/compositions/preview",
                    {"world_id": target["world_id"]},
                ),
            ):
                probe_body = (
                    placement("cc0.marker-cube", "probe", "marker", STALE_SHA256)
                    if method == "POST"
                    else None
                )
                status, answer = http.request(method, path, query=query, body=probe_body)
                probes += 1
                target["_answers"].append((status, answer))
        for (fs, fb), (is_, ib) in zip(foreign["_answers"], invented["_answers"], strict=True):
            seen_foreign = without_identities(fb, foreign)
            seen_invented = without_identities(ib, invented)
            if fs != is_ or seen_foreign != seen_invented:
                mismatches.append({"foreign": [fs, fb], "invented": [is_, ib]})
        foreign.pop("_answers")
    _, listed = http.request("GET", "/world-entries")
    report = {
        "pid": os.getpid(),
        "edits_accepted": accepted,
        "probes": probes,
        "mismatches": mismatches,
        "own_entry_listed": own["entry_id"] in [e["entry_id"] for e in listed],
        "foreign_entry_listed": foreign["entry_id"] in [e["entry_id"] for e in listed],
        "started_epoch": started,
        "finished_epoch": time.time(),
    }
    Path(arguments.out).write_text(json.dumps(report, indent=2))
    return 0


def reopen_client(arguments: argparse.Namespace) -> int:
    http = WorldClient(arguments.base_url, Path(arguments.token_file).read_text())
    status, entry = http.request("GET", f"/world-entries/{arguments.entry}")
    if status != 200:
        print(f"saved world answered {status}", file=sys.stderr)
        return 1
    query = {"world_id": entry["world_id"]}
    version_id = entry["authored_version_id"]
    _, version = http.request("GET", f"/world/versions/{version_id}", query=query)
    _, listed = http.request(
        "GET",
        f"/world/versions/{version_id}/society/events",
        query={**query, "limit": str(EVENTS_LIMIT)},
    )
    _, snapshot = http.request("GET", f"/world/versions/{version_id}/society", query=query)
    Path(arguments.out).write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "entry": entry,
                "version": version,
                "events": listed["events"],
                "society_state_sha256": snapshot.get("state_sha256"),
            }
        )
    )
    return 0


def baseline(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    others = stack.state.get("other_workspaces", [])
    if len(others) < 1 or "read_only_token" not in stack.state or stack.state.get("model"):
        raise SystemExit(
            "baseline needs a no-model stack started with --workspaces 2 --read-only-token --tiles"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    w1 = client(stack, transcripts, "w1", "token")
    w2 = client(stack, transcripts, "w2", "token-2")

    def read_only() -> Client:
        return client(stack, transcripts, "read-only", "token-read")

    rows: list[Row] = []
    a1, w1_entry, w2_entry = row_a1_starter(w1, w2)
    rows.append(a1)
    rows.append(row_d1_edit(stack, w1, w1_entry["entry_id"]))
    rows += journey(stack, w2, w2_entry["entry_id"], out)
    a2, towns = row_a2_generated(stack, w1)
    rows.append(a2)
    rows.append(row_a3_source(stack, w1, w2, out))
    held_entries = w1.call("A4", "GET", "/world-entries")[1]
    source = next((e for e in held_entries if e.get("source_kind") == "personal"), None)
    rows.append(
        row_a4_discovery(
            stack,
            w1,
            w2,
            read_only(),
            {"starter": w1_entry, "towns": towns, "source": source},
            out,
        )
    )
    rows.append(
        row_b1_no_model(
            stack,
            w1,
            read_entry(w1, "B1", w1_entry["entry_id"]),
            towns[0] if towns else None,
            w2,
            read_entry(w2, "B1", w2_entry["entry_id"]),
        )
    )
    own = {
        "w1": {
            k: read_entry(w1, "C1", w1_entry["entry_id"])[k]
            for k in ("entry_id", "authored_version_id", "world_id")
        },
        "w2": {
            k: read_entry(w2, "C1", w2_entry["entry_id"])[k]
            for k in ("entry_id", "authored_version_id", "world_id")
        },
    }
    rows.append(isolation(stack, out, own, ISOLATION_ROUNDS))
    rows.append(existing_tests(out, worktree))
    rows.append(row_c2_client(stack, read_entry(w1, "C2", w1_entry["entry_id"]), out, read_only()))
    rows.append(row_c3_revoke(stack, w1, read_only, read_entry(w1, "C3", w1_entry["entry_id"])))
    rows.append(
        row_f3_context(
            stack,
            w1,
            w2,
            lambda: client(stack, transcripts, "peer", PEER_TOKEN),
            read_entry(w1, "F3", w1_entry["entry_id"]),
            out,
        )
    )
    rows.append(row_f4_boundary(out, worktree))
    rows += row_g1_g3_clock(
        stack, w1, towns, out, Path(arguments.w7_client) if arguments.w7_client else None
    )
    # The journey workspace, last: it holds one saved world and room for a town, so F1's client
    # can make a world of its own there, and A-16 compares the journey world before and after.
    rows.append(row_a4_client(stack, w2, "token-2", out, arguments.exercise_own_worlds_only))
    results = {
        "profile": "q10-foundation-acceptance-results/v1",
        "candidate": stack.state["tree"],
        "launcher_run": stack.state["run_id"],
        "started_at": started,
        "finished_at": dt.datetime.now(dt.UTC).isoformat(),
        "timing_claims": False,
        "rows": [row.document() for row in rows],
        "counts": {state: sum(r.status == state for r in rows) for state in STATES},
    }
    (out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True))
    public_state = {k: v for k, v in stack.state.items() if k not in ("database",)}
    manifest = {
        "driver": str(Path(__file__).resolve().relative_to(REPOSITORY)),
        "driver_sha256": DRIVER_SHA256_AT_START,
        "driver_changed_during_run": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        != DRIVER_SHA256_AT_START,
        "launcher_sha256": hashlib.sha256((HERE / "launch.py").read_bytes()).hexdigest(),
        "command": ["foundation.py", *sys.argv[1:]],
        "launcher_state": public_state,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    for row in rows:
        reason = "; ".join(row.failures or row.blocked_by)
        print(f"{row.row:12} {row.status:8} {reason}")
    print(json.dumps(results["counts"]))
    return 0 if results["counts"]["failed"] == 0 else 1


# -- spending (B1 rows I1 to I5) ---------------------------------------------------------------------

#: The spending tables in restore order, parents first (``tests/test_spending_witness.py``).
SPENDING_TABLES = (
    "spending_authority",
    "spending_authority_term",
    "spending_authority_state",
    "spending_authority_revocation",
    "spending_grant",
    "spending_grant_state",
    "spending_grant_revocation",
    "spending_reservation",
    "spending_event",
)
#: The authority's ceiling, above any one grant, and the grants: each racing workspace's small
#: enough that its two processes reach it in seconds; the kill window's workspace its own.
AUTHORITY_CEILING_USD = "0.020"
GRANT_CEILING_USD = "0.006"
KILL_GRANT_CEILING_USD = "0.004"
SPENDING_MAX_CALLS = 1000
#: How long each race client asks, and how long the kill window runs before the kill.
RACE_SECONDS = 15
KILL_AFTER_SECONDS = 3
#: The question every spending client asks; it is admitted before anything is sent.
SPENDING_QUESTION = {"question": "where was I?"}


def spend_client(arguments: argparse.Namespace) -> int:
    """One client asking for a plan until its time runs out, counting what each answer was."""
    http = WorldClient(arguments.base_url, Path(arguments.token_file).read_text(), timeout=30)
    started = time.time()
    outcomes: dict[str, int] = {}
    deadline = time.monotonic() + arguments.seconds
    errors = 0
    while time.monotonic() < deadline:
        try:
            status, body = http.request("POST", "/selection/plan", body=SPENDING_QUESTION)
        except (ClientError, OSError):
            # A killed server is an outcome of the run, counted, never a crash of the client.
            errors += 1
            time.sleep(0.2)
            continue
        reason = (body or {}).get("spending", {}).get("reason") if isinstance(body, dict) else None
        key = f"{status}:{reason or problem_code(body) or ''}"
        outcomes[key] = outcomes.get(key, 0) + 1
    Path(arguments.out).write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_epoch": started,
                "finished_epoch": time.time(),
                "outcomes": outcomes,
                "connection_errors": errors,
            }
        )
    )
    return 0


def operator(stack: Stack, *command: str) -> tuple[int, dict[str, Any]]:
    """``python -m exulanica.spending`` as the operator: owner database, the API's witness."""
    environment = LAUNCH.clean_environment()
    environment.update(
        {
            "EXULANICA_DATABASE_URL": stack.state["database"]["owner_url_for_evidence_reads"],
            "EXULANICA_SPENDING_WITNESS_DIR": str(stack.run_dir / LAUNCH.SPENDING_WITNESS_NAME),
        }
    )
    completed = subprocess.run(
        [str(stack.worktree / ".venv" / "bin" / "python"), "-m", "exulanica.spending", *command],
        cwd=stack.worktree,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    text = completed.stdout.strip() or completed.stderr.strip()
    try:
        return completed.returncode, json.loads(text.splitlines()[-1]) if text else {}
    except ValueError:
        return completed.returncode, {"unparsed": text[-500:]}


def scripted_calls(stack: Stack) -> int:
    log = Path(stack.state["scripted_model"]["log"])
    return len(log.read_text().splitlines()) if log.exists() else 0


def spending_of(c: Client, step: str) -> dict[str, Any]:
    status, body = c.call(step, "GET", "/spending")
    if status != 200:
        raise RuntimeError(f"GET /spending answered {status}: {body}")
    return body["providers"][0]


def ask(c: Client, step: str) -> tuple[int, str | None]:
    status, body = c.call(step, "POST", "/selection/plan", body=SPENDING_QUESTION)
    reason = (body or {}).get("spending", {}).get("reason") if isinstance(body, dict) else None
    return status, reason


def ledger_dump(stack: Stack, path: Path) -> None:
    """An evidence copy of the spending tables, as a backup of them would hold them."""
    database = stack.state["database"]
    command = [
        str(Path(database["postgres_bin"]) / "pg_dump"),
        "--data-only",
        "--disable-triggers",
        "--no-owner",
        "--no-privileges",
        f"--restrict-key={EVIDENCE_RESTRICT_KEY}",
    ]
    for table in SPENDING_TABLES:
        command += ["-t", table]
    path.write_bytes(
        subprocess.run(
            [*command, database["owner_url_for_evidence_reads"]], capture_output=True, check=True
        ).stdout
    )


def ledger_restore(stack: Stack, path: Path) -> None:
    """Put the spending tables back as the dump holds them, as restoring a backup does."""
    database = stack.state["database"]
    script = path.with_suffix(".restore.sql")
    script.write_text(f"truncate {', '.join(SPENDING_TABLES)};\n" + path.read_text())
    subprocess.run(
        [
            str(Path(database["postgres_bin"]) / "psql"),
            "--quiet",
            "--set=ON_ERROR_STOP=1",
            "--single-transaction",
            "--file",
            str(script),
            database["owner_url_for_evidence_reads"],
        ],
        capture_output=True,
        check=True,
    )


def kill_second_api(stack: Stack) -> dict[str, Any]:
    """SIGKILL the second API this run started: only its recorded process, checked by its
    marker and port, never anything else."""
    pid = stack.state["pids"]["api_2"]
    command = LAUNCH.command_of(pid)
    port = str(stack.state["second_api"]["port"])
    if LAUNCH.API_MARKER not in command or port not in command:
        raise SystemExit(f"pid {pid} is not this run's second API: {command[:120]}")
    os.killpg(pid, signal.SIGKILL)
    return {"pid": pid, "signal": "SIGKILL"}


def race(stack: Stack, out: Path, tokens: Sequence[str], seconds: int) -> list[dict[str, Any]]:
    """Clients through both APIs at once, one process each, for ``seconds``."""
    ports = (stack.state["ports"]["api"], stack.state["second_api"]["port"])
    launched = []
    for index, (token, port) in enumerate((token, port) for token in tokens for port in ports):
        result = out / "evidence" / f"race-{index}.json"
        launched.append(
            (
                result,
                subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "spend-client",
                        "--base-url",
                        f"http://127.0.0.1:{port}",
                        "--token-file",
                        str(stack.token_file(token)),
                        "--seconds",
                        str(seconds),
                        "--out",
                        str(result),
                    ]
                ),
            )
        )
    reports = []
    for result, process in launched:
        process.wait()
        reports.append(json.loads(result.read_text()) if result.exists() else {})
    return reports


def spending(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    scripted = stack.state.get("scripted_model") or {}
    if (
        scripted.get("spending") != "durable"
        or "second_api" not in stack.state
        or len(stack.state.get("other_workspaces", [])) < 3
    ):
        raise SystemExit(
            "spending needs a stack started with --scripted-model PLAN --spending durable "
            "--second-api --workspaces 4"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    w1 = client(stack, transcripts, "w1", "token")
    w2 = client(stack, transcripts, "w2", "token-2")
    w3 = client(stack, transcripts, "w3", "token-3")
    w4 = client(stack, transcripts, "w4", "token-4")
    workspaces = {
        "w1": stack.state["workspace_id"],
        "w2": stack.state["other_workspaces"][0]["workspace_id"],
        "w3": stack.state["other_workspaces"][1]["workspace_id"],
        "w4": stack.state["other_workspaces"][2]["workspace_id"],
    }
    later = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    decided = ["--operator", "q10-acceptance", "--reason", "Q10 synthetic acceptance run"]
    rows: list[Row] = []

    def grant(label: str, ceiling: str, until: str = later) -> tuple[int, dict[str, Any]]:
        return operator(
            stack,
            "grant",
            "--authority",
            authority,
            "--workspace",
            workspaces[label],
            "--ceiling-usd",
            ceiling,
            "--max-calls",
            str(SPENDING_MAX_CALLS),
            "--valid-until",
            until,
            *decided,
        )

    before = spending_of(w1, "setup")
    status_issue, issued = operator(
        stack,
        "issue",
        "--provider",
        before["provider"],
        "--ceiling-usd",
        AUTHORITY_CEILING_USD,
        "--max-calls",
        str(SPENDING_MAX_CALLS),
        "--valid-until",
        later,
        *decided,
    )
    authority = issued.get("authority_id")
    if status_issue != 0 or not authority:
        raise SystemExit(f"issuing the authority failed: {issued}")

    not_granted = Row(
        "I1-not-granted",
        "budget.not_granted",
        "A workspace with no grant is refused 429 spending_not_granted and nothing reaches the "
        "transport.",
    )
    calls_before = scripted_calls(stack)
    status_w3, reason_w3 = ask(w3, "I1-not-granted")
    not_granted.expect(
        (status_w3, reason_w3) == (429, "spending_not_granted"),
        f"an ungranted workspace answered {status_w3} {reason_w3}",
    )
    not_granted.expect(scripted_calls(stack) == calls_before, "the transport was called")
    not_granted.observed = {"answer": [status_w3, reason_w3]}
    rows.append(not_granted.close())

    for label, ceiling in (
        ("w1", GRANT_CEILING_USD),
        ("w2", GRANT_CEILING_USD),
        ("w3", KILL_GRANT_CEILING_USD),
    ):
        status_grant, granted = grant(label, ceiling)
        if status_grant != 0:
            raise SystemExit(f"granting {label} failed: {granted}")
    snapshot = out / "evidence" / "ledger-after-grants.sql"
    ledger_dump(stack, snapshot)

    survive = Row(
        "I2",
        "budget.crash_retry",
        "Killing the second API while a client asks through it, then restarting each API, never "
        "lowers the committed allowance any read reports. Deduplication of real retries is not "
        "delivered (amendment A-22): production calls carry no request key.",
    )
    loop = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "spend-client",
            "--base-url",
            f"http://127.0.0.1:{stack.state['second_api']['port']}",
            "--token-file",
            str(stack.token_file("token-3")),
            "--seconds",
            str(KILL_AFTER_SECONDS + 3),
            "--out",
            str(out / "evidence" / "kill-client.json"),
        ]
    )
    time.sleep(KILL_AFTER_SECONDS)
    killed = kill_second_api(stack)
    loop.wait()
    after_kill = spending_of(w3, "I2")
    stack.restart_api(api="second")
    after_second = spending_of(w3, "I2")
    stack.restart_api()
    w1 = client(stack, transcripts, "w1", "token")
    w2 = client(stack, transcripts, "w2", "token-2")
    w3 = client(stack, transcripts, "w3", "token-3")
    after_primary = spending_of(w3, "I2")
    committed = [Decimal(p["committed_usd"]) for p in (after_kill, after_second, after_primary)]
    kill_client = json.loads((out / "evidence" / "kill-client.json").read_text())
    survive.expect(committed[0] > 0, "nothing was committed before the kill")
    # Every transport call so far was workspace 3's (the ungranted ask sent nothing).
    sent_by_w3 = scripted_calls(stack)
    held = after_primary["committed_calls"] + after_primary["unresolved"]["count"] - sent_by_w3
    survive.expect(held >= 0, f"{held} committed calls fewer than were sent")
    survive.expect(committed == sorted(committed), f"committed fell across restarts: {committed}")
    survive.observed = {
        "sent_by_killed_workspace": sent_by_w3,
        "held_not_sent": held,
        "held_in_flight_usd": after_primary["in_flight_usd"],
        "killed": killed,
        "kill_client": kill_client,
        "after_kill": after_kill,
        "after_second_restart": after_second,
        "after_primary_restart": after_primary,
    }
    survive.blocked_by.append(
        "retry deduplication not delivered for production call sites (A-22); reported as a limit"
    )
    rows.append(survive.close())

    racing = Row(
        "I1",
        "budget.race",
        f"Workspaces 1 and 2 each race two client processes, one through each API, for "
        f"{RACE_SECONDS} s against their own grants of {GRANT_CEILING_USD} USD under one "
        f"authority of {AUTHORITY_CEILING_USD} USD. Requests are admitted during the race; each "
        "workspace's committed liability stays within its grant and the authority's within its "
        "ceiling; the limit is refused by name; scripted transport calls equal committed plus "
        "unresolved calls across every workspace.",
    )
    calls_at_race = scripted_calls(stack)
    reports = race(stack, out, ("token", "token-2"), RACE_SECONDS)
    reads = {label: spending_of(c, "I1") for label, c in (("w1", w1), ("w2", w2), ("w3", w3))}
    total_usd = sum(Decimal(r["committed_usd"]) for r in reads.values())
    race_calls = sum(
        reads[label]["committed_calls"] + reads[label]["unresolved"]["count"]
        for label in ("w1", "w2")
    )
    admitted = sum(
        count
        for r in reports
        for key, count in r.get("outcomes", {}).items()
        if not key.startswith("429:")
    )
    refused = sum(
        count
        for r in reports
        for key, count in r.get("outcomes", {}).items()
        if key == "429:spending_limit_reached"
    )
    spans = [(r.get("started_epoch"), r.get("finished_epoch")) for r in reports]
    overlap = min(end for _, end in spans) - max(start for start, _ in spans) if spans else None
    for label in ("w1", "w2"):
        racing.expect(
            Decimal(reads[label]["committed_usd"]) <= Decimal(GRANT_CEILING_USD),
            f"{label} committed {reads[label]['committed_usd']} beyond its grant",
        )
    racing.expect(
        total_usd <= Decimal(AUTHORITY_CEILING_USD),
        f"committed {total_usd} exceeds the authority ceiling",
    )
    racing.expect(admitted > 0, "no request was admitted during the race")
    racing.expect(refused > 0, "no request was refused at the limit")
    racing.expect(
        scripted_calls(stack) - calls_at_race == race_calls,
        f"{scripted_calls(stack) - calls_at_race} transport calls in the race, {race_calls} "
        "committed or unresolved by the racing workspaces (amendment A-25)",
    )
    racing.expect(overlap is not None and overlap > 0, f"the clients did not overlap ({overlap})")
    racing.observed = {
        "reports": reports,
        "reads": reads,
        "committed_usd": str(total_usd),
        "admitted_during_race": admitted,
        "refused_at_limit": refused,
        "transport_calls": [calls_at_race, scripted_calls(stack)],
        "overlap_seconds": overlap,
    }
    rows.append(racing.close())

    restore = Row(
        "I3",
        "budget.restore",
        "With the spending tables restored to their state before any spending, admission is "
        "refused spending_suspended (ledger behind its witness, retry after reauthorization) with "
        "nothing sent; reconciling the restore carries forward exactly what was committed, and "
        "after reauthorization each workspace's committed amount is unchanged and its availability "
        "is at most its grant less that amount (amendment A-23, C-10).",
    )
    committed_before = {k: Decimal(v["committed_usd"]) for k, v in reads.items()}
    ledger_restore(stack, snapshot)
    calls_before = scripted_calls(stack)
    status_r, body_r = w1.call("I3", "POST", "/selection/plan", body=SPENDING_QUESTION)
    detail = (body_r or {}).get("spending", {}) if isinstance(body_r, dict) else {}
    restore.expect(
        status_r == 429
        and detail.get("reason") == "spending_suspended"
        and detail.get("retry") == "after_reauthorization",
        f"after the restore admission answered {status_r} {detail}",
    )
    restore.expect(scripted_calls(stack) == calls_before, "the transport was called")
    status_c, carried = operator(stack, "reconcile-restore", "--authority", authority, *decided)
    status_a, reauthorized = operator(
        stack,
        "reauthorize",
        "--authority",
        authority,
        "--ceiling-usd",
        AUTHORITY_CEILING_USD,
        "--max-calls",
        str(SPENDING_MAX_CALLS),
        "--valid-until",
        later,
        *decided,
    )
    restore.expect(status_c == 0, f"reconcile-restore exited {status_c}: {carried}")
    restore.expect(status_a == 0, f"reauthorize exited {status_a}: {reauthorized}")
    restore.expect(
        Decimal(str(carried.get("carried_usd", "-1"))) == sum(committed_before.values()),
        f"carried {carried.get('carried_usd')}, committed {sum(committed_before.values())}",
    )
    after = {label: spending_of(c, "I3") for label, c in (("w1", w1), ("w2", w2), ("w3", w3))}
    for label, read in after.items():
        restore.expect(
            Decimal(read["committed_usd"]) == committed_before[label],
            f"{label} committed {read['committed_usd']}, was {committed_before[label]}",
        )
        restore.expect(
            Decimal(read["available_usd"])
            <= Decimal(read["grant"]["ceiling_usd"]) - Decimal(read["committed_usd"]),
            f"{label} may spend {read['available_usd']} after reauthorization",
        )
    restore.observed = {
        "refusal": [status_r, detail],
        "reconcile_restore": carried,
        "reauthorize": reauthorized,
        "committed_before": {k: str(v) for k, v in committed_before.items()},
        "after": after,
    }
    rows.append(restore.close())

    revoke = Row(
        "I4",
        "budget.revoke",
        "After workspace 2's grant is revoked it is refused spending_revoked with nothing sent, "
        "and its committed history stays readable.",
    )
    status_v, revoked = operator(
        stack,
        "revoke",
        "--authority",
        authority,
        "--workspace",
        workspaces["w2"],
        "--grant",
        spending_of(w2, "I4")["grant"]["grant_id"],
        *decided,
    )
    calls_before = scripted_calls(stack)
    status_w2, reason_w2 = ask(w2, "I4")
    w2_read = spending_of(w2, "I4")
    revoke.expect(status_v == 0, f"revoke exited {status_v}: {revoked}")
    revoke.expect(
        (status_w2, reason_w2) == (429, "spending_revoked"),
        f"a revoked workspace answered {status_w2} {reason_w2}",
    )
    revoke.expect(scripted_calls(stack) == calls_before, "the transport was called")
    revoke.expect(w2_read["grant"]["state"] == "revoked", f"grant state {w2_read['grant']}")
    revoke.expect(Decimal(w2_read["committed_usd"]) > 0, "the committed history is gone")
    revoke.observed = {"answer": [status_w2, reason_w2], "read": w2_read}
    rows.append(revoke.close())

    expiry = Row(
        "I5",
        "budget.expired",
        "A workspace whose only grant's time has passed is refused spending_expired with "
        "nothing sent (amendment A-24).",
    )
    soon = (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    status_g, short = grant("w4", "0.001", soon)
    time.sleep(5)
    calls_before = scripted_calls(stack)
    status_e, reason_e = ask(w4, "I5")
    expiry.expect(status_g == 0, f"the short grant exited {status_g}")
    expiry.expect(
        (status_e, reason_e) == (429, "spending_expired"),
        f"an expired grant answered {status_e} {reason_e}",
    )
    expiry.expect(scripted_calls(stack) == calls_before, "the transport was called")
    expiry.observed = {"answer": [status_e, reason_e], "short_grant": short}
    rows.append(expiry.close())

    results = {
        "profile": "q10-foundation-acceptance-results/v1",
        "candidate": stack.state["tree"],
        "launcher_run": stack.state["run_id"],
        "started_at": started,
        "finished_at": dt.datetime.now(dt.UTC).isoformat(),
        "timing_claims": False,
        "authority": authority,
        "rows": [row.document() for row in rows],
        "counts": {state: sum(r.status == state for r in rows) for state in STATES},
    }
    (out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True))
    manifest = {
        "driver_sha256": DRIVER_SHA256_AT_START,
        "driver_changed_during_run": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        != DRIVER_SHA256_AT_START,
        "launcher_sha256": hashlib.sha256((HERE / "launch.py").read_bytes()).hexdigest(),
        "command": ["foundation.py", *sys.argv[1:]],
        "launcher_state": {k: v for k, v in stack.state.items() if k != "database"},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    for row in rows:
        print(f"{row.row:16} {row.status:8} {'; '.join(row.failures or row.blocked_by)}")
    print(json.dumps(results["counts"]))
    return 0 if results["counts"]["failed"] == 0 else 1


# -- the edit-alternative comparison (N1.h, V7 package d) -------------------------------------------

COMPARISONS = "/society/comparisons"
PERSON_ROLE = "society_decision"
#: The model whose arm every comparison needs; the scripted plan answers its choices.
COMPARED_MODEL = {
    "provider": "nebius_token_factory",
    "model_id": "Qwen/Qwen3-235B-A22B-Instruct-2507",
}
COMPARISON_SECONDS = 600


def finished(c: Client, step: str, entry: Mapping[str, Any], comparison: str) -> dict[str, Any]:
    deadline = time.monotonic() + COMPARISON_SECONDS
    read: dict[str, Any] = {}
    while time.monotonic() < deadline:
        _, read = c.call(
            step,
            "GET",
            version_path(entry, f"{COMPARISONS}/{comparison}"),
            query=world_query(entry),
        )
        if (read.get("start") or {}).get("state") in ("finished", "closed"):
            return read
        time.sleep(3)
    return read


def alternative(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if "scripted_model" not in stack.state or not stack.state.get("society_playback"):
        raise SystemExit(
            "alternative needs a stack started with --scripted-model PLAN --society-playback"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    w1 = client(stack, transcripts, "w1", "token")
    row = Row(
        "N1.h",
        "journey.alternative",
        "On a saved starter world whose people were brought in before a bench was placed, two "
        "comparisons with the same model, group and seed freeze the input before the bench and "
        "the bench's input (V7 package d). Every run completes; the arms and seed agree; only the "
        "run frozen at the bench's input offers the bench as a target and has a person heading "
        "for it; the live society's state, tick and events and the version's edit history are "
        "unchanged. Declared limit: each run starts from the society's genesis, not from the "
        "live society at the edit's tick (docs/society-experiments.md, 'An earlier input.').",
    )
    status, entry = w1.call(
        "N1.h", "POST", "/world-entries/starter", body={"title": "Q10 alternative"}
    )
    if status != 200:
        raise SystemExit(f"starter answered {status}: {entry}")
    apply(w1, "N1.h", entry, "cc0.market-stall", "stall", "stall")
    entry = read_entry(w1, "N1.h", entry["entry_id"])
    status, _ = w1.call(
        "N1.h",
        "POST",
        version_path(entry, "/society"),
        query=world_query(entry),
        body={"region_id": STARTER_REGION, "profile": SAVED_WORLD_SOCIETY},
    )
    row.expect(status == 200, f"the society answered {status}")
    entry = read_entry(w1, "N1.h", entry["entry_id"])
    status_bench, _ = apply(w1, "N1.h", entry, "cc0.bench", "bench", "bench")
    row.expect(status_bench in (200, 201), f"the bench answered {status_bench}")
    entry = read_entry(w1, "N1.h", entry["entry_id"])
    _, plan = w1.call(
        "N1.h",
        "GET",
        version_path(entry, f"{COMPARISONS}/plan"),
        query={
            **world_query(entry),
            "role": PERSON_ROLE,
            "group": "everyone",
            "model": f"{COMPARED_MODEL['provider']}/{COMPARED_MODEL['model_id']}",
            "seeds": "1",
        },
    )
    newest = (plan.get("plan") or {}).get("input_seq")
    row.expect(newest is not None and newest >= 2, f"the plan freezes input {newest}")
    _, society_before = society(w1, "N1.h", entry)
    events_before, _ = events_history(w1, "N1.h", entry)
    _, version_before = w1.call("N1.h", "GET", version_path(entry), query=world_query(entry))
    bound = (plan.get("plan") or {}).get("suggested_usd") or "0.05"
    reads: dict[str, dict[str, Any]] = {}
    ids: dict[str, str] = {}
    for label, frozen in (("without", 1), ("with", newest)):
        comparison = str(uuid.uuid4())
        status_start, start = w1.call(
            "N1.h",
            "POST",
            version_path(entry, COMPARISONS),
            query=world_query(entry),
            body={
                "comparison_id": comparison,
                "role": PERSON_ROLE,
                "group": {"kind": "everyone"},
                "models": [COMPARED_MODEL],
                "control": False,
                "seeds": 1,
                "bound_usd": str(bound),
                "input_seq": frozen,
            },
        )
        row.expect(
            status_start in (200, 201),
            f"the {label} comparison answered {status_start} {problem_code(start)}",
        )
        ids[label] = comparison
        reads[label] = finished(w1, "N1.h", entry, comparison) if status_start in (200, 201) else {}
    runs: dict[str, dict[str, Any]] = {}
    for label, read in reads.items():
        row.expect(
            (read.get("start") or {}).get("state") == "finished",
            f"the {label} comparison ended {(read.get('start') or {}).get('state')}",
        )
        seeds = read.get("seeds") or []
        statuses = [r.get("status") for s in seeds for r in (s.get("runs") or {}).values()]
        row.expect(
            statuses and all(x == "completed" for x in statuses),
            f"the {label} comparison's runs are {statuses}",
        )
        routine = ((seeds[0].get("runs") or {}).get("routine") or {}) if seeds else {}
        if routine.get("run_id"):
            _, runs[label] = w1.call(
                "N1.h",
                "GET",
                version_path(entry, f"{COMPARISONS}/{ids[label]}/runs/{routine['run_id']}"),
                query=world_query(entry),
            )
    bench_target = f"authored:{entry['authored_version_id']}:bench:rest"
    offered = {
        label: [t.get("target_id") for t in (run.get("place") or {}).get("targets", [])]
        for label, run in runs.items()
    }
    heading = {
        label: sum(
            1
            for minute in run.get("minutes", [])
            for person in minute.get("people", [])
            if (person.get("goal") or {}).get("target_id") == bench_target
        )
        for label, run in runs.items()
    }
    row.expect(set(runs) == {"without", "with"}, f"routine runs read: {sorted(runs)}")
    row.expect(bench_target in offered.get("with", []), "the with-bench run offers no bench")
    row.expect(bench_target not in offered.get("without", []), "the without-bench run offers it")
    row.expect(heading.get("with", 0) > 0, "no person heads for the bench in the with-bench run")
    row.expect(heading.get("without", 0) == 0, "a person heads for a bench that is not there")
    if set(reads) == {"without", "with"}:
        arms = {
            label: sorted(a.get("key") for a in read.get("arms", []))
            for label, read in reads.items()
        }
        digests = {
            label: [s.get("seed_digest") for s in read.get("seeds", [])]
            for label, read in reads.items()
        }
        frozen = {
            label: (read.get("input") or {}).get("input_seq") for label, read in reads.items()
        }
        row.expect(arms["without"] == arms["with"], f"arms differ: {arms}")
        row.expect(digests["without"] == digests["with"], "the seeds differ")
        row.expect(frozen == {"without": 1, "with": newest}, f"frozen inputs {frozen}")
    _, society_after = society(w1, "N1.h", entry)
    events_after, _ = events_history(w1, "N1.h", entry)
    _, version_after = w1.call("N1.h", "GET", version_path(entry), query=world_query(entry))
    row.expect(
        {k: society_after.get(k) for k in ("current_tick", "state_sha256", "input_seq")}
        == {k: society_before.get(k) for k in ("current_tick", "state_sha256", "input_seq")},
        "the live society moved",
    )
    row.expect(events_after == events_before, "the live society's events changed")
    row.expect(
        version_after.get("edits") == version_before.get("edits"), "the edit history changed"
    )
    row.observed = {
        "frozen_inputs": {label: read.get("input") for label, read in reads.items()},
        "states": {label: (read.get("start") or {}).get("state") for label, read in reads.items()},
        "bench_target": bench_target,
        "bench_offered": {label: bench_target in t for label, t in offered.items()},
        "minutes_heading_for_bench": heading,
        "live_society": {
            k: society_after.get(k) for k in ("current_tick", "state_sha256", "input_seq")
        },
        "scripted_calls": scripted_calls(stack),
    }
    row.close()
    results = {
        "profile": "q10-foundation-acceptance-results/v1",
        "candidate": stack.state["tree"],
        "launcher_run": stack.state["run_id"],
        "started_at": started,
        "finished_at": dt.datetime.now(dt.UTC).isoformat(),
        "timing_claims": False,
        "rows": [row.document()],
        "counts": {state: int(row.status == state) for state in STATES},
    }
    (out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True))
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "driver_sha256": DRIVER_SHA256_AT_START,
                "driver_changed_during_run": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                != DRIVER_SHA256_AT_START,
                "launcher_sha256": hashlib.sha256((HERE / "launch.py").read_bytes()).hexdigest(),
                "command": ["foundation.py", *sys.argv[1:]],
                "launcher_state": {k: v for k, v in stack.state.items() if k != "database"},
            },
            indent=2,
            sort_keys=True,
        )
    )
    print(f"{row.row:16} {row.status:8} {'; '.join(row.failures or row.blocked_by)}")
    return 0 if row.status != "failed" else 1


# -- Companion actions (M6 rows F1, F2 and N1.i) -----------------------------------------------------

ACTIONS = "/selection/actions"
COMPANION_PLAN = HERE / "plans" / "companion.json"
COMPANION_TRANSFORM = {
    "x_mm": -6000,
    "y_mm": 0,
    "z_mm": 4000,
    "yaw_microradians": 0,
    "scale_milli": 1000,
}
M6_LANE_TESTS = (
    "tests/test_companion_actions_postgres.py",
    "tests/test_companion_action_plan.py",
    "tests/test_companion_action_policy_boundary.py",
)


def ask_companion(
    c: Client,
    step: str,
    entry: Mapping[str, Any],
    utterance: str,
    base: str | None = None,
    **extra: Any,
) -> tuple[int, dict[str, Any]]:
    body: dict[str, Any] = {
        "version_id": entry["authored_version_id"],
        "base_state_sha256": base or entry["authored_state_sha256"],
        "utterance": utterance,
        "origin_role": "fictional",
        "context": {"placement": {"region_id": STARTER_REGION, "transform": COMPANION_TRANSFORM}},
        "saved_entry": resume_point(entry),
        **extra,
    }
    return c.call(step, "POST", ACTIONS, query=world_query(entry), body=body)


def confirm(c: Client, step: str, entry: Mapping[str, Any], planned: Mapping[str, Any]):
    """Send a prepared step's own request to the route it names, as a direct client would."""
    method, template = planned["operation"].split(" ", 1)
    path = template
    for key, value in (planned.get("bind") or {}).items():
        path = path.replace("{" + key + "}", str(value))
    return c.call(
        step, method, path, query=planned.get("query") or world_query(entry), body=planned["body"]
    )


def outcome(c: Client, step: str, entry: Mapping[str, Any], plan: Mapping[str, Any]):
    return c.call(
        step,
        "POST",
        f"{ACTIONS}/outcome",
        query=world_query(entry),
        body={
            "version_id": entry["authored_version_id"],
            "plan_sha256": plan.get("plan_sha256"),
            "steps": plan.get("steps", []),
        },
    )


def companion(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if (
        Path(stack.state.get("scripted_model", {}).get("plan", "")).name
        != "scripted-model-plan.json"
        or stack.state["scripted_model"]["plan_sha256"]
        != hashlib.sha256(COMPANION_PLAN.read_bytes()).hexdigest()
        or len(stack.state.get("other_workspaces", [])) < 3
        or "read_only_token" not in stack.state
    ):
        raise SystemExit(
            "companion needs a stack started with --scripted-model "
            "scripts/acceptance/plans/companion.json --workspaces 4 --read-only-token"
        )
    utterances = json.loads(COMPANION_PLAN.read_text())["utterances"]
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    w1, w2, w3, w4 = (
        client(stack, transcripts, f"w{i}", LAUNCH.token_file_name(i)) for i in range(1, 5)
    )
    read_only = client(stack, transcripts, "read-only", "token-read")
    rows: list[Row] = []

    def starter(c: Client, title: str) -> dict[str, Any]:
        status, made = c.call("setup", "POST", "/world-entries/starter", body={"title": title})
        if status != 200:
            raise SystemExit(f"starter answered {status}: {made}")
        return made

    # F1: the Companion's placement and the direct placement, compared.
    parity = Row(
        "F1",
        "companion.parity",
        "The Companion plans 'put a bench here' as one prepared composition-apply step whose "
        "preview document equals the direct preview route's answer for the same body; nothing is "
        "written before confirmation; confirming sends the step's own request and is answered by "
        "the direct route, and the outcome read names that edit (same edit id, applied, matching "
        "its preview); the direct placement of the same bench in another workspace yields an edit "
        "and view of the same kind and shape; a repeated confirmation is refused and changes "
        "nothing; a confirmation sent with a read-only grant is refused and the plan reads "
        "not_applied.",
    )
    e1 = starter(w1, "Q10 companion parity")
    calls = scripted_calls(stack)
    control_equal, control = no_write_control(stack, w1, e1)
    before = stack.evidence_digest()
    status_plan, plan = ask_companion(w1, "F1", e1, utterances["bench"])
    after = stack.evidence_digest()
    planned = (plan.get("steps") or [{}])[0]
    parity.expect(control_equal, "the evidence method saw a change across a plain read")
    parity.expect(
        status_plan == 200 and plan.get("outcome") == "plan",
        f"the Companion answered {status_plan} {plan.get('outcome')} "
        f"{(plan.get('refusal') or {}).get('code')}",
    )
    parity.expect(before == after, "planning wrote to the database or store")
    parity.expect(scripted_calls(stack) - calls == 2, "planning did not ask exactly two calls")
    parity.expect(planned.get("state") == "prepared", f"the step is {planned.get('state')}")
    parity.expect(
        planned.get("operation") == "POST /world/versions/{version_id}/compositions/apply",
        f"the step names {planned.get('operation')}",
    )
    status_preview, direct_preview = w1.call(
        "F1",
        "POST",
        version_path(e1, "/compositions/preview"),
        query=world_query(e1),
        body=(planned.get("preview") or {}).get("body"),
    )
    parity.expect(
        status_preview == 200 and direct_preview == (planned.get("preview") or {}).get("document"),
        "the plan's preview differs from the direct preview route's answer",
    )
    status_confirm, confirmed = confirm(w1, "F1", e1, planned)
    status_outcome, read = outcome(w1, "F1", e1, plan)
    receipt = ((read.get("steps") or [{}])[0].get("receipts") or [{}])[0]
    parity.expect(status_confirm == 201, f"confirmation answered {status_confirm}")
    parity.expect(status_outcome == 200, f"the outcome read answered {status_outcome}")
    parity.expect(read.get("state") == "applied", f"the outcome reads {read.get('state')}")
    parity.expect(
        receipt.get("edit_id") == (confirmed.get("edits") or [{}])[-1].get("edit_id"),
        "the outcome names another edit",
    )
    parity.expect(
        (read.get("steps") or [{}])[0].get("matches_preview") is True,
        "the applied edit does not match its preview",
    )
    e2 = starter(w2, "Q10 direct parity")
    status_direct, direct = apply(w2, "F1", e2, "cc0.bench", "bench", "bench")
    companion_edit = (confirmed.get("edits") or [{}])[-1]
    direct_edit = (direct.get("edits") or [{}])[-1]
    parity.expect(status_direct == 201, f"the direct placement answered {status_direct}")
    parity.expect(
        companion_edit.get("kind") == direct_edit.get("kind") == "add_object",
        f"edit kinds {companion_edit.get('kind')} and {direct_edit.get('kind')}",
    )
    parity.expect(sorted(confirmed) == sorted(direct), "the two views differ in shape")
    placed = {o["object_id"]: o for o in confirmed.get("objects", [])}
    mine = placed.get(companion_edit.get("object_id"), {})
    theirs = next((o for o in direct.get("objects", []) if o["object_id"] == "bench"), {})
    same = {k: mine.get(k) == theirs.get(k) for k in ("asset", "region_id", "transform", "origin")}
    parity.expect(all(same.values()), f"the placed objects differ: {same}")
    status_again, again = confirm(w1, "F1", e1, planned)
    parity.expect(
        status_again == 409 and problem_code(again) == "stale_saved_world_entry",
        f"a repeated confirmation answered {status_again} {problem_code(again)}",
    )
    e1 = read_entry(w1, "F1", e1["entry_id"])
    # The world now holds an object, so the form offers an objects slot: the second ask is the one
    # the scripted plan answers with that slot.
    status_second, second = ask_companion(w1, "F1", e1, utterances["bench_by_stall"])
    second_step = (second.get("steps") or [{}])[0]
    parity.expect(
        status_second == 200 and second.get("outcome") == "plan",
        f"a second plan answered {status_second} {second.get('outcome')}",
    )
    status_ro, refused_ro = confirm(read_only, "F1", e1, second_step) if second_step else (None, {})
    _, read_ro = outcome(w1, "F1", e1, second)
    parity.expect(status_ro == 404, f"a read-only confirmation answered {status_ro}")
    parity.expect(read_ro.get("state") == "not_applied", f"it reads {read_ro.get('state')}")
    parity.observed = {
        "plan": {k: plan.get(k) for k in ("outcome", "kind", "plan_sha256", "atomic")},
        "step": {
            k: planned.get(k)
            for k in ("state", "operation", "receipt", "confirmation", "replay", "pins")
        },
        "receipt": receipt,
        "companion_edit": companion_edit,
        "direct_edit": direct_edit,
        "same_object_fields": same,
        "repeat": [status_again, problem_code(again)],
        "read_only": [status_ro, problem_code(refused_ro), read_ro.get("state")],
        "control": control,
    }
    rows.append(parity.close())

    # N1.i: the journey's bench through the Companion, on a world whose people can use it.
    journey_row = Row(
        "N1.i",
        "journey.companion_edit",
        "On a saved starter with a stall and its people brought in, the Companion's bench, "
        "confirmed as F1 confirms, is taken by the society in the next minute and offered as one "
        "rest target, as the direct bench is in N1.c.",
    )
    e3 = starter(w3, "Q10 companion journey")
    apply(w3, "N1.i", e3, "cc0.market-stall", "stall", "stall")
    e3 = read_entry(w3, "N1.i", e3["entry_id"])
    w3.call(
        "N1.i",
        "POST",
        version_path(e3, "/society"),
        query=world_query(e3),
        body={"region_id": STARTER_REGION, "profile": SAVED_WORLD_SOCIETY},
    )
    e3 = read_entry(w3, "N1.i", e3["entry_id"])
    _, held = society(w3, "N1.i", e3)
    status_j, journey_plan = ask_companion(w3, "N1.i", e3, utterances["bench_by_stall"])
    journey_step = (journey_plan.get("steps") or [{}])[0]
    status_jc, _ = confirm(w3, "N1.i", e3, journey_step) if journey_step.get("body") else (None, {})
    took = advance_once(journey_row, w3, "N1.i", e3)
    subject = ((journey_step.get("body") or {}).get("placement") or {}).get("subject_id")
    targets = [
        t for t in (took.get("places") or {}).get("targets", []) if t.get("object_id") == subject
    ]
    journey_row.expect(
        status_j == 200 and journey_plan.get("outcome") == "plan",
        f"the Companion answered {status_j} {journey_plan.get('outcome')}",
    )
    journey_row.expect(status_jc == 201, f"confirmation answered {status_jc}")
    journey_row.expect(
        took.get("input_seq") == (held.get("input_seq") or 0) + 1,
        "the next minute took no new input",
    )
    journey_row.expect(
        [t.get("affordance") for t in targets] == ["rest"],
        "the Companion's bench is not one rest target",
    )
    journey_row.observed = {
        "subject": subject,
        "targets": targets,
        "input_seq": [held.get("input_seq"), took.get("input_seq")],
    }
    rows.append(journey_row.close())

    # F2: what the Companion refuses, and that refusing writes nothing.
    refusals = Row(
        "F2",
        "companion.refusals",
        "With nothing written in any case: a stale base is refused stale_version with no model "
        "call; an utterance naming a digest, a permission and a route, answered with an option "
        "the form never offered, is refused not_drafted with none of the utterance's digest in "
        "the plan; an ambiguous kind is asked about (asset_ambiguous) and the chosen answer is "
        "prepared without a model; a change the form cannot express is refused "
        "action_not_offered; M6's lane tests pass. A model timeout cannot be produced by the "
        "scripted transport and stays unexercised here.",
    )
    e4 = starter(w4, "Q10 companion refusals")
    observed: dict[str, Any] = {}
    control_equal, _ = no_write_control(stack, w4, e4)
    refusals.expect(control_equal, "the evidence method saw a change across a plain read")
    before = stack.evidence_digest()
    calls = scripted_calls(stack)
    _, stale = ask_companion(w4, "F2", e4, utterances["bench"], base=STALE_SHA256)
    refusals.expect(
        (stale.get("refusal") or {}).get("code") == "stale_version",
        f"a stale base is {stale.get('outcome')} {stale.get('refusal')}",
    )
    refusals.expect(scripted_calls(stack) == calls, "a stale request asked a model")
    _, injected = ask_companion(w4, "F2", e4, utterances["inject"])
    refusals.expect(
        (injected.get("refusal") or {}).get("code") == "not_drafted",
        f"the injection is {injected.get('outcome')} {injected.get('refusal')}",
    )
    refusals.expect("b41289ac" not in json.dumps(injected), "the plan carries the digest")
    _, ambiguous = ask_companion(w4, "F2", e4, utterances["seat"])
    clarification = ambiguous.get("clarification") or {}
    refusals.expect(
        clarification.get("code") == "asset_ambiguous",
        f"an ambiguous kind is {ambiguous.get('outcome')} {clarification.get('code')}",
    )
    calls = scripted_calls(stack)
    chosen = [dict((clarification.get("actions") or [{}])[0], asset_key="cc0.bench")]
    status_prep, prepared = w4.call(
        "F2",
        "POST",
        f"{ACTIONS}/prepare",
        query=world_query(e4),
        body={
            "version_id": e4["authored_version_id"],
            "base_state_sha256": e4["authored_state_sha256"],
            "origin_role": "fictional",
            "context": {
                "placement": {"region_id": STARTER_REGION, "transform": COMPANION_TRANSFORM}
            },
            "actions": chosen,
        },
    )
    refusals.expect(
        status_prep == 200 and prepared.get("outcome") == "plan",
        f"preparing the answer gave {status_prep} {prepared.get('outcome')}",
    )
    refusals.expect(scripted_calls(stack) == calls, "preparing asked a model")
    _, other = ask_companion(w4, "F2", e4, utterances["other"])
    refusals.expect(
        (other.get("refusal") or {}).get("code") == "action_not_offered",
        f"an inexpressible change is {other.get('outcome')} {other.get('refusal')}",
    )
    after = stack.evidence_digest()
    refusals.expect(before == after, "a refused or unconfirmed request wrote something")
    lane = subprocess.run(
        [
            str(stack.worktree / ".venv" / "bin" / "python"),
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            *M6_LANE_TESTS,
        ],
        cwd=stack.worktree,
        env={
            **LAUNCH.clean_environment(),
            "EXULANICA_TEST_POSTGRES": "private",
            "EXULANICA_REQUIRE_POSTGRES": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    (out / "evidence" / "f2-lane-tests.txt").write_text(lane.stdout + lane.stderr)
    refusals.expect(lane.returncode == 0, f"M6's lane tests exited {lane.returncode}")
    observed.update(
        {
            "stale": stale.get("refusal"),
            "injection": injected.get("refusal"),
            "injection_calls": [
                c.get("outcome") for c in (injected.get("execution") or {}).get("calls", [])
            ],
            "ambiguous": {k: clarification.get(k) for k in ("code", "slot")},
            "prepared": prepared.get("outcome"),
            "other": other.get("refusal"),
            "lane_tests_exit": lane.returncode,
            "timeout": "not exercised (scripted transport)",
        }
    )
    refusals.observed = observed
    rows.append(refusals.close())

    results = {
        "profile": "q10-foundation-acceptance-results/v1",
        "candidate": stack.state["tree"],
        "launcher_run": stack.state["run_id"],
        "started_at": started,
        "finished_at": dt.datetime.now(dt.UTC).isoformat(),
        "timing_claims": False,
        "rows": [row.document() for row in rows],
        "counts": {state: sum(r.status == state for r in rows) for state in STATES},
    }
    (out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True))
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "driver_sha256": DRIVER_SHA256_AT_START,
                "driver_changed_during_run": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                != DRIVER_SHA256_AT_START,
                "launcher_sha256": hashlib.sha256((HERE / "launch.py").read_bytes()).hexdigest(),
                "plan_sha256": stack.state["scripted_model"]["plan_sha256"],
                "command": ["foundation.py", *sys.argv[1:]],
                "launcher_state": {k: v for k, v in stack.state.items() if k != "database"},
            },
            indent=2,
            sort_keys=True,
        )
    )
    for row in rows:
        print(f"{row.row:16} {row.status:8} {'; '.join(row.failures or row.blocked_by)}")
    print(json.dumps(results["counts"]))
    return 0 if results["counts"]["failed"] == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("baseline")
    run.add_argument("--worktree", required=True)
    run.add_argument("--out", required=True)
    run.add_argument(
        "--w7-client",
        help="W7's delivered client-example.py, pinned by digest, for rows G1 and G3",
    )
    run.add_argument(
        "--exercise-own-worlds-only",
        action="store_true",
        help="A4-client also requires F1's exercise client to leave every saved world that "
        "existed before it untouched (amendment A-16; for candidates carrying F1's change)",
    )
    probe = commands.add_parser("isolation-client")
    for name in ("--base-url", "--token-file", "--own", "--foreign", "--out"):
        probe.add_argument(name, required=True)
    probe.add_argument("--rounds", type=int, default=ISOLATION_ROUNDS)
    reopen = commands.add_parser("reopen-client")
    for name in ("--base-url", "--token-file", "--entry", "--out"):
        reopen.add_argument(name, required=True)
    talk = commands.add_parser("companion")
    talk.add_argument("--worktree", required=True)
    talk.add_argument("--out", required=True)
    other = commands.add_parser("alternative")
    other.add_argument("--worktree", required=True)
    other.add_argument("--out", required=True)
    money = commands.add_parser("spending")
    money.add_argument("--worktree", required=True)
    money.add_argument("--out", required=True)
    spender = commands.add_parser("spend-client")
    for name in ("--base-url", "--token-file", "--out"):
        spender.add_argument(name, required=True)
    spender.add_argument("--seconds", type=float, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return {
        "baseline": baseline,
        "isolation-client": isolation_client,
        "reopen-client": reopen_client,
        "spending": spending,
        "alternative": alternative,
        "companion": companion,
        "spend-client": spend_client,
    }[arguments.command](arguments)


if __name__ == "__main__":
    sys.exit(main())
