"""The Companion's choice of a mind, without a database or a model.

A drafted ``choose_mind`` step is typed from the options it names (a being or a group, and a mind)
and prepared as one request to the models route. What the planner holds by construction is read
here against independent sources: the groups against a society state written by hand, the request
against the models route's own body model, the question and the refusals against a stand-in for the
choice record's checks whose answers the test states. What the real checks answer, and that the
route takes the request, is in ``tests/test_companion_minds_postgres.py``. The world is the things
plan tests' (``test_companion_things_plan``).
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path

import pytest
from exulanica.api.routes.selection import _execution
from exulanica.api.routes.selection_actions import ActionPlanView, PrepareRequest
from exulanica.api.routes.world_models import RoleChoiceBody
from exulanica.selection import action_minds as minds
from exulanica.selection import action_plan as plan
from exulanica.selection.action_plan import MIND
from exulanica.selection.action_plan import WorldEditOperation as Op

from test_companion_things_plan import VERSION, _context, _read, _world

ROOT = Path(__file__).resolve().parents[1]
NANO = minds.MindChoice("nebius_token_factory", "example/nano", "Nano", "A small open model.")
ULTRA = minds.MindChoice("nebius_token_factory", "example/ultra", "Ultra", "A large open model.")
BOUND = 8


def _newest(kind: str) -> int:
    lock = json.loads((ROOT / "assets/catalogs/things/kinds.lock.json").read_text())
    return max(row["version"] for row in lock["kinds"] if row["kind"] == kind)


def _person(number: int, kind: str | None, role=None, **more) -> dict:
    return {
        "id": str(uuid.UUID(int=number)),
        "display_name": f"{kind or 'person'} {number}",
        "kind": None if kind is None else {"kind": kind, "version": _newest(kind)},
        "role": role,
        **more,
    }


#: A society of things written by hand: three villagers, a knight and a lantern spirit, in the
#: order they stand in its state. Their ids are 1 to 5.
TOWN = {
    "inhabitants": [
        _person(1, "villager", "villager"),
        _person(2, "villager", "villager"),
        _person(3, "knight", "knight"),
        _person(4, "villager", "villager"),
        _person(5, "lantern_spirit", "lantern spirit"),
    ]
}
VILLAGERS = tuple(str(uuid.UUID(int=number)) for number in (1, 2, 4))
KNIGHT = str(uuid.UUID(int=3))
EVERYONE = tuple(str(uuid.UUID(int=number)) for number in (1, 2, 3, 4, 5))


class Checks:
    """A stand-in for the choice record's checks (``Minds``): the answers are the test's own.

    ``running`` are the beings models run now, ``refused`` those a choice may not name with the
    code it is refused by; a choice of a model that would run more than :data:`BOUND` is refused
    whole, as the route refuses it."""

    role_key = "society_decision"
    #: Who asks; a test of the key sets one.
    actor = None

    def __init__(self, *, running=(), refused=None, choice_seq=4, host=None, whole=None):
        self.running = set(running)
        self.refused = dict(refused or {})
        self.choice_seq = choice_seq
        self.host = host
        self.whole = whole
        self.previews: list[tuple[tuple[str, ...], object]] = []

    #: The models offered, for a test that needs names sharing a word.
    offered = (NANO, ULTRA)

    def models(self):
        return self.offered

    def host_refusal(self):
        return self.host

    def preview(self, subjects, model):
        self.previews.append((tuple(subjects), model))
        taken = [subject for subject in subjects if subject not in self.refused]
        left: dict[str, list[str]] = {}
        for subject in subjects:
            if subject in self.refused:
                left.setdefault(self.refused[subject], []).append(subject)
        after = (self.running - set(taken)) | (set(taken) if model is not None else set())
        code = self.whole or ("too_many_model_people" if len(after) > BOUND else None)
        return {
            "code": code,
            "subjects": taken,
            "left_out": left,
            "run_now": len(self.running),
            "run_after": len(after),
            "bound": BOUND,
            "choice_seq": self.choice_seq,
        }

    def cost(self, model, subjects):
        return {"per": "simulated_minute", "subjects": subjects, "usd_at_most": "0.010000"}


def _town(checks: Checks | None = None, state=TOWN) -> plan._World:
    read = _read()
    read = dataclasses.replace(read, society=dataclasses.replace(read.society, state=state))
    return plan._with_minds(_with_route(_world(read)), Checks() if checks is None else checks)


def _with_route(world: plan._World) -> plan._World:
    """The models route as a version's capability read states it for the people's role."""
    stated = {
        "operation": MIND,
        "bind": {"version_id": str(VERSION), "role_key": "society_decision"},
        "subject": "person",
        "requires": ["model.invoke", "world.write"],
        "permitted": True,
        "state": "available",
        "code": None,
        "spends": True,
        "effects": [{"on": "decisions", "state": "available", "code": None}],
    }
    return dataclasses.replace(world, descriptors={**world.descriptors, MIND: stated})


def _label(choices, value: str) -> str:
    return next(choice.label for choice in choices if choice.value == value)


def _draft(world: plan._World, *options: str) -> plan._Verdict:
    return plan._typed_from_draft([{"operation": "choose_mind", "options": list(options)}], world)


def _planned(world: plan._World, *options: str) -> dict:
    return plan._world_edit_document(_draft(world, *options), _context(), world, previewer=None)


# -- the groups a world holds ----------------------------------------------------------------------


def test_the_groups_are_everyone_then_each_kind_present_as_the_state_holds_them():
    found = minds.groups(TOWN)
    assert [(group.value, group.subjects) for group in found] == [
        ("everyone", EVERYONE),
        ("kind:villager", VILLAGERS),
        ("kind:knight", (KNIGHT,)),
        ("kind:lantern_spirit", (str(uuid.UUID(int=5)),)),
    ]
    # A society of things states each being's role as its kind's own word: the same people said
    # twice, so no role is listed beside the kinds.
    assert not [group for group in found if group.value.startswith("role:")]


def test_a_role_is_a_group_where_the_people_have_one_and_a_kind_where_they_have_none():
    living = {
        "inhabitants": [
            _person(1, None, {"key": "baker", "label": "baker", "destination_id": "a"}),
            _person(2, None, {"key": "resident", "label": "resident", "destination_id": "b"}),
            _person(3, None, {"key": "baker", "label": "baker", "destination_id": "a"}),
            _person(4, None, None),
        ]
    }
    found = {group.value: (group.title, group.subjects) for group in minds.groups(living)}
    one, two, three, four = (str(uuid.UUID(int=number)) for number in (1, 2, 3, 4))
    assert found == {
        "everyone": ("everyone here", (one, two, three, four)),
        "role:baker": ("everyone whose role is baker", (one, three)),
        "role:resident": ("everyone whose role is resident", (two,)),
    }
    assert minds.groups({"inhabitants": []}) == ()


def test_a_role_whose_people_are_exactly_a_kind_s_is_that_group_by_either_name():
    """Every villager here is a farmer and nobody else is: one group, listed once, that answers
    to "villagers" and to "farmers". A role everybody holds names everyone."""
    farmers = {
        "inhabitants": [
            _person(1, "villager", "farmer"),
            _person(2, "villager", "farmer"),
            _person(3, "knight", "knight"),
        ]
    }
    found = minds.groups(farmers)
    assert [(group.value, group.labels) for group in found] == [
        ("everyone", ()),
        ("kind:villager", ("villager", "farmer")),
        ("kind:knight", ("knight",)),
    ]
    world = _town(state=farmers)
    nano = _label(world.mind_choices, minds.mind_value(NANO.provider, NANO.model_id))
    villagers = _label(world.groups, "kind:villager")
    for words in ("let Nano decide for the farmers", "let Nano decide for the villagers"):
        [action] = _words(world, words, villagers, nano).actions
        assert action.whom == "kind:villager", words
    # A label neither the kind nor the role holds still asks.
    [asked] = _words(world, "let Nano decide for the bakers", villagers, nano).actions
    assert asked.whom is None

    residents = {
        "inhabitants": [
            _person(number, None, {"key": "resident", "label": "resident", "destination_id": "a"})
            for number in (1, 2, 3)
        ]
    }
    [everyone] = minds.groups(residents)
    assert (everyone.value, everyone.labels) == ("everyone", ("resident",))
    world = _town(state=residents)
    routine = _label(world.mind_choices, "routine")
    # The one group the words name is everyone: it stands, with no question.
    said = _words(
        world,
        "all the residents go back to their own routine",
        _label(world.groups, "everyone"),
        routine,
    )
    assert said.clarification is None and said.actions[0].whom == "everyone"


def test_a_being_of_a_made_kind_is_in_everyone_and_in_its_role_and_in_no_kind_s_group():
    """A being a workspace made is named in a state by its kind's source and digest, not by a
    shipped kind and version. It has no shipped kind's label, so it joins no kind's group; it is
    one of everyone, and of its role where the state gives it one. A choice for it is prepared as
    any being's is."""
    made = {
        **_person(6, None, "wanderer"),
        "kind": {"source": "workspace", "sha256": "ab" * 32},
    }
    state = {"inhabitants": [*TOWN["inhabitants"], made]}
    found = {group.value: group.subjects for group in minds.groups(state)}
    six = str(uuid.UUID(int=6))
    assert found["everyone"] == (*EVERYONE, six)
    assert found["role:wanderer"] == (six,)
    assert [value for value, subjects in found.items() if six in subjects] == [
        "everyone",
        "role:wanderer",
    ]
    assert found["kind:villager"] == VILLAGERS
    world = _town(state=state)
    [step] = _planned(
        world, _label(world.groups, "role:wanderer"), _label(world.mind_choices, "routine")
    )["steps"]
    assert (step["state"], step["body"]["subjects"]) == ("prepared", [six])


