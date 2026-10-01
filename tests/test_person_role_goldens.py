"""The person role, byte for byte: what it asks, records and does for scripted answers.

A person's decisions are kept as bytes. A request and a receipt are sealed documents that a
comparison rebuilds to the byte, a minute's state is held to its recorded digest, and a receipt
names the digest of the messages its model read. This file drives the small square in memory
(``living_square_support``) with every person at a choice point decided by scripted answers, under
the decision contract's first and second versions, and pins the SHA-256 of what the person role
produced: its requests, its receipts, what each minute did with them, the states and the events;
and, for asks through the real client behind a scripted transport, every request it sent a model
and every result it recorded. A change to one byte of any of them fails here.

The scripted answers cover what a receipt can carry: an offered option of every kind the contract
states, an answer never offered, a call that timed out, a receipt a person's own request supersedes
and one asked over an earlier minute. ``EXULANICA_PERSON_ROLE_GOLDENS=print`` prints the digests
this tree produces.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections import Counter
from decimal import Decimal
from typing import Any

import pytest
from exulanica.api.society_person_decisions import PersonAsk, ask_person
from exulanica.canonical import canonical_json
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import MANIFEST_PATH, AnsweringMechanism, parse_manifest
from exulanica.models.transport import HttpResponse
from exulanica.world.society import society_state_sha256
from exulanica.world.society_authored_ground import AUTHORED_GROUND_POPULATION
from exulanica.world.society_decision_contract import (
    PROMPT_VERSION,
    at_choice_point,
    decision_contract,
    decision_messages,
)
from exulanica.world.society_decisions import (
    person_request,
    receipt_for,
    validate_decision_receipt,
)
from exulanica.world.society_model_decisions import append_decision_events, model_goal_policies
from exulanica.world.society_planner import (
    advance_purposeful_society,
    initial_purposeful_society,
    ordered_events_document,
)

import living_square_support as square
from model_fakes import FakeTransport, RecordingPolicy, chat_body

SEED = square.DEVELOPMENT_SEEDS[0]
#: Minutes each run plays: enough for every kind of option to be chosen and applied.
MINUTES = 60
#: The two versions of the decision contract, as a request records them.
CONTRACTS = {
    "first": {"society-decision-action": 1, "society-decision-policy": 1},
    "second": {"society-decision-action": 2, "society-decision-policy": 2},
}
PROBE_RECORD = "docs/evaluation/2026-09-25-society-person-models-probe.json"
#: A clock that never moves, so every latency a receipt records is zero on every run. The asks
#: give it to the client as well as to the host, since the client measures each call's latency
#: on its own clock.
CLOCK = 1000.0
#: How long the slow transport of the control below takes to answer: real time that must not
#: reach anything the asks record.
SLOW_ANSWER_S = 0.005
#: What an answer outside the offer reads as, in every script below.
NOT_OFFERED = "fly to the moon"

#: The digests this file pins, per contract: the SHA-256 of the canonical JSON of each list.
EXPECTED = {
    "first": {
        "contract": "7c45f952b053d52ec4ef541bf49f89f6064339699e110d22e51cf0c82333d13b",
        "counts": {
            "applied_kinds": {"target": 40, "wait": 12},
            "dispositions": {
                "applied": 52,
                "rejected": 18,
                "stale": 5,
                "superseded": 1,
                "unavailable": 12,
            },
            "reasons": {
                "answer_not_offered": 17,
                "decision_context_changed": 5,
                "model_timed_out": 12,
                "person_asked_directly": 1,
                "place_taken_this_minute": 1,
                "validated_choice": 52,
            },
            "receipts": 88,
            "requests": 83,
        },
        "dispositions": "62c5b3ed7837a48aa46244ea8c9d2ea1c29089f73b58d741ce7b20ca01b74f9c",
        "events": "c2a706a5528aa16fd6bbf939a3fd7d04fa949ce6868d24ea39f81d7dca9b2a11",
        "receipts": "0cb2b5034add92178cf16cd46ffb36325591b5ed76823eb49ea7740f9760d43b",
        "requests": "755fc254c265c1ee55572711c3d381ed00df1786ae882aa1681185c6b5fd6c58",
        "states": "28fad957c548efcc95ec3bbeceb59e21022f1bbab969d6fb05bdcfcf32891865",
    },
    "second": {
        "contract": "d38ae0c9c085c74c92d25656ce4c0a5eea89ff11fa149125e6199284b2152a92",
        "counts": {
            "applied_kinds": {"stand": 7, "talk": 2, "target": 32, "wait": 6},
            "dispositions": {
                "applied": 47,
                "rejected": 15,
                "stale": 4,
                "superseded": 2,
                "unavailable": 16,
            },
            "reasons": {
                "answer_not_offered": 15,
                "decision_context_changed": 4,
                "model_timed_out": 16,
                "person_asked_directly": 2,
                "validated_choice": 47,
            },
            "receipts": 84,
            "requests": 79,
        },
        "dispositions": "af11543d5bb7ca15bca063c3805a2e5a2d367cd71ef18862bec671212d17e659",
        "events": "371178a78de94e38849a20b4ae7cb917948266d5ef3e462258a8a3735da619ea",
        "receipts": "36a5d866d1b09e4c03c5ba972eb40b1eeb9d43355256f7944ddc5f1c6d67edc9",
        "requests": "7cde14fb0c62515e39e3229c1ba15f2c694c262f4d25a9bd5c90291620317144",
        "states": "bd59ec1642046f940586a4d71b09611a6b317b50af11b223102eadb5cb296c85",
    },
}
#: The asks: every request sent to a scripted model, and every result recorded.
EXPECTED_ASKS = {
    "counts": {
        "asks": 16,
        "mechanisms": {"json_schema": 8, "tool_call": 8},
        "outcomes": {"answer_not_offered": 3, "validated_choice": 13},
        "sent": 27,
    },
    "results": "42f4464a7dfa355b89ac84d4d2ec8963dba739a92afc64ecd7ef91a98a447545",
    "sent": "2a5c778d8d2d5959461104ca70a6b8d18b60cf28cbef7c88a9fb0850558ada50",
}


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _wire_digest(value: Any) -> str:
    """The SHA-256 of what went over the wire, as JSON with sorted keys: a request carries its
    temperature as a float, which canonical JSON refuses by design."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _number(text: str) -> int:
    return int(text[:12], 16)


