"""The movement modules' layer, tested for real: pure steps that cannot reach what they must not.

``exulanica.movement`` has its own slot in the exhaustive import-linter layers, directly under the
world that composes its inputs, and a forbidden contract naming the database, the store, the
evidence spine, the pipeline, the world, the traffic simulation, the model client and the numeric
stack. A contract that has never failed is one nobody has tested, so this file makes it fail, in a
private copy of the package so that no other test running at the same time sees a planted import.

It also scans the package for a clock, randomness, the environment and a float literal, which the
exact replay of a flight depends on and the linter cannot see; the project's own environment
reader, ``exulanica.env``, is one of the contract's forbidden imports.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = ROOT / "exulanica" / "movement"

MOVEMENT_CONTRACT = (
    "Movement modules are pure: no database, store, evidence, pipeline, world, traffic or model"
)
FORBIDDEN = (
    "psycopg",
    "exulanica.db",
    "exulanica.store",
    "exulanica.evidence",
    "exulanica.ingest",
    "exulanica.migrations",
    "exulanica.identity",
    "exulanica.selection",
    "exulanica.reconstruction",
    "exulanica.capture",
    "exulanica.world",
    "exulanica.traffic",
    "exulanica.models",
    "exulanica.api",
    "numpy",
    "torch",
    "exulanica.env",
)
NEGATIVE_CONTROL_PREFIX = "_negative_control_"
#: Modules whose names alone would let a step depend on the machine or the moment it runs.
_UNREPLAYABLE = ("random", "time", "datetime", "os", "secrets", "uuid")


def _sources() -> list[Path]:
    return sorted(_PACKAGE.rglob("*.py"))


def _lint_imports(cwd: Path) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("lint-imports", path=str(Path(sys.executable).parent))
    assert executable is not None, "lint-imports is not installed next to this interpreter"
    # lint-imports puts its working directory first on the path, so run from a copy it analyses
    # the copy. No cache, so nothing stale is read; a wide terminal, so no name is wrapped.
    return subprocess.run(
        [executable, "--no-cache", "--no-logo"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "COLUMNS": "200"},
        check=False,
    )


def _contract_lines(output: str) -> dict[str, str]:
    found = {}
    for line in output.splitlines():
        matched = re.fullmatch(r"(.+) (KEPT|BROKEN)", line.strip())
        if matched:
            found[matched.group(1)] = matched.group(2)
    return found


def test_movement_has_its_layer_under_the_world_and_a_forbidden_contract():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    [layers] = [
        contract
        for contract in contracts
        if contract["type"] == "layers" and contract["containers"] == ["exulanica"]
    ]
    order = layers["layers"]
    at = order.index("movement")
    assert order[at - 1] == "world | identity"
    [movement] = [contract for contract in contracts if contract["name"] == MOVEMENT_CONTRACT]
    assert movement["type"] == "forbidden"
    assert movement["source_modules"] == ["exulanica.movement"]
    assert sorted(movement["forbidden_modules"]) == sorted(FORBIDDEN)


def test_lint_imports_keeps_the_movement_contract():
    result = _lint_imports(ROOT)
    # Only this contract is asserted: another test may be breaking its own on purpose right now.
    assert _contract_lines(result.stdout).get(MOVEMENT_CONTRACT) == "KEPT", result.stdout


def test_the_negative_control_breaks_the_contract_for_every_forbidden_import(tmp_path: Path):
    """In a private copy: one planted module per forbidden import, each named as a violation."""
    copy_root = tmp_path / "checkout"
    shutil.copytree(
        ROOT / "exulanica",
        copy_root / "exulanica",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy2(ROOT / "pyproject.toml", copy_root / "pyproject.toml")
    planted = {}
    for imported in FORBIDDEN:
        name = f"{NEGATIVE_CONTROL_PREFIX}{imported.replace('.', '_')}"
        module = copy_root / "exulanica" / "movement" / f"{name}.py"
        with module.open("x", encoding="utf-8") as handle:
            handle.write(f"import {imported}  # a deliberate violation in a throwaway copy\n")
        planted[imported] = f"exulanica.movement.{name}"
    result = _lint_imports(copy_root)
    assert result.returncode != 0, result.stdout + result.stderr
    assert _contract_lines(result.stdout).get(MOVEMENT_CONTRACT) == "BROKEN", result.stdout
    for imported, module in planted.items():
        # The chain starts at the planted module, which exists only in the copy.
        assert f"{module} -> {imported} (l.1)" in result.stdout, (imported, result.stdout)
    assert not list(_PACKAGE.glob(f"{NEGATIVE_CONTROL_PREFIX}*"))


def test_no_step_reads_a_clock_randomness_the_environment_or_a_float_literal():
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                names = []
            assert not set(names) & set(_UNREPLAYABLE), (path.name, names)
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                raise AssertionError(f"{path.name}:{node.lineno} holds a float literal")
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "float":
                raise AssertionError(f"{path.name}:{node.lineno} makes a float")
