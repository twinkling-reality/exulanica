"""Selected subjects use the existing direct/Companion writers and replay, as runtime role.

The model client is absent. These tests are private database evidence, not live inference.
"""

import dataclasses
import json
import os
import uuid
from pathlib import Path

import pytest
from exulanica.api.authorisation import load_token_directory
from exulanica.api.permissions import Permission
from exulanica.world.society import UnavailableSocietyInput
from psycopg import sql

import test_thing_card_postgres as cards
from test_society_saved_world_api import OWNER, TOKEN, routes

saved_world = cards.saved_world
app = cards.app
pytestmark = pytest.mark.postgres


def _setup_grants(world, client, monkeypatch):
    grants = json.loads(os.environ["EXULANICA_API_TOKENS"])
    owner = grants[TOKEN]
    choices = {
        "subject-reader-credential-long-enough": {
            **owner,
            "permissions": [str(Permission.WORLD_READ)],
        },
        "subject-colleague-credential-long-enough": {**owner, "actor": str(uuid.uuid4())},
        "subject-stranger-credential-long-enough": {
            **owner,
            "workspace_id": str(uuid.uuid4()),
            "actor": str(uuid.uuid4()),
        },
        "subject-ungranted-credential-long-enough": {
            **owner,
            "permissions": [str(Permission.ADMISSION_READ)],
        },
    }
    monkeypatch.setenv("EXULANICA_API_TOKENS", json.dumps(grants | choices))
    client.app.state.services = dataclasses.replace(
        client.app.state.services, tokens=load_token_directory()
    )
    return [{"Authorization": f"Bearer {key}"} for key in choices]


def _offer(client, world, ref, headers=OWNER):
    scope, version, _society = routes(world)
    return client.get(f"{version}/subjects/{ref}", headers=headers, params=scope)


