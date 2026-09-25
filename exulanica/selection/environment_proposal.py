"""Bounded natural-language proposals for authored environment edits.

The model fills one field: an operation enum assembled from actions the authoritative
client/server context supports. Identifiers, source bindings, transforms, origin
roles, and base digests never enter model output. This module returns a proposal and performs no
write. The utterance is sent with every saved name no right can release replaced, and a place's
name left to the boundary every hosted request passes, which sends it only under the account
holder's right for this role (:class:`~exulanica.selection.request_names.RequestNames`).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field, create_model

from exulanica.models.client import ModelClient
from exulanica.models.errors import StructuredOutputError, TruncatedResponseError
from exulanica.models.manifest import Role
from exulanica.selection.calls import CallLog, ModelCall
from exulanica.selection.request_names import RequestNames
from exulanica.selection.validation import Session

__all__ = [
    "ENVIRONMENT_PROMPT_VERSION",
    "EnvironmentOperation",
    "EnvironmentProposalDecision",
    "EnvironmentProposalRefusal",
    "draft_environment_operation",
    "propose_environment_operation",
]

ENVIRONMENT_PROMPT_VERSION: Final = "environment-proposal-1"
_ATTEMPTS: Final = 2


class EnvironmentOperation(StrEnum):
    PLACE_SELECTED_FEATURE = "place_selected_feature"
    REMOVE_SELECTED_AUTHORED_INSTANCE = "remove_selected_authored_instance"
    UNDO_LATEST_VERSION_EDIT = "undo_latest_version_edit"


class EnvironmentRefusalCode(StrEnum):
    UNSUPPORTED = "unsupported"
    NOT_DRAFTED = "not_drafted"


@dataclass(frozen=True, slots=True)
class EnvironmentProposalRefusal:
    code: EnvironmentRefusalCode
    detail: str


@dataclass(frozen=True, slots=True)
class EnvironmentProposalDecision:
    operation: EnvironmentOperation | None
    refusal: EnvironmentProposalRefusal | None
    model_id: str | None
    calls: tuple[ModelCall, ...]


_SYSTEM: Final = """You select one supported operation for an environment editing panel.
You do not apply anything. The person will see an exact typed preview and must apply or discard it.

Choose an operation only when the request directly asks for it. A request to move, resize, rotate,
restyle, blend, generate, extract, inspect, search, or change source data is unsupported. Do not
approximate it with another operation. Use null when none of the offered operations exactly matches.

The form contains only an operation enum or null. You cannot provide identifiers, geometry,
transforms, roles, source bindings, explanations, or executable text."""


def _draft_model(
    operations: Sequence[EnvironmentOperation],
) -> type[BaseModel]:
    values = tuple(operation.value for operation in operations)
    return create_model(
        "EnvironmentOperationDraft",
        __config__=ConfigDict(extra="forbid"),
        operation=(
            Literal[values] | None,  # type: ignore[valid-type]
            Field(
                description=(
                    "The exact supported operation requested, or null when none is an exact match."
                )
            ),
        ),
    )


def draft_environment_operation(
    client: ModelClient,
    utterance: str,
    operations: Sequence[EnvironmentOperation],
    *,
    placeholders: Mapping[uuid.UUID, str] | None = None,
    log: CallLog | None = None,
) -> EnvironmentProposalDecision:
    """Select one offered operation, with one repair and no fallback mutation.

    ``placeholders`` is the request's record of the names in ``utterance``, handed to the
    boundary with the request. ``log`` is the request's own record, which hears every attempt
    when ``client`` is the request's copy (``ModelClient.with_attempts``).
    """
    if not operations:
        return EnvironmentProposalDecision(
            operation=None,
            refusal=EnvironmentProposalRefusal(
                EnvironmentRefusalCode.UNSUPPORTED,
                "the current selection offers no supported environment operation",
            ),
            model_id=None,
            calls=(),
        )
    schema = _draft_model(operations)
    offered = "\n".join(f"- {operation.value}" for operation in operations)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"Supported operations for the current authoritative context:\n{offered}\n\n"
                f'The person typed:\n"""{utterance}"""'
            ),
        },
    ]
    log = CallLog() if log is None else log
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            drafted = client.structured(
                Role.STRUCTURED_EXTRACTION,
                messages,
                schema,
                prompt_version=ENVIRONMENT_PROMPT_VERSION,
                placeholders=placeholders,
            )
            log.record(drafted.call)
            value = drafted.value.operation
            if value is None:
                return EnvironmentProposalDecision(
                    operation=None,
                    refusal=EnvironmentProposalRefusal(
                        EnvironmentRefusalCode.UNSUPPORTED,
                        "the request does not exactly match a supported environment operation",
                    ),
                    model_id=drafted.call.served_model_id,
                    calls=log.calls,
                )
            return EnvironmentProposalDecision(
                operation=EnvironmentOperation(value),
                refusal=None,
                model_id=drafted.call.served_model_id,
                calls=log.calls,
            )
        except (StructuredOutputError, TruncatedResponseError) as rejected:
            if attempt == _ATTEMPTS:
                return EnvironmentProposalDecision(
                    operation=None,
                    refusal=EnvironmentProposalRefusal(
                        EnvironmentRefusalCode.NOT_DRAFTED,
                        "the model could not choose a supported typed operation",
                    ),
                    model_id=None,
                    calls=log.calls,
                )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "The form was refused. Return only one offered operation or null. "
                        f"Validator: {rejected}"
                    ),
                }
            )
    raise AssertionError("unreachable")


def propose_environment_operation(
    connection: psycopg.Connection,
    client: ModelClient,
    utterance: str,
    session: Session,
    operations: Sequence[EnvironmentOperation],
) -> EnvironmentProposalDecision:
    """Draft the operation an utterance asks for, with the utterance's saved names decided first.

    The request sends through its own copy of the client, so its record lists every attempt it
    paid for; an error that ends it carries that record to the problem body.
    """
    log = CallLog()
    try:
        names = RequestNames.read(connection, session.workspace_id)
        return draft_environment_operation(
            client.with_attempts(log.attempt),
            names.sendable(utterance),
            operations,
            placeholders=names.placeholders,
            log=log,
        )
    except Exception as failed:
        log.on_failure(ENVIRONMENT_PROMPT_VERSION).note(failed)
        raise
