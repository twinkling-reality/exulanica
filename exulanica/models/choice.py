"""One choice among labelled options, asked of a model and checked on the way back.

A caller that needs a model to pick exactly one of a few options it computed, and nothing else,
describes the choice as a :class:`ChoiceRequest`. The request builds both ways of asking a model
for it: one OpenAI-format function whose single argument is an enum of the options, forced by name,
and a strict JSON schema whose single property is that enum. It is the one place in this codebase a
function tool is built, which is what lets the policy boundary admit a tool: a request carrying
``tools`` or ``tool_choice`` passes :func:`exulanica.models.policy.request_parts` only when they are
exactly the ones the request's :class:`ChoiceRequest` built, and any other tool is refused as text
no policy is shown.

**Labels are structure, not carried text.** An option reads as short lowercase product
vocabulary, the caller's own words for what an option is: letters, digits, spaces and a little
punctuation, checked here, so a label cannot carry a saved name's capitals, a placeholder's
brackets or a sentence of somebody's text. The description is product instruction, written in
code, like a system message. The function's name and its argument's are fixed values
(:data:`CHOICE_FUNCTION`, :data:`CHOICE_ARGUMENT`), never a caller's text. What a caller shows the
model about the situation goes in its messages, where every policy judges it.

**A reply is one of the labels, exactly.** :meth:`ChoiceRequest.answer` refuses anything else:
another string, a second argument, a missing one. A tool call is read from the one tool call the
reply carries and refused when it names another function or carries no call at all.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica.models.errors import StructuredOutputError
from exulanica.models.manifest import AnsweringMechanism
from exulanica.models.schema import response_format_for_schema, validate_against_schema

__all__ = [
    "CHOICE_ARGUMENT",
    "CHOICE_FUNCTION",
    "OPTIONS_MAXIMUM",
    "ChoiceRefused",
    "ChoiceRequest",
]

#: How many options one choice may offer: a bound on the enum, which rides in every request.
OPTIONS_MAXIMUM: Final = 64
#: The one function every choice is asked by, and its one argument: fixed values, so nothing a
#: caller writes rides in a name, where no policy could replace it.
CHOICE_FUNCTION: Final = "act"
CHOICE_ARGUMENT: Final = "action"
#: An option label: lowercase product vocabulary, no capitals, brackets, quotes or newlines.
_LABEL: Final = re.compile(r"^[a-z0-9][a-z0-9 ,.'()-]{0,118}[a-z0-9)]$")
#: The description is instruction text: printable ASCII, one line, bounded.
_DESCRIPTION: Final = re.compile(r"^[ -~]{1,300}$")


class ChoiceRefused(StructuredOutputError):
    """A reply that is not exactly one of the offered options. Nothing it carried is used."""


@dataclass(frozen=True, slots=True)
class ChoiceRequest:
    """One choice among ``options``, asked by the fixed function or by a schema."""

    description: str
    options: tuple[str, ...]

    @property
    def name(self) -> str:
        return CHOICE_FUNCTION

    @property
    def argument(self) -> str:
        return CHOICE_ARGUMENT

    def __post_init__(self) -> None:
        if not isinstance(self.description, str) or not _DESCRIPTION.fullmatch(self.description):
            raise ValueError("a choice's description is one line of printable instruction text")
        options = tuple(self.options)
        if not 1 <= len(options) <= OPTIONS_MAXIMUM:
            raise ValueError(f"a choice offers 1 to {OPTIONS_MAXIMUM} options, not {len(options)}")
        if len(set(options)) != len(options):
            raise ValueError("a choice offers each option once")
        for option in options:
            if not isinstance(option, str) or not _LABEL.fullmatch(option):
                raise ValueError(
                    f"option {option!r} is not a label: lowercase words, digits, spaces and "
                    "a little punctuation, as product vocabulary reads"
                )
        object.__setattr__(self, "options", options)

    def schema(self) -> dict[str, Any]:
        """The arguments' schema: one required property, an enum of the options, nothing else."""
        return {
            "type": "object",
            "properties": {self.argument: {"type": "string", "enum": list(self.options)}},
            "required": [self.argument],
            "additionalProperties": False,
        }

    def tool(self) -> dict[str, Any]:
        """The one function a reply may call, in the OpenAI tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema(),
            },
        }

    def tool_choice(self) -> dict[str, Any]:
        """Forcing the reply to call that function by name."""
        return {"type": "function", "function": {"name": self.name}}

    def response_format(self) -> dict[str, Any]:
        """The same choice as a strict JSON schema."""
        return response_format_for_schema(self.schema(), self.name)

    def payload_fields(self, mechanism: AnsweringMechanism) -> dict[str, Any]:
        """The request fields that ask for this choice by ``mechanism``."""
        if mechanism is AnsweringMechanism.TOOL_CALL:
            return {"tools": [self.tool()], "tool_choice": self.tool_choice()}
        if mechanism is AnsweringMechanism.JSON_SCHEMA:
            return {"response_format": self.response_format()}
        raise ValueError(f"no request is built for answering mechanism {mechanism!r}")

    def carries(self, tools: object, tool_choice: object) -> bool:
        """Whether ``tools`` and ``tool_choice`` are exactly the ones this request built."""
        return tools == [self.tool()] and tool_choice == self.tool_choice()

    def answer(self, arguments: object) -> str:
        """The option a reply's arguments chose, or :class:`ChoiceRefused` saying why not."""
        try:
            checked = validate_against_schema(arguments, self.schema(), name=self.name)
        except StructuredOutputError as exc:
            raise ChoiceRefused(f"the reply is not one of the offered options: {exc}") from exc
        return str(checked[self.argument])

    def answer_from_tool_call(self, message: Mapping[str, Any]) -> str:
        """The option a reply's one tool call chose, or :class:`ChoiceRefused` saying why not."""
        calls = message.get("tool_calls")
        if not isinstance(calls, list) or len(calls) != 1:
            count = len(calls) if isinstance(calls, list) else 0
            raise ChoiceRefused(f"the reply carries {count} tool calls; it must carry exactly one")
        function = calls[0].get("function") if isinstance(calls[0], Mapping) else None
        if not isinstance(function, Mapping) or function.get("name") != self.name:
            raise ChoiceRefused(f"the reply's tool call does not call {self.name}")
        raw = function.get("arguments")
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc:
            raise ChoiceRefused("the reply's tool call arguments are not JSON") from exc
        return self.answer(arguments)
