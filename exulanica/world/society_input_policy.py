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
LEGACY_INPUT = "exulanica.society-input/v1"
LOCAL_INPUT = "exulanica.society-input/v2"
AUTHORED_GROUND_INPUT = "exulanica.society-input/authored-ground-v1"
AUTHORED_GROUND_INPUT_V2 = "exulanica.society-input/authored-ground-v2"
AUTHORED_GROUND_INPUT_V3 = "exulanica.society-input/authored-ground-v3"
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
)
#: Compositions that record a known unreachable authored activity against that activity alone,
#: type-check authored transforms strictly, and publish an ``unavailable_affordances`` list.
LOCAL_FAILURE_COMPOSITIONS = (
    LOCAL_COMPOSITION,
    AUTHORED_GROUND_COMPOSITION,
    AUTHORED_GROUND_COMPOSITION_V2,
    AUTHORED_GROUND_COMPOSITION_V3,
)
LOCAL_FAILURE_INPUTS = (
    LOCAL_INPUT,
    AUTHORED_GROUND_INPUT,
    AUTHORED_GROUND_INPUT_V2,
    AUTHORED_GROUND_INPUT_V3,
)
#: Every input profile a saved world's own ground produces, oldest first. A society's inputs may
#: move forward along this order and never back.
AUTHORED_GROUND_INPUTS: Final = (
    AUTHORED_GROUND_INPUT,
    AUTHORED_GROUND_INPUT_V2,
    AUTHORED_GROUND_INPUT_V3,
)
#: Input profiles that record the purposeful routine they were composed under. Every other profile
#: records none and is read under the routine the society was first released with.
ROUTINE_INPUTS: Final = (AUTHORED_GROUND_INPUT_V3,)
#: Why an activity may be recorded as unavailable on its own, per input profile. A profile only
#: ever gains reasons in a new version, so a stored input is read with the vocabulary it was
#: written under.
LOCAL_RECORD_REASONS: Final[Mapping[str, frozenset[str]]] = {
    LOCAL_INPUT: frozenset({UNREACHABLE}),
    AUTHORED_GROUND_INPUT: frozenset({UNREACHABLE}),
    AUTHORED_GROUND_INPUT_V2: frozenset({UNREACHABLE, MOVES, OFF_GROUND, UNSUPPORTED_BEHAVIOUR}),
    AUTHORED_GROUND_INPUT_V3: frozenset({UNREACHABLE, MOVES, OFF_GROUND, UNSUPPORTED_BEHAVIOUR}),
}
#: Why a placement may be named as unread, per input profile that carries the list.
UNREAD_PLACEMENT_REASONS: Final[Mapping[str, frozenset[str]]] = {
    AUTHORED_GROUND_INPUT_V2: frozenset({NO_AUTHORED_FRAME}),
    AUTHORED_GROUND_INPUT_V3: frozenset({NO_AUTHORED_FRAME}),
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
        subject = f"authored:{row['version_id']}:{row['object_id']}"
        if (
            row["subject_id"] != subject
            or row["target_id"] != f"{subject}:{row['affordance']}"
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
