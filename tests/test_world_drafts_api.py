"""``POST /worlds/specification/drafts``: a description drafted into a proposal the specification's
own validation judges, sampled when valid, refused by name when nothing in it is a town, answered
503 with no model, and nothing written. The specification document and its validation are the
stand-ins the drafter's tests use."""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import Mapping
from typing import Any

import pytest
from exulanica.api import permissions
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.routes import world_drafts
from exulanica.api.services import Services
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import BudgetExceededError, TransportError
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.selection.look_choosing import CHOOSER_ROLE, LookOption, render_request
from exulanica.selection.world_drafting import DRAFTER_ROLE
from exulanica.world import specification_source
from exulanica.world.specification_samples import Counted, TownSample
from exulanica.world.specification_source import ValueRefusal
from exulanica.world.style_pack_library import style_pack_library
from fastapi.testclient import TestClient

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from model_fakes import FakeTransport, chat_body
from test_companion_saved_names import named as saved_named  # noqa: F401
from tests_support_api import EVERY_PERMISSION, scratch_database
from world_specification_standin import specification_document

pytestmark = pytest.mark.postgres

TOKEN = "world-drafts-owner-token-at-least-32-chars"
NO_MODEL_TOKEN = "world-drafts-no-model-token-at-least-32-chars"
DRAFTER = load_manifest()[DRAFTER_ROLE].primary.model_id
CHOOSER = load_manifest()[CHOOSER_ROLE].primary.model_id


def _form(**changes: Any) -> dict[str, Any]:
    form: dict[str, Any] = {
        "preset": "small_town",
        "fit": "all",
        "not_supported": [],
        "city_extent_x_mm": None,
        "block_length_mm": None,
        "storey_band_low": None,
        "storey_band_high": None,
    }
    form.update(changes)
    return form


def _reply(form: dict[str, Any]) -> HttpResponse:
    return HttpResponse(
        status_code=200, text=json.dumps(chat_body(json.dumps(form), model=DRAFTER))
    )


class _Samples:
    def __init__(self) -> None:
        self.asked: list[tuple[str, dict[str, int | str]]] = []

    def sample(self, preset: str, values: Mapping[str, int | str], sha256: str) -> TownSample:
        self.asked.append((preset, dict(values)))
        return TownSample(
            status="sampled",
            tiles=int(values["city_extent_x_mm"]) // 128000,
            people=46,
            vehicles=9,
            streets=(Counted("high_street", "High street", 1),),
            premises=(Counted("cafe", "Cafe", 4),),
            buildings=23,
        )


def _standin_refusal(preset: str, values: Mapping[str, int | str]) -> ValueRefusal | None:
    """The stand-in validation: three tiles need blocks of 130 m or more (the stand-in's other rule,
    two tiles with blocks of 120 m or less, is not needed by these tests)."""
    if values["city_extent_x_mm"] == 384000 and int(values["block_length_mm"]) < 130000:
        return ValueRefusal(
            code="specification_values_disagree",
            detail="three tiles generate with blocks of 130 m or more",
            key="block_length_mm",
            value=values["block_length_mm"],
            minimum=130000,
            maximum=140000,
            step=10000,
        )
    return None


@pytest.fixture(name="named")
def _named_alias(request):
    """A photograph of a person and a place, named Maria Estrada and Lantern House by the
    account holder, the product's own way (tests/test_companion_saved_names.py)."""
    return request.getfixturevalue("saved_named")


@pytest.fixture
def drafts(named, spine_schema, monkeypatch):
    _psycopg, scratch = spine_schema
    repository, store, _session, entities = named
    place = entities["place"]
    repository.connection.commit()
    grant = {"workspace_id": str(repository.workspace_id), "actor": str(uuid.uuid4())}
    no_model = [p for p in EVERY_PERMISSION if p != str(permissions.Permission.MODEL_INVOKE)]
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {**grant, "permissions": EVERY_PERMISSION},
                NO_MODEL_TOKEN: {**grant, "permissions": no_model},
            }
        ),
    )
    samples = _Samples()
    monkeypatch.setattr(specification_source, "served_document", specification_document)
    monkeypatch.setattr(specification_source, "value_refusal", _standin_refusal)
    monkeypatch.setattr(world_drafts, "sample_worker", lambda: samples)
    transport = FakeTransport()
    database = scratch_database(scratch)

    def app(model: bool = True) -> TestClient:
        return TestClient(
            create_app(
                Services(
                    database=database,
                    readonly_database=database,
                    store=store,
                    tokens=load_token_directory(),
                    executor_shares_the_write_role=True,
                    model_client=ModelClient(
                        api_key="test-key-not-real",
                        transport=transport,
                        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
                    )
                    if model
                    else None,
                ),
                verify=False,
            )
        )

    return app, transport, samples, place


