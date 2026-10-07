"""Measure the models that may draft a creature from a person's description.

    uv run python scripts/measure_creature_drafting_models.py preregister --out DIR
    uv run python scripts/measure_creature_drafting_models.py dry-run --out DIR
    EXULANICA_BUDGET_USD=<bound> uv run python scripts/measure_creature_drafting_models.py run \
        --out DIR --env-file PATH

THE RUN STEP SPENDS MONEY, on Nebius Token Factory. It reads the provider's key, and only that
variable, from the ``.env`` file ``--env-file`` names, into its own process (never into its
environment, never printed or written), and its bound from ``EXULANICA_BUDGET_USD`` (and
``EXULANICA_BUDGET_MAX_CALLS`` when set), neither above what the pre-registration states. It runs
only on the tree the pre-registration names. ``DIR`` is where every file this writes goes; a
comparison of models is kept out of the repository until the provider's terms are confirmed, so
``DIR`` is an ignored folder, and only the chosen models' own timings are later written where the
manifest can quote them.

Every candidate is asked every held-out description of ``tests/fixtures/creatures/creatures.v1.json``
through ``draft_creature``, the product's own drafting path
(:mod:`exulanica.selection.creature_drafting`), with the specification drafter's role pointed at
the candidate on an in-memory copy of the manifest, the vehicle the creature drafter takes until
this measurement gives it a role and a timeout. A drafted creature is assembled and held to every
reader a thing passes in this process, as the product holds it. Within each description the
candidates take turns, so a slow minute at the provider falls on all of them. The development
creatures of the same file are never asked here: they are the only ones words may be tuned on.

Measured per description and candidate, each by rule and none by eye: **valid** (a creature
assembled after at most one repair), **valid on the first try**, and **matched** (the
description's pre-registered checks hold for the drafted creature's recipe). ``preregister``
writes the descriptions, their checks, the candidates, the rule, the bound and the stop rules
before any model is asked; ``dry-run`` drives the whole run over a scripted transport that answers
every call with a development creature's form, spending nothing; ``run`` refuses unless the
pre-registration still matches.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from exulanica.canonical import canonical_json  # noqa: E402

PROFILE: Final = "exulanica.digest-bound-record/v1"
SCRIPT: Final = "scripts/measure_creature_drafting_models.py"
DRAFTER: Final = "exulanica/selection/creature_drafting.py"
FIXTURES: Final = ROOT / "tests" / "fixtures" / "creatures" / "creatures.v1.json"
BUDGET_VARIABLE: Final = "EXULANICA_BUDGET_USD"
CALLS_VARIABLE: Final = "EXULANICA_BUDGET_MAX_CALLS"
KEY_VARIABLE: Final = "NEBIUS_API_KEY"
#: Three licence-resolved text models with a JSON schema the manifest holds: the specification
#: drafter's primary (Nemotron 3 Super) and fallback (Qwen3 235B), and the structured extraction
#: fallback (DeepSeek V4 Flash). Nemotron 3 Nano 30B is left out: in the kind drafter's measured run
#: it ran on in blank space to its token ceiling.
CANDIDATES: Final = (
    "nvidia/nemotron-3-super-120b-a12b",
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "deepseek-ai/DeepSeek-V4-Flash-0731",
)
#: The most this measurement may spend, on Nebius Token Factory (allocation CREATURE-DRAFT).
BOUND_USD: Final = Decimal("0.40")
#: Eight descriptions, three candidates, one form and one repair at most.
MAX_CALLS: Final = 48
MAX_TOKENS: Final = 16384
CALL_TIMEOUT_SECONDS: Final = 180
#: The run stops when this many drafts in a row for one description gave no valid creature, which
#: with three candidates is every candidate: a defect in the form or the words, not a model's skill.
REFUSED_IN_A_ROW: Final = 3
#: What each check asks of a drafted creature's recipe: a whole number of a kind of limb, a number
#: of heads, a posture, or at least so many tail bones.
CHECKS: Final = {
    "legs": "the recipe has exactly this many legs",
    "arms": "the recipe has exactly this many arms",
    "wings": "the recipe has exactly this many wings",
    "tentacles": "the recipe has exactly this many tentacles",
    "heads": "the recipe has exactly this many heads",
    "posture": "the recipe's posture is this",
    "tail_at_least": "the recipe has at least this many tail bones",
}
#: The checks each held-out description is matched by, keyed as the fixture names it: only what its
#: words state, never a figure they leave open.
DESCRIPTION_CHECKS: Final = {
    "ten_legs": [{"legs": 10}],
    "dragon": [{"legs": 4}, {"wings": 2}, {"tail_at_least": 1}],
    "three_heads": [{"heads": 3}, {"legs": 4}],
    "serpent": [{"posture": "serpentine"}, {"legs": 0}],
    "winged_horse": [{"legs": 4}, {"wings": 2}],
    "floating_eight": [{"tentacles": 8}, {"posture": "floating"}],
    "raptor": [{"legs": 2}, {"tail_at_least": 1}],
    "four_arms": [{"arms": 4}, {"legs": 2}],
}
RULE: Final = {
    "valid": "the creature was assembled, every document passing its reader, after at most one repair",
    "valid_first_try": "the first form the model returned was accepted and its creature assembled",
    "matched": "every check of the description holds for the drafted creature's recipe",
    "draft_time": "one description's draft time is the sum of its drafter attempts' latencies, as the client measured each",
    "eligible": "a candidate is eligible when at least 6 of the 8 descriptions were valid and at least 5 matched",
    "choice": "the eligible NVIDIA model (identifier beginning nvidia/) with the shortest longest draft time is chosen when that longest is at most speed_bound_ms; otherwise the eligible model with the shortest longest draft time. Ties go to more valid on the first try, then more matched, then the lower total cost. The fallback is the next eligible model in the same order.",
    "speed_bound_ms": 60000,
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _document(record: Mapping[str, Any]) -> dict[str, Any]:
    return {"profile": PROFILE, "record": record, "record_sha256": _sha256(canonical_json(record))}


def _write_new(out: Path, name: str, value: Mapping[str, Any], *, record: bool = True) -> Path:
    target = out / name
    if target.exists():
        raise SystemExit(f"{target} exists; a measurement's files are written once")
    out.mkdir(parents=True, exist_ok=True)
    body = _document(value) if record else value
    target.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {target}", flush=True)
    return target


def _read_record(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_bytes())
    if _sha256(canonical_json(document["record"])) != document["record_sha256"]:
        raise SystemExit(f"{path} does not match its own digest")
    record: dict[str, Any] = document["record"]
    return record


def _tree() -> dict[str, Any]:
    """HEAD, the SHA-256 of ``git diff HEAD --binary`` and of each untracked file git does not
    ignore: the exact tree, uncommitted and new files too."""
    git = ["git", "--no-optional-locks"]
    head = subprocess.run(
        [*git, "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, check=True, text=True
    ).stdout.strip()
    diff = subprocess.run(
        [*git, "diff", "HEAD", "--binary", "--no-renames"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    listed = subprocess.run(
        [*git, "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    untracked = sorted(name for name in listed.decode("utf-8").split("\0") if name)
    return {
        "head": head,
        "diff_head_sha256": _sha256(diff),
        "untracked_sha256": {name: _sha256((ROOT / name).read_bytes()) for name in untracked},
    }


def _descriptions() -> list[dict[str, Any]]:
    fixtures = json.loads(FIXTURES.read_text("utf-8"))
    return [
        {"key": key, "description": fixtures["held_out"][key]["description"], "checks": checks}
        for key, checks in DESCRIPTION_CHECKS.items()
    ]


def _manifest_sha256() -> str:
    from exulanica.models.manifest import MANIFEST_PATH

    return _sha256(MANIFEST_PATH.read_bytes())


def _pinned(manifest: Any, model_id: str) -> Any:
    """The manifest with the vehicle role pointed at ``model_id`` alone, in memory only."""
    from exulanica.models.manifest import Role

    binding = manifest[Role.SPECIFICATION_DRAFTER]
    roles = dict(manifest.roles)
    roles[Role.SPECIFICATION_DRAFTER] = dataclasses.replace(
        binding,
        primary=manifest.spec(model_id),
        fallback=None,
        timeout_seconds=CALL_TIMEOUT_SECONDS,
    )
    return dataclasses.replace(manifest, roles=roles)


def _instructions() -> tuple[str, Any]:
    from exulanica.selection.creature_drafting import creature_drafting_prompt, render_instructions
    from exulanica.things.bodies import body_grammar
    from exulanica.things.catalogs import thing_catalogs

    prompt = creature_drafting_prompt()
    return render_instructions(prompt, body_grammar(), thing_catalogs()), prompt


def _form_sha256() -> str:
    """The SHA-256 of the schema every request sends, as the client sends it."""
    from exulanica.models.schema import response_format_for
    from exulanica.selection.creature_drafting import draft_form

    return _sha256(canonical_json(response_format_for(draft_form(), arrays_last=True)))


def _registration() -> dict[str, Any]:
    from exulanica.things.bodies import body_grammar
    from exulanica.things.catalogs import thing_catalogs

    instructions, prompt = _instructions()
    return {
        "question": (
            "Which model should draft a creature from a person's description: the share of "
            "creatures that pass every check on the first try and after one repair, the share "
            "matching the words by rule, draft time, and cost"
        ),
        "candidates": list(CANDIDATES),
        "candidates_rule": (
            "the specification drafter's primary and fallback and the structured extraction "
            "fallback, three licence-resolved text models with a JSON schema in the manifest"
        ),
        "descriptions": _descriptions(),
        "held_out": (
            "the held-out creatures of tests/fixtures/creatures/creatures.v1.json; its development "
            "creatures are not asked"
        ),
        "checks_meaning": dict(CHECKS),
        "rule": dict(RULE),
        "attempts": "one form and one repair, the drafter's own rule",
        "not_answered": (
            "a draft the provider did not answer (timed out or failed), or that the run could not "
            "finish, is not valid and is recorded with why; a timed-out attempt is charged its "
            "reservation, as the budget guard holds it"
        ),
        "order": "description by description; within a description every candidate in turn",
        "vehicle_role": "specification_drafter, pinned in memory to each candidate",
        "bound_usd": str(BOUND_USD),
        "max_calls": MAX_CALLS,
        "provider": "Nebius Token Factory",
        "stop_rules": [
            f"the bound, USD {BOUND_USD}: a call whose reservation would pass it is not sent",
            f"{MAX_CALLS} calls",
            f"{REFUSED_IN_A_ROW} drafts in a row for one description without a valid creature "
            "(with three candidates, every candidate); a draft is one candidate's form and repair",
            "a run that stops is recorded as stopped, with every call made, and chooses nothing",
        ],
        "call_timeout_seconds": CALL_TIMEOUT_SECONDS,
        "max_tokens": MAX_TOKENS,
        "prompt_version": prompt.prompt_version,
        "prompt_file_sha256": prompt.sha256,
        "instructions_sha256": _sha256(instructions.encode("utf-8")),
        "form_sha256": _form_sha256(),
        "drafter_sha256": _sha256((ROOT / DRAFTER).read_bytes()),
        "grammar_sha256": body_grammar().sha256,
        "thing_catalogs_sha256": thing_catalogs().sha256,
        "fixtures_sha256": _sha256(FIXTURES.read_bytes()),
        "manifest_sha256": _manifest_sha256(),
        "script": SCRIPT,
        "script_sha256": _sha256((ROOT / SCRIPT).read_bytes()),
        "tree": _tree(),
        "kept": (
            "outside the repository until Nebius Token Factory confirms its terms allow comparing "
            "models; the chosen models' own timings alone become the manifest's tracked basis"
        ),
        "measured": [
            "per description and candidate: valid, valid on the first try, matched, each check, "
            "the attempts' outcomes and each refusing check's code, place and sentence",
            "every call: provider, latency, outcome, prompt, completion and reasoning tokens, cost "
            "and whether it is known",
            "per candidate: valid, first-try and matched counts, draft time p50 and longest, call "
            "latency p50, p99 and longest, total cost",
            "the run's clock window",
        ],
        "written_before_this_measurement_asked_any_model": True,
    }


def preregister(out: Path) -> None:
    _write_new(out, "preregistration.json", _registration())


def _registered(out: Path) -> dict[str, Any]:
    registered = _read_record(out / "preregistration.json")
    now = _registration()
    for key in (
        "candidates",
        "descriptions",
        "checks_meaning",
        "rule",
        "bound_usd",
        "max_calls",
        "call_timeout_seconds",
        "max_tokens",
        "prompt_file_sha256",
        "instructions_sha256",
        "form_sha256",
        "drafter_sha256",
        "grammar_sha256",
        "thing_catalogs_sha256",
        "fixtures_sha256",
        "manifest_sha256",
        "script_sha256",
        "tree",
    ):
        if registered[key] != now[key]:
            raise SystemExit(f"{key} has changed since the pre-registration; register again")
    return registered


def _percentile(values: Sequence[int], share: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(share * len(ordered)) - 1))]


def _count(recipe: Mapping[str, Any], role: str) -> int:
    return sum(limb["count"] for limb in recipe["limbs"] if limb["role"] == role)


def _check(check: Mapping[str, Any], recipe: Mapping[str, Any] | None) -> bool:
    """Whether ``check`` (one of :data:`CHECKS`) holds for a drafted creature's recipe."""
    if recipe is None:
        return False
    ((name, value),) = check.items()
    if name in ("legs", "arms", "wings", "tentacles"):
        return _count(recipe, name.removesuffix("s")) == value
    if name == "heads":
        return len(recipe["heads"]) == value
    if name == "posture":
        return bool(recipe["posture"] == value)
    if name == "tail_at_least":
        return int(recipe["tail"]) >= value
    raise SystemExit(f"a check of no known kind: {check}")


