"""The authored-world extension to WMP 1.0, and the compatibility it must not cost.

The fixture ``tests/fixtures/wmp-1.0-before-authored-world`` was written by the unmodified
projector at 90edb49, before any extension code existed, and signed with a key derived from a
fixed test string. It is a real 1.0 package from before this change, not a reconstruction of
one, and ``wmp-1.0-before-authored-world.expected.json`` holds what that commit's verifier said
about it. Nothing in this file may edit either.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from exulanica.world_package.package import (
    PROFILE_VERSION,
    import_check_package,
    inspect_package,
    verify_package,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = _FIXTURES / "wmp-1.0-before-authored-world"
GOLDEN_EXPECTED = json.loads(
    (_FIXTURES / "wmp-1.0-before-authored-world.expected.json").read_text(encoding="utf-8")
)


def _golden_copy(tmp_path: Path) -> Path:
    destination = tmp_path / "golden"
    shutil.copytree(GOLDEN, destination)
    return destination


def test_a_1_0_package_written_before_the_extension_still_verifies_unchanged(tmp_path: Path):
    package = _golden_copy(tmp_path)
    before = {path: path.read_bytes() for path in sorted(package.rglob("*")) if path.is_file()}
    report = verify_package(package).as_dict()
    for key, value in GOLDEN_EXPECTED["verify"].items():
        assert report[key] == value, key
    assert report["profile_version"] == PROFILE_VERSION
    after = {path: path.read_bytes() for path in sorted(package.rglob("*")) if path.is_file()}
    assert after == before, "verification must not touch the package it verifies"


def test_the_pre_extension_inspect_and_import_check_answers_are_preserved(tmp_path: Path):
    package = _golden_copy(tmp_path)
    inspected = inspect_package(package)
    for key, value in GOLDEN_EXPECTED["inspect"].items():
        assert inspected[key] == value, key
    for name, declared in (
        ("import_check_undeclared", {}),
        (
            "import_check_declared",
            {
                "supported_style_profiles": frozenset({"origin-landscape@1"}),
                "supported_interaction_capabilities": frozenset({"comfort.vignette@1"}),
            },
        ),
    ):
        checked = import_check_package(package, **declared)
        for key, value in GOLDEN_EXPECTED[name].items():
            assert checked[key] == value, (name, key)
