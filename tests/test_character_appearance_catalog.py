"""Catalog looks in the backend: the browser's draw byte for byte, and saved-look families."""

import copy
import hashlib
import json
import sys
import uuid
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.world.character_appearance import (
    CharacterSubject,
    DrawStream,
    catalog_base_schema_sha256,
    catalog_recipe_families,
    designed_looks,
    draw_look,
    look_from_recipe,
    look_sha256,
    recipe_from_look,
    validate_look,
    validate_recipe,
)

ROOT = Path(__file__).parents[1]
CATALOG = json.loads((ROOT / "assets/characters/catalog.json").read_text())
LOOKS = json.loads((ROOT / "assets/characters/looks.json").read_text())
VECTORS = json.loads((ROOT / "tests/vectors/character_draw_v1.json").read_text())
AVATAR = CharacterSubject(kind="avatar", subject_id=uuid.UUID(int=7))


def test_draw_vectors_shared_with_the_browser_reproduce_exactly():
    assert VECTORS["profile"] == "exulanica.character-draw-conformance/v1"
    assert VECTORS["catalog"] == {
        "catalogId": CATALOG["catalogId"],
        "revision": CATALOG["revision"],
        "canonicalSha256": hashlib.sha256(canonical_json(CATALOG)).hexdigest(),
    }
    assert len(VECTORS["vectors"]) == 10
    for vector in VECTORS["vectors"]:
        stream = DrawStream(VECTORS["domain"], vector["subject"])
        assert stream._seed.decode() == vector["seed"]
        assert [stream.next() for _ in range(12)] == vector["streamPrefix"]
        look = draw_look(CATALOG, VECTORS["domain"], vector["subject"])
        assert look == vector["look"]
        assert look_sha256(look) == vector["lookSha256"]


def test_a_draw_depends_only_on_the_subject_and_the_domain():
    subject = VECTORS["vectors"][0]["subject"]
    reordered = copy.deepcopy(CATALOG)
    for profile in reordered["population"]:
        profile["bases"] = dict(reversed(profile["bases"].items()))
    assert draw_look(reordered, "street-population/v1", subject) == draw_look(
        CATALOG, "street-population/v1", subject
    )
    with pytest.raises(ValueError, match="unknown character draw domain"):
        draw_look(CATALOG, "street-population/v2", subject)


def test_draw_streams_refuse_ambiguous_inputs_and_out_of_range_draws():
    with pytest.raises(ValueError, match="printable ASCII"):
        DrawStream("street-population/v1", "café")
    with pytest.raises(ValueError, match="printable ASCII"):
        DrawStream("street-population/v1", "line\nbreak")
    stream = DrawStream("test/v1", "subject")
    with pytest.raises(ValueError, match="draw bound"):
        stream.below(0)
    with pytest.raises(ValueError, match="draw bound"):
        stream.below(0x200001)
    with pytest.raises(ValueError, match="too wide"):
        stream.triangular(0, 1, 0x200000)
    assert stream.triangular(3, 3, 3) == 3
    values = [stream.triangular(-500, 0, 800) for _ in range(2000)]
    assert min(values) >= -500 and max(values) <= 800
    assert min(values) < -250 and max(values) > 500


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda look: look.update(profile="exulanica.character-look/v2"), "unsupported look"),
        (lambda look: look.update(extra=1), "exactly the declared fields"),
        (lambda look: look["parts"].update(hat=None), "parts must be exactly"),
        (lambda look: look["parts"].update(outfit=None), "outfit is required"),
        (lambda look: look["materials"].update(skin="skin/unknown"), "not a skin"),
        (lambda look: look["colours"].update(hairColour="green"), "not a hairColour"),
        (lambda look: look["parameters"].update(heightMillimetres=2500), "outside"),
        (lambda look: look["parameters"].update(fullness=True), "outside"),
        (lambda look: look["parameters"].update(fullness=12.5), "outside"),
        (lambda look: look.update(baseId="child"), "unknown makehuman-people/v1 base"),
    ],
)
def test_a_look_is_exactly_a_recipe_over_one_base(edit, message):
    look = copy.deepcopy(VECTORS["vectors"][0]["look"])
    edit(look)
    with pytest.raises(ValueError, match=message):
        validate_look(CATALOG, look)


