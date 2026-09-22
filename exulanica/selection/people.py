"""People's names never go to a hosted model. They are replaced before anything is sent.

The account holder's rule is absolute: a person's name, which in this product exists only because
the account holder typed it as an annotation, is never sent to a hosted model, with or without a
right. The Companion used to send every named entity to the planner by name, and the question as
typed to the planner, the composer and the request classifier.

So a name is found and replaced locally, before a request is built:

*   **The names to look for** are every name the account holder has saved for a person, and only
    those: an entity of class ``person`` or ``voice`` that carries a name. Deleted and merged
    records are included, because a name the account holder once typed is still a person's name.
*   **A saved name is recognised** whole, or by any part of it at least three letters long,
    case-insensitively and only as a whole word. "Maria Estrada" is recognised as "Maria Estrada",
    "Maria" or "Estrada".
*   **Each recognised person gets a placeholder**, ``[person A]``, ``[person B]`` and so on,
    stable for the whole request, so the planner can be told which catalogue id "[person A]" is
    and the composer can refer to the same person the same way. The browser substitutes the name
    back from the account holder's own data. Letters only, because answer text may not carry a
    digit a value reference does not cover.

What this cannot do, stated rather than hidden: a name the account holder has not saved cannot be
recognised as a person's name, so it leaves as the text it was typed as. And a saved name that is
also an ordinary word is replaced wherever that word appears, which can make a question harder to
understand; that is the rule's cost, paid in the direction the rule chose.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import psycopg

__all__ = ["PersonName", "Redacted", "placeholder_for", "redact_people", "saved_person_names"]

#: The shortest part of a saved name that is recognised on its own. Shorter parts ("Li", "de",
#: "al") are ordinary words far more often than they are anyone's whole reference to a person.
MIN_PART_LETTERS = 3

#: A placeholder already in the text, kept whole by ``split`` because the group is captured.
_PLACEHOLDER = re.compile(r"(\[person [A-Z]+\])")


@dataclass(frozen=True, slots=True)
class PersonName:
    entity_id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True)
class Redacted:
    """Text with every recognised saved person name replaced, and who each placeholder is."""

    text: str
    #: entity id -> placeholder, in the order the people were first recognised.
    placeholders: Mapping[uuid.UUID, str] = field(default_factory=dict)


def saved_person_names(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> tuple[PersonName, ...]:
    """Every name the account holder has saved for a person, live or not."""
    rows = connection.execute(
        "select entity_id, display_name from entity "
        "where workspace_id=%s and class in ('person','voice') and display_name is not null "
        "order by entity_id",
        (workspace_id,),
    ).fetchall()
    return tuple(PersonName(row["entity_id"], row["display_name"]) for row in rows)


def placeholder_for(index: int) -> str:
    """``[person A]`` for 0, ``[person Z]`` for 25, ``[person AA]`` for 26."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return f"[person {letters}]"


def _patterns(people: Iterable[PersonName]) -> list[tuple[re.Pattern[str], uuid.UUID]]:
    """One pattern per recognisable form of each name, longest first so whole names win."""
    forms: list[tuple[str, uuid.UUID]] = []
    for person in people:
        whole = " ".join(person.name.split())
        if whole:
            forms.append((whole, person.entity_id))
        for part in whole.split(" "):
            if len(re.sub(r"[^\w]", "", part)) >= MIN_PART_LETTERS and part != whole:
                forms.append((part, person.entity_id))
    forms.sort(key=lambda form: len(form[0]), reverse=True)
    return [
        (
            re.compile(
                r"(?<!\w)" + r"\s+".join(re.escape(word) for word in form.split(" ")) + r"(?!\w)",
                re.IGNORECASE,
            ),
            entity_id,
        )
        for form, entity_id in forms
    ]


def redact_people(
    text: str,
    people: Iterable[PersonName],
    placeholders: Mapping[uuid.UUID, str] | None = None,
) -> Redacted:
    """Replace every recognised saved person name in ``text``.

    ``placeholders`` continues an earlier redaction, so a person recognised in the question keeps
    the same placeholder when recognised again in a packet.
    """
    assigned: dict[uuid.UUID, str] = dict(placeholders or {})
    # Split around placeholders already in the text, so a short saved name can never match inside
    # one ("[person A]" must not become "[person [person B]]" for somebody saved as "A"). Even
    # positions are text, odd positions are placeholders, and the list is rebuilt after every
    # pattern so the next one sees the placeholders this one inserted.
    pieces = _PLACEHOLDER.split(text)
    # A label already in the text, typed or left by an earlier pass, is never handed to anybody
    # else, or two people would read the same.
    taken = set(assigned.values()) | set(pieces[1::2])
    for pattern, entity_id in _patterns(people):
        rebuilt: list[str] = []
        for position, piece in enumerate(pieces):
            if position % 2 or not pattern.search(piece):
                rebuilt.append(piece)
                continue
            if entity_id not in assigned:
                label = next(
                    placeholder_for(n)
                    for n in range(len(taken) + 1)
                    if placeholder_for(n) not in taken
                )
                assigned[entity_id] = label
                taken.add(label)
            rebuilt.append(pattern.sub(assigned[entity_id], piece))
        pieces = _PLACEHOLDER.split("".join(rebuilt))
    return Redacted(text="".join(pieces), placeholders=assigned)
