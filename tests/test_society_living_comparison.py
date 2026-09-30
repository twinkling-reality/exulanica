"""A living town's comparison runs from its own genesis and replays without a model call."""

from __future__ import annotations

import uuid

from exulanica.world.society_catalogs import comparison_catalogs_for_engine
from exulanica.world.society_comparison import RunPlan, play, replay
from exulanica.world.society_comparison_drawing import decode, encode
from exulanica.world.society_comparison_result import replay_document, run_outcome
from exulanica.world.society_decision_contract import decision_contract
from exulanica.world.society_living import LIVING_TOWN_PROFILE, input_routine

from living_town_support import town_input

CONTRACT = decision_contract()
SOURCE = town_input()


class _Choosing:
    def offerable(self, _tick, due):
        return {
            subject: frozenset(option.label for option in options)
            for subject, options in due.items()
        }

    def answers(self, requests):
        results = []
        for request in requests:
            option = next(
                option for option in request["context"]["options"] if option["kind"] == "target"
            )
            results.append(
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": {"label": option["label"], "option": option},
                    "provider": None,
                }
            )
        return results


def _plan(kind: str) -> RunPlan:
    return RunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"living-comparison:{kind}"),
        society_id=uuid.uuid5(uuid.NAMESPACE_URL, "living-comparison:society"),
        seed="town-comparison-development",
        population=SOURCE["population"]["size"],
        inputs=(SOURCE,),
        ticks=8,
        decider=(
            {"kind": "model", "provider": "nebius_token_factory", "model_id": "test/model"}
            if kind == "model"
            else {"kind": kind}
        ),
        provider_config=(
            {
                "provider": "nebius_token_factory",
                "model_id": "test/model",
                "mechanism": "tool_call",
                "choice_seq": None,
                "manifest_sha256": "0" * 64,
                "prompt_version": "society-person-choice/v1",
                "contract": CONTRACT.binding(),
                "deadline_ms": 20_000,
            }
            if kind == "model"
            else None
        ),
        contract=CONTRACT,
        engine_profile=LIVING_TOWN_PROFILE,
    )


def test_living_comparison_plays_and_replays_its_own_model_choices_byte_for_byte():
    plan = _plan("model")
    played = play(plan, _Choosing())
    assert played.start["profile"] == LIVING_TOWN_PROFILE
    assert played.requests and played.receipts
    assert any(
        event.kind == "decision_applied" and event.document["disposition"] == "applied"
        for event in played.events
    )
    again = replay(
        plan,
        list(zip(played.requests, played.receipts, strict=True)),
        minute_digests=played.minute_digests,
    )
    assert again.start == played.start
    assert again.states == played.states
    assert again.events == played.events
    assert again.requests == played.requests
    assert again.receipts == played.receipts
    assert again.choice_points == played.choice_points


def test_living_wait_anchor_keeps_the_group_waiting():
    routine = play(_plan("routine"), _Choosing())
    waited = play(_plan("wait"), _Choosing())
    assert not routine.requests and not waited.requests
    assert routine.minute_digests != waited.minute_digests


def test_living_replay_drawing_round_trips_with_names_and_needs():
    plan = _plan("routine")
    played = play(plan, _Choosing())
    document = replay_document(plan, {}, "one", "f" * 64, played, model_name=lambda model: model)
    assert document["profile"] == "exulanica.society-comparison-run-replay/v3"
    assert document["people"][0]["name"] == "Resident 1"
    assert document["need_thresholds"]
    assert set(document["minutes"][0]["people"][0]["needs"]) == set(document["need_thresholds"])
    assert decode(encode(document)) == document


def test_living_run_records_fourth_score_terms_from_its_exact_needs():
    plan = _plan("routine")
    played = play(plan, _Choosing())
    catalogs = comparison_catalogs_for_engine(plan.engine_profile)
    outcome = run_outcome(
        plan,
        {"profile": "exulanica.society-comparison/v2", "document_sha256": "0" * 64},
        "routine",
        "f" * 64,
        played,
        None,
        catalogs,
    )
    terms = outcome["terms"]
    assert terms["need_thresholds"] == {
        key: catalogs_need.threshold
        for key, catalogs_need in input_routine(SOURCE).needs.items()
        if key in played.start["population"]["supported_needs"]
    }
    assert terms["need_unit"].startswith("sum_of_supported_need_thousandths")
