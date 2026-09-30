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
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]
sys.path.insert(0, str(REPOSITORY / "clients" / "python"))

from exulanica_client.client import Exchange, WorldClient  # noqa: E402


def _launcher() -> Any:
    spec = importlib.util.spec_from_file_location("exulanica_acceptance_launch", HERE / "launch.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LAUNCH = _launcher()

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

    def restart_api(self, revoke: str | None = None) -> dict[str, Any]:
        command = [
            sys.executable,
            str(HERE / "launch.py"),
            "restart-api",
            "--worktree",
            str(self.worktree),
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
        "attestation": human_attestation(stack),
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


def row_a4_discovery(w1: Client, starter: Mapping[str, Any]) -> Row:
    row = Row(
        "A4",
        "discover.per_kind",
        "Per-kind capability discovery (F1): GET /worlds/capabilities and GET "
        "/world/versions/{v}/capabilities.",
    )
    status_kinds, _ = w1.call("A4", "GET", "/worlds/capabilities")
    status_version, _ = w1.call(
        "A4", "GET", version_path(starter, "/capabilities"), query=world_query(starter)
    )
    row.observed = {"worlds_capabilities": status_kinds, "version_capabilities": status_version}
    if status_kinds == 404 and status_version == 404:
        row.blocked_by.append("F1 capability projection not in this candidate (both routes 404)")
    return row.close()


def row_b1_no_model(
    stack: Stack, w1: Client, starter: Mapping[str, Any], town: Mapping[str, Any] | None
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
        "scripted-model mode (B2) not yet built; no-model answers 503",
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
        "join": "event.document.target.object_id -> version.edits[].object_id",
        "edits_naming_bench": [
            {"edit_id": e["edit_id"], "edit_seq": e["edit_seq"], "kind": e["kind"]} for e in added
        ],
    }
    cause.blocked_by.append(
        "N-G4 (F1): no read links an event's input_seq to the authored edit; joined by object_id"
    )
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

    for identity, check, expected, blockers in (
        (
            "N1.h",
            "journey.alternative",
            "Compare the world without the bench from an exact starting state, original history "
            "preserved.",
            ["N-G5 (V7): no edit-alternative comparison on the saved-world engine"],
        ),
        (
            "N1.i",
            "journey.companion_edit",
            "The same bench edit through the Companion with identical receipts.",
            ["M6 not delivered", "scripted-model mode (B2) not yet built"],
        ),
        (
            "N1.j",
            "journey.browser",
            "The production browser performs preview, confirm, response and explanation.",
            ["not part of BASELINE-0; browser rehearsal step not yet written"],
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
    rows.append(row_a4_discovery(w1, read_entry(w1, "A4", w1_entry["entry_id"])))
    rows.append(
        row_b1_no_model(
            stack, w1, read_entry(w1, "B1", w1_entry["entry_id"]), towns[0] if towns else None
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
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("baseline")
    run.add_argument("--worktree", required=True)
    run.add_argument("--out", required=True)
    probe = commands.add_parser("isolation-client")
    for name in ("--base-url", "--token-file", "--own", "--foreign", "--out"):
        probe.add_argument(name, required=True)
    probe.add_argument("--rounds", type=int, default=ISOLATION_ROUNDS)
    reopen = commands.add_parser("reopen-client")
    for name in ("--base-url", "--token-file", "--entry", "--out"):
        reopen.add_argument(name, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return {
        "baseline": baseline,
        "isolation-client": isolation_client,
        "reopen-client": reopen_client,
    }[arguments.command](arguments)


if __name__ == "__main__":
    sys.exit(main())
