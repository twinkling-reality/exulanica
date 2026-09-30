"""What a comparison's records say, as the routes serve them: pure, with no database.

A comparison's definition, checked before it is stored (:func:`check_definition_body`); a run's
outcome, built from what the run did (:func:`run_outcome`); a version's comparisons
(:func:`listing_document`); one comparison's scores per seed and per arm, what each arm's model
answered beside them, its registered differences and the server's verdict, read from its
definition and its runs' outcomes alone (:func:`comparison_result`); and one run replayed with no
call, as the page draws it (:func:`replay_document`). No projection here returns a run's seed or a
raw state: a reader names seeds by digest.

A comparison is read under the catalogs and the binding it recorded, never under whatever is
newest. The first version (``exulanica.society-comparison/v1``) scores need relief less the turns
a model did not decide, over everybody; the second (``v2``) scores need relief alone over the
comparison's group, everybody else keeping the decider the comparison froze for them, and reports
what each model answered apart (:mod:`exulanica.world.society_score_v2`). Both are served in the
same documents, a first-version comparison with what it did not record left null.

The verdict's words are the server's: a comparison is judged only when its seeds are held out, it
registered a claim with a control and a pre-registration, every run completed, and the code that
scores and judges it is the code it registered (:func:`binding_holds`). The claim is
:mod:`exulanica.world.society_comparison_claim` and the verdict's assembly
:mod:`exulanica.world.society_comparison_verdict`.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from exulanica.grammar.errors import CatalogError
from exulanica.models.manifest import AnsweringMechanism
from exulanica.world import (
    society_comparison_claim,
    society_comparison_verdict,
    society_score,
    society_score_v2,
    society_score_v3,
)
from exulanica.world.decision_roles import DecisionRole, RoleRefused, decision_roles
from exulanica.world.society_catalogs import (
    PERSON_SCORE_CATALOG,
    SEED_PHASES,
    ComparisonCatalogs,
    load_comparison_catalogs,
)
from exulanica.world.society_comparison import (
    DECIDER_KINDS,
    OTHER_DECIDER_KINDS,
    PlayedRun,
    ReplayMismatch,
    RunPlan,
    replay,
)
from exulanica.world.society_comparison_claim import Resamples
from exulanica.world.society_comparison_verdict import (
    RELIABILITY_THREE,
    ROUTINE_ROLE,
    WAITING_ROLE,
    ComparisonRefused,
    protocol_for,
    protocol_value,
    protocol_values,
    read_comparison,
    score_version,
)
from exulanica.world.society_decisions import PERSON_PROVIDER_CONFIG
from exulanica.world.society_planner import routine_of

__all__ = [
    "ANSWERING_SOURCES",
    "ARM_ROLES",
    "BINDING_PROFILE",
    "BINDING_PROFILES",
    "DECIMAL_PLACES",
    "DEFINITION_PROFILES",
    "FAILURE_PROFILE",
    "GROUP_SOURCES",
    "LISTING_PROFILE",
    "MINUTES_PER_HOUR",
    "REPLAY_PROFILE",
    "RESULT_PROFILE",
    "RUN_PROFILE",
    "RUN_PROFILES",
    "ComparisonRefused",
    "binding_holds",
    "check_definition_body",
    "comparison_result",
    "decimal_text",
    "definition_role",
    "definition_version",
    "listing_document",
    "others_asked",
    "protocol_value",
    "protocol_values",
    "replay_document",
    "run_outcome",
    "scoring_binding",
    "verified_replay",
]

#: A definition's profile by version: the first scores everybody, the second a group.
DEFINITION_PROFILES: Final = {
    1: "exulanica.society-comparison/v1",
    2: "exulanica.society-comparison/v2",
}
#: A completed run's outcome by the definition version it belongs to, and a failed one's.
RUN_PROFILES: Final = {
    1: "exulanica.society-comparison-run/v1",
    2: "exulanica.society-comparison-run/v2",
}
RUN_PROFILE: Final = RUN_PROFILES[2]
FAILURE_PROFILE: Final = "exulanica.society-comparison-failure/v1"
LISTING_PROFILE: Final = "exulanica.society-comparisons/v2"
RESULT_PROFILE: Final = "exulanica.society-comparison-result/v2"
REPLAY_PROFILE: Final = "exulanica.society-comparison-run-replay/v2"
#: The binding a comparison registers by the version of the score it is scored under, naming every
#: module it is scored and judged by. The first version's binding has no profile: it names its
#: scorer and claim by digest alone. The third also names the third score's module.
BINDING_PROFILES: Final = {
    2: "exulanica.society-comparison-binding/v2",
    3: "exulanica.society-comparison-binding/v3",
}
BINDING_PROFILE: Final = BINDING_PROFILES[3]
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
#: Where a comparison's group came from: everybody in the world, people named by the command, or
#: the people one of the world owner's choices named, by its sequence and digest.
#: The page has words for exactly these (``GROUP_SOURCE_WORDS`` in
#: web/packages/app/src/ui/society-comparison.ts, held to this tuple by a parity test).
GROUP_SOURCES: Final = (
    "everyone",
    "named",
    "owner_choice",
)
#: The decider each anchor role runs with: the routine for the score's one, waiting for its zero.
_ANCHORS: Final = {ROUTINE_ROLE: "routine", WAITING_ROLE: "wait"}
#: The definition version a comparison is defined under.
_DEFINED_VERSION: Final = 2
#: The score versions a definition of that version is scored under: both group the people they
#: score and report what each model answered apart, the second weighing need relief alone and the
#: third need relief and variety.
_DEFINED_SCORES: Final = (2, society_score_v3.CATALOG_VERSION)
#: Places a decimal the server writes carries. A score is exact until it is written; four places
#: tell apart seeds whose relief differs by a ten-thousandth of what the routine spares, which is
#: finer than any difference a comparison of eight seeds can claim.
DECIMAL_PLACES: Final = 4
_QUANTUM: Final = Decimal(1).scaleb(-DECIMAL_PLACES)
#: A unit: what a run's cost is stated per, whatever window the protocol sets.
MINUTES_PER_HOUR: Final = 60
#: What each binding version holds by digest, by the name its record gives each: the first names
#: the scorer and the claim; the second every module a second-version score and verdict is read by.
_BOUND_MODULES: Final[dict[int, dict[str, ModuleType]]] = {
    1: {"scorer_sha256": society_score, "claim_sha256": society_comparison_claim},
    2: {
        module.__name__: module
        for module in (
            society_score,
            society_score_v2,
            society_comparison_claim,
            society_comparison_verdict,
        )
    },
    3: {
        module.__name__: module
        for module in (
            society_score,
            society_score_v2,
            society_score_v3,
            society_comparison_claim,
            society_comparison_verdict,
        )
    },
}


def _module_sha256(module: ModuleType) -> str:
    return hashlib.sha256(Path(str(module.__file__)).read_bytes()).hexdigest()


def scoring_binding(catalogs: ComparisonCatalogs | None = None) -> dict[str, Any]:
    """What a comparison under ``catalogs`` is scored and judged under: the three catalogs and the
    modules that read them, by digest, in the form of the score version the catalogs hold. A
    comparison read under any other is not judged."""
    found = load_comparison_catalogs() if catalogs is None else catalogs
    version = score_version(found)
    if version not in _BOUND_MODULES:
        raise ComparisonRefused("score_version_unknown", f"no binding for score v{version}")
    recorded = {"versions": dict(sorted(found.versions.items())), "sha256": found.sha256}
    modules = {name: _module_sha256(module) for name, module in _BOUND_MODULES[version].items()}
    if version == 1:
        return {"catalogs": recorded, **modules}
    return {"profile": BINDING_PROFILES[version], "catalogs": recorded, "modules": modules}


def _binding_version(recorded: Mapping[str, Any]) -> int:
    for version, profile in BINDING_PROFILES.items():
        if recorded.get("profile") == profile and set(recorded) == {
            "profile",
            "catalogs",
            "modules",
        }:
            return version
    if "profile" not in recorded and set(recorded) == {"catalogs", *_BOUND_MODULES[1]}:
        return 1
    raise ComparisonRefused("binding_unknown", "a comparison names a binding this code cannot read")


def _recorded_catalogs(recorded: Mapping[str, Any]) -> ComparisonCatalogs:
    """The catalogs a comparison's binding names, read at the versions it recorded."""
    try:
        return load_comparison_catalogs(versions=recorded["catalogs"]["versions"])
    except CatalogError as exc:
        raise ComparisonRefused("catalogs_unavailable", str(exc)) from exc


