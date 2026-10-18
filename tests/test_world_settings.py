"""A world's setting: the shared cases, the two legibility rules, the named parts and every
published look.

The case file is shared with the browser's reader
(``web/packages/atlas-core/test/world-setting.test.ts``), which must reach the same verdict on
every case: the same refusal reason and path, or the same digest of the setting and of the pack as
drawn. Each refusal's reason and path were stated by hand when the case was written. The two
legibility figures are checked against arithmetic done by hand here, and the looks are read from
their committed files, never through the code under test.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.world import style_packs
from exulanica.world import world_settings as ws
from exulanica.world.style_pack_library import load_style_pack_library

ROOT = Path(__file__).resolve().parents[1]
STYLE_PACKS = ROOT / "assets" / "style-packs"
CASES: dict[str, Any] = json.loads(
    (STYLE_PACKS / "settings" / "setting-cases.v1.json").read_text(encoding="utf-8")
)
SHARED: dict[str, Any] = json.loads(
    (STYLE_PACKS / "manifest-cases.v1.json").read_text(encoding="utf-8")
)
RULES = ws.load_setting_rules()
PARTS = ws.load_setting_parts()
CONTEXT = style_packs.load_context(ROOT)
#: What a preset states that is a look's finish and frame cost, never a setting's.
THE_LOOKS_OWN = ("tone_mapping", "sun.shadow", "contact_shadow", "sky.face_texels", "post.taa")


def _case_context() -> style_packs.StylePackContext:
    stated = SHARED["context"]
    return style_packs.StylePackContext(
        families={
            key: style_packs.LookFamily(**value) for key, value in stated["families"].items()
        },
        texture_sets=frozenset(stated["texture_sets"]),
    )


def _case_pack(name: str) -> ws.ResolvedPack:
    context = _case_context()
    return ws.resolve_chain(
        [style_packs.read_manifest(manifest, context) for manifest in CASES["packs"][name]]
    )


def _published() -> list[tuple[str, dict[str, Any]]]:
    """Every version of every look the library holds, current and earlier, from the files."""
    found = []
    for manifest in sorted(STYLE_PACKS.glob("packs/*/manifest.json")):
        found.append((f"{manifest.parent.name} current", json.loads(manifest.read_text("utf-8"))))
    for manifest in sorted(STYLE_PACKS.glob("published/*/*/manifest.json")):
        name = f"{manifest.parent.parent.name} version {manifest.parent.name}"
        found.append((name, json.loads(manifest.read_text("utf-8"))))
    return found


PUBLISHED = _published()


@pytest.mark.parametrize("case", CASES["cases"], ids=[case["name"] for case in CASES["cases"]])
def test_every_shared_case_has_its_stated_verdict(case: dict[str, Any]) -> None:
    expected = case["expect"]
    pack = _case_pack(case["pack"])
    if "sha256" in expected:
        setting = ws.read_setting(case["setting"], RULES)
        applied = ws.apply_setting(pack, setting, _case_context(), RULES)
        assert ws.setting_sha256(setting) == expected["sha256"]
        assert ws.applied_sha256(applied) == expected["drawn_sha256"]
        return
    with pytest.raises(ws.SettingRefused) as refused:
        ws.apply_setting(pack, ws.read_setting(case["setting"], RULES), _case_context(), RULES)
    assert (refused.value.reason, refused.value.path) == (expected["refusal"], expected["path"])


def test_the_cases_cover_a_valid_setting_and_every_refusal_reason() -> None:
    reasons = {case["expect"].get("refusal", "valid") for case in CASES["cases"]}
    assert reasons == {"valid", "shape", "range", "reference", "duplicate", "legibility"}


def test_a_setting_that_changes_nothing_draws_the_pack_as_it_is() -> None:
    town = CASES["packs"]["town"][0]
    pack = _case_pack("town")
    own = ws.AppliedSetting(pack=pack, preset=town["light"]["presets"]["day"])
    nothing = next(c for c in CASES["cases"] if c["name"] == "a setting that changes nothing")
    assert nothing["expect"]["drawn_sha256"] == ws.applied_sha256(own)


def test_reading_returns_the_setting_it_was_given() -> None:
    for case in CASES["cases"]:
        if "sha256" in case["expect"]:
            assert ws.read_setting(case["setting"], RULES) == case["setting"]


def test_open_light_is_the_sun_on_level_ground_and_the_sky_through_the_exposure() -> None:
    # By hand: a white sun straight overhead at strength 1 gives white's luminance, 65535; a white
    # sky at image light 1 and sky strength 1 gives the same; exposure 1 leaves their sum.
    preset = copy.deepcopy(CASES["packs"]["town"][0]["light"]["presets"]["day"])
    preset["exposure_permille"] = 1000
    preset["sun"].update(
        {"elevation_mdeg": 85_000, "colour": [255, 255, 255], "intensity_permille": 1000}
    )
    preset["sky"].update(
        {"zenith": [255, 255, 255], "horizon": [255, 255, 255], "intensity_permille": 1000}
    )
    preset["environment"]["intensity_permille"] = 1000
    # sin(85 degrees) is 0.9962; Bhaskara's form gives 4*85*95/(40500-85*95) = 0.9961, which is
    # 996 per mille.
    assert ws.open_light(preset, RULES) == 65535 * 996 // 1000 + 65535
    preset["exposure_permille"] = 500
    assert ws.open_light(preset, RULES) == (65535 * 996 // 1000 + 65535) // 2
    preset["sun"]["intensity_permille"] = 0
    preset["sky"]["zenith"] = preset["sky"]["horizon"] = [0, 0, 0]
    assert ws.open_light(preset, RULES) == 0


def test_contrast_is_the_lighter_over_the_darker_each_raised_a_twentieth_of_white() -> None:
    # By hand: white over black is (65535 + 3277) / 3277 = 20.998, the WCAG ratio's 21 to 1.
    assert ws.contrast_permille([255, 255, 255], [0, 0, 0], RULES) == 20998
    assert ws.contrast_permille([0, 0, 0], [255, 255, 255], RULES) == 20998
    assert ws.contrast_permille([90, 120, 30], [90, 120, 30], RULES) == 1000


def test_the_floors_stand_where_their_sources_say() -> None:
    """The rules file cites figures; this holds the file to them."""
    cozy = json.loads((STYLE_PACKS / "packs/exulanica.cozy-town/manifest.json").read_text("utf-8"))
    assert ws.open_light(cozy["light"]["presets"]["evening"], RULES) == 21032
    too_dark = next(c for c in CASES["cases"] if c["name"].startswith("a night too dark"))
    town = _case_pack("town")
    night = copy.deepcopy(dict(town.light["presets"]["day"]))
    for path, value in too_dark["setting"]["light"]["changes"].items():
        *parents, leaf = path.split(".")
        holder = night
        for parent in parents:
            holder = holder[parent]
        holder[leaf] = value
    assert ws.open_light(night, RULES) < RULES.open_light_minimum < 21032
    resolved = ws.resolve_chain([cozy])
    footway = ws._role_colour(resolved, "path.footway_paving")
    carriageway = ws._role_colour(resolved, "road.carriageway_asphalt")
    paint = ws._role_colour(resolved, "road.road_paint_white")
    assert footway is not None and carriageway is not None and paint is not None
    assert ws.contrast_permille(footway, carriageway, RULES) == 2556
    assert ws.contrast_permille(paint, carriageway, RULES) == 3569


def test_a_setting_may_change_no_part_of_a_looks_finish_or_frame_cost() -> None:
    preset = CASES["packs"]["town"][0]["light"]["presets"]["day"]
    for path in RULES.light_changes:
        assert not any(path == own or path.startswith(f"{own}.") for own in THE_LOOKS_OWN), path
        *parents, leaf = path.split(".")
        holder: Any = preset
        for name in parents:
            assert name in holder, f"{path} is no value of a preset"
            holder = holder[name]
        if leaf in holder:
            continue
        # A value the profile added later, which a preset may leave out (the night's stars and
        # moon): a part states it, and the preset reads with it.
        stated = [
            alternative["changes"][path]
            for part in PARTS.parts.values()
            for alternative in part["light"]
            if path in alternative["changes"]
        ]
        assert stated, f"{path} is no value of a preset"
        changed = copy.deepcopy(preset)
        target = changed
        for name in parents:
            target = target[name]
        target[leaf] = stated[0]
        assert style_packs._light_preset(changed, "")[parents[0]][leaf] == stated[0]
    assert len(set(RULES.light_changes)) == len(RULES.light_changes)


@pytest.mark.parametrize("named", PUBLISHED, ids=[name for name, _ in PUBLISHED])
def test_every_published_look_stands_in_light_a_setting_is_held_to(
    named: tuple[str, dict[str, Any]],
) -> None:
    """A look never states a preset its own setting rule would refuse."""
    _name, manifest = named
    if manifest["light"] is None:
        pytest.skip("drawn on a base, which states the light")
    for key, preset in manifest["light"]["presets"].items():
        assert ws.open_light(preset, RULES) >= RULES.open_light_minimum, key


@pytest.mark.parametrize("named", PUBLISHED, ids=[name for name, _ in PUBLISHED])
def test_every_part_makes_a_setting_every_published_look_can_wear(
    named: tuple[str, dict[str, Any]],
) -> None:
    """A world keeps the look version it was given, so each part must compose and apply over every
    version the library still serves, alone and one of each axis together."""
    _name, manifest = named
    chain = [style_packs.read_manifest(manifest, CONTEXT)]
    if manifest["base"] is not None:
        # A look drawn on another is worn on its whole chain, as the library holds it.
        below = load_style_pack_library().chain(manifest["base"]["manifest_sha256"])
        assert below is not None, "the library does not hold this look's base"
        chain.extend(below)
    pack = ws.resolve_chain(chain)
    for axis, key in PARTS.parts:
        composed = ws.compose_setting({axis: key}, pack, CONTEXT, PARTS)
        setting = ws.read_setting(composed, RULES)
        assert setting == composed
        ws.apply_setting(pack, setting, CONTEXT, RULES)
    by_axis: dict[str, list[str]] = {}
    for axis, key in PARTS.parts:
        by_axis.setdefault(axis, []).append(key)
    for sky in by_axis["sky"]:
        for ground in by_axis["ground"]:
            for cover in by_axis["cover"]:
                chosen = {"sky": sky, "ground": ground, "cover": cover}
                setting = ws.read_setting(ws.compose_setting(chosen, pack, CONTEXT, PARTS), RULES)
                ws.apply_setting(pack, setting, CONTEXT, RULES)


def test_a_composed_setting_is_exact_for_its_look() -> None:
    cozy = ws.resolve_chain(
        [json.loads((STYLE_PACKS / "packs/exulanica.cozy-town/manifest.json").read_text("utf-8"))]
    )
    finished = ws.resolve_chain(
        [
            json.loads(
                (STYLE_PACKS / "packs/exulanica.finished-town/manifest.json").read_text("utf-8")
            )
        ]
    )
    # Cozy town states lit glass; Finished town does not, so its night leaves that swatch out.
    assert "glass_lit" in cozy.swatches and "glass_lit" not in finished.swatches
    night = ws.compose_setting({"sky": "night"}, cozy, CONTEXT, PARTS)
    assert night["swatches"]["glass_lit"] == {"emission_permille": 1000}
    assert (
        "glass_lit"
        not in ws.compose_setting({"sky": "night"}, finished, CONTEXT, PARTS)["swatches"]
    )
    # Snow lies on the upward faces of every wall role the look dresses, and of no other family.
    snow = ws.compose_setting({"cover": "snow"}, cozy, CONTEXT, PARTS)
    walls = {role for role in cozy.surfaces if role.startswith("wall.")}
    assert set(snow["up"]) == walls and len(walls) > 3
    assert snow["parts"] == [{"axis": "cover", "key": "snow"}]
    # Axes are applied in the file's order, so snow lies over a ground's bare earth.
    both = ws.compose_setting({"cover": "snow", "ground": "sand"}, cozy, CONTEXT, PARTS)
    assert both["parts"] == [{"axis": "ground", "key": "sand"}, {"axis": "cover", "key": "snow"}]
    assert both["surfaces"]["ground.default"] == snow["surfaces"]["ground.default"]
    assert both["edge"] == ws.compose_setting({"ground": "sand"}, cozy, CONTEXT, PARTS)["edge"]


def test_dusk_is_the_looks_own_evening_and_figures_for_a_look_that_states_none() -> None:
    town = _case_pack("town")
    assert "evening" in town.light["presets"]
    assert ws.compose_setting({"sky": "dusk"}, town, _case_context(), PARTS)["light"] == {
        "from": "evening",
        "changes": {},
    }
    day_only = ws.ResolvedPack(
        light={"default_preset": "day", "presets": {"day": town.light["presets"]["day"]}},
        edge=town.edge,
        swatches=town.swatches,
        surfaces=town.surfaces,
    )
    composed = ws.compose_setting({"sky": "dusk"}, day_only, _case_context(), PARTS)
    assert composed["light"]["from"] == "day" and composed["light"]["changes"]
    ws.apply_setting(day_only, ws.read_setting(composed, RULES), _case_context(), RULES)


#: A computed sky as a look states one, for the parts' figures over it.
ANALYTIC = {
    "kind": "analytic",
    "turbidity_permille": 2200,
    "rayleigh_permille": 1000,
    "mie_micro": 3500,
    "mie_direction_permille": 780,
}


def _computed(pack: ws.ResolvedPack) -> ws.ResolvedPack:
    """``pack`` with its default preset's sky computed from its sun."""
    presets = copy.deepcopy(dict(pack.light["presets"]))
    presets[pack.light["default_preset"]]["sky"]["model"] = dict(ANALYTIC)
    return ws.ResolvedPack(
        light={**pack.light, "presets": presets},
        edge=pack.edge,
        swatches=pack.swatches,
        surfaces=pack.surfaces,
    )


