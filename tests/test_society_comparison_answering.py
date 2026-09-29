"""How a comparison's model is asked is part of what the model is there.

The mechanism a model answers a person's choice by changes what it chooses, not only how long it
takes: lane M4's probe measured Nemotron 3.5 Lightning choosing to wait in 13 of 16 answers by a
JSON schema and in 2 of 16 by a forced call
(``docs/evaluation/2026-09-26-society-model-actions-probe.json``). So a definition records, for
every model it names, the order that model is asked in, whose order that is and the record that
measured a model's own order; a definition that records another order than the contract and the
manifest give is refused, and a run is stopped before it asks anything when they would now ask the
model otherwise than the definition recorded.
"""

from __future__ import annotations

import copy
import types
import uuid

import pytest
from exulanica.api.society_comparison_runner import (
    ComparisonArm,
    SocietyComparisonRunner,
    _RunStoppedBeforeStart,
)
from exulanica.models.manifest import load_manifest
from exulanica.world.society_comparison_result import (
    ComparisonRefused,
    check_definition_body,
)
from exulanica.world.society_decision_contract import decision_contract, person_role

from comparison_support import development_body, model_arm, seeded_catalogs

MANIFEST = load_manifest()
CATALOGS = seeded_catalogs()
NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
QWEN = "Qwen/Qwen3-235B-A22B-Instruct-2507"


class _Client:
    """Stands in for the model client where nothing is asked: a run's asking is only built."""

    def with_policy(self, _policy):
        return self


def _runner() -> SocietyComparisonRunner:
    return SocietyComparisonRunner(
        database=None,  # type: ignore[arg-type]
        runtime=None,  # type: ignore[arg-type]
        client=_Client(),  # type: ignore[arg-type]
        policy_for=lambda _workspace: None,  # type: ignore[arg-type,return-value]
        manifest=MANIFEST,
        manifest_sha256="a" * 64,
        workspace_id=uuid.uuid4(),
        world_id="world:test",
        actor=uuid.uuid4(),
        catalogs=CATALOGS,
    )


def _arm(model_id: str) -> dict:
    spec = MANIFEST.offered(person_role().chosen, model_id)
    return _runner().model_arm(ComparisonArm(spec.provider, spec.model_id), "candidate")


def test_an_arm_records_the_order_its_model_is_asked_in_and_whose_order_it_is():
    nano = MANIFEST.offered(person_role().chosen, NANO)
    qwen = MANIFEST.offered(person_role().chosen, QWEN)
    # The positive controls: Nano's manifest entry states an order measured for it, Qwen's none.
    assert [m.value for m in nano.answering_order] == ["json_schema", "tool_call"]
    assert qwen.answering_order == ()
    assert decision_contract().asks_in_a_models_own_order
    assert _arm(NANO)["answering"] == {
        "order": ["json_schema", "tool_call"],
        "mechanism": "json_schema",
        "source": "model",
        "record": nano.answering_order_record,
    }
    assert _arm(QWEN)["answering"] == {
        "order": ["tool_call", "json_schema"],
        "mechanism": "tool_call",
        "source": "contract",
        "record": None,
    }
    # The mechanism its requests record is the first of that order.
    for model_id in (NANO, QWEN):
        arm = _arm(model_id)
        assert arm["provider_config"]["mechanism"] == arm["answering"]["mechanism"]


def test_the_first_contract_asks_every_model_in_its_own_order():
    """The first decision policy predates a model's own order: under it Nano is asked as every
    model is, by a forced call first, so the contract version is part of the answering too."""
    first = decision_contract(versions={"society-decision-action": 1, "society-decision-policy": 1})
    nano = MANIFEST.offered(person_role().chosen, NANO)
    assert not first.asks_in_a_models_own_order
    assert first.answering(nano) == {
        "order": ["tool_call", "json_schema"],
        "mechanism": "tool_call",
        "source": "contract",
        "record": None,
    }
    assert first.mechanism_for(nano).value == "tool_call"  # type: ignore[union-attr]


def _with_arm(change) -> dict:
    body = copy.deepcopy(development_body(CATALOGS))
    change(body["arms"])
    return body


@pytest.mark.parametrize(
    "change",
    [
        lambda arms: arms["model_a"].pop("answering"),
        lambda arms: arms["routine"].update(answering=arms["model_a"]["answering"]),
        lambda arms: arms["model_a"]["answering"].update(mechanism="json_schema"),
        lambda arms: arms["model_a"]["answering"].update(order=["tool_call", "tool_call"]),
        lambda arms: arms["model_a"]["answering"].update(order=["tool_call", "carrier_pigeon"]),
        lambda arms: arms["model_a"]["answering"].update(source="model"),
        lambda arms: arms["model_a"]["answering"].update(source="the_owner"),
        lambda arms: arms["model_a"]["answering"].update(extra=True),
    ],
    ids=[
        "model-arm-without",
        "anchor-with",
        "mechanism-not-the-configs",
        "mechanism-twice",
        "unknown-mechanism",
        "own-order-without-record",
        "unknown-source",
        "unknown-key",
    ],
)
def test_a_definition_records_exactly_how_each_model_is_asked(change):
    # The positive control: the body as the runner builds it is accepted.
    check_definition_body(development_body(CATALOGS), CATALOGS)
    with pytest.raises(ComparisonRefused, match="arm_answering"):
        check_definition_body(_with_arm(change), CATALOGS)


