"""A creature its workspace keeps lives in a society of things, and the society holds none of the
words it was made from.

With no database: a fixture creature is assembled with nonsense words for everything a person's
words reach, its run form is built (:mod:`exulanica.things.run_forms`), and a thing of that kind is
placed on the starter's square beside shipped things. What is shown:

*   it arrives as a placed being, named by its body, its kind named by digest alone, and the input
    and the state each state its run form once;
*   it walks and stands by the routine, is offered what its kind lists and nothing else, may be
    decided for by a model or played by a person, and picks a thing up in its jaws;
*   a decider is told what its body is, in a sentence built from its figures;
*   when its workspace no longer holds its kind it leaves that minute, for that reason, and the
    society goes on and still reads everything it recorded;
*   nothing a person's words reached is anywhere in the inputs, the states or the events;
*   an input with no made thing keeps the bytes it always had.

The expected names and sentences are written by hand from the fixture's figures.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from typing import Any

import pytest
from exulanica.canonical import canonical_json
from exulanica.selection.creature_drafting import assembled_form
from exulanica.things.bodies import body_grammar, read_body_recipe
from exulanica.things.creatures import assemble_creature
from exulanica.things.run_forms import run_form
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import PlacedThing, WorkspaceKindReference
from exulanica.world.society_decision_contract import (
    choice_options,
    observed_context,
    person_role,
)
from exulanica.world.society_hands import acts_open
from exulanica.world.society_planner import advance_purposeful_society, validate_society_input
from exulanica.world.society_things import (
    THINGS_PROFILE,
    advance_things,
    initial_things_society,
    kind_allows,
    validate_things_state,
)

import things_society_support as support
from creature_support import form_of
from things_society_support import SEED, SOCIETY, compose, reference, thing

CANARIES = ("quorzle", "wibbet", "zanthrefol", "mipwick", "brindlefex", "ovanthrel", "ab" * 32)
BY = {
    "kind": "model",
    "provider": "frobnitz_provider",
    "model_id": "frobnitz/model",
    "prompt_version": "frobnitz-prompt-1",
    "prompt_sha256": "cd" * 32,
    "words_sha256": "ab" * 32,
    "execution_sha256": None,
}
WELL = thing("well", "well", 2, -4_000, 2_000)
SWORD = thing("sword", "sword", 2, 3_500, 3_000)
KNIGHT = thing("knight", "knight", 1, 3_000, 3_000)
POPULATION = 6
#: How many edits the starter's square took: the next edit is one more.
EDITS = len(support.square.square_objects())


def canary_creature(name: str, *, hands: bool = False) -> Any:
    """A fixture creature assembled under nonsense words for everything a person's words reach:
    its label and key, its summary, its recipe's appearance and the digest of the words."""
    form = form_of(name, label="quorzle wibbet")
    form["summary"] = "Zanthrefol mipwick."
    form["appearance"] = "Brindlefex ovanthrel plates over its hide."
    for ability in ("rest", "visit", "talk"):
        form[f"can_{ability}"] = True
        form[f"weight_{ability}"] = 100
    if hands:
        for ability in ("pick_up", "put_down"):
            form[f"can_{ability}"] = True
            form[f"weight_{ability}"] = 0
    return assemble_creature(assembled_form(form, body_grammar()), by=BY)


def _made(name: str, *, hands: bool = False) -> tuple[str, dict[str, Any]]:
    """A fixture creature kept under nonsense words: its kind's digest and its run form."""
    creature = canary_creature(name, hands=hands)
    recipe = read_body_recipe(dict(creature.recipe))
    return creature.kind.sha256, run_form(creature.kind, creature.plan, recipe)


def _placed(placed_id: str, sha256: str, x_mm: int, z_mm: int, **changes: Any) -> PlacedThing:
    placed = PlacedThing(
        placed_id,
        WorkspaceKindReference(sha256),
        "region:starter",
        Transform(x_mm, 0, z_mm, 0, 1000),
        ObjectOrigin("authored", "fictional"),
    )
    return dataclasses.replace(placed, **changes)


