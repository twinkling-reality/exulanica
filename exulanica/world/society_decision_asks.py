"""A recorded decision asked again of another model, and kept beside the answer the world used
(migration 0216). Never applied: nothing here is read by a society's minute, input or transition.

A society's decision request holds what a character was told and the options it had; its receipt
is the answer the society took up. Asking another model the *identical* request means the same
context and options, sent by the role the request's contract names, under the terms it was asked
under. :func:`reproduced` proves that before anything is sent: the role's terms for the context
still carry the request's prompt version, the contract at the request's catalog versions is the
one it recorded, and the role's first messages for the context, by the mechanism the first model
answered by, still digest to what that model's receipt recorded. A model that answers by another
mechanism is sent the same messages but for the words describing how to answer; both digests are
kept.

:func:`record` appends an ask; :func:`asks` reads them back; :func:`comparison` sets them beside the
original: each model, what it chose, whether the choice and its kind match the original's, and
what it cost. A person's last :data:`ASK_AGAIN_MOST` answered decisions are what one comparison of a
character asks again, each of a chosen model and once more of the model that answered it
(:func:`exulanica.api.decision_asks.ask_again_offer` states what that would cost before anything is
asked).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.errors import ExulanicaError
from exulanica.models.manifest import AnsweringMechanism, ModelSpec
from exulanica.world.decision_roles import (
    DecisionContract,
    DecisionRole,
    RoleRefused,
    RoleTerms,
    decision_roles,
)
from exulanica.world.society import UnknownSociety, society_state_sha256
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_repository import SocietyRepository

__all__ = [
    "ASK_AGAIN_MOST",
    "ASK_AGAIN_SCAN",
    "ASK_REFUSALS",
    "MAX_BOUND_USD",
    "DecisionAskRefused",
    "Recorded",
    "Reproduced",
    "asks",
    "comparison",
    "earlier_ask",
    "record",
    "recorded",
    "reproduced",
]

#: The most one ask may spend: a few answers of the largest model a person may choose.
MAX_BOUND_USD: Final = Decimal("0.10")

#: The most recorded decisions of one person a comparison asks again: a stretch of a run long enough
#: to show how often two models choose alike, short enough that its asks finish in about a minute.
ASK_AGAIN_MOST: Final = 12

#: How many of a person's newest decisions are read to find their last answered ones: a decision a
#: model never answered (timed out, refused) is skipped, so a few times as many as are asked.
ASK_AGAIN_SCAN: Final = 4 * ASK_AGAIN_MOST

#: Why a recorded decision is not asked again, by code.
ASK_REFUSALS: Final = {
    "decision_not_answered": "no model answered this request, so there is nothing to compare",
    "decision_not_reproducible": (
        "the request can no longer be sent as it was: its role's terms or messages changed"
    ),
    "not_the_same_request": "the rules this model is asked under would not send every option",
    "bound_out_of_range": (
        f"an ask's bound is at least what one answer needs and at most {MAX_BOUND_USD} USD"
    ),
}


class DecisionAskRefused(ExulanicaError):
    """A recorded decision not asked again, by code."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        if code not in ASK_REFUSALS:
            raise ValueError(f"unknown ask refusal {code!r}")
        super().__init__(f"{code}: {detail or ASK_REFUSALS[code]}")
        self.code = code
        self.detail = detail or ASK_REFUSALS[code]


@dataclass(frozen=True, slots=True)
class Recorded:
    """A recorded request, the receipt the society took up, and the society they belong to."""

    society_id: uuid.UUID
    engine: str
    request: dict[str, Any]
    decision: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class Reproduced:
    """What the request was asked under, proved again: its role, terms, contract, the mechanism
    the first model answered by, and the digest of the messages that model read."""

    role: DecisionRole
    terms: RoleTerms
    contract: DecisionContract
    mechanism: AnsweringMechanism
    messages_sha256: str


def recorded(society: SocietyRepository, version_id: uuid.UUID, request_id: uuid.UUID) -> Recorded:
    """The request and its receipt, read as the decision read route reads them (its inputs
    authorized), or :class:`~exulanica.world.society.UnknownSociety`."""
    read = SocietyDecisionRepository(society).read(version_id, request_id)
    row = society._row(version_id)
    if row is None:
        raise UnknownSociety("society is unavailable")
    return Recorded(
        society_id=row["society_id"],
        engine=row["engine_version"],
        request=read["request"],
        decision=read["decision"],
    )


def reproduced(held: Recorded) -> Reproduced:
    """Prove the request can be sent again exactly as the first model read it, or refuse."""
    decision = held.decision
    provider = None if decision is None else decision.get("provider")
    if not isinstance(provider, Mapping) or not isinstance(provider.get("messages_sha256"), str):
        raise DecisionAskRefused("decision_not_answered")
    config = held.request.get("provider_config")
    if not isinstance(config, Mapping) or not isinstance(config.get("contract"), Mapping):
        raise DecisionAskRefused("decision_not_answered")
    try:
        role = decision_roles().for_contract(config["contract"])
        contract = role.contract(dict(config["contract"]["catalog_versions"]))
        mechanism = AnsweringMechanism(str(config["mechanism"]))
    except (RoleRefused, KeyError, TypeError, ValueError) as exc:
        raise DecisionAskRefused("decision_not_reproducible") from exc
    context = held.request["context"]
    terms = role.terms_of(context)
    if terms.prompt_version != config.get("prompt_version") or contract.sha256 != config[
        "contract"
    ].get("sha256"):
        raise DecisionAskRefused("decision_not_reproducible")
    digest = society_state_sha256(role.adapter.messages(role, context, mechanism))
    if digest != provider["messages_sha256"]:
        raise DecisionAskRefused("decision_not_reproducible")
    return Reproduced(role, terms, contract, mechanism, digest)


