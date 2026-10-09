"""A thing's card and its look swap, through the routes and against PostgreSQL.

In a saved world's society of things a knight, a second knight, a sword and a well are placed. The
card of each says what it is in its kind's words; what it can do here and what others can do with
it are only what a module the society runs acts on (a knight's kind lists following, which no
module runs, so the card does not); where it is, what it holds, who decides for it, how it is drawn
and what else it may be drawn as. Choosing another look answers the card again: the same minute
and the same state digest, the look changed and nothing else. A look made for another body, or for
another object, is refused by name. A society whose input names something no longer available is
refused by name, as the society read refuses it, and so is a line said under such an input; a look
the library no longer serves is passed by, and the owner can still choose another.
"""

from __future__ import annotations

import dataclasses
import time
import uuid

import pytest
from exulanica.abilities.registry import PURPOSEFUL_BY_KIND
from exulanica.api import thing_card
from exulanica.world import thing_library, thing_looks
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_controls import LEASE_SECONDS

import test_society_lines_postgres as lines
import test_society_person_decisions_postgres as decisions
import test_society_stay_requests_api as stays
import test_society_things_postgres as things_api
from society_seed_support import choose_society_seed
from test_society_saved_world_api import OWNER, routes

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres
#: A society seed under which the knight is offered to say something to the other knight in the
#: first minute it is asked (the routine moves the other knight, so a world's own seed may not).
SPEAKING = "625fa188f3f60b26f3a5378131b84cac0d97602b2e655b02dd114896b5504c50"


def _society(client, world):
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, world, "knight", "knight", 1, 3_000, 3_000)
    things_api._place(client, world, "sword", "sword", 3, 5_000, 1_000)
    return things_api._make_society(client, world)


def _card(client, world, thing_id):
    scope, _, society = routes(world)
    return client.get(f"{society}/things/{thing_id}", headers=OWNER, params=scope)


