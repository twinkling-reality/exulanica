"""A line a society of things' person says, asked of a model and checked before it is said.

What is shown here, with no database, through the host's one ask path:

*   a v7 person is asked under its engine's own terms: the third catalogs, the second prompt, a
    choice that takes a line where an option says something, and messages that ask for the line;
*   an answer naming a say option with a line is accepted with the line in its proposal, and the
    receipt binds it;
*   an answer naming a say option with no line, or another option with one, is asked once more,
    as an option not offered is;
*   a line that breaks the line rule is refused ``line_out_of_bounds``, and one the workspace's
    rules would change, as they change a saved name, ``line_refused_by_rules``: neither is said.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import time
import uuid
from decimal import Decimal

from exulanica.api.society_person_decisions import PersonAsk, ask_person
from exulanica.canonical import canonical_json
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import MANIFEST_PATH, AnsweringMechanism, parse_manifest
from exulanica.models.transport import HttpResponse
from exulanica.world.society import society_state_sha256
from exulanica.world.society_decision_contract import (
    choice_options,
    decision_context,
    person_role,
)
from exulanica.world.society_decisions import receipt_for, seal, validate_decision_receipt
from exulanica.world.society_things import THINGS_PROFILE, initial_things_society

from model_fakes import FakeTransport, RecordingPolicy, chat_body
from things_society_support import SEED, SOCIETY, compose, thing

PROBE_RECORD = "docs/evaluation/2026-09-25-society-person-models-probe.json"
GATE = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
KNIGHT = thing("knight", "knight", 1, 3_000, 3_000)
#: A word standing for a name an account holder saved: the rules a test client applies change it.
SAVED = "Ashworth"


class _Rules(RecordingPolicy):
    """A workspace's rules as a test states them: they change every text naming ``SAVED``."""

    def admit(self, request):
        self.requests.append(request)
        return tuple(text.replace(SAVED, "someone") for text in request.texts)


def _things_terms():
    return person_role().terms(THINGS_PROFILE)


def _asked():
    """A knight standing beside a villager, asked under the society of things' terms."""
    document = compose((GATE, KNIGHT))
    state = initial_things_society(SOCIETY, SEED, document, population=6)
    knight = next(p for p in state["inhabitants"] if p["came_by"] == "placed")
    villager = next(p for p in state["inhabitants"] if p["came_by"] == "populated")
    state = copy.deepcopy(state)
    near = next(p for p in state["inhabitants"] if p["id"] == villager["id"])
    near["position_mm"] = [knight["position_mm"][0] + 2_000, knight["position_mm"][1]]
    contract = person_role().contract(_things_terms().versions)
    options = choice_options(state, document, knight["id"], contract, seed=SEED)
    return state, document, knight, contract, options


def _request(state, document, subject, options, contract, *, model):
    context = decision_context(state, document, subject, options)
    return seal(
        {
            "profile": person_role().request_profile,
            "request_id": str(uuid.uuid5(SOCIETY, f"{subject}:{state['tick']}")),
            "subject_id": subject,
            "branch_id": state["branch_id"],
            "base_tick": state["tick"],
            "base_state_sha256": society_state_sha256(state),
            "input_seq": document["input_seq"],
            "input_sha256": document["document_sha256"],
            "context": context,
            "context_sha256": society_state_sha256(context),
            "provider_config": {
                "provider": "example_provider",
                "model_id": model,
                "mechanism": "tool_call",
                "choice_seq": 1,
                "manifest_sha256": "a" * 64,
                "prompt_version": _things_terms().prompt_version,
                "contract": contract.binding(),
                "deadline_ms": 20000,
            },
        }
    )


def _manifest():
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    model_id = next(
        model_id
        for model_id, raw in sorted(document["models"].items())
        if raw["min_max_tokens"] is not None and "text" in raw["catalog_use_cases"]
    )
    document["models"][model_id]["answering"] = {"tool_call": PROBE_RECORD}
    return parse_manifest(document), model_id


def _reply(arguments: dict, model: str) -> HttpResponse:
    body = chat_body("", model=model, finish_reason="tool_calls")
    body["choices"][0]["message"]["content"] = None
    body["choices"][0]["message"]["tool_calls"] = [
        {
            "id": "c",
            "type": "function",
            "function": {"name": "act", "arguments": json.dumps(arguments)},
        }
    ]
    return HttpResponse(200, json.dumps(body))