def _part_light(key: str) -> dict[str, Any]:
    return next(part for (axis, name), part in PARTS.parts.items() if name == key)["light"][0]


def test_a_computed_sky_takes_a_parts_own_figures_for_it_and_a_gradient_none() -> None:
    town = _case_pack("town")
    computed = _computed(town)
    noon = _part_light("clear_noon")
    # A computed sky at a noon sun is several times a gradient's brightness: the part dims it there.
    assert noon["for_sky_model"]["analytic"] == {
        "sky.intensity_permille": 250,
        "environment.intensity_permille": 450,
    }
    assert noon["changes"]["sky.intensity_permille"] == 1000
    over_gradient = ws.compose_setting({"sky": "clear_noon"}, town, _case_context(), PARTS)
    assert over_gradient["light"]["changes"] == noon["changes"]
    over_computed = ws.compose_setting({"sky": "clear_noon"}, computed, _case_context(), PARTS)
    assert over_computed["light"]["changes"] == {
        **noon["changes"],
        **noon["for_sky_model"]["analytic"],
    }
    applied = ws.apply_setting(
        computed, ws.read_setting(over_computed, RULES), _case_context(), RULES
    )
    assert applied.preset["sky"]["model"] == ANALYTIC
    assert applied.preset["sky"]["intensity_permille"] == 250
    # Under full cloud the part draws its own gradient over a computed sky, as the night does on
    # any look, and over a gradient it states nothing of the sky's model.
    for key in ("overcast", "thick_fog"):
        plain = ws.compose_setting({"sky": key}, town, _case_context(), PARTS)
        assert "sky.model" not in plain["light"]["changes"]
        composed = ws.compose_setting({"sky": key}, computed, _case_context(), PARTS)
        assert composed["light"]["changes"] == {**plain["light"]["changes"], "sky.model": None}
        drawn = ws.apply_setting(computed, ws.read_setting(composed, RULES), _case_context(), RULES)
        assert drawn.preset["sky"]["model"] is None


