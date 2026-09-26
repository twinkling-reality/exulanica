#!/usr/bin/env python3
"""Do two open models serve the people of a world differently in the same hour?

    uv run python scripts/measure_society_comparison.py anchors --seeds <file>
    uv run python scripts/measure_society_comparison.py dry-run --seeds <file>
    uv run python scripts/measure_society_comparison.py preregister
    uv run python scripts/measure_society_comparison.py run --seeds <file>

**The question.** The small square of a starter world, its eight simulated people brought in, one
simulated hour: with Qwen3 235B Instruct deciding for every one of them, and with Nemotron 3.5
Lightning, how much of the need above the routine's rest threshold are they spared, as a share of
what their own routine spares them against waiting (the score of ``society-person-score.v1``), and
is the difference between the two models larger than the protocol lets a comparison claim? The
comparison runs each model, the first model a second time as the control, the routine and waiting
on every held-out seed of ``society-comparison-seeds.v1``, through the product's own runner
(``SocietyComparisonRunner``), and reads its verdict from the product's own route.

**The dry run** (``dry-run``) plays the same comparison on the eight development seeds with a
scripted model behind the real client: the harness checked end to end, and the anchors the
protocol's floor rests on measured on this world, asking no model.

**One pre-registration** (``preregister``) states the comparison before any held-out seed is run:
the candidates, the primary difference, the family, the control, the held-out seeds by digest,
the window, the scoring binding and the tree it measures, every path that differs from HEAD by
its digest, tracked or not. The run takes the tree again before its first call and refuses to run
unless it is the pre-registered one apart from ``docs/evaluation/``, which this script writes.

**The run** (``run``) is judged once: it refuses when its record exists. It reads the held-out
seeds from ``--seeds``, uses a seed only when the SHA-256 of its text is the catalog's commitment,
and never prints or records one: the records name seeds by digest. Every run is read back by
replaying it through the product's route with the billed calls counted before and after.

**Spend.** The key is read from the environment, ``KEY_VARIABLE`` only, and reaches nothing but
the client. The run reads its bound from ``BUDGET_VARIABLE`` and refuses a bound above the one
pre-registered; every call of every run is within it. The record names the provider and the model
of every call, with its tokens and cost.
"""

from __future__ import annotations

import argparse
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
PREREGISTRATION: Final = "docs/evaluation/2026-09-26-society-model-comparison-preregistration.json"
RECORD: Final = "docs/evaluation/2026-09-26-society-model-comparison.json"
ARTIFACTS: Final = "docs/evaluation/artifacts/2026-09-26-society-model-comparison"
DRY_RUN: Final = f"{ARTIFACTS}/dry-run.json"
RUN: Final = f"{ARTIFACTS}/run.json"
RUN_AS_RUN: Final = f"{ARTIFACTS}/measure_society_comparison-run-as-run.py.txt"
SCRIPT: Final = "scripts/measure_society_comparison.py"
#: Where this script's records and artifacts go: the one part of a tree a run does not measure.
RECORDS_DIRECTORY: Final = "docs/evaluation/"

