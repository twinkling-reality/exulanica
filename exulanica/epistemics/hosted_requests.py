"""The account holder's rules for what a hosted request may carry, for one workspace.

:class:`WorkspaceRequestPolicy` is the policy :mod:`exulanica.models.policy` describes, for the
requests of one workspace. The code that knows the workspace attaches it with
:meth:`~exulanica.models.client.ModelClient.with_policy`: the API for the request it serves
(``Services.hosted_model``), the caption pass for the capture it indexes, the vision stage for the
photograph it sends, the society runtime for the decision it asks for. It judges each request as
the request is about to leave:

*   **A person's name never goes**, with or without a right, and neither does a voice's, an
    object's, an event's or a conversation's: no right releases those.
*   **A confirmed place's name goes only where a right releases it** for this request's
    hand-over, meaning every model the role's chain can reach at its destination. The resolver
    that reads the place-name right is injected, because the right is kept above this layer. It
    is asked once per hand-over for the life of the policy, and only for a request that carries a
    saved place's name.
*   **A photograph's bytes and the text derived from it go only under a current personal model
    right** naming every model of the hand-over, for every photograph the request declares or the
    policy is scoped to, all or nothing. The check is injected for the same reason, and it is the
    product's own (``exulanica.ingest.model_rights.require_model_right``), so a capture screened
    under a synthetic or benchmark authority passes it exactly as it passes everywhere else. A
    request with an image part and no photograph is refused.

Every name that does not go is replaced by a placeholder of its class, the way
:mod:`exulanica.epistemics.saved_names` replaces it, with labels that are consistent within one
request and never reuse a label the request already carries. A caller that sends several requests
about one question passes the placeholders it has already given its entities
(``HostedRequest.placeholders``), and a name withheld here is written as that placeholder, so each
request, and the answer that comes back, names each entity one way. Each placeholder must be one
of its entity's own class, and no two entities may share one. Labels this policy gives itself are
not kept from one request to the next.

**What this does not do.** It never rewrites a system message: those are product instructions,
and ``tests/test_hosted_boundary.py`` asserts that no saved name is in any of them on every hosted
call path. It cannot recognise a name the account holder has not saved. And it cannot undo a
replacement a caller made before the request reached it: the Companion's call sites replace every
saved name no right can release and leave a place's to this policy, so a place right is honoured by
every request of a role it names.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager

import psycopg

from exulanica.epistemics.saved_names import PLACEHOLDER, SavedName, redact_names, saved_names
from exulanica.errors import PrivacyAdmissionError
from exulanica.models.handoff import ModelHandoff
from exulanica.models.policy import HostedRequest, HostedRequestRefused

__all__ = [
    "PLACE",
    "PhotographRight",
    "ReleasedPlaces",
    "WorkspaceRequestPolicy",
    "borrowing",
    "no_place_released",
]

#: The one class whose saved names a right can release: the account holder's rule is "places
#: only, if I allow it".
PLACE = "place"

#: Raises :class:`~exulanica.errors.PrivacyAdmissionError` unless every photograph may reach every
#: model of the hand-over. Called with the policy's connection, idle, and the workspace.
PhotographRight = Callable[
    [psycopg.Connection, uuid.UUID, frozenset[uuid.UUID], ModelHandoff], None
]

#: Every place whose confirmed name may go to the hand-over, read on the policy's idle connection.
#: The place-name right's resolver has this shape (``released_place_names``).
ReleasedPlaces = Callable[[psycopg.Connection, uuid.UUID, ModelHandoff], frozenset[uuid.UUID]]


def no_place_released(
    connection: psycopg.Connection, workspace_id: uuid.UUID, handoff: ModelHandoff
) -> frozenset[uuid.UUID]:
    """The resolver where no place-name right is read: every place's name is withheld."""
    return frozenset()


def borrowing(
    connection: psycopg.Connection,
) -> Callable[[], AbstractContextManager[psycopg.Connection]]:
    """Lend the policy a connection its caller already holds, idle, for as long as it needs one."""

    @contextmanager
    def lend() -> Iterator[psycopg.Connection]:
        yield connection

    return lend