def binding_holds(recorded: Mapping[str, Any], catalogs: ComparisonCatalogs | None = None) -> bool:
    """Whether a comparison is read now under what it registered: the catalogs at the versions it
    recorded, and every module its binding names, byte for byte. ``catalogs`` stands in for the
    committed ones where a caller reads under a copy of its own."""
    version = _binding_version(recorded)
    found = _recorded_catalogs(recorded) if catalogs is None else catalogs
    return score_version(found) == version and scoring_binding(found) == dict(recorded)


def definition_version(definition: Mapping[str, Any]) -> int:
    """A stored definition's version, from its profile; any other profile is refused by name."""
    for version, profile in DEFINITION_PROFILES.items():
        if definition.get("profile") == profile:
            return version
    raise ComparisonRefused("definition_unknown", f"no comparison {definition.get('profile')!r}")


def definition_role(definition: Mapping[str, Any]) -> DecisionRole:
    """The decision role a comparison asks: the registered role whose contract is the one its
    definition recorded (:meth:`~exulanica.world.decision_roles.RoleRegistry.for_contract`). A
    definition names its role by that contract, catalogs and digest, so no second field states it;
    one no registered role holds is refused by name."""
    try:
        return decision_roles().for_contract(definition["contract"])
    except RoleRefused as exc:
        raise ComparisonRefused(exc.code, exc.detail) from exc