def _draft(client: TestClient, description: str, token: str = TOKEN):
    return client.post(
        "/worlds/specification/drafts",
        headers={"Authorization": f"Bearer {token}"},
        json={"description": description},
    )


def test_a_description_becomes_a_proposal_the_specification_judges_and_a_sample(drafts):
    app, transport, samples, _place = drafts
    transport.responses.append(
        _reply(
            _form(
                preset="market_town",
                storey_band_high=5,
                fit="part",
                not_supported=["harbour like [place A]", "where [person A] lives"],
            )
        )
    )
    description = (
        "A market town with taller buildings, where Maria lives, a harbour like lantern house"
    )

    with app() as client:
        response = _draft(client, description)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["description"] == description
    assert body["refusal"] is None
    proposal = body["proposal"]
    assert proposal["preset"] == "market_town"
    assert proposal["values"] == {
        "city_extent_x_mm": 384000,
        "block_length_mm": 140000,
        "storey_band_low": 2,
        "storey_band_high": 5,
    }
    assert proposal["set_by_words"] == ["storey_band_high"]
    assert proposal["valid"] is True and proposal["value_refusal"] is None
    assert proposal["sample"]["people"] == 46 and proposal["sample"]["tiles"] == 3
    assert samples.asked == [("market_town", proposal["values"])]
    # The person's own words, the saved name written back for the person who typed it.
    # The person's own words, as typed: never a saved name, whole or as saved.
    assert body["not_supported"] == ["harbour like lantern house", "where Maria lives"]
    assert "Estrada" not in response.text and "Lantern House" not in response.text
    assert body["model_id"] == DRAFTER
    assert body["model_name"] == load_manifest().model_name(DRAFTER)
    assert body["prompt_version"] == "world-drafting-2"
    assert [call["role"] for call in body["execution"]["calls"]] == [str(DRAFTER_ROLE)]
    # No saved name left the server, a place's included.
    sent = json.dumps(transport.requests[0]["payload"]).lower()
    assert "lantern" not in sent and "maria" not in sent and "estrada" not in sent
    # Asked with the ceiling the role declares, as the comparison that chose its model was.
    declared = load_manifest()[DRAFTER_ROLE].max_tokens
    assert declared is not None
    assert transport.requests[0]["payload"]["max_tokens"] == declared.value


def test_a_proposal_the_validation_refuses_is_returned_refused_by_name_and_not_sampled(drafts):
    app, transport, samples, _ = drafts
    transport.responses.append(_reply(_form(city_extent_x_mm=384000, fit="all")))

    with app() as client:
        response = _draft(client, "a long town of three tiles")

    proposal = response.json()["proposal"]
    assert proposal["valid"] is False
    assert proposal["value_refusal"] == {
        "code": "specification_values_disagree",
        "detail": "three tiles generate with blocks of 130 m or more",
        "key": "block_length_mm",
        "value": 90000,
        "minimum": 130000,
        "maximum": 140000,
        "step": 10000,
        "choices": [],
        "with_key": None,
        "with_value": None,
    }
    assert proposal["sample"] is None and samples.asked == []


def test_nothing_a_town_can_be_is_refused_by_name_with_nothing_sampled(drafts):
    app, transport, samples, _ = drafts
    transport.responses.append(
        _reply(_form(fit="none", not_supported=["a floating city in the clouds"]))
    )

    with app() as client:
        body = _draft(client, "a floating city in the clouds").json()

    assert body["proposal"] is None
    assert body["refusal"]["code"] == "description_not_supported"
    assert body["not_supported"] == ["a floating city in the clouds"]
    assert samples.asked == []
    # A refused draft is offered no look, and the look step asks nothing.
    assert body["look_offer"] is None and transport.call_count == 1


def test_without_a_model_the_route_says_so_and_asks_for_nothing(drafts, monkeypatch):
    app, transport, _, _ = drafts

    def unread() -> Mapping[str, Any]:
        raise AssertionError("the specification is read only once a model can be asked")

    monkeypatch.setattr(specification_source, "served_document", unread)
    with app(model=False) as client:
        response = _draft(client, "a small town")

    assert response.status_code == 503
    assert transport.call_count == 0


def test_drafting_needs_the_accounts_model_right(drafts):
    app, transport, _, _ = drafts

    with app() as client:
        response = _draft(client, "a small town", token=NO_MODEL_TOKEN)

    assert response.status_code == 403
    assert transport.call_count == 0


def test_a_description_of_nothing_but_spaces_is_refused_before_any_model_is_asked(drafts):
    app, transport, _, _ = drafts

    with app() as client:
        response = _draft(client, "   \n\t ")

    assert response.status_code == 422
    assert transport.call_count == 0


def test_a_description_past_its_ceiling_is_refused_before_any_model_is_asked(drafts):
    app, transport, _, _ = drafts

    with app() as client:
        response = _draft(client, "a" * 1001)

    assert response.status_code == 422
    assert transport.call_count == 0


