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
from exulanica.selection import setting_choosing, world_drafting
from exulanica.selection.look_choosing import CHOOSER_ROLE, LookOption, render_request
from exulanica.selection.world_drafting import DRAFTER_ROLE
from exulanica.world import specification_source
from exulanica.world.specification_samples import Counted, TownSample
from exulanica.world.specification_source import ValueRefusal
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.world_settings import SETTINGS_DIRECTORY, SettingParts, setting_parts
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


#: A host that lists no part of a setting, so the setting step asks nothing.
NO_PARTS = SettingParts(version=0, sha256="0" * 64, axes=(), parts={})


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
    # The setting step runs after the look step and has tests of its own below: with no part to
    # choose it asks nothing, so every other test here holds the draft and the look step alone.
    monkeypatch.setattr(world_drafts, "setting_parts", lambda: NO_PARTS)
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
    assert body["prompt_version"] == "world-drafting-6"
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


def test_words_that_ask_for_no_town_are_refused_by_name_with_nothing_sampled(drafts):
    app, transport, samples, _ = drafts
    transport.responses.append(_reply(_form(fit="none", not_supported=["a red bicycle"])))

    with app() as client:
        body = _draft(client, "a red bicycle").json()

    assert body["proposal"] is None
    assert body["refusal"]["code"] == "description_not_supported"
    assert "no town" in body["refusal"]["detail"]
    assert body["not_supported"] == ["a red bicycle"]
    assert samples.asked == []
    # A refused draft is offered no look, and the look step asks nothing.
    assert body["look_offer"] is None and transport.call_count == 1


def test_a_town_whose_words_no_value_can_say_is_proposed_as_the_presets_own(drafts):
    """A description that asks for a town is never answered that it cannot be made: the drafter
    answers fit part with no value set, and the proposal is the preset's own town with every part
    of the words named as left out."""
    app, transport, samples, _ = drafts
    left_out = ["seaside", "at dawn", "mist off the water"]
    transport.responses += [
        _reply(_form(preset="small_town", fit="part", not_supported=left_out)),
        _choice(None, []),
    ]

    with app() as client:
        answer = _draft(client, "A sleepy seaside town at dawn, mist off the water")

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["refusal"] is None
    proposal = body["proposal"]
    assert (proposal["preset"], proposal["fit"], proposal["valid"]) == ("small_town", "part", True)
    assert proposal["set_by_words"] == []
    preset = next(p for p in specification_document()["presets"] if p["key"] == "small_town")
    assert proposal["values"] == preset["values"]
    assert body["not_supported"] == left_out
    # It is a town like any other: sampled, and asked which look its words want.
    assert samples.asked == [("small_town", preset["values"])]
    assert body["look_offer"]["state"] == "none" and transport.call_count == 2


def test_the_drafters_words_refuse_only_what_asks_for_no_place_where_people_live():
    """Both files the drafter is asked with, the one without notes and the one with, say the same
    thing about fit: a description that asks for a town is part, and none is for no place at all."""
    plain = world_drafting.drafting_prompt()
    noted = world_drafting.drafting_prompt(world_drafting.NOTES_PROMPT_PATH)
    assert (plain.prompt_version, noted.prompt_version) == ("world-drafting-6", "world-drafting-7")
    for prompt in (plain, noted):
        fit = next(line for line in prompt.instructions.splitlines() if line.startswith("- fit:"))
        assert "any other place where people live" in fit
        assert "the town is still made, from the preset" in fit
        assert fit.endswith(
            "none only when the description does not ask for a place where people live at all."
        )


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
        (TransportError("the step's deadline ended", deadline_ended=True), "timed_out"),
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


# -- the setting offered after the draft and the look --------------------------------------------

SETTING_ROLE = setting_choosing.CHOOSER_ROLE
#: The host's named parts, read from the committed file, not through the loader under test.
PARTS_FILE = json.loads((SETTINGS_DIRECTORY / "setting-parts.v1.json").read_text("utf-8"))


def _setting(words: list[str], **parts: str | None) -> HttpResponse:
    answer = {axis["key"]: parts.get(axis["key"]) for axis in PARTS_FILE["axes"]}
    content = json.dumps({**answer, "words": words})
    model = load_manifest()[SETTING_ROLE].primary.model_id
    return HttpResponse(status_code=200, text=json.dumps(chat_body(content, model=model)))


def _with_settings(monkeypatch) -> None:
    monkeypatch.setattr(world_drafts, "setting_parts", setting_parts)


