"""The domain-rows acceptance driver in ``scripts/acceptance/domain_rows.py``, without a server.

These hold what the driver builds and derives by itself, since it imports nothing from the
product: the containers it admits are the ones the product's own inspector admits or refuses by
the code each row expects, and the reading line it derives from V7's record gives the record's own
figures. Running it against a stack is the acceptance run itself.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path
from types import ModuleType

import pytest
from exulanica.world.static_glb import StaticGlbRefused, inspect_static_glb

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "acceptance" / "domain_rows.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exulanica_acceptance_domain_rows", DRIVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DRIVE = _load()


def test_the_driver_imports_nothing_from_the_product():
    tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "exulanica" not in imported


def test_the_cube_it_admits_is_a_container_the_product_admits():
    payload = DRIVE.cube(1.0)
    magic, version, length = struct.unpack_from("<III", payload)

    assert (magic, version, length) == (0x46546C67, 2, len(payload))
    inspect_static_glb(payload)
    assert DRIVE.cube(1.0) == payload, "the same cube is the same bytes"
    assert DRIVE.cube(0.8) != payload


def test_each_hostile_fixture_is_refused_by_the_product_with_the_code_its_row_expects():
    ceiling = 1024
    by_content = {
        name: detail
        for name, _, _, _, code, detail in DRIVE.hostile_fixtures(ceiling)
        if code == "asset_content_refused"
    }
    assert set(by_content.values()) == {
        "malformed_container",
        "compressed_content",
        "required_extension",
        "external_reference",
        "unsupported_feature",
    }
    for name, payload, _, _, code, detail in DRIVE.hostile_fixtures(ceiling):
        if code != "asset_content_refused":
            continue
        with pytest.raises(StaticGlbRefused) as refused:
            inspect_static_glb(payload)
        assert refused.value.reason == detail, name


def test_the_cases_refused_before_the_content_is_read_carry_what_their_code_names():
    cases = {case[0]: case for case in DRIVE.hostile_fixtures(1024)}

    assert len(cases["oversized"][1]) > 1024
    assert cases["oversized"][3:5] == (413, "asset_too_large")
    for name, code in (
        ("licence", "licence_not_admitted"),
        ("attribution", "attribution_required"),
    ):
        _, payload, changes, status, wanted, _ = cases[name]
        inspect_static_glb(payload)
        assert (status, wanted) == (422, code)
        assert DRIVE.declaration(payload, **changes)["rights"]["basis"] == "licensed"


def test_a_declaration_names_its_bytes_by_digest_and_size():
    payload = DRIVE.cube(0.5)
    document = DRIVE.declaration(payload)

    assert document["content_sha256"] == hashlib.sha256(payload).hexdigest()
    assert document["byte_size"] == len(payload)
    assert document["rights"]["statement"] == DRIVE.RIGHTS_STATEMENT


def test_the_line_it_derives_gives_the_records_own_populations():
    from exulanica.world.society_comparison_reading import READING_CATALOG

    catalog = json.loads(Path(READING_CATALOG).read_text())
    living = DRIVE.hour_entry(catalog, "living")
    record = json.loads((ROOT / living["source"]).read_text())["record"]
    population_most, decided_most = DRIVE.line_bound(
        record["line"], record["derived"]["run_budget_us"]
    )

    assert population_most == record["derived"]["population_most"]
    for derived in record["derived"]["decided_most"]:
        assert decided_most(derived["population"]) == derived["decided_most"]


def test_the_comparisons_plan_answers_both_roles_of_both_models():
    plan = json.loads(DRIVE.COMPARISONS_PLAN.read_text())
    answered = {
        (rule["match"].get("model"), rule["match"].get("contains")) for rule in plan["rules"]
    }

    for model in (DRIVE.GOING_MODEL, DRIVE.WAITING_MODEL):
        assert (model["model_id"], None) in answered
        assert (model["model_id"], "Green elapsed:") in answered


def test_the_e4_revision_is_one_the_product_publishes_with_its_new_colour_served(tmp_path):
    from exulanica.world.character_catalog_publication import catalog_documents
    from exulanica.world.character_catalogs import publication_families, read_publication_document

    class Stack:
        worktree = ROOT
        run_dir = tmp_path

    directory = DRIVE.catalog_c(Stack(), 9)
    (layered,) = catalog_documents(directory)
    publication = read_publication_document(layered)
    first = layered["catalog"]["families"][0]

    assert publication.revision == 9
    assert DRIVE.NEW_COLOUR in first["colours"][DRIVE.NEW_COLOUR_SLOT]
    keys = [colour["key"] for colour in first["colours"][DRIVE.NEW_COLOUR_SLOT]]
    assert len(keys) == len(set(keys))
    assert publication_families(layered)
    repository = json.loads((ROOT / "assets" / "characters" / "catalog.json").read_text())
    assert DRIVE.NEW_COLOUR not in repository["families"][0]["colours"][DRIVE.NEW_COLOUR_SLOT]


def test_h3_reads_the_hour_line_whatever_other_windows_the_catalog_states():
    hour = {"key": "living", "state_family": "living", "source": "hour.json"}
    day = {
        "key": "living-1440",
        "state_family": "living",
        "window_ticks": 1440,
        "source": "day.json",
    }
    other = {"key": "quiet", "state_family": "quiet", "source": "quiet.json"}

    for entries in ([hour, day, other], [day, hour], [other, day, hour]):
        assert DRIVE.hour_entry({"entries": entries}, "living") == hour
    assert DRIVE.hour_entry({"entries": [day, other]}, "living") == {}


def test_the_day_line_it_derives_gives_the_day_records_own_populations():
    from exulanica.world.society_comparison_reading import READING_CATALOG, measured_line

    catalog = json.loads(Path(READING_CATALOG).read_text())
    day = DRIVE.window_entry(catalog, "living", DRIVE.DAY_TICKS)
    # The product's own reader names the same record for a living town's day.
    assert day["source"] == measured_line("living", DRIVE.DAY_TICKS)["source"]
    record = json.loads((ROOT / day["source"]).read_text())["record"]
    assert record["window_ticks"] == DRIVE.DAY_TICKS
    population_most, decided_most = DRIVE.line_bound(
        record["line"], record["derived"]["run_budget_us"]
    )

    assert population_most == record["derived"]["population_most"]
    for derived in record["derived"]["decided_most"]:
        assert decided_most(derived["population"]) == derived["decided_most"]


def test_h4_reads_the_day_line_and_never_the_hours():
    hour = {"key": "living", "state_family": "living", "source": "hour.json"}
    day = {
        "key": "living-1440",
        "state_family": "living",
        "window_ticks": 1440,
        "source": "day.json",
    }
    mislabelled = dict(day, key="living-720")

    for entries in ([hour, day], [day, hour]):
        assert DRIVE.window_entry({"entries": entries}, "living", 1440) == day
    assert DRIVE.window_entry({"entries": [hour]}, "living", 1440) == {}
    assert DRIVE.window_entry({"entries": [hour, mislabelled]}, "living", 1440) == {}


def test_a56_lets_only_the_seeds_versions_of_the_catalogs_module_change():
    source = (ROOT / "exulanica" / "world" / "society_catalogs.py").read_text()
    table = "    COMPARISON_SEEDS_CATALOG: 6,\n}"
    schemas = "for version in (3, 4, 5, 6)"
    assert table in source and schemas in source

    seeds_moved = source.replace(table, "    COMPARISON_SEEDS_CATALOG: 7,\n}").replace(
        schemas, "for version in (3, 4, 5, 6, 7)"
    )
    assert DRIVE.seeds_versions_only(source, seeds_moved)
    assert DRIVE.seeds_versions_only(source, source.replace("#: ", "#: Seen: ", 1))
    # Another catalog's version in the same table, or any other value, is not the seeds'.
    score = "    PERSON_SCORE_CATALOG: 5,\n    COMPARISON_PROTOCOL_CATALOG: 4,"
    assert score in source
    assert not DRIVE.seeds_versions_only(
        source, source.replace(score, score.replace("SCORE_CATALOG: 5", "SCORE_CATALOG: 6"))
    )
    assert not DRIVE.seeds_versions_only(source, source.replace('"hour", "day"', '"hour"', 1))


def test_a56_lets_a_seeds_file_be_added_or_extended_but_never_rewritten():
    old = {
        "schema_version": 1,
        "catalog_id": "society-comparison-seeds",
        "catalog_version": 5,
        "entries": [{"phase": "held_out", "seed": "1"}],
    }
    extended = dict(
        old, catalog_version=6, entries=[*old["entries"], {"phase": "held_out", "seed": "2"}]
    )
    rewritten = dict(old, entries=[{"phase": "held_out", "seed": "9"}])

    assert DRIVE.seeds_entries_kept(None, json.dumps(old))
    assert DRIVE.seeds_entries_kept(json.dumps(old), json.dumps(extended))
    assert not DRIVE.seeds_entries_kept(json.dumps(old), json.dumps(rewritten))
    assert not DRIVE.seeds_entries_kept(json.dumps(old), None)
    assert not DRIVE.seeds_entries_kept(json.dumps(old), json.dumps(dict(old, catalog_id="other")))
    assert DRIVE.SEEDS_FILE.fullmatch("society-comparison-seeds.v6.json")
    assert not DRIVE.SEEDS_FILE.fullmatch("society-comparison-protocol.v4.json")


def test_a56_globs_only_a_directory_the_digest_reads_whole(tmp_path):
    whole, mixed = tmp_path / "routines", tmp_path / "world"
    whole.mkdir()
    mixed.mkdir()
    for name in ("a.v1.json", "b.v1.json"):
        (whole / name).write_text("{}")
    (mixed / "engines.v2.json").write_text("{}")
    (mixed / "arrival.v1.json").write_text("{}")
    data = {whole / "a.v1.json", whole / "b.v1.json", mixed / "engines.v2.json"}

    assert DRIVE.globbed_directories(data) == [whole]
    # A JSON file there that the digest does not read means the digest does not read it whole.
    (whole / "c.v1.json").write_text("{}")
    assert DRIVE.globbed_directories(data) == []


def test_a5_reads_the_newest_recipe_catalog_by_its_version_number(tmp_path):
    folder = tmp_path / DRIVE.RECIPE_CATALOGS
    folder.mkdir(parents=True)
    for version in (2, 10, 9):
        entries = [{"key": "small_town", "specification": f"s{version}", "values": {}}]
        (folder / f"world-recipe.v{version}.json").write_text(json.dumps({"entries": entries}))
    name, entry = DRIVE.newest_recipe(tmp_path, "small_town")
    assert (name, entry["specification"]) == ("world-recipe.v10.json", "s10")


def test_a5_asks_two_served_permille_values_each_unlike_the_preset():
    specification = {
        "values": [
            {"key": "storey_band_low", "minimum": 1, "maximum": 6},
            {"key": "cross_street_hierarchy", "choices": ["local_street"]},
            {"key": "a_permille", "minimum": 0, "maximum": 1000},
            {"key": "b_permille", "minimum": 0, "maximum": 1000},
            {"key": "c_permille", "minimum": 0, "maximum": 1000},
        ]
    }
    preset = {"storey_band_low": 2, "a_permille": 500, "b_permille": 0, "c_permille": 7}
    assert DRIVE.asked_values(specification, preset) == {"a_permille": 0, "b_permille": 1000}


def test_s1_reads_each_committed_pack_and_every_file_it_lists(tmp_path):
    """A-64: S1's expectations come from the committed files, read here as the row reads them."""
    folder = tmp_path / DRIVE.STYLE_PACKS / "a.pack"
    (folder / "pieces").mkdir(parents=True)
    piece = b"glTF piece bytes"
    (folder / "pieces" / "door.glb").write_bytes(piece)
    manifest = {
        "pack_id": "a.pack",
        "version": 2,
        "licence": {"id": "CC0-1.0", "attribution": None},
        "files": [{"path": "pieces/door.glb", "media_type": "model/gltf-binary"}],
    }
    raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    (folder / "manifest.json").write_bytes(raw)
    (read,) = DRIVE.committed_packs(tmp_path)
    assert read["raw"] == raw and read["document"]["pack_id"] == "a.pack"
    assert [(f["path"], f["data"]) for f in read["files"]] == [("pieces/door.glb", piece)]


def test_s1_identifies_a_manifest_by_its_canonical_bytes_without_the_final_newline():
    """A-67: a committed manifest is its canonical JSON and one newline; the host names and serves
    it without that newline, and a file not ending in exactly one is refused by the row."""
    assert DRIVE.canonical_manifest(b'{"a":1}\n') == b'{"a":1}'
    assert DRIVE.canonical_manifest(b'{"a":1}') is None
    assert DRIVE.canonical_manifest(b'{"a":1}\n\n') is None
