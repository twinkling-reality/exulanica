"""No name the account holder saved goes to a hosted model; each is replaced before sending.

A name exists in this product only because the account holder typed it as an annotation: who a
person is, what a place is called, what an object is. The account holder's rules are that a
person's name never goes to a hosted model, with or without a right, and that a confirmed place's
name goes only under a right the account holder grants for that place and that model. Every other
saved name is found and replaced locally, by this module, in two places: the Companion's own
requests, which replace every saved name no right can release and leave a place's to the boundary,
and the boundary every hosted request passes (:mod:`exulanica.epistemics.hosted_requests`), which
leaves a place's name only where a right releases it for that request's models:

*   **The names to look for** are every name the account holder has saved for any entity. Deleted
    and merged records are included, because a name the account holder once typed is still theirs.
*   **A saved name is recognised** whole, case-insensitively and only as a whole word. A person's
    or a voice's name is also recognised by any part of at least three letters, because people are
    named by first name: "Maria Estrada" is recognised as "Maria Estrada", "Maria" or "Estrada".
    Other names are recognised whole only, because their parts are ordinary words: a saved
    "Lantern House" must not turn "photos of the house" into a filter on one particular place.
*   **Each recognised entity gets a placeholder** of its class, ``[person A]``, ``[place A]``,
    ``[object A]``, stable for the whole request, so the planner can be told which catalogue id a
    placeholder is and the composer refers to the same entity the same way. The browser restores
    the name from the account holder's own data. Letters only, because answer text may not carry
    a digit that no value reference covers.

What this cannot do, stated rather than hidden: a name the account holder has not saved cannot be
recognised, so it leaves as the text it was typed as; and a saved name that is also an ordinary
word is replaced wherever that word appears, which for a person includes each part of their name:
somebody saved as Rose makes "the rose garden" arrive as "the [person A] garden".
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import psycopg

__all__ = [
    "PLACEHOLDER",
    "Redacted",
    "SavedName",
    "recognised_spans",
    "redact_names",
    "saved_names",
]

#: The shortest part of a person's saved name that is recognised on its own. Shorter parts ("Li",
#: "de", "al") are ordinary words far more often than they are anyone's whole reference to a person.
MIN_PART_LETTERS = 3

#: The classes whose names are recognised by their parts as well as whole.
_BY_PART = frozenset({"person", "voice"})

_CLASSES = ("person", "voice", "place", "object", "conversation", "event")

#: A placeholder of any class, captured whole so ``split`` keeps it as one piece.
PLACEHOLDER = re.compile(r"(\[(?:" + "|".join(_CLASSES) + r") [A-Z]+\])")


@dataclass(frozen=True, slots=True)
class SavedName:
    entity_id: uuid.UUID
    entity_class: str
    name: str


@dataclass(frozen=True, slots=True)
class Redacted:
    """Text with every recognised saved name replaced, and which entity each placeholder is."""

    text: str
    #: entity id -> placeholder, in the order the entities were first recognised.
    placeholders: Mapping[uuid.UUID, str] = field(default_factory=dict)


def saved_names(connection: psycopg.Connection, workspace_id: uuid.UUID) -> tuple[SavedName, ...]:
    """Every name the account holder has saved for any entity, live or not."""
    rows = connection.execute(
        "select entity_id, class, display_name from entity "
        "where workspace_id=%s and display_name is not null order by entity_id",
        (workspace_id,),
    ).fetchall()
    return tuple(
        SavedName(row["entity_id"], str(row["class"]), row["display_name"]) for row in rows
    )


def _label(entity_class: str, index: int) -> str:
    """``[place A]`` for 0, ``[place Z]`` for 25, ``[place AA]`` for 26."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return f"[{entity_class} {letters}]"


def _patterns(names: Iterable[SavedName]) -> list[tuple[re.Pattern[str], SavedName]]:
    """One pattern per recognisable form of each name, longest first so whole names win.

    A form a JSON string would spell differently, one with a quotation mark or a backslash in it,
    is also recognised as JSON spells it, the way canonical JSON writes it (non-ASCII kept as
    itself), because a request can carry a JSON document as text.
    """
    forms: list[tuple[str, SavedName]] = []
    for saved in names:
        whole = " ".join(saved.name.split())
        if not whole:
            continue
        forms.append((whole, saved))
        if saved.entity_class in _BY_PART:
            for part in whole.split(" "):
                if len(re.sub(r"[^\w]", "", part)) >= MIN_PART_LETTERS and part != whole:
                    forms.append((part, saved))
    forms.extend(
        (spelled, saved)
        for form, saved in list(forms)
        if (spelled := json.dumps(form, ensure_ascii=False)[1:-1]) != form
    )
    forms.sort(key=lambda form: len(form[0]), reverse=True)
    return [
        (
            re.compile(
                r"(?<!\w)" + r"\s+".join(re.escape(word) for word in form.split(" ")) + r"(?!\w)",
                re.IGNORECASE,
            ),
            saved,
        )
        for form, saved in forms
    ]


def recognised_spans(text: str, names: Iterable[SavedName]) -> list[tuple[int, int, SavedName]]:
    """Where in ``text`` a saved name is recognised, as :func:`redact_names` would recognise it,
    and whose it is.

    The same patterns in the same order, longest first, each span kept only where no longer one
    and no placeholder already in the text covers it. For a caller that must leave a saved name's
    own words as they are while it rewrites the rest of a text, such as the Companion writing a
    simulated person's name as a placeholder (``exulanica/selection/society_question.py``).
    """
    taken = [(match.start(), match.end()) for match in PLACEHOLDER.finditer(text)]
    found: list[tuple[int, int, SavedName]] = []
    for pattern, saved in _patterns(names):
        for match in pattern.finditer(text):
            start, end = match.start(), match.end()
            held = (*taken, *((a, b) for a, b, _ in found))
            if all(end <= a or start >= b for a, b in held):
                found.append((start, end, saved))
    return sorted(found, key=lambda span: span[:2])


def redact_names(
    text: str,
    names: Iterable[SavedName],
    placeholders: Mapping[uuid.UUID, str] | None = None,
    *,
    reserved: Iterable[str] = (),
) -> Redacted:
    """Replace every recognised saved name in ``text``.

    ``placeholders`` continues an earlier redaction, so an entity recognised in the question keeps
    the same placeholder when recognised again in a packet. ``reserved`` names labels that are
    never handed out here, because another part of the same request already carries them for an
    entity this call cannot know.
    """
    assigned: dict[uuid.UUID, str] = dict(placeholders or {})
    # Split around placeholders already in the text, so a short saved name can never match inside
    # one. Even positions are text and odd positions are placeholders; the list is rebuilt after
    # every pattern so the next one sees the placeholders this one inserted.
    pieces = PLACEHOLDER.split(text)
    # A label already present, typed or left by an earlier pass, is never handed to anything else.
    taken = set(assigned.values()) | set(pieces[1::2]) | set(reserved)
    for pattern, saved in _patterns(names):
        rebuilt: list[str] = []
        for position, piece in enumerate(pieces):
            if position % 2 or not pattern.search(piece):
                rebuilt.append(piece)
                continue
            if saved.entity_id not in assigned:
                label = next(
                    _label(saved.entity_class, n)
                    for n in range(len(taken) + 1)
                    if _label(saved.entity_class, n) not in taken
                )
                assigned[saved.entity_id] = label
                taken.add(label)
            rebuilt.append(pattern.sub(assigned[saved.entity_id], piece))
        pieces = PLACEHOLDER.split("".join(rebuilt))
    return Redacted(text="".join(pieces), placeholders=assigned)
