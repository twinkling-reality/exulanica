"""Actual PostgreSQL transactions; generated photographs and scripted vision only."""

import concurrent.futures
import threading
import uuid

import pytest
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.person_review import create_subject
from exulanica.ingest.personal_requests import admission_status, personal_request
from exulanica.ingest.repository import IngestRepository

from test_intake_upload import _TOKEN
from test_intake_upload import upload as upload
from test_personal_admission_route import batch, post, reviewing


def actor(upload):
    return upload.client.app.state.services.tokens.session_for(_TOKEN).actor


def test_concurrent_admission_returns_one_batch_job_and_receipt(upload):
    body = batch(upload, count=1)
    body["request_id"] = str(uuid.uuid4())
    barrier = threading.Barrier(2)

    def send():
        barrier.wait(timeout=10)
        return post(upload, "/personal-admission", body)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: send(), range(2)))
    assert all(r.status_code == 202 for r in responses), [r.text for r in responses]
    assert responses[0].json() == responses[1].json()
    assert len(upload.rows("select * from personal_request_receipt")) == 1
    assert len(upload.rows("select * from capture_reconstruction_authorization")) == 1
    assert len(upload.rows("select * from reconstruction_privacy_screening")) == 1
    assert responses[0].json()["receipt_only"] is True
    assert post(upload, "/personal-admission", body).json() == responses[0].json()
    changed = {**body, "purpose": "A different purpose"}
    assert post(upload, "/personal-admission", changed).status_code == 409
    assert len(upload.rows("select * from personal_request_receipt")) == 1


def linked(upload):
    body = batch(upload, count=2)
    assert post(upload, "/personal-admission", body).status_code == 202
    upload.drain(screened=False)
    selected = [
        {
            "capture_id": member["capture_id"],
            "region_key": upload.get(f"/person-regions/{member['capture_id']}").json()["regions"][
                0
            ]["region_key"],
        }
        for member in body["members"]
    ]
    return selected


def test_concurrent_link_consent_edit_and_unlink_replay_once(upload):
    regions = linked(upload)
    body = {"request_id": str(uuid.uuid4()), "regions": regions}
    before = len(upload.rows("select * from person_region"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda _: post(upload, "/identity/subjects/link", body), range(2))
        )
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert responses[0].json() == responses[1].json()
    subject = responses[0].json()["subject_id"]
    assert len(upload.rows("select * from person_subject")) == 1
    assert len(upload.rows("select * from person_region")) == before + 2
    consent = {"request_id": str(uuid.uuid4()), "consent_scope": "likeness", "decision": "granted"}
    path = f"/person-subjects/{subject}/consents"
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        consents = list(pool.map(lambda _: post(upload, path, consent), range(2)))
    assert all(r.status_code == 201 for r in consents), [r.text for r in consents]
    assert consents[0].json() == consents[1].json()
    assert len(upload.rows("select * from person_presentation_consent")) == 1
    edit = {
        "request_id": str(uuid.uuid4()),
        "edits": [{"region_key": regions[0]["region_key"], "action": "confirm"}],
    }
    path = f"/person-regions/{regions[0]['capture_id']}/edits"
    first = post(upload, path, edit)
    assert first.status_code == 201, first.text
    assert post(upload, path, edit).json() == first.json()
    assert len(upload.rows("select * from person_region")) == before + 3
    unlink = {"request_id": str(uuid.uuid4()), "subject_id": subject, "regions": regions[:1]}
    first = post(upload, "/identity/subjects/unlink", unlink)
    assert first.status_code == 201, first.text
    assert post(upload, "/identity/subjects/unlink", unlink).json() == first.json()
    assert len(upload.rows("select * from person_region")) == before + 4


def test_status_restores_exact_original_metadata_without_original_delivery(upload):
    body = batch(upload, count=1)
    body["request_id"] = str(uuid.uuid4())
    first = post(upload, "/personal-admission", body)
    assert first.status_code == 202, first.text
    # A new authenticated request/connection has no browser cache.
    recovered = upload.get("/personal-admission").json()
    assert recovered["sources"][0]["sha256"] == body["members"][0]["sha256"]
    assert recovered["sources"][0]["bytes"] == body["members"][0]["bytes"]
    assert (
        recovered["sources"][0]["authority"]["account_authority_basis"]
        == body["authority"]["account_authority_basis"]
    )
    assert recovered["requests"][0]["batch_id"] == first.json()["batch_id"]
    assert "regions" not in recovered["requests"][0]["receipts"][0]
    assert (
        "purpose"
        not in upload.rows("select response_refs from personal_request_receipt")[0]["response_refs"]
    )


