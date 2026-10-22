"""A landing refusal's words are data the server reads (``assets/catalogs/landing-words``): every
sentence the rule says, with exactly the slots it fills, and every part kind named once with the
sentence it is said with; a catalog that would say less, or leave a slot the rule never fills, is
refused by name (``exulanica/world/thing_landing.py`` ``landing_words``). What each refusal says is
pinned in ``tests/test_thing_landing.py``."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.world.thing_landing import (
    LANDING_WORDS_DIRECTORY,
    PART_KINDS,
    SENTENCE_SLOTS,
    BlockedPart,
    landing_words,
    step_words,
)
from exulanica.world.thing_landing import _blocked_words as blocked_words


def _copy(tmp_path: Path) -> Path:
    directory = tmp_path / "landing-words"
    shutil.copytree(LANDING_WORDS_DIRECTORY, directory)
    return directory


def _edit(directory: Path, name: str, key: str, field: str, value: object) -> None:
    path = directory / name
    document = json.loads(path.read_text(encoding="utf-8"))
    (entry,) = [entry for entry in document["entries"] if entry["key"] == key]
    entry[field] = value
    path.write_text(json.dumps(document), encoding="utf-8")


def test_every_sentence_and_every_part_kind_is_stated_once():
    words = landing_words()
    assert set(words.sentences) == set(SENTENCE_SLOTS)
    assert set(words.parts) == set(PART_KINDS)
    # Each part kind is said with its own name, in its kind's sentence; one with no words of its
    # own is somewhere people cannot walk through.
    for kind in PART_KINDS:
        said = blocked_words(BlockedPart(kind, "", ()))
        name, sentence = words.parts[kind]
        assert said.endswith(".") and (name in said if name else sentence == "unnamed_part")
    assert blocked_words(BlockedPart("water", "duck pond", ())) == "That spot is in the duck pond."
    assert blocked_words(BlockedPart("blocked", "anything", ())) == (
        "That spot is somewhere people cannot walk through."
    )


def test_a_step_is_said_in_the_forms_the_catalog_states_rounded_up():
    assert [step_words(mm) for mm in (201, 250, 999, 1_000, 1_201)] == [
        "21 cm",
        "25 cm",
        "1.0 m",
        "1.0 m",
        "1.3 m",
    ]


@pytest.mark.parametrize(
    ("name", "key", "field", "value", "refused"),
    [
        # A slot the rule never fills, and one it fills that the sentence leaves out.
        ("landing-sentence.v1.json", "off_ground", "words", "The ground there is {step}.", "fills"),
        ("landing-sentence.v1.json", "in_part", "words", "That spot is in the {place}.", "fills"),
        ("landing-sentence.v1.json", "step_metres", "words", "{} m", "fills"),
        # A part said with a sentence the rule does not say of parts.
        ("landing-part.v1.json", "water", "sentence", "outside", "is one of"),
        # A part said by its name with none, and a nameless one said by a name it lacks.
        ("landing-part.v1.json", "water", "name", "", "has one"),
        ("landing-part.v1.json", "blocked", "sentence", "on_part", "has one"),
    ],
)
def test_a_catalog_that_would_say_otherwise_is_refused_by_name(
    tmp_path, name, key, field, value, refused
):
    directory = _copy(tmp_path)
    # Positive control: the copy as shipped reads as the shipped words do.
    assert landing_words(directory) == landing_words()
    edited = tmp_path / "edited"
    shutil.copytree(directory, edited)
    _edit(edited, name, key, field, value)
    with pytest.raises(CatalogError, match=refused):
        landing_words(edited)


def test_a_catalog_missing_a_sentence_or_a_part_kind_is_refused(tmp_path):
    for name, key, refused in (
        ("landing-sentence.v1.json", "side_higher", "the rule says"),
        ("landing-part.v1.json", "tree", "a part is one of"),
    ):
        directory = tmp_path / key
        shutil.copytree(LANDING_WORDS_DIRECTORY, directory)
        path = directory / name
        document = json.loads(path.read_text(encoding="utf-8"))
        document["entries"] = [entry for entry in document["entries"] if entry["key"] != key]
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(CatalogError, match=refused):
            landing_words(directory)