def test_a_sky_a_part_turns_to_the_gradient_takes_none_of_its_computed_figures(
    tmp_path: Path,
) -> None:
    source = json.loads((STYLE_PACKS / "settings" / ws.PARTS_FILE).read_text("utf-8"))
    night = next(part for part in source["parts"] if part["key"] == "night")
    night["light"][0]["for_sky_model"] = {"analytic": {"exposure_permille": 500}}
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings" / ws.PARTS_FILE).write_text(json.dumps(source), "utf-8")
    parts = ws.load_setting_parts(tmp_path / "settings", RULES)
    composed = ws.compose_setting(
        {"sky": "night"}, _computed(_case_pack("town")), _case_context(), parts
    )
    assert (
        composed["light"]["changes"]["exposure_permille"]
        == night["light"][0]["changes"]["exposure_permille"]
    )


def test_the_earlier_parts_file_still_reads_and_composes_as_it_did(tmp_path: Path) -> None:
    """Version 2, unread by the host, stays as it was: under this reader it reads, and its noon over
    a computed sky is its own figures, with none for that sky."""
    earlier = (STYLE_PACKS / "settings" / "setting-parts.v2.json").read_text("utf-8")
    assert '"version": 2' in earlier and "for_sky_model" not in earlier
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings" / ws.PARTS_FILE).write_text(earlier, "utf-8")
    parts = ws.load_setting_parts(tmp_path / "settings", RULES)
    assert parts.version == 2 and parts.parts.keys() == PARTS.parts.keys()
    composed = ws.compose_setting(
        {"sky": "clear_noon"}, _computed(_case_pack("town")), _case_context(), parts
    )
    assert composed["light"]["changes"]["sky.intensity_permille"] == 1000


