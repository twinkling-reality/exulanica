"""Numbers a role's callers use are the manifest's, stated there with their reasons.

The composer's completion ceiling, the prompt tokens one image is reserved at and the width of an
embedding are single-model facts. Each is declared once in ``models.manifest.json`` beside the
measurement it rests on; the code reads it, and a role that states none is refused by name rather
than given a number nobody chose.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal

import pytest
from exulanica.epistemics.caption_embeddings import QueryEmbedding
from exulanica.models.errors import ManifestError
from exulanica.models.manifest import MANIFEST_PATH, Role, load_manifest, parse_manifest


def _document():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)


def test_a_role_s_image_reservation_is_per_image():
    binding = load_manifest()[Role.VISION]
    assert binding.image_prompt_tokens_reserved is not None
    assert binding.image_reservation(3) == 3 * binding.image_reservation(1)


def test_a_role_that_declares_no_image_reservation_is_sent_no_image():
    with pytest.raises(ManifestError, match="declares no image_prompt_tokens_reserved"):
        load_manifest()[Role.STRUCTURED_EXTRACTION].image_reservation(1)


def test_a_query_vector_of_another_width_is_refused():
    width = load_manifest()[Role.EMBEDDING].primary.embedding_dimensions
    QueryEmbedding(vector=(1.0,) * width, model_id="m", pipeline_version=1)
    with pytest.raises(ValueError, match=f"must contain {width} finite dimensions"):
        QueryEmbedding(vector=(1.0,) * (width - 1), model_id="m", pipeline_version=1)


@pytest.mark.parametrize(
    "declared",
    [
        {"value": 800},
        {"value": 800, "basis": " "},
        {"value": 0, "basis": "a reason"},
        {"value": 800, "basis": "a reason", "unit": "tokens"},
        800,
    ],
    ids=["no-basis", "blank-basis", "zero", "extra-field", "bare-number"],
)
def test_a_declared_number_states_a_positive_value_and_its_reason(declared):
    document = copy.deepcopy(_document())
    document["roles"]["vision"]["image_prompt_tokens_reserved"] = declared
    with pytest.raises(ManifestError, match="image_prompt_tokens_reserved"):
        parse_manifest(document)


def test_a_judgement_names_the_record_that_measured_it():
    document = copy.deepcopy(_document())
    judge = next(key for key, spec in document["models"].items() if "judging" in spec)
    document["models"][judge]["judging"] = {"sign_completeness": "a later measurement"}
    with pytest.raises(ManifestError, match=r"judging\.sign_completeness names the record"):
        parse_manifest(document)
