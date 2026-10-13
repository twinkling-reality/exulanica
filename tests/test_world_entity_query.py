"""World matching preserves identities, incomplete work and final appearance authority."""

import dataclasses
import hashlib
import uuid
from copy import deepcopy

import pytest
from exulanica.api.routes.world_entity_query import WorldEntityQueryBody
from exulanica.api.world_entity_query import (
    PROFILE,
    Appearance,
    inspect_appearances,
    query_result,
    reference_key,
)
from exulanica.world.appearance_colour import ColourSwatch
from exulanica.world.static_glb import PROFILE as STATIC_PROFILE
from pydantic import ValidationError

from test_appearance_colour import _constant

BODY = {
    "profile": PROFILE,
    "predicate": {
        "kind": "declared_base_colour",
        "quantifier": "any_constant_primitive",
        "colour": {"kind": "swatch", "srgb8": [255, 0, 0]},
    },
}


def _inventory():
    return {
        "world_id": "world",
        "version_id": str(uuid.uuid4()),
        "read": {"society": {"tick": 4}},
        "entities": [
            {"reference": {"source": source, "id": "same"}, "aliases": aliases}
            for source, aliases in (
                ("authored-thing", [{"source": "society-being", "id": "being"}]),
                ("authored-object", []),
            )
        ],
        "coverage": [{"source": "things", "state": "complete"}],
        "representations": [],
    }


def _appearance(data, look="a"):
    return Appearance(
        "being",
        "k" * 64,
        "workspace",
        look * 64,
        hashlib.sha256(data).hexdigest(),
        len(data),
        STATIC_PROFILE,
    )


def test_request_is_closed_strict_numeric_and_rejects_inverted_channels():
    assert WorldEntityQueryBody.model_validate(BODY).predicate.colour.domain() == ColourSwatch(
        (255, 0, 0)
    )
    for value in (True, 1.0, "1", -1, 256):
        body = deepcopy(BODY)
        body["predicate"]["colour"]["srgb8"][0] = value
        with pytest.raises(ValidationError):
            WorldEntityQueryBody.model_validate(body)
    for mutate in (
        lambda body: body.update(extra=True),
        lambda body: body["predicate"].update(quantifier="mostly"),
        lambda body: body["predicate"].update(colour={"kind": "named", "name": "yellow"}),
        lambda body: body["predicate"].update(
            colour={"kind": "interval", "lower": [5, 0, 0], "upper": [4, 1, 1]}
        ),
    ):
        body = deepcopy(BODY)
        mutate(body)
        with pytest.raises(ValidationError):
            WorldEntityQueryBody.model_validate(body)


def test_match_reuses_checked_bytes_without_collapsing_entities_or_unknown_sources():
    data = _constant((1, 0, 0, 1)).build()
    inventory = _inventory()
    keys = [reference_key(row) for row in inventory["entities"]]
    selection = {keys[0]: _appearance(data), keys[1]: "appearance_adapter_unavailable"}
    calls = []
    facts = inspect_appearances(selection, lambda look: calls.append(look) or data)
    response = query_result(
        inventory, selection, selection, facts, ColourSwatch((255, 0, 0)), BODY["predicate"]
    )
    assert len(calls) == 1
    assert [row["state"] for row in response["entities"]] == ["match", "unknown"]
    assert response["entities"][0]["aliases"] == inventory["entities"][0]["aliases"]
    assert response["coverage"]["entities"] == {
        "total": 2,
        "evaluated": 1,
        "matched": 1,
        "no_match": 0,
        "unknown": 1,
    }
    assert response["coverage"]["state"] == "incomplete"
    # Byte reuse does not merge two separately authorized identities.
    selection[keys[1]] = selection[keys[0]]
    calls.clear()
    facts = inspect_appearances(selection, lambda look: calls.append(look) or data)
    assert len(calls) == 1 and len(facts) == 2
    # One identity loses authority after those shared bytes were read.
    final = {**selection, keys[1]: "kind_unavailable"}
    response = query_result(
        inventory, selection, final, facts, ColourSwatch((255, 0, 0)), BODY["predicate"]
    )
    assert [row["state"] for row in response["entities"]] == ["match", "unknown"]
    assert response["entities"][1]["appearance"] is None


