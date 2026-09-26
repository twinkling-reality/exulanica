"""What a comparison's records say, as the routes serve them: pure, with no database.

A comparison's definition, checked before it is stored (:func:`check_definition_body`); a run's
outcome, built from what the run did (:func:`run_outcome`); a version's comparisons
(:func:`listing_document`); one comparison's scores per seed and per arm, its registered
differences and the server's verdict, read from its definition and its runs' outcomes alone
(:func:`comparison_result`); and one run replayed with no call, as the page draws it
(:func:`replay_document`). No projection here returns a run's seed or a raw state: a reader names
seeds by digest.

The verdict's words are the server's: a comparison is judged only when its seeds are held out, it
registered a claim with a control and a pre-registration, every run completed, and the code that
scores it is the code it registered (:func:`scoring_binding`). The score and the claim themselves
are :mod:`exulanica.world.society_score` and :mod:`exulanica.world.society_comparison_claim`.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

from exulanica.world import society_comparison_claim, society_score
from exulanica.world.society_catalogs import (
    SEED_PHASES,
    ComparisonCatalogs,
    load_comparison_catalogs,
)
from exulanica.world.society_comparison import (
    DECIDER_KINDS,
    PlayedRun,
    ReplayMismatch,
    RunPlan,
    replay,
)
from exulanica.world.society_comparison_claim import (
    Protocol,
    Resamples,
    family_differences,
    judge,
)
from exulanica.world.society_decisions import PERSON_PROVIDER_CONFIG
from exulanica.world.society_planner import routine_of
from exulanica.world.society_score import (
    PersonScore,
    RunTerms,
    need_threshold,
    person_score,
    seed_score,
    state_measures,
)

__all__ = [
    "ARM_ROLES",
    "DECIMAL_PLACES",
    "FAILURE_PROFILE",
    "LISTING_PROFILE",
    "MINUTES_PER_HOUR",
    "PROTOCOL_KEYS",
    "REPLAY_PROFILE",
    "RESULT_PROFILE",
    "RUN_PROFILE",
    "ComparisonRefused",
    "check_definition_body",
    "comparison_result",
    "decimal_text",
    "listing_document",
    "protocol_value",
    "protocol_values",
    "replay_document",
    "run_outcome",
    "scoring_binding",
    "verified_replay",
]

RUN_PROFILE: Final = "exulanica.society-comparison-run/v1"
FAILURE_PROFILE: Final = "exulanica.society-comparison-failure/v1"
LISTING_PROFILE: Final = "exulanica.society-comparisons/v1"
RESULT_PROFILE: Final = "exulanica.society-comparison-result/v1"
REPLAY_PROFILE: Final = "exulanica.society-comparison-run-replay/v1"
#: What an arm is to its comparison, in the order a reader lists them: a model compared, the same
#: model run again to bound run-to-run variation, the routine (the score's one) and waiting (its
#: zero). The page reads exactly these (``ARM_ROLES`` in
#: web/packages/app/src/society-comparison-api.ts, held to this tuple by a parity test).
ARM_ROLES: Final = (
    "candidate",
    "control",
    "one",
    "zero",
)
#: The decider each anchor role runs with.
_ANCHORS: Final = {"one": "routine", "zero": "wait"}
#: Places a decimal the server writes carries. A score is exact until it is written; four places
#: tell apart seeds whose relief differs by a ten-thousandth of what the routine spares, which is
#: finer than any difference a comparison of eight seeds can claim.
DECIMAL_PLACES: Final = 4
_QUANTUM: Final = Decimal(1).scaleb(-DECIMAL_PLACES)
#: A unit: what a run's cost is stated per, whatever window the protocol sets.
MINUTES_PER_HOUR: Final = 60
#: Every value of the comparison protocol catalog this code reads.
PROTOCOL_KEYS: Final = frozenset(
    {
        "bootstrap_resamples",
        "family_alpha_per_mille",
        "interval_per_mille",
        "need_relief_floor",
        "population_maximum",
        "runs_at_once",
        "window_ticks",
    }
)


class ComparisonRefused(ValueError):
    """A comparison this society cannot be given, refused by name."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _module_sha256(module: Any) -> str:
    return hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()


def scoring_binding(catalogs: ComparisonCatalogs | None = None) -> dict[str, Any]:
    """What a comparison is scored and judged under: the three catalogs and the two modules that
    read them, by digest. A comparison read under any other is not judged."""
    found = load_comparison_catalogs() if catalogs is None else catalogs
    return {
        "catalogs": {"versions": dict(sorted(found.versions.items())), "sha256": found.sha256},
        "scorer_sha256": _module_sha256(society_score),
        "claim_sha256": _module_sha256(society_comparison_claim),
    }


