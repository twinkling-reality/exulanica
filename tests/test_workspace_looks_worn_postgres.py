"""A thing wears a look its workspace keeps, named by digest, and stops when the look is withdrawn.

A workspace admits a look of its own for a person's body (an imported traveller's look, built for
these tests from a shipped container). Through the routes and against PostgreSQL: a knight's card
lists it among the looks it may wear, by its digest alone; choosing it answers the card wearing it
at the same minute and state; the version's looks read lists the knight under its workspace looks
and not among the shipped ones, so a reader that knows only shipped looks draws its kind's first; a
crossing may bring it too. Once the workspace withdraws the look, every read passes the choice by
and the knight wears its kind's first look again, or the choice made before it where there is one.
An object, with no bones to dress, is never offered it, and a digest the workspace does not keep is
refused by name, another workspace's look's digest exactly as one nobody keeps. Every look a card
lists names its licence, as its origin states it.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.api import thing_card
from exulanica.store.local import LocalContentAddressedStore
from exulanica.things.authored import container_of
from exulanica.world.thing_looks import (
    ThingLookRefused,
    check_crossing_look,
    record_crossing_look,
)
from exulanica.world.thing_store import ThingStore

import test_society_person_decisions_postgres as decisions
import test_society_stay_requests_api as stays
from test_society_saved_world_api import OWNER, routes
from test_thing_card_postgres import _card, _shipped, _society, _swap
from test_thing_store_admission import _imported, _shipped_look

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres


def _admitted(client, world, root, shipped="blocky-traveller", key="fixture-traveller-own"):
    """The workspace admits an imported look built from a shipped look's container under its own
    key (a traveller's by default), and answers it."""
    document = _imported()
    if shipped != "blocky-traveller":
        document = {**_shipped_look(shipped), "look": key, "label": "a sword's own look"}
        document["origin"] = _imported()["origin"]
    services = decisions._services(client)
    with services.database.session(world["workspace"]) as connection:
        kept = ThingStore(
            connection, world["workspace"], LocalContentAddressedStore(root)
        ).admit_look(
            document,
            container_of(shipped),
            created_by=world["session"].actor,
            admit=lambda _look: None,
        )
    return kept.look


def _looks_read(client, world):
    scope, root, _ = routes(world)
    read = client.get(f"{root}/thing-looks", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    return read.json()


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_being_wears_its_workspace_s_own_look_until_it_is_withdrawn(app, tmp_path):
    world, client = app
    snapshot = _society(client, world)
    knight = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")
    look = _admitted(client, world, tmp_path)
    own = {"source": "workspace", "sha256": look.sha256}
    before = _card(client, world, knight["id"]).json()
    assert own | {"label": look.label} in [
        {key: entry[key] for key in ("source", "sha256", "label")}
        for entry in before["looks"]
        if entry.get("source") == "workspace"
    ]
    # Every listed look names its licence: the imported one its share-alike credit, as the fixture
    # states it, and every shipped one CC0.
    licences = {entry["sha256"]: entry["licence"] for entry in before["looks"]}
    assert licences[look.sha256] == _imported()["origin"]["licence"]
    assert {licence["spdx"] for digest, licence in licences.items() if digest != look.sha256} == {
        "CC0-1.0"
    }
    swapped = _swap(client, world, knight["id"], own)
    assert swapped.status_code == 200, swapped.text
    after = swapped.json()
    assert {key: after["look"][key] for key in ("source", "sha256", "label")} == own | {
        "label": look.label
    }
    assert after["society"] == before["society"]
    read = _looks_read(client, world)
    assert knight["id"] not in {entry["thing_id"] for entry in read["looks"]}
    assert [entry["look"] for entry in read["workspace_looks"]] == [own]
    # A crossing may bring it too, recorded beside the owner's choice, by digest.
    services = decisions._services(client)
    with services.database.session(world["workspace"]) as connection:
        recorded = record_crossing_look(
            connection,
            workspace_id=world["workspace"],
            world_id=world["binding"].world_id,
            version_id=world["binding"].version_id,
            thing_id=uuid.UUID(knight["id"]),
            crossing_id=uuid.uuid4(),
            kind=knight["kind"],
            look=own,
        )
    assert recorded.document() == own
    # Withdrawn, the look is passed by everywhere: the knight wears its kind's first look again.
    with services.database.session(world["workspace"]) as connection:
        ThingStore(connection, world["workspace"], None).withdraw_look(
            look.look, look.version, "withdrawn in a test", withdrawn_by=world["session"].actor
        )
    read = _looks_read(client, world)
    assert "workspace_looks" not in read
    assert knight["id"] not in {entry["thing_id"] for entry in read["looks"]}
    card = _card(client, world, knight["id"]).json()
    assert (card["look"]["look"], card["look"]["chosen_by_owner"]) == (
        before["look"]["look"],
        False,
    )
    assert own["sha256"] not in {entry["sha256"] for entry in card["looks"]}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_workspace_look_is_refused_for_an_object_or_a_digest_it_does_not_keep(app, tmp_path):
    world, client = app
    snapshot = _society(client, world)
    knight = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")
    sword = next(t for t in snapshot["state"]["things"] if t["placed_id"] == "sword")
    look = _admitted(client, world, tmp_path)
    own = {"source": "workspace", "sha256": look.sha256}
    # An object has no bones to dress: it is never offered a workspace look, and choosing one is
    # refused (its body plan is not a person's either).
    assert all(
        entry.get("source") != "workspace"
        for entry in _card(client, world, sword["id"]).json()["looks"]
    )
    refused = _swap(client, world, sword["id"], own)
    assert (refused.status_code, refused.json()["code"]) == (422, "look_unfit")
    # Even a look the workspace keeps for an object's own rigid body: an object has no bones to
    # dress, so it wears only its kind's own shipped looks, and is never offered one of these.
    rigid = _admitted(client, world, tmp_path / "rigid", "primitive-sword", "fixture-sword-own")
    assert rigid.body_plan == "rigid/v1"
    card = _card(client, world, sword["id"]).json()
    assert rigid.sha256 not in {entry["sha256"] for entry in card["looks"]}
    # Nor is a person offered a look made for another body: the knight's card lists only its own.
    listed = {entry["sha256"] for entry in _card(client, world, knight["id"]).json()["looks"]}
    assert look.sha256 in listed and rigid.sha256 not in listed
    refused = _swap(client, world, sword["id"], {"source": "workspace", "sha256": rigid.sha256})
    assert (refused.status_code, refused.json()["code"]) == (422, "look_unfit")
    # A crossing bringing it for the object is refused by the body plan alone, as a door checks it.
    services = decisions._services(client)
    with (
        services.database.session(world["workspace"]) as connection,
        pytest.raises(ThingLookRefused) as unfit,
    ):
        check_crossing_look(
            sword["kind"], own, connection=connection, workspace_id=world["workspace"]
        )
    assert unfit.value.code == "look_unfit"
    unknown = {"source": "workspace", "sha256": "0" * 64}
    refused = _swap(client, world, knight["id"], unknown)
    assert (refused.status_code, refused.json()["code"]) == (422, "look_not_shipped")
    assert "workspace_looks" not in _looks_read(client, world)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_withdrawn_look_leaves_the_choice_made_before_it_worn(app, tmp_path):
    world, client = app
    snapshot = _society(client, world)
    knight = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")
    before = _card(client, world, knight["id"]).json()
    shipped = _shipped(
        next(
            entry
            for entry in before["looks"]
            if entry.get("source") != "workspace" and entry["look"] != before["look"]["look"]
        )
    )
    assert _swap(client, world, knight["id"], shipped).status_code == 200
    look = _admitted(client, world, tmp_path)
    worn = _swap(client, world, knight["id"], {"source": "workspace", "sha256": look.sha256})
    assert worn.status_code == 200, worn.text
    services = decisions._services(client)
    with services.database.session(world["workspace"]) as connection:
        ThingStore(connection, world["workspace"], None).withdraw_look(
            look.look, look.version, "withdrawn in a test", withdrawn_by=world["session"].actor
        )
    worn = _card(client, world, knight["id"]).json()["look"]
    assert (_shipped(worn), worn["chosen_by_owner"]) == (shipped, True)
    read = _looks_read(client, world)
    assert [entry["look"] for entry in read["looks"] if entry["thing_id"] == knight["id"]] == [
        shipped
    ]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_look_withdrawn_between_two_reads_leaves_the_kind_s_first_worn(
    app, tmp_path, monkeypatch
):
    """The card reads the choice, then the look it names: a look withdrawn in between is no look to
    wear, and the card answers with its kind's first look rather than failing."""
    world, client = app
    snapshot = _society(client, world)
    knight = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")
    first = _card(client, world, knight["id"]).json()["look"]
    look = _admitted(client, world, tmp_path)
    worn = _swap(client, world, knight["id"], {"source": "workspace", "sha256": look.sha256})
    assert worn.status_code == 200, worn.text
    monkeypatch.setattr(thing_card, "admitted_look_by_digest", lambda *_args: None)
    card = _card(client, world, knight["id"])
    assert card.status_code == 200, card.text
    assert card.json()["look"] == first


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_another_workspace_s_look_is_answered_as_a_look_nobody_keeps(app, tmp_path):
    """Another workspace keeps a look for a person's body. Naming its digest is answered exactly as
    a digest nobody keeps is; the card never lists it, and the version's looks read never shows
    it."""
    world, client = app
    snapshot = _society(client, world)
    knight = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")
    elsewhere = uuid.uuid4()
    services = decisions._services(client)
    with services.database.session(elsewhere) as connection:
        theirs = (
            ThingStore(connection, elsewhere, LocalContentAddressedStore(tmp_path))
            .admit_look(
                _imported(),
                container_of("blocky-traveller"),
                created_by=uuid.uuid4(),
                admit=lambda _look: None,
            )
            .look
        )
    named = _swap(client, world, knight["id"], {"source": "workspace", "sha256": theirs.sha256})
    nobody = _swap(client, world, knight["id"], {"source": "workspace", "sha256": "0" * 64})
    assert (named.status_code, named.json()) == (nobody.status_code, nobody.json())
    assert (named.status_code, named.json()["code"]) == (422, "look_not_shipped")
    card = _card(client, world, knight["id"]).json()
    assert theirs.sha256 not in {entry["sha256"] for entry in card["looks"]}
    assert card["look"]["chosen_by_owner"] is False
    assert "workspace_looks" not in _looks_read(client, world)
