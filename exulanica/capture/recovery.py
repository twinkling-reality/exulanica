"""What happened to a set of photographs, as a closed vocabulary, and who may say so.

``recovery_state`` is an OUTCOME. A verdict emitted before a run is a PREDICTION, and the two are
separate types on purpose: :class:`exulanica.capture.verdict.CaptureVerdict` carries a predicted
ceiling and has no way to become a state, and :class:`RecoveryOutcome` below can only be built
from a run's own receipt. Collapsing them would let a guess about a reconstruction be recorded
as a reconstruction, which is the failure this repository is built to prevent.

The five states, in order:

*   ``not_attempted``: the state a set arrives in. Nothing was measured and nothing was refused.
*   ``insufficient_overlap``: the set will not rebuild because its photographs do not overlap
    enough. Written from a verdict, as a refusal to attempt, which is a fact about the
    photographs rather than a claim about a reconstruction; or from a pose receipt that placed
    no photograph at all.
*   ``registered_partial``: a run placed photographs and the pose gate did not accept the set,
    usually because too few were placed and sometimes for another reason the receipt records
    (the bowl's 40-photograph group placed 40 of 40 and was refused on camera translation).
    Only a pose receipt says this.
*   ``registered_scene``: a run placed the set and the pose gate accepted it. Only a pose
    receipt says this.
*   ``trained_radiance``: a trained scene was delivered for the set. Only a training receipt
    says this.

The dominant real outcome for an ordinary capture is the second, and it has a name so that a
set in it is a room of its own photographs with a stated reason instead of an absence.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Literal

from exulanica.canonical import sha256_of_canonical

__all__ = [
    "BASES",
    "MEMBER_DIGEST_PROFILE",
    "POSE_RECEIPT_PROFILE",
    "RECOVERY_STATES",
    "WRITABLE_WITHOUT_RUN",
    "Basis",
    "RecoveryOutcome",
    "RecoveryState",
    "member_digest",
    "outcome_from_pose_receipt",
]

RecoveryState = Literal[
    "not_attempted",
    "insufficient_overlap",
    "registered_partial",
    "registered_scene",
    "trained_radiance",
]

#: Ordered from nothing to everything. Migration 0063 carries the same five in a check
#: constraint, and ``tests/test_place_recovery_state.py`` holds the two lists equal.
RECOVERY_STATES: Final[tuple[RecoveryState, ...]] = (
    "not_attempted",
    "insufficient_overlap",
    "registered_partial",
    "registered_scene",
    "trained_radiance",
)

#: The only states a record may hold without a run having produced a receipt.
WRITABLE_WITHOUT_RUN: Final[frozenset[RecoveryState]] = frozenset(
    {"not_attempted", "insufficient_overlap"}
)

Basis = Literal["verdict", "pose_receipt", "training_receipt", "withdrawal"]

#: What a state change may rest on. Closed, and the schema refuses any other.
BASES: Final[tuple[Basis, ...]] = ("verdict", "pose_receipt", "training_receipt", "withdrawal")

#: The pose receipt shape this reader agrees to. Restated rather than imported, because
#: ``exulanica.capture`` may not import ``exulanica.reconstruction``, and because this is the
#: reader's half of that agreement: another profile is refused rather than read under an
#: interpretation nobody agreed to.
POSE_RECEIPT_PROFILE: Final = "exulanica.colmap-pose-receipt/v2"

MEMBER_DIGEST_PROFILE: Final = "exulanica.place-record-members/v1"


def member_digest(capture_ids: Iterable[uuid.UUID]) -> bytes:
    """The digest that makes one exact set of photographs one record per workspace.

    Over the sorted canonical text of the ids, so it names the set and not the order the set was
    given in. Migration 0063 stores it and cannot recompute it, which is the same arrangement
    0024 accepted for a scene's member digest.
    """
    ids = sorted(str(uuid.UUID(str(capture_id))) for capture_id in capture_ids)
    if not ids:
        raise ValueError("a record holds at least one photograph")
    if len(set(ids)) != len(ids):
        raise ValueError("a capture appears twice, so the members are not a set")
    return sha256_of_canonical({"profile": MEMBER_DIGEST_PROFILE, "captures": ids})


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    """A state a run's own receipt established, with the integers it was read from."""

    state: RecoveryState
    basis: Literal["pose_receipt"]
    registered_count: int
    member_count: int
    accepted: bool


def outcome_from_pose_receipt(receipt: Mapping[str, object]) -> RecoveryOutcome:
    """Read the outcome a pose receipt records, or raise naming what does not fit.

    The state is read from counts and the gate's own acceptance, never from
    ``registered_fraction``: that field is a float, and the count it was computed from is in the
    same receipt. No photograph placed is ``insufficient_overlap``; some placed without the gate
    accepting is ``registered_partial``, which is the correct but empty outcome that looks like a
    downstream bug when nobody reads the gate first; an accepted set is ``registered_scene``.
    """
    if receipt.get("profile") != POSE_RECEIPT_PROFILE:
        raise ValueError(f"unexpected pose receipt profile {receipt.get('profile')!r}")
    quality = receipt.get("quality")
    if not isinstance(quality, Mapping):
        raise ValueError("the pose receipt has no quality block")
    registered = quality.get("registered_images")
    member_count = quality.get("source_count")
    accepted = quality.get("accepted")
    if not isinstance(registered, list) or type(member_count) is not int or member_count < 1:
        raise ValueError("the pose receipt does not count its photographs")
    if type(accepted) is not bool:
        raise ValueError("the pose receipt does not say whether the gate accepted it")
    count = len(registered)
    if count > member_count or (accepted and count == 0):
        raise ValueError("the pose receipt's counts contradict each other")
    state: RecoveryState
    if count == 0:
        state = "insufficient_overlap"
    elif accepted:
        state = "registered_scene"
    else:
        state = "registered_partial"
    return RecoveryOutcome(state, "pose_receipt", count, member_count, accepted)
