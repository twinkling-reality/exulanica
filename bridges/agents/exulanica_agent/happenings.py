"""What happened to the things an agent decides for, in words its mind can read.

The door reports what became of each turn (``outcome``: the status and reason the world's host
recorded) and every change to the agent's permission (``grant``, ``grant_ended``). Each becomes a
:class:`Happening` with plain words. A reason this library does not know is kept by its code, so a
newer door never makes a happening disappear.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "REASON_WORDS",
    "Happening",
    "from_ended",
    "from_grant",
    "from_outcome",
    "permission_summary",
]

#: Why a turn was not taken, as the world's host records it, in plain words.
REASON_WORDS: Final = {
    "no_answer_in_time": "no answer came in time, so the world's own routine decided",
    "decider_disconnected": "you were not connected, so the world's own routine decided",
    "grant_revoked": "your permission had been ended, so the world's own routine decided",
    "grant_expired": "your permission had run out, so the world's own routine decided",
    "answer_not_offered": "the answer was not one of the offered actions",
    "line_refused_by_rules": "the line was not said, because the world's rules would change it",
    "line_out_of_bounds": "the line was not said: a line is one line, as long as its action allows",
    "line_missing": "the action says something, but no line came with it",
}
_ENDED_WORDS: Final = {
    "revoked": "the world's owner ended it",
    "expired": "it ran out",
}


@dataclass(frozen=True, slots=True)
class Happening:
    """One thing that happened, with the words a mind reads and what it was about."""

    what: str
    words: str
    minute: int | None = None
    thing: str | None = None
    line: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {"what": self.what, "words": self.words}
        for key in ("minute", "thing", "line", "reason"):
            value = getattr(self, key)
            if value is not None:
                document[key] = value
        return document


def from_outcome(
    frame: Mapping[str, Any],
    *,
    minute: int | None,
    thing: str | None,
    answered: tuple[str, str | None] | None,
) -> Happening:
    """What the host recorded for one turn: taken, or not and why. ``answered`` is the action and
    line this agent gave, or None when it gave none."""
    status = frame.get("status")
    reason = frame.get("reason") if isinstance(frame.get("reason"), str) else None
    when = "" if minute is None else f"Minute {minute}: "
    if status == "accepted":
        action, line = answered if answered is not None else (None, None)
        said = "" if line is None else f' and said "{line}"'
        chose = "" if action is None else f": {action}"
        return Happening(
            "answer_taken",
            f"{when}your answer was taken{chose}{said}.",
            minute=minute,
            thing=thing,
            line=line,
            reason=reason,
        )
    if status == "stale":
        why = "the world had moved on before the answer counted"
    elif reason in REASON_WORDS:
        why = REASON_WORDS[reason]
    else:
        why = f"it was not taken ({reason or status})"
    return Happening(
        "answer_not_taken",
        f"{when}{why}.",
        minute=minute,
        thing=thing,
        line=None if answered is None else answered[1],
        reason=reason or (status if isinstance(status, str) else None),
    )


def permission_summary(scope: Mapping[str, Any], expires_at: str | None) -> dict[str, Any]:
    """The parts of a grant an agent acts on: the things it decides for, how many bodies of its
    own it may bring, whether they may speak, and when the permission ends."""
    things = scope.get("things")
    return {
        "things": [str(thing) for thing in things] if isinstance(things, list) else [],
        "visitors_maximum": int(scope.get("visitors_maximum") or 0),
        "may_speak": bool(scope.get("may_speak", False)),
        "ends_at": expires_at,
        "ended": None,
    }


def from_grant(scope: Mapping[str, Any], expires_at: str | None) -> Happening:
    summary = permission_summary(scope, expires_at)
    count = len(summary["things"])
    parts = []
    if count:
        parts.append(f"you decide for {count} of this world's things")
    if summary["visitors_maximum"]:
        parts.append(f"you may bring in {summary['visitors_maximum']} body of your own")
    parts.append("your things may speak" if summary["may_speak"] else "your things may not speak")
    if expires_at:
        parts.append(f"until {expires_at}")
    return Happening("permission_changed", "Your permission: " + ", ".join(parts) + ".")


def from_ended(frame: Mapping[str, Any]) -> Happening:
    reason = frame.get("reason") if isinstance(frame.get("reason"), str) else None
    why = _ENDED_WORDS.get(reason or "", "it ended")
    return Happening(
        "permission_ended",
        f"Your permission in this world has ended: {why}. The world's own routine decides now.",
        reason=reason,
    )
