#!/usr/bin/env python3
"""Does swapping one group's open model change how that group's people fare in the same hour?

    uv run python scripts/measure_group_comparison.py design
    uv run python scripts/measure_group_comparison.py anchors --seeds <file>
    uv run python scripts/measure_group_comparison.py dry-run --seeds <file>
    uv run python scripts/measure_group_comparison.py preregister
    uv run python scripts/measure_group_comparison.py run --seeds <file>

**The question.** The small square of a starter world, its eight simulated people brought in, one
simulated hour. The world's owner chooses Qwen3 235B Instruct for half of them, the first half by
identity, and the rest keep their own routine. With that group decided by Qwen, as the owner chose,
or by Nemotron 3.5 Lightning or Nemotron 3 Nano 30B, swapped in for them, how much of the need
above the routine's rest threshold are the group's people spared, as a share of what their own
routine spares them against waiting (the score of ``society-person-score.v2``, how the people fared
and nothing else), and is Lightning's difference from Qwen larger than the protocol lets a
comparison claim? Beside each score, what each model answered: its share of the group's turns
answered, refused and left to the routine, each model asked as the contract and its manifest entry
ask it (Nano by a JSON schema, the order measured for it; the others by a forced call).

**The design measurement** (``design``) plays the small square's hour in memory on seeds derived
from a fixed label, none of them committed, with each seed's first and second half of the people by
identity waiting at every choice point while everybody else follows their routine, and writes how
often the routine spares such a group less than the protocol's floor: the exclusion the
pre-registration expects. It asks no model and uses no database.

**The anchors** (``anchors``) play the comparison on the development seeds with a scripted model
behind the real client and print what the routine spares the group against waiting on each seed
and how many choice points it has, asking no model and recording nothing.

**The dry run** (``dry-run``) plays the same comparison on the development seeds with the scripted
model and writes it as an artifact: the harness checked end to end, asking no model.

**One pre-registration** (``preregister``) states the comparison before any held-out seed is run:
the candidates, each with how it is asked (the mechanisms in order, the one it answers by and whose
order that is, since the mechanism changes what a model chooses), the group, the primary difference,
the family, the control, the held-out seeds by digest, the simulated window, the floor and the share
of seeds it is expected to exclude, the fewest scored seeds a verdict reads, the bound, the hours of
the clock the run starts within (a provider's answer time varies within one evening), the scoring
binding, the design and dry-run artifacts by digest, and the tree it measures, every path that
differs from HEAD by its digest, tracked or not. The run takes the tree again before its first call
and refuses to run unless it is the pre-registered one apart from ``docs/evaluation/``, which this
script writes.

**The run** (``run``) is judged once: it refuses when its record exists, outside its registered
hours, and when any candidate would now be asked otherwise than registered. It reads the held-out seeds
from ``--seeds``, uses a seed only when the SHA-256 of its text is the catalog's commitment, and
never prints or records one: the records name seeds by digest. Every run is read back by replaying
it through the product's route with the billed calls counted before and after.

**Spend.** The key is read from the environment, ``KEY_VARIABLE`` only, and reaches nothing but the
client. The run reads its bound from ``BUDGET_VARIABLE`` and refuses a bound above the one
pre-registered; every call of every run is within it. The record names the provider and the model
of every call, with its tokens and cost.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from measure_living_square import bring_in, make_square  # noqa: E402
from measure_living_world_pace import Api  # noqa: E402
from measure_society_person_models import _application, _grant  # noqa: E402

from exulanica.canonical import canonical_json  # noqa: E402

PROFILE: Final = "exulanica.digest-bound-record/v1"
#: The day the comparison is pre-registered, which names its records; they exist once it runs.
RECORD_DAY: Final = "2026-09-26"
PREREGISTRATION: Final = (
    f"docs/evaluation/{RECORD_DAY}-society-group-comparison-preregistration.json"
)
RECORD: Final = f"docs/evaluation/{RECORD_DAY}-society-group-comparison.json"
ARTIFACTS: Final = f"docs/evaluation/artifacts/{RECORD_DAY}-society-group-comparison"
DRY_RUN: Final = f"{ARTIFACTS}/dry-run.json"
DESIGN: Final = f"{ARTIFACTS}/design-exclusion.json"
RUN: Final = f"{ARTIFACTS}/run.json"
RUN_AS_RUN: Final = f"{ARTIFACTS}/measure_group_comparison-run-as-run.py.txt"
SCRIPT: Final = "scripts/measure_group_comparison.py"
#: Where this script's records and artifacts go: the one part of a tree a run does not measure.
RECORDS_DIRECTORY: Final = "docs/evaluation/"

#: The owner's choice for the group, then the models swapped in for it: the first judged
#: comparison's two models, so the score of how people fared answers its question on fresh seeds,
#: then Nemotron 3 Nano 30B, the one model the manifest asks in an order measured for it. The first
#: is also run twice as the control. DeepSeek V4 Flash does not join: the development run on the
#: acceptance slot measured the four candidates and the control at about 0.032 USD a seed, which on
#: twelve seeds leaves the bound no room for the variation it also measured.
MODELS: Final = (
    ("nebius_token_factory", "Qwen/Qwen3-235B-A22B-Instruct-2507"),
    ("nebius_token_factory", "nvidia/Nemotron-3_5-Lightning"),
    ("nebius_token_factory", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"),
)
#: The arms and the claim ``comparison_body`` defines for :data:`MODELS` with the control: one arm
#: per model, lettered in order, the first again as the control, and the anchors; the primary pair
#: is the first two models, and the family adds each model against the routine.
_KEYS: Final = tuple(f"model_{chr(ord('a') + index)}" for index in range(len(MODELS)))
ARMS: Final = (*_KEYS, f"{_KEYS[0]}_again", "routine", "wait")
CLAIM: Final = {
    "primary": [_KEYS[0], _KEYS[1]],
    "family": [[_KEYS[0], _KEYS[1]], *(["routine", key] for key in _KEYS)],
    "control": [_KEYS[0], f"{_KEYS[0]}_again"],
}
#: The society's own seed, which decides nothing a comparison runs: every run takes its own.
SOCIETY_SEED: Final = hashlib.sha256(b"exulanica.society-group-comparison/society").hexdigest()
KEY_VARIABLE: Final = "NEBIUS_API_KEY"
BUDGET_VARIABLE: Final = "EXULANICA_BUDGET_USD"
MAX_CALLS_VARIABLE: Final = "EXULANICA_BUDGET_MAX_CALLS"
#: The most the judged run may spend, set in the pre-registration from the development pair's
#: measured cost; the lane's whole allowance is 0.50 USD.
RUN_BOUND_USD: Final = Decimal("0.40")
#: Far above the asks thirty-six model hours of four people make (the model socket measured up to
#: 208 an hour for eight); the dollar bound is what stops a run.
MAX_CALLS: Final = 12000
#: What each dry-run call is charged, so the dry run's spend is known and asks nothing.
DRY_RUN_CEILING_USD: Final = Decimal("1000")
#: How many hours after its pre-registration the judged run may start: the window is stated on the
#: clock, since a provider's answer time varies within one evening (finding #44), and the record
#: says when the run started and ended.
RUN_WINDOW_HOURS: Final = 3
#: The design measurement's seeds, derived from a fixed label; none is committed or held out.
DESIGN_SEEDS: Final = 24
#: The fewest scored seeds a verdict reads: an interval needs two
#: (exulanica/world/society_comparison_claim.py); with fewer the comparison is not judged.
MINIMUM_SCORED_SEEDS: Final = 2
#: Said by the pre-registration and the run record of what came before them, in words.
EARLIER_MEASUREMENTS: Final = (
    "A design measurement on 24 seeds derived from a fixed label, none of them committed, played "
    "the small square's hour in memory with each seed's first and second half of the people by "
    "identity waiting at every choice point while the rest followed their routine, asking no "
    "model: 7 of the 48 groups had the routine spare them less than the floor of 575 per person "
    "against waiting, 3 of them nothing. This script's design step made it again on the tree "
    "this comparison measures and wrote it beside this comparison's artifacts.",
    "The anchors and the dry run of this script on the eight development seeds, each with a "
    "scripted model behind the product's client, asked no model.",
    "A development comparison on the acceptance slot, from 02:34:33 to 02:42:46 UTC on "
    "2026-09-27, decided for the same group with everybody else on their routine by Qwen3 235B "
    "Instruct (run twice), Nemotron 3.5 Lightning, DeepSeek V4 Flash and Nemotron 3 Nano 30B on "
    "the first two development seeds: all 14 runs completed, the second seed was spared less "
    "than the floor and excluded, and the calls cost 0.06442178 USD, 0.0318 to 0.0326 USD a seed "
    "for the five model runs, from 0.0020 USD a run for Nano to 0.0108 for DeepSeek. Lightning "
    "and DeepSeek each reached the contract's 20 second deadline at the 95th percentile on one "
    "seed. Without DeepSeek a seed cost at most 0.0256 USD, which on twelve seeds is 0.31 USD, "
    "and with it 0.0326, or 0.39 USD against a bound of at most 0.40, so DeepSeek does not join.",
)


# -- records --------------------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _document(record: dict[str, Any]) -> dict[str, Any]:
    return {"profile": PROFILE, "record": record, "record_sha256": _sha256(canonical_json(record))}


def _write_new(relative: str, value: dict[str, Any], *, record: bool = True) -> None:
    target = ROOT / relative
    if target.exists():
        raise SystemExit(f"{relative} exists, and docs/evaluation is append-only")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = _document(value) if record else value
    target.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {relative}", flush=True)


def _write_new_bytes(relative: str, data: bytes) -> None:
    target = ROOT / relative
    if target.exists():
        raise SystemExit(f"{relative} exists, and docs/evaluation is append-only")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"wrote {relative}", flush=True)


def _read_record(relative: str) -> dict[str, Any]:
    document = json.loads((ROOT / relative).read_bytes())
    if _sha256(canonical_json(document["record"])) != document["record_sha256"]:
        raise SystemExit(f"{relative} does not match its own digest")
    return document["record"]


def _tree() -> dict[str, Any]:
    """The tree as it is now: HEAD, and the digest of every path that differs from it, tracked
    or not, so a new file is bound as surely as a changed one. A deleted path's digest is None."""

    def git(*arguments: str) -> bytes:
        return subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, check=True).stdout

    changed = git("diff", "HEAD", "--name-only", "-z").decode().split("\0")
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
    files: dict[str, str | None] = {}
    for path in sorted({path for path in (*changed, *untracked) if path}):
        target = ROOT / path
        files[path] = _sha256(target.read_bytes()) if target.is_file() else None
    return {"head": git("rev-parse", "HEAD").decode().strip(), "files_sha256": files}


