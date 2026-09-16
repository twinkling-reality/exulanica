"""A connection that has declared which workspace it speaks for.

This exists to be the first parameter of every function in this package, so that "the
connection under this statement declared a workspace" is a property of the type rather than a
property of the caller's memory. There is no constructor that skips
:func:`~exulanica.db.session.set_workspace`, so there is no way to hand a spine module an
undeclared connection.

**The scoping is doubled today, and that is worth stating rather than discovering.** A
connection handed to :class:`~exulanica.ingest.repository.IngestRepository` is declared twice:
once here, and once by :class:`~exulanica.epistemics.assertions.AssertionWriter`, which the
repository also constructs and which calls ``set_workspace`` on the same connection. So
deleting either call leaves the connection scoped anyway, and a test that reverts one of them
and expects a failure passes for the wrong reason. Measured. Neither call is redundant in the
sense that it can be removed: the assertion writer is constructed directly by
``exulanica.identity`` on connections that never see a repository, and this class is the whole of
what makes a spine module safe to call. What is false is the idea that either one is *load
bearing for the other*, and the rule this package actually holds is structural, not behavioural:
see the package docstring.
"""

from __future__ import annotations

import uuid

import psycopg
from psycopg.rows import dict_row

from exulanica.db.session import set_workspace

__all__ = ["WorkspaceScope"]


class WorkspaceScope:
    """A live connection, the workspace it has declared, and nothing else.

    Not a dataclass. Constructing one has two effects on the connection it is handed, and a
    generated ``__init__`` would hide both: the row factory becomes ``dict_row``, because every
    query in this package selects by name, and the workspace is declared for the rest of the
    session.
    """

    __slots__ = ("connection", "workspace_id")

    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        connection.row_factory = dict_row
        set_workspace(connection, workspace_id)
        self.connection = connection
        self.workspace_id = workspace_id
