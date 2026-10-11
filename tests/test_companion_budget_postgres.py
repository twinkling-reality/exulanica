"""The Companion's budget for a world's minds and a town taking its newcomers in, through the
application and PostgreSQL: each step is the request.

In a saved world on a host that offers societies of things, as its owner, with the model scripted:

*   "let this town spend up to 50 cents an hour on minds" is one step, the budget route's own
    request, planned without writing anything, with every figure of its sheet held here against
    another source: the default against the policy catalog's file, the most an answer can cost
    against the host's own reservation, the typical price and rate against the evaluation record,
    the head count against the society's own read; sent, it is the budget that route records,
    which the outcome read credits, and which a later budget supersedes;
*   a budget of nothing asks no model, and both sheets say so by the host's own reason: the
    budget's, and the next choice of a mind (what the capability read of the role does not say).

In a generated town with its own people and a knight placed after they came, the typed request
``take_in`` is the take-in route's request; sent, the town's society is made again as one that
holds the knight, the outcome read credits it, and asked again the plan refuses by the capability
read's own code, as the route does.
"""

from __future__ import annotations

import json
import uuid
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from exulanica.api.decision_host import ask_bound_usd, hour_refusal
from exulanica.models.manifest import load_manifest
from exulanica.selection.action_plan import (
    ACTION_PROMPT_VERSION,
    BUDGET,
    TAKE_IN,
    TAKE_IN_KEEPS,
    TAKE_IN_LOSES,
)
from exulanica.world import saved_entries
from exulanica.world.decision_roles import decision_roles
from exulanica.world.minds_budget import MindsBudget

import test_companion_budget_plan as budget_plan
import test_companion_minds_postgres as minds
import test_companion_things_postgres as things
from test_society_made_world import made as imported_made  # noqa: F401
from test_society_saved_world_api import OWNER, routes
from test_society_take_in_postgres import TOWN, V5, V7, _held, _offered, _town
from test_walking_surfaces_v3_postgres import (  # noqa: F401
    _every_town_a_test_makes_is_made,
    _made_alias,
    _offering_things,
    _place,
)

companion = things.companion
saved_world = things.saved_world
saved_world_app = things.saved_world_app
pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs/evaluation/2026-10-10-minds-ask-rates.json"
NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SENTENCE = "Let this town spend up to 50 cents an hour on minds"


def _budgets(world) -> int:
    row = world["connection"].execute("select count(*) as n from world_minds_budget")
    return row.fetchone()["n"]


def _draft(transport, *options):
    transport.responses[:] = [
        things._reply({"kind": "world_edit"}),
        things._reply({"steps": [{"operation": "set_minds_budget", "options": list(options)}]}),
    ]


def _arm(name: str) -> dict:
    """One arm of the evaluation record, as its file states it."""
    return json.loads(RECORD.read_text())["record"]["arms"][name]


def _bound(client, model_id: str) -> Decimal:
    """The most one answer of ``model_id`` can cost a being of a society of things: the figure
    the host reserves by."""
    [role] = [found for found in decision_roles() if found.subject == "person"]
    asked = role.contract(role.terms(things.V7).versions)
    spec = load_manifest().offered(role.chosen, model_id)
    return ask_bound_usd(role, client.app.state.services.model_client.budget, spec, asked)


def _interval_ms(client, world) -> int:
    """The wait between two simulated minutes at the speed the world's control holds."""
    scope, _root, society = routes(world)
    control = client.get(society + "/control", headers=OWNER, params=scope)
    assert control.status_code == 200, control.text
    read = control.json()
    return int(read["base_tick_interval_ms"]) // int(read["speed"])