def test_two_accounts_asking_the_same_of_the_same_world_never_share_a_key():
    one, other = uuid.UUID(int=10), uuid.UUID(int=11)
    asked = ("world:test", VERSION, 4, 0, VILLAGERS, "routine")
    assert minds.choice_key(*asked, one) == minds.choice_key(*asked, one)
    assert len({minds.choice_key(*asked, actor) for actor in (one, other, None)}) == 3
    # The step's own key is the asking account's.
    keys = []
    for actor in (one, other):
        checks = Checks()
        checks.actor = actor
        world = _town(checks)
        [step] = _planned(
            world, _label(world.groups, "kind:villager"), _label(world.mind_choices, "routine")
        )["steps"]
        keys.append(step["body"]["idempotency_key"])
    assert len(set(keys)) == 2


def test_a_step_that_holds_no_request_reads_back_as_not_applied():
    """A step the plan blocked, or left for later, holds no request: nothing sent it, so the
    outcome read says it was not applied whatever answer a client attaches, and reads nothing."""
    from exulanica.selection import action_outcome

    for read, operation in (
        (action_outcome._mind_step, MIND),
        (action_outcome._play_step, plan.PLAY),
        (action_outcome._presence_step, plan.PRESENCE),
    ):
        step = {
            "index": 1,
            "operation": operation,
            "state": "blocked",
            "body": None,
            "answer": {"status": 200, "choice_seq": 3},
        }
        found = read(None, None, "world:test", VERSION, step)
        assert (found["index"], found["state"], found["receipts"]) == (1, "not_applied", [])