def _minute(state, document, before=None):
    """One minute over ``document``: the input the society consumed last, or, with ``before``,
    the input it moves on to from that one."""
    inputs = [document] if before is None else [before, document]
    planned, events = advance_purposeful_society(state, SEED, inputs)
    after, events, _bound = advance_things(state, planned, SEED, document, events)
    return after, events


def _person(state, **match):
    return next(p for p in state["inhabitants"] if all(p.get(k) == v for k, v in match.items()))


def _contract():
    role = person_role()
    return role.contract(role.terms(THINGS_PROFILE).versions)


def _hour(state, document, minutes=60):
    states, events = [state], []
    for _ in range(minutes):
        state, recorded = _minute(state, document)
        states.append(state)
        events.extend(recorded)
    return states, events


def test_a_made_creature_arrives_named_by_its_body_and_by_its_kind_s_digest_alone():
    sha256, form = _made("horse")
    document = compose(
        (WELL, KNIGHT, _placed("creature:1", sha256, -2_000, 4_000)), made_kinds={sha256: form}
    )
    validate_society_input(document)
    made = {"source": "workspace", "sha256": sha256}
    entry = next(e for e in document["things"] if e["placed_id"] == "creature:1")
    assert entry["kind"] == made and entry["arrival_mm"] is None
    assert document["kinds"] == {sha256: form}
    assert {"kind": "made_thing_kind", "identity": sha256, "sha256": sha256} in document[
        "dependency_refs"
    ]
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    being = _person(state, placed_id="creature:1")
    # Named by hand from the horse fixture's figures: four legs, one head, no wings.
    assert being["display_name"] == "Four legged creature"
    assert (being["kind"], being["came_by"], being["role"]) == (
        made,
        "placed",
        "four legged creature",
    )
    assert state["kinds"] == {sha256: form}
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    assert being["position_mm"] == nodes[being["location"]["node_id"]]
    # The knight beside it is the shipped being it always was.
    assert _person(state, placed_id="knight")["kind"] == reference("knight", 1)
    validate_things_state(state)


def test_two_creatures_of_one_kind_state_its_run_form_once_and_are_told_apart_by_number():
    sha256, form = _made("horse")
    document = compose(
        (_placed("creature:1", sha256, -2_000, 4_000), _placed("creature:2", sha256, 2_000, 4_000)),
        made_kinds={sha256: form},
    )
    assert list(document["kinds"]) == [sha256]
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    names = sorted(p["display_name"] for p in state["inhabitants"] if p["came_by"] == "placed")
    assert names == ["Four legged creature", "Four legged creature 2"]
    assert list(state["kinds"]) == [sha256]


def test_it_walks_and_stays_by_the_routine_and_the_same_hour_twice_is_the_same_bytes():
    sha256, form = _made("horse")
    document = compose(
        (WELL, _placed("creature:1", sha256, -2_000, 4_000)), made_kinds={sha256: form}
    )
    genesis = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    states, events = _hour(genesis, document)
    identity = _person(genesis, placed_id="creature:1")["id"]
    places = {tuple(_person(s, id=identity)["position_mm"]) for s in states}
    assert len(places) > 1, "the creature never left where it was placed"
    mine = [e for e in events if str(e.subject_id) == identity]
    # It does what its kind lists (rest, visit, stand, talk) and nothing else.
    done = {e.document["action"]["kind"] for e in mine if e.document["action"] is not None}
    assert done <= {"idle", "move", "rest", "visit", "stand", "talk"} and "move" in done
    assert {e.document["profile"] for e in mine} == {THINGS_PROFILE}
    again, events_again = _hour(genesis, document)
    assert canonical_json(states[-1]) == canonical_json(again[-1])
    assert [e.event_id for e in events] == [e.event_id for e in events_again]
    for state in states:
        validate_things_state(state)