def _measured(tree: Mapping[str, Any]) -> dict[str, Any]:
    """What a run measures of a tree: all of it but the records and artifacts this script writes."""
    return {
        "head": tree["head"],
        "files_sha256": {
            path: digest
            for path, digest in tree["files_sha256"].items()
            if not path.startswith(RECORDS_DIRECTORY)
        },
    }


# -- the comparison -------------------------------------------------------------------------------


def _seeds(path: Path, phase: str) -> list[str]:
    """Every seed the catalog commits to ``phase``, in its order, read from ``path``: a line is
    used only when the SHA-256 of its text is a commitment. Nothing prints a seed."""
    from exulanica.world.society_catalogs import load_comparison_catalogs

    committed = [
        str(entry["seed_digest"])
        for entry in load_comparison_catalogs().seeds.values()
        if entry["phase"] == phase
    ]
    found = {
        _sha256(line.strip().encode("utf-8")): line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    missing = [digest for digest in committed if digest not in found]
    if missing:
        raise SystemExit(f"{len(missing)} committed {phase} seeds are not in {path}")
    return [found[digest] for digest in committed]


def _scripted_client() -> Any:
    """The product's client with a scripted model behind it, for the dry run: no network."""
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.manifest import load_manifest
    from measure_society_person_models import ScriptedChooser

    return ModelClient(
        api_key="dry-run-not-a-credential",
        manifest=load_manifest(),
        transport=ScriptedChooser(SOCIETY_SEED),
        budget=BudgetGuard(ceiling_usd=DRY_RUN_CEILING_USD, max_calls=MAX_CALLS),
    )


def _outcomes(owner_url: str, world_id: str) -> list[dict[str, Any]]:
    """Every completed outcome the world's comparison recorded, as stored."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(owner_url, row_factory=dict_row) as connection:
        return [
            row["document"]
            for row in connection.execute(
                "select document from society_comparison_outcome where world_id=%s "
                "and status='completed' order by run_id",
                (world_id,),
            ).fetchall()
        ]


def _calls_by_model(owner_url: str, world_id: str) -> list[dict[str, Any]]:
    """Every call the world's comparison receipts record, by the provider and the model that took
    it, and by whether it was asked for the group or for somebody outside it."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(owner_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            "select receipt from society_comparison_decision where world_id=%s "
            "order by run_id, decision_seq",
            (world_id,),
        ).fetchall()
    totals: dict[tuple[str, str], Counter[str]] = {}
    cost: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        provider = row["receipt"]["provider"]
        if provider is None:
            continue
        key = (provider["provider"], provider["model_id"])
        counted = totals.setdefault(key, Counter())
        counted["asks"] += 1
        counted["calls"] += len(provider["calls"])
        counted["prompt_tokens"] += provider["prompt_tokens"]
        counted["completion_tokens"] += provider["completion_tokens"]
        cost[key] = cost.get(key, Decimal(0)) + Decimal(provider["cost_usd"])
    return [
        {
            "provider": provider,
            "model_id": model_id,
            **dict(sorted(counted.items())),
            "cost_usd": str(cost[(provider, model_id)]),
        }
        for (provider, model_id), counted in sorted(totals.items())
    ]


