"""The person role's asks, under the names the comparison runner imports them by.

Every role is asked through one generic path (:mod:`exulanica.api.decision_host`). The comparison
of models asks a person's decisions by these names until a comparison names the role it asks;
each binds the generic path to the person role and adds nothing of its own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from exulanica.api.decision_host import (
    RoleAsk,
    answer_tokens,
    ask,
    sendable_labels,
)
from exulanica.api.decision_host import ask_bound_usd as _ask_bound_usd
from exulanica.api.decision_host import model_refusal as _model_refusal
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import AnsweringMechanism, Manifest, ModelSpec
from exulanica.world.decision_roles import DecisionContract
from exulanica.world.society_decision_contract import person_role

__all__ = ["PersonAsk", "answer_tokens", "ask_bound_usd", "ask_person", "model_refusal"]


@dataclass(frozen=True, slots=True)
class PersonAsk:
    """One reserved request of a person, the model it asks and how."""

    request: dict[str, Any]
    spec: ModelSpec
    mechanism: AnsweringMechanism


def ask_person(
    client: ModelClient,
    asked: PersonAsk,
    contract: DecisionContract,
    ends_at: float,
    *,
    keep_usd: Decimal = Decimal(0),
    keep_calls: int = 0,
) -> dict[str, Any]:
    """A person's answer, asked through the one generic path, :func:`decision_host.ask`."""
    return ask(
        client,
        RoleAsk(person_role(), asked.request, asked.spec, asked.mechanism),
        contract,
        ends_at,
        keep_usd=keep_usd,
        keep_calls=keep_calls,
    )


def ask_bound_usd(budget: BudgetGuard, spec: ModelSpec, contract: DecisionContract) -> Decimal:
    """The most one ask of ``spec`` for a person may reserve."""
    return _ask_bound_usd(person_role(), budget, spec, contract)


def model_refusal(
    client: ModelClient | None,
    manifest: Manifest,
    contract: DecisionContract,
    model: Mapping[str, str],
) -> str | None:
    """Why a person's chosen model is not asked here, or None when it may be."""
    return _model_refusal(person_role(), client, manifest, contract, model)


def _sendable_labels(
    client: ModelClient, model_id: str, labels: Sequence[str]
) -> frozenset[str] | None:
    """The labels the client's rules send as they are for ``model_id``, for a person."""
    return sendable_labels(person_role(), client, model_id, labels)
