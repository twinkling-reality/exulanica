"""Subject identity: one uuid5 rule for every generated subject a person can point at.

    identity = uuid5(SUBJECT_NAMESPACE, canonical_json([
        "exulanica.grammar.subject/v1", grammar_id, root_identity,
        subject_kind, owner_identity, ordinal,
    ]))

``root_identity`` is the admitted identity of the subject a generation was run for, which the
contract hands every stage as ``StageContext.subject_identity``. ``owner_identity`` is the
subject this one belongs to, and the root owns the top of the tree. ``ordinal`` is the subject's
place among its owner's subjects of the same kind.

**What is deliberately not in the tuple.** Neither the seed nor the grammar version. An identity
must survive regeneration: a reseed changes every generated value and keeps every identity, and
a grammar version bump keeps them too. So a grammar version that assigns ``(kind, owner,
ordinal)`` to different subjects than its predecessor did must say so in its parameter
migration, whose identity policy is ``preserved``, ``rekeyed`` or ``introduced``
(:mod:`exulanica.grammar.migration`). What a pinned subject keeps across a reseed is decided by
whoever owns the edit log, not here.

**Why canonical JSON.** A delimited string is not injective once a part may contain the
delimiter; a canonical JSON array is, and it is the one serialisation every digest here already
trusts.

The namespace is itself a uuid5, of a fixed URL under the reserved ``.invalid`` domain, so its
value is reproducible from this docstring and is pinned by a test.
"""

from __future__ import annotations

import uuid
from typing import Final

from exulanica.canonical import canonical_json
from exulanica.grammar.records import (
    MAX_SAFE_INTEGER,
    require_identity,
    require_integer,
    require_key,
)

__all__ = ["SUBJECT_NAMESPACE", "SUBJECT_RULE", "subject_identity"]

SUBJECT_RULE: Final = "exulanica.grammar.subject/v1"
SUBJECT_NAMESPACE: Final = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://exulanica.invalid/grammar/subject"
)


def subject_identity(
    *,
    grammar_id: str,
    root_identity: str,
    subject_kind: str,
    owner_identity: str,
    ordinal: int,
) -> str:
    """The canonical lowercase UUID of one generated subject. Pure; refuses malformed parts."""
    require_key("grammar_id", grammar_id)
    require_identity("root_identity", root_identity)
    require_key("subject_kind", subject_kind)
    require_identity("owner_identity", owner_identity)
    require_integer("ordinal", ordinal, minimum=0, maximum=MAX_SAFE_INTEGER)
    name = canonical_json(
        [SUBJECT_RULE, grammar_id, root_identity, subject_kind, owner_identity, ordinal]
    ).decode("utf-8")
    return str(uuid.uuid5(SUBJECT_NAMESPACE, name))