def protocol_values(catalogs: ComparisonCatalogs) -> dict[str, int]:
    """The protocol's values, refused by name unless they are exactly the ones read here: a key
    added to the catalog and a key removed from it are both refused, as the decision policy's
    are."""
    values = {key: int(entry["value"]) for key, entry in catalogs.protocol.items()}  # type: ignore[call-overload]
    if set(values) != PROTOCOL_KEYS:
        raise ComparisonRefused(
            "protocol_keys",
            f"the protocol states {sorted(values)}; read are {sorted(PROTOCOL_KEYS)}",
        )
    return values


def _protocol(catalogs: ComparisonCatalogs) -> Protocol:
    values = protocol_values(catalogs)
    return Protocol(
        resamples=values["bootstrap_resamples"],
        interval_per_mille=values["interval_per_mille"],
        family_alpha_per_mille=values["family_alpha_per_mille"],
    )


def protocol_value(catalogs: ComparisonCatalogs, key: str) -> int:
    return protocol_values(catalogs)[key]


def check_definition_body(body: Mapping[str, Any], catalogs: ComparisonCatalogs) -> None:
    """Refuse by name a definition this code cannot run or judge as it states itself."""
    phase = body["phase"]
    if phase not in SEED_PHASES:
        raise ComparisonRefused("phase_unknown", f"no phase {phase!r}")
    committed = {
        str(entry["seed_digest"]) for entry in catalogs.seeds.values() if entry["phase"] == phase
    }
    seeds = list(body["seeds"])
    if not seeds or len(set(seeds)) != len(seeds) or not set(seeds) <= committed:
        raise ComparisonRefused(
            "seeds_not_committed", f"each seed is named once and committed to {phase}"
        )
    if phase == "development" and body["preregistration"] is not None:
        # 0113 holds the same rule; it is refused here by name before it is a database error.
        raise ComparisonRefused(
            "preregistration_not_held_out", "a development comparison is not judged or registered"
        )
    if body["window_ticks"] != protocol_value(catalogs, "window_ticks"):
        raise ComparisonRefused("window_not_the_protocol", "a comparison runs the protocol's hour")
    arms = body["arms"]
    roles = Counter(arm["role"] for arm in arms.values())
    if any(role not in ARM_ROLES for role in roles) or roles["one"] != 1 or roles["zero"] != 1:
        raise ComparisonRefused(
            "arms_not_anchored", "one routine arm, one waiting arm, known roles"
        )
    if roles["candidate"] < 1:
        raise ComparisonRefused("no_candidate", "a comparison compares at least one model")
    candidates = {key: arm for key, arm in arms.items() if arm["role"] == "candidate"}
    for key, arm in arms.items():
        kind = arm["decider"]["kind"]
        anchor = _ANCHORS.get(arm["role"])
        if kind not in DECIDER_KINDS or (anchor or "model") != kind:
            raise ComparisonRefused("arm_decider", f"arm {key} is a {arm['role']} run by {kind}")
        config = arm["provider_config"]
        if (kind == "model") != (config is not None):
            raise ComparisonRefused(
                "arm_provider", f"exactly a model arm records its asking: {key}"
            )
        if config is not None and (
            set(config) != PERSON_PROVIDER_CONFIG
            or (config["provider"], config["model_id"])
            != (arm["decider"]["provider"], arm["decider"]["model_id"])
        ):
            raise ComparisonRefused("arm_provider", f"arm {key} records the model it asks")
        if arm["role"] == "control" and not any(
            arm["decider"] == other["decider"] for other in candidates.values()
        ):
            raise ComparisonRefused("control_without_candidate", f"arm {key} repeats no candidate")
    claim = body["claim"]
    if claim is None:
        if phase == "held_out":
            raise ComparisonRefused("claim_not_registered", "a held-out comparison registers one")
        return
    family = [tuple(pair) for pair in claim["family"]]
    if tuple(claim["primary"]) not in family or any(
        arm not in arms for pair in family for arm in pair
    ):
        raise ComparisonRefused("claim_arms", "the primary difference is one of the family's")
    control = claim["control"]
    if control is not None and (
        arms[control[0]]["role"] != "candidate"
        or arms[control[1]]["role"] != "control"
        or arms[control[0]]["decider"] != arms[control[1]]["decider"]
    ):
        raise ComparisonRefused("claim_control", "a control is one candidate and its repeat")
    if phase == "held_out" and (control is None or not isinstance(body["preregistration"], dict)):
        raise ComparisonRefused("claim_not_registered", "a judged claim has a control, registered")


