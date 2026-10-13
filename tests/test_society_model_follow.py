"""A generated walking creature chooses bounded pursuit through the ordinary model role.

The transport is scripted infrastructure evidence, never a live model-quality measurement.
Body admission, options, request/receipt validation, paced movement, memory and replay are real.
"""

from __future__ import annotations

import copy
import json
import math
import uuid
from decimal import Decimal
from itertools import pairwise

import pytest
from exulanica.abilities.registry import FOLLOW_KEEPING_NEAR, FOLLOW_PERSISTENT
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.transport import HttpResponse
from exulanica.selection.creature_drafting import assembled_form
from exulanica.things.bodies import body_grammar, read_body_recipe
from exulanica.things.creatures import assemble_creature
from exulanica.things.run_forms import run_form
from exulanica.world.role_decisions import (
    check_role_result,
    play_minutes,
    replay_minutes,
    validate_role_receipt,
    validate_role_request,
)
from exulanica.world.society_actions import (
    ActionIntent,
    action_goal_policies,
    append_action_events,
    build_action_request,
)
from exulanica.world.society_comparison import _purposeful_step, _things_finish
from exulanica.world.society_decision_contract import choice_options, person_role
from exulanica.world.society_kinds import pace_permille_of
from exulanica.world.society_model_decisions import model_goal_policies
from exulanica.world.society_planner import advance_purposeful_society, input_sha256
from exulanica.world.society_play import play_contract
from exulanica.world.society_things import THINGS_PROFILE, initial_things_society

from creature_support import form_of
from model_fakes import FakeTransport, RecordingPolicy, chat_body
from test_decision_roles import MODEL_ID, _Live, _manifest
from test_society_made_kinds import BY, _placed
from things_society_support import SEED, SOCIETY, compose, thing


def scenario(*, walking=True):
    form = form_of("ten_legs", label="hill crawler", moves=["walking"] if walking else [])
    # Keep the author's wait preference; existing planner fallback still uses world weights.
    form["weight_wait"] = 1000
    form["weight_stand"] = 0
    if not walking:
        for ability in ("stand", "follow"):
            form[f"can_{ability}"] = False
            form[f"weight_{ability}"] = 0
    creature = assemble_creature(assembled_form(form, body_grammar()), by=BY)
    semantics = run_form(creature.kind, creature.plan, read_body_recipe(dict(creature.recipe)))
    document = compose(
        (
            _placed("crawler", creature.kind.sha256, -3_000, 3_000),
            thing("guide", "knight", 1, 3_000, 3_000),
        ),
        made_kinds={creature.kind.sha256: semantics},
    )
    state = initial_things_society(SOCIETY, SEED, document, population=6)
    # A small recorded test budget makes a pursuit span several real engine minutes.
    state["movement_budget_mm_per_tick"] = 2_000
    return creature, document, state


def inhabitant(state, placed_id="crawler"):
    return next(p for p in state["inhabitants"] if p.get("placed_id") == placed_id)


class PursuitTransport(FakeTransport):
    """Choose the offered pursuit, continue it, then stop; no authored motion or model network."""

    def __init__(self):
        super().__init__()
        self.followed = False
        self.stopped = False
        self.next_kind = "follow"
        self.invalid = False

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        enum = payload["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
        prefixes = {
            "follow": "follow ",
            "carry_on": "carry on",
            "stop_following": "stop following",
            "wait": "wait here",
        }
        action = next(
            (label for label in enum if label.startswith(prefixes[self.next_kind])),
            "not an offered action",
        )
        if self.invalid:
            action = "follow an absent creature"
        body = chat_body("", model=payload["model"], prompt_tokens=200, completion_tokens=30)
        body["choices"][0]["finish_reason"] = "tool_calls"
        body["choices"][0]["message"].update(
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call",
                        "type": "function",
                        "function": {
                            "name": "act",
                            "arguments": json.dumps(
                                {
                                    "action": action,
                                    **(
                                        {"line": None}
                                        if "line"
                                        in payload["tools"][0]["function"]["parameters"][
                                            "properties"
                                        ]
                                        else {}
                                    ),
                                }
                            ),
                        },
                    }
                ],
            }
        )
        return HttpResponse(200, json.dumps(body))


class PursuitAnswers(_Live):
    def __init__(self, *args, transport):
        super().__init__(*args)
        self.transport = transport

    def answers(self, requests):
        results = []
        for request in requests:
            kinds = {option["kind"] for option in request["context"]["options"]}
            if not self.transport.followed:
                self.transport.next_kind = "follow"
                self.transport.followed = True
            elif "stop_following" in kinds and request["base_tick"] >= 8:
                self.transport.next_kind = "stop_following"
                self.transport.stopped = True
            else:
                self.transport.next_kind = "wait" if self.transport.stopped else "carry_on"
            results.extend(super().answers([request]))
        return results


