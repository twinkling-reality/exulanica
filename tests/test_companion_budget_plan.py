"""The Companion's budget for a world's minds and a town taking its newcomers in, without a
database or a model.

A drafted ``set_minds_budget`` step is typed from the amounts code read in the person's own
sentence and prepared as one request to the budget route; ``take_in`` is one request to the
take-in route, offered only where the capability read says so. What the planner holds by
construction is read here against independent sources: the request against the budget route's own
body model, the figures against the sentence written beside them, what a taking-in loses and keeps
against the list the route's owner stated, and the sheet's figures against a stand-in whose
answers the test states. What the real route and host answer is in
``tests/test_companion_budget_postgres.py``.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path

import pytest
from exulanica.api.routes.selection import _execution
from exulanica.api.routes.selection_actions import ActionPlanView, PrepareRequest
from exulanica.api.routes.world_models import MindsBudgetBody
from exulanica.selection import action_budget as budgets
from exulanica.selection import action_plan as plan
from exulanica.selection.action_plan import BUDGET, TAKE_IN

from test_companion_action_plan import _clock, _descriptor, _simulation_world
from test_companion_minds_plan import NANO, Checks, _label, _town
from test_companion_things_plan import VERSION, _context

SIM = plan.SimulationAction
#: What every world has before anyone sets a budget, as the stand-in states it.
DEFAULT = {"usd_per_hour": "0.250000", "decisions_per_hour": 600}


def _granted(_operation: str) -> tuple[list[str], bool]:
    return ["model.invoke", "world.write"], True


class Budgets(Checks):
    """A stand-in for the budget's reads (``Budgets``): the answers are the test's own. ``now``
    is the world's budget; a sheet is whatever the test says one is, with the budget now."""

    def __init__(self, *, usd="0.250000", decisions=600, seq=None, **more):
        super().__init__(**more)
        self.now = {
            "usd_per_hour": usd,
            "decisions_per_hour": decisions,
            "set_by_a_person": seq is not None,
            "budget_seq": seq,
        }
        self.sheets: list[tuple[str, int, int | None]] = []

    def budget(self):
        return {"now": dict(self.now), "default": dict(DEFAULT)}

    def budget_sheet(self, usd_per_hour, decisions_per_hour, beings):
        self.sheets.append((usd_per_hour, decisions_per_hour, beings))
        return {
            "now": dict(self.now),
            "asked": {"usd_per_hour": usd_per_hour, "decisions_per_hour": decisions_per_hour},
            "beings": beings,
            "binds": {"at_most_price": "usd", "at_typical_price": "decisions"},
        }


def _world(sentence: str | None, checks: Budgets | None = None, grant=_granted) -> plan._World:
    return plan._with_budget(_town(Budgets() if checks is None else checks), grant, sentence)


def _planned(world: plan._World, *options: str, more=()) -> dict:
    steps = [*more, {"operation": "set_minds_budget", "options": list(options)}]
    return plan._world_edit_document(
        plan._typed_from_draft(steps, world), _context(), world, previewer=None
    )


def _view(document: dict) -> None:
    ActionPlanView.model_validate(
        {**document, "execution": _execution((), (), prompt_version=plan.ACTION_PROMPT_VERSION)}
    )


# -- what the drafter is shown -------------------------------------------------------------------


def test_the_drafter_is_listed_the_amounts_of_the_sentence_and_the_two_budgets_with_no_figure():
    world = _world("Let this town spend up to 50 cents and 2000 decisions an hour on minds")
    assert [(choice.label, choice.title) for choice in world.amounts] == [
        ("amount-1", "0.50 US dollars an hour"),
        ("amount-2", "2000 model decisions an hour"),
        ("budget-nothing", "nothing"),
        ("budget-default", "the default"),
    ]
    # Each amount is shown with the person's own words for it, and every label is on the form.
    assert "50 cents" in world.amounts[0].detail and "2000 decisions" in world.amounts[1].detail
    assert {choice.label for choice in world.amounts} <= set(plan.iter_labels(world))
    assert "AMOUNTS THE REQUEST STATES" in plan._render_options(world)
    assert "set_minds_budget" in plan.DRAFT_OPERATIONS
    # A sentence that states no amount lists the two fixed budgets alone.
    assert [choice.label for choice in _world("Put a bench here").amounts] == [
        "budget-nothing",
        "budget-default",
    ]


# -- the step ------------------------------------------------------------------------------------


