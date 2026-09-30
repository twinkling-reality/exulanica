"""Versioned bounded model proposals; no provider call occurs during simulation replay.

The social society's own profile is kept here: ``v1`` (``exulanica-society/v3``), a structured
proposal of a known target or a wait. Its engine and its proposal route are retired, so nothing
asks for one or records a new one; a stored request and receipt of it are checked here, read back
and replayed. Every other request and receipt a society stores is a decision role's
(:mod:`exulanica.world.decision_roles`), read by the role whose registry entry names its profile,
the person's first: one of the options the role's contract offered, asked of the model the world's
owner chose, with the provider, the mechanism, every attempt and the cost it paid recorded on the
receipt, checked by the one generic path (:mod:`exulanica.world.role_decisions`). A request of no
profile either names is refused by name. A receipt of any profile is replayed from what it stores,
never asked again.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from exulanica.world.decision_roles import DecisionContract, RoleOption, decision_roles
from exulanica.world.role_decisions import (
    PROVIDER_CONFIG,
    PROVIDER_RECORD,
    RECEIPT_STATUSES,
    RESULT_BYTES,
    check_envelope,
    role_request,
    seal,
    sealed_receipt,
    validate_role_receipt,
    validate_role_request,
)
from exulanica.world.society_decision_contract import person_role

__all__ = [
    "DECISION_PROFILE",
    "PERSON_PROVIDER_CONFIG",
    "PERSON_PROVIDER_RECORD",
    "REQUEST_PROFILE",
    "GoalProposal",
    "person_request",
    "receipt_for",
    "seal",
    "validate_decision_receipt",
    "validate_decision_request",
]

REQUEST_PROFILE = "exulanica.society-decision-request/v1"
DECISION_PROFILE = "exulanica.society-decision/v1"
#: What a role's request and receipt record about the model and the call, by the names the
#: comparison modules read until a comparison names the role it asks.
PERSON_PROVIDER_CONFIG = PROVIDER_CONFIG
PERSON_PROVIDER_RECORD = PROVIDER_RECORD


class GoalProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["choose_goal", "wait"]
    target_id: Annotated[str, Field(min_length=1, max_length=1000)] | None


def person_request(
    state: dict,
    document: dict,
    subject_id: str,
    *,
    request_id: uuid.UUID,
    contract: DecisionContract,
    seed: str,
    provider_config: dict,
    offer: Callable[[Sequence[RoleOption]], Sequence[RoleOption]] | None = None,
) -> tuple[dict | None, str]:
    """A person's sealed request, as :func:`~exulanica.world.role_decisions.role_request` seals
    any role's, under the person role. The comparison modules build one here until a comparison
    names the role it asks."""
    return role_request(
        person_role(),
        state,
        document,
        subject_id,
        request_id=request_id,
        contract=contract,
        seed=seed,
        provider_config=provider_config,
        offer=offer,
    )


def _v1_request(document: dict) -> None:
    check_envelope(document, (REQUEST_PROFILE,))


def validate_decision_request(document: dict) -> None:
    """A stored or rebuilt request: the social society's own profile, or a registered role's."""
    if document.get("profile") == REQUEST_PROFILE:
        _v1_request(document)
        return
    role = decision_roles().for_request(str(document.get("profile")))
    if role is None:
        raise ValueError("invalid recorded decision request")
    validate_role_request(role, document)


def receipt_for(request: dict, sequence: int, result: dict) -> dict:
    """The receipt of ``request``'s answer, under the profile its request's profile records."""
    validate_decision_request(request)
    if request["profile"] == REQUEST_PROFILE:
        return sealed_receipt(DECISION_PROFILE, request, sequence, result)
    role = decision_roles().for_request(request["profile"])
    assert role is not None  # validate_decision_request refused any other profile
    return sealed_receipt(role.receipt_profile, request, sequence, result)


def validate_decision_receipt(document: dict, request: dict) -> None:
    if request.get("profile") == REQUEST_PROFILE:
        result = {key: document[key] for key in ("status", "reason", "proposal", "provider")}
        if result["status"] not in RECEIPT_STATUSES:
            raise ValueError("invalid decision status")
        if result["proposal"] is not None:
            GoalProposal.model_validate(result["proposal"])
        if document != receipt_for(request, document["decision_seq"], result):
            raise ValueError("decision receipt request binding mismatch")
        # Provider metadata stays serializable and bounded without admitting arbitrary output.
        if len(json.dumps(result)) > RESULT_BYTES:
            raise ValueError("decision result exceeds bound")
        return
    role = decision_roles().for_request(str(request.get("profile")))
    if role is None:
        raise ValueError("invalid recorded decision request")
    validate_role_receipt(role, document, request)