def run_scenario(*, invalid=False):
    creature, document, start = scenario()
    subject = inhabitant(start)["id"]
    role = person_role()
    terms = role.terms(THINGS_PROFILE)
    contract = role.contract(terms.versions)
    manifest = _manifest()
    spec = manifest.offered(role.chosen, MODEL_ID)
    mechanism = contract.mechanism_for(spec)
    transport = PursuitTransport()
    transport.invalid = invalid
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=100),
    ).with_policy(RecordingPolicy())
    config = {
        "provider": spec.provider,
        "model_id": MODEL_ID,
        "mechanism": mechanism.value,
        "choice_seq": 1,
        "manifest_sha256": "a" * 64,
        "prompt_version": terms.prompt_version,
        "contract": contract.binding(),
        "deadline_ms": contract.value("decision_deadline_ms"),
    }

    def play(asking):
        return play_minutes(
            [role],
            role,
            start=copy.deepcopy(start),
            sources=[document],
            seed=SEED,
            ticks=20,
            step=_purposeful_step,
            config_for=lambda who: config if who == subject else None,
            request_id_for=lambda who, tick: uuid.uuid5(SOCIETY, f"follow:{who}:{tick}"),
            asking=asking,
            seam=lambda _state, _due: {},
            contract=contract,
            finish=_things_finish(SEED),
        )

    played = play(PursuitAnswers(role, client, spec, mechanism, contract, transport=transport))
    return creature, document, start, role, contract, transport, played, play


def test_generated_body_model_pursuit_moves_at_its_pace_and_replays_without_a_provider():
    creature, _document, start, role, contract, transport, played, play = run_scenario()
    subject = inhabitant(start)["id"]
    assert creature.plan_document["moves"]
    assert any(
        r["proposal"]["option"]["kind"] == "follow" for r in played.receipts if r["proposal"]
    )
    assert any(
        r["proposal"]["option"]["kind"] == "stop_following"
        for r in played.receipts
        if r["proposal"]
    )
    assert [e.kind for e in played.events if str(e.subject_id) == subject].count("followed") == 1
    assert any(
        e.kind == "stopped_following" and e.document["reason"] == "chose_to_stop_following"
        for e in played.events
    )
    people = [inhabitant(state) for state in played.states]
    assert len({tuple(p["position_mm"]) for p in people if p.get("following")}) > 1
    assert not people[-1].get("following")
    pace = pace_permille_of(start, inhabitant(start)["kind"])
    assert pace is not None and pace != 1000
    budget = max(1, 2_000 * pace // 1000)
    moving = [p for p in people if p.get("following") and len(p["motion_path_mm"]) > 1]
    assert moving
    distances = [
        sum(
            math.isqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)
            for a, b in pairwise(p["motion_path_mm"])
        )
        for p in moving
    ]
    assert all(0 < distance <= budget for distance in distances)
    assert budget in distances
    for request, receipt in zip(played.requests, played.receipts, strict=True):
        validate_role_request(role, request)
        validate_role_receipt(role, receipt, request)
        assert (
            role.contract(request["provider_config"]["contract"]["catalog_versions"]).binding()
            == contract.binding()
        )
        assert "surroundings" in request["context"]
        assert "point" not in {o["kind"] for o in request["context"]["options"]}
    assert any("remembers" in request["context"] for request in played.requests[1:])
    before = {state["tick"]: state for state in (start, *played.states)}
    asked_ticks = {request["base_tick"] for request in played.requests}
    assert all(role.adapter.due(before[tick], subject) for tick in asked_ticks)
    assert any(
        state["tick"] - 1 not in asked_ticks
        and inhabitant(state).get("following")
        and len(inhabitant(state)["motion_path_mm"]) > 1
        for state in played.states
    )
    calls = transport.call_count
    replayed = replay_minutes(
        list(zip(played.requests, played.receipts, strict=True)),
        minute_digests=played.minute_digests,
        play=play,
    )
    assert calls > 0 and transport.call_count == calls
    assert replayed.states == played.states and replayed.events == played.events


def test_refused_model_answer_leaves_routine_in_charge_and_never_starts_following():
    _creature, document, start, _role, _contract, transport, played, _play = run_scenario(
        invalid=True
    )
    assert transport.call_count > 0
    assert all(r["status"] == "rejected" and r["proposal"] is None for r in played.receipts)
    assert not any(e.kind == "followed" for e in played.events)
    assert all(not inhabitant(state).get("following") for state in played.states)
    routine = copy.deepcopy(start)
    for actual in played.states:
        planned, events = _purposeful_step(routine, SEED, [document], {})
        routine, _events = _things_finish(SEED)(routine, planned, document, events, [])
        assert inhabitant(actual)["position_mm"] == inhabitant(routine)["position_mm"]
        assert inhabitant(actual)["action"] == inhabitant(routine)["action"]


