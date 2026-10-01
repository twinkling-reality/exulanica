"""Published character catalogs, the parametric family and prepared-body checks, without a DB."""

import copy
import json
import struct
import uuid
from pathlib import Path

import pytest
from exulanica.world.character_appearance import (
    CharacterRecipe,
    CharacterSubject,
    catalog_recipe_families,
    validate_recipe,
)
from exulanica.world.character_bodies import BodyRefused, measure_prepared_body
from exulanica.world.character_catalog_publication import catalog_documents
from exulanica.world.character_catalogs import (
    LAYERED_PROFILE,
    PARAMETRIC_PROFILE,
    PublicationRefused,
    ServedCatalogs,
    layered_bundle,
    read_publication_document,
)
from exulanica.world.character_parametric import (
    body_declaration,
    declared_family,
    is_parametric_family,
    parametric_recipe_families,
    parametric_representation,
    preparer_recipe,
    recipe_input_sha256,
)

ROOT = Path(__file__).parents[1]
CHARACTERS = ROOT / "assets/characters"
CATALOG = json.loads((CHARACTERS / "catalog.json").read_text())
LOOKS = json.loads((CHARACTERS / "looks.json").read_text())
PARAMETRIC = ROOT / "assets/characters/makehuman-parametric-v1"
AVATAR = CharacterSubject(kind="avatar", subject_id=uuid.UUID(int=7))


@pytest.fixture(scope="module")
def documents():
    layered, parametric = catalog_documents(CHARACTERS)
    return layered, parametric


def catalog_b():
    """Revision 3: one feminine hairstyle removed and the feminine height bound narrowed."""
    catalog = copy.deepcopy(CATALOG)
    catalog["revision"] = 3
    feminine = next(b for b in catalog["families"][0]["bases"] if b["baseId"] == "feminine")
    feminine["parts"] = [p for p in feminine["parts"] if p["partId"] != "feminine/hair/long01"]
    feminine["heightMillimetres"]["max"] -= 10
    choices = catalog["population"][0]["choices"]["feminine"]["hair"]
    choices.pop("feminine/hair/long01")
    return layered_bundle(catalog, LOOKS)


# -- publications ---------------------------------------------------------------------------


def test_the_first_publication_derives_every_saved_family_digest_unchanged(documents):
    layered, _ = documents
    publication = read_publication_document(layered)
    assert publication.profile == LAYERED_PROFILE
    assert publication.kind == "layered-people"
    assert (publication.catalog_id, publication.revision) == ("exulanica-characters", 2)
    assert [f.sha256 for f in publication.families] == [
        f.sha256 for f in catalog_recipe_families(CATALOG, LOOKS)
    ]


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d.update(profile="exulanica.character-catalog-bundle/v9"), "no reader"),
        (lambda d: d.update(extra=1), "exactly its catalog and looks"),
        (lambda d: d["catalog"].update(catalogId="Upper"), "catalog id"),
        (lambda d: d["catalog"].update(revision=0), "positive integer"),
        (lambda d: d["catalog"].update(revision=2.5), "positive integer"),
        (lambda d: d["catalog"]["families"][0].update(weight=0.5), "integers and strings"),
        (lambda d: d["looks"]["defaults"].update(player="nobody"), "derive its families"),
    ],
)
def test_a_document_no_adapter_can_read_is_refused_by_name(documents, edit, message):
    layered = copy.deepcopy(documents[0])
    edit(layered)
    with pytest.raises(PublicationRefused, match=message):
        read_publication_document(layered)


def test_served_catalogs_resolve_a_family_to_the_newest_publication_that_derives_it(documents):
    a = read_publication_document(documents[0])
    b = read_publication_document(catalog_b())
    feminine_a, masculine_a = a.families
    feminine_b, masculine_b = b.families
    assert feminine_a.sha256 != feminine_b.sha256
    assert masculine_a.sha256 == masculine_b.sha256

    served = ServedCatalogs(publications=(a, b))
    assert served.resolve(feminine_a.sha256) is a
    assert served.resolve(feminine_b.sha256) is b
    assert served.resolve(masculine_a.sha256) is b
    assert served.current() == (b,)
    assert (served.state(a), served.state(b)) == ("retained", "current")
    assert set(served.families) == {feminine_a.sha256, feminine_b.sha256, masculine_a.sha256}

    withdrawn = ServedCatalogs(publications=(b,), withdrawn=frozenset({a.catalog_sha256}))
    assert withdrawn.resolve(feminine_a.sha256) is None
    assert not withdrawn.serves(feminine_a.sha256)
    assert withdrawn.resolve(masculine_a.sha256) is b


# -- the parametric family --------------------------------------------------------------------