def test_the_drafter_is_shown_this_world_s_groups_with_their_numbers_and_the_minds_offered():
    world = _town()
    assert [(choice.value, choice.title) for choice in world.groups] == [
        ("everyone", "everyone here (5)"),
        ("kind:villager", "every villager (3)"),
        ("kind:knight", "every knight (1)"),
        ("kind:lantern_spirit", "every lantern spirit (1)"),
    ]
    assert [(choice.value, choice.title) for choice in world.mind_choices] == [
        ("routine", "their own routine"),
        ("model:nebius_token_factory/example/nano", "Nano"),
        ("model:nebius_token_factory/example/ultra", "Ultra"),
    ]
    shown = plan._render_options(world)
    assert "GROUPS OF BEINGS IN THIS WORLD\n  group-1: everyone here (5)" in shown
    assert "MINDS A BEING CAN BE GIVEN\n  mind-routine: their own routine." in shown
    # Every label a mind step may name is on the form, and nothing else of the world's is lost.
    assert {choice.label for choice in (*world.groups, *world.mind_choices)} <= set(
        plan.iter_labels(world)
    )


# -- what the drafter names, read back -------------------------------------------------------------


def test_a_group_and_a_mind_are_one_typed_choice():
    world = _town()
    verdict = _draft(
        world, _label(world.groups, "kind:villager"), _label(world.mind_choices, "routine")
    )
    assert verdict.refusal is None and verdict.clarification is None
    [action] = verdict.actions
    assert (action.operation, action.whom, action.mind) == (
        Op.CHOOSE_MIND,
        "kind:villager",
        "routine",
    )
    assert action.document() == {
        "operation": "choose_mind",
        "whom": "kind:villager",
        "mind": "routine",
    }


def test_a_kind_of_thing_named_is_the_group_of_that_kind_here():
    world = _town()
    nano = _label(world.mind_choices, minds.mind_value(NANO.provider, NANO.model_id))
    [action] = _draft(world, "knight", nano).actions
    assert action.whom == "kind:knight"


def test_a_being_named_is_that_being_and_two_meanings_are_asked_about():
    world = _town()
    nano = _label(world.mind_choices, minds.mind_value(NANO.provider, NANO.model_id))
    being = world.beings[0]
    [action] = _draft(world, being.label, nano).actions
    assert action.whom == f"being:{being.value}"
    both = _draft(world, being.label, _label(world.groups, "kind:villager"), nano)
    assert both.clarification["code"] == "whom_ambiguous"
    assert both.clarification["slot"] == "whom"
    assert [candidate["value"] for candidate in both.clarification["candidates"]] == [
        f"being:{being.value}",
        "kind:villager",
    ]
    assert both.clarification["actions"] == [
        {"operation": "choose_mind", "whom": None, "mind": action.mind}
    ]


def test_a_being_named_beside_the_group_that_is_only_it_is_that_being_said_twice():
    read = _read()
    knight = dataclasses.replace(read.society.beings[0], id=KNIGHT, kind="knight")
    society = dataclasses.replace(read.society, state=TOWN, beings=(knight,))
    world = plan._with_minds(
        _with_route(_world(dataclasses.replace(read, society=society))), Checks()
    )
    verdict = _draft(
        world,
        world.beings[0].label,
        _label(world.groups, "kind:knight"),
        _label(world.mind_choices, "routine"),
    )
    # One meaning, so nothing is asked: the two options name the same one being.
    assert verdict.clarification is None
    [action] = verdict.actions
    assert action.whom == f"being:{KNIGHT}"


def test_a_choice_naming_nobody_or_no_mind_is_asked_about_with_what_this_world_holds():
    world = _town()
    nobody = _planned(world, _label(world.mind_choices, "routine"))
    assert nobody["outcome"] == "clarify"
    assert (nobody["clarification"]["code"], nobody["clarification"]["slot"]) == (
        "whom_required",
        "whom",
    )
    assert [candidate["value"] for candidate in nobody["clarification"]["candidates"]] == [
        choice.value for choice in world.groups
    ]
    no_mind = _planned(world, _label(world.groups, "everyone"))
    assert (no_mind["clarification"]["code"], no_mind["clarification"]["slot"]) == (
        "mind_required",
        "mind",
    )
    assert [candidate["title"] for candidate in no_mind["clarification"]["candidates"]] == [
        "their own routine",
        "Nano",
        "Ultra",
    ]
    two = _draft(
        world,
        _label(world.groups, "everyone"),
        *(choice.label for choice in world.mind_choices[1:]),
    )
    assert two.clarification["code"] == "mind_ambiguous"


# -- the person's own words, held to what the drafter named ----------------------------------------


def test_a_label_is_said_when_the_words_hold_it_whatever_follows():
    assert minds.said("baker", "Give the bakers a mind of their own")
    assert minds.said("lantern spirit", "every Lantern-Spirit here, please")
    assert not minds.said("steward", "the bakers and the teachers")
    assert not minds.said("knight", "tonight everyone rests")
    assert not minds.said("", "anything")


