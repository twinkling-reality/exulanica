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

import datetime as dt
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import NoReturn

import psycopg
from psycopg.types.json import Jsonb

from exulanica.api.composer_rights import observation_screening
from exulanica.errors import PrivacyAdmissionError
from exulanica.evidence.blob import BlobId
from exulanica.ingest.model_rights import require_model_right
from exulanica.ingest.personal_admission import creature_picture_note_context, role_handoff
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.spine.artifacts import CaptureArtifactRow
from exulanica.models.manifest import Manifest
from exulanica.references import store as reference_store
from exulanica.references.bundle import THINGS_PICTURE_PROFILE, read_bundle
from exulanica.references.for_drafting import NotesRefused, PictureNotesAuthority
from exulanica.references.pictures import PICTURE_ROLE, PictureUnavailable, ReferencePicture
from exulanica.store.base import ContentAddressedStore

__all__ = ["picture_refusal", "picture_still_readable", "reference_picture_source"]


def picture_refusal(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    capture_id: uuid.UUID,
    requester: uuid.UUID,
    asked_at: dt.datetime | None = None,
) -> tuple[str | None, CaptureArtifactRow | None, tuple[uuid.UUID, ...]]:
    """Why this workspace's ``capture_id`` may not be read for ``requester``'s reference notes, by
    code, or the rendition's artifact row and the rights it may be read under. A capture of another
    workspace reads as one with no screening; a picture whose rights another person granted reads
    as not admitted, so a request reads only its requester's own pictures. With ``asked_at``, when
    the request was made, a picture its requester stopped any reading right on since then reads as
    not admitted too, as the request's finish would withdraw what it read."""
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
    if asked_at is not None and _stopped_since(
        connection, workspace_id, capture_id, requester, asked_at
    ):
        return "picture_not_admitted", None, ()
    # A person the product already found in the picture is refused before any model sees it.
    if _person_found(connection, workspace_id, capture_id):
        return "shows_people", None, ()
    renditions = repository.current_capture_artifacts(capture_ids=[capture_id], kind="rendition")
    rendition = renditions.get(capture_id)
    if rendition is None:
        return "picture_has_no_rendition", None, ()
    return None, rendition, tuple(right.right_id for right in decision.rights)


def _person_found(
    connection: psycopg.Connection, workspace_id: uuid.UUID, capture_id: uuid.UUID
) -> bool:
    return (
        connection.execute(
            "select 1 from person_region_current where workspace_id=%s and capture_id=%s "
            "and action <> 'deleted' limit 1",
            (workspace_id, capture_id),
        ).fetchone()
        is not None
    )


def _stopped_since(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    capture_id: uuid.UUID,
    requester: uuid.UUID,
    asked_at: dt.datetime,
) -> bool:
    """Whether ``requester`` stopped any reading right on this picture at or after ``asked_at``."""
    return (
        connection.execute(
            "select 1 from personal_model_right where workspace_id=%s and capture_id=%s "
            "and model_role=%s and granted_by=%s and withdrawn_at >= %s limit 1",
            (workspace_id, capture_id, str(PICTURE_ROLE), requester, asked_at),
        ).fetchone()
        is not None
    )


def picture_still_readable(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    capture_id: uuid.UUID,
    right_ids: tuple[uuid.UUID, ...],
    requester: uuid.UUID,
    asked_at: dt.datetime,
) -> str | None:
    """Why a picture admitted under exactly ``right_ids`` may no longer be read, or None: every one
    of those rights still current for this picture (0073's own currency), none of ``requester``'s
    reading rights on it stopped since ``asked_at``, and no person found in it since. Asked as the
    reading is sent, so another person's right never stands in for a stopped one, and a picture
    whose notes the finish would withdraw is not sent."""
    row = connection.execute(
        "select count(*) filter (where personal_model_right_allows(workspace_id,right_id,"
        "capture_id,model_provider,model_role,model_id,model_revision,destination,"
        "clock_timestamp())) as current from personal_model_right "
        "where workspace_id=%s and capture_id=%s and right_id = any(%s)",
        (workspace_id, capture_id, list(right_ids)),
    ).fetchone()
    current = 0 if row is None else int(row["current"] if isinstance(row, dict) else row[0])
    if not right_ids or current != len(set(right_ids)):
        return "picture_not_admitted"
    if _stopped_since(connection, workspace_id, capture_id, requester, asked_at):
        return "picture_not_admitted"
    if _person_found(connection, workspace_id, capture_id):
        return "shows_people"
    return None


