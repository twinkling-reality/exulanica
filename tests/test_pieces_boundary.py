"""The piece formats belong to no side, and what the product reads of them needs no numpy.

The import contracts in pyproject.toml hold the same three rules on the import graph; this file
holds them by reading the source, and proves the numpy rule at run time in a child interpreter
where numpy cannot be imported.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIECES = ROOT / "exulanica_pieces"
#: What the product may read: plain Python.
FORMAT_MODULES = ("budgets", "canonical", "colour", "records", "vocabulary")


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_the_piece_formats_import_neither_the_product_nor_the_appearance_code() -> None:
    for path in PIECES.rglob("*.py"):
        for name in _imports(path):
            assert name.split(".")[0] not in ("exulanica", "exulanica_appearance"), (
                f"{path.relative_to(ROOT)} imports {name}"
            )


def test_the_format_modules_import_only_the_standard_library_and_each_other() -> None:
    for module in FORMAT_MODULES:
        for name in _imports(PIECES / f"{module}.py"):
            top = name.split(".")[0]
            if top == "exulanica_pieces":
                assert not name.startswith("exulanica_pieces.geometry"), (module, name)
            else:
                assert top in sys.stdlib_module_names or top == "__future__", (module, name)


def test_the_product_never_imports_the_piece_geometry() -> None:
    for path in (ROOT / "exulanica").rglob("*.py"):
        for name in _imports(path):
            assert not name.startswith("exulanica_pieces.geometry"), (
                f"{path.relative_to(ROOT)} imports {name}"
            )


def test_the_format_modules_load_where_numpy_cannot() -> None:
    program = (
        "import sys\n"
        "sys.modules['numpy'] = None\n"
        "import exulanica_pieces.canonical, exulanica_pieces.colour\n"
        "import exulanica_pieces.records, exulanica_pieces.vocabulary\n"
        "from exulanica_pieces.budgets import read_budgets\n"
        "from exulanica_pieces.colour import read_table\n"
        "from pathlib import Path\n"
        f"read_table(Path({str(ROOT)!r}))\n"
        f"read_budgets(Path({str(ROOT)!r}))\n"
        "print('loaded without numpy')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, cwd=ROOT, check=False
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "loaded without numpy"
