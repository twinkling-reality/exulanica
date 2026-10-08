"""Measure the models that may draft a world kind from a person's description.

    uv run python scripts/measure_kind_drafting_models.py preregister --out DIR
    uv run python scripts/measure_kind_drafting_models.py dry-run --out DIR
    EXULANICA_BUDGET_USD=<bound> uv run python scripts/measure_kind_drafting_models.py run \
        --out DIR --env-file PATH
    uv run python scripts/measure_kind_drafting_models.py amend --out DIR --bound-usd USD \
        --bound-calls N --bound-basis TEXT
    uv run python scripts/measure_kind_drafting_models.py continuation-dry-run --out DIR
    EXULANICA_BUDGET_USD=<bound> uv run python scripts/measure_kind_drafting_models.py continue \
        --out DIR --env-file PATH

THE RUN STEP SPENDS MONEY, on Nebius Token Factory. It reads the provider's key, and only that
variable, from the ``.env`` file ``--env-file`` names, into its own process (never into its
environment, never printed or written), and its bound from ``EXULANICA_BUDGET_USD`` (and
``EXULANICA_BUDGET_MAX_CALLS`` when set), neither above what the pre-registration states. It runs
only on the tree the pre-registration names. ``DIR`` is where every file this writes goes; a
comparison of models is kept out of the repository until the provider's terms are confirmed, so
``DIR`` is an ignored folder, and only the chosen models' own timings are later written where the
manifest can quote them.

Every candidate is asked every fixed description through ``draft_kind``, the product's own drafting
path (:mod:`exulanica.selection.kind_drafting`), with the kind drafter's role pointed at the
candidate on an in-memory copy of the manifest (the measurements up to v3.3 drove the specification
drafter's role, before the kind drafter had one; their as-run copies say so). A drafted kind is held to both stages of
the kind checks in this process, as the kind worker holds it. Within each description the
candidates take turns, so a slow minute at the provider falls on all of them.

Measured per description and candidate, each by rule and none by eye: **valid** (a kind that
passed both stages after at most two repairs), **valid on the first try**, and **matched** (the
description's pre-registered checks hold for the drafted kind). ``preregister`` writes the
descriptions, their checks, the candidates, the rule, the bound and the stop rules before any model
is asked; ``dry-run`` drives the whole run over a scripted transport that answers every call with a
hand-written test kind's brief, spending nothing; ``run`` refuses unless the pre-registration still matches.

A run cut off from outside before it wrote its record is continued, never restarted: ``amend``
writes, before any call, the amendment naming the drafts the cut-off log observed, what the cut-off
part is charged and the continuation's bound; ``continue`` (THE CONTINUATION SPENDS MONEY) asks only
the drafts never observed, once, and writes each result as it ends.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import json
import os
import re
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
from exulanica.selection.kind_drafting import DRAFTER_ROLE  # noqa: E402

PROFILE: Final = "exulanica.digest-bound-record/v1"
SCRIPT: Final = "scripts/measure_kind_drafting_models.py"
DRAFTER: Final = "exulanica/selection/kind_drafting.py"
COMPILER: Final = "exulanica/selection/kind_brief.py"
BUDGET_VARIABLE: Final = "EXULANICA_BUDGET_USD"
CALLS_VARIABLE: Final = "EXULANICA_BUDGET_MAX_CALLS"
KEY_VARIABLE: Final = "NEBIUS_API_KEY"
#: The open models root's v3.3 ruling approves from the manifest's catalog on Nebius Token Factory,
#: each with a SHIP licence verdict in docs/license-matrix.md: Nemotron 3.5 Lightning
#: (OpenMDW-1.1), Nemotron 3 Super (the NVIDIA open model licence; the specification drafter's
#: primary), DeepSeek V4 Flash (MIT) and Qwen3 235B Instruct (Apache-2.0; its fallback). Nano 30B
#: ran on in blank space to the token ceiling on 17 of its 18 calls in the v3 run; MiniMax M3's
#: licence is conditional; Nemotron 3 Ultra's is read from the catalog only.
CANDIDATES: Final = (
    "nvidia/Nemotron-3_5-Lightning",
    "nvidia/nemotron-3-super-120b-a12b",
    "deepseek-ai/DeepSeek-V4-Flash-0731",
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
)
#: The most this measurement may spend, on Nebius Token Factory, under root's allocation
#: KINDS-V3.3: every draft at three attempts, each at the budget guard's own worst-case reservation
#: (the 16,384-token ceiling and the longest repairs), USD 0.64243464 over the six descriptions and
#: four candidates, so the bound never cuts the registered order short. The v3 run spent USD
#: 0.0040 a call on Super and 0.0061 on Qwen3 235B.
BOUND_USD: Final = Decimal("0.643")
#: Six descriptions, four candidates and three attempts.
MAX_CALLS: Final = 72
#: The completion ceiling every candidate is asked with, one for all so none is truncated by a
#: choice made for another: the specification drafter's.
MAX_TOKENS: Final = 16384
#: How long one call may take before it is abandoned, the same for every candidate: a brief is
#: several thousand tokens of JSON after a model's own reasoning. Root's v3.1 ruling: 240 s, since
#: Qwen3 235B timed out at 180 s on three of six in the v3 run and answered the others in 15 to
#: 85 s; Super's longest there was 33 s.
CALL_TIMEOUT_SECONDS: Final = 240
#: The run stops when this many drafts in a row for one description gave no valid kind, every
#: candidate: a brief or an instruction every model fails is a defect to
#: fix before more is spent, not a model's skill.
REFUSED_IN_A_ROW: Final = len(CANDIDATES)

#: The fixed descriptions, written for this measurement as a person might type them, with the
#: checks a drafted kind must pass to count as matching its words: what any kind true to the words
#: has, in the vocabulary the drafter is given. A check is data read by :func:`_check`.
CHECKS: Final = {
    "role": "some part takes the engine role, or one of the roles listed (of the form, when given)",
    "form": "some part is of the form (alone, without role)",
    "structures": "at least this many parts are structures",
    "closed_zone": "some zone's access is closed",
    "enclosure": "the site's enclosure is this",
    "people": "someone lives there (a part with the home role) or people come from off the site "
    "(offsite_residents above 0, in the first preset when it names a parameter)",
    "visitors": "some part names a use class that admits visitors (its visitor_affordances are "
    "not empty)",
}
DESCRIPTIONS: Final = (
    {
        "description": (
            "A summer camp in a forest clearing with wooden cabins, a dining hall, a campfire "
            "circle and a lake for canoeing."
        ),
        "checks": [{"role": "water"}, {"people": True}, {"structures": 2}],
    },
    {
        "description": (
            "The inside of a small vet's surgery: a waiting room with chairs, a reception desk, "
            "two consulting rooms and kennels at the back."
        ),
        "checks": [
            {"enclosure": "indoor"},
            {"role": "seat"},
            {"role": "workplace"},
            {"visitors": True},
        ],
    },
    {
        "description": "A tennis club with three grass courts, a clubhouse with a bar and a small car park.",
        "checks": [
            {"role": ["ground", "field"], "form": "area"},
            {"role": "parking", "form": "area"},
            {"visitors": True},
        ],
    },
    {
        "description": "A monastery with a cloister garden, a chapel, a refectory and the monks' cells.",
        "checks": [{"role": ["bed", "home"]}, {"people": True}, {"structures": 2}],
    },
    {
        "description": (
            "A rooftop community garden with raised vegetable beds, a small greenhouse, benches "
            "and a beehive corner nobody may enter."
        ),
        "checks": [{"closed_zone": True}, {"role": "seat"}, {"role": "field"}],
    },
    {
        "description": (
            "A motorway service station with a petrol forecourt, a shop, a cafe, toilets and a "
            "lorry park."
        ),
        "checks": [{"role": "shop"}, {"role": "parking", "form": "area"}, {"visitors": True}],
    },
)
#: The v3.2 run's six held-out descriptions (pre-registration c157f252 and its amendment), all
#: asked and read, so spent: they join the development set.
SPENT_V32: Final = (
    {
        "description": (
            "The inside of a small hairdresser's: a reception desk, styling chairs at mirrors, "
            "wash basins and a bench for waiting."
        ),
        "checks": [
            {"enclosure": "indoor"},
            {"role": "seat"},
            {"role": "workplace"},
            {"visitors": True},
        ],
    },
    {
        "description": (
            "A lakeside boathouse with a wooden jetty, rowing boats for hire and a kiosk selling "
            "ice cream."
        ),
        "checks": [{"role": "water"}, {"role": "workplace"}, {"visitors": True}],
    },
    {
        "description": "A row of almshouses round a garden courtyard with a well and benches.",
        "checks": [{"role": "home"}, {"role": "seat"}, {"people": True}],
    },
    {
        "description": (
            "A market garden with polytunnels, rows of vegetable beds, a packing shed and a farm "
            "shop."
        ),
        "checks": [
            {"role": "field"},
            {"role": "workplace", "form": "structure"},
            {"visitors": True},
        ],
    },
    {
        "description": (
            "A garden centre with greenhouses, long tables of plants for sale, a cafe and a car "
            "park."
        ),
        "checks": [{"role": "shop"}, {"role": "parking", "form": "area"}, {"visitors": True}],
    },
    {
        "description": (
            "A mountain refuge hut with bunk rooms, a common room with a stove, and a woodshed."
        ),
        "checks": [{"role": "bed"}, {"people": True}],
    },
)
#: The v3.1 run's first two held-out descriptions (pre-registration 5b7fb160), asked and read
#: while finding why that run stopped, so spent as held-out; its other four were never asked and
#: stay held-out above.
SPENT_V31: Final = (
    {
        "description": (
            "A riding stables with stalls for the horses, a paddock, a tack room and a small "
            "office."
        ),
        "checks": [
            {"role": "workplace", "form": "structure"},
            {"role": ["field", "ground"], "form": "area"},
            {"people": True},
        ],
    },
    {
        "description": (
            "A village fire station with an engine bay, a crew room, a tower for drying hoses "
            "and a yard."
        ),
        "checks": [{"role": "workplace", "form": "structure"}, {"people": True}],
    },
)
#: The six held-out descriptions of the drafter v3 run (pre-registration 09785e14), read while
#: finding why that run's kinds missed their checks, so spent as a held-out set: they join the
#: development set (:data:`DEVELOPMENT`).
SPENT_DESCRIPTIONS: Final = (
    {
        "description": (
            "A small family farm with a farmhouse, a big red barn, two fields of wheat and a duck "
            "pond."
        ),
        "checks": [
            {"role": "field"},
            {"role": "water"},
            {"role": "home"},
            {"role": "workplace"},
            {"structures": 2},
        ],
    },
    {
        "description": (
            "A building site for a new block of flats: site cabins, a tower crane nobody may walk "
            "under, stacks of bricks and a fence round the edge."
        ),
        "checks": [{"closed_zone": True}, {"role": "workplace"}, {"form": "boundary"}],
    },
    {
        "description": (
            "The inside of a cosy corner cafe: a counter, small tables with chairs, and a kitchen "
            "behind."
        ),
        "checks": [
            {"enclosure": "indoor"},
            {"role": "seat"},
            {"role": "workplace"},
            {"visitors": True},
        ],
    },
    {
        "description": (
            "A little fishing harbour with a quay, moored boats, a fish market and a row of "
            "fishermen's cottages."
        ),
        "checks": [{"role": "water"}, {"role": "home"}, {"visitors": True}],
    },
    {
        "description": "A woodworking yard with a timber store, a saw shed and a small office.",
        "checks": [{"role": "workplace", "form": "structure"}, {"people": True}],
    },
    {
        "description": "A village primary school with classrooms, a playground and a vegetable garden.",
        "checks": [
            {"role": "workplace"},
            {"role": ["ground", "field"], "form": "area"},
            {"people": True},
        ],
    },
)
RULE: Final = {
    "valid": "the kind passed stage A and stage B of the kind checks after at most two repairs",
    "valid_first_try": "the first form the model returned was accepted and its kind passed both stages",
    "matched": "every check of the description holds for the drafted kind",
    "draft_time": "one description's draft time is the sum of its drafter attempts' latencies, as the client measured each",
    "eligible": "a candidate is eligible when at least 5 of the 6 descriptions were valid and at least 4 matched",
    "choice": "the eligible NVIDIA model (identifier beginning nvidia/) with the shortest longest draft time is chosen when that longest is at most speed_bound_ms; otherwise the eligible model with the shortest longest draft time. Ties go to more valid on the first try, then more matched, then the lower total cost. The fallback is the next eligible model in the same order.",
    "speed_bound_ms": 120000,
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


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, check=True, text=True
    ).stdout.strip()


def _tree() -> dict[str, Any]:
    """HEAD, the SHA-256 of ``git diff HEAD --binary`` and of each untracked file git does not
    ignore: the exact tree, uncommitted and new files too."""
    git = ["git", "--no-optional-locks"]
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
        "head": _head(),
        "diff_head_sha256": _sha256(diff),
        "untracked_sha256": {name: _sha256((ROOT / name).read_bytes()) for name in untracked},
    }


def _manifest_sha256() -> str:
    from exulanica.models.manifest import MANIFEST_PATH

    return _sha256(MANIFEST_PATH.read_bytes())


def _pinned(manifest: Any, model_id: str) -> Any:
    """The manifest with the vehicle role pointed at ``model_id`` alone, in memory only."""

    binding = manifest[DRAFTER_ROLE]
    roles = dict(manifest.roles)
    roles[DRAFTER_ROLE] = dataclasses.replace(
        binding,
        primary=manifest.spec(model_id),
        fallback=None,
        timeout_seconds=CALL_TIMEOUT_SECONDS,
    )
    return dataclasses.replace(manifest, roles=roles)


def _instructions() -> tuple[str, Any]:
    from exulanica.selection.kind_drafting import kind_drafting_prompt, render_instructions
    from exulanica.world.kinds.catalogs import load_kind_catalogs
    from exulanica.world.society_living import town_routine

    prompt = kind_drafting_prompt()
    return render_instructions(prompt, load_kind_catalogs(), town_routine()), prompt


def _form_sha256() -> str:
    """The SHA-256 of the schema every request sends, as the client sends it."""
    from exulanica.models.schema import response_format_for
    from exulanica.selection.kind_brief import brief_form

    return _sha256(canonical_json(response_format_for(brief_form(), arrays_last=True)))


def _registration() -> dict[str, Any]:
    from exulanica.world.kinds.catalogs import load_kind_catalogs

    instructions, prompt = _instructions()
    return {
        "question": (
            "Which model should draft a world kind from a person's description: the share of "
            "kinds that pass the kind checks on the first try and after at most two repairs, the "
            "share matching the words by rule, draft time, and cost"
        ),
        "candidates": list(CANDIDATES),
        "candidates_rule": "the open models root's v3.3 ruling approves, NVIDIA models first",
        "descriptions": [dict(entry) for entry in DESCRIPTIONS],
        "checks_meaning": dict(CHECKS),
        "rule": dict(RULE),
        "attempts": "one brief and two repairs at most, the drafter's own rule",
        "not_answered": (
            "a draft the provider did not answer (timed out or failed), or that the run could not "
            "finish, is not valid and is recorded with why; a timed-out attempt is charged its "
            "reservation, as the budget guard holds it"
        ),
        "order": "description by description; within a description every candidate in turn",
        "vehicle_role": f"{DRAFTER_ROLE}, pinned in memory to each candidate",
        "bound_usd": str(BOUND_USD),
        "max_calls": MAX_CALLS,
        "provider": "Nebius Token Factory",
        "stop_rules": [
            f"the bound, USD {BOUND_USD}: a call whose reservation would pass it is not sent",
            f"{MAX_CALLS} calls",
            f"{REFUSED_IN_A_ROW} drafts in a row for one description without a valid kind (every "
            "candidate); a draft is one candidate's brief and its repairs",
            "a run that stops is recorded as stopped, with every call made, and chooses nothing",
        ],
        "call_timeout_seconds": CALL_TIMEOUT_SECONDS,
        "max_tokens": MAX_TOKENS,
        "prompt_version": prompt.prompt_version,
        "prompt_file_sha256": prompt.sha256,
        "instructions_sha256": _sha256(instructions.encode("utf-8")),
        "form_sha256": _form_sha256(),
        "drafter_sha256": _sha256((ROOT / DRAFTER).read_bytes()),
        "compiler_sha256": _sha256((ROOT / COMPILER).read_bytes()),
        "kind_catalogs": dict(load_kind_catalogs().sha256),
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
            "the attempts' outcomes and the refusing check's code",
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
        "compiler_sha256",
        "kind_catalogs",
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


def _uses(document: Mapping[str, Any]) -> dict[str, Any]:
    from exulanica.world.society_living import town_routine

    uses = {key: tuple(use.visitor_affordances) for key, use in town_routine().use_classes.items()}
    uses.update({use["key"]: tuple(use["visitor_affordances"]) for use in document["use_classes"]})
    return uses


def _check(check: Mapping[str, Any], document: Mapping[str, Any] | None) -> bool:
    """Whether ``check`` (one of :data:`CHECKS`) holds for a drafted kind document."""
    if document is None:
        return False
    parts = document["parts"]
    if "role" in check:
        roles = {check["role"]} if isinstance(check["role"], str) else set(check["role"])
        return any(
            roles & set(part["roles"]) and check.get("form", part["form"]) == part["form"]
            for part in parts
        )
    if "form" in check:
        return any(part["form"] == check["form"] for part in parts)
    if "structures" in check:
        return sum(part["form"] == "structure" for part in parts) >= check["structures"]
    if "closed_zone" in check:
        return any(zone["access"] == "closed" for zone in document["zones"])
    if "enclosure" in check:
        return bool(document["site"]["enclosure"] == check["enclosure"])
    if "people" in check:
        offsite = document["society"]["offsite_residents"]
        if isinstance(offsite, dict):
            offsite = document["presets"][0]["values"].get(offsite["parameter"], 0)
        return offsite > 0 or any("home" in part["roles"] for part in parts)
    if "visitors" in check:
        uses = _uses(document)
        return any(uses.get(part["use_class"]) for part in parts if part["use_class"])
    raise SystemExit(f"a check of no known kind: {check}")


def _checked(document: dict[str, Any]) -> Any:
    from exulanica.selection.kind_drafting import KindVerdict
    from exulanica.world.kinds.document import KindRefused, read_kind
    from exulanica.world.kinds.samples import check_samples

    try:
        kind = read_kind(document)
        return KindVerdict(True, kind, check_samples(kind))
    except KindRefused as refused:
        return KindVerdict(False, code=refused.code, where=refused.where, detail=refused.detail)


def _ask(client: Any, entry: Mapping[str, Any]) -> dict[str, Any]:
    from exulanica.models.errors import BudgetExceededError, ModelError
    from exulanica.selection.calls import CallLog
    from exulanica.selection.kind_drafting import draft_kind

    attempts: list[Any] = []
    # The drafter records each attempt here as it goes, so a call that raises keeps the rest.
    trail: list[dict[str, Any]] = []
    sender = client.with_attempts(attempts.append)
    unanswered: str | None = None
    failure = ""
    try:
        drafted = draft_kind(
            sender,
            entry["description"],
            role=DRAFTER_ROLE,
            check=_checked,
            log=CallLog(),
            max_tokens=MAX_TOKENS,
            trail=trail,
        )
    except BudgetExceededError:
        # The guard refused to send: nothing was spent on the call it refused.
        drafted, unanswered = None, "over_bound"
    except ModelError as failed:
        drafted = None
        unanswered = "timed_out" if getattr(failed, "timed_out", False) else "failed"
        failure = f"{type(failed).__name__}: {failed}"[:300]
    except Exception as failed:  # a paid run records what broke rather than losing its calls
        drafted, unanswered = None, "error"
        failure = f"{type(failed).__name__}: {failed}"[:300]
    document = None if drafted is None else drafted.document
    checks = [_check(check, document) for check in entry["checks"]]
    return {
        "valid": document is not None,
        "valid_first_try": drafted is not None and drafted.attempts == ("passed",),
        "matched": document is not None and all(checks),
        "checks": checks,
        "outcomes": [] if drafted is None else list(drafted.attempts),
        # Each attempt as it went: a refused kind's check, place, sentence and document.
        "trail": [dict(step) for step in trail],
        "unanswered": unanswered,
        "failure": failure,
        "refused_by": None
        if drafted is None or drafted.refusal is None or drafted.refusal.check is None
        else list(drafted.refusal.check),
        "kind": None
        if document is None
        else {
            "sha256": hashlib.sha256(canonical_json(document)).hexdigest(),
            "parts": len(document["parts"]),
            "zones": len(document["zones"]),
            "enclosure": document["site"]["enclosure"],
        },
        "document": document,
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


def _append(sink: Path, asked: Mapping[str, Any]) -> None:
    """One draft's result appended to ``sink`` and on disk before the next is asked."""
    sink.parent.mkdir(parents=True, exist_ok=True)
    with sink.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asked, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _asks(
    client_for: Callable[[str], Any], candidates: Sequence[str], sink: Path | None = None
) -> tuple[list[Any], str]:
    """Every description asked of every candidate in turn; each result appended to ``sink`` as
    it ends, so a run cut off from outside keeps every draft it saw."""
    asks: list[dict[str, Any]] = []
    for number, entry in enumerate(DESCRIPTIONS, 1):
        refused_in_a_row = 0
        for model_id in candidates:
            started = time.monotonic()
            asked = _ask(client_for(model_id), entry)
            asked.update(
                description=number,
                model_id=model_id,
                wall_ms=round((time.monotonic() - started) * 1000),
            )
            asks.append(asked)
            if sink is not None:
                _append(sink, asked)
            print(
                f"d{number} {model_id}: valid={asked['valid']} first={asked['valid_first_try']} "
                f"matched={asked['matched']} outcomes={asked['outcomes']} "
                f"unanswered={asked['unanswered']} "
                f"{sum(a['latency_ms'] for a in asked['attempts'])} ms",
                flush=True,
            )
            if asked["unanswered"] == "over_bound":
                return asks, f"stopped: the bound or the call count, at description {number}"
            refused_in_a_row = 0 if asked["valid"] else refused_in_a_row + 1
            if refused_in_a_row >= REFUSED_IN_A_ROW:
                return (
                    asks,
                    f"stopped: {refused_in_a_row} drafts in a row without a valid kind for "
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
    eligible = [s for s in summaries if s["valid"] >= 5 and s["matched"] >= 4]
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
    client_for: Callable[[str], Any],
    *,
    dry: bool,
    spent: Callable[[], Decimal],
    sink: Path | None = None,
) -> dict[str, Any]:
    started = _now()
    asks, ended_as = _asks(client_for, CANDIDATES, sink)
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


