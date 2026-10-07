"""Versioned projection policy and local activity failures, without invented access nodes."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any, Final

LEGACY_COMPOSITION = "exulanica.society-composition/v1"
LOCAL_COMPOSITION = "exulanica.society-composition/v2"
#: The projection of a saved world that has no district: its walkable area is the authored
#: ground the world's own structural snapshot declares, and every activity comes from a
#: reviewed object the person placed in it.
AUTHORED_GROUND_COMPOSITION = "exulanica.society-composition/authored-ground-v1"
#: The same projection, refusing per object rather than for the whole world, and giving every
#: activity the places its occupants stand at. It never rewrites a stored authored-ground-v1
#: input; a society holding those replays them with their own semantics.
AUTHORED_GROUND_COMPOSITION_V2 = "exulanica.society-composition/authored-ground-v2"
#: The same projection again, recording the purposeful routine it was composed under
#: (``exulanica.world.society_catalogs``) and naming, for each activity, the routine's entry for the
#: object's kind in place of a fixed duration. It never rewrites a stored authored-ground-v2 input;
#: an input that records no routine is read under the rules it was recorded with.
AUTHORED_GROUND_COMPOSITION_V3 = "exulanica.society-composition/authored-ground-v3"
#: A new made-world society stands at the world-owned opening source its saved version pins.
#: Existing v3 societies keep the region-origin rule recorded in their inputs.
AUTHORED_GROUND_COMPOSITION_V4 = "exulanica.society-composition/authored-ground-v4"
#: The society of things (``exulanica-society/v7``) reads the fourth composition's ground, at the
#: opening source its saved version pins where the ground states none, and the things the world's
#: author placed in the version, each with what its kind says it is and does
#: (:mod:`exulanica.things.kinds`): a placed object blocks walking or offers a rest or a visit as
#: its kind says, a placed being lives there, and a gate is where visitors from outside arrive.
AUTHORED_GROUND_COMPOSITION_V5 = "exulanica.society-composition/authored-ground-v5"
LEGACY_INPUT = "exulanica.society-input/v1"
LOCAL_INPUT = "exulanica.society-input/v2"
AUTHORED_GROUND_INPUT = "exulanica.society-input/authored-ground-v1"
AUTHORED_GROUND_INPUT_V2 = "exulanica.society-input/authored-ground-v2"
AUTHORED_GROUND_INPUT_V3 = "exulanica.society-input/authored-ground-v3"
AUTHORED_GROUND_INPUT_V4 = "exulanica.society-input/authored-ground-v4"
AUTHORED_GROUND_INPUT_V5 = "exulanica.society-input/authored-ground-v5"
#: A saved world whose own records state its walking surfaces (a world generated from the city
#: grammar): the society walks those surfaces, the world's premises and benches are its activities,
#: and the input records the population its ground's rule derived (migration 0118).
WALKING_SURFACES_COMPOSITION = "exulanica.society-composition/walking-surfaces-v1"
WALKING_SURFACES_INPUT = "exulanica.society-input/walking-surfaces-v1"
#: The same projection again, carrying the town's living place beside it: the place the world's
#: records make under a living routine, whose homes, workplaces and shifts the living town reads
#: (migration 0120). It never rewrites a stored walking-surfaces-v1 input; a society holding those
#: replays them with their own semantics.
WALKING_SURFACES_COMPOSITION_V2 = "exulanica.society-composition/walking-surfaces-v2"
WALKING_SURFACES_INPUT_V2 = "exulanica.society-input/walking-surfaces-v2"
UNREACHABLE = "authored_affordance_unreachable"
#: An object that moves offers no activity: where it stands when an inhabitant arrives is a phase
#: the renderer holds and the society does not.
MOVES = "authored_object_moves"
#: An object that does not rest on the ground plane offers no activity: every reviewed activity
#: is used standing beside or on an object resting on the ground.
OFF_GROUND = "authored_object_off_ground"
#: A behaviour the society has no rule for, on an object that blocks nothing, offers no activity.
UNSUPPORTED_BEHAVIOUR = "unsupported_active_behaviour"
#: An environment placement in a saved world is not placed in the world's own frame: the ground
#: states no surveyed origin to place an admitted source against, so the society does not read it.
NO_AUTHORED_FRAME = "environment_placement_has_no_authored_frame"

_PAIRS = (
    (LEGACY_COMPOSITION, LEGACY_INPUT),
    (LOCAL_COMPOSITION, LOCAL_INPUT),
    (AUTHORED_GROUND_COMPOSITION, AUTHORED_GROUND_INPUT),
    (AUTHORED_GROUND_COMPOSITION_V2, AUTHORED_GROUND_INPUT_V2),
    (AUTHORED_GROUND_COMPOSITION_V3, AUTHORED_GROUND_INPUT_V3),
    (AUTHORED_GROUND_COMPOSITION_V4, AUTHORED_GROUND_INPUT_V4),
    (WALKING_SURFACES_COMPOSITION, WALKING_SURFACES_INPUT),
    (WALKING_SURFACES_COMPOSITION_V2, WALKING_SURFACES_INPUT_V2),
    (AUTHORED_GROUND_COMPOSITION_V5, AUTHORED_GROUND_INPUT_V5),
)
#: Compositions that record a known unreachable authored activity against that activity alone,
#: type-check authored transforms strictly, and publish an ``unavailable_affordances`` list.
LOCAL_FAILURE_COMPOSITIONS = (
    LOCAL_COMPOSITION,
    AUTHORED_GROUND_COMPOSITION,
    AUTHORED_GROUND_COMPOSITION_V2,
    AUTHORED_GROUND_COMPOSITION_V3,
    AUTHORED_GROUND_COMPOSITION_V4,
    WALKING_SURFACES_COMPOSITION,
    WALKING_SURFACES_COMPOSITION_V2,
    AUTHORED_GROUND_COMPOSITION_V5,
)
LOCAL_FAILURE_INPUTS = (
    LOCAL_INPUT,
    AUTHORED_GROUND_INPUT,
    AUTHORED_GROUND_INPUT_V2,
    AUTHORED_GROUND_INPUT_V3,
    AUTHORED_GROUND_INPUT_V4,
    WALKING_SURFACES_INPUT,
    WALKING_SURFACES_INPUT_V2,
    AUTHORED_GROUND_INPUT_V5,
)
#: Every input profile a saved world's own ground produces, oldest first. A society's inputs may
#: move forward along this order and never back; a society whose first input pins where people
#: arrive (``ARRIVAL_INPUTS``) keeps its first input's profile for its whole life.
AUTHORED_GROUND_INPUTS: Final = (
    AUTHORED_GROUND_INPUT,
    AUTHORED_GROUND_INPUT_V2,
    AUTHORED_GROUND_INPUT_V3,
    AUTHORED_GROUND_INPUT_V4,
    WALKING_SURFACES_INPUT,
    WALKING_SURFACES_INPUT_V2,
    AUTHORED_GROUND_INPUT_V5,
)
#: Input profiles that record the purposeful routine they were composed under. Every other profile
#: records none and is read under the routine the society was first released with.
ROUTINE_INPUTS: Final = (
    AUTHORED_GROUND_INPUT_V3,
    AUTHORED_GROUND_INPUT_V4,
    WALKING_SURFACES_INPUT,
    WALKING_SURFACES_INPUT_V2,
    AUTHORED_GROUND_INPUT_V5,
)
#: Input profiles that state where a person arrives by the opening source the version pins: the
#: fourth composition's always, and the things composition's wherever the ground states no arrival
#: of its own (``arrival`` is null where it does).
ARRIVAL_INPUTS: Final = (AUTHORED_GROUND_INPUT_V4, AUTHORED_GROUND_INPUT_V5)
#: Input profiles that carry the things the world's author placed in the version, which only a
#: society of things reads.
THING_INPUTS: Final = (AUTHORED_GROUND_INPUT_V5,)
#: Input profiles that record the population their ground's rule derived from the world.
POPULATION_INPUTS: Final = (WALKING_SURFACES_INPUT, WALKING_SURFACES_INPUT_V2)
#: Input profiles that carry the living place a living society over them walks, with the living
#: routine it was made under.
LIVING_INPUTS: Final = (WALKING_SURFACES_INPUT_V2,)
#: The composition an input over a world's own walking surfaces is made under, by the state
#: family of the engine that consumes it: the purposeful society walks the surfaces alone, and the
#: living town also reads the living place they are made from.
WALKING_SURFACES_BY_FAMILY: Final[Mapping[str, str]] = {
    "purposeful": WALKING_SURFACES_COMPOSITION,
    "living": WALKING_SURFACES_COMPOSITION_V2,
}
#: The input profiles whose activities may name a world's own records as their subjects, besides
#: the objects its person placed: those composed over a world's own walking surfaces. Which kinds
#: of record, the ground its navigation profile names states (the society ground catalog's
#: ``record_subjects``): a record's subject is its kind and its identity.
WORLD_RECORD_INPUTS: Final = (WALKING_SURFACES_INPUT, WALKING_SURFACES_INPUT_V2)
#: Record kinds an input profile's activities may name as their subjects whatever ground it is
#: composed over, by profile.
PROFILE_RECORD_SUBJECTS: Final[Mapping[str, tuple[str, ...]]] = {
    # A thing the world's author placed, by its id in the version.
    AUTHORED_GROUND_INPUT_V5: ("thing",),
}


def _record_subjects(document: Mapping[str, Any]) -> tuple[str, ...]:
    stated = PROFILE_RECORD_SUBJECTS.get(document["profile"], ())
    if document["profile"] not in WORLD_RECORD_INPUTS:
        return stated
    from exulanica.world.society_grounds import record_subjects_for

    navigation = document.get("navigation")
    profile = navigation.get("profile") if isinstance(navigation, Mapping) else None
    return (*record_subjects_for(str(profile)), *stated)


#: Why an activity may be recorded as unavailable on its own, per input profile. A profile only
#: ever gains reasons in a new version, so a stored input is read with the vocabulary it was
#: written under.
LOCAL_RECORD_REASONS: Final[Mapping[str, frozenset[str]]] = {
    LOCAL_INPUT: frozenset({UNREACHABLE}),
    AUTHORED_GROUND_INPUT: frozenset({UNREACHABLE}),
    AUTHORED_GROUND_INPUT_V2: frozenset({UNREACHABLE, MOVES, OFF_GROUND, UNSUPPORTED_BEHAVIOUR}),
    AUTHORED_GROUND_INPUT_V3: frozenset({UNREACHABLE, MOVES, OFF_GROUND, UNSUPPORTED_BEHAVIOUR}),
    AUTHORED_GROUND_INPUT_V4: frozenset({UNREACHABLE, MOVES, OFF_GROUND, UNSUPPORTED_BEHAVIOUR}),
    AUTHORED_GROUND_INPUT_V5: frozenset({UNREACHABLE, MOVES, OFF_GROUND, UNSUPPORTED_BEHAVIOUR}),
    # A world that states its walking surfaces joins no object its person placed to them, and a
    # place of its own too close to another's is not stood at: either activity is unreachable.
    WALKING_SURFACES_INPUT: frozenset({UNREACHABLE}),
    WALKING_SURFACES_INPUT_V2: frozenset({UNREACHABLE}),
}
#: Why a placement may be named as unread, per input profile that carries the list.
UNREAD_PLACEMENT_REASONS: Final[Mapping[str, frozenset[str]]] = {
    AUTHORED_GROUND_INPUT_V2: frozenset({NO_AUTHORED_FRAME}),
    AUTHORED_GROUND_INPUT_V3: frozenset({NO_AUTHORED_FRAME}),
    AUTHORED_GROUND_INPUT_V4: frozenset({NO_AUTHORED_FRAME}),
    AUTHORED_GROUND_INPUT_V5: frozenset({NO_AUTHORED_FRAME}),
    WALKING_SURFACES_INPUT: frozenset({NO_AUTHORED_FRAME}),
    WALKING_SURFACES_INPUT_V2: frozenset({NO_AUTHORED_FRAME}),
}
#: The bound on a local record list, shared with targets as the input bound always was.
LOCAL_RECORD_BOUND: Final = 4096


def input_profile(composition: str) -> str:
    for policy, profile in _PAIRS:
        if composition == policy:
            return profile
    raise ValueError("unsupported society composition policy")


def composition_profile(profile: str) -> str:
    for policy, value in _PAIRS:
        if profile == value:
            return policy
    raise ValueError("unsupported society input profile")


def is_authored_ground(profile: object) -> bool:
    """Whether an input profile is one a saved world's own ground produces."""
    return profile in AUTHORED_GROUND_INPUTS


