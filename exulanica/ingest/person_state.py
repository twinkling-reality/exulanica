"""Read one database-resolved privacy snapshot for both mask production and admission.

Consent precedence and expiry belong to the shared SQL policy. The offline receipt fold is
unchanged; it is not used to decide permission for a new operation against this database.
"""

from __future__ import annotations

import uuid

from exulanica.consent.regions import Silhouette
from exulanica.consent.states import ResolvedPresentation
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.spine.privacy import current_inputs
from exulanica.ingest.spine.scope import WorkspaceScope

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
    """The live outlines, subjects and states at one database evaluation instant."""
    inputs = current_inputs(
        WorkspaceScope(repository.connection, repository.workspace_id), capture_id
    )
    outlines = {}
    resolved = {}
    subjects = {}
    for row in (inputs or {}).get("regions", []):
        key = bytes.fromhex(row["region_key"])
        outlines[key] = Silhouette.from_digest_input(row["silhouette"])
        subjects[key] = uuid.UUID(row["subject_id"]) if row["subject_id"] else None
        resolved[key] = ResolvedPresentation(
            state=row["state"], name_permitted=row["name_permitted"]
        )
    return CaptureRegionState(outlines, resolved, subjects)
