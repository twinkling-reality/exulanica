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
    record = json.loads((ROOT / DRIVE.LIVING_RECORD).read_text())["record"]
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
