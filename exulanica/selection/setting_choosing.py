"""The setting a person's description asks for, chosen in a short step of its own after the draft.

A world's setting (:mod:`exulanica.world.world_settings`) is chosen from named parts, one an axis:
an hour and sky, the ground and what lies beyond, a cover such as snow. This step is asked after
the specification drafter and the look chooser, separately from both, with only the description
and the parts (each part's axis, key, title and description), and answers a listed part for each
axis or none, with the description's own words that chose them. It never sees the draft or the
look and neither sees it, so offering a setting can move neither (the look chooser's module says
what was measured when a look was offered inside the drafter).

Deterministic validation decides: a part not listed is outside the answer's form; a phrase not
copied from the description, words without a part or a part without words are refused, repaired
once, and then the step answers none. Whatever it answers, the person chooses: the host composes
the parts they take into a setting for the look the world is made in, and holds it to the setting's
own rules. The step is optional, so it runs within one deadline, the role's timeout, over its call
and its repair together.
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
from exulanica.models.manifest import Role
from exulanica.selection.calls import CallLog, ModelCall
from exulanica.selection.world_drafting import verbatim_bounds

__all__ = [
    "CHOOSER_ROLE",
    "PROMPT_PATH",
    "ChooserPrompt",
    "SettingAxis",
    "SettingChoice",
    "SettingOption",
    "choice_schema",
    "choose_setting",
    "chooser_prompt",
    "render_request",
]

PROMPT_PATH: Final = Path(__file__).with_name("setting-choosing.v1.json")
_PROMPT_PROFILE: Final = "exulanica.setting-choosing-prompt/v1"
#: The step answers once and is repaired at most once.
ATTEMPTS: Final = 2
#: The role every call of the step is sent under.
CHOOSER_ROLE: Final = Role.SETTING_CHOOSER
#: The answer's field for the description's own words; no axis may take this key.
WORDS_FIELD: Final = "words"


@dataclass(frozen=True, slots=True)
class ChooserPrompt:
    version: int
    sha256: str
    instructions: str
    repair_refused: str
    repair_truncated: str
    words_maximum: int
    word_characters_maximum: int

    @property
    def prompt_version(self) -> str:
        return f"setting-choosing-{self.version}"


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
        words_maximum=int(document["words_maximum"]),
        word_characters_maximum=int(document["word_characters_maximum"]),
    )


@dataclass(frozen=True, slots=True)
class SettingAxis:
    """One axis of a setting: what the chooser is told of it."""

    key: str
    title: str


@dataclass(frozen=True, slots=True)
class SettingOption:
    """One named part: what the chooser is told of it, and nothing else."""

    axis: str
    key: str
    title: str
    description: str


@dataclass(frozen=True, slots=True)
class SettingChoice:
    """What the step answered: a listed part for some axes and the description's own words for
    them, or none, with why when it is none because the answer was refused."""

    #: The part chosen for each axis that has one, in the axes' order.
    parts: Mapping[str, str]
    #: The description's own slices the answer copied, as the description given spells them.
    words: tuple[str, ...]
    refused: str | None
    model_id: str | None
    calls: tuple[ModelCall, ...]
    #: Where in the description given each of ``words`` is, ``(start, end)``.
    words_at: tuple[tuple[int, int], ...] = ()


def choice_schema(
    axes: Sequence[SettingAxis], options: Sequence[SettingOption], prompt: ChooserPrompt
) -> type[BaseModel]:
    """The answer's form: for each axis one of its listed keys or null, then the phrases last."""
    phrase = Annotated[str, Field(min_length=1, max_length=prompt.word_characters_maximum)]
    fields: dict[str, Any] = {}
    for axis in axes:
        if axis.key == WORDS_FIELD:
            raise ValueError(f"an axis may not be named {WORDS_FIELD}")
        keys = tuple(option.key for option in options if option.axis == axis.key)
        if not keys:
            continue
        fields[axis.key] = (
            Literal[keys] | None,  # type: ignore[valid-type]
            Field(
                description=f"{axis.title}: the one listed part the description asks for, or null."
            ),
        )
    fields[WORDS_FIELD] = (
        Annotated[list[phrase], Field(max_length=prompt.words_maximum)],  # type: ignore[valid-type]
        Field(description="The description's own words that chose the parts, copied exactly."),
    )
    return create_model(  # type: ignore[call-overload,no-any-return]
        "SettingChoiceForm", __config__=ConfigDict(extra="forbid"), **fields
    )