def _ask(client: Any, entry: Mapping[str, Any]) -> dict[str, Any]:
    from exulanica.models.errors import BudgetExceededError, ModelError
    from exulanica.models.manifest import Role
    from exulanica.selection.calls import CallLog
    from exulanica.selection.creature_drafting import draft_creature

    attempts: list[Any] = []
    sender = client.with_attempts(attempts.append)
    unanswered: str | None = None
    failure = ""
    try:
        drafted = draft_creature(
            sender,
            entry["description"],
            role=Role.SPECIFICATION_DRAFTER,
            log=CallLog(),
            max_tokens=MAX_TOKENS,
        )
    except BudgetExceededError:
        drafted, unanswered = None, "over_bound"
    except ModelError as failed:
        drafted = None
        unanswered = "timed_out" if getattr(failed, "timed_out", False) else "failed"
        failure = f"{type(failed).__name__}: {failed}"[:300]
    except Exception as failed:  # a paid run records what broke rather than losing its calls
        drafted, unanswered = None, "error"
        failure = f"{type(failed).__name__}: {failed}"[:300]
    creature = None if drafted is None else drafted.creature
    recipe = None if creature is None else dict(creature.recipe)
    checks = [_check(check, recipe) for check in entry["checks"]]
    return {
        "valid": creature is not None,
        "valid_first_try": drafted is not None and drafted.attempts == ("passed",),
        "matched": creature is not None and all(checks),
        "checks": checks,
        "outcomes": [] if drafted is None else list(drafted.attempts),
        "refusals": [] if drafted is None else [list(refusal) for refusal in drafted.refusals],
        "unanswered": unanswered,
        "failure": failure,
        "creature": None
        if creature is None
        else {
            "kind": creature.kind.kind,
            "kind_sha256": creature.kind.sha256,
            "plan_sha256": creature.plan.sha256,
            "bones": len(creature.plan.bones),
            "moves": list(creature.kind.document["moves"]),
            "recipe": recipe,
        },
        "attempts": [
            {
                "model_id": usage.model_id,
                "provider": usage.provider,
                "outcome": str(usage.outcome),
                "failure": usage.failure[:200],
                "latency_ms": round(usage.latency_s * 1000),
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "reasoning_tokens": usage.reasoning_tokens,
                "usd": str(usage.usd),
                "cost_basis": str(usage.cost_basis),
            }
            for usage in attempts
        ],
    }


