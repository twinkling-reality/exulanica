"""The Companion's budget for a world's minds where every mind runs on a model on this computer.

An answer of a model on this computer costs nothing, so the most one answer can cost is nothing:
the dollars bound no number of answers and the decisions are what runs out. The sheet says so
(``answers_for_usd`` null at both prices, the decisions binding) instead of dividing by the price,
for a budget of money and for a budget of no money, under which the host still asks such a model
(:func:`exulanica.api.decision_host.hour_refusal` admits an ask whose bound is nothing). Through
the application and PostgreSQL, as ``test_companion_budget_postgres.py`` states a priced model's
sheet.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from exulanica.api.decision_host import hour_refusal
from exulanica.world.decision_roles import decision_roles
from exulanica.world.minds_budget import MindsBudget

import test_companion_budget_postgres as budget
import test_companion_minds_postgres as minds
import test_companion_things_postgres as things
from test_society_made_world import made as imported_made  # noqa: F401
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
NO_MONEY_BOUND = {"at_most_price": None, "at_typical_price": None}
DECISIONS_BIND = {"at_most_price": "decisions", "at_typical_price": "decisions"}
#: A budget of no money that names no decisions: they stay as the world has them.
NO_MONEY = "Let this town spend zero dollars an hour on minds"


def _sheet(client, world, transport, sentence: str, label: str) -> dict:
    labels = things._look(client, world, transport, sentence)
    budget._draft(transport, things._label(labels, label, starts=True))
    plan = things._ask(client, world, sentence)
    assert plan["outcome"] == "plan", things._why(plan)
    [step] = plan["steps"]
    return step


def test_a_sheet_where_every_mind_answers_for_nothing_is_bound_by_its_decisions_only(companion):
    world, client, transport = companion
    society = minds._town(client, world)
    [knight] = minds._of_kind(society, "knight")
    people = minds._models_read(client, world)
    # The positive control: this host offers a model on this computer, and its answer is free.
    free = [model for model in people["view"]["models"] if model["on_this_computer"]]
    assert free, "the host offers no model on this computer"
    [model] = free[:1]
    assert budget._bound(client, model["model_id"]) == 0
    chosen = minds._choose(
        client, world, [knight], {"provider": model["provider"], "model_id": model["model_id"]}
    )
    assert chosen.status_code == 200, chosen.text

    step = _sheet(client, world, transport, budget.SENTENCE, "0.50 US dollars an hour.")
    sheet = step["budget"]
    assert sheet["minded"] == 1
    [row] = sheet["models"]
    assert row["model_id"] == model["model_id"]
    assert Decimal(row["usd_per_answer_at_most"]) == 0
    decisions = sheet["asked"]["decisions_per_hour"]
    assert Decimal(sheet["asked"]["usd_per_hour"]) == Decimal("0.5") and decisions > 0
    assert sheet["answers_for_usd"] == NO_MONEY_BOUND
    assert sheet["binds"] == DECISIONS_BIND
    assert sheet["refused_now"] is None

    # The host's own rule agrees: asked one after another, its answers stop at the decisions,
    # never at the dollars, whatever the dollars are.
    role = decision_roles().role(minds._people_entry()["key"])
    contract = role.contract_for(things.V7)

    def admitted(usd: Decimal) -> int:
        asked, held = 0, MindsBudget(usd, decisions)
        while hour_refusal(asked, Decimal(0), Decimal(0), contract, held) is None:
            asked += 1
        return asked

    assert admitted(Decimal("0.5")) == admitted(Decimal(0)) == decisions

    # A budget of no money with decisions above none: the free model is still asked, and the
    # sheet says the same of it.
    labels = things._look(client, world, transport, NO_MONEY)
    nothing = things._label(labels, "0.00 US dollars an hour.", starts=True)
    budget._draft(transport, nothing)
    plan = things._ask(client, world, NO_MONEY)
    assert plan["outcome"] == "plan", things._why(plan)
    [zero] = plan["steps"]
    assert zero["body"]["usd_per_hour"] == "0.000000"
    assert zero["body"]["decisions_per_hour"] == decisions
    assert zero["budget"]["answers_for_usd"] == NO_MONEY_BOUND
    assert zero["budget"]["binds"] == DECISIONS_BIND
    assert zero["budget"]["refused_now"] is None