def render_request(
    description: str, axes: Sequence[SettingAxis], options: Sequence[SettingOption]
) -> str:
    """The one user message: the description, then each axis and its parts. Nothing else reaches
    the model."""
    blocks = []
    for axis in axes:
        listed = [option for option in options if option.axis == axis.key]
        if not listed:
            continue
        lines = "\n".join(f"- {one.key}: {one.title}. {one.description}" for one in listed)
        blocks.append(f"{axis.key} ({axis.title}):\n{lines}")
    parts = "\n\n".join(blocks)
    return f"The person's description:\n{description}\n\nThe parts of a setting, by axis:\n{parts}"


def _problem(form: dict[str, Any], description: str) -> str | None:
    words = list(form[WORDS_FIELD])
    chosen = [key for axis, key in form.items() if axis != WORDS_FIELD and key is not None]
    if not chosen and words:
        return "words is empty when every axis is null."
    if chosen and not words:
        return "a chosen part names the description's words that chose it."
    missing = [word for word in words if verbatim_bounds(word, description) is None]
    if missing:
        return "these were not copied word for word from the description: " + "; ".join(
            json.dumps(word, ensure_ascii=False) for word in missing
        )
    return None


def choose_setting(
    client: ModelClient,
    description: str,
    axes: Sequence[SettingAxis],
    options: Sequence[SettingOption],
    *,
    role: Role | str = CHOOSER_ROLE,
    prompt: ChooserPrompt | None = None,
    placeholders: Mapping[uuid.UUID, str] | None = None,
    log: CallLog | None = None,
    max_tokens: int | None = None,
    deadline_s: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> SettingChoice:
    """Ask which listed part of each axis ``description`` asks for, with one repair, and answer
    none on a second refusal. ``description`` is the text as it was sent to the drafter (saved
    names already replaced, ``placeholders`` the record of those replacements, handed to the
    boundary with the request); ``axes`` and ``options`` the host's named parts. The model sees
    nothing else. A model error (a timeout, a failure, a refused request, no allowance left) is
    the caller's.

    The call and its repair share one deadline, ``deadline_s`` or else the role's timeout: each
    is sent with what is left of it, and no repair is asked once none is left."""
    prompt = chooser_prompt() if prompt is None else prompt
    timeout = float(client.manifest[role].timeout_seconds)
    ends = clock() + (timeout if deadline_s is None else min(deadline_s, timeout))
    if max_tokens is None:
        declared = client.manifest[role].max_tokens
        max_tokens = None if declared is None else declared.value
    log = CallLog() if log is None else log
    if not options:
        return SettingChoice({}, (), None, None, log.calls)
    schema = choice_schema(axes, options, prompt)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt.instructions},
        {"role": "user", "content": render_request(description, axes, options)},
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
            log.record(answered.call)
            form = answered.value.model_dump()
            problem = _problem(form, description)
            if problem is None:
                at: list[tuple[int, int]] = []
                for word in form[WORDS_FIELD]:
                    bounds = verbatim_bounds(word, description)
                    if bounds is not None and bounds not in at:
                        at.append(bounds)
                return SettingChoice(
                    {axis.key: form[axis.key] for axis in axes if form.get(axis.key) is not None},
                    tuple(description[start:end] for start, end in at),
                    None,
                    answered.call.served_model_id,
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
    return SettingChoice({}, (), refused, None, log.calls)
