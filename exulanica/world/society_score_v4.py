"""Living-town terms for the fourth person score, with the established anchored score math.

Urgency is the sum of every supported need above its own recorded routine threshold, across
person-minutes. Its raw units differ from the purposeful score's one-need urgency. The fourth
catalog keeps the third score's half need-relief and half performed-activity variety weights,
its same-seed routine and waiting anchors, and its reliability classes and exclusions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from exulanica.world import society_score_v2, society_score_v3
from exulanica.world.society_catalogs import RoutineModel
from exulanica.world.society_score import ScoreRefused

__all__ = ["CATALOG_VERSION", "run_terms", "validate_terms"]

CATALOG_VERSION: Final = 4
NEED_UNIT: Final = "sum_of_supported_need_thousandths_above_each_threshold_per_person_minute"


def _thresholds(state: Mapping[str, Any], routine: RoutineModel) -> dict[str, int]:
    if state.get("routine") != routine.binding():
        raise ScoreRefused("living_routine_changed", "a minute names another living routine")
    supported = state.get("population", {}).get("supported_needs")
    if (
        not isinstance(supported, list)
        or not supported
        or any(not isinstance(key, str) for key in supported)
        or supported != sorted(set(supported))
        or any(key not in routine.needs for key in supported)
    ):
        raise ScoreRefused(
            "living_needs_unsupported", "the living population names supported needs"
        )
    return {key: routine.needs[key].threshold for key in supported}


def run_terms(
    states: Sequence[Mapping[str, Any]],
    events: Iterable[Any],
    *,
    people: Iterable[str],
    choice_points: int,
    routine: RoutineModel,
    score: society_score_v2.PersonScore,
) -> dict[str, Any]:
    """Extract exact living terms; project only the fields shared term counting reads.

    A missing, extra or malformed need refuses the whole run. An action counts for variety only
    after it is performed, while active or completed; a selected goal and walking never count.
    The established v2 counter reads the projected urgency, action and motion path, and the
    decision_applied event dispositions unchanged.
    """
    if not states:
        raise ScoreRefused("no_minutes", "a run with no minutes has nothing to score")
    thresholds = _thresholds(states[0], routine)
    projected = []
    for state in states:
        if _thresholds(state, routine) != thresholds:
            raise ScoreRefused(
                "living_need_thresholds_changed", "a run changes its need thresholds"
            )
        inhabitants = []
        for person in state["inhabitants"]:
            needs = person.get("needs")
            if (
                not isinstance(needs, dict)
                or set(needs) != set(thresholds)
                or any(type(value) is not int or not 0 <= value <= 1000 for value in needs.values())
            ):
                raise ScoreRefused(
                    "living_needs_mismatch", "each person has exactly the supported needs"
                )
            urgency = sum(max(0, needs[key] - threshold) for key, threshold in thresholds.items())
            action = person["action"]
            performed = action["kind"] in routine.activities and action["status"] in (
                "active",
                "completed",
            )
            inhabitants.append(
                {
                    "id": person["id"],
                    "need_milli": urgency,
                    "motion_path_mm": person["motion_path_mm"],
                    "action": {
                        "kind": action["kind"] if performed else "idle",
                        "status": action["status"] if performed else "active",
                    },
                }
            )
        projected.append({"tick": state["tick"], "inhabitants": inhabitants})
    terms = society_score_v2.run_terms(
        projected,
        events,
        people=people,
        threshold=0,
        choice_points=choice_points,
        score=score,
    ).document()
    return {**terms, "need_thresholds": thresholds, "need_unit": NEED_UNIT}


def validate_terms(document: Mapping[str, Any]) -> society_score_v2.RunTerms:
    """A stored fourth-score term document with its need identity and units, or a refusal."""
    thresholds = document.get("need_thresholds")
    if (
        document.get("need_unit") != NEED_UNIT
        or document.get("threshold") != 0
        or not isinstance(thresholds, dict)
        or not thresholds
        or any(
            not isinstance(key, str) or type(value) is not int or not 0 <= value <= 1000
            for key, value in thresholds.items()
        )
    ):
        raise ScoreRefused("living_terms_binding", "the stored terms name their need thresholds")
    return society_score_v2.RunTerms.from_document(document)


def score(catalog: Mapping[str, Mapping[str, Any]]) -> society_score_v3.PersonScore:
    """The fourth catalog has the third's weights and reliability mapping exactly."""
    return society_score_v3.person_score(catalog)
