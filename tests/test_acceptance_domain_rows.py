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
from decimal import Decimal
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


#: The catalogs module's shape at the heads A-56 compares, where the module stated the seeds
#: catalog's versions itself (they now live in exulanica/world/society_comparison_seeds.py, which
#: the drawing digest does not cover): a table mapping each catalog to its version, the seeds
#: schemas built for a tuple of versions, and other values beside them.
A56_CATALOGS_SOURCE = """
#: The versions a comparison over a day is defined under.
DAY_COMPARISON_VERSIONS: Final = {
    PERSON_SCORE_CATALOG: 5,
    COMPARISON_PROTOCOL_CATALOG: 4,
    COMPARISON_SEEDS_CATALOG: 6,
}
COMPARISON_WINDOWS: Final = ("hour", "day")
SCHEMAS: Final = {
    **{
        (COMPARISON_SEEDS_CATALOG, version): CatalogSchema(COMPARISON_SEEDS_CATALOG, version)
        for version in (3, 4, 5, 6)
    },
}
"""


def test_a56_lets_only_the_seeds_versions_of_the_catalogs_module_change():
    source = A56_CATALOGS_SOURCE
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


def test_w1_writes_exactly_one_figure_of_the_farm_kind_as_a_float():
    """A-70: the refused upload differs from the farm kind in one figure only, now a float; the
    identity and version are left as they are."""
    document = json.loads((ROOT / DRIVE.FARM_KIND).read_text())
    floated, changed = DRIVE.float_figure(document)

    def figures(value):
        if isinstance(value, dict):
            return [x for v in value.values() for x in figures(v)]
        if isinstance(value, list):
            return [x for v in value for x in figures(v)]
        return [value] if isinstance(value, (int, float)) and not isinstance(value, bool) else []

    assert changed
    assert floated["kind"] == document["kind"] and floated["version"] == document["version"]
    assert sum(isinstance(f, float) for f in figures(floated)) == 1
    assert len(figures(floated)) == len(figures(document))


def test_w3_reads_a_plan_position_inside_a_site_by_its_drawings_frame():
    """A-73: a position is (east, south) in the region's frame and the drawing's site runs x east
    and y north from its south-west corner, so a person at (43.6 m, -54.75 m) stands inside a 96 m
    by 128 m site, and outside it once the site is shrunk to a tenth about its centre."""
    extent = {"widthMm": 96_000, "depthMm": 128_000}
    assert DRIVE.inside_site([43_600, -54_750], extent)
    assert not DRIVE.inside_site([43_600, 54_750], extent)
    assert not DRIVE.inside_site([43_600, -54_750], extent, 0.1)
    assert DRIVE.inside_site([48_000, -64_000], extent, 0.1)


def test_v1_replaces_a_csrf_token_at_any_depth_and_nothing_else():
    answer = {"csrf_token": "t", "role": "guest", "nested": [{"csrf_token": "u", "n": 1}]}
    assert DRIVE.redacted(answer) == {
        "csrf_token": "[redacted]",
        "role": "guest",
        "nested": [{"csrf_token": "[redacted]", "n": 1}],
    }
    assert answer["csrf_token"] == "t"


def test_v1_reads_an_allowance_as_numbers_by_provider():
    figures = DRIVE.allowance_figures(
        [
            {"provider": "p", "available_usd": "0.05000000", "available_calls": 200},
            {"provider": "q", "available_usd": None, "available_calls": None},
        ]
    )
    assert figures == {"p": (DRIVE.Decimal("0.05"), 200), "q": (None, None)}
    assert DRIVE.allowance_figures(None) == {}