def _config(contract) -> dict[str, Any]:
    return {
        "provider": "example_provider",
        "model_id": "example/model",
        "mechanism": "tool_call",
        "choice_seq": 1,
        "manifest_sha256": "a" * 64,
        "prompt_version": PROMPT_VERSION,
        "contract": contract.binding(),
        "deadline_ms": contract.value("decision_deadline_ms"),
    }


def _call(request: dict[str, Any], *, answers: int, outcome: str) -> dict[str, Any]:
    """The call record a receipt carries, scripted: the model, how it was asked, what it cost."""
    return {
        "provider": "example_provider",
        "model_id": "example/model",
        "served_model_id": "example/model" if outcome == "completed" else None,
        "mechanism": "tool_call",
        "prompt_version": PROMPT_VERSION,
        "messages_sha256": society_state_sha256(
            decision_messages(request["context"], AnsweringMechanism.TOOL_CALL)
        ),
        "answers_asked": answers,
        "calls": [{"outcome": outcome, "attempt": index} for index in range(answers)],
        "prompt_tokens": 100 * answers,
        "completion_tokens": 20 * answers,
        "cost_usd": f"0.{answers:08d}",
        "cost_known": True,
        "latency_ms": 700 * answers,
    }


def _answer(request: dict[str, Any]) -> dict[str, Any]:
    """A scripted result, decided by the request's own digest: mostly an offered option."""
    number = _number(request["document_sha256"])
    options = request["context"]["options"]
    if number % 7 == 5:
        return {
            "status": "rejected",
            "reason": "answer_not_offered",
            "proposal": None,
            "provider": _call(request, answers=2, outcome="completed"),
        }
    if number % 7 == 6:
        return {
            "status": "unavailable",
            "reason": "model_timed_out",
            "proposal": None,
            "provider": _call(request, answers=1, outcome="timed_out"),
        }
    option = options[(number // 7) % len(options)]
    return {
        "status": "accepted",
        "reason": "validated_choice",
        "proposal": {"label": option["label"], "option": option},
        "provider": _call(request, answers=1, outcome="completed"),
    }


def _run(versions: dict[str, int]) -> dict[str, Any]:
    """Every person at a choice point asked, each minute, under the contract of ``versions``."""
    contract = decision_contract(versions)
    document = square.compose(square.square_objects())
    state = initial_purposeful_society(
        square.SOCIETY, SEED, document, population=AUTHORED_GROUND_POPULATION
    )
    requests: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    dispositions: list[list[Any]] = []
    states: list[str] = []
    events: list[Any] = []
    sequence = 0
    previous: dict[str, Any] | None = None
    for _minute in range(MINUTES):
        people = sorted(
            (person for person in state["inhabitants"] if at_choice_point(person)),
            key=lambda person: person["id"],
        )
        asked = []
        for person in people:
            request, _status = person_request(
                state,
                document,
                person["id"],
                request_id=uuid.uuid5(square.SOCIETY, f"golden:{person['id']}:{state['tick']}"),
                contract=contract,
                seed=SEED,
                provider_config=_config(contract),
            )
            if request is not None:
                asked.append(request)
        minute_receipts = []
        for request in asked:
            sequence += 1
            receipt = receipt_for(request, sequence, _answer(request))
            validate_decision_receipt(receipt, request)
            minute_receipts.append(receipt)
        # A receipt asked over the minute before, consumed now: stale by name.
        if state["tick"] % 10 == 7 and previous is not None:
            sequence += 1
            receipt = receipt_for(previous, sequence, _answer(previous))
            validate_decision_receipt(receipt, previous)
            minute_receipts.append(receipt)
        # A person's own request this minute supersedes their model's.
        directed: dict[str, dict[str, Any]] = {}
        if state["tick"] % 10 == 3 and asked:
            directed[asked[0]["subject_id"]] = {"allowed_target_ids": [], "wait": True}
        policies, decided = model_goal_policies(state, document, minute_receipts, directed)
        after, minute_events = advance_purposeful_society(
            state, SEED, [document], goal_policy=policies
        )
        minute_events = append_decision_events(
            state, after, document, minute_receipts, decided, minute_events
        )
        requests.extend(asked)
        receipts.extend(minute_receipts)
        dispositions.extend(
            [d.decision_seq, d.subject_id, d.disposition, d.reason] for d in decided
        )
        states.append(society_state_sha256(after))
        events.extend(minute_events)
        previous = asked[0] if asked else None
        state = after
    applied_kinds = Counter(
        receipt["proposal"]["option"]["kind"]
        for receipt, disposition in zip(receipts, dispositions, strict=True)
        if disposition[2] == "applied"
    )
    return {
        "contract": contract.binding(),
        "requests": requests,
        "receipts": receipts,
        "dispositions": dispositions,
        "states": states,
        "events": ordered_events_document(tuple(events)),
        "counts": {
            "requests": len(requests),
            "receipts": len(receipts),
            "dispositions": dict(sorted(Counter(d[2] for d in dispositions).items())),
            "reasons": dict(sorted(Counter(d[3] for d in dispositions).items())),
            "applied_kinds": dict(sorted(applied_kinds.items())),
        },
    }


def _digests(run: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = {key: _digest(run[key]) for key in run if key != "counts"}
    found["counts"] = run["counts"]
    return found


def _report(name: str, found: Any) -> None:
    if os.environ.get("EXULANICA_PERSON_ROLE_GOLDENS") == "print":
        print(f"\n{name} = {json.dumps(found, indent=4, sort_keys=True)}")


@pytest.mark.parametrize("version", sorted(CONTRACTS))
def test_the_person_role_records_and_applies_the_same_bytes(version):
    run = _run(CONTRACTS[version])
    found = _digests(run)
    _report(version, found)
    # Each run exercised what it is meant to pin: choices applied of every kind its contract
    # states, answers refused and timed out, receipts stale and superseded.
    kinds = {"first": {"target", "wait"}, "second": {"target", "wait", "stand", "talk"}}[version]
    assert set(run["counts"]["applied_kinds"]) == kinds, run["counts"]
    assert {"answer_not_offered", "model_timed_out", "decision_context_changed"} <= set(
        run["counts"]["reasons"]
    ), run["counts"]
    assert "person_asked_directly" in run["counts"]["reasons"], run["counts"]
    assert found == EXPECTED[version]


def _manifest():
    """The manifest with two example models the person role may be asked by: one verified by a
    forced function, one by a schema first, each at stated prices, so no catalog refresh moves a
    digest here."""
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    template = next(
        raw
        for _model_id, raw in sorted(document["models"].items())
        if raw.get("answering") and raw["min_max_tokens"] is not None
    )
    fixed = {
        "provider": template["provider"],
        "input_usd_per_mtok": Decimal("0.10"),
        "output_usd_per_mtok": Decimal("0.40"),
        "context_window_tokens": 131072,
        "min_max_tokens": 64,
        "default_max_tokens": 512,
        "catalog_use_cases": ["text", "function_calling"],
    }
    document["models"]["example/tool-model"] = {
        **template,
        **fixed,
        "description": "Example tool model, asked by a forced function",
        "answering": {"tool_call": PROBE_RECORD},
    }
    document["models"]["example/tool-model"].pop("answering_order", None)
    document["models"]["example/schema-model"] = {
        **template,
        **fixed,
        "description": "Example schema model, asked by a schema first",
        "answering": {"tool_call": PROBE_RECORD, "json_schema": PROBE_RECORD},
        "answering_order": {
            "mechanisms": ["json_schema", "tool_call"],
            "record": PROBE_RECORD,
            "reason": "A stated order, so this file asks one model by each mechanism.",
        },
    }
    return parse_manifest(document)


class _Scripted(FakeTransport):
    """A model that answers each ask by a label its offer holds, chosen by the offer's digest;
    for some offers it first answers with a label never offered, and for some it never offers one
    at all."""

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        if "tools" in payload:
            enum = payload["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
        else:
            schema = payload["response_format"]["json_schema"]["schema"]
            enum = schema["properties"]["action"]["enum"]
        number = _number(_digest(enum))
        retried = len(payload["messages"]) > 2
        if number % 4 == 3 or (number % 4 == 1 and not retried):
            label = NOT_OFFERED
        else:
            label = enum[number % len(enum)]
        body = chat_body(
            "", model=payload["model"], prompt_tokens=300, completion_tokens=40, reasoning_tokens=10
        )
        if "tools" in payload:
            body["choices"][0]["finish_reason"] = "tool_calls"
            body["choices"][0]["message"]["content"] = None
            body["choices"][0]["message"]["tool_calls"] = [
                {
                    "id": "call",
                    "type": "function",
                    "function": {"name": "act", "arguments": json.dumps({"action": label})},
                }
            ]
        else:
            body["choices"][0]["message"]["content"] = json.dumps({"action": label})
        return HttpResponse(200, json.dumps(body))


class _Slow(_Scripted):
    """The scripted model, answering only after some real time has passed."""

    def post_json(self, url, *, headers, payload, timeout):
        time.sleep(SLOW_ANSWER_S)
        return super().post_json(url, headers=headers, payload=payload, timeout=timeout)


def _asks(transport: _Scripted, *, frozen: bool = True) -> dict[str, Any]:
    """The first sixteen asks of the second contract's run, through the real client behind
    ``transport``: what was sent, what was recorded, and their counts. With ``frozen`` the client
    reads the test's clock; without it, its own default, the real monotonic clock."""
    manifest = _manifest()
    contract = decision_contract(CONTRACTS["second"])
    requests = _run(CONTRACTS["second"])["requests"][:16]
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("5"), max_calls=1000),
        **({"clock": lambda: CLOCK} if frozen else {}),
    ).with_policy(RecordingPolicy())
    results = []
    for index, request in enumerate(requests):
        spec = manifest.spec(("example/tool-model", "example/schema-model")[index % 2])
        mechanism = contract.mechanism_for(spec)
        assert mechanism is not None
        results.append(
            ask_person(client, PersonAsk(request, spec, mechanism), contract, CLOCK + 20)
        )
    sent = [
        {key: request["payload"][key] for key in sorted(request["payload"])}
        for request in transport.requests
    ]
    return {
        "sent": _wire_digest(sent),
        "results": _wire_digest(results),
        "counts": {
            "asks": len(results),
            "sent": len(sent),
            "outcomes": dict(sorted(Counter(r["reason"] for r in results).items())),
            "mechanisms": dict(
                sorted(Counter(r["provider"]["mechanism"] for r in results).items())
            ),
        },
    }


def test_the_person_role_sends_and_records_the_same_bytes(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: CLOCK)
    found = _asks(_Scripted())
    _report("asks", found)
    # The script exercised a retry that was answered, one that was not, and both mechanisms.
    assert found["counts"]["outcomes"].keys() == {"validated_choice", "answer_not_offered"}
    assert found["counts"]["mechanisms"].keys() == {"tool_call", "json_schema"}
    assert found["counts"]["sent"] > found["counts"]["asks"]
    assert found == EXPECTED_ASKS


def test_the_asks_record_no_real_time(monkeypatch):
    """A control for the golden above: real time passes during and between the calls, and nothing
    the asks record moves. Its other arm is the client on its own clock, the real one, which the
    same slow answers do reach: the control can see what it says is absent."""
    monkeypatch.setattr(time, "monotonic", lambda: CLOCK)
    assert _asks(_Slow()) == EXPECTED_ASKS
    unfrozen = _asks(_Slow(), frozen=False)
    assert unfrozen["sent"] == EXPECTED_ASKS["sent"]
    assert unfrozen["results"] != EXPECTED_ASKS["results"]
