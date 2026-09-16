"""PG18 evidence for action audit, authorization, concurrency and isolation."""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.society import StaleSocietyState, UnavailableSocietyInput, UnknownSociety
from exulanica.world.society_action_repository import SocietyActionRepository
from exulanica.world.society_actions import ActionIntent, action_goal_policies
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.structure_repository import WorldStructureRepository
from psycopg.errors import CheckViolation
from psycopg.types.json import Jsonb

from society_fixtures import SEED, edited, seal, society_input
from world_structure_fixtures import structural_candidate

pytestmark = pytest.mark.postgres


@pytest.fixture
def action_world(repository):
    connection = repository.connection
    workspace = repository.workspace_id
    actor = uuid.uuid4()
    structures = WorldStructureRepository(connection, workspace)
    preview = structures.preview(structural_candidate(), proposed_by=actor)
    snapshot = structures.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=actor,
    )
    version = WorldObjectRepository(connection, workspace).create_version(
        source_snapshot_id=snapshot.snapshot_id,
        title="Synthetic society action fixture",
        created_by=actor,
    )
    place = uuid.uuid4()
    connection.execute("insert into place(workspace_id,place_id) values(%s,%s)", (workspace, place))
    rights = {"withdrawn": False}

    def authorize(document):
        if rights["withdrawn"] and document["availability"] == "available":
            raise UnavailableSocietyInput("fixture source withdrawn")

    return {
        "connection": connection,
        "workspace": workspace,
        "actor": actor,
        "version": version,
        "place": place,
        "rights": rights,
        "authorize": authorize,
    }


def society_repository(world):
    return SocietyRepository(
        world["connection"], world["workspace"], input_authorizer=world["authorize"]
    )


def action_repository(world, workspace=None):
    return SocietyActionRepository(
        world["connection"],
        workspace or world["workspace"],
        input_authorizer=world["authorize"],
    )


def create_society(world, profile="exulanica-society/v2"):
    document = society_input(world["version"].version_id)
    society = society_repository(world).create(
        world["version"].version_id,
        place_id=world["place"],
        region_id="region-a",
        seed=SEED,
        actor=world["actor"],
        profile=profile,
        initial_input=document,
    )
    return society, document


def create_action(world, society, target, *, request_id=None, base_tick=None):
    subject = uuid.UUID(society["state"]["inhabitants"][0]["id"])
    envelope = action_repository(world).create(
        world["version"].version_id,
        request_id=request_id or uuid.uuid4(),
        requested_by=world["actor"],
        subject_id=subject,
        base_tick=society["current_tick"] if base_tick is None else base_tick,
        base_state_sha256=society["state_sha256"],
        intent=ActionIntent("perform", target["target_id"], target["affordance"]),
    )
    return envelope, subject


@pytest.mark.parametrize("profile", ["exulanica-society/v2", "exulanica-society/v3"])
def test_v2_v3_request_is_immutable_idempotent_and_ready_for_exact_step(action_world, profile):
    world = action_world
    society, document = create_society(world, profile)
    target = document["targets"][0]
    request_id = uuid.uuid4()
    envelope, subject = create_action(world, society, target, request_id=request_id)
    assert envelope["status"] == "pending" and envelope["consumption"] is None
    assert envelope["request"]["target"] == target
    assert envelope["request"]["requested_by"] == str(world["actor"])
    assert action_repository(world).read(world["version"].version_id, request_id) == envelope
    assert action_repository(world).history(world["version"].version_id) == (envelope,)
    retry, _ = create_action(world, society, target, request_id=request_id)
    assert retry == envelope
    pending = action_repository(world).pending_for_step(
        world["version"].version_id,
        base_tick=society["current_tick"],
        base_state_sha256=society["state_sha256"],
    )
    policies, dispositions = action_goal_policies(society["state"], document, list(pending))
    assert policies[str(subject)]["preferred_target_id"] == target["target_id"]
    assert dispositions[0].disposition == "applied"
    advanced = society_repository(world).advance(
        world["version"].version_id,
        base_tick=society["current_tick"],
        base_state_sha256=society["state_sha256"],
    )
    person = next(
        value for value in advanced["state"]["inhabitants"] if value["id"] == str(subject)
    )
    assert person["goal"]["target_id"] == target["target_id"]
    consumed = action_repository(world).read(world["version"].version_id, request_id)
    assert consumed["status"] == "consumed"
    assert consumed["consumption"] == {"tick": 1, "disposition": "applied"}
    assert society_repository(world).replay(world["version"].version_id)["replay_verified"]
    with pytest.raises(CheckViolation), world["connection"].transaction():
        world["connection"].execute(
            "update world_society_action_request set document=document where workspace_id=%s",
            (world["workspace"],),
        )


