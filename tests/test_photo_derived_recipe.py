"""The photo-derived recipe object, which cannot be built without a right for every photograph.

A personal model right (migration 0073) names one capture, one model and one destination, so the
object names one right per photograph and the model and destination those rights must share. Each
test below breaks one of its rules and expects the refusal that rule gives. Nothing here touches a
database or a photograph: the object is plain data, and the check that the rights are current
belongs to the world service that will write the recipe. The last tests hold the object to the
right's own code, so the two spellings of a model and a destination cannot drift apart.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.ingest import model_rights
from exulanica.materials import MaterialObjectError, canonical_bytes
from exulanica.materials.photo_derived import (
    LOCAL_PROCESS,
    LOCAL_PROVIDER,
    PHOTO_DERIVED_RECIPE_PROFILE,
    ModelReference,
    PhotoDerivedRecipe,
    PhotoSource,
)

RECIPE = "ab" * 32
RECEIPT = "cd" * 32
COMMIT = "0123456789abcdef0123456789abcdef01234567"
LOCAL = ModelReference(LOCAL_PROVIDER, "texture_inverse", "exulanica/texture-inverse", COMMIT)
HOSTED = ModelReference("nebius", "vision", "Qwen/Qwen2.5-VL-72B-Instruct", None)
FIRST = uuid.UUID("11111111-1111-4111-8111-111111111111")
SECOND = uuid.UUID("22222222-2222-4222-8222-222222222222")

ORIGINS = (
    "https://models.example.com",
    "https://models.example.com:8443",
    "https://localhost",
    "http://localhost:8080",
    "https://" + "a" * 63 + ".example.com",
)
NOT_ORIGINS = (
    "",
    "local",
    "http://models.example.com",
    "https://models.example.com:443",
    "http://localhost:80",
    "https://models.example.com:0",
    "https://models.example.com:65536",
    "https://models.example.com/v1",
    "https://Models.example.com",
    "https://example",
    "https://10.0.0.1",
    "https://models.0x1f",
    "https://user@models.example.com",
    "https://models.example.com\n",
    "https://" + "a" * 64 + ".example.com",
    "https://" + ".".join(["abcdefghij"] * 25) + ".com",
)
MALFORMED_MODELS = (
    (("Local", "texture_inverse", "m", COMMIT), "provider is a provider key"),
    (("local-ai", "texture_inverse", "m", COMMIT), "provider is a provider key"),
    (("", "texture_inverse", "m", COMMIT), "provider is a provider key"),
    ((None, "texture_inverse", "m", COMMIT), "provider is a provider key"),
    (("local", "Texture", "m", COMMIT), "role is a role name"),
    (("local", "texture inverse", "m", COMMIT), "role is a role name"),
    (("local", "t" * 64, "m", COMMIT), "role is a role name"),
    (("local", "texture_inverse", "", COMMIT), "named by its identifier"),
    (("local", "texture_inverse", "-m", COMMIT), "named by its identifier"),
    (("local", "texture_inverse", "a model", COMMIT), "named by its identifier"),
    (("local", "texture_inverse", "m" * 201, COMMIT), "named by its identifier"),
    (("local", "texture_inverse", "m", COMMIT[:-1]), "revision is a full lowercase commit"),
    (("local", "texture_inverse", "m", COMMIT.upper()), "revision is a full lowercase commit"),
    (("local", "texture_inverse", "m", True), "revision is a full lowercase commit"),
    (("local", "texture_inverse", "m", None), "pinned to a full commit"),
    # The content-pinned form a trained checkpoint will use arrives with that checkpoint.
    (("local", "texture_inverse", "m", "sha256:" + "ab" * 32), "full lowercase commit"),
)


def _source(capture: uuid.UUID, right: uuid.UUID | None = None) -> PhotoSource:
    return PhotoSource(capture, right or uuid.uuid4(), RECEIPT)


def _recipe(**changes) -> PhotoDerivedRecipe:
    fields = {
        "recipe_sha256": RECIPE,
        "model": LOCAL,
        "destination": LOCAL_PROCESS,
        "sources": (_source(FIRST), _source(SECOND)),
    }
    fields.update(changes)
    return PhotoDerivedRecipe(**fields)


# -- what a whole one looks like ---------------------------------------------------------------


def test_the_document_names_the_model_the_destination_and_a_right_per_photograph():
    first, second = uuid.uuid4(), uuid.uuid4()
    recipe = _recipe(sources=(_source(SECOND, second), _source(FIRST, first)))
    document = recipe.as_document()
    assert document == {
        "profile": PHOTO_DERIVED_RECIPE_PROFILE,
        "recipe_sha256": RECIPE,
        "model": {
            "provider": "local",
            "role": "texture_inverse",
            "model_id": "exulanica/texture-inverse",
            "revision": COMMIT,
        },
        "destination": "local-process",
        "sources": [
            {"capture_id": str(SECOND), "right_id": str(second), "right_receipt_sha256": RECEIPT},
            {"capture_id": str(FIRST), "right_id": str(first), "right_receipt_sha256": RECEIPT},
        ],
    }
    # Photographs stay in the order they were read, and the document is canonical JSON.
    assert recipe.source_capture_ids == (SECOND, FIRST)
    assert json.loads(canonical_bytes(document)) == document


def test_the_model_is_spelled_the_way_a_personal_model_right_spells_it():
    assert set(LOCAL.as_record()) == {"provider", "role", "model_id", "revision"}
    assert HOSTED.as_record()["revision"] is None


@pytest.mark.parametrize("destination", ORIGINS)
def test_a_hosted_model_names_an_origin(destination):
    assert _recipe(model=HOSTED, destination=destination).destination == destination


# -- the photographs and their rights ------------------------------------------------------------


def test_a_photograph_is_named_once():
    with pytest.raises(MaterialObjectError, match="each photograph once"):
        _recipe(sources=(_source(FIRST), _source(FIRST)))


def test_two_photographs_never_share_a_right():
    shared = uuid.uuid4()
    with pytest.raises(MaterialObjectError, match="no two photographs share one"):
        _recipe(sources=(_source(FIRST, shared), _source(SECOND, shared)))


@pytest.mark.parametrize(
    "sources",
    [
        (),
        [_source(FIRST)],
        (FIRST,),
        ({"capture_id": str(FIRST)},),
        None,
    ],
    ids=["none", "a list", "a bare capture", "a mapping", "absent"],
)
def test_no_photograph_is_named_without_its_right(sources):
    with pytest.raises(MaterialObjectError, match="never built without a right for each"):
        _recipe(sources=sources)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ((str(FIRST), uuid.uuid4(), RECEIPT), "a photograph is named by its capture id"),
        ((FIRST, None, RECEIPT), "a personal model right is named by its uuid"),
        ((FIRST, str(uuid.uuid4()), RECEIPT), "a personal model right is named by its uuid"),
        ((FIRST, uuid.uuid4(), None), "receipt is named by its sha256"),
        ((FIRST, uuid.uuid4(), "CD" * 32), "receipt is named by its sha256"),
        ((FIRST, uuid.uuid4(), "cd" * 31), "receipt is named by its sha256"),
        ((FIRST, uuid.uuid4(), bytes.fromhex(RECEIPT)), "receipt is named by its sha256"),
    ],
)
def test_a_right_is_its_uuid_and_the_digest_of_its_receipt(fields, message):
    with pytest.raises(MaterialObjectError, match=message):
        PhotoSource(*fields)


# -- where the photographs went ------------------------------------------------------------------


@pytest.mark.parametrize(
    "destination",
    ["https://models.example.com", "http://localhost:8080", "https://localhost"],
)
def test_a_local_model_reads_only_in_this_process(destination):
    """Stricter than the right itself, which only refuses the reverse."""
    with pytest.raises(MaterialObjectError, match="only a local model does"):
        _recipe(model=LOCAL, destination=destination)


def test_a_hosted_model_never_reads_photographs_kept_in_this_process():
    with pytest.raises(MaterialObjectError, match="only a local model does"):
        _recipe(model=HOSTED, destination=LOCAL_PROCESS)


@pytest.mark.parametrize("destination", (*NOT_ORIGINS, None, b"local-process"))
def test_an_origin_is_written_the_one_way_a_right_accepts(destination):
    with pytest.raises(MaterialObjectError, match="names where the photographs went"):
        _recipe(model=HOSTED, destination=destination)


# -- the model -----------------------------------------------------------------------------------


@pytest.mark.parametrize(("fields", "message"), MALFORMED_MODELS)
def test_a_malformed_model_is_refused(fields, message):
    with pytest.raises(MaterialObjectError, match=message):
        ModelReference(*fields)


def test_the_model_is_a_model_reference_and_the_recipe_a_digest():
    with pytest.raises(MaterialObjectError, match="names the model that read it"):
        _recipe(model=LOCAL.as_record())
    for digest in ("ab" * 31, "AB" * 32, None, bytes.fromhex(RECIPE)):
        with pytest.raises(MaterialObjectError, match="names its recipe by sha256"):
            _recipe(recipe_sha256=digest)


# -- the same spellings as the personal model right's own code -------------------------------------


def test_the_local_names_are_the_rights_own():
    assert (LOCAL_PROVIDER, LOCAL_PROCESS) == (
        model_rights.LOCAL_PROVIDER,
        model_rights.LOCAL_PROCESS,
    )


@pytest.mark.parametrize("reference", [LOCAL, HOSTED], ids=["local", "hosted"])
def test_a_model_is_one_record_whichever_module_writes_it(reference):
    identity = model_rights.ModelIdentity(
        provider=reference.provider,
        role=reference.role,
        model_id=reference.model_id,
        revision=reference.revision,
    )
    assert identity.as_record() == reference.as_record()


@pytest.mark.parametrize(("fields", "message"), MALFORMED_MODELS)
def test_a_model_this_object_refuses_the_right_refuses_too(fields, message):
    with pytest.raises(ValueError):
        model_rights.ModelIdentity(*fields)


@pytest.mark.parametrize("destination", ORIGINS)
def test_an_origin_this_object_accepts_is_the_rights_own_spelling(destination):
    assert model_rights.egress_origin(destination) == destination


@pytest.mark.parametrize("destination", NOT_ORIGINS)
def test_an_origin_this_object_refuses_is_never_stored_by_a_right_as_written(destination):
    """The right's code refuses it, or writes it another way before a right can hold it."""
    try:
        spelled = model_rights.egress_origin(destination)
    except ValueError:
        return
    assert spelled != destination