def validate_local_affordances(document: dict, affordances: Collection[str]) -> None:
    """Check the activities an input records as unavailable on their own, against the affordances
    its routine states."""
    records = document["unavailable_affordances"]
    if (
        not isinstance(records, list)
        or len(records) + len(document["targets"]) > LOCAL_RECORD_BOUND
    ):
        raise ValueError("local activity bound exceeded")
    reasons = LOCAL_RECORD_REASONS[document["profile"]]
    names = []
    for row in records:
        if not isinstance(row, dict) or set(row) != {
            "target_id",
            "subject_id",
            "object_id",
            "version_id",
            "affordance",
            "reason",
        }:
            raise ValueError("invalid unavailable affordance fields")
        if any(not isinstance(v, str) or not 1 <= len(v) <= 1000 for v in row.values()):
            raise ValueError("invalid unavailable affordance reference")
        if row["version_id"] != document["version_id"] or row["affordance"] not in affordances:
            raise ValueError("unavailable affordance scope or action mismatch")
        subjects = {f"authored:{row['version_id']}:{row['object_id']}"} | {
            f"{kind}:{row['object_id']}" for kind in _record_subjects(document)
        }
        if (
            row["subject_id"] not in subjects
            or row["target_id"] != f"{row['subject_id']}:{row['affordance']}"
            or row["reason"] not in reasons
        ):
            raise ValueError("unavailable affordance identity or reason mismatch")
        names.append(row["target_id"])
    if names != sorted(set(names)) or set(names).intersection(
        t["target_id"] for t in document["targets"]
    ):
        raise ValueError("unavailable affordances must be sorted, unique and disjoint")
    if document["availability"] == "unavailable" and records:
        raise ValueError("unavailable input cannot expose local activity records")


def validate_unread_placements(document: dict[str, Any]) -> None:
    """The placements an input names as not read, each once, with a reason its profile knows."""
    records = document["unread_placements"]
    if not isinstance(records, list) or len(records) > LOCAL_RECORD_BOUND:
        raise ValueError("unread placement bound exceeded")
    reasons = UNREAD_PLACEMENT_REASONS[document["profile"]]
    names = []
    for row in records:
        if (
            not isinstance(row, dict)
            or set(row) != {"instance_id", "reason"}
            or not isinstance(row["instance_id"], str)
            or not 1 <= len(row["instance_id"]) <= 1000
            or row["reason"] not in reasons
        ):
            raise ValueError("invalid unread placement")
        names.append(row["instance_id"])
    if names != sorted(set(names)):
        raise ValueError("unread placements must be sorted and unique")
    if document["availability"] == "unavailable" and records:
        raise ValueError("unavailable input cannot expose local placement records")
