"""Every discovered catalog says where its content came from, and no unknown shape is skipped.

Discovery reads every JSON catalog under assets/catalogs instead of maintaining a list of ids.
Entry catalogs carry a reason for every entry or for an empty vocabulary. Traffic catalogs add
per-field sources citing a listed reference or declaring a value. Lettering catalogs carry the
pinned font source; their dedicated tests hold the digests and licence.

The checks bind city schema reason fields, accepted provenance registers and published texture
references to the same discovered content. A discovery floor guards against an empty or truncated
scan without repeating the number of versioned entry catalogs in a growing repository.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from exulanica.grammar.catalogs import CatalogError, catalog_digest, load_catalog
from exulanica.grammar.grammars.city.catalogs import (
    CATALOG_DIRECTORY,
    city_catalog_schemas,
    load_city_catalogs,
)
from exulanica.grammar.textures import read_texture_manifest

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = ROOT / "assets" / "catalogs"
#: Shapes this file knows how to judge, by the marker keys a file carries.
ENTRY_SHAPE = ("entries", "schema_version")
CITED_SHAPE = ("entries", "references", "schema_version")
GLYPH_SHAPE = ("glyphs",)
#: How a city reason states its origin. A register the tests do not know fails below.
REGISTERS = ("Authored", "Derived:", "The material the")
#: Substance, the same demand made of an entry reason and of an empty catalog's statement.
WORDS = 5


def discovered() -> dict[tuple[str, ...], list[Path]]:
    """Every file under assets/catalogs that calls itself a catalog, grouped by shape."""
    found: dict[tuple[str, ...], list[Path]] = {}
    for path in sorted(CATALOGS.rglob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or "catalog_id" not in document:
            continue
        shape = tuple(
            sorted(
                key
                for key in ("entries", "glyphs", "references", "schema_version")
                if key in document
            )
        )
        found.setdefault(shape, []).append(path)
    return found


def test_the_discovery_finds_every_family_and_no_unknown_shape():
    found = discovered()
    assert set(found) == {ENTRY_SHAPE, CITED_SHAPE, GLYPH_SHAPE}, sorted(found)
    # A discovery floor catches an empty or truncated scan. Every discovered catalog is
    # checked below, including new versions; an exact total would restate a growing inventory.
    assert len(found[ENTRY_SHAPE]) > 100
    # The traffic catalogs: vehicle classes, right-of-way policies, signal plans, the two access
    # mappings, the road derivation and the signal placement.
    assert len(found[CITED_SHAPE]) == 7
    assert len(found[GLYPH_SHAPE]) == 4
    # And the discovery is looking where the catalogs are: the city files are among what it found.
    assert CATALOGS / "band.v1.json" in found[ENTRY_SHAPE]
    assert CATALOGS / "traffic" / "signal-plan.v1.json" in found[CITED_SHAPE]


def test_every_entry_in_every_discovered_catalog_says_why_it_exists():
    checked = 0
    for path in discovered()[ENTRY_SHAPE]:
        document = json.loads(path.read_text(encoding="utf-8"))
        for entry in document["entries"]:
            checked += 1
            where = f"{path.name} {entry.get('key')}"
            reason = entry.get("reason")
            assert isinstance(reason, str) and reason.strip(), f"{where} has no reason"
            assert len(reason.split()) >= WORDS, f"{where} reason is not a sentence: {reason!r}"
    # A floor, not a total: what each catalog holds is pinned in test_grammar_catalogs.py for the
    # city and in test_society_living.py for society, and restating it here would be a second place
    # for the same number to drift. What this guards is a loop that checks nothing.
    assert checked > 100, checked


def test_a_catalog_with_no_entries_states_why_it_is_empty():
    """An empty vocabulary satisfies every rule about entries by having none."""
    empty = 0
    for path in discovered()[ENTRY_SHAPE]:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["entries"]:
            assert "empty_reason" not in document, path.name
            continue
        empty += 1
        stated = document.get("empty_reason")
        assert isinstance(stated, str) and len(stated.split()) >= WORDS, path.name
    assert empty == 1


def test_every_traffic_entry_names_a_source_for_every_number_it_states():
    for path in discovered()[CITED_SHAPE]:
        document = json.loads(path.read_text(encoding="utf-8"))
        references = set(document["references"])
        for entry in document["entries"]:
            sources = entry.get("sources")
            assert isinstance(sources, dict) and sources, f"{path.name} {entry['key']}"
            for field, text in sources.items():
                where = f"{path.name} {entry['key']}.{field}"
                if text.startswith("declared: "):
                    assert len(text.split()) >= WORDS, where
                    continue
                assert text.startswith("cited "), where
                named = text[len("cited ") :].split(":", 1)[0].split(" and ")
                assert set(named) <= references, where


def test_every_lettering_catalog_pins_the_font_its_glyphs_came_from():
    for path in discovered()[GLYPH_SHAPE]:
        document = json.loads(path.read_text(encoding="utf-8"))
        source = document.get("source")
        assert isinstance(source, dict), path.name
        assert (ROOT / source["file"]).is_file(), path.name
        assert len(source["sha256"]) == 64, path.name
        assert source["url"] and source["licence"]["file"], path.name
        assert (ROOT / source["licence"]["file"]).is_file(), path.name


def test_every_city_schema_requires_a_reason_of_its_entries():
    """Asked of the code, so a schema written without one fails here rather than shipping."""
    schemas = city_catalog_schemas(texture_sets=read_texture_manifest())
    assert len(schemas) == 18
    without = [
        schema.catalog_id
        for schema in schemas
        if "reason" not in {name for name, _check in schema.fields}
    ]
    assert without == []


def test_the_registers_a_reason_can_be_written_in_are_exactly_the_known_ones():
    """Both directions: an unknown register fails, and a register nobody uses any more fails too."""
    seen: dict[str, set[str]] = {register: set() for register in REGISTERS}
    for catalog in load_city_catalogs():
        for entry in catalog.entries:
            reason = dict(entry.values)["reason"]
            register = next((r for r in REGISTERS if str(reason).startswith(r)), None)
            assert register, (catalog.catalog_id, entry.key, str(reason)[:60])
            seen[register].add(catalog.catalog_id)
    assert all(catalogs for catalogs in seen.values()), {k: sorted(v) for k, v in seen.items()}
    # An authored reason is authored in this repository, so its licence says so.
    for catalog in load_city_catalogs():
        for entry in catalog.entries:
            if str(dict(entry.values)["reason"]).startswith("Authored"):
                assert entry.licence.origin == "original", (catalog.catalog_id, entry.key)


def test_the_loader_refuses_an_empty_catalog_that_says_nothing(tmp_path):
    directory = tmp_path / "catalogs"
    shutil.copytree(CATALOG_DIRECTORY, directory)
    path = directory / "action-vocabulary.v1.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    schema = next(
        s
        for s in city_catalog_schemas(texture_sets=read_texture_manifest())
        if s.catalog_id == "action-vocabulary"
    )
    del document["empty_reason"]
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CatalogError, match="empty_reason"):
        load_catalog(path, schema)
    document["empty_reason"] = ""
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CatalogError, match="empty_reason"):
        load_catalog(path, schema)


def test_the_loader_refuses_a_statement_of_emptiness_on_a_catalog_with_entries(tmp_path):
    directory = tmp_path / "catalogs"
    shutil.copytree(CATALOG_DIRECTORY, directory)
    path = directory / "band.v1.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["empty_reason"] = "This catalog has an entry, so this sentence is a contradiction."
    path.write_text(json.dumps(document), encoding="utf-8")
    schema = next(
        s
        for s in city_catalog_schemas(texture_sets=read_texture_manifest())
        if s.catalog_id == "band"
    )
    with pytest.raises(CatalogError, match="empty_reason"):
        load_catalog(path, schema)


def test_saying_why_a_catalog_is_empty_cannot_rebake_a_tile(tmp_path):
    """The statement is outside the digest on purpose: it travels into no tile key.

    The catalog digest goes into a tile record and from there into a baked tile key, so a sentence
    about an absence must not move it. An entry reason is different and does move it, because it is
    part of what the city can say.
    """
    directory = tmp_path / "catalogs"
    shutil.copytree(CATALOG_DIRECTORY, directory)
    path = directory / "action-vocabulary.v1.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    before = catalog_digest(load_city_catalogs(directory))
    document["empty_reason"] = "Reworded entirely, with the same meaning and a different sentence."
    path.write_text(json.dumps(document), encoding="utf-8")
    assert catalog_digest(load_city_catalogs(directory)) == before
