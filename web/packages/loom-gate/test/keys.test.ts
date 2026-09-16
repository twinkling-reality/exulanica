import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  AWAITING_JUDGE,
  CANONICAL_KEYS,
  CAPTURE_LABELS,
  DECIDED_BY,
  GATE_KEY_SET_VERSION,
  GateEvidenceError,
  JUDGED_KEY,
  MELBOURNE_ENVELOPE,
  THRESHOLDS,
  decideKeySet,
  decideMechanical,
  millimetres,
  type MechanicalKey,
} from '../src/index.js';

const here = dirname(fileURLToPath(import.meta.url));
const repository = join(here, '..', '..', '..', '..');
const reconciliation = JSON.parse(
  readFileSync(join(repository, 'docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v3.json'), 'utf8'),
) as {
  record: {
    keySet: string;
    thresholds: Record<string, number>;
    melbourneEnvelope: Record<string, number>;
    canonicalKeys: { key: string; evidenceKind: string; decidedBy?: string[] }[];
    judgedKey: { captures: string[] };
  };
};

function passing(): Record<MechanicalKey, Record<string, number>> {
  return {
    continuousTexturedStreetAndFacades: {
      streetAndFacadeTriangles: 10,
      untexturedStreetAndFacadeTriangles: 0,
      routeSupportGapSamples: 0,
    },
    noCutsOrFloatingGeometry: {
      routeSupportGapSamples: 0,
      ringEdgesWithoutDrawnFacade: 0,
      componentsDetachedFromSupport: 0,
      trianglesInsideBuildings: 0,
    },
    usefulEyeLevelMovement: {
      walkedDisplacementMm: 125_000,
      maxLateralDeviationMm: 0,
      recoveryEvents: 0,
      harnessPositionWrites: 0,
      traceSamples: 2500,
      routeSupportGapSamples: 0,
      maxEyeHeightErrorMm: 50,
      maxSupportResampleDeltaMm: 50,
    },
    completeCapsuleClearanceVerification: {
      capsuleSamples: 2500,
      capsuleSamplesChecked: 2500,
      capsuleTriangleContactSamples: 0,
      capsuleRingContactSamples: 0,
    },
    practicalBrowserBudget: {
      environmentTransferredBytes: MELBOURNE_ENVELOPE.environmentTransferredBytes,
      drawnTriangles: MELBOURNE_ENVELOPE.drawnTriangles,
      environmentDecodedTextureBytes: MELBOURNE_ENVELOPE.environmentDecodedTextureBytes,
      maxDrawCalls: MELBOURNE_ENVELOPE.maxDrawCalls,
      gpuErrors: 0,
      pageErrors: 0,
    },
    companionPresent: { captures: 3, capturesWithCompanionShown: 3 },
    reticlePresent: { captures: 3, capturesWithReticleCentred: 3 },
    authenticatedShellAndAuthoredHandlersPreserved: {
      captures: 3,
      capturesInProductShell: 3,
      foreignListeners: 0,
      productWindowKeydownListeners: 1,
      interactionsNotCarriedByProduct: 0,
      substitutedPages: 0,
    },
  };
}

describe('the key set is the reconciled one', () => {
  it('matches the latest retained reconciliation record exactly', () => {
    const record = reconciliation.record;
    expect(record.keySet).toBe(GATE_KEY_SET_VERSION);
    expect(record.canonicalKeys.map((entry) => entry.key)).toEqual([...CANONICAL_KEYS]);
    expect(record.thresholds).toEqual({ ...THRESHOLDS });
    expect(record.melbourneEnvelope).toEqual({ ...MELBOURNE_ENVELOPE });
    expect(record.judgedKey.captures).toEqual([...CAPTURE_LABELS]);
    for (const entry of record.canonicalKeys) {
      if (entry.evidenceKind === 'judged') {
        expect(entry.key).toBe(JUDGED_KEY);
        continue;
      }
      expect(entry.decidedBy).toEqual([...DECIDED_BY[entry.key as MechanicalKey]]);
    }
  });

  it('holds exactly nine keys, eight mechanical and one judged', () => {
    expect(CANONICAL_KEYS).toHaveLength(9);
    expect(Object.keys(DECIDED_BY)).toHaveLength(8);
    expect(Object.keys(DECIDED_BY)).not.toContain(JUDGED_KEY);
  });
});

describe('the mechanical decisions can pass and can fail', () => {
  it('passes a block at every threshold', () => {
    for (const [key, measured] of Object.entries(passing())) {
      expect(decideMechanical(key as MechanicalKey, measured), key).toBe(true);
    }
  });

  it('fails every key one step past its threshold', () => {
    const past: Record<MechanicalKey, [string, number]> = {
      continuousTexturedStreetAndFacades: ['untexturedStreetAndFacadeTriangles', 1],
      noCutsOrFloatingGeometry: ['componentsDetachedFromSupport', 1],
      usefulEyeLevelMovement: ['maxEyeHeightErrorMm', THRESHOLDS.eyeHeightToleranceMm + 1],
      completeCapsuleClearanceVerification: ['capsuleSamplesChecked', 2499],
      practicalBrowserBudget: ['maxDrawCalls', MELBOURNE_ENVELOPE.maxDrawCalls + 1],
      companionPresent: ['capturesWithCompanionShown', 2],
      reticlePresent: ['capturesWithReticleCentred', 2],
      authenticatedShellAndAuthoredHandlersPreserved: ['foreignListeners', 1],
    };
    for (const [key, [field, value]] of Object.entries(past)) {
      const measured = { ...passing()[key as MechanicalKey], [field]: value };
      expect(decideMechanical(key as MechanicalKey, measured), key).toBe(false);
    }
  });

  it('refuses a missing, negative or fractional measurement rather than deciding', () => {
    const { gpuErrors: _dropped, ...missing } = passing().practicalBrowserBudget;
    expect(() => decideMechanical('practicalBrowserBudget', missing)).toThrow(GateEvidenceError);
    expect(() =>
      decideMechanical('reticlePresent', { captures: 3, capturesWithReticleCentred: -1 }),
    ).toThrow(GateEvidenceError);
    expect(() =>
      decideMechanical('reticlePresent', { captures: 3, capturesWithReticleCentred: 2.5 }),
    ).toThrow(GateEvidenceError);
  });

  it('never decides the judged key', () => {
    const decided = decideKeySet(passing());
    expect(decided[JUDGED_KEY]).toBe(AWAITING_JUDGE);
    expect(Object.keys(decided)).toEqual([...CANONICAL_KEYS]);
  });
});

describe('the harness rounds as the canonical rule does', () => {
  it('rounds half toward zero', () => {
    expect(millimetres(0.0015)).toBe(1);
    expect(millimetres(0.0025)).toBe(2);
    expect(millimetres(-0.0025)).toBe(-2);
    expect(millimetres(1.6204)).toBe(1620);
    expect(millimetres(1.6206)).toBe(1621);
    expect(() => millimetres(Number.NaN)).toThrow(GateEvidenceError);
  });
});

describe('the package holds no randomness and no vocabulary', () => {
  it('never samples a random number', () => {
    const sources = readdirSync(join(here, '..', 'src')).filter((name) => name.endsWith('.ts'));
    expect(sources.length).toBeGreaterThan(0);
    for (const name of sources) {
      const text = readFileSync(join(here, '..', 'src', name), 'utf8');
      expect(text, name).not.toMatch(/Math\.random|crypto\.getRandomValues|Date\.now|performance\.now/);
      expect(text, name).not.toMatch(/owned-|flatiron|playcanvas/i);
    }
  });
});
