#!/usr/bin/env python3
"""Do a society of things' beings say something new when shown what they said and who they are?

    uv run python scripts/measure_society_line_variety.py preregister
    uv run python scripts/measure_society_line_variety.py run

**The question.** Asked by the same open model, beings that are shown what they said lately and
what they are, and told to say something new or do something else (arm B, the prompt as it ships),
repeat themselves less than beings shown neither and told neither (arm A): every line a being says
is compared with every earlier line it said and with the last line said to it, and a line whose
word set shares at least half its words with any of them (token-set Jaccard 0.5 or more) is a near
repeat.

**The scene** is the "Three strangers" development scene (``scripts/demo/scenes/three-strangers.v2.json``)
in memory: its things placed on the tests' own starter square at the scene's offsets, with three
villagers the routine runs. Its knight, traveller and lantern spirit each have the run's model for
a mind. Every minute each of the three that is due is asked through the product's path: the request
(``role_request``), the one hosted ask (``decision_host.ask``) with the host's token bound and the
contract's deadline, the receipt (``role_receipt``), and the minute (the decision roles' receipts,
the planner, the things phase). No database, no world of anybody's.

**The arms.** B is the person role's terms for the society of things as the registry states them.
A is the same but for three things: the instruction without the sentences that tell the model to
say something new and that it need not answer (``A_LEAVES_OUT``), its first sentence naming neither
what the being is nor what it said, and the request's context without ``being`` and ``said``. Each
model runs both arms for ``MINUTES`` minutes, A first, from the same seed.

**Spend.** The key is read from the environment, ``KEY_VARIABLE`` only, and reaches nothing but the
client; the bound is read from ``BUDGET_VARIABLE`` and refused above ``BOUND_USD``; the run stops at
``MAX_CALLS`` calls or the bound, whichever comes first, and then records itself as incomplete with
no verdict. Every record is written by this script and none is edited after, under ``OUTPUT``,
which git ignores: per-model figures stay unpublished until the provider's terms allow it.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
# The tree this script measures, ahead of any installed copy of the package.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from measure_society_person_models import (  # noqa: E402
    _bound,
    _manifest_sha256,
    _measured,
    _read_record,
    _sha256,
    _tree,
    _write_new,
    _write_new_bytes,
)

from exulanica.canonical import canonical_json  # noqa: E402

OUTPUT: Final = ".exulanica/line-variety"
PREREGISTRATION: Final = f"{OUTPUT}/preregistration.json"
RECORD: Final = f"{OUTPUT}/record.json"
SCRIPT: Final = "scripts/measure_society_line_variety.py"
SCRIPT_AS_RUN: Final = f"{OUTPUT}/measure_society_line_variety-as-run.py.txt"
SCENE: Final = "scripts/demo/scenes/three-strangers.v2.json"
ENGINE: Final = "exulanica-society/v7"
#: The scene's minds, as its document names them for the Three strangers.
MODELS: Final = (
    "nvidia/Nemotron-3_5-Lightning",
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "deepseek-ai/DeepSeek-V4-Flash-0731",
)
ARMS: Final = ("A", "B")
MINUTES: Final = 30
POPULATION: Final = 3
#: The square's walkable area is 12 m either side of its centre; the scene's far edge is 12.3 m
#: ahead, so every thing is placed this much nearer.
FORWARD_SHIFT_MM: Final = 3_000
BOUND_USD: Final = Decimal("0.50")
MAX_CALLS: Final = 800
SIMILAR: Final = Decimal("0.5")
#: What arm A's instruction leaves out of arm B's, each exactly as the registry states it.
A_LEAVES_OUT: Final = (
    " Say something new that fits what the being is and what is around it: never repeat a line it "
    "or others already said. It need not answer every line; when it has nothing new to say, choose "
    "another action.",
)
#: And what arm A's first sentences say instead.
A_REPLACES: Final = (
    (
        "You are told what it is, how it is, what it can do now, what it holds, what others said "
        "to it lately and what it said itself.",
        "You are told how it is, what it can do now, what it holds and what others said to it "
        "lately.",
    ),
)
A_WITHHOLDS: Final = ("being", "said")
BENCHMARK_REASON: Final = (
    "A recorded measurement asks the scene's models about a development scene built in memory from "
    "the tests' own starter square; no person's data is in it."
)
_WORD: Final = re.compile(r"[a-z0-9']+")
#: The committed files the run reads beside the package's code, bound by digest in the
#: pre-registration so a reader without this tree can check them.
READS: Final = (
    SCRIPT,
    SCENE,
    "assets/catalogs/roles/decision-roles.v6.json",
    "assets/catalogs/society/society-decision-action.v4.json",
    "assets/catalogs/society/society-decision-policy.v4.json",
    "exulanica/abilities/ability-modules.v1.json",
    "tests/things_society_support.py",
)


# -- the metric -----------------------------------------------------------------------------------


def words(line: str) -> frozenset[str]:
    return frozenset(_WORD.findall(line.lower()))


def similar(a: str, b: str) -> bool:
    """Token-set Jaccard of at least ``SIMILAR``: the shared words at least half of all words."""
    left, right = words(a), words(b)
    union = left | right
    if not union:
        return True
    return Decimal(len(left & right)) / Decimal(len(union)) >= SIMILAR


def near_repeats(lines: Sequence[Mapping[str, Any]]) -> list[bool]:
    """For each line of one run, in the order said: whether it nearly repeats an earlier line its
    speaker said in the run, or the line it answers (the last said to it or to everyone near it
    that it heard before it spoke)."""
    found = []
    for index, line in enumerate(lines):
        earlier = [other["line"] for other in lines[:index] if other["speaker"] == line["speaker"]]
        if line["answers"] is not None:
            earlier.append(line["answers"])
        found.append(any(similar(line["line"], other) for other in earlier))
    return found


def share(repeats: Sequence[bool]) -> Decimal | None:
    if not repeats:
        return None
    return (Decimal(sum(repeats)) / Decimal(len(repeats))).quantize(Decimal("0.0001"))


def verdict(arms: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The pre-registered rule over the arms pooled across models: B passes where its near-repeat
    share is at most half of A's and it had no more refused answers than A."""
    a, b = arms["A"], arms["B"]
    if a["share"] is None or b["share"] is None:
        return {"passes": None, "why": "an arm said no line"}
    passes = Decimal(b["share"]) * 2 <= Decimal(a["share"]) and b["refused"] <= a["refused"]
    return {"passes": passes, "why": "share B <= share A / 2 and refused B <= refused A"}


