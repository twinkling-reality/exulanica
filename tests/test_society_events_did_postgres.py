"""What a decision did, as the society events read serves it beside the event (private PostgreSQL).

A person on a saved world's square goes somewhere a scripted model chose for them; the minute that
applies the choice records a ``decision_applied`` event. The events read gives that event ``did``,
its chosen option in a History branch's shape, read from the decision's receipt and never stored, so
a person's day says what was done rather than the choice as offered. Other events carry none.
"""

from __future__ import annotations

import pytest
from exulanica.world.society_moments import load_rules, option_did

import test_society_stay_requests_api as stays
from test_society_decision_asks_postgres import _recorded, _Waiter
from test_society_person_decisions_postgres import _callers
from test_society_person_decisions_postgres import app as app
from test_society_person_decisions_postgres import saved_world as saved_world
from test_society_saved_world_api import routes

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_applied_decision_s_event_says_what_its_chosen_option_did(app) -> None:
    world, client = app
    _services, snapshot, receipt = _recorded(world, client, _Waiter())
    stays._step(world, client, snapshot)
    owner = _callers(client, world, listed=True)["owner"][0]
    scope, version, _society = routes(world)
    read = client.get(
        version + "/society/events",
        headers=owner,
        params={**scope, "kinds": ["decision_applied", "goal_selected"]},
    )
    assert read.status_code == 200, read.text
    events = read.json()["events"]
    applied = {
        e["document"]["request_id"]: e for e in events if e["event_kind"] == "decision_applied"
    }
    # The positive control: the minute applied the model's choice, and the receipt names a going.
    assert receipt["request_id"] in applied
    option = receipt["proposal"]["option"]
    assert option["kind"] == "target" and option["target_id"]
    event = applied[receipt["request_id"]]
    assert event["did"] == {
        "kind": "went",
        "target": {"target_id": option["target_id"], "activity": option["activity"]},
        "with": None,
    }
    # The stored document is served as recorded: nothing joined lands in it.
    assert "did" not in event["document"]
    assert all("did" in e for e in applied.values())
    assert all("did" not in e for e in events if e["event_kind"] != "decision_applied")


def test_a_walk_to_a_chosen_spot_is_a_going_and_another_unmapped_kind_says_none():
    rules = load_rules()
    point = {"kind": "point", "label": "walk to a spot you choose", "target_id": "node:1"}
    assert option_did(point, rules)["kind"] == "went_to_spot"
    assert (
        option_did({"kind": "juggle", "label": "juggle", "target_id": None}, rules)["kind"] is None
    )
    talk = {
        "kind": "talk",
        "label": "talk with Ines, 3 m away",
        "target_id": None,
        "partner_id": "b",
    }
    assert option_did(talk, rules) == {"kind": "talked", "target": None, "with": "b"}
