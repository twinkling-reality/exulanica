"""The volume document: parts from the volume catalogs, every value held to its bound, refused by
path and code; the catalogs and the volume rules that name them are pinned."""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import shutil
from pathlib import Path

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.landform import SERVED_LAND_RULES, land_rules
from exulanica.grammar.volumes import (
    CATALOG_VERSION,
    CATALOG_VERSIONS,
    LAND_CATALOGS,
    PROFILE,
    SERVED_VOLUME_RULES,
    SHAPES,
    VOLUME_RULES_VERSION,
    VolumeRefused,
    check_volume_rules,
    load_volume_catalog,
    read_volume_document,
    volume_catalog,
    volume_rules,
)

CATALOGS = Path(__file__).parents[1] / "assets" / "catalogs" / "volumes"

#: Every shipped volume catalog, byte for byte. A catalog changes by a new file
#: (``volume-value.v2.json``) and a new volume rules version; never by an edit, since a world's
#: volumes name the catalogs that shaped them.
SHIPPED = {
    "volume-shape.v1.json": "a74a4ac2b8679d36caf3603c82011fd9b05ca3ca42622907402d6ed49a831e45",
    "volume-value.v1.json": "8da177cfd44b106adc05abb6852f80e3ecd9362db7eaac925b426c26347a870c",
    "volume-shape.v2.json": "46dd7702ec5757e20426c660b11010bc1bbf1b7d965f1272bd97ec734b01073f",
    "volume-value.v2.json": "ced8acf3b5675bd1bd43c70ce3af14f8cd29ddb32bdee2130fd055680d98287b",
    "volume-shape.v3.json": "6fe17ddbd5accec6aed83e6ccf25eaf2e65ac3b7d479185a20ee2858ab8305f6",
    "volume-value.v3.json": "6590e0d89cb675bb79e850bf7ac562467921b81403e20e2bfba03c38b295194d",
}

#: Each volume rules version and the catalog digests it names.
RULES = {
    1: {
        "volume-shape.v1": "d48a201d138463faeb44b572d9eba01ee6b9be999925e3414b7ddccdda7aa196",
        "volume-value.v1": "d9614f44462693864815532efeac4de59e76718d066cfe77b17ce5494ed3f869",
    },
    2: {
        "volume-shape.v2": "cc5763039e163e8358a478fb5abb63b376c1a6473b89e98cd4d94b37b055e19d",
        "volume-value.v2": "b1879ca4841ee62a7a20cb597bd5ef76cef730498e2918b0dce6565c2a6f3cb5",
    },
    3: {
        "volume-shape.v3": "1483230908de90e963bcf95eb41083c79288de764e5b13bba5b9f09f8c14a46b",
        "volume-value.v3": "c10eb009d170e772d0646e910dab79422f9d2865adfc58e3d9927bebf07bb1e4",
    },
}
#: Each volume rules version whose volumes may state a top land, and the land rules realizing it.
TOP_LAND_RULES = {3: 3}

#: A sea stack: an overhanging column, a shoulder, a leaning spur, a tilted ledge, a sea arch
#: through its foot and a level top, weathered and bedded.
STACK = {
    "profile": PROFILE,
    "id": "sea_stack",
    "erosion": {"amplitude_mm": 2500, "wavelength_mm": 14000, "octaves": 3, "ridged": "yes"},
    "strata": {"amplitude_mm": 600, "period_mm": 3200},
    "parts": [
        {"id": "trunk", "shape": "column", "at_mm": [0, 0, -8000], "height_mm": 52000,
         "base_radius_mm": 11000, "top_radius_mm": 15000, "round_mm": 2000},
        {"id": "shoulder", "shape": "sphere", "at_mm": [6000, -3000, 30000], "radius_mm": 9000,
         "blend_mm": 4000},
        {"id": "spur", "shape": "capsule", "at_mm": [-4000, 5000, 20000],
         "to_mm": [-14000, 9000, 16000], "radius_mm": 5000, "to_radius_mm": 1500,
         "blend_mm": 3000, "yaw_mdeg": 30000},
        {"id": "ledge", "shape": "box", "at_mm": [8000, 8000, 10000],
         "size_mm": [12000, 9000, 6000], "round_mm": 1500, "blend_mm": 2000,
         "tilt_mdeg": 12000, "toward_mdeg": 210000},
        {"id": "sea_arch", "shape": "arch", "at_mm": [0, 0, -3000], "width_mm": 9000,
         "spring_mm": 6000, "depth_mm": 40000, "blend_mm": 1500, "yaw_mdeg": 70000},
        {"id": "top", "shape": "cap", "height_mm": 41000, "blend_mm": 800},
    ],
}  # fmt: skip
#: The stack's identity read against each catalog version: the newer carries its strata values too.
STACK_SHA256 = {
    1: "a3d38dc6ba7dba815092cc8868307e76cec4e12c83b4637b21e28b25b27b66bd",
    2: "486944d84cad9c8c4ce63a5294083c89368d0a3b427fbbe79a220fb2179945ca",
    3: "486944d84cad9c8c4ce63a5294083c89368d0a3b427fbbe79a220fb2179945ca",
}

