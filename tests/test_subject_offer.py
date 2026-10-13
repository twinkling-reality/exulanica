"""Subject offers narrow existing authorities; descriptors never confer a grant."""

import copy
import json
import uuid
from pathlib import Path

import pytest
from exulanica.api.permissions import Permission
from exulanica.api.subject_offer import SubjectOfferContext, subject_offer
from exulanica.world import action_catalog
from exulanica.world.errors import UnknownWorldResource

CATALOG = Path(__file__).resolve().parents[1] / "assets/catalogs/actions"


def document(version):
    return json.loads((CATALOG / f"actions.v{version}.json").read_text())


@pytest.mark.parametrize(
    "member,value",
    [
        ("when", [{"fact": "account", "value": "owner", "code": "not_owner"}]),
        ("when", [{"fact": "mode", "value": "guess", "code": "not_playing"}]),
        ("when", [{"fact": "mode", "value": [], "code": "not_playing"}]),
        ("spend_read", "POST /models/run"),
    ],
)
def test_v2_refuses_unknown_facts_values_and_mutating_spend_reads(member, value):
    raw = document(2)
    raw["entries"][0][member] = value
    with pytest.raises(action_catalog.ActionCatalogError):
        action_catalog.read(raw)


def test_v1_remains_closed_even_in_a_file_named_v2():
    raw = document(1)
    raw["catalog_version"] = 2
    raw["entries"][0]["when"] = []
    with pytest.raises(action_catalog.ActionCatalogError):
        action_catalog.read(raw, "actions.v2.json")
    assert action_catalog.read(document(1))
    assert action_catalog.load(CATALOG)


def test_conditions_cannot_enable_a_refused_operation_or_change_its_permission():
    play = next(a for a in action_catalog.offered() if a.id == "clock.play")
    refused = dict(state="unsupported", code="host_refuses", permitted=False)
    assert action_catalog.narrow_offer(play, refused, {"mode": "paused"}) == refused
    available = dict(state="available", code=None, permitted=False)
    narrowed = action_catalog.narrow_offer(play, available, {"mode": "playing"})
    assert narrowed == dict(state="unavailable", code="already_playing", permitted=False)
    assert available["state"] == "available"
    assert action_catalog.narrow_offer(play, available, {})["state"] == "unavailable"


def test_destroying_never_uses_a_spend_read_instead_of_a_plan():
    raw = document(2)
    entry = raw["entries"][0]
    entry.update(plan_word=None, cost_class="model_calls", spend_read="GET /worlds/drafts")
    with pytest.raises(action_catalog.ActionCatalogError, match="spends or destroys"):
        action_catalog.read(raw)


def context():
    ident = str(uuid.uuid4())
    card = dict(
        thing_id=ident,
        subject_id=ident,
        label="Knight",
        kind={"kind": "knight"},
        decider=dict(kind="person", played_by_you=False, may_change=False, refusal="being_played"),
        look=None,
        looks=[],
        where={},
        holding=[],
        abilities=[],
        offers=[],
    )
    actions = action_catalog.offered()
    operations = [
        dict(operation=a.route, bind=dict(a.bind), state="available", code=None)
        for a in actions
        if a.id == "minds.choose"
    ]
    return ident, SubjectOfferContext(
        capabilities=dict(
            world_id="world:test",
            version_id=str(uuid.uuid4()),
            kind="town",
            society={"held": True},
            operations=operations,
        ),
        read={"tick": 3, "state_sha256": "a" * 64},
        facts={"society": "held"},
        card=card,
        play=dict(code="being_played", playing=False, played=[]),
    )


def test_other_persons_being_is_not_offered_for_play_or_model_choice():
    ident, ctx = context()
    result = subject_offer(ctx, f"being:{ident}", frozenset(Permission))
    actions = {a["id"]: a for a in result["actions"]}
    assert actions["beings.play"]["code"] == "being_played"
    assert actions["beings.give-back"]["code"] == "not_played"
    assert actions["minds.choose"]["code"] == "being_played"
    property_ = next(p for p in result["properties"] if p["key"] == "decided_by")
    assert not property_["changeable"]
    assert not any(a["id"] in {"things.move", "things.remove"} for a in result["actions"])
    assert result["read"] == ctx.read


def test_subject_kind_mismatch_and_noncanonical_refs_are_concealed():
    ident, ctx = context()
    for ref in [f"thing:{ident}", f"being:{uuid.uuid4()}", "part:x", "being:not-an-id"]:
        with pytest.raises(UnknownWorldResource):
            subject_offer(ctx, ref, frozenset(Permission))


def test_an_offer_with_no_write_grant_does_not_make_properties_changeable():
    ident, ctx = context()
    card = copy.deepcopy(ctx.card)
    card["looks"] = [{"look": "plain", "version": 1}]
    from dataclasses import replace

    result = subject_offer(
        replace(ctx, card=card), f"being:{ident}", frozenset({Permission.WORLD_READ})
    )
    look = next(p for p in result["properties"] if p["key"] == "look")
    assert look["code"] == "not_permitted" and not look["changeable"]