def test_a_model_is_named_by_the_words_of_its_served_name():
    nano = minds.MindChoice("p", "a/nano", "Nemotron 3 Nano 30B", "")
    ultra = minds.MindChoice("p", "a/ultra", "Nemotron 3 Ultra 550B", "")
    qwen = minds.MindChoice("p", "q/qwen", "Qwen3 235B Instruct", "")
    offered = (nano, ultra, qwen)
    assert minds.said_minds("let Nemotron run them", offered) == (nano, ultra)
    assert minds.said_minds("the Ultra one, please", offered) == (ultra,)
    assert minds.said_minds("use Nemotron 3 Nano 30B for the knight", offered) == (nano,)
    assert minds.said_minds("qwen3 for everyone", offered) == (qwen,)
    # A number alone tells no model from another, and words that name none name none.
    assert minds.said_minds("give 3 knights a brain", offered) == ()
    assert minds.said_minds("", offered) == ()


def _words(world: plan._World, utterance: str, *options: str) -> plan._Verdict:
    return plan._typed_from_draft(
        [{"operation": "choose_mind", "options": list(options)}], world, utterance
    )


def test_a_group_the_words_do_not_name_is_asked_about_never_replaced_by_another():
    world = _town()
    nano = _label(world.mind_choices, minds.mind_value(NANO.provider, NANO.model_id))
    # The drafter named the knights for words that asked for wizards, which this world lacks.
    verdict = _words(
        world, "let Nano decide for the wizards", _label(world.groups, "kind:knight"), nano
    )
    [action] = verdict.actions
    assert action.whom is None and action.mind == minds.mind_value(NANO.provider, NANO.model_id)
    asked = plan._world_edit_document(verdict, _context(), world, previewer=None)
    assert asked["clarification"]["code"] == "whom_required"
    assert [candidate["value"] for candidate in asked["clarification"]["candidates"]] == [
        choice.value for choice in world.groups
    ]
    # The same draft for words that do name them stands, and everyone needs no word of its own.
    [named] = _words(
        world, "let Nano decide for the knights", _label(world.groups, "kind:knight"), nano
    ).actions
    assert named.whom == "kind:knight"
    [all_of_them] = _words(
        world, "Nano for the whole town", _label(world.groups, "everyone"), nano
    ).actions
    assert all_of_them.whom == "everyone"


def test_the_group_the_words_name_outranks_beings_the_draft_names_that_are_not_in_it():
    """A draft naming beings where the words name a group ("both villagers") is held to the words:
    a being outside that group is not what was asked for, and the group is."""
    read = _read()
    knight = dataclasses.replace(read.society.beings[0], id=KNIGHT, kind="knight")
    villager = dataclasses.replace(
        read.society.beings[1], id=VILLAGERS[0], kind="villager", display_name="Villager"
    )
    society = dataclasses.replace(read.society, state=TOWN, beings=(knight, villager))
    world = plan._with_minds(
        _with_route(_world(dataclasses.replace(read, society=society))), Checks()
    )
    routine = _label(world.mind_choices, "routine")
    knight_label, villager_label = (being.label for being in world.beings)
    # The words name the villagers; the draft named the knight, who is not one.
    [action] = _words(
        world, "the villagers follow their own routine again", knight_label, routine
    ).actions
    assert (action.whom, action.mind) == ("kind:villager", "routine")
    # Two steps, one a being outside the group and one a being inside it: the group, said once.
    both = plan._typed_from_draft(
        [
            {"operation": "choose_mind", "options": [knight_label, routine]},
            {"operation": "choose_mind", "options": [villager_label, routine]},
        ],
        world,
        "both villagers should follow their own routine again",
    )
    assert both.clarification is None
    assert [(found.whom, found.mind) for found in both.actions] == [("kind:villager", "routine")]
    # One being of a group of several, alone: that one or all of them is asked.
    one = _words(world, "the villager by the gate thinks for itself", villager_label, routine)
    assert one.clarification["code"] == "whom_ambiguous"
    assert [candidate["value"] for candidate in one.clarification["candidates"]] == [
        f"being:{VILLAGERS[0]}",
        "kind:villager",
    ]
    # The knight is the only knight: the being and its kind are one meaning, and it stands.
    [alone] = _words(world, "the knight thinks for itself", knight_label, routine).actions
    assert alone.whom == f"being:{KNIGHT}"
    # Everyone drafted where the words name a group: which is asked, never everyone taken.
    everyone = _words(
        world, "the villagers think for themselves", _label(world.groups, "everyone"), routine
    )
    assert everyone.clarification["code"] == "whom_ambiguous"
    assert [candidate["value"] for candidate in everyone.clarification["candidates"]] == [
        "everyone",
        "kind:villager",
    ]
    # No kind's or role's label in the words and no name: whom is the person's to say.
    unnamed = _words(world, "give him his own routine back", knight_label, routine)
    assert unnamed.actions[0].whom is None
    named = _words(world, "give Traveller its own routine back", knight_label, routine)
    assert named.actions[0].whom == f"being:{KNIGHT}"


def test_a_word_several_models_share_is_asked_about_among_them():
    checks = Checks()
    checks.offered = (
        minds.MindChoice("p", "a/nano", "Example Nano", ""),
        minds.MindChoice("p", "a/ultra", "Example Ultra", ""),
        minds.MindChoice("p", "b/other", "Other Flash", ""),
    )
    world = _town(checks)
    group = _label(world.groups, "kind:knight")
    first = world.mind_choices[1]
    verdict = _words(world, "let Example decide for the knight", group, first.label)
    assert verdict.clarification["code"] == "mind_ambiguous"
    assert [candidate["title"] for candidate in verdict.clarification["candidates"]] == [
        "Example Nano",
        "Example Ultra",
    ]
    # Said in full, it is that one, whichever the drafter named beside it.
    [action] = _words(
        world, "let Example Ultra decide for the knight", group, world.mind_choices[2].label
    ).actions
    assert action.mind == "model:p/a/ultra"
    # The words name one model and the draft another: the person is asked which.
    crossed = _words(world, "let Example Ultra decide for the knight", group, first.label)
    assert crossed.clarification["code"] == "mind_ambiguous"
    assert {candidate["title"] for candidate in crossed.clarification["candidates"]} == {
        "Example Nano",
        "Example Ultra",
    }


