"""The tool that should make the world a person described, chosen in a short step of its own.

A world is made by a tool (:mod:`exulanica.world.world_tools`): the town's, whose worlds are
streets lined with buildings, or the general one, which lays out any other place. Before anything
is drafted this step is asked which, with only the description and each listed tool's own words
for what it can make and what it cannot, and answers a listed tool or none, with the
description's own words that say what the place is. Deterministic validation decides: a tool not
listed, a phrase not copied from the description, words without a tool or a tool without words
are refused, repaired once, and then the step answers none. Whoever asks takes the catalog's tool
for an unsure choice when it answers none or fails, and records that it did.

The step runs within one deadline, the role's timeout, over its call and its repair together.
The step's role, :data:`CHOOSER_ROLE`, has its timeout from a pre-registered measurement of its
primary's own calls (the role's ``timeout_basis`` in the model manifest names the record).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from exulanica.models.client import ModelClient
from exulanica.models.errors import StructuredOutputError, TruncatedResponseError
from exulanica.models.identity import chat_model_identity
from exulanica.models.manifest import Role
from exulanica.selection.calls import CallLog, ModelCall
from exulanica.selection.world_drafting import verbatim_bounds
from exulanica.world.world_tools import WorldTool

__all__ = [
    "CHOOSER_ROLE",
    "PROMPT_PATH",
    "ChooserPrompt",
    "ToolChoice",
    "choice_schema",
    "choose_tool",
    "chooser_prompt",
    "render_request",
]

PROMPT_PATH: Final = Path(__file__).with_name("tool-choosing.v1.json")
_PROMPT_PROFILE: Final = "exulanica.tool-choosing-prompt/v1"
#: The step answers once and is repaired at most once.
ATTEMPTS: Final = 2
#: The role every call of the step is sent under.
CHOOSER_ROLE: Final = Role.WORLD_TOOL_CHOOSER


@dataclass(frozen=True, slots=True)
class ChooserPrompt:
    version: int
    sha256: str
    instructions: str
    repair_refused: str
    repair_truncated: str
    tool_words_maximum: int
    tool_word_characters_maximum: int

    @property
    def prompt_version(self) -> str:
        return f"tool-choosing-{self.version}"


def chooser_prompt(path: Path = PROMPT_PATH) -> ChooserPrompt:
    """The chooser's words, read once and named by the file's SHA-256."""
    raw = path.read_bytes()
    document = json.loads(raw)
    if document.get("profile") != _PROMPT_PROFILE:
        raise ValueError(f"{path.name} is not a {_PROMPT_PROFILE} document")
    return ChooserPrompt(
        version=int(document["version"]),
        sha256=hashlib.sha256(raw).hexdigest(),
        instructions=str(document["instructions"]),
        repair_refused=str(document["repair"]["refused"]),
        repair_truncated=str(document["repair"]["truncated"]),
        tool_words_maximum=int(document["tool_words_maximum"]),
        tool_word_characters_maximum=int(document["tool_word_characters_maximum"]),
    )


@dataclass(frozen=True, slots=True)
class ToolChoice:
    """What the step answered: a listed tool and the description's own words for it, or none,
    with why when it is none because the answer was refused."""

    tool: str | None
    #: The description's own slices the answer copied, as the description given spells them.
    tool_words: tuple[str, ...]
    refused: str | None
    model_id: str | None
    calls: tuple[ModelCall, ...]
    #: Where in the description given each of ``tool_words`` is, ``(start, end)``.
    tool_words_at: tuple[tuple[int, int], ...] = ()


def choice_schema(tools: Sequence[WorldTool], prompt: ChooserPrompt) -> type[BaseModel]:
    """The answer's form: one listed key or null, and up to the prompt's bound of phrases."""
    phrase = Annotated[str, Field(min_length=1, max_length=prompt.tool_word_characters_maximum)]
    keys = tuple(tool.key for tool in tools)
    return create_model(  # type: ignore[call-overload,no-any-return]
        "ToolChoiceForm",
        __config__=ConfigDict(extra="forbid"),
        tool=(
            Literal[keys] | None,  # type: ignore[valid-type]
            Field(description="The one listed tool that can make the place, or null."),
        ),
        tool_words=(
            Annotated[list[phrase], Field(max_length=prompt.tool_words_maximum)],  # type: ignore[valid-type]
            Field(description="The description's own words that say what the place is."),
        ),
    )


def render_request(description: str, tools: Sequence[WorldTool]) -> str:
    """The one user message: the description, then the tools. Nothing else reaches the model."""
    listed = "\n".join(
        f"- {tool.key}: It can make: {tool.makes} It cannot make: {tool.cannot}" for tool in tools
    )
    return f"The person's description:\n{description}\n\nThe tools:\n{listed}"


def _problem(form: dict[str, Any], description: str) -> str | None:
    tool, words = form["tool"], list(form["tool_words"])
    if tool is None and words:
        return "tool_words is empty when tool is null."
    if tool is not None and not words:
        return "a chosen tool names the description's words that say what the place is."
    missing = [word for word in words if verbatim_bounds(word, description) is None]
    if missing:
        return "these were not copied word for word from the description: " + "; ".join(
            json.dumps(word, ensure_ascii=False) for word in missing
        )
    return None


def choose_tool(
    client: ModelClient,
    description: str,
    tools: Sequence[WorldTool],
    *,
    role: Role | str = CHOOSER_ROLE,
    prompt: ChooserPrompt | None = None,
    placeholders: Mapping[uuid.UUID, str] | None = None,
    log: CallLog | None = None,
    max_tokens: int | None = None,
    deadline_s: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ToolChoice:
    """Ask which listed tool should make the world ``description`` asks for, with one repair, and
    answer none on a second refusal. ``description`` is the text as it is sent to a drafter (saved
    names already replaced, ``placeholders`` the record of those replacements, handed to the
    boundary with the request); ``tools`` the catalog's. The model sees nothing else. A model
    error (a timeout, a failure, a refused request, no allowance left) is the caller's.

    The call and its repair share one deadline, ``deadline_s`` or else the role's timeout: each
    is sent with what is left of it, and no repair is asked once none is left."""
    prompt = chooser_prompt() if prompt is None else prompt
    timeout = float(client.manifest[role].timeout_seconds)
    ends = clock() + (timeout if deadline_s is None else min(deadline_s, timeout))
    if max_tokens is None:
        declared = client.manifest[role].max_tokens
        max_tokens = None if declared is None else declared.value
    log = CallLog() if log is None else log
    if not tools:
        return ToolChoice(None, (), None, None, log.calls)
    schema = choice_schema(tools, prompt)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt.instructions},
        {"role": "user", "content": render_request(description, tools)},
    ]
    refused: str | None = None
    for attempt in range(1, ATTEMPTS + 1):
        left = ends - clock()
        if left <= 0:
            refused = f"{refused}; no time was left to repair it"
            break
        try:
            answered = client.structured(
                role,
                messages,
                schema,
                prompt_version=prompt.prompt_version,
                placeholders=placeholders,
                max_tokens=max_tokens,
                deadline_s=left,
            )
            log.record(answered.call, manifest=client.manifest)
            identity = chat_model_identity(answered.call, client.manifest)
            form = answered.value.model_dump()
            problem = _problem(form, description)
            if problem is None:
                at: list[tuple[int, int]] = []
                for word in form["tool_words"]:
                    bounds = verbatim_bounds(word, description)
                    if bounds is not None and bounds not in at:
                        at.append(bounds)
                return ToolChoice(
                    form["tool"],
                    tuple(description[start:end] for start, end in at),
                    None,
                    identity.model_id,
                    log.calls,
                    tuple(at),
                )
            log.rejected((problem,))
            refused = problem
            repair = prompt.repair_refused.format(problem=problem)
        except TruncatedResponseError:
            refused = "the answer was cut short"
            repair = prompt.repair_truncated
        except StructuredOutputError as rejected:
            refused = f"the answer was outside its form: {rejected}"
            repair = prompt.repair_refused.format(problem=refused)
        if attempt == ATTEMPTS:
            break
        messages.append({"role": "user", "content": repair})
    return ToolChoice(None, (), refused, None, log.calls)
