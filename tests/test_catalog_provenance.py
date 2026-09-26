"""Every catalog in the repository says where its content came from, and none is skipped.

This gate DISCOVERS catalogs. It asks the tree what is there and the code what it requires, and it
holds no list of catalog ids, because a gate that enumerates is silent about the class nobody
thought to add. That is not hypothetical here: the rule that authored vocabulary must say why it is
authored ran over fourteen ids while eighteen city catalogs shipped, and band.v1.json stated a
ground band on every frontage in the world with no reason at all. Two of the eighteen SCHEMAS did
not declare the reason field either, so the loader never asked for one.

Five families ship, in three shapes, and this file makes a substantive claim about each file it
finds rather than a claim about which test covers it:

*   city, society and world object catalogs, ``entries`` and ``schema_version``: every entry
    carries a reason.
*   traffic catalogs, which add ``references``: every entry carries per-field ``sources``, each
    citing a listed reference or declaring a value; test_traffic_catalogs.py holds their content.
*   lettering catalogs, ``glyphs``: provenance is the pinned ``source`` of the font the glyphs were
    converted from; test_lettering_catalog.py holds the digests and the licence.

A new shape fails here. That is the point: it is cheaper to loosen this file deliberately than to
discover later that a family was never checked.

**Seen to refuse, 2026-09-18, six ways, each restored afterwards.** A check nobody has watched fail
is a claim about the tree sitting where nothing tests it:

1. A new catalog whose entry has no reason: four rules fire, the shape count, the reason rule, the
   register rule, and the digest test, because the loader refuses a file the schemas do not name.
2. The reason removed from band/ground: the reason rule.
3. action-vocabulary stops saying why it is empty: the empty rule, and the loader refuses it too.
4. A reason reading "Because it seemed like a sensible height for a shopfront": the register rule.
5. The band schema stops declaring the reason field: the schema rule, asked of the code.
6. A register added here that nothing in the tree uses: the register rule, from the other side.

Two errors in that record, both caught because a result looked like an answer. The first run used
``-x``, so it recorded which test failed FIRST rather than which rules fire; re-run without it,
case 1 fires four. And the first measurement of what the city fixture rebuild would change compared
the wrong committed file and produced 7,590 differences, which cannot be true of a catalog reason;
against the file the fixture test actually pins, exactly one leaf value of 5,985 moves, its catalog
digest.

A third error, found by the orchestrator rather than by me: all of that was first measured on a tree
thirty commits behind main, against a catalog set where ``material`` was still v3 with eleven
entries. The numbers were true of a tree nobody would merge. Re-derived after rebasing, the shape
held and every figure changed, and the entry count in this file was itself a restatement of what
test_grammar_catalogs.py already pins, so it is a floor now instead of a total.

The material test in test_grammar_city_catalogs.py had the same defect and is fixed in the same
commit: it pinned sixteen texture set names inline while the manifest held seventeen. It now asserts
that every material names a published set and states the partition, which published set no material
names, today exactly cc0.sign-panel because no surface role names a sign panel yet. Seen to refuse:
a material naming an unpublished set is caught by the loader before the test runs; a published set
that no material names fails the partition; two materials depicting one set fail the duplicate rule.
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
    # Counted from the tree, so adding a catalog to a family is visible here as a number: eighteen
    # city catalogs, seven society catalogs (the living society's five and the purposeful routine's
    # two versions), the words both the inspector and the Companion say of a simulated person, the
    # world object catalog's two versions and its arrangements.
    assert len(found[ENTRY_SHAPE]) == 29
    assert len(found[CITED_SHAPE]) == 5
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