def _scripted(budget: Any) -> tuple[Callable[[str], Any], list[dict[str, Any]]]:
    """Clients over a transport that answers every call with the hand-written test farm's brief,
    spending nothing, and the list every request they send is recorded in."""
    from kind_briefs import brief_of, fixture_kind, held_to_form
    from model_fakes import FakeTransport, RecordingPolicy, chat_body

    from exulanica.models.client import ModelClient
    from exulanica.models.manifest import load_manifest
    from exulanica.models.transport import HttpResponse

    form = held_to_form(brief_of(fixture_kind("farm")))
    requests: list[dict[str, Any]] = []

    class Farm(FakeTransport):
        def post_json(self, url, *, headers, payload, timeout):  # type: ignore[no-untyped-def]
            self.requests.append({"url": url, "payload": dict(payload)})
            requests.append({"url": url, "payload": dict(payload)})
            body = chat_body(json.dumps(form), model=payload["model"])
            return HttpResponse(status_code=200, text=json.dumps(body))

    manifest = load_manifest()

    def client_for(model_id: str) -> Any:
        return ModelClient(
            api_key="dry-run-key-not-real",
            manifest=_pinned(manifest, model_id),
            transport=Farm(),
            budget=budget,
            policy=RecordingPolicy(),
        )

    return client_for, requests


