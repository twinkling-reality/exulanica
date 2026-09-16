"""The nine hard-pass keys of the visual gate, and the only spellings that resolve to them.

Three retained rejection records scored the same questions under three drifted spellings: six
keys in the first Helsinki record, seven in its successor and nine in Melbourne. A corridor scored
against a fourth spelling would be comparable to none of them, so this module is the one place the
spellings are reconciled, and it is a closed vocabulary rather than a convention.

**A spelling nobody listed raises.** :func:`resolve` refuses an unknown spelling instead of passing
it through, because a key that silently passes through is a key that silently drops out of the
block the corridor has to beat.

**Absence is not a value.** A key a retained record did not score is absent from that record's
entry in :data:`RETAINED_RECORDS`. Nothing here infers ``True`` or ``False`` for it, and nothing
here re-scores a retained run: the retained values are quoted under their own spellings by the
reconciliation record and no canonical value is asserted for any predecessor run.

**Every threshold is an integer.** Lengths are millimetres and budgets are bytes or counts, so a
threshold can enter a digest input as it stands. ``exulanica.canonical`` refuses floats there, and
a record that restated a threshold as a float would not be writable at all.

Pure: this module imports nothing from the product, performs no I/O and holds no clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

__all__ = [
    "AUTHENTICATION_CONDITIONS",
    "CANONICAL_KEYS",
    "CANONICAL_SPELLINGS",
    "CAPTURE_LABELS",
    "CLASSIFICATION",
    "EVIDENCE_KINDS",
    "GATE_KEY_SET_VERSION",
    "JUDGED_KEY",
    "MELBOURNE_ENVELOPE",
    "RETAINED_RECORDS",
    "RUBRIC_PATH",
    "RUBRIC_QUESTIONS",
    "THRESHOLDS",
    "GateKey",
    "RetainedRecord",
    "UnknownGateKey",
    "key",
    "resolve",
]

EvidenceKind = Literal["mechanical", "judged"]

#: Bumped only by a new reconciliation record. The corridor is scored against this version.
GATE_KEY_SET_VERSION: Final = "exulanica.visual-gate-keys/v1"

EVIDENCE_KINDS: Final[tuple[EvidenceKind, ...]] = ("mechanical", "judged")

#: The three route captures every key that reads a capture reads, in route order.
CAPTURE_LABELS: Final[tuple[str, ...]] = ("start", "midpoint", "endpoint")

RUBRIC_PATH: Final = "docs/visual-gate-rubric.md"

#: The rubric's three questions, as the operator fixed them. Ids are what a judged record carries.
RUBRIC_QUESTIONS: Final[tuple[tuple[str, str], ...]] = (
    (
        "premises",
        "Can the viewer name a plausible use for at least three ground-floor premises?",
    ),
    (
        "frontage",
        "Is the frontage continuous, with no gap that reads as a cut?",
    ),
    (
        "depth",
        "Is there a legible depth cue at roughly 30 m, 100 m and 300 m?",
    ),
)

#: The two conditions the product-shell key has actually been scored under. Melbourne's record
#: set the key true while its preview API answered three 404s, so the key alone never says which.
AUTHENTICATION_CONDITIONS: Final[tuple[str, ...]] = ("credentialed-api", "vite-preview-api")

#: Every geometric tolerance the gate uses. Millimetres unless the name says otherwise.
THRESHOLDS: Final[Mapping[str, int]] = MappingProxyType(
    {
        # The grounded Atlas contract: eye height, capsule radius and maximum step.
        "eyeHeightMm": 1620,
        "eyeHeightToleranceMm": 50,
        "capsuleRadiusMm": 340,
        "capsuleHeightMm": 1900,
        "stepHeightMm": 180,
        "walkableSlopeDegrees": 12,
        # "Support resampled to within 0.05 m": both the sample spacing and the agreement.
        "supportSampleSpacingMm": 50,
        "supportAgreementMm": 50,
        # The same 0.05 m is the only contact tolerance, so nothing here invents a second one.
        "contactToleranceMm": 50,
        # The deepest reveal the corridor target allows, 120 to 250 mm, bounds what counts as
        # facade: a surface farther than this from the collision ring is not the facade.
        "facadeBandMm": 250,
        # Where a collision edge is probed for a drawn facade: the eye-level band.
        "facadeProbeHeightMm": 1000,
        # The bounded route: roughly 125 m, walked at least 120 m, with no collision slide.
        "routeLengthMm": 125_000,
        "minimumWalkedMm": 120_000,
        "maximumLateralDeviationMm": 340,
        # How far to either side a building counts as frontage when a route is chosen.
        "frontageSearchMm": 40_000,
    }
)

#: Melbourne's measured values, which docs/evaluation names its accepted 125 m envelope. Only the
#: values that do not vary between runs of one build decide ``practicalBrowserBudget``.
MELBOURNE_ENVELOPE: Final[Mapping[str, int]] = MappingProxyType(
    {
        "environmentTransferredBytes": 28_247_006,
        "drawnTriangles": 227_173,
        "environmentDecodedTextureBytes": 167_772_160,
        "maxDrawCalls": 87,
    }
)

#: How the mechanical keys classify a drawn triangle. Stated once so both implementations and
#: the reconciliation record say the same thing.
CLASSIFICATION: Final[Mapping[str, str]] = MappingProxyType(
    {
        "drawnGeometry": (
            "Every triangle of every enabled, visible mesh instance the application renders in "
            "its world layer, in world coordinates, read from the live renderer."
        ),
        "walkingSurfaceTriangle": (
            "A drawn triangle whose unit normal has an upward component of at least cos(12 "
            "degrees) and whose centroid lies no more than 0.18 m above the navigation support."
        ),
        "facadeTriangle": (
            "A drawn triangle whose unit normal has a vertical component of at most sin(12 "
            "degrees), whose centroid lies within 0.25 m horizontally of a building exterior ring "
            "edge and between the support and that building's top."
        ),
        "texturedTriangle": (
            "A drawn triangle whose mesh carries a texture coordinate channel and whose material "
            "binds at least one texture with nonzero decoded bytes."
        ),
        "component": (
            "A connected set of drawn triangles, joined where vertices coincide to the millimetre."
        ),
        "contact": (
            "Two components are in contact when a vertex of one lies within 0.05 m of a triangle "
            "of the other, or inside the other's closed volume, or an edge of one crosses a "
            "triangle of the other."
        ),
        "buildingVolume": (
            "The prism of a building exterior ring from its support to its top, shrunk by 0.05 m "
            "on every side."
        ),
        "routeSample": (
            "A point of the walked trace resampled along its length at 0.05 m spacing."
        ),
    }
)


@dataclass(frozen=True, slots=True)
class GateKey:
    """One canonical key: what makes it true, and what decides it."""

    spelling: str
    definition: str
    evidence_kind: EvidenceKind
    #: The named measurement that decides a mechanical key. None for the judged key.
    measurement: str | None
    #: The measured fields the decision reads. Empty for the judged key.
    decided_by: tuple[str, ...]
    #: Retained spellings, other than the canonical spelling itself, that resolve to this key.
    predecessor_spellings: tuple[str, ...]


JUDGED_KEY: Final = "readsAsInhabitedStreet"

CANONICAL_KEYS: Final[tuple[GateKey, ...]] = (
    GateKey(
        spelling="continuousTexturedStreetAndFacades",
        definition=(
            "True only when at least one walking-surface or facade triangle is drawn, every drawn "
            "walking-surface and facade triangle is textured, and the drawn walking surface has "
            "no gap at any route sample."
        ),
        evidence_kind="mechanical",
        measurement="textured-surface-coverage/v1",
        decided_by=(
            "streetAndFacadeTriangles",
            "untexturedStreetAndFacadeTriangles",
            "routeSupportGapSamples",
        ),
        predecessor_spellings=(
            "continuousTexturedGround",
            "continuousTexturedStreet",
            "continuousSourceTexturedStreetAndFacades",
        ),
    ),
    GateKey(
        spelling=JUDGED_KEY,
        definition=(
            "True only when the human judge named in docs/visual-gate-rubric.md answers yes to all "
            "three rubric questions for each of the start, midpoint and endpoint captures, nine "
            "yes answers of nine, and never when an answer is missing or was given by a model."
        ),
        evidence_kind="judged",
        measurement=None,
        decided_by=(),
        predecessor_spellings=(
            "recognizableUrbanStreet",
            "recognizableUrbanScene",
            "recognizableMelbourneUrbanScene",
        ),
    ),
    GateKey(
        spelling="noCutsOrFloatingGeometry",
        definition=(
            "True only when the drawn walking surface has no gap at any route sample, every "
            "building exterior ring edge has drawn geometry within 0.05 m of its midpoint at 1 m "
            "above the support, every drawn component reaches the walking surface through a chain "
            "of contacts, and no drawn triangle lies inside a building volume."
        ),
        evidence_kind="mechanical",
        measurement="drawn-geometry-integrity/v1",
        decided_by=(
            "routeSupportGapSamples",
            "ringEdgesWithoutDrawnFacade",
            "componentsDetachedFromSupport",
            "trianglesInsideBuildings",
        ),
        predecessor_spellings=(
            "noFloatingOrCutGeometry",
            "noCutOrFloatingGeometry",
            "noLargeCutsOrFloatingGeometry",
        ),
    ),
    GateKey(
        spelling="usefulEyeLevelMovement",
        definition=(
            "True only when key events delivered to the product's own handlers, with no position "
            "written by the harness, carried the player at least 120 m along the route heading "
            "with at most 0.34 m of lateral deviation and no recovery event, and every route "
            "sample of the live per-frame trace had drawn walking surface beneath it and stood "
            "1.62 m, within 0.05 m, above it, where the product's navigation support and the drawn "
            "support agree within 0.05 m."
        ),
        evidence_kind="mechanical",
        measurement="product-driven-route-trace/v1",
        decided_by=(
            "walkedDisplacementMm",
            "maxLateralDeviationMm",
            "recoveryEvents",
            "harnessPositionWrites",
            "traceSamples",
            "routeSupportGapSamples",
            "maxEyeHeightErrorMm",
            "maxSupportResampleDeltaMm",
        ),
        predecessor_spellings=("eyeLevelMovement", "verifiedEyeLevelMovement"),
    ),
    GateKey(
        spelling="completeCapsuleClearanceVerification",
        definition=(
            "True only when, at every route sample, a vertical capsule of radius 0.34 m and total "
            "height 1.9 m standing on the drawn walking surface keeps at least 0.34 m from every "
            "drawn triangle that rises more than 0.18 m above that surface and lies outside every "
            "building exterior ring with at least 0.34 m to its nearest edge, with no sample "
            "skipped."
        ),
        evidence_kind="mechanical",
        measurement="capsule-clearance/v1",
        decided_by=(
            "capsuleSamples",
            "capsuleSamplesChecked",
            "capsuleTriangleContactSamples",
            "capsuleRingContactSamples",
        ),
        predecessor_spellings=(),
    ),
    GateKey(
        spelling="practicalBrowserBudget",
        definition=(
            "True only when the environment's transferred bytes, the drawn triangles, the "
            "environment's decoded texture bytes and the run's maximum per-frame draw calls are "
            "each no greater than Melbourne's envelope of 28,247,006 bytes, 227,173 triangles, "
            "167,772,160 bytes and 87 draw calls, and the run recorded no GPU error and no "
            "uncaught page exception or unhandled rejection; frame time, low-percentile frame "
            "rate and heap are reported beside Melbourne's and do not decide the key, because "
            "they vary between runs of one build."
        ),
        evidence_kind="mechanical",
        measurement="browser-envelope/v1",
        decided_by=(
            "environmentTransferredBytes",
            "drawnTriangles",
            "environmentDecodedTextureBytes",
            "maxDrawCalls",
            "gpuErrors",
            "pageErrors",
        ),
        predecessor_spellings=(),
    ),
    GateKey(
        spelling="companionPresent",
        definition=(
            "True only when, at each of the three captures, the product's Companion presence "
            "element is connected, ready, marked shown and laid out with a nonzero box inside the "
            "viewport, and its encounter surface is connected and open."
        ),
        evidence_kind="mechanical",
        measurement="live-dom-companion/v1",
        decided_by=("captures", "capturesWithCompanionShown"),
        predecessor_spellings=(),
    ),
    GateKey(
        spelling="reticlePresent",
        definition=(
            "True only when, at each of the three captures, the product's reticle element is "
            "connected, displayed with nonzero opacity and a nonzero box, and centred on the "
            "viewport within 1 px."
        ),
        evidence_kind="mechanical",
        measurement="live-dom-reticle/v1",
        decided_by=("captures", "capturesWithReticleCentred"),
        predecessor_spellings=(),
    ),
    GateKey(
        spelling="authenticatedShellAndAuthoredHandlersPreserved",
        definition=(
            "True only when every capture was taken in the product's own shell document with a "
            "mounted world and no credential gate, empty-world or error surface, every listener on "
            "the window, the document and the world canvas comes from the product's own modules, "
            "the product's keyboard listeners carried every interaction the harness made, and no "
            "page or handler was substituted; as the retained Melbourne record used it, the key "
            "does not by itself assert a bearer credential, so every record states its "
            "authentication condition in a separate field."
        ),
        evidence_kind="mechanical",
        measurement="product-shell-and-listeners/v1",
        decided_by=(
            "captures",
            "capturesInProductShell",
            "foreignListeners",
            "productWindowKeydownListeners",
            "interactionsNotCarriedByProduct",
            "substitutedPages",
        ),
        predecessor_spellings=(),
    ),
)

CANONICAL_SPELLINGS: Final[tuple[str, ...]] = tuple(item.spelling for item in CANONICAL_KEYS)


class UnknownGateKey(KeyError):
    """A spelling this module does not list. Never passed through, never guessed."""


def _resolution_table() -> Mapping[str, str]:
    """Every spelling that resolves, built once, refusing any spelling claimed twice.

    Raising at import is deliberate: an ambiguous table is a vocabulary that means two things,
    and a module that cannot be imported is louder than a test that nobody runs.
    """
    table: dict[str, str] = {}
    for item in CANONICAL_KEYS:
        for spelling in (item.spelling, *item.predecessor_spellings):
            claimed = table.get(spelling)
            if claimed is not None and claimed != item.spelling:
                raise RuntimeError(
                    f"gate key spelling {spelling!r} resolves to both {claimed!r} and "
                    f"{item.spelling!r}"
                )
            table[spelling] = item.spelling
    return MappingProxyType(table)


_RESOLVE: Final = _resolution_table()
_BY_SPELLING: Final = MappingProxyType({item.spelling: item for item in CANONICAL_KEYS})


def resolve(spelling: str) -> str:
    """The canonical spelling ``spelling`` resolves to, or :class:`UnknownGateKey`."""
    canonical = _RESOLVE.get(spelling)
    if canonical is None:
        raise UnknownGateKey(
            f"{spelling!r} is not a hard-pass key spelling this gate reconciles. Add it to "
            "exulanica/evaluation/gate_keys.py through a new reconciliation record, or use one of "
            f"{', '.join(CANONICAL_SPELLINGS)}."
        )
    return canonical


def key(spelling: str) -> GateKey:
    """The canonical key a spelling resolves to."""
    return _BY_SPELLING[resolve(spelling)]


@dataclass(frozen=True, slots=True)
class RetainedRecord:
    """A retained rejection record, and the spelling it used for each key it scored."""

    label: str
    path: str
    record_sha256: str
    brief_path: str
    #: Canonical spelling to the spelling this record used. A key it did not score is absent.
    spellings: Mapping[str, str]


RETAINED_RECORDS: Final[tuple[RetainedRecord, ...]] = (
    RetainedRecord(
        label="helsinki-visual-feasibility",
        path="docs/evaluation/2026-09-12-helsinki-visual-feasibility.json",
        record_sha256="caf3c54cbd14cc7be35702b4b0abb583d3db8f821628a6e6312d02b84758087a",
        brief_path="docs/briefs/2026-09-12-helsinki-visual-feasibility.md",
        spellings=MappingProxyType(
            {
                "continuousTexturedStreetAndFacades": "continuousTexturedGround",
                "readsAsInhabitedStreet": "recognizableUrbanStreet",
                "noCutsOrFloatingGeometry": "noFloatingOrCutGeometry",
                "usefulEyeLevelMovement": "eyeLevelMovement",
                "companionPresent": "companionPresent",
                "reticlePresent": "reticlePresent",
            }
        ),
    ),
    RetainedRecord(
        label="helsinki-terminal-lod-successor",
        path="docs/evaluation/2026-09-12-helsinki-terminal-lod-successor.json",
        record_sha256="6cc00994c74ddf976c1bd3899dd637fdea4f4acf9e1b4e7605ea63426dd26c85",
        brief_path="docs/briefs/2026-09-12-helsinki-terminal-lod-successor.md",
        spellings=MappingProxyType(
            {
                "continuousTexturedStreetAndFacades": "continuousTexturedStreet",
                "readsAsInhabitedStreet": "recognizableUrbanScene",
                "noCutsOrFloatingGeometry": "noCutOrFloatingGeometry",
                "usefulEyeLevelMovement": "verifiedEyeLevelMovement",
                "companionPresent": "companionPresent",
                "reticlePresent": "reticlePresent",
                "authenticatedShellAndAuthoredHandlersPreserved": (
                    "authenticatedShellAndAuthoredHandlersPreserved"
                ),
            }
        ),
    ),
    RetainedRecord(
        label="melbourne-c4-29-visual-feasibility",
        path="docs/evaluation/2026-09-12-melbourne-c4-29-visual-feasibility.json",
        record_sha256="97b66da014db8457b6ef60e31ffea84eb3e3c37c821b019862bf2838f7bc8206",
        brief_path="docs/briefs/2026-09-12-melbourne-c4-29-visual-feasibility.md",
        spellings=MappingProxyType(
            {
                "continuousTexturedStreetAndFacades": "continuousSourceTexturedStreetAndFacades",
                "readsAsInhabitedStreet": "recognizableMelbourneUrbanScene",
                "noCutsOrFloatingGeometry": "noLargeCutsOrFloatingGeometry",
                "usefulEyeLevelMovement": "usefulEyeLevelMovement",
                "completeCapsuleClearanceVerification": "completeCapsuleClearanceVerification",
                "practicalBrowserBudget": "practicalBrowserBudget",
                "companionPresent": "companionPresent",
                "reticlePresent": "reticlePresent",
                "authenticatedShellAndAuthoredHandlersPreserved": (
                    "authenticatedShellAndAuthoredHandlersPreserved"
                ),
            }
        ),
    ),
)