def test_a_budget_step_is_the_budget_route_s_request_with_what_it_comes_to():
    checks = Budgets(seq=3)
    world = _world("Let this town spend up to 50 cents an hour on minds", checks)
    document = _planned(world, "amount-1")
    assert document["outcome"] == "plan", document.get("refusal")
    [step] = document["steps"]
    assert (step["operation"], step["state"], step["confirmation"]) == (
        BUDGET,
        "prepared",
        "required",
    )
    assert step["bind"] == {"version_id": str(VERSION), "role_key": "society_decision"}
    # The request is the route's own body: exactly its fields, taken by its own model.
    sent = MindsBudgetBody.model_validate(step["body"])
    assert set(step["body"]) == set(MindsBudgetBody.model_fields)
    # Fifty cents is half a dollar; the decisions the words did not name stay the world's 600.
    assert (sent.usd_per_hour, sent.decisions_per_hour) == ("0.500000", 600)
    assert step["action"] == {
        "operation": "set_minds_budget",
        "usd_per_hour": "0.500000",
        "decisions_per_hour": 600,
        "figures_named": ["usd_per_hour"],
    }
    # Setting a budget asks no model; nothing undoes it but another budget.
    assert step["spends"] is False and document["spends"] is False
    assert step["compensation"] is None
    assert (step["replay"], step["receipt"]) == (
        "same_key_returns_the_recorded_budget",
        "minds_budget",
    )
    assert step["pins"] == {"budget_seq": 3}
    # The sheet's figures are the route's own, for this town's five beings, with what was named.
    assert checks.sheets == [("0.500000", 600, 5)]
    assert step["budget"]["named"] == ["usd_per_hour"]
    assert step["budget"]["binds"] == {"at_most_price": "usd", "at_typical_price": "decisions"}
    assert step["budget"]["now"]["budget_seq"] == 3
    _view(document)


def test_the_figures_are_the_sentence_s_whatever_the_draft_named():
    """A drafter that names the wrong listed option, or none, cannot move a figure: where the
    words state an amount, that amount is the budget, or the figure is asked for."""
    world = _world("Let the minds make 1,200 decisions an hour")
    for options in ((), ("amount-1",)):
        [step] = _planned(world, *options)["steps"]
        assert (step["body"]["usd_per_hour"], step["body"]["decisions_per_hour"]) == (
            "0.250000",
            1200,
        ), options
        assert step["action"]["figures_named"] == ["decisions_per_hour"]
    # A draft that names a budget with no figure beside an amount the words state is asked
    # about: neither the amount nor the fixed budget is planned.
    for options in (("budget-nothing",), ("budget-default",), ("amount-1", "budget-nothing")):
        document = _planned(world, *options)
        assert document["outcome"] == "clarify" and document["steps"] == [], options
        assert document["clarification"]["code"] == "budget_required"


def test_both_figures_named_in_one_sentence_are_one_step():
    world = _world("Give the minds a dollar and 3000 answers an hour")
    document = plan._world_edit_document(
        plan._typed_from_draft(
            [
                {"operation": "set_minds_budget", "options": ["amount-1"]},
                {"operation": "set_minds_budget", "options": ["amount-2"]},
            ],
            world,
        ),
        _context(),
        world,
        previewer=None,
    )
    [step] = document["steps"]
    assert (step["body"]["usd_per_hour"], step["body"]["decisions_per_hour"]) == ("1.000000", 3000)
    assert step["action"]["figures_named"] == ["usd_per_hour", "decisions_per_hour"]


@pytest.mark.parametrize(
    ("option", "figures"),
    [("budget-nothing", ("0.000000", 0)), ("budget-default", ("0.250000", 600))],
)
def test_a_budget_with_no_figure_is_the_one_the_draft_and_the_sentence_both_name(option, figures):
    sentence = {
        "budget-nothing": "Spend nothing on minds",
        "budget-default": "Put the minds budget back to its default",
    }
    # The world's budget is another, so both are a change.
    held = Budgets(usd="2.000000", decisions=50, seq=1)
    [step] = _planned(_world(sentence[option], held), option)["steps"]
    assert (step["body"]["usd_per_hour"], step["body"]["decisions_per_hour"]) == figures
    assert step["action"]["figures_named"] == ["usd_per_hour", "decisions_per_hour"]
    # The same draft over the other sentence is asked for its figure: the model's choice alone
    # is no budget.
    for other in set(sentence) - {option}:
        document = _planned(_world(sentence[other], held), option)
        assert document["outcome"] == "clarify" and document["steps"] == []
        assert document["clarification"]["code"] == "budget_required"


