"""A person's own picture admitted through the app's routes, as a reference job may read it.

Only a picture a privacy screening permits looking at, with a current right for the picture role
and a rendition, is handed over: its rendition's bytes, never the original, and the right ids it is
read under. Everything else is refused by code. The admission and the derivative worker are the
product's; the vision stage is the counting double the admission tests use, and no model is called.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from exulanica.api.reference_pictures import picture_refusal, reference_picture_source
from exulanica.evidence.blob import BlobId
from exulanica.ingest.personal_admission import role_notices
from exulanica.references.pictures import PictureUnavailable

from test_intake_upload import upload as upload
from test_personal_admission_route import batch, post

pytestmark = pytest.mark.postgres


def _admitted(upload, roles: tuple[str, ...]) -> uuid.UUID:
    body = batch(upload, count=1)
    until = body["authority"]["valid_until"]
    notices = role_notices()
    body["model_rights"] = [
        {"role": role, "valid_until": until, "notice": notices[role]} for role in roles
    ]
    response = post(upload, "/personal-admission", body)
    assert response.status_code == 202, response.text
    return uuid.UUID(body["members"][0]["capture_id"])


def _now(upload) -> dt.datetime:
    return upload.repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]


def _granted_by(upload, capture_id) -> uuid.UUID:
    """The person who granted the picture's rights, as the database recorded them."""
    (row,) = upload.rows(
        "select distinct granted_by from personal_model_right where capture_id = %s", capture_id
    )
    return row["granted_by"]


def _refusal(upload, capture_id, requester=None):
    if requester is None:
        rows = upload.rows(
            "select distinct granted_by from personal_model_right where capture_id = %s",
            capture_id,
        )
        requester = rows[0]["granted_by"] if rows else uuid.uuid4()
    return picture_refusal(upload.repository.connection, upload.workspace_id, capture_id, requester)


def _rights(upload, capture_id) -> set[uuid.UUID]:
    rows = upload.rows(
        "select right_id from personal_model_right where capture_id = %s and model_role = %s",
        capture_id,
        "reference_vision",
    )
    return {row["right_id"] for row in rows}


def test_an_admitted_picture_is_handed_over_as_its_rendition_with_its_rights(upload) -> None:
    capture_id = _admitted(upload, ("reference_vision",))
    upload.drain(screened=False)
    reason, rendition, rights = _refusal(upload, capture_id)
    assert reason is None
    assert set(rights) == _rights(upload, capture_id) and rights
    (row,) = upload.rows(
        "select a.content_sha256 from artifact a join capture c "
        "on a.source_blob_sha256 = c.blob_sha256 where c.capture_id = %s and a.kind = 'rendition'",
        capture_id,
    )
    assert rendition.content_sha256 == bytes(row["content_sha256"])
    picture = reference_picture_source(upload.database.session, upload.store)(
        upload.workspace_id, capture_id, _granted_by(upload, capture_id), _now(upload)
    )
    assert picture.image == upload.store.get(BlobId(rendition.content_sha256))
    (original,) = upload.rows("select blob_sha256 from capture where capture_id = %s", capture_id)
    assert picture.image != upload.store.get(BlobId(bytes(original["blob_sha256"])))
    assert picture.right_ids == rights


def test_a_picture_without_a_right_for_the_picture_role_is_not_admitted(upload) -> None:
    capture_id = _admitted(upload, ("vision",))
    upload.drain(screened=False)
    assert _refusal(upload, capture_id) == ("picture_not_admitted", None, ())
    with pytest.raises(PictureUnavailable) as refused:
        reference_picture_source(upload.database.session, upload.store)(
            upload.workspace_id, capture_id, _granted_by(upload, capture_id), _now(upload)
        )
    assert refused.value.reason == "picture_not_admitted"


def test_an_unknown_picture_or_one_nobody_admitted_reads_as_not_screened(upload) -> None:
    assert _refusal(upload, uuid.uuid4()) == ("picture_not_screened", None, ())
    uploaded = upload.one().json()["accepted"][0]
    assert _refusal(upload, uuid.UUID(uploaded["capture_id"]))[0] == "picture_not_screened"


def test_an_admitted_picture_waits_for_its_rendition(upload) -> None:
    capture_id = _admitted(upload, ("reference_vision",))
    assert _refusal(upload, capture_id) == ("picture_has_no_rendition", None, ())


def test_a_picture_another_person_admitted_is_not_admitted_for_this_one(upload) -> None:
    capture_id = _admitted(upload, ("reference_vision",))
    upload.drain(screened=False)
    holder = _granted_by(upload, capture_id)
    assert _refusal(upload, capture_id, holder)[0] is None
    assert _refusal(upload, capture_id, uuid.uuid4()) == ("picture_not_admitted", None, ())


def test_an_exempt_picture_holds_no_right_and_is_not_admitted(upload) -> None:
    capture_id = uuid.UUID(upload.one().json()["accepted"][0]["capture_id"])
    upload.screen()
    assert _refusal(upload, capture_id, uuid.uuid4()) == ("picture_not_admitted", None, ())