# -- definitions --------------------------------------------------------------------------------


#: Whose order a model is asked in: its own, measured and named by its manifest entry, or the
#: contract's.
ANSWERING_SOURCES: Final = (
    "model",
    "contract",
)
_ANSWERING_KEYS: Final = frozenset({"order", "mechanism", "source", "record"})
_MECHANISMS: Final = frozenset(mechanism.value for mechanism in AnsweringMechanism)


def _check_config(key: str, decider: Mapping[str, Any], config: Any) -> None:
    kind = decider["kind"]
    if (kind == "model") != (config is not None):
        raise ComparisonRefused(
            "arm_provider", f"exactly a model decider records its asking: {key}"
        )
    if config is not None and (
        set(config) != PERSON_PROVIDER_CONFIG
        or (config["provider"], config["model_id"]) != (decider["provider"], decider["model_id"])
    ):
        raise ComparisonRefused("arm_provider", f"{key} records the model it asks")


def _check_answering(key: str, config: Any, answering: Any) -> None:
    """Exactly a model decider records its answering: the mechanisms it is asked by in order,
    each once, the first the one its requests record, whose order that is, and the record that
    measured a model's own order (:meth:`~exulanica.world.society_decision_contract.
    DecisionContract.answering`)."""
    if (config is not None) != (answering is not None):
        raise ComparisonRefused(
            "arm_answering", f"exactly a model decider records its answering: {key}"
        )
    if answering is None:
        return
    order = answering.get("order") if isinstance(answering, Mapping) else None
    if (
        not isinstance(order, list)
        or set(answering) != _ANSWERING_KEYS
        or not order
        or len(set(order)) != len(order)
        or not set(order) <= _MECHANISMS
        or answering["mechanism"] != order[0]
        or answering["mechanism"] != config["mechanism"]
        or answering["source"] not in ANSWERING_SOURCES
        or (answering["source"] == "model") != isinstance(answering["record"], str)
    ):
        raise ComparisonRefused("arm_answering", f"{key} records the order its model is asked in")


