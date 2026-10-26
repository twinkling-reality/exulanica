"""A town made from a person's words is titled from them: their sentence up to its first comma, or
its first 48 characters ending on a whole word, with a capital first letter and no full stop; never
a saved name it holds; cut short, never ending on a joining word the catalog lists; the preset's
label where fewer than two words are left (``exulanica/api/world_making.py`` ``title_from_words``
and ``assets/catalogs/world-titles/title-joining-word.v2.json``)."""

from __future__ import annotations

import pytest
from exulanica.api.world_making import (
    TITLE_FROM_WORDS_CHARACTERS,
    title_from_words,
    title_joining_words,
)
from exulanica.selection.world_drafting import SentDescription


def _typed(words: str, *, names: tuple[tuple[int, int], ...] = ()) -> SentDescription:
    """``words`` as typed, with saved names at ``names`` (where each stands in the typed words); the
    sent text is not read by the title."""
    return SentDescription(
        text=words,
        placeholders={},
        typed=words,
        replaced=tuple((start, end, start, end) for start, end in names),
    )


def test_a_sentence_is_titled_up_to_its_first_comma_with_a_capital_and_no_full_stop():
    words = "a cozy little town by the sea at dusk, with a bakery, a bookshop and a lighthouse"
    assert title_from_words(_typed(words)) == "A cozy little town by the sea at dusk"
    assert title_from_words(_typed("  a harbour town at night.  ")) == "A harbour town at night"


def test_a_long_sentence_is_cut_at_48_characters_on_a_whole_word():
    words = "a long quiet market town of red brick houses beside a slow river and a mill"
    title = title_from_words(_typed(words))
    assert title == "A long quiet market town of red brick houses"
    assert len(title) <= TITLE_FROM_WORDS_CHARACTERS and words.startswith(title.lower())


def test_a_saved_name_never_enters_the_title_which_ends_before_it():
    words = "a quiet town where Ada Lovelace keeps a bakery, by the sea"
    at = words.index("Ada Lovelace")
    named = _typed(words, names=((at, at + len("Ada Lovelace")),))
    assert title_from_words(named) == "A quiet town"
    # A saved name after the first comma does not shorten it.
    later = words.index("sea")
    assert title_from_words(_typed(words, names=((later, later + 3),))) == (
        "A quiet town where Ada Lovelace keeps a bakery"
    )


@pytest.mark.parametrize("word", sorted(title_joining_words()))
def test_a_title_cut_short_never_ends_on_a_joining_word_the_catalog_lists(word):
    assert title_from_words(_typed(f"a quiet harbour town {word}, by the sea")) == (
        "A quiet harbour town"
    )
    assert title_from_words(_typed(f"a quiet harbour town {word} {word.upper()}, by the sea")) == (
        "A quiet harbour town"
    )


def test_a_cut_at_48_characters_drops_the_joining_words_it_ends_on():
    words = "a long quiet market town of red brick houses and the old mill by a river"
    within = " ".join(words.split()[:10])
    assert within == "a long quiet market town of red brick houses and"
    assert len(within) <= TITLE_FROM_WORDS_CHARACTERS < len(within + " the")
    assert title_from_words(_typed(words)) == "A long quiet market town of red brick houses"


@pytest.mark.parametrize(
    ("words", "title"),
    [
        # DESIGN's finding (26 October): the cut fell inside "on a misty morning" and "with glowing
        # windows", leaving the adjective without its noun.
        (
            "a bright toy town among wheat fields on a misty morning",
            "A bright toy town among wheat fields",
        ),
        (
            "a snowy mountain village at night with glowing windows",
            "A snowy mountain village at night",
        ),
        # DESIGN (26 October): a phrase of place ("beneath", "among", ...) goes whole too.
        (
            "a quiet mountain village beneath tall snowy peaks and pine forests",
            "A quiet mountain village",
        ),
    ],
)
def test_a_cut_for_length_inside_a_phrase_drops_the_whole_phrase(words, title):
    assert title_from_words(_typed(words)) == title


def test_a_whole_sentence_keeps_its_last_word():
    """Nothing was cut, so the person's own last word stands."""
    assert title_from_words(_typed("a little town to grow old in")) == (
        "A little town to grow old in"
    )


def test_the_joining_words_are_single_lowercase_words_with_their_class():
    words = title_joining_words()
    assert {"a", "the", "of", "and", "where"} <= words
    assert all(word.isalpha() and word == word.casefold() for word in words)
    # A noun a title may well end on is not one of them.
    assert not {"town", "sea", "harbour", "night"} & words


def test_fewer_than_two_words_leave_the_preset_s_label():
    assert title_from_words(_typed("harbour, with boats")) is None
    words = "Ada Lovelace's town"
    assert title_from_words(_typed(words, names=((0, len("Ada Lovelace")),))) is None
    assert title_from_words(_typed("a" * 60 + " town")) is None
    assert title_from_words(_typed("harbour and the, with boats")) is None
