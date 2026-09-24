"""The selection routes construct no domain object: they validate, delegate and render views.

``exulanica/api/routes/selection*.py`` may construct its own request and response views, the
framework's objects, and a gateway that works on the route's connection, which is a class whose
constructor takes that connection first, as a repository's does. Every other class it can name
comes from a product package below the API, and constructing one in a route is domain logic in
the HTTP layer: a plan, an answer or a placement belongs to the module that owns its rules.

Each module's syntax tree is read and every call resolved against the module's own namespace and
every import in its source, so neither an alias nor an import inside a function hides a class, and
a view defined in the module is recognised as one. An exception is not a domain object here. The
controls below require the rule to see a construction it is shown, one of them behind a local
import, so a resolution that found nothing cannot pass for a clean module.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUTES = sorted((ROOT / "exulanica/api/routes").glob("selection*.py"))
#: A function appended to a route module by the local-import control.
PLANTED = (
    "\n\ndef _planted():\n"
    "    from exulanica.world import ObjectOrigin\n"
    "\n"
    "    return ObjectOrigin('authored', 'fictional')\n"
)


def _gateway(cls: type) -> bool:
    """A class that works on the connection it is handed first, as a repository does."""
    try:
        parameters = list(inspect.signature(cls).parameters)
    except (TypeError, ValueError):
        return False
    return parameters[:1] == ["connection"]


def _domain_class(value: Any) -> bool:
    return (
        inspect.isclass(value)
        and value.__module__.startswith("exulanica.")
        and not value.__module__.startswith("exulanica.api.")
        and not issubclass(value, BaseException)
        and not _gateway(value)
    )


def _resolve(node: ast.expr, namespace: dict[str, Any]) -> Any:
    if isinstance(node, ast.Name):
        return namespace.get(node.id)
    if isinstance(node, ast.Attribute):
        owner = _resolve(node.value, namespace)
        return None if owner is None else getattr(owner, node.attr, None)
    return None


def constructions(source: str, namespace: dict[str, Any]) -> list[tuple[int, str]]:
    """Each call in ``source`` that constructs a domain class, as (line, class name)."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            callee = _resolve(node.func, namespace)
            if _domain_class(callee):
                found.append((node.lineno, callee.__qualname__))
    return sorted(found)


def _namespace(path: Path) -> dict[str, Any]:
    """The module's own names, and every name an import anywhere in its source binds.

    An import inside a function binds nothing at module level, so a class a route imported locally
    would otherwise resolve to nothing and pass unseen.
    """
    package = "exulanica.api.routes"
    namespace = dict(vars(importlib.import_module(f"{package}.{path.stem}")))
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            source = "." * node.level + (node.module or "")
            module = importlib.import_module(importlib.util.resolve_name(source, package))
            for alias in node.names:
                namespace.setdefault(alias.asname or alias.name, getattr(module, alias.name, None))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    namespace.setdefault(alias.asname, importlib.import_module(alias.name))
                else:
                    top = alias.name.partition(".")[0]
                    namespace.setdefault(top, importlib.import_module(top))
    return namespace


def test_the_rule_reads_both_selection_route_modules():
    assert [path.name for path in ROUTES] == ["selection.py", "selection_environment.py"]


@pytest.mark.parametrize("path", ROUTES, ids=lambda path: path.name)
def test_a_selection_route_module_constructs_no_domain_object(path):
    found = constructions(path.read_text(encoding="utf-8"), _namespace(path))
    assert found == [], f"{path.name} constructs domain objects at (line, class): {found}"


def test_the_rule_sees_a_construction_and_passes_a_view_and_a_gateway():
    """The control: a plan built in a route is found; a view and a repository are not."""
    namespace = _namespace(ROOT / "exulanica/api/routes/selection.py")
    source = (
        "def route(connection, session):\n"
        "    PlaceBridgeRepository(connection, session.workspace_id)\n"
        "    ModelCallView(role='r')\n"
        "    return SelectionPlan(intent=Intent.CONTENT)\n"
    )
    assert constructions(source, namespace) == [(4, "SelectionPlan")]


def test_the_rule_sees_a_class_a_route_imports_inside_its_body(tmp_path):
    """The control for a local import: the class is bound nowhere at module level."""
    route = ROOT / "exulanica/api/routes/selection_environment.py"
    planted = tmp_path / route.name
    planted.write_text(route.read_text(encoding="utf-8") + PLANTED, encoding="utf-8")
    source = planted.read_text(encoding="utf-8")
    found = constructions(source, _namespace(planted))
    assert found == [(len(source.splitlines()), "ObjectOrigin")]
