"""What one Companion request calls each entity its hosted requests may name.

A name exists in this product only because the account holder typed it. Their rules: a person's
saved name never goes to a hosted model, with or without a right, and neither does a voice's, an
object's, an event's or a conversation's; a confirmed place's name goes only under a right the
account holder grants for that place and that model. The second is decided for each request and
its hand-over where every hosted request passes, by
:class:`~exulanica.epistemics.hosted_requests.WorkspaceRequestPolicy`. The Companion's call sites
decide only the first, with a :class:`RequestNames` made once for the request:

*   **Every saved name is recognised in one pass**, the way
    :func:`~exulanica.epistemics.saved_names.redact_names` recognises it, longest form first, so a
    place saved as "Victoria Station" is read as the place and not as somebody saved as Victoria.
*   **A name no right can release is replaced** by its placeholder. A place's name is written as
    the account holder saved it, for the boundary to send or to withhold.
*   **One record for the whole request.** Each entity keeps one placeholder across the question,
    the planner's catalogue and the packet, and every hosted call hands the record to the boundary,
    so a place it withholds is written with the placeholder the rest of the request uses. The
    answer's ``names`` is this record, which is how the browser puts each name back.
*   **By id where words cannot say which entity.** A place the request refers to by id, the place
    a photograph was confirmed taken at or a place the planner's catalogue names, is written by
    name only where no other saved name would be read as the same words. Otherwise it stays its
    placeholder, withheld on that line even where it is allowed, because the boundary reads words
    and would give the line to the other entity.

What this does not do: a place's name is written back in the spelling the account holder saved,
not the spelling of the text it was found in, so a sign painted in capitals reaches a model that
may receive the name in the saved spelling.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from types import MappingProxyType

import psycopg

from exulanica.epistemics.hosted_requests import PLACE
from exulanica.epistemics.saved_names import PLACEHOLDER, SavedName, redact_names, saved_names

__all__ = ["RequestNames"]


class RequestNames:
    """The saved names one request may meet, and the placeholder it has given each entity."""

    __slots__ = ("_by_entity", "_by_name", "_names", "_placeholders", "_typed")

    def __init__(self, names: Iterable[SavedName]) -> None:
        self._names = tuple(names)
        self._by_entity = {saved.entity_id: saved for saved in self._names}
        #: entity id -> placeholder, in the order the entities were first recognised.
        self._placeholders: dict[uuid.UUID, str] = {}
        #: Labels a text already carried when it reached the request, never handed to an entity.
        self._typed: set[str] = set()
        #: Whether each place asked about may be written by name. Read once per request.
        self._by_name: dict[uuid.UUID, bool] = {}

    @classmethod
    def read(cls, connection: psycopg.Connection, workspace_id: uuid.UUID) -> RequestNames:
        """Every name the account holder has saved in this workspace, and an empty record."""
        return cls(saved_names(connection, workspace_id))

    @property
    def placeholders(self) -> Mapping[uuid.UUID, str]:
        """The record as it stands: each entity recognised so far, and its placeholder."""
        return MappingProxyType(dict(self._placeholders))

    def sendable(self, text: str) -> str:
        """``text`` as a call site may send it: nothing replaced that a right could release.

        A label the text already carries is kept as it is and never given to an entity, and a
        place whose placeholder it carries stays a placeholder here, because the two could not be
        told apart once the name was written back.
        """
        typed = set(PLACEHOLDER.findall(text))
        self._typed |= typed
        redacted = redact_names(text, self._names, self._placeholders, reserved=self._typed)
        self._placeholders = dict(redacted.placeholders)
        sent = redacted.text
        for entity, label in self._placeholders.items():
            if label not in typed and label in sent and self._written_by_name(entity):
                sent = sent.replace(label, self._by_entity[entity].name)
        return sent

    def reference(self, entity_id: uuid.UUID) -> str | None:
        """How the request names one entity it refers to by id, or None if it has no saved name.

        The entity is given its placeholder here if nothing recognised it yet, from its own saved
        name alone, so another entity saved under the same words cannot take its place.
        """
        saved = self._by_entity.get(entity_id)
        if saved is None:
            return None
        if entity_id not in self._placeholders:
            self._placeholders = dict(
                redact_names(
                    saved.name, (saved,), self._placeholders, reserved=self._typed
                ).placeholders
            )
        if self._written_by_name(entity_id):
            return saved.name
        return self._placeholders.get(entity_id)

    def labelled(self, text: str) -> str:
        """``text`` with every entity of the record written as its placeholder, and nothing else.

        For reading what came back: a model given a place's name may copy the name where the
        record would have it copy the placeholder.
        """
        recorded = [self._by_entity[entity] for entity in self._placeholders]
        return redact_names(text, recorded, self._placeholders, reserved=self._typed).text

    def _written_by_name(self, entity_id: uuid.UUID) -> bool:
        """A place no other saved name would be read as: its name, not its placeholder, is sent."""
        saved = self._by_entity.get(entity_id)
        if saved is None or saved.entity_class != PLACE:
            return False
        if entity_id not in self._by_name:
            others = [name for name in self._names if name.entity_id != entity_id]
            read_as = redact_names(saved.name, others).text
            self._by_name[entity_id] = PLACEHOLDER.fullmatch(read_as) is None
        return self._by_name[entity_id]
