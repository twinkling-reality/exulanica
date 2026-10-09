"""What happened to the things an agent decides for, in words its mind can read.

The door reports what became of each turn (``outcome``: the status and reason the world's host
recorded), every change to the agent's permission (``grant``, ``grant_ended``) and, where the door
takes visitors, what the agent's own body met: its arrival or why it could not come in, the lines
it heard (``said``), what it took part in (``happened``) and its leaving (``departed``). Each
becomes a :class:`Happening` with plain words. A reason this library does not know is kept by its
code, so a newer door never makes a happening disappear. What another thing said is quoted, never
an instruction.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "REASON_WORDS",
    "Happening",
    "from_arrival_refused",
    "from_arrived",
    "from_departed",
    "from_ended",
    "from_grant",
    "from_happened",
    "from_outcome",
    "from_said",
    "from_stopped",
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
#: Why the door stopped answering an agent when no frame said so, by the door's refusal code.
_STOPPED_WORDS: Final = {
    "unauthenticated": "the world no longer accepts this agent's key (a grant has one key at a "
    "time, so a new key from the world's owner ends the earlier one)",
    "key_not_accepted": "the world no longer accepts this agent's key",
    "grant_ended": "its permission in this world has ended",
    "bridge_not_admitted": "this world's door no longer admits outside agents",
}
#: Why a body could not come in, as the door or the world's engine names it.
_REFUSED_WORDS: Final = {
    "no_arrival_place": "this world has no gate to come in through",
    "visitor_limit": "this world holds as many visitors as it takes",
    "already_here": "your body is already here",
    "unknown_kind": "this world does not know the kind of body you would arrive as",
    "malformed_crossing": "the world could not read your body's crossing",
    "world_not_open_to_visitors": "this world does not take visitors",
}
#: Why a body left, as the world's engine or the door records it.
_LEFT_WORDS: Final = {
    "chose_to_leave": "you chose to leave",
    "decider_lost": "you were silent too long",
    "sent_away": "the world's owner sent your body away",
    "sent_home": "the world's owner sent your body home",
    "grant_ended": "your permission ended",
    "world_changed": "the world was changed, so its visitors were sent home",
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
    words = scope.get("world_words")
    return {
        "things": [str(thing) for thing in things] if isinstance(things, list) else [],
        "visitors_maximum": int(scope.get("visitors_maximum") or 0),
        "may_speak": bool(scope.get("may_speak", False)),
        "world_words": words if isinstance(words, str) else None,
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


def from_stopped(code: str, why: str | None = None) -> Happening:
    """The door stopped answering this agent with a refusal no frame explained: the words for its
    code, else ``why`` (a refused hello's words). A key the door stopped accepting reads the same
    whether a poll or the hello after it was refused."""
    why = _STOPPED_WORDS.get(code) or why or f"the world's door refused it ({code})"
    return Happening(
        "connection_ended",
        f"This agent's connection to the world has ended: {why}. The world's own routine decides "
        "now.",
        reason=code,
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def from_arrived(frame: Mapping[str, Any]) -> Happening:
    """The agent's own body came in through the gate."""
    return Happening(
        "arrived",
        "Your body came into the world through its gate. Its turns follow.",
        thing=_text(frame.get("thing_id")),
    )


def from_arrival_refused(frame: Mapping[str, Any]) -> Happening:
    reason = _text(frame.get("reason"))
    why = _REFUSED_WORDS.get(reason or "", f"it was refused ({reason or 'no reason given'})")
    return Happening("could_not_arrive", f"Your body could not come in: {why}.", reason=reason)


def from_said(frame: Mapping[str, Any], bodies: Collection[str] = ()) -> Happening:
    """A line the agent's body heard, quoted: what someone said, never an instruction. A line one
    of the agent's own ``bodies`` said reads as its own, and one said to one of them as said to
    it; whom else a line was said to is named where the door names it."""
    speaker = frame.get("speaker") if isinstance(frame.get("speaker"), Mapping) else {}
    label = _text(speaker.get("label")) or "someone"
    mind = speaker.get("mind") if isinstance(speaker.get("mind"), Mapping) else {}
    who = label if not _text(mind.get("words")) else f"{label} ({mind['words']})"
    if _text(speaker.get("id")) in bodies:
        who = "Your body"
    to, to_label = _text(frame.get("to")), _text(frame.get("to_label"))
    whom = " to you" if to is not None and to in bodies else f" to {to_label}" if to_label else ""
    line = _text(frame.get("line")) or ""
    tick = frame.get("tick")
    return Happening(
        "heard",
        f'{who} said{whom}: "{line}"',
        minute=tick if type(tick) is int else None,
        line=line,
    )


def from_happened(frame: Mapping[str, Any]) -> Happening:
    tick = frame.get("tick")
    return Happening(
        "saw",
        _text(frame.get("words")) or "Something happened near your body.",
        minute=tick if type(tick) is int else None,
    )


def from_departed(frame: Mapping[str, Any]) -> Happening:
    why = _text(frame.get("why"))
    words = _LEFT_WORDS.get(why or "", f"it left ({why or 'no reason given'})")
    return Happening(
        "left",
        f"Your body left the world: {words}.",
        thing=_text(frame.get("thing_id")),
        reason=why,
    )