# -- the scene ------------------------------------------------------------------------------------


def scene_things() -> list[Any]:
    from things_society_support import thing

    scene = json.loads((ROOT / SCENE).read_bytes())
    return [
        thing(
            entry["thing_id"],
            entry["kind"]["kind"],
            entry["kind"]["version"],
            entry["place"]["right_mm"],
            entry["place"]["forward_mm"] - FORWARD_SHIFT_MM,
            yaw=entry["place"]["turn_microradians"],
        )
        for entry in scene["things"]
    ]


def _arm_role(role: Any, arm: str) -> Any:
    if arm == "B":
        return role
    terms = role.terms(ENGINE)
    instruction = terms.instruction
    for left_out in A_LEAVES_OUT:
        if left_out not in instruction:
            raise SystemExit("arm A's instruction no longer matches the registry's")
        instruction = instruction.replace(left_out, "")
    for said, instead in A_REPLACES:
        if said not in instruction:
            raise SystemExit("arm A's instruction no longer matches the registry's")
        instruction = instruction.replace(said, instead)
    return dataclasses.replace(
        role,
        engine_terms={
            **role.engine_terms,
            ENGINE: dataclasses.replace(terms, instruction=instruction),
        },
    )


def _withhold(arm: str):
    if arm == "B":
        return None

    def withhold(context: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in context.items() if key not in A_WITHHOLDS}

    return withhold


def _answered(heard: Sequence[Mapping[str, Any]], tick: int) -> str | None:
    """The last line said to a being, or to everyone near it, that it heard before ``tick``."""
    before = [entry for entry in heard if entry["tick"] < tick]
    return before[-1]["line"] if before else None