def test_a_parts_figures_for_a_computed_sky_name_a_model_and_values_a_setting_may_change(
    tmp_path: Path,
) -> None:
    source = json.loads((STYLE_PACKS / "settings" / ws.PARTS_FILE).read_text("utf-8"))
    at = next(index for index, part in enumerate(source["parts"]) if part["key"] == "clear_noon")
    (tmp_path / "settings").mkdir()

    def load(document: dict[str, Any]) -> ws.SettingParts:
        (tmp_path / "settings" / ws.PARTS_FILE).write_text(json.dumps(document), "utf-8")
        return ws.load_setting_parts(tmp_path / "settings", RULES)

    unknown = copy.deepcopy(source)
    unknown["parts"][at]["light"][0]["for_sky_model"] = {"gradient": {"exposure_permille": 900}}
    with pytest.raises(style_packs.StylePackRefused) as refused:
        load(unknown)
    assert (refused.value.reason, refused.value.path) == (
        "reference",
        f"parts[{at}].light[0].for_sky_model.gradient",
    )
    finish = copy.deepcopy(source)
    finish["parts"][at]["light"][0]["for_sky_model"]["analytic"]["tone_mapping"] = "linear"
    with pytest.raises(style_packs.StylePackRefused) as refused:
        load(finish)
    assert (refused.value.reason, refused.value.path) == (
        "reference",
        f"parts[{at}].light[0].for_sky_model.analytic.tone_mapping",
    )