@pytest.mark.parametrize(
    ("sentence", "code"),
    [
        # A span that is not one hour, said in the plural, with a count or by a short form.
        ("Let the town spend 10 dollars every 24 hours", "budget_period"),
        ("$50 for 30 days", "budget_period"),
        ("20 dollars for 2 weeks", "budget_period"),
        ("5 dollars over the next few days", "budget_period"),
        ("$1 per 10 minutes", "budget_period"),
        ("5 dollars for today", "budget_period"),
        ("$0.01/min", "budget_period"),
        # A number said in passing, in a sentence that asks for nothing or the default.
        ("The minds cost me 3 dollars yesterday, turn them off", "budget_required"),
        ("I was charged $4, stop the AI spending", "budget_required"),
        ("I paid 2 dollars already, put the budget back to default", "budget_required"),
        # Number words joined by "and" or "to".
        ("allow one hundred and twenty decisions an hour", "budget_required"),
        ("a hundred and fifty dollars an hour", "budget_required"),
        ("a dollar and a half an hour", "budget_required"),
        ("a dollar and 25 cents an hour", "budget_required"),
        ("fifty to sixty cents an hour", "budget_required"),
        ("between one and two dollars an hour", "budget_required"),
        # The two budgets with no figure, where the sentence states neither.
        ("No limit on the minds", "budget_required"),
        ("make it cheaper", "budget_required"),
    ],
)
def test_a_sentence_the_money_review_found_planned_wrongly_is_asked_about_whatever_the_draft(
    sentence, code
):
    """Each of these was planned as a budget the person did not state. Whichever listed options
    a draft names, the plan is now a question and holds no step and no figure."""
    world = _world(sentence, Budgets(seq=2))
    listed = [choice.label for choice in world.amounts]
    drafts = [(), *((label,) for label in listed), tuple(listed)]
    for options in drafts:
        document = _planned(world, *options)
        assert document["outcome"] == "clarify" and document["steps"] == [], (sentence, options)
        asked = document["clarification"]
        assert asked["code"] in (code, "budget_required"), (sentence, options, asked["code"])
        assert asked["actions"][0]["usd_per_hour"] is None
        assert asked["actions"][0]["decisions_per_hour"] is None
    # With no fixed budget named, the question is the one the words call for.
    assert _planned(world)["clarification"]["code"] == code


def test_a_planned_budget_is_held_to_the_budget_it_was_planned_against():
    """A figure the words did not name is the world's as it stood at the plan: the request
    names that budget's sequence, so one set since refuses it instead of being put back."""
    [step] = _planned(_world("Let the minds spend 50 cents an hour", Budgets(seq=3)), "amount-1")[
        "steps"
    ]
    assert step["body"]["after_budget_seq"] == 3
    # A world nobody set a budget for is held to there being none.
    [first] = _planned(_world("Let the minds spend 50 cents an hour"), "amount-1")["steps"]
    assert first["body"]["after_budget_seq"] == 0
    assert MindsBudgetBody.model_validate(first["body"]).after_budget_seq == 0


@pytest.mark.parametrize(
    "sentence",
    [
        # A span, a total, a part of the day that no span word names.
        "Let the minds spend 5 dollars for 24h",
        "Give the town a total of 20 dollars for its minds",
        "This afternoon the minds may spend 3 dollars",
        "5 dollars until Friday",
        # A report of the past whose verb is on no list.
        "That cost 3 dollars! Turn it down.",
        "It made only 5 decisions, raise the budget to 2 dollars an hour",
        # A rate for each being, said after the hour.
        "50 cents an hour each",
        "2 dollars an hour per being",
        # The sentence's own off, reset and not, with a draft that names no fixed budget.
        "Turn the minds off, 3 dollars is too much",
        "Reset the budget, 5 dollars an hour is too high",
        "make it 25, not 50 cents",
        "I don't want to pay 5 dollars an hour",
        # A figure with an end, a floor, the world's own time after the hour.
        "2 dollars an hour for the next 3 hours",
        "at least a dollar",
        "50 cents an hour of game time",
        "5 dollars per hour and a half",
        # Words in another script, and a sign that makes the figure a change.
        "$50 \u0432 \u043d\u0435\u0434\u0435\u043b\u044e",
        "+50 cents an hour",
        # A figure for everyone, or for each of something, is not the world's budget.
        "Give everyone a dollar an hour",
        "Give every knight a dollar an hour",
        # An hour that ends, a report in the present, a move with no end.
        "Let the minds spend 5 dollars for just this one hour",
        "The minds spend 3 dollars an hour",
        "Lower the budget from 2 dollars",
    ],
)
def test_a_sentence_that_is_none_of_the_shapes_is_asked_about_whatever_the_draft(sentence):
    """Sentences three readings found planned as a figure nobody stated. The reader plans only a
    sentence the whole of which is one of the shapes, so each is a question with no step and no
    figure under every draft the form allows: none, each listed option alone, and all of them."""
    world = _world(sentence, Budgets(seq=2))
    assert world.said_shape is None, sentence
    listed = [choice.label for choice in world.amounts]
    for options in [(), *((label,) for label in listed), tuple(listed)]:
        document = _planned(world, *options)
        assert document["outcome"] == "clarify" and document["steps"] == [], (sentence, options)
        asked = document["clarification"]
        assert asked["code"] in ("budget_required", "budget_period"), (sentence, asked["code"])
        assert asked["actions"][0]["usd_per_hour"] is None
        assert asked["actions"][0]["decisions_per_hour"] is None


@pytest.mark.parametrize("sentence", ["take the limit off", "turn the cap off", "No limit, off"])
def test_a_limit_taken_off_is_never_planned_as_a_budget_of_nothing(sentence):
    world = _world(sentence, Budgets(usd="2.000000", decisions=50, seq=1))
    for options in ((), ("budget-nothing",), ("budget-default",)):
        document = _planned(world, *options)
        assert document["outcome"] == "clarify" and document["steps"] == [], (sentence, options)


