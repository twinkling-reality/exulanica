"""Pure, deterministic paired experiments over the living-v4 society.

This module does not create authored objects, change a society profile, persist a run, or claim
that synthetic behaviour predicts people.  It consumes two already validated society inputs: a
baseline and a successor that adds exactly one reviewed rest target.  Both arms start from the
same sealed checkpoint and use :func:`advance_living_society` for every follow-up transition.

The first executable contract deliberately measures only facts carried by v4 states and events.
The originally proposed work-shift denominator, an unreachable-goal count, and a record of wanting
rest while every destination was full are not canonical v4 evidence, so results name them as
unsupported instead of estimating them.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from copy import deepcopy
from itertools import pairwise
from typing import Any, Final

from exulanica.world.assets import reviewed_assets
from exulanica.world.society import SOCIETY_NAMESPACE, SocietyEvent, society_state_sha256
from exulanica.world.society_catalogs import RoutineModel
from exulanica.world.society_choice import DeterministicChoices
from exulanica.world.society_living import (
    LIVING_PROFILE,
    LivingPlace,
    advance_living_society,
    current_routine,
    initial_living_society,
    routine_for,
)
from exulanica.world.society_place import ceil_distance, place_from_society_input, validate_place
from exulanica.world.society_planner import validate_input_successor, validate_society_input

__all__ = [
    "CHECKPOINT_PROFILE",
    "DEVELOPMENT_SEEDS",
    "EVIDENCE_PROFILE",
    "EXPERIMENT_PROFILE",
    "HELD_OUT_SEEDS",
    "RESULT_PROFILE",
    "ExperimentIntegrityError",
    "compare_arm_metrics",
    "execute_pair",
    "freeze_noop_control_definition",
    "freeze_rest_amenity_definition",
    "prepare_checkpoint",
    "recompute_pair_result",
    "validate_experiment_checkpoint",
    "validate_experiment_definition",
    "verify_pair_result",
]

EXPERIMENT_PROFILE: Final = "exulanica.society-experiment/rest-amenity/v1"
CHECKPOINT_PROFILE: Final = "exulanica.society-experiment-checkpoint/v1"
EVIDENCE_PROFILE: Final = "exulanica.society-experiment-evidence/v1"
RESULT_PROFILE: Final = "exulanica.society-experiment-result/v1"
ARM_EVIDENCE_PROFILE: Final = "exulanica.society-experiment-arm-evidence/v1"
INTERVENTION_PROFILE: Final = "exulanica.society-intervention/add-rest-amenity/v1"
NOOP_PROFILE: Final = "exulanica.society-intervention/noop/v1"
EXPERIMENT_NAMESPACE: Final = uuid.UUID("b28cc287-cc5c-4ab8-959a-df1996317689")

_QUESTION: Final = (
    "Does one additional reachable one-person rest amenity reduce high-fatigue person-minutes "
    "in this fixed living-v4 synthetic society?"
)
_NON_CLAIMS: Final = (
    "no claim about real people or urban planning",
    "no claim of general social prediction",
    "no visual-plausibility claim",
)
_LIMITS: Final = (
    "the input producer, not this module, validates geometry, rights and object bytes",
    "results establish deterministic synthetic mechanics only",
    "persistence, API and package projection are not part of this core",
)
_UPSTREAM_REQUIREMENTS: Final = (
    "authored object and asset authorization",
    "registered district frame",
    "non-blocking footprint and collision validation",
    "exact transform to the published access node",
)

# Committed before any development outcome was observed. Repeating a digest is replay, not a new
# sample. This wave may run development seeds only; the held-out tuple is retained but unexecuted.
DEVELOPMENT_SEEDS: Final = (
    "d72efdfb8c7801bd6da989751b1b593f1a7d2819791fa0736500119dada453a5",
    "34de30a0788e31f055e62871a5b538d8fb4565ed772816789852a30c2974135e",
    "7bafaff2d76d1f27302a5d73ef4a3472b096745bf37eab0dd87558f4a02677d5",
    "5fb3c2d45a4670cfedd5b357752193288ca2bb30f7ea5af904d18ffc8d2db176",
    "7b193b6210133be895a4bd566dce3fff575cc9e1e80b7a780c16245bb24910a2",
    "8a07ec12aa83d2bba82b884446b7272417cc3470aeb2962ac0df7ecbdc920c10",
    "b0c74f35ee2d055616426653ceb1da669359f3e8cfc8c0f31286bfec5203c8f6",
    "d14e9f8a6d40fc9796dfd953621185bd833a491bfa94fa5a564eb62399332a16",
    "e5d10d283dbc72554f171609b30e1a4743110864f62d1cb9432c03ced714243e",
    "1b140512150cef23211b7a649fcefef15264b12bd34f7c5969fead27d6c7d357",
    "dfdbd9dbe47dd1f26e80cab545f8804bf31aa8d7c94096283150dece59cf84ce",
    "09f1924d67b72f57a2236da8cffa9b8087ad8762eb3c674d8a7870a8acb2ee7d",
    "8707dd081f1cd5459dabf971eef6859c57455a5b274f26021461158acfbb10f4",
    "9fc8b1428f9acc207486231a0b7b242a73bfe5c98510aa57b7e4c30b5222ee5f",
    "8b275dc6940baeb1f7937c6c1ee93c33debc2b8587fa6e6cc6d9b2e653f4e532",
    "2ad0efad239bad7299f7c6a993f6b89df3b809c26aff3c6a981551dc5738c511",
)
HELD_OUT_SEEDS: Final = (
    "600372da11508da6ee76e155ae7231267817a0f003eb58cb9accd8c01ae5117e",
    "5e219814943ea8e2b9559e21a8d8700f6575c9f3afe3a140d937bfa07289a950",
    "b0feb419e4d08998ac026324e875201af10662bfbd761f60e9dfdc95658ee4bc",
    "15d38f35677e6cdc9dbf4d42f8157005b11d8ef4b8a8b237844b656d713fff4d",
    "8b63306c0812924f734319fe7f9bd7989af0383fd5206038985f55c9d38340d6",
    "1427fc8cdb51aa8c8083b3c91a29c45259a6c327b25c5a0ad1ab8d5585f52d15",
    "2122e90f7eeb3b3946efe8e6bf60b070cd47b1f9c7244e95d48fb02a2adab86c",
    "ec41517886d5e405fb9901ff7de6fd0e5cbde8f4df951240390350fcd448713e",
    "868085ae51990a11d17227328b77d042e82af15839ab1bcd06d8ef72f6172255",
    "bc7ffa74220dd38ad830863dfb793d4fa4b45816235b2ac77219f20f685de49a",
    "ccef8362f06bb3f98dd266e98345bd8226342a17211e4decb9533d8e0de4dab7",
    "a774b77387830c0d79c511e0318bc9897c7ee1b869c721c8a9a8cb2151fa130b",
    "584e2a245885b294631a2279704234297df97ba294e4e230af7f88847cf6a9d0",
    "6f21db8d2a1608bbf76312aa438b039300980f43964761ff83430f967da4d0e6",
    "d9ad09d7e3f3071ad9a216b5d88ea3631a5065ad751266e085c8e679b42deb59",
    "e98cc6b90753c9ae8caeef43be00c9df67f66eaba816bdd2af3250fa35e4df5f",
)

_UNSUPPORTED_METRICS: Final = (
    {
        "metric": "completed_work_shifts_over_due_work_shifts",
        "reason": "living-v4 does not canonically record the due-shift denominator",
    },
    {
        "metric": "unreachable_goal_count",
        "reason": "living-v4 does not canonically record every discarded unreachable option",
    },
    {
        "metric": "wanted_rest_but_no_destination_was_free",
        "reason": "living-v4 deliberately does not record this counterfactual shortage",
    },
)


class ExperimentIntegrityError(ValueError):
    """A definition, checkpoint, input, evidence, or result does not match its binding."""


class _InterventionRefusal(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _digest(document: dict[str, Any]) -> str:
    return society_state_sha256({k: v for k, v in document.items() if k != "document_sha256"})


def _seal(document: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(document)
    result["document_sha256"] = _digest(result)
    return result


def _verify_seal(document: dict[str, Any], profile: str, what: str) -> None:
    if document.get("profile") != profile:
        raise ExperimentIntegrityError(f"unsupported {what} profile")
    if document.get("document_sha256") != _digest(document):
        raise ExperimentIntegrityError(f"{what} digest mismatch")


def _input_binding(document: dict[str, Any], place: LivingPlace) -> dict[str, Any]:
    return {
        "profile": document["profile"],
        "input_seq": document["input_seq"],
        "document_sha256": document["document_sha256"],
        "place_sha256": place.document["document_sha256"],
        "world_id": document["world_id"],
        "version_id": document["version_id"],
        "district_id": document["district_id"],
    }


def _marker_plate_digest() -> str:
    return next(
        asset.content_sha256 for asset in reviewed_assets() if asset.asset_key == "cc0.marker-plate"
    )


def _validate_intervention_inputs(
    baseline_input: dict[str, Any],
    treatment_input: dict[str, Any],
    target_id: str,
) -> dict[str, Any]:
    """Verify the successor differs only by one supported authored rest target and its lineage."""
    validate_society_input(baseline_input)
    try:
        validate_input_successor(baseline_input, treatment_input)
    except ValueError as exc:
        raise _InterventionRefusal("invalid_intervention_input", str(exc)) from exc

    old_targets = {row["target_id"]: row for row in baseline_input["targets"]}
    new_targets = {row["target_id"]: row for row in treatment_input["targets"]}
    added_ids = sorted(set(new_targets) - set(old_targets))
    if added_ids != [target_id] or any(new_targets[key] != row for key, row in old_targets.items()):
        raise _InterventionRefusal(
            "intervention_not_one_added_target",
            "treatment must retain every target and add exactly the declared target",
        )
    target = new_targets[target_id]
    if (
        target["origin"] != "authored"
        or not target["object_id"]
        or target["affordance"] != "rest"
        or target["duration_ticks"] != 3
        or target["enabled"] is not True
    ):
        raise _InterventionRefusal(
            "unsupported_rest_intervention",
            "the added target must be one enabled authored rest target with duration three",
        )
    if target["node_id"] not in {row["node_id"] for row in baseline_input["navigation"]["nodes"]}:
        raise _InterventionRefusal(
            "intervention_node_missing", "the added rest target has no baseline navigation node"
        )

    intervention_fields = {
        "input_seq",
        "authored_state",
        "targets",
        "dependency_refs",
        "document_sha256",
    }
    for key in set(baseline_input) | set(treatment_input):
        if key in intervention_fields:
            continue
        if key not in baseline_input or key not in treatment_input:
            raise _InterventionRefusal(
                "intervention_changed_baseline",
                f"the treatment changed the presence of baseline field {key}",
            )
        if treatment_input[key] != baseline_input[key]:
            raise _InterventionRefusal(
                "intervention_changed_baseline",
                f"the treatment changed baseline field {key}",
            )
    old_authored, new_authored = baseline_input["authored_state"], treatment_input["authored_state"]
    if (
        new_authored["edit_seq"] != old_authored["edit_seq"] + 1
        or new_authored["delta_sha256"] == old_authored["delta_sha256"]
    ):
        raise _InterventionRefusal(
            "invalid_authored_successor",
            "the intervention needs exactly one new authored cursor and a new delta digest",
        )

    old_refs = {
        (row["kind"], row["identity"], row["sha256"]): row
        for row in baseline_input["dependency_refs"]
    }
    new_refs = {
        (row["kind"], row["identity"], row["sha256"]): row
        for row in treatment_input["dependency_refs"]
    }
    if not set(old_refs) <= set(new_refs):
        raise _InterventionRefusal(
            "intervention_removed_dependency", "the treatment removed baseline dependency evidence"
        )
    added_refs = [new_refs[key] for key in sorted(set(new_refs) - set(old_refs))]
    expected_object_identity = f"{treatment_input['version_id']}:{target['object_id']}"
    object_refs = [
        row
        for row in added_refs
        if row["kind"] == "authored_object" and row["identity"] == expected_object_identity
    ]
    if len(object_refs) != 1:
        raise _InterventionRefusal(
            "missing_authored_object_lineage",
            "the added target needs one new authored-object dependency",
        )
    plate_digest = _marker_plate_digest()
    if not any(
        row
        == {
            "kind": "reviewed_asset",
            "identity": "cc0.marker-plate",
            "sha256": plate_digest,
        }
        for row in treatment_input["dependency_refs"]
    ):
        raise _InterventionRefusal(
            "unreviewed_rest_asset",
            "the treatment does not bind the reviewed cc0.marker-plate bytes",
        )
    allowed_added = {
        ("authored_object", expected_object_identity),
        ("reviewed_asset", "cc0.marker-plate"),
    }
    if any((row["kind"], row["identity"]) not in allowed_added for row in added_refs):
        raise _InterventionRefusal(
            "intervention_added_unrelated_dependency",
            "the treatment added dependency evidence unrelated to the one rest amenity",
        )
    return {
        "profile": INTERVENTION_PROFILE,
        "target": deepcopy(target),
        "reviewed_asset": {
            "asset_key": "cc0.marker-plate",
            "content_sha256": plate_digest,
        },
        "added_dependency_refs": deepcopy(added_refs),
        "upstream_requirements": list(_UPSTREAM_REQUIREMENTS),
    }


def _definition(
    *,
    purpose: str,
    baseline_input: dict[str, Any],
    treatment_input: dict[str, Any],
    intervention: dict[str, Any],
    warmup_ticks: int,
    followup_ticks: int,
    population: int | None,
    routine: RoutineModel,
) -> dict[str, Any]:
    if type(warmup_ticks) is not int or warmup_ticks < 1:
        raise ValueError("warmup ticks must be positive")
    if type(followup_ticks) is not int or followup_ticks < 1:
        raise ValueError("follow-up ticks must be positive")
    if population is not None and (type(population) is not int or population < 1):
        raise ValueError("population must be positive or omitted")
    if baseline_input.get("input_seq") != 1:
        raise ValueError("an experiment baseline must be the society genesis input")
    baseline_place = LivingPlace(place_from_society_input(baseline_input, routine), routine)
    treatment_place = LivingPlace(place_from_society_input(treatment_input, routine), routine)
    baseline_rest_capacity = sum(
        row["visitor_capacity"]
        for row in baseline_place.document["destinations"]
        if row["enabled"] and "rest" in row["affordances"]
    )
    if baseline_rest_capacity < 1:
        raise ValueError("the baseline must publish at least one usable rest destination")
    return _seal(
        {
            "profile": EXPERIMENT_PROFILE,
            "purpose": purpose,
            "question": _QUESTION,
            "non_claims": list(_NON_CLAIMS),
            "engine_profile": LIVING_PROFILE,
            "choice_source": "deterministic_chooser",
            "routine": routine.binding(),
            "baseline_input": _input_binding(baseline_input, baseline_place),
            "treatment_input": _input_binding(treatment_input, treatment_place),
            "intervention": intervention,
            "warmup_ticks": warmup_ticks,
            "followup_ticks": followup_ticks,
            "population": population,
            "primary_metric": {
                "name": "high_fatigue_person_minutes",
                "need": "fatigue",
                "threshold_milli": routine.needs["fatigue"].threshold,
                "denominator": "eligible_population_times_followup_ticks",
                "predeclared_relative_improvement_threshold_milli": 100,
            },
            "seed_commitment": {
                "development": list(DEVELOPMENT_SEEDS),
                "held_out": list(HELD_OUT_SEEDS),
                "held_out_status": "committed_not_executed_in_wave_1",
            },
            "unsupported_metrics": deepcopy(list(_UNSUPPORTED_METRICS)),
            "limits": list(_LIMITS),
        }
    )


def freeze_rest_amenity_definition(
    baseline_input: dict[str, Any],
    treatment_input: dict[str, Any],
    *,
    target_id: str,
    warmup_ticks: int = 240,
    followup_ticks: int = 1200,
    population: int | None = None,
    routine: RoutineModel | None = None,
) -> dict[str, Any]:
    """Freeze exact inputs, split, metrics and one reviewed intervention before a run."""
    model = current_routine() if routine is None else routine
    intervention = _validate_intervention_inputs(baseline_input, treatment_input, target_id)
    return _definition(
        purpose="development_or_held_out_pair",
        baseline_input=baseline_input,
        treatment_input=treatment_input,
        intervention=intervention,
        warmup_ticks=warmup_ticks,
        followup_ticks=followup_ticks,
        population=population,
        routine=model,
    )


def freeze_noop_control_definition(
    baseline_input: dict[str, Any],
    *,
    warmup_ticks: int = 240,
    followup_ticks: int = 1200,
    population: int | None = None,
    routine: RoutineModel | None = None,
) -> dict[str, Any]:
    """Freeze an instrument control whose two arms deliberately consume the same input."""
    model = current_routine() if routine is None else routine
    validate_society_input(baseline_input)
    return _definition(
        purpose="no_op_instrument_control",
        baseline_input=baseline_input,
        treatment_input=baseline_input,
        intervention={"profile": NOOP_PROFILE},
        warmup_ticks=warmup_ticks,
        followup_ticks=followup_ticks,
        population=population,
        routine=model,
    )


def validate_experiment_definition(
    definition: dict[str, Any],
    baseline_input: dict[str, Any],
    treatment_input: dict[str, Any],
    *,
    routine: RoutineModel | None = None,
) -> None:
    """Validate a frozen definition against both complete authoritative input documents.

    A digest carried by a caller is not authority. Persistence adapters use this function only
    after resolving the two immutable input rows themselves, so the definition is checked against
    the full documents and their derived places before any record is written.
    """
    model = current_routine() if routine is None else routine
    _validate_definition(definition, model)
    _validate_bound_input(definition["baseline_input"], baseline_input, "baseline")
    _validate_bound_input(definition["treatment_input"], treatment_input, "treatment")
    baseline_place = LivingPlace(place_from_society_input(baseline_input, model), model)
    treatment_place = LivingPlace(place_from_society_input(treatment_input, model), model)
    if baseline_place.document["document_sha256"] != definition["baseline_input"]["place_sha256"]:
        raise ExperimentIntegrityError("baseline place changed after definition freeze")
    if treatment_place.document["document_sha256"] != definition["treatment_input"]["place_sha256"]:
        raise ExperimentIntegrityError("treatment place changed after definition freeze")
    if definition["intervention"]["profile"] == NOOP_PROFILE:
        if baseline_input != treatment_input:
            raise ExperimentIntegrityError("no-op definition does not bind one exact input")
        return
    try:
        intervention = _validate_intervention_inputs(
            baseline_input,
            treatment_input,
            definition["intervention"]["target"]["target_id"],
        )
    except _InterventionRefusal as exc:
        raise ExperimentIntegrityError(exc.detail) from exc
    if intervention != definition["intervention"]:
        raise ExperimentIntegrityError("intervention binding changed after definition freeze")


_DEFINITION_FIELDS: Final = {
    "profile",
    "purpose",
    "question",
    "non_claims",
    "engine_profile",
    "choice_source",
    "routine",
    "baseline_input",
    "treatment_input",
    "intervention",
    "warmup_ticks",
    "followup_ticks",
    "population",
    "primary_metric",
    "seed_commitment",
    "unsupported_metrics",
    "limits",
    "document_sha256",
}


def _validate_definition(definition: dict[str, Any], routine: RoutineModel) -> None:
    _verify_seal(definition, EXPERIMENT_PROFILE, "experiment definition")
    if set(definition) != _DEFINITION_FIELDS:
        raise ExperimentIntegrityError("invalid experiment definition fields")
    if definition["engine_profile"] != LIVING_PROFILE:
        raise ExperimentIntegrityError("experiment engine profile mismatch")
    if definition["choice_source"] != "deterministic_chooser":
        raise ExperimentIntegrityError("experiment does not use the deterministic chooser")
    if definition["routine"] != routine.binding():
        raise ExperimentIntegrityError("experiment routine binding mismatch")
    if (
        definition["question"] != _QUESTION
        or definition["non_claims"] != list(_NON_CLAIMS)
        or definition["limits"] != list(_LIMITS)
        or definition["unsupported_metrics"] != list(_UNSUPPORTED_METRICS)
    ):
        raise ExperimentIntegrityError("experiment declaration mismatch")
    if type(definition["warmup_ticks"]) is not int or definition["warmup_ticks"] < 1:
        raise ExperimentIntegrityError("experiment warmup ticks must be positive")
    if type(definition["followup_ticks"]) is not int or definition["followup_ticks"] < 1:
        raise ExperimentIntegrityError("experiment follow-up ticks must be positive")
    population = definition["population"]
    if population is not None and (type(population) is not int or population < 1):
        raise ExperimentIntegrityError("experiment population must be positive or omitted")
    if definition["primary_metric"] != {
        "name": "high_fatigue_person_minutes",
        "need": "fatigue",
        "threshold_milli": routine.needs["fatigue"].threshold,
        "denominator": "eligible_population_times_followup_ticks",
        "predeclared_relative_improvement_threshold_milli": 100,
    }:
        raise ExperimentIntegrityError("experiment primary metric mismatch")
    for name in ("baseline_input", "treatment_input"):
        binding = definition[name]
        if set(binding) != {
            "profile",
            "input_seq",
            "document_sha256",
            "place_sha256",
            "world_id",
            "version_id",
            "district_id",
        }:
            raise ExperimentIntegrityError(f"invalid {name.replace('_', ' ')} fields")
        if (
            binding["profile"]
            not in (
                "exulanica.society-input/v1",
                "exulanica.society-input/v2",
            )
            or type(binding["input_seq"]) is not int
            or binding["input_seq"] < 1
            or not all(
                isinstance(binding[key], str) and binding[key]
                for key in ("world_id", "version_id", "district_id")
            )
            or not all(_is_digest(binding[key]) for key in ("document_sha256", "place_sha256"))
        ):
            raise ExperimentIntegrityError(f"invalid {name.replace('_', ' ')} binding")
    baseline, treatment = definition["baseline_input"], definition["treatment_input"]
    if baseline["input_seq"] != 1:
        raise ExperimentIntegrityError("experiment baseline is not the genesis input")
    intervention = definition["intervention"]
    if definition["purpose"] == "no_op_instrument_control":
        if intervention != {"profile": NOOP_PROFILE} or treatment != baseline:
            raise ExperimentIntegrityError("invalid no-op intervention binding")
    elif definition["purpose"] == "development_or_held_out_pair":
        _validate_intervention_binding(intervention, baseline, treatment)
    else:
        raise ExperimentIntegrityError("unsupported experiment purpose")
    seeds = definition["seed_commitment"]
    if seeds != {
        "development": list(DEVELOPMENT_SEEDS),
        "held_out": list(HELD_OUT_SEEDS),
        "held_out_status": "committed_not_executed_in_wave_1",
    }:
        raise ExperimentIntegrityError("experiment seed commitment mismatch")


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_intervention_binding(
    intervention: dict[str, Any],
    baseline: dict[str, Any],
    treatment: dict[str, Any],
) -> None:
    if (
        set(intervention)
        != {
            "profile",
            "target",
            "reviewed_asset",
            "added_dependency_refs",
            "upstream_requirements",
        }
        or intervention["profile"] != INTERVENTION_PROFILE
    ):
        raise ExperimentIntegrityError("invalid rest intervention fields")
    if intervention["upstream_requirements"] != list(_UPSTREAM_REQUIREMENTS):
        raise ExperimentIntegrityError("rest intervention upstream requirements mismatch")
    target = intervention["target"]
    if set(target) != {
        "target_id",
        "subject_id",
        "node_id",
        "affordance",
        "duration_ticks",
        "origin",
        "object_id",
        "version_id",
        "enabled",
    } or (
        target["affordance"] != "rest"
        or target["duration_ticks"] != 3
        or target["origin"] != "authored"
        or target["enabled"] is not True
        or not all(
            isinstance(target[key], str) and target[key]
            for key in ("target_id", "subject_id", "node_id", "object_id")
        )
        or target["version_id"] != treatment["version_id"]
    ):
        raise ExperimentIntegrityError("invalid rest intervention target")
    if intervention["reviewed_asset"] != {
        "asset_key": "cc0.marker-plate",
        "content_sha256": _marker_plate_digest(),
    }:
        raise ExperimentIntegrityError("rest intervention reviewed asset mismatch")
    refs = intervention["added_dependency_refs"]
    if not isinstance(refs, list) or not refs:
        raise ExperimentIntegrityError("rest intervention dependency binding missing")
    expected_object = f"{treatment['version_id']}:{target['object_id']}"
    object_refs = 0
    keys = []
    for row in refs:
        if set(row) != {"kind", "identity", "sha256"} or not _is_digest(row["sha256"]):
            raise ExperimentIntegrityError("invalid rest intervention dependency binding")
        key = (row["kind"], row["identity"], row["sha256"])
        keys.append(key)
        if row["kind"] == "authored_object" and row["identity"] == expected_object:
            object_refs += 1
        elif row != {
            "kind": "reviewed_asset",
            "identity": "cc0.marker-plate",
            "sha256": _marker_plate_digest(),
        }:
            raise ExperimentIntegrityError("unrelated rest intervention dependency binding")
    if keys != sorted(set(keys)):
        raise ExperimentIntegrityError("rest intervention dependencies must be sorted and unique")
    if object_refs != 1:
        raise ExperimentIntegrityError("rest intervention authored-object binding missing")
    if treatment["input_seq"] != baseline["input_seq"] + 1:
        raise ExperimentIntegrityError("rest intervention input sequence mismatch")
    for key in ("profile", "world_id", "version_id", "district_id"):
        if treatment[key] != baseline[key]:
            raise ExperimentIntegrityError(f"rest intervention changed {key}")
    if (
        treatment["document_sha256"] == baseline["document_sha256"]
        or treatment["place_sha256"] == baseline["place_sha256"]
    ):
        raise ExperimentIntegrityError("rest intervention did not change input and place")


def _validate_bound_input(binding: dict[str, Any], document: dict[str, Any], name: str) -> None:
    validate_society_input(document)
    if document["document_sha256"] != binding["document_sha256"]:
        raise ExperimentIntegrityError(f"{name} input binding mismatch")
    for key in ("profile", "input_seq", "world_id", "version_id", "district_id"):
        if document[key] != binding[key]:
            raise ExperimentIntegrityError(f"{name} input changed {key}")


def prepare_checkpoint(
    definition: dict[str, Any],
    seed_sha256: str,
    baseline_input: dict[str, Any],
    *,
    phase: str = "development",
    routine: RoutineModel | None = None,
) -> dict[str, Any]:
    """Advance one actual living-v4 society to the definition's sealed split point."""
    model = current_routine() if routine is None else routine
    _validate_definition(definition, model)
    _validate_bound_input(definition["baseline_input"], baseline_input, "baseline")
    allowed = DEVELOPMENT_SEEDS if phase == "development" else HELD_OUT_SEEDS
    if phase not in ("development", "held_out"):
        raise ValueError("phase must be development or held_out")
    if seed_sha256 not in allowed:
        raise ExperimentIntegrityError(f"seed is not committed to the {phase} split")

    place = LivingPlace(place_from_society_input(baseline_input, model), model)
    if place.document["document_sha256"] != definition["baseline_input"]["place_sha256"]:
        raise ExperimentIntegrityError("baseline place binding mismatch")
    society_id = uuid.uuid5(EXPERIMENT_NAMESPACE, f"{definition['document_sha256']}:{seed_sha256}")
    state = initial_living_society(
        society_id,
        seed_sha256,
        place,
        model,
        branch_id=f"experiment:{definition['document_sha256']}",
        population=definition["population"],
    )
    warmup_events: list[dict[str, Any]] = []
    for _ in range(definition["warmup_ticks"]):
        state, produced = advance_living_society(
            state, seed_sha256, [place], model, DeterministicChoices()
        )
        warmup_events.extend(_event_document(event) for event in produced)
    return _seal(
        {
            "profile": CHECKPOINT_PROFILE,
            "definition_sha256": definition["document_sha256"],
            "phase": phase,
            "seed_sha256": seed_sha256,
            "warmup_ticks": definition["warmup_ticks"],
            "input": deepcopy(definition["baseline_input"]),
            "routine": model.binding(),
            "state": state,
            "state_sha256": society_state_sha256(state),
            "warmup_event_count": len(warmup_events),
            "warmup_events_sha256": society_state_sha256({"events": warmup_events}),
        }
    )


