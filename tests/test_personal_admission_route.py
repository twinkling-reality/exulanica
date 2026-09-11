"""The authenticated personal batch uses PostgreSQL receipts and the ordinary worker."""

import datetime as dt
import uuid

import pytest
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.personal_admission import HUMAN_ATTESTATION
from exulanica.ingest.privacy import require_privacy_screening

from conftest import photo_bytes
from test_intake_upload import _TOKEN
from test_intake_upload import upload as upload


def post(upload, path, body):
    return upload.client.post(path, json=body, headers={"Authorization": f"Bearer {_TOKEN}"})


def batch(upload, count=2):
    data = [photo_bytes(when=f"2026:08:27 10:00:0{i}") for i in range(count)]
    uploaded = upload.post([("files", (f"{i}.jpg", item)) for i, item in enumerate(data)])
    assert uploaded.status_code == 202
    now = dt.datetime.now(dt.UTC)
    return {
        "operation": "detect",
        "purpose": "Inspect my photographs",
        "authority": {
            "account_authority_basis": "I own these test photographs",
            "authorized_at": (now - dt.timedelta(minutes=1)).isoformat(),
            "valid_until": (now + dt.timedelta(hours=1)).isoformat(),
        },
        "recorded_at": now.isoformat(),
        "members": [
            {"capture_id": item["capture_id"], "sha256": item["blob_sha256"], "bytes": len(source)}
            for item, source in zip(uploaded.json()["accepted"], data, strict=True)
        ],
    }


def reviewing(body):
    body.update(
        operation="review", reviewed_by_name="Fixture reviewer", attestation=HUMAN_ATTESTATION
    )
    for member in body["members"]:
        member["review"] = "no-person"
    return body


def test_batch_detection_proposes_people_before_review_and_refuses_geometry(upload):
    body = batch(upload)
    response = post(upload, "/personal-admission", body)
    assert response.status_code == 202, response.text
    receipts = response.json()["receipts"]
    for receipt in receipts:
        assert receipt["eligibility_state"] == "blocked"
        assert receipt["regions"] == []
        with pytest.raises(PrivacyAdmissionError):
            require_privacy_screening(
                upload.repository,
                uuid.UUID(receipt["capture_id"]),
                uuid.UUID(receipt["screening_id"]),
            )
    outcomes = upload.drain(screened=False)
    assert all(not result.errors for result in outcomes), outcomes
    assert upload.vision.calls == 2
    for member in body["members"]:
        regions = upload.get(f"/person-regions/{member['capture_id']}").json()["regions"]
        assert len(regions) == 1
        assert regions[0]["action"] == "detected"
        assert regions[0]["confirmed_by"] is None
    assert not upload.rows("select artifact_id from artifact where kind='point_map'")


def test_human_review_binds_named_attestation_and_exact_personal_authority(upload):
    body = reviewing(batch(upload))
    response = post(upload, "/personal-admission", body)
    assert response.status_code == 202, response.text
    for receipt in response.json()["receipts"]:
        assert receipt["eligibility_state"] == "eligible"
        require_privacy_screening(
            upload.repository, uuid.UUID(receipt["capture_id"]), uuid.UUID(receipt["screening_id"])
        )
    rows = upload.rows("select receipt_record from reconstruction_privacy_screening")
    assert len(rows) == 2
    for row in rows:
        scope = row["receipt_record"]["authorization"]["scope"]
        assert scope["reviewed_by_name"] == "Fixture reviewer"
        assert scope["human_attestation"] == HUMAN_ATTESTATION
        assert row["receipt_record"]["human_review"]["reviewed_by"]
    assert {
        row["corpus_class"]
        for row in upload.rows("select corpus_class from capture_reconstruction_authorization")
    } == {"personal"}


@pytest.mark.parametrize(
    "refusal", ["unnamed", "future", "bytes", "digest", "attestation", "actor"]
)
def test_batch_refuses_entire_inventory_before_receipts(upload, refusal):
    body = reviewing(batch(upload))
    if refusal == "unnamed":
        body["reviewed_by_name"] = "   "
    elif refusal == "future":
        body["recorded_at"] = (dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1)).isoformat()
    elif refusal == "bytes":
        body["members"][-1]["bytes"] += 1
    elif refusal == "digest":
        body["members"][-1]["sha256"] = "f" * 64
    elif refusal == "attestation":
        body["attestation"] = ""
    else:
        body["actor_id"] = str(uuid.uuid4())
    response = post(upload, "/personal-admission", body)
    assert response.status_code in {409, 422}, response.text
    assert upload.rows("select authorization_id from capture_reconstruction_authorization") == []
    assert upload.rows("select screening_id from reconstruction_privacy_screening") == []


