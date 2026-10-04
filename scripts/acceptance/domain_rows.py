#!/usr/bin/env python3
"""The domain rows the foundation driver does not check, against a running acceptance stack.

    .venv/bin/python scripts/acceptance/domain_rows.py comparisons --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/domain_rows.py assets      --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/domain_rows.py characters  --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/domain_rows.py catalog     --worktree PATH --out DIR

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
import struct
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
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
        status_again in (200, 201) and again == start,
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


def drawing_drift(worktree: Path, record_head: str) -> dict[str, Any]:
    """The drawing files that differ between the commit a record measured and the candidate's
    checkout, computed here (A-56), each with whether A-56 lets it differ: a seeds catalog file
    keeping its entries, or the catalogs module changing only the seeds catalog's versions. The
    files are the ones the candidate's own digest reads; a file at the record's head the candidate
    no longer has is found by its directory's glob."""
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
    globs = sorted({f":(glob){Path(relative(p)).parent}/*.json" for p in listed["data"]})
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
    checkout = rehearse.main_checkout(stack.worktree)
    gpu, quiet = checkout / ".exulanica/bin/gpu-slot", checkout / ".exulanica/bin/quiet-slot"
    command = rehearse.browser_slot_command(
        gpu if gpu.exists() else None,
        quiet if quiet.exists() else None,
        ["node", str(CATALOG_RUNNER), str(plan_file)],
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
    }
    return commands[arguments.command](arguments)


if __name__ == "__main__":
    sys.exit(main())
