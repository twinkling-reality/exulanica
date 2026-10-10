"""The Companion's choice of a mind through the application and PostgreSQL: the step is the request.

In a saved world on a host that offers societies of things, as its owner, with the model scripted:

*   "let <a model> decide for the knight" is one step, the models route's own request for that
    being, planned without writing anything, with what it will cost said from the figure the host
    itself reserves by; sent, it is the choice that route records, which the outcome read credits;
*   a choice that would run more beings by models than the world's contract allows is asked about
    with the groups that fit, and the route itself refuses the same choice by name;
*   a being a person plays is left out of a group's choice and counted by the code the route
    refuses it with, and a choice naming it alone is blocked by that code.

Every refusal a plan states is held against what the models route answers the same choice with.
The drafter's option labels are read from the request the scripted model was sent, the way the
model reads them (``test_companion_things_postgres``).
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from exulanica.api.decision_host import ask_bound_usd
from exulanica.models.manifest import load_manifest
from exulanica.selection.action_plan import ACTION_PROMPT_VERSION, MIND
from exulanica.world.decision_roles import decision_roles

import test_companion_things_postgres as things
import test_society_made_kinds_postgres as made
from test_society_saved_world_api import OWNER, routes

companion = things.companion
saved_world = things.saved_world
saved_world_app = things.saved_world_app
pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "assets/catalogs/roles"
POLICIES = ROOT / "assets/catalogs/society"


def _catalog_value(policy_version: int, key: str) -> int:
    """A decision policy's value as its catalog file states it."""
    document = json.loads(
        (POLICIES / f"society-decision-policy.v{policy_version}.json").read_text()
    )
    return next(entry["value"] for entry in document["entries"] if entry["key"] == key)


def _people_entry() -> dict:
    """The people's role as the newest registry file states it."""
    newest = max(
        ROLES.glob("decision-roles.v*.json"), key=lambda path: int(path.stem.split("v")[-1])
    )
    document = json.loads(newest.read_text())
    return next(entry for entry in document["entries"] if entry["subject"] == "person")


def _town(client, world) -> dict:
    """A well and a knight placed, people brought in: the society, as its own read gives it."""
    things._place(client, world, "well", "well", 2, -4_000, 2_000)
    things._place(client, world, "knight-1", "knight", 1, 3_000, 1_000)
    things._society(client, world)
    return things._now(client, world)


def _of_kind(society: dict, kind: str) -> list[str]:
    return [
        person["id"]
        for person in society["state"]["inhabitants"]
        if (person.get("kind") or {}).get("kind") == kind
    ]


def _groups(society: dict) -> dict[str, int]:
    """The groups the society's own read holds, counted from it: everyone, each kind, and each role
    whose people are not exactly a kind's (a knight's role is its kind's own word)."""
    people = society["state"]["inhabitants"]
    kinds: dict[str, list[str]] = {}
    roles: dict[str, list[str]] = {}
    for person in people:
        kinds.setdefault(person["kind"]["kind"], []).append(person["id"])
        roles.setdefault(person["role"], []).append(person["id"])
    found = {"everyone": len(people)}
    found.update({f"kind:{kind}": len(members) for kind, members in kinds.items()})
    same = [set(members) for members in kinds.values()]
    found.update(
        {
            f"role:{role}": len(members)
            for role, members in roles.items()
            if set(members) not in same
        }
    )
    return found