# -- the look offered after the draft ------------------------------------------------------------


def _choice(look: str | None, words: list[str]) -> HttpResponse:
    content = json.dumps({"look": look, "look_words": words})
    return HttpResponse(status_code=200, text=json.dumps(chat_body(content, model=CHOOSER)))


def _payload_bytes(request: Mapping[str, Any]) -> bytes:
    return json.dumps(
        {"url": request["url"], "payload": request["payload"]}, sort_keys=True
    ).encode()


def test_a_look_the_words_ask_for_is_offered_in_the_persons_own_words(drafts):
    app, transport, _, _ = drafts
    transport.responses += [
        _reply(_form(fit="part", not_supported=["a harbour like it"])),
        _choice("exulanica.cozy-town", ["cozy", "warm evening light like [place A]"]),
    ]
    description = "A cozy town in warm evening light like lantern house, a harbour like it"

    with app() as client:
        body = _draft(client, description).json()

    offer = body["look_offer"]
    cozy = style_pack_library().pack("exulanica.cozy-town")
    assert cozy is not None
    assert (offer["state"], offer["reason"]) == ("offered", None)
    assert (offer["pack_id"], offer["version"], offer["manifest_sha256"]) == (
        cozy.pack_id,
        cozy.version,
        cozy.manifest_sha256,
    )
    # The person's own words, as typed: the saved name written back, never sent.
    assert offer["look_words"] == ["cozy", "warm evening light like lantern house"]
    assert offer["prompt_version"] == "look-choosing-1"
    assert [call["role"] for call in offer["execution"]["calls"]] == [str(CHOOSER_ROLE)]
    # The draft's own execution lists the drafter's calls alone.
    assert [call["role"] for call in body["execution"]["calls"]] == [str(DRAFTER_ROLE)]
    # The step was shown the description as the drafter was sent it, and the looks; no name.
    first, second = transport.requests
    sent = first["payload"]["messages"][1]["content"]
    assert "[place A]" in sent
    messages = second["payload"]["messages"]
    looks = tuple(
        LookOption(pack.pack_id, pack.title, pack.description)
        for pack in style_pack_library().packs
    )
    words = "A cozy town in warm evening light like [place A], a harbour like it"
    assert messages[1]["content"] == render_request(words, looks)
    assert "lantern" not in json.dumps(second["payload"]).lower()


def test_the_drafters_request_is_the_same_byte_for_byte_with_the_look_step_on_and_off(
    drafts, monkeypatch
):
    """The fit rule as a test: offering looks never changes what the drafter is asked."""
    app, transport, _, _ = drafts
    description = "A cozy little market town in warm evening light"
    transport.responses += [_reply(_form()), _choice(None, [])]
    with app() as client:
        on = _draft(client, description).json()
    assert on["look_offer"]["state"] == "none" and transport.call_count == 2
    drafted_with_step = _payload_bytes(transport.requests[0])

    # Off: a library holding no look, so the step asks nothing.
    library = style_pack_library()
    monkeypatch.setattr(
        world_drafts,
        "style_pack_library",
        lambda: dataclasses.replace(library, packs=()),
    )
    transport.requests.clear()
    transport.responses.append(_reply(_form()))
    with app() as client:
        off = _draft(client, description).json()
    assert off["look_offer"] is None and transport.call_count == 1

    assert _payload_bytes(transport.requests[0]) == drafted_with_step
    assert {k: v for k, v in on.items() if k != "look_offer"} == {
        k: v for k, v in off.items() if k != "look_offer"
    } | {"execution": on["execution"]}


def test_a_refused_answer_offers_no_look_and_says_why(drafts):
    app, transport, _, _ = drafts
    unlisted = _choice("exulanica.cozy-town", ["snug"])
    transport.responses += [_reply(_form()), unlisted, unlisted]

    with app() as client:
        offer = _draft(client, "a cozy little town").json()["look_offer"]

    assert (offer["state"], offer["reason"], offer["pack_id"]) == ("none", "answer_refused", None)
    assert offer["look_words"] == [] and len(offer["execution"]["calls"]) == 2


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (TransportError("no whole answer", timed_out=True), "timed_out"),
        (TransportError("the provider failed", retryable=False), "failed"),
        (BudgetExceededError("no allowance", spent_usd=1, ceiling_usd=1), "no_allowance"),
    ],
)
def test_a_look_step_that_cannot_answer_leaves_the_draft_and_says_why(
    drafts, monkeypatch, failure, reason
):
    app, transport, _, _ = drafts
    transport.responses.append(_reply(_form()))

    def unanswered(*args: Any, **kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr(world_drafts, "choose_look", unanswered)
    with app() as client:
        response = _draft(client, "a cozy little town")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["proposal"]["preset"] == "small_town"
    assert (body["look_offer"]["state"], body["look_offer"]["reason"]) == ("unavailable", reason)
    assert body["look_offer"]["pack_id"] is None
