"""Which workspace is this, on which connection, and which vocabulary answers the question?

The transactional operations live in :mod:`exulanica.identity.decisions`. This is rows: it knows how
an entity, a link, a rejection and an event are stored, and it knows nothing about what sequence
of them constitutes a merge.

This module holds three things of its own, and this class has no query in it. Every read and
write lives in the module named for the question its table answers, and the repository exposes
each as an attribute, so a call site says which table group it is touching before it says what it
is doing:

*   :mod:`exulanica.identity.occurrences` as ``occurrences``: which detection is this, and which
    detections is this person confirmed to be?
*   :mod:`exulanica.identity.entities` as ``entities``: what is one person record, and which record
    represents it now?
*   :mod:`exulanica.identity.links` as ``links``: what has been decided about this detection, in
    what state, and by whom?
*   :mod:`exulanica.identity.rejections` as ``rejections``: has this pair, on this basis, already
    been refused, and what is new about the one being asked now?
*   :mod:`exulanica.identity.never_same` as ``never_same``: were these two records pulled apart by a
    person, so that a merge of them must be refused?
*   :mod:`exulanica.identity.proposals` as ``proposals``: what did the producer ask, and which of
    those questions is still waiting for an answer?
*   :mod:`exulanica.identity.events` as ``events``: what was decided, in what order, and does the
    record say enough to undo it?
*   :mod:`exulanica.identity.recomputation` as ``recomputation``: what must be recomputed because of
    this decision?

**The collaborators take the repository rather than a connection and a workspace id.** That is
what keeps the scoping structural rather than remembered. ``Entities(connection, workspace)`` is
not a constructible thing; ``Entities(repository)`` is, and the repository is the only object in
this package that calls :func:`exulanica.db.session.set_workspace`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from exulanica.db.session import set_workspace
from exulanica.identity.entities import Entities
from exulanica.identity.events import Events
from exulanica.identity.links import Links
from exulanica.identity.never_same import NeverSamePairs
from exulanica.identity.occurrences import Occurrences
from exulanica.identity.proposals import Proposals
from exulanica.identity.recomputation import Recomputation
from exulanica.identity.rejections import Rejections

__all__ = ["IdentityRepository"]


class IdentityRepository:
    """One workspace, one connection, and the eight vocabularies over the identity tables."""

    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        self._db = connection
        self._db.row_factory = dict_row
        self.workspace_id = workspace_id
        # Same reason as IngestRepository: the guards assert the session's workspace matches the
        # row being written, and row-level security makes an unscoped connection see an empty
        # database rather than raise.
        set_workspace(connection, workspace_id)

        self.occurrences = Occurrences(self)
        self.entities = Entities(self)
        self.links = Links(self)
        self.rejections = Rejections(self)
        self.never_same = NeverSamePairs(self)
        self.proposals = Proposals(self)
        self.events = Events(self)
        self.recomputation = Recomputation(self)

    @property
    def connection(self) -> psycopg.Connection:
        return self._db

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        """One decision lands together or not at all.

        Not a convenience. A merge that half-applied would leave entities pointing at a target
        that no event records, and the ledger would no longer describe the state.
        """
        with self._db.transaction():
            self.recomputation.serialize()
            yield self._db
