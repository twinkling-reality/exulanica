"""A fixed product probe, its prepared inputs, and deterministic receipt replay.

The probe exercises one registered role's plain choices and spoken lines. A workspace record
cannot author cases, a threshold or a licence class. Completion is distinct from passing, and
passing this probe alone does not install a model in the execution manifest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.models.choice import ChoiceRefused
from exulanica.models.manifest import AnsweringMechanism, ModelSpec
from exulanica.models.provider_catalog import ProviderModel, ProviderPrice
from exulanica.things.lines import LineRefused, check_line
from exulanica.world.decision_roles import decision_roles
from exulanica.world.role_decisions import names_its_listener
from exulanica.world.society_planner import input_sha256

PROFILE: Final = "exulanica.model-probe-definition/v1"
RECEIPT_PROFILE: Final = "exulanica.model-probe-receipt/v1"
OUTCOME_PROFILE: Final = "exulanica.model-probe-outcome/v1"
BOOK: Final = Path(__file__).with_name("model-probe.v1.json")
_ROOT: Final = Path(__file__).resolve().parents[2]


def seal(document: dict[str, Any]) -> dict[str, Any]:
    document["document_sha256"] = input_sha256(document)
    return document


def case_book() -> tuple[dict[str, Any], str]:
    """Read authored cases only while their role's source contracts still match."""
    raw = BOOK.read_bytes()
    book = json.loads(raw)
    if any(
        hashlib.sha256((_ROOT / name).read_bytes()).hexdigest() != digest
        for name, digest in book["sources"].items()
    ):
        raise ValueError("model_probe_contract_changed")
    role = decision_roles().role(book["role"])
    cases = book["cases"]
    if len(cases) != book["plain_cases"] + book["line_cases"]:
        raise ValueError("model_probe_cases_invalid")
    for index, context in enumerate(cases):
        if role.takes_line(context) != (index >= book["plain_cases"]):
            raise ValueError("model_probe_cases_invalid")
        role.choice(context)
        if index >= book["plain_cases"] and len(role.line_labels(context)) != len(
            context["options"]
        ):
            raise ValueError("model_probe_line_not_exercised")
    return book, hashlib.sha256(raw).hexdigest()


def prepare_definition(
    stated: ProviderModel,
    price: ProviderPrice,
    *,
    added_seq: int,
    added_sha256: str,
    catalog_sha256: str,
    price_read_at: str,
) -> dict[str, Any]:
    """Bind a live provider rate and a fixed operation estimate to one adding of a model."""
    book, digest = case_book()
    if price.model_id != stated.model_id or price.context_window_tokens < book["answer_tokens"]:
        raise ValueError("model_probe_context_too_small")
    role = decision_roles().role(book["role"])
    contract = role.contract_for(book["engine"])
    calls = len(book["cases"]) * len(book["mechanisms"])
    # A context-window ceiling, rather than a character/token conversion claimed as exact.
    # Output is part of that window on some providers; counting it again is conservative.
    upper = (
        Decimal(price.context_window_tokens) * price.input_usd_per_mtok
        + Decimal(book["answer_tokens"]) * price.output_usd_per_mtok
    ) / 1_000_000
    return seal(
        {
            "profile": PROFILE,
            "provider": stated.provider,
            "model_id": stated.model_id,
            "added_seq": added_seq,
            "added_sha256": added_sha256,
            "catalog_sha256": catalog_sha256,
            "stated": asdict(stated),
            "price": {
                "input_usd_per_mtok": str(price.input_usd_per_mtok),
                "output_usd_per_mtok": str(price.output_usd_per_mtok),
                "context_window_tokens": price.context_window_tokens,
                "response_sha256": price.response_sha256,
                "read_at": price_read_at,
            },
            "cases_sha256": digest,
            "messages_sha256": hashlib.sha256(
                canonical_json(
                    [
                        role.adapter.messages(role, context, AnsweringMechanism(mechanism))
                        for mechanism in book["mechanisms"]
                        for context in book["cases"]
                    ]
                )
            ).hexdigest(),
            "role": book["role"],
            "engine": book["engine"],
            "contract": dict(contract.versions),
            "prompt_version": role.terms(book["engine"]).prompt_version,
            "deadline_ms": contract.value("decision_deadline_ms"),
            "answer_tokens": book["answer_tokens"],
            "mechanisms": book["mechanisms"],
            "operation_estimate": {
                "basis": "context_window_upper_bound",
                "max_calls": calls,
                "ceiling_usd": str(upper * calls),
                "rates_live_read": True,
                "inference_verified": False,
            },
        }
    )


def validate_definition(definition: Mapping[str, Any]) -> dict[str, Any]:
    book, digest = case_book()
    if (
        definition.get("profile") != PROFILE
        or definition.get("document_sha256") != input_sha256(dict(definition))
        or definition.get("cases_sha256") != digest
        or definition.get("role") != book["role"]
        or definition.get("engine") != book["engine"]
        or definition.get("mechanisms") != book["mechanisms"]
        or definition.get("answer_tokens") != book["answer_tokens"]
    ):
        raise ValueError("model_probe_definition_changed")
    role = decision_roles().role(book["role"])
    messages_digest = hashlib.sha256(
        canonical_json(
            [
                role.adapter.messages(role, context, AnsweringMechanism(mechanism))
                for mechanism in book["mechanisms"]
                for context in book["cases"]
            ]
        )
    ).hexdigest()
    if definition.get("messages_sha256") != messages_digest:
        raise ValueError("model_probe_contract_changed")
    if (
        definition["contract"] != dict(role.contract_for(book["engine"]).versions)
        or definition["prompt_version"] != role.terms(book["engine"]).prompt_version
        or definition["deadline_ms"]
        != role.contract_for(book["engine"]).value("decision_deadline_ms")
    ):
        raise ValueError("model_probe_contract_changed")
    return book