def test_it_is_offered_what_its_kind_lists_and_may_be_given_a_mind_or_played():
    sha256, form = _made("horse")
    document = compose(
        (WELL, KNIGHT, _placed("creature:1", sha256, 2_000, 3_000)), made_kinds={sha256: form}
    )
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    being = _person(state, placed_id="creature:1")
    kinds = {o.kind for o in choice_options(state, document, being["id"], _contract(), seed=SEED)}
    # It says lines (its kind lists say) and never leaves (only a visitor from outside does).
    assert {"say_to", "say"} & kinds and "leave" not in kinds
    assert kind_allows(state, being["id"], "model") and kind_allows(state, being["id"], "person")
    assert kind_allows(state, being["id"], "routine")
    assert not kind_allows(state, being["id"], "external")
    # The knight is offered to speak to it by its body's name, as the page names it.
    knight = _person(state, placed_id="knight")
    labels = [
        o.label for o in choice_options(state, document, knight["id"], _contract(), seed=SEED)
    ]
    assert any("four legged creature" in label for label in labels), labels


def test_a_decider_is_told_what_its_body_is_in_a_sentence_built_from_its_figures():
    sha256, form = _made("horse")
    document = compose((_placed("creature:1", sha256, 2_000, 3_000),), made_kinds={sha256: form})
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    being = _person(state, placed_id="creature:1")
    shown = observed_context(state, document, being["id"], (), profile="p")
    # By hand from the horse fixture: 2,400 mm long, 1,800 mm high, four legs, a tail of three
    # bones, a head with no jaw, holding with nothing.
    assert shown["being"] == {
        "kind": "four legged creature",
        "summary": "A creature about 2.4 m long and 1.8 m high with one head, four legs and a "
        "tail. It moves over the ground.",
    }


def test_a_creature_that_holds_with_its_jaws_picks_a_sword_up_in_its_mouth():
    sha256, form = _made("crocodile", hands=True)
    document = compose(
        (SWORD, _placed("creature:1", sha256, 3_500, 3_000)), made_kinds={sha256: form}
    )
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    being = _person(state, placed_id="creature:1")
    sword = next(t for t in state["things"] if t["placed_id"] == "sword")
    # Stood at the sword itself, so the act is within the module's reach whatever node it took.
    here = {**being, "position_mm": list(sword["position_mm"])}
    acts = [(act.ability, act.thing_id, act.socket) for act in acts_open(state, here, document)]
    # A crocodile fixture 4,500 mm long holds one thing up to a quarter of its length in its
    # mouth: the sword, 1,000 mm, fits.
    assert acts == [("pick_up", sword["id"], "mouth")]
    # A creature that holds with nothing is offered no hands act.
    plain_sha, plain = _made("horse")
    other = compose(
        (SWORD, _placed("creature:1", plain_sha, 3_500, 3_000)), made_kinds={plain_sha: plain}
    )
    plain_state = initial_things_society(SOCIETY, SEED, other, population=POPULATION)
    horse = {
        **_person(plain_state, placed_id="creature:1"),
        "position_mm": list(sword["position_mm"]),
    }
    assert acts_open(plain_state, horse, other) == []


def test_it_leaves_the_minute_its_kind_is_erased_and_the_society_goes_on():
    sha256, form = _made("horse")
    kept = compose(
        (WELL, KNIGHT, _placed("creature:1", sha256, -2_000, 4_000)), made_kinds={sha256: form}
    )
    state = initial_things_society(SOCIETY, SEED, kept, population=POPULATION)
    states, _events = _hour(state, kept, minutes=5)
    identity = _person(state, placed_id="creature:1")["id"]
    # The workspace no longer holds the kind: the thing reads gone, and nobody states its form.
    erased = compose(
        (WELL, KNIGHT, _placed("creature:1", sha256, -2_000, 4_000, kind_gone=True)),
        made_kinds={},
        input_seq=2,
    )
    validate_society_input(erased)
    assert "kinds" not in erased and erased["things_gone"] == ["creature:1"]
    assert [e["placed_id"] for e in erased["things"]] == ["knight", "well"]
    after, events = _minute(states[-1], erased, before=kept)
    left = [e for e in events if e.kind == "thing_departed"]
    assert [(str(e.subject_id), e.document["reason"]) for e in left] == [(identity, "kind_erased")]
    assert left[0].document["thing"]["kind"] == {"source": "workspace", "sha256": sha256}
    assert all(p["id"] != identity for p in after["inhabitants"]) and "kinds" not in after
    validate_things_state(after)
    # The knight is still here and the society plays on.
    later, _ = _hour(after, erased, minutes=10)
    assert _person(later[-1], placed_id="knight")