BOULDER = {"id": "boulder", "shape": "sphere", "radius_mm": 3000}


def volume(*parts: dict, **top: object) -> dict:
    return {"profile": PROFILE, "id": "mass", **top, "parts": [dict(part) for part in parts]}


def refusal(raw: object) -> VolumeRefused:
    with pytest.raises(VolumeRefused) as caught:
        read_volume_document(raw)
    return caught.value


def test_the_shipped_catalogs_are_never_edited():
    found = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in CATALOGS.iterdir()
    }
    assert found == SHIPPED


def test_every_value_names_an_owner_and_holds_its_default_and_every_shape_has_a_field():
    catalog = volume_catalog()
    assert set(catalog.shapes) == SHAPES
    owners = {"volume", "erosion", "strata", "part", "top_land", *catalog.shapes}
    for (owner, name), bound in catalog.values.items():
        assert owner in owners, (owner, name)
        if bound.words:
            assert 0 <= bound.default < len(bound.words), (owner, name)
        else:
            assert bound.minimum <= bound.default <= bound.maximum, (owner, name)
    assert {key for key, shape in catalog.shapes.items() if not shape.placed} == {"cap"}
    assert catalog.shapes["arch"].ops == ("carve",)


def test_a_stated_document_is_read_with_its_defaults_written_in():
    read = read_volume_document(volume(BOULDER, {"id": "flat", "shape": "cap", "height_mm": 1000}))
    assert read.canonical() == {
        "profile": PROFILE,
        "id": "mass",
        "look": "rock",
        "top_look": "moss",
        "walk": "tops",
        "erosion": {"amplitude_mm": 0, "wavelength_mm": 12000, "octaves": 3, "ridged": "no"},
        "strata": {"amplitude_mm": 0, "period_mm": 3000, "spread_mm": 0, "relief_permille": 0,
                   "offset_permille": 0, "tilt_mdeg": 0, "toward_mdeg": 0},
        "parts": [
            {"id": "boulder", "shape": "sphere", "op": "add", "at_mm": [0, 0, 0], "yaw_mdeg": 0,
             "tilt_mdeg": 0, "toward_mdeg": 0, "blend_mm": 0, "look": "volume",
             "radius_mm": 3000},
            {"id": "flat", "shape": "cap", "op": "cap", "blend_mm": 0, "look": "volume",
             "height_mm": 1000},
        ],
    }  # fmt: skip


def test_the_identity_is_the_digest_of_the_canonical_document_and_reading_it_again_keeps_it():
    for version in CATALOG_VERSIONS:
        catalog = volume_catalog(version)
        read = read_volume_document(STACK, catalog)
        assert read.sha256 == hashlib.sha256(read.canonical_bytes).hexdigest()
        assert (read.sha256, read.catalog_version) == (STACK_SHA256[version], version)
        again = read_volume_document(read.canonical(), catalog)
        assert again.canonical_bytes == read.canonical_bytes
    assert read_volume_document(STACK).catalog_version == CATALOG_VERSION


def test_a_later_catalog_keeps_every_entry_of_the_one_before():
    for earlier, later in itertools.pairwise(CATALOG_VERSIONS):
        before, after = volume_catalog(earlier), volume_catalog(later)
        assert after.shapes == before.shapes
        assert {key: after.values[key] for key in before.values} == dict(before.values)