def test_the_parametric_family_is_derived_and_its_default_body_measured(documents):
    _, parametric = documents
    publication = read_publication_document(parametric)
    assert publication.profile == PARAMETRIC_PROFILE
    assert publication.kind == "parametric-body"
    (family,) = publication.families
    assert is_parametric_family(family)
    assert family.permitted_uses == ("authored-avatar",)
    declared = declared_family(parametric, family.family_id)
    kinds = {p.key: p.kind for p in family.parameters}
    assert kinds["heightCm"] == "integer" and kinds["hair"] == "choice"
    weight = next(p for p in family.parameters if p.key == "weight")
    assert (weight.minimum, weight.maximum, weight.unit_denominator) == (150, 850, 1000)
    (body,) = declared.representations
    assert body.representationId == "reviewed:makehuman.parametric.default.v1"
    assert body.asset.contentSha256 == (
        "8eb8c98fa5c516197f1a9a36d76e87145975c28a061d2a9c0762a94e10604051"
    )
    # Measured from the body's own bytes, and equal to what the builder recorded.
    assert body.descriptor.unitScaleMillionths == 1130365
    assert body.descriptor.clips["walk"].speedMillimetresPerSecond == 1181
    assert body.measurements["triangles"] == 41110
    # Thousandths are the builder's numbers again, exactly.
    assert (
        preparer_recipe(declared, body.values)
        == json.loads((PARAMETRIC / "default.look.json").read_text())["recipe"]
    )


def test_a_reviewed_body_binds_only_its_exact_recipe(documents):
    _, parametric = documents
    (family,) = parametric_recipe_families(parametric)
    (body,) = declared_family(parametric, family.family_id).representations
    recipe = CharacterRecipe(
        family_id=family.family_id,
        family_sha256=family.sha256,
        parameters=body.values,
        seed=0,
        representation_id=body.representationId,
    )
    assert recipe.input_sha256 == body.recipeInputSha256 == recipe_input_sha256(body.values)

    def resolve(representation_id):
        return parametric_representation(parametric, family, representation_id)

    binding = validate_recipe(recipe, family, AVATAR, resolve)
    assert binding.asset.asset_key == "makehuman.parametric.default.v1"
    taller = recipe.model_copy(update={"parameters": {**body.values, "heightCm": 176}})
    with pytest.raises(ValueError, match="not prepared for these exact recipe inputs"):
        validate_recipe(taller, family, AVATAR, resolve)
    elsewhere = recipe.model_copy(update={"representation_id": "reviewed:someone.else.v1"})
    with pytest.raises(ValueError, match="not prepared"):
        validate_recipe(elsewhere, family, AVATAR, resolve)
    inhabitant = CharacterSubject(
        kind="synthetic-inhabitant", subject_id=uuid.UUID(int=8), society_id=uuid.UUID(int=9)
    )
    with pytest.raises(ValueError, match="does not permit this use"):
        validate_recipe(recipe, family, inhabitant, resolve)


def test_publishing_another_body_never_changes_what_a_recipe_means(documents):
    _, parametric = documents
    (before,) = parametric_recipe_families(parametric)
    more = copy.deepcopy(parametric)
    family = more["families"][0]
    extra = copy.deepcopy(family["representations"][0])
    extra["values"] = {**extra["values"], "heightCm": 180}
    extra["recipeInputSha256"] = recipe_input_sha256(extra["values"])
    extra["representationId"] = "reviewed:makehuman.parametric.tall.v1"
    family["representations"].append(extra)
    more["revision"] = 2
    (after,) = parametric_recipe_families(more)
    assert after.sha256 == before.sha256
    narrowed = copy.deepcopy(parametric)
    narrowed["families"][0]["controls"][0]["max"] -= 1
    (changed,) = parametric_recipe_families(narrowed)
    assert changed.sha256 != before.sha256


def test_a_body_bound_to_another_recipe_is_refused_in_the_document(documents):
    _, parametric = documents
    tampered = copy.deepcopy(parametric)
    tampered["families"][0]["representations"][0]["values"]["heightCm"] = 190
    with pytest.raises(PublicationRefused, match="bound to another recipe"):
        read_publication_document(tampered)


def test_a_default_body_that_disagrees_with_its_builder_record_is_not_published(tmp_path):
    folder = tmp_path / "makehuman-parametric-v1"
    folder.mkdir()
    for path in PARAMETRIC.iterdir():
        (folder / path.name).write_bytes(path.read_bytes())
    look = json.loads((folder / "default.look.json").read_text())
    look["descriptor"]["unitScale"] *= 1.01
    (folder / "default.look.json").write_text(json.dumps(look))
    (tmp_path / "parametric-catalog.json").write_bytes(
        (CHARACTERS / "parametric-catalog.json").read_bytes()
    )
    with pytest.raises(ValueError, match="unit scale measures"):
        catalog_documents(tmp_path)


