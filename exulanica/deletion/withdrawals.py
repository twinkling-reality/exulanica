"""The withdrawals a restore carries, read from their catalog and written again the product's way.

A tombstone is not the only way a person ends something. Stopping a model right, withdrawing a
consent or logging out is recorded in the row it ends, or as a row of its own, and a database
restored from a backup taken before it holds the thing as current again: the tombstone replay of
``exulanica.deletion.restore`` never sees it. ``withdrawals.v2.json`` names every such withdrawal,
the rows each one writes and how a withdrawn row is recognised, and this module does three things
with it for a checkpoint of profile ``exulanica.restore-tombstone-checkpoint/v2``:

* :func:`read_withdrawals` reads every withdrawn row the catalog names, across workspaces, as the
  checkpoint's record of them. A column kind is carried as its identity and the columns a
  withdrawal sets and nothing else; an event kind as its whole row, because the row is the
  withdrawal.
* :func:`reapply` writes one carried withdrawal into a restored database with the statement the
  product writes: a column kind sets its columns on a row whose withdrawal is still open, so every
  trigger that update fires runs (migration 0104's search-entry erasure among them); an event kind
  appends its row when the database holds what it ends, through the product's own writer where the
  catalog names one (a retraction also retracts its claim). A chain the backup ends at a grant made
  before one the carried withdrawal follows is continued with a withdrawal of its own, by the writer
  the catalog names. A row the backup does not hold needs nothing, because a restore never brings
  back a row its backup lacks.
* :func:`stale_withdrawals` names a withdrawal the restored database holds that the checkpoint
  does not, which means the checkpoint is older than the backup.

The catalog is data with an identity (:data:`CATALOG_IDENTITY`); a checkpoint records it, and a
replay under another catalog refuses.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json

__all__ = [
    "CATALOG",
    "CATALOG_IDENTITY",
    "CATALOG_PATH",
    "EXCLUSIONS",
    "WRITER_KEYS",
    "Carried",
    "CarryRefused",
    "Exclusion",
    "WithdrawalKind",
    "Writer",
    "kind_of",
    "read_withdrawals",
    "reapply",
    "stale_withdrawals",
]

CATALOG_PATH: Final = Path(__file__).with_name("withdrawals.v2.json")
CATALOG_PROFILE: Final = "exulanica.restore-withdrawal-catalog/v2"


class CarryRefused(RuntimeError):
    """A carried withdrawal cannot be written into this database as the checkpoint records it."""


@dataclass(frozen=True, slots=True)
class Join:
    """The row of ``table`` a carried row names, matched on ``on``, which both tables share."""

    table: str
    on: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Condition:
    """One test on one column: ``is null``, ``is not null``, or membership in a set of values.

    The column is the row's own, or with ``of`` the column of the row it names in another table.
    """

    column: str
    is_: Literal["null", "not null"] | None = None
    in_: tuple[str, ...] | None = None
    of: Join | None = None

    def over(self, alias: str) -> sql.Composable:
        if self.of is not None:
            return sql.SQL("exists (select 1 from {} j where ({}) = ({}) and {})").format(
                sql.Identifier(self.of.table),
                _names(self.of.on, "j"),
                _names(self.of.on, alias),
                Condition(self.column, self.is_, self.in_).over("j"),
            )
        column = sql.Identifier(alias, self.column)
        if self.is_ == "null":
            return sql.SQL("{} is null").format(column)
        if self.is_ == "not null":
            return sql.SQL("{} is not null").format(column)
        if self.in_ is not None:
            return sql.SQL("{}::text = any({})").format(column, sql.Literal(list(self.in_)))
        raise ValueError(f"condition on {self.column} states neither is nor in")


@dataclass(frozen=True, slots=True)
class Ends:
    """The rows an event withdrawal ends: rows of ``table`` matching the event on ``columns``."""

    table: str
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WithdrawalKind:
    """One table's withdrawals, as the catalog states them."""

    kind: str
    table: str
    shape: Literal["column", "event"]
    identity: tuple[str, ...]
    columns: tuple[str, ...]
    withdrawn: Condition
    carried_when: tuple[Condition, ...]
    workspace: str | None
    ends: Ends | None
    order: str | None
    #: The name of the product's writer of the carried row, or None for the generic insert.
    writer: str | None = None
    #: The name of the writer that continues a chain the carried row cannot follow.
    continues: str | None = None

    def carried(self, alias: str) -> sql.Composable:
        """The rows a checkpoint carries: withdrawn, and whatever else the catalog requires."""
        return sql.SQL(" and ").join(
            [self.withdrawn.over(alias), *(c.over(alias) for c in self.carried_when)]
        )

    @property
    def chained(self) -> bool:
        """Whether the withdrawal ends a chain of decisions in its own table."""
        return self.ends is not None and self.ends.table == self.table


