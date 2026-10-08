"""The look a person's description asks for, chosen in a short step of its own after the draft.

The specification drafter (:mod:`exulanica.selection.world_drafting`) drafts a world from a
description and never sees a look, so offering one can never move a draft's fit (measured: looks
offered inside the drafter moved fit; deliveries record the runs). This step is asked separately,
with only the description and the library's looks (each pack's id, title and description), and
answers a listed look or none, with the description's own words that chose it. Deterministic
validation decides: a look not listed, a phrase not copied from the description, words without a
look or a look without words are refused, repaired once, and then the step answers none. Whatever
it answers, the person chooses; the library's default stands when it answers none or fails.
The step is optional, so it runs within one deadline, the role's timeout, over its call and its
repair together: the draft it follows is never kept waiting longer than that by it.

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
from exulanica.models.manifest import Role
from exulanica.selection.calls import CallLog, ModelCall
from exulanica.selection.world_drafting import verbatim_bounds

__all__ = [
    "CHOOSER_ROLE",
    "PROMPT_PATH",
    "ChooserPrompt",
    "LookChoice",
    "LookOption",
    "choice_schema",
    "choose_look",
    "chooser_prompt",
    "render_request",
]

PROMPT_PATH: Final = Path(__file__).with_name("look-choosing.v1.json")
_PROMPT_PROFILE: Final = "exulanica.look-choosing-prompt/v1"
#: The step answers once and is repaired at most once.
ATTEMPTS: Final = 2
#: The role every call of the step is sent under.
CHOOSER_ROLE: Final = Role.LOOK_CHOOSER


@dataclass(frozen=True, slots=True)
class ChooserPrompt:
    version: int
    sha256: str
    instructions: str
    repair_refused: str
    repair_truncated: str
    look_words_maximum: int
    look_word_characters_maximum: int

    @property
    def prompt_version(self) -> str:
        return f"look-choosing-{self.version}"


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
        look_words_maximum=int(document["look_words_maximum"]),
        look_word_characters_maximum=int(document["look_word_characters_maximum"]),
    )


@dataclass(frozen=True, slots=True)
class LookOption:
    """One look the library offers: what the chooser is told of it, and nothing else."""

    pack_id: str
    title: str
    description: str


@dataclass(frozen=True, slots=True)
class LookChoice:
    """What the step answered: a listed look and the description's own words for it, or none,
    with why when it is none because the answer was refused."""

    look: str | None
    #: The description's own slices the answer copied, as the description given spells them.
    look_words: tuple[str, ...]
    refused: str | None
    model_id: str | None
    calls: tuple[ModelCall, ...]
    #: Where in the description given each of ``look_words`` is, ``(start, end)``.
    look_words_at: tuple[tuple[int, int], ...] = ()


def choice_schema(options: Sequence[LookOption], prompt: ChooserPrompt) -> type[BaseModel]:
    """The answer's form: one listed id or null, and up to the prompt's bound of phrases."""
    phrase = Annotated[str, Field(min_length=1, max_length=prompt.look_word_characters_maximum)]
    ids = tuple(option.pack_id for option in options)
    return create_model(  # type: ignore[call-overload,no-any-return]
        "LookChoiceForm",
        __config__=ConfigDict(extra="forbid"),
        look=(
            Literal[ids] | None,  # type: ignore[valid-type]
            Field(description="The one listed look the description asks for, or null."),
        ),
        look_words=(
            Annotated[list[phrase], Field(max_length=prompt.look_words_maximum)],  # type: ignore[valid-type]
            Field(description="The description's own words that chose the look, copied exactly."),
        ),
    )


def render_request(description: str, options: Sequence[LookOption]) -> str:
    """The one user message: the description, then the looks. Nothing else reaches the model."""
    looks = "\n".join(
        f"- {option.pack_id}: {option.title}. {option.description}" for option in options
    )
    return f"The person's description:\n{description}\n\nThe looks:\n{looks}"


def _problem(form: dict[str, Any], description: str) -> str | None:
    look, words = form["look"], list(form["look_words"])
    if look is None and words:
        return "look_words is empty when look is null."
    if look is not None and not words:
        return "a chosen look names the description's words that chose it."
    missing = [word for word in words if verbatim_bounds(word, description) is None]
    if missing:
        return "these were not copied word for word from the description: " + "; ".join(
            json.dumps(word, ensure_ascii=False) for word in missing
        )
    return None


def choose_look(
    client: ModelClient,
    description: str,
    options: Sequence[LookOption],
    *,
    role: Role | str = CHOOSER_ROLE,
    prompt: ChooserPrompt | None = None,
    placeholders: Mapping[uuid.UUID, str] | None = None,
    log: CallLog | None = None,
    max_tokens: int | None = None,
    deadline_s: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> LookChoice:
    """Ask which listed look ``description`` asks for, with one repair, and answer none on a
    second refusal. ``description`` is the text as it was sent to the drafter (saved names
    already replaced, ``placeholders`` the record of those replacements, handed to the boundary
    with the request); ``options`` the library's looks. The model sees nothing else. A model
    error (a timeout, a failure, a refused request, no allowance left) is the caller's.

    The call and its repair share one deadline, ``deadline_s`` or else the role's timeout: each
    is sent with what is left of it, and no repair is asked once none is left."""
    prompt = chooser_prompt() if prompt is None else prompt
    timeout = float(client.manifest[role].timeout_seconds)
    ends = clock() + (timeout if deadline_s is None else min(deadline_s, timeout))
    if max_tokens is None:
        # The ceiling the role declares, as the measurement that set its timeout asked with.
        declared = client.manifest[role].max_tokens
        max_tokens = None if declared is None else declared.value
    log = CallLog() if log is None else log
    if not options:
        return LookChoice(None, (), None, None, log.calls)
    schema = choice_schema(options, prompt)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt.instructions},
        {"role": "user", "content": render_request(description, options)},
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
                for word in form["look_words"]:
                    bounds = verbatim_bounds(word, description)
                    if bounds is not None and bounds not in at:
                        at.append(bounds)
                return LookChoice(
                    form["look"],
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
    return LookChoice(None, (), refused, None, log.calls)