def test_changed_appearance_and_removed_subject_suppress_previously_matching_facts():
    data = _constant((1, 0, 0, 1)).build()
    inventory = _inventory()
    key = reference_key(inventory["entities"][0])
    selection = {key: _appearance(data)}
    facts = inspect_appearances(selection, lambda _: data)
    inventory["entities"] = inventory["entities"][:1]
    final = {key: dataclasses.replace(selection[key], look_sha256="b" * 64)}
    response = query_result(
        inventory, selection, final, facts, ColourSwatch((255, 0, 0)), BODY["predicate"]
    )
    row = response["entities"][0]
    assert (row["state"], row["reason"], row["appearance"], row["match_basis"]) == (
        "unknown",
        "appearance_changed",
        None,
        [],
    )
    inventory["entities"] = []
    assert (
        query_result(inventory, selection, {}, facts, ColourSwatch((255, 0, 0)), BODY["predicate"])[
            "entities"
        ]
        == []
    )


def test_byte_and_primitive_budgets_missing_and_corrupt_containers_are_unknown():
    data = _constant((1, 0, 0, 1)).build()
    key = ("society-being", "a", None)
    appearance = _appearance(data)

    def forbidden(_):
        raise AssertionError("out-of-budget bytes must not be read")

    assert (
        inspect_appearances({key: appearance}, forbidden, maximum_container_bytes=1)[key]
        == "container_byte_budget"
    )
    assert (
        inspect_appearances({key: appearance}, forbidden, maximum_primitives=0)[key]
        == "primitive_budget"
    )
    assert (
        inspect_appearances({key: appearance}, lambda _: b"wrong")[key]
        == "container_binding_mismatch"
    )

    def missing(_):
        raise FileNotFoundError

    assert inspect_appearances({key: appearance}, missing)[key] == "container_unavailable"
    unsupported = dataclasses.replace(appearance, container_profile="rigged/v1")
    assert inspect_appearances({key: unsupported}, forbidden)[key] == "unsupported_profile"


def test_positive_partial_and_not_enumerated_coverage_cannot_be_reported_complete():
    source = _constant((1, 0, 0, 1))
    source.scene(0, source.node(mesh=0))
    data = source.build()
    inventory = _inventory()
    inventory["entities"] = inventory["entities"][:1]
    key = reference_key(inventory["entities"][0])
    selection = {key: _appearance(data)}
    facts = inspect_appearances(selection, lambda _: data, maximum_primitives=1)
    response = query_result(
        inventory, selection, selection, facts, ColourSwatch((255, 0, 0)), BODY["predicate"]
    )
    assert response["entities"][0]["state"] == "match"
    assert response["entities"][0]["coverage"]["unexamined"] == 1
    assert response["coverage"]["state"] == "incomplete"


def test_entity_budget_prevents_authority_reads_and_preserves_inventory_coverage():
    from exulanica.api.world_entity_query import resolve_appearances

    inventory = _inventory()
    inventory["coverage"].append({"source": "generated_semantics", "state": "not_enumerated"})
    inventory["representations"] = [{"reference": {"source": "point-map-instance", "id": "map"}}]
    selected = resolve_appearances(None, uuid.uuid4(), inventory, maximum_entities=0)
    assert set(selected.values()) == {"entity_budget"}
    response = query_result(
        inventory, selected, selected, {}, ColourSwatch((255, 0, 0)), BODY["predicate"]
    )
    assert response["coverage"]["entities"]["unknown"] == 2
    assert response["coverage"]["sources"] == inventory["coverage"]
    assert response["coverage"]["representations"] == 1
    assert response["coverage"]["state"] == "incomplete"
    assert reference_key(
        {"reference": {"source": "role-subject", "id": "same", "role_key": "a"}}
    ) != reference_key({"reference": {"source": "role-subject", "id": "same", "role_key": "b"}})


def test_digest_dedup_does_not_bypass_a_second_container_length_binding():
    data = _constant((1, 0, 0, 1)).build()
    first = ("society-being", "one", None)
    second = ("society-being", "two", None)
    appearance = _appearance(data)
    selected = {
        first: appearance,
        second: dataclasses.replace(appearance, container_bytes=len(data) + 1),
    }
    facts = inspect_appearances(selected, lambda _: data)
    assert isinstance(facts[first], dict)
    assert facts[second] == "container_binding_mismatch"
