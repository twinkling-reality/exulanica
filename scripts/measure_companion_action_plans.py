#!/usr/bin/env python3
"""The Companion's action planning, measured against a frozen set of requests (campaign P1).

    python3 scripts/measure_companion_action_plans.py fixtures --worktree W --out DIR
    python3 scripts/measure_companion_action_plans.py scripted-plan --set SET --fixtures FIX
                                                     --worktree W --answers expected|question
                                                     --out PLAN.json
    python3 scripts/measure_companion_action_plans.py grant --worktree W --ceiling-usd USD
                                                     --hours H --out DIR
    python3 scripts/measure_companion_action_plans.py run --worktree W --set SET --fixtures FIX
                                                     --passes N --ceiling-usd USD --out DIR
                                                     [--arm model|scripted|no-model]
    python3 scripts/measure_companion_action_plans.py score --set SET --run DIR --prefix-file FILE

The set (``docs/evaluation/2026-10-02-companion-action-plans-set.json``) holds each request's
words, its fixture and page context, and the answer expected of ``POST /selection/actions``,
written before any call. This harness sends each request to that route on a running acceptance
stack (``scripts/acceptance/launch.py up --workspaces 3``) and compares the answer with the
expectation by the set's own ``expectation_rules``.

It is an independent client: it imports nothing from ``exulanica``, speaks HTTP through the
repository's standard-library developer client by way of the acceptance driver
(``scripts/acceptance/foundation.py``), and holds no credential outside the request header. Its
one evidence read is marked as such: the row counts and row digests of the tables a plan must
leave as it found them, read through the owner URL the launcher recorded, before and after every request.

``fixtures`` makes the worlds through the application, one workspace each: ``square`` (a market
stall, a lamp post and two benches), ``square-people`` (the same, with people brought in, time
paused at speed 1) and ``bare`` (a starter with nothing placed). ``square-playing`` is
``square-people`` with time playing, set by ``run`` around the requests that name it; each switch
is also the watch's positive control, since the watch must see the change it makes.

``run`` stops itself, before the next request, on any of the set's stop rules: a watched table
changed across a request, a planted value appeared in a step, a request with no server answer, the
campaign's cost reaching ``--ceiling-usd`` (or the next request, at the most one has cost so far,
passing it), or provider errors passing 10 percent of a pass. A request's cost is its execution
record's sum, or where the record cannot price an attempt, the ledger's charge across the request,
which holds that attempt at its reservation (amendment 2). Latency is wall time measured here,
outside any quiet window unless the record says otherwise.

``score`` reads the prefix (kept outside the repository until the result is recorded), checks it
against the set's digests, and scores each split: held-out is the result; development is the part
that may be seen while the harness is checked.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent


def _foundation() -> Any:
    name = "exulanica_acceptance_foundation"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / "acceptance" / "foundation.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


F = _foundation()

SET_KIND = "exulanica.evaluation.companion-action-plans-set/v1"
RECORD_PROFILE = "exulanica.digest-bound-record/v1"
ROUTE = "/selection/actions"
#: Which token file each fixture's workspace answers to; ``square-playing`` is ``square-people``.
FIXTURE_TOKENS = {"square": "token", "square-people": "token-2", "bare": "token-3"}
#: How long the harness waits for one plan. The server's own bound for one plan on 61d99d9a is
#: 150 s, as ``action_bound_seconds`` sums it: three structured-extraction calls, each walking a
#: chain of two models at the manifest's 25 s. This is that bound with a margin of 150 s for the
#: version, capability, preview and clock reads around the calls, so the server, never the
#: harness, decides when a plan has failed. A test holds it above the candidate's bound.
PLAN_TIMEOUT_SECONDS = 300.0
PLAYING = "square-playing"
FIXTURE_OF = {
    "square": "square",
    "square-people": "square-people",
    PLAYING: "square-people",
    "bare": "bare",
}
#: The objects of ``square`` and ``square-people``, in the order they are placed: name, kind and
#: where, in millimetres in the starter region: all in its far half, so the near half is clear.
SQUARE_OBJECTS = (
    ("stall", "cc0.market-stall", (6000, 0, 9000)),
    ("lamp", "cc0.lamp-post", (-6000, 0, 7000)),
    ("bench-1", "cc0.bench", (-6000, 0, 10000)),
    ("bench-2", "cc0.bench", (-2000, 0, 10000)),
)
#: Where the page says the person points, and where they stand, facing the near half: an
#: arrangement is anchored 8 m in front of the viewer, clear of the objects and of where people
#: arrive (the starter's spawn, 4 m into the far half).
POINTED = {"x_mm": 2000, "y_mm": 0, "z_mm": -7000, "yaw_microradians": 0, "scale_milli": 1000}
VIEWER = {"x_mm": 0, "z_mm": 2000, "yaw_microradians": 3141593}
CONTEXTS = ("full", "no-placement", "no-viewer", "no-role")
SELECTED = "+selected:"
#: The tables a plan must leave as it found them: the route's own tests' list, and the playback
#: controls and clock a simulation plan reads.
WATCHED = (
    "world_alternate_version",
    "world_alternate_object",
    "world_alternate_version_edit",
    "world_style_proposal",
    "world_style_preview",
    "world_style_version",
    "world_style_audit_event",
    "saved_world_entry",
    "world_society",
    "world_society_event",
    "world_society_control",
    "world_society_control_event",
    "world_society_input",
    "world_clock",
    "world_clock_event",
)
#: A simulation step that moves time on by a minute, as its route key names it.
CONTROL_STEP = "POST /world/versions/{version_id}/society/control/steps"
#: A provider error: the request did not come back answered, or an attempt failed or timed out.
FAILED_ATTEMPTS = ("failed", "timed_out")
ERROR_SHARE = Decimal("0.10")
NO_MODEL = (503, "provider_credential_absent")
ARMS = ("model", "scripted", "no-model")


# -- the set ---------------------------------------------------------------------------------------


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def load_set(path: Path) -> tuple[dict[str, Any], str]:
    """The set's record, refused unless its digest holds, and the file's own digest."""
    raw = path.read_bytes()
    document = json.loads(raw)
    if document.get("profile") != RECORD_PROFILE:
        raise SystemExit(f"{path} is not a {RECORD_PROFILE} record")
    record = document["record"]
    if hashlib.sha256(canonical(record)).hexdigest() != document["record_sha256"]:
        raise SystemExit(f"{path}: the record does not reproduce its record_sha256")
    if record.get("kind") != SET_KIND:
        raise SystemExit(f"{path} holds {record.get('kind')!r}, not {SET_KIND}")
    return record, hashlib.sha256(raw).hexdigest()


def split_of(prefix: str, utterance: str) -> str:
    """The set's split rule: development when sha256(prefix + utterance) is 0 mod 5."""
    drawn = int(hashlib.sha256((prefix + utterance).encode("utf-8")).hexdigest(), 16)
    return "development" if drawn % 5 == 0 else "held_out"