def test_a_look_cannot_wear_another_bodys_part():
    look = copy.deepcopy(VECTORS["vectors"][0]["look"])
    other = "feminine" if look["baseId"] == "masculine" else "masculine"
    look["parts"]["outfit"] = f"{other}/outfit/male_casualsuit01"
    with pytest.raises(ValueError, match="is not a outfit on"):
        validate_look(CATALOG, look)


def test_one_saved_look_family_per_body_with_designed_defaults():
    families = catalog_recipe_families(CATALOG, LOOKS)
    assert [f.family_id for f in families] == [
        "makehuman-people/v1/feminine",
        "makehuman-people/v1/masculine",
    ]
    designed = designed_looks(CATALOG, LOOKS)
    for family, base in zip(families, CATALOG["families"][0]["bases"], strict=True):
        assert family.permitted_uses == ("authored-avatar",)
        parameters = {p.key: p for p in family.parameters}
        outfits = [p["partId"] for p in base["parts"] if p["slot"] == "outfit"]
        assert parameters["outfit"].choices == tuple(outfits)
        assert parameters["hair"].choices[-1] == "none"
        assert (
            parameters["heightMillimetres"].minimum,
            parameters["heightMillimetres"].maximum,
        ) == (
            base["heightMillimetres"]["min"],
            base["heightMillimetres"]["max"],
        )
        assert parameters["fullness"].unit_denominator == 1000
        default = designed[LOOKS["defaults"]["bases"][base["baseId"]]]["look"]
        recipe = recipe_from_look(default, family)
        assert recipe.parameters == {p.key: p.default for p in family.parameters}
        assert validate_recipe(recipe, family, AVATAR) is None
        assert look_from_recipe(CATALOG, recipe, family) == default


def test_every_designed_look_round_trips_through_a_saved_recipe():
    families = {f.family_id: f for f in catalog_recipe_families(CATALOG, LOOKS)}
    for entry in LOOKS["looks"]:
        look = entry["look"]
        family = families[f"{look['familyId']}/{look['baseId']}"]
        recipe = recipe_from_look(look, family)
        validate_recipe(recipe, family, AVATAR)
        assert look_from_recipe(CATALOG, recipe, family) == look
        other = next(f for f in families.values() if f is not family)
        with pytest.raises(ValueError, match="another base"):
            recipe_from_look(look, other)


def test_a_saved_recipe_refuses_another_bodys_garment_and_inhabitant_use():
    feminine, masculine = catalog_recipe_families(CATALOG, LOOKS)
    recipe = recipe_from_look(
        designed_looks(CATALOG, LOOKS)[LOOKS["defaults"]["bases"]["feminine"]]["look"], feminine
    )
    crossed = recipe.model_copy(
        update={"parameters": {**recipe.parameters, "outfit": "masculine/outfit/male_worksuit01"}}
    )
    with pytest.raises(ValueError, match="outfit is not a declared choice"):
        validate_recipe(crossed, feminine, AVATAR)
    with pytest.raises(ValueError, match="exact configured family revision"):
        validate_recipe(recipe, masculine, AVATAR)
    inhabitant = CharacterSubject(
        kind="synthetic-inhabitant", subject_id=uuid.UUID(int=8), society_id=uuid.UUID(int=9)
    )
    with pytest.raises(ValueError, match="does not permit this use"):
        validate_recipe(recipe, feminine, inhabitant)