def dry_run(out: Path) -> None:
    """The whole run over a transport that answers every call with the hand-written test farm's
    brief, spending nothing, so the record path is exercised before money is."""
    from exulanica.models.budget import BudgetGuard

    budget = BudgetGuard(ceiling_usd=BOUND_USD, max_calls=MAX_CALLS)
    client_for, _ = _scripted(budget)
    sink = out / "dry-run-asks.jsonl"
    if sink.exists():
        raise SystemExit(f"{sink} exists")
    run = _run(client_for, dry=True, spent=lambda: budget.spent_usd, sink=sink)
    _write_new(out, "dry-run.json", run, record=False)


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
    sink = out / "run-asks.jsonl"
    for done in (out / "record.json", sink):
        if done.exists():
            raise SystemExit(f"{done} exists; a measurement runs once")
    # Kept before any call, so a cut-off still names the script that asked.
    (out / "measure_kind_drafting_models-as-run.py.txt").write_bytes(as_run)
    # Only this variable is read from the file, into this process; it is never exported.
    key = api_key_from_env(KEY_VARIABLE, dotenv=env_file)
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(load_manifest().bound_origins()))
    manifest = load_manifest()
    budget = BudgetGuard(ceiling_usd=bound, max_calls=calls)
    reason = "fixed descriptions of kinds of world written for this measurement, no account holder's data"
    clients = {
        model_id: ModelClient(
            api_key=key, manifest=_pinned(manifest, model_id), budget=budget
        ).with_policy(BenchmarkInputs(reason))
        for model_id in CANDIDATES
    }
    del key
    measured = _run(clients.__getitem__, dry=False, spent=lambda: budget.spent_usd, sink=sink)
    _write_new(out, "run.json", measured, record=False)
    decision = measured["decision"]
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
            "decision": decision,
            "provider": "Nebius Token Factory",
            "spent_usd": measured["spent_usd"],
            "bound_usd": str(bound),
            "max_calls": calls,
            "within_bound": Decimal(measured["spent_usd"]) <= bound,
        },
    )