_COLUMNS: Final = (
    "ask_id, request_id, asked_by, idempotency_key, provider, model_id, mechanism, "
    "prompt_version, messages_sha256, request_messages_sha256, bound_id, bound_usd, status, "
    "reason, document, asked_at"
)


def earlier_ask(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    society_id: uuid.UUID,
    asked_by: uuid.UUID,
    idempotency_key: uuid.UUID,
) -> dict[str, Any] | None:
    """The ask ``asked_by`` made under ``idempotency_key``, or None."""
    with connection.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            f"select {_COLUMNS} from world_society_decision_ask where workspace_id=%s "
            "and society_id=%s and asked_by=%s and idempotency_key=%s",
            (workspace_id, society_id, asked_by, idempotency_key),
        ).fetchone()


def record(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    held: Recorded,
    *,
    ask_id: uuid.UUID,
    asked_by: uuid.UUID,
    idempotency_key: uuid.UUID | None,
    spec: ModelSpec,
    mechanism: AnsweringMechanism,
    prompt_version: str,
    messages_sha256: str,
    request_messages_sha256: str,
    bound_id: uuid.UUID | None,
    bound_usd: Decimal,
    answer: Mapping[str, Any],
) -> dict[str, Any]:
    """Append the ask and its answer beside its request, and answer the row."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "insert into world_society_decision_ask (workspace_id, society_id, request_id, ask_id, "
            "asked_by, idempotency_key, provider, model_id, mechanism, prompt_version, "
            "messages_sha256, request_messages_sha256, bound_id, bound_usd, status, reason, "
            f"document) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            f"returning {_COLUMNS}",
            (
                workspace_id,
                held.society_id,
                held.request["request_id"],
                ask_id,
                asked_by,
                idempotency_key,
                spec.provider,
                spec.model_id,
                mechanism.value,
                prompt_version,
                messages_sha256,
                request_messages_sha256,
                bound_id,
                bound_usd,
                answer["status"],
                answer["reason"],
                Jsonb(dict(answer)),
            ),
        ).fetchone()
    assert row is not None
    return row


def asks(
    connection: psycopg.Connection, workspace_id: uuid.UUID, held: Recorded
) -> list[dict[str, Any]]:
    """Every ask of the request, oldest first."""
    with connection.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            f"select {_COLUMNS} from world_society_decision_ask where workspace_id=%s "
            "and society_id=%s and request_id=%s order by asked_at, ask_id",
            (workspace_id, held.society_id, held.request["request_id"]),
        ).fetchall()


def _answer(proposal: Any, provider: Any) -> dict[str, Any]:
    """What one answer chose and what it cost, as a comparison states it."""
    option = proposal.get("option") if isinstance(proposal, Mapping) else None
    return {
        "chose": proposal.get("label") if isinstance(proposal, Mapping) else None,
        "kind": option.get("kind") if isinstance(option, Mapping) else None,
        "line": proposal.get("line") if isinstance(proposal, Mapping) else None,
        "served_model_id": provider.get("served_model_id")
        if isinstance(provider, Mapping)
        else None,
        "cost_usd": provider.get("cost_usd") if isinstance(provider, Mapping) else None,
        "cost_known": provider.get("cost_known") if isinstance(provider, Mapping) else None,
        "prompt_tokens": provider.get("prompt_tokens") if isinstance(provider, Mapping) else None,
        "completion_tokens": (
            provider.get("completion_tokens") if isinstance(provider, Mapping) else None
        ),
        "latency_ms": provider.get("latency_ms") if isinstance(provider, Mapping) else None,
    }


def comparison(held: Recorded, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The original answer and every ask, each ask with whether its choice and its kind are the
    original's."""
    decision = held.decision or {}
    provider = decision.get("provider")
    original = {
        "provider": provider.get("provider") if isinstance(provider, Mapping) else None,
        "model_id": provider.get("model_id") if isinstance(provider, Mapping) else None,
        "status": decision.get("status"),
        "reason": decision.get("reason"),
        **_answer(decision.get("proposal"), provider),
    }
    views = []
    for row in rows:
        document = row["document"]
        answer = _answer(document.get("proposal"), document.get("provider"))
        views.append(
            {
                "ask_id": str(row["ask_id"]),
                "provider": row["provider"],
                "model_id": row["model_id"],
                "mechanism": row["mechanism"],
                "status": row["status"],
                "reason": row["reason"],
                **answer,
                "same_choice": answer["chose"] is not None and answer["chose"] == original["chose"],
                "same_kind": answer["kind"] is not None and answer["kind"] == original["kind"],
                "same_messages": row["messages_sha256"] == row["request_messages_sha256"],
                "bound_usd": str(row["bound_usd"]),
                "asked_at": row["asked_at"].isoformat(),
            }
        )
    return {
        "request_id": str(held.request["request_id"]),
        "base_tick": held.request.get("base_tick"),
        "original": original,
        "asks": views,
    }