def test_regions_across_photographs_share_subject_and_can_be_unlinked(upload):
    body = batch(upload)
    assert post(upload, "/personal-admission", body).status_code == 202
    upload.drain(screened=False)
    selected = []
    for member in body["members"]:
        regions = upload.get(f"/person-regions/{member['capture_id']}").json()["regions"]
        selected.append(
            {"capture_id": member["capture_id"], "region_key": regions[0]["region_key"]}
        )
    response = post(upload, "/identity/subjects/link", {"regions": selected})
    assert response.status_code == 201, response.text
    subject = response.json()["subject_id"]
    assert len(upload.rows("select subject_id from person_subject")) == 1
    for item in selected:
        region = upload.get(f"/person-regions/{item['capture_id']}").json()["regions"][0]
        assert region["subject_id"] == subject
        assert region["action"] == "confirmed"
    confirmation = post(
        upload,
        f"/person-regions/{selected[1]['capture_id']}/edits",
        {"edits": [{"region_key": selected[1]["region_key"], "action": "confirm"}]},
    )
    assert confirmation.status_code == 201, confirmation.text
    response = post(
        upload, "/identity/subjects/unlink", {"regions": selected[:1], "subject_id": subject}
    )
    assert response.status_code == 201, response.text
    first = upload.get(f"/person-regions/{selected[0]['capture_id']}").json()["regions"][0]
    second = upload.get(f"/person-regions/{selected[1]['capture_id']}").json()["regions"][0]
    assert first["subject_id"] is None
    assert second["subject_id"] == subject
    assert len(upload.rows("select region_edit_id from person_region")) == 6


def test_shared_subject_consent_supports_review_then_unlink_invalidates_geometry(upload):
    body = batch(upload)
    assert post(upload, "/personal-admission", body).status_code == 202
    upload.drain(screened=False)
    selected = []
    for member in body["members"]:
        regions = upload.get(f"/person-regions/{member['capture_id']}").json()["regions"]
        selected.append(
            {"capture_id": member["capture_id"], "region_key": regions[0]["region_key"]}
        )
    linked = post(upload, "/identity/subjects/link", {"regions": selected})
    assert linked.status_code == 201, linked.text
    subject = linked.json()["subject_id"]
    granted = post(
        upload,
        f"/person-subjects/{subject}/consents",
        {"consent_scope": "likeness", "decision": "granted"},
    )
    assert granted.status_code == 201, granted.text
    reviewing(body)
    body["recorded_at"] = dt.datetime.now(dt.UTC).isoformat()
    for member, item in zip(body["members"], selected, strict=True):
        member["review"] = "confirmed-regions"
        member["edits"] = [
            {"action": "confirm", "region_key": item["region_key"], "silhouette": None}
        ]
    reviewed = post(upload, "/personal-admission", body)
    assert reviewed.status_code == 202, reviewed.text
    receipts = reviewed.json()["receipts"]
    for receipt in receipts:
        require_privacy_screening(
            upload.repository, uuid.UUID(receipt["capture_id"]), uuid.UUID(receipt["screening_id"])
        )
    unlinked = post(
        upload, "/identity/subjects/unlink", {"regions": selected[:1], "subject_id": subject}
    )
    assert unlinked.status_code == 201, unlinked.text
    with pytest.raises(PrivacyAdmissionError):
        require_privacy_screening(
            upload.repository,
            uuid.UUID(receipts[0]["capture_id"]),
            uuid.UUID(receipts[0]["screening_id"]),
        )
    require_privacy_screening(
        upload.repository,
        uuid.UUID(receipts[1]["capture_id"]),
        uuid.UUID(receipts[1]["screening_id"]),
    )


def test_subject_batch_refuses_unknown_region_without_creating_subject(upload):
    body = batch(upload)
    assert post(upload, "/personal-admission", body).status_code == 202
    upload.drain(screened=False)
    capture = body["members"][0]["capture_id"]
    region = upload.get(f"/person-regions/{capture}").json()["regions"][0]
    response = post(
        upload,
        "/identity/subjects/link",
        {
            "regions": [
                {"capture_id": capture, "region_key": region["region_key"]},
                {"capture_id": body["members"][1]["capture_id"], "region_key": "f" * 64},
            ]
        },
    )
    assert response.status_code == 409, response.text
    assert upload.rows("select subject_id from person_subject") == []
    assert all(
        row["action"] == "detected" for row in upload.rows("select action from person_region")
    )


def test_duplicate_region_edits_refuse_atomically_before_subject_can_be_lost(upload):
    body = batch(upload, count=1)
    capture = body["members"][0]["capture_id"]
    subject = post(upload, "/person-subjects", {}).json()["subject_id"]
    response = post(
        upload,
        f"/person-regions/{capture}/edits",
        {
            "edits": [
                {
                    "action": "add",
                    "region_key": "a" * 64,
                    "subject_id": subject,
                    "silhouette": {
                        "kind": "polygon",
                        "points": [[0, 0], [500000, 0], [500000, 500000]],
                    },
                },
                {"action": "confirm", "region_key": "a" * 64},
            ]
        },
    )
    assert response.status_code == 409, response.text
    assert "exactly once" in response.json()["detail"]
    assert upload.get(f"/person-regions/{capture}").json()["regions"] == []
