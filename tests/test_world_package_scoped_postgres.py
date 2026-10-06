"""A World Memory Package carries its own workspace's rows, on any connection.

The projector runs inside a transaction that names the workspace (``exulanica.workspace_id``), and
under the runtime role row-level security keeps every read to it. An owner, a superuser or a
BYPASSRLS role skips row-level security, and person withdrawal and the package command project on
such a connection. So every read the projection makes names its workspace itself: on a database
many visitors share, a package must never carry another workspace's photographs, people or
deletions.

The behaviour, twice on the owner's connection. First, a stranger's workspace beside the rich world
holds a photograph and two named people, and the rich world's package names none of them. Second,
the rich world is itself the stranger: it holds rows in every table the projection reads
(photographs and their derivatives, pipeline history, people named, withdrawn and kept, a deletion
and its tombstone, two worlds' versions, structure, style and interaction policy), and a second
workspace's package names none of the identifiers or digests in any of those rows.

The guard: every query the projection makes, in its own modules and in the readers it calls
elsewhere, that reads a workspace table compares that table's workspace with the one being
packaged, read from the source, so a new query that forgets it fails here before it runs.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import re
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository, name_occurrence
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.stages import STAGES
from exulanica.world_package.projector import project_world_package

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, iso, write_photo
from pg_harness import open_scratch_connection
from test_photo_point_map_composition import placed as imported_placed  # noqa: F401
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401
from test_world_package_withdrawal_postgres import _named
from world_package_rich_world import build_rich_world
from world_support import registered_world

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "exulanica"
#: Where the projection's reads are: its own modules that hold SQL, whole (``export_partition``,
#: ``environments`` and ``authored`` hold none), and the readers it calls elsewhere, by function.
#: A method is named ``Class.method``, and every method of that class it calls through ``self`` is
#: read with it.
SCANNED: tuple[tuple[Path, tuple[str, ...] | None], ...] = (
    (PACKAGE / "world_package" / "projector.py", None),
    (PACKAGE / "world_package" / "extension_projection.py", None),
    (PACKAGE / "graph" / "entities.py", ("_withdrawn_entity_ids",)),
    (PACKAGE / "world" / "worlds.py", ("workspace_world",)),
    (PACKAGE / "world" / "object_repository.py", ("WorldObjectRepository.version",)),
)
MIGRATIONS = PACKAGE / "migrations"
#: A value compared with a workspace column that names the workspace being packaged: a query
#: parameter, or ``current_workspace()``, the workspace the projector's transaction names (0001).
_PARAMETER = r"(?:%s|%\(\w+\)s|\{\}|\$\d+|current_workspace\(\))"
#: Words that end a FROM clause's list of tables.
_CLAUSE_END = (
    r"\b(?:where|join|left|right|inner|full|cross|natural|lateral|on|using|order|group|having|"
    r"limit|offset|union|except|intersect|window|for|returning)\b|\)|;|$"
)
_NOT_AN_ALIAS = frozenset(
    (
        *("where", "join", "left", "right", "inner", "full", "cross", "natural", "lateral"),
        *("on", "using", "order", "group", "having", "limit", "offset", "union", "except"),
        *("intersect", "window", "for", "returning"),
    )
)


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


@pytest.fixture(name="placed")
def _placed_alias(request):
    return request.getfixturevalue("imported_placed")


def _workspace_tables() -> frozenset[str]:
    """Every table some migration creates with a ``workspace_id`` column."""
    found = set()
    for path in sorted(MIGRATIONS.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        for name, body in re.findall(r"create table (\w+) \((.*?)\n\);", text, re.S):
            if re.search(r"^\s*workspace_id\b", body, re.M):
                found.add(name)
    return frozenset(found)


def _text(node: ast.AST, constants: dict[str, str]) -> str | None:
    """The SQL a string expression spells: literals, f-strings (a named module constant spelled
    out, anything else as ``{}``), ``+`` of strings and ``sql.SQL(...)`` (``.format`` included).
    None when the expression is not a string."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value.value, ast.Name) and value.value.id in constants:
                parts.append(constants[value.value.id])
            else:
                parts.append("{}")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _text(node.left, constants), _text(node.right, constants)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "SQL" and node.args:
            return _text(node.args[0], constants)
        if node.func.attr == "format":
            return _text(node.func.value, constants)
    return None


