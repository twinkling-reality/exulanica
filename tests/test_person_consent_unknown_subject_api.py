"""Actual PostgreSQL HTTP refusals for foreign and invented person-subject UUIDs."""

import uuid

import pytest

import test_world_objects_api as object_helpers

objects_api = object_helpers.objects_api
pytestmark = pytest.mark.postgres


def recorded_rows(connection):
    return {
        table: connection.execute(f"select * from {table} order by 1,2").fetchall()
        for table in ("person_presentation_consent", "personal_request_receipt", "person_subject")
    }


@pytest.mark.parametrize("idempotent", [False, True])
def test_foreign_and_invented_subjects_return_same_404_without_consent_writes(
    objects_api,
    repository,
    idempotent,
):
    api = objects_api
    own = api.post("/person-subjects", {})
    foreign = api.stranger_post("/person-subjects", {})
    assert own.status_code == foreign.status_code == 201
    own_id, foreign_id = own.json()["subject_id"], foreign.json()["subject_id"]
    valid = {"consent_scope": "presence", "decision": "granted"}
    owner_receipt = api.post(f"/person-subjects/{own_id}/consents", valid)
    foreign_receipt = api.stranger_post(f"/person-subjects/{foreign_id}/consents", valid)
    assert owner_receipt.status_code == foreign_receipt.status_code == 201
    assert owner_receipt.json()["actor_role"] == foreign_receipt.json()["actor_role"] == "owner"
    before = recorded_rows(repository.connection)
    assert len(before["person_presentation_consent"]) == 2
    results = []
    for subject in (foreign_id, str(uuid.uuid4())):
        body = valid | ({"request_id": str(uuid.uuid4())} if idempotent else {})
        response = api.post(f"/person-subjects/{subject}/consents", body)
        assert response.status_code == 404, response.text
        results.append(response.json())
        assert recorded_rows(repository.connection) == before
        if idempotent:
            assert api.post(f"/person-subjects/{subject}/consents", body).json() == response.json()
    assert (
        results[0]
        == results[1]
        == {
            "code": "unknown_reference",
            "detail": "no such person subject",
        }
    )
    # The reverse foreign workspace access has exactly the same unavailable response.
    reverse = api.stranger_post(f"/person-subjects/{own_id}/consents", valid)
    assert reverse.status_code == 404 and reverse.json() == results[0]
    assert recorded_rows(repository.connection) == before
    assert api.client.post(f"/person-subjects/{own_id}/consents", json=valid).status_code == 401


def test_owned_subject_idempotent_consent_retains_actor_and_replay_semantics(
    objects_api, repository
):
    api = objects_api
    response = api.post("/person-subjects", {})
    assert response.status_code == 201
    subject_id = response.json()["subject_id"]
    route = f"/person-subjects/{subject_id}/consents"
    body = {"consent_scope": "presence", "decision": "granted", "request_id": str(uuid.uuid4())}
    first = api.post(route, body)
    assert first.status_code == 201, first.text
    assert first.json()["actor_role"] == "owner"
    before = recorded_rows(repository.connection)
    replay = api.post(route, body)
    assert replay.status_code == 201 and replay.json() == first.json()
    assert recorded_rows(repository.connection) == before
    consent = before["person_presentation_consent"][0]
    assert consent["actor_id"] == api.actor and consent["actor_role"] == "owner"
    assert api.post(route, body | {"decision": "revoked"}).status_code == 409
    assert api.post(route, body | {"actor_role": "subject"}).status_code == 422
    assert recorded_rows(repository.connection) == before
