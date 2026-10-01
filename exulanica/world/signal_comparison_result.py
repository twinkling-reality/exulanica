"""What a signal comparison's records say: its catalogs, its definition's checks, each run's
outcome, and the comparison as the reads serve it.

A signal comparison is read by its own measure, the mean delay per entry at its group's signalled
junctions (:func:`~exulanica.world.signal_comparison.measure`), each run's integer terms beside
it: the vehicles that entered each signal's junction and their summed delay, and what the
episode's trips came to. Nothing here is a person's score or shares one's scale. Each run also
states what its arm's model was asked: every choice point's receipt by status and reason, the
greens it kept and let end, what it cost and how long each ask took. A choice point the model did
not answer in time, refused or answered with something not offered is the plan's switch, and its
receipt says which.

Differences between arms are paired over seeds and read by the person comparison's claim module
(:mod:`exulanica.world.society_comparison_claim`), which takes any exact per-seed measure: a
percentile bootstrap from SHA-256 draws and Holm's procedure over the registered family. A
comparison on development seeds is ``not_judged`` (``development_seeds``), whatever its numbers.
Cars in these episodes do not see walkers (``crossings_fed: false``), which every result states.

Nothing here reads a world, a model or a database.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from functools import cache
from pathlib import Path
from typing import Any, Final

from exulanica.models.usage import usd_string
from exulanica.world.signal_comparison import PlayedSignalRun, SignalRunPlan, measure
from exulanica.world.signal_comparison_repository import (
    DEFINITION_PROFILE,
    FAILURE_PROFILE,
    RUN_PROFILE,
    SignalComparisonRefused,
)
from exulanica.world.society_comparison_claim import Protocol, family_differences

__all__ = [
    "ARM_ROLES",
    "LISTING_PROFILE",
    "RESULT_PROFILE",
    "SignalCatalogs",
    "check_definition",
    "comparison_result",
    "failure_outcome",
    "listing_document",
    "run_outcome",
    "signal_catalogs",
]

#: What an arm is to its comparison: a model compared, the same model run again to bound
#: run-to-run variation, or the plan's fixed timing, the measure's baseline.
ARM_ROLES: Final = ("candidate", "control", "one")
LISTING_PROFILE: Final = "exulanica.signal-comparisons/v1"
RESULT_PROFILE: Final = "exulanica.signal-comparison-result/v1"
_CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2] / "assets" / "catalogs" / "traffic-comparison"
)
_PROTOCOL_KEYS: Final = frozenset(
    {
        "bootstrap_resamples",
        "family_alpha_per_mille",
        "interval_per_mille",
        "runs_at_once",
        "seeds_most",
    }
)
#: Places a delay in milliseconds is written to: a mean of whole milliseconds over a few dozen
#: entries, shown to a hundredth of a millisecond.
_PLACES: Final = 2


@dataclass(frozen=True, slots=True)
class SignalCatalogs:
    """The protocol and seed catalogs a signal comparison is defined and judged under."""

    protocol: Mapping[str, int]
    seeds: Mapping[str, Mapping[str, Any]]
    versions: Mapping[str, int]

    def value(self, key: str) -> int:
        return int(self.protocol[key])

    def development_seeds(self) -> tuple[str, ...]:
        """The development seeds whose text the catalog commits, in its order."""
        return tuple(
            str(entry["seed"])
            for entry in self.seeds.values()
            if entry["phase"] == "development" and "seed" in entry
        )


@cache
def signal_catalogs() -> SignalCatalogs:
    """The signal comparison catalogs a new comparison is defined under, refused by name where a
    protocol states a key no reader reads or a seed's text is not the digest it is committed by."""
    protocol = json.loads(
        (_CATALOG_DIRECTORY / "signal-comparison-protocol.v1.json").read_text(encoding="utf-8")
    )
    seeds = json.loads(
        (_CATALOG_DIRECTORY / "signal-comparison-seeds.v1.json").read_text(encoding="utf-8")
    )
    values = {entry["key"]: entry["value"] for entry in protocol["entries"]}
    if set(values) != _PROTOCOL_KEYS or any(type(value) is not int for value in values.values()):
        raise SignalComparisonRefused("protocol_keys", "the signal protocol is not one this reads")
    for entry in seeds["entries"]:
        text = entry.get("seed")
        if text is not None and hashlib.sha256(text.encode()).hexdigest() != entry["seed_digest"]:
            raise SignalComparisonRefused("seed_text", f"{entry['key']} is not its digest's text")
        if entry["phase"] != "development" and text is not None:
            raise SignalComparisonRefused("held_out_seed_text", f"{entry['key']} states its text")
    return SignalCatalogs(
        protocol=values,
        seeds={entry["key"]: entry for entry in seeds["entries"]},
        versions={
            protocol["catalog_id"]: int(protocol["catalog_version"]),
            seeds["catalog_id"]: int(seeds["catalog_version"]),
        },
    )