#: The two open models compared, the first also run twice as the control: a large model that
#: answers without reasoning, the cheaper of the two per hour, and a small reasoning model from
#: NVIDIA, both verified by the model socket's probe to answer the contract's choice.
MODELS: Final = (
    ("nebius_token_factory", "Qwen/Qwen3-235B-A22B-Instruct-2507"),
    ("nebius_token_factory", "nvidia/Nemotron-3_5-Lightning"),
)
#: The society's own seed, which decides nothing a comparison runs: every run takes its own.
SOCIETY_SEED: Final = hashlib.sha256(b"exulanica.society-model-comparison/society").hexdigest()
KEY_VARIABLE: Final = "NEBIUS_API_KEY"
BUDGET_VARIABLE: Final = "EXULANICA_BUDGET_USD"
MAX_CALLS_VARIABLE: Final = "EXULANICA_BUDGET_MAX_CALLS"
#: What the run may spend: the model socket measured at most 0.0082 USD per simulated hour of
#: eight people for Qwen and 0.0193 for Lightning, so twenty-four model hours are about 0.29, and
#: what calls under way hold at the end, sixteen asks at once, is well under the rest.
RUN_BOUND_USD: Final = Decimal("0.38")
#: Far above the asks twenty-four model hours make (the socket measured up to 208 an hour); the
#: dollar bound is what stops a run.
MAX_CALLS: Final = 8000
#: What each dry-run call is charged, so the dry run's spend is known and asks nothing.
DRY_RUN_CEILING_USD: Final = Decimal("1000")
#: Said by the run record of what came before it, in words.
EARLIER_MEASUREMENTS: Final = (
    "An anchors run and a dry run on the eight development seeds, each with a scripted model "
    "behind the product's client, checked the harness and measured the anchors the protocol's "
    "floor rests on; neither asked a model.",
    "Two development pairs asked both candidate models on one development seed, against a "
    "separate database, for the Compare view's browser evidence. The first stopped its Lightning "
    "run by the share of the budget the playback host keeps for other work, which the runner "
    "then stopped applying, since a comparison's process does no other work; neither pair is "
    "part of this comparison, and no held-out seed was run before this pre-registration.",
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


def _calls_by_model(owner_url: str, world_id: str) -> list[dict[str, Any]]:
    """Every call the world's comparison receipts record, by the provider and the model that took
    it."""
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


def compare(
    seeds: Sequence[str],
    *,
    phase: str,
    live: bool,
    preregistration: dict[str, str] | None,
) -> dict[str, Any]:
    """The comparison on ``seeds`` in a fresh starter world with the small square, read back
    through the product's routes, every run replayed with the billed calls counted."""
    from exulanica.api.society_comparison_runner import ComparisonArm
    from exulanica.orchestration.compare import comparison_body

    grant = _grant()
    client = None if live else _scripted_client()
    with _application([grant], live=live, model_client=client) as (http, services, urls):
        api = Api(http, grant["token"])
        world = make_square(api, "Model comparison")
        bring_in(api, world, SOCIETY_SEED)
        runner = services.comparison_runner(grant["id"], world["scope"]["world_id"], grant["actor"])
        if runner is None:
            raise SystemExit("the application configures no society runtime")
        comparison_id = uuid.uuid4()
        runner.define(
            uuid.UUID(world["version"]),
            comparison_id=comparison_id,
            body=comparison_body(
                runner,
                [ComparisonArm(provider, model_id) for provider, model_id in MODELS],
                seeds,
                control=True,
                phase=phase,
                preregistration=preregistration,
            ),
        )
        started = time.perf_counter()
        runner.run_all(comparison_id, runner.reserve_all(comparison_id, seeds))
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
        return {
            "comparison_id": str(comparison_id),
            "phase": phase,
            "models": [{"provider": p, "model_id": m} for p, m in MODELS],
            "listing": listing,
            "result": result,
            "replays": replays,
            "billed_calls_during_replays": budget.billed_calls - billed,
            "replay_ms": {"minimum": min(replay_ms), "maximum": max(replay_ms)}
            if replay_ms
            else None,
            "runs_s": round(ran_s, 1),
            "calls_by_model": _calls_by_model(urls["owner"], world["scope"]["world_id"]),
            "anchors": _anchors(urls["owner"], world["scope"]["world_id"]),
            "spent_usd": str(budget.spent_usd),
            "process_ceiling_usd": str(budget.ceiling_usd),
        }


def _anchors(owner_url: str, world_id: str) -> list[dict[str, Any]]:
    """What the routine spared against waiting on each seed, from the anchor runs' recorded
    terms: the measurement the protocol's floor rests on, in need-thousandths times minutes."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(owner_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            "select document from society_comparison_outcome where world_id=%s "
            "and status='completed' and document->>'arm' in ('routine','wait')",
            (world_id,),
        ).fetchall()
    urgency: dict[str, dict[str, int]] = {}
    for row in rows:
        document = row["document"]
        urgency.setdefault(document["seed_digest"], {})[document["arm"]] = document["terms"][
            "urgency"
        ]
    return [
        {
            "seed_digest": seed,
            "wait_urgency": held["wait"],
            "routine_urgency": held["routine"],
            "spared": held["wait"] - held["routine"],
        }
        for seed, held in sorted(urgency.items())
    ]


# -- steps ----------------------------------------------------------------------------------------


def anchors(seeds_path: Path) -> None:
    """The dry run's comparison, printed and not recorded: what the routine spares against
    waiting on each development seed, and how long a run takes to replay, for the protocol's
    floor and population bound before anything is registered. Asks no model."""
    compared = compare(
        _seeds(seeds_path, "development"), phase="development", live=False, preregistration=None
    )
    spared = sorted(row["spared"] for row in compared["anchors"])
    print(
        json.dumps(
            {
                "spared": spared,
                "median": (spared[(len(spared) - 1) // 2] + spared[len(spared) // 2]) / 2,
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
            "profile": "exulanica.society-model-comparison-dry-run/v1",
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
    from exulanica.models.manifest import MANIFEST_PATH, Role, load_manifest
    from exulanica.world.society_catalogs import load_comparison_catalogs
    from exulanica.world.society_comparison_result import protocol_values, scoring_binding
    from exulanica.world.society_decision_contract import decision_contract

    if (ROOT / PREREGISTRATION).exists():
        raise SystemExit(f"{PREREGISTRATION} exists")
    tree = _tree()
    catalogs = load_comparison_catalogs()
    manifest = load_manifest()
    contract = decision_contract()
    candidates = []
    for provider, model_id in MODELS:
        spec = manifest.offered(Role.SOCIETY_DECISION, model_id)
        mechanism = contract.mechanism_for(spec)
        if spec.provider != provider or mechanism is None:
            raise SystemExit(f"{provider}/{model_id} is not askable under the contract")
        candidates.append(
            {
                "provider": provider,
                "model_id": model_id,
                "description": spec.description,
                "mechanism": mechanism.value,
            }
        )
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
            "arms": ["model_a", "model_b", "model_a_again", "routine", "wait"],
            "primary": {
                "measure": "the mean over held-out seeds of model_b's score minus model_a's",
                "pair": ["model_a", "model_b"],
            },
            "family": [["model_a", "model_b"], ["routine", "model_a"], ["routine", "model_b"]],
            "control": ["model_a", "model_a_again"],
            "decision_rule": (
                "different only when Holm's procedure over the family at the protocol's family "
                "error rejects the primary hypothesis and the primary mean's size exceeds the "
                "larger end, in size, of the control's interval; otherwise no measured difference"
            ),
            "seeds": {
                "phase": "held_out",
                "digests": [
                    str(entry["seed_digest"])
                    for entry in catalogs.seeds.values()
                    if entry["phase"] == "held_out"
                ],
            },
            "world": {
                "starter": "the starter world with the small square placed where a person arrives",
                "society_seed_sha256": _sha256(SOCIETY_SEED.encode()),
            },
            "bound_usd": str(RUN_BOUND_USD),
            "max_calls": MAX_CALLS,
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
    raw = os.environ.get(BUDGET_VARIABLE)
    if not raw or not Decimal(0) < Decimal(raw) <= RUN_BOUND_USD:
        raise SystemExit(f"{BUDGET_VARIABLE} must state a bound within (0, {RUN_BOUND_USD}]")
    if not os.environ.get(KEY_VARIABLE):
        raise SystemExit(f"{KEY_VARIABLE} is not in this process's environment")
    seeds = _seeds(seeds_path, "held_out")
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(load_manifest().bound_origins()))
    os.environ[MAX_CALLS_VARIABLE] = str(MAX_CALLS)
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
        {"profile": "exulanica.society-model-comparison-run/v1", "tree": tree, **compared},
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
            "verdict": result["verdict"],
            "differences": result["differences"],
            "control_bound": result["control_bound"],
            "summaries": result["summaries"],
            "seeds": result["seeds"],
            "every_run_replayed": all(r["replay_verified"] for r in compared["replays"].values()),
            "billed_calls_during_replays": compared["billed_calls_during_replays"],
            "calls_by_model": compared["calls_by_model"],
            "spent_usd": compared["spent_usd"],
            "bound_usd": raw,
            "within_bound": Decimal(compared["spent_usd"]) <= Decimal(raw),
        },
    )


def _write_new_bytes(relative: str, data: bytes) -> None:
    target = ROOT / relative
    if target.exists():
        raise SystemExit(f"{relative} exists, and docs/evaluation is append-only")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"wrote {relative}", flush=True)


def main(argv: Sequence[str] | None = None) -> None:
    # The bytes that run, read before anything else can change the file.
    as_run = Path(__file__).read_bytes()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("step", choices=("anchors", "dry-run", "preregister", "run"))
    parser.add_argument("--seeds", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.step != "preregister" and arguments.seeds is None:
        raise SystemExit(f"{arguments.step} reads its seeds from --seeds")
    if arguments.step == "anchors":
        anchors(arguments.seeds)
    elif arguments.step == "dry-run":
        dry_run(arguments.seeds)
    elif arguments.step == "preregister":
        preregister()
    else:
        run(as_run, arguments.seeds)


if __name__ == "__main__":
    main()
