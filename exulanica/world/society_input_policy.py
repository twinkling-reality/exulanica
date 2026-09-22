"""Versioned projection policy and local activity failures, without invented access nodes."""

from __future__ import annotations

LEGACY_COMPOSITION = "exulanica.society-composition/v1"
LOCAL_COMPOSITION = "exulanica.society-composition/v2"
#: The projection of a saved world that has no district: its walkable area is the authored
#: ground the world's own structural snapshot declares, and every activity comes from a
#: reviewed object the person placed in it.
AUTHORED_GROUND_COMPOSITION = "exulanica.society-composition/authored-ground-v1"
LEGACY_INPUT = "exulanica.society-input/v1"
LOCAL_INPUT = "exulanica.society-input/v2"
AUTHORED_GROUND_INPUT = "exulanica.society-input/authored-ground-v1"
UNREACHABLE = "authored_affordance_unreachable"

_PAIRS = (
    (LEGACY_COMPOSITION, LEGACY_INPUT),
    (LOCAL_COMPOSITION, LOCAL_INPUT),
    (AUTHORED_GROUND_COMPOSITION, AUTHORED_GROUND_INPUT),
)
#: Compositions that record a known unreachable authored activity against that activity alone,
#: type-check authored transforms strictly, and publish an ``unavailable_affordances`` list.
LOCAL_FAILURE_COMPOSITIONS = (LOCAL_COMPOSITION, AUTHORED_GROUND_COMPOSITION)
LOCAL_FAILURE_INPUTS = (LOCAL_INPUT, AUTHORED_GROUND_INPUT)


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


def validate_local_affordances(document: dict, durations: dict) -> None:
    records = document["unavailable_affordances"]
    if not isinstance(records, list) or len(records) + len(document["targets"]) > 4096:
        raise ValueError("local activity bound exceeded")
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
        if row["version_id"] != document["version_id"] or row["affordance"] not in durations:
            raise ValueError("unavailable affordance scope or action mismatch")
        subject = f"authored:{row['version_id']}:{row['object_id']}"
        if (
            row["subject_id"] != subject
            or row["target_id"] != f"{subject}:{row['affordance']}"
            or row["reason"] != UNREACHABLE
        ):
            raise ValueError("unavailable affordance identity or reason mismatch")
        names.append(row["target_id"])
    if names != sorted(set(names)) or set(names).intersection(
        t["target_id"] for t in document["targets"]
    ):
        raise ValueError("unavailable affordances must be sorted, unique and disjoint")
    if document["availability"] == "unavailable" and records:
        raise ValueError("unavailable input cannot expose local activity records")
