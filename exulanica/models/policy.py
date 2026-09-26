"""What a hosted request may carry, decided at the one point every hosted request passes.

Every request this codebase sends to a hosted model is sent by :class:`ModelClient`, and every one
of its sending methods (``chat``, which ``structured`` and ``vision`` call, and ``embed``) hands the
request to the policies attached to the client before anything else is done with it: before the
response cache key is computed and before the model chain is walked. A client with no policy
refuses to send, by name, with :class:`NoHostedRequestPolicy`. A call site cannot reach a hosted
model without a policy, and a policy is attached by the code that knows whose data the request
carries.

**What a policy sees** is a :class:`HostedRequest`:

*   the role and its hand-over: every model the role's chain can reach and the destination, the
    same value a personal model right is checked against;
*   ``texts``: every text the request carries outside its system messages, in payload order: user
    and assistant message contents, their text parts, and embedding inputs. A policy returns them
    as they may leave, the same number in the same order, and the client sends exactly those;
*   ``instructions``: the system messages. A system message is product instruction, written in
    code, and is sent as written. A policy may refuse a request because of one and never rewrites
    one, because rewriting fixed instructions would change every prompt for every account holder
    whose saved names are ordinary words;
*   ``photographs``: the captures whose bytes or derived text the request carries, as the caller
    declares them, and ``images``: how many image parts it carries;
*   ``placeholders``: the placeholder the caller already gave each entity its texts may name, so
    a name a policy withholds is written the way the caller's other requests about the same
    question write it. Empty for a caller that keeps no such record.

Text anywhere else in a request, in a caller's extra parameter or in a message field other than
its content, is refused before any policy is asked, because it is text no policy would be shown.
The one exception is a choice's function: ``tools`` and ``tool_choice`` pass as structure only
when they are exactly the ones the request's :class:`~exulanica.models.choice.ChoiceRequest`
built, whose option labels are product vocabulary it has already checked. Any other tool is
refused.

**What this layer does not do** is decide. It knows nothing of the database, the workspace or
the account holder's rules. The policy that applies them is
:class:`exulanica.epistemics.hosted_requests.WorkspaceRequestPolicy`, attached where the workspace
is known. The one policy defined here, :class:`BenchmarkInputs`, is for inputs that carry no
account holder's data at all, and it admits no photograph and no image.
"""

from __future__ import annotations

import copy
import dataclasses
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from exulanica.errors import ExulanicaError, PrivacyAdmissionError
from exulanica.models.choice import ChoiceRequest
from exulanica.models.handoff import ModelHandoff
from exulanica.models.manifest import Role

__all__ = [
    "BenchmarkInputs",
    "HostedRequest",
    "HostedRequestPolicy",
    "HostedRequestRefused",
    "NoHostedRequestPolicy",
    "admitted_payload",
    "request_parts",
]

#: The chat message role whose content is product instruction rather than carried text.
INSTRUCTION_ROLE = "system"

#: The payload fields that carry what a policy judges (messages and embedding inputs) or product
#: structure it does not rewrite (the numbers, the response schema the client builds, and the
#: model identifier the chain writes from the manifest). Any other field is a caller's extra
#: parameter, and one that carries text is refused, because text outside messages and inputs is
#: text no policy is shown.
_JUDGED_FIELDS = frozenset({"messages", "input"})
_STRUCTURE_FIELDS = frozenset({"max_tokens", "temperature", "response_format", "model"})
#: The fields that ask for a choice by a function. Structure only when a choice request built them.
_CHOICE_FIELDS = frozenset({"tools", "tool_choice"})
#: A message carries its text in ``content`` and nothing else; ``role`` says whose it is.
_MESSAGE_FIELDS = frozenset({"role", "content"})


class NoHostedRequestPolicy(ExulanicaError):
    """A client with no policy attached was asked to send a hosted request.

    A configuration fault, not a model failure, and deliberately not a
    :class:`~exulanica.models.errors.ModelError`: every ``except ModelError`` that degrades
    quietly, a retrieval that falls back to lexical search or a society decision recorded as
    unavailable, would otherwise turn a missing policy into a silent change of behaviour.
    """


class HostedRequestRefused(PrivacyAdmissionError):
    """A policy refused the request, and nothing was sent.

    A :class:`~exulanica.errors.PrivacyAdmissionError`, so a caller that already answers without
    a model when a right is missing answers the same way here.
    """


@dataclass(frozen=True, slots=True)
class HostedRequest:
    """One request about to leave for a hosted model, as a policy judges it."""

    role: Role
    handoff: ModelHandoff
    texts: tuple[str, ...]
    instructions: tuple[str, ...]
    photographs: frozenset[uuid.UUID]
    images: int
    #: Left out of the hash, which every other field supports: a mapping cannot be hashed.
    placeholders: Mapping[uuid.UUID, str] = dataclasses.field(
        default_factory=lambda: MappingProxyType({}), hash=False
    )


class HostedRequestPolicy(Protocol):
    """Decides what one request may carry. Raises to refuse; returns the texts as they may leave."""

    def admit(self, request: HostedRequest) -> Sequence[str]: ...


