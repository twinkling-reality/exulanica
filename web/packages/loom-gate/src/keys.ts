/**
 * The nine hard-pass keys, their thresholds and the mechanical decisions, as the harness runs them.
 *
 * `exulanica/evaluation/gate_keys.py` is the reconciled vocabulary and
 * `docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v3.json` is the retained statement of it,
 * superseding earlier versions only in how the judged key is asked and in the wording of one
 * definition; no number this module holds has changed.
 * This module restates the same numbers so a browser run can decide without a Python process, and
 * the package test pins every one of them to the retained record, so the two cannot drift apart
 * without a test saying so. The record writer then re-decides every key in Python and refuses to
 * write when the two decisions disagree.
 *
 * No vocabulary about any world lives here: nothing names a building, a material, a street or a
 * renderer entity. A key is decided from counts and lengths alone.
 */

export const GATE_KEY_SET_VERSION = 'exulanica.visual-gate-keys/v3';

export const CANONICAL_KEYS = [
  'continuousTexturedStreetAndFacades',
  'readsAsInhabitedStreet',
  'noCutsOrFloatingGeometry',
  'usefulEyeLevelMovement',
  'completeCapsuleClearanceVerification',
  'practicalBrowserBudget',
  'companionPresent',
  'reticlePresent',
  'authenticatedShellAndAuthoredHandlersPreserved',
] as const;

export type CanonicalKey = (typeof CANONICAL_KEYS)[number];

export const JUDGED_KEY = 'readsAsInhabitedStreet' as const;

export type MechanicalKey = Exclude<CanonicalKey, typeof JUDGED_KEY>;

export const CAPTURE_LABELS = ['start', 'midpoint', 'endpoint'] as const;

export type CaptureLabel = (typeof CAPTURE_LABELS)[number];

/** Millimetres unless the name says otherwise. Integers, as in the retained record. */
export const THRESHOLDS = Object.freeze({
  eyeHeightMm: 1620,
  eyeHeightToleranceMm: 50,
  capsuleRadiusMm: 340,
  capsuleHeightMm: 1900,
  stepHeightMm: 180,
  walkableSlopeDegrees: 12,
  supportSampleSpacingMm: 50,
  supportAgreementMm: 50,
  contactToleranceMm: 50,
  facadeBandMm: 250,
  facadeProbeHeightMm: 1000,
  routeLengthMm: 125_000,
  minimumWalkedMm: 120_000,
  maximumLateralDeviationMm: 340,
  frontageSearchMm: 40_000,
});

/** Melbourne's measured values that do not vary between runs of one build. */
export const MELBOURNE_ENVELOPE = Object.freeze({
  environmentTransferredBytes: 28_247_006,
  drawnTriangles: 227_173,
  environmentDecodedTextureBytes: 167_772_160,
  maxDrawCalls: 87,
});

/** The fields each mechanical key is decided from, in the reconciled order. */
export const DECIDED_BY: Readonly<Record<MechanicalKey, readonly string[]>> = Object.freeze({
  continuousTexturedStreetAndFacades: [
    'streetAndFacadeTriangles',
    'untexturedStreetAndFacadeTriangles',
    'routeSupportGapSamples',
  ],
  noCutsOrFloatingGeometry: [
    'routeSupportGapSamples',
    'ringEdgesWithoutDrawnFacade',
    'componentsDetachedFromSupport',
    'trianglesInsideBuildings',
  ],
  usefulEyeLevelMovement: [
    'walkedDisplacementMm',
    'maxLateralDeviationMm',
    'recoveryEvents',
    'harnessPositionWrites',
    'traceSamples',
    'routeSupportGapSamples',
    'maxEyeHeightErrorMm',
    'maxSupportResampleDeltaMm',
  ],
  completeCapsuleClearanceVerification: [
    'capsuleSamples',
    'capsuleSamplesChecked',
    'capsuleTriangleContactSamples',
    'capsuleRingContactSamples',
  ],
  practicalBrowserBudget: [
    'environmentTransferredBytes',
    'drawnTriangles',
    'environmentDecodedTextureBytes',
    'maxDrawCalls',
    'gpuErrors',
    'pageErrors',
  ],
  companionPresent: ['captures', 'capturesWithCompanionShown'],
  reticlePresent: ['captures', 'capturesWithReticleCentred'],
  authenticatedShellAndAuthoredHandlersPreserved: [
    'captures',
    'capturesInProductShell',
    'foreignListeners',
    'productWindowKeydownListeners',
    'interactionsNotCarriedByProduct',
    'substitutedPages',
  ],
});

export type Measured = Readonly<Record<string, number>>;