def test_the_strata_vary_their_beds_only_from_catalog_version_2():
    varied = {"amplitude_mm": 900, "period_mm": 4000, "spread_mm": 2000, "tilt_mdeg": 4000}
    read = read_volume_document(volume(BOULDER, strata=varied))
    assert read.strata["spread_mm"] == 2000 and read.strata["relief_permille"] == 0
    with pytest.raises(VolumeRefused) as caught:
        read_volume_document(volume(BOULDER, strata=varied), volume_catalog(1))
    assert caught.value.path == "strata"
    assert "states no spread_mm, tilt_mdeg" in caught.value.detail
    widest = {"amplitude_mm": 900, "period_mm": 4000, "spread_mm": 3000}
    assert read_volume_document(volume(BOULDER, strata=widest)).strata["spread_mm"] == 3000
    too_wide = refusal(volume(BOULDER, strata={**widest, "spread_mm": 3001}))
    assert (too_wide.path, too_wide.code) == ("strata.spread_mm", "volume_invalid")
    assert "at least 1 m" in too_wide.detail


def test_reading_never_changes_the_document_it_was_given():
    raw = copy.deepcopy(STACK)
    read_volume_document(raw)
    assert raw == STACK


def _with(path: tuple, value: object) -> dict:
    raw = copy.deepcopy(STACK)
    target = raw
    for step in path[:-1]:
        target = target[step]
    if value is _DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return raw


_DELETE = object()


@pytest.mark.parametrize(
    ("path", "value", "where", "code", "words"),
    [
        (("profile",), "exulanica.volume/v2", "profile", "volume_invalid", "profile is"),
        (("colour",), "red", "", "volume_invalid", "may have"),
        (("id",), "Sea Stack", "id", "volume_invalid", "lowercase key"),
        (("look",), "glass", "look", "volume_invalid", "one of rock, wall"),
        (("erosion", "depth_mm"), 3, "erosion", "volume_invalid", "states no depth_mm"),
        (("erosion", "amplitude_mm"), 9000, "erosion.amplitude_mm", "volume_invalid", "0 to 8000"),
        (("strata",), [600], "strata", "volume_invalid", "an object"),
        (("parts", 0, "shape"), "cone", "parts[0].shape", "volume_invalid", "not one of"),
        (("parts", 0, "colour"), 1, "parts[0]", "volume_invalid", "states no colour"),
        (("parts", 0, "height_mm"), _DELETE, "parts[0].height_mm", "volume_invalid", "required"),
        (("parts", 1, "radius_mm"), 400001, "parts[1].radius_mm", "volume_invalid",
         "500 to 400000"),
        (("parts", 1, "radius_mm"), 9000.5, "parts[1].radius_mm", "volume_invalid",
         "whole number"),
        (("parts", 1, "radius_mm"), True, "parts[1].radius_mm", "volume_invalid", "whole number"),
        (("parts", 1, "at_mm"), [0, 0], "parts[1].at_mm", "volume_invalid", "list of 3"),
        (("parts", 1, "at_mm"), [0, 0, 1300000], "parts[1].at_mm[2]", "volume_invalid",
         "-1200000 to 1200000"),
        (("parts", 1, "yaw_mdeg"), 360000, "parts[1].yaw_mdeg", "volume_invalid", "0 to 359999"),
        (("parts", 1, "id"), "trunk", "parts[1].id", "volume_invalid", "used twice"),
        (("parts", 4, "op"), "add", "parts[4].op", "volume_part_wrong_op", "does carve"),
        (("parts", 5, "at_mm"), [0, 0, 0], "parts[5].at_mm", "volume_part_wrong_op",
         "states no at_mm"),
        (("parts", 3, "round_mm"), 4600, "parts[3].round_mm", "volume_rounding_too_large",
         "half its smallest side"),
        (("parts", 0, "round_mm"), 11001, "parts[0].round_mm", "volume_rounding_too_large",
         "smaller radius"),
        (("parts", 2, "to_mm"), [0, 0, 0], "parts[2].to_mm", "volume_invalid", "not its own point"),
    ],
)  # fmt: skip
def test_every_refusal_names_its_path_its_code_and_what_it_broke(path, value, where, code, words):
    refused = refusal(_with(path, value))
    assert (refused.path, refused.code) == (where, code)
    assert words in refused.detail


