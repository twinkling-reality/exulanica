"""How a comparison's runs become its scores and its verdict: the one place either is decided.

The claim itself, paired differences, the bootstrap, Holm's procedure and the control's bound, is
:mod:`exulanica.world.society_comparison_claim`, and a run's terms are computed by the score of its
version (:mod:`exulanica.world.society_score` for the first, :mod:`exulanica.world.society_score_v2`
for the second). This module decides everything between them, from a comparison's definition and
its runs' outcomes and nothing else (:func:`read_comparison`):

*   **Which terms and which floor.** A run's terms are read under the score version its catalogs
    state, and scored against the floor that version's protocol names: the first's whole floor, the
    second's floor per scored person.
*   **Who scored.** A second-version run scored exactly the comparison's group, or everybody when
    the group is everybody; an outcome that scored anybody else is refused by name.
*   **Against which anchors.** Each run is scored against its seed's waiting run, the score's zero,
    and its routine run, the score's one, found by their roles; what each arm's model answered is
    read over that routine run's choice points.
*   **Whether it is complete, and judged.** A comparison with a run missing or failed is
    ``incomplete``. One run on development seeds, or read under scoring code other than the code it
    registered, is ``not_judged`` whatever its numbers, and so is one whose claim finds fewer than
    two seeds every arm it reads scored, too few for an interval, or no control to bound it. The
    family is read over the seeds every arm it names scored, the control over the seeds both of its
    arms scored.
*   **What the verdict says of reliability.** How people fared can be the same under two models
    that answered very differently, since the routine decides every turn a model leaves. So the
    verdict carries whether the primary pair's answered shares, each arm's answered turns over its
    turns pooled over its completed runs, differ by more than the control pair's do: the same
    model run twice bounds that variation too, with no constant of its own.

A comparison registered under the second binding holds this module's digest, so the rules that
turned its outcomes into its scores and its verdict are the rules it registered
(:func:`~exulanica.world.society_comparison_result.scoring_binding`). Nothing here reads a world,
a model or a database: outcomes in, scores and a verdict out.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Final

from exulanica.world import society_score, society_score_v2
from exulanica.world.society_catalogs import (
    COMPARISON_PROTOCOL_CATALOG,
    PERSON_SCORE_CATALOG,
    ComparisonCatalogs,
)
from exulanica.world.society_comparison_claim import (
    Difference,
    Protocol,
    family_differences,
    judge,
)

__all__ = [
    "ANCHOR_ROLES",
    "PROTOCOL_KEYS_BY_VERSION",
    "RELIABILITY_THREE",
    "ROUTINE_ROLE",
    "WAITING_ROLE",
    "Assembled",
    "ComparisonRefused",
    "Reading",
    "answered_share",
    "assemble",
    "protocol_for",
    "protocol_value",
    "protocol_values",
    "read_comparison",
    "score_version",
]

#: The anchor roles a run is scored against: waiting, the score's zero, and the routine, its one.
WAITING_ROLE: Final = "zero"
ROUTINE_ROLE: Final = "one"
ANCHOR_ROLES: Final = frozenset({WAITING_ROLE, ROUTINE_ROLE})
#: Answered, refused and left to the routine: what a model's turns came to, in that order.
RELIABILITY_THREE: Final = ("answered", "refused", "left_to_routine")
#: Every value of each comparison protocol version this code reads.
PROTOCOL_KEYS_BY_VERSION: Final = {
    1: frozenset(
        {
            "bootstrap_resamples",
            "family_alpha_per_mille",
            "interval_per_mille",
            "need_relief_floor",
            "population_maximum",
            "runs_at_once",
            "window_ticks",
        }
    ),
    2: frozenset(
        {
            "bootstrap_resamples",
            "family_alpha_per_mille",
            "interval_per_mille",
            "need_relief_floor_per_person",
            "population_maximum",
            "runs_at_once",
            "window_ticks",
        }
    ),
}
#: Why a comparison is not judged, as :data:`~exulanica.world.society_comparison_claim
#: .NOT_JUDGED_REASONS` names them.
_DEVELOPMENT: Final = "development_seeds"
_OTHER_CODE: Final = "scored_under_other_code"
_TOO_FEW: Final = "too_few_seeds_scored"


class ComparisonRefused(ValueError):
    """A comparison this society cannot be given, or this code cannot read, refused by name."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


# -- the protocol ---------------------------------------------------------------------------------


def _integer(key: str, value: object) -> int:
    if type(value) is not int:
        raise ComparisonRefused("protocol_keys", f"the protocol's {key} is not a whole number")
    return value


