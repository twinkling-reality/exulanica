"""The lettering tool stays outside the product, in both directions, and fontTools with it.

The product reads glyph catalogs. It never parses a font, so it never needs fontTools, and
fontTools must never reach the root environment: every lane runs ``uv sync --locked --offline``, so
a new root dependency breaks all of them at once. Three rules hold that:

1. The import contract in ``pyproject.toml`` forbids ``exulanica_lettering_tool`` over the import
   graph, as it forbids ``exulanica_training``.
2. This file reads the source, for a tree where the tool is not installed and so is absent from
   that graph, and reads the lock, where the dependency would show up.
3. ``tools/lettering`` carries its own ``[tool.uv]`` table. Without one, uv walks up and takes the
   ROOT project's settings: MEASURED 2026-09-17, it wrote the root's ``moge`` dependency metadata
   into the tool's lock and resolved a different Python. A tool environment that inherits the
   product's settings is one edit away from sharing its lock.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "lettering"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def test_nothing_in_the_product_imports_the_tool_or_a_font_parser():
    offenders = sorted(
        f"{path.relative_to(ROOT)} imports {name}"
        for path in (ROOT / "exulanica").rglob("*.py")
        for name in _imports(path)
        if name.split(".")[0] in {"exulanica_lettering_tool", "fontTools", "fonttools"}
    )
    assert offenders == []


def test_the_import_contract_names_the_tool():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    (contract,) = [
        c for c in contracts if c["name"] == "The product never imports the lettering tool"
    ]
    assert contract["type"] == "forbidden"
    assert contract["source_modules"] == ["exulanica"]
    assert contract["forbidden_modules"] == ["exulanica_lettering_tool"]
    (layers,) = [c for c in contracts if c["type"] == "layers" and c["containers"] == ["exulanica"]]
    assert layers["exhaustive"] is True
    assert "lettering" in " ".join(layers["layers"]).split()


def test_font_tools_is_in_the_tool_s_lock_and_nowhere_near_the_product_s():
    product = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    # Every dependency the product can install, from every list that can carry one. Prose may name
    # fontTools (the contracts below explain themselves); a requirement may not.
    requirements = [
        *product["project"]["dependencies"],
        *(
            requirement
            for extra in product["project"].get("optional-dependencies", {}).values()
            for requirement in extra
        ),
        *(
            requirement
            for group in product.get("dependency-groups", {}).values()
            for requirement in group
        ),
    ]
    assert [name for name in requirements if "fonttools" in name.lower()] == []
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert "fonttools" not in lock.lower(), (
        "fontTools has entered the product's lock. Every lane runs uv sync --locked --offline; "
        "the conversion tool keeps its own environment in tools/lettering for this reason."
    )
    tool = tomllib.loads((TOOL / "pyproject.toml").read_text(encoding="utf-8"))
    assert tool["project"]["name"] == "exulanica-lettering-tool"
    assert tool["project"]["dependencies"] == ["fonttools==4.65.0"]
    # Its own [tool.uv] table, or uv takes the root project's settings.
    assert "uv" in tool["tool"]
    tool_lock = tomllib.loads((TOOL / "uv.lock").read_text(encoding="utf-8"))
    assert {package["name"] for package in tool_lock["package"]} >= {"fonttools", "pytest"}
    assert "manifest" not in tool_lock or "dependency-metadata" not in tool_lock["manifest"], (
        "the tool's lock carries the root project's dependency metadata, which means uv resolved "
        "it with the root's settings"
    )


def test_the_tool_reaches_nothing_of_the_product():
    for path in (TOOL / "exulanica_lettering_tool").rglob("*.py"):
        for name in _imports(path):
            top = name.split(".")[0]
            assert top != "exulanica", f"{path.relative_to(ROOT)} imports {name}"
            assert top not in {"psycopg", "fastapi", "requests", "httpx", "urllib3"}, (
                f"{path.relative_to(ROOT)} imports {name}; the tool reads files and nothing else"
            )


def test_the_tool_is_not_on_the_product_s_test_path_or_in_its_wheel():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["exulanica"]
    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