def test_a_volume_lists_one_to_its_catalog_most_parts_and_adds_at_least_one():
    most = volume_catalog().values[("volume", "parts")].maximum
    spheres = [{**BOULDER, "id": f"boulder_{index}"} for index in range(most + 1)]
    assert (refusal(volume(*spheres)).code, refusal(volume(*spheres)).path) == (
        "volume_too_many_parts",
        "parts",
    )
    assert read_volume_document(volume(*spheres[:most])).parts[-1].id == f"boulder_{most - 1}"
    assert refusal(volume()).path == "parts"
    carved = {**BOULDER, "op": "carve"}
    assert "adds at least one part" in refusal(volume(carved)).detail


def test_the_volume_rules_name_the_shipped_catalogs_by_digest():
    assert VOLUME_RULES_VERSION in SERVED_VOLUME_RULES
    for version, catalogs in RULES.items():
        named: dict[str, object] = {"version": version, "catalogs": catalogs}
        if version in TOP_LAND_RULES:
            named["land_rules"] = land_rules(TOP_LAND_RULES[version])
            # The land rules read the landform catalog the volume catalog reads a top land against.
            land_catalog = LAND_CATALOGS[SERVED_VOLUME_RULES[version]]
            assert SERVED_LAND_RULES[TOP_LAND_RULES[version]] == land_catalog
        assert volume_rules(version) == named
        assert check_volume_rules(volume_rules(version)) == SERVED_VOLUME_RULES[version]
    assert set(RULES) == set(SERVED_VOLUME_RULES)
    served = SERVED_VOLUME_RULES.items()
    assert set(TOP_LAND_RULES) == {rules for rules, catalog in served if catalog in LAND_CATALOGS}


@pytest.mark.parametrize(
    "named",
    [
        None,
        {"version": 2, "catalogs": RULES[1]},
        {"version": 3, "catalogs": RULES[2]},
        {"version": 1, "catalogs": {**RULES[1], "volume-value.v1": "0" * 64}},
        {"version": 1, "catalogs": {"volume-shape.v1": RULES[1]["volume-shape.v1"]}},
    ],
)
def test_rules_this_server_does_not_serve_are_refused_by_name(named):
    with pytest.raises(VolumeRefused) as caught:
        check_volume_rules(named)
    assert caught.value.code == "volume_rules_changed"
    assert f"volume rules version {VOLUME_RULES_VERSION}" in caught.value.detail
    assert "versions 1, 2" in caught.value.detail


def _corrupt(tmp_path: Path, name: str, change) -> Path:
    for path in CATALOGS.iterdir():
        shutil.copy(path, tmp_path / path.name)
    target = tmp_path / name
    document = json.loads(target.read_text(encoding="utf-8"))
    change(document["entries"])
    target.write_text(json.dumps(document), encoding="utf-8")
    return tmp_path


def _entry(entries: list, key: str) -> dict:
    return next(entry for entry in entries if entry["key"] == key)


@pytest.mark.parametrize("version", CATALOG_VERSIONS)
@pytest.mark.parametrize(
    ("name", "change", "words"),
    [
        ("volume-value", lambda e: _entry(e, "part_blend_mm").update(default=-1),
         "default lies within"),
        ("volume-value", lambda e: _entry(e, "volume_walk").update(default=2),
         "indexes its words"),
        ("volume-value", lambda e: _entry(e, "sphere_radius_mm").update(owner="ball"),
         "unknown owner"),
        ("volume-value", lambda e: _entry(e, "sphere_radius_mm").update(value="size_mm"),
         "keyed by its owner and value"),
        ("volume-value", lambda e: e.remove(_entry(e, "part_tilt_mdeg")),
         "does not bound part_tilt_mdeg"),
        ("volume-shape", lambda e: _entry(e, "cap").update(ops=["cap", "add"]),
         "does nothing else"),
        ("volume-shape", lambda e: _entry(e, "arch").update(ops=["bend"]),
         "distinct words"),
    ],
)  # fmt: skip
def test_a_catalog_that_breaks_its_own_rules_is_refused(tmp_path, version, name, change, words):
    directory = _corrupt(tmp_path, f"{name}.v{version}.json", change)
    with pytest.raises(CatalogError, match=words):
        load_volume_catalog(directory, version)
