"""A workspace Companion proposal, whose confirmation uses the ordinary world-draft POST."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from exulanica.world.model_probe_contract import seal

PROFILE = "exulanica.companion-world-draft-plan/v1"
OPERATION = "POST /worlds/drafts"


def digest(plan: Mapping[str, Any]) -> str:
    return seal({k: v for k, v in plan.items() if k != "plan_sha256"})["document_sha256"]


def prepare_world_draft(
    description: str, idempotency_key: uuid.UUID, offer: Mapping[str, Any]
) -> dict[str, Any]:
    quote = offer.get("operation")
    refused = not offer["offered"] or quote is None
    body = (
        None
        if refused
        else dict(
            description=description,
            idempotency_key=str(idempotency_key),
            operation=quote,
            maximum_usd=quote["maximum_usd"],
        )
    )
    plan = dict(
        profile=PROFILE,
        outcome="refused" if refused else "plan",
        refusal=None if not refused else {"code": offer["code"] or "world_draft_price_unavailable"},
        steps=[]
        if refused
        else [
            dict(
                index=0,
                action={"operation": "draft_world"},
                operation=OPERATION,
                bind={},
                query={},
                body=body,
                state="prepared",
                confirmation="required",
                spends=True,
                cost=quote,
                readback="GET /worlds/drafts/{draft_id}",
            )
        ],
    )
    plan["plan_sha256"] = digest(plan)
    return plan