def protocol_values(catalogs: ComparisonCatalogs) -> dict[str, int]:
    """The protocol's values, refused by name unless they are exactly the ones read here for its
    version: a key added to the catalog and a key removed from it are both refused, as the decision
    policy's are."""
    version = int(catalogs.versions[COMPARISON_PROTOCOL_CATALOG])
    expected = PROTOCOL_KEYS_BY_VERSION.get(version)
    values = {key: _integer(key, entry["value"]) for key, entry in catalogs.protocol.items()}
    if expected is None or set(values) != expected:
        raise ComparisonRefused(
            "protocol_keys",
            f"the protocol v{version} states {sorted(values)}; read are {sorted(expected or ())}",
        )
    return values


def protocol_value(catalogs: ComparisonCatalogs, key: str) -> int:
    return protocol_values(catalogs)[key]


def protocol_for(catalogs: ComparisonCatalogs) -> Protocol:
    """The protocol a claim is made under, from the catalogs' values."""
    values = protocol_values(catalogs)
    return Protocol(
        resamples=values["bootstrap_resamples"],
        interval_per_mille=values["interval_per_mille"],
        family_alpha_per_mille=values["family_alpha_per_mille"],
    )


def score_version(catalogs: ComparisonCatalogs) -> int:
    """The version of the score the catalogs hold."""
    return int(catalogs.versions[PERSON_SCORE_CATALOG])


# -- the two scores, read the same way ----------------------------------------------------------


class _FirstScore:
    """The first score: need relief less the turns a model did not decide, over everybody."""

    version: Final = 1

    def __init__(self, catalogs: ComparisonCatalogs) -> None:
        self.score = society_score.person_score(catalogs.score)
        self.floor = protocol_value(catalogs, "need_relief_floor")

    @staticmethod
    def terms(document: Mapping[str, Any]) -> society_score.RunTerms:
        return society_score.RunTerms.from_document(document)

    def seed(self, run: Any, waiting: Any, routine: Any) -> tuple[str | None, Fraction | None]:
        scored = society_score.seed_score(
            run, waiting=waiting, routine=routine, score=self.score, floor=self.floor
        )
        return scored.excluded, scored.score

    @staticmethod
    def counts(run: Any, routine: Any) -> dict[str, Any]:
        """What a first-version run recorded of its turns: each by reason, never by class, and
        no choice point of the routine's, so the split and the rates are left null."""
        reasons = dict(run.not_applied_reasons)
        refused = reasons.get("answer_not_offered", 0)
        return {
            "turns": run.turns,
            "answered": run.applied,
            "refused": refused,
            "left_to_routine": run.turns - run.applied - refused,
            "not_answered": None,
            "not_applied": None,
            "reasons": reasons,
            "routine_choice_points": None,
        }

    @staticmethod
    def measures(run: Any) -> dict[str, Any]:
        return {**society_score.state_measures(run), "minutes_by_activity": None}


class _SecondScore:
    """The second score: need relief alone over the group, what each model answered apart."""

    version: Final = 2

    def __init__(self, catalogs: ComparisonCatalogs) -> None:
        self.score = society_score_v2.person_score(catalogs.score)
        self.floor = protocol_value(catalogs, "need_relief_floor_per_person")

    @staticmethod
    def terms(document: Mapping[str, Any]) -> society_score_v2.RunTerms:
        return society_score_v2.RunTerms.from_document(document)

    def seed(self, run: Any, waiting: Any, routine: Any) -> tuple[str | None, Fraction | None]:
        scored = society_score_v2.seed_score(
            run, waiting=waiting, routine=routine, score=self.score, floor_per_person=self.floor
        )
        return scored.excluded, scored.score

    @staticmethod
    def counts(run: Any, routine: Any) -> dict[str, Any]:
        found = society_score_v2.reliability(run, routine=routine)
        counts = found.counts
        reasons: Counter[str] = Counter()
        for _key, held in run.reasons:
            reasons.update(dict(held))
        return {
            "turns": found.turns,
            "answered": counts[society_score_v2.ANSWERED],
            "refused": counts[society_score_v2.REFUSED],
            "left_to_routine": sum(counts[key] for key in society_score_v2.LEFT_TO_ROUTINE),
            "not_answered": counts["not_answered"],
            "not_applied": counts["not_applied"],
            "reasons": dict(sorted(reasons.items())),
            "routine_choice_points": found.routine_choice_points,
        }

    @staticmethod
    def measures(run: Any) -> dict[str, Any]:
        return society_score_v2.state_measures(run)


_SCORES: Final = {reader.version: reader for reader in (_FirstScore, _SecondScore)}


def _score_reader(catalogs: ComparisonCatalogs) -> _FirstScore | _SecondScore:
    reader = _SCORES.get(score_version(catalogs))
    if reader is None:
        raise ComparisonRefused("score_version_unknown", "no reader for this score's version")
    return reader(catalogs)