def check_definition(document: Mapping[str, Any], catalogs: SignalCatalogs) -> None:
    """Refuse by name a definition this code cannot run or read as it states itself."""
    if document["profile"] != DEFINITION_PROFILE:
        raise SignalComparisonRefused("definition_profile", "not a signal comparison definition")
    phase = document["phase"]
    committed = {
        str(entry["seed_digest"]) for entry in catalogs.seeds.values() if entry["phase"] == phase
    }
    seeds = list(document["seeds"])
    if not seeds or len(set(seeds)) != len(seeds) or not set(seeds) <= committed:
        raise SignalComparisonRefused(
            "seeds_not_committed", f"each seed is named once and committed to {phase}"
        )
    if len(seeds) > catalogs.value("seeds_most"):
        raise SignalComparisonRefused("seeds_out_of_range", "more seeds than the protocol runs")
    if phase == "development" and document["preregistration"] is not None:
        raise SignalComparisonRefused(
            "preregistration_not_held_out", "a development comparison is not registered"
        )
    arms = document["arms"]
    roles = [arm["role"] for arm in arms.values()]
    if any(role not in ARM_ROLES for role in roles) or roles.count("one") != 1:
        raise SignalComparisonRefused("arms_not_anchored", "one fixed-timing arm, known roles")
    if roles.count("candidate") < 1:
        raise SignalComparisonRefused("no_candidate", "a comparison compares at least one model")
    for key, arm in arms.items():
        kind = arm["decider"]["kind"]
        expected = "fixed" if arm["role"] == "one" else "model"
        if kind != expected or (kind == "model") != (arm["provider_config"] is not None):
            raise SignalComparisonRefused("arm_decider", f"arm {key} is a {arm['role']} by {kind}")
    claim = document["claim"]
    family = [tuple(pair) for pair in claim["family"]]
    if tuple(claim["primary"]) not in family or any(
        arm not in arms for pair in family for arm in pair
    ):
        raise SignalComparisonRefused("claim_arms", "the primary difference is the family's")
    control = claim["control"]
    if control is not None and (
        arms[control[0]]["role"] != "candidate"
        or arms[control[1]]["role"] != "control"
        or arms[control[0]]["decider"] != arms[control[1]]["decider"]
    ):
        raise SignalComparisonRefused("claim_control", "a control is one candidate and its repeat")
    group = list(document["group"])
    if not group or group != sorted(set(group)):
        raise SignalComparisonRefused("group_empty", "a group names each signal once, in order")