def _asks(client_for: Callable[[str], Any], candidates: Sequence[str]) -> tuple[list[Any], str]:
    asks: list[dict[str, Any]] = []
    for number, entry in enumerate(_descriptions(), 1):
        refused_in_a_row = 0
        for model_id in candidates:
            started = time.monotonic()
            asked = _ask(client_for(model_id), entry)
            asked.update(
                description=number,
                key=entry["key"],
                model_id=model_id,
                wall_ms=round((time.monotonic() - started) * 1000),
            )
            asks.append(asked)
            print(
                f"d{number} {entry['key']} {model_id}: valid={asked['valid']} "
                f"first={asked['valid_first_try']} matched={asked['matched']} "
                f"outcomes={asked['outcomes']} unanswered={asked['unanswered']} "
                f"{sum(a['latency_ms'] for a in asked['attempts'])} ms",
                flush=True,
            )
            if asked["unanswered"] == "over_bound":
                return asks, f"stopped: the bound or the call count, at description {number}"
            refused_in_a_row = 0 if asked["valid"] else refused_in_a_row + 1
            if refused_in_a_row >= REFUSED_IN_A_ROW:
                return (
                    asks,
                    f"stopped: {refused_in_a_row} drafts in a row without a valid creature for "
                    f"description {number}",
                )
    return asks, "complete"