def decimal_text(value: Fraction) -> str:
    """An exact value as the server writes it: rounded half to even at ``DECIMAL_PLACES``."""
    written = (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
        _QUANTUM, rounding=ROUND_HALF_EVEN
    )
    return format(written + Decimal(0), "f")


def _nearest_rank(values: Sequence[int], share: int) -> int | None:
    """The nearest-rank percentile: the smallest value with ``share`` percent at or below it."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, -(-share * len(ordered) // 100) - 1)]


def run_outcome(
    plan: RunPlan,
    definition: Mapping[str, Any],
    arm: str,
    seed_digest_text: str,
    played: PlayedRun,
    calls: Mapping[str, Any] | None,
    score: PersonScore,
) -> dict[str, Any]:
    """A completed run's outcome: its minutes' digests, its events and receipts, the score's
    integer terms and, for a model arm, what its asking took. Every run of a comparison is
    scored over all of its people."""
    threshold = need_threshold(routine_of(plan.inputs[-1]))
    terms = society_score.run_terms(
        played.states,
        played.events,
        people=[person["id"] for person in played.start["inhabitants"]],
        threshold=threshold,
        score=score,
    )
    return {
        "profile": RUN_PROFILE,
        "status": "completed",
        "definition_sha256": definition["document_sha256"],
        "arm": arm,
        "seed_digest": seed_digest_text,
        "minutes": {"count": len(played.states), "state_sha256": played.minute_digests},
        "events_sha256": played.events_sha256,
        "receipts": {"count": len(played.receipts), "sha256": played.receipts_sha256},
        "terms": terms.document(),
        "calls": None if calls is None else dict(calls),
    }


def _seed_names(catalogs: ComparisonCatalogs) -> dict[str, str]:
    return {str(entry["seed_digest"]): key for key, entry in catalogs.seeds.items()}


def _arm_order(arms: Mapping[str, Any]) -> list[str]:
    return sorted(arms, key=lambda key: (ARM_ROLES.index(arms[key]["role"]), key))


def _difference_document(found: Any, rejected: set[tuple[str, str]] | None) -> dict[str, Any]:
    return {
        "first": found.first,
        "second": found.second,
        "mean": decimal_text(found.mean),
        "low": decimal_text(found.low),
        "high": decimal_text(found.high),
        "rejected": None if rejected is None else (found.first, found.second) in rejected,
    }


def comparison_result(
    row: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    catalogs: ComparisonCatalogs | None = None,
    *,
    model_name: Callable[[str], str],
) -> dict[str, Any]:
    """A comparison's scores, per seed and per arm, its registered differences and the server's
    verdict, read from its definition and its runs' outcomes alone. ``model_name`` names each
    model an arm asks (:func:`_arm_document`)."""
    found_catalogs = load_comparison_catalogs() if catalogs is None else catalogs
    definition = row["document"]
    score = person_score(found_catalogs.score)
    protocol = _protocol(found_catalogs)
    floor = protocol_value(found_catalogs, "need_relief_floor")
    arms = definition["arms"]
    order = _arm_order(arms)
    names = _seed_names(found_catalogs)
    by_seed: dict[str, dict[str, Mapping[str, Any]]] = {seed: {} for seed in definition["seeds"]}
    for run in runs:
        by_seed.setdefault(run["seed_digest"], {})[run["arm"]] = run
    complete = all(
        by_seed[seed].get(arm, {}).get("status") == "completed"
        for seed in definition["seeds"]
        for arm in arms
    )
    scores: dict[str, dict[str, Fraction | None]] = {arm: {} for arm in arms}
    seeds_out = []
    pooled: dict[str, dict[str, Any]] = {
        arm: {
            "turns": 0,
            "not_applied": 0,
            "cost": Fraction(0),
            "cost_known": True,
            "runs": 0,
            "asked": 0,
            "first_refused": 0,
            "latencies": [],
            "measures": [],
        }
        for arm in arms
    }
    anchor = {arms[key]["role"]: key for key in arms if arms[key]["role"] in _ANCHORS}
    for seed in definition["seeds"]:
        held = by_seed[seed]
        terms = {
            arm: RunTerms.from_document(run["outcome"]["terms"])
            for arm, run in held.items()
            if run.get("status") == "completed"
        }
        excluded = None
        runs_out: dict[str, Any] = {}
        for arm in order:
            run = held.get(arm)
            status = "incomplete" if run is None or run.get("status") is None else run["status"]
            value = None
            if arm in terms and anchor["zero"] in terms and anchor["one"] in terms:
                scored = seed_score(
                    terms[arm],
                    waiting=terms[anchor["zero"]],
                    routine=terms[anchor["one"]],
                    score=score,
                    floor=floor,
                )
                excluded = scored.excluded
                value = scored.score
            scores[arm][seed] = value
            calls = None if status != "completed" else run["outcome"]["calls"]  # type: ignore[index]
            run_terms = terms.get(arm)
            if run_terms is not None:
                pool = pooled[arm]
                counted = dict(run_terms.counted)
                pool["turns"] += run_terms.turns
                pool["not_applied"] += sum(counted.values())
                pool["runs"] += 1
                pool["measures"].append(state_measures(run_terms))
                if calls is not None:
                    pool["cost"] += Fraction(Decimal(calls["cost_usd"]))
                    pool["cost_known"] = pool["cost_known"] and calls["cost_known"]
                    pool["asked"] += calls["asked"]
                    pool["first_refused"] += calls["first_answers_refused"]
                    pool["latencies"].extend(calls["latencies_ms"])
            runs_out[arm] = {
                "run_id": None if run is None else str(run["run_id"]),
                "status": status,
                "failure": run["outcome"]["code"] if status == "failed" else None,  # type: ignore[index]
                "score": None if value is None else decimal_text(value),
                "turns": 0 if run_terms is None else run_terms.turns,
                "not_applied": 0 if run_terms is None else sum(dict(run_terms.counted).values()),
                "calls": None
                if calls is None
                else {
                    "asked": calls["asked"],
                    "first_answers_refused": calls["first_answers_refused"],
                    "cost_usd": calls["cost_usd"],
                    "cost_known": calls["cost_known"],
                    "latency_ms": {
                        "p50": _nearest_rank(calls["latencies_ms"], 50),
                        "p95": _nearest_rank(calls["latencies_ms"], 95),
                    },
                },
            }
        seeds_out.append(
            {"seed_digest": seed, "name": names.get(seed), "excluded": excluded, "runs": runs_out}
        )
    summaries = {}
    key = definition["document_sha256"]
    for arm in order:
        values = [value for value in scores[arm].values() if value is not None]
        pool = pooled[arm]
        interval = None
        mean = None
        if values:
            mean = sum(values, Fraction(0)) / len(values)
        if len(values) >= 2:
            _mean, low, high, _p = Resamples(f"{key}:arm:{arm}", len(values), protocol).summarise(
                values
            )
            interval = {"low": decimal_text(low), "high": decimal_text(high)}
        measures = pool["measures"]
        summaries[arm] = {
            "mean_score": None if mean is None else decimal_text(mean),
            "interval": interval,
            "not_applied_share": None
            if pool["turns"] == 0
            else decimal_text(Fraction(pool["not_applied"], pool["turns"])),
            "cost_usd_per_hour": None
            if arms[arm]["decider"]["kind"] != "model" or pool["runs"] == 0
            else decimal_text(
                pool["cost"] / pool["runs"] * MINUTES_PER_HOUR / definition["window_ticks"]
            ),
            "cost_known": pool["cost_known"],
            "latency_ms": {
                "p50": _nearest_rank(pool["latencies"], 50),
                "p95": _nearest_rank(pool["latencies"], 95),
            },
            "held_out": {
                "first_answers_refused": None
                if pool["asked"] == 0
                else decimal_text(Fraction(pool["first_refused"], pool["asked"])),
                **{
                    name: None
                    if not measures
                    else decimal_text(sum((m[name] for m in measures), Fraction(0)) / len(measures))
                    for name in society_score.STATE_MEASURES
                },
            },
        }
    claim = definition["claim"]
    differences: list[dict[str, Any]] = []
    control_bound = None
    verdict: dict[str, Any] = {"code": "not_judged", "higher": None, "reason": None}
    if not complete:
        verdict = {"code": "incomplete", "higher": None, "reason": None}
    elif definition["phase"] == "development":
        verdict["reason"] = "development_seeds"
    elif definition["scoring"] != scoring_binding(found_catalogs):
        verdict["reason"] = "scored_under_other_code"
    if claim is not None and complete:
        family = [tuple(pair) for pair in claim["family"]]
        control = claim["control"]
        judged_arms = sorted({arm for pair in family for arm in pair})
        shared = [
            seed
            for seed in definition["seeds"]
            if all(scores[arm].get(seed) is not None for arm in judged_arms)
        ]
        control_shared = (
            []
            if control is None
            else [
                seed
                for seed in definition["seeds"]
                if all(scores[arm].get(seed) is not None for arm in control)
            ]
        )
        if len(shared) >= 2 and control is not None and len(control_shared) >= 2:
            found = judge(
                scores,
                primary=tuple(claim["primary"]),
                family=family,
                control=tuple(control),
                key=key,
                protocol=protocol,
            )
            rejected = set(found.rejected)
            differences = [_difference_document(d, rejected) for d in found.differences]
            control_bound = decimal_text(found.control_bound)
            if verdict["code"] == "not_judged" and verdict["reason"] is None:
                verdict = {"code": found.code, "higher": found.higher, "reason": None}
        elif len(shared) >= 2:
            # Registered differences with no control, or too few seeds its two arms scored,
            # to bound them: shown, and never judged.
            differing, rejected = family_differences(
                scores, family=family, key=key, protocol=protocol
            )
            differences = [_difference_document(differing[pair], rejected) for pair in family]
            if verdict["code"] == "not_judged" and verdict["reason"] is None:
                verdict["reason"] = "too_few_seeds_scored"
        elif verdict["code"] == "not_judged" and verdict["reason"] is None:
            verdict["reason"] = "too_few_seeds_scored"
    return {
        "profile": RESULT_PROFILE,
        "comparison_id": str(row["comparison_id"]),
        "created_at": row["created_at"].isoformat(),
        "phase": definition["phase"],
        "window_ticks": definition["window_ticks"],
        "population": definition["population"],
        "preregistration": definition["preregistration"],
        "arms": [_arm_document(arm, arms[arm], model_name) for arm in order],
        "primary": None if claim is None else list(claim["primary"]),
        "control": None if claim is None or claim["control"] is None else list(claim["control"]),
        "seeds": seeds_out,
        "summaries": summaries,
        "differences": differences,
        "control_bound": control_bound,
        "verdict": verdict,
    }


def _arm_document(
    key: str, arm: Mapping[str, Any], model_name: Callable[[str], str]
) -> dict[str, Any]:
    """An arm as the documents serve it. A model arm carries the name ``model_name`` gives its
    model, which the routes take from ``Manifest.model_name``: the rule the People panel and the
    Companion name a model by, so one model is never called two things."""
    decider = arm["decider"]
    return {
        "key": key,
        "role": arm["role"],
        "decider": {
            "kind": decider["kind"],
            **(
                {
                    "provider": decider["provider"],
                    "model_id": decider["model_id"],
                    "name": model_name(decider["model_id"]),
                }
                if decider["kind"] == "model"
                else {}
            ),
        },
        "description": arm["description"],
    }


def listing_document(
    rows: Sequence[Mapping[str, Any]],
    counts: Mapping[uuid.UUID, tuple[int, int]],
    *,
    model_name: Callable[[str], str],
) -> dict[str, Any]:
    """A version's comparisons, newest first, each with its arms and how far its runs got;
    ``model_name`` names each model an arm asks (:func:`_arm_document`)."""
    comparisons = []
    for row in rows:
        definition = row["document"]
        runs, completed = counts.get(row["comparison_id"], (0, 0))
        arms = definition["arms"]
        comparisons.append(
            {
                "comparison_id": str(row["comparison_id"]),
                "created_at": row["created_at"].isoformat(),
                "phase": definition["phase"],
                "arms": [_arm_document(arm, arms[arm], model_name) for arm in _arm_order(arms)],
                "seeds": len(definition["seeds"]),
                "runs": runs,
                "runs_completed": completed,
                "runs_expected": len(definition["seeds"]) * len(arms),
            }
        )
    return {"profile": LISTING_PROFILE, "comparisons": comparisons}


def replay_document(
    plan: RunPlan,
    definition: Mapping[str, Any],
    arm: str,
    digest: str,
    played: PlayedRun,
) -> dict[str, Any]:
    """One replayed run as the page draws it: the place from the frozen input, each person's
    minute by minute, and what each turn's receipt and minute did. No seed, no raw state."""
    document = plan.inputs[-1]
    routine = routine_of(document)
    positions = {node["node_id"]: node["position_mm"] for node in document["navigation"]["nodes"]}
    # What a person's action may be while they do something, in the routine's own words: the
    # affordance of an object's activity, or the key of one at no object.
    activities = [
        {"kind": affordance, "label": routine.default(affordance).label}
        for affordance in routine.affordances
    ] + [
        {"kind": activity.key, "label": activity.label}
        for activity in routine.activities.values()
        if activity.setting != "object"
    ]
    targets = []
    for target in document["targets"]:
        activity = routine.activities.get(str(target.get("activity")))
        label = (
            activity.label if activity is not None else routine.default(target["affordance"]).label
        )
        x, z = positions[target["node_id"]]
        targets.append(
            {
                "target_id": target["target_id"],
                "affordance": target["affordance"],
                "activity": target.get("activity") or target["affordance"],
                "label": label,
                "x": x,
                "z": z,
                "places": [
                    list(positions[node]) for node in target["place_node_ids"] if node in positions
                ],
            }
        )

    def person(value: Mapping[str, Any]) -> dict[str, Any]:
        path = value["motion_path_mm"] or [value["position_mm"]]
        goal = value["goal"]
        return {
            "id": value["id"],
            "x": value["position_mm"][0],
            "z": value["position_mm"][1],
            "path": [list(point) for point in path],
            "action": value["action"]["kind"],
            "status": value["action"]["status"],
            "reason": value["action"]["reason"],
            "goal": None
            if goal is None
            else {"kind": goal["kind"], "target_id": goal["target_id"], "reason": goal["reason"]},
            "need_milli": value["need_milli"],
        }

    minutes = [
        {"tick": state["tick"], "people": [person(p) for p in state["inhabitants"]]}
        for state in (played.start, *played.states)
    ]
    dispositions = {
        event.document["decision_seq"]: event.document
        for event in played.events
        if event.kind == society_score.DECISION_EVENT
    }
    decisions = []
    for receipt in played.receipts:
        applied = dispositions.get(receipt["decision_seq"])
        call = receipt["provider"] or {}
        decisions.append(
            {
                "decision_seq": receipt["decision_seq"],
                "subject_id": receipt["subject_id"],
                "tick": receipt["base_tick"] + 1,
                "status": receipt["status"],
                "reason": receipt["reason"],
                "disposition": None if applied is None else applied["disposition"],
                "disposition_reason": None if applied is None else applied["reason"],
                "chose": None if receipt["proposal"] is None else receipt["proposal"]["label"],
                "latency_ms": call.get("latency_ms"),
                "cost_usd": call.get("cost_usd"),
            }
        )
    events = [
        {
            "tick": event.tick,
            "subject_id": str(event.subject_id),
            "kind": event.kind,
            "reason": str(event.document.get("reason", "")),
            "summary": str(event.document.get("summary", "")),
        }
        for event in played.events
        if event.subject_id is not None
    ]
    return {
        "profile": REPLAY_PROFILE,
        "replay_verified": True,
        "run_id": str(plan.run_id),
        "arm": arm,
        "seed_digest": digest,
        "threshold": need_threshold(routine),
        "place": {
            "nodes": [
                {"id": node["node_id"], "x": node["position_mm"][0], "z": node["position_mm"][1]}
                for node in document["navigation"]["nodes"]
            ],
            "edges": [
                [edge["from_node_id"], edge["to_node_id"]]
                for edge in document["navigation"]["edges"]
            ],
            "targets": targets,
        },
        "activities": activities,
        "people": [
            {"id": value["id"], "name": value["display_name"]}
            for value in played.start["inhabitants"]
        ],
        "minutes": minutes,
        "decisions": decisions,
        "events": events,
    }


def verified_replay(
    plan: RunPlan,
    stored: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
    outcome: Mapping[str, Any],
) -> PlayedRun:
    """A completed run played again from what it stored, with no call, and held to its outcome:
    every minute's state, its events and its receipts. Anything else is a
    :class:`~exulanica.world.society_comparison.ReplayMismatch`."""
    if outcome["status"] != "completed":
        raise ReplayMismatch("a run that did not complete has no hour to replay")
    played = replay(plan, stored, minute_digests=outcome["minutes"]["state_sha256"])
    if played.events_sha256 != outcome["events_sha256"]:
        raise ReplayMismatch("the run's events are not the ones it recorded")
    if (len(played.receipts), played.receipts_sha256) != (
        outcome["receipts"]["count"],
        outcome["receipts"]["sha256"],
    ):
        raise ReplayMismatch("the run's receipts are not the ones it recorded")
    return played
