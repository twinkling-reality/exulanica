"""Capture: whether a set of photographs can rebuild, decided before any GPU spend.

Pure: the standard library and Pillow, and from this package only :mod:`exulanica.canonical`,
:mod:`exulanica.errors` and the one decoder, :mod:`exulanica.corpus.decode`, all below it. No
database, no object store, no evidence address, no numeric stack. ``pyproject.toml`` places it
beside ``exulanica.reconstruction`` in the layer list, so neither may import the other, and a
forbidden contract keeps the rest out.

*   :mod:`exulanica.capture.overlap` measures the photographs and builds the pairwise graph.
*   :mod:`exulanica.capture.verdict` reads a predicted ceiling off that graph under a declared
    policy.
*   :mod:`exulanica.capture.instructions` says what to do about it in plain language.
*   :mod:`exulanica.capture.recovery` is the closed outcome vocabulary a record carries, and the
    only way to read an outcome from a run's receipt.
"""

from exulanica.capture.instructions import INSTRUCTION_VOCABULARY, Instruction, instruction
from exulanica.capture.overlap import (
    DescriptorParameters,
    OverlapGraph,
    OverlapMeasurement,
    Photograph,
    measure_overlap,
    overlap_graph,
)
from exulanica.capture.recovery import (
    RECOVERY_STATES,
    WRITABLE_WITHOUT_RUN,
    RecoveryOutcome,
    RecoveryState,
    outcome_from_pose_receipt,
)
from exulanica.capture.verdict import (
    POLICY_V1,
    CaptureVerdict,
    OverlapPolicy,
    PredictedCeiling,
    assess_capture_set,
    verdict_for_measurement,
)

__all__ = [
    "INSTRUCTION_VOCABULARY",
    "POLICY_V1",
    "RECOVERY_STATES",
    "WRITABLE_WITHOUT_RUN",
    "CaptureVerdict",
    "DescriptorParameters",
    "Instruction",
    "OverlapGraph",
    "OverlapMeasurement",
    "OverlapPolicy",
    "Photograph",
    "PredictedCeiling",
    "RecoveryOutcome",
    "RecoveryState",
    "assess_capture_set",
    "instruction",
    "measure_overlap",
    "outcome_from_pose_receipt",
    "overlap_graph",
    "verdict_for_measurement",
]