def test_a_thing_whose_kind_is_gone_stays_out_though_the_same_creature_is_kept_again():
    # The workspace erased the creature after the thing was placed and then kept the same document
    # again: the store states the run form, and the thing is still gone, so it is still left out.
    sha256, form = _made("horse")
    again = compose(
        (WELL, _placed("creature:1", sha256, -2_000, 4_000, kind_gone=True)),
        made_kinds={sha256: form},
    )
    assert [e["placed_id"] for e in again["things"]] == ["well"]
    assert "kinds" not in again and again["things_gone"] == ["creature:1"]
    # A second thing of that kind placed since is read, and the kind is then stated, not gone.
    both = compose(
        (
            WELL,
            _placed("creature:1", sha256, -2_000, 4_000, kind_gone=True),
            _placed("creature:2", sha256, 2_000, 4_000),
        ),
        made_kinds={sha256: form},
    )
    assert [e["placed_id"] for e in both["things"]] == ["creature:2", "well"]
    assert list(both["kinds"]) == [sha256] and both["things_gone"] == ["creature:1"]
    validate_society_input(both)
    # In a society that held the first, it leaves because its kind was erased while the second,
    # of the same kind, comes and lives.
    kept = compose((WELL, _placed("creature:1", sha256, -2_000, 4_000)), made_kinds={sha256: form})
    state = initial_things_society(SOCIETY, SEED, kept, population=POPULATION)
    first = _person(state, placed_id="creature:1")["id"]
    moved_on = compose(
        (
            WELL,
            _placed("creature:1", sha256, -2_000, 4_000, kind_gone=True),
            _placed("creature:2", sha256, 2_000, 4_000),
        ),
        made_kinds={sha256: form},
        input_seq=2,
        edit_seq=EDITS + 1,
    )
    after, events = _minute(state, moved_on, before=kept)
    left = [e for e in events if e.kind == "thing_departed"]
    assert [(str(e.subject_id), e.document["reason"]) for e in left] == [(first, "kind_erased")]
    assert [p["placed_id"] for p in after["inhabitants"] if p["came_by"] == "placed"] == [
        "creature:2"
    ]
    assert list(after["kinds"]) == [sha256]


def test_an_author_s_removal_is_still_an_author_s_removal():
    sha256, form = _made("horse")
    kept = compose((WELL, _placed("creature:1", sha256, -2_000, 4_000)), made_kinds={sha256: form})
    state = initial_things_society(SOCIETY, SEED, kept, population=POPULATION)
    removed = compose(
        (WELL, _placed("creature:1", sha256, -2_000, 4_000, removed=True)),
        made_kinds={sha256: form},
        input_seq=2,
        edit_seq=EDITS + 1,
    )
    assert "kinds" not in removed and "things_gone" not in removed
    _after, events = _minute(state, removed, before=kept)
    assert [e.document["reason"] for e in events if e.kind == "thing_departed"] == [
        "removed_by_author"
    ]


def test_nothing_a_person_s_words_reached_is_in_the_inputs_the_states_or_the_events():
    sha256, form = _made("crocodile", hands=True)
    kept = compose(
        (WELL, SWORD, KNIGHT, _placed("creature:1", sha256, 2_000, 3_000)),
        made_kinds={sha256: form},
    )
    genesis = initial_things_society(SOCIETY, SEED, kept, population=POPULATION)
    states, events = _hour(genesis, kept, minutes=30)
    being = _person(genesis, placed_id="creature:1")
    shown = observed_context(
        states[-1],
        kept,
        being["id"],
        choice_options(states[-1], kept, being["id"], _contract(), seed=SEED),
        profile="p",
    )
    erased = compose(
        (WELL, SWORD, KNIGHT, _placed("creature:1", sha256, 2_000, 3_000, kind_gone=True)),
        made_kinds={},
        input_seq=2,
    )
    after, last = _minute(states[-1], erased, before=kept)
    recorded = (
        canonical_json(
            [kept, erased, *states, after, shown, *[e.document for e in (*events, *last)]]
        )
        .decode()
        .lower()
    )
    for canary in (*CANARIES, "frobnitz"):
        assert canary not in recorded, canary
    # The positive control: the same search finds a word the record does hold.
    assert "four legged creature" in recorded