def test_stale_duplicate_foreign_and_forged_requests_fail_closed(action_world):
    world = action_world
    society, document = create_society(world)
    target = document["targets"][0]
    with pytest.raises(StaleSocietyState, match="changed"):
        create_action(world, society, target, base_tick=1)
    envelope, _ = create_action(world, society, target)
    with pytest.raises(StaleSocietyState, match="already has"):
        create_action(world, society, target)
    with pytest.raises(StaleSocietyState, match="reused"):
        action_repository(world).create(
            world["version"].version_id,
            request_id=uuid.UUID(envelope["request"]["request_id"]),
            requested_by=world["actor"],
            subject_id=uuid.uuid4(),
            base_tick=society["current_tick"],
            base_state_sha256=society["state_sha256"],
            intent=ActionIntent("go_to", target["target_id"]),
        )
    with pytest.raises(UnknownSociety):
        action_repository(world, uuid.uuid4()).read(
            world["version"].version_id, uuid.UUID(envelope["request"]["request_id"])
        )
    forged = dict(envelope["request"])
    forged["branch_id"] = str(uuid.uuid4())
    with pytest.raises(CheckViolation), world["connection"].transaction():
        world["connection"].execute(
            "insert into world_society_action_request(workspace_id,society_id,action_seq,"
            "request_id,requested_by,subject_id,target_id,base_tick,input_seq,document,"
            "document_sha256) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                world["workspace"],
                society["society_id"],
                2,
                uuid.uuid4(),
                world["actor"],
                uuid.UUID(forged["subject_id"]),
                target["target_id"],
                forged["base_tick"],
                forged["input_seq"],
                Jsonb(forged),
                forged["document_sha256"],
            ),
        )


def test_source_withdrawal_blocks_new_and_historical_request_materialization(action_world):
    world = action_world
    society, document = create_society(world)
    envelope, _ = create_action(world, society, document["targets"][0])
    world["rights"]["withdrawn"] = True
    request_id = uuid.UUID(envelope["request"]["request_id"])
    with pytest.raises(UnavailableSocietyInput):
        action_repository(world).read(world["version"].version_id, request_id)
    with pytest.raises(UnavailableSocietyInput):
        action_repository(world).history(world["version"].version_id)
    with pytest.raises(UnavailableSocietyInput):
        create_action(world, society, document["targets"][1])


def test_queued_input_change_consumes_request_as_stale_and_replays(action_world):
    world = action_world
    society, document = create_society(world)
    envelope, _subject = create_action(world, society, document["targets"][0])
    changed = edited(document)
    changed["targets"][0]["node_id"] = "a"
    society_repository(world).record_input(world["version"].version_id, seal(changed))
    advanced = society_repository(world).advance(
        world["version"].version_id,
        base_tick=society["current_tick"],
        base_state_sha256=society["state_sha256"],
    )
    consumed = action_repository(world).read(
        world["version"].version_id, uuid.UUID(envelope["request"]["request_id"])
    )
    assert consumed["consumption"] == {"tick": 1, "disposition": "stale"}
    event = (
        world["connection"]
        .execute(
            "select document from world_society_event where workspace_id=%s and society_id=%s "
            "and event_kind='user_action_requested'",
            (world["workspace"], advanced["society_id"]),
        )
        .fetchone()["document"]
    )
    assert event["disposition"] == "stale" and event["reason"] == "action_context_changed"
    assert society_repository(world).replay(world["version"].version_id)["replay_verified"]