def test_a_definition_recording_another_order_than_the_contract_gives_is_refused():
    runner = _runner()
    body = copy.deepcopy(development_body(CATALOGS))
    body["arms"]["model_a"] = _arm(NANO)
    # The positive control: the model's answering as the contract and its entry give it.
    runner._answering_held(body)
    # The same mechanism under another order is not how this model is asked here.
    body["arms"]["model_a"]["answering"] = {
        "order": ["json_schema", "tool_call"],
        "mechanism": "json_schema",
        "source": "contract",
        "record": None,
    }
    check_definition_body(body, CATALOGS)  # well formed, and still not this model's
    with pytest.raises(ComparisonRefused, match="answering_not_the_models"):
        runner._answering_held(body)


def _plan(arm: dict) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        decider=arm["decider"],
        provider_config=arm["provider_config"],
        others={},
        contract=decision_contract(),
    )


def test_a_run_whose_model_would_be_asked_in_another_order_stops_before_it_asks():
    runner = _runner()
    arm = _arm(NANO)
    model_id = arm["provider_config"]["model_id"]
    # The positive controls: as recorded, and with nothing recorded (a definition from before
    # answering was recorded, held to the mechanism alone), the run's asking is built.
    runner._asking(_plan(arm), {model_id: arm["answering"]})  # type: ignore[arg-type]
    runner._asking(_plan(arm), {})  # type: ignore[arg-type]
    # The same first mechanism, recorded under another order or as another's order: stopped.
    for changed in (
        {**arm["answering"], "order": ["json_schema"]},
        {**arm["answering"], "source": "contract", "record": None},
    ):
        with pytest.raises(_RunStoppedBeforeStart) as stopped:
            runner._asking(_plan(arm), {model_id: changed})  # type: ignore[arg-type]
        assert stopped.value.code == "provider_configuration_changed"


def test_a_test_arm_is_recorded_as_the_runner_records_one():
    """The shared test arm names its answering by the contract, as the runner does."""
    arm = model_arm("candidate")
    spec = MANIFEST.offered(person_role().chosen, arm["decider"]["model_id"])
    assert arm["answering"] == decision_contract().answering(spec)


def test_one_model_is_asked_one_way_wherever_it_decides():
    """A model that decides for the group in one arm and for somebody outside it is asked in the
    same order in both places: two answerings of one model are refused before anything is
    stored."""
    from exulanica.world.society_comparison_repository import _held_asking

    contract = decision_contract()
    arm = _arm(QWEN)
    body = copy.deepcopy(development_body(CATALOGS))
    body["arms"]["model_a"] = arm
    outside = {
        "id": "b",
        "decider": arm["decider"],
        "provider_config": {**arm["provider_config"], "choice_seq": 1},
        "choice": {"choice_seq": 1, "document_sha256": "d" * 64},
        "answering": dict(arm["answering"]),
    }
    # The positive control: the same answering in both places is held.
    _held_asking(body, [outside], contract, person_role())
    outside["answering"] = {**arm["answering"], "order": ["tool_call"]}
    with pytest.raises(ComparisonRefused, match="asking_not_the_definitions"):
        _held_asking(body, [outside], contract, person_role())


def test_a_run_reads_the_answering_its_definition_recorded_for_each_model():
    """What a run holds its models to is what its definition recorded: the arm's model and every
    model the owner chose for somebody outside the group, by model id; nothing for an anchor, and
    nothing where a definition recorded no answering."""
    from exulanica.api.society_comparison_runner import _recorded_answering

    nano, qwen = _arm(NANO), _arm(QWEN)
    definition = {
        "arms": {"model_a": nano, "routine": {"provider_config": None, "answering": None}},
        "others": [
            {
                "provider_config": {**qwen["provider_config"], "choice_seq": 1},
                "answering": qwen["answering"],
            },
            {"provider_config": None, "answering": None},
        ],
    }
    assert _recorded_answering(definition, "model_a") == {
        NANO: nano["answering"],
        QWEN: qwen["answering"],
    }
    assert _recorded_answering(definition, "routine") == {QWEN: qwen["answering"]}
    unrecorded = {"arms": {"model_a": {**nano, "answering": None}}, "others": []}
    assert _recorded_answering(unrecorded, "model_a") == {}


def test_an_outside_persons_model_records_how_it_is_asked():
    arm = _arm(QWEN)
    body = copy.deepcopy(development_body(CATALOGS))
    body["group"] = {"people": ["a"], "source": {"kind": "named"}}
    outside = {
        "id": "b",
        "decider": arm["decider"],
        "provider_config": {**arm["provider_config"], "choice_seq": 1},
        "choice": {"choice_seq": 1, "document_sha256": "d" * 64},
        "answering": dict(arm["answering"]),
    }
    body["others"] = [outside]
    # The positive control: an outside person's model with its answering is accepted.
    check_definition_body(body, CATALOGS)
    for answering in (None, {**arm["answering"], "mechanism": "json_schema"}):
        body["others"] = [{**outside, "answering": answering}]
        with pytest.raises(ComparisonRefused, match="arm_answering"):
            check_definition_body(body, CATALOGS)