def _validate_checkpoint(
    definition: dict[str, Any], checkpoint: dict[str, Any], routine: RoutineModel
) -> None:
    _verify_seal(checkpoint, CHECKPOINT_PROFILE, "experiment checkpoint")
    if set(checkpoint) != {
        "profile",
        "definition_sha256",
        "phase",
        "seed_sha256",
        "warmup_ticks",
        "input",
        "routine",
        "state",
        "state_sha256",
        "warmup_event_count",
        "warmup_events_sha256",
        "document_sha256",
    }:
        raise ExperimentIntegrityError("invalid experiment checkpoint fields")
    if checkpoint["definition_sha256"] != definition["document_sha256"]:
        raise ExperimentIntegrityError("checkpoint definition binding mismatch")
    phase = checkpoint["phase"]
    if phase not in ("development", "held_out"):
        raise ExperimentIntegrityError("checkpoint phase is invalid")
    committed = DEVELOPMENT_SEEDS if phase == "development" else HELD_OUT_SEEDS
    if checkpoint["seed_sha256"] not in committed:
        raise ExperimentIntegrityError("checkpoint seed is not committed to its phase")
    if checkpoint["warmup_ticks"] != definition["warmup_ticks"]:
        raise ExperimentIntegrityError("checkpoint warmup binding mismatch")
    if checkpoint["input"] != definition["baseline_input"]:
        raise ExperimentIntegrityError("checkpoint input binding mismatch")
    if checkpoint["routine"] != routine.binding():
        raise ExperimentIntegrityError("checkpoint routine binding mismatch")
    state = checkpoint["state"]
    if society_state_sha256(state) != checkpoint["state_sha256"]:
        raise ExperimentIntegrityError("checkpoint state digest mismatch")
    if (
        state.get("profile") != LIVING_PROFILE
        or state.get("tick") != definition["warmup_ticks"]
        or state.get("seed_sha256") != checkpoint["seed_sha256"]
        or state.get("routine") != routine.binding()
        or state.get("input_sha256") != definition["baseline_input"]["document_sha256"]
        or state.get("place", {}).get("place_sha256")
        != definition["baseline_input"]["place_sha256"]
    ):
        raise ExperimentIntegrityError("checkpoint state binding mismatch")