def _prepare(client, world, action, *, base=None):
    scope, version, _society = routes(world)
    if base is None:
        read = client.get(version, headers=OWNER, params=scope)
        assert read.status_code == 200, read.text
        base = read.json()["state_sha256"]
    response = client.post(
        "/selection/actions/prepare",
        headers=OWNER,
        params=scope,
        json={
            "version_id": str(world["binding"].version_id),
            "base_state_sha256": base,
            "actions": [action],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _send(client, step):
    method, template = step["operation"].split(" ", 1)
    return client.request(
        method,
        template.format(**step["bind"]),
        headers=OWNER,
        params=step["query"],
        json=step["body"],
    )


def _outcome(client, world, plan, receipt):
    scope, _, _society = routes(world)
    (step,) = plan["steps"]
    step = {
        **step,
        "answer": {"status": receipt.status_code, "choice_seq": receipt.json()["choice_seq"]},
    }
    response = client.post(
        "/selection/actions/outcome",
        headers=OWNER,
        params=scope,
        json={
            "version_id": plan["version_id"],
            "plan_sha256": plan["plan_sha256"],
            "steps": [step],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _counts(world):
    tables = (
        "world_society_control",
        "world_society_control_event",
        "world_society_event",
        "world_society_model_choice",
        "world_thing_look",
        "world_minds_budget",
    )
    with world["connection"].transaction():
        return {
            table: world["connection"]
            .execute(sql.SQL("select count(*) as n from {}").format(sql.Identifier(table)))
            .fetchone()["n"]
            for table in tables
        }


def _actions(offer):
    assert offer.status_code == 200, offer.text
    return {a["id"]: a for a in offer.json()["actions"]}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_subject_offer_to_companion_play_choice_receipts_and_replay(app, monkeypatch):
    world, client = app
    reader, colleague, stranger, ungranted = _setup_grants(world, client, monkeypatch)
    before = _offer(client, world, "world")
    assert _actions(before)["people.bring-in"]["state"] == "available"
    assert before.headers["Cache-Control"] == "private, no-store"
    assert _offer(client, world, f"being:{uuid.uuid4()}").status_code == 404
    snapshot = cards._society(client, world)
    knight = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")
    sword = next(t for t in snapshot["state"]["things"] if t["placed_id"] == "sword")
    ref = f"being:{knight['id']}"
    counts = _counts(world)
    assert counts["world_society_control"] == 0
    offer = _offer(client, world, ref)
    acts = _actions(offer)
    assert acts["beings.play"]["state"] == "available"
    assert acts["beings.give-back"]["code"] == "not_played"
    assert acts["things.look"]["state"] == "available"
    assert acts["minds.choose"]["state"] == "available"
    direct = cards._card(client, world, knight["id"]).json()
    properties = {p["key"]: p for p in offer.json()["properties"]}
    assert properties["decided_by"]["value"] == direct["decider"]
    assert properties["can_do"]["value"] == direct["abilities"]
    assert offer.json()["read"] == direct["society"]
    world_actions = _actions(_offer(client, world, "world"))
    assert world_actions["people.bring-in"]["code"] == "people_already_here"
    assert world_actions["clock.play"]["state"] == "available"
    assert world_actions["clock.pause"]["code"] == "already_paused"
    assert world_actions["people.bring-back"]["code"] == "engine_keeps_its_people"
    assert world_actions["people.bring-back"]["state"] == "unsupported"
    assert world_actions["minds.budget"]["state"] == "available"
    thing = _actions(_offer(client, world, f"thing:{sword['id']}"))
    assert thing["things.move"]["runs_by"]["bind"]["thing_id"] == "sword"
    assert "beings.play" not in thing
    assert _offer(client, world, f"thing:{knight['id']}").status_code == 404

    # Merely reading or preparing the offer appends no choice or look and moves no minute.
    with world["connection"].transaction():
        count = (
            world["connection"]
            .execute("select count(*) as n from world_society_model_choice")
            .fetchone()["n"]
        )
    plan = _prepare(client, world, {"operation": "play_being", "subject_id": knight["id"]})
    assert plan["outcome"] == "plan", plan
    assert _counts(world) == counts
    (step,) = plan["steps"]
    assert step["operation"] == acts["beings.play"]["runs_by"]["route"]
    assert client.app.state.services.model_client is None
    receipt = _send(client, step)
    assert receipt.status_code == 201, receipt.text
    repeat = _send(client, step)
    assert repeat.status_code == 201
    assert repeat.json()["choice_seq"] == receipt.json()["choice_seq"]
    assert _outcome(client, world, plan, receipt)["state"] == "applied"
    own = _actions(_offer(client, world, ref))
    assert own["beings.play"]["code"] == "no_change"
    assert own["beings.give-back"]["state"] == "available"
    assert own["minds.choose"]["code"] == "being_played"
    other = _offer(client, world, ref, colleague)
    assert _actions(other)["beings.play"]["code"] == "being_played"
    assert _actions(other)["beings.give-back"]["code"] == "not_played"
    assert str(world["session"].actor) not in other.text
    assert "account_id" not in other.text

    give = _prepare(client, world, {"operation": "give_back", "subject_id": knight["id"]})
    returned = _send(client, give["steps"][0])
    assert returned.status_code == 200, returned.text
    assert _outcome(client, world, give, returned)["state"] == "applied"
    choice = _prepare(client, world, {"operation": "choose_mind", "whom": ref, "mind": "routine"})
    chosen = _send(client, choice["steps"][0])
    assert chosen.status_code == 200, chosen.text
    assert _outcome(client, world, choice, chosen)["state"] == "applied"

    # Choosing an existing body's look changes no society time or state.
    before_look = _offer(client, world, ref).json()
    chosen_look = direct["looks"][-1]
    look = (
        {"source": "workspace", "sha256": chosen_look["sha256"]}
        if chosen_look.get("source") == "workspace"
        else {key: chosen_look[key] for key in ("look", "version", "sha256")}
    )
    scope, version, society = routes(world)
    response = client.post(
        f"{society}/things/{knight['id']}/look", headers=OWNER, params=scope, json={"look": look}
    )
    assert response.status_code == 200, response.text
    after_look = _offer(client, world, ref).json()
    assert before_look["read"] == after_look["read"]
    assert (
        next(p for p in after_look["properties"] if p["key"] == "look")["value"]
        == response.json()["look"]
    )
    replay = client.get(f"{society}/replay", headers=OWNER, params=scope)
    assert replay.status_code == 200 and replay.json()["replay_verified"], replay.text

    # A grant still belongs to the writer; a served action never conveys it.
    readonly = _offer(client, world, ref, reader)
    assert all(not a["permitted"] for a in readonly.json()["actions"])
    for credential in (reader, ungranted):
        denied = client.post(
            f"{society}/play",
            headers=credential,
            params=scope,
            json={"subject_id": knight["id"], "idempotency_key": str(uuid.uuid4())},
        )
        assert denied.status_code == 404
    for credential in (stranger, ungranted):
        missing = _offer(client, world, ref, credential)
        invented = client.get(
            f"/world/versions/{uuid.uuid4()}/subjects/{ref}", headers=credential, params=scope
        )
        assert missing.status_code == invented.status_code == 404
        assert missing.json()["code"] == invented.json()["code"] == "unknown_reference"
    assert _offer(client, world, "object:x").status_code == 404
    assert (
        _prepare(
            client, world, {"operation": "play_being", "subject_id": knight["id"]}, base="0" * 64
        )["refusal"]["code"]
        == "stale_version"
    )
    with world["connection"].transaction():
        assert (
            world["connection"]
            .execute("select count(*) as n from world_society_model_choice")
            .fetchone()["n"]
            == count + 3
        )

    # Budget values remain visible without disclosing the setter's account.
    budget = client.post(
        f"{version}/models/society_decision/budget",
        headers=OWNER,
        params=scope,
        json={"idempotency_key": str(uuid.uuid4()), "usd_per_hour": "0", "decisions_per_hour": 0},
    )
    assert budget.status_code == 200, budget.text
    own_budget = next(
        p for p in _offer(client, world, "world").json()["properties"] if p["key"] == "mind_budget"
    )["value"]["budget"]
    other_budget = next(
        p
        for p in _offer(client, world, "world", colleague).json()["properties"]
        if p["key"] == "mind_budget"
    )["value"]["budget"]
    assert own_budget["set_by_you"] is True
    assert other_budget["set_by_you"] is False
    assert "set_by" not in other_budget
    assert str(world["session"].actor) not in json.dumps(other_budget)

    def unavailable(*args):
        raise UnavailableSocietyInput("the test source was withdrawn")

    monkeypatch.setattr(client.app.state, "society_input_authorizer", unavailable)
    for reference in (ref, "world"):
        refused = _offer(client, world, reference)
        assert refused.status_code == 424
        assert refused.json()["code"] == "unavailable_society_input"

    evidence_path = os.environ.get("EXULANICA_SUBJECT_OFFER_EVIDENCE")
    if evidence_path:
        Path(evidence_path).write_text(
            json.dumps(
                {
                    "profile": "exulanica.subject-offer-test-evidence/v1",
                    "private_database_fixture": True,
                    "live_inference_verified": False,
                    "model_client_configured": client.app.state.services.model_client is not None,
                    "world_before_society": before.json(),
                    "selected_being": offer.json(),
                    "card": direct,
                    "world_actions": world_actions,
                    "thing_actions": thing,
                    "counts_before_reads_and_prepare": counts,
                    "prepared_play": plan,
                    "play_receipt": receipt.json(),
                    "same_play_retry": repeat.json(),
                    "own_play_actions": own,
                    "other_person_offer": other.json(),
                    "give_back_receipt": returned.json(),
                    "routine_choice": chosen.json(),
                    "look_response": response.json(),
                    "read_before_look": before_look["read"],
                    "read_after_look": after_look["read"],
                    "replay": replay.json(),
                    "reader_offer": readonly.json(),
                    "own_budget": own_budget,
                    "other_person_budget": other_budget,
                    "withdrawn_source_refusal": refused.json(),
                },
                indent=2,
            )
            + "\n"
        )