def test_a_budget_in_a_sentence_is_the_budget_route_s_request_and_its_sheet_is_true(companion):
    world, client, transport = companion
    society = minds._town(client, world)
    [knight] = minds._of_kind(society, "knight")
    people = minds._models_read(client, world)
    [nano] = [model for model in people["view"]["models"] if model["model_id"] == NANO]
    chosen = minds._choose(
        client, world, [knight], {"provider": nano["provider"], "model_id": NANO}
    )
    assert chosen.status_code == 200, chosen.text

    labels = things._look(client, world, transport, SENTENCE)
    amount = things._label(labels, "0.50 US dollars an hour.", starts=True)
    # The two budgets with no figure are listed beside the sentence's own amount.
    things._label(labels, "nothing.", starts=True)
    things._label(labels, "the default.", starts=True)
    before = _budgets(world)
    _draft(transport, amount)
    plan = things._ask(client, world, SENTENCE)

    assert plan["outcome"] == "plan", things._why(plan)
    assert plan["execution"]["prompt_version"] == ACTION_PROMPT_VERSION
    assert _budgets(world) == before == 0, "planning recorded a budget"
    [step] = plan["steps"]
    entry = minds._people_entry()
    assert (step["operation"], step["state"], step["confirmation"]) == (
        BUDGET,
        "prepared",
        "required",
    )
    assert step["bind"] == {
        "version_id": str(world["binding"].version_id),
        "role_key": entry["key"],
    }
    assert step["requires"] == ["model.invoke", "world.write"] and step["permitted"] is True
    assert step["spends"] is False and plan["spends"] is False
    [terms] = [found for found in entry["engine_terms"] if found["engine"] == things.V7]
    default_usd = Decimal(
        minds._catalog_value(terms["policy_version"], "spend_per_world_hour_microusd")
    ) / Decimal(1_000_000)
    default_decisions = minds._catalog_value(
        terms["policy_version"], "decisions_per_world_hour_maximum"
    )
    # Half a dollar, and the decisions the words did not name stay the catalog's own figure.
    assert Decimal(step["body"]["usd_per_hour"]) == Decimal("0.5")
    assert step["body"]["decisions_per_hour"] == default_decisions

    sheet = step["budget"]
    assert sheet["named"] == ["usd_per_hour"]
    assert Decimal(sheet["now"]["usd_per_hour"]) == default_usd
    assert sheet["now"]["decisions_per_hour"] == default_decisions
    assert sheet["now"]["set_by_a_person"] is False and sheet["now"]["set_by_you"] is False
    # The budget now is said as whose it is ("you" or not), never by an account's id.
    assert "set_by" not in sheet["now"]
    assert {k: v for k, v in sheet["default"].items() if k != "set_by"} == {
        k: v for k, v in sheet["now"].items() if k != "set_by_you"
    }
    assert Decimal(sheet["asked"]["usd_per_hour"]) == Decimal("0.5")
    assert sheet["hour_so_far"] == {"decisions": 0, "usd": "0.000000"}
    assert sheet["left_this_hour"] == {"decisions": default_decisions, "usd": "0.500000"}
    # This town's own head count, and the one being a model decides for.
    assert sheet["beings"] == len(society["state"]["inhabitants"]) > 1
    assert sheet["minded"] == 1
    [model] = sheet["models"]
    assert (model["model_id"], model["name"], model["beings"]) == (NANO, nano["name"], 1)
    one = _bound(client, NANO)
    assert Decimal(model["usd_per_answer_at_most"]) == one and one > 0
    # The typical price and rate are the evaluation record's cut arm's own counts.
    arm = _arm("society_of_things")
    assert arm["engine"] == things.V7 and arm["status"] == "cut"
    price = Decimal(arm["usd"]) / arm["asks"]
    rate = Decimal(arm["asks"]) / (arm["beings_with_the_model"] * arm["simulated_minutes"])
    assert Decimal(model["usd_per_answer_typical"]) == price.quantize(Decimal("0.00000001"))
    assert model["typical"]["rate_class"] == "estimate"
    assert model["typical"]["price_class"] == "measured"
    assert model["typical"]["source"] == "docs/evaluation/2026-10-10-minds-ask-rates.json"
    # What half a dollar pays for: every ask weighed at the bound before it is made.
    half = Decimal("0.5")
    at_most = int(half // one)
    typically = int((half - one) // price) + 1
    assert sheet["answers_for_usd"] == {"at_most_price": at_most, "at_typical_price": typically}
    # The same two counts, by asking the host's own rule for the hour one ask after another:
    # an ask is admitted while the rule refuses nothing, and then costs its price.
    role = decision_roles().role(entry["key"])
    contract = role.contract_for(things.V7)
    held = MindsBudget(half, 10**9)

    def admitted(cost: Decimal) -> int:
        asked, spent = 0, Decimal(0)
        while hour_refusal(asked, spent, one, contract, held) is None:
            asked, spent = asked + 1, spent + cost
        return asked

    assert (admitted(one), admitted(price)) == (at_most, typically)
    assert at_most < default_decisions < typically, "the fixture no longer shows both answers"
    assert sheet["binds"] == {"at_most_price": "usd", "at_typical_price": "decisions"}
    # How often this town's minds ask in a real hour at the speed its control holds.
    minutes = 3_600_000 // _interval_ms(client, world)
    demand = sheet["demand"]
    assert demand["simulated_minutes_per_real_hour"] == minutes
    assert demand["rate_class"] == "estimate"

    def asks(beings: int) -> int:
        return int((rate * beings * minutes).to_integral_value(ROUND_HALF_UP))

    def covered(beings: int) -> int:
        capacity = min(default_decisions, typically)
        wanted = rate * beings * minutes
        return 60 if wanted <= capacity else int(Decimal(60 * capacity) / wanted)

    assert demand["minded"] == {
        "beings": 1,
        "asks_per_real_hour": asks(1),
        "minutes_covered": covered(1),
    }
    assert demand["everyone"] == {
        "beings": sheet["beings"],
        "asks_per_real_hour": asks(sheet["beings"]),
        "minutes_covered": covered(sheet["beings"]),
    }
    assert sheet["refused_now"] is None
    assert sheet["host"]["refusal"] == people["host_refusal"]
    # The sheet the page's kept plan holds has the members the application serves, no others.
    kept = {**budget_plan.SHEET, "now": {}, "asked": {}, "beings": 0, "named": []}
    assert set(sheet) == set(kept)
    assert set(sheet["host"]) == set(kept["host"]) and set(sheet["demand"]) == set(kept["demand"])
    assert set(sheet["models"][0]) == set(kept["models"][0])

    sent = things._send(client, step)
    assert sent.status_code == 200, sent.text
    recorded = sent.json()["budget"]
    assert (recorded["budget_seq"], recorded["usd_per_hour"]) == (1, "0.500000")
    assert recorded["decisions_per_hour"] == default_decisions
    assert minds._models_read(client, world)["budget"]["usd_per_hour"] == "0.500000"
    # Sent again, the same plan answers the budget it recorded.
    again = things._send(client, step)
    assert again.status_code == 200 and again.json()["budget"]["budget_seq"] == 1
    assert _budgets(world) == 1

    answered = {**step, "answer": {"status": 200, "budget_seq": 1}}
    read = things._outcome(client, world, plan, [answered])
    assert read["state"] == "applied"
    [receipt] = read["steps"][0]["receipts"]
    assert (receipt["budget_seq"], receipt["document_sha256"], receipt["usd_per_hour"]) == (
        1,
        recorded["document_sha256"],
        "0.500000",
    )
    # A step sent back with no answer, or naming another budget, is never credited.
    assert things._outcome(client, world, plan, [step])["steps"][0]["state"] == "not_applied"
    other = {**step, "answer": {"status": 200, "budget_seq": 2}}
    assert things._outcome(client, world, plan, [other])["steps"][0]["state"] == "not_applied"

    # The same words asked again are no change now.
    _draft(transport, amount)
    same = things._ask(client, world, SENTENCE)
    assert same["outcome"] == "refused"
    assert [(found["state"], found["code"]) for found in same["steps"]] == [
        ("blocked", "no_change")
    ]

    # A budget of nothing: no model is asked, and the sheet says so by the host's own reason.
    labels = things._look(client, world, transport, "Spend nothing on minds")
    _draft(transport, things._label(labels, "nothing.", starts=True))
    nothing = things._ask(client, world, "Spend nothing on minds")
    assert nothing["outcome"] == "plan", things._why(nothing)
    [zero] = nothing["steps"]
    assert (zero["body"]["usd_per_hour"], zero["body"]["decisions_per_hour"]) == ("0.000000", 0)
    assert zero["budget"]["named"] == ["usd_per_hour", "decisions_per_hour"]
    assert zero["budget"]["now"]["budget_seq"] == 1 and zero["pins"] == {"budget_seq": 1}
    # The budget now is the one this same person set a moment ago, and the sheet can say so.
    assert zero["budget"]["now"]["set_by_you"] is True
    assert zero["budget"]["refused_now"] == "world_hour_decisions_spent"
    assert zero["budget"]["answers_for_usd"] == {"at_most_price": 0, "at_typical_price": 0}
    assert zero["body"]["idempotency_key"] != step["body"]["idempotency_key"]
    stopped = things._send(client, zero)
    assert stopped.status_code == 200 and stopped.json()["budget"]["budget_seq"] == 2
    # The first budget was recorded and is no longer the world's.
    assert things._outcome(client, world, plan, [answered])["steps"][0]["state"] == "superseded"

    # A mind chosen now is told the same before its yes: the world's budget asks nobody.
    # (The bakers: few enough to stand beside the knight under today's head count.)
    labels = things._look(client, world, transport, "a model for the bakers")
    _routine, model_label = minds._mind_labels(labels, nano["name"])
    bakers = things._label(labels, "everyone whose role is baker (", starts=True)
    minds._draft(transport, bakers, model_label)
    mind = things._ask(client, world, f"let {nano['name']} decide for the bakers")
    assert mind["outcome"] == "plan", things._why(mind)
    cost = mind["steps"][0]["cost"]
    assert cost["refused_now"] == "world_hour_decisions_spent"
    assert cost["hour_so_far"] == {"decisions": 0, "usd": "0.000000"}
    assert cost["ceilings"]["decisions_per_world_hour"] == 0
    # What these beings typically cost a simulated minute, from the same record, as an estimate.
    named = mind["steps"][0]["mind"]["subjects"]
    assert named == len(mind["steps"][0]["body"]["subjects"]) >= 1
    assert Decimal(cost["usd_typical"]) == (price * rate * named).quantize(Decimal("0.00000001"))
    assert Decimal(cost["usd_per_answer_typical"]) == price.quantize(Decimal("0.00000001"))
    assert cost["typical"]["rate_class"] == "estimate"


def test_a_model_nobody_measured_has_no_typical_figure_and_the_sheet_says_neither(companion):
    world, client, transport = companion
    society = minds._town(client, world)
    [knight] = minds._of_kind(society, "knight")
    people = minds._models_read(client, world)
    other = next(model for model in people["view"]["models"] if model["model_id"] != NANO)
    chosen = minds._choose(
        client, world, [knight], {"provider": other["provider"], "model_id": other["model_id"]}
    )
    assert chosen.status_code == 200, chosen.text
    labels = things._look(client, world, transport, SENTENCE)
    _draft(transport, things._label(labels, "0.50 US dollars an hour.", starts=True))
    [step] = things._ask(client, world, SENTENCE)["steps"]
    sheet = step["budget"]
    [model] = sheet["models"]
    assert model["model_id"] == other["model_id"]
    # Nothing is carried over from the model that was measured.
    assert model["usd_per_answer_typical"] is None and model["typical"] is None
    one = _bound(client, other["model_id"])
    assert sheet["answers_for_usd"] == {
        "at_most_price": int(Decimal("0.5") // one),
        "at_typical_price": None,
    }
    assert sheet["binds"]["at_typical_price"] is None and sheet["demand"] is None


def test_a_world_with_no_people_can_be_given_a_budget_and_the_sheet_names_no_model(companion):
    world, client, transport = companion
    labels = things._look(client, world, transport, "Let the minds make 900 decisions an hour")
    _draft(transport, things._label(labels, "900 model decisions an hour.", starts=True))
    plan = things._ask(client, world, "Let the minds make 900 decisions an hour")
    assert plan["outcome"] == "plan", things._why(plan)
    [step] = plan["steps"]
    sheet = step["budget"]
    assert (sheet["beings"], sheet["minded"], sheet["models"]) == (None, 0, [])
    assert sheet["answers_for_usd"] == {"at_most_price": None, "at_typical_price": None}
    assert sheet["binds"] == {"at_most_price": None, "at_typical_price": None}
    assert sheet["demand"] is None and sheet["named"] == ["decisions_per_hour"]
    sent = things._send(client, step)
    assert sent.status_code == 200 and sent.json()["budget"]["decisions_per_hour"] == 900


def _prepare(api, entry: dict, actions: list[dict]):
    root = f"/world/versions/{entry['authored_version_id']}?world_id={entry['world_id']}"
    base = api.get(root).json()["state_sha256"]
    return api.post(
        f"/selection/actions/prepare?world_id={entry['world_id']}",
        {
            "version_id": entry["authored_version_id"],
            "base_state_sha256": base,
            "actions": actions,
        },
    )


#: The identity of the one town this file makes: the take-in tests' own (``TOWN``), whose
#: streets leave the knight's place open. A town's seed is drawn from its identity, so a town
#: made with no fixed identity is another town every run: its people, its streets and where a
#: thing may stand all differ. With this identity the town is the same town each time.
TOWN_ID = TOWN


def test_a_living_town_takes_a_knight_in_by_the_plan_s_one_request(made, monkeypatch):
    api = made
    _offering_things(api)
    monkeypatch.setattr(saved_entries, "new_world_id", lambda _kind: TOWN_ID)
    entry, society, take_in = _town(api, "A town asked to take a knight in")
    assert entry["world_id"] == TOWN_ID
    created = api.post(
        society, {"region_id": entry["generated_ground"]["region_id"], "profile": V5}
    )
    assert created.status_code in (200, 201), created.text
    residents = [person["id"] for person in created.json()["state"]["inhabitants"]]

    # Nothing is placed: the plan refuses by the capability read's own code, as the route does.
    early = _prepare(api, entry, [{"operation": "take_in"}])
    assert early.status_code == 200, early.text
    refused = early.json()
    assert refused["outcome"] == "refused" and refused["steps"] == []
    assert refused["refusal"]["code"] == "action_unavailable"
    assert refused["refusal"]["capability"]["code"] == "nothing_to_take_in"
    direct = api.post(take_in, {})
    assert (direct.status_code, direct.json()["code"]) == (409, "nothing_to_take_in")

    # A budget asked for in a living town states this town's own head count on its sheet.
    budgeted = _prepare(
        api,
        entry,
        [
            {
                "operation": "set_minds_budget",
                "usd_per_hour": "0.500000",
                "decisions_per_hour": 700,
                "figures_named": ["usd_per_hour", "decisions_per_hour"],
            }
        ],
    )
    assert budgeted.status_code == 200, budgeted.text
    [budget_step] = budgeted.json()["steps"]
    assert budget_step["state"] == "prepared", budgeted.json()["refusal"]
    # The rule, whatever the town: the sheet's head count is the society's own.
    assert budget_step["budget"]["beings"] == len(residents) >= 1
    assert budget_step["budget"]["minded"] == 0

    east, _height, south = entry["generated_ground"]["arrival_mm"]
    _place(api, entry, "knight", "knight", 1, east - 2_000, south)
    assert _offered(api, entry) == ("available", None)
    before = _held(api, entry)
    prepared = _prepare(api, entry, [{"operation": "take_in"}])
    assert prepared.status_code == 200, prepared.text
    plan = prepared.json()
    assert plan["outcome"] == "plan", (plan["refusal"], plan["clarification"])
    assert plan["kind"] == "simulation" and plan["spends"] is False
    # Planning erased nothing and made nothing.
    assert _held(api, entry) == before
    [step] = plan["steps"]
    assert (step["operation"], step["state"], step["confirmation"]) == (
        TAKE_IN,
        "prepared",
        "required",
    )
    assert step["requires"] == ["deletion.write", "world.write"] and step["permitted"] is True
    assert step["erases"] == {
        "undo": False,
        "loses": list(TAKE_IN_LOSES),
        "keeps": list(TAKE_IN_KEEPS),
    }
    assert step["compensation"] is None and step["body"] == {}
    assert step["pins"]["tick"] == before["society"]["current_tick"]
    assert step["pins"]["society_state_sha256"] == before["society"]["state_sha256"]

    method, template = step["operation"].split(" ", 1)
    assert method == "POST"
    sent = api.post(
        template.format(**step["bind"]) + f"?world_id={step['query']['world_id']}", step["body"]
    )
    assert sent.status_code in (200, 201), sent.text
    taken = sent.json()
    assert taken["profile"] == V7
    # The same people, and the knight among them.
    populated = [p["id"] for p in taken["state"]["inhabitants"] if p["came_by"] == "populated"]
    assert populated == residents
    after = _held(api, entry)
    assert after["society"]["engine_version"] == V7
    assert (after["erasures"], after["tombstones"]) == (
        before["erasures"] + 1,
        before["tombstones"] + 1,
    )

    def outcome(steps: list[dict]):
        read = api.post(
            f"/selection/actions/outcome?world_id={entry['world_id']}",
            {
                "version_id": plan["version_id"],
                "plan_sha256": plan["plan_sha256"],
                "steps": steps,
            },
        )
        assert read.status_code == 200, read.text
        return read.json()

    answered = {**step, "answer": {"status": 200, "society_id": after["society"]["society_id"]}}
    read = outcome([answered])
    assert read["state"] == "applied"
    [receipt] = read["steps"][0]["receipts"]
    assert (receipt["society_id"], receipt["engine"]) == (after["society"]["society_id"], V7)
    # A step sent back with no answer, or naming another society, is never credited.
    assert outcome([step])["steps"][0]["state"] == "not_applied"
    stranger = {**step, "answer": {"status": 200, "society_id": str(uuid.uuid4())}}
    assert outcome([stranger])["steps"][0]["state"] == "not_applied"

    # Asked again: the town takes its newcomers in already, by the read's code and the route's.
    again = _prepare(api, entry, [{"operation": "take_in"}]).json()
    assert again["outcome"] == "refused" and again["steps"] == []
    assert again["refusal"]["code"] == "action_unsupported"
    assert again["refusal"]["capability"]["code"] == "society_takes_in_already"
    twice = api.post(take_in, {})
    assert (twice.status_code, twice.json()["code"]) == (409, "society_takes_in_already")
    assert _held(api, entry) == after
