"""The personal model right that text derived from a photograph is sent under, from the API.

A packet carries the claims stored about each photograph it cites: the text the vision pass
transcribed from a sign, the scene it described, the date the camera recorded. Those are derived
from the photograph, so they are personal exactly when the photograph is, and the account holder
has decided that derived text goes to a hosted model only under a current personal model right
naming that model and its destination, the same as the photograph's bytes. The ingest stages and
the caption vector pass ask that through :func:`exulanica.ingest.model_rights.require_model_right`.

It lives here rather than in ``exulanica.selection`` because answering a question and ingesting a
photograph are sibling workflows that may not import each other, and the right is ingest's. The
API sits above both, so it builds the check and hands it on, twice: to
:func:`exulanica.selection.question.answer_question`, which calls it immediately before the
composer and refuses to compose without one, and to every workspace policy the API attaches to a
model client (``Services.hosted_model``), which calls it again for every photograph a request
names as the request leaves. That is the shape the caption vector pass already has: the worker
supplies ``before_send`` and the pass cannot send without it.

**All or nothing.** Every photograph must be permitted for every model the role can reach. A
capture screened under a synthetic or benchmark exemption needs no right; that decision is the
right module's.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable

import psycopg

from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.model_rights import require_model_right
from exulanica.ingest.repository import IngestRepository
from exulanica.models.handoff import ModelHandoff

__all__ = ["composer_rights_check", "photograph_text_right"]


def _observation_screening(repository: IngestRepository, capture_id: uuid.UUID) -> uuid.UUID | None:
    """The receipt that lets this capture be looked at, chosen as the derivative worker chooses.

    The newest current eligible receipt first; otherwise the newest detection-only receipt that
    still permits observation. The same order as ``DerivativeWorker._run_job``, so a capture the
    worker would have sent to the vision model is judged here against the same receipt.
    """
    screening = repository.latest_privacy_screening(capture_id)
    if screening is not None:
        return screening.screening_id
    row = repository.connection.execute(
        "select screening_id from reconstruction_privacy_screening "
        "where workspace_id=%s and capture_id=%s "
        "and screening_method='person_detection_only' "
        "and privacy_screening_allows_observation(workspace_id,capture_id,screening_id) "
        "order by screened_at desc,screening_id desc limit 1",
        (repository.workspace_id, capture_id),
    ).fetchone()
    return None if row is None else row["screening_id"]


def photograph_text_right(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    captures: Iterable[uuid.UUID],
    handoff: ModelHandoff,
) -> None:
    """Raise ``PrivacyAdmissionError`` unless every capture may reach ``handoff``.

    The photograph right a workspace policy is built with. Called on an idle connection, because
    ``require_model_right`` takes its own read-only transaction under the asset read lock and
    refuses a connection already inside one.
    """
    repository = IngestRepository(connection, workspace_id)
    for capture_id in sorted(set(captures), key=str):
        screening_id = _observation_screening(repository, capture_id)
        if screening_id is None:
            raise PrivacyAdmissionError(
                f"capture {capture_id}: no privacy screening permits sending text derived "
                "from it to a model"
            )
        try:
            require_model_right(repository, capture_id, screening_id, handoff)
        except PrivacyAdmissionError as refusal:
            raise PrivacyAdmissionError(f"capture {capture_id}: {refusal}") from refusal


def composer_rights_check(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> Callable[[Iterable[uuid.UUID], ModelHandoff], None]:
    """:func:`photograph_text_right` on ``connection``, shaped as ``answer_question`` asks."""

    def check(capture_ids: Iterable[uuid.UUID], handoff: ModelHandoff) -> None:
        photograph_text_right(connection, workspace_id, capture_ids, handoff)

    return check
