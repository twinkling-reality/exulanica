"""What each offered model's maker says of it: ``model-cards.v1.json`` beside the manifest.

A person choosing a model reads who made it, how large it is, what its maker says it is for,
where it runs and what it costs. The last two the manifest already states (a provider on this
computer, the prices); this file holds the first three as they were read once from the model's
own card on Hugging Face, at a pinned revision, on the day it names: the maker, the parameters
as the card states them (``None`` where it states none), the licence the card states (by its plain
name, as ``docs/license-matrix.md`` reads it) and one short quote, a whole sentence or clause of
the maker's words, of what the maker says the model is for.

Every word of a card's ``says`` is its maker's. Nothing here is this product's own claim about a
model, and nothing compares one model with another. A model served from this computer names the
card of the open model it is built from. ``tests/test_model_cards.py`` holds every card to a
model the manifest declares and every model a chosen role offers to a card, so an identifier the
manifest moves fails there by name.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

__all__ = [
    "MODEL_CARDS_PATH",
    "PROFILE",
    "SAYS_MAXIMUM",
    "ModelCard",
    "ModelCardError",
    "model_card",
    "model_cards",
    "read_model_cards",
]

MODEL_CARDS_PATH: Final = Path(__file__).with_name("model-cards.v1.json")
PROFILE: Final = "exulanica.model-cards/v1"
#: The longest quote a card keeps, in characters: a whole sentence or clause of the maker's words
#: that fits about 120 characters, as the chooser shows it on two lines at most.
SAYS_MAXIMUM: Final = 120
_CARD_FIELDS: Final = frozenset(
    {"maker", "card", "revision", "parameters", "licence", "says", "read_on"}
)
#: A card's repository on Hugging Face: its owner and its name.
_REPOSITORY: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
#: A pinned revision: the card's commit, never a branch that moves.
_REVISION: Final = re.compile(r"[0-9a-f]{40}")
#: A parameter count as a card writes it: "120B", "3.5B".
_COUNT: Final = re.compile(r"[0-9]+(\.[0-9]+)?B")
_DAY: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
#: Where one sentence ends and another begins.
_SECOND_SENTENCE: Final = re.compile(r"[.!?]\s+\S")


class ModelCardError(ValueError):
    """The cards file, or one card in it, is not what this module reads."""


@dataclass(frozen=True, slots=True)
class ModelCard:
    """One model's card, as it was read."""

    maker: str
    #: The card's repository on Hugging Face.
    card: str
    revision: str
    #: The parameters in all and those active for each token, as the card states them; ``None``
    #: where it states none (a dense model states no active count).
    total: str | None
    active: str | None
    licence: str
    says: str
    read_on: str

    @property
    def source(self) -> str:
        """The card at the revision it was read at."""
        return f"https://huggingface.co/{self.card}/blob/{self.revision}/README.md"

    def served(self) -> dict[str, Any]:
        """The card as the models read serves it beside each model."""
        return {
            "maker": self.maker,
            "parameters": None
            if self.total is None
            else {"total": self.total, "active": self.active},
            "licence": self.licence,
            "says": self.says,
            "source": self.source,
            "read_on": self.read_on,
        }


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ModelCardError(f"{where} is not a non-empty trimmed string")
    return value


def _card(model_id: str, value: object) -> ModelCard:
    if not isinstance(value, Mapping) or set(value) != _CARD_FIELDS:
        raise ModelCardError(f"{model_id}: a card states exactly {sorted(_CARD_FIELDS)}")
    card = _text(value["card"], f"{model_id}: card")
    if _REPOSITORY.fullmatch(card) is None:
        raise ModelCardError(f"{model_id}: card {card!r} is not a Hugging Face repository")
    revision = _text(value["revision"], f"{model_id}: revision")
    if _REVISION.fullmatch(revision) is None:
        raise ModelCardError(f"{model_id}: revision {revision!r} is not a pinned commit")
    parameters = value["parameters"]
    total = active = None
    if parameters is not None:
        if not isinstance(parameters, Mapping) or set(parameters) != {"total", "active"}:
            raise ModelCardError(f"{model_id}: parameters state total and active, or are null")
        total, active = parameters["total"], parameters["active"]
        for count in (total, active):
            if count is not None and (
                not isinstance(count, str) or _COUNT.fullmatch(count) is None
            ):
                raise ModelCardError(f"{model_id}: {count!r} is not a count like 120B")
        if total is None:
            raise ModelCardError(f"{model_id}: an active count needs the total beside it")
    says = _text(value["says"], f"{model_id}: says")
    if len(says) > SAYS_MAXIMUM or "\n" in says or _SECOND_SENTENCE.search(says):
        raise ModelCardError(
            f"{model_id}: says is one sentence at most, of {SAYS_MAXIMUM} characters or fewer"
        )
    read_on = _text(value["read_on"], f"{model_id}: read_on")
    if _DAY.fullmatch(read_on) is None:
        raise ModelCardError(f"{model_id}: read_on {read_on!r} is not a day")
    return ModelCard(
        maker=_text(value["maker"], f"{model_id}: maker"),
        card=card,
        revision=revision,
        total=total,
        active=active,
        licence=_text(value["licence"], f"{model_id}: licence"),
        says=says,
        read_on=read_on,
    )


def read_model_cards(document: object) -> Mapping[str, ModelCard]:
    """Every card in a cards document, by the manifest identifier of the model it describes."""
    if not isinstance(document, Mapping) or document.get("profile") != PROFILE:
        raise ModelCardError(f"the cards document is not {PROFILE}")
    cards = document.get("cards")
    if not isinstance(cards, Mapping) or not cards:
        raise ModelCardError("the cards document states no cards")
    return MappingProxyType(
        {str(model_id): _card(str(model_id), card) for model_id, card in cards.items()}
    )


@lru_cache(maxsize=1)
def model_cards() -> Mapping[str, ModelCard]:
    """The shipped cards. Cached: the file ships with the code and never changes under it."""
    try:
        document = json.loads(MODEL_CARDS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelCardError(f"no model cards at {MODEL_CARDS_PATH}") from exc
    return read_model_cards(document)


def model_card(model_id: str) -> ModelCard | None:
    """The card of the model the manifest names ``model_id``, or ``None`` where none is kept (a
    model a workspace probed, which ships no card)."""
    return model_cards().get(model_id)
