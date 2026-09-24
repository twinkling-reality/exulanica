"""A society decision releases no place's name, whatever the account holder allowed for a role.

A society decision is sent on whatever role its host configures, and the place-name right is
granted per role. The runtime therefore attaches the workspace's policy with the resolver that
releases nothing (``exulanica/api/society_decision_runtime.py``): a grant the account holder made
for the Companion's composer describes the Companion's requests, never a simulated inhabitant's.
This runs the runtime itself over the authenticated society fixture, with the instance's real
resolver configured and the composer's role allowed for a place whose saved name the decision's
context carries.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace

import pytest
from exulanica.consent.place_name_rights import grant_place_name, released_place_names
from exulanica.consent.place_names import load_place_name_uses
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository, name_occurrence
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role, load_manifest
from exulanica.store.local import LocalContentAddressedStore

import test_world_objects_api as object_helpers
from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, write_photo
from test_society_social_postgres import provider_for, social

objects_api = object_helpers.objects_api
pytestmark = pytest.mark.postgres

__all__ = ["objects_api", "social"]

#: A word the fixture's decision context carries, in its authored target's identifiers, saved here
#: as a place's name so the request's text holds a saved place.
PLACE = "new-marker"


def _save_place(repository, tmp_path, photo_dir) -> tuple[uuid.UUID, uuid.UUID]:
    """A place named through the product's naming path, and the account holder who named it."""
    pipeline = PhotoIngestPipeline(
        repository,
        LocalContentAddressedStore(tmp_path / "society-place-blobs"),
        vision=CountingVisionModel(payload=json.loads(json.dumps(DEFAULT_PAYLOAD))),
    )
    outcome = ingest_observed(
        pipeline, repository, write_photo(photo_dir, "marker.jpg", when="2026:08:28 08:00:00")
    )
    assert outcome.error is None, outcome.error
    occurrence = repository.connection.execute(
        "select occurrence_id from occurrence where workspace_id=%s and capture_id=%s "
        "and class='place'",
        (repository.workspace_id, outcome.capture_id),
    ).fetchone()
    actor = uuid.uuid4()
    place = name_occurrence(
        IdentityRepository(repository.connection, repository.workspace_id),
        AssertionWriter(repository.connection, repository.workspace_id),
        occurrence_id=occurrence["occurrence_id"],
        display_name=PLACE,
        actor=actor,
    ).entity_id
    return place, actor


def test_a_decision_carries_no_place_allowed_for_the_composer(
    social, repository, transport, manifest, tmp_path, photo_dir
):
    api, _, _, route, _, _, body = social
    place, namer = _save_place(repository, tmp_path, photo_dir)
    uses = load_place_name_uses()
    use = uses.use(Role.REASONING_CHEAP.value)
    assert use is not None, "the composer's role is not offered, so nothing here is allowed"
    grant_place_name(
        repository.connection,
        repository.workspace_id,
        entity_id=place,
        role=use.role.value,
        notice=uses.notice(use, uses.handoff(use, load_manifest())),
        actor=namer,
    )
    repository.connection.commit()
    services = api.client.app.state.services
    api.client.app.state.services = replace(services, released_place_names=released_place_names)
    # Positive control: the instance's resolver does release the place to the decision's role.
    handoff = uses.handoff(use, manifest)
    assert released_place_names(repository.connection, repository.workspace_id, handoff) == {place}
    client = ModelClient(api_key="test-key-not-real", manifest=manifest, transport=transport)
    api.client.app.state.society_decision_provider = provider_for(client, transport, manifest)

    response = api.post(route + "/decisions", body)

    assert response.status_code == 200, response.text
    assert response.json()["decision"]["status"] == "accepted", response.text
    (request,) = transport.requests
    (context,) = [m["content"] for m in request["payload"]["messages"] if m["role"] == "user"]
    assert PLACE not in context, "a society decision carried a place's allowed name"
    assert "[place A]" in context, "the context carried no saved place, so this shows nothing"