def play(client: Any, spec: Any, arm: str, *, seed: str) -> dict[str, Any]:
    """One model's run of one arm: ``MINUTES`` minutes of the scene, every due mind asked."""
    from exulanica.api.decision_host import RoleAsk, ask
    from exulanica.world.decision_roles import decision_roles
    from exulanica.world.role_decisions import apply_receipts, role_receipt, role_request
    from exulanica.world.society_decision_contract import person_role
    from exulanica.world.society_planner import advance_purposeful_society
    from exulanica.world.society_things import advance_things, initial_things_society

    from things_society_support import SOCIETY, compose

    role = person_role()
    asked_role = _arm_role(role, arm)
    contract = role.contract(role.terms(ENGINE).versions)
    mechanism = contract.mechanism_for(spec)
    roles = decision_roles().hosted_by(ENGINE)
    document = compose(scene_things())
    state = initial_things_society(SOCIETY, seed, document, population=POPULATION)
    minds = sorted(p["id"] for p in state["inhabitants"] if p["came_by"] == "placed")
    lines: list[dict[str, Any]] = []
    outcomes: dict[str, int] = {}
    sequence = 0
    for _minute in range(MINUTES):
        receipts = []
        for subject in minds:
            if not role.adapter.due(state, subject):
                continue
            request, _status = role_request(
                role,
                state,
                document,
                subject,
                request_id=uuid.uuid5(SOCIETY, f"{arm}:{spec.model_id}:{subject}:{state['tick']}"),
                contract=contract,
                seed=seed,
                provider_config={
                    "provider": spec.provider,
                    "model_id": spec.model_id,
                    "mechanism": mechanism.value,
                    "choice_seq": 1,
                    "manifest_sha256": _manifest_sha256(),
                    "prompt_version": role.terms(ENGINE).prompt_version,
                    "contract": contract.binding(),
                    "deadline_ms": contract.value("decision_deadline_ms"),
                },
                withhold=_withhold(arm),
            )
            if request is None:
                continue
            result = ask(
                client,
                RoleAsk(asked_role, request, spec, mechanism),
                contract,
                time.monotonic() + contract.value("decision_deadline_ms") / 1000,
            )
            if result["reason"] in ("process_budget_spent", "process_share_spent"):
                raise _Spent()
            outcome = f"{result['status']}:{result['reason']}"
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            sequence += 1
            receipts.append(role_receipt(role, request, sequence, result))
        previous = state
        policies, decided = apply_receipts(roles, state, document, receipts, {})
        planned, events = advance_purposeful_society(state, seed, [document], goal_policy=policies)
        by_request = {str(d.request_id): d for d in decided}
        consumed = [(r, by_request[str(r["request_id"])]) for r in receipts]
        state, events, _bound = advance_things(
            previous, planned, seed, document, events, (), decisions=consumed
        )
        speakers = {p["id"]: p for p in previous["inhabitants"]}
        for event in events:
            if event.kind != "said":
                continue
            speaker = str(event.subject_id)
            heard = speakers[speaker].get("heard", [])
            to_it = [h for h in heard if h["to"] in (speaker, None)]
            lines.append(
                {
                    "tick": event.tick,
                    "speaker": speaker,
                    "to": event.document["thing"]["to"],
                    "line": event.document["thing"]["line"],
                    "answers": _answered(to_it, event.tick),
                }
            )
    repeats = near_repeats(lines)
    refused = sum(count for outcome, count in outcomes.items() if outcome.startswith("rejected:"))
    return {
        "model_id": spec.model_id,
        "arm": arm,
        "minutes": MINUTES,
        "outcomes": dict(sorted(outcomes.items())),
        "refused": refused,
        "lines": [
            {**line, "near_repeat": repeat} for line, repeat in zip(lines, repeats, strict=True)
        ],
        "near_repeats": sum(repeats),
        "share": None if share(repeats) is None else str(share(repeats)),
    }


class _Spent(Exception):
    """The bound or the call limit was reached: the run is incomplete."""