def _swap(client, world, thing_id, look):
    scope, _, society = routes(world)
    return client.post(
        f"{society}/things/{thing_id}/look", headers=OWNER, params=scope, json={"look": look}
    )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_thing_s_card_says_what_it_is_does_here_and_wears(app):
    world, client = app
    snapshot = _society(client, world)
    knight = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")
    sword = next(t for t in snapshot["state"]["things"] if t["placed_id"] == "sword")
    read = _card(client, world, knight["id"])
    assert read.status_code == 200, read.text
    card = read.json()
    assert (card["profile"], card["thing_id"], card["subject_id"]) == (
        "exulanica.thing-card/v1",
        knight["id"],
        knight["id"],
    )
    assert (card["kind"]["label"], card["kind"]["class"], card["came_by"]) == (
        "knight",
        "being",
        "placed",
    )
    assert "exulanica-ability/hands/v1" in card["runs"]
    abilities = {ability["key"] for ability in card["abilities"]}
    # Only what a running module acts on: hands and lines are run, following is not built.
    assert {"pick_up", "give", "say"} <= abilities and "follow" not in abilities
    # The routine's abilities, by the version of the purposeful module a society made now runs.
    routine = {"wait", "stand", "talk", "rest", "visit"}
    assert {a["module"] for a in card["abilities"] if a["key"] in routine} == {PURPOSEFUL_BY_KIND}
    assert routine <= abilities
    offers = {offer["key"] for offer in card["offers"]}
    assert {"receive", "hear"} <= offers and "be_followed" not in offers
    assert all(entry["module"] in card["runs"] for entry in card["abilities"] + card["offers"])
    assert card["holding"] == [] and card["lines"] == []
    assert (card["decider"]["kind"], card["decider"]["may_change"]) == ("routine", True)
    assert card["look"]["chosen_by_owner"] is False
    assert card["look"]["look"] in {look["look"] for look in card["looks"]}
    assert card["society"] == {
        "tick": snapshot["current_tick"],
        "state_sha256": snapshot["state_sha256"],
    }
    # An object: where it lies, no decider and no lines; its own looks only.
    thing = _card(client, world, sword["id"]).json()
    assert (thing["kind"]["class"], thing["decider"], thing["lines"], thing["holding"]) == (
        "object",
        None,
        None,
        None,
    )
    assert thing["where"]["on_ground"] is True
    assert {look["look"] for look in thing["looks"]} == {"kaykit-sword", "primitive-sword"}
    # Nobody here: refused by name.
    assert _card(client, world, uuid.uuid4()).status_code == 404


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_choosing_a_look_changes_only_the_look(app):
    world, client = app
    snapshot = _society(client, world)
    knight = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")
    before = _card(client, world, knight["id"]).json()
    other = next(look for look in before["looks"] if look["look"] != before["look"]["look"])
    chosen = {key: other[key] for key in ("look", "version", "sha256")}
    swapped = _swap(client, world, knight["id"], chosen)
    assert swapped.status_code == 200, swapped.text
    after = swapped.json()
    assert {key: after["look"][key] for key in ("look", "version", "sha256")} == chosen
    assert after["look"]["chosen_by_owner"] is True
    # The proof: the same minute, the same state, read in the swap's own transaction.
    assert after["society"] == before["society"]
    assert {k: v for k, v in after.items() if k != "look"} == {
        k: v for k, v in before.items() if k != "look"
    }
    # And the card read afterwards wears it too.
    assert _card(client, world, knight["id"]).json()["look"]["look"] == chosen["look"]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_look_made_for_another_body_or_object_is_refused(app):
    world, client = app
    snapshot = _society(client, world)
    knight = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")
    sword = next(t for t in snapshot["state"]["things"] if t["placed_id"] == "sword")
    well = _card(
        client,
        world,
        next(t["id"] for t in snapshot["state"]["things"] if t["placed_id"] == "well"),
    ).json()["look"]
    bench_like = {key: well[key] for key in ("look", "version", "sha256")}
    refused = _swap(client, world, knight["id"], bench_like)
    assert (refused.status_code, refused.json()["code"]) == (422, "look_unfit")
    # An object wears only its kind's own looks, though a well's look is made for a rigid body too.
    refused = _swap(client, world, sword["id"], bench_like)
    assert (refused.status_code, refused.json()["code"]) == (422, "look_unfit")
    unknown = {"look": "no-such-look", "version": 1, "sha256": "0" * 64}
    refused = _swap(client, world, knight["id"], unknown)
    assert (refused.status_code, refused.json()["code"]) == (422, "look_not_shipped")
    # Nothing was written: each card still wears its kind's first look.
    assert _card(client, world, knight["id"]).json()["look"]["chosen_by_owner"] is False


def _shipped(look):
    return {key: look[key] for key in ("look", "version", "sha256")}


def _refusing(client, refused):
    """The application's input check, refusing every input ``refused`` names, as one naming a
    withdrawn asset is refused; the check it had before still runs for the others."""
    before = getattr(client.app.state, "society_input_authorizer", None)

    def check(connection, session, document):
        if refused(document):
            raise UnavailableSocietyInput("an asset this input names was withdrawn")
        if before is not None:
            before(connection, session, document)

    client.app.state.society_input_authorizer = check
    return before


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_card_and_the_swap_are_refused_as_the_society_read_where_its_input_is_unavailable(app):
    world, client = app
    snapshot = _society(client, world)
    knight = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")
    card = _card(client, world, knight["id"]).json()
    other = next(look for look in card["looks"] if look["look"] != card["look"]["look"])
    before = _refusing(client, lambda _document: True)
    scope, _, society = routes(world)
    answers = [
        client.get(society, headers=OWNER, params=scope),
        _card(client, world, knight["id"]),
        _swap(client, world, knight["id"], _shipped(other)),
    ]
    assert [(answer.status_code, answer.json()["code"]) for answer in answers] == [
        (424, "unavailable_society_input")
    ] * 3
    client.app.state.society_input_authorizer = before
    # Nothing was written: the knight still wears its kind's first look.
    assert _card(client, world, knight["id"]).json()["look"] == card["look"]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_chosen_look_the_library_no_longer_serves_is_passed_by(app, monkeypatch):
    """A release drops the look a knight was dressed in: the card and the version's looks read pass
    the choice by, the knight wears its kind's first look, and the owner can still choose."""
    world, client = app
    snapshot = _society(client, world)
    knight = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")
    before = _card(client, world, knight["id"]).json()
    other = next(look for look in before["looks"] if look["look"] != before["look"]["look"])
    assert _swap(client, world, knight["id"], _shipped(other)).status_code == 200
    served = thing_library.shipped_looks()
    kept = {key: look for key, look in served.items() if key != (other["look"], other["version"])}
    for module in (thing_looks, thing_card):
        monkeypatch.setattr(module, "shipped_looks", lambda: kept)
    card = _card(client, world, knight["id"])
    assert card.status_code == 200, card.text
    assert (
        card.json()["look"],
        other["look"] in {look["look"] for look in card.json()["looks"]},
    ) == (
        before["look"],
        False,
    )
    scope, root, _ = routes(world)
    read = client.get(f"{root}/thing-looks", headers=OWNER, params=scope).json()
    assert knight["id"] not in {entry["thing_id"] for entry in read["looks"]}
    again = _swap(client, world, knight["id"], _shipped(before["look"]))
    assert again.status_code == 200, again.text
    assert (_shipped(again.json()["look"]), again.json()["look"]["chosen_by_owner"]) == (
        _shipped(before["look"]),
        True,
    )