def test_two_models_each_said_in_full_are_read_a_step_at_a_time():
    checks = Checks()
    checks.offered = (
        minds.MindChoice("p", "a/nano", "Example Nano", ""),
        minds.MindChoice("p", "a/ultra", "Example Ultra", ""),
    )
    world = _town(checks)
    sentence = "Example Nano for the knights and Example Ultra for the villagers"
    verdict = plan._typed_from_draft(
        [
            {
                "operation": "choose_mind",
                "options": [_label(world.groups, "kind:knight"), world.mind_choices[1].label],
            },
            {
                "operation": "choose_mind",
                "options": [_label(world.groups, "kind:villager"), world.mind_choices[2].label],
            },
        ],
        world,
        sentence,
    )
    assert verdict.clarification is None
    assert [(action.whom, action.mind) for action in verdict.actions] == [
        ("kind:knight", "model:p/a/nano"),
        ("kind:villager", "model:p/a/ultra"),
    ]


def test_words_that_name_no_model_ask_which_mind_among_all_of_them():
    world = _town()
    group = _label(world.groups, "kind:knight")
    drafted = [choice.label for choice in world.mind_choices[1:]]
    verdict = _words(world, "give the knight a brain of its own", group, *drafted)
    [action] = verdict.actions
    assert action.mind is None
    asked = plan._world_edit_document(verdict, _context(), world, previewer=None)
    assert asked["clarification"]["code"] == "mind_required"
    assert [candidate["value"] for candidate in asked["clarification"]["candidates"]] == [
        choice.value for choice in world.mind_choices
    ]
    # Their own routine is the drafter's reading alone: no word of a model's name is needed.
    [routine] = _words(
        world, "the knight thinks for itself again", group, _label(world.mind_choices, "routine")
    ).actions
    assert routine.mind == "routine"


# -- the step, before the yes ----------------------------------------------------------------------


def test_the_step_is_the_models_route_s_request_with_what_it_comes_to_and_costs():
    checks = Checks(running={VILLAGERS[0]})
    world = _town(checks)
    nano = minds.mind_value(NANO.provider, NANO.model_id)
    document = _planned(
        world, _label(world.groups, "kind:villager"), _label(world.mind_choices, nano)
    )
    assert document["outcome"] == "plan", document.get("refusal")
    [step] = document["steps"]
    assert (step["operation"], step["state"], step["confirmation"]) == (
        MIND,
        "prepared",
        "required",
    )
    assert step["bind"] == {"version_id": str(VERSION), "role_key": "society_decision"}
    assert step["query"] == {"world_id": "world:authored:test"}
    # Exactly the body the models route takes, read by its own model.
    sent = RoleChoiceBody.model_validate(step["body"])
    assert set(step["body"]) == set(RoleChoiceBody.model_fields)
    assert sorted(sent.subjects) == sorted(VILLAGERS)
    assert sent.model is not None
    assert (sent.model.provider, sent.model.model_id) == (NANO.provider, NANO.model_id)
    assert step["requires"] == ["model.invoke", "world.write"] and step["permitted"] is True
    assert step["spends"] is True and document["spends"] is True
    assert step["titles"] == {"whom": "every villager", "mind": "Nano"}
    assert step["mind"] == {
        "subjects": 3,
        "left_out": {},
        "run_now": 1,
        "run_after": 3,
        "bound": BOUND,
        "host_refusal": None,
        "model_refusal": None,
        "groups_here": [
            {"value": "everyone", "title": "everyone here", "count": 5},
            {"value": "kind:villager", "title": "every villager", "count": 3},
            {"value": "kind:knight", "title": "every knight", "count": 1},
            {"value": "kind:lantern_spirit", "title": "every lantern spirit", "count": 1},
        ],
    }
    assert step["cost"] == {"per": "simulated_minute", "subjects": 3, "usd_at_most": "0.010000"}
    assert step["pins"] == {"choice_seq": 4}
    assert step["compensation"] is None
    # The route's own view takes the plan as it stands, the new fields with it.
    ActionPlanView.model_validate(
        {
            **document,
            "execution": _execution((), (), prompt_version=plan.ACTION_PROMPT_VERSION),
        }
    )


def test_the_same_plan_asks_with_the_same_key_and_a_later_one_with_another():
    world = _town()
    options = (_label(world.groups, "kind:knight"), _label(world.mind_choices, "routine"))
    first = _planned(world, *options)["steps"][0]["body"]["idempotency_key"]
    assert _planned(world, *options)["steps"][0]["body"]["idempotency_key"] == first
    later = _town(Checks(choice_seq=5))
    assert _planned(later, *options)["steps"][0]["body"]["idempotency_key"] != first
    everyone = (_label(world.groups, "everyone"), _label(world.mind_choices, "routine"))
    assert _planned(world, *everyone)["steps"][0]["body"]["idempotency_key"] != first
    uuid.UUID(first)


