"""What a living town's day comparison records of each run: its sealed hours, and its day.

A comparison whose window is a day plays each run hour by hour
(:func:`~exulanica.world.society_comparison.play_hour`). At the end of each hour the host seals
it (:func:`hour_document`): the hour's minute digests, its events and receipts, the fifth score's
terms over the group for the hour (:func:`~exulanica.world.society_score_v5.hour_terms`), what the
hour's asking took, and, for every person, what they were doing each minute and where they were
headed, coded as the run's drawing classifies a minute (:func:`minute_record`). The state the hour
ended in is stored beside it, as the canonical bytes its last minute's digest is the SHA-256 of
(:func:`state_bytes`), so the next hour, a host that takes the run over, and a read of the next
hour start from it (:func:`state_from_bytes`). Once every hour is sealed, the run's one outcome is
its day (:func:`day_outcome`): the hours by digest, every receipt by digest, and the day's terms,
assembled from the hours' (:func:`~exulanica.world.society_score_v5.day_terms`).

Nothing here reads a database or asks a model: a plan, played minutes and sealed hours in,
documents out.
"""

from __future__ import annotations

import hashlib
import json
import string
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.models.usage import usd_string
from exulanica.world import society_score_v5
from exulanica.world.society import society_state_sha256
from exulanica.world.society_catalogs import DAY_SCORE_BY_FAMILY, ComparisonCatalogs
from exulanica.world.society_comparison import HOUR_TICKS, HourStart, PlayedRun, RunPlan
from exulanica.world.society_engines import society_engine
from exulanica.world.society_living import input_routine, living_places
from exulanica.world.society_planner import ordered_events_document

__all__ = [
    "ACTIVITY_CODES",
    "DAY_RUN_PROFILE",
    "HOUR_PROFILE",
    "WAITING",
    "WALKING",
    "combined_calls",
    "day_outcome",
    "hour_document",
    "minute_record",
    "state_bytes",
    "state_from_bytes",
    "vocabulary",
]

#: A sealed hour of a run, and a run's completed day.
HOUR_PROFILE: Final = "exulanica.society-comparison-hour/v1"
DAY_RUN_PROFILE: Final = "exulanica.society-comparison-run/v3"
#: How a minute is coded in a person's record of an hour: walking, waiting where they are, or one
#: of the run's activities by its place in the run's vocabulary (:func:`vocabulary`), as the
#: run's drawing classifies a minute.
WALKING: Final = "-"
WAITING: Final = "."
ACTIVITY_CODES: Final = string.digits + string.ascii_lowercase + string.ascii_uppercase
#: An action under way, as the drawing reads a minute.
_UNDER_WAY: Final = frozenset({"active", "completed"})


def vocabulary(plan: RunPlan) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """What a run's minute records name by position: the routine's activities, in the order its
    drawing lists them, each with its code, and the places of the run's frozen input, by
    destination id, each with its label."""
    source = plan.inputs[-1]
    routine = input_routine(source)
    activities = [
        {"code": ACTIVITY_CODES[index], "kind": activity.key, "label": activity.label}
        for index, activity in enumerate(routine.activities.values())
    ]
    if len(activities) > len(ACTIVITY_CODES):
        raise ValueError("a routine names more activities than a minute's code holds")
    [place] = living_places([source], routine)
    places = [
        {
            "destination_id": destination["destination_id"],
            "label": destination["label"]
            or (destination["use_class"] or "place").replace("_", " "),
        }
        for destination in sorted(
            place.document["destinations"], key=lambda found: found["destination_id"]
        )
    ]
    return activities, places


def minute_record(states: Sequence[Mapping[str, Any]], plan: RunPlan) -> dict[str, dict[str, Any]]:
    """For every person of an hour's ``states``, what they were doing each minute and where they
    were headed: ``doing``, one code a minute (:data:`WALKING`, :data:`WAITING` or an activity's
    code), and ``heading``, the minutes their goal's place changed at, each with that place's
    position in the run's vocabulary or None for no goal. A minute is classified as the run's
    drawing classifies it: walking while its path has more than one point, else doing the
    activity under way when the routine names it, else waiting."""
    activities, places = vocabulary(plan)
    code_of = {activity["kind"]: activity["code"] for activity in activities}
    place_of = {place["destination_id"]: index for index, place in enumerate(places)}
    record: dict[str, dict[str, Any]] = {}
    for offset, state in enumerate(states):
        for person in state["inhabitants"]:
            held = record.setdefault(person["id"], {"doing": [], "heading": []})
            action = person["action"]
            if len(person["motion_path_mm"]) > 1:
                code = WALKING
            elif action["status"] in _UNDER_WAY and action["kind"] in code_of:
                code = code_of[action["kind"]]
            else:
                code = WAITING
            held["doing"].append(code)
            goal = person["goal"]
            heading = None if goal is None else place_of.get(goal["destination_id"])
            if not held["heading"] or held["heading"][-1][1] != heading:
                held["heading"].append([offset, heading])
    return {
        subject: {"doing": "".join(held["doing"]), "heading": held["heading"]}
        for subject, held in sorted(record.items())
    }


def state_bytes(state: Mapping[str, Any]) -> bytes:
    """The canonical bytes of a state, whose SHA-256 is its digest (``society_state_sha256``)."""
    return canonical_json(dict(state))


def state_from_bytes(data: bytes, digest: str) -> dict[str, Any]:
    """The state stored as ``data``, held to the digest a run recorded for it: bytes that are not
    the state ``digest`` names are refused."""
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("stored state is not the one its minute's digest names")
    state = json.loads(data)
    if society_state_sha256(state) != digest:
        raise ValueError("stored state is not canonical")
    return state