def _check_group(body: Mapping[str, Any]) -> None:
    group, others = body["group"], body["others"]
    source = group["source"]
    kind = source.get("kind")
    people = group["people"]
    if kind not in GROUP_SOURCES:
        raise ComparisonRefused("group_source", f"no group source {kind!r}")
    if (kind == "everyone") != (people is None):
        raise ComparisonRefused("group_people", "exactly a group of everyone names nobody")
    if people is not None and (not people or sorted(set(people)) != list(people)):
        raise ComparisonRefused("group_people", "a group names each person once, in order")
    if kind == "owner_choice" and set(source) != {"kind", "choice_seq", "document_sha256"}:
        raise ComparisonRefused("group_source", "an owner's choice is named by sequence and digest")
    if kind != "owner_choice" and set(source) != {"kind"}:
        raise ComparisonRefused("group_source", f"a {kind} group names nothing else")
    ids = [other["id"] for other in others]
    if ids != sorted(set(ids)) or (people is not None and set(ids) & set(people)):
        raise ComparisonRefused("others", "everybody outside the group is named once, in order")
    if people is None and others:
        raise ComparisonRefused("others", "a group of everyone leaves nobody outside it")
    for other in others:
        if set(other) != {"id", "decider", "provider_config", "choice", "answering"}:
            raise ComparisonRefused("others", "a person outside the group states their decider")
        if other["decider"]["kind"] not in OTHER_DECIDER_KINDS:
            raise ComparisonRefused("others", f"{other['id']} is decided by their owner's choice")
        _check_config(other["id"], other["decider"], other["provider_config"])
        _check_answering(other["id"], other["provider_config"], other["answering"])
        choice = other["choice"]
        if choice is not None and set(choice) != {"choice_seq", "document_sha256"}:
            raise ComparisonRefused("others", "an owner's choice is named by sequence and digest")
        if (other["decider"]["kind"] == "model") and choice is None:
            raise ComparisonRefused("others", "a model outside the group is an owner's choice")


def check_definition_body(body: Mapping[str, Any], catalogs: ComparisonCatalogs) -> None:
    """Refuse by name a definition this code cannot run or judge as it states itself.

    What the society holds, the people of the group and the owner's choices for everybody else, is
    checked against the society where the definition is recorded
    (:meth:`~exulanica.world.society_comparison_repository.SocietyComparisonRepository.define`).
    """
    phase = body["phase"]
    if phase not in SEED_PHASES:
        raise ComparisonRefused("phase_unknown", f"no phase {phase!r}")
    if score_version(catalogs) not in _DEFINED_SCORES:
        raise ComparisonRefused(
            "catalogs_not_the_definition_version",
            f"a comparison is defined under a score of {list(_DEFINED_SCORES)}, "
            f"these catalogs hold v{score_version(catalogs)}",
        )
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
    _check_group(body)
    if phase == "held_out" and any(other["decider"]["kind"] == "model" for other in body["others"]):
        # A model outside the group is asked in every arm, the anchors included, so the score's
        # one and the rates' denominator would move with its answers: a judged claim keeps
        # everybody outside the group on their routine, where both hold exactly.
        raise ComparisonRefused(
            "held_out_others_not_routine",
            "a held-out comparison keeps everybody outside its group on their routine",
        )
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
        _check_config(f"arm {key}", arm["decider"], arm["provider_config"])
        _check_answering(f"arm {key}", arm["provider_config"], arm.get("answering"))
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


# -- the two scores, read the same way ----------------------------------------------------------


def _reliability_document(counts: Mapping[str, Any]) -> dict[str, Any]:
    """What a model answered, as a document serves it beside a score: counts, shares of the run's
    own turns, and rates per choice point of the routine's run where one was recorded."""
    turns = counts["turns"]
    points = counts["routine_choice_points"]
    return {
        **{key: counts[key] for key in ("turns", *RELIABILITY_THREE)},
        "not_answered": counts["not_answered"],
        "not_applied": counts["not_applied"],
        "shares": None
        if turns == 0
        else {key: decimal_text(Fraction(counts[key], turns)) for key in RELIABILITY_THREE},
        "per_routine_choice": None
        if not points
        else {key: decimal_text(Fraction(counts[key], points)) for key in RELIABILITY_THREE},
        "routine_choice_points": points,
        "reasons": dict(sorted(counts["reasons"].items())),
        "reasons_by_class": counts.get("reasons_by_class"),
    }


# -- outcomes -----------------------------------------------------------------------------------