# -- the continuation of a run cut off from outside -----------------------------------------------
#
# The v3.2 run (pre-registration c157f252) was cut off at 12:15 on 2026-10-07 when the session
# that started it ended, before it wrote a record; its log holds the nine drafts it observed. Root's
# ruling (ROOT 4, 14:21): a pre-registered run cut off by an outside cause keeps every result it
# observed and is never restarted, since asking an observed description again would be a second
# look at a held-out set. The continuation takes the logged drafts as given and asks only the drafts
# never observed, in the pre-registered order, under the same tree, prompt, form, drafter, compiler
# and manifest, writing each result as it arrives; the decision is the pre-registered rule's over
# every description.

#: The cut-off run's log, one line per draft as it ended: what that run observed.
CUT_OFF_LOG: Final = "run.log.txt"
CUT_OFF_LOG_SHA256: Final = "eeace2f7cf1bb329f7492e98fa3eb29e5c806a78e42b70cad4365dded6019716"
#: A draft's line, as :func:`_asks` printed it.
_LOGGED: Final = re.compile(
    r"d(?P<description>[0-9]+) (?P<model_id>\S+): valid=(?P<valid>True|False) "
    r"first=(?P<first>True|False) matched=(?P<matched>True|False) "
    r"outcomes=(?P<outcomes>\[[^\]]*\]) unanswered=(?P<unanswered>\S+) (?P<draft_ms>[0-9]+) ms"
)
#: The amendment the continuation runs under, beside the pre-registration it amends.
AMENDMENT: Final = "amendment.json"
#: Each continuation draft is appended here as it ends, so a cut-off keeps every result.
CONTINUATION_ASKS: Final = "continuation-asks.jsonl"
#: The most characters a repair's place in the brief is allowed when sizing a worst-case
#: reservation: a place is a path of field names and indices, a few dozen characters.
_WHERE_ALLOWANCE: Final = 400
#: The most characters of a check's sentence a repair repeats (:func:`draft_kind`).
_DETAIL_CEILING: Final = 400


def _order() -> list[tuple[int, str]]:
    """Every draft, description by description and within a description every candidate."""
    return [
        (number, model_id) for number in range(1, len(DESCRIPTIONS) + 1) for model_id in CANDIDATES
    ]


def _observed(out: Path) -> list[dict[str, Any]]:
    """The drafts the cut-off run's log holds, read from its lines, which must be the log whose
    digest the ruling names and the first drafts of the pre-registered order."""
    data = (out / CUT_OFF_LOG).read_bytes()
    if _sha256(data) != CUT_OFF_LOG_SHA256:
        raise SystemExit(f"{out / CUT_OFF_LOG} is not the cut-off run's log ({CUT_OFF_LOG_SHA256})")
    observed = []
    for number, line in enumerate(data.decode("utf-8").splitlines(), 1):
        found = _LOGGED.fullmatch(line)
        if found is None:
            raise SystemExit(f"{CUT_OFF_LOG} line {number} is not a draft's line: {line!r}")
        observed.append(
            {
                "description": int(found["description"]),
                "model_id": found["model_id"],
                "valid": found["valid"] == "True",
                "valid_first_try": found["first"] == "True",
                "matched": found["matched"] == "True",
                "outcomes": list(ast.literal_eval(found["outcomes"])),
                "unanswered": None if found["unanswered"] == "None" else found["unanswered"],
                "draft_ms": int(found["draft_ms"]),
                "line": line,
                "observed_from": f"{CUT_OFF_LOG} line {number}",
            }
        )
    drafts = [(ask["description"], ask["model_id"]) for ask in observed]
    if drafts != _order()[: len(drafts)]:
        raise SystemExit(f"{CUT_OFF_LOG}'s drafts are not the first of the pre-registered order")
    return observed


