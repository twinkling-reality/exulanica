"""The local detector's words are a versioned catalog, and the segmentation stage prompts with it.

The words are the stage's parameter, so a mask records exactly the vocabulary it was made under.
A published version is frozen: changing a word is a new version, which re-keys every mask made
under it, never an edit to one that masks already name.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.ingest import stages
from exulanica.ingest.detector_vocabulary import DIRECTORY, detector_vocabulary
from exulanica.ingest.stages import STAGES

#: SHA-256 of ``detector-vocabulary.v1.json`` as published. Masks name its words.
V1_SHA256 = "b1bcb4a9183f4aae838939d40114026f948c8f574dc58f241d69b70060132f2f"


def test_the_segmentation_stage_prompts_with_the_catalog_s_words_in_its_order():
    assert STAGES["segmentation"].params["detector_vocabulary"] == list(detector_vocabulary())
    assert len(detector_vocabulary()) == len(set(detector_vocabulary())) > 0


def test_the_stage_states_no_word_list_of_its_own():
    """The words come from the catalog, never from a list written into the stage's parameters."""
    source = Path(stages.__file__).read_text(encoding="utf-8")
    written = [
        value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and key.value == "detector_vocabulary"
    ]
    assert len(written) == 1
    assert not isinstance(written[0], (ast.List, ast.Tuple)), "the stage restates the vocabulary"


def test_a_published_vocabulary_version_is_frozen():
    published = DIRECTORY / "detector-vocabulary.v1.json"
    assert hashlib.sha256(published.read_bytes()).hexdigest() == V1_SHA256


def test_a_version_with_no_file_is_refused_by_name():
    detector_vocabulary.cache_clear()
    with pytest.raises(CatalogError, match=r"detector-vocabulary\.v999\.json"):
        detector_vocabulary(999)
