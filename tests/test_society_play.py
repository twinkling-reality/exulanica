"""A person playing one being ("Play this one"), in memory: the decider, giving a being back, and
what a minute takes from the person's answer.

A choice names a person playing a being by account. Giving the being back records a choice naming
the same person with ``ended``: the being is decided for again as it was before the play began, by
its own earlier choice, or, with none, by whatever decides for a being no choice names (a gate's
group, or the routine), so nothing is copied. A minute takes the person's latest answer for it where
the request offers its label, else the request's idle option, ``person_no_answer``. Only a played
being's request offers a walk to a spot the person chooses, and its receipt names the node the host
took for the spot.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.deciders import DeciderRefused, decider, is_played, receipt_decider
from exulanica.world.role_decisions import check_role_result, role_request
from exulanica.world.society_decision_contract import (
    POINT_KIND,
    choice_options,
    person_role,
    point_node,
)
from exulanica.world.society_model_choice_repository import (
    SocietyModelChoiceRepository,
    _view,
    latest_choices,
)
from exulanica.world.society_play import answer_document, person_result, play_contract
from exulanica.world.society_things import initial_things_society

from things_society_support import SEED, SOCIETY, compose, thing

ACCOUNT = str(uuid.UUID(int=0xA1))
SUBJECT = str(uuid.UUID(int=0x5B))
MODEL = {"kind": "model", "provider": "nebius", "model_id": "m"}
PLAYED = {"kind": "person", "account_id": ACCOUNT}


def test_a_person_playing_a_being_is_named_by_account_beside_the_owner_s_requests():
    assert is_played(decider(PLAYED)) and not is_played(decider({"kind": "person"}))
    with pytest.raises(DeciderRefused, match="account"):
        decider({"kind": "person", "account_id": "Hazel"})


def _row(sequence: int, described: dict, *, ended: str | None = None) -> dict:
    role = person_role()
    document = {
        "profile": role.choice_profile,
        "choice_seq": sequence,
        role.choice_subjects: [SUBJECT],
        "decider": described,
        "chosen_by": ACCOUNT,
        **({"ended": ended} if ended else {}),
    }
    return {"document": document, "recorded_at": None}


def test_giving_a_being_back_restores_what_decided_for_it_before_the_play():
    current = SocietyModelChoiceRepository._current
    role = person_role()
    # Its own choice of a model, then a play: the person decides; given back, the model again.
    assert current(role, [_row(1, MODEL), _row(2, PLAYED)])[SUBJECT]["decider"] == PLAYED
    restored_rows = [_row(1, MODEL), _row(2, PLAYED), _row(3, PLAYED, ended="given_back")]
    restored = current(role, restored_rows)
    assert restored[SUBJECT]["decider"] == MODEL
    # With no own choice before, nothing is copied: no choice names it, so a gate's group or the
    # routine decides for it again.
    assert current(role, [_row(1, PLAYED), _row(2, PLAYED, ended="player_left")]) == {}
    # A comparison names the same decider for it, by the same rule over the choices as read.
    views = [_view(row["document"], None) for row in restored_rows]
    assert latest_choices(role, views)[SUBJECT]["choice_seq"] == 1


def test_a_minute_takes_the_person_s_answer_else_carries_on():
    context = {
        "options": [
            {"label": "go to the well, 6 m away", "kind": "target"},
            {"label": "say something to everyone near you", "kind": "say_all"},
            {"label": "carry on", "kind": "carry_on"},
        ]
    }
    kinds = ("say_to", "say_all")
    answered = answer_document(SUBJECT, 7, "say something to everyone near you", "Good night.")
    taken = person_result(context, "carry on", answered, line_kinds=kinds)
    assert (taken["status"], taken["reason"], taken["proposal"]["line"]) == (
        "accepted",
        "validated_choice",
        "Good night.",
    )
    assert taken["provider"]["kind"] == "person" and taken["provider"]["answer_sha256"]
    assert receipt_decider(taken) == "person"
    # No answer, or one the minute no longer offers: the being carries on, never the routine.
    for answer in (None, answer_document(SUBJECT, 7, "go to the bench", None)):
        idle = person_result(context, "carry on", answer, line_kinds=kinds)
        assert (idle["reason"], idle["proposal"]["label"], idle["provider"]["answer_sha256"]) == (
            "person_no_answer",
            "carry on",
            None,
        )


def _knight_free_to_choose():
    """A society of things at genesis, its placed knight free to choose."""
    document = compose(
        (
            thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593),
            thing("knight", "knight", 1, 3_000, 3_000),
        )
    )
    state = initial_things_society(SOCIETY, SEED, document, population=6)
    knight = next(p for p in state["inhabitants"] if p["placed_id"] == "knight")
    return state, document, knight


def test_only_a_played_being_s_request_offers_a_walk_to_a_spot():
    state, document, knight = _knight_free_to_choose()
    role = person_role()
    played = play_contract(role, "exulanica-society/v7")
    asked = role.contract(role.terms("exulanica-society/v7").versions)
    walks = [
        option
        for option in choice_options(state, document, knight["id"], played, seed=SEED)
        if option.kind == POINT_KIND
    ]
    assert [option.label for option in walks] == ["walk to a spot you choose"]
    # A model or an outside program is asked under the engine's own terms, which state no walk.
    offered = choice_options(state, document, knight["id"], asked, seed=SEED)
    assert offered and not [option for option in offered if option.kind == POINT_KIND]


def test_a_walk_s_receipt_names_its_node_and_no_other_option_s_does():
    state, document, knight = _knight_free_to_choose()
    role = person_role()
    played = play_contract(role, "exulanica-society/v7")
    request, _status = role_request(
        role,
        state,
        document,
        knight["id"],
        request_id=uuid.uuid4(),
        contract=played,
        seed=SEED,
        provider_config={"kind": "person", "contract": played.binding()},
    )
    assert request is not None
    options = request["context"]["options"]
    walk = next(option for option in options if option["kind"] == POINT_KIND)
    node = point_node(state, document, knight["id"], [5_000, 5_000])
    assert node is not None
    answer = answer_document(knight["id"], state["tick"], walk["label"], None, [5_000, 5_000])
    taken = person_result(
        request["context"],
        role.idle_label(request["context"]),
        answer,
        line_kinds=("say_to", "say_all"),
        point_kinds=(POINT_KIND,),
        node_id=node,
    )
    assert taken is not None and taken["proposal"]["node_id"] == node
    check_role_result(role, taken, request)
    waiting = next(option for option in options if option["kind"] == "wait")
    for proposal in (
        {"label": waiting["label"], "option": waiting, "node_id": node},
        {"label": walk["label"], "option": walk},
    ):
        with pytest.raises(ValueError, match="proposes one of the options"):
            check_role_result(role, {**taken, "proposal": proposal}, request)
    # No open node near the spot: the being carries on, as with no answer.
    idle = person_result(
        request["context"],
        role.idle_label(request["context"]),
        answer,
        line_kinds=("say_to", "say_all"),
        point_kinds=(POINT_KIND,),
        node_id=None,
    )
    assert idle is not None and idle["reason"] == "person_no_answer"