def test_a_later_mind_step_states_what_it_comes_to_and_costs_before_the_one_yes():
    """Every step is confirmed by the one yes, so a choice after the first says its count, who is
    left out and its cost on the plan too, as the world stands when the plan is made."""
    checks = Checks(refused={VILLAGERS[1]: "being_played"})
    world = _town(checks)
    nano = minds.mind_value(NANO.provider, NANO.model_id)
    verdict = plan._typed_from_draft(
        [
            {
                "operation": "choose_mind",
                "options": [_label(world.groups, "kind:knight"), _label(world.mind_choices, nano)],
            },
            {
                "operation": "choose_mind",
                "options": [
                    _label(world.groups, "kind:villager"),
                    _label(world.mind_choices, nano),
                ],
            },
            {
                "operation": "choose_mind",
                "options": [
                    _label(world.groups, "kind:lantern_spirit"),
                    _label(world.mind_choices, "routine"),
                ],
            },
        ],
        world,
    )
    document = plan._world_edit_document(verdict, _context(), world, previewer=None)
    assert document["outcome"] == "plan", document.get("refusal")
    first, later, routine = document["steps"]
    assert (first["state"], later["state"], routine["state"]) == ("prepared", "pending", "pending")
    assert later["body"] is None, "a later step is prepared again before it is sent"
    assert later["mind"]["subjects"] == 2 and later["mind"]["left_out"] == {"being_played": 1}
    assert later["mind"]["groups_here"] == first["mind"]["groups_here"]
    assert later["cost"] == {"per": "simulated_minute", "subjects": 2, "usd_at_most": "0.010000"}
    assert later["spends"] is True and later["titles"] == {"whom": "every villager", "mind": "Nano"}
    # A later routine step asks nobody: no cost, and it does not say it spends.
    assert routine["spends"] is False and routine["cost"] is None
    assert routine["mind"]["subjects"] == 1
    # A later choice the route would refuse now is blocked on the plan, by the route's code.
    alone = _town(Checks(refused={KNIGHT: "being_played"}))
    blocked = plan._world_edit_document(
        plan._typed_from_draft(
            [
                {
                    "operation": "choose_mind",
                    "options": [
                        _label(alone.groups, "kind:villager"),
                        _label(alone.mind_choices, "routine"),
                    ],
                },
                {
                    "operation": "choose_mind",
                    "options": [
                        _label(alone.groups, "kind:knight"),
                        _label(alone.mind_choices, "routine"),
                    ],
                },
            ],
            alone,
        ),
        _context(),
        alone,
        previewer=None,
    )
    assert blocked["outcome"] == "plan"
    assert (blocked["steps"][1]["state"], blocked["steps"][1]["code"]) == (
        "blocked",
        "being_played",
    )
    ActionPlanView.model_validate(
        {**document, "execution": _execution((), (), prompt_version=plan.ACTION_PROMPT_VERSION)}
    )


def test_a_model_whose_provider_s_allowance_is_used_up_is_said_not_to_be_asked():
    """The workspace's allowance for a provider, once used up, refuses every ask of its models:
    the offer says so on the model, so a step naming it states no cost it would not meet."""
    from exulanica.api.mind_offer import WorldMinds
    from exulanica.world.decision_roles import decision_roles

    [role] = [found for found in decision_roles() if found.subject == "person"]

    class Refused:
        reason = "spending_limit_reached"

    class Spent:
        def __init__(self, providers):
            self.providers = providers

        def every(self, providers):
            return Refused() if set(providers) <= self.providers else None

    class Services:
        def provider_refusal(self, _provider):
            return None

    def offer(spent):
        return WorldMinds(
            None, uuid.UUID(int=1), "world:test", VERSION, role, None, Services(), None, spent
        )

    open_handed = offer(None).models()
    assert open_handed and all(model.refusal is None for model in open_handed)
    provider = open_handed[0].provider
    used_up = offer(Spent({provider})).models()
    assert {model.refusal for model in used_up if model.provider == provider} == {
        "spending_limit_reached"
    }
    elsewhere = offer(Spent({"another_provider"})).models()
    assert all(model.refusal is None for model in elsewhere)
    # And such a model's step says why and states no cost.
    world = _town(Checks())
    costly = minds.MindChoice(NANO.provider, NANO.model_id, "Nano", "", "spending_limit_reached")
    checks = Checks()
    checks.offered = (costly,)
    world = _town(checks)
    [step] = _planned(
        world,
        _label(world.groups, "kind:knight"),
        _label(world.mind_choices, minds.mind_value(NANO.provider, NANO.model_id)),
    )["steps"]
    assert step["mind"]["model_refusal"] == "spending_limit_reached"


def test_the_allowance_is_read_once_for_a_plan_and_a_failed_read_fails_no_plan(caplog):
    """The durable allowance is read once when the offer is made for a plan, inside its own
    savepoint; a read that fails leaves the allowance unknown: the offer is made, no model is said
    to be refused by it, and the failure's text, which may hold a connection string, is not kept."""
    import contextlib

    from exulanica.api.mind_offer import world_minds

    class Refused:
        reason = "spending_limit_reached"

    class Spent:
        def every(self, _providers):
            return Refused()

    class Connection:
        def __init__(self):
            self.savepoints = 0
            self.left = []

        @contextlib.contextmanager
        def transaction(self):
            self.savepoints += 1
            try:
                yield
            except Exception as exc:
                self.left.append(type(exc).__name__)
                raise

        def execute(self, _query, _parameters):
            return self

        def fetchone(self):
            return None

    class Services:
        def __init__(self, failing):
            self.failing = failing
            self.reads = 0

        def provider_refusal(self, _provider):
            return None

        def spending_refusals(self, _connection, _workspace):
            self.reads += 1
            if self.failing:
                raise RuntimeError("postgresql://someone:secret@host/db is not reachable")
            return Spent()

    read, connection = Services(failing=False), Connection()
    offer = world_minds(connection, uuid.UUID(int=1), "world:test", VERSION, read)
    assert offer.models() and {model.refusal for model in offer.models()} == {
        "spending_limit_reached"
    }
    assert (read.reads, connection.savepoints, connection.left) == (1, 1, [])

    failed, connection = Services(failing=True), Connection()
    offer = world_minds(connection, uuid.UUID(int=1), "world:test", VERSION, failed)
    assert offer is not None and offer.spent is None
    assert offer.models() and all(model.refusal is None for model in offer.models())
    assert offer.models() == offer.models()
    # Read once however often the offer is asked, and the failure left its own savepoint.
    assert (failed.reads, connection.savepoints, connection.left) == (1, 1, ["RuntimeError"])
    assert "RuntimeError" in caplog.text and "secret" not in caplog.text