def test_a_picture_the_product_found_a_person_in_is_refused_as_showing_people(upload) -> None:
    from exulanica.ingest.person_review import record_region_edits

    capture_id = _admitted(upload, ("reference_vision",))
    upload.drain(screened=False)
    holder = _granted_by(upload, capture_id)
    assert _refusal(upload, capture_id, holder)[0] is None
    record_region_edits(
        upload.repository,
        capture_id=capture_id,
        actor=holder,
        edits=[
            {
                "action": "add",
                "region_key": "cc" * 32,
                "silhouette": {
                    "kind": "polygon",
                    "points": [[0, 0], [400000, 0], [400000, 400000], [0, 400000]],
                },
            }
        ],
    )
    assert _refusal(upload, capture_id, holder) == ("shows_people", None, ())


def test_the_send_time_check_reads_exactly_the_rights_the_picture_was_admitted_under(
    upload,
) -> None:
    from exulanica.ingest.model_rights import withdraw_model_right
    from exulanica.ingest.person_review import record_region_edits
    from exulanica.ingest.repository import IngestRepository

    capture_id = _admitted(upload, ("reference_vision",))
    upload.drain(screened=False)
    holder = _granted_by(upload, capture_id)
    source = reference_picture_source(upload.database.session, upload.store)
    # Asked later than the stop below, so only the check on exactly these rights can refuse.
    later = _now(upload) + dt.timedelta(hours=1)
    picture = source(upload.workspace_id, capture_id, holder, later)
    assert picture.recheck() is None
    (right_id,) = picture.right_ids
    repository = IngestRepository(upload.repository.connection, upload.workspace_id)
    withdraw_model_right(repository, right_id=right_id, withdrawn_by=holder)
    regranted = _admitted_again(upload, capture_id)
    # A current right stands for the picture again, but not the one this reading was admitted
    # under: the reading already in flight may not go.
    assert picture.recheck() == "picture_not_admitted"
    fresh = source(upload.workspace_id, capture_id, holder, later)
    assert fresh.right_ids == regranted and fresh.recheck() is None
    record_region_edits(
        upload.repository,
        capture_id=capture_id,
        actor=holder,
        edits=[
            {
                "action": "add",
                "region_key": "dd" * 32,
                "silhouette": {
                    "kind": "polygon",
                    "points": [[0, 0], [400000, 0], [400000, 400000], [0, 400000]],
                },
            }
        ],
    )
    assert fresh.recheck() == "shows_people"


def _admitted_again(upload, capture_id) -> tuple[uuid.UUID, ...]:
    """A new picture right on the same picture, under the authority and grantor of the first."""
    from exulanica.ingest.model_rights import grant_model_right
    from exulanica.ingest.personal_admission import role_handoff
    from exulanica.ingest.repository import IngestRepository

    (first,) = upload.rows(
        "select authorization_id, granted_by, purpose from personal_model_right "
        "where capture_id = %s order by granted_at limit 1",
        capture_id,
    )
    handoff = role_handoff("reference_vision")
    repository = IngestRepository(upload.repository.connection, upload.workspace_id)
    now = upload.repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]
    return tuple(
        grant_model_right(
            repository,
            capture_id=capture_id,
            authorization_id=first["authorization_id"],
            identity=identity,
            destination=handoff.destination,
            granted_by=first["granted_by"],
            purpose=first["purpose"],
            valid_until=now + dt.timedelta(minutes=30),
        ).right_id
        for identity in handoff.identities
    )


def test_a_picture_whose_requester_stopped_a_reading_right_since_asking_is_not_read(upload):
    from exulanica.ingest.model_rights import withdraw_model_right
    from exulanica.ingest.repository import IngestRepository

    capture_id = _admitted(upload, ("reference_vision",))
    upload.drain(screened=False)
    holder = _granted_by(upload, capture_id)
    (second,) = _admitted_again(upload, capture_id)
    asked = _now(upload)
    source = reference_picture_source(upload.database.session, upload.store)
    picture = source(upload.workspace_id, capture_id, holder, asked)
    assert picture.recheck() is None
    # The person stops one of their two current rights after asking: the other still stands, but
    # the finish would withdraw whatever is read, so nothing is read.
    repository = IngestRepository(upload.repository.connection, upload.workspace_id)
    rights = upload.rows(
        "select right_id from personal_model_right where capture_id = %s and model_role = %s",
        capture_id,
        "reference_vision",
    )
    (stopped,) = [row["right_id"] for row in rights if row["right_id"] not in picture.right_ids]
    assert second in {stopped, *picture.right_ids}
    withdraw_model_right(repository, right_id=stopped, withdrawn_by=holder)
    assert picture.recheck() == "picture_not_admitted"
    with pytest.raises(PictureUnavailable) as refused:
        source(upload.workspace_id, capture_id, holder, asked)
    assert refused.value.reason == "picture_not_admitted"
    # Asked after that stop, the remaining right is read.
    assert source(upload.workspace_id, capture_id, holder, _now(upload)).recheck() is None