def _ask(replies, *, rules=None):
    state, document, knight, contract, options = _asked()
    manifest, model_id = _manifest()
    request = _request(state, document, knight["id"], options, contract, model=model_id)
    transport = FakeTransport([_reply(reply, model_id) for reply in replies])
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10),
        policy=rules or RecordingPolicy(),
    )
    result = ask_person(
        client,
        PersonAsk(request, manifest.spec(model_id), AnsweringMechanism.TOOL_CALL),
        contract,
        time.monotonic() + 20.0,
    )
    return request, result, transport, options


def _say_all(options):
    return next(option for option in options if option.kind == "say_all")


def test_a_said_line_is_accepted_beside_its_option_and_bound_by_the_receipt():
    _state, _document, _knight, _contract, options = _asked()
    say = _say_all(options)
    request, result, transport, _options = _ask([{"action": say.label, "line": "Good morning."}])
    assert (result["status"], result["reason"]) == ("accepted", "validated_choice")
    assert result["proposal"] == {
        "label": say.label,
        "option": say.as_record(),
        "line": "Good morning.",
    }
    assert result["provider"]["prompt_version"] == "society-person-choice/v2"
    validate_decision_receipt(receipt_for(request, 1, result), request)
    # Asked under the engine's own terms: a choice with a line, and its instruction.
    (sent,) = transport.requests
    (tool,) = sent["payload"]["tools"]
    assert tool["function"]["parameters"]["properties"]["line"]["maxLength"] == 200
    assert sent["payload"]["messages"][0]["content"] == _things_terms().instruction
    assert "line" in sent["payload"]["messages"][-1]["content"]


def test_a_line_where_none_is_said_or_none_where_one_is_is_asked_once_more():
    _state, _document, _knight, _contract, options = _asked()
    say = _say_all(options)
    wait = next(option for option in options if option.kind == "wait")
    _request_doc, result, transport, _options = _ask(
        [{"action": say.label, "line": None}, {"action": wait.label, "line": "Hello."}]
    )
    assert (result["status"], result["reason"]) == ("rejected", "answer_not_offered")
    assert transport.call_count == 2
    second = transport.requests[1]["payload"]["messages"]
    assert second[-1]["content"] == _things_terms().not_offered
    # The positive control: the answer asked once more is taken when it is right.
    _request_doc, result, _transport, _options = _ask(
        [{"action": say.label, "line": None}, {"action": wait.label, "line": None}]
    )
    assert (result["status"], result["proposal"]["label"]) == ("accepted", wait.label)
    assert "line" not in result["proposal"]


def test_a_line_that_breaks_the_rule_or_would_be_changed_by_the_rules_is_never_said():
    _state, _document, _knight, _contract, options = _asked()
    say = _say_all(options)
    _request_doc, result, _transport, _options = _ask(
        [{"action": say.label, "line": "one line\nand another"}]
    )
    assert (result["status"], result["reason"], result["proposal"]) == (
        "rejected",
        "line_out_of_bounds",
        None,
    )
    _request_doc, result, _transport, _options = _ask(
        [{"action": say.label, "line": f"Say hello to {SAVED}."}], rules=_Rules()
    )
    assert (result["status"], result["reason"], result["proposal"]) == (
        "rejected",
        "line_refused_by_rules",
        None,
    )
    # The positive control: the same rules let a line naming nobody be said.
    _request_doc, result, _transport, _options = _ask(
        [{"action": say.label, "line": "Say hello to everyone."}], rules=_Rules()
    )
    assert result["proposal"]["line"] == "Say hello to everyone."


#: The SHA-256 of the canonical bytes of what the second prompt sends for the knight's request, by
#: mechanism; ``EXULANICA_LINE_GOLDENS=print`` prints what this tree produces.
MESSAGES_SHA256 = {
    "tool_call": "a2bf22558cc35aa52e28fadc81130f37e476cc05e12e213fe0183dc6249b616e",
    "json_schema": "72d2fa95af73c191731df8faa659a70bfe81b848dfd8f3760315d7a3eee5df3a",
}


def test_the_second_prompt_is_kept_as_bytes():
    state, document, knight, contract, options = _asked()
    request = _request(state, document, knight["id"], options, contract, model="example/model")
    role = person_role()
    found = {
        mechanism.value: hashlib.sha256(
            canonical_json(role.adapter.messages(role, request["context"], mechanism))
        ).hexdigest()
        for mechanism in (AnsweringMechanism.TOOL_CALL, AnsweringMechanism.JSON_SCHEMA)
    }
    if os.environ.get("EXULANICA_LINE_GOLDENS") == "print":
        print(json.dumps(found, indent=2))
    assert found == MESSAGES_SHA256