def test_their_own_routine_asks_nobody_and_states_no_cost():
    world = _town(Checks(running=set(VILLAGERS)))
    document = _planned(
        world, _label(world.groups, "kind:villager"), _label(world.mind_choices, "routine")
    )
    [step] = document["steps"]
    assert step["body"]["model"] is None
    assert step["spends"] is False and document["spends"] is False
    assert step["cost"] is None
    assert (step["mind"]["run_now"], step["mind"]["run_after"]) == (3, 0)
    assert step["titles"]["mind"] == "their own routine"


def test_whoever_may_not_be_chosen_for_is_left_out_and_counted_by_the_route_s_code():
    checks = Checks(refused={KNIGHT: "being_played", VILLAGERS[1]: "decided_from_outside"})
    world = _town(checks)
    nano = minds.mind_value(NANO.provider, NANO.model_id)
    [step] = _planned(world, _label(world.groups, "everyone"), _label(world.mind_choices, nano))[
        "steps"
    ]
    assert step["state"] == "prepared"
    assert sorted(step["body"]["subjects"]) == sorted(set(EVERYONE) - {KNIGHT, VILLAGERS[1]})
    assert step["mind"]["subjects"] == 3
    assert step["mind"]["left_out"] == {"being_played": 1, "decided_from_outside": 1}
    # With nobody left to name, the step is blocked by the code its only subject is refused by.
    alone = _planned(world, _label(world.groups, "kind:knight"), _label(world.mind_choices, nano))
    assert alone["outcome"] == "refused"
    assert alone["refusal"]["code"] == "preview_blocked"
    assert (alone["steps"][0]["state"], alone["steps"][0]["code"]) == ("blocked", "being_played")
    assert alone["steps"][0]["body"] is None


def test_a_choice_past_the_world_s_bound_is_asked_about_with_what_fits_and_never_trimmed():
    # Seven beings run by models already, none of them here: three villagers more would be ten.
    elsewhere = {str(uuid.UUID(int=number)) for number in range(101, 108)}
    checks = Checks(running=elsewhere)
    world = _town(checks)
    nano = minds.mind_value(NANO.provider, NANO.model_id)
    document = _planned(
        world, _label(world.groups, "kind:villager"), _label(world.mind_choices, nano)
    )
    assert document["outcome"] == "clarify"
    asked = document["clarification"]
    assert (asked["code"], asked["slot"]) == ("too_many_people_for_models", "whom")
    assert asked["facts"] == {"asked": 3, "bound": BOUND, "run_now": 7}
    # Only the groups of one fit; the answer is the person's, none is taken for them.
    assert [candidate["value"] for candidate in asked["candidates"]] == [
        "kind:knight",
        "kind:lantern_spirit",
    ]
    assert asked["actions"] == [{"operation": "choose_mind", "whom": None, "mind": nano}]
    # The answer comes back as a typed action and is prepared with no model.
    answered = plan._world_edit_document(
        plan._typed_from_request(
            [{"operation": "choose_mind", "whom": "kind:knight", "mind": nano}], world
        ),
        _context(),
        world,
        previewer=None,
    )
    assert answered["outcome"] == "plan"
    assert answered["steps"][0]["body"]["subjects"] == [KNIGHT]
    # With nothing that fits, the step is blocked by the route's own code.
    full = _town(Checks(running={str(uuid.UUID(int=number)) for number in range(101, 109)}))
    refused = _planned(full, _label(full.groups, "kind:knight"), _label(full.mind_choices, nano))
    assert refused["outcome"] == "refused"
    assert refused["steps"][0]["code"] == "too_many_model_people"
    assert refused["steps"][0]["mind"]["bound"] == BOUND


def test_a_choice_the_route_refuses_whole_is_blocked_by_that_code():
    world = _town(Checks(whole="engine_takes_no_model_choice"))
    document = _planned(
        world, _label(world.groups, "everyone"), _label(world.mind_choices, "routine")
    )
    assert document["outcome"] == "refused"
    assert document["steps"][0]["code"] == "engine_takes_no_model_choice"


def test_why_this_host_asks_no_model_is_on_the_step():
    world = _town(Checks(host="models_not_run_here"))
    nano = minds.mind_value(NANO.provider, NANO.model_id)
    [step] = _planned(world, _label(world.groups, "kind:knight"), _label(world.mind_choices, nano))[
        "steps"
    ]
    assert step["state"] == "prepared"
    assert step["mind"]["host_refusal"] == "models_not_run_here"
    # The bound it would meet once this host asks stays on the step; the page shows no figure
    # while nothing is asked (web/packages/app/test/companion-mind-plan.test.ts).
    assert step["cost"]["usd_at_most"] == "0.010000"


