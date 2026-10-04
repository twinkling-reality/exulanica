"""The query planner and the appearance drafter against a reply that runs on, with no database.

The same three bounds as the Companion's action drafters (``test_companion_draft_runaways``): each
form is sent with its lists last, each reply has its own ceiling, and a cut reply is repaired by
how it ran on. The lists are put last only in the schema sent to the model; the models, and the API
that describes them, keep their own order.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.response import Runaway
from exulanica.models.schema import response_format_for
from exulanica.models.transport import HttpResponse
from exulanica.selection import planner, proposal
from exulanica.selection.plan import EntitySelector, Intent, SelectionPlan
from exulanica.selection.request_names import RequestNames
from exulanica.selection.runaway_repair import RUNAWAY_REPAIRS
from exulanica.world import STYLE_REGISTRY

from form_shapes import arrays_followed_by_a_property
from model_fakes import FakeTransport, RecordingPolicy, chat_body

EXTRACTOR = load_manifest()[Role.STRUCTURED_EXTRACTION].primary.model_id


def _client(*responses: HttpResponse) -> tuple[ModelClient, FakeTransport]:
    transport = FakeTransport(list(responses))
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10),
        policy=RecordingPolicy(),
    )
    return client, transport


def _reply(text: str, *, finish_reason: str = "stop") -> HttpResponse:
    body = chat_body(text, model=EXTRACTOR, finish_reason=finish_reason)
    return HttpResponse(status_code=200, text=json.dumps(body))


def _ran_on_in_whitespace() -> HttpResponse:
    return _reply(
        '{\n  "intent": "content",\n  "content": {"scope"' + "\n   " * 300, finish_reason="length"
    )


def _unordered(schema):
    """``schema`` with every key and every ``required`` list sorted: what it says, not its order."""
    if isinstance(schema, dict):
        return {
            key: sorted(value) if key == "required" else _unordered(value)
            for key, value in sorted(schema.items())
        }
    if isinstance(schema, list):
        return [_unordered(item) for item in schema]
    return schema


def _appearance_form() -> type:
    catalogue = (
        proposal.SourceChoice(
            source_id=uuid.UUID(int=1),
            evidence_span_id=uuid.UUID(int=2),
            region_id="region-a",
            slot_key="slot-00",
        ),
    )
    return proposal._draft_model(proposal._proposable_profiles(STYLE_REGISTRY), catalogue)


# -- the order the model sees --------------------------------------------------------------------


def test_the_planners_lists_are_sent_last_and_only_when_asked():
    sent = response_format_for(SelectionPlan, arrays_last=True)["json_schema"]["schema"]
    assert arrays_followed_by_a_property(sent) == []
    unordered = response_format_for(SelectionPlan)["json_schema"]["schema"]
    assert sorted(arrays_followed_by_a_property(unordered)) == [
        "$.entities|0.ids (followed by mode)",
        "$.time (followed by place)",
    ]


def test_the_appearance_drafts_references_are_sent_last():
    form = _appearance_form()
    sent = response_format_for(form, arrays_last=True)["json_schema"]["schema"]
    assert arrays_followed_by_a_property(sent) == []
    assert list(sent["properties"])[-1] == "references"
    assert arrays_followed_by_a_property(response_format_for(form)["json_schema"]["schema"]) == [
        "$.references (followed by spoken)"
    ]


def test_the_order_sent_changes_no_model_and_no_api_description():
    # The model's own schema, which the API describes, keeps its field order.
    assert list(SelectionPlan.model_json_schema()["properties"])[:4] == [
        "intent",
        "entities",
        "time",
        "place",
    ]
    assert list(EntitySelector.model_json_schema()["properties"]) == ["ids", "mode"]
    # The same fields, types and requirements either way: only the order differs.
    plain = response_format_for(SelectionPlan)["json_schema"]["schema"]
    ordered = response_format_for(SelectionPlan, arrays_last=True)["json_schema"]["schema"]
    assert _unordered(plain) == _unordered(ordered)
    assert list(plain["properties"]) != list(ordered["properties"])


def test_a_plan_parses_to_the_same_model_whatever_order_its_keys_came_in():
    plan = SelectionPlan(
        intent=Intent.CAPTURES, entities=EntitySelector(ids=[uuid.UUID(int=5)], mode="any")
    )
    written = plan.model_dump(mode="json")
    lists_last = {key: written[key] for key in written if key != "time"} | {"time": written["time"]}
    lists_last["entities"] = {"mode": "any", "ids": [str(uuid.UUID(int=5))]}
    parsed = []
    for body in (written, lists_last):
        client, _transport = _client(_reply(json.dumps(body)))
        parsed.append(
            client.structured(
                Role.STRUCTURED_EXTRACTION,
                [{"role": "user", "content": "x"}],
                SelectionPlan,
                prompt_version="test",
                arrays_last=True,
            ).value
        )
    assert parsed[0] == parsed[1] == plan


# -- the planner -----------------------------------------------------------------------------------


def test_the_planner_sends_its_lists_last_within_its_ceiling_and_names_how_a_reply_ran_on():
    plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query="harbour")
    client, transport = _client(_ran_on_in_whitespace(), _reply(plan.model_dump_json()))

    proposed = planner.propose_plan(client, "which photographs?", (), names=RequestNames(()))

    assert proposed == plan
    first, second = (request["payload"] for request in transport.requests)
    # The request names the schema it was sent with, and that is the one the reply was held to.
    assert first["response_format"] == response_format_for(SelectionPlan, arrays_last=True)
    assert [first["max_tokens"], second["max_tokens"]] == [planner.PLANNER_MAX_TOKENS] * 2
    assert (
        load_manifest()[Role.STRUCTURED_EXTRACTION].default_max_tokens > planner.PLANNER_MAX_TOKENS
    )
    assert second["messages"][-1] == {
        "role": "user",
        "content": RUNAWAY_REPAIRS[Runaway.WHITESPACE],
    }


# -- the appearance drafter ------------------------------------------------------------------------


def test_the_appearance_drafter_has_its_own_ceiling_above_the_roles_floor():
    binding = load_manifest()[Role.STRUCTURED_EXTRACTION]
    assert binding.min_max_tokens < proposal.DRAFT_MAX_TOKENS < binding.default_max_tokens


def test_the_appearance_drafter_sends_its_references_last():
    from test_selection_proposal import catalogue, current_reference, draft, reply

    client, transport = _client(reply(draft()))
    proposal.draft_appearance(client, "softer horizon", current_reference(), catalogue())

    (request,) = transport.requests
    sent = request["payload"]["response_format"]["json_schema"]["schema"]
    assert arrays_followed_by_a_property(sent) == []
    assert list(sent["properties"])[-1] == "references"
    assert request["payload"]["max_tokens"] == proposal.DRAFT_MAX_TOKENS