def _summaries(
    asks: Sequence[Mapping[str, Any]], candidates: Sequence[str]
) -> list[dict[str, Any]]:
    summaries = []
    for model_id in candidates:
        mine = [ask for ask in asks if ask["model_id"] == model_id]
        draft_ms = [sum(a["latency_ms"] for a in ask["attempts"]) for ask in mine]
        calls = [a for ask in mine for a in ask["attempts"]]
        call_ms = [a["latency_ms"] for a in calls]
        summaries.append(
            {
                "model_id": model_id,
                "descriptions": len(mine),
                "valid": sum(ask["valid"] for ask in mine),
                "valid_first_try": sum(ask["valid_first_try"] for ask in mine),
                "matched": sum(ask["matched"] for ask in mine),
                "draft_ms": {
                    "p50": _percentile(draft_ms, 0.5),
                    "longest": max(draft_ms, default=None),
                },
                "calls": {
                    "rows": len(call_ms),
                    "p50_ms": _percentile(call_ms, 0.5),
                    "p99_ms": _percentile(call_ms, 0.99),
                    "longest_ms": max(call_ms, default=None),
                    "timed_out": sum(1 for a in calls if a["outcome"] == "timed_out"),
                },
                "cost_usd": str(sum((Decimal(a["usd"]) for a in calls), Decimal(0))),
                "cost_known": all(a["cost_basis"] == "reported" for a in calls),
            }
        )
    return summaries