def _scanned_nodes(tree: ast.Module, functions: tuple[str, ...] | None) -> list[ast.AST]:
    """The parts of a module whose statements are read: all of it, or the named functions and,
    for a method, every method of its class it reaches through ``self``."""
    if functions is None:
        return [tree]
    chosen: list[ast.AST] = []
    for name in functions:
        owner, _, method = name.rpartition(".")
        if not owner:
            chosen += [
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == name
            ]
            continue
        [cls] = [
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner
        ]
        methods = {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}
        reached, waiting = set(), [method]
        while waiting:
            current = waiting.pop()
            if current in reached or current not in methods:
                continue
            reached.add(current)
            for call in ast.walk(methods[current]):
                if (
                    isinstance(call, ast.Attribute)
                    and isinstance(call.value, ast.Name)
                    and call.value.id == "self"
                ):
                    waiting.append(call.attr)
        chosen += [methods[name] for name in sorted(reached)]
    assert len(chosen) >= len(functions), functions
    return chosen


def _statements(path: Path, functions: tuple[str, ...] | None) -> list[tuple[int, str]]:
    """Every SQL statement in the scanned parts of ``path`` that reads a table, with its line."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = _text(node.value, {}) if node.value is not None else None
            for target in targets:
                if isinstance(target, ast.Name) and value is not None:
                    constants[target.id] = value
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    found = []
    for scope in _scanned_nodes(tree, functions):
        for node in ast.walk(scope):
            statement = _text(node, constants)
            if statement is None or _text(parents.get(node, tree), constants) is not None:
                continue  # not a string, or a part of a larger one read whole
            if re.search(r"\bselect\b", statement, re.I) and re.search(
                r"\b(from|join)\s", statement, re.I
            ):
                found.append((node.lineno, " ".join(statement.split())))
    return found


def _table_references(statement: str) -> list[tuple[str, str | None]]:
    """Each table a statement reads, as (table, alias): FROM lists with commas, joins, schema
    qualified names (the schema dropped) and a table named by a placeholder (``{}``)."""
    found = []

    def one(item: str) -> None:
        words = item.strip().split()
        if not words or words[0].startswith("(") or "(" in words[0]:
            return  # a subquery or a function, read where its own statement is
        table = words[0].split(".")[-1].strip('"')
        rest = [word for word in words[1:] if word.lower() != "as"]
        alias = rest[0] if rest and rest[0].lower() not in _NOT_AN_ALIAS else None
        found.append((table, alias))

    for listed in re.finditer(rf"\bfrom\s+(.*?)(?={_CLAUSE_END})", statement, re.I | re.S):
        for item in listed.group(1).split(","):
            one(item)
    for joined in re.finditer(r"\bjoin\s+(\S+(?:\s+(?:as\s+)?\w+)?)", statement, re.I):
        one(joined.group(1))
    return found


def _unscoped(statement: str, tables: frozenset[str]) -> list[str]:
    """The workspace tables a statement reads without comparing that table's workspace with a
    parameter, directly or through an equality with another table's scoped workspace."""
    references = [
        (table, alias)
        for table, alias in _table_references(statement)
        if table in tables or table == "{}"
    ]
    names = {alias or table: table for table, alias in references}
    scoped = {
        name
        for name in names
        if re.search(rf"\b{re.escape(name)}\.workspace_id\s*=\s*{_PARAMETER}", statement)
        or re.search(rf"{_PARAMETER}\s*=\s*{re.escape(name)}\.workspace_id\b", statement)
    }
    unaliased = [table for table, alias in references if alias is None]
    bare = len(re.findall(rf"(?<![.\w])workspace_id\s*=\s*{_PARAMETER}", statement))
    if unaliased and bare >= len(unaliased):
        scoped |= set(unaliased)
    pairs = re.findall(r"\b(\w+)\.workspace_id\s*=\s*(\w+)\.workspace_id\b", statement)
    changed = True
    while changed:
        changed = False
        for left, right in pairs:
            for one, other in ((left, right), (right, left)):
                if other in scoped and one in names and one not in scoped:
                    scoped.add(one)
                    changed = True
        for using in re.finditer(r"\bjoin\s+(\w+)(?:\s+(\w+))?\s+using\s*\(([^)]*)\)", statement):
            name = (
                using.group(2) if using.group(2) and using.group(2) != "using" else using.group(1)
            )
            if "workspace_id" in using.group(3) and scoped and name in names and name not in scoped:
                scoped.add(name)
                changed = True
    return sorted(table for name, table in names.items() if name not in scoped)


