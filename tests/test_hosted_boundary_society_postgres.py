"""The society runtime sends a decision through the workspace's policy, never around it.

``tests/test_hosted_boundary.py`` runs the society decision path with the policy attached the way
the runtime attaches it. This runs the runtime itself, over the authenticated society fixture,
with a provider whose client carries no policy at all: a request can only leave if
``request_decision`` attached the workspace's.
"""

from __future__ import annotations

import pytest
from exulanica.epistemics.hosted_requests import WorkspaceRequestPolicy
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role

import test_world_objects_api as object_helpers
from test_society_social_postgres import provider_for, social

objects_api = object_helpers.objects_api
pytestmark = pytest.mark.postgres

__all__ = ["objects_api", "social"]


def test_a_society_decision_leaves_only_through_the_workspace_policy(
    social, repository, transport, manifest, monkeypatch
):
    api, _, _, route, _, _, body = social
    admitted: list[tuple[object, Role]] = []
    original = WorkspaceRequestPolicy.admit

    def admit(self, request):
        texts = original(self, request)
        admitted.append((self.workspace_id, request.role))
        return texts

    monkeypatch.setattr(WorkspaceRequestPolicy, "admit", admit)
    # The process's client, with no policy: only the runtime's attachment lets it send.
    client = ModelClient(api_key="test-key-not-real", manifest=manifest, transport=transport)
    api.client.app.state.society_decision_provider = provider_for(client, transport, manifest)

    response = api.post(api.in_world(route + "/decisions"), body)

    assert response.status_code == 200, response.text
    assert response.json()["decision"]["status"] == "accepted", response.text
    assert len(transport.requests) == 1
    assert admitted == [(repository.workspace_id, Role.REASONING_CHEAP)]