def _anchors(outcomes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """What the routine spared the group against waiting on each seed, and the routine's choice
    points for the group there, from the anchor runs' recorded terms: the measurements the floor
    and the rates rest on, in need-thousandths times minutes and in person-minutes."""
    held: dict[str, dict[str, Mapping[str, Any]]] = {}
    for outcome in outcomes:
        if outcome["arm"] in ("routine", "wait"):
            held.setdefault(outcome["seed_digest"], {})[outcome["arm"]] = outcome["terms"]
    return [
        {
            "seed_digest": seed,
            "people": len(terms["routine"]["people"]),
            "wait_urgency": terms["wait"]["urgency"],
            "routine_urgency": terms["routine"]["urgency"],
            "spared": terms["wait"]["urgency"] - terms["routine"]["urgency"],
            "routine_choice_points": terms["routine"]["choice_points"],
        }
        for seed, terms in sorted(held.items())
        if set(terms) == {"routine", "wait"}
    ]


def compare(
    seeds: Sequence[str],
    *,
    phase: str,
    live: bool,
    preregistration: dict[str, str] | None,
) -> dict[str, Any]:
    """The comparison on ``seeds`` in a fresh starter world with the small square, its owner's
    choice of the first model for half its people as the group, read back through the product's
    routes, every run replayed with the billed calls counted."""
    from exulanica.api.society_comparison_runner import ComparisonArm
    from exulanica.orchestration.compare import comparison_body

    grant = _grant()
    client = None if live else _scripted_client()
    with _application([grant], live=live, model_client=client) as (http, services, urls):
        api = Api(http, grant["token"])
        world = make_square(api, "Group model comparison")
        bring_in(api, world, SOCIETY_SEED)
        society = api("GET", f"/world/versions/{world['version']}/society", params=world["scope"])
        people = sorted(person["id"] for person in society["state"]["inhabitants"])
        # The group: the first half of the people by identity, for whom the owner chooses the
        # first model, as the People panel records a choice.
        owner_model = {"provider": MODELS[0][0], "model_id": MODELS[0][1]}
        api(
            "POST",
            f"/world/versions/{world['version']}/society/models",
            params=world["scope"],
            json={
                "idempotency_key": str(uuid.uuid5(uuid.NAMESPACE_URL, SOCIETY_SEED)),
                "people": people[: len(people) // 2],
                "model": owner_model,
            },
        )
        runner = services.comparison_runner(grant["id"], world["scope"]["world_id"], grant["actor"])
        if runner is None:
            raise SystemExit("the application configures no society runtime")
        version = uuid.UUID(world["version"])
        group = runner.group_of_choice(version, 1)
        others = runner.others_for(version, group["people"])
        comparison_id = uuid.uuid4()
        body = comparison_body(
            runner,
            [ComparisonArm(provider, model_id) for provider, model_id in MODELS],
            seeds,
            control=True,
            phase=phase,
            preregistration=preregistration,
            group=group,
            others=others,
        )
        # The arms and the claim the runner defines are the ones this script registers, checked
        # before anything is asked.
        if sorted(body["arms"]) != sorted(ARMS) or body["claim"] != CLAIM:
            raise SystemExit("the definition is not the comparison this script registers")
        runner.define(version, comparison_id=comparison_id, body=body)
        started = time.perf_counter()
        started_utc = _now()
        runner.run_all(comparison_id, runner.reserve_all(comparison_id, seeds))
        ended_utc = _now()
        ran_s = time.perf_counter() - started
        route = f"/world/versions/{world['version']}/society/comparisons"
        listing = api("GET", route, params=world["scope"])
        result = api("GET", f"{route}/{comparison_id}", params=world["scope"])
        budget = services.model_client.budget
        billed = budget.billed_calls
        replays = {}
        replay_ms = []
        for seed in result["seeds"]:
            for arm, run in sorted(seed["runs"].items()):
                if run["status"] != "completed":
                    continue
                started = time.perf_counter()
                replayed = api(
                    "GET", f"{route}/{comparison_id}/runs/{run['run_id']}", params=world["scope"]
                )
                replay_ms.append(round((time.perf_counter() - started) * 1000))
                replays[run["run_id"]] = {
                    "arm": arm,
                    "seed_digest": seed["seed_digest"],
                    "replay_verified": replayed["replay_verified"],
                    "minutes": len(replayed["minutes"]),
                    "decisions": len(replayed["decisions"]),
                }
        outcomes = _outcomes(urls["owner"], world["scope"]["world_id"])
        return {
            "comparison_id": str(comparison_id),
            "phase": phase,
            "models": [{"provider": p, "model_id": m} for p, m in MODELS],
            "group": result["group"],
            "others": result["others"],
            "listing": listing,
            "result": result,
            "replays": replays,
            "billed_calls_during_replays": budget.billed_calls - billed,
            "replay_ms": {"minimum": min(replay_ms), "maximum": max(replay_ms)}
            if replay_ms
            else None,
            "runs_s": round(ran_s, 1),
            "started_utc": started_utc,
            "ended_utc": ended_utc,
            "calls_by_model": _calls_by_model(urls["owner"], world["scope"]["world_id"]),
            "anchors": _anchors(outcomes),
            "spent_usd": str(budget.spent_usd),
            "process_ceiling_usd": str(budget.ceiling_usd),
        }


# -- steps ----------------------------------------------------------------------------------------


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def design() -> None:
    """How often the protocol's floor excludes a half-square group, in memory and asking no model:
    on each of :data:`DESIGN_SEEDS` seeds derived from a fixed label, each half of the square's
    people by identity waits at every choice point, or follows its routine, while everybody else
    follows theirs; the routine spares the group ``U_wait - U_routine``, and a group is below the
    floor when that is under the floor per person times its size."""
    sys.path.insert(0, str(ROOT / "tests"))
    import living_square_support as square

    from exulanica.world.society_catalogs import load_comparison_catalogs
    from exulanica.world.society_comparison import RunPlan, _wait_policy, genesis
    from exulanica.world.society_comparison_result import protocol_value
    from exulanica.world.society_decision_contract import at_choice_point, decision_contract
    from exulanica.world.society_planner import advance_purposeful_society, routine_of
    from exulanica.world.society_score import need_threshold

    if (ROOT / DESIGN).exists():
        raise SystemExit(f"{DESIGN} exists")
    contract = decision_contract()
    document = square.compose(square.square_objects())
    catalogs = load_comparison_catalogs()
    ticks = protocol_value(catalogs, "window_ticks")
    floor = protocol_value(catalogs, "need_relief_floor_per_person")
    threshold = need_threshold(routine_of(document))
    wait = _wait_policy(contract)

    def urgencies(seed: str, waiting: frozenset[str]) -> tuple[list[str], dict[str, int]]:
        plan = RunPlan(
            run_id=uuid.uuid4(),
            society_id=square.SOCIETY,
            seed=seed,
            population=8,
            inputs=(document,),
            ticks=ticks,
            decider={"kind": "routine"},
            provider_config=None,
            contract=contract,
        )
        state = genesis(plan)
        people = sorted(person["id"] for person in state["inhabitants"])
        urgency = dict.fromkeys(people, 0)
        for _ in range(ticks):
            policies = {
                person["id"]: dict(wait)
                for person in state["inhabitants"]
                if at_choice_point(person) and person["id"] in waiting
            }
            state, _ = advance_purposeful_society(state, seed, [document], goal_policy=policies)
            for person in state["inhabitants"]:
                urgency[person["id"]] += max(0, person["need_milli"] - threshold)
        return people, urgency

    spared: list[int] = []
    for index in range(DESIGN_SEEDS):
        seed = _sha256(f"exulanica.comparev2/design/{index}".encode())
        people, routine = urgencies(seed, frozenset())
        for group in (frozenset(people[:4]), frozenset(people[4:])):
            _people, waited = urgencies(seed, group)
            spared.append(sum(waited[p] for p in group) - sum(routine[p] for p in group))
    ordered = sorted(spared)
    middle = len(ordered) // 2
    _write_new(
        DESIGN,
        {
            "profile": "exulanica.society-group-comparison-design/v1",
            "question": " ".join((design.__doc__ or "").split()),
            "seeds": DESIGN_SEEDS,
            "seed_label": "exulanica.comparev2/design/<index>, SHA-256",
            "groups": len(spared),
            "group_size": 4,
            "window_ticks": ticks,
            "floor_per_person": floor,
            "threshold": threshold,
            "below_floor": sum(1 for value in spared if value < floor * 4),
            "spared_zero": sum(1 for value in spared if value == 0),
            "spared_median": str(Decimal(ordered[middle - 1] + ordered[middle]) / 2),
            "spared_min": ordered[0],
            "spared_max": ordered[-1],
            "spared": spared,
        },
        record=False,
    )


def anchors(seeds_path: Path) -> None:
    """The dry run's comparison, printed and not recorded: what the routine spares the group
    against waiting on each development seed, per person and against the floor, and how long a
    run takes to replay. Asks no model."""
    from exulanica.world.society_catalogs import load_comparison_catalogs
    from exulanica.world.society_comparison_result import protocol_value

    floor = protocol_value(load_comparison_catalogs(), "need_relief_floor_per_person")
    compared = compare(
        _seeds(seeds_path, "development"), phase="development", live=False, preregistration=None
    )
    rows = compared["anchors"]
    print(
        json.dumps(
            {
                "group": [person["id"] for person in compared["group"]["people"]],
                "spared_per_person": sorted(row["spared"] // row["people"] for row in rows),
                "below_floor": sum(1 for row in rows if row["spared"] < floor * row["people"]),
                "seeds": len(rows),
                "routine_choice_points": sorted(row["routine_choice_points"] for row in rows),
                "replay_ms": compared["replay_ms"],
                "runs_s": compared["runs_s"],
                "verdict": compared["result"]["verdict"],
            },
            indent=2,
        )
    )


def dry_run(seeds_path: Path) -> None:
    """The comparison on the development seeds with a scripted model: no model is asked."""
    if (ROOT / DRY_RUN).exists():
        raise SystemExit(f"{DRY_RUN} exists")
    tree = _tree()
    compared = compare(
        _seeds(seeds_path, "development"), phase="development", live=False, preregistration=None
    )
    _write_new(
        DRY_RUN,
        {
            "profile": "exulanica.society-group-comparison-dry-run/v1",
            "scripted": (
                "A scripted model behind the product's client answered every ask with an offered "
                "action drawn from a seed; the token counts and costs below are the script's, "
                "priced at the manifest's rates, and no model was asked or paid."
            ),
            "tree": tree,
            **compared,
        },
        record=False,
    )


def preregister() -> None:
    """State the comparison before any held-out seed is run, with the tree it measures."""
    from exulanica.models.manifest import MANIFEST_PATH, load_manifest
    from exulanica.world.society_catalogs import load_comparison_catalogs
    from exulanica.world.society_comparison_result import protocol_values, scoring_binding
    from exulanica.world.society_decision_contract import decision_contract, person_role

    if (ROOT / PREREGISTRATION).exists():
        raise SystemExit(f"{PREREGISTRATION} exists")
    tree = _tree()
    catalogs = load_comparison_catalogs()
    manifest = load_manifest()
    contract = decision_contract()
    candidates = []
    for provider, model_id in MODELS:
        spec = manifest.offered(person_role().chosen, model_id)
        answering = contract.answering(spec)
        if spec.provider != provider or answering is None:
            raise SystemExit(f"{provider}/{model_id} is not askable under the contract")
        candidates.append(
            {
                "provider": provider,
                "model_id": model_id,
                "name": manifest.model_name(model_id),
                "answering": answering,
            }
        )
    for artifact in (DESIGN, DRY_RUN):
        if not (ROOT / artifact).exists():
            raise SystemExit(f"{artifact} is written before the pre-registration")
    opens = dt.datetime.now(dt.UTC).replace(microsecond=0)
    window = {
        "not_before_utc": opens.isoformat(),
        "not_after_utc": (opens + dt.timedelta(hours=RUN_WINDOW_HOURS)).isoformat(),
        "local": (
            f"{opens.astimezone().isoformat()} to "
            f"{(opens + dt.timedelta(hours=RUN_WINDOW_HOURS)).astimezone().isoformat()}"
        ),
        "why": (
            "a provider's answer time varies within one evening (finding #44), and a turn a "
            "model does not answer by the contract's deadline is left to the routine, so the run "
            "starts within these hours and its record says when it started and ended"
        ),
    }
    held_out = [
        str(entry["seed_digest"])
        for entry in catalogs.seeds.values()
        if entry["phase"] == "held_out"
    ]
    _write_new(
        PREREGISTRATION,
        {
            "question": __doc__.split("\n\n")[2].replace("\n", " "),
            "written_before_any_held_out_seed_was_run": True,
            "earlier_measurements": list(EARLIER_MEASUREMENTS),
            "tree": tree,
            "script": SCRIPT,
            "script_sha256": _sha256((ROOT / SCRIPT).read_bytes()),
            "manifest_sha256": _sha256(MANIFEST_PATH.read_bytes()),
            "contract": contract.binding(),
            "scoring": scoring_binding(catalogs),
            "protocol": protocol_values(catalogs),
            "candidates": candidates,
            "group": {
                "rule": (
                    "the first half of the square's people by subject id, for whom the world's "
                    "owner chooses the first candidate before the comparison is defined; the "
                    "comparison's group is that choice's people"
                ),
                "everybody_else": "their own routine: the owner chooses nothing for them",
            },
            "arms": list(ARMS),
            "primary": {
                "measure": "the mean over scored held-out seeds of model_b's score minus model_a's",
                "pair": CLAIM["primary"],
            },
            "family": CLAIM["family"],
            "control": CLAIM["control"],
            "decision_rule": (
                "different only when Holm's procedure over the family at the protocol's family "
                "error rejects the primary hypothesis and the primary mean's size exceeds the "
                "larger end, in size, of the control's interval; otherwise no measured "
                "difference; with fewer than the minimum scored seeds, not judged"
            ),
            "reliability": (
                "reported apart and never weighed: each arm's share of the group's turns "
                "answered, refused and left to the routine, and the same per choice point of the "
                "seed's routine run; the verdict also says whether the primary pair's answered "
                "shares differ by more than the control pair's"
            ),
            "seeds": {"phase": "held_out", "count": len(held_out), "digests": held_out},
            "minimum_scored_seeds": MINIMUM_SCORED_SEEDS,
            "expected_exclusion": (
                "about one seed in seven (7 of 48 half-square groups in the design measurement "
                "spared less than the floor), so about two of twelve"
            ),
            "world": {
                "starter": "the starter world with the small square placed where a person arrives",
                "society_seed_sha256": _sha256(SOCIETY_SEED.encode()),
            },
            "bound_usd": str(RUN_BOUND_USD),
            "max_calls": MAX_CALLS,
            "run_window": window,
            "artifacts": {
                artifact: _sha256((ROOT / artifact).read_bytes()) for artifact in (DESIGN, DRY_RUN)
            },
        },
    )


def run(as_run: bytes, seeds_path: Path) -> None:
    """The judged run, once."""
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
    from exulanica.models.manifest import load_manifest

    tree = _tree()
    registered = _read_record(PREREGISTRATION)
    measured, bound_tree = _measured(tree), _measured(registered["tree"])
    differ = sorted(
        path
        for path in {*measured["files_sha256"], *bound_tree["files_sha256"]}
        if measured["files_sha256"].get(path) != bound_tree["files_sha256"].get(path)
    )
    if measured["head"] != bound_tree["head"] or differ:
        raise SystemExit(f"the tree is not the pre-registered one: {measured['head']} {differ}")
    if _sha256(as_run) != registered["script_sha256"]:
        raise SystemExit("the bytes running are not the script the pre-registration binds")
    if (ROOT / RECORD).exists():
        raise SystemExit(f"{RECORD} exists: the comparison is judged once")
    window = registered["run_window"]
    now = dt.datetime.now(dt.UTC)
    if not (
        dt.datetime.fromisoformat(window["not_before_utc"])
        <= now
        <= dt.datetime.fromisoformat(window["not_after_utc"])
    ):
        raise SystemExit(f"the run starts within its registered hours, {window['local']}")
    from exulanica.world.society_decision_contract import decision_contract, person_role

    for candidate in registered["candidates"]:
        spec = load_manifest().offered(person_role().chosen, candidate["model_id"])
        if decision_contract().answering(spec) != candidate["answering"]:
            raise SystemExit(f"{candidate['model_id']} would be asked otherwise than registered")
    raw = os.environ.get(BUDGET_VARIABLE)
    if not raw or not Decimal(0) < Decimal(raw) <= Decimal(registered["bound_usd"]):
        raise SystemExit(
            f"{BUDGET_VARIABLE} must state a bound within (0, {registered['bound_usd']}]"
        )
    if not os.environ.get(KEY_VARIABLE):
        raise SystemExit(f"{KEY_VARIABLE} is not in this process's environment")
    seeds = _seeds(seeds_path, "held_out")
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(load_manifest().bound_origins()))
    os.environ[MAX_CALLS_VARIABLE] = str(registered["max_calls"])
    compared = compare(
        seeds,
        phase="held_out",
        live=True,
        preregistration={
            "record": PREREGISTRATION,
            "record_sha256": _sha256(canonical_json(registered)),
        },
    )
    _write_new(
        RUN,
        {"profile": "exulanica.society-group-comparison-run/v1", "tree": tree, **compared},
        record=False,
    )
    _write_new_bytes(RUN_AS_RUN, as_run)
    result = compared["result"]
    _write_new(
        RECORD,
        {
            "preregistration": PREREGISTRATION,
            "preregistration_record_sha256": _sha256(canonical_json(registered)),
            "earlier_measurements": list(EARLIER_MEASUREMENTS),
            "run_artifact": RUN,
            "run_sha256": _sha256((ROOT / RUN).read_bytes()),
            "script_as_run": RUN_AS_RUN,
            "script_sha256": _sha256(as_run),
            "tree": tree,
            "run_window": registered["run_window"],
            "started_utc": compared["started_utc"],
            "ended_utc": compared["ended_utc"],
            "arms": result["arms"],
            "group": result["group"],
            "others": result["others"],
            "verdict": result["verdict"],
            "differences": result["differences"],
            "control_bound": result["control_bound"],
            "summaries": result["summaries"],
            "seeds": result["seeds"],
            "scored_seeds": sum(1 for seed in result["seeds"] if seed["excluded"] is None),
            "every_run_replayed": all(r["replay_verified"] for r in compared["replays"].values()),
            "billed_calls_during_replays": compared["billed_calls_during_replays"],
            "calls_by_model": compared["calls_by_model"],
            "anchors": compared["anchors"],
            "spent_usd": compared["spent_usd"],
            "bound_usd": raw,
            "within_bound": Decimal(compared["spent_usd"]) <= Decimal(raw),
        },
    )


def main(argv: Sequence[str] | None = None) -> None:
    # The bytes that run, read before anything else can change the file.
    as_run = Path(__file__).read_bytes()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("step", choices=("design", "anchors", "dry-run", "preregister", "run"))
    parser.add_argument("--seeds", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.step not in ("design", "preregister") and arguments.seeds is None:
        raise SystemExit(f"{arguments.step} reads its seeds from --seeds")
    if arguments.step == "design":
        design()
    elif arguments.step == "anchors":
        anchors(arguments.seeds)
    elif arguments.step == "dry-run":
        dry_run(arguments.seeds)
    elif arguments.step == "preregister":
        preregister()
    else:
        run(as_run, arguments.seeds)


if __name__ == "__main__":
    main()