def test_a_figure_the_words_did_not_name_is_the_world_s_when_a_typed_budget_is_read():
    """A question answered later, or a later step prepared again, carries the figure the person
    did not name as it stood when the step was made. It is read again from the budget now, so
    what somebody set in between is kept and not put back."""
    held = Budgets(usd="0.250000", decisions=600, seq=1)
    world = _world("Let the minds spend 50 cents an hour", held)
    [step] = _planned(world, "amount-1")["steps"]
    assert (step["body"]["decisions_per_hour"], step["pins"]) == (600, {"budget_seq": 1})
    # Somebody sets the decisions to 100 while the sheet is open.
    held.now.update({"decisions_per_hour": 100, "budget_seq": 2})
    typed = plan._typed_from_request([step["action"]], world)
    [again] = plan._world_edit_document(typed, _context(), world, previewer=None)["steps"]
    assert (again["body"]["usd_per_hour"], again["body"]["decisions_per_hour"]) == ("0.500000", 100)
    # Its pins name the budget it is now held to, which is how the page sees it has moved.
    assert again["pins"] == {"budget_seq": 2} and again["body"]["after_budget_seq"] == 2
    # A figure the person named is theirs, whatever the world's is now.
    held.now.update({"usd_per_hour": "3.000000", "budget_seq": 3})
    [named] = plan._world_edit_document(
        plan._typed_from_request([step["action"]], world), _context(), world, previewer=None
    )["steps"]
    assert named["body"]["usd_per_hour"] == "0.500000"
    # A typed budget that names no figure is taken as sent (a client's own two figures).
    both = {**step["action"], "figures_named": [], "decisions_per_hour": 700}
    [sent] = plan._world_edit_document(
        plan._typed_from_request([both], world), _context(), world, previewer=None
    )["steps"]
    assert sent["body"]["decisions_per_hour"] == 700


def test_a_figure_the_budget_s_record_cannot_hold_is_asked_for_and_not_refused_at_send():
    for sentence in (
        "Let the minds spend 5,000,000 dollars an hour",
        "Allow 9,000,000,000 decisions an hour",
    ):
        document = _planned(_world(sentence), "amount-1")
        assert document["outcome"] == "clarify" and document["steps"] == [], sentence
        assert document["clarification"]["code"] == "budget_required"


# -- what is asked first, never guessed ----------------------------------------------------------


def test_a_sentence_that_states_no_amount_is_asked_for_the_figure():
    world = _world("Let the minds spend more")
    for options in ((), ("budget-nothing", "budget-default")):
        document = _planned(world, *options)
        assert document["outcome"] == "clarify"
        asked = document["clarification"]
        assert (asked["code"], asked["slot"], asked["candidates"]) == ("budget_required", None, [])
        assert asked["actions"][0]["usd_per_hour"] is None
        # The question carries the budget the world has now, for the page's words.
        # (A quarter of a dollar is 250,000 millionths.)
        assert asked["facts"] == {"usd_per_hour_microusd": 250_000, "decisions_per_hour": 600}
        _view(document)


@pytest.mark.parametrize(
    "sentence",
    [
        "Raise the minds budget by 50 cents an hour",
        "Let the minds spend a dollar fifty an hour",
        "Give the minds 20 cents more an hour",
    ],
)
def test_a_change_or_a_split_figure_is_asked_for_its_amount_and_never_planned(sentence):
    """What code read is fifty cents, a dollar, twenty cents: none is what the person means, so
    none becomes a budget whatever the draft names."""
    world = _world(sentence)
    assert "do not state plainly" in world.amounts[0].title
    for options in ((), ("amount-1",)):
        document = _planned(world, *options)
        assert document["outcome"] == "clarify" and document["steps"] == []
        assert document["clarification"]["code"] == "budget_required"


def test_a_range_is_asked_about_between_its_two_ends():
    world = _world("Let the minds spend 50 to 60 cents an hour")
    asked = _planned(world, "amount-1")["clarification"]
    assert (asked["code"], asked["slot"]) == ("budget_ambiguous", "usd_per_hour")
    assert [c["value"] for c in asked["candidates"]] == ["0.500000", "0.600000"]


def test_an_amount_over_another_span_is_asked_about_and_never_converted():
    world = _world("Let the minds spend 5 dollars a day")
    document = _planned(world, "amount-1")
    assert document["outcome"] == "clarify"
    assert document["clarification"]["code"] == "budget_period"
    # No figure was worked out of the day's five dollars.
    assert document["clarification"]["actions"][0] == {
        "operation": "set_minds_budget",
        "usd_per_hour": None,
        "decisions_per_hour": None,
        "figures_named": [],
    }
    assert document["steps"] == []