def _unobserved(observed: Sequence[Mapping[str, Any]]) -> list[tuple[int, str]]:
    return _order()[len(observed) :]


def _first_prompt_chars() -> dict[int, int]:
    """Each description's first request's prompt characters, as the client counts them for its
    reservation, read from the request the drafter sends over a scripted transport (no spend)."""
    from exulanica.models.budget import BudgetGuard

    chars = {}
    for number, entry in enumerate(DESCRIPTIONS, 1):
        client_for, requests = _scripted(BudgetGuard(ceiling_usd=BOUND_USD, max_calls=MAX_CALLS))
        _ask(client_for(CANDIDATES[0]), entry)
        chars[number] = sum(len(str(message)) for message in requests[0]["payload"]["messages"])
    return chars


def _longest_repair_chars() -> int:
    """The most prompt characters one repair can add, as the client counts a message: the longest
    of the prompt's repairs, the checks' repair with the longest code and meaning, a place of
    :data:`_WHERE_ALLOWANCE` characters and a sentence at the drafter's ceiling."""
    from exulanica.selection.kind_drafting import kind_drafting_prompt
    from exulanica.world.kinds.document import KIND_CODES

    prompt = kind_drafting_prompt()
    checks = prompt.repair_checks.format(
        code=max((code for code, _ in KIND_CODES), key=len),
        where="w" * _WHERE_ALLOWANCE,
        detail="d" * _DETAIL_CEILING,
        meaning=max((meaning for _, meaning in KIND_CODES), key=len),
    )
    texts = (
        checks,
        prompt.repair_refused,
        prompt.repair_truncated,
        prompt.repair_whitespace,
        prompt.repair_repetition,
    )
    return max(len(str({"role": "user", "content": text})) for text in texts)


def _worst_case(chars: Mapping[int, int], repair: int, number: int, model_id: str) -> list[Decimal]:
    """The budget guard's reservation for each attempt a draft may make, its repairs at their
    longest: what a call whose cost was never seen is charged."""
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.manifest import load_manifest
    from exulanica.selection.kind_drafting import DRAFT_ATTEMPTS

    spec = load_manifest().spec(model_id)
    guard = BudgetGuard(ceiling_usd=BOUND_USD, max_calls=MAX_CALLS)
    return [
        guard.estimate_usd(
            spec, prompt_chars=chars[number] + repair * attempt, max_tokens=MAX_TOKENS
        )
        for attempt in range(DRAFT_ATTEMPTS)
    ]