# -- what is not offered ---------------------------------------------------------------------------


def test_the_capability_read_and_the_route_s_object_decide_whether_a_mind_is_offered():
    nano = minds.mind_value(NANO.provider, NANO.model_id)
    typed = [{"operation": "choose_mind", "whom": "everyone", "mind": nano}]
    # No object handed: the step is not offered, whatever the read lists.
    bare = plan._with_minds(_with_route(_world()), None)
    assert MIND not in bare.descriptors
    refused = plan._world_edit_document(
        plan._Verdict(actions=[plan._Action(Op.CHOOSE_MIND, whom="everyone", mind=nano)]),
        _context(),
        bare,
        previewer=None,
    )
    assert refused["refusal"]["code"] == "action_not_offered"
    # A caller whose grant does not hold the route.
    world = _town()
    ungranted = dataclasses.replace(
        world,
        descriptors={**world.descriptors, MIND: {**world.descriptors[MIND], "permitted": False}},
    )
    verdict = plan._typed_from_request(typed, ungranted)
    document = plan._world_edit_document(verdict, _context(), ungranted, previewer=None)
    assert document["refusal"]["code"] == "action_not_permitted"
    # A world with nobody in it: the read's own state and code.
    empty = dataclasses.replace(
        world,
        descriptors={
            **world.descriptors,
            MIND: {
                **world.descriptors[MIND],
                "state": "unavailable",
                "code": "society_unavailable",
            },
        },
    )
    document = plan._world_edit_document(verdict, _context(), empty, previewer=None)
    assert document["refusal"]["code"] == "action_unavailable"
    assert document["refusal"]["capability"]["code"] == "society_unavailable"


def test_a_society_the_plan_may_not_read_makes_the_step_unavailable_by_name():
    read = dataclasses.replace(_read(), society=None)
    world = plan._with_minds(_with_route(_world(read)), Checks())
    assert world.groups == ()
    stated = world.descriptors[MIND]
    assert (stated["state"], stated["code"]) == ("unavailable", "unavailable_society_input")


@pytest.mark.parametrize(
    ("whom", "mind", "code"),
    [
        ("kind:dragon", "routine", "not_in_catalogue"),
        ("role:baker", "routine", "not_in_catalogue"),
        ("everyone", "model:nebius_token_factory/example/other", "not_in_catalogue"),
    ],
)
def test_a_typed_choice_naming_what_this_world_does_not_hold_is_refused(whom, mind, code):
    world = _town()
    verdict = plan._typed_from_request(
        [{"operation": "choose_mind", "whom": whom, "mind": mind}], world
    )
    assert verdict.refusal is not None and verdict.refusal["code"] == code


def test_a_being_the_typed_choice_names_is_left_to_the_route_s_own_check():
    stranger = str(uuid.UUID(int=77))
    checks = Checks(refused={stranger: "person_not_in_this_world"})
    world = _town(checks)
    verdict = plan._typed_from_request(
        [{"operation": "choose_mind", "whom": f"being:{stranger}", "mind": "routine"}], world
    )
    assert verdict.refusal is None
    document = plan._world_edit_document(verdict, _context(), world, previewer=None)
    assert document["steps"][0]["code"] == "person_not_in_this_world"
    assert checks.previews[-1] == ((stranger,), None)


def test_one_choice_names_at_most_what_the_route_s_body_takes():
    limit = RoleChoiceBody.model_fields["subjects"].metadata
    assert (
        next(m.max_length for m in limit if hasattr(m, "max_length")) == minds.SUBJECTS_PER_CHOICE
    )
    crowd = {
        "inhabitants": [
            _person(number, "villager", "villager")
            for number in range(1, minds.SUBJECTS_PER_CHOICE + 2)
        ]
    }
    world = _town(Checks(), state=crowd)
    document = _planned(
        world, _label(world.groups, "everyone"), _label(world.mind_choices, "routine")
    )
    assert document["steps"][0]["code"] == "too_many_subjects_for_one_choice"


def test_the_prepare_route_s_body_takes_a_typed_choice():
    body = PrepareRequest.model_validate(
        {
            "version_id": str(VERSION),
            "base_state_sha256": "a" * 64,
            "actions": [{"operation": "choose_mind", "whom": "everyone", "mind": "routine"}],
        }
    )
    assert body.actions[0].model_dump(exclude_none=True) == {
        "operation": "choose_mind",
        "whom": "everyone",
        "mind": "routine",
    }


def test_a_plan_made_before_a_mind_could_be_chosen_still_reads():
    """The plan format grew by optional fields: every plan the page's tests keep from before
    (their steps state no mind and no cost, their questions no figures) is read by the route's own
    view as it was, and a mind plan made now is read with them."""
    kept = sorted((ROOT / "web/packages/app/test/companion-plans").glob("*.json"))
    plans = [
        document
        for document in (json.loads(path.read_text()) for path in kept)
        if isinstance(document, dict) and document.get("profile") == plan.PLAN_PROFILE
    ]
    before = [
        document
        for document in plans
        if not any("mind" in step for step in document["steps"])
        and "facts" not in (document.get("clarification") or {})
    ]
    assert len(before) >= 5 and len(plans) > len(before)
    for document in plans:
        ActionPlanView.model_validate(document)
    for document in before:
        served = ActionPlanView.model_validate(document)
        assert all(step.mind is None and step.cost is None for step in served.steps)
        assert served.clarification is None or served.clarification.facts is None
