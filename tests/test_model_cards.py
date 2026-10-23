"""The model cards beside the manifest: what each offered model's maker says of it.

Every card names a model the manifest declares and every model a chosen role offers has a card,
so an identifier the manifest moves fails here by name rather than leaving a model the chooser
shows with nobody's words. Each card's quote is one short sentence at most, read from the card at
a pinned revision; a card that is wrong in any of the ways the reader checks is refused.
"""

from __future__ import annotations

import copy
import json

import pytest
from exulanica.models.manifest import load_manifest
from exulanica.models.model_cards import (
    MODEL_CARDS_PATH,
    SAYS_MAXIMUM,
    ModelCardError,
    model_cards,
    read_model_cards,
)
from exulanica.world.decision_roles import decision_roles

DOCUMENT = json.loads(MODEL_CARDS_PATH.read_text(encoding="utf-8"))


def offered_by_a_chosen_role() -> set[str]:
    manifest = load_manifest()
    return {
        spec.model_id
        for role in decision_roles()
        if role.chosen is not None
        for spec in manifest.offered_models(role.chosen)
        if role.contract().mechanism_for(spec) is not None
    }


def test_every_card_names_a_model_the_manifest_declares():
    cards = model_cards()
    assert cards, "the positive control: the shipped file holds cards"
    assert set(cards) <= load_manifest().model_ids, (
        "a card names a model the manifest does not declare: "
        f"{sorted(set(cards) - load_manifest().model_ids)}"
    )


def test_every_model_a_chosen_role_offers_has_its_makers_card():
    offered = offered_by_a_chosen_role()
    assert offered, "the positive control: a chosen role offers models"
    missing = sorted(offered - set(model_cards()))
    assert not missing, f"no card says what these offered models are for: {missing}"


def test_each_card_is_read_at_a_pinned_revision_and_served_with_its_source():
    for model_id, card in model_cards().items():
        served = card.served()
        assert set(served) == {"maker", "parameters", "licence", "says", "source", "read_on"}, (
            model_id
        )
        assert served["source"] == (
            f"https://huggingface.co/{card.card}/blob/{card.revision}/README.md"
        )
        assert len(card.says) <= SAYS_MAXIMUM


def _bad(**changes: object) -> dict:
    document = copy.deepcopy(DOCUMENT)
    model_id = sorted(document["cards"])[0]
    document["cards"][model_id].update(changes)
    return document


@pytest.mark.parametrize(
    ("changes", "why"),
    [
        ({"revision": "main"}, "not a pinned commit"),
        ({"says": "It reasons. It also writes code."}, "one sentence at most"),
        ({"says": "a" * (SAYS_MAXIMUM + 1)}, "one sentence at most"),
        ({"parameters": {"total": "120 billion", "active": None}}, "not a count"),
        ({"parameters": {"total": None, "active": "12B"}}, "needs the total"),
        ({"card": "a model"}, "not a Hugging Face repository"),
        ({"read_on": "today"}, "not a day"),
        ({"maker": " NVIDIA"}, "trimmed string"),
        ({"licence": ""}, "licence is not a non-empty trimmed string"),
        ({"score": 1}, "states exactly"),
    ],
)
def test_a_card_wrong_in_any_way_the_reader_checks_is_refused(changes, why):
    assert read_model_cards(copy.deepcopy(DOCUMENT)), "the positive control: the file reads"
    with pytest.raises(ModelCardError, match=why):
        read_model_cards(_bad(**changes))


def test_a_document_of_another_profile_is_refused():
    with pytest.raises(ModelCardError, match=r"is not exulanica\.model-cards/v1"):
        read_model_cards({**DOCUMENT, "profile": "exulanica.model-cards/v0"})
