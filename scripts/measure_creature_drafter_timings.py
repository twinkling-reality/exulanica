"""Measure how long the creature drafter's primary takes to draft a creature, bodies of every kind.

    uv run python scripts/measure_creature_drafter_timings.py preregister --out DIR
    uv run python scripts/measure_creature_drafter_timings.py dry-run --out DIR
    EXULANICA_BUDGET_USD=<bound> uv run python scripts/measure_creature_drafter_timings.py run \
        --out DIR --env-file PATH
    uv run python scripts/measure_creature_drafter_timings.py timings --out DIR

THE RUN STEP SPENDS MONEY, on Nebius Token Factory. It reads the provider's key, and only that
variable, from the ``.env`` file ``--env-file`` names, into its own process (never into its
environment, never printed or written), and its bound from ``EXULANICA_BUDGET_USD`` (and
``EXULANICA_BUDGET_MAX_CALLS`` when set), neither above what the pre-registration states. It runs
only on the tree the pre-registration names. ``DIR`` is an ignored folder where every file this
writes goes, except the public timings record that ``timings`` writes.

Why: the creature drafter's timeout rests on its primary's calls in the first measurement, eight
descriptions whose longest call took 25.7 s. Drafting bodies with many legs, heads or limbs later
took up to 110 s, past that timeout. So this asks :data:`DESCRIPTIONS`, 24 descriptions written for
it, simple and complex bodies, none asked of a model before, through the product's drafting path
(:func:`exulanica.selection.creature_drafting.draft_creature`) with the ``creature_drafter`` role's
primary alone and a call timeout of :data:`CALL_TIMEOUT_SECONDS`, so a slow call is measured rather
than cut. Each description is asked once, with the drafter's one repair. ``timings`` writes the
primary's own calls (rows, p50, p99, longest) for the manifest's timeout basis; nothing of any other
model is asked or published.
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
SCRIPT: Final = "scripts/measure_creature_drafter_timings.py"
DRAFTER: Final = "exulanica/selection/creature_drafting.py"
BUDGET_VARIABLE: Final = "EXULANICA_BUDGET_USD"
CALLS_VARIABLE: Final = "EXULANICA_BUDGET_MAX_CALLS"
KEY_VARIABLE: Final = "NEBIUS_API_KEY"
#: The most this measurement may spend, on Nebius Token Factory (allocation
#: CREATURE-DRAFT-TIMING), and the most calls: 24 descriptions, a form and a repair each.
BOUND_USD: Final = Decimal("0.40")
MAX_CALLS: Final = 60
MAX_TOKENS: Final = 16384
CALL_TIMEOUT_SECONDS: Final = 240
#: Written for this measurement before any model was asked; simple and complex bodies (many legs,
#: heads, necks, tails, tentacles, wings with legs), none of them words asked of a model before.
DESCRIPTIONS: Final = (
    "a red dragon with four legs and two great wings",
    "a hydra with five long necks and one heavy tail",
    "a wolf with six legs that hunts at night",
    "a phoenix with long trailing tail feathers",
    "a unicorn with a spiral horn and a flowing mane",
    "a fox with three bushy tails",
    "an octopus that walks on land on its eight arms",
    "a stone golem with two heavy arms and short legs",
    "a manticore with a lion's body, bat wings and a scorpion's tail",
    "a giant tortoise carrying a small garden on its shell",
    "a snake with a pair of feathered wings",
    "a dragonfly as big as a horse with four clear wings",
    "a bear that walks on six legs",
    "a jellyfish that floats above the streets trailing dozens of tendrils",
    "a long-necked grazing beast with a striped coat",
    "a crab with one huge claw and eight legs",
    "a millipede with a hundred tiny legs",
    "a kraken with twelve tentacles",
    "a frog as big as a car",
    "a seahorse that swims through the air",
    "a beetle with shining armoured wing cases",
    "a two-headed eagle",
    "a giant sloth that hangs from lamp posts",
    "a scorpion with two tails",
)


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


def _manifest_sha256() -> str:
    from exulanica.models.manifest import MANIFEST_PATH

    return _sha256(MANIFEST_PATH.read_bytes())


def _primary_alone(manifest: Any) -> Any:
    """The manifest with the creature drafter's role pointed at its primary alone, with the
    measurement's call timeout, in memory only."""
    from exulanica.models.manifest import Role

    binding = manifest[Role.CREATURE_DRAFTER]
    roles = dict(manifest.roles)
    roles[Role.CREATURE_DRAFTER] = dataclasses.replace(
        binding, fallback=None, timeout_seconds=CALL_TIMEOUT_SECONDS
    )
    return dataclasses.replace(manifest, roles=roles)


def _primary() -> str:
    from exulanica.models.manifest import Role, load_manifest

    return str(load_manifest()[Role.CREATURE_DRAFTER].primary.model_id)