def test_two_amounts_of_one_kind_are_asked_about_and_the_answer_is_the_plan():
    world = _world("Let the minds spend 30 cents or 50 cents an hour")
    document = _planned(world, "amount-1", "amount-2")
    assert document["outcome"] == "clarify"
    asked = document["clarification"]
    assert (asked["code"], asked["slot"]) == ("budget_ambiguous", "usd_per_hour")
    assert [(c["value"], c["title"]) for c in asked["candidates"]] == [
        ("0.300000", "0.30 US dollars an hour"),
        ("0.500000", "0.50 US dollars an hour"),
    ]
    # The answer comes back as typed actions through the route's own body model.
    answered = {**asked["actions"][0], "usd_per_hour": "0.500000"}
    body = PrepareRequest.model_validate(
        {"version_id": str(VERSION), "base_state_sha256": "a" * 64, "actions": [answered]}
    )
    typed = plan._typed_from_request([body.actions[0].model_dump()], world)
    [step] = plan._world_edit_document(typed, _context(), world, previewer=None)["steps"]
    assert (step["body"]["usd_per_hour"], step["body"]["decisions_per_hour"]) == ("0.500000", 600)


def test_the_amount_the_world_already_has_is_the_one_a_sentence_moves_from():
    world = _world("Raise the minds budget from 25 cents to 75 cents an hour")
    [step] = _planned(world, "amount-1", "amount-2")["steps"]
    assert step["body"]["usd_per_hour"] == "0.750000"


def test_two_counts_are_asked_about_and_a_count_comes_back_as_its_text():
    world = _world("Allow 800 decisions an hour, or 900 decisions an hour")
    asked = _planned(world)["clarification"]
    assert (asked["code"], asked["slot"]) == ("budget_ambiguous", "decisions_per_hour")
    assert [c["value"] for c in asked["candidates"]] == ["800", "900"]
    body = PrepareRequest.model_validate(
        {
            "version_id": str(VERSION),
            "base_state_sha256": "a" * 64,
            "actions": [{**asked["actions"][0], "decisions_per_hour": "900"}],
        }
    )
    typed = plan._typed_from_request([body.actions[0].model_dump()], world)
    assert typed.actions[0].decisions_per_hour == 900


# -- what is refused -----------------------------------------------------------------------------


def test_the_budget_the_world_already_has_is_no_change():
    world = _world("Let the minds spend 25 cents an hour")
    document = _planned(world, "amount-1")
    assert document["outcome"] == "refused"
    assert document["refusal"]["code"] == "preview_blocked"
    [step] = document["steps"]
    assert (step["state"], step["code"], step["body"]) == ("blocked", "no_change", None)


def test_a_typed_budget_is_checked_as_the_route_s_body_is():
    world = _world(None)
    for raw in (
        {"usd_per_hour": "-0", "decisions_per_hour": 5},
        {"usd_per_hour": "0.1234567", "decisions_per_hour": 5},
        {"usd_per_hour": "1", "decisions_per_hour": -1},
        {"usd_per_hour": "1", "decisions_per_hour": 2**31},
    ):
        verdict = plan._typed_from_request([{"operation": "set_minds_budget", **raw}], world)
        assert verdict.refusal is not None and verdict.refusal["code"] == "not_understood", raw
    # A figure left open is asked for, not refused.
    typed = plan._typed_from_request(
        [{"operation": "set_minds_budget", "usd_per_hour": None, "decisions_per_hour": 5}], world
    )
    asked = plan._requirements(typed.actions, _context(), world)
    assert asked is not None and asked["code"] == "budget_required"


def test_the_step_is_offered_only_where_the_route_hands_it_and_the_grant_holds_it():
    sentence = "Let the minds spend 50 cents an hour"
    # No budget is handed: the form's operation is refused by name, not approximated.
    bare = _town(Budgets())
    unstated = {key: value for key, value in bare.descriptors.items() if key != BUDGET}
    refused = _planned(
        dataclasses.replace(bare, descriptors=unstated, said_amounts=budgets.amounts(sentence))
    )
    assert refused["refusal"]["code"] == "action_not_offered"
    denied = _planned(_world(sentence, grant=lambda _op: (["model.invoke", "world.write"], False)))
    assert denied["refusal"]["code"] == "action_not_permitted"
    assert denied["refusal"]["capability"]["requires"] == ["model.invoke", "world.write"]


# -- the key -------------------------------------------------------------------------------------


def test_the_key_follows_the_world_s_newest_budget_the_figures_and_who_asks():
    asked = ("world:a", "society_decision", 3, "0.500000", 600)
    one, other = uuid.UUID(int=1), uuid.UUID(int=2)
    assert budgets.budget_key(*asked, one) == budgets.budget_key(*asked, one)
    assert len({budgets.budget_key(*asked, actor) for actor in (one, other, None)}) == 3
    moved = [
        ("world:b", "society_decision", 3, "0.500000", 600),
        ("world:a", "society_decision", 4, "0.500000", 600),
        ("world:a", "society_decision", 3, "0.500001", 600),
        ("world:a", "society_decision", 3, "0.500000", 601),
    ]
    assert len({budgets.budget_key(*item, one) for item in [asked, *moved]}) == 5
    # The step's own key: the same plan asks with the same key, and after another setting a new one.
    sentence = "Let the minds spend 50 cents an hour"
    keys = [
        _planned(_world(sentence, Budgets(seq=seq)), "amount-1")["steps"][0]["body"][
            "idempotency_key"
        ]
        for seq in (None, None, 1)
    ]
    assert keys[0] == keys[1] != keys[2]


