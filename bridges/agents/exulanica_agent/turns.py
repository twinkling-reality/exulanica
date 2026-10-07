"""A turn: one moment a thing the agent decides for may act, asked exactly as a model is asked.

The door's ``asked`` frame carries the request as one of the world's own models receives it: the
messages the world renders for its role (a system message and a user message), the forced function
``act`` in the tool format, the minute, and the request's context. A turn hands the messages and the
function to whatever mind the agent uses, and takes its answer back: one offered action, written
exactly as offered, with a line when that action says something.

Nothing here renders a world's words: they come from the world, so an agent reads what a model
reads and never a second wording of it. An ``asked`` frame without them comes from a door older
than this library, and is refused by name.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "ARRIVAL_MARGIN_SECONDS",
    "Answer",
    "FrameRefused",
    "Option",
    "Turn",
    "turn_from_frame",
]

#: How much earlier than its deadline a turn is treated as over: the poll that brings an ask reads
#: the door at most about a second after the ask was written, and the answer must cross back.
ARRIVAL_MARGIN_SECONDS: Final = 1.0
_ROLES: Final = frozenset({"system", "user"})


class FrameRefused(ValueError):
    """An ``asked`` frame this library cannot hand to a mind as a model would receive it."""


@dataclass(frozen=True, slots=True)
class Option:
    """One action a turn offers: its words, exactly as an answer must repeat them, and whether it
    says something, with the longest line it takes."""

    action: str
    says_line: bool
    line_characters_maximum: int | None

    def as_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {"action": self.action, "says_line": self.says_line}
        if self.line_characters_maximum is not None:
            document["line_characters_maximum"] = self.line_characters_maximum
        return document


@dataclass(frozen=True, slots=True)
class Answer:
    """What became of an answer: ``received`` when the door stored it; otherwise the refusal's
    code and words. The world's host decides later whether a received answer is taken, which
    arrives as a happening."""

    received: bool
    refusal: str | None = None
    words: str = ""


def _text(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise FrameRefused(f"an asked frame's {where} is text")
    return value


def _whole(value: object, where: str) -> int:
    if type(value) is not int or value < 0:
        raise FrameRefused(f"an asked frame's {where} is a whole number")
    return value


def _messages(value: object) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise FrameRefused(
            "an asked frame carries the messages a model receives; this door is older than the "
            "agent library needs"
        )
    messages = []
    for message in value:
        if (
            not isinstance(message, Mapping)
            or set(message) != {"role", "content"}
            or message["role"] not in _ROLES
            or not isinstance(message["content"], str)
        ):
            raise FrameRefused("an asked frame's messages are system and user text")
        messages.append({"role": message["role"], "content": message["content"]})
    return tuple(messages)


def _offered(act: object) -> tuple[str, list[str], bool]:
    """The forced function's name, its offered actions in order, and whether it takes a line."""
    if not isinstance(act, Mapping) or act.get("type") != "function":
        raise FrameRefused(
            "an asked frame carries the function a model answers by; this door is older than the "
            "agent library needs"
        )
    function = act.get("function")
    parameters = function.get("parameters") if isinstance(function, Mapping) else None
    properties = parameters.get("properties") if isinstance(parameters, Mapping) else None
    action = properties.get("action") if isinstance(properties, Mapping) else None
    labels = action.get("enum") if isinstance(action, Mapping) else None
    name = function.get("name") if isinstance(function, Mapping) else None
    if (
        not isinstance(name, str)
        or not name
        or not isinstance(labels, list)
        or not labels
        or not all(isinstance(label, str) and label for label in labels)
        or len(set(labels)) != len(labels)
    ):
        raise FrameRefused("an asked frame's function offers its actions by name")
    return name, list(labels), "line" in properties


def _options(context: object, labels: list[str], takes_line: bool) -> tuple[Option, ...]:
    """The offered actions, from the request's own option records, which must offer exactly what
    the function offers and in its order; an option says something when its record bounds a
    line."""
    records = context.get("options") if isinstance(context, Mapping) else None
    if (
        not isinstance(records, list)
        or [record.get("label") if isinstance(record, Mapping) else None for record in records]
        != labels
    ):
        raise FrameRefused("an asked frame's function and its options offer different actions")
    options = []
    for record in records:
        maximum = record.get("line_characters_maximum")
        if maximum is not None and (type(maximum) is not int or maximum < 1):
            raise FrameRefused("an option bounds its line by a whole number of characters")
        if maximum is not None and not takes_line:
            raise FrameRefused("an option says something, but the function takes no line")
        options.append(
            Option(
                action=record["label"],
                says_line=maximum is not None,
                line_characters_maximum=maximum,
            )
        )
    return tuple(options)


