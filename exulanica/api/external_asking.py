"""The port an outside program's door implements, so the decision host can ask it.

An outside program, such as a game's bridge, decides for a subject under a grant the world's owner
issued (:mod:`exulanica.world.deciders`). The decision host asks it as it asks a chosen model,
before a society's minute, through an :class:`ExternalAsker` the application registers: the host
never imports a door, and a host with none registered asks no outside program and writes nothing
for its subjects, so the routine decides for them, as a host with no model client asks no model.

Asking takes two steps, the shape every model ask has too. :meth:`ExternalAsker.configuration` is
called before the host reserves the minute's requests: it states what the request records about
the program as the grant stands now (:data:`~exulanica.world.deciders.EXTERNAL_CONFIG` but the
contract, which the host adds), and a refusal decided before asking, when the door holds no live
connection for the grant or the grant was revoked or has expired. A refused subject still gets its
request, answered at once as ``unavailable`` for that reason, so a world counts the minutes an
outside program was silent from its own records. :meth:`ExternalAsker.answer` is then called from
the host's pool with no connection held, as a model is asked, and returns the result a receipt
records: one offered label or none, and the program's answer in
:data:`~exulanica.world.deciders.EXTERNAL_RECORD`'s fields. The host checks it exactly as it checks
a model's answer, and the minute checks it again.

Both are called from the host's threads, several at once, and the host waits for neither past the
end of its minute's asks: a statement that comes late, raises or is malformed leaves its own
subject unasked that minute, an answer that comes late is recorded as ``no_answer_in_time``, and
one that fails the checks as ``decider_disconnected``. A door returns in time on its own; the host
never waits for one that does not.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Final, Protocol

__all__ = ["REFUSALS_BEFORE_ASKING", "ExternalAsker"]

#: Why an outside program is not asked for a subject this minute, decided before asking: each is
#: recorded on the subject's receipt, and the routine decides that turn.
REFUSALS_BEFORE_ASKING: Final = frozenset(
    {"decider_disconnected", "grant_revoked", "grant_expired"}
)


class ExternalAsker(Protocol):
    """An outside program's door, as the decision host asks it."""

    def configuration(
        self,
        workspace_id: uuid.UUID,
        world_id: str,
        subject_id: str,
        decider: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], str | None]:
        """What the door states about the program the external ``decider`` names, as its grant
        stands now: ``{kind, bridge, grant_id, grant_seq, mapping_sha256, deadline_ms}``, the
        request's record of it but the contract, which the host adds; and why it cannot be asked
        this minute, one of :data:`REFUSALS_BEFORE_ASKING`, or None. ``deadline_ms`` is the door's
        own figure, held by the host within the role contract's deadline. A grant the door holds
        no record of is a fault, raised, not a refusal: a choice naming a grant is recorded in the
        grant's own transaction."""
        ...

    def answer(
        self,
        workspace_id: uuid.UUID,
        world_id: str,
        request: Mapping[str, Any],
        ends_at: float,
    ) -> dict[str, Any]:
        """The program's answer to the sealed ``request`` as a receipt records it,
        ``{status, reason, proposal, provider}``, returned by ``ends_at`` (``time.monotonic``):
        late, it is ``unavailable`` with ``no_answer_in_time``. ``accepted`` names one offered
        label with the program's record in ``provider``; with no answer, ``unavailable`` names one
        of the outside reasons and ``provider`` is None."""
        ...