def choose(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The primary and its fallback by the pre-registered rule, with the order it read them in."""
    eligible = [s for s in summaries if s["valid"] >= 6 and s["matched"] >= 5]
    bound = RULE["speed_bound_ms"]

    def key(summary: Mapping[str, Any]) -> tuple[int, int, int, int, Decimal]:
        longest = summary["draft_ms"]["longest"] or 0
        nvidia_in_time = summary["model_id"].startswith("nvidia/") and longest <= bound
        return (
            0 if nvidia_in_time else 1,
            longest,
            -summary["valid_first_try"],
            -summary["matched"],
            Decimal(summary["cost_usd"]),
        )

    order = [s["model_id"] for s in sorted(eligible, key=key)]
    return {
        "eligible": [s["model_id"] for s in eligible],
        "order": order,
        "primary": order[0] if order else None,
        "fallback": order[1] if len(order) > 1 else None,
    }


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _run(
    client_for: Callable[[str], Any], *, dry: bool, spent: Callable[[], Decimal]
) -> dict[str, Any]:
    started = _now()
    asks, ended_as = _asks(client_for, CANDIDATES)
    summaries = _summaries(asks, CANDIDATES)
    return {
        "dry_run": dry,
        "provider": "Nebius Token Factory",
        "window": {"started": started, "ended": _now()},
        "ended_as": ended_as,
        "tree": _tree(),
        "manifest_sha256": _manifest_sha256(),
        "asks": asks,
        "summaries": summaries,
        "decision": choose(summaries) if ended_as == "complete" else None,
        "spent_usd": str(spent()),
    }


def dry_run(out: Path) -> None:
    """The whole run over a transport that answers every call with a development creature's form,
    spending nothing, so the record path is exercised before money is."""
    from model_fakes import FakeTransport, RecordingPolicy, chat_body
    from test_creature_drafting import _form_of

    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.manifest import load_manifest
    from exulanica.models.transport import HttpResponse

    form = _form_of("horse", label="dry run beast")

    class Answers(FakeTransport):
        def post_json(self, url, *, headers, payload, timeout):  # type: ignore[no-untyped-def]
            self.requests.append({"url": url, "payload": dict(payload)})
            body = chat_body(json.dumps(form), model=payload["model"])
            return HttpResponse(status_code=200, text=json.dumps(body))

    manifest = load_manifest()
    budget = BudgetGuard(ceiling_usd=BOUND_USD, max_calls=MAX_CALLS)

    def client_for(model_id: str) -> Any:
        return ModelClient(
            api_key="dry-run-key-not-real",
            manifest=_pinned(manifest, model_id),
            transport=Answers(),
            budget=budget,
            policy=RecordingPolicy(),
        )

    measured = _run(client_for, dry=True, spent=lambda: budget.spent_usd)
    _write_new(out, "dry-run.json", measured, record=False)


def run(out: Path, as_run: bytes, env_file: Path | None) -> None:
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.credentials import api_key_from_env
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
    from exulanica.models.manifest import load_manifest
    from exulanica.models.policy import BenchmarkInputs

    registered = _registered(out)
    raw = os.environ.get(BUDGET_VARIABLE)
    if not raw:
        raise SystemExit(f"{BUDGET_VARIABLE} must state this run's bound")
    bound = Decimal(raw)
    if not Decimal(0) < bound <= Decimal(registered["bound_usd"]):
        raise SystemExit(f"{BUDGET_VARIABLE}={bound} is not within (0, {registered['bound_usd']}]")
    calls = int(os.environ.get(CALLS_VARIABLE) or registered["max_calls"])
    if not 0 < calls <= registered["max_calls"]:
        raise SystemExit(f"{CALLS_VARIABLE}={calls} is not within (0, {registered['max_calls']}]")
    if env_file is None or not env_file.is_file():
        raise SystemExit("--env-file names the .env file the provider's key is read from")
    if (out / "record.json").exists():
        raise SystemExit(f"{out / 'record.json'} exists")
    # Only this variable is read from the file, into this process; it is never exported.
    key = api_key_from_env(KEY_VARIABLE, dotenv=env_file)
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(load_manifest().bound_origins()))
    manifest = load_manifest()
    budget = BudgetGuard(ceiling_usd=bound, max_calls=calls)
    reason = "fixed descriptions of imagined creatures written for this measurement, no account holder's data"
    clients = {
        model_id: ModelClient(
            api_key=key, manifest=_pinned(manifest, model_id), budget=budget
        ).with_policy(BenchmarkInputs(reason))
        for model_id in CANDIDATES
    }
    del key
    measured = _run(clients.__getitem__, dry=False, spent=lambda: budget.spent_usd)
    _write_new(out, "run.json", measured, record=False)
    (out / "measure_creature_drafting_models-as-run.py.txt").write_bytes(as_run)
    _write_new(
        out,
        "record.json",
        {
            "preregistration_record_sha256": _sha256(canonical_json(registered)),
            "run_sha256": _sha256((out / "run.json").read_bytes()),
            "script_sha256": _sha256(as_run),
            "tree": measured["tree"],
            "window": measured["window"],
            "ended_as": measured["ended_as"],
            "rule": registered["rule"],
            "summaries": measured["summaries"],
            "decision": measured["decision"],
            "provider": "Nebius Token Factory",
            "spent_usd": measured["spent_usd"],
            "bound_usd": str(bound),
            "max_calls": calls,
            "within_bound": Decimal(measured["spent_usd"]) <= bound,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("preregister", "dry-run", "run"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, help="run: the .env file the key is read from")
    arguments = parser.parse_args()
    out = arguments.out.resolve()
    if out == ROOT or (ROOT in out.parents and ".exulanica" not in out.parts):
        raise SystemExit("--out names a folder git ignores (under .exulanica), never a tracked one")
    as_run = (ROOT / SCRIPT).read_bytes()
    if arguments.step == "preregister":
        preregister(out)
    elif arguments.step == "dry-run":
        dry_run(out)
    else:
        run(out, as_run, arguments.env_file)


if __name__ == "__main__":
    main()