class WorkspaceRequestPolicy:
    """The account holder's rules, applied to each hosted request one workspace sends.

    ``connection`` opens (or lends) an idle connection scoped to ``workspace_id`` for the length
    of one judgement; the right check and the resolver each take their own read-only transaction
    on it, and nothing is held while the model runs. ``photographs`` scopes the policy to
    captures every request it admits is treated as carrying, for a client that sends a
    photograph whose caller does not name it on the request.
    """

    def __init__(
        self,
        workspace_id: uuid.UUID,
        *,
        connection: Callable[[], AbstractContextManager[psycopg.Connection]],
        photograph_right: PhotographRight,
        released_places: ReleasedPlaces,
        photographs: Iterable[uuid.UUID] = (),
    ) -> None:
        if not isinstance(workspace_id, uuid.UUID):
            raise TypeError("a workspace policy names its workspace by id")
        if not callable(connection) or not callable(photograph_right):
            raise TypeError("a workspace policy needs a connection and a photograph right check")
        if not callable(released_places):
            raise TypeError("a workspace policy needs a place-name resolver")
        self._workspace_id = workspace_id
        self._connection = connection
        self._photograph_right = photograph_right
        self._released_places = released_places
        self._photographs = frozenset(photographs)
        if not all(isinstance(capture, uuid.UUID) for capture in self._photographs):
            raise TypeError("a workspace policy is scoped to photographs by capture id")
        self._released: dict[ModelHandoff, frozenset[uuid.UUID]] = {}

    @property
    def workspace_id(self) -> uuid.UUID:
        return self._workspace_id

    def admit(self, request: HostedRequest) -> tuple[str, ...]:
        photographs = request.photographs | self._photographs
        if request.images and not photographs:
            raise HostedRequestRefused(
                f"a request to the {request.role} role carries {request.images} image(s) and "
                "names no photograph, so no right can be checked for them"
            )
        with self._connection() as connection:
            if photographs:
                try:
                    self._photograph_right(
                        connection, self._workspace_id, photographs, request.handoff
                    )
                except PrivacyAdmissionError as refusal:
                    raise HostedRequestRefused(
                        f"nothing derived from {len(photographs)} photograph(s) goes to the "
                        f"{request.role} role: {refusal}"
                    ) from refusal
            names = saved_names(connection, self._workspace_id)
            withheld = self._withheld(connection, names, request)
        # A label anywhere in the request, its instructions included, is never handed to another
        # entity: the reader of the request would take the two for one. Nor is one the caller's
        # record gives an entity this workspace no longer names.
        reserved = frozenset(
            label
            for text in (*request.instructions, *request.texts)
            for label in PLACEHOLDER.findall(text)
        ) | frozenset(request.placeholders.values())
        placeholders: Mapping[uuid.UUID, str] = _callers_placeholders(request, names)
        admitted: list[str] = []
        for text in request.texts:
            redacted = redact_names(text, withheld, placeholders, reserved=reserved)
            placeholders = redacted.placeholders
            admitted.append(redacted.text)
        return tuple(admitted)

    def _withheld(
        self,
        connection: psycopg.Connection,
        names: tuple[SavedName, ...],
        request: HostedRequest,
    ) -> tuple[SavedName, ...]:
        """Every saved name this request may not carry: all of them but a released place's."""
        places = tuple(name for name in names if name.entity_class == PLACE)
        carried = {
            entity for text in request.texts for entity in redact_names(text, places).placeholders
        }
        if not carried:
            return names
        released = self._released_for(connection, request.handoff)
        return tuple(
            name
            for name in names
            if not (name.entity_class == PLACE and name.entity_id in released)
        )

    def _released_for(
        self, connection: psycopg.Connection, handoff: ModelHandoff
    ) -> frozenset[uuid.UUID]:
        if handoff not in self._released:
            released = self._released_places(connection, self._workspace_id, handoff)
            if not isinstance(released, frozenset) or not all(
                isinstance(entity, uuid.UUID) for entity in released
            ):
                raise TypeError("a place-name resolver answers with a frozenset of entity ids")
            self._released[handoff] = released
        return self._released[handoff]


def _callers_placeholders(
    request: HostedRequest, names: tuple[SavedName, ...]
) -> dict[uuid.UUID, str]:
    """The caller's placeholders for the entities this workspace names, checked.

    Each is a placeholder of its own entity's class, and no two entities share one: a reader of
    the request would take them for one entity. An entry for an entity with no saved name here is
    left out, since nothing of it can be withheld, and its label stays reserved.
    """
    labels = list(request.placeholders.values())
    if len(set(labels)) != len(labels):
        raise HostedRequestRefused("the request's placeholders give two entities one label")
    classes = {name.entity_id: name.entity_class for name in names}
    record: dict[uuid.UUID, str] = {}
    # The refusals never quote a label: one that is not a placeholder may be a name.
    for entity, label in request.placeholders.items():
        if PLACEHOLDER.fullmatch(label) is None:
            raise HostedRequestRefused(
                "the request's placeholders give an entity something that is not a placeholder"
            )
        if entity not in classes:
            continue
        if label[1:].split(" ", 1)[0] != classes[entity]:
            raise HostedRequestRefused(
                f"the request's placeholders give a {classes[entity]} another class's placeholder"
            )
        record[entity] = label
    return record