def test_every_projection_read_of_a_workspace_table_names_its_workspace():
    tables = _workspace_tables()
    assert {"capture", "entity", "entity_link", "occurrence", "tombstone"} <= tables
    unscoped = []
    for path, functions in SCANNED:
        statements = _statements(path, functions)
        # A reader moved or renamed leaves its entry reading nothing, which would pass vacuously.
        assert statements, f"{path.relative_to(ROOT)} {functions} holds no statement to read"
        for line, statement in statements:
            for table in _unscoped(statement, tables):
                unscoped.append(f"{path.relative_to(ROOT)}:{line} {table}")
    assert unscoped == [], unscoped


@pytest.mark.parametrize(
    ("statement", "unscoped"),
    [
        ("select * from capture where workspace_id = %s", []),
        ("select * from capture", ["capture"]),
        ("select * from public.capture c where c.workspace_id = %s", []),
        ("select * from public.capture c where c.capture_id = %s", ["capture"]),
        ("select * from capture c, entity e where c.workspace_id = %s", ["entity"]),
        (
            "select * from capture c, entity e where c.workspace_id = %s "
            "and e.workspace_id = c.workspace_id",
            [],
        ),
        (
            "select * from capture c join entity e on e.entity_id = c.capture_id "
            "where c.workspace_id = %s",
            ["entity"],
        ),
        ("select * from {} where workspace_id = %s", []),
        ("select * from {} where world_id = %s", ["{}"]),
        (
            "select * from capture c join entity e on e.workspace_id = e.workspace_id "
            "where c.workspace_id = %s",
            ["entity"],
        ),
    ],
)
def test_the_scan_reads_what_it_claims_to(statement, unscoped):
    """The guard's own controls: each form a read can take, scoped and not."""
    assert _unscoped(statement, frozenset({"capture", "entity"})) == unscoped


#: The stranger's people, named so nothing in the rich world's own workspace can spell them.
STRANGER_NAMES = ("Oriel Stranger-Vantongeren", "Pell Stranger-Quist")