def _models_read(client, world) -> dict:
    scope, root, _ = routes(world)
    read = client.get(root + "/models", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    [people] = [role for role in read.json()["roles"] if role["subject"] == "person"]
    return people


def _choose(client, world, subjects, model):
    """The same choice sent to the models route directly: the authority a plan is held to."""
    scope, root, _ = routes(world)
    return client.post(
        root + f"/models/{_people_entry()['key']}",
        headers=OWNER,
        params=scope,
        json={"idempotency_key": str(uuid.uuid4()), "subjects": list(subjects), "model": model},
    )


def _choices(world) -> int:
    row = world["connection"].execute("select count(*) as n from world_society_model_choice")
    return row.fetchone()["n"]


def _mind_labels(labels: dict[str, str], model_name: str) -> tuple[str, str]:
    """The labels the drafter is shown for their own routine and for the model named."""
    return (
        things._label(labels, "their own routine.", starts=True),
        things._label(labels, f"{model_name}.", starts=True),
    )


def _draft(transport, *options):
    transport.responses[:] = [
        things._reply({"kind": "world_edit"}),
        things._reply({"steps": [{"operation": "choose_mind", "options": list(options)}]}),
    ]


def test_a_mind_for_the_knight_is_the_models_route_s_request_and_the_choice_it_records(
    companion,
):
    world, client, transport = companion
    society = _town(client, world)
    [knight] = _of_kind(society, "knight")
    people = _models_read(client, world)
    offered = people["view"]["models"][0]
    labels = things._look(client, world, transport, "let a model decide for the knight")
    _routine, model_label = _mind_labels(labels, offered["name"])
    group = things._label(labels, "every knight (1)")
    before = _choices(world)
    _draft(transport, group, model_label)
    plan = things._ask(client, world, f"let {offered['name']} decide for the knight")

    assert plan["outcome"] == "plan", things._why(plan)
    assert plan["execution"]["prompt_version"] == ACTION_PROMPT_VERSION
    assert _choices(world) == before, "planning recorded a choice"
    [step] = plan["steps"]
    entry = _people_entry()
    assert (step["operation"], step["state"], step["confirmation"]) == (
        MIND,
        "prepared",
        "required",
    )
    assert step["bind"] == {
        "version_id": str(world["binding"].version_id),
        "role_key": entry["key"],
    }
    assert step["body"]["subjects"] == [knight]
    assert step["body"]["model"] == {
        "provider": offered["provider"],
        "model_id": offered["model_id"],
    }
    assert step["titles"] == {"whom": "every knight", "mind": offered["name"]}
    assert step["spends"] is True and plan["spends"] is True
    # What the choice comes to, against the society's own read and the role's own catalog.
    policy = entry["policy_version"]
    assert step["mind"]["subjects"] == 1 and step["mind"]["left_out"] == {}
    assert (step["mind"]["run_now"], step["mind"]["run_after"]) == (0, 1)
    assert step["mind"]["bound"] == _catalog_value(policy, entry["subjects_bound"])
    assert step["mind"]["host_refusal"] == people["host_refusal"]
    assert step["mind"]["model_refusal"] == offered["refusal"]
    counts = {group["value"]: group["count"] for group in step["mind"]["groups_here"]}
    assert counts == _groups(society)
    # The starter square's villagers each have a role of their own: a baker is among them.
    assert counts["kind:villager"] == len(_of_kind(society, "villager")) and "role:baker" in counts
    # What it may cost: the figure the host reserves for one answer, once a being a minute, and
    # the ceilings of the contract this society's engine is asked under.
    [role] = [found for found in decision_roles() if found.subject == "person"]
    asked = role.contract(role.terms(things.V7).versions)
    budget = client.app.state.services.model_client.budget
    spec = load_manifest().offered(role.chosen, offered["model_id"])
    one = ask_bound_usd(role, budget, spec, asked)
    cost = step["cost"]
    assert cost["per"] == "simulated_minute" and cost["subjects"] == 1
    assert Decimal(cost["usd_per_answer_at_most"]) == one and one > 0
    assert Decimal(cost["usd_at_most"]) == one
    assert cost["usd_typical"] is None
    [terms] = [found for found in entry["engine_terms"] if found["engine"] == things.V7]
    assert Decimal(cost["ceilings"]["usd_per_world_hour"]) * 1_000_000 == _catalog_value(
        terms["policy_version"], "spend_per_world_hour_microusd"
    )
    assert cost["ceilings"]["decisions_per_world_hour"] == _catalog_value(
        terms["policy_version"], "decisions_per_world_hour_maximum"
    )

    sent = things._send(client, step)
    assert sent.status_code == 200, sent.text
    choice = sent.json()
    assert choice["people"] == [knight]
    assert choice["decider"] == {"kind": "model", **step["body"]["model"]}
    after = _models_read(client, world)["view"]["choices"]
    [chosen] = [found for found in after if found["subject_id"] == knight]
    assert chosen["model"]["model_id"] == offered["model_id"]
    # Sent again, the same plan answers the choice it recorded.
    again = things._send(client, step)
    assert again.status_code == 200 and again.json()["choice_seq"] == choice["choice_seq"]
    assert _choices(world) == before + 1

    read = things._outcome(
        client,
        world,
        plan,
        [{**step, "answer": {"status": 200, "choice_seq": choice["choice_seq"]}}],
    )
    assert read["state"] == "applied"
    [receipt] = read["steps"][0]["receipts"]
    assert (receipt["choice_seq"], receipt["document_sha256"], receipt["subjects"]) == (
        choice["choice_seq"],
        choice["document_sha256"],
        1,
    )
    # A step sent back with no answer, or naming another choice, is never credited.
    unsent = things._outcome(client, world, plan, [step])
    assert unsent["steps"][0]["state"] == "not_applied"
    other = things._outcome(
        client,
        world,
        plan,
        [{**step, "answer": {"status": 200, "choice_seq": choice["choice_seq"] + 1}}],
    )
    assert other["steps"][0]["state"] == "not_applied"

    # Taking the mind back is the routine: nobody is asked and nothing is said to cost.
    labels = things._look(client, world, transport, "the knight decides for itself again")
    routine, _model = _mind_labels(labels, offered["name"])
    _draft(transport, things._label(labels, "every knight (1)"), routine)
    back = things._ask(client, world, "the knight decides for itself again")
    [step] = back["steps"]
    assert step["body"]["model"] is None and step["spends"] is False and step["cost"] is None
    assert (step["mind"]["run_now"], step["mind"]["run_after"]) == (1, 0)
    assert step["body"]["idempotency_key"] != plan["steps"][0]["body"]["idempotency_key"]
    returned = things._send(client, step)
    assert returned.status_code == 200 and returned.json()["decider"] == {"kind": "routine"}


def test_a_choice_past_the_world_s_bound_is_asked_about_and_the_route_refuses_it_by_name(
    companion,
):
    world, client, transport = companion
    society = _town(client, world)
    everyone = [person["id"] for person in society["state"]["inhabitants"]]
    villagers = _of_kind(society, "villager")
    entry = _people_entry()
    bound = _catalog_value(entry["policy_version"], entry["subjects_bound"])
    assert len(villagers) <= bound < len(everyone), "the fixture no longer straddles the bound"
    offered = _models_read(client, world)["view"]["models"][0]
    model = {"provider": offered["provider"], "model_id": offered["model_id"]}
    labels = things._look(client, world, transport, "give everyone a mind")
    _routine, model_label = _mind_labels(labels, offered["name"])
    before = _choices(world)
    _draft(transport, things._label(labels, f"everyone here ({len(everyone)})"), model_label)
    plan = things._ask(client, world, f"let {offered['name']} decide for everyone")

    assert plan["outcome"] == "clarify", things._why(plan)
    asked = plan["clarification"]
    assert (asked["code"], asked["slot"]) == ("too_many_people_for_models", "whom")
    assert asked["facts"] == {"asked": len(everyone), "bound": bound, "run_now": 0}
    # Every other group this world holds fits, since nobody has a model yet; none is taken for
    # the person.
    fitting = [value for value, count in _groups(society).items() if count <= bound]
    assert [candidate["value"] for candidate in asked["candidates"]] == fitting
    assert "kind:villager" in fitting and "role:baker" in fitting and "everyone" not in fitting
    assert plan["steps"] == [] and _choices(world) == before
    # The route itself refuses the choice the plan asked about, by its own name.
    refused = _choose(client, world, everyone, model)
    assert (refused.status_code, refused.json()["code"]) == (422, "too_many_model_people")

    # The answer is the person's: the typed action comes back with the slot filled.
    [action] = asked["actions"]
    prepared = things._prepare(client, world, [{**action, "whom": "kind:villager"}])
    assert prepared["outcome"] == "plan", things._why(prepared)
    [step] = prepared["steps"]
    assert sorted(step["body"]["subjects"]) == sorted(villagers)
    assert (step["mind"]["run_after"], step["mind"]["bound"]) == (len(villagers), bound)
    assert Decimal(step["cost"]["usd_at_most"]) == Decimal(
        step["cost"]["usd_per_answer_at_most"]
    ) * len(villagers)
    sent = things._send(client, step)
    assert sent.status_code == 200, sent.text
    assert sorted(sent.json()["people"]) == sorted(villagers)


def test_a_played_being_is_left_out_of_a_group_and_blocks_a_choice_naming_it_alone(companion):
    world, client, transport = companion
    society = _town(client, world)
    [knight] = _of_kind(society, "knight")
    villagers = _of_kind(society, "villager")
    scope, root, _ = routes(world)
    played = client.post(
        root + "/society/play",
        headers=OWNER,
        params=scope,
        json={"idempotency_key": str(uuid.uuid4()), "subject_id": knight},
    )
    assert played.status_code == 201, played.text
    # What the route answers a choice naming the played being, alone: the code a plan must state.
    refused = _choose(client, world, [knight], None)
    assert refused.status_code == 409, refused.text
    code = refused.json()["code"]
    assert code == "being_played"

    offered = _models_read(client, world)["view"]["models"][0]
    labels = things._look(client, world, transport, "everyone back to their own routine")
    routine, _model = _mind_labels(labels, offered["name"])
    everyone = things._label(labels, f"everyone here ({len(villagers) + 1})")
    _draft(transport, everyone, routine)
    plan = things._ask(client, world, "everyone back to their own routine")
    assert plan["outcome"] == "plan", things._why(plan)
    [step] = plan["steps"]
    assert sorted(step["body"]["subjects"]) == sorted(villagers)
    assert step["mind"]["left_out"] == {code: 1}
    assert things._send(client, step).status_code == 200

    _draft(transport, things._label(labels, "every knight (1)"), routine)
    alone = things._ask(client, world, "the knight back to its own routine")
    assert alone["outcome"] == "refused"
    assert alone["refusal"]["code"] == "preview_blocked"
    assert (alone["steps"][0]["state"], alone["steps"][0]["code"]) == ("blocked", code)
    assert alone["steps"][0]["body"] is None


def test_a_being_that_is_not_here_is_refused_by_the_code_the_route_answers(companion):
    world, client, _transport = companion
    _town(client, world)
    stranger = str(uuid.uuid4())
    refused = _choose(client, world, [stranger], None)
    assert refused.status_code == 422, refused.text
    code = refused.json()["code"]
    prepared = things._prepare(
        client,
        world,
        [{"operation": "choose_mind", "whom": f"being:{stranger}", "mind": "routine"}],
    )
    assert prepared["outcome"] == "refused"
    assert prepared["steps"][0]["code"] == code == "person_not_in_this_world"
    # A group this world does not hold never reaches the route.
    unknown = things._prepare(
        client, world, [{"operation": "choose_mind", "whom": "kind:dragon", "mind": "routine"}]
    )
    assert unknown["refusal"]["code"] == "not_in_catalogue"


def test_a_mind_is_chosen_for_a_being_of_a_made_kind_through_the_real_read(
    companion, spine_schema, tmp_path
):
    """A creature its workspace keeps lives in the society beside a knight. Its kind is named in
    the state by source and digest, not by a shipped kind: it is one of everyone, joins no kind's
    group, and a mind chosen for it by name is the models route's own request, which the route
    records for that being alone."""
    world, client, transport = companion
    creature = made._keep(world, spine_schema, tmp_path)
    things._place(client, world, "well", "well", 2, -4_000, 2_000)
    things._place(client, world, "knight", "knight", 2, 3_000, 3_000)
    made._place_made(client, world, made.CREATURE, creature.kind.sha256, 1_000, 5_000)
    things._society(client, world)
    society = things._now(client, world)
    people = society["state"]["inhabitants"]
    [being] = [
        person
        for person in people
        if person["kind"] == {"source": "workspace", "sha256": creature.kind.sha256}
    ]
    shipped = [person for person in people if "kind" in (person["kind"] or {})]
    assert len(shipped) == len(people) - 1

    offered = _models_read(client, world)["view"]["models"][0]
    words = f"let {offered['name']} decide for {being['display_name']}"
    labels = things._look(client, world, transport, words)
    _routine, model_label = _mind_labels(labels, offered["name"])
    _draft(transport, things._label(labels, being["display_name"], starts=True), model_label)
    before = _choices(world)
    plan = things._ask(client, world, words)

    assert plan["outcome"] == "plan", things._why(plan)
    assert _choices(world) == before, "planning recorded a choice"
    [step] = plan["steps"]
    assert (step["operation"], step["state"]) == (MIND, "prepared")
    assert step["body"]["subjects"] == [being["id"]]
    assert step["mind"]["subjects"] == 1 and step["mind"]["left_out"] == {}
    # The groups the step states: everyone counts the made being; the kinds' groups hold the
    # shipped beings only, counted from the society's own read.
    counts = {group["value"]: group["count"] for group in step["mind"]["groups_here"]}
    assert counts["everyone"] == len(people)
    kinds: dict[str, int] = {}
    for person in shipped:
        kinds[person["kind"]["kind"]] = kinds.get(person["kind"]["kind"], 0) + 1
    assert {
        value.removeprefix("kind:"): count
        for value, count in counts.items()
        if value.startswith("kind:")
    } == kinds
    # Sent, it is the route's own choice for that being; the same choice sent directly agrees.
    sent = things._send(client, step)
    assert sent.status_code == 200, sent.text
    assert sent.json()["people"] == [being["id"]]
    # Everyone back to their routine names the made being with the rest.
    everyone = things._prepare(
        client, world, [{"operation": "choose_mind", "whom": "everyone", "mind": "routine"}]
    )
    assert everyone["outcome"] == "plan", things._why(everyone)
    assert sorted(everyone["steps"][0]["body"]["subjects"]) == sorted(p["id"] for p in people)