def splits(record: Mapping[str, Any], prefix: str) -> dict[str, str]:
    """Each request's split, refused unless the prefix is the one the set pre-registered."""
    rule = record["split"]
    if hashlib.sha256(prefix.encode("utf-8")).hexdigest() != rule["prefix_sha256"]:
        raise SystemExit("the prefix is not the one the set's prefix_sha256 names")
    assignment = [[r["id"], split_of(prefix, r["utterance"])] for r in record["records"]]
    encoded = json.dumps(assignment, separators=(",", ":")).encode()
    if hashlib.sha256(encoded).hexdigest() != rule["assignment_sha256"]:
        raise SystemExit("the splits drawn do not reproduce the set's assignment_sha256")
    return dict((identifier, split) for identifier, split in assignment)


# -- requests ----------------------------------------------------------------------------------------


def parse_context(context: str) -> tuple[str, str | None]:
    base, _, selected = context.partition(SELECTED)
    if base not in CONTEXTS:
        raise ValueError(f"unknown page context {context!r}")
    return base, selected or None


def request_body(item: Mapping[str, Any], fixtures: Mapping[str, Any]) -> dict[str, Any]:
    """The route's body for one request, from its fixture and its named page context."""
    fixture = fixtures[FIXTURE_OF[item["fixture"]]]
    base, selected = parse_context(item["context"])
    context: dict[str, Any] = {}
    if base != "no-placement":
        context["placement"] = {"region_id": fixture["region_id"], "transform": dict(POINTED)}
    if base != "no-viewer":
        context["viewer"] = {**VIEWER, "region_id": fixture["region_id"]}
    if selected is not None:
        context["selected_object_id"] = fixture["objects"][selected]
    body: dict[str, Any] = {
        "version_id": fixture["version_id"],
        "base_state_sha256": fixture["state_sha256"],
        "context": context,
        "utterance": item["utterance"],
    }
    if base != "no-role":
        body["origin_role"] = "fictional"
    if item.get("appearance_basis") is not None:
        body["appearance_basis"] = item["appearance_basis"]
    return body


# -- what came back, and whether it is what was expected -------------------------------------------


def _name(value: Any, names: Mapping[str, str]) -> Any:
    return names.get(value, f"unlisted:{value}") if isinstance(value, str) else value


def observe(plan: Mapping[str, Any], names: Mapping[str, str]) -> dict[str, Any]:
    """An answer in the set's terms: objects by their fixture names, simulation by its action."""
    seen: dict[str, Any] = {"outcome": plan.get("outcome"), "kind": plan.get("kind")}
    steps = plan.get("steps") or []
    if plan.get("outcome") == "plan" and plan.get("kind") == "simulation":
        actions = [step.get("action") or {} for step in steps]
        advancing = [
            a for a, s in zip(actions, steps, strict=True) if s["operation"] == CONTROL_STEP
        ]
        first = actions[0] if actions else {}
        seen["simulation"] = {
            "operation": "advance" if advancing else first.get("operation"),
            "speed": None if advancing else first.get("speed"),
            "minutes": len(advancing) if advancing else None,
        }
    elif plan.get("outcome") == "plan":
        observed_steps = []
        for step in steps:
            action = step.get("action") or {}
            shown: dict[str, Any] = {"operation": action.get("operation")}
            for slot in ("asset_key", "arrangement_key"):
                if action.get(slot) is not None:
                    shown[slot] = action[slot]
            if action.get("object_id") is not None:
                shown["object"] = _name(action["object_id"], names)
            observed_steps.append(shown)
        seen["steps"] = observed_steps
    clarification = plan.get("clarification")
    if clarification:
        seen["clarification"] = {
            "code": clarification.get("code"),
            "candidates": sorted(
                str(names.get(c.get("value"), c.get("value")))
                for c in clarification.get("candidates") or []
            ),
        }
    refusal = plan.get("refusal")
    if refusal:
        seen["refusal"] = {
            "code": refusal.get("code"),
            "alternatives": sorted(refusal.get("alternatives") or []),
        }
    return seen


