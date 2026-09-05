"""Human benchmark review is authenticated, source-exact and atomic; no real receipts here."""

import datetime as dt
import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.canonical import sha256_of_canonical
from exulanica.ingest.reference_admission import HUMAN_ATTESTATION
from exulanica.store.local import LocalContentAddressedStore
from fastapi.testclient import TestClient

from conftest import photo_bytes
from tests_support_api import scratch_database

TOKEN = "reference-admission-synthetic-test-token-0001"
ACTOR = uuid.UUID("8dbf7c37-7f3c-4703-8bc3-722ed38e3950")


@pytest.fixture
def reviewed_api(tmp_path, repository, spine_schema, monkeypatch):
    _, scratch = spine_schema
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps({TOKEN: {"workspace_id": str(repository.workspace_id), "actor": str(ACTOR)}}),
    )
    database = scratch_database(scratch)
    services = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path / "blobs"),
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    with TestClient(create_app(services, verify=False)) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        result = client.post(
            "/intake",
            headers=headers,
            files=[
                ("files", ("one.jpg", photo_bytes(), "image/jpeg")),
                ("files", ("two.jpg", photo_bytes(size=(162, 102)), "image/jpeg")),
            ],
        )
        assert result.status_code == 202, result.text
        body = {
            "members": [
                {"capture_id": row["capture_id"], "source_sha256": row["blob_sha256"]}
                for row in result.json()["accepted"]
            ],
            "source_manifest_sha256": "ab" * 32,
            "official_source_url": "https://example.org/synthetic-test-only",
            "retrieval_date": "2026-09-05",
            "license_document_sha256": "cd" * 32,
            "permitted_use": "Synthetic automated test; not a real license or human receipt",
            "reviewed_by_name": "SIMULATED TEST HUMAN",
            "reviewed_at": dt.datetime.now(dt.UTC).isoformat(),
            "attestation": HUMAN_ATTESTATION,
        }
        body["source_manifest"] = {
            "profile": "exulanica.reference-inputs/v1",
            "corpus_class": "benchmark",
            "retrieval_date": body["retrieval_date"],
            "official_source_url": body["official_source_url"],
            "license": {"document_sha256": body["license_document_sha256"]},
            "files": [{"sha256": row["source_sha256"]} for row in body["members"]],
            "evaluation_split": {
                "training_sha256": [body["members"][0]["source_sha256"]],
                "heldout_sha256": [body["members"][1]["source_sha256"]],
            },
        }
        body["source_manifest_sha256"] = sha256_of_canonical(body["source_manifest"]).hex()
        yield client, headers, body, repository


def test_review_needs_session_and_never_accepts_client_actor(reviewed_api):
    client, headers, body, _ = reviewed_api
    assert client.post("/operations/reconstruction-admission", json=body).status_code == 401
    for forbidden in ("actor", "workspace_id"):
        response = client.post(
            "/operations/reconstruction-admission",
            headers=headers,
            json={**body, forbidden: str(uuid.uuid4())},
        )
        assert response.status_code == 422


def test_review_refuses_missing_attestation_and_changed_or_foreign_capture_atomically(reviewed_api):
    client, headers, body, repository = reviewed_api
    for replacement in (
        {"attestation": ""},
        {"reviewed_by_name": " "},
        {"attestation": "An AI inspected the images"},
        {"reviewed_at": (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).isoformat()},
    ):
        assert client.post(
            "/operations/reconstruction-admission", headers=headers, json={**body, **replacement}
        ).status_code in (409, 422)
    for replacement in ({"source_sha256": "ff" * 32}, {"capture_id": str(uuid.uuid4())}):
        altered = json.loads(json.dumps(body))
        altered["members"][-1].update(replacement)
        result = client.post("/operations/reconstruction-admission", headers=headers, json=altered)
        assert result.status_code == 409, result.text
    for altered in (
        {**body, "members": body["members"][:1]},
        {**body, "source_manifest_sha256": "ff" * 32},
    ):
        assert (
            client.post(
                "/operations/reconstruction-admission", headers=headers, json=altered
            ).status_code
            == 409
        )
    for change in ("changed_bytes", "personal_corpus", "different_date", "overlapping_split"):
        altered = json.loads(json.dumps(body))
        manifest = altered["source_manifest"]
        if change == "changed_bytes":
            altered["members"][-1]["source_sha256"] = "ff" * 32
            manifest["files"][-1]["sha256"] = "ff" * 32
            manifest["evaluation_split"]["heldout_sha256"] = ["ff" * 32]
        elif change == "personal_corpus":
            manifest["corpus_class"] = "personal"
        elif change == "different_date":
            manifest["retrieval_date"] = "2026-09-04"
        else:
            manifest["evaluation_split"]["heldout_sha256"].append(
                manifest["evaluation_split"]["training_sha256"][0]
            )
        altered["source_manifest_sha256"] = sha256_of_canonical(manifest).hex()
        response = client.post(
            "/operations/reconstruction-admission", headers=headers, json=altered
        )
        assert response.status_code == 409, (change, response.text)
    assert (
        repository.connection.execute(
            "select count(*) as n from capture_reconstruction_authorization where workspace_id=%s",
            (repository.workspace_id,),
        ).fetchone()["n"]
        == 0
    )


def test_exact_review_writes_existing_receipts_and_queues_only_capture_ids(reviewed_api):
    client, headers, body, repository = reviewed_api
    response = client.post("/operations/reconstruction-admission", headers=headers, json=body)
    assert response.status_code == 202, response.text
    result = response.json()
    assert len(result["receipts"]) == 2
    for receipt in result["receipts"]:
        screening = repository.privacy_screening(uuid.UUID(receipt["screening_id"]))
        row = repository.connection.execute(
            "select reviewed_by from reconstruction_privacy_screening where screening_id=%s",
            (screening.screening_id,),
        ).fetchone()
        assert row["reviewed_by"] == ACTOR
        assert screening.corpus_class == "benchmark"
        assert screening.eligibility_state == "eligible"
        assert (
            screening.authorization_scope["source_manifest_sha256"]
            == body["source_manifest_sha256"]
        )
        assert repository.privacy_screening_allows(screening.capture_id, screening.screening_id)
        assert screening.authorization_scope["source_manifest"] == body["source_manifest"]
    job = repository.connection.execute(
        "select payload from job where job_id=%s", (uuid.UUID(result["queued_job_id"]),)
    ).fetchone()
    assert set(job["payload"]["capture_ids"]) == {row["capture_id"] for row in body["members"]}
    assert all(row["source_sha256"] not in json.dumps(job["payload"]) for row in body["members"])