@dataclass(frozen=True, slots=True)
class BenchmarkInputs:
    """For a client whose every input carries no account holder's data.

    Public benchmark questions, invented catalogues, synthetic sentences: text somebody wrote to
    measure a model, never text from a workspace. ``reason`` says which inputs, so the attachment
    reads as the statement it is. Texts leave as written. A declared photograph or an image part is
    refused, because a photograph is account holder data whatever else is true of it; a synthetic
    or benchmark photograph goes through a workspace policy, whose right check already admits
    captures screened under a synthetic or benchmark authority.

    Product code never attaches it: ``tests/test_hosted_boundary.py`` fails when a module under
    ``exulanica/`` names it anywhere but here.
    """

    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("BenchmarkInputs states which inputs carry no account holder's data")

    def admit(self, request: HostedRequest) -> Sequence[str]:
        if request.photographs or request.images:
            raise HostedRequestRefused(
                "a client attached to benchmark inputs sends no photograph and no image; a "
                "synthetic or benchmark photograph goes through its workspace's policy"
            )
        return request.texts


def request_parts(
    payload: Mapping[str, Any], choice: ChoiceRequest | None = None
) -> tuple[tuple[str, ...], tuple[str, ...], int]:
    """``(texts, instructions, images)`` of a chat or embedding payload, in payload order.

    ``choice`` is the request's choice, when it asks a model to pick one of its options: its
    ``tools`` and ``tool_choice`` are admitted only when they are exactly that choice's, and so is
    its ``response_format``. The choice's own options and description are not among the parts
    returned here; the client shows them to every policy beside these (``ModelClient._admit``).
    """
    texts: list[str] = []
    instructions: list[str] = []
    images = 0
    if _CHOICE_FIELDS & set(payload) and (
        choice is None or not choice.carries(payload.get("tools"), payload.get("tool_choice"))
    ):
        raise HostedRequestRefused(
            "the request carries a tool that no choice request built, so its text is text no "
            "policy is shown"
        )
    if (
        choice is not None
        and "response_format" in payload
        and payload["response_format"] != choice.response_format()
    ):
        raise HostedRequestRefused(
            "the request's response format is not the one its choice built, so the options it "
            "carries are options no policy is shown"
        )
    for field, value in payload.items():
        if field in _CHOICE_FIELDS:
            continue
        if field not in _JUDGED_FIELDS | _STRUCTURE_FIELDS and _carries_text(value):
            raise HostedRequestRefused(
                f"the request field {field!r} carries text outside its messages and inputs, "
                "where no policy is shown it"
            )
    if "input" in payload:
        texts.extend(_strings(payload["input"], "input"))
    for message in payload.get("messages") or ():
        for key, value in message.items():
            if key not in _MESSAGE_FIELDS and _carries_text(value):
                raise HostedRequestRefused(
                    f"a message field {key!r} carries text outside its content, where no policy "
                    "is shown it"
                )
        into = instructions if message.get("role") == INSTRUCTION_ROLE else texts
        content = message.get("content")
        if isinstance(content, str):
            into.append(content)
            continue
        for part in _parts(content):
            kind = part.get("type")
            if kind == "text":
                into.append(_string(part.get("text"), "a text part"))
            elif kind == "image_url":
                images += 1
            else:
                raise HostedRequestRefused(
                    f"a message part of type {kind!r} is neither text nor an image, so no policy "
                    "can say what it carries"
                )
    return tuple(texts), tuple(instructions), images


def admitted_payload(payload: Mapping[str, Any], admitted: Sequence[str]) -> dict[str, Any]:
    """A copy of ``payload`` carrying ``admitted`` in place of its texts, in the same order.

    The caller's messages are not touched: a caller that repairs a refused answer appends to the
    list it sent and sends it again, and that list must still hold what the caller wrote.
    """
    remaining = list(admitted)
    result = copy.deepcopy(dict(payload))

    def take() -> str:
        if not remaining:
            raise HostedRequestRefused("a policy returned fewer texts than the request carries")
        value = remaining.pop(0)
        return _string(value, "an admitted text")

    if "input" in result:
        result["input"] = [take() for _ in _strings(result["input"], "input")]
    for message in result.get("messages") or ():
        if message.get("role") == INSTRUCTION_ROLE:
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = take()
            continue
        for part in _parts(content):
            if part.get("type") == "text":
                part["text"] = take()
    if remaining:
        raise HostedRequestRefused("a policy returned more texts than the request carries")
    return result


def _carries_text(value: Any) -> bool:
    if isinstance(value, str):
        return True
    if isinstance(value, Mapping):
        return any(_carries_text(key) or _carries_text(item) for key, item in value.items())
    if isinstance(value, list | tuple):
        return any(_carries_text(item) for item in value)
    return False


def _strings(values: Iterable[Any], where: str) -> list[str]:
    return [_string(value, where) for value in values]


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise HostedRequestRefused(f"{where} is not text, so no policy can say what it carries")
    return value


def _parts(content: Any) -> list[Mapping[str, Any]]:
    if not isinstance(content, list) or not all(isinstance(part, Mapping) for part in content):
        raise HostedRequestRefused(
            "a message content is neither text nor a list of parts, so no policy can say what it "
            "carries"
        )
    return content