def _registration() -> dict[str, Any]:
    from exulanica.selection.creature_drafting import creature_drafting_prompt
    from exulanica.things.bodies import body_grammar
    from exulanica.things.catalogs import thing_catalogs

    prompt = creature_drafting_prompt()
    return {
        "question": (
            "How long the creature drafter's primary takes to answer a call, over simple and "
            "complex bodies, so its role's timeout rests on calls like the ones it will serve"
        ),
        "primary": _primary(),
        "descriptions": list(DESCRIPTIONS),
        "descriptions_rule": (
            "written for this measurement before any model was asked, simple and complex bodies, "
            "none of them words asked of a model before"
        ),
        "attempts": "one form and one repair, the drafter's own rule; each description asked once",
        "order": "the descriptions in their order, one at a time",
        "role": "creature_drafter, its primary alone, the call timeout below, in memory only",
        "call_timeout_seconds": CALL_TIMEOUT_SECONDS,
        "max_tokens": MAX_TOKENS,
        "bound_usd": str(BOUND_USD),
        "max_calls": MAX_CALLS,
        "provider": "Nebius Token Factory",
        "stop_rules": [
            f"the bound, USD {BOUND_USD}: a call whose reservation would pass it is not sent",
            f"{MAX_CALLS} calls",
            "a run that stops is recorded as stopped, with every call made",
        ],
        "measured": [
            "every call: latency, outcome, prompt, completion and reasoning tokens, cost",
            "per description: the attempts' outcomes and whether a creature was drafted",
            "the primary's calls: rows, p50, p99 and longest, and how many timed out",
        ],
        "timings_rule": (
            "rows are every call the primary answered; a call that timed out is counted apart and "
            "named in the record, and a run with one cannot give a basis below its timeout"
        ),
        "prompt_version": prompt.prompt_version,
        "prompt_file_sha256": prompt.sha256,
        "drafter_sha256": _sha256((ROOT / DRAFTER).read_bytes()),
        "grammar_sha256": body_grammar().sha256,
        "thing_catalogs_sha256": thing_catalogs().sha256,
        "manifest_sha256": _manifest_sha256(),
        "script": SCRIPT,
        "script_sha256": _sha256((ROOT / SCRIPT).read_bytes()),
        "tree": _tree(),
        "written_before_this_measurement_asked_any_model": True,
    }


def preregister(out: Path) -> None:
    _write_new(out, "preregistration.json", _registration())


