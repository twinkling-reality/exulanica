"""Sealed operation and request terms for durable world drafting."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from exulanica.world.model_probe_contract import seal

QUOTE_PROFILE = "exulanica.world-draft-operation/v1"
DEFINITION_PROFILE = "exulanica.world-draft-definition/v1"
OUTCOME_PROFILE = "exulanica.world-draft-result/v1"


def validate_definition(document: Mapping[str, Any]) -> None:
    quote = document.get("quote")
    if (
        document.get("profile") != DEFINITION_PROFILE
        or not isinstance(quote, Mapping)
        or quote.get("profile") != QUOTE_PROFILE
        or seal(dict(quote))["document_sha256"] != quote.get("document_sha256")
        or not isinstance(document.get("manifest_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", document["manifest_sha256"]) is None
        or type(document.get("deadline_seconds")) is not int
        or not 1 <= document["deadline_seconds"] <= 86400
    ):
        raise ValueError("world_draft_definition_invalid")
    providers = quote.get("providers")
    if not isinstance(providers, list) or not providers:
        raise ValueError("world_draft_definition_invalid")
    total = Decimal(0)
    keys = set()
    calls = 0
    for row in providers:
        key = row.get("provider")
        amount = Decimal(row["ceiling_usd"])
        if (
            not isinstance(key, str)
            or key in keys
            or not amount.is_finite()
            or amount <= 0
            or type(row.get("max_calls")) is not int
            or row["max_calls"] < 1
        ):
            raise ValueError("world_draft_definition_invalid")
        keys.add(key)
        total += amount
        calls += row["max_calls"]
    if str(total) != quote.get("maximum_usd") or calls != quote.get("calls_at_most"):
        raise ValueError("world_draft_definition_invalid")
