#!/usr/bin/env python3
"""The domain rows the foundation driver does not check, against a running acceptance stack.

    .venv/bin/python scripts/acceptance/domain_rows.py comparisons --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/domain_rows.py assets      --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/domain_rows.py characters  --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/domain_rows.py catalog     --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/domain_rows.py made-with   --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/domain_rows.py packs       --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/domain_rows.py kinds       --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/domain_rows.py references  --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/domain_rows.py things      --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/domain_rows.py door        --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/domain_rows.py guests      --worktree PATH --out DIR

Each subcommand checks rows against the stack ``launch.py up`` started for ``--worktree``,
restarts that stack's API with ``launch.py restart-api`` where a row needs a fresh process, and
leaves the stack running:

- ``comparisons``: H1 (two models deciding for a generated town's people, a same-model control and
  a cancel), H2 (fixed signal timing against two models), H3 (the living town's reading line,
  from V7's record on the candidate) and H4 (its day line, from the day record the candidate's
  catalog binds). The stack is started with ``--workspaces 2
  --read-only-token --scripted-model scripts/acceptance/plans/comparisons.json --spending process
  --society-playback --no-derivative-worker``: the plan answers each model's asks by choosing
  among the options the request itself offers, so the two models choose differently and the same
  model always chooses alike.
- ``assets``: D2 (a workspace asset's admission, preparation, placement and withdrawal) and D3
  (its refusals). The stack is started with ``--workspaces 2 --no-derivative-worker`` and no
  scripted model; the driver runs the installation's asset preparation process itself.
- ``characters``: E1 (two character families of different kinds) and E2 (a catalog's next
  revision, then its withdrawal). Any stack whose launcher published the character catalogs.
- ``catalog``: E4 (an option the host publishes appears in the production page's look editor
  without a rebuild), through ``catalog_browser.mjs`` under gpu-slot then quiet-slot, on a
  ``--production`` stack.
- ``made-with``: A5 (a generated world's saved entry states what it was made with, and a new world
  made from those values states the same). The stack is started with ``--workspaces 2
  --no-derivative-worker``.
- ``references``: R1 (reference notes where the installation does not offer them). The stack is
  started with ``--workspaces 2 --read-only-token --no-derivative-worker`` and no reference worker.
- ``things``: T1 (the shipped thing library), T2 (a placed thing) and SC1 (the demo scene built
  through the public routes). Any stack with two workspaces.
- ``door``: D1 (the door's grants for an outside program). The stack is started with ``--workspaces
  2 --read-only-token --no-derivative-worker --door-bridges FILE``, FILE holding AGENTS' example
  bridge entry as shipped.
- ``guests``: V1 (a guest enters by the run's code, through the local HTTPS edge, and the model
  chosen for its people spends from its own allowance). The stack is started with
  ``--accounts-guest-code --edge-port PORT --tiles --scripted-model
  scripts/acceptance/plans/comparisons.json --spending durable --society-playback
  --no-derivative-worker``; the driver trusts the edge's root
  certificate in its own process only, and never writes the code or a session's CSRF token.
- ``packs``: S1 (the committed style pack library the host serves, against the committed files)
  and S2 (a world's appearance naming its pack). Any stack with two workspaces.
- ``kinds``: W1 (a creator's world kind kept in its workspace), W2 (a world of a kind, its site
  drawing, title and body limits) and W3 (people living in it). The stack is started with
  ``--workspaces 2 --read-only-token --no-derivative-worker``.
- ``kind-drafts``: KD1 (a kind of place drafted from words, kept with its provenance and never the
  words). The stack is started with ``--workspaces 2 --peer-token --scripted-model
  scripts/acceptance/plans/kind-draft.json --spending process --no-derivative-worker``.
- ``pieces``: PR1 (asking for a look's generated pieces, with no generation session). The stack is
  started with ``--workspaces 2 --scripted-model scripts/acceptance/plans/spending.json --spending
  durable --no-derivative-worker``; the driver issues a GPU authority and grants as an operator does.
- ``hands``: HN1 (a being picks a thing up in a society of things). A fresh database, and the stack
  started with ``--workspaces 2 --society-of-things --society-playback --scripted-model
  scripts/acceptance/plans/hands.json --spending process --no-derivative-worker``.
- ``picture-rights``: LP1 (a picture's reading right stopped by its grantor, with the grantor's
  other rights on the picture and never a later consent). The stack is started with ``--workspaces
  2 --peer-token --reference-pictures --scripted-model scripts/acceptance/plans/spending.json
  --spending durable --no-derivative-worker --depth-worker``: pictures are offered only where a
  reference worker, a model client and durable spending run.
- ``guest-turns``: V7 (every waiting guest takes a turn) and PR2 (a guest asking for pieces). The
  stack is started as ``guest-places``'s; ``guest-allowance`` also checks KD2 (drafting refused
  before anything is spent when a guest's allowance cannot cover one attempt).

Every row ends ``passed``, ``failed`` or ``blocked``, by the rules of ``foundation.py``, whose
records, clients and stack this file uses. Like it, this is an independent client: it imports
nothing from ``exulanica`` and speaks HTTP through the repository's standard-library developer
client. Its other reads are evidence reads, marked as such (the scripted model's request log, the
run's store and database digests), and its other acts are an installation's own commands run as
the role an installation runs them as (asset preparation as the runtime role, character catalog
publication as the host administrator). Rows with a scripted model establish mechanics only,
never model quality, and nothing here makes a timing claim.

Outputs under ``--out``: ``results.json``, ``transcripts/<client>.jsonl``, ``evidence/`` and
``manifest.json`` (the tree, this file's and ``foundation.py``'s digests at start, the launcher run).
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import secrets
import ssl
import struct
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _foundation() -> Any:
    name = "exulanica_acceptance_foundation"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / "foundation.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Its dataclasses resolve their own module by name while the class is made.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


F = _foundation()
LAUNCH = F.LAUNCH
Row, Stack, Transcripts = F.Row, F.Stack, F.Transcripts
#: This file's digest as the run began; the run records whether it changed before the end.
DRIVER_SHA256_AT_START = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

#: The plan every comparisons run is served by, and the two models it answers differently: the
#: first chooses a place to go, the second to wait, each among the options the request offers.
COMPARISONS_PLAN = HERE / "plans" / "comparisons.json"
GOING_MODEL = {"provider": "nebius_token_factory", "model_id": "Qwen/Qwen3-235B-A22B-Instruct-2507"}
WAITING_MODEL = {
    "provider": "nebius_token_factory",
    "model_id": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
}
PERSON_ROLE = "society_decision"
#: A living town, the engine a generated town's society runs, over the generated ground's region.
TOWN_ENGINE = "exulanica-society/v5"
TOWN_REGION = "region:generated"
#: How many of the town's people H1's group names, and how many development seeds it runs.
GROUP_SIZE = 6
H1_SEEDS = 2
#: The cancelled comparison: everybody, over enough seeds that a host is still playing it when
#: the cancel arrives.
CANCEL_SEEDS = 3
#: Every arm a comparison of two models with a control plays, by the start's own keys.
H1_ARMS = {"routine", "wait", "model_a", "model_b", "model_a_again"}
#: How long a host may take to play a comparison, how often the driver looks, and how long it
#: waits after a restart for anything to resume: past the comparison lease (30 s) by a margin.
PLAY_SECONDS = 900
CANCEL_LOOK_SECONDS = 0.2
QUIET_AFTER_RESTART_SECONDS = 75
CANCELLED = "comparison_cancelled"
#: The developer client a reader outside the application runs, as a separate process.
DEVELOPER_CLIENT = Path("clients") / "python"
#: V7's and the existing comparison tests the row re-runs on the candidate.
H1_TESTS = (
    "tests/test_developer_client_comparisons.py",
    "tests/test_comparison_cancel_postgres.py",
    "tests/test_comparison_frozen_input_postgres.py",
    "tests/test_living_town_comparison_capacity_postgres.py",
)


# -- shared ----------------------------------------------------------------------------------------


def comparisons_path(entry: Mapping[str, Any], suffix: str = "") -> str:
    return F.version_path(entry, f"/society/comparisons{suffix}")


def model_text(model: Mapping[str, str]) -> str:
    return f"{model['provider']}/{model['model_id']}"


def scripted_log(stack: Stack) -> list[dict[str, Any]]:
    """An evidence read: every request the scripted model answered, in order."""
    log = Path(stack.state["scripted_model"]["log"])
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def read_comparison(c: Any, step: str, entry: Mapping[str, Any], comparison: str):
    return c.call(
        step, "GET", comparisons_path(entry, f"/{comparison}"), query=F.world_query(entry)
    )


def played(c: Any, step: str, entry: Mapping[str, Any], comparison: str) -> dict[str, Any]:
    """The comparison once its start finished or closed, or as last read when the time ran out."""
    deadline = time.monotonic() + PLAY_SECONDS
    read: dict[str, Any] = {}
    while time.monotonic() < deadline:
        _, read = read_comparison(c, step, entry, comparison)
        if (read.get("start") or {}).get("finished_at"):
            return read
        time.sleep(2)
    return read


def runs_of(read: Mapping[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Every run a comparison read lists: its seed's digest, its arm and the run."""
    return [
        (seed.get("seed_digest"), arm, run)
        for seed in read.get("seeds") or []
        for arm, run in sorted((seed.get("runs") or {}).items())
    ]


def live_state(c: Any, step: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    """What a comparison must leave as it was: the live society, its events and the edits."""
    _, society = F.society(c, step, entry)
    history, _ = F.events_history(c, step, entry)
    _, version = c.call(step, "GET", F.version_path(entry), query=F.world_query(entry))
    return {
        "society": {k: society.get(k) for k in ("current_tick", "state_sha256", "input_seq")},
        "events_sha256": F.canonical_sha256(history),
        "events": len(history),
        "edits_sha256": F.canonical_sha256(version.get("edits")),
        "version_state_sha256": version.get("state_sha256"),
    }


def entry_point(worktree: Path, name: str) -> list[str]:
    """The command an installation runs as ``name``: the function ``pyproject.toml`` declares for
    it, called by the checkout's interpreter, so a virtual environment installed before the entry
    point was declared still runs the checkout's own command."""
    scripts = tomllib.loads((worktree / "pyproject.toml").read_text())["project"]["scripts"]
    module, function = scripts[name].split(":")
    return [
        str(worktree / ".venv" / "bin" / "python"),
        "-c",
        f"import sys; from {module} import {function} as main; sys.exit(main())",
    ]


def lane_tests(out: Path, worktree: Path, name: str, tests: Sequence[str]) -> dict[str, Any]:
    """The owners' tests the row re-runs on the candidate, against a private PostgreSQL server."""
    completed = subprocess.run(
        [
            str(worktree / ".venv" / "bin" / "python"),
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            *tests,
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
    (out / "evidence" / f"{name}.txt").write_text(completed.stdout + completed.stderr)
    tail = completed.stdout.strip().splitlines()[-1:] or [""]
    return {"tests": list(tests), "exit": completed.returncode, "summary": tail[0]}


def write_results(
    out: Path, stack: Stack, rows: Sequence[Any], started: str, command: Sequence[str]
) -> dict[str, Any]:
    results = {
        "profile": "q10-foundation-acceptance-results/v1",
        "candidate": stack.state["tree"],
        "launcher_run": stack.state["run_id"],
        "started_at": started,
        "finished_at": dt.datetime.now(dt.UTC).isoformat(),
        "timing_claims": False,
        "rows": [row.document() for row in rows],
        "counts": {state: sum(row.status == state for row in rows) for state in F.STATES},
    }
    (out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True))
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "driver_sha256": DRIVER_SHA256_AT_START,
                "driver_changed_during_run": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                != DRIVER_SHA256_AT_START,
                "foundation_sha256": F.DRIVER_SHA256_AT_START,
                "launcher_sha256": hashlib.sha256((HERE / "launch.py").read_bytes()).hexdigest(),
                "command": ["domain_rows.py", *command],
                "launcher_state": {k: v for k, v in stack.state.items() if k != "database"},
            },
            indent=2,
            sort_keys=True,
        )
    )
    for row in rows:
        print(f"{row.row:16} {row.status:8} {'; '.join(row.failures or row.blocked_by)}")
    return results


# -- H1: a comparison of two models with a control, from outside -----------------------------------


def generated_town(c: Any, step: str, title: str) -> dict[str, Any]:
    """A small town made through the application, with its living society brought in."""
    status, town = c.call(
        step, "POST", "/worlds/generated", body={"recipe": "small_town", "title": title}
    )
    if status != 201:
        raise SystemExit(f"the town answered {status}: {town}")
    status, society = c.call(
        step,
        "POST",
        F.version_path(town, "/society"),
        query=F.world_query(town),
        body={"region_id": TOWN_REGION, "profile": TOWN_ENGINE},
    )
    if status not in (200, 201):
        raise SystemExit(f"the town's society answered {status}: {society}")
    return F.read_entry(c, step, town["entry_id"])


def plan_of(
    c: Any,
    step: str,
    entry: Mapping[str, Any],
    models: Sequence[Mapping[str, str]],
    *,
    control: bool,
    seeds: int,
    people: Sequence[str] = (),
    window: str = "hour",
) -> tuple[int, dict[str, Any]]:
    query: dict[str, Any] = {
        **F.world_query(entry),
        "role": PERSON_ROLE,
        "group": "named" if people else "everyone",
        "seeds": str(seeds),
        "control": "true" if control else "false",
    }
    if window != "hour":
        query["window"] = window
    # The client takes one value per name, so repeated names ride in a list the server reads.
    pairs = [*query.items(), *(("model", model_text(m)) for m in models)]
    pairs += [("person", person) for person in people]
    return c.call(step, "GET", comparisons_path(entry, "/plan") + "?" + _encoded(pairs))


def _encoded(pairs: Sequence[tuple[str, str]]) -> str:
    return urllib.parse.urlencode(list(pairs))


def bound_from(plan: Mapping[str, Any]) -> str:
    """The bound a start states: what the plan says lets a typical comparison finish, never above
    the most it can cost."""
    planned = plan.get("plan") or {}
    most = Decimal(str(planned.get("most_usd") or "0"))
    suggested = Decimal(str(planned.get("suggested_usd") or most))
    return format(min(most, suggested) if most > 0 else suggested, "f")


def start_body(
    comparison: str,
    models: Sequence[Mapping[str, str]],
    *,
    control: bool,
    seeds: int,
    bound: str,
    people: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "comparison_id": comparison,
        "role": PERSON_ROLE,
        "group": {"kind": "named", "people": list(people)} if people else {"kind": "everyone"},
        "models": [dict(m) for m in models],
        "control": control,
        "seeds": seeds,
        "bound_usd": bound,
    }


def independent_reader(
    stack: Stack, out: Path, entry: Mapping[str, Any], comparison: str, label: str
) -> dict[str, Any]:
    """The developer client, a separate process with no site directory, holding ``world.read``
    alone, reads the comparison and checks what it says from its reads."""
    transcript = out / "evidence" / f"reader-{label}.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            "-s",
            "-E",
            "-m",
            "exulanica_client",
            "comparisons",
            "--base-url",
            stack.base_url,
            "--world",
            entry["world_id"],
            "--version",
            entry["authored_version_id"],
            "--comparison",
            comparison,
            "--transcript",
            str(transcript),
        ],
        cwd=stack.worktree / DEVELOPER_CLIENT,
        env={
            "PATH": os.environ.get("PATH", ""),
            "EXULANICA_TOKEN": stack.token_file("token-read").read_text().strip(),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    (out / "evidence" / f"reader-{label}.txt").write_text(completed.stdout + completed.stderr)
    record = json.loads(transcript.read_text()) if transcript.exists() else {}
    return {
        "exit": completed.returncode,
        "result": record.get("result"),
        "checks": record.get("checks", []),
        "runs_read": record.get("runs_read", []),
    }


#: A comparison start's states, in the order the host moves it (A-91).
START_STATES = ("waiting", "running", "finished")


def same_start(first: Any, again: Any) -> bool:
    """Whether a resent start answered the same comparison: the same document but each start's
    state, which may have moved on between the two sends (A-91)."""

    def states_and_rest(document: Any) -> tuple[list[Any], Any]:
        if not isinstance(document, dict):
            return [], document
        rest = json.loads(json.dumps(document))
        states = []
        for comparison in rest.get("comparisons") or []:
            start = comparison.get("start") if isinstance(comparison, dict) else None
            states.append(start.pop("state", None) if isinstance(start, dict) else None)
        return states, rest

    before, rest_first = states_and_rest(first)
    after, rest_again = states_and_rest(again)
    return (
        rest_first == rest_again
        and len(before) == len(after)
        and all(
            a in START_STATES
            and b in START_STATES
            and START_STATES.index(b) >= START_STATES.index(a)
            for a, b in zip(before, after, strict=True)
        )
    )


def row_h1(stack: Stack, transcripts: Any, out: Path) -> tuple[Row, dict[str, Any]]:
    row = Row(
        "H1",
        "compare.person",
        "On a generated town's living society, a comparison of two scripted models deciding for a "
        "named group, with the first run again as the control, is planned, started (the same start "
        "sent again finds it) and played by the host from the society's input as it stood: every "
        "run of every arm on every seed completes, every arm shares the seeds, the control arm "
        "chose as its model did, and the pair chose differently; a reader outside the application "
        "with world.read alone confirms the start finished within its bound, every planned run has "
        "an outcome and every model run was replayed from its record with exactly the asks it "
        "counted; another workspace cannot read it; after an API restart every read answers the "
        "same with no model call; the live society, its events and the version's edits are "
        "unchanged; each run reads a score and no traffic delay. A second comparison cancelled "
        "while a host plays it closes as "
        "comparison_cancelled with no run left open, a repeated cancel finds the first and changes "
        "nothing, and after a restart and the comparison lease no further model call is made. The "
        "existing reader test and V7's cancel, frozen-input and living-town tests pass on the "
        "candidate. Scripted answers: mechanics only.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    entry = generated_town(w1, "H1", "Q10 H1 town")
    _, society = F.society(w1, "H1", entry)
    population = len(((society.get("state") or {}).get("inhabitants")) or [])
    status_plan, plan = plan_of(w1, "H1", entry, [GOING_MODEL], control=False, seeds=1)
    people = [p.get("id") for p in (plan.get("people") or [])][:GROUP_SIZE]
    row.expect(status_plan == 200, f"the plan answered {status_plan}")
    row.expect(len(people) == GROUP_SIZE, f"the plan names {len(people)} people")
    models = [GOING_MODEL, WAITING_MODEL]
    status_plan, plan = plan_of(
        w1, "H1", entry, models, control=True, seeds=H1_SEEDS, people=people
    )
    row.expect(status_plan == 200, f"the selection's plan answered {status_plan}")
    row.expect(plan.get("plan_refusal") is None, f"the plan refuses: {plan.get('plan_refusal')}")
    before = live_state(w1, "H1", entry)
    comparison = str(uuid.uuid4())
    body = start_body(
        comparison, models, control=True, seeds=H1_SEEDS, bound=bound_from(plan), people=people
    )
    status_start, start = w1.call(
        "H1", "POST", comparisons_path(entry), query=F.world_query(entry), body=body
    )
    row.expect(status_start == 201, f"the start answered {status_start} {F.problem_code(start)}")
    status_again, again = w1.call(
        "H1", "POST", comparisons_path(entry), query=F.world_query(entry), body=body
    )
    row.expect(
        status_again in (200, 201) and same_start(start, again),
        f"the same start sent again answered {status_again} {F.problem_code(again)}",
    )
    read = played(w1, "H1", entry, comparison)
    start_read = read.get("start") or {}
    row.expect(start_read.get("state") == "finished", f"the start ended {start_read.get('state')}")
    runs = runs_of(read)
    arms = {arm for _, arm, _ in runs}
    statuses = sorted({run.get("status") for _, _, run in runs})
    seeds = {arm: sorted({s for s, a, _ in runs if a == arm}) for arm in arms}
    row.expect(arms == H1_ARMS, f"the arms played are {sorted(arms)}")
    row.expect(len(runs) == len(H1_ARMS) * H1_SEEDS, f"{len(runs)} runs read")
    row.expect(statuses == ["completed"], f"the runs ended {statuses}")
    row.expect(
        len({tuple(v) for v in seeds.values()}) == 1
        and len(next(iter(seeds.values()), [])) == H1_SEEDS,
        "the arms did not share the seeds",
    )
    run_keys = {key for _, _, run in runs for key in run}
    row.expect(
        "score" in run_keys and not run_keys & {"measure", "delay_ms", "mean_delay_ms"},
        f"a person run reads {sorted(run_keys)}",
    )
    frozen = read.get("input") or {}
    row.expect(
        frozen.get("input_seq") == before["society"]["input_seq"],
        f"the comparison froze input {frozen.get('input_seq')}, not the society's newest "
        f"{before['society']['input_seq']}",
    )
    # What each model arm chose, from the runs the server replays.
    chosen: dict[str, dict[str, list[str]]] = {}
    replays: dict[str, Any] = {}
    for seed, arm, run in runs:
        if arm not in ("model_a", "model_b", "model_a_again") or not run.get("run_id"):
            continue
        status_run, drawn = w1.call(
            "H1",
            "GET",
            comparisons_path(entry, f"/{comparison}/runs/{run['run_id']}"),
            query=F.world_query(entry),
        )
        row.expect(status_run == 200, f"run {arm} answered {status_run}")
        row.expect(drawn.get("replay_verified") is True, f"run {arm} was not replayed from record")
        replays[run["run_id"]] = drawn
        chosen.setdefault(arm, {})[seed] = [
            str(d.get("chose")) for d in drawn.get("decisions") or [] if d.get("chose")
        ]
    row.expect(
        chosen.get("model_a") == chosen.get("model_a_again"),
        "the control arm chose otherwise than its model's arm",
    )
    row.expect(
        bool(chosen.get("model_a")) and chosen.get("model_a") != chosen.get("model_b"),
        "the two models chose alike",
    )
    reader = independent_reader(stack, out, entry, comparison, "h1")
    row.expect(reader["exit"] == 0, f"the outside reader exited {reader['exit']}")
    row.expect(
        reader["result"] == "confirmed", f"the outside reader's result is {reader['result']}"
    )
    row.expect(
        bool(reader["checks"]) and all(check.get("holds") for check in reader["checks"]),
        "an outside reader's check does not hold",
    )
    status_foreign, foreign = w2.call(
        "H1",
        "GET",
        comparisons_path(entry, f"/{comparison}"),
        query=F.world_query(entry),
    )
    row.expect(
        status_foreign == 404 and F.problem_code(foreign) == "unknown_reference",
        f"another workspace's read answered {status_foreign} {F.problem_code(foreign)}",
    )
    calls_played = len(scripted_log(stack))
    restart = stack.restart_api()
    _, reread = read_comparison(w1, "H1 after restart", entry, comparison)
    replays_after = {
        run_id: w1.call(
            "H1 after restart",
            "GET",
            comparisons_path(entry, f"/{comparison}/runs/{run_id}"),
            query=F.world_query(entry),
        )[1]
        for run_id in replays
    }
    calls_after = len(scripted_log(stack))
    row.expect(reread == read, "the comparison read differently after the restart")
    row.expect(replays_after == replays, "a run read differently after the restart")
    row.expect(
        calls_after == calls_played,
        f"reading after the restart made {calls_after - calls_played} calls",
    )
    after = live_state(w1, "H1", entry)
    row.expect(after == before, "the live society, its events or the version's edits changed")
    cancel = cancel_while_played(stack, w1, entry, row)
    tests = lane_tests(out, stack.worktree, "h1-tests", H1_TESTS)
    row.expect(
        tests["exit"] == 0, f"the comparison tests exited {tests['exit']}: {tests['summary']}"
    )
    row.observed = {
        "town": {
            "entry_id": entry["entry_id"],
            "population": population,
            "generated_ground": entry.get("generated_ground"),
        },
        "comparison_id": comparison,
        "group": len(people),
        "bound_usd": body["bound_usd"],
        "start": start_read,
        "input": frozen,
        "arms": sorted(arms),
        "run_statuses": statuses,
        "verdict": read.get("verdict"),
        "chosen_counts": {
            arm: {seed: len(c) for seed, c in by_seed.items()} for arm, by_seed in chosen.items()
        },
        "chosen_kinds": {
            arm: sorted({choice.split(",")[0] for c in by_seed.values() for choice in c})[:6]
            for arm, by_seed in chosen.items()
        },
        "reader": {k: reader[k] for k in ("exit", "result")}
        | {"checks_held": sum(bool(c.get("holds")) for c in reader["checks"])},
        "foreign_read": [status_foreign, F.problem_code(foreign)],
        "scripted_calls": {"played": calls_played, "after_restart_reads": calls_after},
        "restart": restart,
        "live": after,
        "cancel": cancel,
        "tests": tests,
    }
    return row.close(), entry


def cancel_while_played(stack: Stack, c: Any, entry: Mapping[str, Any], row: Row) -> dict[str, Any]:
    """Start a comparison of everybody, cancel it once a host is playing it and its model has been
    asked, cancel it again, and watch that nothing asks the model after it closed, across a
    restart and past the comparison lease."""
    status_plan, plan = plan_of(
        c, "H1 cancel", entry, [GOING_MODEL], control=False, seeds=CANCEL_SEEDS
    )
    row.expect(
        status_plan == 200 and plan.get("plan_refusal") is None,
        f"the cancel comparison's plan answered {status_plan} {plan.get('plan_refusal')}",
    )
    comparison = str(uuid.uuid4())
    asked_before = len(scripted_log(stack))
    status, _ = c.call(
        "H1 cancel",
        "POST",
        comparisons_path(entry),
        query=F.world_query(entry),
        body=start_body(
            comparison, [GOING_MODEL], control=False, seeds=CANCEL_SEEDS, bound=bound_from(plan)
        ),
    )
    row.expect(status == 201, f"the comparison to cancel answered {status}")
    deadline = time.monotonic() + PLAY_SECONDS
    playing: dict[str, Any] = {}
    while time.monotonic() < deadline:
        _, playing = read_comparison(c, "H1 cancel", entry, comparison)
        running = any(
            (run.get("progress") or {}).get("state") == "running" for _, _, run in runs_of(playing)
        )
        if (playing.get("start") or {}).get("finished_at") or (
            running and len(scripted_log(stack)) > asked_before
        ):
            break
        time.sleep(CANCEL_LOOK_SECONDS)
    in_play = not (playing.get("start") or {}).get("finished_at")
    row.expect(in_play, "the comparison finished before it could be cancelled while played")
    status_first, first = c.call(
        "H1 cancel",
        "POST",
        comparisons_path(entry, f"/{comparison}/cancel"),
        query=F.world_query(entry),
    )
    status_second, second = c.call(
        "H1 cancel",
        "POST",
        comparisons_path(entry, f"/{comparison}/cancel"),
        query=F.world_query(entry),
    )
    cancelled_at = [
        ((entry_read.get("start") or {}).get("cancel") or {}).get("requested_at")
        for entry_read in ((first or {}).get("comparisons") or [{}])[:1]
        + ((second or {}).get("comparisons") or [{}])[:1]
    ]
    row.expect(status_first == 200, f"the cancel answered {status_first} {F.problem_code(first)}")
    row.expect(status_second == 200, f"the repeated cancel answered {status_second}")
    row.expect(
        len(cancelled_at) == 2
        and cancelled_at[0] is not None
        and cancelled_at[0] == cancelled_at[1],
        f"the repeated cancel did not find the first: {cancelled_at}",
    )
    closed = played(c, "H1 cancel", entry, comparison)
    start = closed.get("start") or {}
    left = [
        run for _, _, run in runs_of(closed) if run.get("status") not in ("completed", "failed")
    ]
    failures = sorted(
        {str(run.get("failure")) for _, _, run in runs_of(closed) if run.get("status") == "failed"}
    )
    row.expect(
        start.get("closed_reason") == CANCELLED,
        f"the cancelled start closed as {start.get('closed_reason')} ({start.get('state')})",
    )
    row.expect(not left, f"{len(left)} runs were left open")
    row.expect(
        any(CANCELLED in failure for failure in failures),
        f"no run failed as {CANCELLED}: {failures}",
    )
    asked_at_close = len(scripted_log(stack))
    restart = stack.restart_api()
    time.sleep(QUIET_AFTER_RESTART_SECONDS)
    _, later = read_comparison(c, "H1 cancel after restart", entry, comparison)
    asked_later = len(scripted_log(stack))
    row.expect(
        asked_later == asked_at_close, f"{asked_later - asked_at_close} calls after the close"
    )
    row.expect(
        later.get("start") == start, "the cancelled start read differently after the restart"
    )
    row.expect(
        [run.get("status") for _, _, run in runs_of(later)]
        == [run.get("status") for _, _, run in runs_of(closed)],
        "a cancelled comparison's run changed after the restart",
    )
    return {
        "comparison_id": comparison,
        "in_play_when_cancelled": in_play,
        "cancel": [status_first, status_second, cancelled_at],
        "start": start,
        "run_failures": failures,
        "runs": len(runs_of(closed)),
        "scripted_calls": {
            "before_start": asked_before,
            "at_close": asked_at_close,
            "after_restart_and_lease": asked_later,
        },
        "restart": restart,
    }


# -- H2: a signal comparison of fixed timing and two models, from outside ---------------------------

SIGNALS = "/traffic/comparisons"
#: H2's development seeds, and the signal answers the plan scripts: the first model keeps the
#: green at every point, and the second is never answered, so the fixed plan decides its points.
H2_SEEDS = 2
H2_ARMS = {"fixed", "model_a", "model_b", "model_a_again"}
#: The action key a receipt records for the label the first model chooses.
KEEP = "keep"
#: The traffic delay measure a signal comparison reads, which no person's score shares.
SIGNAL_MEASURE = "mean_delay_per_entry_ms"
#: The owners' signal comparison tests the row re-runs on the candidate.
H2_TESTS = (
    "tests/test_signal_comparison_postgres.py",
    "tests/test_signal_comparison_play.py",
    "tests/test_signal_unreachable_point_postgres.py",
)
#: How many generated towns a workspace may hold: H2 tries H1's town first, then makes others.
TOWNS_ALLOWED = 3


def signals_path(entry: Mapping[str, Any], suffix: str = "") -> str:
    return F.version_path(entry, f"{SIGNALS}{suffix}")


def signal_plan(c: Any, step: str, entry: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
    pairs = [
        ("world_id", entry["world_id"]),
        ("model", model_text(GOING_MODEL)),
        ("model", model_text(WAITING_MODEL)),
        ("control", "true"),
        ("seeds", str(H2_SEEDS)),
    ]
    return c.call(step, "GET", signals_path(entry, "/plan") + "?" + _encoded(pairs))


def signalled_town(
    c: Any, first: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]:
    """The first town whose roads drive and carry signals: H1's, then towns made for H2 while the
    workspace may hold them. A town whose roads the traffic compiler refuses is a stated limit of
    generated towns, so each refusal is recorded and another town is tried."""
    tried: list[dict[str, Any]] = []
    entry: dict[str, Any] | None = dict(first)
    while entry is not None:
        status, plan = signal_plan(c, "H2", entry)
        refusal = (plan or {}).get("refusal") or (plan or {}).get("plan_refusal")
        tried.append(
            {
                "entry_id": entry["entry_id"],
                "status": status,
                "refusal": refusal,
                "signals": len((plan or {}).get("signals") or []),
            }
        )
        if status == 200 and refusal is None and (plan or {}).get("signals"):
            return entry, plan, tried
        if len(tried) >= TOWNS_ALLOWED:
            return None, plan, tried
        entry = generated_town(c, "H2", f"Q10 H2 town {len(tried)}")
    return None, {}, tried


def signal_role(c: Any, step: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    """The live town's signal role as the models read serves it: its subjects and the owner's
    choices, which a comparison must not write."""
    _, read = c.call(step, "GET", F.version_path(entry, "/models"), query=F.world_query(entry))
    role = next((r for r in read.get("roles") or [] if r.get("key") == "junction_signal"), {})
    return {key: role.get(key) for key in ("available", "subjects", "choices")}


def row_h2(stack: Stack, transcripts: Any, out: Path, first: Mapping[str, Any]) -> Row:
    row = Row(
        "H2",
        "compare.signal",
        "On a generated town whose roads drive and carry signals, a signal comparison of fixed "
        "timing against two scripted models, the first run again as the control, is planned, "
        "started and played by the host: every run completes; the comparison names its roads "
        "by their digests and city identity; on each seed every arm plays the same episode and the "
        "same trip requests; every point a model was asked keeps its receipt, the second model's "
        "unanswered asks included, each left to the fixed plan; the control arm's receipts and "
        "measure equal its model's; each model run replays from its record with no model call, "
        "reproducing its continuation and terms against the roads it names (a replay refuses "
        "roads_changed otherwise); the result reads mean delay per entry and no "
        "person score, as H1's person result reads a score and no delay; another workspace cannot "
        "read it; the town's live signal choices read as before. V7's signal comparison tests pass "
        "on the candidate. Scripted answers: mechanics only.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    entry, plan, tried = signalled_town(w1, first)
    if entry is None:
        row.expect(False, f"no generated town drives with signals in {len(tried)} tries: {tried}")
        row.observed = {"towns_tried": tried}
        return row.close()
    signal_role_before = signal_role(w1, "H2", entry)
    comparison = str(uuid.uuid4())
    most = Decimal(str((plan.get("plan") or {}).get("most_usd") or "0"))
    bound = format(min(most, Decimal("1.00")), "f")
    body = {
        "comparison_id": comparison,
        "models": [dict(GOING_MODEL), dict(WAITING_MODEL)],
        "control": True,
        "seeds": H2_SEEDS,
        "bound_usd": bound,
    }
    status_start, start = w1.call(
        "H2", "POST", signals_path(entry), query=F.world_query(entry), body=body
    )
    row.expect(status_start == 201, f"the start answered {status_start} {F.problem_code(start)}")
    deadline = time.monotonic() + PLAY_SECONDS
    read: dict[str, Any] = {}
    while time.monotonic() < deadline:
        _, read = w1.call(
            "H2", "GET", signals_path(entry, f"/{comparison}"), query=F.world_query(entry)
        )
        if (read.get("start") or {}).get("finished_at"):
            break
        time.sleep(2)
    start_read = read.get("start") or {}
    row.expect(start_read.get("state") == "finished", f"the start ended {start_read.get('state')}")
    runs = runs_of(read)
    arms = {arm for _, arm, _ in runs}
    statuses = sorted({str(run.get("status")) for _, _, run in runs})
    row.expect(arms == H2_ARMS, f"the arms played are {sorted(arms)}")
    row.expect(len(runs) == len(H2_ARMS) * H2_SEEDS, f"{len(runs)} runs read")
    row.expect(statuses == ["completed"], f"the runs ended {statuses}")
    roads = read.get("roads") or {}
    row.expect(
        all(len(str(roads.get(key) or "")) == 64 for key in ("roads_version", "input_sha256"))
        and bool(roads.get("city_identity")),
        f"the comparison names roads {roads}",
    )
    measure = read.get("measure") or {}
    row.expect(measure.get("primary") == SIGNAL_MEASURE, f"the measure is {measure.get('primary')}")
    keys = {key for _, _, run in runs for key in run}
    row.expect("score" not in keys and "score" not in read, "a signal result reads a person score")
    reads: dict[tuple[str, str], dict[str, Any]] = {}
    for seed, arm, run in runs:
        if not run.get("run_id"):
            continue
        _, reads[(seed, arm)] = w1.call(
            "H2",
            "GET",
            signals_path(entry, f"/{comparison}/runs/{run['run_id']}"),
            query=F.world_query(entry),
        )
    episodes: dict[str, set[Any]] = {}
    requested: dict[str, set[Any]] = {}
    for (seed, _), run_read in reads.items():
        outcome = run_read.get("outcome") or {}
        episodes.setdefault(seed, set()).add(outcome.get("episode"))
        requested.setdefault(seed, set()).add(
            json.dumps(((outcome.get("terms") or {}).get("trips") or {}).get("requested"))
        )
    row.expect(
        len(episodes) == H2_SEEDS and all(len(v) == 1 and None not in v for v in episodes.values()),
        f"the arms of a seed played different episodes: {episodes}",
    )
    row.expect(
        all(len(v) == 1 for v in requested.values()), "the arms of a seed requested other trips"
    )
    receipts = {key: run_read.get("receipts") or [] for key, run_read in reads.items()}
    fixed_asked = sum(len(r) for (seed, arm), r in receipts.items() if arm == "fixed")
    kept = [x for (seed, arm), r in receipts.items() if arm == "model_a" for x in r]
    unanswered = [x for (seed, arm), r in receipts.items() if arm == "model_b" for x in r]
    row.expect(fixed_asked == 0, f"the fixed arm holds {fixed_asked} receipts")
    row.expect(
        bool(kept) and all(x.get("status") == "accepted" and x.get("chose") == KEEP for x in kept),
        "the first model's receipts are not all accepted choices to keep the green",
    )
    row.expect(
        bool(unanswered)
        and all(x.get("status") != "accepted" and x.get("chose") is None for x in unanswered),
        "the unanswered model's receipts were not retained as unanswered",
    )
    for seed in episodes:
        first_arm = reads.get((seed, "model_a"), {})
        again = reads.get((seed, "model_a_again"), {})
        row.expect(
            [
                (x.get("signal_id"), x.get("choice_second"), x.get("chose"))
                for x in first_arm.get("receipts") or []
            ]
            == [
                (x.get("signal_id"), x.get("choice_second"), x.get("chose"))
                for x in again.get("receipts") or []
            ]
            and (first_arm.get("outcome") or {}).get("terms")
            == (again.get("outcome") or {}).get("terms"),
            "the control arm differs from its model's arm",
        )
    calls_before_replay = len(scripted_log(stack))
    replays: dict[str, Any] = {}
    for (seed, arm), run_read in reads.items():
        if arm == "fixed":
            continue
        status_replay, replay = w1.call(
            "H2",
            "GET",
            signals_path(entry, f"/{comparison}/runs/{run_read.get('run_id')}/replay"),
            query=F.world_query(entry),
        )
        outcome = run_read.get("outcome") or {}
        replays[f"{arm}:{seed[:12] if seed else seed}"] = {
            "status": status_replay,
            "reproduced": replay.get("reproduced"),
            "points": replay.get("points"),
            "receipts": len(run_read.get("receipts") or []),
        }
        row.expect(
            status_replay == 200
            and replay.get("reproduced") is True
            and replay.get("continuation_sha256") == outcome.get("continuation_sha256")
            and replay.get("terms") == outcome.get("terms")
            and replay.get("points") == len(run_read.get("receipts") or []),
            f"run {arm} did not replay its record",
        )
    calls_after_replay = len(scripted_log(stack))
    row.expect(
        calls_after_replay == calls_before_replay,
        f"replaying made {calls_after_replay - calls_before_replay} calls",
    )
    status_foreign, foreign = w2.call(
        "H2", "GET", signals_path(entry, f"/{comparison}"), query=F.world_query(entry)
    )
    row.expect(
        status_foreign == 404 and F.problem_code(foreign) == "unknown_reference",
        f"another workspace's read answered {status_foreign} {F.problem_code(foreign)}",
    )
    signal_role_after = signal_role(w1, "H2", entry)
    row.expect(
        signal_role_after == signal_role_before,
        "the town's signal choices read differently after the comparison",
    )
    tests = lane_tests(out, stack.worktree, "h2-tests", H2_TESTS)
    row.expect(
        tests["exit"] == 0,
        f"the signal comparison tests exited {tests['exit']}: {tests['summary']}",
    )
    row.observed = {
        "towns_tried": tried,
        "town": {"entry_id": entry["entry_id"], "generated_ground": entry.get("generated_ground")},
        "signals": len(plan.get("signals") or []),
        "comparison_id": comparison,
        "bound_usd": bound,
        "start": start_read,
        "roads": roads,
        "measure": measure,
        "arms": sorted(arms),
        "run_statuses": statuses,
        "mean_delay_ms": {
            f"{arm}:{(seed or '')[:12]}": (run.get("measure") or {}).get("mean_delay_ms")
            for seed, arm, run in runs
        },
        "receipts": {
            "fixed": fixed_asked,
            "model_a": len(kept),
            "model_b_unanswered": len(unanswered),
            "model_b_reasons": sorted({str(x.get("reason")) for x in unanswered}),
        },
        "replays": replays,
        "verdict": read.get("verdict"),
        "foreign_read": [status_foreign, F.problem_code(foreign)],
        "signal_role": signal_role_after,
        "scripted_calls": {
            "before_replay": calls_before_replay,
            "after_replay": calls_after_replay,
        },
        "tests": tests,
    }
    return row.close()


# -- D2, D3: workspace assets, from outside --------------------------------------------------------

ASSETS = "/workspace-assets"
DECLARATION_PROFILE = "exulanica.workspace-asset-admission/v1"
RIGHTS_STATEMENT = "exulanica.workspace-asset-rights-statement/v1"
GLB_MEDIA_TYPE = "model/gltf-binary"
#: The admission's byte ceiling, which the list read serves; the oversized case is one byte past it.
CONTENT_BYTES_FALLBACK = 32 * 1024 * 1024
#: How long the driver's own preparation process may run once.
PREPARATION_SECONDS = 300
#: A unit cube's corners and triangles, wound outward, standing on y = 0.
CUBE_CORNERS = (
    (-0.5, 0.0, -0.5), (0.5, 0.0, -0.5), (0.5, 1.0, -0.5), (-0.5, 1.0, -0.5),
    (-0.5, 0.0, 0.5), (0.5, 0.0, 0.5), (0.5, 1.0, 0.5), (-0.5, 1.0, 0.5),
)  # fmt: skip
CUBE_TRIANGLES = (
    0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4,
    3, 6, 2, 3, 7, 6, 0, 4, 7, 0, 7, 3, 1, 2, 6, 1, 6, 5,
)  # fmt: skip
#: The A2 lane tests D2 and D3 re-run on the candidate; the interrupted preparation is bound to the
#: one an HTTP client cannot reproduce (A-41).
D_TESTS = (
    "tests/test_workspace_assets_postgres.py",
    "tests/test_workspace_asset_placement_postgres.py",
)


def glb(document: Mapping[str, Any], binary: bytes) -> bytes:
    """A GLB of exactly this JSON and binary chunk, padded as the format says."""
    raw = json.dumps(document).encode("utf-8")
    raw += b" " * (-len(raw) % 4)
    padded = binary + b"\x00" * (-len(binary) % 4)
    body = (
        struct.pack("<II", len(raw), 0x4E4F534A)
        + raw
        + struct.pack("<II", len(padded), 0x004E4942)
        + padded
    )
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body


def cube_document(side: float = 1.0) -> tuple[dict[str, Any], bytes]:
    """A cube ``side`` metres a side as one indexed primitive: its document and binary chunk."""
    points = [tuple(axis * side for axis in corner) for corner in CUBE_CORNERS]
    positions = b"".join(struct.pack("<3f", *point) for point in points)
    indices = struct.pack(f"<{len(CUBE_TRIANGLES)}H", *CUBE_TRIANGLES)
    binary = positions + indices
    document = {
        "asset": {"version": "2.0", "generator": "q10 acceptance"},
        "buffers": [{"byteLength": len(binary) + (-len(binary) % 4)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions), "target": 34962},
            {
                "buffer": 0,
                "byteOffset": len(positions),
                "byteLength": len(indices),
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "type": "VEC3",
                "count": len(points),
                "min": [min(p[axis] for p in points) for axis in range(3)],
                "max": [max(p[axis] for p in points) for axis in range(3)],
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "type": "SCALAR",
                "count": len(CUBE_TRIANGLES),
            },
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    return document, binary


def cube(side: float = 1.0, **changes: Any) -> bytes:
    document, binary = cube_document(side)
    document.update(changes)
    return glb(document, binary)


def declaration(payload: bytes, **changes: Any) -> dict[str, Any]:
    rights = {
        "basis": "own_work",
        "licence_id": None,
        "attribution": None,
        "source_reference": None,
        "statement": RIGHTS_STATEMENT,
    }
    rights.update(changes.pop("rights", {}))
    document = {
        "profile": DECLARATION_PROFILE,
        "content_kind": "static_glb",
        "title": "Q10 acceptance cube",
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "byte_size": len(payload),
        "unit": "metre",
        "expected_dimensions_mm": None,
        "rights": rights,
    }
    document.update(changes)
    return document


def raw_call(
    stack: Stack,
    token_file: str,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    content_type: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """One request outside the JSON client, for a multipart body or a byte answer."""
    headers = {"Authorization": f"Bearer {stack.token_file(token_file).read_text().strip()}"}
    if content_type is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(
        f"{stack.base_url}{path}", data=body, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as refused:
        return refused.code, dict(refused.headers), refused.read()


def admit(
    stack: Stack, log: Path, token_file: str, payload: bytes, document: Mapping[str, Any] | str
) -> tuple[int, Any]:
    """``POST /workspace-assets``: the declaration as a form field and the bytes as a file part.
    The exchange is appended to ``log`` without the bytes or a credential."""
    boundary = f"q10-{uuid.uuid4().hex}"
    text = document if isinstance(document, str) else json.dumps(document)
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="declaration"\r\n\r\n'.encode()
        + text.encode()
        + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="content"; '
        f'filename="object.glb"\r\nContent-Type: {GLB_MEDIA_TYPE}\r\n\r\n'.encode()
        + payload
        + f"\r\n--{boundary}--\r\n".encode()
    )
    status, _, answer = raw_call(
        stack,
        token_file,
        "POST",
        ASSETS,
        body=body,
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    try:
        parsed = json.loads(answer or b"null")
    except ValueError:
        parsed = {"unparsed": answer[:200].decode("utf-8", "replace")}
    with log.open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "at": dt.datetime.now(dt.UTC).isoformat(),
                    "token": token_file,
                    "payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "payload_bytes": len(payload),
                    "declaration": text if len(text) < 4096 else text[:4096],
                    "status": status,
                    "response_body": parsed,
                },
                sort_keys=True,
            )
            + "\n"
        )
    return status, parsed


def workspace_ids(stack: Stack) -> list[str]:
    """The run's workspaces in token order: ``token`` first, then ``token-2``."""
    named = [stack.state["workspace_id"]]
    named += [w["workspace_id"] for w in stack.state.get("other_workspaces", [])]
    return named


def namespace_listing(stack: Stack, workspace: str) -> list[str]:
    """An evidence read: the files in one workspace's asset namespace, with their sizes."""
    root = Path(stack.state["data_dir"]) / "workspace-assets" / uuid.UUID(workspace).hex
    if not root.exists():
        return []
    return sorted(
        f"{path.relative_to(root)}\t{path.stat().st_size}"
        for path in root.rglob("*")
        if path.is_file()
    )


def prepare_once(stack: Stack, out: Path, workspace: str, label: str) -> dict[str, Any]:
    """The workspace's asset preparation process, run once by the driver as the runtime role over
    the run's data directory, as an installation runs it beside its API."""
    completed = subprocess.run(
        [
            *entry_point(stack.worktree, "exulanica-asset-preparation"),
            "--workspace",
            workspace,
            "--once",
        ],
        cwd=stack.worktree,
        env={
            **LAUNCH.clean_environment(),
            "EXULANICA_DATABASE_URL": stack.state["database"]["runtime_url"],
            "EXULANICA_DATA_DIR": stack.state["data_dir"],
        },
        capture_output=True,
        text=True,
        timeout=PREPARATION_SECONDS,
        check=False,
    )
    (out / "evidence" / f"preparation-{label}.txt").write_text(completed.stdout + completed.stderr)
    events = []
    for line in completed.stdout.splitlines():
        try:
            events.append(json.loads(line).get("event"))
        except ValueError:
            continue
    return {"exit": completed.returncode, "events": events}


def asset_read(c: Any, step: str, asset_id: str) -> tuple[int, Any]:
    return c.call(step, "GET", f"{ASSETS}/{asset_id}")


def asset_source(asset_id: str, digest: str | None) -> dict[str, Any]:
    source: dict[str, Any] = {"kind": "workspace_asset", "asset_id": asset_id}
    if digest is not None:
        source["prepared_sha256"] = digest
    return source


def asset_placement(
    entry: Mapping[str, Any], asset_id: str, digest: str | None, subject: str, where: str
) -> dict[str, Any]:
    body = F.placement("unused", subject, where, entry["authored_state_sha256"])
    body["source"] = asset_source(asset_id, digest)
    body["saved_entry"] = F.resume_point(entry)
    return body


def compose(c: Any, step: str, entry: Mapping[str, Any], action: str, body: Mapping[str, Any]):
    """A preview or an apply; a preview takes no saved-world binding, an apply advances it."""
    if action == "preview":
        body = {k: v for k, v in body.items() if k != "saved_entry"}
    return c.call(
        step,
        "POST",
        F.version_path(entry, f"/compositions/{action}"),
        query=F.world_query(entry),
        body=body,
    )


def placed_object(version: Mapping[str, Any], subject: str) -> dict[str, Any] | None:
    return next(
        (
            o
            for o in version.get("objects") or []
            if subject in (o.get("object_id"), o.get("subject_id"))
        ),
        None,
    )


def row_d2(stack: Stack, transcripts: Any, out: Path, log: Path) -> Row:
    row = Row(
        "D2",
        "assets.admit_lifecycle",
        "A static GLB declared own work is admitted to workspace 1 with its preparation "
        "requested; the installation's preparation process prepares it once and its prepared "
        "bytes are delivered with their digest; it is placed in a saved starter world through the "
        "composition apply path, by its id and prepared digest, and reopened, also after an API "
        "restart, with the object naming it; workspace 2 cannot read it, find it in its list, "
        "detect it by its id, or place it by its id and digest (unknown_workspace_asset), exactly "
        "as an id that never existed; after workspace 1 withdraws it the asset reads 410, its bytes "
        "are refused 410, the placed object stays with availability withdrawn, a preview made "
        "before the withdrawal can no longer be applied (composition_blocked "
        "workspace_asset_withdrawn), and the withdrawal destroys no file in the namespace. A2's "
        "admission and placement tests pass on the candidate.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    first, second = workspace_ids(stack)[:2]
    payload = cube(1.0)
    status, view = admit(stack, log, "token", payload, declaration(payload))
    row.expect(status == 201, f"the admission answered {status} {F.problem_code(view)}")
    asset_id = (view or {}).get("asset_id", "")
    row.expect(
        ((view or {}).get("preparation") or {}).get("state") == "requested",
        f"the preparation reads {((view or {}).get('preparation') or {}).get('state')}",
    )
    prepared_run = prepare_once(stack, out, first, "d2")
    row.expect(prepared_run["exit"] == 0, f"the preparation process exited {prepared_run['exit']}")
    _, prepared = asset_read(w1, "D2", asset_id)
    output = ((prepared or {}).get("preparation") or {}).get("output") or {}
    digest = output.get("content_sha256")
    row.expect(
        (prepared or {}).get("availability") == {"state": "placeable", "code": None},
        f"the prepared asset reads {(prepared or {}).get('availability')}",
    )
    status_bytes, headers, delivered = raw_call(
        stack, "token", "GET", f"{ASSETS}/{asset_id}/prepared/bytes"
    )
    row.expect(
        status_bytes == 200 and hashlib.sha256(delivered).hexdigest() == digest,
        f"the prepared bytes answered {status_bytes} with another digest",
    )
    # Workspace 2, before anything else: its reads of workspace 1's asset and of an invented id.
    invented = str(uuid.uuid4())
    foreign = {
        "read": asset_read(w2, "D2 w2", asset_id),
        "invented": asset_read(w2, "D2 w2", invented),
        "bytes": raw_call(stack, "token-2", "GET", f"{ASSETS}/{asset_id}/prepared/bytes")[0],
        "bytes_invented": raw_call(stack, "token-2", "GET", f"{ASSETS}/{invented}/prepared/bytes")[
            0
        ],
    }
    _, listed_2 = w2.call("D2 w2", "GET", ASSETS)
    row.expect(
        foreign["read"] == foreign["invented"]
        and foreign["read"][0] == 404
        and F.problem_code(foreign["read"][1]) == "unknown_reference",
        f"workspace 2's read answered {foreign['read'][0]}, an invented id {foreign['invented'][0]}",
    )
    row.expect(
        foreign["bytes"] == foreign["bytes_invented"] == 404,
        f"workspace 2's byte reads answered {foreign['bytes']} and {foreign['bytes_invented']}",
    )
    row.expect(asset_id not in json.dumps(listed_2), "workspace 2's list names workspace 1's asset")
    status_w2, entry_w2 = w2.call(
        "D2 w2", "POST", "/world-entries/starter", body={"title": "Q10 D2 foreign"}
    )
    foreign_place = (
        compose(
            w2,
            "D2 w2",
            entry_w2,
            "preview",
            asset_placement(entry_w2, asset_id, digest, "q10-foreign", "stall"),
        )
        if status_w2 == 200
        else (status_w2, entry_w2)
    )
    invented_place = (
        compose(
            w2,
            "D2 w2",
            entry_w2,
            "preview",
            asset_placement(entry_w2, invented, digest, "q10-foreign", "stall"),
        )
        if status_w2 == 200
        else (status_w2, entry_w2)
    )
    row.expect(
        json.dumps(foreign_place[1], sort_keys=True).replace(asset_id, "<asset>")
        == json.dumps(invented_place[1], sort_keys=True).replace(invented, "<asset>")
        and "unknown_workspace_asset" in json.dumps(foreign_place[1]),
        f"workspace 2's placement answered {foreign_place[0]} {json.dumps(foreign_place[1])[:200]}",
    )
    # Workspace 1 places it in a saved starter world and reopens it.
    status_entry, entry = w1.call("D2", "POST", "/world-entries/starter", body={"title": "Q10 D2"})
    row.expect(status_entry == 200, f"the starter answered {status_entry}")
    status_apply, applied = compose(
        w1, "D2", entry, "apply", asset_placement(entry, asset_id, digest, "q10-cube", "stall")
    )
    row.expect(status_apply == 201, f"the apply answered {status_apply} {F.problem_code(applied)}")
    entry = F.read_entry(w1, "D2", entry["entry_id"])
    _, version = w1.call("D2", "GET", F.version_path(entry), query=F.world_query(entry))
    obj = placed_object(version, "q10-cube") or {}
    row.expect(
        (obj.get("workspace_asset") or {}).get("asset_id") == asset_id
        and (obj.get("workspace_asset") or {}).get("content_sha256") == digest,
        f"the reopened version names {obj.get('workspace_asset')}",
    )
    restart = stack.restart_api()
    _, reopened = w1.call(
        "D2 after restart", "GET", F.version_path(entry), query=F.world_query(entry)
    )
    row.expect(reopened == version, "the version read differently after the restart")
    # A preview made before the withdrawal, applied after it.
    status_preview, previewed = compose(
        w1, "D2", entry, "preview", asset_placement(entry, asset_id, digest, "q10-cube-2", "bench")
    )
    row.expect(
        status_preview == 200 and previewed.get("availability") == "ready",
        f"the preview answered {status_preview} {previewed.get('availability')}",
    )
    files_before = namespace_listing(stack, first)
    status_withdraw, withdrawn = w1.call("D2", "POST", f"{ASSETS}/{asset_id}/withdraw")
    status_again, again = w1.call("D2", "POST", f"{ASSETS}/{asset_id}/withdraw")
    row.expect(
        status_withdraw == 200 and withdrawn == {"asset_id": asset_id, "withdrawn": True},
        f"the withdrawal answered {status_withdraw} {withdrawn}",
    )
    row.expect(
        status_again == 200 and again == withdrawn, "a repeated withdrawal answered otherwise"
    )
    status_gone, gone = asset_read(w1, "D2", asset_id)
    status_gone_bytes = raw_call(stack, "token", "GET", f"{ASSETS}/{asset_id}/prepared/bytes")[0]
    row.expect(
        status_gone == 410 and F.problem_code(gone) == "withdrawn",
        f"the withdrawn asset reads {status_gone} {F.problem_code(gone)}",
    )
    row.expect(status_gone_bytes == 410, f"the withdrawn bytes answered {status_gone_bytes}")
    entry = F.read_entry(w1, "D2", entry["entry_id"])
    stale = asset_placement(entry, asset_id, digest, "q10-cube-2", "bench")
    status_stale, refused = compose(w1, "D2", entry, "apply", stale)
    row.expect(
        status_stale == 409
        and refused == {"code": "composition_blocked", "detail": "workspace_asset_withdrawn"},
        f"the stale preview's apply answered {status_stale} {refused}",
    )
    _, after = w1.call("D2", "GET", F.version_path(entry), query=F.world_query(entry))
    kept = placed_object(after, "q10-cube") or {}
    row.expect(
        (kept.get("workspace_asset") or {}).get("availability") == "withdrawn",
        f"the placed object reads {(kept.get('workspace_asset') or {}).get('availability')}",
    )
    files_after = namespace_listing(stack, first)
    row.expect(
        files_before == files_after and bool(files_before),
        "the withdrawal changed the namespace's files",
    )
    tests = lane_tests(out, stack.worktree, "d2-tests", D_TESTS)
    row.expect(tests["exit"] == 0, f"A2's tests exited {tests['exit']}: {tests['summary']}")
    row.observed = {
        "asset_id": asset_id,
        "input_sha256": hashlib.sha256(payload).hexdigest(),
        "prepared_sha256": digest,
        "preparation_process": prepared_run,
        "dimensions_mm": ((prepared or {}).get("preparation") or {}).get("dimensions_mm"),
        "delivered": [status_bytes, headers.get("ETag"), headers.get("Cache-Control")],
        "foreign": {
            "read": [foreign["read"][0], F.problem_code(foreign["read"][1])],
            "invented": [foreign["invented"][0], F.problem_code(foreign["invented"][1])],
            "bytes": [foreign["bytes"], foreign["bytes_invented"]],
            "placement": [foreign_place[0], invented_place[0]],
        },
        "placed": [status_apply, obj.get("workspace_asset")],
        "restart": restart,
        "withdrawal": [status_withdraw, status_again],
        "after_withdrawal": {
            "read": [status_gone, F.problem_code(gone)],
            "bytes": status_gone_bytes,
            "stale_preview_apply": [status_stale, refused],
            "object": (kept.get("workspace_asset") or {}).get("availability"),
        },
        "namespace_files": {"before_withdrawal": len(files_before), "after": len(files_after)},
        "workspace_2": second,
        "tests": tests,
    }
    return row.close()


def hostile_fixtures(
    ceiling: int,
) -> list[tuple[str, bytes, dict[str, Any] | None, int, str, str | None]]:
    """Each D3 case: its name, bytes, declaration changes (None for the plain one), and the status,
    code and detail it is refused with (A-41)."""
    document, binary = cube_document(0.8)
    script = b"alert('q10')"
    scripted = json.loads(json.dumps(document))
    offset = len(binary) + (-len(binary) % 4)
    scripted["bufferViews"].append({"buffer": 0, "byteOffset": offset, "byteLength": len(script)})
    scripted["buffers"] = [{"byteLength": offset + len(script) + (-len(script) % 4)}]
    scripted["images"] = [{"bufferView": 2, "mimeType": "text/javascript"}]
    padded = binary + b"\x00" * (-len(binary) % 4) + script
    external = json.loads(json.dumps(document))
    external["buffers"][0]["uri"] = "https://example.invalid/q10.bin"
    refused = 422, "asset_content_refused"
    return [
        ("malformed", b"glTF" + b"\x00" * 60, None, *refused, "malformed_container"),
        ("draco", cube(0.8, extensionsUsed=["KHR_draco_mesh_compression"]), None, *refused,
         "compressed_content"),
        ("meshopt", cube(0.8, extensionsUsed=["EXT_meshopt_compression"]), None, *refused,
         "compressed_content"),
        ("required_extension", cube(0.8, extensionsRequired=["KHR_materials_variants"]), None,
         *refused, "required_extension"),
        ("external_uri", glb(external, binary), None, *refused, "external_reference"),
        ("script_member", cube(0.8, scripts=[{"source": "alert('q10')"}]), None, *refused,
         "unsupported_feature"),
        ("script_image", glb(scripted, padded), None, *refused, "unsupported_feature"),
        ("oversized", b"\x00" * (ceiling + 4), None, 413, "asset_too_large", None),
        ("licence", cube(0.7), {"rights": {"basis": "licensed", "licence_id": "CC-BY-NC-4.0"}},
         422, "licence_not_admitted", None),
        ("attribution", cube(0.7), {"rights": {"basis": "licensed", "licence_id": "CC-BY-4.0"}},
         422, "attribution_required", None),
    ]  # fmt: skip


def quiet_digest(stack: Stack, c: Any) -> tuple[bool, dict[str, Any]]:
    """The evidence method's control: a plain read between two digests leaves them equal."""
    before = stack.evidence_digest()
    c.call("evidence-control", "GET", ASSETS)
    after = stack.evidence_digest()
    return before == after, {"before": before, "after": after}


def row_d3(stack: Stack, transcripts: Any, out: Path, log: Path) -> Row:
    row = Row(
        "D3",
        "assets.refusals",
        "Each hostile admission is refused with its stable code and leaves the asset list, the "
        "workspace's namespace files and the database's data as they were (after a no-write "
        "control): malformed_container; compressed_content for Draco and meshopt; "
        "required_extension; external_reference; unsupported_feature for an unknown top-level "
        "member and for an image that is not PNG or JPEG (the general refusal that covers an "
        "embedded script, A-41); 413 asset_too_large one past the byte ceiling; "
        "licence_not_admitted and attribution_required. A preparation cancelled while requested "
        "publishes nothing when the preparation process runs, and a new request then prepares "
        "exactly one output. The interrupted-then-retried case is A2's lane test re-run on the "
        "candidate, not a driver observation.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    first = workspace_ids(stack)[0]
    _, listed = w1.call("D3", "GET", ASSETS)
    ceiling = int(
        ((listed.get("admission") or {}).get("bounds") or {}).get("content_bytes")
        or CONTENT_BYTES_FALLBACK
    )
    control, control_digests = quiet_digest(stack, w1)
    row.expect(control, "the evidence digest changed across a plain read")
    cases: dict[str, Any] = {}
    for name, payload, changes, status_wanted, code, detail in hostile_fixtures(ceiling):
        _, listed_before = w1.call("D3", "GET", ASSETS)
        files_before = namespace_listing(stack, first)
        digest_before = stack.evidence_digest()
        status, answer = admit(
            stack, log, "token", payload, declaration(payload, **(changes or {}))
        )
        digest_after = stack.evidence_digest()
        _, listed_after = w1.call("D3", "GET", ASSETS)
        files_after = namespace_listing(stack, first)
        seen = (status, F.problem_code(answer), (answer or {}).get("detail") if detail else None)
        cases[name] = {
            "answered": list(seen),
            "unchanged": {
                "list": listed_before.get("assets") == listed_after.get("assets"),
                "namespace": files_before == files_after,
                "database": digest_before == digest_after,
            },
        }
        row.expect(seen == (status_wanted, code, detail), f"{name} answered {seen}")
        row.expect(
            all(cases[name]["unchanged"].values()), f"{name} left {cases[name]['unchanged']}"
        )
    # A preparation cancelled while it is requested, then requested again.
    payload = cube(0.6)
    status, view = admit(stack, log, "token", payload, declaration(payload))
    asset_id = (view or {}).get("asset_id", "")
    row.expect(status == 201, f"the cancel case's admission answered {status}")
    status_cancel, cancelled = w1.call("D3", "POST", f"{ASSETS}/{asset_id}/preparation/cancel")
    preparation = (cancelled or {}).get("preparation") or {}
    row.expect(
        status_cancel == 200 and preparation.get("state") == "cancelled",
        f"the cancel answered {status_cancel} {preparation.get('state')}",
    )
    files_cancelled = namespace_listing(stack, first)
    ran = prepare_once(stack, out, first, "d3-after-cancel")
    _, after_run = asset_read(w1, "D3", asset_id)
    files_after_run = namespace_listing(stack, first)
    row.expect(
        ((after_run or {}).get("preparation") or {}).get("state") == "cancelled"
        and files_after_run == files_cancelled,
        "the cancelled preparation published something",
    )
    status_again, _ = w1.call("D3", "POST", f"{ASSETS}/{asset_id}/preparation")
    row.expect(status_again == 202, f"the new request answered {status_again}")
    ran_again = prepare_once(stack, out, first, "d3-after-request")
    _, prepared = asset_read(w1, "D3", asset_id)
    files_prepared = namespace_listing(stack, first)
    output = ((prepared or {}).get("preparation") or {}).get("output") or {}
    added = sorted(set(files_prepared) - set(files_after_run))
    row.expect(
        ((prepared or {}).get("preparation") or {}).get("state") == "prepared"
        and len(added) == 1
        and output.get("content_sha256", "-") in added[0],
        f"the new request prepared {((prepared or {}).get('preparation') or {}).get('state')} "
        f"adding {len(added)} files",
    )
    tests = lane_tests(
        out,
        stack.worktree,
        "d3-interrupted",
        (
            "tests/test_workspace_assets_postgres.py::"
            "test_an_interrupted_preparation_is_retaken_and_makes_one_output",
        ),
    )
    row.expect(tests["exit"] == 0, f"A2's interrupted-preparation test exited {tests['exit']}")
    row.observed = {
        "byte_ceiling": ceiling,
        "control": control_digests,
        "cases": cases,
        "cancel": {
            "asset_id": asset_id,
            "cancel": [status_cancel, preparation.get("state"), preparation.get("failure")],
            "process_after_cancel": ran,
            "request_again": status_again,
            "process_after_request": ran_again,
            "prepared": ((prepared or {}).get("preparation") or {}).get("state"),
            "attempts": ((prepared or {}).get("preparation") or {}).get("attempts"),
            "files_added": len(added),
        },
        "interrupted_retry_lane_test_on_candidate": tests,
    }
    return row.close()


def assets(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if len(workspace_ids(stack)) < 2 or stack.state.get("scripted_model"):
        raise SystemExit("assets needs a stack started with --workspaces 2 and no scripted model")
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    log = out / "transcripts" / "admissions.jsonl"
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_d2(stack, transcripts, out, log), row_d3(stack, transcripts, out, log)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- H3: the living town's reading line, from V7's record on the candidate --------------------------

#: Which reading catalog the candidate reads, named by the candidate itself, so a re-measured line
#: in a newer catalog is checked with no change here; the record is the one its entry names.
READING_CATALOG_PATH = (
    "from exulanica.world.society_comparison_reading import READING_CATALOG; print(READING_CATALOG)"
)


def hour_entry(catalog: Mapping[str, Any], family: str) -> dict[str, Any]:
    """The family's hour line in a reading catalog, or an empty entry. A catalog may state a
    family's line for longer windows too (``window_ticks``); the hour's is the one keyed by the
    family's name alone, as the catalog's reader requires of it, whatever the entries' order."""
    return next(
        (
            dict(e)
            for e in catalog.get("entries", [])
            if e.get("state_family") == family and e.get("key") == family
        ),
        {},
    )


def window_entry(catalog: Mapping[str, Any], family: str, window_ticks: int) -> dict[str, Any]:
    """The family's line over a window longer than an hour, keyed ``<family>-<ticks>`` with its
    ``window_ticks``, as the catalog's reader requires of it, or an empty entry."""
    return next(
        (
            dict(e)
            for e in catalog.get("entries", [])
            if e.get("state_family") == family
            and e.get("key") == f"{family}-{window_ticks}"
            and e.get("window_ticks") == window_ticks
        ),
        {},
    )


#: Every file the drawing digest covers, named by the candidate's interpreter as the digest reads
#: them (its modules by source path, its data files), each relative to the checkout where it is
#: inside it, and each data file's directory with the glob the digest reads it by.
DRAWING_FILES = """
import importlib.util, json
from exulanica.world import society_comparison_drawing as d
print(json.dumps({
    "modules": [importlib.util.find_spec(m).origin for m in d.DRAWING_MODULES],
    "data": [str(p) for p in d.drawing_data()],
}))
"""
#: What A-56 lets a drawing digest move for, as a seeds catalog file's name.
SEEDS_FILE = re.compile(r"society-comparison-seeds\.v[0-9]+\.json")
#: The constant naming the seeds catalog in the catalogs module: A-56 lets the version a table maps
#: it to, and the versions its schemas are built for, change, and nothing else.
SEEDS_CONSTANT = "COMPARISON_SEEDS_CATALOG"


class _SeedsVersionsBlanked(ast.NodeTransformer):
    """The module with the seeds catalog's version in every table and its schemas' versions blanked,
    so two sources differing only there, or in comments, dump alike."""

    def visit_Dict(self, node: ast.Dict) -> ast.AST:
        self.generic_visit(node)
        node.values = [
            ast.Constant("seeds-version")
            if isinstance(key, ast.Name) and key.id == SEEDS_CONSTANT
            else value
            for key, value in zip(node.keys, node.values, strict=True)
        ]
        return node

    def visit_DictComp(self, node: ast.DictComp) -> ast.AST:
        self.generic_visit(node)
        key = node.key
        if (
            isinstance(key, ast.Tuple)
            and key.elts
            and isinstance(key.elts[0], ast.Name)
            and key.elts[0].id == SEEDS_CONSTANT
        ):
            for generator in node.generators:
                generator.iter = ast.Constant("seeds-versions")
        return node


def seeds_versions_only(before: str, after: str) -> bool:
    """Whether two sources of the catalogs module differ only in the seeds catalog's versions
    (A-56): the version a table maps the seeds constant to and the versions its schemas are built
    for, or in comments."""

    def blanked(source: str) -> str:
        return ast.dump(_SeedsVersionsBlanked().visit(ast.parse(source)))

    return blanked(before) == blanked(after)


def seeds_entries_kept(before: str | None, after: str | None) -> bool:
    """Whether a seeds catalog file kept every entry it held (A-56): a new file holds none to keep;
    a removed file keeps nothing."""
    if after is None:
        return False
    if before is None:
        return True
    old, new = json.loads(before), json.loads(after)
    return all(entry in new.get("entries", []) for entry in old.get("entries", [])) and {
        k: v for k, v in old.items() if k not in ("entries", "catalog_version")
    } == {k: v for k, v in new.items() if k not in ("entries", "catalog_version")}


def globbed_directories(data: set[Path]) -> list[Path]:
    """The directories the drawing digest reads whole: each whose every JSON file is a data file
    it reads. A data file named alone (the engines file beside other catalogs) brings no glob, so
    its neighbours are not drawing files; a glob finds a file the record's head had and the
    candidate removed."""
    return sorted({p.parent for p in data if set(p.parent.glob("*.json")) <= data}, key=str)


def drawing_drift(worktree: Path, record_head: str) -> dict[str, Any]:
    """The drawing files that differ between the commit a record measured and the candidate's
    checkout, computed here (A-56), each with whether A-56 lets it differ: a seeds catalog file
    keeping its entries, or the catalogs module changing only the seeds catalog's versions. The
    files are the ones the candidate's own digest reads; a file at the record's head the candidate
    no longer has is found by the glob of a directory the digest reads whole."""
    named = subprocess.run(
        [str(worktree / ".venv" / "bin" / "python"), "-c", DRAWING_FILES],
        cwd=worktree,
        env=LAUNCH.clean_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    if named.returncode != 0:
        return {"computed": False, "why": f"the drawing files: {named.stderr.strip()[-200:]}"}
    listed = json.loads(named.stdout)

    def relative(path: str) -> str:
        return str(Path(path).resolve().relative_to(worktree.resolve()))

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(worktree), *args], capture_output=True, text=True, check=False
        )

    if git("cat-file", "-e", f"{record_head}^{{commit}}").returncode != 0:
        return {"computed": False, "why": f"the record's head {record_head} is not in this clone"}
    files = sorted({relative(p) for p in listed["modules"] + listed["data"]})
    globs = [
        f":(glob){relative(str(d))}/*.json"
        for d in globbed_directories({Path(p).resolve() for p in listed["data"]})
    ]
    changed = git("diff", "--name-only", record_head, "--", *files, *globs).stdout.split()
    changed += git("ls-files", "--others", "--exclude-standard", "--", *globs).stdout.split()
    found = []
    for path in sorted(set(changed)):
        shown = git("show", f"{record_head}:{path}")
        before = shown.stdout if shown.returncode == 0 else None
        after = (worktree / path).read_text() if (worktree / path).is_file() else None
        if SEEDS_FILE.fullmatch(Path(path).name):
            allowed = seeds_entries_kept(before, after)
        elif path == "exulanica/world/society_catalogs.py" and before and after:
            allowed = seeds_versions_only(before, after)
        else:
            allowed = False
        found.append({"path": path, "at_head": before is not None, "allowed": allowed})
    return {
        "computed": True,
        "record_head": record_head,
        "changed": found,
        "stands": all(f["allowed"] for f in found),
    }


def drawing_verdict(row: Row, worktree: Path, record: Mapping[str, Any], candidate: str) -> Any:
    """Block ``row`` unless the record measured the candidate's drawing code, or the drawing files
    that differ since the record's head are all ones A-56 lets differ; the computed drift, or None
    where the digests are equal."""
    source = record.get("source") or {}
    if candidate == source.get("drawing_code_sha256"):
        return None
    drift = drawing_drift(worktree, str(source.get("head") or ""))
    if not drift.get("stands"):
        row.blocked_by.append(
            f"the record measured drawing code {source.get('drawing_code_sha256')}, the "
            f"candidate's is {candidate}, and the drawing files changed since its head are not all "
            f"ones A-56 allows: {drift}; the line needs a re-measure in a quiet window (A-39)"
        )
    return drift


#: A day, in the simulated minutes a comparison's window counts.
DAY_TICKS = 1440


#: How the record's script names the drawing code it measured: the module's own digest, read by
#: the candidate's interpreter as the script reads it (``scripts/measure_living_comparison_replay.py``).
DRAWING_DIGEST = (
    "from exulanica.world.society_comparison_drawing import CODE_SHA256; print(CODE_SHA256)"
)


def line_bound(line: Mapping[str, Any], run_us: int) -> tuple[int, Any]:
    """The populations the line allows, derived here from its four figures: the most people a run
    holds where a model decides for one of them, and, for a population, the most it decides for."""
    fixed = int(line["replay_fixed_ms"]) * 1000
    person = int(line["replay_per_person_us"])
    decided = int(line["replay_per_decided_person_us"])
    pair = int(line["replay_per_decided_pair_us"])
    population_most = max(0, (run_us - fixed - decided) // (person + pair))

    def decided_most(population: int) -> int:
        room = run_us - fixed - person * population
        return max(0, min(population, room // (decided + pair * population)))

    return population_most, decided_most


def row_h3(stack: Stack, transcripts: Any, out: Path, town: Mapping[str, Any]) -> Row:
    row = Row(
        "H3",
        "compare.capacity_record",
        "Passed on the living line's record (A-39) only when, computed on the candidate: the "
        "reading catalog the candidate reads binds the record its living entry names by the "
        "sha256 of the file; the record's drawing "
        "code digest equals the candidate's, by the record script's own method, so the record "
        "measured this source, or the drawing files changed since the record's head are only "
        "ones A-56 lets change, computed here; the record names each graph's total population and every point's "
        "model-decided population; and on H1's live town the plan serves population_most and "
        "decided_most as the record's line derives them for that population. No timing is "
        "measured here.",
    )
    worktree = stack.worktree
    named = subprocess.run(
        [str(worktree / ".venv" / "bin" / "python"), "-c", READING_CATALOG_PATH],
        cwd=worktree,
        env=LAUNCH.clean_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    catalog_path = Path(named.stdout.strip())
    row.expect(
        named.returncode == 0 and catalog_path.is_file(),
        f"the candidate names no reading catalog: {named.stderr.strip()[-200:]}",
    )
    catalog = json.loads(catalog_path.read_text()) if catalog_path.is_file() else {}
    entry = hour_entry(catalog, "living")
    living_record = str(entry.get("source") or "")
    record_path = worktree / living_record
    record_sha = (
        hashlib.sha256(record_path.read_bytes()).hexdigest() if record_path.is_file() else ""
    )
    row.expect(
        record_path.is_file() and entry.get("source_sha256") == record_sha,
        f"the catalog binds {living_record} {entry.get('source_sha256')}, the file is "
        f"{record_sha or 'absent'}",
    )
    record = (
        (json.loads(record_path.read_text()).get("record") or {}) if record_path.is_file() else {}
    )
    drawing = subprocess.run(
        [str(worktree / ".venv" / "bin" / "python"), "-c", DRAWING_DIGEST],
        cwd=worktree,
        env=LAUNCH.clean_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    candidate_drawing = drawing.stdout.strip()
    recorded_drawing = (record.get("source") or {}).get("drawing_code_sha256")
    row.expect(
        drawing.returncode == 0, f"the drawing digest did not compute: {drawing.stderr[-200:]}"
    )
    # A-39: a record that measured other code blocks H3 until a quiet-window re-measure, unless
    # the drawing files changed since its head are ones A-56 lets change.
    drift = (
        drawing_verdict(row, worktree, record, candidate_drawing)
        if drawing.returncode == 0
        else None
    )
    graphs = record.get("graphs") or []
    points = record.get("points") or []
    row.expect(
        bool(graphs) and all(isinstance(g.get("population"), int) for g in graphs),
        "a graph names no total population",
    )
    row.expect(
        bool(points)
        and all(
            isinstance(p.get("population"), int) and isinstance(p.get("decided"), int)
            for p in points
        ),
        "a point names no total or model-decided population",
    )
    # Half the pair's read budget for one run, as the record derived it from its protocol.
    run_us = int((record.get("derived") or {}).get("run_budget_us") or 0)
    line = record.get("line") or {}
    line_keys = (
        "replay_fixed_ms",
        "replay_per_person_us",
        "replay_per_decided_person_us",
        "replay_per_decided_pair_us",
    )
    row.expect(
        {k: line.get(k) for k in line_keys} == {k: entry.get(k) for k in line_keys},
        "the catalog's line is not the record's",
    )
    population_most, decided_most = line_bound(line, run_us)
    c = F.client(stack, transcripts, "w1", "token")
    status, plan = plan_of(c, "H3", town, [GOING_MODEL], control=False, seeds=1)
    population = plan.get("population")
    row.expect(status == 200, f"the plan answered {status}")
    row.expect(
        plan.get("population_most") == population_most,
        f"the plan serves population_most {plan.get('population_most')}, the line derives "
        f"{population_most}",
    )
    row.expect(
        isinstance(population, int) and plan.get("decided_most") == decided_most(population),
        f"the plan serves decided_most {plan.get('decided_most')} for {population}, the line "
        f"derives {decided_most(population) if isinstance(population, int) else None}",
    )
    row.observed = {
        "reading_catalog": str(catalog_path.relative_to(worktree))
        if catalog_path.is_relative_to(worktree)
        else str(catalog_path),
        "record": living_record,
        "record_sha256": record_sha,
        "catalog_binds": [entry.get("source"), entry.get("source_sha256")],
        "drawing_code_sha256": {"record": recorded_drawing, "candidate": candidate_drawing},
        "drawing_drift": drift,
        "record_head": (record.get("source") or {}).get("head"),
        "graphs": [
            {k: g.get(k) for k in ("world_id", "population", "outside_specification")}
            for g in graphs
        ],
        "points": len(points),
        "line": {k: line.get(k) for k in line_keys},
        "run_budget_us": run_us,
        "derived": {
            "population_most": population_most,
            "decided_most": decided_most(population) if isinstance(population, int) else None,
        },
        "plan": {k: plan.get(k) for k in ("population", "population_most", "decided_most")},
        "town": town.get("entry_id"),
    }
    return row.close()


def row_h4(stack: Stack, transcripts: Any, out: Path, town: Mapping[str, Any]) -> Row:
    row = Row(
        "H4",
        "compare.day_record",
        "A living town's day, read by its day line (A-57), passed only when, computed on the "
        "candidate: the reading catalog the candidate reads binds the record its living day entry "
        "(window_ticks 1440) names by the sha256 of the file; the record measured a window of 1440 "
        "minutes and the candidate's drawing code, by the record script's own method, or drawing "
        "files changed since its head only as A-56 allows, computed here; the catalog's "
        "day line is the record's; and on H1's live town the plan offers the day window, reads it "
        "by that record, and serves population_most and decided_most for a day as the line derives "
        "them with the record's run budget. No timing is measured here.",
    )
    worktree = stack.worktree
    named = subprocess.run(
        [str(worktree / ".venv" / "bin" / "python"), "-c", READING_CATALOG_PATH],
        cwd=worktree,
        env=LAUNCH.clean_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    catalog_path = Path(named.stdout.strip())
    row.expect(
        named.returncode == 0 and catalog_path.is_file(),
        f"the candidate names no reading catalog: {named.stderr.strip()[-200:]}",
    )
    catalog = json.loads(catalog_path.read_text()) if catalog_path.is_file() else {}
    entry = window_entry(catalog, "living", DAY_TICKS)
    day_record = str(entry.get("source") or "")
    record_path = worktree / day_record
    record_sha = (
        hashlib.sha256(record_path.read_bytes()).hexdigest() if record_path.is_file() else ""
    )
    row.expect(
        bool(day_record) and record_path.is_file() and entry.get("source_sha256") == record_sha,
        f"the catalog binds {day_record or 'no day record'} {entry.get('source_sha256')}, the "
        f"file is {record_sha or 'absent'}",
    )
    record = (
        (json.loads(record_path.read_text()).get("record") or {}) if record_path.is_file() else {}
    )
    row.expect(
        record.get("window_ticks") == DAY_TICKS,
        f"the record measured a window of {record.get('window_ticks')} minutes",
    )
    drawing = subprocess.run(
        [str(worktree / ".venv" / "bin" / "python"), "-c", DRAWING_DIGEST],
        cwd=worktree,
        env=LAUNCH.clean_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    candidate_drawing = drawing.stdout.strip()
    recorded_drawing = (record.get("source") or {}).get("drawing_code_sha256")
    row.expect(
        drawing.returncode == 0, f"the drawing digest did not compute: {drawing.stderr[-200:]}"
    )
    drift = (
        drawing_verdict(row, worktree, record, candidate_drawing)
        if drawing.returncode == 0
        else None
    )
    run_us = int((record.get("derived") or {}).get("run_budget_us") or 0)
    line = record.get("line") or {}
    line_keys = (
        "replay_fixed_ms",
        "replay_per_person_us",
        "replay_per_decided_person_us",
        "replay_per_decided_pair_us",
    )
    row.expect(
        bool(line) and {k: line.get(k) for k in line_keys} == {k: entry.get(k) for k in line_keys},
        "the catalog's day line is not the record's",
    )
    population_most, decided_most = line_bound(line, run_us) if line else (None, lambda _: None)
    c = F.client(stack, transcripts, "w1", "token")
    status, plan = plan_of(c, "H4", town, [GOING_MODEL], control=False, seeds=1, window="day")
    population = plan.get("population")
    offered = next((w for w in plan.get("windows") or [] if w.get("window") == "day"), {})
    row.expect(status == 200, f"the plan answered {status}")
    row.expect(
        offered.get("refusal") is None and offered.get("window_ticks") == DAY_TICKS,
        f"the day window is {offered.get('window_ticks')} minutes, refused {offered.get('refusal')}",
    )
    row.expect(
        offered.get("reading_record") == day_record,
        f"the day is read by {offered.get('reading_record')}, the catalog names {day_record}",
    )
    row.expect(
        plan.get("window") == "day" and plan.get("window_ticks") == DAY_TICKS,
        f"the plan answers window {plan.get('window')} of {plan.get('window_ticks')} minutes",
    )
    row.expect(
        plan.get("population_most") == population_most,
        f"the plan serves population_most {plan.get('population_most')} for a day, the line "
        f"derives {population_most}",
    )
    row.expect(
        isinstance(population, int) and plan.get("decided_most") == decided_most(population),
        f"the plan serves decided_most {plan.get('decided_most')} for {population} over a day, "
        f"the line derives {decided_most(population) if isinstance(population, int) else None}",
    )
    row.observed = {
        "reading_catalog": str(catalog_path.relative_to(worktree))
        if catalog_path.is_relative_to(worktree)
        else str(catalog_path),
        "record": day_record,
        "record_sha256": record_sha,
        "catalog_binds": [entry.get("key"), entry.get("source"), entry.get("source_sha256")],
        "window_ticks": record.get("window_ticks"),
        "drawing_code_sha256": {"record": recorded_drawing, "candidate": candidate_drawing},
        "drawing_drift": drift,
        "record_head": (record.get("source") or {}).get("head"),
        "line": {k: line.get(k) for k in line_keys},
        "run_budget_us": run_us,
        "derived": {
            "population_most": population_most,
            "decided_most": decided_most(population) if isinstance(population, int) else None,
        },
        "day_window": offered,
        "plan": {
            k: plan.get(k)
            for k in ("window", "window_ticks", "population", "population_most", "decided_most")
        },
        "plan_refusal": plan.get("plan_refusal"),
        "town": town.get("entry_id"),
    }
    return row.close()


# -- E1, E2: character families and catalog revisions, from outside --------------------------------

CATALOGS = "/world/character-catalogs"
LAYERED_FAMILY = "makehuman-people/v1/feminine"
PARAMETRIC_FAMILY = "makehuman-parametric/v1"
#: The option A's look uses and catalog B removes (the same change as C7's own catalog B).
REMOVED_PART = "feminine/hair/long01"
REMOVED_BASE = "feminine"
LAYERED_CATALOG_ID = "exulanica-characters"
#: The layered catalog's revision the repository carries, which a fresh run's launcher publishes.
REPOSITORY_LAYERED_REVISION = json.loads(
    (HERE.parents[1] / "assets" / "characters" / "catalog.json").read_text()
)["revision"]
CHARACTER_SOURCE = Path("assets/characters")
NOT_SERVED_FAMILY = "quaternius-modular-v2"
E_TESTS = (
    "tests/test_character_catalog_api.py",
    "tests/test_character_catalog_postgres.py",
    "tests/test_character_catalogs.py",
    "tests/test_character_appearance_api.py",
)


def starter(c: Any, step: str, title: str) -> tuple[int, dict[str, Any]]:
    """The workspace's starter world: a new one, or the one it holds already, since a workspace
    holds one starter entry (saved_world_conflict)."""
    status, entry = c.call(step, "POST", "/world-entries/starter", body={"title": title})
    if status == 409 and F.problem_code(entry) == "saved_world_conflict":
        _, entries = c.call(step, "GET", "/world-entries")
        held = next((e for e in entries or [] if not e.get("generated_ground")), None)
        if held is not None:
            return 200, F.read_entry(c, step, held["entry_id"])
    return status, entry


def appearance_path(entry: Mapping[str, Any], actor: str, suffix: str = "") -> str:
    return F.version_path(entry, f"/characters/avatar/{actor}/appearance{suffix}")


def representations(document: Any) -> list[dict[str, Any]]:
    """Every reviewed representation a served catalog document states, wherever it nests."""
    found: list[dict[str, Any]] = []
    if isinstance(document, dict):
        if "representationId" in document and "values" in document:
            found.append(document)
        for value in document.values():
            found += representations(value)
    elif isinstance(document, list):
        for value in document:
            found += representations(value)
    return found


def default_recipe(entry: Mapping[str, Any], **chosen: Any) -> dict[str, Any]:
    """A family's recipe at its declared defaults, with ``chosen`` values instead where given."""
    family = entry["family"]
    parameters = {p["key"]: p["default"] for p in family["parameters"]}
    parameters.update({k: v for k, v in chosen.items() if k in parameters})
    return {
        "family_id": family["family_id"],
        "family_sha256": entry["family_sha256"],
        "parameters": parameters,
        "seed": family.get("default_seed", 0),
    }


def catalog_tool(stack: Stack, out: Path, label: str, *arguments: str) -> dict[str, Any]:
    """``exulanica-character-catalog`` as the host administrator: the owner connection and the
    run's data directory, as ``launch.py up`` publishes."""
    completed = subprocess.run(
        [*entry_point(stack.worktree, "exulanica-character-catalog"), *arguments],
        cwd=stack.worktree,
        env={
            **LAUNCH.clean_environment(),
            "EXULANICA_DATABASE_URL": stack.state["database"]["owner_url_for_evidence_reads"],
            "EXULANICA_DATA_DIR": stack.state["data_dir"],
        },
        capture_output=True,
        text=True,
        check=False,
    )
    (out / "evidence" / f"catalog-{label}.txt").write_text(completed.stdout + completed.stderr)
    return {"exit": completed.returncode, "lines": completed.stdout.strip().splitlines()[-4:]}


def catalog_b(stack: Stack) -> Path:
    """The repository's layered catalog at the next revision without ``REMOVED_PART``, in the run
    directory beside links to the unchanged family folders. No parametric catalog: B is layered."""
    source = stack.worktree / CHARACTER_SOURCE
    target = stack.run_dir / "catalog-b"
    target.mkdir(exist_ok=True)
    catalog = json.loads((source / "catalog.json").read_text())
    catalog["revision"] = int(catalog["revision"]) + 1
    for family in catalog["families"]:
        for base in family["bases"]:
            if base["baseId"] == REMOVED_BASE:
                base["parts"] = [p for p in base["parts"] if p["partId"] != REMOVED_PART]
    for population in catalog.get("population", []):
        for slots in (population.get("choices") or {}).values():
            for slot in slots.values():
                if isinstance(slot, dict):
                    slot.pop(REMOVED_PART, None)
    (target / "catalog.json").write_text(json.dumps(catalog, indent=2))
    (target / "looks.json").write_bytes((source / "looks.json").read_bytes())
    for folder in source.iterdir():
        if folder.is_dir() and not (target / folder.name).exists():
            (target / folder.name).symlink_to(folder)
    return target


def row_e1(stack: Stack, transcripts: Any, out: Path) -> tuple[Row, dict[str, Any]]:
    row = Row(
        "E1",
        "characters.two_families",
        "On the token actor's own avatar in a saved world (A-42), the families read serves two "
        "families of different kinds from the published catalogs, the layered "
        f"{LAYERED_FAMILY} (choice parameters) and the parametric {PARAMETRIC_FAMILY} (integer "
        "controls, a reviewed body), whose declared parameters and revisions differ; a look is "
        "saved in each through the same PUT with its base revision, each drawn available; a "
        "stale base is refused 409 stale_appearance and writes nothing; after an API restart the "
        f"current look and the history read the same. {NOT_SERVED_FAMILY} is not a served family.",
    )
    c = F.client(stack, transcripts, "w1", "token")
    # The launcher's test database outlives a stack, and E2 withdraws the repository's layered
    # catalog in it: a database an earlier characters run used no longer serves catalog A (A-47).
    _, listing = c.call("E1", "GET", CATALOGS)
    served = {
        (p.get("catalog_id"), p.get("revision"), p.get("state"))
        for p in (listing or {}).get("publications", [])
    }
    if not any(cid == LAYERED_CATALOG_ID and state == "current" for cid, _, state in served) or any(
        cid == LAYERED_CATALOG_ID and revision != REPOSITORY_LAYERED_REVISION
        for cid, revision, _ in served
    ):
        row.blocked_by.append(
            "this stack's database carries an earlier run's catalog publication or withdrawal: "
            f"{sorted(map(str, served))}; run characters on a fresh test database"
        )
        return row.close(), {}
    actor = stack.state["actor"]
    status, entry = starter(c, "E1", "Q10 E1")
    row.expect(status == 200, f"the starter answered {status}")
    _, families = c.call(
        "E1", "GET", appearance_path(entry, actor, "/families"), query=F.world_query(entry)
    )
    by_id = {f["family"]["family_id"]: f for f in families or []}
    layered, parametric = by_id.get(LAYERED_FAMILY), by_id.get(PARAMETRIC_FAMILY)
    row.expect(layered is not None and parametric is not None, f"families served: {sorted(by_id)}")
    row.expect(
        not any(NOT_SERVED_FAMILY in family for family in by_id),
        f"{NOT_SERVED_FAMILY} is served",
    )
    kinds = {f.get("kind") for f in families or []}
    row.expect(
        {"layered-people", "parametric-body"} <= kinds, f"family kinds {sorted(map(str, kinds))}"
    )
    saved: dict[str, Any] = {}
    if layered and parametric:
        layered_kinds = {p["kind"] for p in layered["family"]["parameters"]}
        parametric_kinds = {p["kind"] for p in parametric["family"]["parameters"]}
        row.expect(
            "choice" in layered_kinds
            and "integer" in parametric_kinds
            and layered["family"]["family_revision"] != parametric["family"]["family_revision"]
            and {p["key"] for p in layered["family"]["parameters"]}
            != {p["key"] for p in parametric["family"]["parameters"]},
            "the two families declare the same capabilities",
        )
        hair = {"hair": REMOVED_PART}
        first = default_recipe(layered, **hair)
        status_first, saved_first = c.call(
            "E1",
            "PUT",
            appearance_path(entry, actor),
            query=F.world_query(entry),
            body={"base_revision": 0, "recipe": first},
        )
        row.expect(
            status_first == 200
            and ((saved_first or {}).get("current") or {}).get("render_status") == "available",
            f"the layered look answered {status_first} {F.problem_code(saved_first)}",
        )
        _, listing = c.call("E1", "GET", CATALOGS)
        reviewed: list[dict[str, Any]] = []
        for publication in (listing or {}).get("publications", []):
            if publication.get("kind") == "parametric-body":
                status_doc, _, body = raw_call(
                    stack, "token", "GET", f"{CATALOGS}/{publication['catalog_sha256']}"
                )
                row.expect(
                    status_doc == 200
                    and hashlib.sha256(body).hexdigest() == publication["catalog_sha256"],
                    "a served catalog document is not the bytes its digest names",
                )
                reviewed += representations(json.loads(body)) if status_doc == 200 else []
        row.expect(bool(reviewed), "the parametric catalog states no reviewed body")
        second = default_recipe(parametric)
        if reviewed:
            second["parameters"] = dict(reviewed[0]["values"])
            second["representation_id"] = reviewed[0]["representationId"]
        status_second, saved_second = c.call(
            "E1",
            "PUT",
            appearance_path(entry, actor),
            query=F.world_query(entry),
            body={"base_revision": 1, "recipe": second},
        )
        current = (saved_second or {}).get("current") or {}
        row.expect(
            status_second == 200
            and current.get("render_status") == "available"
            and (current.get("render") or {}).get("kind") == "parametric-body",
            f"the parametric look answered {status_second} {F.problem_code(saved_second)} "
            f"{current.get('render_status')}",
        )
        status_stale, stale = c.call(
            "E1",
            "PUT",
            appearance_path(entry, actor),
            query=F.world_query(entry),
            body={"base_revision": 1, "recipe": first},
        )
        row.expect(
            status_stale == 409 and F.problem_code(stale) == "stale_appearance",
            f"a stale base answered {status_stale} {F.problem_code(stale)}",
        )
        _, before = c.call("E1", "GET", appearance_path(entry, actor), query=F.world_query(entry))
        _, history = c.call(
            "E1", "GET", appearance_path(entry, actor, "/history"), query=F.world_query(entry)
        )
        row.expect(
            (before or {}).get("revision") == 2,
            f"the look is at revision {(before or {}).get('revision')}",
        )
        restart = stack.restart_api()
        _, after = c.call(
            "E1 after restart", "GET", appearance_path(entry, actor), query=F.world_query(entry)
        )
        _, history_after = c.call(
            "E1 after restart",
            "GET",
            appearance_path(entry, actor, "/history"),
            query=F.world_query(entry),
        )
        row.expect(after == before, "the current look read differently after the restart")
        row.expect(history_after == history, "the history read differently after the restart")
        row.expect(
            [r.get("revision") for r in history_after or []] == [2, 1],
            "the history does not hold both looks",
        )
        saved = {
            "entry": entry,
            "actor": actor,
            "layered_recipe": first,
            "layered_revision": (saved_first or {}).get("current", {}).get("document", {}),
        }
        row.observed = {
            "families": sorted(by_id),
            "kinds": sorted(map(str, kinds)),
            "layered": {"family_sha256": layered["family_sha256"], "kinds": sorted(layered_kinds)},
            "parametric": {
                "family_sha256": parametric["family_sha256"],
                "kinds": sorted(parametric_kinds),
                "representation_id": second.get("representation_id"),
            },
            "saves": [status_first, status_second],
            "stale": [status_stale, F.problem_code(stale)],
            "current_after_restart": {
                "revision": (after or {}).get("revision"),
                "render_status": ((after or {}).get("current") or {}).get("render_status"),
            },
            "restart": restart,
        }
    return row.close(), saved


def row_e2(stack: Stack, transcripts: Any, out: Path, saved: Mapping[str, Any]) -> Row:
    row = Row(
        "E2",
        "characters.catalog_revisions",
        "With a look saved under catalog A's feminine family using an option, publishing catalog B "
        "(the layered catalog's next revision without that option) leaves the look as it was, "
        "drawn from A, retained, by the family digest it saved; after A is withdrawn the look "
        "reads the explicit family_source_unavailable state with its recipe intact, never "
        "another family's look, and a save on that family is refused 424 appearance_unavailable. "
        "C7's catalog and appearance tests pass on the candidate.",
    )
    c = F.client(stack, transcripts, "w1", "token")
    if not saved:
        row.blocked_by.append("E1 saved no look to hold catalog B against")
        return row.close()
    entry, actor = saved["entry"], saved["actor"]
    query = F.world_query(entry)

    # The look at its first revision, as history serves it.
    def first_look() -> dict[str, Any]:
        _, history = c.call("E2", "GET", appearance_path(entry, actor, "/history"), query=query)
        return next((r for r in history or [] if r.get("revision") == 1), {})

    before = first_look()
    _, listing = c.call("E2", "GET", CATALOGS)
    a = next(
        (
            p
            for p in (listing or {}).get("publications", [])
            if p.get("catalog_id") == LAYERED_CATALOG_ID
        ),
        {},
    )
    published = catalog_tool(
        stack, out, "publish-b", "publish", "--directory", str(catalog_b(stack)), "--apply"
    )
    row.expect(published["exit"] == 0, f"publishing catalog B exited {published['exit']}")
    _, listing_b = c.call("E2", "GET", CATALOGS)
    states = {
        (p.get("catalog_id"), p.get("revision")): p.get("state")
        for p in (listing_b or {}).get("publications", [])
    }
    row.expect(
        states.get((LAYERED_CATALOG_ID, a.get("revision"))) == "retained"
        and states.get((LAYERED_CATALOG_ID, (a.get("revision") or 0) + 1)) == "current",
        f"the catalogs read {states}",
    )
    with_b = first_look()
    row.expect(
        with_b.get("document") == before.get("document")
        and with_b.get("render_status") == "available"
        and (with_b.get("render") or {}).get("catalog_sha256") == a.get("catalog_sha256"),
        f"the A look under B reads {with_b.get('render_status')} from "
        f"{(with_b.get('render') or {}).get('catalog_sha256')}",
    )
    withdrawn = catalog_tool(
        stack,
        out,
        "withdraw-a",
        "withdraw",
        "--catalog-sha256",
        str(a.get("catalog_sha256")),
        "--reason",
        "q10_acceptance_e2",
        "--apply",
    )
    row.expect(withdrawn["exit"] == 0, f"withdrawing catalog A exited {withdrawn['exit']}")
    without_a = first_look()
    row.expect(
        without_a.get("render_status") == "family_source_unavailable"
        and without_a.get("render") is None
        and (without_a.get("document") or {}).get("recipe")
        == (before.get("document") or {}).get("recipe"),
        f"without A the look reads {without_a.get('render_status')}",
    )
    _, now = c.call("E2", "GET", appearance_path(entry, actor), query=query)
    status_save, refused = c.call(
        "E2",
        "PUT",
        appearance_path(entry, actor),
        query=query,
        body={"base_revision": (now or {}).get("revision", 0), "recipe": saved["layered_recipe"]},
    )
    row.expect(
        status_save == 424 and F.problem_code(refused) == "appearance_unavailable",
        f"a save on the withdrawn family answered {status_save} {F.problem_code(refused)}",
    )
    tests = lane_tests(out, stack.worktree, "e-tests", E_TESTS)
    row.expect(tests["exit"] == 0, f"C7's tests exited {tests['exit']}: {tests['summary']}")
    row.observed = {
        "catalog_a": {k: a.get(k) for k in ("catalog_sha256", "revision")},
        "publish_b": published,
        "catalog_states": {f"{k[0]}@{k[1]}": v for k, v in states.items()},
        "look_under_b": {
            "render_status": with_b.get("render_status"),
            "catalog_sha256": (with_b.get("render") or {}).get("catalog_sha256"),
            "resolution": (with_b.get("render") or {}).get("resolution"),
        },
        "withdraw_a": withdrawn,
        "look_without_a": {
            "render_status": without_a.get("render_status"),
            "render": without_a.get("render"),
            "recipe_intact": (without_a.get("document") or {}).get("recipe")
            == (before.get("document") or {}).get("recipe"),
        },
        "save_on_withdrawn_family": [status_save, F.problem_code(refused)],
        "tests": tests,
    }
    return row.close()


def characters(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if not stack.state.get("character_catalogs"):
        raise SystemExit("characters needs a stack whose launcher published the character catalogs")
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    e1, saved = row_e1(stack, transcripts, out)
    rows = [e1, row_e2(stack, transcripts, out, saved)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- K2: withdrawal of stored bytes, from outside ---------------------------------------------------


def k2_assets(stack: Stack, transcripts: Any, out: Path, log: Path, row: Row) -> dict[str, Any]:
    """K2 (a), A-40: workspace 1 withdraws a prepared asset whose identical bytes workspace 2
    admitted on its own. Workspace 1's reads refuse even by the known digest, nothing of its
    namespace is destroyed, and workspace 2's asset still reads and delivers."""
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    first, second = workspace_ids(stack)[:2]
    payload = cube(0.9)
    status_1, view_1 = admit(stack, log, "token", payload, declaration(payload))
    status_2, view_2 = admit(stack, log, "token-2", payload, declaration(payload))
    row.expect(
        status_1 == 201 and status_2 == 201,
        f"the identical admissions answered {status_1} and {status_2}",
    )
    asset_1, asset_2 = (view_1 or {}).get("asset_id", ""), (view_2 or {}).get("asset_id", "")
    row.expect(asset_1 != asset_2, "the two workspaces' admissions share an id")
    runs = [prepare_once(stack, out, first, "k2-w1"), prepare_once(stack, out, second, "k2-w2")]
    row.expect(all(r["exit"] == 0 for r in runs), f"a preparation process exited {runs}")
    _, prepared_1 = asset_read(w1, "K2 assets", asset_1)
    digest = (((prepared_1 or {}).get("preparation") or {}).get("output") or {}).get(
        "content_sha256"
    )
    status_entry, entry = w1.call(
        "K2 assets", "POST", "/world-entries/starter", body={"title": "Q10 K2"}
    )
    row.expect(status_entry == 200, f"the starter answered {status_entry}")
    files_before = namespace_listing(stack, first)
    status_withdraw, _ = w1.call("K2 assets", "POST", f"{ASSETS}/{asset_1}/withdraw")
    row.expect(status_withdraw == 200, f"the withdrawal answered {status_withdraw}")
    status_read, read = asset_read(w1, "K2 assets", asset_1)
    status_bytes = raw_call(stack, "token", "GET", f"{ASSETS}/{asset_1}/prepared/bytes")[0]
    status_place, placed = compose(
        w1, "K2 assets", entry, "apply", asset_placement(entry, asset_1, digest, "q10-k2", "stall")
    )
    row.expect(
        status_read == 410 and F.problem_code(read) == "withdrawn",
        f"the withdrawn asset reads {status_read} {F.problem_code(read)}",
    )
    row.expect(status_bytes == 410, f"the withdrawn bytes answered {status_bytes}")
    row.expect(
        status_place == 409
        and placed == {"code": "composition_blocked", "detail": "workspace_asset_withdrawn"},
        f"a placement by the known digest answered {status_place} {placed}",
    )
    files_after = namespace_listing(stack, first)
    row.expect(files_after == files_before, "the withdrawal destroyed a file")
    status_other, other = asset_read(w2, "K2 assets", asset_2)
    status_other_bytes, _, other_bytes = raw_call(
        stack, "token-2", "GET", f"{ASSETS}/{asset_2}/prepared/bytes"
    )
    row.expect(
        status_other == 200
        and (other or {}).get("availability") == {"state": "placeable", "code": None},
        f"workspace 2's asset reads {status_other} {(other or {}).get('availability')}",
    )
    row.expect(
        status_other_bytes == 200 and hashlib.sha256(other_bytes).hexdigest() == digest,
        f"workspace 2's bytes answered {status_other_bytes}",
    )
    return {
        "assets": [asset_1, asset_2],
        "prepared_sha256": digest,
        "withdrawal": status_withdraw,
        "workspace_1": {
            "read": [status_read, F.problem_code(read)],
            "bytes": status_bytes,
            "placement_by_digest": [status_place, placed],
            "namespace_files_unchanged": files_after == files_before,
            "namespace_files": len(files_after),
        },
        "workspace_2": {"read": status_other, "bytes": status_other_bytes},
    }


#: How long the in-process derivative worker may take to finish a photograph's batch.
DERIVATION_SECONDS = 600
#: Where the run's content-addressed store keeps a blob: ``<data_dir>/blobs/sha-256/ab/cd/<digest>``.
STORE_PREFIX = "sha-256"


#: Drawn once per run into every photograph: the launcher's test database outlives a stack, and a
#: live capture an earlier run left in another workspace would hold the same bytes and rightly
#: defer their purge.
RUN_MARK = uuid.uuid4().bytes
#: P's width in K2: of this run's own, and never the shared photograph's 64.
P_WIDTH = 96 + RUN_MARK[0] % 160


def photograph(seed: int, width: int = 64) -> bytes:
    """A small synthetic JPEG, different for every seed and every run: development data, no
    person, no place. Photographs of one width and no EXIF have the same intake probe bytes."""
    import io

    from PIL import Image

    image = Image.new("RGB", (width, 48), ((seed * 53) % 256, 90, (seed * 97) % 256))
    for x in range(width):
        image.putpixel((x, seed % 48), (255, 255, 255))
        mark = RUN_MARK[x % len(RUN_MARK)]
        image.putpixel((x, (seed + 24) % 48), (mark, 255 - mark, mark // 2))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


def owner_sql(
    stack: Stack, statement: str, *values: object, workspace: str | None = None
) -> list[tuple[Any, ...]]:
    """An evidence read as the database owner, scoped to ``workspace`` where its tables force
    row-level security."""
    import psycopg

    with psycopg.connect(stack.state["database"]["owner_url_for_evidence_reads"]) as connection:
        if workspace is not None:
            connection.execute(
                "select set_config('exulanica.workspace_id', %s, true)", (workspace,)
            )
        cursor = connection.execute(statement, values)
        rows = cursor.fetchall() if cursor.description else []
        connection.commit()
    return rows


def tombstone_capture(stack: Stack, workspace: str, capture: str, reason: str) -> str:
    """A capture tombstone written as the owner, as the deletion contract's tests and the
    installation driver write one: no route writes it (A-40)."""
    import psycopg

    with psycopg.connect(stack.state["database"]["owner_url_for_evidence_reads"]) as connection:
        connection.execute("select set_config('exulanica.workspace_id', %s, true)", (workspace,))
        row = connection.execute(
            "insert into tombstone (workspace_id, scope, capture_id, requested_by, reason) "
            "values (%s, 'capture', %s, gen_random_uuid(), %s) returning tombstone_id::text",
            (workspace, capture, reason),
        ).fetchone()
        connection.commit()
    return row[0]


def stored(stack: Stack, digest: str) -> bool:
    """An evidence read: whether the run's store holds a blob with this digest."""
    path = (
        Path(stack.state["data_dir"]) / "blobs" / STORE_PREFIX / digest[:2] / digest[2:4] / digest
    )
    return path.exists()


def uploaded(stack: Stack, out: Path, token_file: str, name: str, photo: bytes) -> dict[str, Any]:
    """One photograph through ``POST /intake``, then its batch's job read until it ends."""
    path = stack.run_dir / name
    path.write_bytes(photo)
    status, answer = F.upload(stack, token_file, [path])
    accepted = (answer or {}).get("accepted") or [{}]
    return {
        "status": status,
        "capture_id": accepted[0].get("capture_id"),
        "blob_sha256": accepted[0].get("blob_sha256"),
        "job": (answer or {}).get("queued_job_id"),
        "refused": (answer or {}).get("refused"),
    }


def derived(c: Any, step: str, job: str | None) -> dict[str, Any]:
    deadline = time.monotonic() + DERIVATION_SECONDS
    read: dict[str, Any] = {}
    while job and time.monotonic() < deadline:
        _, read = c.call(step, "GET", f"/operations/derivative-jobs/{job}")
        if (read or {}).get("state") in ("done", "failed"):
            return read
        time.sleep(2)
    return read or {}


def span_of(c: Any, step: str, capture: str) -> dict[str, Any]:
    _, sources = c.call(step, "GET", "/graph/sources")
    return next((s for s in sources or [] if s.get("capture_id") == capture), {})


def evidence_reads(stack: Stack, token_file: str, span: str) -> list[int]:
    """The capture's original and viewer bytes, by the span its reads address."""
    return [
        raw_call(stack, token_file, "GET", f"/evidence/{span}")[0],
        raw_call(stack, token_file, "GET", f"/evidence/{span}/masked")[0],
    ]


def purge(stack: Stack, out: Path, label: str, url: str, workspace: str) -> dict[str, Any]:
    """``exulanica-purge`` over one workspace with the database URL given, as an installation runs
    it. The URL is passed in the environment and never written to evidence."""
    completed = subprocess.run(
        [
            *entry_point(stack.worktree, "exulanica-purge"),
            "--workspace",
            workspace,
            "--data-dir",
            stack.state["data_dir"],
        ],
        cwd=stack.worktree,
        env={**LAUNCH.clean_environment(), "EXULANICA_PURGE_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    text = (completed.stdout + completed.stderr).replace(url, "<url>")
    (out / "evidence" / f"purge-{label}.txt").write_text(text)
    return {"exit": completed.returncode, "lines": text.strip().splitlines()[-8:]}


def k2_photographs(stack: Stack, transcripts: Any, out: Path, row: Row) -> dict[str, Any]:
    """K2 (b), A-40: workspace 1 holds photographs P (bytes of its own) and S; workspace 2 holds
    S's identical bytes. The capture tombstones no route writes are written as the owner; then
    workspace 1's reads refuse, the runtime role's purge destroys nothing, and the purge role's
    erases P's bytes and keeps S's, which workspace 2's live capture holds."""
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    first = workspace_ids(stack)[0]
    shared = photograph(7)
    photos = {
        # A width of this run's own: an intake probe's bytes follow the photograph's size, and an
        # earlier run's live capture of the same size would hold P's probe.
        "p": uploaded(stack, out, "token", "k2-p.jpg", photograph(5, width=P_WIDTH)),
        "s": uploaded(stack, out, "token", "k2-s.jpg", shared),
        "s2": uploaded(stack, out, "token-2", "k2-s2.jpg", shared),
    }
    row.expect(
        all(p["status"] == 202 and p["capture_id"] for p in photos.values()),
        f"intake answered {[p['status'] for p in photos.values()]}",
    )
    row.expect(
        photos["s"]["blob_sha256"] == photos["s2"]["blob_sha256"] != photos["p"]["blob_sha256"],
        "the shared photograph's digests differ, or P's equals them",
    )
    jobs = {
        key: derived(w1 if key != "s2" else w2, "K2 photographs", p["job"])
        for key, p in photos.items()
    }
    row.expect(
        all(j.get("state") == "done" for j in jobs.values()),
        f"the derivations ended {[j.get('state') for j in jobs.values()]}",
    )
    spans = {
        key: span_of(w1 if key != "s2" else w2, "K2 photographs", p["capture_id"])
        for key, p in photos.items()
    }
    before = {
        "p": evidence_reads(stack, "token", spans["p"].get("evidence_span_id", "-")),
        "s": evidence_reads(stack, "token", spans["s"].get("evidence_span_id", "-")),
        "s2": evidence_reads(stack, "token-2", spans["s2"].get("evidence_span_id", "-")),
    }
    row.expect(
        all(status == 200 for reads in before.values() for status in reads),
        f"the evidence reads before the withdrawal answered {before}",
    )
    tombstones = [
        tombstone_capture(stack, first, photos[key]["capture_id"], f"Q10 K2 withdrawal of {key}")
        for key in ("p", "s")
    ]
    after = {
        "p": evidence_reads(stack, "token", spans["p"].get("evidence_span_id", "-")),
        "s": evidence_reads(stack, "token", spans["s"].get("evidence_span_id", "-")),
        "s2": evidence_reads(stack, "token-2", spans["s2"].get("evidence_span_id", "-")),
    }
    row.expect(after["p"] == [410, 410] and after["s"] == [410, 410], f"W1 reads {after}")
    row.expect(after["s2"] == [200, 200], f"W2 reads {after['s2']} after W1's withdrawal")
    listing_before = stack.evidence_digest()
    runtime = purge(stack, out, "runtime-role", stack.state["database"]["runtime_url"], first)
    listing_runtime = stack.evidence_digest()
    row.expect(
        runtime["exit"] == 2
        and any("refusing to destroy anything" in line for line in runtime["lines"]),
        f"the runtime role's purge exited {runtime['exit']}",
    )
    row.expect(
        listing_runtime["store_listing_sha256"] == listing_before["store_listing_sha256"],
        "the runtime role's purge changed the store",
    )
    purge_url = Path(stack.state["purge_url_file"]).read_text().strip()
    privileged = purge(stack, out, "purge-role", purge_url, first)
    row.expect(privileged["exit"] == 0, f"the purge role's purge exited {privileged['exit']}")
    blobs = {
        "p": stored(stack, photos["p"]["blob_sha256"]),
        "s": stored(stack, photos["s"]["blob_sha256"]),
    }
    row.expect(not blobs["p"], "P's bytes are still stored after the purge")
    row.expect(blobs["s"], "S's bytes, which W2's live capture holds, were erased")
    open_tombstones = owner_sql(
        stack,
        "select t.capture_id::text, t.purge_completed_at is not null from tombstone t "
        "where t.workspace_id = %s and t.scope = 'capture' order by 1",
        first,
        workspace=first,
    )
    complete = {str(capture): bool(done) for capture, done in open_tombstones}
    row.expect(
        complete.get(str(photos["p"]["capture_id"])) is True,
        "P's tombstone is not complete: something still holds bytes only workspace 1 held",
    )
    row.expect(
        complete.get(str(photos["s"]["capture_id"])) is False,
        "S's tombstone completed although workspace 2's live capture holds its bytes",
    )
    s2_after = evidence_reads(stack, "token-2", spans["s2"].get("evidence_span_id", "-"))
    row.expect(s2_after == [200, 200], f"W2 reads {s2_after} after the purge")
    return {
        "photographs": {
            key: {k: p.get(k) for k in ("status", "capture_id", "blob_sha256")}
            for key, p in photos.items()
        },
        "derivations": {key: j.get("state") for key, j in jobs.items()},
        "evidence_reads": {"before": before, "after_withdrawal": after, "w2_after_purge": s2_after},
        "tombstones": tombstones,
        "purge_runtime_role": runtime,
        "store_unchanged_by_runtime_role": listing_runtime["store_listing_sha256"]
        == listing_before["store_listing_sha256"],
        "purge_role": privileged,
        "stored_after_purge": blobs,
        "tombstones_complete": [list(t) for t in open_tombstones],
    }


#: How long the depth worker may take to draw a photograph's point map on the CPU.
DEPTH_SECONDS = 900
DEPTH_ROLE = "depth"
#: The material set a recipe is made from, as C7's and the material tests make one.
RECIPE_SET = "cc0.brick-running-bond"
#: A use a place-name right is offered for, and the contract sentence K2 records for it.
PLACE_NAME_USE = "embedding"
PLACE_NAME_CONTRACT = (
    "exulanica/consent/place_name_rights.py: a withdrawal stops the name reaching hosted models; "
    "reads answer as before with the use not allowed, so there is no read to refuse"
)


def k2_rights(stack: Stack, transcripts: Any, out: Path, row: Row) -> dict[str, Any]:
    """K2 (c), A-44: a depth model right's point map read before and after its withdrawal, a
    withdrawn recipe's reads, and a place-name right's withdrawal, which has no read to refuse."""
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    first = workspace_ids(stack)[0]
    observed: dict[str, Any] = {}
    # -- a depth right
    photo = uploaded(stack, out, "token", "k2-depth.jpg", photograph(11, width=320))
    derived(w1, "K2 depth", photo["job"])
    _, admission = w1.call("K2 depth", "GET", "/personal-admission")
    offer = next(
        (
            o
            for o in (admission or {}).get("model_right_offers") or []
            if o.get("role") == DEPTH_ROLE
        ),
        {},
    )
    now = dt.datetime.now(dt.UTC)
    review = {
        "members": [
            {
                "capture_id": photo["capture_id"],
                "sha256": photo["blob_sha256"],
                "bytes": (stack.run_dir / "k2-depth.jpg").stat().st_size,
                "review": "no-person",
            }
        ],
        "purpose": "Q10 acceptance K2: a depth model right over a synthetic fixture",
        "authority": {
            "account_authority_basis": "Synthetic fixture drawn by the acceptance driver; no person",
            "authorized_at": (now - dt.timedelta(minutes=1)).isoformat(),
            "valid_until": (now + dt.timedelta(hours=1)).isoformat(),
        },
        "recorded_at": (now - dt.timedelta(seconds=1)).isoformat(),
        "operation": "review",
        "reviewed_by_name": F.STAND_IN_REVIEWER,
        "attestation": (admission or {}).get("attestation"),
        "model_rights": [
            {
                "role": DEPTH_ROLE,
                "valid_until": (now + dt.timedelta(minutes=50)).isoformat(),
                "notice": offer.get("notice"),
            }
        ],
    }
    status_review, reviewed = w1.call("K2 depth", "POST", "/personal-admission", body=review)
    right_ids = [
        right
        for receipt in (reviewed or {}).get("receipts") or []
        for right in receipt.get("model_right_ids") or []
    ]
    row.expect(
        status_review == 202 and len(right_ids) == 1,
        f"the review with a depth right answered {status_review} with {len(right_ids)} rights",
    )
    deadline = time.monotonic() + DEPTH_SECONDS
    point_map: dict[str, Any] = {}
    while time.monotonic() < deadline:
        _, maps = w1.call("K2 depth", "GET", "/geometry")
        point_map = next(
            (
                m
                for m in maps or []
                if m.get("capture_id") == photo["capture_id"] and m.get("state") == "available"
            ),
            {},
        )
        if point_map:
            break
        time.sleep(5)
    artifact = point_map.get("artifact_id", "-")
    read_before = raw_call(stack, "token", "GET", f"/geometry/{artifact}")[0]
    foreign_read = raw_call(stack, "token-2", "GET", f"/geometry/{artifact}")[0]
    row.expect(read_before == 200, f"the point map read answered {read_before} before withdrawal")
    row.expect(foreign_read == 404, f"another workspace's point map read answered {foreign_read}")
    right = right_ids[0] if right_ids else str(uuid.uuid4())
    path = f"/personal-admission/model-rights/{right}/withdraw"
    foreign_withdraw = w2.call("K2 depth", "POST", path)[0]
    status_withdraw, withdrawn = w1.call("K2 depth", "POST", path)
    status_again, again = w1.call("K2 depth", "POST", path)
    status_after, after = w1.call("K2 depth", "GET", f"/geometry/{artifact}")
    row.expect(
        foreign_withdraw == 404, f"another workspace's withdrawal answered {foreign_withdraw}"
    )
    row.expect(
        status_withdraw == 200 and (withdrawn or {}).get("state") == "ended",
        f"the withdrawal answered {status_withdraw} {(withdrawn or {}).get('state')}",
    )
    row.expect(
        status_again == 200 and again == withdrawn, "a repeated withdrawal answered otherwise"
    )
    row.expect(
        status_after == 404 and F.problem_code(after) == "unknown_reference",
        f"the point map read after withdrawal answered {status_after} {F.problem_code(after)}",
    )
    observed["depth"] = {
        "capture_id": photo["capture_id"],
        "review": [status_review, len(right_ids)],
        "point_map": {k: point_map.get(k) for k in ("artifact_id", "kind", "stage_key", "state")},
        "read_before": read_before,
        "foreign": {"read": foreign_read, "withdraw": foreign_withdraw},
        "withdrawal": [status_withdraw, (withdrawn or {}).get("state"), status_again],
        "read_after": [status_after, F.problem_code(after)],
        "checkpoint": (stack.state.get("depth_worker") or {}).get("checkpoint"),
    }
    # -- a recipe
    _, library = w1.call("K2 recipe", "GET", "/materials/library")
    material = next(
        (e for e in (library or {}).get("sets") or [] if e.get("set_id") == RECIPE_SET), {}
    )
    recipe = dict(material.get("recipe") or {})
    recipe["resolution"] = {"width": 16, "height": 16}
    status_made, made = w1.call(
        "K2 recipe",
        "POST",
        "/materials/recipes",
        body={
            "recipe": recipe,
            "based_on": {"set_id": RECIPE_SET, "version": material.get("version", 1)},
            "label": "Q10 K2",
        },
    )
    recipe_id = (made or {}).get("recipe_id", "-")
    row.expect(status_made == 201, f"the recipe answered {status_made} {F.problem_code(made)}")
    reads = ("", "/bake", "/bake/bytes")
    before = [
        raw_call(stack, "token", "GET", f"/materials/recipes/{recipe_id}{r}")[0] for r in reads[:1]
    ]
    foreign = raw_call(stack, "token-2", "GET", f"/materials/recipes/{recipe_id}")[0]
    status_gone, gone = w1.call("K2 recipe", "POST", f"/materials/recipes/{recipe_id}/withdraw")
    after_reads = [
        raw_call(stack, "token", "GET", f"/materials/recipes/{recipe_id}{r}") for r in reads
    ]
    codes = []
    for status_read, _, body in after_reads:
        try:
            codes.append([status_read, (json.loads(body or b"{}") or {}).get("code")])
        except ValueError:
            codes.append([status_read, None])
    foreign_after = raw_call(stack, "token-2", "GET", f"/materials/recipes/{recipe_id}")[0]
    row.expect(before == [200], f"the recipe read answered {before} before withdrawal")
    row.expect(
        status_gone == 200 and gone == {"recipe_id": recipe_id, "withdrawn": True},
        f"the recipe's withdrawal answered {status_gone} {gone}",
    )
    row.expect(all(c == [410, "withdrawn"] for c in codes), f"the withdrawn recipe's reads {codes}")
    row.expect(
        foreign == foreign_after == 404, f"another workspace's reads {foreign} {foreign_after}"
    )
    observed["recipe"] = {
        "recipe_id": recipe_id,
        "made": status_made,
        "read_before": before,
        "withdrawal": status_gone,
        "reads_after": dict(zip(["recipe", "bake", "bake_bytes"], codes, strict=True)),
        "foreign": [foreign, foreign_after],
    }
    # -- a place-name right: the withdraw route's answer; no read to refuse
    entity = owner_sql(
        stack,
        "insert into entity (workspace_id, class) values (%s, 'place') returning entity_id::text",
        first,
        workspace=first,
    )
    entity_id = entity[0][0] if entity else str(uuid.uuid4())
    status_place, place = w1.call(
        "K2 place name",
        "POST",
        f"/place-name-rights/{entity_id}/withdrawals",
        body={"use": PLACE_NAME_USE},
    )
    status_read_place, read_place = w1.call(
        "K2 place name", "GET", f"/place-name-rights/{entity_id}"
    )
    uses = [
        {k: u.get(k) for k in ("use", "state", "allowed")}
        for u in (read_place or {}).get("uses") or []
    ]
    observed["place_name"] = {
        "entity_written_as_owner": entity_id,
        "withdrawal": [status_place, F.problem_code(place)],
        "read_after": [status_read_place, uses],
        "result": "no read to refuse",
        "contract": PLACE_NAME_CONTRACT,
    }
    return observed


def row_k2(stack: Stack, transcripts: Any, out: Path, log: Path) -> Row:
    row = Row(
        "K2",
        "store.withdrawal",
        "A-40 and A-44, in three parts. (a) A workspace asset withdrawn by workspace 1 reads 410, "
        "its prepared bytes are refused, a placement by its id and known prepared digest is "
        "refused workspace_asset_withdrawn, nothing of the namespace is destroyed, and workspace "
        "2's own admission of identical bytes still reads and delivers. (b) Photographs: after "
        "workspace 1's capture tombstones (written as the owner, since no route writes one) its "
        "evidence reads answer 410; the purge run "
        "with the runtime role's credential refuses to destroy anything and leaves the store as it "
        "was; run with the purge role it erases the bytes only workspace 1 held and keeps the bytes "
        "workspace 2's live capture holds, whose reads still answer, so P's tombstone completes and "
        "S's stays open. (c) A depth model right's "
        "point map reads 200, then 404 after the right is withdrawn (ended; a repeat finds the "
        "first; another workspace 404); a withdrawn recipe's reads answer 410 and another "
        "workspace's 404; a place-name right has no read to refuse, by contract.",
    )
    row.observed["assets"] = k2_assets(stack, transcripts, out, log, row)
    row.observed["photographs"] = k2_photographs(stack, transcripts, out, row)
    row.observed["rights"] = k2_rights(stack, transcripts, out, row)
    return row.close()


#: A picture's reading right (docs/personal-admission.md, docs/reference-notes-contract.md section 10).
PICTURE_RIGHT_ROLE = "reference_vision"
#: How long after a stop LP1 waits before a later consent, longer than the second its admissions
#: are recorded before they are sent, so the consent is granted after the stop.
PICTURE_GRANT_GAP_SECONDS = 2.5


def picture_right(
    c: Any, step: str, stack: Stack, photo: Mapping[str, Any], name: str
) -> tuple[int, list[str]]:
    """``c``'s person admits ``photo`` again with a picture's reading right, as the account holder
    does, against the exact words the reference list states for that right."""
    _, admission = c.call(step, "GET", "/personal-admission")
    # A-141: the words a picture's reading right is granted against are the ones the reference
    # list states under pictures.consent.uses, served where pictures are offered.
    _, listed = c.call(step, "GET", "/worlds/references")
    uses = (((listed or {}).get("pictures") or {}).get("consent") or {}).get("uses") or []
    offer = next((u for u in uses if u.get("role") == PICTURE_RIGHT_ROLE), {})
    now = dt.datetime.now(dt.UTC)
    status, answer = c.call(
        step,
        "POST",
        "/personal-admission",
        body={
            "members": [
                {
                    "capture_id": photo["capture_id"],
                    "sha256": photo["blob_sha256"],
                    "bytes": (stack.run_dir / name).stat().st_size,
                    "review": "no-person",
                }
            ],
            "purpose": "Q10 acceptance LP1: a picture's reading right over a synthetic fixture",
            "authority": {
                "account_authority_basis": "Synthetic fixture drawn by the acceptance driver; no person",
                "authorized_at": (now - dt.timedelta(minutes=1)).isoformat(),
                "valid_until": (now + dt.timedelta(hours=1)).isoformat(),
            },
            "recorded_at": (now - dt.timedelta(seconds=1)).isoformat(),
            "operation": "review",
            "reviewed_by_name": F.STAND_IN_REVIEWER,
            "attestation": (admission or {}).get("attestation"),
            "model_rights": [
                {
                    "role": PICTURE_RIGHT_ROLE,
                    "valid_until": (now + dt.timedelta(minutes=50)).isoformat(),
                    "notice": offer.get("notice"),
                }
            ],
        },
    )
    rights = [
        right
        for receipt in (answer or {}).get("receipts") or []
        for right in receipt.get("model_right_ids") or []
    ]
    return status, rights


def right_states(c: Any, step: str, capture: str) -> dict[str, str]:
    """Every right ``c``'s person granted over ``capture``, by id, with its state, as their own
    admission read lists them."""
    _, admission = c.call(step, "GET", "/personal-admission")
    return {
        str(right.get("right_id")): str(right.get("state"))
        for source in (admission or {}).get("sources") or []
        if source.get("capture_id") == capture
        for right in source.get("model_rights") or []
    }


def row_lp1(stack: Stack, transcripts: Any, out: Path) -> Row:
    row = Row(
        "LP1",
        "references.picture_right_stop",
        "A picture's reading right is stopped by its grantor, with the grantor's other reading "
        "rights on that picture, and never a consent given later (candidate-36): on one picture of "
        f"workspace 1, A grants two {PICTURE_RIGHT_ROLE} rights and B (another person of the "
        "workspace) one; B's stop of A's first right is 404 as for an id nobody granted; A's stop "
        "of it answers ended and ends A's second, B's standing; A then grants a third, and A's "
        "stop of the first again leaves the third current. An owner's own stop is left to LOOKUP's "
        "HTTP tests: this stack has no owner session.",
    )
    a = F.client(stack, transcripts, "w1", "token")
    b = F.client(stack, transcripts, "peer", "token-peer")
    photo = uploaded(stack, out, "token", "lp1-picture.jpg", photograph(23, width=320))
    derived(a, "LP1", photo["job"])
    capture = photo["capture_id"]
    _, listed = a.call("LP1", "GET", "/worlds/references")
    consent = ((listed or {}).get("pictures") or {}).get("consent")
    if not consent:
        row.blocked_by.append(
            "the reference list states no picture consent here (pictures not offered on this stack)"
        )
        row.observed = {"pictures": (listed or {}).get("pictures")}
        return row.close()
    status_1, first = picture_right(a, "LP1 A first", stack, photo, "lp1-picture.jpg")
    status_2, second = picture_right(a, "LP1 A second", stack, photo, "lp1-picture.jpg")
    status_b, theirs = picture_right(b, "LP1 B", stack, photo, "lp1-picture.jpg")
    granted = [status_1, status_2, status_b]
    row.expect(
        granted == [202, 202, 202] and all(len(ids) >= 1 for ids in (first, second, theirs)),
        f"the grants answered {granted} with {[len(first), len(second), len(theirs)]} rights",
    )
    if not (first and second and theirs):
        row.observed = {"granted": granted}
        return row.close()
    path = f"/personal-admission/model-rights/{first[0]}/withdraw"
    status_foreign, foreign = b.call("LP1 B stops A's", "POST", path)
    a_before = right_states(a, "LP1 A before", capture)
    status_stop, stopped = a.call("LP1 A stops", "POST", path)
    a_after, b_after = (
        right_states(a, "LP1 A after", capture),
        right_states(b, "LP1 B after", capture),
    )
    # A right's grant time is its admission's recorded_at, which picture_right sets a second before
    # it sends; a consent given since the stop must be recorded after it (A-141's second clause).
    time.sleep(PICTURE_GRANT_GAP_SECONDS)
    status_3, third = picture_right(a, "LP1 A third", stack, photo, "lp1-picture.jpg")
    # The later consent read before the repeated stop, so the stop's own effect is what is judged.
    a_between = right_states(a, "LP1 A between", capture)
    status_again, _ = a.call("LP1 A stops again", "POST", path)
    a_last = right_states(a, "LP1 A last", capture)
    row.expect(
        status_foreign == 404,
        f"B's stop of A's right answered {status_foreign} {F.problem_code(foreign)}",
    )
    # One grant records a right for each model the role reaches, so each is judged as a set.
    row.expect(
        all(a_before.get(r) == "current" for r in (*first, *second)),
        f"before the stop A's rights read {a_before}",
    )
    row.expect(
        status_stop == 200 and (stopped or {}).get("state") == "ended",
        f"A's stop answered {status_stop} {(stopped or {}).get('state')}",
    )
    row.expect(
        all(a_after.get(r) == "ended" for r in (*first, *second)),
        f"after A's stop A's rights read {a_after}",
    )
    row.expect(
        all(b_after.get(r) == "current" for r in theirs),
        f"after A's stop B's rights read {b_after}",
    )
    row.expect(
        bool(third) and all(a_between.get(r) == "current" for r in third),
        f"the later consent read before the repeated stop {a_between}",
    )
    row.expect(
        status_3 == 202
        and bool(third)
        and status_again == 200
        and all(a_last.get(r) == "current" for r in third),
        f"the later consent answered {status_3}; the repeated stop {status_again}; A's rights {a_last}",
    )
    row.observed = {
        "capture": capture,
        "granted": granted,
        "b_stops_a": [status_foreign, F.problem_code(foreign)],
        "a_before": a_before,
        "a_stop": [status_stop, (stopped or {}).get("state")],
        "a_after": a_after,
        "b_after": b_after,
        "later": [status_3, status_again],
        "third": third,
        "a_between": a_between,
        "a_last": a_last,
    }
    return row.close()


def picture_rights(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if (
        not stack.token_file("token-peer").exists()
        or not stack.state.get("reference_pictures")
        or (stack.state.get("scripted_model") or {}).get("spending") != "durable"
    ):
        raise SystemExit(
            "picture-rights needs a stack started with --workspaces 2 --peer-token "
            "--reference-pictures --scripted-model scripts/acceptance/plans/spending.json "
            "--spending durable --no-derivative-worker --depth-worker (A-141)"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_lp1(stack, Transcripts(out / "transcripts"), out)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


def withdrawal(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if (
        len(workspace_ids(stack)) < 2
        or stack.state.get("scripted_model")
        or not stack.state.get("depth_worker")
        or not stack.state.get("purge_url_file")
    ):
        raise SystemExit(
            "withdrawal needs a stack started with --workspaces 2 --no-derivative-worker "
            "--depth-worker, no scripted model, and a launcher that records the purge URL file"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    log = out / "transcripts" / "admissions.jsonl"
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_k2(stack, transcripts, out, log)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- X1: both decision roles through the one seam, from outside -------------------------------------

MODELS = "/models"
SIGNAL_ROLE = "junction_signal"
#: A model the manifest declares but offers neither decision role (an embedding model).
NOT_OFFERED = {"provider": "nebius_token_factory", "model_id": "Qwen/Qwen3-Embedding-8B"}
#: How long the host may take to ask a chosen person's model once the society plays, and how long
#: past a signal choice's effective second its first sealed segment may take.
PERSON_DECISION_SECONDS = 300
#: How many of the town's people X1 chooses the model for, at most.
PEOPLE_CHOSEN_MOST = 16
SIGNAL_SEAL_SECONDS = 180
SIGNAL_WINDOW_SECONDS = 5


def without_clock(read: Any) -> Any:
    """A traffic read without the server's current second, which moves between two reads."""
    return (
        {k: v for k, v in read.items() if k != "clock_second"} if isinstance(read, dict) else read
    )


def roles_read(c: Any, step: str, entry: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    _, read = c.call(step, "GET", F.version_path(entry, MODELS), query=F.world_query(entry))
    return {role.get("key"): role for role in (read or {}).get("roles") or []}


def choose_model(
    c: Any,
    step: str,
    entry: Mapping[str, Any],
    role: str,
    subjects: Sequence[str],
    model: Mapping[str, str] | None,
) -> tuple[int, Any]:
    return c.call(
        step,
        "POST",
        F.version_path(entry, f"{MODELS}/{role}"),
        query=F.world_query(entry),
        body={
            "idempotency_key": str(uuid.uuid4()),
            "subjects": list(subjects),
            "model": None if model is None else dict(model),
        },
    )


def control(c: Any, step: str, entry: Mapping[str, Any], mode: str) -> tuple[int, Any]:
    path = F.version_path(entry, "/society/control")
    _, read = c.call(step, "GET", path, query=F.world_query(entry))
    return c.call(
        step,
        "PUT",
        path,
        query=F.world_query(entry),
        body={"base_revision": (read or {}).get("revision", 0), "mode": mode, "speed": 1},
    )


def signal_town(c: Any) -> dict[str, Any] | None:
    """A generated town of the workspace whose signal role names signals: one the comparisons
    run made, or a new one while the count policy allows."""
    _, entries = c.call("X1", "GET", "/world-entries")
    for listed in entries or []:
        if not listed.get("generated_ground"):
            continue
        entry = F.read_entry(c, "X1", listed["entry_id"])
        if (roles_read(c, "X1", entry).get(SIGNAL_ROLE) or {}).get("subjects"):
            return entry
    for index in range(TOWNS_ALLOWED):
        status, town = c.call(
            "X1",
            "POST",
            "/worlds/generated",
            body={"recipe": "small_town", "title": f"Q10 X1 {index}"},
        )
        if status != 201:
            return None
        if (roles_read(c, "X1", town).get(SIGNAL_ROLE) or {}).get("subjects"):
            return town
    return None


def row_x1(stack: Stack, transcripts: Any, out: Path) -> Row:
    row = Row(
        "X1",
        "roles.both",
        "On one generated town of the workspace the host plays, both decision roles pass through "
        "the one seam up to selection (A-43): GET .../models "
        "serves the person role and the junction-signal role with their subjects, models and an "
        "operation descriptor each; POST .../models/{role} selects a scripted model for people "
        "and for a signal, and refuses by name a model the role is not offered and a subject not "
        "in the world, for each role. Beyond selection each role keeps its own receipts and "
        "replay: the playing society asks the chosen people's model and the people role reads "
        "its decisions, and the society's replay answers the live state with no model call; the "
        "chosen signal's sealed segment names its decisions' digest and reads the same again "
        "with no model call. Scripted answers: mechanics only.",
    )
    # The host plays the run's first workspace alone, so both roles are that workspace's: the
    # people of a generated town's living society, and one of the same town's signals.
    town_client = c = F.client(stack, transcripts, "w1", "token")
    town = signal_town(town_client)
    entry = town or {}
    if town and F.society(c, "X1", town)[0] != 200:
        c.call(
            "X1",
            "POST",
            F.version_path(town, "/society"),
            query=F.world_query(town),
            body={"region_id": TOWN_REGION, "profile": TOWN_ENGINE},
        )
    row.expect(town is not None, "no generated town of the workspace carries signals")
    if town is None:
        return row.close()
    people_roles = roles_read(c, "X1", entry)
    signal_roles = roles_read(town_client, "X1", town) if town else {}
    person, signal = people_roles.get(PERSON_ROLE) or {}, signal_roles.get(SIGNAL_ROLE) or {}
    for name, role in (("person", person), ("signal", signal)):
        descriptor = role.get("capability") or {}
        row.expect(
            bool(role) and role.get("available") is True and bool(descriptor),
            f"the {name} role reads available {role.get('available')} "
            f"({role.get('reason') or role.get('host_refusal')})",
        )
    _, society = F.society(c, "X1", entry)
    inhabitants = [
        p.get("id") for p in ((society or {}).get("state") or {}).get("inhabitants") or []
    ]
    signals = [s.get("signal_id") for s in signal.get("subjects") or []]
    refusals = {
        "person_not_offered": choose_model(
            c, "X1", entry, PERSON_ROLE, inhabitants[:1], NOT_OFFERED
        ),
        "person_not_in_world": choose_model(
            c, "X1", entry, PERSON_ROLE, [str(uuid.uuid4())], GOING_MODEL
        ),
        "signal_not_offered": choose_model(
            town_client, "X1", town or entry, SIGNAL_ROLE, signals[:1], NOT_OFFERED
        )
        if town
        else (None, None),
        "signal_not_in_world": choose_model(
            town_client, "X1", town or entry, SIGNAL_ROLE, [str(uuid.uuid4())], GOING_MODEL
        )
        if town
        else (None, None),
    }
    wanted = {
        "person_not_offered": "model_not_offered",
        "person_not_in_world": "person_not_in_this_world",
        "signal_not_offered": "model_not_offered",
        "signal_not_in_world": "signal_not_in_world",
    }
    for key, (status_refused, body) in refusals.items():
        row.expect(
            status_refused == 422 and F.problem_code(body) == wanted[key],
            f"{key} answered {status_refused} {F.problem_code(body)}",
        )
    # As many people as the role lets one choice name, up to a bound: a few chosen people may meet
    # no choice point for many simulated minutes (A-46).
    most = person.get("model_subjects_maximum") or PEOPLE_CHOSEN_MOST
    chosen_people = inhabitants[: min(int(most), PEOPLE_CHOSEN_MOST)]
    status_people, people_choice = choose_model(
        c, "X1", entry, PERSON_ROLE, chosen_people, GOING_MODEL
    )
    row.expect(status_people == 200, f"the people's choice answered {status_people}")
    status_signal, signal_choice = (
        choose_model(town_client, "X1", town, SIGNAL_ROLE, signals[:1], GOING_MODEL)
        if town
        else (None, {})
    )
    row.expect(status_signal == 200, f"the signal's choice answered {status_signal}")
    # The person role's own receipts and replay.
    status_play, _ = control(c, "X1", entry, "playing")
    row.expect(status_play == 200, f"playing the society answered {status_play}")
    deadline = time.monotonic() + PERSON_DECISION_SECONDS
    latest: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        view = (roles_read(c, "X1", entry).get(PERSON_ROLE) or {}).get("view") or {}
        latest = [
            d for d in view.get("latest") or [] if d.get("model_id") == GOING_MODEL["model_id"]
        ]
        if latest:
            break
        time.sleep(3)
    status_pause, _ = control(c, "X1", entry, "paused")
    row.expect(status_pause == 200, f"pausing the society answered {status_pause}")
    row.expect(bool(latest), "no person decision by the chosen model was read")
    calls_before = len(scripted_log(stack))
    _, live = F.society(c, "X1", entry)
    status_replay, replayed = c.call(
        "X1", "GET", F.version_path(entry, "/society/replay"), query=F.world_query(entry)
    )
    calls_after = len(scripted_log(stack))
    row.expect(
        status_replay == 200
        and (replayed or {}).get("state_sha256") == (live or {}).get("state_sha256"),
        f"the society's replay answered {status_replay} with another state",
    )
    row.expect(calls_after == calls_before, f"the replay made {calls_after - calls_before} calls")
    # The signal role's own receipts and replay.
    sealed: list[dict[str, Any]] = []
    second = (signal_choice or {}).get("effective_second")
    traffic: tuple[int, Any] = (0, {})
    if town and isinstance(second, int):
        query = {
            **F.world_query(town),
            "from_second": str(second),
            "seconds": str(SIGNAL_WINDOW_SECONDS),
        }
        deadline = time.monotonic() + SIGNAL_SEAL_SECONDS
        while time.monotonic() < deadline:
            traffic = town_client.call("X1", "GET", F.version_path(town, "/traffic"), query=query)
            sealed = (traffic[1] or {}).get("sealed_segments") or [] if traffic[0] == 200 else []
            if sealed:
                break
            time.sleep(3)
        calls_signal = len(scripted_log(stack))
        again = town_client.call("X1", "GET", F.version_path(town, "/traffic"), query=query)
        row.expect(
            bool(sealed)
            and all(len(str(seg.get("decisions_sha256") or "")) == 64 for seg in sealed),
            f"the chosen signal's traffic read answered {traffic[0]} with {len(sealed)} sealed "
            "segments",
        )
        # The read serves the server's clock beside the window; everything else is the window's.
        row.expect(
            again[0] == traffic[0] and without_clock(again[1]) == without_clock(traffic[1]),
            "the sealed traffic read differently the second time",
        )
        row.expect(
            len(scripted_log(stack)) == calls_signal, "reading the sealed traffic asked a model"
        )
    row.observed = {
        "world": town["entry_id"],
        "roles": {
            name: {
                "available": role.get("available"),
                "reason": role.get("reason"),
                "host_refusal": role.get("host_refusal"),
                "operation": (role.get("capability") or {}).get("operation"),
                "models": len(role.get("models") or (role.get("view") or {}).get("models") or []),
            }
            for name, role in (("person", person), ("signal", signal))
        },
        "refusals": {k: [v[0], F.problem_code(v[1])] for k, v in refusals.items()},
        "choices": {
            "people": [status_people, (people_choice or {}).get("choice_seq"), len(chosen_people)],
            "signal": [status_signal, (signal_choice or {}).get("effective_second")],
        },
        "person_decisions": [
            {k: d.get(k) for k in ("status", "reason", "disposition", "chose")} for d in latest[:6]
        ],
        "person_replay": [status_replay, calls_before, calls_after],
        "signal_sealed": sealed[:3],
        "seam": "shared through discovery and selection; receipts and replay on each role's own "
        "routes (A-43)",
    }
    return row.close()


def roles(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    served = (stack.state.get("scripted_model") or {}).get("plan_sha256")
    if served != hashlib.sha256(COMPARISONS_PLAN.read_bytes()).hexdigest():
        raise SystemExit("roles needs the comparisons stack (its scripted plan and playback)")
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_x1(stack, transcripts, out)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- X2, X3: the change maps, reviewed against the candidate's source ------------------------------

#: The change maps the owners delivered, by path in the foundation packet's deliveries.
CHANGE_MAPS = {"X2": "F1/change-map-X2.md", "X3": "C7/change-map-X3-v2.md"}
#: What each change map says of the code, as a file and a pattern the candidate's source must hold.
X2_CLAIMS = (
    ("each decision role's host is one entry in a fixed table", "exulanica/api/role_hosts.py",
     r'ROLE_HOSTS: Final\[Mapping\[str, RoleHost\]\] = MappingProxyType\(\s*\{"person": _People\(\), "signal": _Signals\(\)\}'),
    ("the models read does not switch on a role's subject", "exulanica/api/routes/world_models.py",
     r"(?s)\A(?!.*\bsubject\s*==\s*[\"'])"),
    ("the version capability read's adapters are one fixed tuple", "exulanica/api/routes/capabilities.py",
     r"VERSION_ADAPTERS: Final\[tuple\["),
    ("the behaviour descriptor names its options read, not the behaviours",
     "tests/test_world_capabilities_api.py",
     r"def test_a_reviewed_behaviour_added_to_its_catalog_is_offered_with_no_second_definition"),
    ("a registered role with no host is listed and refused by name",
     "tests/test_world_capabilities_api.py",
     r"def test_a_role_the_registry_adds_is_listed_and_refused_until_its_host_is_written"),
)  # fmt: skip
X2_TESTS = (
    "tests/test_world_capabilities_api.py::"
    "test_a_reviewed_behaviour_added_to_its_catalog_is_offered_with_no_second_definition",
    "tests/test_world_capabilities_api.py::"
    "test_a_role_the_registry_adds_is_listed_and_refused_until_its_host_is_written",
)
#: The switches on the family kind the X3 change map names, each where the candidate holds it.
X3_SWITCHES = (
    ("the profile-to-adapter choice", "exulanica/world/character_catalogs.py",
     r"def publication_families\(.*\n(?:.*\n){0,4}?.*if profile == LAYERED_PROFILE:"),
    ("the profile branch in the browser's catalog reader",
     "web/packages/atlas-react/src/playcanvas/character/served.ts",
     r"document\.profile === PARAMETRIC_PROFILE && entry\.kind === 'parametric-body'"),
    ("the family-kind branch in the repository", "exulanica/world/character_appearance_repository.py",
     r"is_parametric_family\(family\)"),
    ("the representation-id prefix in the browser loader", "web/packages/app/src/character-catalog.ts",
     r"PREPARATION_PREFIX = 'preparation:'"),
    ("the saved-choice kind in the looks store", "web/packages/app/src/character-looks-store.ts",
     r"kind: 'prepared'"),
    ("the saved-choice kind in composition", "web/packages/app/src/composition/character.ts",
     r"async function wearPrepared\("),
    ("the preparer entry", "exulanica/world/asset_preparation.py",
     r"CharacterBodyPreparer\.preparer_id"),
)  # fmt: skip


def source_claims(worktree: Path, claims: Sequence[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """Each claim's file and whether the candidate's source holds its pattern, with the line."""
    found = []
    for words, path, pattern in claims:
        file = worktree / path
        text = file.read_text() if file.exists() else ""
        match = re.search(pattern, text) if text else None
        found.append(
            {
                "claim": words,
                "file": path,
                "holds": match is not None,
                "line": None if match is None else text.count("\n", 0, match.start()) + 1,
            }
        )
    return found


def row_x2(out: Path, worktree: Path, deliveries: Path) -> Row:
    row = Row(
        "X2",
        "review.change_map_extension",
        "F1's change map (deliveries/F1/change-map-X2.md) is reviewed against the candidate: its "
        "two test-only extensions (a reviewed behaviour reaching discovery with no second "
        "definition and refused by name out of range; a registered role listed and refused "
        "role_subject_unsupported until its host exists) pass on the candidate, and each thing the "
        "map says of the code holds in the candidate's source: one host table for the roles, no "
        "switch on a role's subject in the models read, one fixed tuple of capability adapters.",
    )
    change_map = deliveries / CHANGE_MAPS["X2"]
    row.expect(change_map.exists(), f"no change map at {CHANGE_MAPS['X2']}")
    claims = source_claims(worktree, X2_CLAIMS)
    for claim in claims:
        row.expect(claim["holds"], f"the source does not hold: {claim['claim']} ({claim['file']})")
    tests = lane_tests(out, worktree, "x2-tests", X2_TESTS)
    row.expect(
        tests["exit"] == 0, f"F1's extension tests exited {tests['exit']}: {tests['summary']}"
    )
    row.observed = {
        "change_map": CHANGE_MAPS["X2"],
        "change_map_sha256": hashlib.sha256(change_map.read_bytes()).hexdigest()
        if change_map.exists()
        else None,
        "claims": claims,
        "tests": tests,
    }
    return row.close()


def row_x3(out: Path, worktree: Path, deliveries: Path) -> Row:
    row = Row(
        "X3",
        "review.change_map_second_family",
        "C7's change map (deliveries/C7/change-map-X3-v2.md) is reviewed against the candidate: "
        "it gives each layer's edit for the second family kind, and every switch on the family "
        "kind it names in a shared layer (catalog adapter, browser reader, repository, loader, "
        "looks store, composition, preparer registry) is found where it says, and is flagged to "
        "root as a repeated switch a third kind would extend.",
    )
    change_map = deliveries / CHANGE_MAPS["X3"]
    row.expect(change_map.exists(), f"no change map at {CHANGE_MAPS['X3']}")
    text = change_map.read_text() if change_map.exists() else ""
    layers = [
        line.split("|")[1].strip()
        for line in text.splitlines()
        if line.startswith("| ") and "---" not in line
    ][1:]
    row.expect(len(layers) >= 10, f"the change map names {len(layers)} layers")
    switches = source_claims(worktree, X3_SWITCHES)
    for switch in switches:
        row.expect(switch["holds"], f"the named switch is not in the source: {switch['claim']}")
    row.observed = {
        "change_map": CHANGE_MAPS["X3"],
        "change_map_sha256": hashlib.sha256(change_map.read_bytes()).hexdigest() if text else None,
        "layers": layers,
        "switches_flagged_to_root": switches,
    }
    return row.close()


def reviews(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    deliveries = Path(arguments.deliveries).resolve()
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_x2(out, worktree, deliveries), row_x3(out, worktree, deliveries)]
    results = {
        "profile": "q10-foundation-acceptance-results/v1",
        "candidate": LAUNCH.tree_identity(worktree),
        "launcher_run": None,
        "started_at": started,
        "finished_at": dt.datetime.now(dt.UTC).isoformat(),
        "timing_claims": False,
        "rows": [row.document() for row in rows],
        "counts": {state: sum(row.status == state for row in rows) for state in F.STATES},
    }
    (out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True))
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "driver_sha256": DRIVER_SHA256_AT_START,
                "foundation_sha256": F.DRIVER_SHA256_AT_START,
                "command": ["domain_rows.py", *sys.argv[1:]],
            },
            indent=2,
            sort_keys=True,
        )
    )
    for row in rows:
        print(f"{row.row:16} {row.status:8} {'; '.join(row.failures or row.blocked_by)}")
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- E4: a newly published option in the production page, from outside -----------------------------

CATALOG_RUNNER = HERE / "catalog_browser.mjs"
#: The option E4 publishes: one more hair colour in the people catalog's first family, data only.
NEW_COLOUR = {"key": "q10-copper", "label": "Copper", "rgb": "#b0643a"}
NEW_COLOUR_SLOT = "hairColour"
CATALOG_BUDGET_SECONDS = 600
HANDSHAKE_SECONDS = 300


def build_digest(stack: Stack) -> str:
    """An evidence read: the digest of every file of the stack's production build."""
    root = Path(stack.state["run_dir"]) / "app-build"
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def catalog_c(stack: Stack, revision: int) -> Path:
    """The repository's layered catalog at ``revision`` with one more hair colour in its first
    family, beside links to the unchanged family folders."""
    source = stack.worktree / CHARACTER_SOURCE
    target = stack.run_dir / f"catalog-e4-{revision}"
    target.mkdir(exist_ok=True)
    catalog = json.loads((source / "catalog.json").read_text())
    catalog["revision"] = revision
    catalog["families"][0]["colours"][NEW_COLOUR_SLOT].append(dict(NEW_COLOUR))
    (target / "catalog.json").write_text(json.dumps(catalog, indent=2))
    (target / "looks.json").write_bytes((source / "looks.json").read_bytes())
    for folder in source.iterdir():
        if folder.is_dir() and not (target / folder.name).exists():
            (target / folder.name).symlink_to(folder)
    return target


def row_e4(stack: Stack, transcripts: Any, out: Path) -> Row:
    row = Row(
        "E4",
        "browser.catalog_injection",
        "In the production build served by the stack, the character studio's people controls, "
        "reached through the page's own tool rail, do not offer a hair colour the repository's "
        "catalog lacks; the host publishes the layered catalog's next revision with that one "
        "colour added to the first family; after the page reloads, the same control offers it "
        "beside every colour it offered before, the page having read the new revision by its "
        "digest, and no file of the production build changed (A-42). A newly published family "
        "is a stated limit and is not checked. Functional only; how it looks stays with the "
        "experience owner.",
    )
    c = F.client(stack, transcripts, "w1", "token")
    _, listing = c.call("E4", "GET", CATALOGS)
    revisions = [
        int(p.get("revision") or 0)
        for p in (listing or {}).get("publications", [])
        if p.get("catalog_id") == LAYERED_CATALOG_ID
    ]
    revision = max(revisions or [REPOSITORY_LAYERED_REVISION]) + 1
    directory = catalog_c(stack, revision)
    build_before = build_digest(stack)
    rehearse = F._rehearsal()
    session_dir = out / "session"
    session_dir.mkdir(parents=True, exist_ok=True)
    ready, published = session_dir / "ready", session_dir / "published.json"
    ports = stack.state["ports"]
    plan = {
        "session": {"id": "e4", "budget_seconds": CATALOG_BUDGET_SECONDS},
        "out": str(session_dir),
        "label": NEW_COLOUR["label"],
        "slot": NEW_COLOUR_SLOT,
        "handshake": {
            "ready": str(ready),
            "published": str(published),
            "wait_seconds": HANDSHAKE_SECONDS,
        },
        "runtime": {
            "app_url": f"http://localhost:{ports['vite']}/",
            "api_base": f"http://127.0.0.1:{ports['api']}",
            "token_file": str(stack.token_file("token")),
            "browser_port": ports["browser"],
            "chrome_flags": list(rehearse.CHROME_GPU_FLAGS),
        },
    }
    plan_file = session_dir / "plan.json"
    plan_file.write_text(json.dumps(plan, indent=2))
    command = F.browser_command(
        rehearse, stack.worktree, ["node", str(CATALOG_RUNNER), str(plan_file)]
    )
    runner_log = (out / "runner.txt").open("w")
    runner = subprocess.Popen(
        command,
        cwd=stack.worktree,
        env=LAUNCH.clean_environment(),
        stdout=runner_log,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + CATALOG_BUDGET_SECONDS + rehearse.GPU_SLOT_WAIT_SECONDS
    while not ready.exists() and runner.poll() is None and time.monotonic() < deadline:
        time.sleep(1)
    publication: dict[str, Any] = {}
    if ready.exists():
        publication = catalog_tool(
            stack, out, "publish-e4", "publish", "--directory", str(directory), "--apply"
        )
        _, after = c.call("E4", "GET", CATALOGS)
        current = next(
            (
                p
                for p in (after or {}).get("publications", [])
                if p.get("catalog_id") == LAYERED_CATALOG_ID and p.get("revision") == revision
            ),
            {},
        )
        publication["catalog_sha256"] = current.get("catalog_sha256")
        publication["state"] = current.get("state")
        published.write_text(json.dumps({"catalog_sha256": current.get("catalog_sha256")}))
    try:
        runner.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        runner.terminate()
        runner.wait(timeout=30)
    runner_log.close()
    build_after = build_digest(stack)
    session = (
        json.loads((session_dir / "session.json").read_text())
        if (session_dir / "session.json").exists()
        else {}
    )
    outcomes = session.get("outcomes") or {}
    row.expect(
        publication.get("exit") == 0, f"publishing the revision exited {publication.get('exit')}"
    )
    row.expect(
        publication.get("state") == "current", f"the new revision reads {publication.get('state')}"
    )
    for step in ("catalog-before", "catalog-after"):
        outcome = outcomes.get(step) or {}
        row.expect(
            outcome.get("status") == "passed",
            f"{step}: {outcome.get('status') or 'not reached'} {outcome.get('reason') or ''}".strip(),
        )
    row.expect(build_before == build_after, "a file of the production build changed")
    row.observed = {
        "runner_exit": runner.returncode,
        "revision": revision,
        "option": NEW_COLOUR,
        "publication": publication,
        "steps": {step: (outcomes.get(step) or {}).get("status") for step in outcomes},
        "observations": {step: (outcomes.get(step) or {}).get("observations") for step in outcomes},
        "facts": session.get("facts"),
        "unreached": session.get("unreached"),
        "build_sha256": {"before": build_before, "after": build_after},
        "index_html_sha256": ((stack.state.get("app") or {}).get("build") or {}).get(
            "index_html_sha256"
        ),
    }
    return row.close()


def catalog(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if (stack.state.get("app") or {}).get("mode") != "production":
        raise SystemExit("catalog needs a stack started with --production")
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_e4(stack, transcripts, out)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- A5: what a generated world was made with ------------------------------------------------------

#: The recipe catalogs as files: A5 reads the preset from the newest one itself (A-63).
RECIPE_CATALOGS = Path("assets") / "catalogs" / "world-recipes"
A5_RECIPE = "small_town"


def newest_recipe(worktree: Path, key: str) -> tuple[str, dict[str, Any]]:
    """The newest recipe catalog file's name and its entry ``key``, read from the file."""
    files = sorted(
        (worktree / RECIPE_CATALOGS).glob("world-recipe.v*.json"),
        key=lambda path: int(path.stem.rsplit(".v", 1)[1]),
    )
    catalog = json.loads(files[-1].read_text())
    return files[-1].name, next(entry for entry in catalog["entries"] if entry["key"] == key)


def asked_values(specification: Mapping[str, Any], preset: Mapping[str, Any]) -> dict[str, int]:
    """Two integer values the specification serves, each set to an end of its range that differs
    from the preset's."""
    asked: dict[str, int] = {}
    for value in specification.get("values", []):
        key = value.get("key")
        if not isinstance(value.get("minimum"), int) or not isinstance(value.get("maximum"), int):
            continue
        if key not in preset or not str(key).endswith("_permille"):
            continue
        end = value["minimum"] if preset[key] != value["minimum"] else value["maximum"]
        if end != preset[key]:
            asked[key] = end
        if len(asked) == 2:
            break
    return asked


def row_a5(stack: Stack, transcripts: Any, worktree: Path) -> Row:
    row = Row(
        "A5",
        "worlds.made_with",
        "A town made from the small_town preset with two values asked states, on its entry and in "
        "the list, the specification and every value the preset's catalog file names with the two "
        "asked in their place; a second town made from the first's recipe_key and values states "
        "the same values; the first town's entry reads the same before and after; the starter "
        "states generated_ground null; the other workspace is answered 404 for both towns and "
        "lists neither.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    catalog_file, preset = newest_recipe(worktree, A5_RECIPE)
    status, specification = w1.call("A5", "GET", "/worlds/specification")
    row.expect(status == 200, f"the specification answered {status}")
    asked = asked_values(specification, preset["values"])
    row.expect(len(asked) == 2, f"found {len(asked)} values to ask")
    expected = {**preset["values"], **asked}
    status_starter, starter = w1.call(
        "A5", "POST", "/world-entries/starter", body={"title": "Q10 made-with starter"}
    )
    row.expect(status_starter == 200, f"the starter answered {status_starter}")
    status_first, first = w1.call(
        "A5",
        "POST",
        "/worlds/generated",
        body={"recipe": A5_RECIPE, "title": "Q10 asked", "values": asked},
    )
    row.expect(
        status_first == 201, f"the asked town answered {status_first} {F.problem_code(first)}"
    )
    if status_first != 201:
        return row.close()
    first_entry = F.read_entry(w1, "A5", first["entry_id"])
    ground = first_entry.get("generated_ground") or {}
    _, listed = w1.call("A5", "GET", "/world-entries")
    listed_ground = (
        next(
            (r.get("generated_ground") for r in listed if r.get("entry_id") == first["entry_id"]),
            None,
        )
        or {}
    )
    for name, found in (("entry", ground), ("list", listed_ground)):
        row.expect(
            found.get("specification") == preset["specification"],
            f"the {name} states specification {found.get('specification')}",
        )
        row.expect(found.get("values") == expected, f"the {name} states other values")
    dropped = dict(expected)
    dropped.pop(next(iter(asked)))
    mutant_fails = ground.get("values") != dropped
    row.expect(mutant_fails, "the values check passed with a key dropped")
    status_second, second = w1.call(
        "A5",
        "POST",
        "/worlds/generated",
        body={
            "recipe": ground.get("recipe_key"),
            "title": "Q10 again",
            "values": ground.get("values"),
        },
    )
    row.expect(status_second == 201, f"the second town answered {status_second}")
    second_ground = (
        (F.read_entry(w1, "A5", second["entry_id"]).get("generated_ground") or {})
        if status_second == 201
        else {}
    )
    row.expect(second_ground.get("values") == expected, "the second town states other values")
    row.expect(
        F.read_entry(w1, "A5", first["entry_id"]) == first_entry,
        "the first town's entry changed when the second was made",
    )
    row.expect(
        F.read_entry(w1, "A5", starter["entry_id"]).get("generated_ground", "absent") is None
        if status_starter == 200
        else False,
        "the starter does not state generated_ground null",
    )
    towns = [first["entry_id"], *([second["entry_id"]] if status_second == 201 else [])]
    stranger = [w2.call("A5", "GET", f"/world-entries/{town}")[0] for town in towns]
    _, theirs = w2.call("A5", "GET", "/world-entries")
    row.expect(stranger == [404] * len(towns), f"the other workspace was answered {stranger}")
    row.expect(
        not {r.get("entry_id") for r in theirs} & set(towns), "the other workspace lists a town"
    )
    row.observed = {
        "catalog_file": catalog_file,
        "specification": preset["specification"],
        "asked": asked,
        "values": ground.get("values"),
        "second_values_equal": second_ground.get("values") == expected,
        "mutant_dropped_key_fails": mutant_fails,
        "stranger": stranger,
    }
    return row.close()


def made_with(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if len(workspace_ids(stack)) < 2:
        raise SystemExit("made-with needs a stack started with --workspaces 2")
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_a5(stack, transcripts, worktree)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- S1: the style pack library over HTTP -------------------------------------------------------------

#: The committed packs as files: S1 reads every manifest and listed file itself (A-64).
STYLE_PACKS = Path("assets") / "style-packs" / "packs"


def canonical_manifest(raw: bytes) -> bytes | None:
    """The bytes a committed manifest is identified and served as: the file, which is its canonical
    JSON and one newline, without that newline (A-67); None for a file not ending in exactly one."""
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        return None
    return raw[:-1]


def committed_packs(worktree: Path) -> list[dict[str, Any]]:
    """Each committed pack: its manifest's bytes and document, and every file it lists, read."""
    packs = []
    for manifest in sorted((worktree / STYLE_PACKS).glob("*/manifest.json")):
        raw = manifest.read_bytes()
        document = json.loads(raw)
        files = [
            {**listed, "data": (manifest.parent / listed["path"]).read_bytes()}
            for listed in document.get("files", [])
        ]
        packs.append({"raw": raw, "document": document, "files": files})
    return packs


def unauthenticated(stack: Stack, path: str) -> int:
    """The status a request with no session is answered with."""
    try:
        with urllib.request.urlopen(f"{stack.base_url}{path}", timeout=60) as response:
            return response.status
    except urllib.error.HTTPError as refused:
        return refused.code


def row_s1(stack: Stack, transcripts: Any, worktree: Path) -> Row:
    row = Row(
        "S1",
        "style_packs.library",
        "GET /world/style-packs lists exactly the committed packs, each with its manifest's id, "
        "version and licence and the SHA-256 of its canonical bytes (the committed file without "
        "its one final newline, A-67), the same for both workspaces; each manifest is served by "
        "that digest as those bytes, as JSON; every "
        "file a manifest lists is served by its digest with the manifest's media type and the "
        "committed bytes; an unknown digest is 404 unknown_reference; no session is 401; a served "
        "content answer is marked immutable.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    committed = committed_packs(worktree)
    row.expect(len(committed) > 0, "no pack is committed")
    status, listing = w1.call("S1", "GET", "/world/style-packs")
    _, theirs = w2.call("S1", "GET", "/world/style-packs")
    row.expect(status == 200, f"the listing answered {status}")
    row.expect(listing == theirs, "the two workspaces were listed different packs")
    listed = {p.get("pack_id"): p for p in (listing.get("packs") or [])}
    expected = {
        pack["document"]["pack_id"]: {
            "version": pack["document"]["version"],
            "manifest_sha256": hashlib.sha256(canonical_manifest(pack["raw"]) or b"").hexdigest(),
            "licence": pack["document"]["licence"]["id"],
        }
        for pack in committed
    }
    row.expect(sorted(listed) == sorted(expected), f"listed {sorted(listed)}")
    for pack_id, wanted in expected.items():
        found = listed.get(pack_id) or {}
        got = {
            "version": found.get("version"),
            "manifest_sha256": found.get("manifest_sha256"),
            "licence": (found.get("licence") or {}).get("id"),
        }
        row.expect(got == wanted, f"{pack_id} is listed as {got}, committed {wanted}")
    served: list[dict[str, Any]] = []
    mutant_fails = None
    for pack in committed:
        canonical = canonical_manifest(pack["raw"])
        row.expect(
            canonical is not None,
            f"{pack['document']['pack_id']}'s manifest does not end in exactly one newline",
        )
        canonical = canonical or pack["raw"]
        digest = hashlib.sha256(canonical).hexdigest()
        status, headers, body = raw_call(stack, "token", "GET", f"/world/style-packs/{digest}")
        # Header names as the server sent them; HTTP reads them without regard to case.
        named = {name.lower(): value for name, value in headers.items()}
        kind = named.get("content-type", "")
        cache = named.get("cache-control", "")
        row.expect(
            status == 200 and body == canonical and kind.startswith("application/json"),
            f"the {pack['document']['pack_id']} manifest answered {status} {kind}",
        )
        row.expect("immutable" in cache, f"a manifest is served with Cache-Control {cache!r}")
        if mutant_fails is None:
            changed = bytes([canonical[0] ^ 1]) + canonical[1:]
            mutant_fails = body != changed
        for listed_file in pack["files"]:
            status, headers, body = raw_call(
                stack, "token", "GET", f"/world/style-packs/{listed_file['sha256']}"
            )
            ok = (
                status == 200
                and body == listed_file["data"]
                and {k.lower(): v for k, v in headers.items()}.get("content-type", "").split(";")[0]
                == listed_file["media_type"]
                and hashlib.sha256(listed_file["data"]).hexdigest() == listed_file["sha256"]
            )
            row.expect(ok, f"{pack['document']['pack_id']} {listed_file['path']} answered {status}")
            served.append({"path": listed_file["path"], "status": status, "equal": ok})
    row.expect(bool(mutant_fails), "the manifest check passed with one byte changed")
    unknown = hashlib.sha256(b"q10 s1 no such pack content").hexdigest()
    status_unknown, _, body_unknown = raw_call(
        stack, "token", "GET", f"/world/style-packs/{unknown}"
    )
    code = (json.loads(body_unknown or b"{}") if status_unknown == 404 else {}).get("code")
    row.expect(
        status_unknown == 404 and code == "unknown_reference",
        f"an unknown digest answered {status_unknown} {code}",
    )
    status_anonymous = unauthenticated(stack, "/world/style-packs")
    row.expect(status_anonymous == 401, f"no session was answered {status_anonymous}")
    row.observed = {
        "packs": expected,
        "files_served": len(served),
        "files_equal": sum(item["equal"] for item in served),
        "unknown": [status_unknown, code],
        "anonymous": status_anonymous,
        "mutant_one_byte_fails": mutant_fails,
    }
    return row.close()


def packs(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if len(workspace_ids(stack)) < 2:
        raise SystemExit("packs needs a stack started with --workspaces 2")
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    s1 = row_s1(stack, transcripts, worktree)
    listing = F.client(stack, transcripts, "w1", "token").call("S2", "GET", "/world/style-packs")[1]
    rows = [
        s1,
        row_s2(stack, transcripts, listing or {}, worktree),
        row_s3(stack, transcripts, listing or {}, worktree),
    ]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


def style_query(entry: Mapping[str, Any]) -> dict[str, str]:
    return {"world_id": entry["world_id"]}


def preview_body(current: Mapping[str, Any], **changes: Any) -> dict[str, Any]:
    """A whole-world appearance proposal over the world's current style, keeping its profile."""
    held = current.get("current") or {}
    # The current style states its whole-world profile as ``global_style``.
    profile = held.get("global_style") or {}
    body = {
        "proposal_id": str(uuid.uuid4()),
        "origin": "settings",
        "origin_reference": "q10-s2",
        "scope": {"kind": "global"},
        "base_style_version_id": held.get("version_id"),
        "base_topology_digest": current.get("current_topology_digest"),
        "profile": {
            "profile_id": profile.get("profile_id"),
            "profile_version": profile.get("profile_version"),
            "parameters": profile.get("parameters") or {},
        },
    }
    body.update(changes)
    return body


#: The committed library document naming the pack a world without a chosen look is made in.
STYLE_LIBRARY = Path("assets") / "style-packs" / "library.v1.json"


def row_s2(stack: Stack, transcripts: Any, listing: Mapping[str, Any], worktree: Path) -> Row:
    row = Row(
        "S2",
        "style_packs.world_binding",
        "The library lists exactly one pack as default, the one the committed library document "
        "names; a generated town is made naming that pack (A-86). On it: a whole-world preview "
        "naming the toon pack as the library lists it "
        "states that pack and writes no version; applying it makes a version naming it, which the "
        "current style reads; rolling back to the base version reads the default pack; the toon pack named "
        "with a digest the library does not hold, and a regional proposal naming a pack, are "
        "refused invalid_style_data and write nothing; the other workspace is answered 404.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    packs = {p.get("pack_id"): p for p in (listing.get("packs") or [])}

    def named(pack_id: str) -> dict[str, Any]:
        found = packs.get(pack_id) or {}
        return {k: found.get(k) for k in ("pack_id", "version", "manifest_sha256")}

    toon, cozy = named("exulanica.toon-town"), named("exulanica.cozy-town")
    committed_default = json.loads((worktree / STYLE_LIBRARY).read_text())["default"]
    listed_default = [p.get("pack_id") for p in listing.get("packs") or [] if p.get("default")]
    default = named(committed_default)
    row.expect(
        listed_default == [committed_default] and default["version"] is not None,
        f"the library lists {listed_default} as default; the committed default is {committed_default}",
    )
    status_town, town = w1.call(
        "S2", "POST", "/worlds/generated", body={"recipe": "small_town", "title": "Q10 S2 town"}
    )
    row.expect(status_town == 201, f"the town answered {status_town} {F.problem_code(town)}")
    if status_town != 201:
        return row.close()
    query = style_query(town)

    def current() -> dict[str, Any]:
        return w1.call("S2", "GET", "/world/styles/current", query=query)[1]

    def versions() -> int:
        return len(w1.call("S2", "GET", "/world/styles/versions", query=query)[1] or [])

    base = current()
    base_id = (base.get("current") or {}).get("version_id")
    made_in = (base.get("current") or {}).get("style_pack")
    row.expect(made_in == default, f"the town was made naming {made_in}, not {default}")
    count = versions()
    status_preview, preview = w1.call(
        "S2",
        "POST",
        "/world/styles/previews",
        query=query,
        body=preview_body(base, style_pack=toon),
    )
    candidate = (preview.get("candidate") or {}).get("style_pack")
    row.expect(
        status_preview == 201 and candidate == toon,
        f"the preview answered {status_preview} {F.problem_code(preview)} naming {candidate}",
    )
    row.expect(versions() == count, "the preview wrote a version")
    status_apply, applied = w1.call(
        "S2",
        "POST",
        f"/world/styles/previews/{preview.get('preview_id')}/apply",
        query=query,
        body={
            "base_style_version_id": base_id,
            "base_topology_digest": base.get("current_topology_digest"),
        },
    )
    after = current()
    row.expect(
        status_apply == 200 and applied.get("style_pack") == toon,
        f"apply answered {status_apply} {F.problem_code(applied)} naming {applied.get('style_pack')}",
    )
    row.expect(
        (after.get("current") or {}).get("style_pack") == toon,
        "the current style names another pack",
    )
    mutant_fails = applied.get("style_pack") != cozy
    row.expect(mutant_fails, "the apply check passed against the cozy pack")
    status_back, back = w1.call(
        "S2",
        "POST",
        "/world/styles/rollback",
        query=query,
        body={
            "base_style_version_id": (after.get("current") or {}).get("version_id"),
            "base_topology_digest": after.get("current_topology_digest"),
            "target_version_id": base_id,
            "origin": "settings",
            "origin_reference": "q10-s2",
        },
    )
    rolled = current()
    row.expect(
        status_back == 200 and (rolled.get("current") or {}).get("style_pack") == default,
        f"rollback answered {status_back} {F.problem_code(back)}; the pack reads "
        f"{(rolled.get('current') or {}).get('style_pack')}",
    )
    count = versions()
    wrong = {**toon, "manifest_sha256": "0" * 64}
    status_wrong, refused = w1.call(
        "S2",
        "POST",
        "/world/styles/previews",
        query=query,
        body=preview_body(rolled, style_pack=wrong),
    )
    row.expect(
        status_wrong == 422
        and F.problem_code(refused) == "invalid_style_data"
        and "exulanica.toon-town" in str(refused.get("detail")),
        f"an unheld digest answered {status_wrong} {F.problem_code(refused)}",
    )
    region = (town.get("generated_ground") or {}).get("region_id") or "region:generated"
    status_region, regional = w1.call(
        "S2",
        "POST",
        "/world/styles/previews",
        query=query,
        body=preview_body(rolled, style_pack=toon, scope={"kind": "region", "region_id": region}),
    )
    row.expect(
        status_region == 422 and F.problem_code(regional) == "invalid_style_data",
        f"a regional proposal naming a pack answered {status_region} {F.problem_code(regional)}",
    )
    row.expect(versions() == count, "a refused preview wrote a version")
    status_stranger, _ = w2.call("S2", "GET", "/world/styles/current", query=query)
    row.expect(status_stranger == 404, f"the other workspace was answered {status_stranger}")
    row.observed = {
        "town": town.get("entry_id"),
        "toon": toon,
        "default": {"committed": committed_default, "listed": listed_default},
        "made_in": made_in,
        "preview": [status_preview, candidate],
        "apply": [status_apply, applied.get("style_pack")],
        "rollback": [status_back, (rolled.get("current") or {}).get("style_pack")],
        "unheld_digest": [status_wrong, F.problem_code(refused)],
        "regional": [status_region, F.problem_code(regional)],
        "stranger": status_stranger,
        "mutant_cozy_fails": mutant_fails,
    }
    return row.close()


#: Every published version of every pack, committed beside the current packs (dbc09bac).
PUBLISHED_PACKS = Path("assets") / "style-packs" / "published.v1.json"
PUBLISHED_DIRECTORY = Path("assets") / "style-packs" / "published"


def row_s3(stack: Stack, transcripts: Any, listing: Mapping[str, Any], worktree: Path) -> Row:
    row = Row(
        "S3",
        "style_packs.earlier_versions",
        "Every published version the committed published list names that is not a pack's current "
        "version is listed among that pack's earlier versions with its digest, and served by that "
        "digest as the committed manifest's canonical bytes; a town made naming an earlier version "
        "is 201 and its current style names that version; a version the library never published is "
        "refused 422 invalid_style_data (A-92).",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    current = {p.get("pack_id"): p for p in listing.get("packs") or []}
    published = json.loads((worktree / PUBLISHED_PACKS).read_text())["versions"]
    earlier = [
        v for v in published if (current.get(v["pack_id"]) or {}).get("version") != v["version"]
    ]
    row.expect(bool(earlier), "the committed list names no earlier version")
    served = []
    for version in earlier:
        pack = current.get(version["pack_id"]) or {}
        listed = {
            (e.get("version"), e.get("manifest_sha256")) for e in pack.get("earlier_versions") or []
        }
        raw = (
            worktree
            / PUBLISHED_DIRECTORY
            / version["pack_id"]
            / str(version["version"])
            / "manifest.json"
        ).read_bytes()
        canonical = canonical_manifest(raw) or raw
        status, _, body = raw_call(
            stack, "token", "GET", f"/world/style-packs/{version['manifest_sha256']}"
        )
        ok = (
            (version["version"], version["manifest_sha256"]) in listed
            and hashlib.sha256(canonical).hexdigest() == version["manifest_sha256"]
            and status == 200
            and body == canonical
        )
        row.expect(ok, f"{version['pack_id']} {version['version']} answered {status}")
        served.append([version["pack_id"], version["version"], status, ok])
    oldest = min(earlier, key=lambda v: (v["pack_id"] != "exulanica.toon-town", v["version"]))
    chosen = {k: oldest[k] for k in ("pack_id", "version", "manifest_sha256")}
    status_town, town = w1.call(
        "S3",
        "POST",
        "/worlds/generated",
        body={"recipe": "small_town", "title": "Q10 S3 town", "style_pack": chosen},
    )
    named = None
    if status_town == 201:
        named = (
            (w1.call("S3", "GET", "/world/styles/current", query=style_query(town))[1] or {}).get(
                "current"
            )
            or {}
        ).get("style_pack")
    row.expect(
        status_town == 201 and named == chosen,
        f"the town in an earlier version answered {status_town} {F.problem_code(town)} naming "
        f"{named}",
    )
    never = {**chosen, "version": 99}
    status_never, refused = w1.call(
        "S3",
        "POST",
        "/worlds/generated",
        body={"recipe": "small_town", "title": "Q10 S3 never", "style_pack": never},
    )
    row.expect(
        status_never == 422 and F.problem_code(refused) == "invalid_style_data",
        f"an unpublished version answered {status_never} {F.problem_code(refused)}",
    )
    row.observed = {
        "earlier": served,
        "town": [status_town, (town or {}).get("entry_id"), chosen, named],
        "unpublished": [status_never, F.problem_code(refused)],
    }
    return row.close()


# -- W1 and W2: a creator's world kind, and a world of a kind ---------------------------------------

#: The repository's farm kind (A-70, A-71): the document W1 uploads under a new key.
FARM_KIND = Path("tests") / "fixtures" / "world-kinds" / "fixture-farm.json"
W1_KIND = "q10_acceptance_farm"
#: The contract's request body limits: an upload's, and a world's of a kind.
KIND_BODY_LIMIT = 131_072
KIND_WORLD_BODY_LIMIT = 16_384


def float_figure(document: Any) -> tuple[Any, bool]:
    """The document with its first integer figure (depth first) written as a float."""
    done = False

    def walk(value: Any) -> Any:
        nonlocal done
        if done:
            return value
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            done = True
            return float(value) + 0.5
        if isinstance(value, dict):
            return {k: walk(v) if k not in ("version",) else v for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    changed = {
        k: (walk(v) if k in ("parameters", "presets", "site", "parts", "zones") else v)
        for k, v in document.items()
    }
    return changed, done


def raw_json(
    stack: Stack, token_file: str, path: str, payload: bytes
) -> tuple[int, dict[str, str], bytes]:
    return raw_call(stack, token_file, "POST", path, body=payload, content_type="application/json")


def row_w1(stack: Stack, transcripts: Any, worktree: Path) -> tuple[Row, dict[str, Any] | None]:
    row = Row(
        "W1",
        "kinds.upload",
        "The repository's farm kind under a new key, uploaded to workspace 1, is kept with origin "
        "uploaded and listed by GET /worlds/kinds for workspace 1 only; the same document again is "
        "409 kind_version_exists; the document with one integer figure written as a float is "
        "refused 422 by name and nothing is kept; a body over 131,072 bytes is 413; the read-only "
        "grant's upload is refused and nothing is kept.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    read_only = F.client(stack, transcripts, "read-only", "token-read")
    # An uploaded kind states its origin as uploaded; the route refuses any other (A-70).
    document = {
        **json.loads((worktree / FARM_KIND).read_text()),
        "kind": W1_KIND,
        "origin": "uploaded",
    }

    def kinds(c: Any) -> list[str]:
        return sorted(
            k.get("kind") for k in (c.call("W1", "GET", "/worlds/kinds")[1] or {}).get("kinds", [])
        )

    before = kinds(w1)
    status_ro, refused_ro = read_only.call(
        "W1", "POST", "/worlds/kinds", body={"document": document}
    )
    row.expect(status_ro in (403, 404), f"the read-only upload answered {status_ro}")
    floated, has_float = float_figure(document)
    status_float, refused_float = w1.call("W1", "POST", "/worlds/kinds", body={"document": floated})
    row.expect(
        has_float and status_float == 422 and F.problem_code(refused_float) is not None,
        f"a float figure answered {status_float} {F.problem_code(refused_float)}",
    )
    row.expect(kinds(w1) == before, "a refused upload kept a kind")
    big = json.dumps({"document": {**document, "summary": "x" * (KIND_BODY_LIMIT + 1)}}).encode()
    status_big, _, _ = raw_json(stack, "token", "/worlds/kinds", big)
    row.expect(status_big == 413, f"a body over the limit answered {status_big}")
    status_kept, kept = w1.call("W1", "POST", "/worlds/kinds", body={"document": document})
    view = kept.get("kind") or {}
    row.expect(
        status_kept in (200, 201)
        and view.get("kind") == W1_KIND
        and view.get("origin") == "uploaded"
        and view.get("source") == "workspace",
        f"the upload answered {status_kept} {F.problem_code(kept)} {view.get('origin')}",
    )
    mine, theirs = kinds(w1), kinds(w2)
    row.expect(W1_KIND in mine and W1_KIND not in theirs, f"listed {mine} and {theirs}")
    status_again, again = w1.call("W1", "POST", "/worlds/kinds", body={"document": document})
    row.expect(
        status_again == 409 and F.problem_code(again) == "kind_version_exists",
        f"the same document again answered {status_again} {F.problem_code(again)}",
    )
    row.observed = {
        "read_only": [status_ro, F.problem_code(refused_ro)],
        "float": [status_float, F.problem_code(refused_float)],
        "too_big": status_big,
        "kept": [status_kept, view.get("kind"), view.get("version"), view.get("origin")],
        "listed": {"w1": mine, "w2": theirs},
        "again": [status_again, F.problem_code(again)],
    }
    return row.close(), (view if status_kept in (200, 201) else None)


def row_w2(
    stack: Stack, transcripts: Any, kept: Mapping[str, Any] | None
) -> tuple[Row, dict[str, Any] | None, dict[str, Any] | None]:
    """W2, and the world of W1's kind with its served drawing, for W3."""
    row = Row(
        "W2",
        "kinds.world",
        "A town made through POST /worlds/kinds/town/worlds and a world of W1's kind are each "
        "saved and listed; the site drawing of W1's kind's world answers with an entity tag equal "
        "to the SHA-256 of its canonical JSON, and the other workspace is answered 404 for it; a "
        "title holding a NUL, and one holding a zero-width space, are 422 invalid_saved_world_entry "
        "and add no entry; a body over 16,384 bytes is 413.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    if kept is None:
        row.blocked_by.append("W1 kept no kind to make a world of")
        return row.close(), None, None
    town_kind = next(
        (
            k
            for k in (w1.call("W2", "GET", "/worlds/kinds")[1] or {}).get("kinds", [])
            if k.get("kind") == "town"
        ),
        {},
    )
    town_preset = ((town_kind.get("presets") or [{}])[0]).get("key")
    status_town, town = w1.call(
        "W2",
        "POST",
        "/worlds/kinds/town/worlds",
        body={"preset": town_preset, "title": "Q10 W2 town"},
    )
    farm_preset = ((kept.get("presets") or [{}])[0]).get("key")
    status_farm, farm = w1.call(
        "W2",
        "POST",
        f"/worlds/kinds/{W1_KIND}/worlds",
        body={"preset": farm_preset, "title": "Q10 W2 farm"},
    )
    listed = {e.get("entry_id") for e in (w1.call("W2", "GET", "/world-entries")[1] or [])}
    row.expect(
        status_town in (200, 201) and town.get("entry_id") in listed,
        f"the town answered {status_town} {F.problem_code(town)}",
    )
    row.expect(
        status_farm in (200, 201) and farm.get("entry_id") in listed,
        f"the farm answered {status_farm} {F.problem_code(farm)}",
    )
    site_path = f"/world/versions/{farm.get('authored_version_id')}/site"
    query = urllib.parse.urlencode({"world_id": farm.get("world_id", "")})
    status_site, headers, body = (None, {}, b"")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status_site, headers, body = raw_call(stack, "token", "GET", f"{site_path}?{query}")
        if status_site != 503:
            break
        time.sleep(3)
    named = {k.lower(): v for k, v in headers.items()}
    tag = named.get("etag", "").strip('"')
    canonical = (
        hashlib.sha256(
            json.dumps(
                json.loads(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
        if status_site == 200
        else None
    )
    row.expect(
        status_site == 200 and tag == canonical, f"the site answered {status_site}, tag {tag[:12]}"
    )
    status_stranger, _, _ = raw_call(stack, "token-2", "GET", f"{site_path}?{query}")
    row.expect(status_stranger == 404, f"the other workspace was answered {status_stranger}")
    before = len(listed)
    titles = {}
    for name, title in (("nul", "Q10 W2\x00farm"), ("zero_width", "Q10 W2​farm")):
        status_title, refused = w1.call(
            "W2",
            "POST",
            f"/worlds/kinds/{W1_KIND}/worlds",
            body={"preset": farm_preset, "title": title},
        )
        titles[name] = [status_title, F.problem_code(refused)]
        row.expect(
            status_title == 422 and F.problem_code(refused) == "invalid_saved_world_entry",
            f"a {name} title answered {status_title} {F.problem_code(refused)}",
        )
    big = json.dumps(
        {"preset": farm_preset, "title": "x" * 150, "values": {"pad": "y" * KIND_WORLD_BODY_LIMIT}}
    ).encode()
    status_big, _, _ = raw_json(stack, "token", f"/worlds/kinds/{W1_KIND}/worlds", big)
    row.expect(status_big == 413, f"a body over the limit answered {status_big}")
    after = len(w1.call("W2", "GET", "/world-entries")[1] or [])
    row.expect(after == before, "a refused world added an entry")
    row.observed = {
        "town": [status_town, town.get("entry_id")],
        "farm": [status_farm, farm.get("entry_id")],
        "site": [status_site, tag, canonical],
        "stranger": status_stranger,
        "titles": titles,
        "too_big": status_big,
    }
    drawing = json.loads(body) if status_site == 200 else None
    farm_entry = F.read_entry(w1, "W2", farm["entry_id"]) if status_farm in (200, 201) else None
    return row.close(), farm_entry, drawing


def kinds(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if len(workspace_ids(stack)) < 2 or not stack.token_file("token-read").exists():
        raise SystemExit("kinds needs a stack started with --workspaces 2 --read-only-token")
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    w1, kept = row_w1(stack, transcripts, worktree)
    w2, farm, drawing = row_w2(stack, transcripts, kept)
    rows = [w1, w2, row_w3(stack, transcripts, farm, drawing)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- W3: people live in a world of a kind -----------------------------------------------------------

#: The society a world of a kind is brought in with, and the input profile its record names (A-73).
SITE_ENGINE = "exulanica-society/v5"
SITE_INPUT_PROFILE = "exulanica.society-input/walking-surfaces-v2"


def inside_site(position: Sequence[int], extent: Mapping[str, Any], shrink: float = 1.0) -> bool:
    """Whether a plan position (east, south) in the region's frame lies inside the site the drawing
    states (x east, y north from its south-west corner, so y is minus south), with its bounds
    shrunk about their centre by ``shrink``."""
    x, y = position[0], -position[1]
    width, depth = extent["widthMm"], extent["depthMm"]
    half_x, half_y = width * shrink / 2, depth * shrink / 2
    return abs(x - width / 2) <= half_x and abs(y - depth / 2) <= half_y


def row_w3(
    stack: Stack, transcripts: Any, farm: Mapping[str, Any] | None, site: Mapping[str, Any] | None
) -> Row:
    row = Row(
        "W3",
        "kinds.people",
        "People brought into W2's world of a kind are placed inside the site its served drawing "
        "states; the society runs the living engine exulanica-society/v5 and its input record "
        "names the walking-surfaces-v2 profile; after one manual step every inhabitant is still "
        "inside the site.",
    )
    if not farm or not site:
        row.blocked_by.append("W2 made no world of a kind with a drawing")
        return row.close()
    w1 = F.client(stack, transcripts, "w1", "token")
    query = F.world_query(farm)
    region = (farm.get("generated_site") or {}).get("region_id")
    status, made = w1.call(
        "W3",
        "POST",
        F.version_path(farm, "/society"),
        query=query,
        body={"region_id": region, "profile": SITE_ENGINE},
    )
    row.expect(status in (200, 201), f"bringing people in answered {status} {F.problem_code(made)}")
    if status not in (200, 201):
        return row.close()
    extent = site.get("extent") or {}
    _, read = F.society(w1, "W3", farm)
    people = (read.get("state") or {}).get("inhabitants") or []
    placed = [p.get("position_mm") for p in people]
    row.expect(read.get("profile") == SITE_ENGINE, f"the society runs {read.get('profile')}")
    status_input, record = w1.call(
        "W3",
        "GET",
        F.version_path(farm, f"/society/inputs/{read.get('input_seq')}"),
        query=query,
    )
    row.expect(
        status_input == 200 and record.get("input_profile") == SITE_INPUT_PROFILE,
        f"the input record answered {status_input} naming {record.get('input_profile')}",
    )
    row.expect(
        len(placed) > 0 and all(p and inside_site(p, extent) for p in placed),
        f"{len(placed)} people, not all inside {extent}",
    )
    mutant_fails = not all(p and inside_site(p, extent, 0.1) for p in placed)
    row.expect(mutant_fails, "the inside check passed with the site shrunk to a tenth")
    status_step, stepped = F.advance(w1, "W3", farm, read)
    _, after = F.society(w1, "W3", farm)
    moved = [p.get("position_mm") for p in (after.get("state") or {}).get("inhabitants") or []]
    row.expect(
        status_step in (200, 201)
        and after.get("current_tick") == (read.get("current_tick") or 0) + 1,
        f"a manual step answered {status_step} {F.problem_code(stepped)}",
    )
    row.expect(
        len(moved) == len(placed) and all(p and inside_site(p, extent) for p in moved),
        "after a step someone is outside the site",
    )
    row.observed = {
        "farm": farm.get("entry_id"),
        "extent": extent,
        "population": len(placed),
        "placed": placed,
        "after_step": moved,
        "engine": read.get("profile"),
        "input_profile": record.get("input_profile"),
        "mutant_tenth_fails": mutant_fails,
    }
    return row.close()


# -- R1: reference notes where an installation does not offer them -------------------------------

#: The contract's four codes for an installation that does not offer web notes (A-72).
REFERENCE_REFUSALS = (
    "references_operator_only",
    "references_not_run_here",
    "reference_budget_unavailable",
    "references_not_configured",
)


def row_r1(stack: Stack, transcripts: Any) -> Row:
    row = Row(
        "R1",
        "references.not_offered",
        "Where web reference notes are not offered: the list holds no request and the capability "
        "is refused with one of the contract's four codes; a valid request is refused 409 with that "
        "code and nothing is queued or written; web false and a 1001-character description are "
        "422; the read-only grant is refused 403; an unknown reference is 404 for its read and its "
        "cancel.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    read_only = F.client(stack, transcripts, "read-only", "token-read")
    status_list, listed = w1.call("R1", "GET", "/worlds/references")
    named = [c for c in REFERENCE_REFUSALS if c in json.dumps(listed.get("capabilities"))]
    row.expect(
        status_list == 200 and listed.get("references") == [] and len(named) == 1,
        f"the list answered {status_list} with codes {named}",
    )
    body = {"purpose": "world_draft", "description": "a quiet harbour town", "web": True}
    before = stack.evidence_digest()
    status_ask, refused = w1.call("R1", "POST", "/worlds/references", body=body)
    after = stack.evidence_digest()
    row.expect(
        status_ask == 409 and named and F.problem_code(refused) == named[0],
        f"a request answered {status_ask} {F.problem_code(refused)}",
    )
    row.expect(before == after, "the refused request wrote to the store or database")
    row.expect(
        (w1.call("R1", "GET", "/worlds/references")[1] or {}).get("references") == [],
        "a request was queued",
    )
    status_web, _ = w1.call("R1", "POST", "/worlds/references", body={**body, "web": False})
    status_long, _ = w1.call(
        "R1", "POST", "/worlds/references", body={**body, "description": "x" * 1001}
    )
    row.expect(
        status_web == 422 and status_long == 422, f"shapes answered {status_web} {status_long}"
    )
    status_ro, _ = read_only.call("R1", "POST", "/worlds/references", body=body)
    row.expect(status_ro == 403, f"the read-only request answered {status_ro}")
    unknown = uuid.uuid4()
    status_read, _ = w1.call("R1", "GET", f"/worlds/references/{unknown}")
    status_cancel, _ = w1.call("R1", "POST", f"/worlds/references/{unknown}/cancel")
    row.expect(
        status_read == 404 and status_cancel == 404,
        f"an unknown reference answered {status_read} and {status_cancel}",
    )
    row.observed = {
        "capability_code": named,
        "request": [status_ask, F.problem_code(refused)],
        "evidence_unchanged": before == after,
        "shapes": [status_web, status_long],
        "read_only": status_ro,
        "unknown": [status_read, status_cancel],
    }
    return row.close()


def row_r2(stack: Stack, transcripts: Any) -> Row:
    row = Row(
        "R2",
        "references.pictures_not_offered",
        "Where a person's pictures are not read for reference notes (the default): the list states "
        "pictures not offered, with a code and at most 4; a request naming a picture is refused "
        "409 with the code the list's pictures.code states and nothing is queued (A-120); a "
        "picture named twice is 422 pictures_repeated; a request asking for neither web notes nor "
        "pictures is 422 nothing_to_look_up (A-103). A-103's constant, "
        "reference_pictures_not_offered, is recorded beside it and not judged.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    status_list, listed = w1.call("R2", "GET", "/worlds/references")
    pictures = (listed or {}).get("pictures") or {}
    row.expect(
        status_list == 200
        and pictures.get("offered") is False
        and bool(pictures.get("code"))
        and pictures.get("maximum") == 4,
        f"the list states pictures {pictures}",
    )
    picture = str(uuid.uuid4())
    base = {"purpose": "world_draft", "description": "a quiet harbour town", "web": True}
    status_one, one = w1.call(
        "R2", "POST", "/worlds/references", body={**base, "pictures": [picture]}
    )
    row.expect(
        status_one == 409 and F.problem_code(one) == pictures.get("code"),
        f"a request naming a picture answered {status_one} {F.problem_code(one)}, the list "
        f"states {pictures.get('code')}",
    )
    row.expect(
        (w1.call("R2", "GET", "/worlds/references")[1] or {}).get("references") == [],
        "a request was queued",
    )
    status_twice, twice = w1.call(
        "R2", "POST", "/worlds/references", body={**base, "pictures": [picture, picture]}
    )
    row.expect(
        status_twice == 422 and F.problem_code(twice) == "pictures_repeated",
        f"a picture named twice answered {status_twice} {F.problem_code(twice)}",
    )
    bare = {"purpose": "world_draft", "description": "a quiet harbour town", "web": False}
    status_bare, nothing = w1.call("R2", "POST", "/worlds/references", body=bare)
    row.expect(
        status_bare == 422 and F.problem_code(nothing) == "nothing_to_look_up",
        f"a request with nothing to look up answered {status_bare} {F.problem_code(nothing)}",
    )
    row.observed = {
        "pictures": pictures,
        "one_picture": [status_one, F.problem_code(one)],
        # A-120: A-103's constant, kept as its own line and not judged.
        "a103_constant_line": F.problem_code(one) == "reference_pictures_not_offered",
        "twice": [status_twice, F.problem_code(twice)],
        "nothing": [status_bare, F.problem_code(nothing)],
    }
    return row.close()


def references(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if not stack.token_file("token-read").exists():
        raise SystemExit("references needs a stack started with --read-only-token")
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_r1(stack, transcripts), row_r2(stack, transcripts)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- T1, T2 and SC1: the thing library, a placed thing, and the demo scene ---------------------------

#: The committed thing library as files (A-77): kinds, looks and the body plans, and where an
#: imported look's container is committed.
THING_CATALOGS = Path("assets") / "catalogs" / "things"
IMPORTED_THINGS = Path("assets") / "things"
#: The shipped kind T2 places, and the demo scene SC1 builds (A-78, A-79).
T2_KIND = {"kind": "sword", "version": 3}
#: The demo scene as the catalog ships it (A-102, A-118): the newest three-strangers version the
#: scene lock ships, profile exulanica.scene/v1, engine v7, a gate.
SCENE_CATALOG = Path("assets") / "catalogs" / "scenes"


def newest_scene(name: str, root: Path = HERE.parents[1]) -> Path:
    """The newest version of ``name`` that the committed scene lock ships."""
    locked = json.loads((root / SCENE_CATALOG / "scenes.lock.json").read_text())["scenes"]
    version = max(int(s["version"]) for s in locked if s["scene"] == name)
    return SCENE_CATALOG / f"{name}.v{version}.json"


DEMO_SCENE = newest_scene("three-strangers")
DEMO_BUILDER = Path("scripts") / "demo" / "build_scene.py"


def canonical_document(raw: bytes) -> bytes:
    """A committed document as the library names it: canonical JSON, keys sorted, no whitespace,
    UTF-8 (A-77)."""
    return json.dumps(
        json.loads(raw), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def committed_things(worktree: Path) -> dict[str, Any]:
    """The committed kinds and looks, each with its canonical bytes and document, the body plans'
    bytes, and every imported container by name."""
    root = worktree / THING_CATALOGS

    def read(folder: str) -> dict[tuple[str, int], dict[str, Any]]:
        found = {}
        for path in sorted((root / folder).glob("*.json")):
            raw = path.read_bytes()
            document = json.loads(raw)
            key = (document.get("kind") or document.get("look"), document.get("version"))
            found[key] = {"canonical": canonical_document(raw), "document": document}
        return found

    return {
        "kinds": read("kinds"),
        "looks": read("looks"),
        "body_plans": (root / "body-plans.v1.json").read_bytes(),
        "imported": {
            path.name: path.read_bytes()
            for path in sorted((worktree / IMPORTED_THINGS).rglob("*.glb"))
        },
    }


def licensed(document: Mapping[str, Any]) -> bool:
    """Whether a document's origin names a licence by SPDX id and verdict, and either a source or
    an authored origin (A-77)."""
    origin = document.get("origin") or {}
    licence = origin.get("licence") or {}
    return (
        bool(licence.get("spdx"))
        and bool(licence.get("verdict"))
        and (origin.get("class") == "authored" or bool(origin.get("sources")))
    )


def row_t1(stack: Stack, transcripts: Any, worktree: Path) -> Row:
    row = Row(
        "T1",
        "things.library",
        "GET /things/library lists exactly the committed kinds and looks by id, version and the "
        "SHA-256 of their canonical JSON, the same for both workspaces; each is served by that "
        "digest as those bytes, the body plans as their file, every look's container at the digest "
        "it pins (an imported one equal to its committed file), marked immutable; an unknown digest "
        "is 404 unknown_reference; no session is 401; every kind and look names its licence and a "
        "source or an authored origin; the KayKit knight and sword are imported, CC0-1.0, by Kay "
        "Lousberg.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    committed = committed_things(worktree)
    status, listing = w1.call("T1", "GET", "/things/library")
    _, theirs = w2.call("T1", "GET", "/things/library")
    row.expect(status == 200 and listing == theirs, f"the listing answered {status}, or differs")

    def keyed(entries: Any, name: str) -> dict[tuple[str, int], str]:
        return {(e.get(name), e.get("version")): e.get("sha256") for e in entries or []}

    for folder, name in (("kinds", "kind"), ("looks", "look")):
        listed = keyed(listing.get(folder), name)
        wanted = {
            key: hashlib.sha256(item["canonical"]).hexdigest()
            for key, item in committed[folder].items()
        }
        row.expect(listed == wanted, f"the {folder} listed differ from the committed ones")
    served: list[dict[str, Any]] = []

    def fetch(digest: str) -> tuple[int, str, str, bytes]:
        status_item, headers, body = raw_call(stack, "token", "GET", f"/things/library/{digest}")
        named = {k.lower(): v for k, v in headers.items()}
        return (
            status_item,
            named.get("content-type", "").split(";")[0],
            named.get("cache-control", ""),
            body,
        )

    for folder in ("kinds", "looks"):
        for key, item in committed[folder].items():
            digest = hashlib.sha256(item["canonical"]).hexdigest()
            got, kind, cache, body = fetch(digest)
            ok = got == 200 and body == item["canonical"] and "immutable" in cache
            row.expect(ok, f"{folder} {key} answered {got}")
            row.expect(licensed(item["document"]), f"{folder} {key} names no licence and source")
            served.append({"item": f"{folder} {key}", "status": got, "equal": ok})
    plans = hashlib.sha256(committed["body_plans"]).hexdigest()
    got, _, _, body = fetch(plans)
    row.expect(
        got == 200
        and body == committed["body_plans"]
        and (listing.get("body_plans") or {}).get("sha256") == plans,
        f"the body plans answered {got}",
    )
    containers = 0
    mutant_fails = None
    for key, item in committed["looks"].items():
        container = item["document"].get("container")
        if not container:
            continue
        containers += 1
        got, kind, _, body = fetch(container["sha256"])
        row.expect(
            got == 200
            and kind == "model/gltf-binary"
            and hashlib.sha256(body).hexdigest() == container["sha256"],
            f"look {key}'s container answered {got} {kind}",
        )
        if item["document"].get("origin", {}).get("class") == "imported":
            files = [
                data
                for data in committed["imported"].values()
                if hashlib.sha256(data).hexdigest() == container["sha256"]
            ]
            row.expect(
                len(files) == 1 and body == files[0],
                f"look {key}'s container is not its committed file",
            )
            if mutant_fails is None and files:
                mutant_fails = body != bytes([files[0][0] ^ 1]) + files[0][1:]
    row.expect(bool(mutant_fails), "the container check passed with one byte changed")
    for name in ("kaykit-knight", "kaykit-sword"):
        document = (committed["looks"].get((name, 1)) or {}).get("document") or {}
        origin = document.get("origin") or {}
        row.expect(
            origin.get("class") == "imported"
            and (origin.get("licence") or {}).get("spdx") == "CC0-1.0"
            and "Kay Lousberg" in (origin.get("authors") or []),
            f"{name} states origin {origin.get('class')} {(origin.get('licence') or {}).get('spdx')}",
        )
    unknown = hashlib.sha256(b"q10 t1 no such thing").hexdigest()
    got, _, _, body = fetch(unknown)
    code = (json.loads(body or b"{}") if got == 404 else {}).get("code")
    row.expect(
        got == 404 and code == "unknown_reference", f"an unknown digest answered {got} {code}"
    )
    anonymous = unauthenticated(stack, "/things/library")
    row.expect(anonymous == 401, f"no session was answered {anonymous}")
    row.observed = {
        "kinds": len(committed["kinds"]),
        "looks": len(committed["looks"]),
        "served": len(served),
        "served_equal": sum(item["equal"] for item in served),
        "containers": containers,
        "unknown": [got, code],
        "anonymous": anonymous,
        "mutant_one_byte_fails": mutant_fails,
    }
    return row.close()


def thing_pose(where: str) -> dict[str, int]:
    x, y, z = F.PLACES[where]
    return {"x_mm": x, "y_mm": y, "z_mm": z, "yaw_microradians": 0}


def saved_entry_binding(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entry_id": entry["entry_id"],
        "base_revision": entry["revision"],
        "authored_state_sha256": entry["authored_state_sha256"],
        "authored_edit_seq": entry["authored_edit_seq"],
    }


def placed(version: Mapping[str, Any], thing_id: str) -> dict[str, Any] | None:
    return next((t for t in version.get("things") or [] if t.get("thing_id") == thing_id), None)


def stands(thing: Mapping[str, Any] | None, pose: Mapping[str, int] | None) -> bool:
    """Whether a placed thing stands at a pose: the stored transform's four figures equal the
    pose's, at the kind's own size (A-78)."""
    transform = (thing or {}).get("transform") or {}
    return (
        pose is not None
        and all(
            transform.get(k) == pose.get(k) for k in ("x_mm", "y_mm", "z_mm", "yaw_microradians")
        )
        and transform.get("scale_milli") == 1000
    )


def row_t2(stack: Stack, transcripts: Any) -> Row:
    row = Row(
        "T2",
        "things.placed",
        "The shipped sword kind placed in the starter's authored version with the saved entry's "
        "binding is 201 and reads back under its id with its kind and pose; move, remove and undo "
        "each answer with a version showing it; the same id again is 409 invalid_object_state; a "
        "pose with a scale is refused 422; a stale base is 409 stale_object_base; "
        "the other workspace is 404; no refusal writes anything.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    status_starter, entry = starter(w1, "T2", "Q10 T2 starter")
    row.expect(status_starter == 200, f"the starter answered {status_starter}")
    if status_starter != 200:
        return row.close()
    query = F.world_query(entry)
    things = F.version_path(entry, "/things")
    base = entry["authored_state_sha256"]
    pose = thing_pose("bench")
    body = {
        "base_state_sha256": base,
        "saved_entry": saved_entry_binding(entry),
        "thing_id": "q10-sword",
        "kind": T2_KIND,
        "region_id": F.STARTER_REGION,
        "pose": pose,
        "origin_role": "fictional",
    }
    status_place, version = w1.call("T2", "POST", things, query=query, body=body)
    found = placed(version, "q10-sword") or {}
    row.expect(status_place == 201, f"placing answered {status_place} {F.problem_code(version)}")
    _, read = w1.call("T2", "GET", F.version_path(entry), query=query)
    stored = placed(read, "q10-sword") or {}
    row.expect(
        stored.get("kind", {}).get("kind") == "sword"
        and stored.get("kind", {}).get("version") == 3
        and stands(stored, pose)
        and stored.get("removed") is False,
        f"the version reads {stored}",
    )
    state = read.get("state_sha256")

    def refused(name: str, change: Mapping[str, Any], status: int, code: str | None) -> None:
        before = w1.call("T2", "GET", F.version_path(entry), query=query)[1].get("state_sha256")
        got, answer = w1.call("T2", "POST", things, query=query, body={**body, **change})
        after = w1.call("T2", "GET", F.version_path(entry), query=query)[1].get("state_sha256")
        row.expect(
            got == status and F.problem_code(answer) == code and before == after,
            f"{name} answered {got} {F.problem_code(answer)}",
        )
        refusals[name] = [got, F.problem_code(answer)]

    refusals: dict[str, Any] = {}
    refused(
        "same id", {"base_state_sha256": state, "saved_entry": None}, 409, "invalid_object_state"
    )
    refused(
        "scale",
        {
            "thing_id": "q10-sword-2",
            "base_state_sha256": state,
            "saved_entry": None,
            "pose": {**pose, "scale_milli": 2000},
        },
        422,
        None,
    )
    refused(
        "stale base", {"thing_id": "q10-sword-3", "saved_entry": None}, 409, "stale_object_base"
    )
    moved_pose = thing_pose("stall")
    status_move, moved = w1.call(
        "T2",
        "POST",
        f"{things}/q10-sword/move",
        query=query,
        body={"base_state_sha256": state, "pose": moved_pose},
    )
    row.expect(
        status_move == 200 and stands(placed(moved, "q10-sword"), moved_pose),
        f"moving answered {status_move} {F.problem_code(moved)}",
    )
    status_remove, removed = w1.call(
        "T2",
        "POST",
        f"{things}/q10-sword/remove",
        query=query,
        body={"base_state_sha256": moved.get("state_sha256")},
    )
    row.expect(
        status_remove == 200 and (placed(removed, "q10-sword") or {}).get("removed") is True,
        f"removing answered {status_remove} {F.problem_code(removed)}",
    )
    status_undo, undone = w1.call(
        "T2",
        "POST",
        f"{things}/undo",
        query=query,
        body={"base_state_sha256": removed.get("state_sha256")},
    )
    row.expect(
        status_undo == 200 and (placed(undone, "q10-sword") or {}).get("removed") is False,
        f"undo answered {status_undo} {F.problem_code(undone)}",
    )
    status_stranger, _ = w2.call("T2", "GET", F.version_path(entry), query=query)
    row.expect(status_stranger == 404, f"the other workspace was answered {status_stranger}")
    row.observed = {
        "placed": [status_place, found.get("thing_id")],
        "stored": stored,
        "schema_version": read.get("schema_version"),
        "refusals": refusals,
        "move": status_move,
        "remove": status_remove,
        "undo": status_undo,
        "stranger": status_stranger,
    }
    return row.close()


def build_scene(
    stack: Stack,
    worktree: Path,
    record: Path,
    *,
    token_file: str = "token-2",
    minds: bool = False,
) -> subprocess.CompletedProcess[str]:
    """The demo scene builder, as a workspace's account runs it (workspace 2's unless named); the
    token is handed to it in its environment only (A-79)."""
    return subprocess.run(
        [
            str(worktree / ".venv" / "bin" / "python"),
            str(worktree / DEMO_BUILDER),
            str(worktree / DEMO_SCENE),
            "--base-url",
            stack.base_url,
            "--record",
            str(record),
            *(["--minds"] if minds else []),
        ],
        cwd=worktree,
        env={
            **LAUNCH.clean_environment(),
            "EXULANICA_TOKEN": stack.token_file(token_file).read_text().strip(),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )


def row_sc1(stack: Stack, transcripts: Any, worktree: Path, out: Path) -> Row:
    row = Row(
        "SC1",
        "demo.scene_built",
        "build_scene.py with the three-strangers scene, as workspace 2, writes its record; the "
        "record's entry, version, state digest and edit sequence equal the entry's; every thing the "
        "scene names is in that version with the kind the scene states and the pose the record "
        "states; a second run adds nothing and names the same version; the entry reopened reads it.",
    )
    w2 = F.client(stack, transcripts, "w2", "token-2")
    scene = json.loads((worktree / DEMO_SCENE).read_text())
    first, second = out / "evidence" / "scene-build-1.json", out / "evidence" / "scene-build-2.json"
    run_one = build_scene(stack, worktree, first)
    (out / "evidence" / "scene-build-1.txt").write_text(run_one.stdout + run_one.stderr)
    row.expect(
        run_one.returncode == 0 and first.exists(), f"the builder exited {run_one.returncode}"
    )
    if not first.exists():
        return row.close()
    record = json.loads(first.read_text())
    entry = F.read_entry(w2, "SC1", record["entry_id"])
    row.expect(
        (
            entry.get("authored_version_id"),
            entry.get("authored_state_sha256"),
            entry.get("authored_edit_seq"),
        )
        == (record.get("version_id"), record.get("state_sha256"), record.get("edit_seq")),
        "the record differs from the entry",
    )
    _, version = w2.call("SC1", "GET", F.version_path(entry), query=F.world_query(entry))
    recorded = {t["thing_id"]: t for t in record.get("things") or []}
    for wanted in scene.get("things") or []:
        stored = placed(version, wanted["thing_id"]) or {}
        kind = stored.get("kind") or {}
        row.expect(
            (kind.get("kind"), kind.get("version"))
            == (wanted["kind"]["kind"], wanted["kind"]["version"])
            and stands(stored, (recorded.get(wanted["thing_id"]) or {}).get("pose")),
            f"{wanted['thing_id']} reads {kind} at {stored.get('transform')}",
        )
    run_two = build_scene(stack, worktree, second)
    (out / "evidence" / "scene-build-2.txt").write_text(run_two.stdout + run_two.stderr)
    again = json.loads(second.read_text()) if second.exists() else {}
    row.expect(
        run_two.returncode == 0
        and again.get("things_added") == 0
        and again.get("version_id") == record.get("version_id"),
        f"a second run exited {run_two.returncode} adding {again.get('things_added')}",
    )
    reopened = F.read_entry(w2, "SC1", record["entry_id"])
    row.expect(
        reopened.get("authored_version_id") == record.get("version_id"),
        "the entry reopened reads another version",
    )
    row.observed = {
        "scene": record.get("scene"),
        "entry_id": record.get("entry_id"),
        "version_id": record.get("version_id"),
        "things": sorted(recorded),
        "things_added": [record.get("things_added"), again.get("things_added")],
    }
    return row.close()


LOOK_CHOICES = "exulanica.thing-look-choices/v1"


#: The catalog scene laid out for a generated town (2160898c), dressed into a town named by --entry.
TOWN_SCENE = Path("assets") / "catalogs" / "scenes" / "three-strangers-in-town.v1.json"


def run_builder(
    stack: Stack, worktree: Path, scene: Path, record: Path, *extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(worktree / ".venv" / "bin" / "python"),
            str(worktree / DEMO_BUILDER),
            str(worktree / scene),
            "--base-url",
            stack.base_url,
            "--record",
            str(record),
            *extra,
        ],
        cwd=worktree,
        env={
            **LAUNCH.clean_environment(),
            "EXULANICA_TOKEN": stack.token_file("token-2").read_text().strip(),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )


def row_sc2(stack: Stack, transcripts: Any, worktree: Path, out: Path) -> Row:
    row = Row(
        "SC2",
        "demo.scene_in_a_town",
        "The catalog scene laid out for a town (three-strangers-in-town v1) is dressed by "
        "build_scene.py into a small town workspace 2 makes through Create a world (A-115): without "
        "--entry the builder refuses and places nothing; with --entry every thing the scene names "
        "stands in the town's version with the kind the scene states and the pose the record "
        "states; a second build adds nothing. No society is started (none is offered on a town's "
        "ground here; root's note).",
    )
    w2 = F.client(stack, transcripts, "w2", "token-2")
    scene = json.loads((worktree / TOWN_SCENE).read_text())
    status_town, town = w2.call(
        "SC2", "POST", "/worlds/generated", body={"recipe": "small_town", "title": "Q10 SC2 town"}
    )
    row.expect(status_town == 201, f"the town answered {status_town} {F.problem_code(town)}")
    if status_town != 201:
        return row.close()
    bare = run_builder(stack, worktree, TOWN_SCENE, out / "evidence" / "sc2-no-entry.json")
    (out / "evidence" / "sc2-no-entry.txt").write_text(bare.stdout + bare.stderr)
    row.expect(
        bare.returncode != 0 and "--entry" in (bare.stdout + bare.stderr),
        f"without --entry the builder exited {bare.returncode}",
    )
    first_record = out / "evidence" / "sc2-build-1.json"
    first = run_builder(stack, worktree, TOWN_SCENE, first_record, "--entry", town["entry_id"])
    (out / "evidence" / "sc2-build-1.txt").write_text(first.stdout + first.stderr)
    row.expect(
        first.returncode == 0 and first_record.exists(), f"the build exited {first.returncode}"
    )
    if not first_record.exists():
        return row.close()
    record = json.loads(first_record.read_text())
    entry = F.read_entry(w2, "SC2", town["entry_id"])
    _, version = w2.call("SC2", "GET", F.version_path(entry), query=F.world_query(entry))
    recorded = {t["thing_id"]: t for t in record.get("things") or []}
    for wanted in scene.get("things") or []:
        stored = placed(version, wanted["thing_id"]) or {}
        kind = stored.get("kind") or {}
        row.expect(
            (kind.get("kind"), kind.get("version"))
            == (wanted["kind"]["kind"], wanted["kind"]["version"])
            and stands(stored, (recorded.get(wanted["thing_id"]) or {}).get("pose")),
            f"{wanted['thing_id']} reads {kind} at {stored.get('transform')}",
        )
    second_record = out / "evidence" / "sc2-build-2.json"
    second = run_builder(stack, worktree, TOWN_SCENE, second_record, "--entry", town["entry_id"])
    (out / "evidence" / "sc2-build-2.txt").write_text(second.stdout + second.stderr)
    again = json.loads(second_record.read_text()) if second_record.exists() else {}
    row.expect(
        second.returncode == 0 and again.get("things_added") == 0,
        f"a second build exited {second.returncode} adding {again.get('things_added')}",
    )
    row.observed = {
        "scene": record.get("scene"),
        "town": town.get("entry_id"),
        "no_entry_exit": bare.returncode,
        "things": sorted(recorded),
        "things_added": [record.get("things_added"), again.get("things_added")],
    }
    return row.close()


def row_s4(stack: Stack, transcripts: Any) -> Row:
    row = Row(
        "S4",
        "things.workspace_store",
        "A workspace's own looks and kinds are read only by digest within that workspace: a look, "
        "its container and a kind for a digest no workspace holds are each 404 unknown_reference "
        "(A-106). An admitted look read by its own workspace and refused to another is not "
        "exercised: no committed look document and container are named by a declared mapping.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    digest = hashlib.sha256(f"q10-s4-{uuid.uuid4()}".encode()).hexdigest()
    answers = {}
    for path in (
        f"/things/looks/{digest}",
        f"/things/looks/{digest}/container",
        f"/things/kinds/{digest}",
    ):
        status, body = w1.call("S4", "GET", path)
        answers[path.replace(digest, "{digest}")] = [status, F.problem_code(body)]
        row.expect(
            status == 404 and F.problem_code(body) == "unknown_reference",
            f"{path.replace(digest, '{digest}')} answered {status} {F.problem_code(body)}",
        )
    row.observed = {"answers": answers}
    return row.close()


def scene_entry(c: Any, step: str, built: Mapping[str, Any]) -> dict[str, Any] | None:
    """The saved world a scene build recorded, read back, or None when the build left none."""
    return F.read_entry(c, step, built["entry_id"]) if built.get("entry_id") else None


def row_t3(stack: Stack, transcripts: Any, built: Mapping[str, Any]) -> Row:
    row = Row(
        "T3",
        "things.looks_worn",
        "On SC1's scene version: GET .../thing-looks answers 200 with profile "
        f"{LOOK_CHOICES}, the version's id and no choice (looks are written by a visitor's "
        "crossing, and the scene's things were placed by its owner, so each wears its kind's first "
        "look), never stored by a cache; another workspace and an unknown version are 404 (A-93).",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    entry = scene_entry(w2, "T3", built)
    row.expect(entry is not None, "SC1 left no scene to read")
    if entry is None:
        return row.close()
    path = F.version_path(entry, "/thing-looks")
    query = F.world_query(entry)
    status, read = w2.call("T3", "GET", path, query=query)
    row.expect(
        status == 200
        and (read or {}).get("profile") == LOOK_CHOICES
        and (read or {}).get("version_id") == entry["authored_version_id"]
        and (read or {}).get("looks") == [],
        f"the looks read answered {status} {read}",
    )
    raw_status, headers, _ = raw_call(
        stack, "token-2", "GET", f"{path}?{urllib.parse.urlencode(query)}"
    )
    cache = {k.lower(): v for k, v in headers.items()}.get("cache-control", "")
    row.expect(raw_status == 200 and "no-store" in cache, f"Cache-Control {cache!r}")
    status_stranger, _ = w1.call("T3", "GET", path, query=query)
    row.expect(status_stranger == 404, f"another workspace was answered {status_stranger}")
    unknown = f"/world/versions/{uuid.uuid4()}/thing-looks"
    status_unknown, _ = w2.call("T3", "GET", unknown, query=query)
    row.expect(status_unknown == 404, f"an unknown version was answered {status_unknown}")
    row.observed = {
        "read": [status, (read or {}).get("profile"), (read or {}).get("looks")],
        "cache_control": cache,
        "stranger": status_stranger,
        "unknown": status_unknown,
    }
    return row.close()


#: The engine of a society of things, as the demo scene names it.
THINGS_ENGINE = "exulanica-society/v7"


def row_t4a(stack: Stack, transcripts: Any, built: Mapping[str, Any], worktree: Path) -> Row:
    row = Row(
        "T4a",
        "things.society_not_offered",
        f"On a host that does not offer the society of things, starting a {THINGS_ENGINE} society "
        "on SC1's scene version is refused 409 society_engine_not_offered and starts nothing "
        "(A-94).",
    )
    w2 = F.client(stack, transcripts, "w2", "token-2")
    entry = scene_entry(w2, "T4a", built)
    row.expect(entry is not None, "SC1 left no scene to start a society on")
    if entry is None or stack.state.get("society_of_things"):
        if stack.state.get("society_of_things"):
            row.blocked_by.append("this stack offers the society of things")
        return row.close()
    scene = json.loads((worktree / DEMO_SCENE).read_text())
    row.expect(scene.get("engine") == THINGS_ENGINE, f"the scene names {scene.get('engine')}")
    status, refused = w2.call(
        "T4a",
        "POST",
        F.version_path(entry, "/society"),
        query=F.world_query(entry),
        body={"region_id": F.STARTER_REGION, "profile": THINGS_ENGINE},
    )
    row.expect(
        status == 409 and F.problem_code(refused) == "society_engine_not_offered",
        f"the society of things answered {status} {F.problem_code(refused)}",
    )
    status_read, _ = F.society(w2, "T4a", entry)
    row.expect(status_read == 404, f"after the refusal the society read answered {status_read}")
    row.observed = {"start": [status, F.problem_code(refused)], "read_after": status_read}
    return row.close()


def row_t4(stack: Stack, transcripts: Any, worktree: Path, out: Path) -> Row:
    row = Row(
        "T4",
        "things.society_lives",
        f"On a host offering the society of things (a fresh database): the demo scene built as "
        f"workspace 1 and a {THINGS_ENGINE} society started on its version in the arrival's "
        "region; the society runs that engine and counts every scene being that has a mind among "
        "its people, placed; a step advances it; its replay answers the live state; the scene's "
        "own --minds step chooses each being's model and reads them back (A-89, A-94, A-102).",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    scene = json.loads((worktree / DEMO_SCENE).read_text())
    record_path = out / "evidence" / "t4-scene-build.json"
    built = build_scene(stack, worktree, record_path, token_file="token")
    (out / "evidence" / "t4-scene-build.txt").write_text(built.stdout + built.stderr)
    row.expect(
        built.returncode == 0 and record_path.exists(), f"the build exited {built.returncode}"
    )
    if not record_path.exists():
        return row.close()
    record = json.loads(record_path.read_text())
    entry = F.read_entry(w1, "T4", record["entry_id"])
    status, society = w1.call(
        "T4",
        "POST",
        F.version_path(entry, "/society"),
        query=F.world_query(entry),
        body={"region_id": record["arrival"]["region_id"], "profile": THINGS_ENGINE},
    )
    society = society if isinstance(society, dict) else {}
    placed_people = {
        p.get("placed_id")
        for p in (society.get("state") or {}).get("inhabitants") or []
        if p.get("came_by") == "placed"
    }
    beings = {m["thing_id"] for m in scene.get("minds") or []}
    row.expect(
        status in (200, 201) and society.get("profile") == THINGS_ENGINE,
        f"the society answered {status} {F.problem_code(society)} running {society.get('profile')}",
    )
    row.expect(
        beings and beings <= placed_people,
        f"the society's placed people are {sorted(placed_people)}, the scene's beings {sorted(beings)}",
    )
    status_step, stepped = F.advance(w1, "T4", entry, society) if society else (None, {})
    stepped = stepped if isinstance(stepped, dict) else {}
    row.expect(
        status_step == 200 and stepped.get("current_tick", -1) > society.get("current_tick", 0),
        f"a step answered {status_step} {F.problem_code(stepped)}",
    )
    _, live = F.society(w1, "T4", entry)
    status_replay, replayed = w1.call(
        "T4", "GET", F.version_path(entry, "/society/replay"), query=F.world_query(entry)
    )
    row.expect(
        status_replay == 200
        and (replayed or {}).get("state_sha256") == (live or {}).get("state_sha256"),
        f"the replay answered {status_replay} with another state",
    )
    minds_record = out / "evidence" / "t4-scene-minds.json"
    minds = build_scene(stack, worktree, minds_record, token_file="token", minds=True)
    (out / "evidence" / "t4-scene-minds.txt").write_text(minds.stdout + minds.stderr)
    # The catalog scene's minds are all models a being is offered (A-102): each is chosen and read
    # back by the builder, at no cost (choosing asks no model).
    lived = json.loads(minds_record.read_text()).get("society") if minds_record.exists() else None
    chosen = {m.get("thing_id") for m in (lived or {}).get("minds") or []}
    row.expect(
        minds.returncode == 0 and chosen == beings,
        f"the scene's minds step exited {minds.returncode} choosing for {sorted(chosen)}",
    )
    row.observed = {
        "scene": record.get("scene"),
        "society": [status, society.get("profile"), society.get("society_id")],
        "placed_people": sorted(placed_people),
        "beings": sorted(beings),
        "step": [status_step, society.get("current_tick"), stepped.get("current_tick")],
        "replay": status_replay,
        "minds_observed": {
            "exit": minds.returncode,
            "said": (minds.stdout + minds.stderr).strip().splitlines()[-3:],
        },
    }
    return row.close()


# -- V2, V3: a visitor crosses in through the door and leaves; DF1: privileged functions ------------

#: The Luanti bridge as shipped: its gate mod's adapter and mapping, and the stand-in that drives one
#: crossing exactly as the mod does (bridges/luanti/tools/cross_once.py).
LUANTI = Path("bridges") / "luanti"
LUANTI_MOD = LUANTI / "mod" / "exulanica_gate"
LUANTI_MAPPING = LUANTI_MOD / "mapping" / "luanti-minetest-game.v2.json"
LUANTI_STANDIN = LUANTI / "tools" / "cross_once.py"
#: What the mapping admits and carries both ways, and a look it names that is not shipped.
CROSSING_TYPE, CROSSING_LOOK, CROSSING_ITEM = "player", "cc0-traveller", "default:torch"
UNSHIPPED_LOOK = "default-skin"
CROSSING_FRAME_SECONDS = 60


def luanti_hello(worktree: Path) -> bytes:
    """The hello the gate mod sends: its adapter's version, the mapping file's own text, and the
    adapter's reads with every mapped item's."""
    adapter = json.loads((worktree / LUANTI_MOD / "adapter.json").read_text())
    text = (worktree / LUANTI_MAPPING).read_text()
    mapping = json.loads(text)
    reads = list(adapter["reads"]) + [item["game_item"] for item in mapping["items"]]
    return (
        '{"adapter_version":'
        + json.dumps(adapter["adapter_version"])
        + ',"mapping":'
        + text
        + ',"reads":'
        + json.dumps(reads)
        + "}"
    ).encode()


def channel(
    stack: Stack,
    credential: str,
    method: str,
    path: str,
    body: Any = None,
    *,
    raw: bytes | None = None,
) -> tuple[int, Any]:
    """A request on a grant's channel, its body as JSON or as the bytes given."""
    if raw is None:
        return door_call(stack, credential, method, path, body)
    request = urllib.request.Request(
        f"{stack.base_url}{path}",
        data=raw,
        method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {credential}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as refused:
        try:
            return refused.code, json.loads(refused.read() or b"null")
        except ValueError:
            return refused.code, None


def frames_until(
    stack: Stack, credential: str, cursor: str, wanted: Callable[[Mapping[str, Any]], bool]
) -> tuple[str, list[dict[str, Any]], int]:
    """Read the channel's frames after ``cursor`` until one is ``wanted`` or the bound passes; the
    cursor after them, every frame read, and the last status."""
    seen: list[dict[str, Any]] = []
    status = 0
    deadline = time.monotonic() + CROSSING_FRAME_SECONDS
    while time.monotonic() < deadline:
        status, read = door_call(
            stack,
            credential,
            "GET",
            f"/door/channel/frames?{urllib.parse.urlencode({'after': cursor})}",
        )
        if status != 200:
            break
        cursor = (read or {}).get("cursor", cursor)
        seen += (read or {}).get("frames") or []
        if any(wanted(frame) for frame in seen):
            break
    return cursor, seen, status


def step(c: Any, label: str, entry: Mapping[str, Any]) -> int:
    """One minute of the society, stepped by its owner."""
    _, now = F.society(c, label, entry)
    return F.advance(c, label, entry, now or {})[0]


def row_v2(stack: Stack, transcripts: Any, worktree: Path, out: Path) -> Row:
    row = Row(
        "V2",
        "door.crossing",
        "A visitor crosses in through the scene's gate and leaves (A-104): the grant 201 and its "
        "hello 200 (an arrival before the hello 409 hello_first); a non-random arrival id 422 "
        "(refused by the request's schema); a look not shipped 422 look_not_shipped; the arrival 201 and again "
        "200 alike; another over the maximum 409 visitors_full; after a step the frames say "
        "arrived, the society holds the visitor (came_by crossed) with the torch it carried, the "
        "models view names it outside and the thing-looks read its look chosen by its crossing; "
        "gone 202; send-away 202 and after a step departed sent_home carrying the torch, which the "
        "world then no longer holds (A-130); a delivery "
        "naming another thing 422 delivery_not_this_departure, the right one 202 recorded and again "
        "not recorded; the revoke then a step gives grant_ended and the next poll 410; the replay "
        "answers the live state; another workspace 404; read-only 403.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    read_only = F.client(stack, transcripts, "read-only", "token-read")
    record_path = out / "evidence" / "v2-scene-build.json"
    built = build_scene(stack, worktree, record_path, token_file="token")
    (out / "evidence" / "v2-scene-build.txt").write_text(built.stdout + built.stderr)
    row.expect(
        built.returncode == 0 and record_path.exists(), f"the scene build exited {built.returncode}"
    )
    if not record_path.exists():
        return row.close()
    record = json.loads(record_path.read_text())
    entry = F.read_entry(w1, "V2", record["entry_id"])
    query = F.world_query(entry)
    status_society, _ = w1.call(
        "V2",
        "POST",
        F.version_path(entry, "/society"),
        query=query,
        body={"region_id": record["arrival"]["region_id"], "profile": THINGS_ENGINE},
    )
    gate = next(t["thing_id"] for t in record["things"] if t["kind"]["kind"] == "gate")
    grant_body = {
        "idempotency_key": str(uuid.uuid4()),
        "bridge": "luanti",
        "version_id": entry["authored_version_id"],
        "minutes": 60,
        "channel_credential": True,
        "visitors_maximum": 1,
        "kinds": [CROSSING_TYPE],
        "gate": gate,
        "may_carry_in": True,
        "may_carry_out": True,
    }
    status_ro, _ = read_only.call("V2", "POST", "/door/grants", query=query, body=grant_body)
    status_grant, granted = w1.call("V2", "POST", "/door/grants", query=query, body=grant_body)
    grant_id = ((granted or {}).get("grant") or {}).get("grant_id")
    credential = ((granted or {}).get("channel_credential") or {}).get("credential")
    row.expect(
        status_society == 200 and status_grant == 201 and credential,
        f"the society answered {status_society}, the grant {status_grant}",
    )
    row.expect(status_ro == 403, f"read-only issuing answered {status_ro}")
    if not credential:
        return row.close()
    arrival = lambda arrival_id, look=CROSSING_LOOK, carried=True: {  # noqa: E731
        "arrival_id": arrival_id,
        "game_type": CROSSING_TYPE,
        "look_key": look,
        "carried": [{"game_item": CROSSING_ITEM, "count": 1}] if carried else [],
    }
    status_early, early = channel(
        stack, credential, "POST", "/door/channel/arrivals", arrival(str(uuid.uuid4()))
    )
    status_hello, said = channel(
        stack, credential, "POST", "/door/channel/hello", raw=luanti_hello(worktree)
    )
    cursor = (said or {}).get("cursor") or ""
    status_fixed, fixed = channel(
        stack,
        credential,
        "POST",
        "/door/channel/arrivals",
        arrival(str(uuid.uuid5(uuid.NAMESPACE_URL, "q10"))),
    )
    status_unshipped, unshipped = channel(
        stack,
        credential,
        "POST",
        "/door/channel/arrivals",
        arrival(str(uuid.uuid4()), UNSHIPPED_LOOK),
    )
    arrival_id = str(uuid.uuid4())
    status_in, came = channel(
        stack, credential, "POST", "/door/channel/arrivals", arrival(arrival_id)
    )
    status_again, again = channel(
        stack, credential, "POST", "/door/channel/arrivals", arrival(arrival_id)
    )
    status_full, full = channel(
        stack,
        credential,
        "POST",
        "/door/channel/arrivals",
        arrival(str(uuid.uuid4()), carried=False),
    )
    thing_id = (came or {}).get("thing_id")
    refusals = {
        "before_hello": [status_early, F.problem_code(early)],
        "not_random": [status_fixed, F.problem_code(fixed)],
        "look_not_shipped": [status_unshipped, F.problem_code(unshipped)],
        "over_the_maximum": [status_full, F.problem_code(full)],
    }
    for name, (got, code), (status, wanted) in (
        ("before_hello", refusals["before_hello"], (409, "hello_first")),
        ("not_random", refusals["not_random"], (422, None)),
        ("look_not_shipped", refusals["look_not_shipped"], (422, "look_not_shipped")),
        ("over_the_maximum", refusals["over_the_maximum"], (409, "visitors_full")),
    ):
        row.expect(
            got == status and (wanted is None or code == wanted), f"{name} answered {got} {code}"
        )
    row.expect(status_hello == 200, f"the hello answered {status_hello} {F.problem_code(said)}")
    row.expect(
        status_in == 201 and thing_id and status_again == 200 and again == came,
        f"the arrival answered {status_in}, again {status_again}",
    )
    status_step, _ = step(w1, "V2", entry), None
    cursor, seen, _ = frames_until(
        stack,
        credential,
        cursor,
        lambda f: f.get("kind") == "arrived" and f.get("arrival_id") == arrival_id,
    )
    arrived = next(
        (f for f in seen if f.get("kind") == "arrived" and f.get("arrival_id") == arrival_id), {}
    )
    row.expect(
        arrived.get("thing_id") == thing_id
        and [c.get("game_item") for c in arrived.get("carried") or []] == [CROSSING_ITEM],
        f"after a step ({status_step}) the frames read {[f.get('kind') for f in seen]}",
    )
    _, society = F.society(w1, "V2", entry)
    state = (society or {}).get("state") or {}
    visitor = next((p for p in state.get("inhabitants") or [] if p.get("id") == thing_id), {})
    held = [t for t in state.get("things") or [] if t.get("held_by") == thing_id]
    row.expect(
        visitor.get("came_by") == "crossed" and len(held) == 1,
        f"the society holds the visitor as {visitor.get('came_by')} holding {len(held)}",
    )
    _, minds = w1.call("V2", "GET", F.version_path(entry, "/society/models"), query=query)
    outside = [o for o in (minds or {}).get("outside") or [] if o.get("subject_id") == thing_id]
    row.expect(
        bool(outside)
        and outside[0].get("grant_id") == grant_id
        and outside[0].get("bridge") == "luanti",
        f"the models view's outside reads {outside}",
    )
    _, looks = w1.call("V2", "GET", F.version_path(entry, "/thing-looks"), query=query)
    worn = [look for look in (looks or {}).get("looks") or [] if look.get("thing_id") == thing_id]
    row.expect(
        bool(worn) and worn[0].get("chosen_by") == "crossing",
        f"the thing-looks read {worn}",
    )
    status_gone, gone = channel(
        stack, credential, "POST", "/door/channel/gone", {"thing_id": thing_id}
    )
    row.expect(status_gone == 202, f"gone answered {status_gone} {gone}")
    status_away, _ = w1.call(
        "V2", "POST", f"/door/grants/{grant_id}/send-away", query=query, body={"thing_id": thing_id}
    )
    step(w1, "V2", entry)
    cursor, seen, _ = frames_until(
        stack,
        credential,
        cursor,
        lambda f: f.get("kind") == "departed" and f.get("thing_id") == thing_id,
    )
    departed = next(
        (f for f in seen if f.get("kind") == "departed" and f.get("thing_id") == thing_id), {}
    )
    carried = departed.get("carried") or []
    row.expect(
        status_away == 202
        and departed.get("why") == "sent_home"
        and [c.get("game_item") for c in carried] == [CROSSING_ITEM],
        f"send-away answered {status_away}; departed {departed}",
    )
    # A-130 (b72a7dee): what the visitor brought went home with it, so the world holds it no more.
    torch = [t.get("id") for t in held]
    _, after_society = F.society(w1, "V2 after", entry)
    left = [
        t.get("id")
        for t in ((after_society or {}).get("state") or {}).get("things") or []
        if t.get("id") in torch
    ]
    row.expect(
        bool(torch) and [c.get("thing_id") for c in carried] == torch and not left,
        f"the departure carried {[c.get('thing_id') for c in carried]}; the brought {torch}; "
        f"still in the world {left}",
    )
    departure = departed.get("departure_id")
    report = {
        "delivered": [
            {"thing_id": c.get("thing_id"), "game_item": c.get("game_item")} for c in carried
        ],
        "not_delivered": [],
    }
    wrong = {
        "delivered": [{"thing_id": str(uuid.uuid4()), "game_item": CROSSING_ITEM}],
        "not_delivered": [],
    }
    path = f"/door/channel/departures/{departure}/delivered"
    status_wrong, wrong_answer = channel(stack, credential, "POST", path, wrong)
    status_report, reported = channel(stack, credential, "POST", path, report)
    status_report_2, reported_2 = channel(stack, credential, "POST", path, report)
    row.expect(
        status_wrong == 422 and F.problem_code(wrong_answer) == "delivery_not_this_departure",
        f"a delivery naming another thing answered {status_wrong} {F.problem_code(wrong_answer)}",
    )
    row.expect(
        status_report == 202
        and (reported or {}).get("recorded") is True
        and status_report_2 == 202
        and (reported_2 or {}).get("recorded") is False,
        f"the delivery answered {status_report} {reported}, again {status_report_2} {reported_2}",
    )
    status_revoke, _ = w1.call(
        "V2", "POST", f"/door/grants/{grant_id}/revoke", query=query, body={}
    )
    step(w1, "V2", entry)
    cursor, seen, _ = frames_until(
        stack, credential, cursor, lambda f: f.get("kind") == "grant_ended"
    )
    status_after, _ = door_call(
        stack,
        credential,
        "GET",
        f"/door/channel/frames?{urllib.parse.urlencode({'after': cursor})}",
    )
    row.expect(
        status_revoke == 200
        and any(f.get("kind") == "grant_ended" for f in seen)
        and status_after == 410,
        f"after the revoke the frames read {[f.get('kind') for f in seen]} and a poll {status_after}",
    )
    _, live = F.society(w1, "V2", entry)
    status_replay, replayed = w1.call(
        "V2", "GET", F.version_path(entry, "/society/replay"), query=query
    )
    row.expect(
        status_replay == 200
        and (replayed or {}).get("state_sha256") == (live or {}).get("state_sha256"),
        f"the replay answered {status_replay} with another state",
    )
    status_stranger, _ = w2.call("V2", "GET", f"/door/grants/{grant_id}", query=query)
    row.expect(status_stranger == 404, f"another workspace was answered {status_stranger}")
    row.observed = {
        "grant": [status_grant, grant_id],
        "read_only": status_ro,
        "hello": status_hello,
        "refusals": refusals,
        "arrival": [status_in, status_again, thing_id],
        "arrived": arrived,
        "visitor": {"came_by": visitor.get("came_by"), "held": len(held)},
        "outside": outside,
        "look": worn,
        "gone": [status_gone, gone],
        "departed": departed,
        "brought_left_in_world": left,
        "delivery": [
            status_wrong,
            F.problem_code(wrong_answer),
            status_report,
            reported,
            status_report_2,
            reported_2,
        ],
        "revoke": [status_revoke, [f.get("kind") for f in seen], status_after],
        "replay": status_replay,
        "stranger": status_stranger,
    }
    return row.close()


def row_v3(stack: Stack, transcripts: Any, worktree: Path, out: Path) -> Row:
    row = Row(
        "V3",
        "door.luanti_standin",
        "The shipped Luanti stand-in (cross_once.py cross), as workspace 1 (the one the host "
        "plays) on the catalog scene V2 built, builds it, opens "
        "the gate and brings one character in exactly as the mod would: it exits 0 and prints the "
        "world, version and character; the society holds that character as crossed, wearing "
        "cc0-traveller, and it is still there after two steps (it answers no ask and has no leave "
        "ability) (A-104).",
    )
    w2 = F.client(stack, transcripts, "w1", "token")
    crossed = subprocess.run(
        [
            str(worktree / ".venv" / "bin" / "python"),
            str(worktree / LUANTI_STANDIN),
            "cross",
            "--api",
            stack.base_url,
            "--token-file",
            str(stack.token_file("token")),
            "--scene",
            str(worktree / DEMO_SCENE),
            "--stay-s",
            "5",
        ],
        cwd=worktree,
        env=LAUNCH.clean_environment(),
        capture_output=True,
        text=True,
        check=False,
        timeout=900,
    )
    (out / "evidence" / "v3-standin.txt").write_text(crossed.stdout + crossed.stderr)
    found = re.search(r"\{.*?\}", crossed.stdout, re.S)
    printed = json.loads(found.group(0)) if found else {}
    row.expect(
        crossed.returncode == 0 and printed.get("character"),
        f"the stand-in exited {crossed.returncode}",
    )
    if not printed.get("character"):
        return row.close()
    entry = {"authored_version_id": printed["version_id"], "world_id": printed["world_id"]}
    for _ in range(2):
        step(w2, "V3", entry)
    _, society = F.society(w2, "V3", entry)
    character = next(
        (
            p
            for p in ((society or {}).get("state") or {}).get("inhabitants") or []
            if p.get("id") == printed["character"]
        ),
        {},
    )
    _, looks = w2.call(
        "V3", "GET", F.version_path(entry, "/thing-looks"), query=F.world_query(entry)
    )
    worn = [
        look
        for look in (looks or {}).get("looks") or []
        if look.get("thing_id") == printed["character"]
    ]
    look_key = ((worn[0] if worn else {}).get("look") or {}).get("look")
    row.expect(
        character.get("came_by") == "crossed", f"the character reads {character.get('came_by')}"
    )
    row.expect(
        printed.get("look_key") == CROSSING_LOOK and bool(worn),
        f"the character wears {look_key} (printed {printed.get('look_key')})",
    )
    row.observed = {"printed": printed, "came_by": character.get("came_by"), "look": worn}
    return row.close()


#: What docs/deployment.md states of the role migration 0161 makes (DF1): its name, and that it
#: cannot log in, is no superuser, does not bypass row-level security and belongs to no role.
DEFINER_ROLE = "exulanica_definer"
DEFINER_FUNCTIONS = (
    "select count(*) filter (where p.proowner <> r.oid), count(*) from pg_proc p "
    "join pg_namespace n on n.oid = p.pronamespace, pg_roles r "
    "where p.prosecdef and r.rolname = '" + DEFINER_ROLE + "' "
    "and n.nspname not in ('pg_catalog', 'information_schema') and n.nspname not like 'pg_toast%'"
)
DEFINER_FLAGS = (
    "select rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolreplication "
    "from pg_roles where rolname = '" + DEFINER_ROLE + "'"
)
DEFINER_MEMBERS = (
    "select count(*) from pg_auth_members m join pg_roles r on r.oid in (m.member, m.roleid) "
    "where r.rolname = '" + DEFINER_ROLE + "'"
)
DEFINER_PUBLIC = (
    "select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
    "where p.prosecdef and n.nspname not in ('pg_catalog', 'information_schema') "
    "and has_function_privilege('public', p.oid, 'execute')"
)


def psql_owner(stack: Stack, sql: str, database_url: str | None = None) -> str:
    """An evidence read as the lane database's owner, through the server's own psql."""
    database = stack.state["database"]
    url = database_url or database["owner_url_for_evidence_reads"]
    done = subprocess.run(
        [str(Path(database["postgres_bin"]) / "psql"), url, "-At", "-F", ",", "-c", sql],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise SystemExit(f"psql refused: {done.stderr.strip()[:300]}")
    return done.stdout.strip()


def definer_reading(stack: Stack, database_url: str | None = None) -> dict[str, Any]:
    others, total = psql_owner(stack, DEFINER_FUNCTIONS, database_url).split(",")
    flags = psql_owner(stack, DEFINER_FLAGS, database_url).split(",")
    return {
        "definers": int(total),
        "owned_by_another": int(others),
        "flags_all_false": flags == ["f"] * 6,
        "memberships": int(psql_owner(stack, DEFINER_MEMBERS, database_url)),
        "public_may_execute": int(psql_owner(stack, DEFINER_PUBLIC, database_url)),
    }


def definer_holds(reading: Mapping[str, Any]) -> bool:
    return (
        reading["definers"] > 0
        and reading["owned_by_another"] == 0
        and reading["flags_all_false"]
        and reading["memberships"] == 0
        and reading["public_may_execute"] == 0
    )


def row_df1(stack: Stack, transcripts: Any) -> Row:
    row = Row(
        "DF1",
        "install.definer_owner",
        "On the run's freshly migrated database, read as its owner (A-105): every SECURITY DEFINER "
        "function is owned by exulanica_definer, which cannot log in, is no superuser, does not "
        "bypass row-level security and belongs to no role and has no member; PUBLIC may execute "
        "none of them. A scratch copy of the schema with one definer given to another owner fails "
        "the same check.",
    )
    reading = definer_reading(stack)
    row.expect(definer_holds(reading), f"the definer reading is {reading}")
    # The mutant: a schema-only copy in a scratch database, one definer handed to the owner.
    database = stack.state["database"]
    owner_url = database["owner_url_for_evidence_reads"]
    binaries = Path(database["postgres_bin"])
    scratch = f"q10_df1_{uuid.uuid4().hex[:8]}"
    scratch_url = owner_url.rsplit("/", 1)[0] + "/" + scratch
    mutant: dict[str, Any] = {}
    try:
        psql_owner(stack, f"create database {scratch}")
        dump = subprocess.run(
            [str(binaries / "pg_dump"), "--schema-only", owner_url],
            capture_output=True,
            text=True,
            check=False,
        )
        subprocess.run(
            [str(binaries / "psql"), scratch_url, "-q", "-v", "ON_ERROR_STOP=0"],
            input=dump.stdout,
            capture_output=True,
            text=True,
            check=False,
        )
        one = psql_owner(
            stack,
            "select p.oid::regprocedure from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
            "where p.prosecdef and n.nspname not in ('pg_catalog', 'information_schema') limit 1",
            scratch_url,
        )
        psql_owner(stack, f"alter function {one} owner to current_user", scratch_url)
        mutant = {"function": one, **definer_reading(stack, scratch_url)}
    finally:
        psql_owner(stack, f"drop database if exists {scratch}")
    row.expect(bool(mutant) and not definer_holds(mutant), f"the mutant reads {mutant}")
    row.observed = {"reading": reading, "mutant": mutant}
    return row.close()


def row_v6(stack: Stack, transcripts: Any, worktree: Path, credential: str | None) -> Row:
    row = Row(
        "V6",
        "door.invite_redeemed",
        "A player's invite redeemed against the door itself (A-114): the owner's invite to a "
        "visitor grant of the Luanti bridge is 201 with a code shown once; the bridge, presenting "
        "its own declared credential, redeems it with a requester digest, 201 with the grant and a "
        "channel credential; the same code again, and a made-up code, are 404 "
        "invite_not_redeemable; the channel credential's hello is 200.",
    )
    if credential is None:
        row.blocked_by.append("no bridge credential was given (--bridge-credential)")
        return row.close()
    w1 = F.client(stack, transcripts, "w1", "token")
    _, entries = w1.call("V6", "GET", "/world-entries")
    held = next((e for e in entries or [] if not e.get("generated_ground")), None)
    if held is None:
        row.blocked_by.append("V2 left no scene world to grant")
        return row.close()
    entry = F.read_entry(w1, "V6", held["entry_id"])
    query = F.world_query(entry)
    _, version = w1.call("V6", "GET", F.version_path(entry), query=query)
    gate = next(
        (
            t.get("thing_id")
            for t in (version or {}).get("things") or []
            if (t.get("kind") or {}).get("kind") == "gate"
        ),
        None,
    )
    status_grant, granted = w1.call(
        "V6",
        "POST",
        "/door/grants",
        query=query,
        body={
            "idempotency_key": str(uuid.uuid4()),
            "bridge": "luanti",
            "version_id": entry["authored_version_id"],
            "minutes": 30,
            "visitors_maximum": 1,
            "kinds": [CROSSING_TYPE],
            **({"gate": gate} if gate else {}),
        },
    )
    grant_id = ((granted or {}).get("grant") or {}).get("grant_id")
    status_invite, invited = w1.call(
        "V6", "POST", f"/door/grants/{grant_id}/invites", query=query, body={}
    )
    code = (invited or {}).get("code")
    row.expect(
        status_grant == 201
        and status_invite == 201
        and code
        and (invited or {}).get("shown") == "once",
        f"the grant answered {status_grant}, the invite {status_invite}",
    )
    requester = hashlib.sha256(f"q10-v6-{uuid.uuid4()}".encode()).hexdigest()
    redeem = {"code": code or "", "requester": requester}
    status_redeem, redeemed = door_call(stack, credential, "POST", "/door/invites/redeem", redeem)
    channel_credential = (redeemed or {}).get("credential")
    row.expect(
        status_redeem == 201
        and ((redeemed or {}).get("grant") or {}).get("grant_id") == grant_id
        and channel_credential,
        f"the redemption answered {status_redeem} {F.problem_code(redeemed)}",
    )
    status_again, again = door_call(stack, credential, "POST", "/door/invites/redeem", redeem)
    status_made_up, made_up = door_call(
        stack, credential, "POST", "/door/invites/redeem", {**redeem, "code": "Q10MADEUPCODE"}
    )
    row.expect(
        status_again == 404 and F.problem_code(again) == "invite_not_redeemable",
        f"the same code again answered {status_again} {F.problem_code(again)}",
    )
    row.expect(
        status_made_up == 404 and F.problem_code(made_up) == "invite_not_redeemable",
        f"a made-up code answered {status_made_up} {F.problem_code(made_up)}",
    )
    status_hello, said = channel(
        stack, channel_credential or "", "POST", "/door/channel/hello", raw=luanti_hello(worktree)
    )
    row.expect(status_hello == 200, f"the hello answered {status_hello} {F.problem_code(said)}")
    w1.call("V6", "POST", f"/door/grants/{grant_id}/revoke", query=query, body={})
    row.observed = {
        "grant": [status_grant, grant_id],
        "invite": [status_invite, (invited or {}).get("shown")],
        "redeem": [status_redeem, F.problem_code(redeemed)],
        "again": [status_again, F.problem_code(again)],
        "made_up": [status_made_up, F.problem_code(made_up)],
        "hello": status_hello,
    }
    return row.close()


def declare_luanti(arguments: argparse.Namespace) -> int:
    """The Luanti bridge as the stand-in declares it, with a credential this driver draws: only its
    digest goes in the file the stack reads; the credential itself goes in ``OUT.credential``, mode
    0600, for V6's redemption, and is never printed."""
    worktree = LAUNCH.checkout(arguments.worktree)
    out = Path(arguments.out).resolve()
    declared = subprocess.run(
        [
            str(worktree / ".venv" / "bin" / "python"),
            str(worktree / LUANTI_STANDIN),
            "declare",
            str(out),
        ],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if declared.returncode != 0:
        raise SystemExit(f"the stand-in did not declare: {declared.stderr.strip()[:300]}")
    entries = json.loads(out.read_text())
    secret = secrets.token_urlsafe(32)
    for entry in entries:
        entry["credential_sha256"] = hashlib.sha256(secret.encode()).hexdigest()
    out.write_text(json.dumps(entries, indent=2) + "\n")
    held = out.with_name(out.name + ".credential")
    held.write_text(secret)
    held.chmod(0o600)
    print(f"{out}: bridge luanti with a driver-held credential")
    return 0


def crossings(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if not stack.state.get("society_of_things") or "door_bridges" not in stack.state:
        raise SystemExit(
            "crossings needs a fresh database and a stack started with --workspaces 2 "
            "--read-only-token --no-derivative-worker --society-of-things --society-playback "
            "--door-bridges FILE (cross_once.py declare FILE)"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    credential = (
        Path(arguments.bridge_credential).read_text().strip()
        if arguments.bridge_credential
        else None
    )
    rows = [
        row_df1(stack, transcripts),
        row_v2(stack, transcripts, worktree, out),
        row_v3(stack, transcripts, worktree, out),
        row_v6(stack, transcripts, worktree, credential),
    ]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


def society_of_things(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if not stack.state.get("society_of_things"):
        raise SystemExit(
            "society-of-things needs a stack started with --society-of-things on a fresh database"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_t4(stack, transcripts, worktree, out)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


def things(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if len(workspace_ids(stack)) < 2:
        raise SystemExit("things needs a stack started with --workspaces 2")
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    sc1 = row_sc1(stack, transcripts, worktree, out)
    rows = [
        row_t1(stack, transcripts, worktree),
        row_t2(stack, transcripts),
        sc1,
        row_t3(stack, transcripts, sc1.observed),
        row_t4a(stack, transcripts, sc1.observed, worktree),
        row_s4(stack, transcripts),
        row_sc2(stack, transcripts, worktree, out),
    ]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- D1: the door's grants --------------------------------------------------------------------------

#: The outside program D1's stack declares: AGENTS' example entry as shipped (A-80), the mapping
#: document its hello sends, and the reads AGENTS' body states (bridges/agents/exulanica_agent/body.py).
DOOR_BRIDGE_ENTRY = Path("bridges") / "agents" / "examples" / "bridge-entry.json"
DOOR_MAPPING = Path("bridges") / "agents" / "exulanica_agent" / "outside-agents.v1.json"
DOOR_READS = ("action", "line", "declared name", "declared maker", "declared mind")


def door_call(
    stack: Stack, credential: str | None, method: str, path: str, body: Any = None
) -> tuple[int, Any]:
    """A request with a door credential (or none), outside the JSON clients' tokens."""
    request = urllib.request.Request(
        f"{stack.base_url}{path}",
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={
            "Content-Type": "application/json",
            **({} if credential is None else {"Authorization": f"Bearer {credential}"}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as refused:
        raw = refused.read()
        try:
            return refused.code, json.loads(raw or b"null")
        except ValueError:
            return refused.code, raw.decode(errors="replace")


def deciders(c: Any, step: str, entry: Mapping[str, Any], people: Sequence[str]) -> dict[str, Any]:
    """Who decides each of ``people`` as the people role's view reads it: the newest choice's
    decider kind, or None for a person no choice names (the routine)."""
    view = (roles_read(c, step, entry).get(PERSON_ROLE) or {}).get("view") or {}
    newest: dict[str, Any] = {}
    for choice in view.get("choices") or []:
        subject = choice.get("subject_id")
        if subject in people and (
            subject not in newest
            or choice.get("choice_seq", 0) >= newest[subject].get("choice_seq", 0)
        ):
            newest[subject] = choice
    return {p: ((newest.get(p) or {}).get("decider") or {}).get("kind") for p in people}


def row_d1(stack: Stack, transcripts: Any, worktree: Path) -> Row:
    row = Row(
        "DR1",
        "door.grants",
        "With AGENTS' example bridge declared: GET /door/bridges lists it; on the starter a visitor "
        "grant naming no version is 422 invalid_scope and one naming the starter's version, whose "
        "society holds no things, is 409 world_not_open_to_visitors (A-109). Named things (A-88): "
        "on a generated town with its society, a grant naming two of its people and the version is "
        "201, the same request again 200 with the same grant, as is the same request with its "
        "things reordered, neither carrying a second credential, and the first issue's credential "
        "still says hello 200 (A-131); the people role reads them "
        "decided from outside; an unknown bridge is 422 bridge_not_offered; the read-only grant is "
        "refused 403; the other workspace reads no grant of workspace 1's (404); things without the version, or the version without things, are 422 "
        "invalid_scope; a person not in the world is 422 person_not_in_this_world. One channel "
        "credential is live: a hello on it is 200, a second credential ends it (its next hello, "
        "and its poll before the second's hello, 401 unauthenticated, A-121), the second polls "
        "only after its own hello (409 hello_first, then 200); "
        "revoking reads ended, hands the people back to their routine, and the hello after is "
        "refused.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    read_only = F.client(stack, transcripts, "read-only", "token-read")
    declared = json.loads((worktree / DOOR_BRIDGE_ENTRY).read_text())
    _, listed = w1.call("D1", "GET", "/door/bridges")
    row.expect(
        any(b.get("bridge") == declared["bridge"] for b in (listed or {}).get("bridges") or []),
        f"the bridges listed are {listed}",
    )
    status_starter, entry = starter(w1, "D1", "Q10 D1 starter")
    row.expect(status_starter == 200, f"the starter answered {status_starter}")
    if status_starter != 200:
        return row.close()
    query = F.world_query(entry)
    body = {
        "idempotency_key": str(uuid.uuid4()),
        "bridge": declared["bridge"],
        "visitors_maximum": 1,
        "kinds": ["visitor"],
        "minutes": 5,
        "channel_credential": True,
    }
    # A visitor grant names a version whose society holds things (A-109): the starter has none.
    visitors = {}
    for name, change, status, code in (
        ("visitors without a version", {}, 422, "invalid_scope"),
        (
            "visitors into a world without things",
            {"version_id": entry["authored_version_id"]},
            409,
            "world_not_open_to_visitors",
        ),
    ):
        got, answer = w1.call(
            "D1",
            "POST",
            "/door/grants",
            query=query,
            body={**body, **change, "idempotency_key": str(uuid.uuid4())},
        )
        visitors[name] = [got, F.problem_code(answer)]
        row.expect(
            got == status and F.problem_code(answer) == code,
            f"{name} answered {got} {F.problem_code(answer)}",
        )

    # Named things: two people of a generated town's society, bound in its version (A-88).
    town = generated_town(w1, "D1 town", "Q10 D1 town")
    town_query = F.world_query(town)
    _, society = F.society(w1, "D1 town", town)
    people = [p.get("id") for p in ((society or {}).get("state") or {}).get("inhabitants") or []][
        :2
    ]
    named = {
        **body,
        "kinds": [],
        "visitors_maximum": 0,
        "things": people,
        "version_id": town["authored_version_id"],
    }
    scope = {}
    for name, change, status, code in (
        ("things without the version", {"version_id": None}, 422, "invalid_scope"),
        ("the version without things", {"things": []}, 422, "invalid_scope"),
        (
            "a person not in the world",
            {"things": [str(uuid.uuid4())]},
            422,
            "person_not_in_this_world",
        ),
    ):
        got, answer = w1.call(
            "D1 named",
            "POST",
            "/door/grants",
            query=town_query,
            body={**named, **change, "idempotency_key": str(uuid.uuid4())},
        )
        scope[name] = [got, F.problem_code(answer)]
        row.expect(
            got == status and F.problem_code(answer) == code,
            f"{name} answered {got} {F.problem_code(answer)}",
        )
    named_body = {**named, "idempotency_key": str(uuid.uuid4())}
    status_named, bound = w1.call(
        "D1 named", "POST", "/door/grants", query=town_query, body=named_body
    )
    named_id = ((bound or {}).get("grant") or {}).get("grant_id")
    row.expect(
        status_named == 201 and named_id and len(people) == 2,
        f"the named grant answered {status_named} {F.problem_code(bound)} for {len(people)} people",
    )
    status_again, again = w1.call(
        "D1 named", "POST", "/door/grants", query=town_query, body=named_body
    )
    row.expect(
        status_again == 200 and ((again or {}).get("grant") or {}).get("grant_id") == named_id,
        f"the same request again answered {status_again}",
    )
    # A-131 (e3e28f29): the same issue with its things in another order is the same grant, 200,
    # carrying no second credential, so the first stays live.
    status_reordered, reordered = w1.call(
        "D1 named",
        "POST",
        "/door/grants",
        query=town_query,
        body={**named_body, "things": list(reversed(named_body["things"]))},
    )
    row.expect(
        status_reordered == 200
        and ((reordered or {}).get("grant") or {}).get("grant_id") == named_id
        and not (reordered or {}).get("channel_credential")
        and not (again or {}).get("channel_credential"),
        f"the issue with its things reordered answered {status_reordered} "
        f"{F.problem_code(reordered)}",
    )
    issued_credential = ((bound or {}).get("channel_credential") or {}).get("credential")
    refusals = {}
    for name, change, client, status, code in (
        ("unknown bridge", {"bridge": "q10-nobody"}, w1, 422, "bridge_not_offered"),
        ("read-only", {}, read_only, 403, None),
    ):
        got, answer = client.call(
            "D1 named",
            "POST",
            "/door/grants",
            query=town_query,
            body={**named, **change, "idempotency_key": str(uuid.uuid4())},
        )
        refusals[name] = [got, F.problem_code(answer)]
        row.expect(
            got == status and (code is None or F.problem_code(answer) == code),
            f"{name} answered {got} {F.problem_code(answer)}",
        )
    status_stranger, _ = w2.call("D1 named", "GET", f"/door/grants/{named_id}", query=town_query)
    row.expect(status_stranger == 404, f"the other workspace was answered {status_stranger}")
    decided = deciders(w1, "D1 named", town, people)
    row.expect(
        all(kind == "external" for kind in decided.values()),
        f"the people role reads the named people decided by {decided}",
    )

    # One live channel credential, and a hello under each (544fc5f6).
    hello = {
        "adapter_version": declared["adapter_versions"][0],
        "mapping": json.loads((worktree / DOOR_MAPPING).read_text()),
        "reads": list(DOOR_READS),
    }
    status_issued_hello, _ = door_call(
        stack, issued_credential, "POST", "/door/channel/hello", hello
    )
    row.expect(
        status_issued_hello == 200,
        f"the credential the first issue gave answered {status_issued_hello} after the re-sends",
    )
    path = f"/door/grants/{named_id}/channel-credentials"
    _, first = w1.call("D1 credential", "POST", path, query=town_query, body={})
    first_credential = (first or {}).get("credential")
    status_hello, said = door_call(stack, first_credential, "POST", "/door/channel/hello", hello)
    row.expect(status_hello == 200, f"the hello answered {status_hello} {F.problem_code(said)}")
    status_second, second = w1.call("D1 credential", "POST", path, query=town_query, body={})
    second_credential = (second or {}).get("credential")
    row.expect(
        status_second == 201 and second_credential,
        f"the second credential answered {status_second}",
    )
    status_ended, ended_answer = door_call(
        stack, first_credential, "POST", "/door/channel/hello", hello
    )
    row.expect(
        status_ended == 401 and F.problem_code(ended_answer) == "unauthenticated",
        f"the ended credential answered {status_ended} {F.problem_code(ended_answer)}",
    )
    # A-121 (1621cb37): the ended credential's poll, before the newer one has said hello, is
    # refused as unauthenticated, never asked for a hello first.
    status_ended_poll, ended_poll = door_call(
        stack, first_credential, "GET", "/door/channel/frames"
    )
    row.expect(
        status_ended_poll == 401 and F.problem_code(ended_poll) == "unauthenticated",
        f"the ended credential's poll answered {status_ended_poll} {F.problem_code(ended_poll)}",
    )
    status_early, early = door_call(stack, second_credential, "GET", "/door/channel/frames")
    row.expect(
        status_early == 409 and F.problem_code(early) == "hello_first",
        f"a poll before its hello answered {status_early} {F.problem_code(early)}",
    )
    status_hello_2, _ = door_call(stack, second_credential, "POST", "/door/channel/hello", hello)
    status_poll, _ = door_call(stack, second_credential, "GET", "/door/channel/frames")
    row.expect(
        status_hello_2 == 200 and status_poll == 200,
        f"the second credential's hello answered {status_hello_2} and its poll {status_poll}",
    )

    status_revoke, _ = w1.call(
        "D1 revoke", "POST", f"/door/grants/{named_id}/revoke", query=town_query, body={}
    )
    _, read = w1.call("D1 revoke", "GET", f"/door/grants/{named_id}", query=town_query)
    ended = ((read or {}).get("grant") or read or {}).get("ended")
    row.expect(
        status_revoke == 200 and ended, f"the revoke answered {status_revoke}; ended {ended}"
    )
    handed_back = deciders(w1, "D1 revoke", town, people)
    row.expect(
        all(kind != "external" for kind in handed_back.values()),
        f"after the revoke the people are decided by {handed_back}",
    )
    status_after, after = door_call(stack, second_credential, "POST", "/door/channel/hello", hello)
    row.expect(400 <= status_after < 500, f"the hello after the revoke answered {status_after}")
    row.observed = {
        "bridge": declared["bridge"],
        "visitors": visitors,
        "again": status_again,
        "refusals": refusals,
        "stranger": status_stranger,
        "named": {
            "grant": [status_named, named_id],
            "people": people,
            "deciders": decided,
            "scope_refusals": scope,
        },
        "credentials": {
            "first_hello": [status_hello, F.problem_code(said)],
            "reordered_issue": [status_reordered, F.problem_code(reordered)],
            "issued_credential_hello_after_resends": status_issued_hello,
            "second": status_second,
            "first_after_second": [status_ended, F.problem_code(ended_answer)],
            "poll_before_hello": [status_early, F.problem_code(early)],
            "ended_credential_poll": [status_ended_poll, F.problem_code(ended_poll)],
            "second_hello_and_poll": [status_hello_2, status_poll],
        },
        "revoke": [status_revoke, ended],
        "deciders_after_revoke": handed_back,
        "hello_after_revoke": [status_after, F.problem_code(after)],
    }
    return row.close()


#: The outside agent AG1 runs: the agent library as shipped (bridges/agents), in its own process,
#: with a fixed policy instead of a mind (the first offered action), and no model anywhere.
AGENT_LIBRARY = Path("bridges") / "agents"
SCRIPTED_AGENT = r"""
import json, sys, time
from exulanica_agent import Body
seen = {"turn": None, "answer": None, "outcome": None, "happened": [], "ended": None}
body = Body.connect(name="Q10 scripted agent", maker="acceptance", mind="first offered action")
try:
    turn = body.next_turn(float(sys.argv[1]))
    if turn is not None:
        action = turn.options[0].action
        answer = turn.act(action, "Hello." if turn.options[0].says_line else None)
        seen["turn"] = {"minute": turn.minute, "options": [o.action for o in turn.options],
                        "acted": action}
        seen["answer"] = {"received": answer.received, "refusal": answer.refusal}
        # The host takes or refuses a received answer at a later minute, as a happening.
        deadline = time.monotonic() + float(sys.argv[2])
        while time.monotonic() < deadline and seen["outcome"] is None:
            for happening in body.happened():
                seen["happened"].append(happening.as_dict())
                if happening.what in ("answer_taken", "answer_not_taken"):
                    seen["outcome"] = happening.as_dict()
            time.sleep(1)
    seen["happened"] = seen["happened"][:20]
    seen["ended"] = body.ended
finally:
    body.close(wait_seconds=20)
print(json.dumps(seen))
"""
AGENT_TURN_SECONDS = 300
#: How long after its answer the agent waits for the host to say whether it was taken (A-100).
AGENT_OUTCOME_SECONDS = 180


def row_ag1(stack: Stack, transcripts: Any, worktree: Path, out: Path) -> Row:
    row = Row(
        "AG1",
        "door.outside_agent_turn",
        "An outside agent built on the shipped agent library, with a fixed first-offered-action "
        "policy and no model, holds a grant naming one person of a generated town the host plays: "
        "it says hello, its person's turn reaches it within 300 s of the society playing, its act "
        "is received by the door, and within 180 s the host tells it the answer was taken "
        "(answer_taken; A-100); then it closes. It brings no body in, so the library makes no "
        "leaving call; V2 checks the leaving routes (A-107).",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    declared = json.loads((worktree / DOOR_BRIDGE_ENTRY).read_text())
    town = generated_town(w1, "AG1", "Q10 AG1 town")
    query = F.world_query(town)
    _, society = F.society(w1, "AG1", town)
    person = next(
        (p.get("id") for p in ((society or {}).get("state") or {}).get("inhabitants") or []), None
    )
    status_grant, granted = w1.call(
        "AG1",
        "POST",
        "/door/grants",
        query=query,
        body={
            "idempotency_key": str(uuid.uuid4()),
            "bridge": declared["bridge"],
            "things": [person],
            "version_id": town["authored_version_id"],
            "minutes": 30,
        },
    )
    grant_id = ((granted or {}).get("grant") or {}).get("grant_id")
    row.expect(status_grant == 201 and grant_id, f"the grant answered {status_grant}")
    if not grant_id:
        return row.close()
    _, issued = w1.call(
        "AG1", "POST", f"/door/grants/{grant_id}/channel-credentials", query=query, body={}
    )
    credential = (issued or {}).get("credential")
    status_play, _ = control(w1, "AG1", town, "playing")
    row.expect(status_play == 200, f"playing the society answered {status_play}")
    agent = subprocess.run(
        [
            str(worktree / ".venv" / "bin" / "python"),
            "-c",
            SCRIPTED_AGENT,
            str(AGENT_TURN_SECONDS),
            str(AGENT_OUTCOME_SECONDS),
        ],
        cwd=worktree,
        env={
            **LAUNCH.clean_environment(),
            "PYTHONPATH": str(worktree / AGENT_LIBRARY),
            "EXULANICA_URL": stack.base_url,
            "EXULANICA_AGENT_KEY": credential or "",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=AGENT_TURN_SECONDS + AGENT_OUTCOME_SECONDS + 120,
    )
    status_pause, _ = control(w1, "AG1", town, "paused")
    (out / "evidence" / "ag1-agent.txt").write_text(agent.stderr)
    try:
        seen = json.loads(agent.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        seen = {}
    row.expect(agent.returncode == 0, f"the agent exited {agent.returncode}")
    turn, answer = seen.get("turn") or {}, seen.get("answer") or {}
    row.expect(bool(turn), "no turn reached the agent")
    row.expect(answer.get("received") is True, f"the act was answered {answer}")
    outcome = seen.get("outcome") or {}
    row.expect(
        outcome.get("what") == "answer_taken",
        f"the host's word on the answer was {outcome or 'none within the wait'}",
    )
    w1.call("AG1", "POST", f"/door/grants/{grant_id}/revoke", query=query, body={})
    row.observed = {
        "grant": [status_grant, grant_id],
        "person": person,
        "play": [status_play, status_pause],
        "agent": {"exit": agent.returncode, **seen},
        "outcome": outcome,
        "leaving": "no leaving call: the agent decides for a named person and brings no body in",
    }
    return row.close()


#: How many grants a workspace may issue in any 24 hours (docs/door-contract.md, e3e28f29).
GRANTS_A_DAY = 50


def row_dr2(stack: Stack, transcripts: Any, worktree: Path) -> Row:
    row = Row(
        "DR2",
        "door.grants_a_day",
        f"A workspace issues at most {GRANTS_A_DAY} grants in any 24 hours (candidate-35): workspace 2 "
        f"issues {GRANTS_A_DAY} grants naming one person of its own town, each 201; the next is 429 "
        "too_many_grants with retry_after_s; workspace 1, whose own grants are fewer, still issues "
        "one, 201.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    declared = json.loads((worktree / DOOR_BRIDGE_ENTRY).read_text())

    def issue(c: Any, town: Mapping[str, Any], person: str) -> tuple[int, Any]:
        return c.call(
            "DR2",
            "POST",
            "/door/grants",
            query=F.world_query(town),
            body={
                "idempotency_key": str(uuid.uuid4()),
                "bridge": declared["bridge"],
                "things": [person],
                "version_id": town["authored_version_id"],
                "minutes": 5,
            },
        )

    def first_person(c: Any, town: Mapping[str, Any]) -> str | None:
        _, society = F.society(c, "DR2", town)
        return next(
            (p.get("id") for p in ((society or {}).get("state") or {}).get("inhabitants") or []),
            None,
        )

    town_2 = generated_town(w2, "DR2", "Q10 DR2 town")
    person_2 = first_person(w2, town_2)
    statuses = [issue(w2, town_2, person_2)[0] for _ in range(GRANTS_A_DAY)] if person_2 else []
    status_over, over = issue(w2, town_2, person_2) if person_2 else (None, {})
    town_1 = generated_town(w1, "DR2", "Q10 DR2 own town")
    person_1 = first_person(w1, town_1)
    status_other, other = issue(w1, town_1, person_1) if person_1 else (None, {})
    row.expect(
        len(statuses) == GRANTS_A_DAY and all(s == 201 for s in statuses),
        f"workspace 2's grants answered {sorted(set(statuses))} ({statuses.count(201)} of "
        f"{GRANTS_A_DAY} 201)",
    )
    retry = (over or {}).get("retry_after_s")
    row.expect(
        status_over == 429
        and F.problem_code(over) == "too_many_grants"
        and isinstance(retry, (int, float))
        and retry > 0,
        f"the grant past the bound answered {status_over} {F.problem_code(over)} retry {retry}",
    )
    row.expect(status_other == 201, f"workspace 1's grant answered {status_other}")
    row.observed = {
        "issued": {str(s): statuses.count(s) for s in sorted(set(statuses))},
        "over": [status_over, F.problem_code(over), retry],
        "other_workspace": [status_other, F.problem_code(other)],
    }
    return row.close()


def door(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if not stack.token_file("token-read").exists() or len(workspace_ids(stack)) < 2:
        raise SystemExit(
            "door needs a stack started with --workspaces 2 --read-only-token --door-bridges"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_d1(stack, transcripts, worktree)]
    if stack.state.get("society_playback") and stack.state.get("scripted_model"):
        rows.append(row_ag1(stack, transcripts, worktree, out))
    rows.append(row_dr2(stack, transcripts, worktree))
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- V1: a guest enters by code, through the local HTTPS edge ----------------------------------------

#: Answer fields that are credentials: a transcript holds a placeholder instead.
GUEST_CREDENTIAL_FIELDS = frozenset({"csrf_token"})
GUEST_CODE_PLACEHOLDER = "[the run's guest code]"
GUEST_WRONG_DETAIL = "that code does not open this server"


def redacted(document: Any) -> Any:
    """``document`` with every credential field's value replaced, at any depth."""
    if isinstance(document, dict):
        return {
            k: "[redacted]" if k in GUEST_CREDENTIAL_FIELDS else redacted(v)
            for k, v in document.items()
        }
    if isinstance(document, list):
        return [redacted(v) for v in document]
    return document


class GuestClient:
    """A browser's requests to the accounts host without a browser: the edge's HTTPS origin, its
    root certificate trusted in this process only, the session cookie the entry set kept as a
    browser keeps it, and on a write the page's Origin and the session's CSRF token. Its transcript
    holds neither the cookie nor the token nor the run's code."""

    def __init__(self, stack: Stack, transcripts: Any, name: str) -> None:
        edge = stack.state["edge"]
        self.origin = str(edge["origin"])
        self.context = ssl.create_default_context(cafile=str(edge["root_certificate"]))
        self.cookie: str | None = None
        self.csrf: str | None = None
        self.set_cookie: str | None = None
        self.step = "start"
        self.record = transcripts.recorder(name, lambda: self.step)

    def call(
        self,
        step: str,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Any = None,
        recorded_body: Any = None,
    ) -> tuple[int, Any]:
        self.step = step
        query = dict(query or {})
        url = self.origin + path + (f"?{urllib.parse.urlencode(query)}" if query else "")
        headers = {"Accept": "application/json", "Origin": self.origin}
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.cookie is not None:
            headers["Cookie"] = self.cookie
        if self.csrf is not None and method not in ("GET", "HEAD"):
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60, context=self.context) as response:
                status, raw, answer_headers = response.status, response.read(), response.headers
        except urllib.error.HTTPError as refused:
            status, raw, answer_headers = refused.code, refused.read(), refused.headers
        self.set_cookie = answer_headers.get("Set-Cookie")
        try:
            answer = json.loads(raw or b"null")
        except ValueError:
            answer = raw.decode(errors="replace")
        self.record(
            F.Exchange(
                method,
                path,
                query,
                status,
                redacted(body if recorded_body is None else recorded_body),
                redacted(answer),
            )
        )
        return status, answer

    def keep_session(self, answer: Mapping[str, Any]) -> bool:
        """Keep the session the last answer set, as a browser keeps its cookie."""
        if not self.set_cookie:
            return False
        self.cookie = self.set_cookie.split(";", 1)[0]
        self.csrf = answer.get("csrf_token")
        return True


def allowance_figures(allowance: Any) -> dict[str, tuple[Decimal | None, int | None]]:
    """Each provider's available money and calls, as numbers."""
    figures = {}
    for entry in allowance or []:
        usd, calls = entry.get("available_usd"), entry.get("available_calls")
        figures[str(entry.get("provider"))] = (
            None if usd is None else Decimal(str(usd)),
            None if calls is None else int(calls),
        )
    return figures


def issued_providers(stack: Stack) -> list[str]:
    """An evidence read: the providers the launcher issued an authority and guest policy for."""
    issued = json.loads((stack.run_dir / "logs" / "guest-policy.txt").read_text())
    return sorted(str(entry["provider"]) for entry in issued)


def row_v1(stack: Stack, transcripts: Any) -> Row:
    accounts = stack.state["accounts"]
    policy = accounts["guest_policy"]
    ceiling, most_calls = Decimal(str(policy["ceiling_usd"])), int(policy["max_calls"])
    row = Row(
        "V1",
        "accounts.guest_by_code",
        "Through the local HTTPS edge (the browser origin https://localhost:<edge port>): a wrong "
        f'code is refused 403 guest_entry_code_wrong with the words "{GUEST_WRONG_DETAIL}" and '
        "no session; the run's code enters (201) with role guest, a workspace of its own, an "
        "allowance on every provider the guest policy names with money and calls available and no "
        "more than the policy grants, and no incomplete step; GET /auth/session reads the same "
        "allowance; the guest makes a town of its own through Create a world (201); in the "
        "arrival world its entry made, the "
        "people it chooses a model for are decided by that model once the society plays; the "
        "allowance "
        "read afterwards has fewer calls or less money available than before.",
    )
    providers = issued_providers(stack)
    code = Path(accounts["code_file"]).read_text().strip()
    stranger = GuestClient(stack, transcripts, "wrong-code")
    status_wrong, wrong = stranger.call(
        "V1 wrong code", "POST", "/auth/guest", body={"code": f"q10-{secrets.token_urlsafe(12)}"}
    )
    row.expect(
        status_wrong == 403
        and F.problem_code(wrong) == "guest_entry_code_wrong"
        and (wrong or {}).get("detail") == GUEST_WRONG_DETAIL,
        f"the wrong code answered {status_wrong} {F.problem_code(wrong)}",
    )
    row.expect(not stranger.set_cookie, "the wrong code's answer set a cookie")
    guest = GuestClient(stack, transcripts, "guest")
    status_in, entered = guest.call(
        "V1 enter",
        "POST",
        "/auth/guest",
        body={"code": code},
        recorded_body={"code": GUEST_CODE_PLACEHOLDER},
    )
    entered = entered if isinstance(entered, dict) else {}
    kept = guest.keep_session(entered)
    synthetic = {
        stack.state.get("workspace_id"),
        *(w.get("workspace_id") for w in stack.state.get("other_workspaces") or []),
    }
    granted = allowance_figures(entered.get("allowance"))
    row.expect(
        status_in == 201 and kept and bool(guest.csrf),
        f"the code answered {status_in} {F.problem_code(entered)}; session kept {kept}",
    )
    row.expect(entered.get("role") == "guest", f"the entry's role is {entered.get('role')}")
    row.expect(
        bool(entered.get("workspace_id")) and entered.get("workspace_id") not in synthetic,
        "the guest's workspace is not its own",
    )
    row.expect(
        entered.get("incomplete") == [], f"the entry left incomplete {entered.get('incomplete')}"
    )
    row.expect(
        sorted(granted) == providers
        and all(
            usd is not None and calls is not None and 0 < usd <= ceiling and 0 < calls <= most_calls
            for usd, calls in granted.values()
        ),
        f"the allowance is {entered.get('allowance')} for providers {providers}",
    )
    status_session, session = guest.call("V1 session", "GET", "/auth/session")
    row.expect(
        status_session == 200 and allowance_figures((session or {}).get("allowance")) == granted,
        f"the session read answered {status_session} with another allowance",
    )
    if not kept:
        return row.close()
    # A guest's workspace holds its arrival world, so its own world is made as a person makes one,
    # through Create a world; the starter is only a workspace's first world (A-85).
    status_own, own = guest.call(
        "V1 own world",
        "POST",
        "/worlds/generated",
        body={"recipe": "small_town", "title": "Q10 V1 own town"},
    )
    row.expect(
        status_own == 201 and bool((own or {}).get("entry_id")),
        f"Create a world answered {status_own} {F.problem_code(own)}",
    )
    # The people are the arrival world's: an empty starter has nowhere for anyone to go (A-84).
    arrival = entered.get("arrival") or {}
    if not arrival.get("entry_id"):
        return row.close()
    entry = F.read_entry(guest, "V1 people", arrival["entry_id"])
    status_society, society = F.society(guest, "V1 people", entry)
    if status_society == 404:
        status_society, _ = guest.call(
            "V1 people",
            "POST",
            F.version_path(entry, "/society"),
            query=F.world_query(entry),
            body={"region_id": TOWN_REGION, "profile": TOWN_ENGINE},
        )
        entry = F.read_entry(guest, "V1 people", entry["entry_id"])
        _, society = F.society(guest, "V1 people", entry)
    row.expect(status_society == 200, f"the arrival world's people answered {status_society}")
    inhabitants = [
        p.get("id") for p in ((society or {}).get("state") or {}).get("inhabitants") or []
    ]
    person = roles_read(guest, "V1 choose", entry).get(PERSON_ROLE) or {}
    most = person.get("model_subjects_maximum") or PEOPLE_CHOSEN_MOST
    chosen = inhabitants[: min(int(most), PEOPLE_CHOSEN_MOST)]
    status_choice, _ = choose_model(guest, "V1 choose", entry, PERSON_ROLE, chosen, GOING_MODEL)
    row.expect(
        bool(chosen) and status_choice == 200,
        f"choosing a model for {len(chosen)} people answered {status_choice}",
    )
    calls_before = len(scripted_log(stack))
    status_play, _ = control(guest, "V1 play", entry, "playing")
    row.expect(status_play == 200, f"playing the society answered {status_play}")
    deadline = time.monotonic() + PERSON_DECISION_SECONDS
    latest: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        view = (roles_read(guest, "V1 play", entry).get(PERSON_ROLE) or {}).get("view") or {}
        latest = [
            d for d in view.get("latest") or [] if d.get("model_id") == GOING_MODEL["model_id"]
        ]
        if latest:
            break
        time.sleep(3)
    status_pause, _ = control(guest, "V1 pause", entry, "paused")
    row.expect(status_pause == 200, f"pausing the society answered {status_pause}")
    row.expect(bool(latest), "no person decision by the chosen model was read")
    calls_after = len(scripted_log(stack))
    status_after, after = guest.call("V1 allowance after", "GET", "/auth/session")
    spent = allowance_figures((after or {}).get("allowance"))
    row.expect(
        status_after == 200
        and sorted(spent) == providers
        and any(
            spent[p][0] is not None
            and spent[p][1] is not None
            and (spent[p][1] < granted[p][1] or spent[p][0] < granted[p][0])
            for p in providers
            if p in granted and None not in granted[p]
        ),
        f"the allowance after reads {(after or {}).get('allowance')}",
    )
    row.observed = {
        "origin": guest.origin,
        "wrong_code": [status_wrong, F.problem_code(wrong), bool(stranger.set_cookie)],
        "entry": [status_in, entered.get("role"), entered.get("incomplete")],
        "own_workspace": entered.get("workspace_id") not in synthetic,
        "arrival": entered.get("arrival"),
        "policy": {"ceiling_usd": str(ceiling), "max_calls": most_calls, "providers": providers},
        "allowance_at_entry": {p: [str(u), c] for p, (u, c) in granted.items()},
        "allowance_after": {p: [str(u), c] for p, (u, c) in spent.items()},
        "session": status_session,
        "own_world": [status_own, (own or {}).get("entry_id")],
        "people_world": entry.get("entry_id"),
        "people": [status_society, len(inhabitants), len(chosen), status_choice],
        "decisions_by_chosen_model": len(latest),
        "scripted_calls_while_playing": calls_after - calls_before,
    }
    return row.close()


# -- V4, V5: guests' places and a guest's allowance used up ---------------------------------------

#: How often a waiting guest's page reads its control (a guest counts as there while it is used),
#: and how long past the play window the rotation may take (the host rereads every 5 s).
GUEST_READ_SECONDS = 20
GUEST_ROTATION_GRACE_SECONDS = 60
GUEST_START_SECONDS = 60


def enter_guest(stack: Stack, transcripts: Any, name: str) -> tuple[GuestClient, dict[str, Any]]:
    """A guest entered by the run's code, its session kept, and the arrival town it was given."""
    guest = GuestClient(stack, transcripts, name)
    code = Path(stack.state["accounts"]["code_file"]).read_text().strip()
    status, entered = guest.call(
        f"{name} enter",
        "POST",
        "/auth/guest",
        body={"code": code},
        recorded_body={"code": GUEST_CODE_PLACEHOLDER},
    )
    entered = entered if isinstance(entered, dict) else {}
    guest.keep_session(entered)
    entered["status"] = status
    return guest, entered


def playing_town(
    guest: GuestClient, label: str, entered: Mapping[str, Any]
) -> dict[str, Any] | None:
    """The guest's arrival town with people brought in and set playing, or None."""
    arrival = entered.get("arrival") or {}
    if not arrival.get("entry_id"):
        return None
    entry = F.read_entry(guest, label, arrival["entry_id"])
    if F.society(guest, label, entry)[0] == 404:
        guest.call(
            label,
            "POST",
            F.version_path(entry, "/society"),
            query=F.world_query(entry),
            body={"region_id": TOWN_REGION, "profile": TOWN_ENGINE},
        )
        entry = F.read_entry(guest, label, entry["entry_id"])
    status, _ = control(guest, label, entry, "playing")
    return entry if status == 200 else None


def control_read(guest: GuestClient, label: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    _, read = guest.call(
        label, "GET", F.version_path(entry, "/society/control"), query=F.world_query(entry)
    )
    read = read if isinstance(read, dict) else {}
    return {
        "running": (read.get("host_playback") or {}).get("running"),
        "code": read.get("host_playback_code"),
        "minds": read.get("model_minds_code"),
        "minds_reason": read.get("model_minds_reason"),
    }


def plays(reading: Mapping[str, Any]) -> bool:
    return reading.get("running") is True and reading.get("code") is None


def waits(reading: Mapping[str, Any]) -> bool:
    return reading.get("code") == "guest_towns_full"


def row_v4(stack: Stack, transcripts: Any) -> Row:
    accounts = stack.state["accounts"]
    window = int(accounts["play_seconds"])
    row = Row(
        "V4",
        "accounts.guest_places",
        f"With one guest's town playing at a time and a play window of {window} s (A-111 as "
        "clarified): guest A's town plays; guest B's town then reads guest_towns_full (not "
        "running); with both kept there, within the window and a minute A reads guest_towns_full "
        "and B's town plays; then, A no longer there, B alone keeps its place through a whole "
        "window.",
    )
    a, entered_a = enter_guest(stack, transcripts, "guest-a")
    town_a = playing_town(a, "V4 A", entered_a)
    row.expect(entered_a.get("status") == 201 and town_a is not None, "guest A has no playing town")
    if town_a is None:
        return row.close()
    timeline: list[dict[str, Any]] = []
    deadline = time.monotonic() + GUEST_START_SECONDS
    reading = control_read(a, "V4 A", town_a)
    while not plays(reading) and time.monotonic() < deadline:
        time.sleep(3)
        reading = control_read(a, "V4 A", town_a)
    row.expect(plays(reading), f"guest A's town reads {reading}")
    b, entered_b = enter_guest(stack, transcripts, "guest-b")
    town_b = playing_town(b, "V4 B", entered_b)
    row.expect(entered_b.get("status") == 201 and town_b is not None, "guest B has no playing town")
    if town_b is None:
        return row.close()
    deadline_b = time.monotonic() + GUEST_START_SECONDS
    first_b = control_read(b, "V4 B", town_b)
    while not waits(first_b) and time.monotonic() < deadline_b:
        time.sleep(3)
        first_b = control_read(b, "V4 B", town_b)
    row.expect(
        waits(first_b) and first_b.get("running") is not True,
        f"guest B's town first reads {first_b}",
    )
    started = time.monotonic()
    rotated = None
    while time.monotonic() < started + window + GUEST_ROTATION_GRACE_SECONDS:
        time.sleep(GUEST_READ_SECONDS)
        read_a, read_b = control_read(a, "V4 both", town_a), control_read(b, "V4 both", town_b)
        timeline.append({"t": round(time.monotonic() - started), "a": read_a, "b": read_b})
        if waits(read_a) and plays(read_b):
            rotated = round(time.monotonic() - started)
            break
    row.expect(rotated is not None, "the places did not rotate within the window and a minute")
    # The control: A no longer reads (it leaves); B, alone, keeps its place through a whole window.
    alone_until = time.monotonic() + window + 30
    kept = rotated is not None
    while rotated is not None and time.monotonic() < alone_until:
        time.sleep(GUEST_READ_SECONDS)
        reading = control_read(b, "V4 B alone", town_b)
        timeline.append({"t": round(time.monotonic() - started), "b": reading})
        kept = kept and plays(reading)
    row.expect(kept, "guest B gave up its place with nobody waiting")
    row.observed = {
        "window_seconds": window,
        "maximum": accounts.get("playing_maximum"),
        "b_first": first_b,
        "rotated_after_seconds": rotated,
        "b_alone_kept": kept,
        "timeline": timeline[-14:],
    }
    return row.close()


def row_v5(stack: Stack, transcripts: Any) -> Row:
    ceiling = stack.state["accounts"]["guest_policy"]["ceiling_usd"]
    row = Row(
        "V5",
        "accounts.allowance_used_up",
        f"A guest whose allowance (USD {ceiling} per provider) is below the smallest ask any offered "
        "model reserves (A-112): its people given a model, its town plays on, the control read "
        "states model_minds_code spending_cap_reached with a sentence, and no model is asked.",
    )
    guest, entered = enter_guest(stack, transcripts, "guest")
    town = playing_town(guest, "V5", entered)
    row.expect(entered.get("status") == 201 and town is not None, "the guest has no playing town")
    if town is None:
        return row.close()
    _, society = F.society(guest, "V5", town)
    people = [p.get("id") for p in ((society or {}).get("state") or {}).get("inhabitants") or []][
        :4
    ]
    status_choice, choice = choose_model(guest, "V5", town, PERSON_ROLE, people, GOING_MODEL)
    calls_before = len(scripted_log(stack))
    deadline = time.monotonic() + PERSON_DECISION_SECONDS
    reading = control_read(guest, "V5", town)
    while reading.get("minds") != "spending_cap_reached" and time.monotonic() < deadline:
        time.sleep(5)
        reading = control_read(guest, "V5", town)
    time.sleep(GUEST_READ_SECONDS)
    after = control_read(guest, "V5", town)
    calls_after = len(scripted_log(stack))
    row.expect(
        status_choice == 200 or F.problem_code(choice) is not None,
        f"choosing the model answered {status_choice} {F.problem_code(choice)}",
    )
    row.expect(
        reading.get("minds") == "spending_cap_reached" and bool(reading.get("minds_reason")),
        f"the control read states {reading}",
    )
    row.expect(plays(after), f"the town no longer plays: {after}")
    row.expect(calls_after == calls_before, f"{calls_after - calls_before} models were asked")
    row.observed = {
        "ceiling_usd": ceiling,
        "choice": [status_choice, F.problem_code(choice)],
        "reading": reading,
        "after": after,
        "calls": calls_after - calls_before,
    }
    return row.close()


def guest_places(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    accounts = stack.state.get("accounts") or {}
    if accounts.get("playing_maximum") != 1 or not accounts.get("play_seconds"):
        raise SystemExit(
            "guest-places needs --accounts-guest-code --guest-playing-maximum 1 "
            "--guest-play-seconds S on its stack"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_v4(stack, Transcripts(out / "transcripts"))]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


def guest_allowance(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if "accounts" not in stack.state or "scripted_model" not in stack.state:
        raise SystemExit(
            "guest-allowance needs --accounts-guest-code --guest-ceiling-usd X with the scripted "
            "comparisons plan on its stack"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    transcripts = Transcripts(out / "transcripts")
    rows = [row_v5(stack, transcripts), row_kd2(stack, transcripts)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- KD1, KD2: a kind of place drafted from words ---------------------------------------------------

#: The plan KD1's stack is served by: the kind drafter answers by description, the hand-written farm
#: brief (tests/kind_briefs.py, a test fixture), a brief with no zones, or a provider failure.
KIND_DRAFT_PLAN = HERE / "plans" / "kind-draft.json"
#: How long a draft may take to end here: the client's call bound and the checks' bound, three times.
KIND_DRAFT_SECONDS = 600
#: What a provider's error status ends a draft as, where the closed list names it (A-137).
PROVIDER_FAILED_CODE = "kind_draft_model_failed"


def kind_draft_ended(c: Any, step: str, draft_id: str) -> dict[str, Any]:
    """The draft once it is no longer drafting, or its last reading at the bound."""
    deadline = time.monotonic() + KIND_DRAFT_SECONDS
    read: dict[str, Any] = {}
    while time.monotonic() < deadline:
        _, body = c.call(step, "GET", f"/worlds/kinds/drafts/{draft_id}")
        read = body if isinstance(body, dict) else {}
        if read.get("state") != "drafting":
            return read
        time.sleep(3)
    return read


def kept_kind_row(stack: Stack, kind: str) -> dict[str, Any] | None:
    """An evidence read as the owner: workspace 1's kept kind of this key, newest version."""
    found = psql_owner(
        stack,
        "select json_build_object('origin', origin, 'document', document)::text from "
        f"world_kind_version where workspace_id = '{stack.state['workspace_id']}' and "
        f"kind = '{kind}' order by version desc limit 1",
    )
    return json.loads(found) if found else None


def row_kd1(stack: Stack, transcripts: Any) -> Row:
    plan = json.loads(KIND_DRAFT_PLAN.read_text())
    words = plan["descriptions"]
    drafter = next(r["match"]["model"] for r in plan["rules"])
    row = Row(
        "KD1",
        "kinds.drafted_from_words",
        "A kind of place drafted from words (candidate-34): before anything is typed the library "
        "says drafting is offered with the closed list of refusals; a draft answers 202 at once; "
        "the farm's words end ready with a kind kept in the workspace, origin drafted, whose "
        "provenance names the role, the model, the prompt version and digest and the SHA-256 of "
        "the words and never the words, and the ended draft forgets them; a second start while "
        "one runs is 409 kind_draft_busy naming the draft only to its starter; another person in "
        "the workspace and another workspace read it 404 kind_draft_unknown; a brief making no "
        "kind ends refused by name after both repairs, with its cost; a provider failure ends "
        "refused with a code from the closed list, with its cost; a world is made of the kept "
        "kind.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    peer = F.client(stack, transcripts, "peer", "token-peer")
    _, library = w1.call("KD1", "GET", "/worlds/kinds")
    drafting = (library or {}).get("drafting") or {}
    closed = {r.get("code") for r in drafting.get("refusals") or []}
    row.expect(
        drafting.get("offered") is True and drafting.get("code") is None and bool(closed),
        f"the library says drafting {drafting.get('offered')} {drafting.get('code')}",
    )
    calls_before = len(scripted_log(stack))
    status, started = w1.call(
        "KD1", "POST", "/worlds/kinds/drafts", body={"description": words["ready"]}
    )
    started = started if isinstance(started, dict) else {}
    draft_id = str(started.get("draft_id") or "")
    row.expect(
        status == 202 and started.get("state") == "drafting" and bool(draft_id),
        f"the start answered {status} {F.problem_code(started)} {started.get('state')}",
    )
    # A second start while the first runs; the first may already have ended, which is then noted.
    status_busy, busy = w1.call(
        "KD1 busy", "POST", "/worlds/kinds/drafts", body={"description": words["ready"]}
    )
    status_peer_busy, peer_busy = peer.call(
        "KD1 peer busy", "POST", "/worlds/kinds/drafts", body={"description": words["ready"]}
    )
    status_peer_read, peer_read = peer.call("KD1 peer", "GET", f"/worlds/kinds/drafts/{draft_id}")
    status_w2_read, w2_read = w2.call("KD1 w2", "GET", f"/worlds/kinds/drafts/{draft_id}")
    busy_seen = status_busy == 409
    if busy_seen:
        row.expect(
            F.problem_code(busy) == "kind_draft_busy" and str(busy.get("draft_id")) == draft_id,
            f"the starter's second start answered {F.problem_code(busy)} naming {busy.get('draft_id')}",
        )
        row.expect(
            status_peer_busy == 409
            and F.problem_code(peer_busy) == "kind_draft_busy"
            and "draft_id" not in (peer_busy or {}),
            f"the other person's start answered {status_peer_busy} {F.problem_code(peer_busy)} "
            f"naming {(peer_busy or {}).get('draft_id')}",
        )
    row.expect(
        status_peer_read == 404 and F.problem_code(peer_read) == "kind_draft_unknown",
        f"the other person read the draft {status_peer_read} {F.problem_code(peer_read)}",
    )
    row.expect(
        status_w2_read == 404 and F.problem_code(w2_read) == "kind_draft_unknown",
        f"another workspace read the draft {status_w2_read} {F.problem_code(w2_read)}",
    )
    ready = kind_draft_ended(w1, "KD1 ready", draft_id)
    kind = (ready.get("kind") or {}) if isinstance(ready.get("kind"), dict) else {}
    row.expect(
        ready.get("state") == "ready"
        and kind.get("origin") == "drafted"
        and kind.get("source") == "workspace",
        f"the farm ended {ready.get('state')} {(ready.get('refusal') or {}).get('code')} "
        f"keeping {kind.get('kind')} {kind.get('origin')}",
    )
    row.expect(ready.get("description") == "", "the ended draft still holds the words")
    row.expect(ready.get("execution") is not None, "the ready draft shows no cost")
    kept = kept_kind_row(stack, str(kind.get("kind"))) if kind.get("kind") else None
    provenance = ((kept or {}).get("document") or {}).get("provenance") or {}
    expected_words = hashlib.sha256(words["ready"].encode("utf-8")).hexdigest()
    row.expect(
        (kept or {}).get("origin") == "drafted"
        and provenance.get("role") == "kind_drafter"
        and provenance.get("model") == drafter
        and bool(provenance.get("prompt_version"))
        and re.fullmatch(r"[0-9a-f]{64}", str(provenance.get("prompt_sha256"))) is not None
        and provenance.get("words_sha256") == expected_words,
        f"the kept kind's provenance is {provenance}",
    )
    row.expect(
        words["ready"] not in json.dumps((kept or {}).get("document") or {}),
        "the kept kind holds the words",
    )
    preset = ((kind.get("presets") or [{}])[0]).get("key")
    status_world, world = (None, {})
    if kind.get("kind"):
        status_world, world = w1.call(
            "KD1 world",
            "POST",
            f"/worlds/kinds/{kind['kind']}/worlds",
            body={"preset": preset, "title": "Q10 KD1 farm"},
        )
    row.expect(
        status_world in (200, 201) and bool((world or {}).get("entry_id")),
        f"a world of the kept kind answered {status_world} {F.problem_code(world)}",
    )
    ended: dict[str, dict[str, Any]] = {}
    for key in ("refused", "failed"):
        before = len(scripted_log(stack))
        status_key, answer = w1.call(
            f"KD1 {key}", "POST", "/worlds/kinds/drafts", body={"description": words[key]}
        )
        read = kind_draft_ended(w1, f"KD1 {key}", str((answer or {}).get("draft_id")))
        ended[key] = {
            "start": status_key,
            "state": read.get("state"),
            "refusal": read.get("refusal"),
            "execution_calls": len(((read.get("execution") or {}).get("calls")) or []),
            "scripted_calls": len(scripted_log(stack)) - before,
        }
    refused = ended["refused"]
    row.expect(
        refused["state"] == "refused"
        and (refused["refusal"] or {}).get("code") == "kind_not_drafted"
        and bool((refused["refusal"] or {}).get("detail"))
        and refused["scripted_calls"] == 3
        and refused["execution_calls"] == 3,
        f"the brief making no kind ended {refused}",
    )
    failed = ended["failed"]
    # A-137 (KINDS v2.1): where the closed list names it, a provider's error status ends the draft
    # kind_draft_model_failed, never said as the model's silence (kind_draft_unanswered).
    provider_code = PROVIDER_FAILED_CODE if PROVIDER_FAILED_CODE in closed else None
    row.expect(
        failed["state"] == "refused"
        and (failed["refusal"] or {}).get("code") in closed
        and (provider_code is None or (failed["refusal"] or {}).get("code") == provider_code)
        and failed["execution_calls"] >= 1,
        f"the provider failure ended {failed}",
    )
    row.observed = {
        "plan_sha256": hashlib.sha256(KIND_DRAFT_PLAN.read_bytes()).hexdigest(),
        "drafting": {"offered": drafting.get("offered"), "code": drafting.get("code")},
        "start": [status, started.get("state")],
        "busy": {
            "seen": busy_seen,
            "starter": [status_busy, F.problem_code(busy)],
            "other_person": [status_peer_busy, F.problem_code(peer_busy)],
            "note": None
            if busy_seen
            else "the first draft ended before the second start: not judged",
        },
        "reads": {"other_person": status_peer_read, "other_workspace": status_w2_read},
        "ready": {
            "state": ready.get("state"),
            "kind": kind.get("kind"),
            "model_id": ready.get("model_id"),
            "provenance": provenance,
            "words_sha256_expected": expected_words,
        },
        "world": [status_world, F.problem_code(world)],
        "ended": ended,
        "provider_failed_code_expected": provider_code,
        "scripted_calls": len(scripted_log(stack)) - calls_before,
    }
    return row.close()


def row_kd2(stack: Stack, transcripts: Any) -> Row:
    ceiling = stack.state["accounts"]["guest_policy"]["ceiling_usd"]
    row = Row(
        "KD2",
        "kinds.drafting_allowance",
        f"A guest whose allowance (USD {ceiling} per provider) is below one drafting attempt "
        "(candidate-34): the kinds library says drafting.code budget_exceeded before anything is "
        "typed, a start is 429 budget_exceeded with its spending member, it is no draft, and no "
        "model is asked.",
    )
    guest, entered = enter_guest(stack, transcripts, "guest-drafts")
    row.expect(entered.get("status") == 201, f"the guest entered {entered.get('status')}")
    calls_before = len(scripted_log(stack))
    _, library = guest.call("KD2", "GET", "/worlds/kinds")
    drafting = (library or {}).get("drafting") or {}
    status, refused = guest.call(
        "KD2", "POST", "/worlds/kinds/drafts", body={"description": "a small farm by a river"}
    )
    _, listed = guest.call("KD2", "GET", "/worlds/kinds/drafts")
    calls_after = len(scripted_log(stack))
    row.expect(
        drafting.get("offered") is False and drafting.get("code") == "budget_exceeded",
        f"the library says drafting {drafting.get('offered')} {drafting.get('code')}",
    )
    row.expect(
        status == 429
        and F.problem_code(refused) == "budget_exceeded"
        and isinstance((refused or {}).get("spending"), dict),
        f"the start answered {status} {F.problem_code(refused)}",
    )
    row.expect((listed or {}).get("drafts") == [], f"the guest's drafts are {listed}")
    row.expect(calls_after == calls_before, f"{calls_after - calls_before} models were asked")
    row.observed = {
        "ceiling_usd": ceiling,
        "drafting": {"offered": drafting.get("offered"), "code": drafting.get("code")},
        "start": [status, F.problem_code(refused), (refused or {}).get("spending")],
        "drafts": (listed or {}).get("drafts"),
        "calls": calls_after - calls_before,
    }
    return row.close()


def kind_drafts(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    served = (stack.state.get("scripted_model") or {}).get("plan_sha256")
    if (
        served != hashlib.sha256(KIND_DRAFT_PLAN.read_bytes()).hexdigest()
        or not stack.token_file("token-peer").exists()
        or not stack.token_file("token-2").exists()
    ):
        raise SystemExit(
            "kind-drafts needs a stack started with --workspaces 2 --peer-token --scripted-model "
            "scripts/acceptance/plans/kind-draft.json --spending process --no-derivative-worker"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_kd1(stack, Transcripts(out / "transcripts"))]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- PR1, PR2: asking for a look's generated pieces -------------------------------------------------

GENERATION_CATALOGS = Path("assets") / "catalogs" / "generation"
#: The provider a piece request's allowance is held to (docs/generated-pieces-contract.md).
GPU_PROVIDER = "nebius_ai_cloud_gpu"
#: The two shipped kinds PR1 asks pieces of, a person's kind and a kind that is not shipped.
PIECE_KINDS = ({"key": "bench", "version": 1}, {"key": "lamp_post", "version": 1})
PERSON_KIND = {"key": "knight", "version": 2}
UNSHIPPED_KIND = {"key": "nowhere_thing", "version": 1}
#: Workspace 1's GPU allowance, and workspace 2's, below one request's worst case.
PIECE_GRANT_USD, PIECE_SMALL_GRANT_USD = "0.50", "0.01"
#: What an ask may name, from the contract's section 2.
PIECE_KINDS_MAXIMUM = 16


def piece_compute(worktree: Path) -> dict[str, Any]:
    """The compute catalog's entry for the GPU provider, read from the committed file."""
    catalog = json.loads((worktree / GENERATION_CATALOGS / "piece-compute.v1.json").read_text())
    return next(e for e in catalog["entries"] if e["provider"] == GPU_PROVIDER)


def expected_estimate(compute: Mapping[str, Any], variants: Sequence[int]) -> dict[str, Any]:
    """An ask's estimate from the catalog's figures: items, warm seconds and dollars."""
    items = sum(variants)
    rate = Decimal(compute["rate_cents_per_hour"]) / 100 / 3600
    return {
        "items": items,
        "first_seconds_warm": len(variants) * compute["item_seconds_typical"],
        "all_seconds_warm": items * compute["item_seconds_typical"],
        "cold_start_seconds": compute["cold_start_seconds"],
        "usd_typical": items * compute["item_seconds_typical"] * rate,
        "usd_worst_case": items * compute["item_seconds_bound"] * rate,
        "provider": GPU_PROVIDER,
    }


def same_estimate(answered: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    try:
        return all(
            Decimal(str(answered.get(key))) == Decimal(str(value))
            if key.startswith("usd_")
            else answered.get(key) == value
            for key, value in expected.items()
        )
    except ArithmeticError:
        return False


def spending_operator(stack: Stack, worktree: Path, *arguments: str) -> dict[str, Any]:
    """The installation's own spending command as its operator (the owner, with the witness)."""
    done = subprocess.run(
        [str(worktree / ".venv" / "bin" / "python"), "-m", "exulanica.spending", *arguments],
        cwd=worktree,
        env={
            **LAUNCH.clean_environment(),
            "EXULANICA_DATABASE_URL": stack.state["database"]["owner_url_for_evidence_reads"],
            "EXULANICA_SPENDING_WITNESS_DIR": str(stack.run_dir / LAUNCH.SPENDING_WITNESS_NAME),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise SystemExit(f"exulanica.spending {arguments[0]} refused: {done.stderr.strip()[-300:]}")
    return json.loads(done.stdout)


def grant_gpu(stack: Stack, worktree: Path) -> dict[str, Any]:
    """An authority for the GPU provider and a grant to each workspace, as an operator issues them."""
    common = ("--operator", "acceptance", "--reason", "acceptance piece requests")
    authority = spending_operator(
        stack,
        worktree,
        "issue",
        "--provider",
        GPU_PROVIDER,
        "--ceiling-usd",
        "1.00",
        "--max-calls",
        "100",
        "--valid-until",
        "2027-01-01T00:00:00Z",
        *common,
    )
    grants = {}
    for workspace, usd in (
        (stack.state["workspace_id"], PIECE_GRANT_USD),
        (stack.state["other_workspaces"][0]["workspace_id"], PIECE_SMALL_GRANT_USD),
    ):
        grants[workspace] = spending_operator(
            stack,
            worktree,
            "grant",
            "--authority",
            authority["authority_id"],
            "--workspace",
            workspace,
            "--ceiling-usd",
            usd,
            "--max-calls",
            "50",
            "--valid-until",
            "2027-01-01T00:00:00Z",
            *common,
        )
    return {"authority": authority.get("authority_id"), "grants": sorted(grants)}


def made_town(c: Any, step: str, title: str) -> dict[str, Any]:
    """A town made through the kinds route, as a person makes one, with its saved entry."""
    town = next(
        (
            k
            for k in (c.call(step, "GET", "/worlds/kinds")[1] or {}).get("kinds", [])
            if k.get("kind") == "town"
        ),
        {},
    )
    _, made = c.call(
        step,
        "POST",
        "/worlds/kinds/town/worlds",
        body={"preset": ((town.get("presets") or [{}])[0]).get("key"), "title": title},
    )
    return made if isinstance(made, dict) else {}


def row_pr1(stack: Stack, transcripts: Any, worktree: Path) -> Row:
    row = Row(
        "PR1",
        "pieces.requests",
        "Asking for a look's generated pieces with no generation session (candidate-34): with an "
        f"operator's {GPU_PROVIDER} grant, an ask for two shipped kinds' pieces in a served look "
        "is 202 with two requested requests, the session off and an estimate equal to the compute "
        "catalog's figures for the requests' variants; its idempotency key answers 200 with the "
        "same requests, and with another body 409 idempotency_key_reused; the same ask with no "
        "key is 200, already waiting; the world's list is newest first; a cancel ends one "
        "cancelled and a second cancel is 409 piece_request_not_cancellable stating cancelled; a "
        "person's kind is 422 kind_without_piece, a repeated kind 422 kind_repeated, 17 kinds 422 "
        "too_many_kinds, an unshipped kind 422 kind_unknown, a manifest digest not served 422 "
        "look_not_served, an unknown world 404 unknown_world, and another workspace reads a "
        "request 404 unknown_piece_request; a workspace whose grant is below one request's worst "
        "case is 429 budget_exceeded with its spending member.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    issued = grant_gpu(stack, worktree)
    compute = piece_compute(worktree)
    styled = {
        e["pack_id"]
        for e in json.loads((worktree / GENERATION_CATALOGS / "piece-styles.v1.json").read_text())[
            "entries"
        ]
    }
    packs = (w1.call("PR1", "GET", "/world/style-packs")[1] or {}).get("packs") or []
    pack = next((p for p in packs if p.get("pack_id") in styled), None)
    town = made_town(w1, "PR1", "Q10 PR1 town")
    if pack is None or not town.get("world_id"):
        row.blocked_by.append(f"no served pack with style words ({sorted(styled)}) or no town")
        row.observed = {"issued": issued, "town": town.get("world_id")}
        return row.close()
    look = {k: pack[k] for k in ("pack_id", "version", "manifest_sha256")}
    world_id = town["world_id"]
    key = str(uuid.uuid4())
    body = {"world_id": world_id, "look": look, "kinds": list(PIECE_KINDS)}
    status, asked = w1.call(
        "PR1 ask", "POST", "/world/piece-requests", body={**body, "idempotency_key": key}
    )
    asked = asked if isinstance(asked, dict) else {}
    requests = asked.get("piece_requests") or []
    ids = [r.get("piece_request_id") for r in requests]
    expected = expected_estimate(compute, [int(r.get("variants") or 0) for r in requests])
    row.expect(
        status == 202
        and len(requests) == 2
        and all(r.get("state") == "requested" for r in requests)
        and {(r.get("kind") or {}).get("key") for r in requests} == {k["key"] for k in PIECE_KINDS}
        and (asked.get("session") or {}).get("state") == "off",
        f"the ask answered {status} {F.problem_code(asked)} with {len(requests)} requests",
    )
    row.expect(
        same_estimate(asked.get("estimate") or {}, expected),
        f"the estimate {asked.get('estimate')} is not the catalog's {expected}",
    )
    status_again, again = w1.call(
        "PR1 key", "POST", "/world/piece-requests", body={**body, "idempotency_key": key}
    )
    row.expect(
        status_again == 200
        and [r.get("piece_request_id") for r in (again or {}).get("piece_requests") or []] == ids,
        f"the same key answered {status_again} {F.problem_code(again)}",
    )
    status_other, other = w1.call(
        "PR1 key other body",
        "POST",
        "/world/piece-requests",
        body={**body, "kinds": [PIECE_KINDS[0]], "idempotency_key": key},
    )
    row.expect(
        status_other == 409 and F.problem_code(other) == "idempotency_key_reused",
        f"the key with another body answered {status_other} {F.problem_code(other)}",
    )
    status_waiting, waiting = w1.call("PR1 waiting", "POST", "/world/piece-requests", body=body)
    row.expect(
        status_waiting == 200
        and sorted(r.get("piece_request_id") for r in (waiting or {}).get("piece_requests") or [])
        == sorted(ids),
        f"the same ask with no key answered {status_waiting} {F.problem_code(waiting)}",
    )
    _, listed = w1.call("PR1 list", "GET", "/world/piece-requests", query={"world_id": world_id})
    listed_rows = (listed or {}).get("piece_requests") or []
    instants = [r.get("requested_at") for r in listed_rows]
    row.expect(
        sorted(r.get("piece_request_id") for r in listed_rows) == sorted(ids)
        and instants == sorted(instants, reverse=True),
        f"the world's list holds {[r.get('piece_request_id') for r in listed_rows]}",
    )
    status_cancel, cancelled = w1.call("PR1 cancel", "DELETE", f"/world/piece-requests/{ids[0]}")
    status_twice, twice = w1.call("PR1 cancel again", "DELETE", f"/world/piece-requests/{ids[0]}")
    row.expect(
        status_cancel == 200 and (cancelled or {}).get("state") == "cancelled",
        f"the cancel answered {status_cancel} {(cancelled or {}).get('state')}",
    )
    row.expect(
        status_twice == 409
        and F.problem_code(twice) == "piece_request_not_cancellable"
        and (twice or {}).get("state") == "cancelled",
        f"the second cancel answered {status_twice} {F.problem_code(twice)} {(twice or {}).get('state')}",
    )
    shipped = sorted(
        (
            {"key": p.name.split(".v")[0], "version": int(p.name.split(".v")[1].split(".")[0])}
            for p in (worktree / "assets" / "catalogs" / "things" / "kinds").glob("*.v*.json")
        ),
        key=lambda k: (k["key"], k["version"]),
    )
    many = shipped[: PIECE_KINDS_MAXIMUM + 1]
    refusals = {}
    for label, changes, status_wanted, code in (
        ("person", {"kinds": [PERSON_KIND]}, 422, "kind_without_piece"),
        ("repeated", {"kinds": [PIECE_KINDS[0], PIECE_KINDS[0]]}, 422, "kind_repeated"),
        ("too many", {"kinds": many}, 422, "too_many_kinds"),
        ("unshipped", {"kinds": [UNSHIPPED_KIND]}, 422, "kind_unknown"),
        ("look", {"look": {**look, "manifest_sha256": "0" * 64}}, 422, "look_not_served"),
        ("world", {"world_id": str(uuid.uuid4())}, 404, "unknown_world"),
    ):
        got_status, got = w1.call(
            f"PR1 {label}", "POST", "/world/piece-requests", body={**body, **changes}
        )
        refusals[label] = [got_status, F.problem_code(got)]
        row.expect(
            (got_status, F.problem_code(got)) == (status_wanted, code),
            f"{label}: answered {got_status} {F.problem_code(got)}, not {status_wanted} {code}",
        )
    row.expect(
        len(many) == PIECE_KINDS_MAXIMUM + 1, f"only {len(many)} shipped kind versions to name"
    )
    status_foreign, foreign = w2.call("PR1 w2 read", "GET", f"/world/piece-requests/{ids[1]}")
    row.expect(
        status_foreign == 404 and F.problem_code(foreign) == "unknown_piece_request",
        f"another workspace read a request {status_foreign} {F.problem_code(foreign)}",
    )
    town_2 = made_town(w2, "PR1 w2", "Q10 PR1 small grant")
    status_small, small = w2.call(
        "PR1 small grant",
        "POST",
        "/world/piece-requests",
        body={"world_id": town_2.get("world_id"), "look": look, "kinds": [PIECE_KINDS[0]]},
    )
    row.expect(
        status_small == 429
        and F.problem_code(small) == "budget_exceeded"
        and isinstance((small or {}).get("spending"), dict),
        f"the small grant answered {status_small} {F.problem_code(small)}",
    )
    row.observed = {
        "issued": issued,
        "look": look,
        "ask": [status, len(requests), [r.get("variants") for r in requests]],
        "estimate": asked.get("estimate"),
        "estimate_expected": {k: str(v) for k, v in expected.items()},
        "same_key": status_again,
        "key_other_body": [status_other, F.problem_code(other)],
        "waiting": status_waiting,
        "cancel": [status_cancel, status_twice, F.problem_code(twice)],
        "refusals": refusals,
        "other_workspace": [status_foreign, F.problem_code(foreign)],
        "small_grant": [status_small, F.problem_code(small), (small or {}).get("spending")],
    }
    return row.close()


def pieces(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if (stack.state.get("scripted_model") or {}).get(
        "spending"
    ) != "durable" or not stack.state.get("other_workspaces"):
        raise SystemExit(
            "pieces needs a stack started with --workspaces 2 --scripted-model "
            "scripts/acceptance/plans/spending.json --spending durable --no-derivative-worker"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_pr1(stack, Transcripts(out / "transcripts"), worktree)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- HN1: a being's hands ---------------------------------------------------------------------------

#: The plan HN1's stack is served by: every being a model runs picks the sword up when offered,
#: else gives it, else waits (A-122).
HANDS_PLAN = HERE / "plans" / "hands.json"
HANDS_MODULE = "exulanica-ability/hands/v1"
#: The modules a new society records to show each being what is near and what it remembers (MM1).
NOTICE_MODULE, REMEMBER_MODULE = "exulanica-ability/notice/v1", "exulanica-ability/remember/v1"
#: hands.json's rules by index: the one matching the memory block, the one matching the noticing
#: block (headings as the decision contract renders them), and the rest.
MEMORY_RULE, NOTICING_RULE = 0, 1
ABILITY_MODULES = Path("exulanica") / "abilities" / "ability-modules.v1.json"
BODY_PLANS = Path("assets") / "catalogs" / "things" / "body-plans.v1.json"
#: Real seconds HN1 waits for the knight to pick the sword up, then watches it held.
HANDS_SECONDS, HANDS_HOLD_SECONDS = 300, 90


def society_events(c: Any, step: str, entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    _, read = c.call(
        step, "GET", F.version_path(entry, "/society/events"), query=F.world_query(entry)
    )
    return list((read or {}).get("events") or []) if isinstance(read, dict) else []


def row_hn1(stack: Stack, transcripts: Any, worktree: Path, out: Path) -> Row:
    modules = {
        m["module"]: m for m in json.loads((worktree / ABILITY_MODULES).read_text())["modules"]
    }
    plans = {p["key"]: p for p in json.loads((worktree / BODY_PLANS).read_text())["entries"]}
    hands_events = set(modules[HANDS_MODULE]["events"])
    humanoid_sockets = {s["key"] for s in plans["humanoid"]["sockets"]}
    row = Row(
        "HN1",
        "things.hands",
        "A being's hands (candidate-34): in the newest locked scene's society of things, with "
        "each being's scene model chosen and every model answering to pick the sword up when "
        "offered, else give it, else wait (A-122): the society's first state names the hands "
        "module; within its bound the knight picks the sword up, an event of the module's kinds "
        "naming the knight and the sword, and holds it in one of the humanoid plan's sockets; the "
        "lantern spirit, whose float socket holds at most 300 mm, never picks up or is given the "
        "1,000 mm sword; replay answers the live state.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    record_path = out / "evidence" / "hn1-scene-build.json"
    built = build_scene(stack, worktree, record_path, token_file="token")
    (out / "evidence" / "hn1-scene-build.txt").write_text(built.stdout + built.stderr)
    row.expect(
        built.returncode == 0 and record_path.exists(), f"the build exited {built.returncode}"
    )
    if not record_path.exists():
        return row.close()
    record = json.loads(record_path.read_text())
    entry = F.read_entry(w1, "HN1", record["entry_id"])
    status, society = w1.call(
        "HN1",
        "POST",
        F.version_path(entry, "/society"),
        query=F.world_query(entry),
        body={"region_id": record["arrival"]["region_id"], "profile": THINGS_ENGINE},
    )
    society = society if isinstance(society, dict) else {}
    state = society.get("state") or {}
    row.expect(
        status in (200, 201) and HANDS_MODULE in (state.get("modules") or []),
        f"the society answered {status} {F.problem_code(society)} running {state.get('modules')}",
    )
    minds_record = out / "evidence" / "hn1-scene-minds.json"
    minds = build_scene(stack, worktree, minds_record, token_file="token", minds=True)
    (out / "evidence" / "hn1-scene-minds.txt").write_text(minds.stdout + minds.stderr)
    row.expect(minds.returncode == 0, f"the scene's minds step exited {minds.returncode}")
    placed = {p.get("placed_id"): p.get("id") for p in state.get("inhabitants") or []}
    knight, spirit = placed.get("knight"), placed.get("lantern-spirit")
    sword = next(
        (t.get("id") for t in state.get("things") or [] if t.get("placed_id") == "sword"), None
    )
    status_play, _ = control(w1, "HN1", entry, "playing")
    row.expect(status_play == 200, f"setting it playing answered {status_play}")
    picked: list[dict[str, Any]] = []
    deadline = time.monotonic() + HANDS_SECONDS
    while time.monotonic() < deadline and not picked:
        time.sleep(5)
        picked = [
            e
            for e in society_events(w1, "HN1", entry)
            if e.get("event_kind") == "picked_up" and e.get("subject_id") == knight
        ]
    time.sleep(HANDS_HOLD_SECONDS if picked else 0)
    events = society_events(w1, "HN1 after", entry)
    hands = [e for e in events if e.get("event_kind") in hands_events]
    _, live = F.society(w1, "HN1 after", entry)
    things = {t.get("id"): t for t in ((live or {}).get("state") or {}).get("things") or []}
    held = things.get(sword) or {}
    row.expect(
        bool(picked)
        and ((picked[0].get("document") or {}).get("thing") or {}).get("thing") == sword,
        f"the knight never picked the sword up in {HANDS_SECONDS} s: {[e.get('event_kind') for e in hands]}",
    )
    row.expect(
        held.get("held_by") == knight and held.get("socket") in humanoid_sockets,
        f"the sword is held by {held.get('held_by')} in {held.get('socket')}",
    )
    spirit_touched = [
        e
        for e in hands
        if e.get("subject_id") == spirit
        or ((e.get("document") or {}).get("thing") or {}).get("with") == spirit
    ]
    row.expect(not spirit_touched, f"the lantern spirit took part in {spirit_touched}")
    status_replay, replayed = w1.call(
        "HN1", "GET", F.version_path(entry, "/society/replay"), query=F.world_query(entry)
    )
    row.expect(
        status_replay == 200, f"the replay answered {status_replay} {F.problem_code(replayed)}"
    )
    log = scripted_log(stack)
    row.observed = {
        "plan_sha256": hashlib.sha256(HANDS_PLAN.read_bytes()).hexdigest(),
        "scene": record.get("scene"),
        "modules": state.get("modules"),
        "beings": {"knight": knight, "lantern-spirit": spirit, "sword": sword},
        "hands_events": [
            {k: e.get(k) for k in ("event_kind", "subject_id", "tick")}
            | {"thing": (e.get("document") or {}).get("thing")}
            for e in hands
        ][:12],
        "sword": {k: held.get(k) for k in ("held_by", "socket", "position_mm")},
        "entry_id": record["entry_id"],
        "scripted_calls": len(log),
        "chose": sorted({str(c.get("chose")).split(",")[0] for c in log if c.get("chose")})[:12],
        "replay": status_replay,
    }
    return row.close()


THING_CARD_PROFILE = "exulanica.thing-card/v1"
THING_CATALOGS = Path("assets") / "catalogs" / "things"


def row_tc1(stack: Stack, transcripts: Any, worktree: Path, hn1: Mapping[str, Any]) -> Row:
    abilities = {
        a["key"]: a
        for a in json.loads((worktree / THING_CATALOGS / "abilities.v1.json").read_text())[
            "entries"
        ]
    }
    shipped = [
        json.loads(path.read_text())
        for path in sorted((worktree / THING_CATALOGS / "looks").glob("*.json"))
    ]
    row = Row(
        "TC1",
        "things.card",
        "A thing's card (candidate-35), on HN1's society: the knight's card is "
        f"{THING_CARD_PROFILE} with its kind file's label and class, abilities exactly the kind's "
        "abilities whose module the society runs (abilities.v1.json, the state's modules), holding "
        "the sword, a decider and every shipped look for its body plan; the sword's card is held "
        "by the knight in HN1's socket with no decider; choosing another shipped look answers the "
        "card with only the look replaced (same minute and state digest); a sword look on the "
        "knight is 422 look_unfit and an unknown digest 422 look_not_shipped, neither written; "
        "another workspace reads it 404, and the author's placed id is not a card.",
    )
    beings = hn1.get("beings") or {}
    knight, sword = beings.get("knight"), beings.get("sword")
    if not hn1.get("entry_id") or not knight or not sword:
        row.blocked_by.append("HN1 left no society with a knight and a sword")
        return row.close()
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    entry = F.read_entry(w1, "TC1", hn1["entry_id"])
    query = F.world_query(entry)
    # Paused, so every read below sees one minute and the look's answer compares with the card.
    status_paused, _ = control(w1, "TC1", entry, "paused")
    time.sleep(GUEST_READ_SECONDS)
    path = lambda thing: F.version_path(entry, f"/society/things/{thing}")  # noqa: E731
    _, society = F.society(w1, "TC1", entry)
    state = (society or {}).get("state") or {}
    held = next((t for t in state.get("things") or [] if t.get("id") == sword), {})
    status, card = w1.call("TC1", "GET", path(knight), query=query)
    card = card if isinstance(card, dict) else {}
    kind = card.get("kind") or {}
    kind_file = (
        json.loads(
            (
                worktree
                / THING_CATALOGS
                / "kinds"
                / f"{kind.get('kind')}.v{kind.get('version')}.json"
            ).read_text()
        )
        if kind.get("kind")
        else {}
    )
    runs = set(state.get("modules") or [])
    # A-140: an ability is listed when a module the society runs serves it, by the module table's
    # own lists (a newer module version, purposeful/v2, serves what the catalog names under v1);
    # each is said in the abilities catalog's words and names a module the society runs.
    serves = {
        key
        for m in json.loads((worktree / ABILITY_MODULES).read_text())["modules"]
        if m["module"] in runs
        for key in m["abilities"]
    }
    expected_abilities = [
        {"key": a["key"], "words": abilities[a["key"]]["words"]}
        for a in kind_file.get("abilities") or []
        if a["key"] in abilities and a["key"] in serves
    ]
    plan = (kind_file.get("body") or {}).get("plan")
    expected_looks = sorted(
        (d["look"], d["version"]) for d in shipped if d.get("body_plan") == plan
    )
    listed_looks = sorted(
        (entry_.get("look"), entry_.get("version"))
        for entry_ in card.get("looks") or []
        if entry_.get("source") != "workspace"
    )
    row.expect(
        status == 200
        and card.get("profile") == THING_CARD_PROFILE
        and kind.get("label") == kind_file.get("label")
        and kind.get("class") == kind_file.get("class") == "being",
        f"the knight's card answered {status} {card.get('profile')} {kind.get('label')}",
    )
    row.expect(
        [{"key": a.get("key"), "words": a.get("words")} for a in card.get("abilities") or []]
        == expected_abilities
        and all(a.get("module") in runs for a in card.get("abilities") or [])
        and "follow" not in [a["key"] for a in card.get("abilities") or []],
        f"the card's abilities are {[a.get('key') for a in card.get('abilities') or []]}, "
        f"expected {[a['key'] for a in expected_abilities]}",
    )
    row.expect(
        [h.get("thing_id") for h in card.get("holding") or []] == [sword],
        f"the knight holds {card.get('holding')}",
    )
    row.expect(card.get("decider") is not None, "the knight's card names no decider")
    row.expect(
        listed_looks == expected_looks,
        f"the card lists looks {listed_looks}, shipped {expected_looks}",
    )
    status_sword, sword_card = w1.call("TC1 sword", "GET", path(sword), query=query)
    where = (sword_card or {}).get("where") or {}
    row.expect(
        status_sword == 200
        and where.get("held_by") == knight
        and where.get("socket") == held.get("socket")
        and (sword_card or {}).get("decider") is None,
        f"the sword's card answered {status_sword} where {where}",
    )
    worn = card.get("look") or {}
    other = next(
        (
            one
            for one in card.get("looks") or []
            if one.get("source") != "workspace" and one.get("look") != worn.get("look")
        ),
        None,
    )
    sword_look = next(iter((sword_card or {}).get("looks") or []), None)
    chosen = {k: other[k] for k in ("look", "version", "sha256")} if other else None
    status_choose, chose = w1.call(
        "TC1 look", "POST", path(knight) + "/look", query=query, body={"look": chosen}
    )
    chose = chose if isinstance(chose, dict) else {}
    same_rest = {k: v for k, v in chose.items() if k != "look"} == {
        k: v for k, v in card.items() if k != "look"
    }
    row.expect(
        status_choose == 200
        and (chose.get("look") or {}).get("look") == (chosen or {}).get("look")
        and (chose.get("look") or {}).get("chosen_by_owner") is True
        and same_rest,
        f"choosing {chosen} answered {status_choose} wearing {(chose.get('look') or {}).get('look')}; "
        f"the rest of the card unchanged {same_rest}",
    )
    refusals = {}
    for label, look, code in (
        (
            "unfit",
            {k: (sword_look or {}).get(k) for k in ("look", "version", "sha256")},
            "look_unfit",
        ),
        ("not shipped", {**(chosen or {}), "sha256": "0" * 64}, "look_not_shipped"),
    ):
        got, answer = w1.call(
            f"TC1 {label}", "POST", path(knight) + "/look", query=query, body={"look": look}
        )
        refusals[label] = [got, F.problem_code(answer)]
        row.expect(
            (got, F.problem_code(answer)) == (422, code),
            f"{label}: answered {got} {F.problem_code(answer)}",
        )
    _, after = w1.call("TC1 after", "GET", path(knight), query=query)
    row.expect(
        ((after or {}).get("look") or {}).get("look") == (chosen or {}).get("look"),
        f"after the refusals the knight wears {((after or {}).get('look') or {}).get('look')}",
    )
    status_foreign, _ = w2.call("TC1 w2", "GET", path(knight), query=query)
    status_placed, _ = w1.call("TC1 placed id", "GET", path("knight"), query=query)
    row.expect(status_foreign == 404, f"another workspace read the card {status_foreign}")
    row.expect(status_placed in (404, 422), f"the placed id answered {status_placed}")
    row.observed = {
        "paused": status_paused,
        "card": [status, card.get("profile"), kind.get("kind"), kind.get("label")],
        "runs": sorted(runs),
        "abilities": [a.get("key") for a in card.get("abilities") or []],
        "holding": card.get("holding"),
        "decider": card.get("decider"),
        "looks": listed_looks,
        "sword_where": where,
        "worn_before": worn.get("look"),
        "chosen": [status_choose, (chose.get("look") or {}).get("look"), same_rest],
        "refusals": refusals,
        "other_workspace": status_foreign,
        "placed_id": status_placed,
    }
    return row.close()


def row_mm1(stack: Stack, worktree: Path, hn1: Mapping[str, Any]) -> Row:
    modules = {
        m["module"]: m for m in json.loads((worktree / ABILITY_MODULES).read_text())["modules"]
    }
    plan = json.loads(HANDS_PLAN.read_text())
    row = Row(
        "MM1",
        "minds.notice_and_remember",
        "A new world's beings notice and remember (candidate-36): HN1's society records "
        f"{NOTICE_MODULE} and {REMEMBER_MODULE}, both built in ability-modules.v1.json; among the "
        "scripted model's requests at least one carries the noticing block ('Around you now:') and "
        "a later one the memory block ('You remember (from what happened here').",
    )
    log = scripted_log(stack)
    rules = [c.get("rule") for c in log]
    noticing = [i for i, r in enumerate(rules) if r in (MEMORY_RULE, NOTICING_RULE)]
    memory = [i for i, r in enumerate(rules) if r == MEMORY_RULE]
    recorded = set(hn1.get("modules") or [])
    row.expect(
        all(modules.get(m, {}).get("status") == "built" for m in (NOTICE_MODULE, REMEMBER_MODULE)),
        "ability-modules.v1.json does not state both modules built",
    )
    row.expect(
        {NOTICE_MODULE, REMEMBER_MODULE} <= recorded,
        f"the society records {sorted(recorded)}",
    )
    row.expect(bool(noticing), f"no request carried the noticing block: rules {rules[:20]}")
    row.expect(
        bool(memory) and bool(noticing) and memory[-1] >= noticing[0],
        f"no request carried the memory block after the noticing one: rules {rules[:20]}",
    )
    row.observed = {
        "plan_sha256": hashlib.sha256(HANDS_PLAN.read_bytes()).hexdigest(),
        "headings": [
            plan["rules"][MEMORY_RULE]["match"]["contains"],
            plan["rules"][NOTICING_RULE]["match"]["contains"],
        ],
        "calls": len(rules),
        "with_noticing": len(noticing),
        "with_memory": len(memory),
        "first": {
            "noticing": noticing[0] if noticing else None,
            "memory": memory[0] if memory else None,
        },
        "modules": sorted(recorded),
    }
    return row.close()


#: The most simulated minutes HR1 steps a society for an asked act to be done.
ASKED_MINUTES = 15


def hands_request(
    c: Any,
    step: str,
    entry: Mapping[str, Any],
    subject: str,
    ability: str,
    thing: str,
    with_id: str | None = None,
) -> tuple[int, Any]:
    """A direct request asking ``subject`` for a hands act, from the society's current state."""
    _, now = F.society(c, step, entry)
    intent: dict[str, Any] = {"kind": "hands", "ability": ability, "thing_id": thing}
    if with_id is not None:
        intent["with_id"] = with_id
    return c.call(
        step,
        "POST",
        F.version_path(entry, "/society/actions"),
        query=F.world_query(entry),
        body={
            "idempotency_key": str(uuid.uuid4()),
            "base_tick": (now or {}).get("current_tick"),
            "base_state_sha256": (now or {}).get("state_sha256"),
            "subject_id": subject,
            "intent": intent,
        },
    )


def row_hr1(stack: Stack, transcripts: Any, worktree: Path, out: Path) -> Row:
    plans = {p["key"]: p for p in json.loads((worktree / BODY_PLANS).read_text())["entries"]}
    float_most = max(s["length_mm_maximum"] for s in plans["bodiless"]["sockets"])
    row = Row(
        "HR1",
        "things.hands_request",
        "A person asks a being to use its hands (candidate-36): on workspace 2's own build of the "
        "newest locked scene, a society of things nobody's model runs, the owner asks the knight to "
        f"pick the sword up and within {ASKED_MINUTES} minutes it does, the event recorded as asked "
        "(asked_to_pick_up) after a user_action_requested event; asking the lantern spirit, whose "
        f"socket holds at most {float_most} mm, to pick the sword up is refused act_not_offered; "
        "a thing the society does not hold is refused thing_gone (each 409 invalid_society_action "
        "naming its reason, A-140); give without the other being is 422; on a town society, which "
        "takes no directed actions, a hands request is refused engine_takes_no_directed_actions.",
    )
    w2 = F.client(stack, transcripts, "w2", "token-2")
    record_path = out / "evidence" / "hr1-scene-build.json"
    built = build_scene(stack, worktree, record_path, token_file="token-2")
    (out / "evidence" / "hr1-scene-build.txt").write_text(built.stdout + built.stderr)
    if not record_path.exists():
        row.expect(False, f"the build exited {built.returncode}")
        return row.close()
    record = json.loads(record_path.read_text())
    entry = F.read_entry(w2, "HR1", record["entry_id"])
    status, society = w2.call(
        "HR1",
        "POST",
        F.version_path(entry, "/society"),
        query=F.world_query(entry),
        body={"region_id": record["arrival"]["region_id"], "profile": THINGS_ENGINE},
    )
    state = (society or {}).get("state") or {}
    placed = {p.get("placed_id"): p.get("id") for p in state.get("inhabitants") or []}
    knight, spirit = placed.get("knight"), placed.get("lantern-spirit")
    sword = next(
        (t.get("id") for t in state.get("things") or [] if t.get("placed_id") == "sword"), None
    )
    row.expect(
        status in (200, 201) and knight and spirit and sword, f"the society answered {status}"
    )
    if not (knight and spirit and sword):
        return row.close()
    refusals = {}
    # A-140: a direct request the state cannot honour is 409 invalid_society_action naming its
    # reason in the detail, as every directed request's refusal is answered and the page reads it
    # (society-directed-action.ts, REFUSAL_WORDS).
    for label, args, wanted in (
        ("spirit", (spirit, "pick_up", sword), (409, "act_not_offered")),
        ("gone", (knight, "pick_up", str(uuid.uuid4())), (409, "thing_gone")),
        ("give without", (knight, "give", sword), (422, None)),
    ):
        got, answer = hands_request(w2, f"HR1 {label}", entry, *args)
        reason = (
            (answer or {}).get("detail") if isinstance((answer or {}).get("detail"), str) else None
        )
        refusals[label] = [got, F.problem_code(answer), reason]
        row.expect(
            got == wanted[0]
            and (
                wanted[1] is None
                or (F.problem_code(answer) == "invalid_society_action" and reason == wanted[1])
            ),
            f"{label}: answered {got} {F.problem_code(answer)} {reason}, not {wanted}",
        )
    status_ask, asked = hands_request(w2, "HR1 ask", entry, knight, "pick_up", sword)
    row.expect(
        status_ask in (200, 201, 202),
        f"asking the knight answered {status_ask} {F.problem_code(asked)}",
    )
    picked: list[dict[str, Any]] = []
    for _ in range(ASKED_MINUTES):
        _, now = F.society(w2, "HR1 step", entry)
        F.advance(w2, "HR1 step", entry, now or {})
        events = society_events(w2, "HR1 events", entry)
        picked = [
            e
            for e in events
            if e.get("event_kind") == "picked_up" and e.get("subject_id") == knight
        ]
        if picked:
            break
    requested = [
        e
        for e in society_events(w2, "HR1 events", entry)
        if e.get("event_kind") == "user_action_requested" and e.get("subject_id") == knight
    ]
    row.expect(
        bool(picked)
        and ((picked[0].get("document") or {}).get("thing") or {}).get("thing") == sword
        and "asked_to_pick_up" in json.dumps(picked[0]),
        f"the knight's asked pick-up: {picked[:1]}",
    )
    row.expect(bool(requested), "no user_action_requested event names the knight")
    town = generated_town(w2, "HR1 town", "Q10 HR1 town")
    _, town_society = F.society(w2, "HR1 town", town)
    person = next(
        (p.get("id") for p in ((town_society or {}).get("state") or {}).get("inhabitants") or []),
        None,
    )
    status_town, town_answer = hands_request(
        w2, "HR1 town", town, person, "pick_up", str(uuid.uuid4())
    )
    town_reason = (town_answer or {}).get("detail")
    row.expect(
        status_town == 409 and town_reason == "engine_takes_no_directed_actions",
        f"a town's hands request answered {status_town} {F.problem_code(town_answer)} {town_reason}",
    )
    row.observed = {
        "society": [status, (society or {}).get("profile")],
        "refusals": refusals,
        "asked": [status_ask, F.problem_code(asked)],
        "picked_up": [
            {k: e.get(k) for k in ("event_kind", "subject_id", "tick")}
            | {"document": e.get("document")}
            for e in picked[:1]
        ],
        "requested": len(requested),
        "town": [status_town, F.problem_code(town_answer), town_reason],
        "float_socket_mm": float_most,
    }
    return row.close()


def hands(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    served = (stack.state.get("scripted_model") or {}).get("plan_sha256")
    if served != hashlib.sha256(HANDS_PLAN.read_bytes()).hexdigest() or not stack.state.get(
        "society_playback"
    ):
        raise SystemExit(
            "hands needs a fresh database and a stack started with --workspaces 2 "
            "--society-of-things --society-playback --scripted-model "
            "scripts/acceptance/plans/hands.json --spending process --no-derivative-worker"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    transcripts = Transcripts(out / "transcripts")
    hn1 = row_hn1(stack, transcripts, worktree, out)
    mm1 = row_mm1(stack, worktree, hn1.observed)
    rows = [
        hn1,
        mm1,
        row_tc1(stack, transcripts, worktree, hn1.observed),
        row_hr1(stack, transcripts, worktree, out),
    ]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- V7, PR2: every guest takes a turn; a guest asks for pieces --------------------------------------

#: The guests V7 enters, in order.
TURN_GUESTS = ("guest-a", "guest-b", "guest-c")


def row_v7(stack: Stack, transcripts: Any) -> tuple[Row, Any]:
    accounts = stack.state["accounts"]
    window = int(accounts["play_seconds"])
    bound = len(TURN_GUESTS) * window + GUEST_ROTATION_GRACE_SECONDS
    row = Row(
        "V7",
        "accounts.guest_turns",
        f"With one guest's town playing at a time and a play window of {window} s (candidate-34): "
        f"guests A, B and C enter in turn and keep reading their control every {GUEST_READ_SECONDS} "
        f"s; within {bound} s of C's entry each of the three has read its town playing at least "
        "once.",
    )
    entered = {}
    for name in TURN_GUESTS:
        guest, came = enter_guest(stack, transcripts, name)
        town = playing_town(guest, f"V7 {name}", came)
        row.expect(came.get("status") == 201 and town is not None, f"{name} has no playing town")
        if town is None:
            return row.close(), None
        entered[name] = (guest, town)
    started = time.monotonic()
    played_at: dict[str, int | None] = dict.fromkeys(TURN_GUESTS)
    timeline = []
    while time.monotonic() < started + bound and None in played_at.values():
        readings = {
            name: control_read(guest, f"V7 {name}", town) for name, (guest, town) in entered.items()
        }
        t = round(time.monotonic() - started)
        timeline.append(
            {"t": t, **{n: [r.get("running"), r.get("code")] for n, r in readings.items()}}
        )
        for name, reading in readings.items():
            if played_at[name] is None and plays(reading):
                played_at[name] = t
        time.sleep(GUEST_READ_SECONDS)
    row.expect(
        all(t is not None for t in played_at.values()),
        f"not every guest played within {bound} s: {played_at}",
    )
    row.observed = {
        "window_seconds": window,
        "maximum": accounts.get("playing_maximum"),
        "first_played_after_seconds": played_at,
        "timeline": timeline[-24:],
    }
    return row.close(), entered[TURN_GUESTS[0]]


def row_pr2(stack: Stack, entered: Any, worktree: Path) -> Row:
    row = Row(
        "PR2",
        "pieces.guest",
        "A guest asking for pieces of its town's look while no generation session runs "
        "(candidate-34) is 409 generation_session_off, and nothing is requested.",
    )
    if entered is None:
        row.blocked_by.append("V7 entered no guest with a town")
        return row.close()
    guest, town = entered
    styled = {
        e["pack_id"]
        for e in json.loads((worktree / GENERATION_CATALOGS / "piece-styles.v1.json").read_text())[
            "entries"
        ]
    }
    packs = (guest.call("PR2", "GET", "/world/style-packs")[1] or {}).get("packs") or []
    pack = next((p for p in packs if p.get("pack_id") in styled), None)
    if pack is None:
        row.blocked_by.append("no served pack with style words")
        return row.close()
    look = {k: pack[k] for k in ("pack_id", "version", "manifest_sha256")}
    status, refused = guest.call(
        "PR2",
        "POST",
        "/world/piece-requests",
        body={"world_id": town["world_id"], "look": look, "kinds": [PIECE_KINDS[0]]},
    )
    _, listed = guest.call(
        "PR2", "GET", "/world/piece-requests", query={"world_id": town["world_id"]}
    )
    row.expect(
        status == 409 and F.problem_code(refused) == "generation_session_off",
        f"the guest's ask answered {status} {F.problem_code(refused)}",
    )
    row.expect(
        (listed or {}).get("piece_requests") == [],
        f"the town lists {(listed or {}).get('piece_requests')}",
    )
    row.observed = {
        "ask": [status, F.problem_code(refused)],
        "listed": (listed or {}).get("piece_requests"),
    }
    return row.close()


def guest_turns(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    accounts = stack.state.get("accounts") or {}
    if accounts.get("playing_maximum") != 1 or not accounts.get("play_seconds"):
        raise SystemExit(
            "guest-turns needs --accounts-guest-code --guest-playing-maximum 1 "
            "--guest-play-seconds S on its stack"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    transcripts = Transcripts(out / "transcripts")
    v7, entered = row_v7(stack, transcripts)
    rows = [v7, row_pr2(stack, entered, worktree)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- LK1: a look offered after a world is drafted ---------------------------------------------------

#: The plan LK1's stack is served by: the drafter always drafts a small town, and the look chooser
#: answers by description (offered, none, an unlisted look, a failure from every model).
LOOK_OFFER_PLAN = HERE / "plans" / "look-offer.json"
LOOK_OFFER_CASES = (
    ("offered", "offered", None),
    ("none", "none", None),
    ("refused", "none", "answer_refused"),
    ("failed", "unavailable", "failed"),
)


def row_lk1(stack: Stack, transcripts: Any) -> Row:
    plan = json.loads(LOOK_OFFER_PLAN.read_text())
    descriptions = plan["descriptions"]
    row = Row(
        "LK1",
        "worlds.look_offer",
        "A world drafted from words carries a look offer (A-113): for a description the chooser "
        "answers with a listed look and copied words, offered with that pack as the library lists "
        "it and those words; for one it answers no look, none; for one it names an unlisted look "
        "twice, none with reason answer_refused; for one every model fails, unavailable with "
        "reason failed. Each draft still proposes the drafter's small town.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    listing = {
        p.get("pack_id"): p
        for p in (w1.call("LK1", "GET", "/world/style-packs")[1] or {}).get("packs") or []
    }
    offers = {}
    for key, state, reason in LOOK_OFFER_CASES:
        status, drafted = w1.call(
            f"LK1 {key}",
            "POST",
            "/worlds/specification/drafts",
            body={"description": descriptions[key]},
        )
        offer = (drafted or {}).get("look_offer") or {}
        preset = ((drafted or {}).get("proposal") or {}).get("preset")
        offers[key] = {
            "status": status,
            "preset": preset,
            **{
                k: offer.get(k)
                for k in ("state", "reason", "pack_id", "version", "look_words", "prompt_version")
            },
        }
        row.expect(
            status == 200 and preset == "small_town",
            f"{key}: the draft answered {status} {F.problem_code(drafted)} proposing {preset}",
        )
        row.expect(
            offer.get("state") == state and offer.get("reason") == reason,
            f"{key}: the offer reads {offer.get('state')} {offer.get('reason')}",
        )
        if key == "offered":
            listed = listing.get("exulanica.cozy-town") or {}
            row.expect(
                offer.get("pack_id") == "exulanica.cozy-town"
                and offer.get("version") == listed.get("version")
                and offer.get("manifest_sha256") == listed.get("manifest_sha256")
                and offer.get("look_words") == ["cozy"],
                f"the offer names {offer.get('pack_id')} {offer.get('version')} with {offer.get('look_words')}",
            )
        else:
            row.expect(
                offer.get("pack_id") is None, f"{key}: the offer names {offer.get('pack_id')}"
            )
    row.observed = {
        "plan_sha256": hashlib.sha256(LOOK_OFFER_PLAN.read_bytes()).hexdigest(),
        "offers": offers,
    }
    return row.close()


def drafts(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    served = (stack.state.get("scripted_model") or {}).get("plan_sha256")
    if served != hashlib.sha256(LOOK_OFFER_PLAN.read_bytes()).hexdigest():
        raise SystemExit(
            "drafts needs a stack started with --scripted-model scripts/acceptance/plans/look-offer.json "
            "--spending process"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_lk1(stack, Transcripts(out / "transcripts"))]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


def guests(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    served = (stack.state.get("scripted_model") or {}).get("plan_sha256")
    if (
        "accounts" not in stack.state
        or "edge" not in stack.state
        or served != hashlib.sha256(COMPARISONS_PLAN.read_bytes()).hexdigest()
    ):
        raise SystemExit(
            "guests needs a stack started with --accounts-guest-code --edge-port PORT --tiles "
            "--scripted-model scripts/acceptance/plans/comparisons.json --spending durable "
            "--society-playback --no-derivative-worker"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_v1(stack, transcripts)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


def comparisons(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    served = (stack.state.get("scripted_model") or {}).get("plan_sha256")
    if served != hashlib.sha256(COMPARISONS_PLAN.read_bytes()).hexdigest():
        raise SystemExit(
            "comparisons needs a stack started with --scripted-model "
            "scripts/acceptance/plans/comparisons.json --society-playback --workspaces 2 "
            "--read-only-token"
        )
    if not stack.state.get("society_playback") or not stack.token_file("token-read").exists():
        raise SystemExit("comparisons needs --society-playback and --read-only-token")
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    transcripts = Transcripts(out / "transcripts")
    started = dt.datetime.now(dt.UTC).isoformat()
    h1, town = row_h1(stack, transcripts, out)
    rows = [
        h1,
        row_h2(stack, transcripts, out, town),
        row_h3(stack, transcripts, out, town),
        row_h4(stack, transcripts, out, town),
    ]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    compare = commands.add_parser("comparisons")
    compare.add_argument("--worktree", required=True)
    compare.add_argument("--out", required=True)
    people = commands.add_parser("characters")
    people.add_argument("--worktree", required=True)
    people.add_argument("--out", required=True)
    page = commands.add_parser("catalog")
    page.add_argument("--worktree", required=True)
    page.add_argument("--out", required=True)
    mapped = commands.add_parser("reviews")
    mapped.add_argument("--worktree", required=True)
    mapped.add_argument("--out", required=True)
    mapped.add_argument("--deliveries", required=True, help="the foundation packet's deliveries")
    both = commands.add_parser("roles")
    both.add_argument("--worktree", required=True)
    both.add_argument("--out", required=True)
    withdrawn = commands.add_parser("withdrawal")
    withdrawn.add_argument("--worktree", required=True)
    withdrawn.add_argument("--out", required=True)
    stored = commands.add_parser("assets")
    stored.add_argument("--worktree", required=True)
    stored.add_argument("--out", required=True)
    made = commands.add_parser("made-with")
    made.add_argument("--worktree", required=True)
    made.add_argument("--out", required=True)
    library = commands.add_parser("packs")
    library.add_argument("--worktree", required=True)
    library.add_argument("--out", required=True)
    kept = commands.add_parser("kinds")
    kept.add_argument("--worktree", required=True)
    kept.add_argument("--out", required=True)
    opened = commands.add_parser("door")
    opened.add_argument("--worktree", required=True)
    opened.add_argument("--out", required=True)
    shipped = commands.add_parser("things")
    shipped.add_argument("--worktree", required=True)
    shipped.add_argument("--out", required=True)
    crossed = commands.add_parser("crossings")
    crossed.add_argument("--worktree", required=True)
    crossed.add_argument("--out", required=True)
    crossed.add_argument("--bridge-credential", help="the file declare-luanti wrote beside its out")
    declaring = commands.add_parser("declare-luanti")
    declaring.add_argument("--worktree", required=True)
    declaring.add_argument("--out", required=True)
    lived = commands.add_parser("society-of-things")
    lived.add_argument("--worktree", required=True)
    lived.add_argument("--out", required=True)
    for name in (
        "guest-places",
        "guest-allowance",
        "drafts",
        "kind-drafts",
        "pieces",
        "hands",
        "guest-turns",
        "picture-rights",
    ):
        guested = commands.add_parser(name)
        guested.add_argument("--worktree", required=True)
        guested.add_argument("--out", required=True)
    entered = commands.add_parser("guests")
    entered.add_argument("--worktree", required=True)
    entered.add_argument("--out", required=True)
    asked = commands.add_parser("references")
    asked.add_argument("--worktree", required=True)
    asked.add_argument("--out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    commands = {
        "comparisons": comparisons,
        "assets": assets,
        "characters": characters,
        "withdrawal": withdrawal,
        "roles": roles,
        "reviews": reviews,
        "catalog": catalog,
        "made-with": made_with,
        "packs": packs,
        "kinds": kinds,
        "references": references,
        "things": things,
        "door": door,
        "guests": guests,
        "society-of-things": society_of_things,
        "crossings": crossings,
        "guest-places": guest_places,
        "guest-allowance": guest_allowance,
        "drafts": drafts,
        "kind-drafts": kind_drafts,
        "pieces": pieces,
        "hands": hands,
        "guest-turns": guest_turns,
        "picture-rights": picture_rights,
        "declare-luanti": declare_luanti,
    }
    return commands[arguments.command](arguments)


if __name__ == "__main__":
    sys.exit(main())
