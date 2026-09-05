"""What must be recomputed because of this decision?

``derived_artifact.dep_index`` is the flattened ``'kind:<uuid>'`` form with a GIN index over it,
precisely so invalidation is a query rather than a hand-maintained list of things to remember. A
generated title naming somebody has to become stale when that person is merged away, or the name
survives its own deletion inside a caption.

**The kinds are named in the signature rather than taken as keywords.** The flattening used to be
a free ``**subjects`` helper, which meant ``mark_stale(entty=x)`` was a well-formed call that
produced a key nothing indexes and reported a confident zero. There are two kinds of dependency
an identity decision touches, they are spelled here, and a third is a deliberate edit.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from exulanica.identity.repository import IdentityRepository

__all__ = ["Recomputation"]

#: What a single subject may be given as. A bare id is the common case and a sequence is the
#: merge and split case, where a decision touches several records at once.
Subjects = uuid.UUID | Sequence[uuid.UUID] | None


class Recomputation:
    """Writes over ``derived_artifact.stale``."""

    def __init__(self, repository: IdentityRepository) -> None:
        self._repository = repository

    def serialize(self) -> None:
        """Keep the exemplar index refresh in the same order as identity decisions."""
        self._repository.connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"identity-match-context:{self._repository.workspace_id}",),
        )

    def mark_stale(self, *, entity: Subjects = None, occurrence: Subjects = None) -> int:
        """Flag every derived artifact that depended on any of these, and say how many.

        The count is how many rows this call changed, not how many depend on the subjects: an
        artifact already stale is left alone and is not counted, because "invalidated by this
        decision" and "currently invalid" are different facts.
        """
        dependencies = _dep_index("entity", entity) + _dep_index("occurrence", occurrence)
        if not dependencies:
            return 0
        cursor = self._repository.connection.execute(
            "update derived_artifact set stale = true where workspace_id = %s "
            "and dep_index && %s::text[] and not stale",
            (self._repository.workspace_id, dependencies),
        )
        return cursor.rowcount


def _dep_index(kind: str, subject: Subjects) -> list[str]:
    """The ``dep_index`` strings for one kind of subject, in the form the GIN index holds."""
    if subject is None:
        return []
    if isinstance(subject, uuid.UUID):
        return [f"{kind}:{subject}"]
    return [f"{kind}:{item}" for item in subject]
