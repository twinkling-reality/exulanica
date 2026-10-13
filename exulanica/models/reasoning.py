"""Separating a reasoning model's scratch work from its answer.

The reasoning models on this platform spend roughly 150 to 215 tokens thinking on every call and
that cannot be switched off. Where the thinking text ends up is the part the documentation gets
wrong, so this module handles **both** observed shapes rather than trusting either:

*   ``message.reasoning_content`` (and its sibling ``message.reasoning``) populated, with
    ``message.content`` holding a clean answer. This is what every archived verification response
    actually shows, including the structured-output one where ``content`` was exactly
    ``{"colours": [...]}`` while ``reasoning_content`` held five numbered thinking steps.
*   Thinking inlined in ``message.content`` inside a ``<think>`` block. `runtime-verification.md`
    section 5 states this is what happens and that ``reasoning_content`` is null. Its own
    archived artifacts contradict it. The code refuses to depend on which one is right, because
    being wrong in either direction means
    a model's scratch work is parsed as a fact.

The third case is the dangerous one and it is why ``complete`` exists: an **unterminated** open
tag means the token limit was reached mid-thought. There is no answer in that response, only a
truncated thought, and a caller that treats the fragment as an answer has invented a fact.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

__all__ = ["SplitContent", "split_message", "split_reasoning"]

#: Every opening/closing pair seen from the reasoning families in this manifest. Matched
#: case-insensitively because the tag casing is not contractual.
_TAG_NAMES: Final = ("think", "thinking", "reasoning")

_OPEN: Final = re.compile(r"<\s*(" + "|".join(_TAG_NAMES) + r")\s*>", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SplitContent:
    """The result of pulling scratch work out of a response.

    ``answer`` is what a caller may use. ``reasoning`` is kept rather than discarded because it
    is genuinely useful when a structured extraction fails and somebody has to work out why, but
    it is never evidence and never enters canonical state.
    """

    answer: str
    reasoning: str | None
    inline: bool
    complete: bool

    @property
    def empty_answer(self) -> bool:
        return not self.answer.strip()


def _closing(tag: str) -> re.Pattern[str]:
    return re.compile(r"<\s*/\s*" + tag + r"\s*>", re.IGNORECASE)


def split_reasoning(content: str | None, *, reasoning_field: str | None = None) -> SplitContent:
    """Split one ``message.content`` into answer and reasoning.

    ``reasoning_field`` is whatever the provider put in ``reasoning_content`` or ``reasoning``.
    It is used when the content carries no inline block, which is the shape actually observed.
    """
    text = content or ""
    match = _OPEN.search(text)
    if match is None:
        return SplitContent(
            answer=text.strip(),
            reasoning=(reasoning_field.strip() if reasoning_field else None) or None,
            inline=False,
            complete=True,
        )

    tag = match.group(1)
    head = text[: match.start()]
    rest = text[match.end() :]
    close = _closing(tag).search(rest)
    if close is None:
        # Truncated mid-thought. Everything after the open tag is scratch work, and there is no
        # answer in this response at all.
        return SplitContent(
            answer=head.strip(),
            reasoning=rest.strip() or None,
            inline=True,
            complete=False,
        )

    inner = rest[: close.start()]
    tail = rest[close.end() :]
    # Recurse over the remainder so a model that emits two blocks does not leave one behind.
    outer = split_reasoning(head + tail, reasoning_field=None)
    pieces = [p for p in (inner.strip(), outer.reasoning) if p]
    combined = "\n\n".join(pieces) if pieces else None
    if reasoning_field and reasoning_field.strip() and reasoning_field.strip() != combined:
        combined = "\n\n".join(p for p in (reasoning_field.strip(), combined) if p)
    return SplitContent(
        answer=outer.answer,
        reasoning=combined,
        inline=True,
        complete=outer.complete,
    )


def split_message(message: Mapping[str, Any]) -> SplitContent:
    """Split a raw ``choices[].message`` object.

    Reads ``reasoning_content`` first and ``reasoning`` second. Both appear in real responses
    from this endpoint carrying identical text; taking the documented name first and the
    undocumented one only as a stand-in means a future response that drops the alias still works.
    """
    field = message.get("reasoning_content")
    if not isinstance(field, str) or not field.strip():
        alias = message.get("reasoning")
        field = alias if isinstance(alias, str) else None
    content = message.get("content")
    return split_reasoning(content if isinstance(content, str) else None, reasoning_field=field)
