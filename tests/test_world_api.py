"""HTTP contract for adaptive-world preview, concurrency, rollback, and source states."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import TopologyContract, TopologySourceSlot, WorldStyleRepository
from fastapi.testclient import TestClient

from conftest import write_photo

pytestmark = pytest.mark.postgres

TOKEN = "world-owner-token-long-enough-for-tests"
STRANGER_TOKEN = "world-stranger-token-long-enough-for-tests"


@dataclass
class WorldApi:
    client: TestClient
    actor: uuid.UUID
    source_id: uuid.UUID

    @property
    def headers(self):
        return {"Authorization": f"Bearer {TOKEN}"}

    def get(self, path):
        return self.client.get(path, headers=self.headers)

    def stranger_get(self, path):
        return self.client.get(path, headers={"Authorization": f"Bearer {STRANGER_TOKEN}"})

    def post(self, path, body):
        return self.client.post(path, headers=self.headers, json=body)

    def delete(self, path):
        return self.client.delete(path, headers=self.headers)

    def current(self):
        return self.get("/world/styles/current").json()

    def preview_body(self, **overrides):
        current = self.current()
        body = {
            "proposal_id": str(uuid.uuid4()),
            "origin": "settings",
            "origin_reference": "appearance-panel",
            "scope": {"kind": "global"},
            "base_style_version_id": current["current"]["version_id"],
            "base_topology_digest": current["current_topology_digest"],
            "profile": {
                "profile_id": "origin-landscape",
                "profile_version": 1,
                "parameters": {"vitality": 0.25},
            },
        }
        body.update(overrides)
        return body


@pytest.fixture
def world_api(repository, spine_schema, tmp_path, monkeypatch):
    _psycopg, scratch = spine_schema
    actor = uuid.uuid4()
    stranger = uuid.uuid4()
    source_id = uuid.uuid4()
    styles = WorldStyleRepository(repository.connection, repository.workspace_id)
    styles.register_topology(
        TopologyContract(
            "api-topology",
            ("region-a",),
            (
                TopologySourceSlot(
                    source_id=source_id,
                    region_id="region-a",
                    slot_key="hero-memory",
                    evidence_span_id=None,
                    missing_reason="no evidence was recorded",
                ),
            ),
        )
    )
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {"workspace_id": str(repository.workspace_id), "actor": str(actor)},
                STRANGER_TOKEN: {
                    "workspace_id": str(stranger),
                    "actor": str(uuid.uuid4()),
                },
            }
        ),
    )
    from tests_support_api import scratch_database

    database = scratch_database(scratch)
    with database.session(stranger) as connection:
        WorldStyleRepository(connection, stranger).register_topology(
            TopologyContract("stranger-topology", ("region-a",))
        )
    services = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path / "blobs"),
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    with TestClient(create_app(services, verify=False)) as client:
        yield WorldApi(client, actor, source_id)


def test_catalog_and_current_state_expose_references_not_renderer_programs(world_api):
    catalog = world_api.get("/world/styles/catalog")
    assert catalog.status_code == 200
    contract = catalog.json()
    assert contract["schemaVersion"] == 1
    assert contract["defaultProfile"]["profileId"] == "origin-landscape"
    aeroheart = next(
        value for value in contract["profiles"] if value["profileId"] == "origin-landscape"
    )
    assert aeroheart["recipeBinding"]["modules"] == [
        "aeroheart-optics-v1",
        "registered-surface-v1",
        "bounded-tempo-v1",
        "source-light-v1",
    ]
    text = catalog.text.lower()
    for forbidden in ("javascript", '"css"', '"shader"', '"layout"', "https://"):
        assert forbidden not in text

    state = world_api.current()
    assert state["current_topology_digest"] == "api-topology"
    assert state["current"]["revision"] == 0
    assert state["current"]["global_style"]["profile_id"] == "origin-landscape"


def test_settings_and_companion_share_the_reviewed_interaction_policy_lifecycle(world_api):
    initial = world_api.get("/world/interactions/current")
    assert initial.status_code == 200, initial.text
    base = initial.json()
    assert base["current"] is None
    assert base["parameters"]["comfort.field-of-view-degrees"] == 70

    proposal_id = uuid.uuid4()
    preview = world_api.post(
        "/world/interactions/previews",
        {
            "proposal_id": str(proposal_id),
            "origin": "settings",
            "origin_reference": "options-panel",
            "base_policy_version_id": None,
            "base_structure_snapshot_id": base["base_structure_snapshot_id"],
            "base_topology_sha256": base["base_topology_sha256"],
            "capability_patch": {"comfort.field-of-view-degrees": 82},
            "proposal_input": {"control_ids": ["fieldOfView"]},
            "explanation": "Apply the field-of-view choice made in Settings.",
        },
    )
    assert preview.status_code == 201, preview.text
    assert preview.json()["candidate_parameters"]["comfort.field-of-view-degrees"] == 82

    applied = world_api.post(
        f"/world/interactions/previews/{preview.json()['preview_id']}/apply",
        {
            "base_policy_version_id": None,
            "base_structure_snapshot_id": base["base_structure_snapshot_id"],
            "base_topology_sha256": base["base_topology_sha256"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["revision"] == 0

    inspected = world_api.get(f"/world/interactions/proposals/{proposal_id}")
    assert inspected.status_code == 200
    assert inspected.json()["status"] == "applied"
    assert inspected.json()["proposal_input"] == {"control_ids": ["fieldOfView"]}

    companion_without_provenance = world_api.post(
        "/world/interactions/previews",
        {
            "proposal_id": str(uuid.uuid4()),
            "origin": "companion",
            "origin_reference": "companion-settings-suggestion",
            "base_policy_version_id": applied.json()["version_id"],
            "base_structure_snapshot_id": base["base_structure_snapshot_id"],
            "base_topology_sha256": base["base_topology_sha256"],
            "capability_patch": {"initiative.mode": "minimal"},
            "proposal_input": {"observed_choice": "skip"},
            "explanation": "Offer less initiative after explicit skips.",
            "reference_ids": ["interaction-event:skip-1"],
        },
    )
    assert companion_without_provenance.status_code == 422
    assert companion_without_provenance.json()["code"] == "invalid_interaction_data"


def test_preview_apply_discard_and_rollback_are_visible_as_immutable_versions(world_api):
    initial = world_api.current()
    preview = world_api.post("/world/styles/previews", world_api.preview_body())
    assert preview.status_code == 201, preview.text
    assert world_api.current()["current"]["version_id"] == initial["current"]["version_id"]

    applied = world_api.post(
        f"/world/styles/previews/{preview.json()['preview_id']}/apply",
        {
            "base_style_version_id": initial["current"]["version_id"],
            "base_topology_digest": "api-topology",
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["revision"] == 1
    assert applied.json()["provenance"] == {
        "origin": "settings",
        "actor": str(world_api.actor),
        "origin_reference": "appearance-panel",
    }

    second = world_api.post("/world/styles/previews", world_api.preview_body())
    assert second.status_code == 201
    discarded = world_api.delete(f"/world/styles/previews/{second.json()['preview_id']}")
    assert discarded.status_code == 204
    assert world_api.current()["current"]["version_id"] == applied.json()["version_id"]

    rolled_back = world_api.post(
        "/world/styles/rollback",
        {
            "target_version_id": initial["current"]["version_id"],
            "base_style_version_id": applied.json()["version_id"],
            "base_topology_digest": "api-topology",
            "origin": "user",
        },
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["revision"] == 2
    assert rolled_back.json()["rollback_target_version_id"] == initial["current"]["version_id"]
    assert [version["revision"] for version in world_api.get("/world/styles/versions").json()] == [
        0,
        1,
        2,
    ]


def test_companion_recipe_proposals_preserve_provenance_and_refinement(world_api):
    initial = world_api.current()
    missing_provenance = world_api.preview_body(
        origin="companion", origin_reference="conversation:17"
    )
    response = world_api.post("/world/styles/previews", missing_provenance)
    assert (response.status_code, response.json()["code"]) == (422, "invalid_style_data")

    draft_id = uuid.uuid4()
    draft_body = world_api.preview_body(
        proposal_id=str(draft_id),
        origin="companion",
        origin_reference="conversation:17",
        model_id="style-proposer/v3",
        prompt_version="world-recipe/v2",
        reference_ids=["design-reference:light-study"],
    )
    draft = world_api.post("/world/styles/previews", draft_body)
    assert draft.status_code == 201, draft.text

    refined_id = uuid.uuid4()
    refined_body = world_api.preview_body(
        proposal_id=str(refined_id),
        origin="companion",
        origin_reference="conversation:18",
        model_id="style-proposer/v3",
        prompt_version="world-recipe/v2",
        reference_ids=["design-reference:light-study"],
        refines_proposal_id=str(draft_id),
        profile={
            "profile_id": "origin-landscape",
            "profile_version": 1,
            "parameters": {"vitality": 0.4, "surface-finish": "clear-lens"},
        },
    )
    refined = world_api.post("/world/styles/previews", refined_body)
    assert refined.status_code == 201, refined.text
    inspected = world_api.get(f"/world/styles/proposals/{refined_id}")
    assert inspected.status_code == 200
    record = inspected.json()
    assert record["status"] == "previewed"
    assert record["refines_proposal_id"] == str(draft_id)
    assert record["model_id"] == "style-proposer/v3"
    assert record["prompt_version"] == "world-recipe/v2"
    assert record["reference_ids"] == ["design-reference:light-study"]
    assert record["recipe_binding"]["modules"] == [
        "aeroheart-optics-v1",
        "registered-surface-v1",
        "bounded-tempo-v1",
        "source-light-v1",
    ]
    assert record["capability_mapping"]["surface-finish"] == "surface.finish"

    discarded = world_api.delete(f"/world/styles/previews/{draft.json()['preview_id']}")
    assert discarded.status_code == 204
    applied = world_api.post(
        f"/world/styles/previews/{refined.json()['preview_id']}/apply",
        {
            "base_style_version_id": initial["current"]["version_id"],
            "base_topology_digest": "api-topology",
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["model_id"] == "style-proposer/v3"
    assert applied.json()["refines_proposal_id"] == str(draft_id)
    assert world_api.get(f"/world/styles/proposals/{refined_id}").json()["status"] == "applied"


def test_frontend_camel_case_proposal_translates_to_the_backend_authority(world_api):
    current = world_api.current()
    response = world_api.post(
        "/world/styles/previews",
        {
            "proposalId": str(uuid.uuid4()),
            "origin": "settings",
            "originReference": "atlas-options",
            "scope": {"kind": "global"},
            "baseStyleVersionId": current["current"]["version_id"],
            "baseTopologyDigest": current["current_topology_digest"],
            "profile": {
                "profileId": "origin-landscape",
                "profileVersion": 1,
                "parameters": {"surface-finish": "clear-lens"},
            },
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["candidate"]["recipe_binding"]["profileId"] == "origin-landscape"


def test_style_topology_and_asset_failures_have_distinct_problem_codes(world_api):
    current = world_api.current()

    invalid = world_api.preview_body()
    invalid["profile"]["parameters"] = {"css": "body { display:none }"}
    response = world_api.post("/world/styles/previews", invalid)
    assert (response.status_code, response.json()["code"]) == (422, "invalid_style_data")

    unknown_version = world_api.preview_body()
    unknown_version["profile"]["profile_version"] = 2
    response = world_api.post("/world/styles/previews", unknown_version)
    assert (response.status_code, response.json()["code"]) == (422, "invalid_style_data")

    stale = world_api.preview_body(base_style_version_id=str(uuid.uuid4()))
    response = world_api.post("/world/styles/previews", stale)
    assert (response.status_code, response.json()["code"]) == (409, "stale_style_version")

    topology = world_api.preview_body(base_topology_digest="old-topology")
    response = world_api.post("/world/styles/previews", topology)
    assert (response.status_code, response.json()["code"]) == (
        409,
        "protected_topology_conflict",
    )

    missing = world_api.get(f"/world/source-media/{world_api.source_id}")
    assert (missing.status_code, missing.json()["code"]) == (424, "unavailable_asset")

    unknown = world_api.get(f"/world/source-media/{uuid.uuid4()}")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "unknown_reference")
    assert current["current"]["revision"] == 0


def test_source_listing_preserves_missing_evidence_instead_of_inventing_an_asset(world_api):
    response = world_api.get("/world/source-media")
    assert response.status_code == 200
    assert response.json() == [
        {
            "source_id": str(world_api.source_id),
            "slot_key": "hero-memory",
            "region_id": "region-a",
            "state": "missing_evidence",
            "reason": "no evidence was recorded",
            "evidence_span_id": None,
            "evidence_path": None,
            "modality": None,
            "media_type": None,
            "byte_size": None,
            "width": None,
            "height": None,
            "captured_at": None,
            "captured_at_uncertainty_ms": None,
            "asset_reference": None,
            "capture_ids": [],
        }
    ]


def test_source_metadata_is_workspace_authorised_without_becoming_an_existence_oracle(world_api):
    real = world_api.stranger_get(f"/world/source-media/{world_api.source_id}")
    invented = world_api.stranger_get(f"/world/source-media/{uuid.uuid4()}")
    assert real.status_code == invented.status_code == 404
    assert (
        real.json()
        == invented.json()
        == {
            "code": "unknown_reference",
            "detail": "no such world resource",
        }
    )


def test_the_request_cannot_choose_the_audit_actor(world_api):
    body = world_api.preview_body(actor=str(uuid.uuid4()))
    response = world_api.post("/world/styles/previews", body)
    assert response.status_code == 422


def test_pending_mask_keeps_review_identity_without_a_byte_reference(
    world_api, repository, tmp_path, photo_dir
):
    store = LocalContentAddressedStore(tmp_path / "blobs")
    outcome = PhotoIngestPipeline(repository, store, vision=None).ingest_file(
        write_photo(photo_dir, "generated-review.jpg")
    )
    assert outcome.error is None
    capture_id = outcome.capture_id
    span_id = repository.connection.execute(
        "select span_id from evidence_span where workspace_id=%s and region is null "
        "and modality='still_image' order by created_at limit 1",
        (repository.workspace_id,),
    ).fetchone()["span_id"]
    source_id = uuid.uuid4()
    WorldStyleRepository(repository.connection, repository.workspace_id).register_topology(
        TopologyContract("manual-review-mask-pending", ("region-a",), (
            TopologySourceSlot(source_id, "generated-review", "region-a", span_id, None),
        ))
    )
    added = world_api.post(f"/person-regions/{capture_id}/edits", {"edits": [{
        "region_key": "ab" * 32, "action": "add", "shape": "box",
        "silhouette": {"kind": "polygon", "points": [
            [100000, 100000], [400000, 100000], [400000, 800000], [100000, 800000],
        ]},
    }]})
    assert added.status_code == 201, added.text
    [pending] = world_api.get("/world/source-media").json()
    assert pending["capture_ids"] == [str(capture_id)]
    assert pending["state"] == "unavailable_asset"
    assert pending["evidence_path"] is None
    assert pending["asset_reference"] is None
    assert world_api.get(f"/world/source-media/{source_id}").status_code == 424
    assert world_api.get(f"/evidence/{span_id}/masked").status_code == 409
    assert world_api.get(f"/person-regions/{capture_id}").json()["regions"][0]["masked"]
    assert world_api.stranger_get("/world/source-media").json() == []
    assert world_api.stranger_get(f"/world/source-media/{source_id}").status_code == 404
    assert world_api.stranger_get(f"/person-regions/{capture_id}").status_code == 404
    repository.insert_tombstone(
        scope="capture", capture_id=capture_id, requested_by=world_api.actor,
        reason="remove generated review fixture",
    )
    [deleted] = world_api.get("/world/source-media").json()
    assert deleted["capture_ids"] == []
    assert deleted["evidence_path"] is None
    assert deleted["asset_reference"] is None