def test_follow_offers_require_body_capability_and_target_offer_and_preserve_player_point():
    _creature, document, state = scenario()
    role = person_role()
    contract = role.contract(role.terms(THINGS_PROFILE).versions)
    subject = inhabitant(state)
    options = choice_options(state, document, subject["id"], contract, seed=SEED)
    assert {o.addressee_id for o in options if o.kind == "follow"} == {
        inhabitant(state, "guide")["id"]
    }
    assert all(o.addressee_id != subject["id"] for o in options if o.kind == "follow")
    assert "point" not in {o.kind for o in options}
    player = choice_options(
        state, document, subject["id"], play_contract(role, THINGS_PROFILE), seed=SEED
    )
    assert {"follow", "point"} <= {o.kind for o in player}
    _creature, fixed_document, stationary = scenario(walking=False)
    assert not [
        o
        for o in choice_options(
            stationary, fixed_document, inhabitant(stationary)["id"], contract, seed=SEED
        )
        if o.kind == "follow"
    ]
    old = role.contract({"society-decision-action": 5, "society-decision-policy": 5})
    assert not [
        o
        for o in choice_options(state, document, subject["id"], old, seed=SEED)
        if o.kind == "follow"
    ]
    legacy_document = copy.deepcopy(document)
    legacy_document["modules"] = sorted(
        FOLLOW_KEEPING_NEAR if m == FOLLOW_PERSISTENT else m for m in document["modules"]
    )
    legacy_document["document_sha256"] = input_sha256(legacy_document)
    legacy = initial_things_society(SOCIETY, SEED, legacy_document, population=6)
    legacy_subject = inhabitant(legacy)["id"]
    assert not [
        o
        for o in choice_options(legacy, legacy_document, legacy_subject, contract, seed=SEED)
        if o.kind == "follow"
    ]
    assert [
        o
        for o in choice_options(
            legacy, legacy_document, legacy_subject, play_contract(role, THINGS_PROFILE), seed=SEED
        )
        if o.kind == "follow"
    ]


def test_a_receipt_cannot_invent_a_target_and_is_stale_after_target_withdrawal():
    _creature, document, start, role, _contract, _transport, played, _play = run_scenario()
    request, receipt = played.requests[0], played.receipts[0]
    for target in (request["subject_id"], str(uuid.uuid4())):
        result = {
            key: copy.deepcopy(receipt[key]) for key in ("status", "reason", "proposal", "provider")
        }
        result["proposal"]["option"]["addressee_id"] = target
        with pytest.raises(ValueError, match="options it offered"):
            check_role_result(role, result, request)
    withdrawn = copy.deepcopy(start)
    withdrawn["inhabitants"] = [
        p for p in withdrawn["inhabitants"] if p.get("placed_id") != "guide"
    ]
    _policies, [disposition] = model_goal_policies(withdrawn, document, [receipt], {})
    assert (disposition.disposition, disposition.reason) == ("stale", "decision_context_changed")


@pytest.mark.parametrize("stale", [False, True])
def test_explicit_owner_command_cancels_pursuit_only_when_applied_and_replays(stale):
    import test_society_follow as following

    document = compose((following.WELL, following.KNIGHT, following.SQUIRE))
    state = following._following(document)
    subject = following._placed(state, "knight")["id"]
    target = next(t for t in document["targets"] if t["enabled"] and t["affordance"] == "visit")
    request = build_action_request(
        state,
        document,
        request_id=uuid.uuid5(SOCIETY, "owner-command"),
        requested_by=uuid.UUID(int=17),
        subject_id=uuid.UUID(subject),
        intent=ActionIntent("go_to", target["target_id"]),
    )
    if stale:
        state, _events, _crossed = following._minute(state, document)

    def minute(before):
        directed, dispositions = action_goal_policies(before, document, [request])
        policies, _ = model_goal_policies(before, document, [], directed)
        planned, events = advance_purposeful_society(before, SEED, [document], goal_policy=policies)
        events = append_action_events(before, planned, document, [request], dispositions, events)
        after, events = _things_finish(SEED)(before, planned, document, events, [])
        return after, events, dispositions

    result = minute(state)
    assert result == minute(copy.deepcopy(state))
    after, events, [disposition] = result
    assert (disposition.disposition == "applied") is not stale
    assert bool(following._placed(after, "knight").get("following")) is stale
    stopped = [
        event
        for event in events
        if event.kind == "stopped_following" and str(event.subject_id) == subject
    ]
    assert [e.document["reason"] for e in stopped] == ([] if stale else ["chose_otherwise"])
    later, _events, _ = following._minute(after, document)
    assert bool(following._placed(later, "knight").get("following")) is stale