def _verify_checkpoint_replay(
    definition: dict[str, Any],
    checkpoint: dict[str, Any],
    baseline_place: LivingPlace,
    routine: RoutineModel,
) -> None:
    """Rebuild the checkpoint and its complete event stream from genesis."""
    seed_sha256 = checkpoint["seed_sha256"]
    society_id = uuid.uuid5(EXPERIMENT_NAMESPACE, f"{definition['document_sha256']}:{seed_sha256}")
    state = initial_living_society(
        society_id,
        seed_sha256,
        baseline_place,
        routine,
        branch_id=f"experiment:{definition['document_sha256']}",
        population=definition["population"],
    )
    events: list[dict[str, Any]] = []
    for _ in range(definition["warmup_ticks"]):
        state, produced = advance_living_society(
            state, seed_sha256, [baseline_place], routine, DeterministicChoices()
        )
        events.extend(_event_document(event) for event in produced)
    if (
        state != checkpoint["state"]
        or society_state_sha256(state) != checkpoint["state_sha256"]
        or len(events) != checkpoint["warmup_event_count"]
        or society_state_sha256({"events": events}) != checkpoint["warmup_events_sha256"]
    ):
        raise ExperimentIntegrityError("checkpoint does not match canonical warmup replay")


def validate_experiment_checkpoint(
    definition: dict[str, Any],
    checkpoint: dict[str, Any],
    baseline_input: dict[str, Any],
    *,
    routine: RoutineModel | None = None,
) -> None:
    """Validate and replay a sealed checkpoint from the authoritative baseline input."""
    model = current_routine() if routine is None else routine
    _validate_definition(definition, model)
    _validate_checkpoint(definition, checkpoint, model)
    _validate_bound_input(definition["baseline_input"], baseline_input, "baseline")
    baseline_place = LivingPlace(place_from_society_input(baseline_input, model), model)
    if baseline_place.document["document_sha256"] != definition["baseline_input"]["place_sha256"]:
        raise ExperimentIntegrityError("baseline place changed after definition freeze")
    _verify_checkpoint_replay(definition, checkpoint, baseline_place, model)


