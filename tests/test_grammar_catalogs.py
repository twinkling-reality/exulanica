"""Catalogs are versioned, licensed data, and the loader refuses anything else.

*   Every shipped entry **carries a licence** stated the way ``docs/license-matrix.md`` states
    one, and every file's **id and version match its name**.
*   The **catalog digest is stable** across two interpreter processes with different hash seeds,
    and it moves when an entry does.
*   A material whose **texture set does not resolve raises**; it is never defaulted.
*   An **unknown key is rejected** rather than ignored, at every level.
*   **What ships is pinned**: every catalog's file version and entry count, and the package
    document names every file with its count, so an entry cannot land without the document that
    describes the catalogs being revisited.

*   A texture manifest outside its agreed shape is refused, and a **rebaked texture set moves the
    catalog digest** while the catalog file stays byte-identical; a set no entry uses does not.

Catalog files and manifests written under ``tmp_path`` below are test inputs. Their texture set
ids, such as ``test-texture-set``, name nothing real and never appear in a shipped file. The
entries written for a catalog start from a shipped entry of that catalog, so an entry refused below
is refused for the one change the case makes. ``tests/test_grammar_city_catalogs.py`` holds what the
city's catalogs say.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

import pytest
from exulanica.grammar.catalogs import (
    LICENCE_VERDICTS,
    CatalogSchema,
    ReferenceField,
    catalog_digest,
    load_catalog,
    text_field,
)
from exulanica.grammar.errors import CatalogError, UnresolvedReferenceError
from exulanica.grammar.grammars.city import catalogs as city_catalogs
from exulanica.grammar.grammars.city.catalogs import (
    CATALOG_DIRECTORY,
    city_catalog_schemas,
    load_city_catalogs,
)
from exulanica.grammar.grammars.city.common import ROLE_CLASSES, SURFACE_ROLES
from exulanica.grammar.textures import (
    MANIFEST_PROFILE,
    TEXTURE_SET_ID,
    TextureSet,
    read_texture_manifest,
)
from exulanica.materials.manifest import CONTAINER_LAYOUT

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs" / "grammar-package.md"

#: What ships today: each catalog's file version and entry count. A change here is a change to
#: what the city can say, and the package document has to say it too.
EXPECTED_CATALOGS = {
    "action-vocabulary": (1, 0),
    "band": (1, 1),
    "crossing-type": (1, 3),
    "era": (1, 4),
    "fitout": (1, 7),
    "junction-control": (1, 4),
    "lane-use": (2, 6),
    "material": (4, 16),
    "parking-kind": (1, 5),
    "roof-family": (2, 3),
    "rooftop-object": (1, 4),
    "signage-lexicon": (2, 18),
    "street-furniture": (2, 9),
    "street-hierarchy": (2, 4),
    "street-name": (1, 12),
    "tree-species": (2, 19),
    "typology": (2, 7),
    "use-class": (1, 11),
}

_ORIGINAL = {
    "spdx": "Apache-2.0",
    "verdict": "SHIP",
    "origin": "original",
    "licence_source": "LICENSE",
    "content_source": "docs/grammar-package.md",
}

_NO_SETS: Mapping[str, TextureSet] = MappingProxyType({})
_TEST_SETS = {"test-texture-set": TextureSet("test-texture-set", 1, "a" * 64, "opaque")}


def _version(catalog_id: str) -> int:
    return EXPECTED_CATALOGS[catalog_id][0]


def _shipped_entry(catalog_id: str, **changes: object) -> dict:
    """A copy of the first shipped entry of a catalog, with ``changes``, as an input to write."""
    path = CATALOG_DIRECTORY / f"{catalog_id}.v{_version(catalog_id)}.json"
    entry = json.loads(path.read_text(encoding="utf-8"))["entries"][0]
    return {**entry, "licence": _ORIGINAL, **changes}


_MATERIAL_ENTRY = _shipped_entry(
    "material", key="test_material", label="Test material", texture_set_id="test-texture-set"
)


def _write(
    directory: Path, stem: str, entries: list, *, version: int | None = None, **envelope: object
) -> Path:
    """``<stem>.v<version>.json``, whose envelope says the same unless ``envelope`` overrides it.

    The version is the shipped catalog's unless given. An empty entry list gets the statement the
    loader requires of one, because these fixtures use ``[]`` as a neutral input to the refusals
    below rather than as a claim that a vocabulary is deliberately empty.
    """
    version = _version(stem) if version is None else version
    document = {
        "schema_version": 1,
        "catalog_id": stem,
        "catalog_version": version,
        "entries": entries,
        **({} if entries else {"empty_reason": "A fixture with no entries, written by a test."}),
        **envelope,
    }
    path = directory / f"{stem}.v{version}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _schema(catalog_id: str, *, texture_sets: Mapping[str, TextureSet] = _NO_SETS) -> CatalogSchema:
    schemas = city_catalog_schemas(texture_sets=texture_sets)
    return next(schema for schema in schemas if schema.catalog_id == catalog_id)


# ---------------------------------------------------------------------------------------------
# What ships


def test_the_shipped_catalogs_load_and_hold_what_is_pinned():
    catalogs = load_city_catalogs()
    assert {
        catalog.catalog_id: (catalog.catalog_version, len(catalog.entries)) for catalog in catalogs
    } == EXPECTED_CATALOGS
    assert sum(count for _version, count in EXPECTED_CATALOGS.values()) == 133


def test_every_shipped_entry_carries_a_licence():
    files = sorted(CATALOG_DIRECTORY.glob("*.json"))
    assert [path.name for path in files] == sorted(
        f"{catalog_id}.v{version}.json"
        for catalog_id, (version, _count) in EXPECTED_CATALOGS.items()
    )
    entries = 0
    for path in files:
        for entry in json.loads(path.read_text(encoding="utf-8"))["entries"]:
            entries += 1
            licence = entry.get("licence")
            assert isinstance(licence, dict), f"{path.name} {entry.get('key')} has no licence"
            assert licence["verdict"] in LICENCE_VERDICTS
            assert (ROOT / licence["content_source"]).is_file(), licence["content_source"]
            if licence["origin"] == "original":
                assert licence["spdx"] == "Apache-2.0"
                assert (ROOT / licence["licence_source"]).is_file()
            else:
                assert licence["licence_source"] != "LICENSE"
                assert licence["content_source"].startswith("assets/catalogs/sources/")
    assert entries == sum(count for _version, count in EXPECTED_CATALOGS.values())
    for catalog in load_city_catalogs():
        for entry in catalog.entries:
            assert entry.licence.verdict in LICENCE_VERDICTS


def test_every_file_version_matches_its_name():
    for path in sorted(CATALOG_DIRECTORY.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert path.name == f"{document['catalog_id']}.v{document['catalog_version']}.json"
        assert document["schema_version"] == 1


def test_a_file_whose_contents_disagree_with_its_name_is_refused(tmp_path):
    version = _version("typology")
    path = _write(tmp_path, "typology", [], catalog_version=version + 1)
    with pytest.raises(CatalogError):
        load_catalog(path, _schema("typology"))
    renamed = tmp_path / f"typology.v{version + 1}.json"
    _write(tmp_path, "typology", []).rename(renamed)
    with pytest.raises(CatalogError):
        load_catalog(renamed, _schema("typology"))
    other = _write(tmp_path, "band", [], catalog_id="typology")
    with pytest.raises(CatalogError):
        load_catalog(other, _schema("band"))
    load_catalog(_write(tmp_path, "typology", []), _schema("typology"))


def test_the_package_document_names_every_catalog_file_with_its_entry_count():
    text = DOCUMENT.read_text(encoding="utf-8")
    for catalog_id, (version, count) in EXPECTED_CATALOGS.items():
        assert f"| `{catalog_id}.v{version}.json` | {count} |" in text, catalog_id


def test_a_directory_with_a_stray_a_stale_or_a_missing_file_is_refused(tmp_path):
    shutil.copytree(CATALOG_DIRECTORY, tmp_path / "catalogs")
    directory = tmp_path / "catalogs"
    load_city_catalogs(directory)
    _write(directory, "lamp-post", [], version=1)
    with pytest.raises(CatalogError):
        load_city_catalogs(directory)
    (directory / "lamp-post.v1.json").unlink()
    _write(directory, "typology", [], version=1)
    with pytest.raises(CatalogError):
        load_city_catalogs(directory)
    (directory / "typology.v1.json").unlink()
    load_city_catalogs(directory)
    (directory / f"typology.v{_version('typology')}.json").unlink()
    with pytest.raises(CatalogError):
        load_city_catalogs(directory)


# ---------------------------------------------------------------------------------------------
# The digest

_DIGEST = r"""
import sys
import exulanica.grammar
from exulanica.grammar.catalogs import catalog_digest
from exulanica.grammar.grammars.city.catalogs import load_city_catalogs