def _charges(observed: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What the cut-off part is charged, each call at its worst-case reservation since no cost of
    it was recorded, and what is left of the pre-registered bound after it; and the most the
    continuation's drafts could reserve."""
    chars = _first_prompt_chars()
    repair = _longest_repair_chars()
    rows = []
    for ask in observed:
        reservations = _worst_case(chars, repair, ask["description"], ask["model_id"])
        # An answered draft made one call per outcome; one the provider left unanswered made an
        # unseen number of calls before the one that failed, so it is charged every attempt.
        calls = len(ask["outcomes"]) if ask["unanswered"] is None else len(reservations)
        rows.append(
            {
                "draft": f"d{ask['description']} {ask['model_id']}",
                "observed": True,
                "calls": calls,
                "usd": str(sum(reservations[:calls], Decimal(0))),
            }
        )
    unobserved = _unobserved(observed)
    if unobserved:
        # The draft under way when the run was cut off: never logged, so any of its attempts may
        # have been sent; charged every attempt.
        number, model_id = unobserved[0]
        reservations = _worst_case(chars, repair, number, model_id)
        rows.append(
            {
                "draft": f"d{number} {model_id}",
                "observed": False,
                "calls": len(reservations),
                "usd": str(sum(reservations, Decimal(0))),
            }
        )
    charged_usd = sum((Decimal(row["usd"]) for row in rows), Decimal(0))
    charged_calls = sum(row["calls"] for row in rows)
    # Count A: one call per observed outcome (one for a draft left unanswered) and one for the
    # draft under way, each at its first attempt's reservation.
    counted = [
        (ask["description"], ask["model_id"], max(1, len(ask["outcomes"]))) for ask in observed
    ]
    if unobserved:
        counted.append((*unobserved[0], 1))
    count_a_usd = sum(
        (
            sum(_worst_case(chars, repair, number, model_id)[:calls], Decimal(0))
            for number, model_id, calls in counted
        ),
        Decimal(0),
    )
    count_a_calls = sum(calls for _, _, calls in counted)
    need = [_worst_case(chars, repair, number, model_id) for number, model_id in unobserved]
    return {
        "first_prompt_chars": {str(number): count for number, count in chars.items()},
        "longest_repair_chars": repair,
        "cut_off_part": rows,
        "cut_off_charged_usd": str(charged_usd),
        "cut_off_charged_calls": charged_calls,
        "count_a": {
            "rule": (
                "one call per observed outcome, one for a draft left unanswered and one for the "
                "draft under way, each at its first attempt's reservation"
            ),
            "usd": str(count_a_usd),
            "calls": count_a_calls,
            "left_of_the_registered_bound": {
                "usd": str(BOUND_USD - count_a_usd),
                "calls": MAX_CALLS - count_a_calls,
            },
        },
        "count_b": {
            "rule": (
                "an answered draft's calls one per outcome; a draft left unanswered and the draft "
                "under way every attempt, repairs at their longest; the cut_off_part rows"
            ),
            "usd": str(charged_usd),
            "calls": charged_calls,
        },
        # The cut-off run's guard admitted a call only while its spend, its held reservations and
        # the call's reservation stayed within the registered bound.
        "cut_off_spend_at_most_usd": str(min(charged_usd, BOUND_USD)),
        "left_of_the_registered_bound": {
            "usd": str(BOUND_USD - charged_usd),
            "calls": MAX_CALLS - charged_calls,
        },
        "continuation_worst_case": {
            "usd": str(sum((sum(row, Decimal(0)) for row in need), Decimal(0))),
            "calls": sum(len(row) for row in need),
        },
    }


def _continuation_asks(
    client_for: Callable[[str], Any], observed: Sequence[Mapping[str, Any]], sink: Path
) -> tuple[list[dict[str, Any]], str]:
    """:func:`_asks` over the drafts the log never observed, the stop rule's count carried from
    the observed drafts of the same description, each result appended to ``sink`` as it ends."""
    seen = {(ask["description"], ask["model_id"]): ask for ask in observed}
    asks: list[dict[str, Any]] = []
    for number, entry in enumerate(DESCRIPTIONS, 1):
        refused_in_a_row = 0
        for model_id in CANDIDATES:
            asked = seen.get((number, model_id))
            if asked is None:
                started = time.monotonic()
                asked = _ask(client_for(model_id), entry)
                asked.update(
                    description=number,
                    model_id=model_id,
                    wall_ms=round((time.monotonic() - started) * 1000),
                    ended=_now(),
                )
                asks.append(asked)
                with sink.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(asked, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                print(
                    f"d{number} {model_id}: valid={asked['valid']} "
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
                    f"stopped: {refused_in_a_row} drafts in a row without a valid kind for "
                    f"description {number}",
                )
    return asks, "complete"


def _combined_summaries(
    observed: Sequence[Mapping[str, Any]], asks: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """:func:`_summaries` over both parts: an observed draft gives its valid, first-try and matched
    readings and its draft time, as its line states them; calls and cost are the continuation's,
    the only ones whose rows were recorded."""
    summaries = []
    for summary in _summaries(asks, CANDIDATES):
        model_id = summary["model_id"]
        seen = [ask for ask in observed if ask["model_id"] == model_id]
        mine = [ask for ask in asks if ask["model_id"] == model_id]
        draft_ms = [ask["draft_ms"] for ask in seen] + [
            sum(a["latency_ms"] for a in ask["attempts"]) for ask in mine
        ]
        summary.update(
            descriptions=len(seen) + len(mine),
            observed_from_the_log=len(seen),
            valid=summary["valid"] + sum(ask["valid"] for ask in seen),
            valid_first_try=summary["valid_first_try"]
            + sum(ask["valid_first_try"] for ask in seen),
            matched=summary["matched"] + sum(ask["matched"] for ask in seen),
            draft_ms={"p50": _percentile(draft_ms, 0.5), "longest": max(draft_ms, default=None)},
            cost_known=summary["cost_known"] and not seen,
        )
        summary["calls"]["of"] = "the continuation's drafts"
        summary["cost_of"] = "the continuation's calls; the cut-off part's cost was never recorded"
        summaries.append(summary)
    return summaries


def _amended(out: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """The pre-registration and its amendment, after checking that everything the
    pre-registration fixed still holds and the script and tree are the amendment's."""
    registered = _read_record(out / "preregistration.json")
    amendment = _read_record(out / AMENDMENT)
    if amendment["preregistration_record_sha256"] != _sha256(canonical_json(registered)):
        raise SystemExit(f"{AMENDMENT} amends another pre-registration")
    now = _registration()
    for key, value in amendment["unchanged"].items():
        if registered[key] != value or now[key] != value:
            raise SystemExit(f"{key} has changed since the pre-registration")
    for key in ("script_sha256", "tree"):
        if amendment[key] != now[key]:
            raise SystemExit(f"{key} has changed since the amendment; amend again")
    return registered, amendment


#: What the pre-registration fixed that the continuation keeps: every key :func:`_registered`
#: checks but the script and the tree, which the amendment states anew.
_UNCHANGED: Final = (
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
    "compiler_sha256",
    "kind_catalogs",
    "manifest_sha256",
)


def amend(out: Path, bound_usd: Decimal, bound_calls: int, basis: str) -> None:
    """Write the amendment the continuation runs under, before it asks any model."""
    registered = _read_record(out / "preregistration.json")
    now = _registration()
    for key in _UNCHANGED:
        if registered[key] != now[key]:
            raise SystemExit(f"{key} has changed since the pre-registration")
    observed = _observed(out)
    charges = _charges(observed)
    log = out / CUT_OFF_LOG
    _write_new(
        out,
        AMENDMENT,
        {
            "amends": "preregistration.json",
            "preregistration_record_sha256": _sha256(canonical_json(registered)),
            "reason": (
                "The run started on root's record of the pre-registration was cut off by an "
                "outside cause: the session that started it ended at its account's usage limit, "
                "after the log's last line and before the run wrote its record, so the drafts it "
                "observed survive only as their log lines and nothing of the draft under way. Root "
                "ruled (ROOT 4, 2026-10-07 14:21 EDT) that a pre-registered run cut off by an "
                "outside cause keeps every result it observed and is never restarted, since "
                "asking an observed description again would be a second look at a held-out set."
            ),
            "cut_off": {
                "log": CUT_OFF_LOG,
                "log_sha256": CUT_OFF_LOG_SHA256,
                "log_last_written": time.strftime(
                    "%Y-%m-%dT%H:%M:%S%z", time.localtime(log.stat().st_mtime)
                ),
                "lines": [ask["line"] for ask in observed],
                "record_written": (out / "record.json").exists(),
            },
            "observed": [
                {key: value for key, value in ask.items() if key != "line"} for ask in observed
            ],
            "asked_in_the_continuation": [
                f"d{number} {model_id}" for number, model_id in _unobserved(observed)
            ],
            "continuation": (
                "the drafts never observed, in the pre-registered order, the stop rule's count "
                "carried from the observed drafts of the same description; each result written to "
                f"{CONTINUATION_ASKS} as it ends; one continuation run, never restarted"
            ),
            "charges": charges,
            "bound": {"usd": str(bound_usd), "calls": bound_calls, "basis": basis},
            "stop_rules": [
                f"the continuation's bound, USD {bound_usd}: a call whose reservation would pass "
                "it is not sent",
                f"{bound_calls} calls in the continuation",
                *registered["stop_rules"][2:],
            ],
            "decision": (
                "the pre-registered rule over descriptions 1 to 6, the observed drafts as their "
                "lines state them; the rule's last tie-break, the lower total cost, reads the "
                "continuation's calls only, the cut-off part's cost never having been recorded"
            ),
            "unchanged": {key: registered[key] for key in _UNCHANGED},
            "script_sha256": now["script_sha256"],
            "tree": now["tree"],
            "notes": [
                "d4 Qwen/Qwen3-235B-A22B-Instruct-2507 and d5 nvidia/nemotron-3-super-120b-a12b "
                "both log 16726 ms: two models on two descriptions with the same millisecond, "
                "unlikely but possible; the log carries nothing more to check it with. Draft time "
                "only orders eligible models, so it cannot change a decision in which "
                "nvidia/nemotron-3-super-120b-a12b, at most 3 matched of 6, is not eligible.",
            ],
            "written_before_the_continuation_asked_any_model": True,
        },
    )


def _continuation(
    client_for: Callable[[str], Any],
    out: Path,
    sink: Path,
    *,
    dry: bool,
    spent: Callable[[], Decimal],
) -> dict[str, Any]:
    observed = _observed(out)
    started = _now()
    asks, ended_as = _continuation_asks(client_for, observed, sink)
    summaries = _combined_summaries(observed, asks)
    return {
        "dry_run": dry,
        "provider": "Nebius Token Factory",
        "window": {"started": started, "ended": _now()},
        "ended_as": ended_as,
        "tree": _tree(),
        "manifest_sha256": _manifest_sha256(),
        "observed": observed,
        "asks": asks,
        "summaries": summaries,
        "decision": choose(summaries) if ended_as == "complete" else None,
        "spent_usd": str(spent()),
    }


def continuation_dry_run(out: Path) -> None:
    """The continuation over the scripted transport, spending nothing, beside the cut-off log."""
    from exulanica.models.budget import BudgetGuard

    sink = out / "continuation-dry-run-asks.jsonl"
    if sink.exists():
        raise SystemExit(f"{sink} exists")
    budget = BudgetGuard(ceiling_usd=BOUND_USD, max_calls=MAX_CALLS)
    client_for, _ = _scripted(budget)
    measured = _continuation(client_for, out, sink, dry=True, spent=lambda: budget.spent_usd)
    _write_new(out, "continuation-dry-run.json", measured, record=False)


def continue_run(out: Path, as_run: bytes, env_file: Path | None) -> None:
    """THE CONTINUATION SPENDS MONEY: the drafts the cut-off run never observed, once."""
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.credentials import api_key_from_env
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
    from exulanica.models.manifest import load_manifest
    from exulanica.models.policy import BenchmarkInputs

    registered, amendment = _amended(out)
    raw = os.environ.get(BUDGET_VARIABLE)
    if not raw:
        raise SystemExit(f"{BUDGET_VARIABLE} must state this run's bound")
    bound = Decimal(raw)
    if not Decimal(0) < bound <= Decimal(amendment["bound"]["usd"]):
        raise SystemExit(
            f"{BUDGET_VARIABLE}={bound} is not within (0, {amendment['bound']['usd']}]"
        )
    calls = int(os.environ.get(CALLS_VARIABLE) or amendment["bound"]["calls"])
    if not 0 < calls <= amendment["bound"]["calls"]:
        raise SystemExit(
            f"{CALLS_VARIABLE}={calls} is not within (0, {amendment['bound']['calls']}]"
        )
    if env_file is None or not env_file.is_file():
        raise SystemExit("--env-file names the .env file the provider's key is read from")
    sink = out / CONTINUATION_ASKS
    for done in (sink, out / "record.json", out / "continuation.json"):
        if done.exists():
            raise SystemExit(f"{done} exists; the continuation runs once")
    # Kept before any call, so a cut-off still names the script that asked.
    (out / "measure_kind_drafting_models-continuation-as-run.py.txt").write_bytes(as_run)
    key = api_key_from_env(KEY_VARIABLE, dotenv=env_file)
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(load_manifest().bound_origins()))
    manifest = load_manifest()
    budget = BudgetGuard(ceiling_usd=bound, max_calls=calls)
    reason = "fixed descriptions of kinds of world written for this measurement, no account holder's data"
    clients = {
        model_id: ModelClient(
            api_key=key, manifest=_pinned(manifest, model_id), budget=budget
        ).with_policy(BenchmarkInputs(reason))
        for model_id in CANDIDATES
    }
    del key
    measured = _continuation(
        clients.__getitem__, out, sink, dry=False, spent=lambda: budget.spent_usd
    )
    _write_new(out, "continuation.json", measured, record=False)
    _write_new(
        out,
        "record.json",
        {
            "preregistration_record_sha256": _sha256(canonical_json(registered)),
            "amendment_record_sha256": _sha256(canonical_json(amendment)),
            "cut_off": (
                "The run started on root's record of the pre-registration was cut off by an "
                "outside cause after its log's ninth line and wrote no record; its nine observed "
                "drafts are taken as their log lines state them, the draft under way then was "
                "never seen, and this continuation asked only the drafts never observed, once."
            ),
            "cut_off_log_sha256": CUT_OFF_LOG_SHA256,
            "continuation_sha256": _sha256((out / "continuation.json").read_bytes()),
            "continuation_asks_sha256": _sha256(sink.read_bytes()) if sink.exists() else None,
            "script_sha256": _sha256(as_run),
            "tree": measured["tree"],
            "window": measured["window"],
            "ended_as": measured["ended_as"],
            "rule": registered["rule"],
            "summaries": measured["summaries"],
            "decision": measured["decision"],
            "provider": "Nebius Token Factory",
            "spent_usd": measured["spent_usd"],
            "spent_of": "the continuation's calls",
            "cut_off_charged_usd": amendment["charges"]["cut_off_charged_usd"],
            "cut_off_charged_calls": amendment["charges"]["cut_off_charged_calls"],
            "bound_usd": str(bound),
            "max_calls": calls,
            "within_bound": Decimal(measured["spent_usd"]) <= bound,
        },
    )


#: The record the manifest's timeout basis quotes: the chosen primary's own timings and nothing
#: else. The candidates' comparison stays out of the repository until the provider's terms are
#: confirmed.
TIMINGS: Final = ROOT / "docs/evaluation/2026-10-07-kind-drafter-timings.json"


def timings(out: Path) -> None:
    """Write the chosen primary's own call timings from a complete run's record."""
    record = _read_record(out / "record.json")
    if record["run_sha256"] != _sha256((out / "run.json").read_bytes()):
        raise SystemExit("record.json names a run.json other than the one in --out")
    if record["ended_as"] != "complete" or record["decision"] is None:
        raise SystemExit("only a complete run's decision has timings to write")
    primary = record["decision"]["primary"]
    if primary is None:
        raise SystemExit("the run chose no model, so there are no timings to write")
    [summary] = [s for s in record["summaries"] if s["model_id"] == primary]
    calls = summary["calls"]
    timing = {
        "kind": "exulanica.kind-drafter-timings/v1",
        # The shape every timeout basis's record has (tests/test_models_call_bounds.py): the
        # role's primary and its own measured calls. The primary's alone, nothing else.
        "measured": {
            "roles": {
                "kind_drafter": {
                    "primary": primary,
                    "primary_measured": {
                        key: calls[key] for key in ("rows", "p50_ms", "p99_ms", "longest_ms")
                    },
                }
            }
        },
        "run_sha256": record["run_sha256"],
        "provider": record["provider"],
        "script_sha256": record["script_sha256"],
        "tree": record["tree"],
        "window": record["window"],
        "note": (
            "The kind drafter's primary's own calls when its pre-registered measurement asked six "
            "held-out descriptions: rows are its calls, a brief and up to two repairs where one "
            "was asked. Nothing of any other model is published here."
        ),
    }
    document = {
        "profile": PROFILE,
        "record": timing,
        "record_sha256": _sha256(canonical_json(timing)),
    }
    TIMINGS.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {TIMINGS.relative_to(ROOT)}", file=sys.stderr)


#: Descriptions written for developing the drafter, never the measurement's: a kind drafted from one
#: of these is seen, read and fixed against, so it says nothing of how the drafter meets words it
#: was not developed on.
DEVELOPMENT: Final = (
    "A riverside campsite with tents, a fire pit and a wash block.",
    "A small bakery with a shop at the front and the ovens behind.",
    "Allotment gardens with sheds, water butts and a tool store.",
    "A railway station platform with a ticket office, benches and a coffee kiosk.",
    "A car repair garage with two work bays and an office.",
    "A beach with a lifeguard hut, a snack kiosk and deck chairs.",
    "A library reading room with shelves, reading tables and a desk.",
    "A vineyard with rows of vines, a winery and a tasting room.",
    *(entry["description"] for entry in SPENT_DESCRIPTIONS),
    *(entry["description"] for entry in SPENT_V31),
    *(entry["description"] for entry in SPENT_V32),
)
#: Root's development allocation for the brief drafter, KINDS-5-DEV, on Nebius Token Factory,
#: over every development run that names it (KINDS-4-DEV's runs, of the earlier drafters, are not
#: counted against it). Development stops at either bound or once 6 of the 8 descriptions have
#: drafted a valid kind on the drafter as it stands.
DEVELOPMENT_ALLOCATION: Final = "KINDS-5-DEV"
DEVELOPMENT_USD: Final = Decimal("0.30")
DEVELOPMENT_CALLS: Final = 40
DEVELOPMENT_ENOUGH: Final = 6


def _drafter_digests() -> tuple[str, str, str]:
    """The prompt file's, the drafter's and the compiler's SHA-256: the drafter as it stands."""
    return (
        _instructions()[1].sha256,
        _sha256((ROOT / DRAFTER).read_bytes()),
        _sha256((ROOT / COMPILER).read_bytes()),
    )


def develop(
    out: Path,
    env_file: Path | None,
    models: Sequence[str],
    descriptions: Sequence[int],
    *,
    confirm: bool = False,
) -> None:
    """Ask ``models`` the development descriptions numbered ``descriptions``, recording every
    attempt; within what is left of the development allocation after the runs already in ``out``.
    Development stops after a description once :data:`DEVELOPMENT_ENOUGH` descriptions have drafted
    a valid kind on the drafter as it stands; with ``confirm``, every description named is asked,
    to confirm a final drafter."""
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.credentials import api_key_from_env
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
    from exulanica.models.manifest import load_manifest
    from exulanica.models.policy import BenchmarkInputs

    written = [
        json.loads(path.read_text("utf-8")) for path in sorted(out.glob("development-*.json"))
    ]
    earlier = [run for run in written if run.get("allocation") == DEVELOPMENT_ALLOCATION]
    spent = sum((Decimal(run["spent_usd"]) for run in earlier), Decimal(0))
    called = sum(run["calls"] for run in earlier)
    bound = DEVELOPMENT_USD - spent
    calls = DEVELOPMENT_CALLS - called
    asked = os.environ.get(BUDGET_VARIABLE)
    if asked:
        bound = min(bound, Decimal(asked))
    asked_calls = os.environ.get(CALLS_VARIABLE)
    if asked_calls:
        calls = min(calls, int(asked_calls))
    if bound <= 0 or calls <= 0:
        raise SystemExit(f"the development allocation is spent: USD {spent}, {called} calls")
    if env_file is None or not env_file.is_file():
        raise SystemExit("--env-file names the .env file the provider's key is read from")
    digests = _drafter_digests()
    tree = _tree()
    valid = {
        ask["description"]
        for run in earlier
        if (run["prompt_file_sha256"], run.get("drafter_sha256"), run.get("compiler_sha256"))
        == digests
        for ask in run["asks"]
        if ask["valid"]
    }
    if not confirm and len(valid) >= DEVELOPMENT_ENOUGH:
        raise SystemExit(f"{len(valid)} descriptions are already valid on this drafter; stopped")
    key = api_key_from_env(KEY_VARIABLE, dotenv=env_file)
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(load_manifest().bound_origins()))
    manifest = load_manifest()
    budget = BudgetGuard(ceiling_usd=bound, max_calls=calls)
    reason = "descriptions of kinds of world written for developing the drafter, no account holder's data"
    clients = {
        model_id: ModelClient(
            api_key=key, manifest=_pinned(manifest, model_id), budget=budget
        ).with_policy(BenchmarkInputs(reason))
        for model_id in models
    }
    del key
    started = _now()
    asks = []
    ended_as = "complete"
    for number in descriptions:
        entry = {"description": DEVELOPMENT[number - 1], "checks": []}
        for model_id in models:
            asked_one = _ask(clients[model_id], entry)
            asked_one.update(description=number, model_id=model_id)
            asks.append(asked_one)
            if asked_one["valid"]:
                valid.add(number)
            last = asked_one["trail"][-1] if asked_one["trail"] else {}
            print(
                f"dev{number} {model_id}: valid={asked_one['valid']} "
                f"outcomes={asked_one['outcomes']} unanswered={asked_one['unanswered']} "
                f"{last.get('where', '')} {last.get('detail', '')[:160]}",
                flush=True,
            )
            if asked_one["unanswered"] == "over_bound":
                ended_as = f"stopped: the bound or the call count, at description {number}"
                break
        if ended_as != "complete":
            break
        if not confirm and len(valid) >= DEVELOPMENT_ENOUGH:
            ended_as = f"stopped: {len(valid)} descriptions valid, after description {number}"
            break
    record = {
        "development": True,
        "confirmation": confirm,
        "ended_as": ended_as,
        "provider": "Nebius Token Factory",
        "allocation": DEVELOPMENT_ALLOCATION,
        "window": {"started": started, "ended": _now()},
        "tree": tree,
        "tree_unchanged_during_the_run": _tree() == tree,
        "prompt_file_sha256": digests[0],
        "drafter_sha256": digests[1],
        "compiler_sha256": digests[2],
        "models": list(models),
        "descriptions": {str(number): DEVELOPMENT[number - 1] for number in descriptions},
        "asks": asks,
        "calls": sum(len(ask["attempts"]) for ask in asks),
        "spent_usd": str(budget.spent_usd),
        "allocation_left_after": {
            "usd": str(DEVELOPMENT_USD - spent - budget.spent_usd),
            "calls": DEVELOPMENT_CALLS - called - sum(len(ask["attempts"]) for ask in asks),
        },
        "valid_on_this_drafter": sorted(valid),
    }
    _write_new(out, f"development-{len(written) + 1:02d}.json", record, record=False)
    print(
        f"spent USD {record['spent_usd']} in {record['calls']} calls; left {record['allocation_left_after']}"
    )
    print(
        f"{ended_as}; valid on this drafter: {len(valid)} of {len(DEVELOPMENT)} descriptions "
        f"{sorted(valid)}; development stops at {DEVELOPMENT_ENOUGH}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "step",
        choices=(
            "preregister",
            "dry-run",
            "run",
            "develop",
            "amend",
            "continuation-dry-run",
            "continue",
            "timings",
        ),
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, help="run: the .env file the key is read from")
    parser.add_argument("--models", nargs="*", default=list(CANDIDATES), help="develop: models")
    parser.add_argument(
        "--descriptions", nargs="*", type=int, default=[], help="develop: numbers, 1 to 22"
    )
    parser.add_argument(
        "--confirm", action="store_true", help="develop: ask every description named"
    )
    parser.add_argument("--bound-usd", type=Decimal, help="amend: the continuation's bound")
    parser.add_argument("--bound-calls", type=int, help="amend: the continuation's calls")
    parser.add_argument("--bound-basis", help="amend: the allocation the bound comes from")
    arguments = parser.parse_args()
    out = arguments.out.resolve()
    if out == ROOT or (ROOT in out.parents and ".exulanica" not in out.parts):
        raise SystemExit("--out names a folder git ignores (under .exulanica), never a tracked one")
    as_run = (ROOT / SCRIPT).read_bytes()
    if arguments.step == "preregister":
        preregister(out)
    elif arguments.step == "dry-run":
        dry_run(out)
    elif arguments.step == "amend":
        if (
            arguments.bound_usd is None
            or arguments.bound_calls is None
            or not arguments.bound_basis
        ):
            raise SystemExit("amend states --bound-usd, --bound-calls and --bound-basis")
        amend(out, arguments.bound_usd, arguments.bound_calls, arguments.bound_basis)
    elif arguments.step == "continuation-dry-run":
        continuation_dry_run(out)
    elif arguments.step == "continue":
        continue_run(out, as_run, arguments.env_file)
    elif arguments.step == "timings":
        timings(out)
    elif arguments.step == "develop":
        numbers = arguments.descriptions or list(range(1, len(DEVELOPMENT) + 1))
        develop(out, arguments.env_file, arguments.models, numbers, confirm=arguments.confirm)
    else:
        run(out, as_run, arguments.env_file)


if __name__ == "__main__":
    main()
