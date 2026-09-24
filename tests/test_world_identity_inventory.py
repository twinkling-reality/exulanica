"""Every place the code assumes a workspace has one world, found by reading the code.

A workspace keys every world table by ``(workspace_id, world_id)``, so storage already holds any
number of worlds. What can still assume one is code: a parameter whose default names a world, a
call that names the legacy world ``atlas:default`` outright, a call into a world-scoped function or
repository that leaves the world out and so takes whatever the callee defaults to, a query on a
world table that never says which world, a route whose ``world_id`` a caller may omit, and a route
that addresses an authored version and names no world at all. Each scan below finds one of those
shapes in ``exulanica/`` and ``scripts/``, and each has a positive control, so a scan that stops
matching fails rather than reporting a clean tree.

The allowlists name what remains, each entry with its reason. They may only shrink: a new
occurrence fails, and so does an entry whose occurrence has gone, so the list is always exactly
what the code holds. ``docs/saved-world-entry.md`` states where the world a request means comes
from instead.

What the scans cannot see. A call is matched to a world-scoped callee by name, and a name defined
both with and without a ``world_id`` parameter is not matched at all. A query counts as naming its
world when ``world_id`` appears anywhere in its text, even for a different table of a join. A
``**kwargs`` call is taken to pass ``world_id``. Those are the limits of reading source rather than
running it; the two-world isolation test (``tests/test_two_worlds_stay_apart.py``) is the check
that runs it.
"""

from __future__ import annotations

import ast
import pathlib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The Python trees scanned: the product package and the scripts that drive it.
SCANNED = ("exulanica", "scripts")

#: The browser sources scanned for the literal, outside their tests.
SCANNED_WEB = (
    "web/packages/app/src",
    "web/packages/atlas-core/src",
    "web/packages/atlas-react/src",
)

#: The identity every workspace's personal-source world had before worlds were registered. Named
#: here because it is what these scans look for; product code resolves worlds instead.
LEGACY_WORLD_ID = "atlas:default"

#: The name the legacy identity was exported under.
LEGACY_NAME = "DEFAULT_WORLD_ID"

#: The table that says which worlds a workspace holds. A statement over it is about the set of
#: worlds rather than inside one, so it names no world by design and is not scanned as one.
REGISTRY_OF_WORLDS = "world_identity"

#: SQL verbs that make a string a statement rather than prose that mentions a table.
_SQL = re.compile(r"\b(select|insert|update|delete)\b", re.IGNORECASE)

# ---------------------------------------------------------------------------------------------
# What remains, with why. Each list may only shrink.
# ---------------------------------------------------------------------------------------------

#: Parameters and fields whose default names a world.
ALLOWED_DEFAULTS: dict[str, str] = {}

#: Code that names the legacy world outright, other than as a default.
ALLOWED_LEGACY_NAMES: dict[str, str] = {
    "scripts/prepare_living_world_preview.py::_snapshot": (
        "a fictional preview fixture's world id, written into the fixture it generates"
    ),
    "scripts/prepare_living_world_preview.py::generate_preview": (
        "a fictional preview fixture's world id, written into the fixture it generates"
    ),
    "scripts/record_living_society.py::flatiron_input": (
        "a fictional society input's world id, written into the record it produces"
    ),
    "scripts/record_personal_admission_evidence.py::rehearse": (
        "the world a rehearsal's frontier manifest names for the fresh workspace it builds"
    ),
}

#: Calls into a world-scoped callable that leave ``world_id`` out.
ALLOWED_OMISSIONS: dict[str, str] = {}

#: Why a saved-world entry statement may be addressed by entry id alone.
_BY_ENTRY = "addressed by entry id, unique in the workspace; the entry row names its own world"
#: Why an experiment definition may be read by experiment id alone.
_BY_EXPERIMENT = (
    "addressed by experiment id, unique in the workspace; the definition row names its own world, "
    "which each read beneath a version compares with the world its caller named"
)

#: Statements on a world table whose text never names a world.
ALLOWED_WORLDLESS_QUERIES: dict[str, str] = {
    **{
        f"exulanica/world/saved_entries.py::SavedWorldEntryRepository.{name} [saved_world_entry]": (
            _BY_ENTRY
        )
        for name in (
            "_advance_revision",
            "advance_authored_locked",
            "advance_style_locked",
            "membership_ledger",
            "update",
        )
    },
    "exulanica/world/society_experiment_repository.py::SocietyExperimentRepository._definition_row"
    " [society_experiment_definition]": _BY_EXPERIMENT,
}

