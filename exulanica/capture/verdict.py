"""A prediction about a set of photographs, made before any run, under a declared policy.

A verdict is a PREDICTED CEILING: the best state the measured overlap leaves open if the set
were run. It is not an outcome, it is not a recovery state, and nothing here can make it one.
:class:`CaptureVerdict` carries the graph it read and the policy that read it; the only state it
can hand a writer is the refusal, ``insufficient_overlap``, through :meth:`CaptureVerdict.refusal`,
and only when it recommends against running. A refusal is a fact about the photographs as this
policy measured them, which is why it may be recorded without a run.
:class:`exulanica.capture.recovery.RecoveryOutcome` is the other type, and only a receipt builds
one.

The ceiling never goes above ``registered_scene``. A pairwise match graph measures whether
photographs can be placed together; it does not measure whether a trained scene will cover held
out views, and the 210-photograph volcanic set is the measured reason: it registered every
photograph and its training was refused on coverage twice.

**The thresholds are data.** Every number that turns graph statistics into a verdict is in
:class:`OverlapPolicy`, is written into the verdict record, and is bound by the verdict digest,
so a verdict names the rule that produced it and a later policy cannot be mistaken for it.

**A policy that failed its held-out check may predict and may not refuse.**
``OverlapPolicy.refusal_authorised`` is recorded in the verdict and migration 0063 reads it
before a verdict may move a record, so the rule holds in the schema and not only here. Policy v1
is not authorised: measured once, after it was fixed, on the 51-photograph bowl that registered
51 of 51 and trained, it predicted ``registered_partial`` and would have refused the one real set
that trained. Until a policy passes a held-out set, ``insufficient_overlap`` is written from a
pose receipt that placed nothing, and a verdict is advice.

**A photograph that could not be measured never causes a refusal on its own.** It is counted in
the set, as the pose gate counts every member, and it is assumed to join the largest group,
which is the most it could do. So an unmeasured photograph can only raise the ceiling, and a
refusal always rests on photographs that were actually measured.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from exulanica.canonical import canonical_json, sha256_digest
from exulanica.capture.instructions import (
    INSTRUCTION_VOCABULARY,
    Instruction,
    InstructionKey,
    instruction,
)
from exulanica.capture.overlap import (
    DescriptorParameters,
    OverlapGraph,
    OverlapMeasurement,
    Photograph,
    measure_overlap,
    overlap_graph,
)

__all__ = [
    "POLICY_V1",
    "VERDICT_PROFILE",
    "Advisory",
    "CaptureVerdict",
    "Fault",
    "OverlapPolicy",
    "PredictedCeiling",
    "assess_capture_set",
    "decide",
    "verdict_for_measurement",
]

VERDICT_PROFILE: Final = "exulanica.capture-overlap-verdict/v1"

PredictedCeiling = Literal["insufficient_overlap", "registered_partial", "registered_scene"]

Fault = Literal[
    "too_few_photographs",
    "no_overlapping_neighbours",
    "separate_groups",
    "mostly_unconnected",
]

Advisory = Literal["some_unconnected", "unreadable_photographs"]


@dataclass(frozen=True, slots=True)
class OverlapPolicy:
    """The declared, versioned rule that turns a measurement into a verdict.

    ``edge_min_score`` is the pair score at which two photographs count as overlapping.
    ``registration_floor`` is the pose gate's own acceptance floor on the fraction of a set that
    registered, 0.8, carried as an exact ratio. ``calibration`` says which measurement set each
    one. ``refusal_authorised`` says whether a verdict under this policy may be recorded as a
    refusal, and it is False for any policy that has not passed a held-out set.
    """

    version: str
    descriptor: DescriptorParameters
    edge_min_score: int
    registration_floor_numerator: int
    registration_floor_denominator: int
    refusal_authorised: bool
    calibration: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        for name in (
            "edge_min_score",
            "registration_floor_numerator",
            "registration_floor_denominator",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive int")
        if self.registration_floor_numerator > self.registration_floor_denominator:
            raise ValueError("the registration floor is a fraction no greater than one")
        if type(self.refusal_authorised) is not bool:
            raise ValueError("refusal_authorised is a bool")

    def record(self) -> dict[str, object]:
        return {
            "version": self.version,
            "descriptor": self.descriptor.record(),
            "edge_min_score": self.edge_min_score,
            "registration_floor": {
                "numerator": self.registration_floor_numerator,
                "denominator": self.registration_floor_denominator,
            },
            "refusal_authorised": self.refusal_authorised,
            "unmeasured_photographs": "counted in the set and assumed to join the largest group",
            "ceiling_never_exceeds": "registered_scene",
            "calibration": dict(self.calibration),
        }


POLICY_V1: Final = OverlapPolicy(
    version="exulanica.capture-overlap-policy/v1",
    descriptor=DescriptorParameters(),
    edge_min_score=8,
    registration_floor_numerator=4,
    registration_floor_denominator=5,
    refusal_authorised=False,
    calibration=(
        (
            "series",
            "Montserrat volcanic sample (Mike R. James and Stuart Robson, CC0), sorted file "
            "names 0 to 112, the dark-backdrop turntable series; every pair",
        ),
        (
            "truth",
            "angle between optical axes of each pair, from the accepted 210-camera pose receipt "
            "of scene 45ad50b7",
        ),
        (
            "edge_min_score",
            "the score maximising true-edge rate on pairs at most 21 degrees apart minus "
            "false-edge rate on pairs at least 90 degrees apart; 21 degrees is the neighbour "
            "spacing of the twelve-photograph set that registered twelve of twelve; measured "
            "9492 per ten thousand at 8 over 6328 pairs (446 near, 2894 far), 9392 at 7, 9427 at 9",
        ),
        (
            "validation",
            "sorted file names 113 to 209, 4656 pairs, not used to choose anything: 8887 at 8, "
            "maximum 8945 at 7",
        ),
        (
            "known_weakness",
            "at this threshold the set that registered twelve of twelve is predicted "
            "registered_partial, and all four measured sets are predicted correctly only at 6 "
            "and 7; widening the step of a fixed start and count turns a refusal back into a run "
            "in 81 of 452 calibration sequences and 17 of 388 validation sequences",
        ),
        (
            "registration_floor",
            "min_registered_fraction of the colmap pose quality gate, which refused 7 of 12",
        ),
        (
            "held_out",
            "chili salmon bowl (Charin Rungchaowarat, CC0), all 51, first measured after this "
            "policy was fixed: pose receipts 292d697b and d3563ac2 registered 51 of 51 and the "
            "set trained, and this policy predicted registered_partial (6 groups, largest 20), "
            "so it fails its held-out check and is not authorised to refuse; the bowl is spent "
            "as a held-out set for any policy chosen after this result",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class CaptureVerdict:
    """A predicted ceiling, the graph it was read from, and what to tell the person.

    Deliberately has no ``recovery_state``. ``predicted_ceiling`` is a prediction and its type
    says so; :meth:`refusal` is the only path from here to a state.
    """

    policy: OverlapPolicy
    graph: OverlapGraph
    predicted_ceiling: PredictedCeiling
    worth_attempting: bool
    fault: Fault | None
    advisories: tuple[Advisory, ...]
    instruction_counts: tuple[tuple[InstructionKey, tuple[tuple[str, int], ...]], ...]

    @property
    def unmeasured(self) -> int:
        return self.graph.photograph_count - self.graph.measured_count

    def refusal(self) -> Literal["insufficient_overlap"] | None:
        """The one state this verdict may write, or None when it may not refuse the set.

        A set whose ceiling is ``registered_partial`` is refused too: the pose gate turns a
        partial registration into no cameras at all, so running it spends everything and
        produces a correct but empty result that looks exactly like a downstream bug. And no
        verdict refuses anything under a policy that is not authorised to, whatever it predicts.
        """
        if self.worth_attempting or not self.policy.refusal_authorised:
            return None
        return "insufficient_overlap"

    def instructions(self) -> tuple[Instruction, ...]:
        return tuple(instruction(key, dict(counts)) for key, counts in self.instruction_counts)

    def record(self) -> dict[str, object]:
        """The canonical record. Integers, strings, booleans and nulls, and no clock."""
        return {
            "profile": VERDICT_PROFILE,
            "policy": self.policy.record(),
            "graph": self.graph.record(),
            "prediction": {
                "ceiling": self.predicted_ceiling,
                "worth_attempting": self.worth_attempting,
                "fault": self.fault,
                "advisories": list(self.advisories),
                "unmeasured": self.unmeasured,
            },
            "instructions": {
                "vocabulary": INSTRUCTION_VOCABULARY,
                "items": [
                    {"key": key, "counts": dict(counts)} for key, counts in self.instruction_counts
                ],
            },
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.record())

    def sha256(self) -> bytes:
        return sha256_digest(self.canonical_bytes())


def decide(graph: OverlapGraph, policy: OverlapPolicy) -> CaptureVerdict:
    """Read a verdict off the graph under ``policy``. No pixel is looked at again here."""
    if graph.edge_min_score != policy.edge_min_score:
        raise ValueError("the graph was thresholded under a different policy")
    total = graph.photograph_count
    measured = graph.measured_count
    largest = graph.largest_component
    best = largest + (total - measured)
    reaches_floor = (
        best * policy.registration_floor_denominator >= policy.registration_floor_numerator * total
    )
    ceiling: PredictedCeiling
    fault: Fault | None = None
    counts: list[tuple[InstructionKey, dict[str, int]]] = []
    if total < 2:
        ceiling, fault = "insufficient_overlap", "too_few_photographs"
        counts.append((fault, {"photographs": total}))
    elif reaches_floor:
        ceiling = "registered_scene"
    elif best < 2:
        ceiling, fault = "insufficient_overlap", "no_overlapping_neighbours"
        counts.append((fault, {"photographs": measured}))
    else:
        ceiling = "registered_partial"
        if graph.structure == "scatter":
            fault = "no_overlapping_neighbours"
            counts.append((fault, {"photographs": measured}))
        elif graph.groups > 1:
            fault = "separate_groups"
            counts.append((fault, {"groups": graph.groups}))
        else:
            # One group that does not reach the floor, and every unmeasured photograph was
            # already credited to it, so the shortfall is measured photographs outside it.
            fault = "mostly_unconnected"
            counts.append(
                (fault, {"largest": largest, "photographs": measured, "others": measured - largest})
            )
    advisories: list[Advisory] = []
    if ceiling == "registered_scene" and measured - largest > 0 and largest > 1:
        advisories.append("some_unconnected")
        counts.append(("some_unconnected", {"others": measured - largest}))
    if total - measured > 0:
        advisories.append("unreadable_photographs")
        counts.append(("unreadable_photographs", {"unreadable": total - measured}))
    return CaptureVerdict(
        policy=policy,
        graph=graph,
        predicted_ceiling=ceiling,
        worth_attempting=ceiling == "registered_scene",
        fault=fault,
        advisories=tuple(advisories),
        instruction_counts=tuple((key, tuple(sorted(values.items()))) for key, values in counts),
    )


def verdict_for_measurement(
    measurement: OverlapMeasurement, policy: OverlapPolicy = POLICY_V1
) -> CaptureVerdict:
    """The verdict for photographs already measured under this policy's descriptor."""
    if measurement.parameters != policy.descriptor:
        raise ValueError("the measurement used a different descriptor than the policy declares")
    graph = overlap_graph(measurement, policy.edge_min_score)
    return decide(graph, policy)


def assess_capture_set(
    photographs: Sequence[Photograph], policy: OverlapPolicy = POLICY_V1
) -> CaptureVerdict:
    """Measure a set of photographs and predict what a run could make of it.

    Costs a decode and a descriptor per photograph and one score per pair. Runs no
    reconstruction, starts no process and touches no device.
    """
    return verdict_for_measurement(measure_overlap(photographs, policy.descriptor), policy)
