"""Executable controls for the deterministic living-v4 rest-amenity experiment core."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from exulanica.world.assets import reviewed_assets
from exulanica.world.society import society_state_sha256
from exulanica.world.society_experiments import (
    DEVELOPMENT_SEEDS,
    HELD_OUT_SEEDS,
    ExperimentIntegrityError,
    compare_arm_metrics,
    execute_pair,
    freeze_noop_control_definition,
    freeze_rest_amenity_definition,
    prepare_checkpoint,
    recompute_pair_result,
    verify_pair_result,
)
from exulanica.world.society_living import LIVING_PROFILE, current_routine
from exulanica.world.society_planner import input_sha256, validate_society_input

from society_living_fixtures import grid_input

TARGET_ID = "authored:rest-experiment:rest"
OBJECT_ID = "object:rest-experiment"


def seal(document):
    document["document_sha256"] = input_sha256(document)
    return document


def seal_record(document):
    document["document_sha256"] = society_state_sha256(
        {key: value for key, value in document.items() if key != "document_sha256"}
    )
    return document


def treatment_input(baseline, *, node_id="walk:03:02", affordance="rest", extra=False):
    treatment = deepcopy(baseline)
    treatment["input_seq"] += 1
    treatment["authored_state"] = {
        "edit_seq": baseline["authored_state"]["edit_seq"] + 1,
        "delta_sha256": "e" * 64,
    }
    target = {
        "target_id": TARGET_ID,
        "subject_id": "authored:rest-experiment",
        "node_id": node_id,
        "affordance": affordance,
        "duration_ticks": 3 if affordance == "rest" else 1,
        "origin": "authored",
        "object_id": OBJECT_ID,
        "version_id": treatment["version_id"],
        "enabled": True,
    }
    treatment["targets"].append(target)
    if extra:
        treatment["targets"].append(
            target
            | {
                "target_id": "authored:uncontrolled:rest",
                "subject_id": "authored:uncontrolled",
                "object_id": "object:uncontrolled",
            }
        )
    treatment["targets"].sort(key=lambda row: row["target_id"])
    plate = next(asset for asset in reviewed_assets() if asset.asset_key == "cc0.marker-plate")
    treatment["dependency_refs"].extend(
        [
            {
                "kind": "authored_object",
                "identity": f"{treatment['version_id']}:{OBJECT_ID}",
                "sha256": society_state_sha256(target),
            },
            {
                "kind": "reviewed_asset",
                "identity": plate.asset_key,
                "sha256": plate.content_sha256,
            },
        ]
    )
    treatment["dependency_refs"].sort(key=lambda row: (row["kind"], row["identity"], row["sha256"]))
    return seal(treatment)


@pytest.fixture(scope="module")
def inputs():
    baseline = grid_input(columns=6, rows=4)
    treatment = treatment_input(baseline)
    validate_society_input(treatment)
    return baseline, treatment


@pytest.fixture(scope="module")
def executed(inputs):
    baseline, treatment = inputs
    definition = freeze_rest_amenity_definition(
        baseline,
        treatment,
        target_id=TARGET_ID,
        warmup_ticks=30,
        followup_ticks=60,
        population=4,
    )
    checkpoint = prepare_checkpoint(definition, DEVELOPMENT_SEEDS[0], baseline)
    result, evidence = execute_pair(definition, checkpoint, baseline, treatment)
    assert evidence is not None
    return definition, checkpoint, result, evidence, baseline, treatment


def test_definition_freezes_the_original_protocol_and_unexecuted_held_out_split(inputs):
    baseline, treatment = inputs
    definition = freeze_rest_amenity_definition(
        baseline, treatment, target_id=TARGET_ID, population=4
    )
    assert definition["warmup_ticks"] == 240
    assert definition["followup_ticks"] == 1200
    assert definition["seed_commitment"] == {
        "development": list(DEVELOPMENT_SEEDS),
        "held_out": list(HELD_OUT_SEEDS),
        "held_out_status": "committed_not_executed_in_wave_1",
    }
    assert definition["intervention"]["target"]["target_id"] == TARGET_ID
    assert definition["intervention"]["reviewed_asset"]["asset_key"] == "cc0.marker-plate"
    assert definition["unsupported_metrics"]


def test_invalid_or_uncontrolled_intervention_refuses_before_outcomes(inputs):
    baseline, _ = inputs
    with pytest.raises(ValueError, match="enabled authored rest target"):
        freeze_rest_amenity_definition(
            baseline,
            treatment_input(baseline, affordance="visit"),
            target_id=TARGET_ID,
        )
    with pytest.raises(ValueError, match="exactly the declared target"):
        freeze_rest_amenity_definition(
            baseline,
            treatment_input(baseline, extra=True),
            target_id=TARGET_ID,
        )


def test_a_later_input_cannot_be_frozen_as_the_genesis_checkpoint(inputs):
    _baseline, treatment = inputs
    with pytest.raises(ValueError, match="genesis"):
        freeze_noop_control_definition(treatment)


def test_noop_arms_yield_zero_and_repeat_byte_identically(inputs):
    baseline, _ = inputs
    definition = freeze_noop_control_definition(
        baseline, warmup_ticks=8, followup_ticks=20, population=4
    )
    checkpoint = prepare_checkpoint(definition, DEVELOPMENT_SEEDS[1], baseline)
    first_result, first_evidence = execute_pair(definition, checkpoint, baseline, baseline)
    second_result, second_evidence = execute_pair(definition, checkpoint, baseline, baseline)
    assert first_result == second_result
    assert first_evidence == second_evidence
    assert first_evidence is not None
    assert (
        first_evidence["arms"]["baseline"]["state_sha256s"]
        == first_evidence["arms"]["treatment"]["state_sha256s"]
    )
    for difference in first_result["comparison"].values():
        if isinstance(difference, dict) and "numerator" in difference:
            assert difference["numerator"] == 0


def test_actual_living_transitions_and_independent_consumer_recompute(executed):
    definition, checkpoint, result, evidence, baseline_input, treatment = executed
    assert result["status"] == "valid"
    assert result["invalid_pairs"] == []
    for arm in evidence["arms"].values():
        assert len(arm["states"]) == definition["followup_ticks"]
        assert {state["profile"] for state in arm["states"]} == {LIVING_PROFILE}
        assert arm["states"][0]["tick"] == checkpoint["state"]["tick"] + 1
        assert arm["states"][-1]["tick"] == checkpoint["state"]["tick"] + 60
        assert arm["events"], "the actual engine, not a scripted counter, must produce events"
    assert (
        evidence["arms"]["baseline"]["states"][0]["input_seq"]
        != evidence["arms"]["treatment"]["states"][0]["input_seq"]
    )

    # A deliberately separate test consumer counts the primary numerator straight from canonical
    # state snapshots, then checks the module's recomputation and integrity verifier.
    for label, arm in evidence["arms"].items():
        manual = sum(
            person["needs"]["fatigue"] >= definition["primary_metric"]["threshold_milli"]
            for state in arm["states"]
            for person in state["inhabitants"]
        )
        assert manual == result["arms"][label]["high_fatigue_person_minutes"]["numerator"]
    assert recompute_pair_result(definition, checkpoint, evidence) == result
    verify_pair_result(result, definition, checkpoint, evidence)
    replay_result, replay_evidence = execute_pair(definition, checkpoint, baseline_input, treatment)
    assert replay_result == result
    assert replay_evidence == evidence


def test_swapping_labels_reverses_every_signed_difference(executed):
    _, _, result, _, _, _ = executed
    baseline = result["arms"]["baseline"]
    treatment = result["arms"]["treatment"]
    forward = compare_arm_metrics(treatment, baseline)
    reverse = compare_arm_metrics(baseline, treatment)
    for key in (
        "high_fatigue_fraction",
        "completed_rest_rate",
        "all_rest_occupancy_fraction",
        "travel_mm_per_inhabitant",
        "fatigue_median_milli",
        "fatigue_p95_milli",
    ):
        assert forward[key]["numerator"] == -reverse[key]["numerator"]
        assert forward[key]["denominator"] == reverse[key]["denominator"]


def test_unreachable_intervention_is_an_explicit_invalid_pair():
    baseline = grid_input(columns=6, rows=4)
    isolated = "walk:05:03"
    baseline["navigation"]["edges"] = [
        row
        for row in baseline["navigation"]["edges"]
        if isolated not in (row["from_node_id"], row["to_node_id"])
    ]
    seal(baseline)
    treatment = treatment_input(baseline, node_id=isolated)
    definition = freeze_rest_amenity_definition(
        baseline,
        treatment,
        target_id=TARGET_ID,
        warmup_ticks=2,
        followup_ticks=4,
        population=2,
    )
    checkpoint = prepare_checkpoint(definition, DEVELOPMENT_SEEDS[2], baseline)
    result, evidence = execute_pair(definition, checkpoint, baseline, treatment)
    assert evidence is None
    assert result["status"] == "invalid_pair"
    assert result["invalid_pairs"][0]["code"] == "intervention_unreachable"
    assert result["arms"] is None and result["comparison"] is None


def test_altered_bindings_and_corrupt_result_reject(executed):
    definition, checkpoint, result, evidence, baseline, treatment = executed

    corrupt_checkpoint = deepcopy(checkpoint)
    corrupt_checkpoint["state"]["tick"] += 1
    with pytest.raises(ExperimentIntegrityError, match="checkpoint digest"):
        execute_pair(definition, corrupt_checkpoint, baseline, treatment)

    changed_input = deepcopy(baseline)
    changed_input["authored_state"]["delta_sha256"] = "9" * 64
    seal(changed_input)
    with pytest.raises(ExperimentIntegrityError, match="baseline input binding"):
        execute_pair(definition, checkpoint, changed_input, treatment)

    changed_routine = replace(current_routine(), sha256="0" * 64)
    with pytest.raises(ExperimentIntegrityError, match="routine binding"):
        execute_pair(
            definition,
            checkpoint,
            baseline,
            treatment,
            routine=changed_routine,
        )

    corrupt_result = deepcopy(result)
    corrupt_result["arms"]["baseline"]["population"] += 1
    with pytest.raises(ExperimentIntegrityError, match="result digest"):
        verify_pair_result(corrupt_result, definition, checkpoint, evidence)

    # Even an attacker who recomputes the outer digest cannot turn changed metrics into evidence.
    corrupt_result["document_sha256"] = society_state_sha256(
        {key: value for key, value in corrupt_result.items() if key != "document_sha256"}
    )
    with pytest.raises(ExperimentIntegrityError, match="does not match canonical evidence"):
        verify_pair_result(corrupt_result, definition, checkpoint, evidence)


def test_resealed_checkpoint_cannot_move_a_development_seed_to_held_out(inputs):
    baseline, _ = inputs
    definition = freeze_noop_control_definition(
        baseline, warmup_ticks=2, followup_ticks=4, population=2
    )
    checkpoint = prepare_checkpoint(definition, DEVELOPMENT_SEEDS[0], baseline)
    relabeled = deepcopy(checkpoint)
    relabeled["phase"] = "held_out"
    seal_record(relabeled)
    with pytest.raises(ExperimentIntegrityError, match="not committed to its phase"):
        execute_pair(definition, relabeled, baseline, baseline)


def test_resealed_evidence_cannot_omit_canonical_events(inputs):
    baseline, _ = inputs
    definition = freeze_noop_control_definition(
        baseline, warmup_ticks=2, followup_ticks=4, population=2
    )
    checkpoint = prepare_checkpoint(definition, DEVELOPMENT_SEEDS[0], baseline)
    result, evidence = execute_pair(definition, checkpoint, baseline, baseline)
    assert result["status"] == "valid" and evidence is not None
    assert all(arm["events"] for arm in evidence["arms"].values())

    missing = deepcopy(evidence)
    for arm in missing["arms"].values():
        arm["events"] = []
        arm["events_sha256"] = society_state_sha256({"events": []})
        seal_record(arm)
    seal_record(missing)
    with pytest.raises(ExperimentIntegrityError, match="canonical transition replay"):
        recompute_pair_result(definition, checkpoint, missing)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.update(warmup_ticks=0), "warmup ticks"),
        (
            lambda row: row["primary_metric"].update(threshold_milli=499),
            "primary metric",
        ),
        (lambda row: row["intervention"].update(unexpected=True), "no-op intervention"),
    ],
)
def test_resealed_definition_still_validates_nested_contract(inputs, mutate, message):
    baseline, _ = inputs
    definition = freeze_noop_control_definition(
        baseline, warmup_ticks=2, followup_ticks=4, population=2
    )
    changed = deepcopy(definition)
    mutate(changed)
    seal_record(changed)
    with pytest.raises(ExperimentIntegrityError, match=message):
        prepare_checkpoint(changed, DEVELOPMENT_SEEDS[0], baseline)


def test_resealed_rest_definition_rejects_unrelated_dependency(inputs):
    baseline, treatment = inputs
    definition = freeze_rest_amenity_definition(
        baseline,
        treatment,
        target_id=TARGET_ID,
        warmup_ticks=2,
        followup_ticks=4,
        population=2,
    )
    changed = deepcopy(definition)
    changed["intervention"]["added_dependency_refs"].append(
        {"kind": "unrelated", "identity": "unrelated", "sha256": "f" * 64}
    )
    changed["intervention"]["added_dependency_refs"].sort(
        key=lambda row: (row["kind"], row["identity"], row["sha256"])
    )
    seal_record(changed)
    with pytest.raises(ExperimentIntegrityError, match="unrelated rest intervention"):
        prepare_checkpoint(changed, DEVELOPMENT_SEEDS[0], baseline)