class _Answer:
    status = 201

    def __init__(self, body: bytes, cookie: str) -> None:
        self.body, self.headers = body, {"Set-Cookie": cookie}

    def read(self) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def test_v1_keeps_a_session_as_a_browser_does_and_records_no_credential(tmp_path, monkeypatch):
    code, token, cookie = "the-run-code", "the-csrf-token", "__Host-session=secret-value"
    sent: list[object] = []

    def urlopen(request, timeout, context):
        sent.append(request)
        body = json.dumps({"csrf_token": token, "role": "guest"}).encode()
        return _Answer(body, f"{cookie}; Path=/; Secure; HttpOnly; SameSite=lax")

    monkeypatch.setattr(DRIVE.urllib.request, "urlopen", urlopen)
    guest = DRIVE.GuestClient.__new__(DRIVE.GuestClient)
    guest.origin, guest.context, guest.step = "https://localhost:4443", None, "start"
    guest.cookie = guest.csrf = guest.set_cookie = None
    guest.record = DRIVE.Transcripts(tmp_path).recorder("guest", lambda: guest.step)

    status, answer = guest.call(
        "enter",
        "POST",
        "/auth/guest",
        body={"code": code},
        recorded_body={"code": DRIVE.GUEST_CODE_PLACEHOLDER},
    )
    assert status == 201 and guest.keep_session(answer)
    assert guest.cookie == cookie and guest.csrf == token
    guest.call("write", "POST", "/worlds/generated", body={"recipe": "small_town"})
    guest.call("read", "GET", "/auth/session")

    first, write, read = sent
    assert json.loads(first.data) == {"code": code}
    assert write.get_header("Cookie") == cookie
    assert write.get_header("X-csrf-token") == token
    assert write.get_header("Origin") == "https://localhost:4443"
    # A read carries the session, never the token a write carries.
    assert read.get_header("Cookie") == cookie and read.get_header("X-csrf-token") is None
    recorded = (tmp_path / "guest.jsonl").read_text()
    for credential in (code, token, "secret-value"):
        assert credential not in recorded
    assert DRIVE.GUEST_CODE_PLACEHOLDER in recorded


def test_h1_takes_a_resent_start_whose_state_moved_on_and_nothing_else():
    def answer(state: str, comparison: str = "c1") -> dict:
        return {
            "comparisons": [{"comparison_id": comparison, "start": {"state": state, "seeds": 3}}]
        }

    assert DRIVE.same_start(answer("waiting"), answer("waiting"))
    assert DRIVE.same_start(answer("waiting"), answer("running"))
    assert DRIVE.same_start(answer("running"), answer("finished"))
    # A state never moves back, an unknown state is none, and another comparison is not this one.
    assert not DRIVE.same_start(answer("running"), answer("waiting"))
    assert not DRIVE.same_start(answer("waiting"), answer("lost"))
    assert not DRIVE.same_start(answer("waiting"), answer("waiting", "c2"))
    assert not DRIVE.same_start(answer("waiting"), {"comparisons": []})


def test_d1_reads_each_persons_newest_choice_and_the_routine_where_none_names_them():
    choices = [
        {"subject_id": "a", "choice_seq": 1, "decider": {"kind": "model"}},
        {"subject_id": "a", "choice_seq": 2, "decider": {"kind": "external"}},
        {"subject_id": "b", "choice_seq": 3, "decider": {"kind": "external"}},
        {"subject_id": "b", "choice_seq": 4, "decider": {"kind": "routine"}},
    ]

    class Client:
        def call(self, step, method, path, query=None):
            view = {"choices": choices}
            return 200, {"roles": [{"key": "society_decision", "view": view}]}

    entry = {"authored_version_id": "v", "world_id": "w"}
    assert DRIVE.deciders(Client(), "D1", entry, ["a", "b", "c"]) == {
        "a": "external",
        "b": "routine",
        "c": None,
    }


def test_df1_holds_only_when_every_definer_is_the_login_less_owners_and_public_runs_none():
    held = {
        "definers": 22,
        "owned_by_another": 0,
        "flags_all_false": True,
        "memberships": 0,
        "public_may_execute": 0,
    }
    assert DRIVE.definer_holds(held)
    for broken in (
        {"definers": 0},
        {"owned_by_another": 1},
        {"flags_all_false": False},
        {"memberships": 1},
        {"public_may_execute": 1},
    ):
        assert not DRIVE.definer_holds({**held, **broken}), broken


def test_v2_says_hello_as_the_gate_mod_does():
    sent = json.loads(DRIVE.luanti_hello(ROOT))
    adapter = json.loads((ROOT / DRIVE.LUANTI_MOD / "adapter.json").read_text())
    mapping = json.loads((ROOT / DRIVE.LUANTI_MAPPING).read_text())
    assert sent["adapter_version"] == adapter["adapter_version"]
    # The mapping travels as the file's own document, and the reads are the adapter's then every
    # mapped item's, as the mod sends them.
    assert sent["mapping"] == mapping
    assert sent["reads"] == [*adapter["reads"], *(item["game_item"] for item in mapping["items"])]
    assert DRIVE.CROSSING_ITEM in sent["reads"]


def test_lk1s_drafted_form_fills_every_value_the_served_specification_lets_a_draft_set():
    from exulanica.world.specification_source import served_document

    plan = json.loads(DRIVE.LOOK_OFFER_PLAN.read_text())
    form = json.loads(plan["rules"][-1]["content"])
    adjustable = {e["key"] for e in served_document()["values"] if e.get("adjustable") is True}
    assert set(form) == {"preset", "fit", "not_supported", *adjustable}
    assert form["preset"] in {p["key"] for p in served_document()["presets"]}


