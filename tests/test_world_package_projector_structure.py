"""The projector holds the 1.0 core and the signing; the authored plane is read elsewhere.

``exulanica/world_package/projector.py`` reads the 1.0 components, signs and receipts. Everything
that reads the authored plane (alternate versions, their objects, overrides, instances and edit
chains, and the reviewed catalogs those objects name) is in
``exulanica/world_package/extension_projection.py``, and which versions an extension may carry is
decided by ``exulanica/world_package/export_partition.py`` from the edit-kind registry. So the
projector names no table of that plane and no list of edit kinds, and imports none of the world
modules those two read the plane with, which is what these tests read from its syntax tree. The
plane's tables are read from the migrations that create them, and its modules from the imports of
the two modules that read it, so neither list is written here.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "exulanica" / "world_package"
MIGRATIONS = ROOT / "exulanica" / "migrations"
#: The reviewed catalogs an authored object names. Migration data rather than plane rows, and read
#: only to describe what the extension's objects reference.
REVIEWED_CATALOGS = frozenset({"world_reviewed_asset", "world_object_behaviour_registry"})
_KIND_LIST = re.compile(r"\bkind\s+in\s*\(", re.IGNORECASE)


def plane_tables() -> frozenset[str]:
    """Every table a migration creates for alternate versions, and the reviewed catalogs."""
    created = {
        match.group(1)
        for path in MIGRATIONS.glob("[0-9]*.sql")
        for match in re.finditer(
            r"create table (world_alternate_\w+)", path.read_text(encoding="utf-8")
        )
    }
    return frozenset(created) | REVIEWED_CATALOGS


def _strings(tree: ast.AST) -> list[tuple[int, str]]:
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def offences(source: str) -> list[str]:
    """Each string in the module that names a plane table or lists edit kinds, with its line."""
    tables = plane_tables()
    found = []
    for line, value in _strings(ast.parse(source)):
        named = sorted(table for table in tables if re.search(rf"\b{table}\b", value))
        if named:
            found.append(f"line {line}: names {named}")
        if _KIND_LIST.search(value):
            found.append(f"line {line}: lists edit kinds")
    return found


def test_the_plane_is_read_from_the_migrations():
    tables = plane_tables()
    assert {"world_alternate_version", "world_alternate_version_edit"} <= tables
    assert len(tables - REVIEWED_CATALOGS) >= 6, sorted(tables)


def test_the_projector_names_no_plane_table_and_no_list_of_edit_kinds():
    assert offences((PACKAGE / "projector.py").read_text(encoding="utf-8")) == []


def test_the_reader_sees_what_it_looks_for():
    """Positive controls: the module that reads the plane names it, and a planted query fails."""
    assert any(
        "world_alternate_version_edit" in offence
        for offence in offences((PACKAGE / "extension_projection.py").read_text(encoding="utf-8"))
    )
    planted = (
        "SQL = \"select 1 from world_alternate_object where kind in ('add_object')\"\n"
        "OTHER = f\"where kind IN ('undo') and {x}\"\n"
    )
    assert offences(planted) == [
        "line 1: names ['world_alternate_object']",
        "line 1: lists edit kinds",
        "line 2: lists edit kinds",
    ]


def _world_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("exulanica.world.")
    }


def test_the_projector_imports_no_module_the_extension_half_reads_the_plane_with():
    """The plane's modules are the ones the extension half imports, read rather than listed."""
    plane_modules = _world_imports(PACKAGE / "extension_projection.py") | _world_imports(
        PACKAGE / "export_partition.py"
    )
    assert {"exulanica.world.object_repository", "exulanica.world.edit_kinds"} <= plane_modules
    assert _world_imports(PACKAGE / "projector.py") & plane_modules == set()
    tree = ast.parse((PACKAGE / "projector.py").read_text(encoding="utf-8"))
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "exulanica.world_package.extension_projection"
        for node in ast.walk(tree)
    )