def compare(expected: Mapping[str, Any] | None, seen: Mapping[str, Any]) -> dict[str, Any]:
    """Each part of the expectation, matched or not, and whether all of it matched."""
    if expected is None:
        return {"scored": False}
    parts = {
        "outcome": seen.get("outcome") == expected["outcome"],
        "kind": seen.get("kind") == expected["kind"],
    }
    if "steps" in expected:
        wanted = expected["steps"]
        got = seen.get("steps") or []
        if expected["kind"] == "appearance":
            got = got[: len(wanted)]
        parts["steps"] = got == wanted
    if "simulation" in expected:
        wanted = expected["simulation"]
        got = seen.get("simulation") or {}
        parts["simulation"] = got.get("operation") == wanted["operation"] and all(
            got.get(field) == wanted[field]
            for field in ("speed", "minutes")
            if wanted[field] is not None
        )
    if "clarification" in expected:
        got = seen.get("clarification") or {}
        parts["clarification"] = got == {
            "code": expected["clarification"]["code"],
            "candidates": sorted(expected["clarification"]["candidates"]),
        }
    if "refusal" in expected:
        got = seen.get("refusal") or {}
        parts["refusal"] = got == {
            "code": expected["refusal"]["code"],
            "alternatives": sorted(expected["refusal"]["alternatives"]),
        }
    return {"scored": True, "parts": parts, "exact": all(parts.values())}


def planted_found(plan: Mapping[str, Any], planted: Sequence[str]) -> list[str]:
    """Every planted value that appears in a request a step would send, or in a clarification's
    typed actions: bodies, binds, queries, actions and preview bodies."""
    if not planted:
        return []
    carried: list[Any] = []
    for step in plan.get("steps") or []:
        carried += [step.get(key) for key in ("body", "bind", "query", "action", "body_from")]
        preview = step.get("preview")
        if isinstance(preview, Mapping):
            carried.append(preview.get("body"))
    clarification = plan.get("clarification") or {}
    carried.append(clarification.get("actions"))
    text = json.dumps(carried, sort_keys=True)
    return [value for value in planted if value in text]


def calls_of(body: Any) -> list[dict[str, Any]]:
    """The execution record's attempts, from a plan or from a problem body that carries one."""
    execution = body.get("execution") if isinstance(body, Mapping) else None
    return list((execution or {}).get("calls") or [])


def cost_of(calls: Sequence[Mapping[str, Any]]) -> tuple[Decimal, bool]:
    """What the attempts cost by their own record, and whether every cost is known."""
    total = Decimal(0)
    known = True
    for call in calls:
        if call.get("cost_basis") == "unknown":
            known = False
        if call.get("usd") is not None:
            total += Decimal(str(call["usd"]))
    return total, known


def served_by(calls: Sequence[Mapping[str, Any]]) -> tuple[list[str], bool]:
    """The models that answered a request's calls, by the execution record, and whether any
    call was answered by another model than the one requested (a fallback in the role's chain).
    A fallback answer is reported apart, never pooled with the requested model's."""
    served = sorted({str(c["served_model"]) for c in calls if c.get("served_model")})
    fallback = any(
        c.get("used_fallback")
        or (c.get("served_model") and c.get("served_model") != c.get("requested_model"))
        for c in calls
    )
    return served, fallback


def provider_error(status: int, calls: Sequence[Mapping[str, Any]]) -> bool:
    """A provider error, for the 10 percent rule: no server answer, an answer with no execution
    record, or an attempt that failed or timed out. A reply the client refused (a truncated draft)
    is the model's answer and is scored as one; it is not an error (root's ruling of 22:51)."""
    return (
        status == 0
        or (status != 200 and not calls)
        or any(call.get("outcome") in FAILED_ATTEMPTS for call in calls)
    )


def request_cost(calls: Sequence[Mapping[str, Any]], ledger_usd: Decimal) -> tuple[Decimal, str]:
    """What one request cost and where that figure comes from. Every attempt priced: the
    execution record's sum. Any attempt the record cannot price (cost_basis unknown): the ledger's
    charge across the request, which holds such an attempt at its reservation (amendment 2)."""
    total, known = cost_of(calls)
    return (total, "execution_record") if known else (ledger_usd, "ledger")


class Budget:
    """The campaign's cost from its execution records, and the stop it calls for."""

    def __init__(self, ceiling: Decimal, spent: Decimal = Decimal(0)) -> None:
        self.ceiling = ceiling
        self.spent = spent
        self.largest = Decimal(0)

    def add(self, cost: Decimal) -> None:
        self.spent += cost
        self.largest = max(self.largest, cost)

    def stop_before_next(self) -> str | None:
        if self.spent >= self.ceiling:
            return f"the execution records reached USD {self.spent}, the ceiling of {self.ceiling}"
        if self.spent + self.largest > self.ceiling:
            return (
                f"the next request, at the most one has cost ({self.largest}), would pass the "
                f"ceiling of {self.ceiling} from USD {self.spent}"
            )
        return None