def _scored_exactly_the_group(definition: Mapping[str, Any], terms: Any) -> None:
    """A second-version run scored the comparison's group and nobody else: the group's people, or,
    for a group of everybody, everybody the run held, nobody left outside it."""
    group = definition["group"]
    if group["source"]["kind"] == "everyone":
        right = not terms.others
    else:
        right = list(terms.people) == sorted(person["id"] for person in group["people"])
    if not right:
        raise ComparisonRefused(
            "scored_people_not_the_group", "a run scored other people than the comparison's group"
        )


def _pooled(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts summed over an arm's completed runs; the rates' denominator summed over them where
    every one of them had a routine run of its seed that recorded one."""
    split = all(run["not_answered"] is not None for run in runs)
    rated = [run for run in runs if run["routine_choice_points"]]
    reasons: Counter[str] = Counter()
    for run in runs:
        reasons.update(run["reasons"])
    return {
        "turns": sum(run["turns"] for run in runs),
        **{key: sum(run[key] for run in runs) for key in RELIABILITY_THREE},
        "not_answered": sum(run["not_answered"] for run in runs) if split and runs else None,
        "not_applied": sum(run["not_applied"] for run in runs) if split and runs else None,
        "reasons": dict(reasons),
        "routine_choice_points": sum(run["routine_choice_points"] for run in rated)
        if rated and len(rated) == len(runs)
        else None,
    }


def answered_share(answered: int, turns: int) -> Fraction | None:
    """An arm's answered turns over its turns, or None for an arm whose model was never asked."""
    return None if turns == 0 else Fraction(answered, turns)


# -- the verdict ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Assembled:
    """A comparison's registered differences, the control's bound and the server's verdict."""

    #: Each registered difference with whether Holm rejects it, or None where nothing was tested.
    differences: tuple[tuple[Difference, bool | None], ...]
    control_bound: Fraction | None
    code: str
    higher: str | None
    reason: str | None
    #: Whether the primary pair's answered shares differ by more than the control pair's; None
    #: where an arm of either pair asked nothing, or no control was registered.
    answered_shares_differ: bool | None


def _answered_differ(
    shares: Mapping[str, Fraction | None],
    primary: Sequence[str] | None,
    control: Sequence[str] | None,
) -> bool | None:
    if primary is None or control is None:
        return None
    first, second = shares.get(primary[0]), shares.get(primary[1])
    again, other = shares.get(control[0]), shares.get(control[1])
    if first is None or second is None or again is None or other is None:
        return None
    return abs(second - first) > abs(other - again)


def _shared(
    scores: Mapping[str, Mapping[str, Fraction | None]], seeds: Sequence[str], arms: Sequence[str]
) -> list[str]:
    return [seed for seed in seeds if all(scores[arm].get(seed) is not None for arm in arms)]


def assemble(
    *,
    phase: str,
    seeds: Sequence[str],
    claim: Mapping[str, Any] | None,
    key: str,
    scores: Mapping[str, Mapping[str, Fraction | None]],
    complete: bool,
    binding_held: bool,
    protocol: Protocol,
    shares: Mapping[str, Fraction | None],
) -> Assembled:
    """The verdict on a comparison from its scores.

    ``scores`` maps each arm to its exact score on each seed, None where the seed is excluded or
    the run did not complete; ``complete`` says every run completed; ``binding_held`` says the code
    and catalogs reading it are the ones it registered; ``key`` is the definition's digest, so its
    draws are its own; ``shares`` is each arm's answered share (:func:`answered_share`).
    """
    code, higher, reason = "not_judged", None, None
    if not complete:
        code = "incomplete"
    elif phase == "development":
        reason = _DEVELOPMENT
    elif not binding_held:
        reason = _OTHER_CODE
    differences: tuple[tuple[Difference, bool | None], ...] = ()
    bound = None
    primary = None if claim is None else tuple(claim["primary"])
    control = None if claim is None or claim["control"] is None else tuple(claim["control"])
    if claim is not None and complete:
        family = [tuple(pair) for pair in claim["family"]]
        judged = sorted({arm for pair in family for arm in pair})
        shared = _shared(scores, seeds, judged)
        control_shared = [] if control is None else _shared(scores, seeds, control)
        if len(shared) >= 2 and control is not None and len(control_shared) >= 2:
            found = judge(
                scores,
                primary=primary,  # type: ignore[arg-type]
                family=family,
                control=control,  # type: ignore[arg-type]
                key=key,
                protocol=protocol,
            )
            rejected = set(found.rejected)
            differences = tuple((d, (d.first, d.second) in rejected) for d in found.differences)
            bound = found.control_bound
            if code == "not_judged" and reason is None:
                code, higher = found.code, found.higher
        elif len(shared) >= 2:
            # Registered differences with no control, or too few seeds its two arms scored, to
            # bound them: shown, and never judged.
            differing, rejected = family_differences(
                scores, family=family, key=key, protocol=protocol
            )
            differences = tuple(
                (differing[pair], pair in rejected)  # type: ignore[index]
                for pair in family
            )
            if code == "not_judged" and reason is None:
                reason = _TOO_FEW
        elif code == "not_judged" and reason is None:
            reason = _TOO_FEW
    return Assembled(
        differences=differences,
        control_bound=bound,
        code=code,
        higher=higher,
        reason=reason,
        answered_shares_differ=_answered_differ(shares, primary, control),
    )


@dataclass(frozen=True, slots=True)
class Reading:
    """What a comparison's outcomes come to, under its score's version: every figure a verdict or a
    served document reads, and the verdict."""

    version: int
    complete: bool
    #: Each arm's exact score on each seed, None where it has none.
    scores: Mapping[str, Mapping[str, Fraction | None]]
    #: Why a seed carries no score, by name, or None.
    excluded: Mapping[str, str | None]
    #: What each arm's model answered on each seed, for a completed run, and pooled over them.
    counts: Mapping[str, Mapping[str, Mapping[str, Any] | None]]
    pooled: Mapping[str, Mapping[str, Any] | None]
    #: Each arm's answered share, pooled, or None for an arm that asked nobody.
    shares: Mapping[str, Fraction | None]
    #: The reported state measures of each arm's completed runs.
    measures: Mapping[str, Sequence[Mapping[str, Any]]]
    assembled: Assembled


def read_comparison(
    definition: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    catalogs: ComparisonCatalogs,
    *,
    binding_held: bool,
) -> Reading:
    """A comparison's scores, what each arm's model answered and its verdict, from its definition
    and its runs (each ``{arm, seed_digest, status, outcome}``) under ``catalogs``, the ones it
    recorded; ``binding_held`` says the code reading it is the code it registered."""
    reader = _score_reader(catalogs)
    arms = definition["arms"]
    seeds = list(definition["seeds"])
    by_seed: dict[str, dict[str, Mapping[str, Any]]] = {seed: {} for seed in seeds}
    for run in runs:
        by_seed.setdefault(run["seed_digest"], {})[run["arm"]] = run
    complete = all(
        by_seed[seed].get(arm, {}).get("status") == "completed" for seed in seeds for arm in arms
    )
    roles = {arms[key]["role"]: key for key in arms if arms[key]["role"] in ANCHOR_ROLES}
    waiting, routine = roles[WAITING_ROLE], roles[ROUTINE_ROLE]
    scores: dict[str, dict[str, Fraction | None]] = {arm: {} for arm in arms}
    counts: dict[str, dict[str, Mapping[str, Any] | None]] = {arm: {} for arm in arms}
    measures: dict[str, list[Mapping[str, Any]]] = {arm: [] for arm in arms}
    excluded: dict[str, str | None] = {}
    for seed in seeds:
        held = by_seed[seed]
        terms = {
            arm: reader.terms(run["outcome"]["terms"])
            for arm, run in held.items()
            if run.get("status") == "completed"
        }
        if reader.version == _SecondScore.version:
            for found in terms.values():
                _scored_exactly_the_group(definition, found)
        excluded[seed] = None
        for arm in arms:
            value = None
            if arm in terms and waiting in terms and routine in terms:
                excluded[seed], value = reader.seed(terms[arm], terms[waiting], terms[routine])
            scores[arm][seed] = value
            if arm not in terms:
                counts[arm][seed] = None
                continue
            # Rates are read over the routine run's choice points for an arm whose model decides
            # for the group; an anchor asks nobody for it and has none.
            asks = arms[arm]["decider"]["kind"] == "model"
            counts[arm][seed] = reader.counts(terms[arm], terms.get(routine) if asks else None)
            measures[arm].append(reader.measures(terms[arm]))
    pooled: dict[str, Mapping[str, Any] | None] = {}
    shares: dict[str, Fraction | None] = {}
    for arm in arms:
        completed = [found for found in counts[arm].values() if found is not None]
        pooled[arm] = _pooled(completed) if completed else None
        shares[arm] = (
            None
            if pooled[arm] is None
            else answered_share(pooled[arm]["answered"], pooled[arm]["turns"])  # type: ignore[index]
        )
    assembled = assemble(
        phase=definition["phase"],
        seeds=seeds,
        claim=definition["claim"],
        key=definition["document_sha256"],
        scores=scores,
        complete=complete,
        binding_held=binding_held,
        protocol=protocol_for(catalogs),
        shares=shares,
    )
    return Reading(
        version=reader.version,
        complete=complete,
        scores=scores,
        excluded=excluded,
        counts=counts,
        pooled=pooled,
        shares=shares,
        measures=measures,
        assembled=assembled,
    )
