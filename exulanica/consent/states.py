"""What a person has agreed to, resolved from receipts and from nothing else.

**Absence of a decision is not consent.** There is no default argument anywhere in this module
that grants anything. An empty receipt log resolves to ``unknown``, ``unknown`` is masked, and a
caller cannot ask for a different starting point. That is the whole of default deny, and it is
here rather than at each call site so that a new caller inherits it instead of remembering it.

**Three consents, and they are genuinely separate.** Presence says a person was here. Naming says
this person is Julie. Likeness says show this person's appearance. Granting one grants nothing
else: a person may be present and named for years while never being visible, which is the case
the old yes-or-no gate could not express and the reason this module exists.

**The reversible state is the only one that is viewer-side.** ``hidden`` means a person who did
consent to likeness is not being shown at the moment, so their pixels are legitimately in the
derivative and in the geometry and the renderer declines to draw them. Every other hidden state
masks the source before reconstruction reads it, because a person who never consented must never
have become depth, points or Gaussians in the first place. :data:`MASKED_STATES` is what the
masking stage reads and the difference is load bearing: confusing the two would either rebuild
the world every time somebody toggled a switch, or leave an unconsented body in the geometry.

**Withdrawal is not a fourth consent.** It arrives from the existing tombstone and purge path and
is passed in, rather than being a scope somebody could grant back by writing another receipt. A
withdrawal reaches forward; a consent receipt written afterwards does not undo it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Final, Literal

__all__ = [
    "CONSENT_SCOPES",
    "MASKED_STATES",
    "ConsentScope",
    "ConsentTransition",
    "PersonState",
    "ResolvedPresentation",
    "resolve_presentation",
]

#: The five states from the design note, in the order least to most revealed. ``withdrawn`` is
#: last rather than first because it is not a degree of revelation at all; see the module
#: docstring.
PersonState = Literal["unknown", "present", "shown", "hidden", "withdrawn"]

#: What a receipt may grant or revoke. ``temporary_hide`` is in this vocabulary because it is a
#: recorded, reversible decision with an actor and a time like any other, not a UI preference.
ConsentScope = Literal["presence", "naming", "likeness", "temporary_hide"]

CONSENT_SCOPES: Final[frozenset[str]] = frozenset(
    {"presence", "naming", "likeness", "temporary_hide"}
)

#: The states whose source derivative is masked before reconstruction reads it. ``hidden`` is
#: deliberately absent: that person consented to their likeness and their geometry is theirs.
MASKED_STATES: Final[frozenset[str]] = frozenset({"unknown", "present", "withdrawn"})


@dataclass(frozen=True, slots=True)
class ConsentTransition:
    """One immutable decision: who, when, which scope, and whether it was given or taken back.

    ``receipt_digest`` is carried so that two decisions recorded at the same instant resolve in
    one order on every machine. Without it a package written on one host and replayed on another
    could disagree about which of two same-second receipts won, and the disagreement would be a
    person visible in one reading and not the other.
    """

    scope: ConsentScope
    granted: bool
    actor: str
    decided_at: dt.datetime
    receipt_digest: bytes

    def __post_init__(self) -> None:
        if self.scope not in CONSENT_SCOPES:
            raise ValueError(f"{self.scope!r} is not one of {sorted(CONSENT_SCOPES)}")
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            raise ValueError("a consent receipt time must carry a UTC offset")
        if len(self.receipt_digest) != 32:
            raise ValueError("a consent receipt digest is 32 bytes")


@dataclass(frozen=True, slots=True)
class ResolvedPresentation:
    """A person's current state, and whether their name may be drawn beside it.

    ``name_permitted`` is separate from ``state`` because naming and likeness are separate
    consents: a silhouette with a name over it is exactly what "present and named but not shown"
    looks like, and collapsing the two would make that unrepresentable.
    """

    state: PersonState
    name_permitted: bool

    @property
    def masked(self) -> bool:
        """Whether the source derivative must hide this person before reconstruction reads it."""
        return self.state in MASKED_STATES

    @property
    def drawn(self) -> bool:
        """Whether a renderer may draw this person's pixels. Only ever true for ``shown``."""
        return self.state == "shown"


def resolve_presentation(
    transitions: tuple[ConsentTransition, ...], *, withdrawn: bool = False
) -> ResolvedPresentation:
    """Fold every receipt for one person into the one state that holds now.

    Receipts are applied oldest first, ties broken by receipt digest, so the result is a function
    of the set rather than of the order a caller happened to read them in. A verifier reading the
    same receipts out of a World Memory Package reaches the same state without a database.

    ``withdrawn`` short circuits everything, including a later grant. That is the point of a
    withdrawal reaching forward: somebody who has taken their consent back does not have it
    restored by the next receipt somebody else writes.
    """
    if withdrawn:
        return ResolvedPresentation(state="withdrawn", name_permitted=False)
    held = {scope: False for scope in CONSENT_SCOPES}
    for transition in sorted(transitions, key=lambda item: (item.decided_at, item.receipt_digest)):
        held[transition.scope] = transition.granted
    if held["likeness"]:
        state: PersonState = "hidden" if held["temporary_hide"] else "shown"
    elif held["presence"]:
        state = "present"
    else:
        state = "unknown"
    return ResolvedPresentation(state=state, name_permitted=held["naming"])