#: Routes whose ``world_id`` parameter a caller may omit.
ALLOWED_OPTIONAL_ROUTE_WORLDS: dict[str, str] = {}

#: Browser sources that spell the legacy world.
ALLOWED_WEB_LITERALS: dict[str, str] = {
    "web/packages/atlas-core/src/world/composer.ts": (
        "the renderer's draft composer names this world when its caller names none; the draft is "
        "drawn in the browser and nothing submits it"
    ),
}


# ---------------------------------------------------------------------------------------------
# Reading the code
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    name: str
    tree: ast.Module


def python_sources(trees: Iterable[str] = SCANNED) -> Iterator[Source]:
    for tree in trees:
        for path in sorted((ROOT / tree).rglob("*.py")):
            yield Source(
                path.relative_to(ROOT).as_posix(), ast.parse(path.read_text(encoding="utf-8"))
            )


def world_tables_from_migrations() -> frozenset[str]:
    """Tables whose ``create table`` statement declares a ``world_id`` column.

    Read from the migration text so the scans need no database; ``test_the_world_tables_are_the
    _schema_s`` holds the result equal to the migrated schema's own answer.
    """
    found: set[str] = set()
    for path in sorted((ROOT / "exulanica" / "migrations").glob("[0-9]*.sql")):
        text = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
        for match in re.finditer(r"create table (?:if not exists )?([a-z_0-9]+)\s*\(", text):
            depth, index = 1, match.end()
            while depth and index < len(text):
                depth += {"(": 1, ")": -1}.get(text[index], 0)
                index += 1
            body = text[match.end() : index - 1]
            if re.search(r"(^|,)\s*world_id\s+text\b", body, re.MULTILINE):
                found.add(match.group(1))
        for match in re.finditer(
            r"alter table (?:only )?([a-z_0-9]+)\s+add column (?:if not exists )?world_id\b", text
        ):
            found.add(match.group(1))
    return frozenset(found)


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _qualname(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    names = []
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(current.name)
    return ".".join(reversed(names)) or "<module>"


def _names_legacy_world(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Name):
        return node.id == LEGACY_NAME
    if isinstance(node, ast.Attribute):
        return node.attr == LEGACY_NAME
    return isinstance(node, ast.Constant) and node.value == LEGACY_WORLD_ID


def _default_nodes(source: Source) -> Iterator[tuple[str, ast.AST]]:
    """Every (key, default expression) a parameter or class field declares."""
    parents = _parents(source.tree)
    for node in ast.walk(source.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = _qualname(node, parents)
            where = node.name if owner == "<module>" else f"{owner}.{node.name}"
            positional = node.args.posonlyargs + node.args.args
            defaulted = positional[len(positional) - len(node.args.defaults) :]
            pairs = list(zip(defaulted, node.args.defaults, strict=True))
            pairs += [
                (argument, default)
                for argument, default in zip(
                    node.args.kwonlyargs, node.args.kw_defaults, strict=True
                )
                if default is not None
            ]
            for argument, default in pairs:
                yield f"{source.name}::{where}({argument.arg})", default
        elif isinstance(node, ast.ClassDef):
            for statement in node.body:
                if isinstance(statement, ast.AnnAssign) and statement.value is not None:
                    target = getattr(statement.target, "id", "?")
                    value = statement.value
                    if isinstance(value, ast.Call):
                        for keyword in value.keywords:
                            if keyword.arg == "default":
                                yield f"{source.name}::{node.name}.{target}", keyword.value
                    else:
                        yield f"{source.name}::{node.name}.{target}", value


def legacy_defaults(sources: Iterable[Source]) -> dict[str, str]:
    """Parameters and fields whose default is the legacy world, by name or by value."""
    found = {}
    for source in sources:
        for key, default in _default_nodes(source):
            if _names_legacy_world(default):
                found[key] = ast.unparse(default)
    return found


def legacy_names(sources: Iterable[Source]) -> dict[str, int]:
    """Every other expression naming the legacy world, counted per enclosing definition."""
    found: dict[str, int] = {}
    for source in sources:
        defaults = {id(default) for _, default in _default_nodes(source)}
        parents = _parents(source.tree)
        for node in ast.walk(source.tree):
            if id(node) in defaults or not _names_legacy_world(node):
                continue
            key = f"{source.name}::{_qualname(node, parents)}"
            found[key] = found.get(key, 0) + 1
    return found


@dataclass(frozen=True)
class WorldScoped:
    """Where a callable of this name takes ``world_id``: a positional index, or keyword only."""

    positional_index: int | None


def world_scoped_callables(sources: Iterable[Source]) -> dict[str, WorldScoped]:
    """Every callable name whose every definition takes a ``world_id`` parameter.

    A class counts under its own name when its ``__init__`` does. A name defined anywhere without
    the parameter is left out, because a call to it cannot be told apart from a call to the
    world-scoped one by reading the call.
    """
    with_world: dict[str, set[int | None]] = {}
    without_world: set[str] = set()
    for source in sources:
        for node in ast.walk(source.tree):
            functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, bool]] = []
            if isinstance(node, ast.ClassDef):
                for statement in node.body:
                    if isinstance(statement, ast.FunctionDef) and statement.name == "__init__":
                        functions.append((node.name, statement, True))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("__"):
                    continue
                is_method = bool(node.args.args) and node.args.args[0].arg in {"self", "cls"}
                functions.append((node.name, node, is_method))
            for name, function, bound in functions:
                positional = function.args.posonlyargs + function.args.args
                offset = 1 if bound and positional else 0
                index = next(
                    (i - offset for i, a in enumerate(positional) if a.arg == "world_id"), None
                )
                keyword_only = any(a.arg == "world_id" for a in function.args.kwonlyargs)
                if index is None and not keyword_only:
                    without_world.add(name)
                else:
                    with_world.setdefault(name, set()).add(index)
    return {
        name: WorldScoped(max(indexes, key=lambda value: -1 if value is None else value))
        for name, indexes in with_world.items()
        if name not in without_world and len(indexes) == 1
    }