def test_failure_rolls_back_operation_and_receipt(upload):
    request = uuid.uuid4()
    with upload.database.session(upload.workspace_id) as connection:
        repository = IngestRepository(connection, upload.workspace_id)

        def fail():
            create_subject(repository, actor=actor(upload))
            raise PrivacyAdmissionError("refuse after subject insert")

        with pytest.raises(PrivacyAdmissionError, match="after subject"):
            personal_request(
                connection,
                workspace=upload.workspace_id,
                actor=actor(upload),
                request_id=request,
                operation="new-subject",
                body={},
                captures=[],
                run=fail,
            )
    assert upload.rows("select * from personal_request_receipt") == []
    assert upload.rows("select * from person_subject") == []
    assert post(upload, "/person-subjects", {"request_id": str(request)}).status_code == 201


def test_replay_rechecks_stale_screening_and_deletion_without_repeating_work(upload):
    body = reviewing(batch(upload, count=1))
    body["request_id"] = str(uuid.uuid4())
    first = post(upload, "/personal-admission", body)
    assert first.status_code == 202, first.text
    capture = body["members"][0]["capture_id"]
    assert first.json()["receipts"][0]["eligibility_state"] == "eligible"
    edit = {
        "edits": [
            {
                "action": "add",
                "region_key": "a" * 64,
                "silhouette": {"kind": "polygon", "points": [[0, 0], [100, 0], [0, 100]]},
            }
        ]
    }
    assert post(upload, f"/person-regions/{capture}/edits", edit).status_code == 201
    stale = post(upload, "/personal-admission", body)
    assert stale.status_code == 202, stale.text
    assert stale.json()["batch_id"] == first.json()["batch_id"]
    assert stale.json()["receipts"][0]["eligibility_state"] == "blocked-or-stale"
    upload.repository.insert_tombstone(
        scope="capture", capture_id=uuid.UUID(capture), requested_by=actor(upload)
    )
    assert post(upload, "/personal-admission", body).status_code == 409
    assert upload.get("/personal-admission").json()["requests"] == []
    assert upload.get("/personal-admission").json()["sources"] == []
    assert len(upload.rows("select * from personal_request_receipt")) == 1


def test_actor_workspace_isolation_and_normal_runtime_rls(upload, spine_schema):
    from exulanica.db.roles import provision_runtime_role

    from conftest import scratch_role_database

    _, scratch = spine_schema
    provision_runtime_role(upload.repository.connection)
    database = scratch_role_database(scratch, "exulanica_app")
    request = uuid.uuid4()
    actors = [uuid.uuid4(), uuid.uuid4()]
    responses = []
    for selected_actor in actors:
        with database.session(upload.workspace_id) as connection:
            repository = IngestRepository(connection, upload.workspace_id)
            responses.append(
                personal_request(
                    connection,
                    workspace=upload.workspace_id,
                    actor=selected_actor,
                    request_id=request,
                    operation="new-subject",
                    body={},
                    captures=[],
                    run=lambda repository=repository, selected_actor=selected_actor: {
                        "subject_id": str(create_subject(repository, actor=selected_actor))
                    },
                )
            )
            assert (
                len(admission_status(connection, upload.workspace_id, selected_actor)["requests"])
                == 1
            )
    assert responses[0]["subject_id"] != responses[1]["subject_id"]
    with database.session(uuid.uuid4()) as connection:
        assert connection.execute("select * from personal_request_receipt").fetchall() == []
        assert admission_status(connection, uuid.uuid4(), actors[0])["requests"] == []


def test_old_grant_replay_is_history_and_does_not_restore_withdrawn_permission(upload):
    regions = linked(upload)
    response = post(upload, "/identity/subjects/link", {"regions": regions})
    subject = response.json()["subject_id"]
    path = f"/person-subjects/{subject}/consents"
    grant = {"request_id": str(uuid.uuid4()), "consent_scope": "likeness", "decision": "granted"}
    first = post(upload, path, grant)
    assert first.status_code == 201, first.text
    assert (
        post(upload, path, {"consent_scope": "likeness", "decision": "revoked"}).status_code == 201
    )
    replay = post(upload, path, grant)
    assert replay.status_code == 201, replay.text
    assert replay.json()["consent_id"] == first.json()["consent_id"]
    assert replay.json()["receipt_only"] is True
    assert len(upload.rows("select * from person_presentation_consent")) == 2
    assert upload.get(f"/person-regions/{regions[0]['capture_id']}").json()["regions"][0]["masked"]
    assert (
        post(upload, path, {"consent_scope": "likeness", "decision": "withdrawn"}).status_code
        == 201
    )
    assert post(upload, path, grant).status_code == 409