def test_a_setting_the_words_ask_for_is_offered_in_the_persons_own_words(drafts, monkeypatch):
    app, transport, _, _ = drafts
    _with_settings(monkeypatch)
    transport.responses += [
        _reply(_form()),
        _choice(None, []),
        _setting(["at dusk", "by the sea near [place A]"], sky="dusk", ground="sea"),
    ]
    description = "A town by the sea near lantern house, at dusk"

    with app() as client:
        body = _draft(client, description).json()

    offer = body["setting_offer"]
    assert (offer["state"], offer["reason"]) == ("offered", None)
    assert offer["parts"] == {"sky": "dusk", "ground": "sea"}
    assert offer["parts_version"] == PARTS_FILE["version"]
    # The person's own words, as typed: the saved name written back, never sent.
    assert offer["setting_words"] == ["at dusk", "by the sea near lantern house"]
    assert offer["prompt_version"] == "setting-choosing-1"
    assert [call["role"] for call in offer["execution"]["calls"]] == [str(SETTING_ROLE)]
    # The draft's and the look offer's executions list their own calls alone.
    assert [call["role"] for call in body["execution"]["calls"]] == [str(DRAFTER_ROLE)]
    assert [call["role"] for call in body["look_offer"]["execution"]["calls"]] == [
        str(CHOOSER_ROLE)
    ]
    # The step was shown the description as the drafter was sent it, and the parts; no name.
    _first, _second, third = transport.requests
    axes = tuple(
        setting_choosing.SettingAxis(axis["key"], axis["title"]) for axis in PARTS_FILE["axes"]
    )
    options = tuple(
        setting_choosing.SettingOption(
            part["axis"], part["key"], part["title"], part["description"]
        )
        for part in PARTS_FILE["parts"]
    )
    words = "A town by the sea near [place A], at dusk"
    assert third["payload"]["messages"][1]["content"] == setting_choosing.render_request(
        words, axes, options
    )
    assert "lantern" not in json.dumps(third["payload"]).lower()


def test_the_drafters_and_the_look_choosers_requests_are_the_same_with_the_setting_step_on_and_off(
    drafts, monkeypatch
):
    """Offering a setting never changes what the drafter or the look chooser is asked."""
    app, transport, _, _ = drafts
    description = "A cozy little market town at dusk"
    transport.responses += [_reply(_form()), _choice(None, [])]
    with app() as client:
        off = _draft(client, description).json()
    assert off["setting_offer"] is None and transport.call_count == 2
    without_step = [_payload_bytes(request) for request in transport.requests]

    _with_settings(monkeypatch)
    transport.requests.clear()
    transport.responses += [_reply(_form()), _choice(None, []), _setting([])]
    with app() as client:
        on = _draft(client, description).json()
    assert on["setting_offer"]["state"] == "none" and transport.call_count == 3
    assert [_payload_bytes(request) for request in transport.requests[:2]] == without_step
    assert {k: v for k, v in on.items() if k != "setting_offer"} == {
        k: v for k, v in off.items() if k != "setting_offer"
    } | {"execution": on["execution"], "look_offer": on["look_offer"]}


def test_a_refused_draft_is_offered_no_setting_and_the_step_asks_nothing(drafts, monkeypatch):
    app, transport, _, _ = drafts
    _with_settings(monkeypatch)
    transport.responses.append(
        _reply(_form(fit="none", not_supported=["a floating city in the clouds"]))
    )
    with app() as client:
        body = _draft(client, "a floating city in the clouds").json()
    assert body["refusal"]["code"] == "description_not_supported"
    assert body["setting_offer"] is None and transport.call_count == 1


def test_a_refused_setting_answer_offers_none_and_says_why(drafts, monkeypatch):
    app, transport, _, _ = drafts
    _with_settings(monkeypatch)
    invented = _setting(["sunset"], sky="dusk")
    transport.responses += [_reply(_form()), _choice(None, []), invented, invented]

    with app() as client:
        offer = _draft(client, "a town at dusk").json()["setting_offer"]

    assert (offer["state"], offer["reason"], offer["parts"]) == ("none", "answer_refused", {})
    assert offer["setting_words"] == [] and len(offer["execution"]["calls"]) == 2


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (TransportError("no whole answer", timed_out=True), "timed_out"),
        (TransportError("the provider failed", retryable=False), "failed"),
        (BudgetExceededError("no allowance", spent_usd=1, ceiling_usd=1), "no_allowance"),
    ],
)
def test_a_setting_step_that_cannot_answer_leaves_the_draft_and_the_look_and_says_why(
    drafts, monkeypatch, failure, reason
):
    app, transport, _, _ = drafts
    _with_settings(monkeypatch)
    transport.responses += [_reply(_form()), _choice("exulanica.cozy-town", ["cozy"])]

    def unanswered(*args: Any, **kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr(world_drafts, "choose_setting", unanswered)
    with app() as client:
        response = _draft(client, "a cozy little town at dusk")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["proposal"]["preset"] == "small_town"
    assert body["look_offer"]["state"] == "offered"
    offer = body["setting_offer"]
    assert (offer["state"], offer["reason"], offer["parts"]) == ("unavailable", reason, {})