class Turn:
    """One open turn: what the thing is shown, what it may do, and how long is left to answer.

    ``turn`` is the handle an answer names: the door's id for the request, which names this turn
    and opens nothing. ``messages`` and ``tool`` are what one of the world's own models receives,
    ready for any chat API that takes OpenAI-format messages and tools, with ``tool_choice``
    forcing the one function.
    """

    def __init__(
        self,
        frame: Mapping[str, Any],
        *,
        received_at: float,
        answer: Callable[[Turn, str, str | None], Answer],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if frame.get("kind") != "asked":
            raise FrameRefused("a turn comes from an asked frame")
        self.turn = _text(frame.get("request_id"), "request id")
        self.request_sha256 = _text(frame.get("request_sha256"), "request digest")
        self.thing = _text(frame.get("subject_id"), "thing")
        self.minute = _whole(frame.get("minute"), "minute")
        self.deadline_ms = _whole(frame.get("deadline_ms"), "deadline")
        self._messages = _messages(frame.get("messages"))
        name, labels, takes_line = _offered(frame.get("act"))
        self._tool = copy.deepcopy(dict(frame["act"]))
        self._tool_name = name
        self.options = _options(frame.get("context"), labels, takes_line)
        self.received_at = received_at
        self._answer = answer
        self._clock = clock

    def __repr__(self) -> str:
        return f"Turn(turn={self.turn!r}, thing={self.thing!r}, minute={self.minute})"

    @property
    def messages(self) -> list[dict[str, str]]:
        """The messages a model receives, as a fresh list each time."""
        return [dict(message) for message in self._messages]

    @property
    def instruction(self) -> str:
        return "\n".join(m["content"] for m in self._messages if m["role"] == "system")

    @property
    def situation(self) -> str:
        return "\n".join(m["content"] for m in self._messages if m["role"] == "user")

    @property
    def tool(self) -> dict[str, Any]:
        """The forced function a model answers by, in the OpenAI tool format."""
        return copy.deepcopy(self._tool)

    @property
    def tool_choice(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self._tool_name}}

    @property
    def seconds_left(self) -> float:
        """Seconds left to answer, kept a margin short of the deadline; zero once it passed."""
        spent = self._clock() - self.received_at
        return max(0.0, self.deadline_ms / 1000 - ARRIVAL_MARGIN_SECONDS - spent)

    def offered(self, action: str) -> Option | None:
        return next((option for option in self.options if option.action == action), None)

    def act(self, action: str, line: str | None = None) -> Answer:
        """Answer with one offered action, exactly as written, and its line when it says one.

        An answer the turn itself shows to be wrong is refused here, with words saying how to put
        it right, before anything is sent; the door checks every answer again.
        """
        if not isinstance(action, str):
            return Answer(False, "answer_not_offered", "An action is text, as it is offered.")
        option = self.offered(action)
        if option is None:
            offered = "; ".join(option.action for option in self.options)
            return Answer(
                False,
                "answer_not_offered",
                f"That is not one of the offered actions. Choose one exactly as written: {offered}",
            )
        if line == "":
            line = None
        if option.says_line and line is None:
            return Answer(False, "line_missing", "This action says something: give its line.")
        if not option.says_line and line is not None:
            return Answer(False, "line_not_offered", "This action says nothing: give no line.")
        maximum = option.line_characters_maximum
        if line is not None and (not isinstance(line, str) or len(line) > (maximum or 0)):
            return Answer(
                False,
                "line_out_of_bounds",
                f"A line is one line of text, at most {maximum} characters.",
            )
        return self._answer(self, action, line)

    def as_dict(self) -> dict[str, Any]:
        """The turn as the facade's tools state it."""
        return {
            "turn": self.turn,
            "thing": self.thing,
            "minute": self.minute,
            "answer_within_ms": round(self.seconds_left * 1000),
            "instruction": self.instruction,
            "situation": self.situation,
            "options": [option.as_dict() for option in self.options],
        }


def turn_from_frame(
    frame: Mapping[str, Any],
    *,
    received_at: float,
    answer: Callable[[Turn, str, str | None], Answer],
    clock: Callable[[], float] = time.monotonic,
) -> Turn:
    """The turn an ``asked`` frame opens, or :class:`FrameRefused` saying what it lacks."""
    return Turn(frame, received_at=received_at, answer=answer, clock=clock)
