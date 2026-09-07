"""Read the recorded regions and receipts for one photograph, and fold them into a decision.

One place, so the masking stage and anything else that must know are reading the same answer. The
fold itself is :func:`exulanica.consent.states.resolve_presentation`, which is pure and is the
same function an offline verifier runs over a World Memory Package; this module is only the part
that fetches rows. Keeping those separate is what stops a second implementation of the rule
appearing next to the database.

**A region whose subject is unknown resolves to ``unknown``, which masks.** That is not a special
case handled here, it is what the pure fold returns for an empty receipt chain, and this module
takes care not to paper over it: a detected region nobody has confirmed has no subject, so it has
no receipts, so it is hidden. The whole of default deny survives the trip through the database
because nothing here supplies a default.
"""

from __future__ import annotations

import uuid

from exulanica.consent.regions import Silhouette
from exulanica.consent.states import ConsentTransition, ResolvedPresentation, resolve_presentation
from exulanica.ingest.repository import IngestRepository

__all__ = ["CaptureRegionState", "region_state_for_capture"]


class CaptureRegionState:
    """The three maps the masking stage needs, keyed by region."""

    __slots__ = ("outlines", "resolved", "subjects")

    def __init__(
        self,
        outlines: dict[bytes, Silhouette],
        resolved: dict[bytes, ResolvedPresentation],
        subjects: dict[bytes, uuid.UUID | None],
    ) -> None:
        self.outlines = outlines
        self.resolved = resolved
        self.subjects = subjects

    @property
    def any_masked(self) -> bool:
        """Whether anybody in this photograph must be hidden before geometry reads it."""
        return any(state.masked for state in self.resolved.values())


def region_state_for_capture(
    repository: IngestRepository, capture_id: uuid.UUID
) -> CaptureRegionState:
    """Every live region on one photograph, with the state that holds for each right now.

    Each subject's chain is read once and folded once per region, because a region-scoped receipt
    and a subject-wide one apply to different regions and must not be merged by the query. A
    region with no subject is folded from an empty chain, which resolves to ``unknown``.
    """
    if not repository.capture_has_person_regions(capture_id=capture_id):
        # The overwhelmingly common case, answered from an index rather than from a `distinct on`
        # over the whole table. See `has_regions` for the measurement that put this here.
        return CaptureRegionState({}, {}, {})
    rows = repository.current_person_regions(capture_ids=[capture_id]).get(capture_id, [])
    outlines: dict[bytes, Silhouette] = {}
    resolved: dict[bytes, ResolvedPresentation] = {}
    subjects: dict[bytes, uuid.UUID | None] = {}
    chains: dict[uuid.UUID, list] = {}
    for row in rows:
        outlines[row.region_key] = Silhouette.from_digest_input(row.silhouette)
        subjects[row.region_key] = row.subject_id
        if row.subject_id is None:
            resolved[row.region_key] = resolve_presentation(())
            continue
        if row.subject_id not in chains:
            chains[row.subject_id] = repository.person_consent_transitions(
                subject_id=row.subject_id
            )
        chain = chains[row.subject_id]
        # A withdrawal is not a scope somebody can grant back, so it is lifted out of the fold and
        # passed as the short circuit it is. See exulanica.consent.states.
        withdrawn = any(item.decision == "withdrawn" for item in chain)
        applicable = tuple(
            ConsentTransition(
                scope=item.consent_scope,
                granted=item.decision == "granted",
                actor=str(item.actor_id),
                decided_at=item.effective_at,
                receipt_digest=item.consent_digest,
            )
            for item in chain
            if item.decision != "withdrawn"
            and (item.region_key is None or item.region_key == row.region_key)
        )
        resolved[row.region_key] = resolve_presentation(applicable, withdrawn=withdrawn)
    return CaptureRegionState(outlines, resolved, subjects)