@pytest.mark.postgres
def test_an_owner_connection_package_carries_no_other_workspace_s_rows(
    repository, placed, photo_dir, tmp_path, spine_schema
):
    """The stranger's photograph (bytes no photograph of the rich world shares) and two people
    named only there; the rich world's package, projected on the owner's connection, carries
    neither the photograph's digest nor either name."""
    world = build_rich_world(repository, placed, photo_dir, tmp_path)
    psycopg_module, scratch = spine_schema
    stranger = uuid.uuid4()
    other = IngestRepository(open_scratch_connection(psycopg_module, scratch), stranger)
    stranger_photos = tmp_path / "stranger-photos"
    stranger_photos.mkdir()
    taken = PhotoIngestPipeline(other, world.store, vision=None).ingest_file(
        write_photo(stranger_photos, "stranger.jpg", when=iso(17))
    )
    assert taken.error is None, taken.error
    for name in STRANGER_NAMES:
        _named(other, name, uuid.uuid4())
    digest = bytes(
        repository.connection.execute(
            "select blob_sha256 from capture where workspace_id = %s", (stranger,)
        ).fetchone()["blob_sha256"]
    ).hex()
    own = {
        bytes(row["blob_sha256"]).hex()
        for row in repository.connection.execute(
            "select blob_sha256 from capture where workspace_id = %s", (repository.workspace_id,)
        )
    }
    assert digest not in own, "the stranger's photograph shares no bytes with the rich world's"
    rolsuper = repository.connection.execute(
        "select rolsuper from pg_roles where rolname = current_user"
    ).fetchone()["rolsuper"]
    assert rolsuper, "the projection runs where row-level security does not"
    output = tmp_path / "package"
    project_world_package(
        repository.connection,
        workspace_id=repository.workspace_id,
        actor=uuid.uuid4(),
        output=output,
        private_key=Ed25519PrivateKey.generate(),
        world_id=world.default_world,
    )
    carried = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in output.rglob("*")
        if path.is_file()
    )
    # The package does carry its own workspace's photographs, so their absence would prove nothing.
    assert any(own_digest in carried for own_digest in own)
    leaked = [value for value in (digest, *STRANGER_NAMES) if value in carried]
    assert leaked == []


def _markers(connection, workspace_id: uuid.UUID, tables: frozenset[str]) -> dict[str, str]:
    """Every identifier and digest in a workspace's rows, with the column it came from: each uuid
    value, as text, and each 32-byte value, as hexadecimal, in every workspace table, and every
    person's name."""
    found: dict[str, str] = {}
    columns = connection.execute(
        "select table_name, column_name, data_type from information_schema.columns "
        "where table_schema = current_schema() and data_type in ('uuid', 'bytea') "
        "and column_name <> 'workspace_id'"
    ).fetchall()
    for column in columns:
        if column["table_name"] not in tables:
            continue
        for row in connection.execute(
            f'select "{column["column_name"]}" as value from "{column["table_name"]}" '
            "where workspace_id = %s",
            (workspace_id,),
        ):
            value = row["value"]
            if value is None:
                continue
            where = f"{column['table_name']}.{column['column_name']}"
            if column["data_type"] == "uuid":
                found.setdefault(str(value), where)
            elif len(bytes(value)) == 32:
                found.setdefault(bytes(value).hex(), where)
    for row in connection.execute(
        "select display_name from entity where workspace_id = %s and display_name is not null",
        (workspace_id,),
    ):
        found.setdefault(row["display_name"], "entity.display_name")
    return found