def _registered(out: Path) -> dict[str, Any]:
    registered = _read_record(out / "preregistration.json")
    now = _registration()
    for key in (
        "primary",
        "descriptions",
        "call_timeout_seconds",
        "max_tokens",
        "bound_usd",
        "max_calls",
        "prompt_file_sha256",
        "drafter_sha256",
        "grammar_sha256",
        "thing_catalogs_sha256",
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


def _ask(client: Any, description: str) -> dict[str, Any]:
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
            sender, description, role=Role.CREATURE_DRAFTER, log=CallLog(), max_tokens=MAX_TOKENS
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
    return {
        "description": description,
        "drafted": creature is not None,
        "outcomes": [] if drafted is None else list(drafted.attempts),
        "refusals": [] if drafted is None else [list(refusal) for refusal in drafted.refusals],
        "unanswered": unanswered,
        "failure": failure,
        "bones": None if creature is None else len(creature.plan.bones),
        "attempts": [
            {
                "model_id": usage.model_id,
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


def _asks(client: Any) -> tuple[list[dict[str, Any]], str]:
    asks: list[dict[str, Any]] = []
    for number, description in enumerate(DESCRIPTIONS, 1):
        started = time.monotonic()
        asked = _ask(client, description)
        asked.update(number=number, wall_ms=round((time.monotonic() - started) * 1000))
        asks.append(asked)
        print(
            f"d{number} drafted={asked['drafted']} outcomes={asked['outcomes']} "
            f"unanswered={asked['unanswered']} "
            f"{[a['latency_ms'] for a in asked['attempts']]} ms",
            flush=True,
        )
        if asked["unanswered"] == "over_bound":
            return asks, f"stopped: the bound or the call count, at description {number}"
    return asks, "complete"


def _summary(asks: Sequence[Mapping[str, Any]], primary: str) -> dict[str, Any]:
    calls = [a for ask in asks for a in ask["attempts"] if a["model_id"] == primary]
    answered = [a["latency_ms"] for a in calls if a["outcome"] != "timed_out"]
    return {
        "descriptions": len(asks),
        "drafted": sum(ask["drafted"] for ask in asks),
        "calls": {
            "rows": len(answered),
            "p50_ms": _percentile(answered, 0.5),
            "p99_ms": _percentile(answered, 0.99),
            "longest_ms": max(answered, default=None),
            "timed_out": sum(1 for a in calls if a["outcome"] == "timed_out"),
        },
        "cost_usd": str(sum((Decimal(a["usd"]) for a in calls), Decimal(0))),
        "cost_known": all(a["cost_basis"] == "reported" for a in calls),
    }


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _run(client: Any, *, dry: bool, spent: Callable[[], Decimal]) -> dict[str, Any]:
    started = _now()
    asks, ended_as = _asks(client)
    return {
        "dry_run": dry,
        "provider": "Nebius Token Factory",
        "window": {"started": started, "ended": _now()},
        "ended_as": ended_as,
        "tree": _tree(),
        "manifest_sha256": _manifest_sha256(),
        "asks": asks,
        "summary": _summary(asks, _primary()),
        "spent_usd": str(spent()),
    }


def dry_run(out: Path) -> None:
    """The whole run over a transport that answers every call with a development creature's form,
    spending nothing, so the record path is exercised before money is."""
    from creature_support import form_of
    from model_fakes import FakeTransport, RecordingPolicy, chat_body

    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.manifest import load_manifest
    from exulanica.models.transport import HttpResponse

    form = form_of("horse", label="dry run beast")

    class Answers(FakeTransport):
        def post_json(self, url, *, headers, payload, timeout):  # type: ignore[no-untyped-def]
            self.requests.append({"url": url, "payload": dict(payload)})
            body = chat_body(json.dumps(form), model=payload["model"])
            return HttpResponse(status_code=200, text=json.dumps(body))

    budget = BudgetGuard(ceiling_usd=BOUND_USD, max_calls=MAX_CALLS)
    client = ModelClient(
        api_key="dry-run-key-not-real",
        manifest=_primary_alone(load_manifest()),
        transport=Answers(),
        budget=budget,
        policy=RecordingPolicy(),
    )
    measured = _run(client, dry=True, spent=lambda: budget.spent_usd)
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
    budget = BudgetGuard(ceiling_usd=bound, max_calls=calls)
    reason = "fixed descriptions of imagined creatures written for this measurement, no account holder's data"
    client = ModelClient(
        api_key=key, manifest=_primary_alone(load_manifest()), budget=budget
    ).with_policy(BenchmarkInputs(reason))
    del key
    measured = _run(client, dry=False, spent=lambda: budget.spent_usd)
    _write_new(out, "run.json", measured, record=False)
    (out / "measure_creature_drafter_timings-as-run.py.txt").write_bytes(as_run)
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
            "primary": registered["primary"],
            "summary": measured["summary"],
            "provider": "Nebius Token Factory",
            "spent_usd": measured["spent_usd"],
            "bound_usd": str(bound),
            "max_calls": calls,
            "within_bound": Decimal(measured["spent_usd"]) <= bound,
        },
    )


#: The record the manifest's timeout basis quotes: the primary's own timings and nothing else.
TIMINGS: Final = ROOT / "docs/evaluation/2026-10-07-creature-drafter-timings-2.json"


def timings(out: Path) -> None:
    """Write the primary's own call timings from a complete run's record."""
    record = _read_record(out / "record.json")
    if record["run_sha256"] != _sha256((out / "run.json").read_bytes()):
        raise SystemExit("record.json names a run.json other than the one in --out")
    if record["ended_as"] != "complete":
        raise SystemExit("only a complete run has timings to write")
    calls = record["summary"]["calls"]
    if calls["timed_out"]:
        raise SystemExit(
            f"{calls['timed_out']} calls timed out at {CALL_TIMEOUT_SECONDS} s: no basis below "
            "that timeout can be written from this run"
        )
    timing = {
        "kind": "exulanica.creature-drafter-timings/v2",
        # The shape every timeout basis's record has (tests/test_models_call_bounds.py): the
        # role's primary and its own measured calls. The primary's alone, nothing else.
        "measured": {
            "roles": {
                "creature_drafter": {
                    "primary": record["primary"],
                    "primary_measured": {
                        key: calls[key] for key in ("rows", "p50_ms", "p99_ms", "longest_ms")
                    },
                }
            }
        },
        "descriptions": list(DESCRIPTIONS),
        "run_sha256": record["run_sha256"],
        "provider": record["provider"],
        "script_sha256": record["script_sha256"],
        "tree": record["tree"],
        "window": record["window"],
        "note": (
            "The creature drafter's primary's own calls when its timing measurement asked the 24 "
            "descriptions listed here, simple and complex bodies, each once with the drafter's one "
            "repair: rows are its answered calls. Nothing of any other model is asked or published."
        ),
    }
    document = {
        "profile": PROFILE,
        "record": timing,
        "record_sha256": _sha256(canonical_json(timing)),
    }
    TIMINGS.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {TIMINGS.relative_to(ROOT)}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("preregister", "dry-run", "run", "timings"))
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
    elif arguments.step == "timings":
        timings(out)
    else:
        run(out, as_run, arguments.env_file)


if __name__ == "__main__":
    main()
