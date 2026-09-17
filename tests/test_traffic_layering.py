"""The traffic layer, tested for real: a pure simulation that cannot reach what it must not.

``exulanica.traffic`` has its own slot in the exhaustive import-linter layers and a forbidden
contract naming the database, the store, the evidence spine, the pipeline, the society engine, the
model client and the numeric stack. A contract that has never failed is one nobody has tested, so
this file makes it fail, in a private copy of the package so that no other test running at the
same time ever sees a planted import.

It also scans the package for a clock, randomness, secrets, the environment and anything that can
make a float, which the determinism of replay depends on and the linter cannot see.
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
_PACKAGE = ROOT / "exulanica" / "traffic"

TRAFFIC_CONTRACT = (
    "Traffic simulation is pure: no database, store, evidence, pipeline, society engine or model"
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
    "exulanica.models",
    "exulanica.api",
    "numpy",
    "torch",
)
NEGATIVE_CONTROL_PREFIX = "_negative_control_"


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


# ---------------------------------------------------------------------------------------------
# The contract


def test_the_traffic_package_exists_and_has_something_to_check():
    assert _PACKAGE.joinpath("__init__.py").is_file()
    assert len(_sources()) >= 10, _sources()


def test_traffic_has_its_own_layer_below_the_database_and_a_forbidden_contract():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    [layers] = [contract for contract in contracts if contract["type"] == "layers"]
    assert layers["exhaustive"] is True
    order = layers["layers"]
    at = order.index("traffic")
    assert order[at - 1 : at + 2] == ["db | models | store", "traffic", "reconstruction | capture"]
    [traffic] = [contract for contract in contracts if contract["name"] == TRAFFIC_CONTRACT]
    assert traffic["type"] == "forbidden"
    assert traffic["source_modules"] == ["exulanica.traffic"]
    assert sorted(traffic["forbidden_modules"]) == sorted(FORBIDDEN)


def test_lint_imports_keeps_the_traffic_contract():
    result = _lint_imports(ROOT)
    # Only this contract is asserted: another test may be breaking its own on purpose right now.
    assert _contract_lines(result.stdout).get(TRAFFIC_CONTRACT) == "KEPT", result.stdout


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
        module = copy_root / "exulanica" / "traffic" / f"{name}.py"
        with module.open("x", encoding="utf-8") as handle:
            handle.write(f"import {imported}  # a deliberate violation in a throwaway copy\n")
        planted[imported] = f"exulanica.traffic.{name}"
    result = _lint_imports(copy_root)
    assert result.returncode != 0, result.stdout + result.stderr
    assert _contract_lines(result.stdout).get(TRAFFIC_CONTRACT) == "BROKEN", result.stdout
    for imported, module in planted.items():
        # The chain starts at the planted module, which exists only in the copy.
        assert f"{module} -> {imported} (l.1)" in result.stdout, (imported, result.stdout)
    assert not list(_PACKAGE.glob(f"{NEGATIVE_CONTROL_PREFIX}*"))


def test_traffic_imports_nothing_first_party_but_grammar_canonical_and_errors():
    allowed = ("exulanica.traffic", "exulanica.grammar", "exulanica.canonical", "exulanica.errors")
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                modules.append(node.module or "")
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                if module.split(".")[0] == "exulanica":
                    assert any(
                        module == name or module.startswith(f"{name}.") for name in allowed
                    ), f"{path.name} imports {module}"


def test_traffic_reads_the_city_in_one_module():
    """Only the converter names the city grammar, so a new city version changes one file."""
    readers = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                modules.append(node.module or "")
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            if any(module.startswith("exulanica.grammar.grammars") for module in modules):
                readers.append(path.name)
    assert sorted(set(readers)) == ["city_roads.py"]
    assert not _PACKAGE.joinpath("provisional_records.py").exists()


# ---------------------------------------------------------------------------------------------
# No clock, no random, no secrets, no environment, no float

_BANNED_MODULES = frozenset(
    {
        "calendar",
        "cmath",
        "datetime",
        "decimal",
        "fractions",
        "math",
        "numpy",
        "os",
        "random",
        "secrets",
        "statistics",
        "time",
        "zoneinfo",
    }
)
#: Exact integer functions from a banned module that the geometry needs.
_ALLOWED_FROM = {"math": frozenset({"isqrt"})}
_BANNED_NAMES = frozenset({"float", "complex"})
_BANNED_CALLS = frozenset({"hash", "id", "pow", "round", "float", "complex"})
_BANNED_ATTRIBUTES = frozenset(
    {
        "environ",
        "fromtimestamp",
        "getenv",
        "getrandbits",
        "monotonic",
        "now",
        "perf_counter",
        "random",
        "SystemRandom",
        "time_ns",
        "today",
        "urandom",
        "utcnow",
        "uuid1",
        "uuid4",
    }
)


def _nondeterminism(source: str, filename: str) -> list[str]:
    problems = []
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        where = f"{filename}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Import):
            problems += [
                f"{where} imports {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] in _BANNED_MODULES
            ]
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _BANNED_MODULES:
                problems += [
                    f"{where} imports {alias.name} from {node.module}"
                    for alias in node.names
                    if alias.name not in _ALLOWED_FROM.get(root, frozenset())
                ]
            problems += [
                f"{where} imports {alias.name}"
                for alias in node.names
                if alias.name in _BANNED_ATTRIBUTES
            ]
        elif isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            problems.append(f"{where} names {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in _BANNED_ATTRIBUTES:
            problems.append(f"{where} reaches .{node.attr}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _BANNED_CALLS:
                problems.append(f"{where} calls {node.func.id}()")
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"load", "loads"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "json"
                and "parse_float" not in {keyword.arg for keyword in node.keywords}
            ):
                problems.append(f"{where} parses JSON without refusing floats")
        elif isinstance(node, ast.Constant) and type(node.value) in {float, complex}:
            problems.append(f"{where} has a non-integer literal {node.value!r}")
        elif isinstance(node, ast.BinOp | ast.AugAssign) and isinstance(node.op, ast.Div | ast.Pow):
            problems.append(f"{where} uses {type(node.op).__name__}, which can make a float")
    return problems


def test_the_nondeterminism_scan_catches_what_it_claims_to():
    """A scan that finds nothing must be shown able to find something."""
    planted = {
        "x = 1.5": "non-integer literal",
        "import random": "imports random",
        "from time import time": "imports time from time",
        "from math import sqrt": "imports sqrt from math",
        "import math": "imports math",
        "import os": "imports os",
        "from datetime import datetime": "imports datetime from datetime",
        "y = a / b": "Div",
        "y = a ** 2": "Pow",
        "y /= 2": "Div",
        "y = float(a)": "calls float()",
        "y: float = 0": "names float",
        "y = hash(a)": "calls hash()",
        "y = round(a)": "calls round()",
        "y = uuid.uuid4()": "reaches .uuid4",
        "y = x.environ['A']": "reaches .environ",
        "y = json.loads(t)": "without refusing floats",
    }
    for source, expected in planted.items():
        found = _nondeterminism(source, "<planted>")
        assert any(expected in problem for problem in found), (source, found)
    clean = "from math import isqrt\ny = a // b << 3\nz = uuid.uuid5(n, s)\nw = {**d}"
    assert _nondeterminism(clean, "<clean>") == []


def test_the_traffic_package_has_no_clock_no_random_no_environment_and_no_float():
    problems = []
    for path in _sources():
        problems += _nondeterminism(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT)))
    assert problems == [], "\n".join(problems)