def _event_document(event: SocietyEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "tick": event.tick,
        "kind": event.kind,
        "subject_id": str(event.subject_id),
        "object_id": None if event.object_id is None else str(event.object_id),
        "document": deepcopy(event.document),
    }


def _ensure_intervention_reachable(
    checkpoint: dict[str, Any], treatment_place: LivingPlace, intervention: dict[str, Any]
) -> None:
    target_id = intervention["target"]["target_id"]
    destination = treatment_place.destinations.get(target_id)
    if destination is None or destination["visitor_capacity"] != 1:
        raise _InterventionRefusal(
            "intervention_not_one_person", "the added rest destination is not one-person capacity"
        )
    node_id = destination["node_id"]
    for person in checkpoint["state"]["inhabitants"]:
        location = person["location"]
        start = location["node_id"] if location["edge"] is None else location["edge"]["to_node_id"]
        if node_id not in treatment_place.paths(start):
            raise _InterventionRefusal(
                "intervention_unreachable",
                f"the added rest destination is unreachable for inhabitant {person['ordinal']}",
            )


def _run_arm(
    *,
    definition: dict[str, Any],
    checkpoint: dict[str, Any],
    seed_sha256: str,
    baseline_place: LivingPlace,
    applied_place: LivingPlace,
    routine: RoutineModel,
    intervention_applied: bool,
) -> dict[str, Any]:
    state = checkpoint["state"]
    states: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for index in range(definition["followup_ticks"]):
        places = (
            [baseline_place, applied_place]
            if index == 0 and intervention_applied
            else [applied_place]
        )
        state, produced = advance_living_society(
            state, seed_sha256, places, routine, DeterministicChoices()
        )
        states.append(state)
        events.extend(_event_document(event) for event in produced)
    state_digests = [society_state_sha256(state) for state in states]
    return _seal(
        {
            "profile": ARM_EVIDENCE_PROFILE,
            "definition_sha256": definition["document_sha256"],
            "checkpoint_sha256": checkpoint["document_sha256"],
            "seed_sha256": seed_sha256,
            "intervention_applied": intervention_applied,
            "input_sha256": applied_place.document["source"]["document_sha256"],
            "place": deepcopy(applied_place.document),
            "states": states,
            "state_sha256s": state_digests,
            "events": events,
            "events_sha256": society_state_sha256({"events": events}),
            "final_state_sha256": state_digests[-1],
        }
    )


