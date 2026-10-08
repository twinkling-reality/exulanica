"""The picture source a reference job reads a person's own pictures through.

A picture is handed over only as its rendition, the 768 px copy with no location or camera details,
and only while a privacy screening permits looking at it, a current right names every model of the
picture role's chain for it (:func:`~exulanica.ingest.model_rights.require_model_right`, the check
the vision stage makes), every such right was granted by the person asking, and the product has
found no person in it. The right ids go into the bundle beside the picture. The request
policy checks the right again when the reading is sent, so a right stopped in between is still
honoured. Anything else is refused by code, and the code is all the job's step shows.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager

import psycopg

from exulanica.api.composer_rights import observation_screening
from exulanica.errors import PrivacyAdmissionError
from exulanica.evidence.blob import BlobId
from exulanica.ingest.model_rights import require_model_right
from exulanica.ingest.personal_admission import role_handoff
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.spine.artifacts import CaptureArtifactRow
from exulanica.references.pictures import PICTURE_ROLE, PictureUnavailable, ReferencePicture
from exulanica.store.base import ContentAddressedStore

__all__ = ["picture_refusal", "reference_picture_source"]


def picture_refusal(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    capture_id: uuid.UUID,
    requester: uuid.UUID,
) -> tuple[str | None, CaptureArtifactRow | None, tuple[uuid.UUID, ...]]:
    """Why this workspace's ``capture_id`` may not be read for ``requester``'s reference notes, by
    code, or the rendition's artifact row and the rights it may be read under. A capture of another
    workspace reads as one with no screening; a picture whose rights another person granted reads
    as not admitted, so a request reads only its requester's own pictures."""
    repository = IngestRepository(connection, workspace_id)
    screening_id = observation_screening(repository, capture_id)
    if screening_id is None:
        return "picture_not_screened", None, ()
    try:
        decision = require_model_right(
            repository, capture_id, screening_id, role_handoff(str(PICTURE_ROLE))
        )
    except PrivacyAdmissionError:
        return "picture_not_admitted", None, ()
    # An exempt capture holds no right, and a bundle names the rights a picture was read under: a
    # person's own picture always has them.
    if not decision.rights or any(right.granted_by != requester for right in decision.rights):
        return "picture_not_admitted", None, ()
    # A person the product already found in the picture is refused before any model sees it.
    if repository.connection.execute(
        "select 1 from person_region_current where workspace_id=%s and capture_id=%s "
        "and action <> 'deleted' limit 1",
        (workspace_id, capture_id),
    ).fetchone():
        return "shows_people", None, ()
    renditions = repository.current_capture_artifacts(capture_ids=[capture_id], kind="rendition")
    rendition = renditions.get(capture_id)
    if rendition is None:
        return "picture_has_no_rendition", None, ()
    return None, rendition, tuple(right.right_id for right in decision.rights)


def reference_picture_source(
    session: Callable[[uuid.UUID], AbstractContextManager[psycopg.Connection]],
    store: ContentAddressedStore,
) -> Callable[[uuid.UUID, uuid.UUID, uuid.UUID], ReferencePicture]:
    """The picture source of a process whose workspaces' sessions are ``session``: a picture by
    workspace, capture and the person asking."""

    def picture(
        workspace_id: uuid.UUID, capture_id: uuid.UUID, requester: uuid.UUID
    ) -> ReferencePicture:
        with session(workspace_id) as connection:
            refusal, rendition, rights = picture_refusal(
                connection, workspace_id, capture_id, requester
            )
        if refusal is not None or rendition is None:
            raise PictureUnavailable(refusal or "picture_not_admitted")
        return ReferencePicture(store.get(BlobId(rendition.content_sha256)), rights)

    return picture