def _sealed(document: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in document.items() if key != "document_sha256"}
    return {**body, "document_sha256": society_state_sha256(body)}


def _clock(state: Mapping[str, Any]) -> dict[str, int] | None:
    clock = state.get("clock")
    if clock is None:
        return None
    return {"day": int(clock["day"]), "minute_of_day": int(clock["minute_of_day"])}


def hour_document(
    plan: RunPlan,
    definition: Mapping[str, Any],
    arm: str,
    seed_digest_text: str,
    start: HourStart,
    played: PlayedRun,
    catalogs: ComparisonCatalogs,
    *,
    calls: Mapping[str, Any] | None,
    others_calls: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """One sealed hour of a day's run: the hour ``played`` holds, played on from ``start``. Its
    terms are the fifth score's over the comparison's group (everybody for a group of everybody),
    with each person's kinds; ``calls`` and ``others_calls`` are what the hour's asking of the
    group and of everybody else took, or None where it asked them nothing."""
    if society_engine(plan.engine_profile).state_family not in DAY_SCORE_BY_FAMILY:
        raise ValueError("window_not_offered: only a society that keeps a day runs one")
    if len(played.states) != HOUR_TICKS:
        raise ValueError("an hour holds exactly its own minutes")
    everybody = [person["id"] for person in played.start["inhabitants"]]
    people = everybody if plan.group is None else sorted(plan.group)
    terms = society_score_v5.hour_terms(
        played.states,
        played.events,
        people=people,
        choice_points=sum(played.choice_points[subject] for subject in people),
        routine=input_routine(plan.inputs[-1]),
        score=society_score_v5.score(catalogs.score).reliability,
    )
    receipts = [receipt["document_sha256"] for receipt in played.receipts]
    return _sealed(
        {
            "profile": HOUR_PROFILE,
            "definition_sha256": definition["document_sha256"],
            "run_id": str(plan.run_id),
            "arm": arm,
            "seed_digest": seed_digest_text,
            "hour": start.hour,
            "first_tick": start.hour * HOUR_TICKS,
            "ticks": HOUR_TICKS,
            "clock": {"start": _clock(start.state), "end": _clock(played.states[-1])},
            "start_state_sha256": society_state_sha256(start.state),
            "minutes": {"count": len(played.states), "state_sha256": played.minute_digests},
            "events_sha256": society_state_sha256(ordered_events_document(tuple(played.events))),
            "receipts": {
                "count": len(receipts),
                "first_sequence": start.first_sequence,
                "sha256": society_state_sha256(receipts),
            },
            "terms": terms,
            "calls": None if calls is None else dict(calls),
            "others_calls": None if others_calls is None else dict(others_calls),
            "people": minute_record(played.states, plan),
        }
    )


def combined_calls(found: Sequence[Mapping[str, Any] | None]) -> dict[str, Any] | None:
    """What a run's asking took over several hours, from each hour's: every count summed, the cost
    added, known only where every hour's was, and every answer time kept in order; None where no
    hour asked anybody."""
    asked = [calls for calls in found if calls is not None]
    if not asked:
        return None
    return {
        "asked": sum(int(calls["asked"]) for calls in asked),
        "first_answers_refused": sum(int(calls["first_answers_refused"]) for calls in asked),
        "cost_usd": usd_string(sum((Decimal(calls["cost_usd"]) for calls in asked), Decimal(0))),
        "cost_known": all(bool(calls["cost_known"]) for calls in asked),
        "latencies_ms": [int(ms) for calls in asked for ms in calls["latencies_ms"]],
    }


def day_outcome(
    definition: Mapping[str, Any],
    arm: str,
    seed_digest_text: str,
    hours: Sequence[Mapping[str, Any]],
    receipt_digests: Sequence[str],
) -> dict[str, Any]:
    """A day's run completed: its sealed ``hours``, every one of its window's in order, by digest;
    every receipt the run recorded, by digest in decision order; the day's terms assembled from the
    hours'; and what its asking took. An outcome is sealed and stored by the repository."""
    window = int(definition["window_ticks"])
    if [hour["hour"] for hour in hours] != list(range(window // HOUR_TICKS)):
        raise ValueError("a day's outcome follows every hour of its window, in order")
    if sum(int(hour["receipts"]["count"]) for hour in hours) != len(receipt_digests):
        raise ValueError("a day's receipts are its hours' receipts")
    if any(
        hour["definition_sha256"] != definition["document_sha256"]
        or (hour["arm"], hour["seed_digest"]) != (arm, seed_digest_text)
        for hour in hours
    ):
        raise ValueError("a day's hours are its own run's")
    return {
        "profile": DAY_RUN_PROFILE,
        "status": "completed",
        "definition_sha256": definition["document_sha256"],
        "arm": arm,
        "seed_digest": seed_digest_text,
        "minutes": {
            "count": sum(int(hour["minutes"]["count"]) for hour in hours),
            "hours": [hour["document_sha256"] for hour in hours],
        },
        "events_sha256": society_state_sha256([hour["events_sha256"] for hour in hours]),
        "receipts": {
            "count": len(receipt_digests),
            "sha256": society_state_sha256(list(receipt_digests)),
        },
        "terms": society_score_v5.day_terms([hour["terms"] for hour in hours]),
        "calls": combined_calls([hour["calls"] for hour in hours]),
        "others_calls": combined_calls([hour["others_calls"] for hour in hours]),
    }
