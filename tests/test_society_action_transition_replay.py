"""Exact database transition binding and deterministic replay for directed actions."""

from __future__ import annotations

import uuid

import pytest

from test_society_actions_postgres import (
    action_repository,
    action_world,
    create_action,
    create_society,
    society_repository,
)

pytestmark = pytest.mark.postgres
__all__ = ["action_world"]


@pytest.mark.parametrize("profile", ["exulanica-society/v2", "exulanica-society/v3"])
def test_normal_step_binds_exact_action_event_and_replays_from_genesis(action_world, profile):
    world = action_world
    snapshot, document = create_society(world, profile)
    envelope, _subject = create_action(world, snapshot, document["targets"][0])
    actions = action_repository(world)
    version_id = world["version"].version_id

    result = society_repository(world).advance(
        version_id,
        base_tick=snapshot["current_tick"],
        base_state_sha256=snapshot["state_sha256"],
    )

    consumed = actions.read(version_id, uuid.UUID(envelope["request"]["request_id"]))
    assert consumed["status"] == "consumed"
    assert consumed["consumption"] == {"tick": 1, "disposition": "applied"}
    binding = (
        world["connection"]
        .execute(
            "select binding.action_seq,binding.tick,binding.disposition,binding.event_id,"
            "event.document from world_society_transition_action binding "
            "join world_society_event event using(workspace_id,society_id,event_id) "
            "where binding.workspace_id=%s and binding.society_id=%s",
            (world["workspace"], snapshot["society_id"]),
        )
        .fetchone()
    )
    assert binding["action_seq"] == 1
    assert binding["document"]["action_request_id"] == envelope["request"]["request_id"]
    assert binding["document"]["action_request_sha256"] == envelope["request"]["document_sha256"]
    assert binding["document"]["disposition"] == binding["disposition"] == "applied"
    transition = (
        world["connection"]
        .execute(
            "select event_ids from world_society_transition "
            "where workspace_id=%s and society_id=%s and tick=%s",
            (world["workspace"], snapshot["society_id"], binding["tick"]),
        )
        .fetchone()
    )
    assert str(binding["event_id"]) in transition["event_ids"]
    replayed = society_repository(world).replay(version_id)
    assert replayed["replay_verified"] and replayed["state"] == result["state"]