def errors_stop(errors: int, planned: int) -> str | None:
    if Decimal(errors) > ERROR_SHARE * planned:
        return f"provider errors reached {errors} of a pass of {planned} requests"
    return None


# -- the stack ---------------------------------------------------------------------------------------


def watched_counts(stack: Any) -> dict[str, list[Any]]:
    """Evidence read: each watched table's row count and the digest of its rows, through the
    owner URL the launcher recorded. The digest is what sees a row changed in place, which a
    count alone would not."""
    database = stack.state["database"]
    query = (
        "select json_build_object("
        + ", ".join(
            f"'{table}', (select json_build_array(count(*), "
            f"md5(coalesce(string_agg(row_text, '|' order by row_text), ''))) "
            f"from (select t::text as row_text from {table} t) rows)"
            for table in WATCHED
        )
        + ")"
    )
    completed = subprocess.run(
        [
            str(Path(database["postgres_bin"]) / "psql"),
            "-At",
            "-X",
            "-c",
            query,
            database["owner_url_for_evidence_reads"],
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def ledger_spent(stack: Any) -> Decimal:
    """Evidence read: what the spending ledger has charged the run's workspaces, each attempt at
    its settled cost or, until it settles, its reservation."""
    database = stack.state["database"]
    workspaces = [stack.state["workspace_id"]] + [
        w["workspace_id"] for w in stack.state.get("other_workspaces", [])
    ]
    listed = ", ".join(f"'{workspace}'" for workspace in workspaces)
    completed = subprocess.run(
        [
            str(Path(database["postgres_bin"]) / "psql"),
            "-At",
            "-X",
            "-c",
            "select coalesce(sum(coalesce(settled_usd, reserved_usd)), 0) from spending_reservation "
            f"where workspace_id in ({listed})",
            database["owner_url_for_evidence_reads"],
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return Decimal(completed.stdout.strip())


def clients(stack: Any, transcripts: Any, timeout: float | None = None) -> dict[str, Any]:
    """One client per fixture's workspace; ``timeout`` replaces the developer client's default."""
    made = {
        name: F.client(stack, transcripts, name, token) for name, token in FIXTURE_TOKENS.items()
    }
    if timeout is not None:
        for name, c in made.items():
            c.http = F.WorldClient(
                stack.base_url,
                stack.token_file(FIXTURE_TOKENS[name]).read_text(),
                timeout=timeout,
                on_exchange=transcripts.recorder(name, lambda c=c: c.step),
            )
    return made


def ask(c: Any, step: str, query: Mapping[str, str], body: Mapping[str, Any]) -> tuple[int, Any]:
    """One plan request. A failure on the client's side (its wait ended, the connection dropped)
    is answered as status 0 with no execution record, so its cost is unknown and the run stops
    on the pre-registered rule instead of crashing."""
    try:
        return c.call(step, "POST", ROUTE, query=query, body=body)
    except (OSError, F.ClientError) as failed:
        return 0, {"code": f"client_failure:{type(failed).__name__}"}


def placement(entry: Mapping[str, Any], name: str, kind: str, where: Sequence[int]) -> dict:
    x, y, z = where
    return {
        "base_state_sha256": entry["authored_state_sha256"],
        "source": {"kind": "reviewed_asset", "asset_key": kind},
        "placement": {
            "subject_id": f"p1-{name}",
            "region_id": F.STARTER_REGION,
            "transform": {
                "x_mm": x,
                "y_mm": y,
                "z_mm": z,
                "yaw_microradians": 0,
                "scale_milli": 1000,
            },
            "origin_role": "fictional",
        },
        "saved_entry": F.resume_point(entry),
    }


def expect(status: int, wanted: int | tuple[int, ...], what: str, body: Any) -> None:
    if status not in (wanted if isinstance(wanted, tuple) else (wanted,)):
        raise SystemExit(f"{what} answered {status}: {json.dumps(body)[:400]}")


def control(c: Any, entry: Mapping[str, Any], mode: str) -> dict[str, Any]:
    """Set the version's playback to ``mode`` at speed 1, from its current revision; a control
    already there is left as it is."""
    path = F.version_path(entry, "/society/control")
    status, read = c.call("control", "GET", path, query=F.world_query(entry))
    expect(status, 200, "the control read", read)
    if read.get("mode") == mode and read.get("speed") == 1:
        return read
    status, written = c.call(
        "control",
        "PUT",
        path,
        query=F.world_query(entry),
        body={"base_revision": read["revision"], "mode": mode, "speed": 1},
    )
    expect(status, 200, f"setting the control {mode}", written)
    return written


def fixture_read(c: Any, entry: Mapping[str, Any]) -> dict[str, Any]:
    status, version = c.call("fixture", "GET", F.version_path(entry), query=F.world_query(entry))
    expect(status, 200, "the version read", version)
    status, capabilities = c.call(
        "fixture", "GET", F.version_path(entry, "/capabilities"), query=F.world_query(entry)
    )
    expect(status, 200, "the capability read", capabilities)
    regions = (capabilities.get("regions") or {}).get("region_ids") or []
    return {
        "entry_id": entry["entry_id"],
        "world_id": entry["world_id"],
        "version_id": entry["authored_version_id"],
        "state_sha256": version["state_sha256"],
        "region_id": F.STARTER_REGION if F.STARTER_REGION in regions else regions[0],
        "regions": regions,
    }


def make_fixtures(stack: Any, out: Path) -> dict[str, Any]:
    transcripts = F.Transcripts(out / "transcripts")
    by_name = clients(stack, transcripts)
    fixtures: dict[str, Any] = {}
    for name, c in by_name.items():
        status, entry = c.call(
            "fixture", "POST", "/world-entries/starter", body={"title": f"P1 {name}"}
        )
        expect(status, 200, f"the {name} starter", entry)
        objects: dict[str, str] = {}
        if name != "bare":
            for subject, kind, where in SQUARE_OBJECTS:
                status, applied = c.call(
                    "fixture",
                    "POST",
                    F.version_path(entry, "/compositions/apply"),
                    query=F.world_query(entry),
                    body=placement(entry, subject, kind, where),
                )
                expect(status, (200, 201), f"placing {subject} in {name}", applied)
                objects[subject] = f"p1-{subject}"
                entry = F.read_entry(c, "fixture", entry["entry_id"])
        if name == "square-people":
            status, created = c.call(
                "fixture",
                "POST",
                F.version_path(entry, "/society"),
                query=F.world_query(entry),
                body={"region_id": F.STARTER_REGION, "profile": F.SAVED_WORLD_SOCIETY},
            )
            expect(status, 200, "bringing people in", created)
            control(c, entry, "paused")
        fixtures[name] = {
            **fixture_read(c, entry),
            "objects": objects,
            "token_file": FIXTURE_TOKENS[name],
        }
    return fixtures


def names_of(fixture: Mapping[str, Any]) -> dict[str, str]:
    return {object_id: name for name, object_id in fixture["objects"].items()}


# -- the run ------------------------------------------------------------------------------------------


def ordered(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The set's order, with the playing fixture's requests together so time is switched twice."""
    return [r for r in records if r["fixture"] != PLAYING] + [
        r for r in records if r["fixture"] == PLAYING
    ]


def run(arguments: argparse.Namespace) -> int:
    worktree = F.LAUNCH.checkout(arguments.worktree)
    stack = F.Stack.read(worktree)
    record, set_sha256 = load_set(Path(arguments.set))
    fixtures = json.loads(Path(arguments.fixtures).read_text())
    out = Path(arguments.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    results_path = out / "results.jsonl"
    if results_path.exists():
        raise SystemExit(f"{results_path} exists: a run never appends to another")
    transcripts = F.Transcripts(out / "transcripts")
    by_fixture = clients(stack, transcripts, timeout=PLAN_TIMEOUT_SECONDS)
    people = by_fixture["square-people"]
    people_entry = F.read_entry(people, "start", fixtures["square-people"]["entry_id"])
    budget = Budget(Decimal(arguments.ceiling_usd))
    items = ordered(record["records"])
    summary: dict[str, Any] = {
        "started_at": dt.datetime.now(dt.UTC).isoformat(),
        "arm": arguments.arm,
        "set_sha256": set_sha256,
        "set_record_sha256": hashlib.sha256(canonical(record)).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "launcher_run": stack.state.get("run_dir"),
        "passes_planned": arguments.passes,
        "ceiling_usd": str(budget.ceiling),
        "watch_controls": [],
        "stopped": None,
        "latency_note": arguments.latency_note,
    }

    def switch(mode: str) -> None:
        before = watched_counts(stack)
        control(people, people_entry, mode)
        after = watched_counts(stack)
        seen = before != after
        summary["watch_controls"].append({"switched_to": mode, "watch_saw_it": seen})
        if not seen:
            raise SystemExit("the watch did not see the harness's own control change")

    stop: str | None = None
    passes_done = 0
    for number in range(1, arguments.passes + 1):
        errors = 0
        playing = False
        for item in items:
            stop = budget.stop_before_next() if arguments.arm != "no-model" else None
            if stop:
                break
            if item["fixture"] == PLAYING and not playing:
                switch("playing")
                playing = True
            fixture = fixtures[FIXTURE_OF[item["fixture"]]]
            c = by_fixture[FIXTURE_OF[item["fixture"]]]
            before = watched_counts(stack)
            charged_before = ledger_spent(stack)
            started = time.monotonic()
            status, body = ask(
                c,
                f"pass-{number}:{item['id']}",
                {"world_id": fixture["world_id"]},
                request_body(item, fixtures),
            )
            wall_ms = round((time.monotonic() - started) * 1000)
            after = watched_counts(stack)
            ledger_usd = ledger_spent(stack) - charged_before
            calls = calls_of(body)
            cost, cost_from = request_cost(calls, ledger_usd)
            budget.add(cost)
            plan = body if status == 200 and isinstance(body, Mapping) else {}
            seen = observe(plan, names_of(fixture)) if plan else {}
            found = planted_found(plan, item.get("planted") or [])
            changed = {t: [before[t], after[t]] for t in WATCHED if before[t] != after[t]}
            failed = provider_error(status, calls)
            served, fallback = served_by(calls)
            errors += failed
            line = {
                "pass": number,
                "id": item["id"],
                "status": status,
                "problem": None if status == 200 else F.problem_code(body),
                "wall_ms": wall_ms,
                "prompt_version": (
                    (body.get("execution") or {}).get("prompt_version")
                    if isinstance(body, Mapping)
                    else None
                ),
                "observed": seen,
                # An answer that is not a plan scores as a miss, never as unscored.
                "match": compare(item["expected"], seen),
                "planted_found": found,
                "watched_changed": changed,
                "provider_error": failed,
                "served_models": served,
                "fallback": fallback,
                "calls": [
                    {
                        key: call.get(key)
                        for key in (
                            "role",
                            "requested_model",
                            "served_model",
                            "outcome",
                            "cost_basis",
                            "usd",
                            "latency_ms",
                            "prompt_tokens",
                            "completion_tokens",
                            "attempts",
                            "used_fallback",
                        )
                    }
                    for call in calls
                ],
                "usd": str(cost),
                "cost_from": cost_from,
                "ledger_usd": str(ledger_usd),
                "spent_usd": str(budget.spent),
            }
            with results_path.open("a") as handle:
                handle.write(json.dumps(line, sort_keys=True) + "\n")
            if changed:
                stop = f"{item['id']} pass {number}: watched tables changed {changed}"
            elif found:
                stop = f"{item['id']} pass {number}: planted values in a step {found}"
            elif status == 0:
                stop = f"{item['id']} pass {number}: no server answer"
            elif arguments.arm != "no-model":
                stop = errors_stop(errors, len(items))
            if stop:
                break
        if playing:
            switch("paused")
        if stop:
            break
        passes_done = number
    summary.update(
        {
            "finished_at": dt.datetime.now(dt.UTC).isoformat(),
            "passes_completed": passes_done,
            "stopped": stop,
            "spent_usd": str(budget.spent),
            "fixtures_unchanged": all(
                fixture_read(
                    by_fixture[name],
                    F.read_entry(by_fixture[name], "end", fixtures[name]["entry_id"]),
                )["state_sha256"]
                == fixtures[name]["state_sha256"]
                for name in FIXTURE_TOKENS
            ),
        }
    )
    (out / "run.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: summary[k] for k in ("passes_completed", "stopped", "spent_usd")}))
    return 0 if stop is None else 3


# -- scoring --------------------------------------------------------------------------------------------


def percentile(values: Sequence[int], share: float) -> int | None:
    if not values:
        return None
    ranked = sorted(values)
    return ranked[min(len(ranked) - 1, max(0, round(share * len(ranked)) - 1))]


def floor_score(records: Sequence[Mapping[str, Any]], identifiers: set[str]) -> dict[str, int]:
    """The score of answering every request ``question``, from the expectations alone."""
    scored = [r for r in records if r["id"] in identifiers and r["expected"] is not None]
    return {
        "scored": len(scored),
        "exact": sum(r["expected"]["outcome"] == "question" for r in scored),
    }


def score(arguments: argparse.Namespace) -> int:
    record, set_sha256 = load_set(Path(arguments.set))
    prefix = Path(arguments.prefix_file).read_text().strip()
    split = splits(record, prefix)
    by_id = {r["id"]: r for r in record["records"]}
    run_dir = Path(arguments.run)
    lines = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines()]
    summary = json.loads((run_dir / "run.json").read_text())
    if summary["set_sha256"] != set_sha256:
        raise SystemExit("the run was made against another set")
    passes = sorted({line["pass"] for line in lines})
    report: dict[str, Any] = {"set_sha256": set_sha256, "run": summary, "passes": {}}
    for split_name in ("held_out", "development"):
        members = {i for i, s in split.items() if s == split_name}
        per_pass = {}
        for number in passes:
            chosen = [x for x in lines if x["pass"] == number and x["id"] in members]
            strata: dict[str, dict[str, int]] = {}
            for line in chosen:
                item = by_id[line["id"]]
                row = strata.setdefault(
                    item["stratum"],
                    {
                        "requests": 0,
                        "scored": 0,
                        "exact": 0,
                        "outcome": 0,
                        "kind": 0,
                        "not_drafted": 0,
                        "provider_errors": 0,
                        "planted_found": 0,
                        "fallback_answers": 0,
                        "fallback_exact": 0,
                    },
                )
                row["requests"] += 1
                if line.get("fallback"):
                    # Answered by a fallback model: counted apart, never in the scored model's.
                    row["fallback_answers"] += 1
                    row["fallback_exact"] += bool(line["match"].get("exact"))
                    row["planted_found"] += bool(line["planted_found"])
                    continue
                row["provider_errors"] += line["provider_error"]
                row["planted_found"] += bool(line["planted_found"])
                row["not_drafted"] += (line["observed"].get("refusal") or {}).get(
                    "code"
                ) == "not_drafted"
                match = line["match"]
                if match.get("scored"):
                    row["scored"] += 1
                    row["exact"] += match["exact"]
                    row["outcome"] += match["parts"]["outcome"]
                    row["kind"] += match["parts"]["kind"]
            overall = {
                key: sum(row[key] for row in strata.values())
                for key in next(iter(strata.values()), {})
            }
            walls = [x["wall_ms"] for x in chosen]
            per_pass[str(number)] = {
                "strata": strata,
                "overall": overall,
                "wall_ms_p50": percentile(walls, 0.5),
                "wall_ms_p95": percentile(walls, 0.95),
                "usd": str(sum((Decimal(x["usd"]) for x in chosen), Decimal(0))),
            }
        agreement = {"requests": 0, "same_every_pass": 0}
        for identifier in sorted(members):
            answers = [canonical(x["observed"]) for x in lines if x["id"] == identifier]
            if len(answers) == len(passes) and len(passes) > 1:
                agreement["requests"] += 1
                agreement["same_every_pass"] += len(set(answers)) == 1
        report["passes"][split_name] = {
            "per_pass": per_pass,
            "agreement": agreement,
            "floor_all_question": floor_score(record["records"], members),
            "no_model_baseline": "503 provider_credential_absent for every request",
        }
    out = run_dir / "score.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(out)
    return 0


# -- the scripted model, for checking this harness ------------------------------------------------------


def escaped(text: str) -> str:
    """``text`` as it appears inside the serialized messages the scripted model matches."""
    return json.dumps(text)[1:-1]


def object_labels(fixture: Mapping[str, Any], selected: str | None) -> dict[str, str]:
    """The labels the drafter is shown for this fixture's objects: the selected object first,
    then newest first by the edit that placed each."""
    newest_first = [name for name, _, _ in reversed(SQUARE_OBJECTS) if name in fixture["objects"]]
    order = ([selected] if selected else []) + [n for n in newest_first if n != selected]
    return {name: f"object-{index}" for index, name in enumerate(order, start=1)}


def drafted_world_edit(item: Mapping[str, Any], fixture: Mapping[str, Any]) -> dict[str, Any]:
    """The world-edit form a model meeting the expectation fills."""
    _, selected = parse_context(item["context"])
    labels = object_labels(fixture, selected)
    expected = item["expected"]
    steps: list[dict[str, Any]] = []
    if expected["outcome"] == "refused":
        steps.append({"operation": "other"})
    elif expected["outcome"] == "clarify":
        code = expected["clarification"]["code"]
        candidates = expected["clarification"]["candidates"]
        if code == "object_ambiguous":
            operation = (
                "remove_object"
                if "emove" in item["utterance"] or "away" in item["utterance"]
                else "move_object"
            )
            steps.append({"operation": operation, "objects": [labels[c] for c in candidates]})
        elif code == "asset_ambiguous":
            steps.append({"operation": "place_object", "kinds": list(candidates)})
        elif code == "object_required":
            steps.append({"operation": "move_object"})
        elif code == "viewer_required":
            steps.append({"operation": "place_arrangement", "arrangements": ["small_square"]})
        else:
            asset = "cc0.bench" if "bench" in item["utterance"] else "cc0.lamp-post"
            steps.append({"operation": "place_object", "kinds": [asset]})
    else:
        for step in expected["steps"]:
            drafted: dict[str, Any] = {"operation": step["operation"]}
            if "asset_key" in step:
                drafted["kinds"] = [step["asset_key"]]
            if "object" in step:
                drafted["objects"] = [labels[step["object"]]]
            if "arrangement_key" in step:
                drafted["arrangements"] = [step["arrangement_key"]]
            steps.append(drafted)
    for drafted in steps:
        drafted.setdefault("kinds", [])
        drafted.setdefault("arrangements", [])
        if fixture["objects"]:
            drafted.setdefault("objects", [])
    return {"steps": steps}


def drafted_simulation(item: Mapping[str, Any]) -> dict[str, Any]:
    expected = item["expected"]
    if expected["outcome"] == "refused":
        return {"action": "other", "speed": None, "minutes": None}
    if expected["outcome"] == "clarify":
        action = (
            "advance" if expected["clarification"]["code"] == "minutes_required" else "set_speed"
        )
        return {"action": action, "speed": None, "minutes": None}
    wanted = expected["simulation"]
    return {
        "action": wanted["operation"],
        "speed": wanted["speed"] if wanted["operation"] in ("set_speed",) else None,
        "minutes": wanted["minutes"],
    }


AUTHORED_PROFILE = """
import json
from exulanica.world import STYLE_REGISTRY
print(json.dumps(sorted(STYLE_REGISTRY.profiles[("origin-landscape", 1)].controls)))
"""


def authored_draft(worktree: Path) -> dict[str, Any]:
    """An authored-design draft the candidate's own style registry accepts, read by a child
    interpreter of the candidate, so this file imports nothing from it."""
    controls = json.loads(
        subprocess.run(
            [str(worktree / ".venv" / "bin" / "python"), "-c", AUTHORED_PROFILE],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    parameters = {key.replace("-", "_"): None for key in controls}
    parameters["horizon_softness"] = 0.8
    return {
        "profile": "origin-landscape@1",
        "parameters": parameters,
        "spoken": "The horizon would sit softer.",
        "impossible": None,
    }


def scripted_plan(arguments: argparse.Namespace) -> int:
    """A scripted-model plan that answers every request in the set: as expected (``expected``),
    or ``question`` to everything, which must score the set's floor."""
    record, _ = load_set(Path(arguments.set))
    fixtures = json.loads(Path(arguments.fixtures).read_text())
    worktree = F.LAUNCH.checkout(arguments.worktree)
    authored = authored_draft(worktree) if arguments.answers == "expected" else None
    rules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in record["records"]:
        words = item["utterance"]
        expected = item["expected"]
        kind = (
            "question" if arguments.answers == "question" or expected is None else expected["kind"]
        )
        if words not in seen:
            rules.append(
                {
                    "match": {"contains": escaped(f'The sentence:\n"""{words}"""')},
                    "content": json.dumps({"kind": kind}),
                }
            )
        seen.add(words)
        if kind in ("question", "capabilities"):
            continue
        fixture = fixtures[FIXTURE_OF[item["fixture"]]]
        if kind == "world_edit":
            draft = drafted_world_edit(item, fixture)
        elif kind == "simulation":
            draft = drafted_simulation(item)
        else:
            draft = authored
        rules.append(
            {
                "match": {"contains": escaped(f'The request:\n"""{words}"""')},
                "content": json.dumps(draft),
            }
        )
    plan = {
        "profile": "q10-scripted-model-plan/v1",
        "bounds": {"ceiling_usd": "1.00", "max_calls": 5000},
        "rules": rules,
    }
    Path(arguments.out).write_text(json.dumps(plan, indent=2) + "\n")
    print(f"{len(rules)} rules")
    return 0


# -- the grant ------------------------------------------------------------------------------------------


def grant(arguments: argparse.Namespace) -> int:
    """One authority bounded at the campaign's ceiling, and a grant under it for each of the
    campaign's workspaces: the authority's ceiling bounds them together."""
    worktree = F.LAUNCH.checkout(arguments.worktree)
    stack = F.Stack.read(worktree)
    out = Path(arguments.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    transcripts = F.Transcripts(out / "transcripts")
    by_name = clients(stack, transcripts)
    provider = F.spending_of(by_name["square"], "grant")["provider"]
    until = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=arguments.hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    decided = ["--operator", "acc-p1", "--reason", "P1 Companion action planning campaign"]
    status, issued = F.operator(
        stack,
        "issue",
        "--provider",
        provider,
        "--ceiling-usd",
        arguments.ceiling_usd,
        "--max-calls",
        str(arguments.max_calls),
        "--valid-until",
        until,
        *decided,
    )
    authority = issued.get("authority_id")
    if status != 0 or not authority:
        raise SystemExit(f"issuing the authority failed: {issued}")
    workspaces = [
        stack.state["workspace_id"],
        *(w["workspace_id"] for w in stack.state.get("other_workspaces", [])),
    ]
    grants = []
    for workspace in workspaces:
        status, granted = F.operator(
            stack,
            "grant",
            "--authority",
            authority,
            "--workspace",
            workspace,
            "--ceiling-usd",
            arguments.ceiling_usd,
            "--max-calls",
            str(arguments.max_calls),
            "--valid-until",
            until,
            *decided,
        )
        if status != 0:
            raise SystemExit(f"granting {workspace} failed: {granted}")
        grants.append(granted)
    document = {
        "provider": provider,
        "authority": issued,
        "grants": grants,
        "valid_until": until,
        "ceiling_usd": arguments.ceiling_usd,
    }
    (out / "grant.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"authority_id": authority, "grants": len(grants)}))
    return 0


def fixtures_command(arguments: argparse.Namespace) -> int:
    worktree = F.LAUNCH.checkout(arguments.worktree)
    stack = F.Stack.read(worktree)
    if len(stack.state.get("other_workspaces", [])) < 2:
        raise SystemExit("fixtures needs a stack started with --workspaces 3")
    out = Path(arguments.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    fixtures = make_fixtures(stack, out)
    (out / "fixtures.json").write_text(json.dumps(fixtures, indent=2, sort_keys=True) + "\n")
    print(out / "fixtures.json")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    made = commands.add_parser("fixtures")
    made.add_argument("--worktree", required=True)
    made.add_argument("--out", required=True)
    made.set_defaults(handler=fixtures_command)
    plan = commands.add_parser("scripted-plan")
    plan.add_argument("--set", required=True)
    plan.add_argument("--fixtures", required=True)
    plan.add_argument("--worktree", required=True)
    plan.add_argument("--answers", choices=("expected", "question"), required=True)
    plan.add_argument("--out", required=True)
    plan.set_defaults(handler=scripted_plan)
    granted = commands.add_parser("grant")
    granted.add_argument("--worktree", required=True)
    granted.add_argument("--ceiling-usd", required=True)
    granted.add_argument("--max-calls", type=int, default=1000)
    granted.add_argument("--hours", type=int, default=3)
    granted.add_argument("--out", required=True)
    granted.set_defaults(handler=grant)
    ran = commands.add_parser("run")
    ran.add_argument("--worktree", required=True)
    ran.add_argument("--set", required=True)
    ran.add_argument("--fixtures", required=True)
    ran.add_argument("--passes", type=int, required=True)
    ran.add_argument("--ceiling-usd", required=True)
    ran.add_argument("--arm", choices=ARMS, required=True)
    ran.add_argument("--latency-note", default="measured outside a quiet window")
    ran.add_argument("--out", required=True)
    ran.set_defaults(handler=run)
    scored = commands.add_parser("score")
    scored.add_argument("--set", required=True)
    scored.add_argument("--run", required=True)
    scored.add_argument("--prefix-file", required=True)
    scored.set_defaults(handler=score)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    sys.exit(main())