# -- with a choice of minds in one request -------------------------------------------------------


def test_a_budget_after_a_mind_states_what_it_comes_to_before_the_one_yes():
    world = _world("Give every villager Nano and let the minds spend a dollar an hour")
    more = [
        {
            "operation": "choose_mind",
            "options": [
                _label(world.groups, "kind:villager"),
                _label(world.mind_choices, f"model:{NANO.provider}/{NANO.model_id}"),
            ],
        }
    ]
    # A sentence that also asks for something else holds words the budget's vocabulary does not
    # account for (a villager, a model's name), so the budget's figure is asked for and the plan
    # is a question that keeps both steps.
    drafted = _planned(world, "amount-1", more=more)
    assert drafted["outcome"] == "clarify" and drafted["steps"] == []
    asked = drafted["clarification"]
    assert (asked["code"], asked["step"]) == ("budget_required", 1)
    mind, budget = asked["actions"]
    assert mind["operation"] == "choose_mind"
    assert (budget["usd_per_hour"], budget["decisions_per_hour"]) == (None, None)
    # Answered with the figure, the two steps are one plan under one yes.
    answered = {**budget, "usd_per_hour": "1.000000", "decisions_per_hour": 600}
    answered["figures_named"] = ["usd_per_hour"]
    typed = plan._typed_from_request([mind, answered], world)
    document = plan._world_edit_document(typed, _context(), world, previewer=None)
    assert document["outcome"] == "plan", document.get("refusal")
    first, second = document["steps"]
    assert (first["action"]["operation"], first["state"]) == ("choose_mind", "prepared")
    # The budget waits for the mind's receipt, with its figures and its sheet already stated,
    # and no request to send until it is prepared again.
    assert (second["operation"], second["state"], second["body"]) == (BUDGET, "pending", None)
    assert second["action"]["usd_per_hour"] == "1.000000"
    assert second["budget"]["asked"] == {"usd_per_hour": "1.000000", "decisions_per_hour": 600}
    assert second["spends"] is False
    _view(document)
    # Prepared again from its typed action, it is the request, with the same figures.
    typed = plan._typed_from_request([second["action"]], world)
    [again] = plan._world_edit_document(typed, _context(), world, previewer=None)["steps"]
    assert again["body"]["usd_per_hour"] == "1.000000" and again["state"] == "prepared"


def test_a_sentence_that_also_gives_a_mind_plans_both_where_the_draft_names_what_it_says():
    """The names code holds for the options the draft's other step named (a group's title and
    label, a mind's title) may stand in that step's clause of the sentence, so the plain budget
    after them is planned."""
    sentence = "Give every knight Nano and let the minds spend a dollar an hour"
    world = _world(sentence)
    mind = {
        "operation": "choose_mind",
        "options": [
            _label(world.groups, "kind:knight"),
            _label(world.mind_choices, f"model:{NANO.provider}/{NANO.model_id}"),
        ],
    }
    budget = {"operation": "set_minds_budget", "options": ["amount-1"]}

    def drafted(steps, said=sentence):
        typed = plan._typed_from_draft(steps, world, said)
        return plan._world_edit_document(typed, _context(), world, previewer=None)

    document = drafted([mind, budget])
    assert document["outcome"] == "plan", document.get("refusal")
    first, second = document["steps"]
    assert first["action"]["operation"] == "choose_mind"
    assert second["action"]["usd_per_hour"] == "1.000000"
    # The same sentence with a draft that names no such options is no shape: a model cannot make
    # a word a name by anything but naming a listed option in another step.
    alone = drafted([budget])
    assert alone["outcome"] == "clarify" and alone["clarification"]["code"] == "budget_required"
    # Named in the budget's own step they are no other step's, and are no names.
    crowded = plan._typed_from_draft(
        [{**budget, "options": [*budget["options"], *mind["options"]]}], world, sentence
    )
    assert [action.budget_question for action in crowded.actions] == ["budget_required"]
    # Naming the mind and not the group leaves the group's words outside.
    other = {"operation": "choose_mind", "options": [mind["options"][1]]}
    partly = plan._typed_from_draft([other, budget], world, sentence)
    assert [
        action.budget_question
        for action in partly.actions
        if action.operation.value == "set_minds_budget"
    ] == ["budget_required"]
    # A doubt beside the names is still a doubt: a day's figure is asked about by the hour.
    daily = "Give every knight Nano and let the minds spend a dollar a day"
    asked = plan._world_edit_document(
        plan._typed_from_draft([mind, budget], _world(daily), daily),
        _context(),
        world,
        previewer=None,
    )
    assert asked["outcome"] == "clarify" and asked["clarification"]["code"] == "budget_period"


