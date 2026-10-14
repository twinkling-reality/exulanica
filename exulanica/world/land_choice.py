"""The land a world made from a sentence stands on, chosen from what was said, with no model.

A place made from a person's words stands on one of the land recipes
(:mod:`exulanica.grammar.landform.recipes`), chosen in this order:

1. **the person's words**: the first recipe, in the catalog's order, that a word of the sentence
   names (whole words, any case; no word names two recipes). A word right after ``no``, ``not``,
   ``without``, ``far from`` or ``away from`` (an article between them aside) is not taken, nor
   anything inside a saved name the sentence carries (its placeholder);
2. **the setting**: the ground part the setting chooser took from the words (``sea``,
   ``snowfield``, ...), as the catalog's ``for_ground`` names it;
3. **the default**: the catalog's one default recipe.

The choice says what chose it and, for words, where they are in the sentence as sent, so the
made world's card can say them back. A phrase a drafter reported it could not make is answered by
the land only where every word of it that is not a small joining word names that land
(:func:`said_by_land`: "in a valley", never "sea with flying boats"). The choice says nothing about
whether the land takes the layout: the composer refuses a layout its land cannot take, and the
caller then makes the world on level ground and says so.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from exulanica.grammar.landform import LandRecipe, land_recipes

__all__ = ["LandChoice", "choose_land", "said_by_land"]

_WORD: Final = re.compile(r"[a-z]+")
#: The words, one or two before a land word, that say the sentence does not want it, and the
#: articles that may stand between them and it.
_NOT_WANTED: Final = (("no",), ("not",), ("without",), ("far", "from"), ("away", "from"))
_ARTICLES: Final = frozenset({"a", "an", "the", "any"})
#: The small words a phrase about land is joined with, which name nothing themselves.
_JOINING: Final = _ARTICLES | frozenset(
    {"in", "on", "by", "at", "near", "beside", "under", "below", "above", "over", "among", "of"}
    | {"along", "to", "from", "with", "and", "up", "down", "into", "onto", "upon"}
)


@dataclass(frozen=True, slots=True)
class LandChoice:
    recipe: LandRecipe
    chosen_by: Literal["words", "setting", "default"]
    #: Where the word that chose it is in the sentence as sent; empty unless words chose it.
    spans: tuple[tuple[int, int], ...]


def _named_by_words(
    text: str, names: Sequence[tuple[int, int]]
) -> tuple[LandRecipe, tuple[int, int]] | None:
    recipes = land_recipes()
    tokens = [
        (match.group(), match.span())
        for match in _WORD.finditer(text.lower())
        if not any(start < match.end() and match.start() < end for start, end in names)
    ]
    found: dict[str, tuple[int, int]] = {}
    for index, (word, span) in enumerate(tokens):
        before = tuple(token for token, _ in tokens[:index] if token not in _ARTICLES)[-2:]
        if any(before[-len(phrase) :] == phrase for phrase in _NOT_WANTED):
            continue
        for recipe in recipes:
            if word in recipe.words and recipe.key not in found:
                found[recipe.key] = span
    for recipe in recipes:
        if recipe.key in found:
            return recipe, found[recipe.key]
    return None


def choose_land(
    text: str, ground: str | None, *, names: Sequence[tuple[int, int]] = ()
) -> LandChoice:
    """The land for a place described by ``text`` (the words as sent, ``names`` the spans of the
    saved names replaced in it), whose setting took the ground part ``ground`` or none."""
    named = _named_by_words(text, names)
    if named is not None:
        return LandChoice(recipe=named[0], chosen_by="words", spans=(named[1],))
    recipes = land_recipes()
    if ground is not None:
        for recipe in recipes:
            if ground in recipe.for_ground:
                return LandChoice(recipe=recipe, chosen_by="setting", spans=())
    return LandChoice(
        recipe=next(recipe for recipe in recipes if recipe.default), chosen_by="default", spans=()
    )


def said_by_land(phrase: str, recipe: LandRecipe) -> bool:
    """Whether the land ``recipe`` says all of ``phrase``: it names something, and every word of it
    but the small joining words is one of the recipe's own words."""
    named = [word for word in _WORD.findall(phrase.lower()) if word not in _JOINING]
    return bool(named) and all(word in recipe.words for word in named)