def candidate_spec(definition: Mapping[str, Any]) -> ModelSpec:
    """Candidate metadata for this probe only, with no answering evidence installed."""
    validate_definition(definition)
    stated, price = definition["stated"], definition["price"]
    return ModelSpec(
        model_id=definition["model_id"],
        provider=definition["provider"],
        description=definition["model_id"],
        input_usd_per_mtok=Decimal(price["input_usd_per_mtok"]),
        output_usd_per_mtok=Decimal(price["output_usd_per_mtok"]),
        context_window_tokens=price["context_window_tokens"],
        min_max_tokens=definition["answer_tokens"],
        default_max_tokens=definition["answer_tokens"],
        emits_inline_reasoning=False,
        supports_json_schema=True,
        catalog_type=stated["type"],
        catalog_use_cases=tuple(stated["use_cases"]),
        catalog_license=stated["licence_stated"],
        region_informational="",
    )


def probe_requests(definition: Mapping[str, Any]) -> list[dict[str, Any]]:
    book = validate_definition(definition)
    role = decision_roles().role(book["role"])
    requests = []
    for mechanism in book["mechanisms"]:
        for index, context in enumerate(book["cases"]):
            messages = role.adapter.messages(role, context, AnsweringMechanism(mechanism))
            requests.append(
                seal(
                    {
                        "case_seq": len(requests) + 1,
                        "case_index": index,
                        "mechanism": mechanism,
                        "takes_line": role.takes_line(context),
                        "context_sha256": hashlib.sha256(canonical_json(context)).hexdigest(),
                        "messages_sha256": hashlib.sha256(canonical_json(messages)).hexdigest(),
                        "definition_sha256": definition["document_sha256"],
                    }
                )
            )
    return requests


def answer_valid(definition: Mapping[str, Any], case_seq: int, answer: Any) -> bool:
    """The actual role choice and line rules, independently rechecked during replay."""
    book = validate_definition(definition)
    requests = probe_requests(definition)
    if not 1 <= case_seq <= len(requests):
        return False
    context = book["cases"][requests[case_seq - 1]["case_index"]]
    role = decision_roles().role(book["role"])
    try:
        label, line = role.choice(context).answer_with_line(answer)
        if (label in role.line_labels(context)) != bool(line):
            return False
        if line is not None:
            if check_line(line, maximum=context["line_characters_maximum"]) != line:
                return False
            option = next(o for o in context["options"] if o["label"] == label)
            request = {
                "context": context,
                "provider_config": {
                    "prompt_version": definition["prompt_version"],
                    "contract": {"catalog_versions": definition["contract"]},
                },
            }
            if names_its_listener(role, request, option, line):
                return False
        return True
    except (ChoiceRefused, LineRefused, ValueError, TypeError, KeyError):
        return False


def replay_outcome(
    definition: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Derive completion and verdict from bound receipts; trust no stored verified assertion."""
    book = validate_definition(definition)
    requests = probe_requests(definition)
    totals = {key: {"plain": 0, "line": 0} for key in book["mechanisms"]}
    complete = len(receipts) == len(requests)
    for index, receipt in enumerate(receipts):
        if (
            index >= len(requests)
            or receipt.get("profile") != RECEIPT_PROFILE
            or receipt.get("request") != requests[index]
            or receipt.get("document_sha256") != input_sha256(dict(receipt))
        ):
            raise ValueError("model_probe_receipt_mismatch")
        calls = receipt["calls"]
        identity = (
            len(calls) == 1
            and calls[0].get("provider") == definition["provider"]
            and calls[0].get("role") == definition["role"]
            and calls[0].get("requested_model") == definition["model_id"]
            and calls[0].get("served_model") == definition["model_id"]
            and calls[0].get("outcome") == "completed"
            and calls[0].get("used_fallback") is False
            and calls[0].get("attempts") == 1
            and calls[0].get("latency_ms", definition["deadline_ms"] + 1)
            <= definition["deadline_ms"]
        )
        if receipt["outcome"] not in ("answered", "invalid") or not identity:
            complete = False
        if (
            receipt["outcome"] == "answered"
            and identity
            and answer_valid(definition, index + 1, receipt["answer"])
        ):
            request = requests[index]
            totals[request["mechanism"]]["line" if request["takes_line"] else "plain"] += 1
    mechanisms = {
        key: {
            **counts,
            "answers": complete and counts["plain"] >= book["plain_at_least"],
            "answers_lines": complete and counts["line"] >= book["line_at_least"],
        }
        for key, counts in totals.items()
    }
    return seal(
        {
            "profile": OUTCOME_PROFILE,
            "definition_sha256": definition["document_sha256"],
            "receipt_sha256s": [r["document_sha256"] for r in receipts],
            "finished": complete,
            "verified": complete and any(value["answers"] for value in mechanisms.values()),
            "mechanisms": mechanisms,
        }
    )


def replay_terminal(
    definition: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    recorded: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconstruct a terminal record, including its interruption, without trusting its verdict."""
    if recorded.get("code") not in ("completed", "not_finished", "cancelled", "stale"):
        raise ValueError("model_probe_outcome_mismatch")
    outcome = replay_outcome(definition, receipts)
    if recorded["code"] != "completed":
        outcome["finished"] = outcome["verified"] = False
        for result in outcome["mechanisms"].values():
            result["answers"] = result["answers_lines"] = False
    outcome = seal({**outcome, "code": recorded["code"], "reason": recorded["reason"]})
    if outcome != dict(recorded):
        raise ValueError("model_probe_outcome_mismatch")
    return outcome