def _callee(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def omitted_worlds(sources: Iterable[Source], scoped: dict[str, WorldScoped]) -> dict[str, int]:
    """Calls to a world-scoped callable that do not pass ``world_id``."""
    found: dict[str, int] = {}
    for source in sources:
        parents = _parents(source.tree)
        for node in ast.walk(source.tree):
            if not isinstance(node, ast.Call):
                continue
            name = _callee(node)
            if name is None or name not in scoped:
                continue
            if any(k.arg in {"world_id", None} for k in node.keywords):
                continue
            index = scoped[name].positional_index
            if index is not None and len(node.args) > index:
                continue
            if any(isinstance(argument, ast.Starred) for argument in node.args):
                continue
            key = f"{source.name}::{_qualname(node, parents)} -> {name}"
            found[key] = found.get(key, 0) + 1
    return found


def _flatten(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            value.value if isinstance(value, ast.Constant) else "{}" for value in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _flatten(node.left) + _flatten(node.right)
    return ""


def worldless_queries(sources: Iterable[Source], tables: frozenset[str]) -> dict[str, int]:
    """Statements naming a world table whose text never says ``world_id``."""
    pattern = re.compile(r"\b(" + "|".join(sorted(tables, key=len, reverse=True)) + r")\b")
    found: dict[str, int] = {}
    for source in sources:
        parents = _parents(source.tree)
        for node in ast.walk(source.tree):
            if not isinstance(node, (ast.Constant, ast.JoinedStr, ast.BinOp)):
                continue
            parent = parents.get(node)
            if isinstance(parent, (ast.BinOp, ast.JoinedStr, ast.Expr)):
                continue
            text = _flatten(node)
            if not text or not _SQL.search(text) or re.search(r"\bworld_id\b", text):
                continue
            named = sorted(set(pattern.findall(text)))
            if not named:
                continue
            key = f"{source.name}::{_qualname(node, parents)} [{', '.join(named)}]"
            found[key] = found.get(key, 0) + 1
    return found


def _request_parameters(dependant: object) -> Iterator[object]:
    """Every query and path parameter of a route, its dependencies' included."""
    yield from getattr(dependant, "query_params", ())
    yield from getattr(dependant, "path_params", ())
    for dependency in getattr(dependant, "dependencies", ()):
        yield from _request_parameters(dependency)


def route_worlds() -> dict[str, bool]:
    """Every route declaring a ``world_id`` parameter, and whether a caller must supply it.

    Walked with :func:`exulanica.api.routes.mounted_routes`, the application's own recursive walk:
    FastAPI keeps included routers as wrappers, and a one-level walk of ``app.routes`` sees none of
    the world routes and reports nothing.
    """
    from exulanica.api import surface
    from exulanica.api.routes import mounted_routes
    from fastapi.routing import APIRoute

    found = {}
    for route in mounted_routes(surface.routing_only_application()):
        if not isinstance(route, APIRoute):
            continue
        for parameter in _request_parameters(route.dependant):
            if parameter.name == "world_id":
                for method in sorted(route.methods):
                    found[f"{method} {route.path}"] = parameter.field_info.is_required()
    return found


def optional_route_worlds() -> dict[str, bool]:
    """Routes that declare a ``world_id`` parameter and give it a default."""
    return {route: False for route, required in route_worlds().items() if not required}


#: The address of an authored version. A version belongs to exactly one world, so a route that
#: takes one is asked in a world, whether or not it declares a ``world_id`` for any other reason.
VERSION_ADDRESS = "/world/versions/{version_id}"


def version_routes() -> list[str]:
    """Every mounted route that addresses an authored version, as ``METHOD /path``."""
    from exulanica.api import surface
    from exulanica.api.routes import mounted_routes
    from fastapi.routing import APIRoute

    return sorted(
        f"{method} {route.path}"
        for route in mounted_routes(surface.routing_only_application())
        if isinstance(route, APIRoute) and route.path.startswith(VERSION_ADDRESS)
        for method in route.methods
    )


def worldless_version_routes(routes: Iterable[str], worlds: dict[str, bool]) -> list[str]:
    """The routes among ``routes`` that a caller can send without naming a world."""
    return sorted(route for route in routes if not worlds.get(route, False))


def web_literals(root: pathlib.Path = ROOT, trees: Iterable[str] = SCANNED_WEB) -> dict[str, int]:
    """Browser source files spelling the legacy world, with how many times."""
    found = {}
    for tree in trees:
        for path in sorted((root / tree).rglob("*.ts")):
            count = path.read_text(encoding="utf-8").count(LEGACY_WORLD_ID)
            if count:
                found[path.relative_to(root).as_posix()] = count
    return found


def _only_shrinks(found: Iterable[str], allowed: dict[str, str], what: str) -> None:
    found = set(found)
    new = sorted(found - set(allowed))
    gone = sorted(set(allowed) - found)
    assert not new, f"{what}, not in the allowlist:\n" + "\n".join(new)
    assert not gone, f"allowlisted {what} no longer in the code; remove the entries:\n" + "\n".join(
        gone
    )


# ---------------------------------------------------------------------------------------------
# The inventory
# ---------------------------------------------------------------------------------------------


def test_no_parameter_or_field_defaults_to_a_world():
    _only_shrinks(legacy_defaults(python_sources()), ALLOWED_DEFAULTS, "defaults naming a world")


def test_no_code_names_the_legacy_world():
    _only_shrinks(legacy_names(python_sources()), ALLOWED_LEGACY_NAMES, "legacy world names")


def test_every_world_scoped_call_names_its_world():
    sources = list(python_sources())
    scoped = world_scoped_callables(sources)
    _only_shrinks(omitted_worlds(sources, scoped), ALLOWED_OMISSIONS, "calls omitting world_id")


def test_every_world_table_statement_names_its_world():
    tables = world_tables_from_migrations() - {REGISTRY_OF_WORLDS}
    found = worldless_queries(python_sources(), tables)
    _only_shrinks(found, ALLOWED_WORLDLESS_QUERIES, "world-table statements naming no world")


def test_every_route_requires_the_world_it_names():
    _only_shrinks(
        optional_route_worlds(), ALLOWED_OPTIONAL_ROUTE_WORLDS, "routes with an optional world_id"
    )


def test_every_route_that_addresses_a_version_requires_its_world():
    routes = version_routes()
    # The guard on the guard: the walk sees the version routes, by name.
    assert "GET /world/versions/{version_id}/society/district" in routes, routes
    assert "POST /world/versions/{version_id}/society/experiments" in routes, routes
    assert worldless_version_routes(routes, route_worlds()) == []


def test_a_version_route_that_names_no_world_is_found():
    """Positive control: a planted version route with no ``world_id``, or an optional one."""
    planted = "GET /world/versions/{version_id}/planted"
    assert worldless_version_routes([planted], {}) == [planted]
    assert worldless_version_routes([planted], {planted: False}) == [planted]
    assert worldless_version_routes([planted], {planted: True}) == []


def test_the_browser_does_not_spell_the_legacy_world():
    _only_shrinks(web_literals(), ALLOWED_WEB_LITERALS, "browser sources spelling the legacy world")


def test_every_allowlist_entry_says_why():
    for allowlist in (
        ALLOWED_DEFAULTS,
        ALLOWED_LEGACY_NAMES,
        ALLOWED_OMISSIONS,
        ALLOWED_WORLDLESS_QUERIES,
        ALLOWED_OPTIONAL_ROUTE_WORLDS,
        ALLOWED_WEB_LITERALS,
    ):
        for key, reason in allowlist.items():
            assert len(reason.split()) >= 4, f"{key} needs a reason, not {reason!r}"


# ---------------------------------------------------------------------------------------------
# Positive controls: each scan finds the shape it exists to find
# ---------------------------------------------------------------------------------------------

_PLANTED = '''
from exulanica.world.models import DEFAULT_WORLD_ID
from exulanica.world import models

def read(connection, workspace_id, world_id=DEFAULT_WORLD_ID): ...
def keyword(connection, *, world_id: str = "atlas:default"): ...

class Contract:
    world_id: str = models.DEFAULT_WORLD_ID

class Repository:
    def __init__(self, connection, workspace_id, *, world_id): ...

def scoped_function(connection, world_id): ...

def route():
    Repository(connection, workspace)
    Repository(connection, workspace, world_id="x")
    Repository(connection, workspace, **options)
    scoped_function(connection)
    scoped_function(connection, "named")
    run(world_id=DEFAULT_WORLD_ID)
    connection.execute("select * from world_style_state where workspace_id=%s")
    connection.execute("select * from world_style_state where workspace_id=%s and world_id=%s")
    connection.execute(f"update world_style_state set x=1 where workspace_id={ws}")
    """select from world_style_state is only prose in a docstring"""
'''


def _planted() -> list[Source]:
    return [Source("planted.py", ast.parse(_PLANTED))]


def test_the_default_scan_finds_a_default_by_name_by_value_and_on_a_field():
    assert legacy_defaults(_planted()) == {
        "planted.py::read(world_id)": "DEFAULT_WORLD_ID",
        "planted.py::keyword(world_id)": "'atlas:default'",
        "planted.py::Contract.world_id": "models.DEFAULT_WORLD_ID",
    }


def test_the_name_scan_finds_a_use_that_is_not_a_default():
    assert legacy_names(_planted()) == {"planted.py::route": 1}


def test_the_omission_scan_finds_a_constructor_and_a_function_called_without_a_world():
    scoped = world_scoped_callables(_planted())
    assert scoped["Repository"] == WorldScoped(None)
    assert scoped["scoped_function"] == WorldScoped(1)
    assert omitted_worlds(_planted(), scoped) == {
        "planted.py::route -> Repository": 1,
        "planted.py::route -> scoped_function": 1,
    }


def test_a_name_defined_without_a_world_is_not_matched():
    sources = [*_planted(), Source("other.py", ast.parse("def scoped_function(x): ..."))]
    assert "scoped_function" not in world_scoped_callables(sources)


def test_the_query_scan_finds_statements_that_name_no_world_and_skips_docstrings():
    found = worldless_queries(_planted(), frozenset({"world_style_state"}))
    assert found == {"planted.py::route [world_style_state]": 2}


def test_the_route_scan_sees_the_included_world_routes_and_a_defaulted_one(monkeypatch):
    """The walk reaches routes inside included routers, and lists one whose world is optional."""
    from exulanica.api import surface
    from fastapi import APIRouter, Query

    seen = route_worlds()
    assert "GET /world/styles/current" in seen, "the walk did not reach the included routers"
    assert "GET /world/versions/{version_id}" in seen

    real = surface.routing_only_application

    def with_optional_world():
        app = real()
        planted = APIRouter(prefix="/planted")

        @planted.get("/read")
        def read(world_id: str = Query("x")) -> None: ...

        app.include_router(planted)
        return app

    monkeypatch.setattr(surface, "routing_only_application", with_optional_world)
    assert optional_route_worlds()["GET /planted/read"] is False


def test_the_web_scan_finds_the_literal_in_a_source_file(tmp_path):
    source = tmp_path / "web" / "src"
    source.mkdir(parents=True)
    (source / "entry.ts").write_text(f"const world = '{LEGACY_WORLD_ID}';\n", encoding="utf-8")
    (source / "clean.ts").write_text("const world = worlds[0];\n", encoding="utf-8")
    assert web_literals(tmp_path, ("web/src",)) == {"web/src/entry.ts": 1}
    assert all((ROOT / tree).is_dir() for tree in SCANNED_WEB)


def test_the_world_tables_are_the_schema_s(repository):
    """The migration reading above against the migrated schema's own list."""
    rows = repository.connection.execute(
        "select distinct c.table_name from information_schema.columns c "
        "join information_schema.tables t on t.table_schema=c.table_schema "
        "and t.table_name=c.table_name and t.table_type='BASE TABLE' "
        "where c.table_schema=current_schema() and c.column_name='world_id'"
    ).fetchall()
    schema = frozenset(row["table_name"] for row in rows)
    assert len(schema) > 30, "the schema answered almost nothing; the query is wrong"
    assert world_tables_from_migrations() == schema