def test_an_input_with_no_made_thing_keeps_the_bytes_it_always_had():
    sha256, form = _made("horse")
    plain = compose((WELL, SWORD, KNIGHT))
    assert canonical_json(compose((WELL, SWORD, KNIGHT), made_kinds={})) == canonical_json(plain)
    assert canonical_json(
        compose((WELL, SWORD, KNIGHT), made_kinds={sha256: form})
    ) == canonical_json(plain)
    assert "kinds" not in plain and "things_gone" not in plain
    # A thing whose kind its workspace holds but whose run form could not be built (the store
    # stated none for it) is left out and is not listed as gone: its kind was not erased.
    unread = compose((WELL, _placed("creature:1", sha256, 2_000, 3_000)), made_kinds={})
    assert [e["placed_id"] for e in unread["things"]] == ["well"]
    assert "kinds" not in unread and "things_gone" not in unread
    # And a made thing nobody stated a run form for is left out, as it was before.
    left_out = compose((WELL, SWORD, KNIGHT, _placed("creature:1", sha256, 2_000, 3_000)))
    assert [e["placed_id"] for e in left_out["things"]] == ["knight", "sword", "well"]
    assert "kinds" not in left_out


def _reread(document: dict[str, Any]) -> None:
    from exulanica.world.society_planner import input_sha256

    del document["document_sha256"]
    document["document_sha256"] = input_sha256(document)
    validate_society_input(document)


def test_an_input_s_made_kinds_are_held_to_their_shape():
    sha256, form = _made("horse")
    good = compose((WELL, _placed("creature:1", sha256, -2_000, 4_000)), made_kinds={sha256: form})
    _reread(copy.deepcopy(good))
    # A run form nobody placed a thing of.
    orphan = copy.deepcopy(compose((WELL,)))
    orphan["kinds"] = {sha256: form}
    # A made thing whose run form is not stated.
    unstated = copy.deepcopy(good)
    del unstated["kinds"]
    # A run form carrying a word of its own.
    worded = copy.deepcopy(good)
    worded["kinds"][sha256]["label"] = "quorzle wibbet"
    # A run form kept under another digest than the one it names.
    misfiled = copy.deepcopy(good)
    misfiled["kinds"][sha256]["reference"]["sha256"] = "0" * 64
    # A thing both listed and gone.
    both = copy.deepcopy(good)
    both["things_gone"] = ["creature:1"]
    # Placed ids out of order.
    unordered = copy.deepcopy(compose((WELL,)))
    unordered["things_gone"] = ["creature:2", "creature:1"]
    # A gone thing named by something that is no placed id.
    unnamed = copy.deepcopy(compose((WELL,)))
    unnamed["things_gone"] = ["Quorzle Wibbet"]
    for broken in (orphan, unstated, worded, misfiled, both, unordered, unnamed):
        with pytest.raises(ValueError):
            _reread(broken)


def test_a_state_s_made_kinds_are_exactly_those_of_who_is_here():
    sha256, form = _made("horse")
    document = compose(
        (WELL, _placed("creature:1", sha256, -2_000, 4_000)), made_kinds={sha256: form}
    )
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    validate_things_state(state)
    without = copy.deepcopy(state)
    del without["kinds"]
    extra = copy.deepcopy(state)
    extra["kinds"]["f" * 64] = form
    worded = copy.deepcopy(state)
    worded["kinds"][sha256]["summary"] = "Quorzle wibbet."
    for broken in (without, extra, worded):
        with pytest.raises(ValueError):
            validate_things_state(broken)
    # A state of shipped beings alone states none, as it always did.
    plain = initial_things_society(SOCIETY, SEED, compose((WELL, KNIGHT)), population=POPULATION)
    assert "kinds" not in plain and "kinds" not in json.dumps(sorted(plain))