print(exulanica.grammar.__file__)
print(catalog_digest(load_city_catalogs()))
"""


def _digest_in_a_new_process(hash_seed: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", _DIGEST],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    module_path, digest = result.stdout.split()
    assert Path(module_path).resolve().is_relative_to(ROOT), module_path
    return digest


def test_the_catalog_digest_is_stable_across_two_processes():
    first = _digest_in_a_new_process("7")
    second = _digest_in_a_new_process("2718281828")
    assert first == second
    assert first == catalog_digest(load_city_catalogs())


def test_the_catalog_digest_moves_when_an_entry_does(tmp_path):
    shutil.copytree(CATALOG_DIRECTORY, tmp_path / "catalogs")
    directory = tmp_path / "catalogs"
    before = catalog_digest(load_city_catalogs(directory))
    band = json.loads((directory / "band.v1.json").read_text(encoding="utf-8"))
    band["entries"][0]["top_maximum_mm"] += 1
    (directory / "band.v1.json").write_text(json.dumps(band), encoding="utf-8")
    after = catalog_digest(load_city_catalogs(directory))
    assert before != after


def test_the_catalog_digest_does_not_depend_on_the_order_catalogs_are_passed_in():
    catalogs = load_city_catalogs()
    assert catalog_digest(catalogs) == catalog_digest(tuple(reversed(catalogs)))


# ---------------------------------------------------------------------------------------------
# References


def test_an_unresolvable_texture_set_reference_raises(tmp_path):
    path = _write(tmp_path, "material", [_MATERIAL_ENTRY])
    with pytest.raises(UnresolvedReferenceError):
        load_catalog(path, _schema("material"))
    with pytest.raises(UnresolvedReferenceError):
        load_catalog(
            path,
            _schema(
                "material",
                texture_sets={"another-set": TextureSet("another-set", 1, "a" * 64, "opaque")},
            ),
        )


def test_a_resolvable_texture_set_reference_loads(tmp_path):
    path = _write(tmp_path, "material", [_MATERIAL_ENTRY])
    schema = _schema("material", texture_sets=_TEST_SETS)
    [entry] = load_catalog(path, schema).entries
    assert dict(entry.values)["texture_set_id"] == "test-texture-set"


@pytest.mark.parametrize("texture_set_id", ["", " test-texture-set", None, 7])
def test_a_missing_or_malformed_texture_set_reference_is_a_schema_error(tmp_path, texture_set_id):
    entry = {**_MATERIAL_ENTRY, "texture_set_id": texture_set_id}
    path = _write(tmp_path, "material", [entry])
    with pytest.raises(CatalogError):
        load_catalog(path, _schema("material", texture_sets=_TEST_SETS))


def test_a_material_entry_with_no_texture_set_field_is_refused(tmp_path):
    entry = {key: value for key, value in _MATERIAL_ENTRY.items() if key != "texture_set_id"}
    path = _write(tmp_path, "material", [entry])
    with pytest.raises(CatalogError):
        load_catalog(path, _schema("material", texture_sets=_TEST_SETS))


# ---------------------------------------------------------------------------------------------
# Which classes a surface role admits


def _dressed(surfaces: list[str], material_class: str) -> tuple[dict, Mapping[str, TextureSet]]:
    """A material entry dressing ``surfaces`` with a set of ``material_class``."""
    entry = {**_MATERIAL_ENTRY, "surfaces": surfaces}
    sets = {"test-texture-set": TextureSet("test-texture-set", 1, "a" * 64, material_class)}
    return entry, MappingProxyType(sets)


def test_every_surface_role_says_which_classes_it_admits():
    """ROLE_CLASSES is keyed, not defaulted, so a role added to the vocabulary must be taught here.

    Without this the table would be silent about a new role until somebody happened to write a
    record that dressed it, which is the failure the table exists to prevent, one level up.
    """
    assert tuple(ROLE_CLASSES) == SURFACE_ROLES


@pytest.mark.parametrize(
    ("surfaces", "material_class"),
    [
        (["wall"], "opaque"),
        (["glazing"], "glazing"),
        (["canopy"], "cutout"),
        (["marking"], "decal"),
        # A crossing is a surface with paint over it, so it admits both, and both are in use.
        (["crossing"], "opaque"),
        (["crossing", "marking"], "decal"),
    ],
)
def test_a_surface_admits_a_set_of_a_class_it_names(tmp_path, surfaces, material_class):
    entry, sets = _dressed(surfaces, material_class)
    path = _write(tmp_path, "material", [entry])
    [loaded] = load_catalog(path, _schema("material", texture_sets=sets)).entries
    assert list(dict(loaded.values)["surfaces"]) == surfaces


@pytest.mark.parametrize(
    ("surfaces", "material_class", "message"),
    [
        # The two this table exists for: paint drawn opaque is a solid rectangle across the road,
        # and a canopy drawn opaque is a leaf-patterned slab instead of leaves with gaps.
        (["marking"], "opaque", "marking admits decal"),
        (["canopy"], "opaque", "canopy admits cutout"),
        (["glazing"], "opaque", "glazing admits glazing"),
        (["wall"], "decal", "wall admits opaque"),
        (["wall"], "glazing", "wall admits opaque"),
        # One surface of several is enough to refuse the record.
        (["crossing", "marking"], "opaque", "marking admits decal"),
    ],
)
def test_a_surface_refuses_a_set_of_a_class_it_does_not_name(
    tmp_path, surfaces, material_class, message
):
    entry, sets = _dressed(surfaces, material_class)
    path = _write(tmp_path, "material", [entry])
    with pytest.raises(CatalogError, match=message):
        load_catalog(path, _schema("material", texture_sets=sets))


def test_a_role_the_table_does_not_name_is_refused_rather_than_assumed_opaque(
    monkeypatch, tmp_path
):
    """The load-bearing half: an untaught role blocks the records that dress it.

    A table that defaulted to opaque would accept this silently, and a role that wanted cutout or
    decal would be drawn solid with nobody told. The message names the role and says what to do.
    """
    entry, sets = _dressed(["wall"], "opaque")
    untaught = {role: classes for role, classes in ROLE_CLASSES.items() if role != "wall"}
    monkeypatch.setattr(city_catalogs, "ROLE_CLASSES", untaught)
    path = _write(tmp_path, "material", [entry])
    with pytest.raises(CatalogError, match="wall admits no material class yet"):
        load_catalog(path, _schema("material", texture_sets=sets))


# ---------------------------------------------------------------------------------------------
# Strictness


_TYPOLOGY_ENTRY = _shipped_entry("typology", key="test_typology", label="Test typology")


@pytest.mark.parametrize(
    "entry",
    [
        {**_TYPOLOGY_ENTRY, "colour": "red"},
        {**_TYPOLOGY_ENTRY, "licence": {**_ORIGINAL, "note": "extra"}},
        {key: value for key, value in _TYPOLOGY_ENTRY.items() if key != "label"},
        {key: value for key, value in _TYPOLOGY_ENTRY.items() if key != "licence"},
        {**_TYPOLOGY_ENTRY, "key": "Test"},
        {**_TYPOLOGY_ENTRY, "label": ""},
        {**_TYPOLOGY_ENTRY, "licence": {**_ORIGINAL, "verdict": "USE-ONLY"}},
        {**_TYPOLOGY_ENTRY, "licence": {**_ORIGINAL, "verdict": "UNVERIFIED"}},
        {**_TYPOLOGY_ENTRY, "licence": {**_ORIGINAL, "spdx": "CC-BY-4.0"}},
        {**_TYPOLOGY_ENTRY, "licence": {**_ORIGINAL, "spdx": "Apache 2"}},
        {**_TYPOLOGY_ENTRY, "licence": {**_ORIGINAL, "origin": "derived"}},
        {**_TYPOLOGY_ENTRY, "licence": {**_ORIGINAL, "origin": "found"}},
        {**_TYPOLOGY_ENTRY, "licence": {**_ORIGINAL, "content_source": ""}},
        {**_TYPOLOGY_ENTRY, "licence": "Apache-2.0"},
        ["test_typology"],
    ],
)
def test_an_entry_outside_its_schema_is_rejected_not_ignored(tmp_path, entry):
    path = _write(tmp_path, "typology", [entry])
    with pytest.raises(CatalogError):
        load_catalog(path, _schema("typology"))


def test_a_well_formed_entry_is_accepted_including_a_derived_one(tmp_path):
    derived = {
        **_TYPOLOGY_ENTRY,
        "key": "test_derived",
        "licence": {
            "spdx": "CC0-1.0",
            "verdict": "SHIP",
            "origin": "derived",
            "licence_source": "https://example.invalid/licence",
            "content_source": "https://example.invalid/source",
        },
    }
    path = _write(tmp_path, "typology", [_TYPOLOGY_ENTRY, derived])
    catalog = load_catalog(path, _schema("typology"))
    assert catalog.keys() == ("test_typology", "test_derived")


def test_a_repeated_entry_key_is_rejected(tmp_path):
    path = _write(tmp_path, "typology", [_TYPOLOGY_ENTRY, _TYPOLOGY_ENTRY])
    with pytest.raises(CatalogError):
        load_catalog(path, _schema("typology"))


_ENVELOPE = '"schema_version": 1, "catalog_id": "typology", "catalog_version": 2'
#: No entries, and the statement the loader requires of a catalog that has none, so that each
#: refusal below is refused for its own reason rather than for the missing statement.
_EMPTY = '"entries": [], "empty_reason": "A fixture with no entries, written by a test."'


def test_the_envelope_the_refusals_below_start_from_loads(tmp_path):
    path = tmp_path / "typology.v2.json"
    path.write_text("{" + _ENVELOPE + ", " + _EMPTY + "}", encoding="utf-8")
    assert load_catalog(path, _schema("typology")).entries == ()


@pytest.mark.parametrize(
    "text",
    [
        "{" + _ENVELOPE + ", " + _EMPTY + ', "comment": "x"}',
        "{" + _ENVELOPE + "}",
        '{"schema_version": 2, "catalog_id": "typology", "catalog_version": 2, ' + _EMPTY + "}",
        "{" + _ENVELOPE + ', "catalog_id": "typology", ' + _EMPTY + "}",
        '{"schema_version": 1.0, "catalog_id": "typology", "catalog_version": 2, ' + _EMPTY + "}",
        "{" + _ENVELOPE + ', "entries": NaN}',
        '{"schema_version": true, "catalog_id": "typology", "catalog_version": 2, ' + _EMPTY + "}",
        '{"schema_version": 1, "catalog_id": "typology", "catalog_version": true, ' + _EMPTY + "}",
        "{" + _ENVELOPE + ', "entries": {}}',
        "[]",
        "not json",
    ],
)
def test_an_envelope_outside_its_schema_is_rejected(tmp_path, text):
    assert _version("typology") == 2
    path = tmp_path / "typology.v2.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(path, _schema("typology"))


def test_a_float_anywhere_in_a_catalog_is_rejected_at_parse_time(tmp_path):
    band = json.loads((CATALOG_DIRECTORY / "band.v1.json").read_text(encoding="utf-8"))
    band["entries"][0]["top_minimum_mm"] = 4000.5
    path = tmp_path / "band.v1.json"
    path.write_text(json.dumps(band), encoding="utf-8")
    with pytest.raises(CatalogError, match="non-integer"):
        load_catalog(path, _schema("band"))


def test_a_band_whose_bounds_are_inverted_is_rejected(tmp_path):
    band = json.loads((CATALOG_DIRECTORY / "band.v1.json").read_text(encoding="utf-8"))
    band["entries"][0]["top_minimum_mm"] = 6001
    path = tmp_path / "band.v1.json"
    path.write_text(json.dumps(band), encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(path, _schema("band"))


def test_a_schema_cannot_redeclare_key_or_licence():
    with pytest.raises(CatalogError):
        CatalogSchema("typology", 1, (("licence", text_field),))


# ---------------------------------------------------------------------------------------------
# The texture manifest, and the pins a resolved reference carries into the digest


def _manifest_entry(set_id: str, content: str = "a" * 64, version: int = 1) -> dict:
    return {
        "set_id": set_id,
        "version": version,
        "content_sha256": content,
        "byte_size": 1024,
        "resolution": {"width": 16, "height": 16},
        "channels": [texture_map.as_channel() for texture_map in CONTAINER_LAYOUT],
        "extent_mm": {"u": 2000, "v": 2000},
        "licence_id": "CC0-1.0",
        "licence_sha256": "b" * 64,
    }


def _manifest_bytes(document: object) -> bytes:
    """The manifest's canonical form, so a refusal below is for its own reason and not the form.

    Sorted keys, no spaces, ASCII: what canonical JSON is for these documents, written with the
    standard library so a document holding a float can still be written and refused on reading.
    """
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")


def _manifest(tmp_path: Path, sets: list, **override: object) -> Path:
    path = tmp_path / "manifest.json"
    document = {"profile": MANIFEST_PROFILE, "sets": sets, **override}
    path.write_bytes(_manifest_bytes(document))
    return path


def test_a_well_formed_manifest_is_read_by_id(tmp_path):
    path = _manifest(
        tmp_path, [_manifest_entry("cc0.test-one"), _manifest_entry("cc0.test-two", "c" * 64, 3)]
    )
    sets = read_texture_manifest(path)
    assert list(sets) == ["cc0.test-one", "cc0.test-two"]
    assert sets["cc0.test-two"] == TextureSet("cc0.test-two", 3, "c" * 64, "opaque")


@pytest.mark.parametrize(
    "document",
    [
        [_manifest_entry("cc0.test-one")],
        {"sets": [_manifest_entry("cc0.test-one")]},
        {"profile": "exulanica.texture-manifest/v2", "sets": []},
        {"profile": MANIFEST_PROFILE, "sets": [], "schema_version": 1},
        {"profile": MANIFEST_PROFILE, "sets": {}},
        {
            "profile": MANIFEST_PROFILE,
            "sets": [_manifest_entry("cc0.test-two"), _manifest_entry("cc0.test-one")],
        },
        {
            "profile": MANIFEST_PROFILE,
            "sets": [_manifest_entry("cc0.test-one"), _manifest_entry("cc0.test-one")],
        },
        {"profile": MANIFEST_PROFILE, "sets": [{**_manifest_entry("cc0.test-one"), "note": 1}]},
        {"profile": MANIFEST_PROFILE, "sets": [_manifest_entry("Cc0.Test")]},
        {"profile": MANIFEST_PROFILE, "sets": [_manifest_entry("cc0.test", "A" * 64)]},
        {"profile": MANIFEST_PROFILE, "sets": [_manifest_entry("cc0.test", version=0)]},
        {"profile": MANIFEST_PROFILE, "sets": [{**_manifest_entry("cc0.test"), "byte_size": 0}]},
        {
            "profile": MANIFEST_PROFILE,
            "sets": [{**_manifest_entry("cc0.test"), "licence_sha256": "short"}],
        },
        {"profile": MANIFEST_PROFILE, "sets": [{**_manifest_entry("cc0.test"), "resolution": 0.5}]},
    ],
)
def test_a_manifest_outside_its_shape_is_refused(tmp_path, document):
    path = tmp_path / "manifest.json"
    path.write_bytes(_manifest_bytes(document))
    with pytest.raises(CatalogError):
        read_texture_manifest(path)


def test_a_missing_manifest_is_refused_rather_than_read_as_empty(tmp_path):
    with pytest.raises(CatalogError):
        read_texture_manifest(tmp_path / "manifest.json")


@pytest.mark.parametrize("set_id", ["Test-texture-set", "1set", "test_set", "test set", "", "-x"])
def test_a_texture_set_id_outside_the_contract_is_refused(tmp_path, set_id):
    """Refused as malformed, not merely as unpublished, even when the malformed name resolves."""
    entry = {**_MATERIAL_ENTRY, "texture_set_id": set_id}
    path = _write(tmp_path, "material", [entry])
    with pytest.raises(CatalogError) as refused:
        load_catalog(path, _schema("material", texture_sets=_TEST_SETS))
    assert not isinstance(refused.value, UnresolvedReferenceError), refused.value
    field = ReferenceField("a texture set", TEXTURE_SET_ID, {set_id: {"set_id": set_id}})
    with pytest.raises(CatalogError) as malformed:
        field("texture_set_id", set_id)
    assert not isinstance(malformed.value, UnresolvedReferenceError), malformed.value


def test_a_rebaked_texture_set_moves_the_catalog_digest_with_the_file_unchanged(tmp_path):
    path = _write(tmp_path, "material", [_MATERIAL_ENTRY])
    before_bytes = path.read_bytes()
    first = read_texture_manifest(
        _manifest(tmp_path, [_manifest_entry("test-texture-set", "a" * 64, 1)])
    )
    rebaked = read_texture_manifest(
        _manifest(tmp_path, [_manifest_entry("test-texture-set", "d" * 64, 2)])
    )
    before = catalog_digest([load_catalog(path, _schema("material", texture_sets=first))])
    after = catalog_digest([load_catalog(path, _schema("material", texture_sets=rebaked))])
    assert path.read_bytes() == before_bytes
    assert before != after
    [entry] = load_catalog(path, _schema("material", texture_sets=rebaked)).entries
    assert dict(entry.values)["texture_set_id"] == "test-texture-set"
    assert dict(entry.values)["label"] == "Test material"


def test_a_set_no_entry_uses_does_not_move_the_catalog_digest(tmp_path):
    path = _write(tmp_path, "material", [_MATERIAL_ENTRY])
    used = _manifest_entry("test-texture-set")
    alone = read_texture_manifest(_manifest(tmp_path, [used]))
    with_unused = read_texture_manifest(
        _manifest(tmp_path, [_manifest_entry("cc0.unused-set", "e" * 64), used])
    )
    rebaked_unused = read_texture_manifest(
        _manifest(tmp_path, [_manifest_entry("cc0.unused-set", "f" * 64, 9), used])
    )
    digests = {
        catalog_digest([load_catalog(path, _schema("material", texture_sets=sets))])
        for sets in (alone, with_unused, rebaked_unused, dict(reversed(with_unused.items())))
    }
    assert len(digests) == 1