@pytest.mark.parametrize(
    ("sentence", "option", "figures"),
    [
        ("Spend nothing on minds", "budget-nothing", ("0.000000", 0)),
        ("Put the minds budget back to the default", "budget-default", ("0.250000", 600)),
    ],
)
def test_a_budget_step_s_own_option_is_no_name_that_hides_the_sentence_s_word(
    sentence, option, figures
):
    """The option a budget step names ("nothing", "the default") is the budget's own, not a name
    of something another step acts on: the sentence's word for it is still read as that word."""
    world = _world(sentence, Budgets(usd="2.000000", decisions=50, seq=1))
    typed = plan._typed_from_draft(
        [{"operation": "set_minds_budget", "options": [option]}], world, sentence
    )
    [step] = plan._world_edit_document(typed, _context(), world, previewer=None)["steps"]
    assert (step["body"]["usd_per_hour"], step["body"]["decisions_per_hour"]) == figures


def test_a_step_that_holds_no_request_reads_back_as_not_applied():
    from exulanica.selection import action_outcome

    step = {
        "index": 1,
        "operation": BUDGET,
        "state": "pending",
        "body": None,
        "bind": {"role_key": "society_decision"},
        "answer": {"status": 200, "budget_seq": 3},
    }
    found = action_outcome._budget_step(None, None, "world:test", step)
    assert (found["index"], found["state"], found["receipts"]) == (1, "not_applied", [])


# -- a living town takes its newcomers in --------------------------------------------------------

#: What the taking-in loses and keeps, as the route's owner stated it for the sheet: the day so
#: far and the clock's position; whether the town was playing and its speed; the models chosen
#: for people; the looks a person saved for residents; comparisons and experiments run from that
#: society; the Companion's answers about it. Kept: the same people with their homes, jobs, roles
#: and shifts; the world; everything placed; door grants and programs; the world's look.
LOSES = [
    "day_so_far",
    "clock_position",
    "playing_and_speed",
    "models_chosen",
    "looks_saved_for_residents",
    "comparisons_and_experiments",
    "companion_answers",
]
KEEPS = [
    "people_homes_jobs_roles_shifts",
    "world",
    "things_placed",
    "door_grants_and_programs",
    "world_look",
]


def _take_in(world: plan._World, clock: dict | None = None) -> dict:
    return plan.simulation_document(
        plan._Simulation(SIM.TAKE_IN), _context(), world, clock or _clock(), plan.TimeSpending()
    )


def test_taking_newcomers_in_is_the_take_in_route_s_request_with_the_loss_stated():
    world = _simulation_world(**{TAKE_IN: _descriptor(TAKE_IN)})
    document = _take_in(world)
    assert document["outcome"] == "plan", document.get("refusal")
    assert document["kind"] == "simulation" and document["spends"] is False
    # It is alone in its plan, under its own yes.
    [step] = document["steps"]
    assert (step["operation"], step["state"], step["confirmation"]) == (
        TAKE_IN,
        "prepared",
        "required",
    )
    # The route takes no body, and the version in its path.
    assert step["body"] == {} and step["bind"] == {"version_id": str(world.version_id)}
    assert step["erases"] == {"undo": False, "loses": LOSES, "keeps": KEEPS}
    # Nothing undoes it, and asked again the route refuses.
    assert step["compensation"] is None
    assert (step["replay"], step["receipt"]) == ("asked_again_is_refused", "society_taken_in")
    # The minute the day would be lost at, for the sheet's words.
    assert step["pins"] == {"clock_revision": 0, "tick": 12, "society_state_sha256": "b" * 64}
    assert step["action"]["operation"] == "take_in"
    _view(document)


@pytest.mark.parametrize(
    ("state", "code", "refusal"),
    [
        ("unavailable", "society_unavailable", "action_unavailable"),
        ("unavailable", "nothing_to_take_in", "action_unavailable"),
        ("unavailable", "unavailable_society_input", "action_unavailable"),
        ("unsupported", "society_takes_in_already", "action_unsupported"),
    ],
)
def test_it_is_refused_by_the_capability_read_s_own_code_wherever_the_route_would_refuse(
    state, code, refusal
):
    stated = {**_descriptor(TAKE_IN), "state": state, "code": code}
    document = _take_in(_simulation_world(**{TAKE_IN: stated}))
    assert document["outcome"] == "refused" and document["steps"] == []
    assert document["refusal"]["code"] == refusal
    assert document["refusal"]["capability"]["code"] == code


def test_it_is_not_offered_where_no_capability_states_it_or_the_grant_does_not_hold_it():
    assert _take_in(_simulation_world())["refusal"]["code"] == "action_not_offered"
    held = {**_descriptor(TAKE_IN), "permitted": False}
    denied = _take_in(_simulation_world(**{TAKE_IN: held}))
    assert denied["refusal"]["code"] == "action_not_permitted"


