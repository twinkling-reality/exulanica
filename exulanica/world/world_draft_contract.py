"""Sealed operation and request terms for durable world drafting."""

from __future__ import annotations

import re
import uuid
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
        or not _reference_or_none(document.get("reference_id"))
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
    # The bounds a start opened, where it states them: one for each of the quote's providers,
    # never above its ceiling there and with its calls, so a start never funds more than quoted.
    funding = document.get("funding")
    if funding is None:
        return
    quoted = {row["provider"]: row for row in providers}
    if not isinstance(funding, list) or sorted(
        row.get("provider") for row in funding if isinstance(row, Mapping)
    ) != sorted(quoted):
        raise ValueError("world_draft_definition_invalid")
    for row in funding:
        amount = Decimal(row["ceiling_usd"])
        if (
            not amount.is_finite()
            or not 0 < amount <= Decimal(quoted[row["provider"]]["ceiling_usd"])
            or row.get("max_calls") != quoted[row["provider"]]["max_calls"]
        ):
            raise ValueError("world_draft_definition_invalid")


def _reference_or_none(value: Any) -> bool:
    """Whether a definition's ``reference_id`` is absent or names a request by its id: the web notes
    a start asked its draft to be made with (docs/reference-notes-contract.md section 9)."""
    if value is None:
        return True
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def reference_of(definition: Mapping[str, Any]) -> uuid.UUID | None:
    """The web notes request a draft's definition names, or None for a draft drafted from its words
    alone."""
    value = definition.get("reference_id")
    return None if value is None else uuid.UUID(value)


def funding_of(definition: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The bounds a draft's definition was funded with: its stored ``funding`` (each provider's
    bound at the lesser of its quoted ceiling and what its grant had left), or, for a draft started
    before funding was stored, its operation's own provider ceilings."""
    return list(definition.get("funding") or definition["quote"]["providers"])