def reference_picture_source(
    session: Callable[[uuid.UUID], AbstractContextManager[psycopg.Connection]],
    store: ContentAddressedStore,
) -> Callable[[uuid.UUID, uuid.UUID, uuid.UUID, dt.datetime], ReferencePicture]:
    """The picture source of a process whose workspaces' sessions are ``session``: a picture by
    workspace, capture, the person asking and when they asked."""

    def picture(
        workspace_id: uuid.UUID, capture_id: uuid.UUID, requester: uuid.UUID, asked_at: dt.datetime
    ) -> ReferencePicture:
        with session(workspace_id) as connection:
            refusal, rendition, rights = picture_refusal(
                connection, workspace_id, capture_id, requester, asked_at
            )
        if refusal is not None or rendition is None:
            raise PictureUnavailable(refusal or "picture_not_admitted")

        def recheck() -> str | None:
            with session(workspace_id) as connection:
                return picture_still_readable(
                    connection, workspace_id, capture_id, rights, requester, asked_at
                )

        return ReferencePicture(store.get(BlobId(rendition.content_sha256)), rights, recheck)

    return picture


def creature_picture_notes_authority(
    *, manifest: Manifest, offered_to: Callable[[uuid.UUID], bool]
) -> PictureNotesAuthority:
    """Check exact picture-note authority on the caller's currency/lifecycle-guarded connection.

    No right row is locked. The worker serializes this read with privacy mutations and capture
    tombstones, releases those locks before dispatch, and repeats it in both publication phases.
    Hosted request policy independently checks declared photographs at its own dispatch boundary.
    """
    handoff = role_handoff("creature_drafter", manifest)

    def check(
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        requester: uuid.UUID,
        reference_id: uuid.UUID,
        photographs: frozenset[uuid.UUID],
        bound: Mapping[uuid.UUID, tuple[uuid.UUID, ...]] | None,
    ) -> dict[uuid.UUID, tuple[uuid.UUID, ...]]:
        def refuse() -> NoReturn:
            raise NotesRefused("reference_withdrawn")

        if not offered_to(workspace_id):
            refuse()
        found = reference_store.read_request(
            connection, workspace_id, reference_id, owner_actor_id=requester
        )
        if found is None or found.bundle is None:
            refuse()
        bundle = read_bundle(found.bundle)
        if bundle.profile != THINGS_PICTURE_PROFILE:
            refuse()
        expected_context = creature_picture_note_context(handoff)
        pictures = {picture.picture_id: picture for picture in bundle.pictures}
        rights_by_picture = {}
        for capture_id in sorted(photographs):
            picture = pictures.get(capture_id)
            if (
                picture is None
                or picture_still_readable(
                    connection,
                    workspace_id,
                    capture_id,
                    picture.model_right_ids,
                    requester,
                    found.created_at,
                )
                is not None
            ):
                refuse()
            # Resolve current screening with the same authoritative observation predicate, with
            # no asset-read lock acquired below the lifecycle lock.
            if not connection.execute(
                "select 1 from reconstruction_privacy_screening where workspace_id=%s "
                "and capture_id=%s and asset_observation_allows(workspace_id,capture_id,"
                "screening_id,clock_timestamp()) limit 1",
                (workspace_id, capture_id),
            ).fetchone():
                refuse()
            if connection.execute(
                "select 1 from personal_model_right where workspace_id=%s and capture_id=%s "
                "and model_role='creature_drafter' and granted_by=%s "
                "and withdrawn_at >= %s limit 1",
                (workspace_id, capture_id, requester, found.created_at),
            ).fetchone():
                refuse()
            selected = []
            for identity in handoff.identities:
                row = connection.execute(
                    "select r.right_id from personal_model_right r join personal_model_right_use u "
                    "using(workspace_id,right_id) where r.workspace_id=%s and r.capture_id=%s "
                    "and r.granted_by=%s and r.model_provider=%s and r.model_role=%s "
                    "and r.model_id=%s and r.model_revision is not distinct from %s "
                    "and r.destination=%s and u.use_context=%s "
                    "and personal_model_right_allows(r.workspace_id,r.right_id,r.capture_id,"
                    "r.model_provider,r.model_role,r.model_id,r.model_revision,r.destination,"
                    "clock_timestamp()) order by r.granted_at desc,r.right_id desc limit 1",
                    (
                        workspace_id,
                        capture_id,
                        requester,
                        identity.provider,
                        identity.role,
                        identity.model_id,
                        identity.revision,
                        handoff.destination,
                        Jsonb(expected_context),
                    ),
                ).fetchone()
                if row is None:
                    refuse()
                selected.append(row["right_id"])
            current = tuple(selected)
            if bound is not None and bound.get(capture_id) != current:
                refuse()
            rights_by_picture[capture_id] = current
        return rights_by_picture

    return check
