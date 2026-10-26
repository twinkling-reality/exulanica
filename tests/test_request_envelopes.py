"""A hold is the worst case its work can reach: each role's request envelope, stated as data, bounds
the input of every request of that role, and work that holds money before it starts is priced at it
rather than at every model's whole context window.

The first test is the guard the envelopes rest on: every stage of a world from a sentence and of a
creature from words is run with the longest words a person may send, in letters that escape longest,
against answers no schema takes, so every repair is sent, and each request is measured as the chain
measures it before sending. A prompt or catalog that grows past its role's envelope fails here
before a person's draft is refused for it.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import uuid
from collections.abc import Callable
from decimal import ROUND_CEILING, Decimal
from typing import Any

import pytest
from exulanica.api import world_draft_offer
from exulanica.api.world_draft_offer import operation_sheet, stages
from exulanica.api.world_draft_worker import limits
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import BudgetExceededError, ProviderRefused
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.provider_catalog import ProviderPrice
from exulanica.models.request_envelopes import PROFILE, read, request_bytes_at_most
from exulanica.models.spending import SpendingTicket, spending_request_key
from exulanica.models.usage import USD_QUANTUM
from exulanica.references import boundary, drafting
from exulanica.references.adapters.base import Leads
from exulanica.references.render import MAX_BLOCK_BYTES
from exulanica.selection import (
    creature_drafting,
    creature_drafts,
    kind_drafting,
    look_choosing,
    setting_choosing,
    tool_choosing,
    world_drafting,
)
from exulanica.selection.look_choosing import LookOption
from exulanica.selection.setting_choosing import SettingAxis, SettingOption
from exulanica.world import specification_source
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.world_settings import setting_parts
from exulanica.world.world_tools import world_tools

from model_fakes import FakeTransport, RecordingPolicy

NOW = dt.datetime(2026, 10, 23, tzinfo=dt.UTC)
#: A letter of three UTF-8 bytes, which the chain's measure escapes to six.
LONGEST = "漢"
WORLD_WORDS = 1000
CREATURE_WORDS = creature_drafts.MAX_WORDS_CHARACTERS


def _sent(stage: Callable[[ModelClient], Any]) -> list[int]:
    """Every request ``stage`` sends to models that answer what no schema takes, by the bytes the
    chain measures (its JSON, every character outside ASCII escaped)."""
    transport = FakeTransport()
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal(100), max_calls=1000),
        policy=RecordingPolicy(),
    )
    # A stage refused for its answers is what is measured here.
    with contextlib.suppress(Exception):
        stage(client)
    return [
        len(json.dumps(request["payload"], ensure_ascii=True).encode("ascii"))
        for request in transport.requests
    ]


def _world_stages() -> dict[Role, Callable[[ModelClient], Any]]:
    words = LONGEST * WORLD_WORDS
    library = style_pack_library()
    looks = tuple(
        LookOption(p.pack_id, p.title, p.description)
        for p in library.packs
        if p.pack_id in library.chooser_offers
    )
    listed = setting_parts()
    view = world_drafting.specification_view(specification_source.served_document())
    return {
        tool_choosing.CHOOSER_ROLE: lambda c: tool_choosing.choose_tool(c, words, world_tools()),
        kind_drafting.DRAFTER_ROLE: lambda c: kind_drafting.draft_kind(
            c, words, role=kind_drafting.DRAFTER_ROLE, check=lambda *_, **__: None
        ),
        world_drafting.DRAFTER_ROLE: lambda c: world_drafting.draft_world_specification(
            c, words, view
        ),
        look_choosing.CHOOSER_ROLE: lambda c: look_choosing.choose_look(c, words, looks),
        setting_choosing.CHOOSER_ROLE: lambda c: setting_choosing.choose_setting(
            c,
            words,
            tuple(SettingAxis(key, title) for key, title in listed.axes),
            tuple(SettingOption(**part) for part in listed.listed()),
        ),
    }


def test_every_stage_s_largest_request_fits_its_role_s_envelope():
    roles = {role for path in stages().values() for role, _ in path}
    assert roles == set(_world_stages())
    for role, stage in _world_stages().items():
        sent = _sent(stage)
        envelope = request_bytes_at_most(role)
        assert envelope is not None, role
        # Every repair was sent: the stage's own number of attempts.
        assert len(sent) == dict(r for path in stages().values() for r in path)[role]
        assert max(sent) <= envelope, (role, sent, envelope)
    words = LONGEST * CREATURE_WORDS
    notes = LONGEST * (MAX_BLOCK_BYTES // len(LONGEST.encode()))
    for reference in (None, notes):
        sent = _sent(
            lambda c, reference=reference: creature_drafting.draft_creature(
                c,
                words,
                role=creature_drafting.DRAFTER_ROLE,
                reference_text=reference,
                reference_bundle_sha256=None if reference is None else "a" * 64,
            )
        )
        assert len(sent) == creature_drafting.DRAFT_ATTEMPTS
        assert max(sent) <= request_bytes_at_most(creature_drafting.DRAFTER_ROLE), sent


@pytest.mark.parametrize("purpose", ["world_draft", "things"])
def test_the_web_notes_two_calls_fit_the_notes_role_s_envelope_at_their_longest(purpose):
    # The planner with the longest words a person may send; the reader with what the searches
    # found filling its material in letters that escape longest, in excerpts that fill the cap.
    words = drafting.prompts_for_request(purpose)
    catalogs = drafting.catalogs_for_prompts(words)
    planned = _sent(
        lambda c: drafting.plan_subjects(
            c, LONGEST * WORLD_WORDS, purpose=purpose, prompts=words, catalogs=catalogs
        )
    )
    query = boundary.AdmittedQuery(
        "tavily_search", "stone houses by the sea", next(iter(catalogs.aspects)), boundary._SEAL
    )
    # More than the reader's material may hold, however large its cap: the cap is measured.
    found = tuple(LONGEST * 200 for _ in range(words.material_characters_maximum // 200 + 1))
    leads = [Leads(query, found, found, len(found), 1, None) for _ in range(words.subjects_maximum)]
    read = _sent(
        lambda c: drafting.read_notes(
            c, leads, prompts=words, catalogs=catalogs, pictures=purpose != "world_draft"
        )
    )
    envelope = request_bytes_at_most(Role.REFERENCE_DRAFTING)
    assert envelope is not None
    assert planned and read
    assert max(planned + read) <= envelope, (planned, read, envelope)


@pytest.mark.parametrize(
    "entries",
    [
        [{"role": "no_such_role", "request_bytes_at_most": 1, "reason": "x"}],
        [{"role": "look_chooser", "request_bytes_at_most": 0, "reason": "x"}],
        [{"role": "look_chooser", "request_bytes_at_most": 1.5, "reason": "x"}],
        [{"role": "look_chooser", "request_bytes_at_most": True, "reason": "x"}],
        [{"role": "look_chooser", "request_bytes_at_most": 1, "reason": " "}],
        [{"role": "look_chooser", "request_bytes_at_most": 1}],
        [
            {"role": "look_chooser", "request_bytes_at_most": 1, "reason": "x"},
            {"role": "look_chooser", "request_bytes_at_most": 2, "reason": "x"},
        ],
    ],
)
def test_the_catalog_reader_refuses_what_bounds_nothing(entries):
    with pytest.raises(ValueError):
        read({"profile": PROFILE, "entries": entries})
    with pytest.raises(ValueError):
        read({"profile": "another/v1", "entries": []})


def _inputs():
    """The world draft's sheet inputs: every stage model priced at twice the manifest's rates,
    read now, and each role sent as often as three times its chain."""
    manifest = load_manifest()
    models = {s for rows in stages().values() for r, _ in rows for s in manifest[r].chain}
    prices = {
        (s.provider, s.model_id): ProviderPrice(
            s.model_id,
            s.input_usd_per_mtok * 2,
            s.output_usd_per_mtok * 2,
            s.context_window_tokens,
            "f" * 64,
        )
        for s in models
    }
    return (
        manifest,
        prices,
        {s.provider: NOW for s in models},
        lambda role: len(manifest[role].chain) * 3,
    )


def _each(input_tokens: int, answer: int, price: ProviderPrice) -> Decimal:
    return (
        (
            Decimal(input_tokens) * price.input_usd_per_mtok
            + Decimal(answer) * price.output_usd_per_mtok
        )
        / Decimal(1_000_000)
    ).quantize(USD_QUANTUM, rounding=ROUND_CEILING)


def test_a_world_draft_is_priced_and_held_at_each_stage_s_envelope(monkeypatch):
    manifest, prices, at, wire = _inputs()
    sheet = operation_sheet(manifest, prices, at, wire, now=NOW)
    assert sheet["basis"] == "request_envelope_ceiling"
    for path in sheet["paths"]:
        for entry in path["stages"]:
            role = Role(entry["role"])
            envelope = request_bytes_at_most(role)
            assert entry["request_bytes_at_most"] == envelope
            for model in entry["models"]:
                price = prices[model["provider"], model["model_id"]]
                least = min(envelope, manifest.spec(model["model_id"]).context_window_tokens)
                assert Decimal(model["reservation_usd"]) == _each(
                    least, entry["answer_tokens_at_most"], price
                )
    # The draft's chain is held to exactly those bounds: no request larger than its stage's
    # envelope or asking a longer answer is sent.
    held = limits(sheet)
    for path in sheet["paths"]:
        for entry in path["stages"]:
            assert held[Role(entry["role"])] == (
                entry["request_bytes_at_most"],
                entry["answer_tokens_at_most"],
            )
    # A role with no envelope is priced at its model's whole context, as before, and so is every
    # stage of a sheet priced before envelopes: far more than this one.
    monkeypatch.setattr(world_draft_offer, "request_bytes_at_most", lambda role: None)
    whole = operation_sheet(manifest, prices, at, wire, now=NOW)
    assert Decimal(whole["maximum_usd"]) > 5 * Decimal(sheet["maximum_usd"])
    old = json.loads(json.dumps(whole))
    for path in old["paths"]:
        for entry in path["stages"]:
            del entry["request_bytes_at_most"]
    contexts = {(p["provider"], p["model_id"]): p["input_tokens_at_most"] for p in old["prices"]}
    for path in old["paths"]:
        for entry in path["stages"]:
            assert limits(old)[Role(entry["role"])][0] == min(
                contexts[m["provider"], m["model_id"]] for m in entry["models"]
            )


def test_a_creature_draft_is_priced_at_its_envelope_and_held_to_it(client, manifest, transport):
    role = creature_drafting.DRAFTER_ROLE
    envelope = request_bytes_at_most(role)
    binding = manifest[role]
    answer = binding.default_max_tokens if binding.max_tokens is None else binding.max_tokens.value
    price = creature_drafts.price_at_most(manifest, 2)
    assert price["basis"]["kind"] == "request_envelope_ceiling"
    assert price["basis"]["input_tokens_at_most"] == max(
        min(envelope, s.context_window_tokens) for s in binding.chain
    )
    each = max(
        s.cost_usd(prompt_tokens=min(envelope, s.context_window_tokens), completion_tokens=answer)
        for s in binding.chain
    )
    assert Decimal(price["usd_at_most"]) == (each * creature_drafting.DRAFT_ATTEMPTS * 2).quantize(
        USD_QUANTUM, rounding=ROUND_CEILING
    )
    held = creature_drafts.draft_limits(manifest)
    assert held == {role: (envelope, answer)}
    # Held to it: a request past the envelope is refused before anything is sent.
    bounded = client.with_prices({}, limits=held)
    with pytest.raises(ProviderRefused) as refused:
        bounded.chat(
            role,
            [{"role": "user", "content": "x" * (envelope + 1)}],
            prompt_version="request-envelope-check",
            max_tokens=answer,
            use_cache=False,
        )
    assert refused.value.reason == "world_draft_request_limit_exceeded"
    assert transport.call_count == 0


class _Holds:
    """A durable authority that admits every attempt, keeping what each was held at."""

    def __init__(self) -> None:
        self.held: list[Decimal] = []

    def admit(self, request):
        self.held.append(request.usd)
        return SpendingTicket(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), request.usd, request.key)

    def dispatch(self, ticket) -> None:
        pass

    def settle(self, ticket, usage) -> None:
        pass

    def release(self, ticket) -> None:
        pass


def test_an_attempt_under_its_priced_bounds_is_held_at_its_own_worst_case(manifest):
    """Under the bounds its price counts, an attempt is admitted and reserved at its own worst case:
    every byte of its request as a token and its whole answer, never the characters' estimate (the
    schema and the escapes left out), which a report could pass. A report at that worst case then
    settles at no more than was held."""
    role = creature_drafting.DRAFTER_ROLE
    binding = manifest[role]
    answer = binding.default_max_tokens if binding.max_tokens is None else binding.max_tokens.value
    held = {role: (request_bytes_at_most(role), answer)}
    words = [{"role": "user", "content": LONGEST * 200}]

    def ask(budget: BudgetGuard) -> tuple[FakeTransport, _Holds]:
        transport, gate = FakeTransport(), _Holds()
        client = ModelClient(
            api_key="test-key-not-real",
            manifest=manifest,
            transport=transport,
            budget=budget,
            policy=RecordingPolicy(),
        )
        with spending_request_key("request-envelope-check"):
            client.with_prices({}, limits=held).with_spending(gate).chat(
                role,
                words,
                prompt_version="request-envelope-check",
                max_tokens=answer,
                use_cache=False,
            )
        return transport, gate

    transport, gate = ask(BudgetGuard(ceiling_usd=Decimal(100), max_calls=10))
    (sent,) = transport.requests
    size = len(json.dumps(sent["payload"], ensure_ascii=True).encode("ascii"))
    spec = binding.primary
    worst = spec.cost_usd(prompt_tokens=size, completion_tokens=answer).quantize(USD_QUANTUM)
    assert gate.held == [worst]
    # The characters' estimate it was held at before is less: a report could have passed it.
    assert BudgetGuard().estimate_usd(spec, prompt_chars=200, max_tokens=answer) < worst
    # The process's own guard reserves the same: a ceiling a quantum short of it sends nothing.
    with pytest.raises(BudgetExceededError):
        ask(BudgetGuard(ceiling_usd=worst - USD_QUANTUM, max_calls=10))
