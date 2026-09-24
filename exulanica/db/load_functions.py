"""The functions a restore runs while it loads rows, and whether each resolves its own names.

A dump made by ``pg_dump`` sets ``search_path`` to the empty string before anything else, and
``psql`` and ``pg_restore`` then copy each table's rows with its CHECK constraints in force, build
each index and fill each stored generated column under that path. Each of those expressions is
stored with its own names resolved, but the body of a PL/pgSQL or string-bodied SQL function is
parsed when it runs, so such a function whose body names anything outside ``pg_catalog``, itself
included, cannot find it and stops the restore. Measured: ``privacy_canonical`` (migration 0040)
calls itself on each member of a JSON value, eight receipt CHECKs call it, and ``COPY
personal_model_right`` stopped at the first model right in both dump formats. A function that
carries its own ``search_path`` resolves under any caller's path; migration 0036 pinned the
JSON-schema validators and 0106 the canonicaliser for this reason.

:func:`loading_functions_without_a_path` asks the catalog for every such function, so one added
later is found without anybody listing it. ``tests/test_restore_loads_every_row.py`` holds the
migrated schema to having none, and ``exulanica-local-db`` pins each one it finds in a restored
schema before loading rows (:func:`pin_loading_functions`), which is what lets a dump taken before
0106 load. A body is read for words that name something of the database outside the system
schemas; a word that matches by accident pins a function that did not need it, which is harmless.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

__all__ = ["LoadingFunction", "loading_functions_without_a_path", "pin_loading_functions"]

#: Every function a restore runs while it loads rows: one a table or domain CHECK calls, one an
#: index expression or predicate calls, one a stored generated column calls. A default is not
#: one, because a dump supplies every column and a restore never evaluates it. A function an
#: extension owns is the extension's, and one in a system schema resolves under any path.
_LOADING: Final = """
with loading as (
  select d.refobjid as function_oid, 'check ' || c.conname as used_by
    from pg_constraint c
    join pg_depend d on d.classid = 'pg_constraint'::regclass and d.objid = c.oid
                    and d.refclassid = 'pg_proc'::regclass
   where c.contype = 'c'
  union all
  select d.refobjid, 'index ' || i.indexrelid::regclass::text
    from pg_index i
    join pg_depend d on d.classid = 'pg_class'::regclass and d.objid = i.indexrelid
                    and d.refclassid = 'pg_proc'::regclass
  union all
  select d.refobjid, 'generated ' || a.attrelid::regclass::text || '.' || a.attname
    from pg_attrdef ad
    join pg_attribute a on a.attrelid = ad.adrelid and a.attnum = ad.adnum
                       and a.attgenerated = 's'
    join pg_depend d on d.classid = 'pg_attrdef'::regclass and d.objid = ad.oid
                    and d.refclassid = 'pg_proc'::regclass
)
select p.oid as function_oid, p.oid::regprocedure::text as signature,
       n.nspname as schema_name, l.lanname as language, p.prosrc as body,
       p.prosqlbody is not null as parsed,
       exists (select 1 from unnest(coalesce(p.proconfig, '{}'::text[])) setting
                where setting like 'search\\_path=%%') as pinned,
       array_agg(distinct loading.used_by order by loading.used_by) as used_by
  from loading
  join pg_proc p on p.oid = loading.function_oid
  join pg_namespace n on n.oid = p.pronamespace
  join pg_language l on l.oid = p.prolang
 where n.nspname <> 'information_schema' and n.nspname !~ '^pg_'
   and not exists (select 1 from pg_depend e where e.classid = 'pg_proc'::regclass
                    and e.objid = p.oid and e.deptype = 'e')
   and (%(schema)s::text is null or n.nspname = %(schema)s::text)
 group by p.oid, n.nspname, l.lanname, p.prosrc, p.prosqlbody, p.proconfig
 order by 2
"""

#: The names a body can reach only through ``search_path``: every function, relation and type
#: outside the system schemas, and the schema each lives in.
_NAMES: Final = """
select x.name, n.nspname as schema_name
  from (select pronamespace as namespace, proname as name from pg_proc
        union select relnamespace, relname from pg_class
        union select typnamespace, typname from pg_type) x
  join pg_namespace n on n.oid = x.namespace
 where n.nspname <> 'information_schema' and n.nspname !~ '^pg_'
"""

#: The languages whose bodies are parsed when they run. A C or internal function has no body to
#: parse, and a SQL function written with BEGIN ATOMIC was parsed when it was created.
_PARSED_WHEN_RUN: Final = frozenset({"plpgsql", "sql"})

_WORD: Final = re.compile(r"[a-z_][a-z0-9_$]*")


@dataclass(frozen=True, slots=True)
class LoadingFunction:
    """A function a restore runs while it loads rows, which resolves names through the path."""

    signature: str
    function_oid: int
    #: The schema the function lives in, then every other schema holding a name it uses.
    schemas: tuple[str, ...]
    #: The names its body uses that only the path can resolve.
    names: tuple[str, ...]
    #: The constraints, indexes and generated columns that call it.
    used_by: tuple[str, ...]


def loading_functions_without_a_path(
    connection: psycopg.Connection[Any], *, schema: str | None = None
) -> list[LoadingFunction]:
    """Every function a restore runs while loading rows that would fail under an empty path.

    ``schema`` narrows the answer to functions in that schema; None asks about every schema.
    """
    homes: dict[str, set[str]] = {}
    with connection.cursor(row_factory=dict_row) as cursor:
        for row in cursor.execute(_NAMES).fetchall():
            homes.setdefault(row["name"], set()).add(row["schema_name"])
        rows = cursor.execute(_LOADING, {"schema": schema}).fetchall()
    found = []
    for row in rows:
        if row["pinned"] or row["parsed"] or row["language"] not in _PARSED_WHEN_RUN:
            continue
        names = sorted(set(_WORD.findall((row["body"] or "").lower())) & set(homes))
        if not names:
            continue
        own = row["schema_name"]
        others = sorted({home for name in names for home in homes[name]} - {own})
        found.append(
            LoadingFunction(
                signature=row["signature"],
                function_oid=int(row["function_oid"]),
                schemas=(own, *others),
                names=tuple(names),
                used_by=tuple(row["used_by"]),
            )
        )
    return found


def pin_loading_functions(
    connection: psycopg.Connection[Any], *, schema: str | None = None
) -> Sequence[LoadingFunction]:
    """Give each function :func:`loading_functions_without_a_path` finds a path of its own.

    The path is the function's own schema, every other schema holding a name its body uses, then
    ``pg_catalog`` and ``pg_temp`` last, as the migrations pin a function. Nothing else about the
    function changes, and it returns what it pinned.
    """
    found = loading_functions_without_a_path(connection, schema=schema)
    with connection.cursor(row_factory=dict_row) as cursor:
        for function in found:
            statement = cursor.execute(
                "select format('alter function %%s set search_path = %%s', %s::oid::regprocedure, "
                "array_to_string(array(select quote_ident(s) from unnest(%s::text[]) s), ', ') "
                "|| ', pg_catalog, pg_temp') as statement",
                (function.function_oid, list(function.schemas)),
            ).fetchone()
            assert statement is not None
            cursor.execute(statement["statement"])
    return found