@pytest.mark.postgres
def test_a_package_names_nothing_of_a_workspace_holding_every_kind_of_row_beside_it(
    repository, placed, photo_dir, tmp_path, spine_schema
):
    """The rich world is the stranger here. A second workspace with a world, a photograph and a
    named person of its own is packaged on the owner's connection, and its package names none of
    the rich workspace's identifiers, digests or names, except those the second workspace's own
    rows hold too (a catalog every workspace is given, for one)."""
    build_rich_world(repository, placed, photo_dir, tmp_path)
    # The rich world is ingested without a vision stage; one observed photograph of a person,
    # named, gives the stranger occurrences and a link to an entity as well.
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    payload["objects"] = [
        {
            "label": "person",
            "salience": "primary",
            "confidence": "high",
            "box": {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.6},
        }
    ]
    observed_dir = tmp_path / "observed"
    observed_dir.mkdir()
    observed = ingest_observed(
        PhotoIngestPipeline(
            repository, placed.api.store, vision=CountingVisionModel(payload=payload)
        ),
        repository,
        write_photo(observed_dir, "observed.jpg", when=iso(18)),
    )
    assert observed.error is None, observed.error
    occurrence = repository.connection.execute(
        "select occurrence_id from occurrence where workspace_id=%s and capture_id=%s "
        "and class='person' order by occurrence_id limit 1",
        (repository.workspace_id, observed.capture_id),
    ).fetchone()
    assert occurrence is not None
    name_occurrence(
        IdentityRepository(repository.connection, repository.workspace_id),
        AssertionWriter(repository.connection, repository.workspace_id),
        occurrence_id=occurrence["occurrence_id"],
        display_name="Quillon Stranger-Observed",
        actor=uuid.uuid4(),
    )
    repository.connection.commit()
    tables = _workspace_tables()
    psycopg_module, scratch = spine_schema
    second = uuid.uuid4()
    own = IngestRepository(open_scratch_connection(psycopg_module, scratch), second)
    world_id = registered_world(own.connection, second)
    own_photos = tmp_path / "second-photos"
    own_photos.mkdir()
    taken = PhotoIngestPipeline(own, placed.api.store, vision=None).ingest_file(
        write_photo(own_photos, "second.jpg", when=iso(19))
    )
    assert taken.error is None, taken.error
    _named(own, "Wren Second-Workspace", uuid.uuid4())
    own.connection.commit()

    stranger = _markers(repository.connection, repository.workspace_id, tables)
    second_rows = _markers(repository.connection, second, tables)
    # A stage's parameter digest is the code's, not a workspace's: a package names the stages its
    # rows were made by, so the digest of a stage the stranger ran is no leak.
    code = {spec.params_digest.hex() for spec in STAGES.values()}
    markers = {
        value: where
        for value, where in stranger.items()
        if value not in second_rows and value not in code
    }
    # The stranger holds rows the projection reads, in many tables, not a handful.
    holding = {
        row["table_name"]
        for row in repository.connection.execute(
            "select table_name from information_schema.columns "
            "where table_schema = current_schema() and column_name = 'workspace_id'"
        )
        if row["table_name"] in tables
        and repository.connection.execute(
            f'select 1 from "{row["table_name"]}" where workspace_id = %s limit 1',
            (repository.workspace_id,),
        ).fetchone()
    }
    assert {"capture", "evidence_span", "occurrence", "entity", "entity_link"} <= holding
    assert {"tombstone", "person_subject", "world_structure_snapshot"} <= holding
    assert len(markers) > 100

    output = tmp_path / "second-package"
    project_world_package(
        repository.connection,
        workspace_id=second,
        actor=uuid.uuid4(),
        output=output,
        private_key=Ed25519PrivateKey.generate(),
        world_id=world_id,
    )
    carried = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in output.rglob("*")
        if path.is_file()
    )
    # The package carries its own workspace's photograph, so an absence proves something.
    assert taken.capture_id is not None and str(taken.capture_id) in second_rows
    assert any(value in carried for value in second_rows)
    leaked = sorted(f"{where} {value}" for value, where in markers.items() if value in carried)
    # A package names a row by pseudonym (exulanica/world_package/pseudonyms.py), the SHA-256 of
    # "<kind>:<identifier>", so each stranger's identifier is also looked for in that form, under
    # every kind the package names.
    named = set(re.findall(r"urn:exulanica:wmp:([a-z0-9_.-]+):([0-9a-f]{64})", carried))
    for kind in {kind for kind, _ in named}:
        digests = {digest for each, digest in named if each == kind}
        leaked += sorted(
            f"{where} {value} as {kind}"
            for value, where in markers.items()
            if hashlib.sha256(f"{kind}:{value}".encode()).hexdigest() in digests
        )
    # The pseudonyms are read: the second workspace's own photograph is named by one.
    assert ("capture", hashlib.sha256(f"capture:{taken.capture_id}".encode()).hexdigest()) in named
    assert leaked == []