def test_pr1s_estimate_from_the_compute_catalog_gives_the_contracts_own_figures():
    # docs/generated-pieces-contract.md: "Four variants of one kind are USD 0.016 typically and USD
    # 0.06 at worst", and the first variant of each kind comes 8 seconds an item apart.
    expected = DRIVE.expected_estimate(DRIVE.piece_compute(ROOT), [4])
    contract = " ".join((ROOT / "docs" / "generated-pieces-contract.md").read_text().split())

    assert "Four variants of one kind are USD 0.016 typically and USD 0.06 at worst" in contract
    assert (expected["usd_typical"], expected["usd_worst_case"]) == (
        Decimal("0.016"),
        Decimal("0.06"),
    )
    assert (expected["items"], expected["first_seconds_warm"], expected["all_seconds_warm"]) == (
        4,
        8,
        32,
    )
    # A mutant: the bounding item's seconds in place of the typical's is not the contract's.
    assert not DRIVE.same_estimate(
        {**{k: str(v) for k, v in expected.items()}, "usd_typical": "0.06"}, expected
    )


def test_pr1_names_more_shipped_kind_versions_than_an_ask_may_hold():
    kinds = list((ROOT / "assets" / "catalogs" / "things" / "kinds").glob("*.v*.json"))

    assert len(kinds) > DRIVE.PIECE_KINDS_MAXIMUM


def test_the_kind_draft_plan_answers_the_manifests_drafter_with_the_fixture_farm():
    from exulanica.models.manifest import load_manifest
    from exulanica.selection.kind_drafting import DRAFTER_ROLE

    sys.path.insert(0, str(ROOT / "tests"))
    from kind_briefs import brief_of, fixture_kind, held_to_form

    plan = json.loads(DRIVE.KIND_DRAFT_PLAN.read_text())
    drafter = load_manifest()[DRAFTER_ROLE].primary.model_id
    by_words = {rule["match"]["contains"]: rule for rule in plan["rules"]}

    assert {rule["match"]["model"] for rule in plan["rules"]} == {drafter}
    assert set(by_words) == set(plan["descriptions"].values())
    ready = by_words[plan["descriptions"]["ready"]]
    assert json.loads(ready["content"]) == held_to_form(brief_of(fixture_kind("farm")))
    assert json.loads(by_words[plan["descriptions"]["refused"]]["content"]) == {"zones": []}
    assert by_words[plan["descriptions"]["failed"]]["status"] == 500


def test_v2_crosses_on_the_newest_luanti_mapping_by_its_version_number(tmp_path):
    # A-142: the mapping is read from the directory, so v10 is newer than v9 and v3.
    mappings = tmp_path / DRIVE.LUANTI_MAPPINGS
    mappings.mkdir(parents=True)
    for version in (2, 3, 9, 10):
        (mappings / f"luanti-minetest-game.v{version}.json").write_text("{}")

    assert DRIVE.newest_mapping(tmp_path).name == "luanti-minetest-game.v10.json"
    shipped = sorted((ROOT / DRIVE.LUANTI_MAPPINGS).glob("luanti-minetest-game.v*.json"))
    assert DRIVE.LUANTI_MAPPING in [path.relative_to(ROOT) for path in shipped]


def test_ln1_reads_the_labels_an_ask_offers_from_the_products_own_choice_function():
    from exulanica.models.choice import ChoiceRequest

    choice = ChoiceRequest(
        description="Choose what to do.", options=("wait", "say hello"), line_characters_maximum=80
    )

    assert DRIVE.offered_labels(choice.tool()) == ["wait", "say hello"]


def test_s5_uploads_the_committed_pack_as_canonical_json_the_product_reads_back():
    from exulanica.world import style_packs

    manifest, files = DRIVE.s5_upload(ROOT)
    raw = DRIVE.canonical_json(manifest)
    declaration = DRIVE.s5_declaration(raw)

    assert raw == style_packs.canonical_json(manifest).encode("ascii")
    assert declaration["manifest_sha256"] == hashlib.sha256(raw).hexdigest()
    assert {f["path"]: f["sha256"] for f in manifest["files"]} == {
        path: hashlib.sha256(data).hexdigest() for path, data in files.items()
    }
    assert not manifest["pack_id"].startswith("exulanica.")
