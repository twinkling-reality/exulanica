"""Identity: turning scene-local occurrences into people, and only ever with a person's say-so.

The rule this package exists to hold, from ``docs/domain-and-evidence-model.md``: a scene-local
occurrence is not a persistent entity, and promotion between them requires explicit user
confirmation. Model confidence is never user confirmation, and a rejected match is never
re-proposed identically.

Nineteen modules in three groups. Six carry the argument, and the split between the last three of
those is the one worth knowing. Eight more are the tables themselves, one module per table, and
:mod:`exulanica.identity.repository` is the index of them. The remaining five are the producer and
its command line: :mod:`exulanica.identity.proposer` writes questions and organizational
guesses,
:mod:`exulanica.identity.match_context` supplies its confirmed exemplar index,
:mod:`exulanica.identity.signals` is the three context signals it scores a pair on, and
:mod:`exulanica.identity.cli` with :mod:`exulanica.identity.__main__` are how it is run by hand.

The six:

*   :mod:`exulanica.identity.keys` derives the two evidence-shaped keys a decision is recorded
    under, so that rejection memory survives a detector re-run.
*   :mod:`exulanica.identity.repository` is one workspace, one connection, and the eight
    vocabularies over the identity tables. Its docstring says which module answers which
    question; a call site names the vocabulary before it names the method.
*   :mod:`exulanica.identity.subjects` is what every decision shares: what can go wrong, and what a
    subject has to be for a decision to be about it.
*   :mod:`exulanica.identity.decisions` applies one user decision as one transaction, and records
    what it did in ``identity_event`` so that undo is exact rather than approximate.
*   :mod:`exulanica.identity.undo` is the inverse of each of those, in a handler table rather than
    a branch, so an event type nobody wrote an inverse for is refused by name instead of quietly
    doing nothing.
*   :mod:`exulanica.identity.naming` renames an entity, which takes two writes and not one. Read
    its docstring before changing either of them.

**No embedding of any kind is derived here.** Open item P-1, "when may a biometric embedding
exist at all", is a human decision that has not been made, and every candidate rule in
``docs/privacy-consent-threat-model.md`` section 10 is a rule about persisting a template. This
package identifies people from what the account holder says, which needs no template and settles
nothing about P-1.
"""

from exulanica.identity.decisions import (
    confirm_link,
    merge_entities,
    name_occurrence,
    reject_link,
    revoke_link,
    split_entity,
)
from exulanica.identity.entities import EntityRow
from exulanica.identity.keys import (
    REGION_GRID,
    TIME_BUCKET_NS,
    USER_STATEMENT_BASIS,
    basis_digest,
    occurrence_identity_key,
    region_bucket,
)
from exulanica.identity.links import LinkRow
from exulanica.identity.naming import ConcurrentRename, RenamedEntity, rename_entity
from exulanica.identity.occurrences import OccurrenceRow
from exulanica.identity.repository import IdentityRepository
from exulanica.identity.subjects import (
    AlreadyIdentified,
    IdentityError,
    NamedPerson,
    NeverSame,
    NotUndoable,
    UnknownSubject,
)
from exulanica.identity.undo import undo

__all__ = [
    "REGION_GRID",
    "TIME_BUCKET_NS",
    "USER_STATEMENT_BASIS",
    "AlreadyIdentified",
    "ConcurrentRename",
    "EntityRow",
    "IdentityError",
    "IdentityRepository",
    "LinkRow",
    "NamedPerson",
    "NeverSame",
    "NotUndoable",
    "OccurrenceRow",
    "RenamedEntity",
    "UnknownSubject",
    "basis_digest",
    "confirm_link",
    "merge_entities",
    "name_occurrence",
    "occurrence_identity_key",
    "region_bucket",
    "reject_link",
    "rename_entity",
    "revoke_link",
    "split_entity",
    "undo",
]