def run_outcome(
    plan: RunPlan,
    definition: Mapping[str, Any],
    arm: str,
    seed_digest_text: str,
    played: PlayedRun,
    calls: Mapping[str, Any] | None,
    catalogs: ComparisonCatalogs,
    *,
    others_calls: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A completed run's outcome: its minutes' digests, its events and receipts, the score's
    integer terms over the people it scores and what its asking took, in the form of its
    definition's version."""
    version = definition_version(definition)
    threshold = society_score.need_threshold(routine_of(plan.inputs[-1]))
    everybody = [person["id"] for person in played.start["inhabitants"]]
    if version == 1:
        terms = society_score.run_terms(
            played.states,
            played.events,
            people=everybody,
            threshold=threshold,
            score=society_score.person_score(catalogs.score),
        ).document()
        extra: dict[str, Any] = {}
    else:
        people = everybody if plan.group is None else sorted(plan.group)
        terms = society_score_v2.run_terms(
            played.states,
            played.events,
            people=people,
            threshold=threshold,
            choice_points=sum(played.choice_points[subject] for subject in people),
            score=_turn_classes(catalogs),
        ).document()
        extra = {"others_calls": None if others_calls is None else dict(others_calls)}
    return {
        "profile": RUN_PROFILES[version],
        "status": "completed",
        "definition_sha256": definition["document_sha256"],
        "arm": arm,
        "seed_digest": seed_digest_text,
        "minutes": {"count": len(played.states), "state_sha256": played.minute_digests},
        "events_sha256": played.events_sha256,
        "receipts": {"count": len(played.receipts), "sha256": played.receipts_sha256},
        "terms": terms,
        "calls": None if calls is None else dict(calls),
        **extra,
    }


def _turn_classes(catalogs: ComparisonCatalogs) -> society_score_v2.PersonScore:
    """The classes a group's turns are counted in, as the score the catalogs hold declares them:
    the second's own, or the third's, which reports the second's unchanged."""
    if score_version(catalogs) == society_score_v3.CATALOG_VERSION:
        return society_score_v3.person_score(catalogs.score).reliability
    return society_score_v2.person_score(catalogs.score)


# -- documents ----------------------------------------------------------------------------------


def _seed_names(catalogs: ComparisonCatalogs) -> dict[str, str]:
    return {str(entry["seed_digest"]): key for key, entry in catalogs.seeds.items()}


def _arm_order(arms: Mapping[str, Any]) -> list[str]:
    return sorted(arms, key=lambda key: (ARM_ROLES.index(arms[key]["role"]), key))


def _decider_document(
    decider: Mapping[str, Any], model_name: Callable[[str], str]
) -> dict[str, Any]:
    """A decider as the documents serve it. A model carries the name ``model_name`` gives it,
    which the routes take from ``Manifest.model_name``: the rule the People panel and the Companion
    name a model by, so one model is never called two things."""
    if decider["kind"] != "model":
        return {"kind": decider["kind"]}
    return {
        "kind": "model",
        "provider": decider["provider"],
        "model_id": decider["model_id"],
        "name": model_name(decider["model_id"]),
    }


def _arm_document(
    key: str, arm: Mapping[str, Any], model_name: Callable[[str], str]
) -> dict[str, Any]:
    return {
        "key": key,
        "role": arm["role"],
        "decider": _decider_document(arm["decider"], model_name),
        "answering": _answering_document(arm.get("answering")),
        "description": arm["description"],
    }


def _answering_document(answering: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """How a model was asked, as its definition recorded it; null for an anchor, for a routine,
    and for a definition recorded before a model's answering was."""
    return None if answering is None else dict(answering)


def _group_document(definition: Mapping[str, Any]) -> dict[str, Any]:
    """Who a comparison scores: a first-version comparison scored everybody and named nobody."""
    if definition_version(definition) == 1:
        return {"people": None, "source": {"kind": "everyone"}, "size": definition["population"]}
    group = definition["group"]
    people = group["people"]
    return {
        "people": [dict(person) for person in people],
        "source": dict(group["source"]),
        "size": len(people),
    }


def _others_document(
    definition: Mapping[str, Any], model_name: Callable[[str], str]
) -> list[dict[str, Any]]:
    """Everybody outside the group and what decides for them in every arm."""
    if definition_version(definition) == 1:
        return []
    return [
        {
            "id": other["id"],
            "name": other["name"],
            "decider": _decider_document(other["decider"], model_name),
            "answering": _answering_document(other.get("answering")),
            "choice": other["choice"],
        }
        for other in definition["others"]
    ]


def _calls_document(calls: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if calls is None:
        return None
    return {
        "asked": calls["asked"],
        "first_answers_refused": calls["first_answers_refused"],
        "cost_usd": calls["cost_usd"],
        "cost_known": calls["cost_known"],
        "latency_ms": {
            "p50": _nearest_rank(calls["latencies_ms"], 50),
            "p95": _nearest_rank(calls["latencies_ms"], 95),
        },
    }


def _difference_document(found: Any, rejected: bool | None) -> dict[str, Any]:
    return {
        "first": found.first,
        "second": found.second,
        "mean": decimal_text(found.mean),
        "low": decimal_text(found.low),
        "high": decimal_text(found.high),
        "rejected": rejected,
    }


def _measure_text(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {key: decimal_text(item) for key, item in value.items()}
    return decimal_text(value)


def _mean_measures(measures: Sequence[Mapping[str, Any]], names: Sequence[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in names:
        values = [m[name] for m in measures]
        if not values or any(value is None for value in values):
            out[name] = None
        elif isinstance(values[0], Mapping):
            keys = sorted({key for value in values for key in value})
            out[name] = {
                key: decimal_text(
                    sum((value.get(key, Fraction(0)) for value in values), Fraction(0))
                    / len(values)
                )
                for key in keys
            }
        else:
            out[name] = decimal_text(sum(values, Fraction(0)) / len(values))
    return out


#: The measures read from states a document reports, by the second score's names; a first-version
#: run records no minutes by activity, which is served as null.
_MEASURES: Final = society_score_v2.STATE_MEASURES


def others_asked(definition: Mapping[str, Any]) -> bool:
    """Whether anybody outside a comparison's group is decided by a model their world's owner chose,
    asked in every arm, the anchors included. Derived from the deciders the definition records, so
    it is never stated twice. A held-out comparison is refused with any such person
    (:func:`check_definition_body`), so where this holds the comparison is a development one, and
    its score's one and its rates' denominator move with those answers too."""
    return definition_version(definition) == _DEFINED_VERSION and any(
        other["decider"]["kind"] == "model" for other in definition["others"]
    )


def comparison_result(
    row: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    catalogs: ComparisonCatalogs | None = None,
    *,
    model_name: Callable[[str], str],
    start: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A comparison's scores, per seed and per arm, what each arm's model answered beside them,
    its registered differences and the server's verdict, read from its definition and its runs'
    outcomes alone, under the catalogs its binding recorded, by the bound reading of
    :func:`~exulanica.world.society_comparison_verdict.read_comparison`; this formats what it
    found. ``catalogs`` stands in for the recorded ones where a caller reads under a copy of its
    own; ``model_name`` names each model a decider asks; ``start`` is its start where it was
    started from the application."""
    definition = row["document"]
    recorded = definition["scoring"]
    found_catalogs = _recorded_catalogs(recorded) if catalogs is None else catalogs
    reading = read_comparison(
        definition, runs, found_catalogs, binding_held=binding_holds(recorded, catalogs)
    )
    protocol = protocol_for(found_catalogs)
    arms = definition["arms"]
    order = _arm_order(arms)
    names = _seed_names(found_catalogs)
    by_seed: dict[str, dict[str, Mapping[str, Any]]] = {seed: {} for seed in definition["seeds"]}
    for run in runs:
        by_seed.setdefault(run["seed_digest"], {})[run["arm"]] = run
    calls_of: dict[str, list[Mapping[str, Any]]] = {arm: [] for arm in arms}
    others_of: dict[str, list[Mapping[str, Any]]] = {arm: [] for arm in arms}
    seeds_out = []
    for seed in definition["seeds"]:
        held = by_seed[seed]
        runs_out: dict[str, Any] = {}
        for arm in order:
            found = held.get(arm)
            status = (
                "incomplete" if found is None or found.get("status") is None else found["status"]
            )
            outcome = found["outcome"] if found is not None and status == "completed" else None
            calls = None if outcome is None else outcome["calls"]
            others_calls = None if outcome is None else outcome.get("others_calls")
            if calls is not None:
                calls_of[arm].append(calls)
            if others_calls is not None:
                others_of[arm].append(others_calls)
            value = reading.scores[arm][seed]
            counts = reading.counts[arm][seed]
            runs_out[arm] = {
                "run_id": None if found is None else str(found["run_id"]),
                "status": status,
                "failure": found["outcome"]["code"]
                if found is not None and status == "failed"
                else None,
                "score": None if value is None else decimal_text(value),
                "parts": _parts_document(reading.parts.get(arm, {}).get(seed)),
                "terms": None if outcome is None else _terms_document(outcome["terms"]),
                "reliability": None if counts is None else _reliability_document(counts),
                "calls": _calls_document(calls),
                "others_calls": _calls_document(others_calls),
            }
        seeds_out.append(
            {
                "seed_digest": seed,
                "name": names.get(seed),
                "excluded": reading.excluded[seed],
                "runs": runs_out,
            }
        )
    key = definition["document_sha256"]
    summaries = {}
    for arm in order:
        values = [value for value in reading.scores[arm].values() if value is not None]
        interval = None
        mean = None
        if values:
            mean = sum(values, Fraction(0)) / len(values)
        if len(values) >= 2:
            _mean, low, high, _p = Resamples(f"{key}:arm:{arm}", len(values), protocol).summarise(
                values
            )
            interval = {"low": decimal_text(low), "high": decimal_text(high)}
        counted = reading.pooled[arm]
        calls = calls_of[arm]
        summaries[arm] = {
            "mean_score": None if mean is None else decimal_text(mean),
            "interval": interval,
            "reliability": None if counted is None else _reliability_document(counted),
            "cost_usd_per_hour": None
            if arms[arm]["decider"]["kind"] != "model"
            else _hourly_cost(calls, definition),
            "cost_known": all(found["cost_known"] for found in calls),
            "others_cost_usd_per_hour": _hourly_cost(others_of[arm], definition),
            "others_cost_known": all(found["cost_known"] for found in others_of[arm]),
            "latency_ms": {
                "p50": _nearest_rank([ms for c in calls for ms in c["latencies_ms"]], 50),
                "p95": _nearest_rank([ms for c in calls for ms in c["latencies_ms"]], 95),
            },
            "held_out": {
                "first_answers_refused": _first_refused(calls),
                **_mean_measures(reading.measures[arm], _MEASURES),
            },
        }
    claim = definition["claim"]
    assembled = reading.assembled
    return {
        "profile": RESULT_PROFILE,
        "comparison_id": str(row["comparison_id"]),
        "created_at": row["created_at"].isoformat(),
        "phase": definition["phase"],
        "score_version": reading.version,
        "start": None if start is None else dict(start),
        "window_ticks": definition["window_ticks"],
        "population": definition["population"],
        "preregistration": definition["preregistration"],
        "group": _group_document(definition),
        "others": _others_document(definition, model_name),
        "others_asked": others_asked(definition),
        "arms": [_arm_document(arm, arms[arm], model_name) for arm in order],
        "primary": None if claim is None else list(claim["primary"]),
        "control": None if claim is None or claim["control"] is None else list(claim["control"]),
        "seeds": seeds_out,
        "summaries": summaries,
        "differences": [_difference_document(d, rejected) for d, rejected in assembled.differences],
        "control_bound": None
        if assembled.control_bound is None
        else decimal_text(assembled.control_bound),
        "verdict": {
            "code": assembled.code,
            "higher": assembled.higher,
            "reason": assembled.reason,
            "answered_shares_differ": assembled.answered_shares_differ,
        },
    }


def _parts_document(parts: Mapping[str, Fraction] | None) -> dict[str, str] | None:
    """Each weighed term of a score that weighs more than one, on one seed, as the score reads it:
    anchored, unclipped, before its weight."""
    return None if parts is None else {key: decimal_text(value) for key, value in parts.items()}


def _terms_document(terms: Mapping[str, Any]) -> dict[str, Any]:
    """A run's stored integer terms as a document serves them, with no person named: the need
    above the threshold summed, the different activity kinds each scored person did summed, the
    choice points, the turns by class and by the reason they were left, and the person-minutes by
    what they were. A score rounds; these do not, so two runs a rounded score shows equal can be
    told apart."""
    served = {
        key: terms[key]
        for key in ("ticks", "threshold", "urgency", "choice_points", "turns", "others_urgency")
        if key in terms
    }
    if "activities" in terms:
        served["variety"] = sum(int(count) for count in terms["activities"].values())
        served["people"] = len(terms["activities"])
    for key in ("classes", "reasons", "person_minutes", "minutes_by_activity"):
        if key in terms:
            served[key] = terms[key]
    return served


def _hourly_cost(calls: Sequence[Mapping[str, Any]], definition: Mapping[str, Any]) -> str | None:
    """What the asking of an arm's completed runs cost for the simulated hour, on average; None
    where none of them asked anybody."""
    if not calls:
        return None
    spent = sum((Fraction(Decimal(c["cost_usd"])) for c in calls), Fraction(0))
    return decimal_text(spent / len(calls) * MINUTES_PER_HOUR / definition["window_ticks"])


def _first_refused(calls: Sequence[Mapping[str, Any]]) -> str | None:
    asked = sum(c["asked"] for c in calls)
    if asked == 0:
        return None
    return decimal_text(Fraction(sum(c["first_answers_refused"] for c in calls), asked))


def listing_document(
    rows: Sequence[Mapping[str, Any]],
    counts: Mapping[uuid.UUID, tuple[int, int, int]],
    *,
    model_name: Callable[[str], str],
    starts: Mapping[uuid.UUID, Mapping[str, Any]],
) -> dict[str, Any]:
    """A version's comparisons, newest first, each with its arms, who it scores, how far its runs
    got and, for one started from the application, its start (``starts``, by comparison id: its
    bound, what it spent and where it stands); ``model_name`` names each model a decider asks."""
    comparisons = []
    for row in rows:
        definition = row["document"]
        runs, completed, finished = counts.get(row["comparison_id"], (0, 0, 0))
        arms = definition["arms"]
        group = _group_document(definition)
        comparisons.append(
            {
                "comparison_id": str(row["comparison_id"]),
                "created_at": row["created_at"].isoformat(),
                "phase": definition["phase"],
                # The score it is read under: the one its binding recorded, never inferred from
                # the definition's version, which two scores share.
                "score_version": int(
                    definition["scoring"]["catalogs"]["versions"][PERSON_SCORE_CATALOG]
                ),
                "group": {"source": group["source"], "size": group["size"]},
                "arms": [_arm_document(arm, arms[arm], model_name) for arm in _arm_order(arms)],
                "seeds": len(definition["seeds"]),
                "runs": runs,
                "runs_completed": completed,
                "runs_finished": finished,
                "runs_expected": len(definition["seeds"]) * len(arms),
                "start": None
                if (start := starts.get(row["comparison_id"])) is None
                else dict(start),
            }
        )
    return {"profile": LISTING_PROFILE, "comparisons": comparisons}


def replay_document(
    plan: RunPlan,
    definition: Mapping[str, Any],
    arm: str,
    digest: str,
    played: PlayedRun,
    *,
    model_name: Callable[[str], str],
) -> dict[str, Any]:
    """One replayed run as the page draws it: the place from the frozen input, each person's
    minute by minute, who decides for each of them in this run, and what each turn's receipt and
    minute did. No seed, no raw state."""
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
    deciders = {}
    for value in played.start["inhabitants"]:
        decider, _config = plan.decider_for(value["id"])
        deciders[value["id"]] = {
            "in_group": plan.group is None or value["id"] in plan.group,
            "decider": _decider_document(decider, model_name),
        }
    return {
        "profile": REPLAY_PROFILE,
        "replay_verified": True,
        "run_id": str(plan.run_id),
        "arm": arm,
        "seed_digest": digest,
        "threshold": society_score.need_threshold(routine),
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
            {"id": value["id"], "name": value["display_name"], **deciders[value["id"]]}
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
