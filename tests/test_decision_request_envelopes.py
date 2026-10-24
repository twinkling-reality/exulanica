"""A person's decision is held at the most its requests can send: each terms the person role asks
under states a request envelope as data, and an ask is priced at it, every answer its contract
allows, rather than by its prompt's characters, which leave the function's options out.

The first test is the guard the envelopes rest on. For every engine the person role is hosted by,
a request at its worst is built from a real one, every part it renders at its own most, whatever
room the context's bound leaves: the most options, each label as long as a label may be, some of
them saying something so that a line is asked; every heard and said line at its most characters,
written in double quotes, which a request escapes twice; a character's name and words at theirs;
the noticed and remembered blocks filled to their byte bounds; and, for a living person, needs up
to the context's own bound. Each is asked through the host's one ask path, the client building the
payload by each answering mechanism, of a model that answers off the offer, so the retry and its
note are sent too, and each request is measured as the chain measures one before sending it.
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from exulanica.abilities.registry import current_modules, recorded_row
from exulanica.api.decision_admission import answer_tokens, ask_bound_usd
from exulanica.api.decision_host import RoleAsk, ask
from exulanica.canonical import canonical_json
from exulanica.models.budget import BudgetGuard
from exulanica.models.choice import ChoiceRequest
from exulanica.models.client import ModelClient
from exulanica.models.manifest import (
    MANIFEST_PATH,
    AnsweringMechanism,
    load_manifest,
    parse_manifest,
)
from exulanica.models.usage import USD_QUANTUM
from exulanica.world import decision_envelopes
from exulanica.world.decision_envelopes import PROFILE, read, request_bytes_at_most
from exulanica.world.decision_roles import decision_roles
from exulanica.world.society_decision_contract import (
    choice_options,
    decision_context,
    named,
    person_role,
)
from exulanica.world.society_living import LIVING_TOWN_PROFILE
from exulanica.world.society_planner import initial_purposeful_society
from exulanica.world.society_things import THINGS_PROFILE, initial_things_society

import living_square_support as square
from decision_role_support import person_like, registry_in_use, write_registry
from model_fakes import FakeTransport, RecordingPolicy
from things_society_support import SEED, SOCIETY, compose, thing

PROBE_RECORD = "docs/evaluation/2026-09-25-society-person-models-probe.json"
#: A character a quoted line escapes twice: once as it is quoted, again in the request's JSON.
QUOTE = '"'
#: The longest option label (``exulanica.models.choice``), checked below.
LABEL_MOST = 120
#: The longest kind label (``exulanica.things.kinds``) and the longest name a being keeps.
KIND_LABEL_MOST = 40
NAME_MOST = 120
NAME = named("N" * NAME_MOST, "a" * KIND_LABEL_MOST)
#: The latest minute a request can tell, at a day far into a world's life.
LATE = {"minute_of_day": 1439, "day": 999_999}


def _label(n: int) -> str:
    return f"option {n:02d} " + "x" * (LABEL_MOST - len(f"option {n:02d} ") - 1) + "y"


def _manifest(mechanism: AnsweringMechanism):
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    model_id = next(
        model_id
        for model_id, raw in sorted(document["models"].items())
        if raw["min_max_tokens"] is not None and "text" in raw["catalog_use_cases"]
    )
    document["models"][model_id]["answering"] = {mechanism.value: PROBE_RECORD}
    return parse_manifest(document), model_id


def _sent(context: dict[str, Any], mechanism: AnsweringMechanism) -> list[int]:
    """Every request one ask over ``context`` sends a model that answers off the offer, by the
    bytes the chain measures: its JSON with every character outside ASCII escaped."""
    role = person_role()
    contract = role.contract(role.terms_of(context).versions)
    manifest, model_id = _manifest(mechanism)
    transport = FakeTransport()
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal(100), max_calls=1000),
        policy=RecordingPolicy(),
    )
    asked = RoleAsk(role, {"context": context}, manifest.spec(model_id), mechanism)
    result = ask(client, asked, contract, time.monotonic() + 60)
    # Every answer the contract allows was asked: the retry carries its note.
    assert result["reason"] == "answer_not_offered"
    assert transport.call_count == contract.value("answer_attempts_maximum")
    return [
        len(json.dumps(request["payload"], ensure_ascii=True).encode("ascii"))
        for request in transport.requests
    ]


def _module_value(name: str, key: str) -> int:
    row = recorded_row(current_modules(), name)
    assert row is not None, name
    return row.value(key)


def _widest_options(context: dict[str, Any], most: int) -> list[dict[str, Any]]:
    """``most`` options, each with the longest label, cycling through the kinds offered."""
    offered = context["options"]
    return [{**offered[n % len(offered)], "label": _label(n)} for n in range(most)]


def _filled(block: dict[str, Any], key: str, entry: Callable[[], dict], most: int) -> None:
    """``block[key]`` given entries while the block stays within ``most`` canonical bytes."""
    while True:
        block[key].append(entry())
        if len(canonical_json(block)) > most:
            block[key].pop()
            return


def _things_widest() -> dict[str, Any]:
    """A society of things' person at its widest: a knight beside a villager, every part at its
    most."""
    gate = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
    knight = thing("knight", "knight", 1, 3_000, 3_000)
    document = compose((gate, knight))
    state = initial_things_society(SOCIETY, SEED, document, population=6)
    state = copy.deepcopy(state)
    placed = next(p for p in state["inhabitants"] if p["came_by"] == "placed")
    near = next(p for p in state["inhabitants"] if p["came_by"] == "populated")
    near["position_mm"] = [placed["position_mm"][0] + 2_000, placed["position_mm"][1]]
    role = person_role()
    contract = role.contract(role.terms(THINGS_PROFILE).versions)
    options = choice_options(state, document, placed["id"], contract, seed=SEED)
    context = decision_context(state, document, placed["id"], options)
    lines = contract.value("lines_heard_maximum")
    characters = contract.value("line_characters_maximum")
    line = QUOTE * characters
    context.update(
        being={"kind": "a" * KIND_LABEL_MOST, "summary": "S" * 160},
        options=_widest_options(context, contract.value("options_maximum")),
        heard=[
            {"from": NAME, "to_you": False, "line": line, "tick": 0, "minutes_ago": 1439}
            for _ in range(lines)
        ],
        said=[{"to": NAME, "line": line, "minutes_ago": 1439} for _ in range(lines)],
        character={
            "name": QUOTE * _module_value("character", "name_characters_maximum"),
            "about": QUOTE * _module_value("character", "about_characters_maximum"),
        },
        holding=["a" * KIND_LABEL_MOST] * contract.value("hands_options_maximum"),
        last_activity="a" * LABEL_MOST,
        world_clock=LATE,
    )
    noticed: dict[str, Any] = {
        "at": {"words": "w" * 80, "good_for": "g" * 80},
        "beings": [],
        "more_beings": 99,
        "things": [],
        "more_things": 99,
    }
    _filled(
        noticed,
        "beings",
        lambda: {
            "who": NAME,
            "kind": "a" * KIND_LABEL_MOST,
            "metres": 1000,
            "doing": "d" * 80,
            "holding": ["a" * KIND_LABEL_MOST],
            "from_elsewhere": True,
            "hears_you": True,
        },
        _module_value("notice", "bytes_maximum"),
    )
    context["surroundings"] = noticed
    remembered: dict[str, Any] = {"beings": [], "places": [], "handed": [], "choices": []}
    memory_most = _module_value("remember", "bytes_maximum")
    _filled(
        remembered,
        "beings",
        lambda: {
            "who": "A",
            "met_minutes_ago": 0,
            "last_minutes_ago": 0,
            "times": 1,
            "how": ["took_from_you", "gave_you", "you_gave", "you_took"],
            "here": True,
            "their_line": {"line": line, "minutes_ago": 0},
            "your_line": {"line": line, "minutes_ago": 0},
        },
        memory_most,
    )
    _filled(
        remembered,
        "choices",
        lambda: {"chose": QUOTE * 40, "minutes_ago": 0, "disposition": "refused"},
        memory_most,
    )
    context["remembers"] = remembered
    assert role.takes_line(context)
    return context


def _square_widest() -> dict[str, Any]:
    """A purposeful person of the small square at their widest: the most options, each with the
    longest label, and the longest last place."""
    document = square.compose(square.square_objects())
    state = initial_purposeful_society(square.SOCIETY, square.DEVELOPMENT_SEEDS[0], document)
    role = person_role()
    contract = role.contract(role.terms(state["profile"]).versions)
    person, options = next(
        (person, options)
        for person in state["inhabitants"]
        if (
            options := choice_options(
                state, document, person["id"], contract, seed=square.DEVELOPMENT_SEEDS[0]
            )
        )
    )
    context = decision_context(state, document, person["id"], options)
    context["options"] = _widest_options(context, contract.value("options_maximum"))
    context["last_activity"] = "a" * LABEL_MOST
    return context


def _living_widest() -> dict[str, Any]:
    """A living town's person at their widest: the most options, each with the longest label, the
    longest job and place words, and needs, each read with its own words, up to the context's
    bound."""
    role = person_role()
    contract = role.contract(role.terms(LIVING_TOWN_PROFILE).versions)
    target = {
        "kind": "target",
        "action": "go",
        "target_id": "t",
        "activity": "a",
        "walk_mm": 0,
    }
    context: dict[str, Any] = {
        "profile": role.context_profile,
        "engine": LIVING_TOWN_PROFILE,
        "subject_id": str(uuid.UUID(int=1)),
        "branch_id": str(uuid.UUID(int=2)),
        "tick": 0,
        "clock": LATE,
        "role": "r" * LABEL_MOST,
        "needs": [],
        "doing": {"kind": "idle", "status": "active", "reason": "awaiting_goal"},
        "options": [
            {**target, "label": _label(n)} for n in range(contract.value("options_maximum"))
        ],
        "here": "h" * LABEL_MOST,
    }
    _filled(
        context,
        "needs",
        lambda: {"label": "n", "milli": 1000, "seen_to_at_milli": 1000},
        contract.value("context_bytes_maximum"),
    )
    return context


#: Each engine the person role is hosted by, and its person at their widest.
WIDEST: dict[str, Callable[[], dict[str, Any]]] = {
    "exulanica-society/v2": _square_widest,
    LIVING_TOWN_PROFILE: _living_widest,
    THINGS_PROFILE: _things_widest,
}


def test_the_longest_label_is_the_one_a_choice_takes():
    assert ChoiceRequest("Choose.", (_label(1), "wait here")).options[0] == _label(1)
    with pytest.raises(ValueError):
        ChoiceRequest("Choose.", ("x" + _label(1), "wait here"))


def test_every_terms_s_largest_request_fits_its_envelope():
    role = person_role()
    assert set(WIDEST) == set(role.engines)
    for engine, widest in WIDEST.items():
        context = widest()
        terms = role.terms_of(context)
        assert terms == role.terms(engine)
        envelope = request_bytes_at_most(role.key, terms.prompt_version)
        assert envelope is not None, terms.prompt_version
        for mechanism in role.contract(terms.versions).mechanism_order:
            sent = _sent(context, mechanism)
            assert max(sent) <= envelope, (engine, mechanism, sent, envelope)


def test_every_terms_the_person_role_asks_under_has_an_envelope():
    role = person_role()
    for terms in role.every_terms():
        assert request_bytes_at_most(role.key, terms.prompt_version) is not None
    # A role the catalog does not name is priced as before.
    for other in decision_roles():
        if other.key != role.key:
            for terms in other.every_terms():
                assert request_bytes_at_most(other.key, terms.prompt_version) is None


def test_the_shipped_envelopes_are_read_whatever_registry_a_process_puts_in_use(
    tmp_path, monkeypatch
):
    """The catalog names the registry it ships beside. A process that puts another registry in use,
    here one that registers a role like the person's and no person, nor any earlier prompt, reads
    the shipped envelopes all the same the first time it asks, and its own role finds none."""
    role = person_role()
    prompts = [terms.prompt_version for terms in role.every_terms()]
    directory, package = write_registry(tmp_path, [person_like("tenant_decision", "tenant")])
    monkeypatch.syspath_prepend(str(tmp_path))
    decision_envelopes._shipped.cache_clear()
    try:
        with registry_in_use(directory, package) as registry:
            assert role.key not in registry.roles
            tenant = registry.role("tenant_decision")
            for prompt in prompts:
                assert request_bytes_at_most(role.key, prompt) is not None, prompt
            assert request_bytes_at_most(tenant.key, tenant.prompt_version) is None
    finally:
        decision_envelopes._shipped.cache_clear()


@pytest.mark.parametrize(
    "entries",
    [
        [
            {
                "role": "no_such_role",
                "prompt_version": "society-person-choice/v9",
                "request_bytes_at_most": 1,
                "reason": "x",
            }
        ],
        [
            {
                "role": "society_decision",
                "prompt_version": "society-person-choice/v999",
                "request_bytes_at_most": 1,
                "reason": "x",
            }
        ],
        [
            {
                "role": "society_decision",
                "prompt_version": "society-person-choice/v9",
                "request_bytes_at_most": 0,
                "reason": "x",
            }
        ],
        [
            {
                "role": "society_decision",
                "prompt_version": "society-person-choice/v9",
                "request_bytes_at_most": 1.5,
                "reason": "x",
            }
        ],
        [
            {
                "role": "society_decision",
                "prompt_version": "society-person-choice/v9",
                "request_bytes_at_most": True,
                "reason": "x",
            }
        ],
        [
            {
                "role": "society_decision",
                "prompt_version": "society-person-choice/v9",
                "request_bytes_at_most": 1,
                "reason": " ",
            }
        ],
        [
            {
                "role": "society_decision",
                "prompt_version": "society-person-choice/v9",
                "request_bytes_at_most": 1,
            }
        ],
        [
            {
                "role": "society_decision",
                "prompt_version": "society-person-choice/v9",
                "request_bytes_at_most": 1,
                "reason": "x",
            },
            {
                "role": "society_decision",
                "prompt_version": "society-person-choice/v9",
                "request_bytes_at_most": 2,
                "reason": "x",
            },
        ],
    ],
)
def test_the_catalog_reader_refuses_what_bounds_nothing(entries):
    with pytest.raises(ValueError):
        read({"profile": PROFILE, "entries": entries})
    with pytest.raises(ValueError):
        read({"profile": "another/v1", "entries": []})


def test_an_ask_is_priced_at_its_terms_envelope_and_every_answer_its_contract_allows():
    """For every model offered the role and each contract it asks under: its answers' input at the
    terms' envelope, each byte a token, at the model's answer bound; a role the catalog does not
    name keeps the characters' estimate."""
    manifest = load_manifest()
    budget = BudgetGuard(ceiling_usd=Decimal(1), max_calls=100)
    role = person_role()
    asked = 0
    for terms in role.every_terms():
        contract = role.contract(terms.versions)
        envelope = request_bytes_at_most(role.key, terms.prompt_version)
        for spec in manifest.offered_models(role.chosen):
            if contract.mechanism_for(spec) is None:
                continue
            each = spec.cost_usd(
                prompt_tokens=envelope, completion_tokens=answer_tokens(spec) or 0
            ).quantize(USD_QUANTUM)
            assert ask_bound_usd(role, budget, spec, contract) == (
                contract.value("answer_attempts_maximum") * each
            )
            asked += 1
    assert asked > 2
    signal = decision_roles().role("junction_signal")
    contract = signal.contract()
    for spec in manifest.offered_models(signal.chosen):
        if contract.mechanism_for(spec) is None:
            continue
        characters = max(
            len(terms.instruction) + len(terms.not_offered) for terms in signal.every_terms()
        ) + 2 * contract.value("context_bytes_maximum")
        assert ask_bound_usd(signal, budget, spec, contract) == contract.value(
            "answer_attempts_maximum"
        ) * budget.estimate_usd(spec, prompt_chars=characters, max_tokens=answer_tokens(spec) or 0)


def test_the_characters_estimate_falls_short_of_the_largest_request():
    """The positive control for the change: what the characters' estimate held for an ask, its
    instruction, note and twice the context's bound, prices fewer input tokens than the largest
    request of the society of things sends, measured in bytes."""
    role = person_role()
    terms = role.terms(THINGS_PROFILE)
    contract = role.contract(terms.versions)
    characters = len(terms.instruction) + len(terms.not_offered)
    estimated_tokens = (characters + 2 * contract.value("context_bytes_maximum")) // 3
    largest = max(_sent(_things_widest(), contract.mechanism_order[0]))
    assert estimated_tokens < largest