def _speaking_knight(client, world):
    """A knight decided by the scripted speaker beside a second knight, under a seed in which it
    says its line in the first minute; answers the knight and the minute after it spoke."""
    client.app.state.services = dataclasses.replace(
        client.app.state.services, societies_of_things=True
    )
    choose_society_seed(client.app, SPEAKING)
    services = decisions._services(client)
    things_api._place(client, world, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, world, "knight", "knight", 1, 3_000, 3_000)
    things_api._place(client, world, "knight-2", "knight", 1, 5_000, 3_000)
    snapshot = things_api._make_society(client, world)
    speaker = next(p for p in snapshot["state"]["inhabitants"] if p.get("placed_id") == "knight")
    manifest, model_id = decisions._offered()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    decisions._choose(services, world, [speaker["id"]], model, manifest=manifest)
    transport = lines._Speaker()
    host = decisions._host(world, decisions._client(manifest, transport), services, manifest)
    assert host.before_minute(decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    snapshot = stays._step(world, client, snapshot)
    said = _card(client, world, speaker["id"]).json()["lines"]
    assert [line["line"] for line in said] == [lines.LINE]
    return speaker, snapshot


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_line_said_under_an_input_no_longer_available_is_left_out_and_the_rest_answered(app):
    """The knight says a line under the society's first input; the author then places a lamp, so
    the society reads a second. Once the first names something no longer available, the events
    read refuses the page that shows the line, while the knight's card answers without it, says
    how many lines it left out and why, and its look can still be changed."""
    world, client = app
    speaker, snapshot = _speaking_knight(client, world)
    things_api._place(client, world, "lamp", "lamp_post", 1, -6_000, 6_000)
    snapshot = stays._step(world, client, snapshot)
    before = _refusing(client, lambda document: document["input_seq"] == 1)
    scope, _, society = routes(world)
    assert client.get(society, headers=OWNER, params=scope).status_code == 200
    events = client.get(society + "/events", headers=OWNER, params=scope)
    assert (events.status_code, events.json()["code"]) == (424, "unavailable_society_input")
    card = _card(client, world, speaker["id"])
    assert card.status_code == 200, card.text
    assert (card.json()["lines"], card.json()["lines_left_out"]) == (
        [],
        {"count": 1, "reason": "unavailable_society_input"},
    )
    other = next(
        look for look in card.json()["looks"] if look["look"] != card.json()["look"]["look"]
    )
    swapped = _swap(client, world, speaker["id"], _shipped(other))
    assert swapped.status_code == 200, swapped.text
    assert _shipped(swapped.json()["look"]) == _shipped(other)
    client.app.state.society_input_authorizer = before
    # Authorized again, the line is shown and nothing is said to be left out.
    shown = _card(client, world, speaker["id"]).json()
    assert ([line["line"] for line in shown["lines"]], "lines_left_out" in shown) == (
        [lines.LINE],
        False,
    )