def test_no_other_refusal_suggests_an_erasure():
    """People asked for where a living society already stands is refused as before, and names no
    alternative, whatever the capability read says the town could take in."""
    world = _simulation_world(**{TAKE_IN: _descriptor(TAKE_IN)})
    refused = plan.simulation_document(
        plan._Simulation(SIM.BRING_PEOPLE), _context(), world, _clock(), plan.TimeSpending()
    )
    assert refused["refusal"]["code"] == "no_change"
    assert refused["refusal"]["alternatives"] == []


def test_the_typed_request_is_taken_alone_by_the_route_s_body_model():
    body = PrepareRequest.model_validate(
        {
            "version_id": str(VERSION),
            "base_state_sha256": "a" * 64,
            "actions": [{"operation": "take_in"}],
        }
    )
    assert body.actions[0].operation == "take_in"
    assert "take_in" in plan.SIMULATION_OPERATIONS


def test_a_taking_in_never_answered_reads_back_as_not_applied():
    from exulanica.selection import action_outcome

    session = type("Session", (), {"workspace_id": uuid.UUID(int=1)})()
    step = {"index": 0, "operation": TAKE_IN, "state": "prepared", "body": {}}

    class Held:
        def execute(self, *_arguments):
            return self

        def fetchone(self):
            return {
                "society_id": uuid.UUID(int=9),
                "region_id": "region:town",
                "engine_version": "exulanica-society/v5",
            }

    found = action_outcome._take_in_step(Held(), session, "world:test", VERSION, step)
    assert found["state"] == "not_applied"
    # Answered by name, but the version's society is still a living one: not applied.
    answered = {**step, "answer": {"status": 200, "society_id": str(uuid.UUID(int=9))}}
    found = action_outcome._take_in_step(Held(), session, "world:test", VERSION, answered)
    assert found["state"] == "not_applied"


# -- the plans the page's tests keep ---------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
KEPT = ROOT / "web/packages/app/test/companion-plans"
#: A whole sheet in the shape the application serves one
#: (``exulanica.api.mind_offer.WorldMinds.budget_sheet``; the PostgreSQL test holds the two to
#: the same members), for a town of five where one model decides for two: half a dollar pays for
#: 161 answers at the most one can cost here (0.0031 dollars) and 1,765 at the typical price.
SHEET = {
    "default": {**DEFAULT, "set_by_a_person": False},
    "hour_so_far": {"decisions": 12, "usd": "0.003400"},
    "left_this_hour": {"decisions": 588, "usd": "0.496600"},
    "minded": 2,
    "models": [
        {
            "provider": NANO.provider,
            "model_id": NANO.model_id,
            "name": NANO.name,
            "beings": 2,
            "usd_per_answer_at_most": "0.00310000",
            "usd_per_answer_typical": "0.00028162",
            "typical": {"rate_class": "estimate", "price_class": "measured"},
        }
    ],
    "answers_for_usd": {"at_most_price": 161, "at_typical_price": 1765},
    "binds": {"at_most_price": "usd", "at_typical_price": "decisions"},
    "demand": {
        "simulated_minutes_per_real_hour": 450,
        "minded": {"beings": 2, "asks_per_real_hour": 233, "minutes_covered": 60},
        "everyone": {"beings": 5, "asks_per_real_hour": 582, "minutes_covered": 60},
        "rate_class": "estimate",
    },
    "refused_now": None,
    "host": {"refusal": None, "allowance": None, "allowance_below_an_hour_of_budget": None},
}


class Sheets(Budgets):
    """The stand-in with a whole sheet, for the plans the page's tests read."""

    def budget_sheet(self, usd_per_hour, decisions_per_hour, beings):
        return {
            **SHEET,
            "now": {**self.now, "set_by_you": False},
            "asked": {
                "usd_per_hour": usd_per_hour,
                "decisions_per_hour": decisions_per_hour,
                "hour": "real_time",
            },
            "beings": beings,
        }


def kept_plans() -> dict[str, dict]:
    """The plans the page's tests keep, as the planner makes them now and the route's view serves
    them: a budget, the question a sentence with no figure is asked, and a taking-in."""
    budget = _planned(
        _world("Let this town spend up to 50 cents an hour on minds", Sheets()), "amount-1"
    )
    question = _planned(_world("Let the minds spend more", Sheets()))
    taking = _take_in(_simulation_world(**{TAKE_IN: _descriptor(TAKE_IN)}))
    served = {}
    for name, document in (
        ("budget-plan", budget),
        ("budget-question", question),
        ("take-in-plan", taking),
    ):
        execution = _execution((), (), prompt_version=plan.ACTION_PROMPT_VERSION)
        view = ActionPlanView.model_validate({**document, "execution": execution})
        served[name] = view.model_dump(mode="json")
    return served


def test_the_plans_the_page_s_tests_keep_are_the_ones_the_planner_makes_now():
    for name, document in kept_plans().items():
        kept = json.loads((KEPT / f"{name}.json").read_text())
        assert kept == document, f"{name}.json is stale: write it again from kept_plans()"