@dataclass(frozen=True, slots=True)
class Exclusion:
    """A withdrawal-shaped table the catalog does not carry, and why."""

    table: str
    reason: str


@dataclass(frozen=True, slots=True)
class Carried:
    """One withdrawal as a checkpoint records it."""

    kind: str
    row: dict[str, Any]


def _condition(value: dict[str, Any]) -> Condition:
    if "is" in value and value["is"] not in ("null", "not null"):
        raise ValueError(f"unknown test {value['is']!r} on {value['column']}")
    values = value.get("in")
    of = value.get("of")
    return Condition(
        column=value["column"],
        is_=value.get("is"),
        in_=None if values is None else tuple(values),
        of=None if of is None else Join(of["table"], tuple(of["on"])),
    )


#: A product writer: the restored database's connection, in the carried row's own workspace
#: session, and the carried row as the checkpoint records it. Deletion knows nothing about how a
#: claim or a consent is written, so the writers a catalog names are given to replay by its caller
#: (``exulanica.orchestration.restore``), keyed by the names the catalog uses.
Writer = Callable[[psycopg.Connection[Any], Mapping[str, Any]], None]


def _load(path: Path) -> tuple[tuple[WithdrawalKind, ...], tuple[Exclusion, ...], dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("profile") != CATALOG_PROFILE:
        raise ValueError(f"{path} is not a {CATALOG_PROFILE} catalog")
    kinds = []
    for entry in document["kinds"]:
        if entry["shape"] not in ("column", "event"):
            raise ValueError(f"{entry['kind']}: unknown shape {entry['shape']!r}")
        ends = entry.get("ends")
        kinds.append(
            WithdrawalKind(
                kind=entry["kind"],
                table=entry["table"],
                shape=entry["shape"],
                identity=tuple(entry["identity"]),
                columns=tuple(entry.get("columns", ())),
                withdrawn=_condition(entry["withdrawn"]),
                carried_when=tuple(_condition(c) for c in entry.get("carried_when", ())),
                workspace=entry["workspace"],
                ends=None if ends is None else Ends(ends["table"], tuple(ends["columns"])),
                order=entry.get("order"),
                writer=entry.get("writer"),
                continues=entry.get("continues"),
            )
        )
    names = [kind.kind for kind in kinds]
    if len(set(names)) != len(names):
        raise ValueError(f"{path} names a kind twice")
    for kind in kinds:
        if (kind.shape == "column") != bool(kind.columns) or (kind.shape == "event") != (
            kind.ends is not None
        ):
            raise ValueError(
                f"{kind.kind}: a column kind names columns, an event kind what it ends"
            )
        if kind.shape == "column" and kind.writer is not None:
            raise ValueError(f"{kind.kind}: a column kind is written by its own update")
        if kind.continues is not None and not (kind.chained and kind.order):
            raise ValueError(f"{kind.kind}: only an ordered chain can be continued")
    exclusions = tuple(Exclusion(e["table"], e["reason"]) for e in document["excluded"])
    return tuple(kinds), exclusions, document


CATALOG, EXCLUSIONS, _DOCUMENT = _load(CATALOG_PATH)

#: What a checkpoint records of the catalog it was sealed under: its profile and the SHA-256 of
#: its canonical JSON. A replay whose catalog differs refuses, because the checkpoint then carries
#: another set of withdrawals than this replay would look for.
CATALOG_IDENTITY: Final = {
    "profile": CATALOG_PROFILE,
    "sha256": hashlib.sha256(canonical_json(_DOCUMENT)).hexdigest(),
}

_BY_KIND: Final = {kind.kind: kind for kind in CATALOG}

#: Every writer name the catalog uses: what a replay must be given, and all it may be given.
WRITER_KEYS: Final = frozenset(
    name for kind in CATALOG for name in (kind.writer, kind.continues) if name is not None
)


def _names(columns: tuple[str, ...], alias: str | None = None) -> sql.Composable:
    return sql.SQL(", ").join(
        sql.Identifier(alias, column) if alias else sql.Identifier(column) for column in columns
    )


def _projection(kind: WithdrawalKind, alias: str) -> sql.Composable:
    """What a checkpoint holds of one withdrawn row: its identity and the withdrawal's columns,
    or for an event the whole row."""
    if kind.shape == "event":
        return sql.SQL("to_jsonb({})").format(sql.Identifier(alias))
    return sql.SQL("jsonb_build_object({})").format(
        sql.SQL(", ").join(
            sql.SQL("{}, {}").format(sql.Literal(column), sql.Identifier(alias, column))
            for column in (*kind.identity, *kind.columns)
        )
    )


def read_withdrawals(connection: psycopg.Connection[Any]) -> list[Carried]:
    """Every withdrawn row the catalog names, in catalog order, each kind in a stable order."""
    carried = []
    for kind in CATALOG:
        order = kind.identity
        if kind.chained and kind.ends is not None and kind.order is not None:
            order = (*kind.ends.columns, kind.order, *kind.identity)
        rows = connection.execute(
            sql.SQL("select {} as row from {} t where {} order by {}").format(
                _projection(kind, "t"),
                sql.Identifier(kind.table),
                kind.carried("t"),
                _names(order, "t"),
            )
        ).fetchall()
        carried.extend(Carried(kind.kind, row["row"]) for row in rows)
    return carried


def kind_of(carried: Carried) -> WithdrawalKind:
    """The catalog entry a carried withdrawal names, or a refusal naming the unknown kind."""
    kind = _BY_KIND.get(carried.kind)
    if kind is None:
        raise CarryRefused(f"the checkpoint carries a withdrawal of unknown kind {carried.kind!r}")
    return kind


def _record(kind: WithdrawalKind) -> sql.Composable:
    """The carried row, typed as a row of the kind's table."""
    return sql.SQL("jsonb_populate_record(null::{}, %(row)s)").format(sql.Identifier(kind.table))


def _matches(columns: tuple[str, ...], left: str, right: str) -> sql.Composable:
    return sql.SQL("({}) is not distinct from ({})").format(
        _names(columns, left), _names(columns, right)
    )


def require_writers(writers: Mapping[str, Writer]) -> None:
    """Refuse writers other than exactly the ones the catalog names, each by its name."""
    missing = sorted(WRITER_KEYS - writers.keys())
    if missing:
        raise CarryRefused(
            f"replay was not given the writers the withdrawal catalog names: {missing}"
        )
    unnamed = sorted(writers.keys() - WRITER_KEYS)
    if unnamed:
        raise CarryRefused(
            f"replay was given writers the withdrawal catalog does not name: {unnamed}"
        )


def reapply(
    connection: psycopg.Connection[Any], carried: Carried, writers: Mapping[str, Writer]
) -> str:
    """Write one carried withdrawal into this database, the product's way, and say what happened.

    Returns ``carried`` when this wrote it, ``continued`` when it withdrew the chain the carried
    row ended after a decision the backup holds and the carried row cannot follow, ``present`` when
    the database already held it exactly, ``absent`` when the database holds nothing it ends, and
    ``already`` when an event withdrawal's chain already ends withdrawn here. Raises
    :class:`CarryRefused` when the database holds the row with another withdrawal than the
    checkpoint records, refuses the write, or ``writers`` is not exactly the catalog's.
    """
    require_writers(writers)
    kind = kind_of(carried)
    parameters = {"row": Jsonb(carried.row)}
    if kind.shape == "column":
        return _reapply_column(connection, kind, parameters)
    return _reapply_event(connection, kind, carried, writers)


def _reapply_column(
    connection: psycopg.Connection[Any], kind: WithdrawalKind, parameters: dict[str, Any]
) -> str:
    table = sql.Identifier(kind.table)
    written = connection.execute(
        sql.SQL(
            "update {table} t set ({columns}) = (select {columns} from {record} r) "
            "where ({identity_t}) = (select {identity} from {record} r) and not ({withdrawn})"
        ).format(
            table=table,
            columns=_names(kind.columns),
            record=_record(kind),
            identity_t=_names(kind.identity, "t"),
            identity=_names(kind.identity),
            withdrawn=kind.withdrawn.over("t"),
        ),
        parameters,
    ).rowcount
    held = connection.execute(
        sql.SQL(
            "select {same} as same from {table} t "
            "join {record} r on ({identity_t}) = ({identity_r})"
        ).format(
            same=_matches(kind.columns, "t", "r"),
            table=table,
            record=_record(kind),
            identity_t=_names(kind.identity, "t"),
            identity_r=_names(kind.identity, "r"),
        ),
        parameters,
    ).fetchone()
    if held is None:
        return "absent"
    if not held["same"]:
        raise CarryRefused(
            f"the restored {kind.table} row holds another withdrawal than the checkpoint records"
        )
    return "carried" if written else "present"


def _reapply_event(
    connection: psycopg.Connection[Any],
    kind: WithdrawalKind,
    carried: Carried,
    writers: Mapping[str, Writer],
) -> str:
    assert kind.ends is not None  # an event kind names what it ends; _load refuses otherwise
    table = sql.Identifier(kind.table)
    parameters = {"row": Jsonb(carried.row)}
    same = sql.SQL(
        "select to_jsonb(t) = to_jsonb(r) as same from {table} t join {record} r "
        "on ({identity_t}) = ({identity_r})"
    ).format(
        table=table,
        record=_record(kind),
        identity_t=_names(kind.identity, "t"),
        identity_r=_names(kind.identity, "r"),
    )
    held = connection.execute(same, parameters).fetchone()
    if held is not None:
        if not held["same"]:
            raise CarryRefused(
                f"the restored {kind.table} row differs from the withdrawal the checkpoint records"
            )
        return "present"
    ordered = kind.chained and kind.order is not None
    ends = sql.SQL("select {} as withdrawn, {} as position from {} e join {} r on {}").format(
        kind.withdrawn.over("e") if kind.chained else sql.SQL("true"),
        sql.Identifier("e", kind.order) if ordered else sql.SQL("null"),
        sql.Identifier(kind.ends.table),
        _record(kind),
        _matches(kind.ends.columns, "e", "r"),
    )
    ends = (
        sql.SQL("{} order by {} desc limit 1").format(ends, sql.Identifier("e", kind.order))
        if ordered
        else sql.SQL("{} limit 1").format(ends)
    )
    found = connection.execute(ends, parameters).fetchone()
    if found is None or found["withdrawn"] is None:
        return "absent"
    if kind.chained and found["withdrawn"]:
        return "already"
    # A chain whose last decision here comes more than one before the carried row's lacks the
    # decisions made after the backup, so the carried row cannot follow it: the chain is
    # continued with a withdrawal of its own. Any other position is written as it is, and the
    # database refuses one it cannot follow.
    continues, writer = kind.continues, kind.writer
    if (
        continues is not None
        and kind.order is not None
        and carried.row[kind.order] > found["position"] + 1
    ):
        _write(connection, kind, "continue", lambda: writers[continues](connection, carried.row))
        # Checked, as a writer's row is: the writer asks the chain at its own instant and may find
        # nothing to withdraw (a decision recorded ahead of this host's clock is not yet one to
        # it), and a replay that completed with the chain still ending in a grant would serve it.
        after = connection.execute(ends, parameters).fetchone()
        if after is None or not after["withdrawn"]:
            raise CarryRefused(
                f"the checkpoint's {kind.kind} withdrawal was not continued: the chain this "
                "backup holds still ends in a decision it does not withdraw"
            )
        return "continued"
    if writer is None:
        _write(
            connection,
            kind,
            "follow",
            lambda: connection.execute(
                sql.SQL("insert into {} select ({}).*").format(table, _record(kind)), parameters
            ),
        )
        return "carried"
    _write(connection, kind, "follow", lambda: writers[writer](connection, carried.row))
    written = connection.execute(same, parameters).fetchone()
    if written is None or not written["same"]:
        raise CarryRefused(
            f"the {kind.kind} writer did not write the {kind.table} row the checkpoint records"
        )
    return "carried"


def _write(
    connection: psycopg.Connection[Any],
    kind: WithdrawalKind,
    verb: str,
    write: Callable[[], object],
) -> None:
    """Run one write in its own savepoint; the database's refusal becomes one naming the kind."""
    try:
        with connection.transaction():
            write()
    except psycopg.Error as error:
        raise CarryRefused(
            f"the checkpoint's {kind.kind} withdrawal cannot {verb} what this backup holds: "
            f"{error.diag.message_primary or error}"
        ) from error


def stale_withdrawals(
    connection: psycopg.Connection[Any], carried: list[Carried]
) -> list[tuple[str, dict[str, Any]]]:
    """Every withdrawal this database holds that the checkpoint does not carry exactly.

    A checkpoint is sealed from the source after every backup of it, and a withdrawal is written
    once and never undone, so each withdrawal a restored database holds is in a current
    checkpoint. One that is not says the checkpoint is older than the backup.
    """
    stale = []
    for kind in CATALOG:
        rows = [item.row for item in carried if item.kind == kind.kind]
        same = (
            sql.SQL("to_jsonb(c) = to_jsonb(t)")
            if kind.shape == "event"
            else _matches((*kind.identity, *kind.columns), "c", "t")
        )
        found = connection.execute(
            sql.SQL(
                "select {projection} as row from {table} t where {carried} and not exists ("
                "select 1 from jsonb_populate_recordset(null::{table}, %(rows)s) c where {same})"
            ).format(
                projection=_projection(kind, "t"),
                table=sql.Identifier(kind.table),
                carried=kind.carried("t"),
                same=same,
            ),
            {"rows": Jsonb(rows)},
        ).fetchall()
        stale.extend((kind.kind, row["row"]) for row in found)
    return stale