def test_family_revisions_ignore_population_tuning_and_follow_the_body_they_describe():
    before = catalog_recipe_families(CATALOG, LOOKS)
    tuned = copy.deepcopy(CATALOG)
    tuned["population"][0]["colours"]["hairColour"]["grey"] += 5
    tuned["revision"] += 1
    assert [f.sha256 for f in catalog_recipe_families(tuned, LOOKS)] == [f.sha256 for f in before]
    narrowed = copy.deepcopy(CATALOG)
    masculine = narrowed["families"][0]["bases"][1]
    masculine["heightMillimetres"]["max"] -= 10
    after = catalog_recipe_families(narrowed, LOOKS)
    assert after[0].sha256 == before[0].sha256
    assert after[1].sha256 != before[1].sha256
    family, base = narrowed["families"][0], masculine
    assert after[1].sources[0].content_sha256 == catalog_base_schema_sha256(narrowed, family, base)


def test_a_rebuilt_or_relabelled_body_keeps_every_saved_look_valid():
    """How an id is drawn is not what a saved look means.

    A rebuilt container, a new clip, a better material pack, a relabelled part or a truer hair
    colour value leaves the family revision alone, so looks saved before an improvement still
    resolve after it; removing a part a look may name does not.
    """
    before = [f.sha256 for f in catalog_recipe_families(CATALOG, LOOKS)]
    redrawn = copy.deepcopy(CATALOG)
    family = redrawn["families"][0]
    for base in family["bases"]:
        base["asset"]["contentSha256"] = "0" * 64
        base["clips"]["idle"]["durationMilli"] += 1
        for part in base["parts"]:
            part["label"] = "Renamed"
            part.get("asset", {})["contentSha256"] = "1" * 64
    for material in family["materials"]:
        material["asset"]["contentSha256"] = "2" * 64
        material["roughnessMilli"] = 500
    family["colours"]["hairColour"][0]["rgb"] = "#000000"
    assert [f.sha256 for f in catalog_recipe_families(redrawn, LOOKS)] == before
    removed = copy.deepcopy(CATALOG)
    masculine = removed["families"][0]["bases"][1]
    worn = {
        part
        for entry in LOOKS["looks"]
        if entry["look"]["baseId"] == "masculine"
        for part in entry["look"]["parts"].values()
    }
    victim = next(
        p for p in masculine["parts"] if p["slot"] == "outfit" and p["partId"] not in worn
    )
    masculine["parts"].remove(victim)
    after = [f.sha256 for f in catalog_recipe_families(removed, LOOKS)]
    assert after[0] == before[0]
    assert after[1] != before[1]


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda d: d.update(profile="exulanica.character-looks/v2"), "another catalog or profile"),
        (lambda d: d["looks"].append(copy.deepcopy(d["looks"][0])), "unique ids"),
        (lambda d: d["defaults"].update(player="nobody"), "unknown looks"),
        (lambda d: d["defaults"]["bases"].pop("masculine"), "exactly one designed default"),
        (lambda d: d["looks"][0]["look"]["parts"].update(shoes=None), "shoes is required"),
    ],
)
def test_designed_looks_refuse_what_the_catalog_does_not_offer(edit, message):
    looks = copy.deepcopy(LOOKS)
    edit(looks)
    with pytest.raises(ValueError, match=message):
        catalog_recipe_families(CATALOG, looks)


def test_a_default_over_the_wrong_body_is_refused():
    looks = copy.deepcopy(LOOKS)
    looks["defaults"]["bases"]["feminine"] = looks["defaults"]["bases"]["masculine"]
    with pytest.raises(ValueError, match="over another base"):
        catalog_recipe_families(CATALOG, looks)


def test_the_committed_catalog_verifies_and_leaves_no_container_unreferenced(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import prepare_character_people as people

    assert people.verify() == 93
    assert people.unreferenced_containers(CATALOG) == []
    stray = tmp_path / "assets/characters/makehuman-people-v1/parts/feminine/hat.glb"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"glTF")
    monkeypatch.setattr(people, "ROOT", tmp_path)
    assert people.unreferenced_containers(CATALOG) == ["makehuman-people-v1/parts/feminine/hat.glb"]