def test_the_parts_name_the_sky_models_the_look_reader_reads() -> None:
    """The kinds a part may state figures for are the look reader's own: it reads a preset whose
    sky is computed by each, and refuses one of another kind."""
    town = CASES["packs"]["town"][0]

    def read(kind: str) -> dict[str, Any]:
        manifest = copy.deepcopy(town)
        manifest["light"]["presets"]["day"]["sky"]["model"] = {**ANALYTIC, "kind": kind}
        return style_packs.read_manifest(manifest, _case_context())

    for kind in ws.SKY_MODEL_KINDS:
        assert read(kind)["light"]["presets"]["day"]["sky"]["model"]["kind"] == kind
    with pytest.raises(style_packs.StylePackRefused) as refused:
        read("gradient")
    assert (refused.value.reason, refused.value.path) == (
        "range",
        "light.presets.day.sky.model.kind",
    )


def test_a_part_that_is_not_listed_is_refused_by_name() -> None:
    with pytest.raises(ws.SettingRefused) as refused:
        ws.compose_setting({"sky": "aurora"}, _case_pack("town"), _case_context(), PARTS)
    assert (refused.value.reason, refused.value.path) == ("reference", "parts.sky")
    with pytest.raises(ws.SettingRefused) as refused:
        ws.compose_setting({"weather": "night"}, _case_pack("town"), _case_context(), PARTS)
    assert (refused.value.reason, refused.value.path) == ("reference", "parts.weather")