def _invalid_result(
    definition: dict[str, Any], checkpoint: dict[str, Any], refusal: _InterventionRefusal
) -> dict[str, Any]:
    return _seal(
        {
            "profile": RESULT_PROFILE,
            "status": "invalid_pair",
            "definition_sha256": definition["document_sha256"],
            "checkpoint_sha256": checkpoint["document_sha256"],
            "seed_sha256": checkpoint["seed_sha256"],
            "invalid_pairs": [{"code": refusal.code, "detail": refusal.detail}],
            "arms": None,
            "comparison": None,
            "unsupported_metrics": deepcopy(definition["unsupported_metrics"]),
        }
    )


def execute_pair(
    definition: dict[str, Any],
    checkpoint: dict[str, Any],
    baseline_input: dict[str, Any],
    treatment_input: dict[str, Any],
    *,
    routine: RoutineModel | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Run both arms from one checkpoint and return a sealed result plus canonical evidence.

    Intervention-delivery failures are explicit invalid-pair results. Integrity failures in an
    already sealed definition, checkpoint, input, evidence or result raise instead.
    """
    model = current_routine() if routine is None else routine
    _validate_definition(definition, model)
    _validate_checkpoint(definition, checkpoint, model)
    _validate_bound_input(definition["baseline_input"], baseline_input, "baseline")
    _validate_bound_input(definition["treatment_input"], treatment_input, "treatment")
    baseline_place = LivingPlace(place_from_society_input(baseline_input, model), model)
    treatment_place = LivingPlace(place_from_society_input(treatment_input, model), model)
    if baseline_place.document["document_sha256"] != definition["baseline_input"]["place_sha256"]:
        raise ExperimentIntegrityError("baseline place changed after definition freeze")
    if treatment_place.document["document_sha256"] != definition["treatment_input"]["place_sha256"]:
        raise ExperimentIntegrityError("treatment place changed after definition freeze")
    _verify_checkpoint_replay(definition, checkpoint, baseline_place, model)

    applied = definition["intervention"]["profile"] != NOOP_PROFILE
    if applied:
        try:
            intervention = _validate_intervention_inputs(
                baseline_input,
                treatment_input,
                definition["intervention"]["target"]["target_id"],
            )
            if intervention != definition["intervention"]:
                raise ExperimentIntegrityError(
                    "intervention binding changed after definition freeze"
                )
            _ensure_intervention_reachable(checkpoint, treatment_place, intervention)
        except _InterventionRefusal as refusal:
            return _invalid_result(definition, checkpoint, refusal), None

    seed_sha256 = checkpoint["seed_sha256"]
    try:
        baseline = _run_arm(
            definition=definition,
            checkpoint=checkpoint,
            seed_sha256=seed_sha256,
            baseline_place=baseline_place,
            applied_place=baseline_place,
            routine=model,
            intervention_applied=False,
        )
    except ValueError as exc:
        refusal = _InterventionRefusal("baseline_transition_refused", str(exc))
        return _invalid_result(definition, checkpoint, refusal), None
    try:
        treatment = _run_arm(
            definition=definition,
            checkpoint=checkpoint,
            seed_sha256=seed_sha256,
            baseline_place=baseline_place,
            applied_place=treatment_place,
            routine=model,
            intervention_applied=applied,
        )
    except ValueError as exc:
        refusal = _InterventionRefusal("treatment_transition_refused", str(exc))
        return _invalid_result(definition, checkpoint, refusal), None
    evidence = _seal(
        {
            "profile": EVIDENCE_PROFILE,
            "definition_sha256": definition["document_sha256"],
            "checkpoint_sha256": checkpoint["document_sha256"],
            "seed_sha256": seed_sha256,
            "arms": {"baseline": baseline, "treatment": treatment},
        }
    )
    return recompute_pair_result(definition, checkpoint, evidence), evidence


def _verify_event(
    row: dict[str, Any], previous_state: dict[str, Any], state: dict[str, Any]
) -> None:
    document = row["document"]
    if (
        row["tick"] != state["tick"]
        or document["tick"] != state["tick"]
        or document["previous_state_sha256"] != society_state_sha256(previous_state)
        or document["input_sha256"] != state["input_sha256"]
        or document["place_sha256"] != state["place"]["place_sha256"]
        or row["subject_id"] != document["subject_id"]
    ):
        raise ExperimentIntegrityError("event does not bind its transition")
    expected = uuid.uuid5(
        SOCIETY_NAMESPACE,
        f"{state['society_id']}:{row['tick']}:{document['order']}:{society_state_sha256(document)}",
    )
    if str(expected) != row["event_id"]:
        raise ExperimentIntegrityError("event identity mismatch")


def _nearest_rank(values: list[int], numerator: int, denominator: int) -> int:
    if not values:
        raise ExperimentIntegrityError("a metric has no observations")
    ordered = sorted(values)
    rank = max(1, math.ceil(len(ordered) * numerator / denominator))
    return ordered[rank - 1]


def _ratio(numerator: int, denominator: int, *, scale: int | None = None) -> dict[str, Any]:
    if denominator <= 0:
        raise ExperimentIntegrityError("metric denominator is not positive")
    result: dict[str, Any] = {"numerator": numerator, "denominator": denominator}
    if scale is not None:
        result["scaled_by"] = scale
        result["scaled_floor"] = numerator * scale // denominator
    return result


def _arm_metrics(
    definition: dict[str, Any],
    checkpoint: dict[str, Any],
    arm: dict[str, Any],
    *,
    expected_binding: dict[str, Any],
    expected_intervention: bool,
    routine: RoutineModel,
) -> dict[str, Any]:
    _verify_seal(arm, ARM_EVIDENCE_PROFILE, "arm evidence")
    if set(arm) != {
        "profile",
        "definition_sha256",
        "checkpoint_sha256",
        "seed_sha256",
        "intervention_applied",
        "input_sha256",
        "place",
        "states",
        "state_sha256s",
        "events",
        "events_sha256",
        "final_state_sha256",
        "document_sha256",
    }:
        raise ExperimentIntegrityError("invalid arm evidence fields")
    if (
        arm["definition_sha256"] != definition["document_sha256"]
        or arm["checkpoint_sha256"] != checkpoint["document_sha256"]
        or arm["seed_sha256"] != checkpoint["seed_sha256"]
        or arm["intervention_applied"] is not expected_intervention
        or arm["input_sha256"] != expected_binding["document_sha256"]
    ):
        raise ExperimentIntegrityError("arm evidence binding mismatch")
    validate_place(arm["place"], routine)
    if (
        arm["place"]["document_sha256"] != expected_binding["place_sha256"]
        or arm["place"]["source"]["document_sha256"] != expected_binding["document_sha256"]
        or arm["place"]["source"]["input_seq"] != expected_binding["input_seq"]
    ):
        raise ExperimentIntegrityError("arm place binding mismatch")
    states = arm["states"]
    if len(states) != definition["followup_ticks"]:
        raise ExperimentIntegrityError("arm evidence follow-up length mismatch")
    state_digests = [society_state_sha256(state) for state in states]
    if (
        state_digests != arm["state_sha256s"]
        or state_digests[-1] != arm["final_state_sha256"]
        or society_state_sha256({"events": arm["events"]}) != arm["events_sha256"]
    ):
        raise ExperimentIntegrityError("arm evidence digest mismatch")

    people = len(checkpoint["state"]["inhabitants"])
    fatigue: list[int] = []
    high_fatigue = travel_mm = collisions = over_capacity = 0
    distinct_positions: list[int] = []
    rest_destinations = {
        row["destination_id"]: row
        for row in arm["place"]["destinations"]
        if row["enabled"] and "rest" in row["affordances"]
    }
    spot_destinations = {row["spot_id"]: row["destination_ids"] for row in arm["place"]["spots"]}
    rest_occupied = 0
    focus_occupied = 0
    focus_id = (
        definition["intervention"].get("target", {}).get("target_id")
        if definition["intervention"]["profile"] == INTERVENTION_PROFILE
        else None
    )

    prior = checkpoint["state"]
    events_by_tick: dict[int, list[dict[str, Any]]] = {}
    for row in arm["events"]:
        events_by_tick.setdefault(row["tick"], []).append(row)
    inhabitant_ids = {row["id"] for row in checkpoint["state"]["inhabitants"]}
    for index, state in enumerate(states, start=1):
        if (
            state["tick"] != checkpoint["state"]["tick"] + index
            or state["society_id"] != checkpoint["state"]["society_id"]
            or state["seed_sha256"] != checkpoint["seed_sha256"]
            or state["routine"] != definition["routine"]
            or state["input_seq"] != expected_binding["input_seq"]
            or state["input_sha256"] != expected_binding["document_sha256"]
            or state["place"]["place_sha256"] != expected_binding["place_sha256"]
            or len(state["inhabitants"]) != people
            or {row["id"] for row in state["inhabitants"]} != inhabitant_ids
        ):
            raise ExperimentIntegrityError("arm state sequence or lineage mismatch")
        tick_events = sorted(
            events_by_tick.pop(state["tick"], []), key=lambda row: row["document"]["order"]
        )
        if [row["document"]["order"] for row in tick_events] != list(range(len(tick_events))):
            raise ExperimentIntegrityError("event order is not contiguous within its tick")
        for row in tick_events:
            _verify_event(row, prior, state)

        positions = Counter()
        occupancy: Counter[str] = Counter()
        for person in state["inhabitants"]:
            if "fatigue" not in person["needs"]:
                raise ExperimentIntegrityError("an eligible inhabitant lacks canonical fatigue")
            value = person["needs"]["fatigue"]
            fatigue.append(value)
            high_fatigue += value >= definition["primary_metric"]["threshold_milli"]
            path = person["motion_path_mm"]
            travel_mm += sum(ceil_distance(a, b) for a, b in pairwise(path))
            if not person["location"]["indoors"] and person["route"] is None:
                positions[tuple(person["position_mm"])] += 1
            held = person["reservation"]
            if held is not None:
                if held["kind"] == "visitor":
                    occupancy[held["id"]] += 1
                elif held["kind"] == "spot":
                    for destination_id in spot_destinations.get(held["id"], []):
                        occupancy[destination_id] += 1
        collisions += sum(count - 1 for count in positions.values() if count > 1)
        distinct_positions.append(len({tuple(p["position_mm"]) for p in state["inhabitants"]}))
        for destination_id, destination in rest_destinations.items():
            count = occupancy[destination_id]
            rest_occupied += count
            over_capacity += count > destination["visitor_capacity"]
        if focus_id in rest_destinations:
            focus_occupied += occupancy[focus_id]
        prior = state
    if events_by_tick:
        raise ExperimentIntegrityError("arm evidence contains events outside the follow-up")

    completed_rest = sum(
        row["kind"] == "action_completed" and row["document"]["outcome"] == "rest_completed"
        for row in arm["events"]
    )
    person_minutes = people * definition["followup_ticks"]
    rest_capacity_minutes = (
        sum(row["visitor_capacity"] for row in rest_destinations.values())
        * definition["followup_ticks"]
    )
    focus_metric: dict[str, Any]
    if focus_id in rest_destinations:
        focus_capacity_minutes = (
            rest_destinations[focus_id]["visitor_capacity"] * definition["followup_ticks"]
        )
        focus_metric = _ratio(focus_occupied, focus_capacity_minutes, scale=1000)
    else:
        focus_metric = {"availability": "not_present"}
    return {
        "population": people,
        "followup_ticks": definition["followup_ticks"],
        "high_fatigue_person_minutes": _ratio(high_fatigue, person_minutes, scale=1000),
        "completed_rest_activities": _ratio(completed_rest, person_minutes, scale=1000),
        "fatigue_milli": {
            "observations": len(fatigue),
            "median_nearest_rank": _nearest_rank(fatigue, 1, 2),
            "p95_nearest_rank": _nearest_rank(fatigue, 95, 100),
        },
        "focus_rest_occupancy": focus_metric,
        "all_rest_occupancy": _ratio(rest_occupied, rest_capacity_minutes, scale=1000),
        "travel_mm_per_inhabitant": _ratio(travel_mm, people),
        "safety": {
            "stationary_collisions": collisions,
            "over_capacity_destination_ticks": over_capacity,
            "transition_refusals": 0,
            "minimum_distinct_positions": min(distinct_positions),
        },
        "evidence": {
            "state_count": len(states),
            "event_count": len(arm["events"]),
            "final_state_sha256": arm["final_state_sha256"],
            "events_sha256": arm["events_sha256"],
            "arm_evidence_sha256": arm["document_sha256"],
        },
    }


def _signed_ratio(left: dict[str, Any], right: dict[str, Any]) -> dict[str, int]:
    numerator = left["numerator"] * right["denominator"] - right["numerator"] * left["denominator"]
    denominator = left["denominator"] * right["denominator"]
    divisor = math.gcd(abs(numerator), denominator)
    return {"numerator": numerator // divisor, "denominator": denominator // divisor}


def compare_arm_metrics(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Return exact signed ``left - right`` differences; swapping arguments reverses every sign."""
    left_fatigue, right_fatigue = (
        left["high_fatigue_person_minutes"],
        right["high_fatigue_person_minutes"],
    )
    absolute = _signed_ratio(left_fatigue, right_fatigue)
    baseline_numerator = right_fatigue["numerator"]
    relative: dict[str, Any]
    if baseline_numerator == 0:
        relative = {
            "availability": "unavailable",
            "reason": "right arm has zero high-fatigue minutes",
        }
    else:
        numerator = (
            left_fatigue["numerator"] * right_fatigue["denominator"]
            - right_fatigue["numerator"] * left_fatigue["denominator"]
        )
        denominator = left_fatigue["denominator"] * baseline_numerator
        divisor = math.gcd(abs(numerator), denominator)
        relative = {"numerator": numerator // divisor, "denominator": denominator // divisor}
    return {
        "direction": "left_minus_right",
        "high_fatigue_fraction": absolute,
        "high_fatigue_relative_change": relative,
        "completed_rest_rate": _signed_ratio(
            left["completed_rest_activities"], right["completed_rest_activities"]
        ),
        "all_rest_occupancy_fraction": _signed_ratio(
            left["all_rest_occupancy"], right["all_rest_occupancy"]
        ),
        "travel_mm_per_inhabitant": _signed_ratio(
            left["travel_mm_per_inhabitant"], right["travel_mm_per_inhabitant"]
        ),
        "fatigue_median_milli": {
            "numerator": left["fatigue_milli"]["median_nearest_rank"]
            - right["fatigue_milli"]["median_nearest_rank"],
            "denominator": 1,
        },
        "fatigue_p95_milli": {
            "numerator": left["fatigue_milli"]["p95_nearest_rank"]
            - right["fatigue_milli"]["p95_nearest_rank"],
            "denominator": 1,
        },
    }


def recompute_pair_result(
    definition: dict[str, Any], checkpoint: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    """Independent result consumer: validate canonical evidence and recompute every metric."""
    model = routine_for(checkpoint["state"])
    _validate_definition(definition, model)
    _validate_checkpoint(definition, checkpoint, model)
    _verify_seal(evidence, EVIDENCE_PROFILE, "experiment evidence")
    if set(evidence) != {
        "profile",
        "definition_sha256",
        "checkpoint_sha256",
        "seed_sha256",
        "arms",
        "document_sha256",
    }:
        raise ExperimentIntegrityError("invalid experiment evidence fields")
    if (
        evidence["definition_sha256"] != definition["document_sha256"]
        or evidence["checkpoint_sha256"] != checkpoint["document_sha256"]
        or evidence["seed_sha256"] != checkpoint["seed_sha256"]
        or set(evidence["arms"]) != {"baseline", "treatment"}
    ):
        raise ExperimentIntegrityError("experiment evidence binding mismatch")
    applied = definition["intervention"]["profile"] != NOOP_PROFILE
    baseline = _arm_metrics(
        definition,
        checkpoint,
        evidence["arms"]["baseline"],
        expected_binding=definition["baseline_input"],
        expected_intervention=False,
        routine=model,
    )
    treatment = _arm_metrics(
        definition,
        checkpoint,
        evidence["arms"]["treatment"],
        expected_binding=definition["treatment_input"],
        expected_intervention=applied,
        routine=model,
    )
    baseline_place = LivingPlace(evidence["arms"]["baseline"]["place"], model)
    treatment_place = LivingPlace(evidence["arms"]["treatment"]["place"], model)
    _verify_checkpoint_replay(definition, checkpoint, baseline_place, model)
    replayed_baseline = _run_arm(
        definition=definition,
        checkpoint=checkpoint,
        seed_sha256=checkpoint["seed_sha256"],
        baseline_place=baseline_place,
        applied_place=baseline_place,
        routine=model,
        intervention_applied=False,
    )
    replayed_treatment = _run_arm(
        definition=definition,
        checkpoint=checkpoint,
        seed_sha256=checkpoint["seed_sha256"],
        baseline_place=baseline_place,
        applied_place=treatment_place,
        routine=model,
        intervention_applied=applied,
    )
    if (
        replayed_baseline != evidence["arms"]["baseline"]
        or replayed_treatment != evidence["arms"]["treatment"]
    ):
        raise ExperimentIntegrityError(
            "experiment evidence does not match canonical transition replay"
        )
    return _seal(
        {
            "profile": RESULT_PROFILE,
            "status": "valid",
            "definition_sha256": definition["document_sha256"],
            "checkpoint_sha256": checkpoint["document_sha256"],
            "seed_sha256": checkpoint["seed_sha256"],
            "invalid_pairs": [],
            "arms": {"baseline": baseline, "treatment": treatment},
            "comparison": compare_arm_metrics(treatment, baseline),
            "unsupported_metrics": deepcopy(definition["unsupported_metrics"]),
        }
    )


def verify_pair_result(
    result: dict[str, Any],
    definition: dict[str, Any],
    checkpoint: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    """Reject a corrupt or stale result, including a valid digest over altered values."""
    _verify_seal(result, RESULT_PROFILE, "experiment result")
    if result.get("status") != "valid":
        raise ExperimentIntegrityError("only a valid pair has recomputable evidence")
    if result != recompute_pair_result(definition, checkpoint, evidence):
        raise ExperimentIntegrityError("experiment result does not match canonical evidence")