# -- prepared-body checks ---------------------------------------------------------------------


def _split(payload):
    length = struct.unpack_from("<I", payload, 12)[0]
    document = json.loads(payload[20 : 20 + length])
    rest = payload[20 + length :]
    binary = bytearray(rest[8 : 8 + struct.unpack_from("<I", rest, 0)[0]])
    return document, binary


def _join(document, binary):
    text = json.dumps(document, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    binary = bytes(binary) + b"\0" * (-len(binary) % 4)
    body = (
        struct.pack("<II", len(text), 0x4E4F534A)
        + text
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body


@pytest.fixture(scope="module")
def body(documents):
    _, parametric = documents
    declared = declared_family(parametric, "makehuman-parametric/v1")
    (representation,) = declared.representations
    payload = (PARAMETRIC / "human-default.glb").read_bytes()
    return payload, body_declaration(declared, representation.values)


def test_the_committed_body_passes_every_check_and_round_trips(body):
    payload, declaration = body
    measured = measure_prepared_body(payload, declaration)
    assert measured.joints == 64 and measured.max_weight_error_millionths < 10_000
    # The helpers below rebuild a container; an untouched rebuild measures the same.
    document, binary = _split(payload)
    assert measure_prepared_body(_join(document, binary), declaration) == measured.__class__(
        **{**measured.document(), "byte_size": len(_join(document, binary))}
    )


def _accessor_offset(document, index):
    accessor = document["accessors"][index]
    view = document["bufferViews"][accessor["bufferView"]]
    return view.get("byteOffset", 0) + accessor.get("byteOffset", 0)


def _hostile(payload, edit):
    document, binary = _split(payload)
    edit(document, binary)
    return _join(document, binary)


def _rename_joint(document, binary):
    document["nodes"][document["skins"][0]["joints"][5]]["name"] = "mixamorig:Tail"


def _drop_weights(document, binary):
    mesh = document["meshes"][0]["primitives"][0]["attributes"]
    del mesh["WEIGHTS_0"]


def _unnormalised(document, binary):
    weights = document["meshes"][0]["primitives"][0]["attributes"]["WEIGHTS_0"]
    struct.pack_into("<ffff", binary, _accessor_offset(document, weights), 0.5, 0.0, 0.0, 0.0)


def _cubic(document, binary):
    for animation in document["animations"]:
        if animation["name"] == "HumanWalk":
            animation["samplers"][1]["interpolation"] = "CUBICSPLINE"


def _flung_joint(document, binary):
    skin = document["skins"][0]
    hand = next(
        i
        for i, node in enumerate(skin["joints"])
        if document["nodes"][node]["name"] == "mixamorig:LeftHand"
    )
    offset = _accessor_offset(document, skin["inverseBindMatrices"]) + hand * 64
    matrix = list(struct.unpack_from("<16f", binary, offset))
    matrix[12] += 25.0
    struct.pack_into("<16f", binary, offset, *matrix)


def _no_hair(document, binary):
    for material in document["materials"]:
        if material["name"] == "Hair":
            material["name"] = "Fur"


@pytest.mark.parametrize(
    ("edit", "failure_class", "code"),
    [
        (_rename_joint, "rig_incompatible", "joints_differ_from_family"),
        (_drop_weights, "rig_incompatible", "influences_not_admitted"),
        (_unnormalised, "rig_incompatible", "weights_not_normalised"),
        (_cubic, "unverified_output", "interpolation_not_admitted"),
        (_flung_joint, "deformation_invalid", "idle_not_on_ground"),
        (_no_hair, "unverified_output", "materials_missing"),
    ],
)
def test_a_body_that_fails_a_check_is_refused_with_its_class(body, edit, failure_class, code):
    payload, declaration = body
    with pytest.raises(BodyRefused) as refused:
        measure_prepared_body(_hostile(payload, edit), declaration)
    assert (refused.value.failure_class, refused.value.code) == (failure_class, code)


def test_a_corrupt_or_oversized_body_is_refused(body):
    payload, declaration = body
    with pytest.raises(BodyRefused) as corrupt:
        measure_prepared_body(payload[:-4096], declaration)
    assert corrupt.value.failure_class == "unverified_output"
    tight = declaration.__class__(
        **{
            **{f: getattr(declaration, f) for f in declaration.__dataclass_fields__},
            "budget": declaration.budget.__class__(
                **{
                    **{
                        f: getattr(declaration.budget, f)
                        for f in declaration.budget.__dataclass_fields__
                    },
                    "max_triangles": 40_000,
                }
            ),
        }
    )
    with pytest.raises(BodyRefused) as over:
        measure_prepared_body(payload, tight)
    assert (over.value.failure_class, over.value.code) == ("over_budget", "triangles")