def pooled(runs: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    arms: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        mine = [run for run in runs if run["arm"] == arm]
        repeats = [line["near_repeat"] for run in mine for line in run["lines"]]
        value = share(repeats)
        arms[arm] = {
            "lines": len(repeats),
            "near_repeats": sum(repeats),
            "share": None if value is None else str(value),
            "refused": sum(run["refused"] for run in mine),
        }
    return arms


# -- the pre-registration -------------------------------------------------------------------------


def preregister() -> None:
    from exulanica.world.society_decision_contract import person_role

    if (ROOT / PREREGISTRATION).exists():
        raise SystemExit(f"{PREREGISTRATION} is already written")
    role = person_role()
    instructions = {arm: _arm_role(role, arm).terms(ENGINE).instruction for arm in ARMS}
    _write_new(
        PREREGISTRATION,
        {
            "question": (
                "Asked by the same open model, do the beings of the Three strangers scene repeat "
                "themselves less when shown what they said lately and what they are and told to "
                "say something new or do something else (arm B, as the prompt ships) than when "
                "shown neither and told neither (arm A)?"
            ),
            "written_before_this_measurement_asked_any_model": True,
            "scene": SCENE,
            "scene_sha256": _sha256((ROOT / SCENE).read_bytes()),
            "placement": (
                f"each thing at the scene's right_mm and forward_mm less {FORWARD_SHIFT_MM} on the "
                f"tests' starter square, {POPULATION} villagers the routine runs; the knight, the "
                "traveller and the lantern spirit asked of the run's model when due"
            ),
            "models": list(MODELS),
            "arms": {
                arm: {
                    "instruction": instructions[arm],
                    "instruction_sha256": _sha256(instructions[arm].encode()),
                    "context_withholds": [] if arm == "B" else list(A_WITHHOLDS),
                }
                for arm in ARMS
            },
            "order": "per model in the order listed, arm A then arm B, each from the same seed",
            "minutes_per_run": MINUTES,
            "metric": (
                "per line, in the order said within a run: a near repeat when its lowercase word "
                f"set ([a-z0-9']+) has token-set Jaccard {SIMILAR} or more with any earlier line "
                "the same being said in the run, or with the last line said to it or to everyone "
                "near that it heard before it spoke; per arm, pooled over the models, the share of "
                "lines that are near repeats"
            ),
            "refused": "per arm, the answers recorded rejected (any reason)",
            "pass_rule": (
                "arm B passes where its pooled near-repeat share is at most half of arm A's and "
                "it had no more refused answers than arm A; no verdict if either arm said no line "
                "or the run stopped at a bound"
            ),
            "reported_not_judged": [
                "lines said per arm and per model, and how many minds chose another action",
                "each model's own share",
            ],
            "stop_rule": (
                f"the whole run stops at USD {BOUND_USD} or {MAX_CALLS} calls, whichever first, "
                "and is then recorded as incomplete with no verdict"
            ),
            "bound_usd": str(BOUND_USD),
            "max_calls": MAX_CALLS,
            "seed": _seed(),
            "manifest_sha256": _manifest_sha256(),
            "tree": _tree(),
            "files_sha256": {path: _sha256((ROOT / path).read_bytes()) for path in READS},
            "record": RECORD,
            "not_covered": [
                "One scene, one seed, one run per model and arm: how much a share varies between "
                "runs is not measured.",
                "Whether a line is apt, kind or in character is not judged; only how much it "
                "repeats.",
                "Near repeats are judged by shared words, so a paraphrase in other words is not "
                "one and a short reply sharing common words may be.",
            ],
        },
    )


def _seed() -> str:
    from things_society_support import SEED

    return SEED


# -- the run --------------------------------------------------------------------------------------


def run(as_run: bytes) -> None:
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
    from exulanica.models.manifest import load_manifest
    from exulanica.models.policy import BenchmarkInputs

    tree = _tree()
    registered = _read_record(PREREGISTRATION)
    if _measured(tree) != _measured(registered["tree"]):
        raise SystemExit("the tree is not the pre-registered one")
    if _sha256(as_run) != registered["files_sha256"][SCRIPT]:
        raise SystemExit("the bytes running are not the pre-registered script")
    for path, digest in registered["files_sha256"].items():
        if _sha256((ROOT / path).read_bytes()) != digest:
            raise SystemExit(f"{path} is not the pre-registered file")
    if (ROOT / RECORD).exists():
        raise SystemExit(f"{RECORD} exists")
    bound = _bound(BOUND_USD)
    manifest = load_manifest()
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(manifest.bound_origins()))
    budget = BudgetGuard(ceiling_usd=bound, max_calls=MAX_CALLS)
    client = ModelClient(manifest=manifest, budget=budget).with_policy(
        BenchmarkInputs(BENCHMARK_REASON)
    )
    runs: list[dict[str, Any]] = []
    complete = True
    try:
        for model_id in MODELS:
            spec = manifest.spec(model_id)
            for arm in ARMS:
                started = time.monotonic()
                played = play(client, spec, arm, seed=registered["seed"])
                played["seconds"] = round(time.monotonic() - started)
                runs.append(played)
                print(
                    f"{model_id} {arm}: {len(played['lines'])} lines, "
                    f"{played['near_repeats']} near repeats, refused {played['refused']}",
                    flush=True,
                )
    except _Spent:
        complete = False
    arms = pooled(runs)
    _write_new_bytes(SCRIPT_AS_RUN, as_run)
    _write_new(
        RECORD,
        {
            "preregistration": PREREGISTRATION,
            "preregistration_record_sha256": _sha256(canonical_json(registered)),
            "script_as_run": SCRIPT_AS_RUN,
            "script_sha256": _sha256(as_run),
            "tree": tree,
            "manifest_sha256": _manifest_sha256(),
            "complete": complete,
            "runs": runs,
            "arms": arms,
            "verdict": verdict(arms) if complete else {"passes": None, "why": "stopped at a bound"},
            "spent_usd": str(budget.spent_usd),
            "calls": budget.billed_calls,
            "bound_usd": str(bound),
            "within_bound": budget.spent_usd <= bound,
        },
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("step", choices=("preregister", "run"))
    step = parser.parse_args(argv).step
    if step == "preregister":
        preregister()
    else:
        run(Path(__file__).read_bytes())


if __name__ == "__main__":
    main()