export class GateEvidenceError extends Error {
  override readonly name = 'GateEvidenceError';
}

function integers(key: MechanicalKey, measured: Measured): Record<string, number> {
  const values: Record<string, number> = {};
  for (const field of DECIDED_BY[key]) {
    const value = measured[field];
    if (value === undefined) {
      throw new GateEvidenceError(`${key}: no evidence for ${field}; the key is not emitted`);
    }
    if (!Number.isSafeInteger(value) || value < 0) {
      throw new GateEvidenceError(`${key}: ${field} must be a non-negative integer, got ${value}`);
    }
    values[field] = value;
  }
  return values;
}

/** Decide one mechanical key. Mirrors `decide_mechanical` in the Python record builder. */
export function decideMechanical(key: MechanicalKey, measured: Measured): boolean {
  const v = integers(key, measured);
  const t = THRESHOLDS;
  const at = (field: string): number => v[field]!;
  switch (key) {
    case 'continuousTexturedStreetAndFacades':
      return at('streetAndFacadeTriangles') > 0 &&
        at('untexturedStreetAndFacadeTriangles') === 0 &&
        at('routeSupportGapSamples') === 0;
    case 'noCutsOrFloatingGeometry':
      return DECIDED_BY[key].every((field) => at(field) === 0);
    case 'usefulEyeLevelMovement':
      return at('walkedDisplacementMm') >= t.minimumWalkedMm &&
        at('maxLateralDeviationMm') <= t.maximumLateralDeviationMm &&
        at('recoveryEvents') === 0 &&
        at('harnessPositionWrites') === 0 &&
        at('traceSamples') > 0 &&
        at('routeSupportGapSamples') === 0 &&
        at('maxEyeHeightErrorMm') <= t.eyeHeightToleranceMm &&
        at('maxSupportResampleDeltaMm') <= t.supportAgreementMm;
    case 'completeCapsuleClearanceVerification':
      return at('capsuleSamples') > 0 &&
        at('capsuleSamplesChecked') === at('capsuleSamples') &&
        at('capsuleTriangleContactSamples') === 0 &&
        at('capsuleRingContactSamples') === 0;
    case 'practicalBrowserBudget':
      return at('environmentTransferredBytes') <= MELBOURNE_ENVELOPE.environmentTransferredBytes &&
        at('drawnTriangles') <= MELBOURNE_ENVELOPE.drawnTriangles &&
        at('environmentDecodedTextureBytes') <=
          MELBOURNE_ENVELOPE.environmentDecodedTextureBytes &&
        at('maxDrawCalls') <= MELBOURNE_ENVELOPE.maxDrawCalls &&
        at('gpuErrors') === 0 &&
        at('pageErrors') === 0;
    case 'companionPresent':
      return at('captures') === CAPTURE_LABELS.length &&
        at('capturesWithCompanionShown') === at('captures');
    case 'reticlePresent':
      return at('captures') === CAPTURE_LABELS.length &&
        at('capturesWithReticleCentred') === at('captures');
    case 'authenticatedShellAndAuthoredHandlersPreserved':
      return at('captures') === CAPTURE_LABELS.length &&
        at('capturesInProductShell') === at('captures') &&
        at('foreignListeners') === 0 &&
        at('productWindowKeydownListeners') > 0 &&
        at('interactionsNotCarriedByProduct') === 0 &&
        at('substitutedPages') === 0;
  }
}

/** The judged key is never decided by the harness. It is carried as awaiting the named judge. */
export const AWAITING_JUDGE = 'awaiting-named-judge' as const;

export type KeySetValue = boolean | typeof AWAITING_JUDGE;

/** All nine keys for one run: eight decided here, the judged one explicitly left to the human. */
export function decideKeySet(
  measured: Readonly<Record<MechanicalKey, Measured>>,
): Readonly<Record<CanonicalKey, KeySetValue>> {
  const result = {} as Record<CanonicalKey, KeySetValue>;
  for (const key of CANONICAL_KEYS) {
    result[key] = key === JUDGED_KEY ? AWAITING_JUDGE : decideMechanical(key, measured[key]);
  }
  return Object.freeze(result);
}

/** Metres to integer millimetres, rounding half toward zero like the canonical rule. */
export function millimetres(metres: number): number {
  if (!Number.isFinite(metres)) throw new GateEvidenceError(`not a finite length: ${metres}`);
  const scaled = metres * 1000;
  const floor = Math.floor(scaled);
  const remainder = scaled - floor;
  if (remainder > 0.5) return floor + 1;
  if (remainder < 0.5) return floor;
  // Exactly half: toward zero.
  return scaled < 0 ? floor + 1 : floor;
}