def call_facts(receipts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What a run's asking came to, from its receipts: never part of its measure."""
    asked = [receipt for receipt in receipts if receipt["provider"] is not None]
    statuses: dict[str, int] = {}
    reasons: dict[str, int] = {}
    kept = 0
    for receipt in receipts:
        statuses[receipt["status"]] = statuses.get(receipt["status"], 0) + 1
        reasons[receipt["reason"]] = reasons.get(receipt["reason"], 0) + 1
        if receipt["status"] == "accepted" and receipt["proposal"]["option"]["kind"] == "keep":
            kept += 1
    return {
        "points": len(receipts),
        "asked": len(asked),
        "kept": kept,
        "let_end": len(receipts) - kept,
        "statuses": dict(sorted(statuses.items())),
        "reasons": dict(sorted(reasons.items())),
        "cost_usd": usd_string(
            sum((Decimal(receipt["provider"]["cost_usd"]) for receipt in asked), Decimal(0))
        ),
        "cost_known": all(receipt["provider"]["cost_known"] for receipt in asked),
        "latencies_ms": [int(receipt["provider"]["latency_ms"]) for receipt in asked],
    }


def run_outcome(
    plan: SignalRunPlan,
    definition: Mapping[str, Any],
    arm: str,
    digest: str,
    played: PlayedSignalRun,
) -> dict[str, Any]:
    """A completed run's one terminal fact: its episode's end, its receipts and its measure."""
    return {
        "profile": RUN_PROFILE,
        "status": "completed",
        "definition_sha256": definition["document_sha256"],
        "arm": arm,
        "seed_digest": digest,
        "episode": plan.episode,
        "continuation_sha256": played.continuation_sha256,
        "receipts": {"count": len(played.receipts), "sha256": played.receipts_sha256},
        "terms": played.terms,
        "calls": call_facts(played.receipts),
    }


def failure_outcome(definition: Mapping[str, Any], arm: str, digest: str, code: str) -> dict:
    """A failed run's one terminal fact, by the code its host stopped it with."""
    return {
        "profile": FAILURE_PROFILE,
        "status": "failed",
        "definition_sha256": definition["document_sha256"],
        "arm": arm,
        "seed_digest": digest,
        "code": code,
    }


def _decimal_ms(numerator: int, denominator: int) -> str:
    quantum = Decimal(1).scaleb(-_PLACES)
    return format((Decimal(numerator) / Decimal(denominator)).quantize(quantum), "f")


def _run_document(run: Mapping[str, Any]) -> dict[str, Any]:
    outcome = run.get("outcome")
    status = "incomplete" if outcome is None else outcome["status"]
    document: dict[str, Any] = {
        "run_id": str(run["run_id"]),
        "status": status,
        "failure": None if status != "failed" else outcome["code"],  # type: ignore[index]
        "measure": None,
        "terms": None,
        "calls": None,
    }
    if status == "completed":
        assert outcome is not None
        found = measure(outcome["terms"])
        document["measure"] = (
            None
            if found is None
            else {
                "delay_ms": found[0],
                "entries": found[1],
                "mean_delay_ms": _decimal_ms(*found),
            }
        )
        document["terms"] = outcome["terms"]
        document["calls"] = outcome["calls"]
    return document


def _differences(
    definition: Mapping[str, Any], seeds: Sequence[Mapping[str, Any]], catalogs: SignalCatalogs
) -> list[dict[str, Any]]:
    """Every registered difference, second minus first in mean delay per entry, over the seeds
    every arm of the family measured, where at least two did: read, never judged here."""
    scores: dict[str, dict[str, Fraction | None]] = {key: {} for key in definition["arms"]}
    for seed in seeds:
        for key, run in seed["runs"].items():
            found = run["measure"]
            scores[key][seed["seed_digest"]] = (
                None if found is None else Fraction(found["delay_ms"], found["entries"])
            )
    family = [tuple(pair) for pair in definition["claim"]["family"]]
    arms = sorted({arm for pair in family for arm in pair})
    shared = [
        seed for seed in scores[arms[0]] if all(scores[arm].get(seed) is not None for arm in arms)
    ]
    if len(shared) < 2:
        return []
    protocol = Protocol(
        resamples=catalogs.value("bootstrap_resamples"),
        interval_per_mille=catalogs.value("interval_per_mille"),
        family_alpha_per_mille=catalogs.value("family_alpha_per_mille"),
    )
    found, rejected = family_differences(
        scores, family=family, key=str(definition["document_sha256"]), protocol=protocol
    )
    return [
        {
            "first": first,
            "second": second,
            "seeds": len(found[(first, second)].seeds),
            "mean_delay_ms": _fraction_text(found[(first, second)].mean),
            "low_ms": _fraction_text(found[(first, second)].low),
            "high_ms": _fraction_text(found[(first, second)].high),
            "rejected": (first, second) in rejected,
        }
        for first, second in family
    ]


def _fraction_text(value: Fraction) -> str:
    quantum = Decimal(1).scaleb(-_PLACES)
    return format((Decimal(value.numerator) / Decimal(value.denominator)).quantize(quantum), "f")


def _arm_document(
    key: str, arm: Mapping[str, Any], model_name: Callable[[str], str]
) -> dict[str, Any]:
    decider = dict(arm["decider"])
    if decider["kind"] == "model":
        decider["name"] = model_name(decider["model_id"])
    return {"key": key, "role": arm["role"], "decider": decider}


def comparison_result(
    row: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    *,
    model_name: Callable[[str], str],
    start: Mapping[str, Any] | None = None,
    catalogs: SignalCatalogs | None = None,
) -> dict[str, Any]:
    """One signal comparison as its read serves it: per seed and per arm each run's measure, terms
    and asking, the registered differences, and the verdict, which development seeds never get."""
    definition = row["document"]
    catalogs = catalogs or signal_catalogs()
    by_seed: dict[str, dict[str, Any]] = {}
    for run in runs:
        by_seed.setdefault(run["seed_digest"], {})[run["arm"]] = _run_document(run)
    seeds = [
        {"seed_digest": digest, "runs": by_seed.get(digest, {})} for digest in definition["seeds"]
    ]
    return {
        "profile": RESULT_PROFILE,
        "comparison_id": str(row["comparison_id"]),
        "created_at": row["created_at"].isoformat(),
        "phase": definition["phase"],
        "roads": definition["roads"],
        "group": definition["group"],
        "signals": definition["signals"],
        "arms": [
            _arm_document(key, arm, model_name) for key, arm in sorted(definition["arms"].items())
        ],
        "measure": {
            "primary": "mean_delay_per_entry_ms",
            "meaning": definition["measure"]["meaning"],
        },
        "seeds": seeds,
        "differences": _differences(definition, seeds, catalogs),
        "verdict": {
            "code": "not_judged" if definition["phase"] == "development" else "incomplete",
            "reason": "development_seeds" if definition["phase"] == "development" else None,
        },
        "start": start,
    }


def listing_document(
    rows: Sequence[Mapping[str, Any]],
    counts: Mapping[Any, tuple[int, int, int]],
    *,
    starts: Mapping[Any, Mapping[str, Any]],
) -> dict[str, Any]:
    """A version's signal comparisons, newest first, each with how far its runs got."""
    return {
        "profile": LISTING_PROFILE,
        "comparisons": [
            {
                "comparison_id": str(row["comparison_id"]),
                "created_at": row["created_at"].isoformat(),
                "phase": row["document"]["phase"],
                "group_size": len(row["document"]["group"]),
                "arms": sorted(row["document"]["arms"]),
                "seeds": len(row["document"]["seeds"]),
                "runs": counts.get(row["comparison_id"], (0, 0, 0))[0],
                "runs_completed": counts.get(row["comparison_id"], (0, 0, 0))[1],
                "runs_finished": counts.get(row["comparison_id"], (0, 0, 0))[2],
                "start": starts.get(row["comparison_id"]),
            }
            for row in rows
        ],
    }