def test_the_parts_file_states_three_axes_and_what_each_part_is_for() -> None:
    assert [axis for axis, _title in PARTS.axes] == ["sky", "ground", "cover"]
    listed = PARTS.listed()
    assert len(listed) == len(PARTS.parts) == 11
    for part in listed:
        assert set(part) == {"axis", "key", "title", "description"}
        assert len(part["description"].split()) >= 5
    for part in PARTS.parts.values():
        assert part["reason"].startswith("Authored:")


def test_a_parts_file_is_refused_for_an_unknown_axis_and_a_repeated_part(tmp_path: Path) -> None:
    source = json.loads((STYLE_PACKS / "settings" / ws.PARTS_FILE).read_text("utf-8"))
    (tmp_path / "colour").mkdir()
    settings = tmp_path / "style-packs" / "settings"
    settings.mkdir(parents=True)

    def load(document: dict[str, Any]) -> ws.SettingParts:
        settings.joinpath(ws.PARTS_FILE).write_text(json.dumps(document), "utf-8")
        return ws.load_setting_parts(settings, RULES)

    assert load(source).parts.keys() == PARTS.parts.keys()
    stray = copy.deepcopy(source)
    stray["parts"][0]["axis"] = "weather"
    with pytest.raises(style_packs.StylePackRefused) as refused:
        load(stray)
    assert (refused.value.reason, refused.value.path) == ("reference", "parts[0].axis")
    twice = copy.deepcopy(source)
    twice["parts"].append(copy.deepcopy(twice["parts"][0]))
    with pytest.raises(style_packs.StylePackRefused) as refused:
        load(twice)
    assert refused.value.reason == "duplicate"
    shadow = copy.deepcopy(source)
    shadow["parts"][0]["light"][0]["changes"]["sun.shadow"] = {"filter": "pcf1"}
    with pytest.raises(style_packs.StylePackRefused) as refused:
        load(shadow)
    assert refused.value.reason == "reference"
    # The rules name every part a stored setting may state: a parts file that names another, or
    # leaves one out, is refused, so the two files never differ.
    renamed = copy.deepcopy(source)
    renamed["parts"][0]["key"] = "first_light"
    with pytest.raises(style_packs.StylePackRefused) as refused:
        load(renamed)
    assert (refused.value.reason, refused.value.path) == ("reference", "parts")
    fewer = copy.deepcopy(source)
    fewer["parts"].pop()
    with pytest.raises(style_packs.StylePackRefused) as refused:
        load(fewer)
    assert (refused.value.reason, refused.value.path) == ("reference", "parts")
    assert {axis: set(keys) for axis, keys in RULES.part_names.items()} == {
        axis: {key for one, key in PARTS.parts if one == axis} for axis, _ in PARTS.axes
    }


def test_the_composed_settings_file_is_what_its_script_writes() -> None:
    """The page's tests draw the committed file, so it must be what the server composes today."""
    import importlib.util
    import sys

    path = ROOT / "scripts" / "style_packs" / "composed_settings.py"
    spec = importlib.util.spec_from_file_location("composed_settings_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        committed = (STYLE_PACKS / "settings" / "setting-composed.v1.json").read_text("utf-8")
        assert committed == module.text()
    finally:
        del sys.modules[spec.name]
    document = json.loads(committed)
    assert document["parts_version"] == PARTS.version
    looks = {row["pack_id"] for row in document["composed"]}
    assert looks == {folder.name for folder in (STYLE_PACKS / "packs").iterdir()}
    assert len(document["composed"]) == len(looks) * (len(PARTS.parts) + 1)
