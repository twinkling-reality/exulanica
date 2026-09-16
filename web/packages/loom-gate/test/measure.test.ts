import { describe, expect, it } from 'vitest';
import {
  AWAITING_JUDGE,
  keySet,
  measureScene,
  mechanicalMeasurements,
  planRoute,
  type RunObservation,
  type TracePose,
} from '../src/index.js';
import { flatSupport, street } from './fixtures.js';

const BOUNDS = [-50, -60, 250, 60] as const;

function walk(): TracePose[] {
  const poses: TracePose[] = [];
  for (let i = 0; i <= 250; i += 1) poses.push({ x: 5 + (125 * i) / 250, y: 1.62, z: 0 });
  return poses;
}

const cleanRun: RunObservation = {
  captures: (['start', 'midpoint', 'endpoint'] as const).map((label) => ({
    label,
    companionShown: true,
    reticleCentred: true,
    inProductShell: true,
  })),
  foreignListeners: 0,
  productWindowKeydownListeners: 2,
  interactionsNotCarriedByProduct: 0,
  substitutedPages: 0,
  recoveryEvents: 0,
  harnessPositionWrites: 0,
  environmentTransferredBytes: 1_000_000,
  environmentDecodedTextureBytes: 4096,
  maxDrawCalls: 12,
  gpuErrors: 0,
  pageErrors: 0,
};

async function run(options: Parameters<typeof street>[0], observation: RunObservation = cleanRun) {
  const scene = street(options);
  const plan = planRoute([5, 0], scene.prisms, BOUNDS);
  const measured = await measureScene({
    meshes: scene.meshes,
    prisms: scene.prisms,
    plan,
    poses: walk(),
    sampleSupport: flatSupport,
  });
  return keySet(mechanicalMeasurements(measured, observation));
}

describe('one run, end to end', () => {
  it('passes every mechanical key for a textured, clean street and leaves the judged key open', async () => {
    const keys = await run({ textured: true });
    expect(keys).toEqual({
      continuousTexturedStreetAndFacades: true,
      readsAsInhabitedStreet: AWAITING_JUDGE,
      noCutsOrFloatingGeometry: true,
      usefulEyeLevelMovement: true,
      completeCapsuleClearanceVerification: true,
      practicalBrowserBudget: true,
      companionPresent: true,
      reticlePresent: true,
      authenticatedShellAndAuthoredHandlersPreserved: true,
    });
  });

  it('fails the textured key for flat colour', async () => {
    const keys = await run({ textured: false });
    expect(keys.continuousTexturedStreetAndFacades).toBe(false);
    expect(keys.noCutsOrFloatingGeometry).toBe(true);
  });

  it('fails integrity and movement for a hole and a pole, and the shell key for a harness page', async () => {
    const keys = await run(
      { textured: true, groundHole: true, poleOnRoute: true },
      { ...cleanRun, substitutedPages: 1 },
    );
    expect(keys.noCutsOrFloatingGeometry).toBe(false);
    expect(keys.continuousTexturedStreetAndFacades).toBe(false);
    expect(keys.usefulEyeLevelMovement).toBe(false);
    expect(keys.completeCapsuleClearanceVerification).toBe(false);
    expect(keys.authenticatedShellAndAuthoredHandlersPreserved).toBe(false);
  });

  it('fails the product-shell keys when a capture lost the Companion or the reticle', async () => {
    const captures = cleanRun.captures.map((capture, index) =>
      index === 1 ? { ...capture, companionShown: false, reticleCentred: false } : capture,
    );
    const keys = await run({ textured: true }, { ...cleanRun, captures });
    expect(keys.companionPresent).toBe(false);
    expect(keys.reticlePresent).toBe(false);
  });

  it('refuses a run whose captures are not the three route captures in order', async () => {
    const scene = street({ textured: true });
    const measured = await measureScene({
      meshes: scene.meshes,
      prisms: scene.prisms,
      plan: planRoute([5, 0], scene.prisms, BOUNDS),
      poses: walk(),
      sampleSupport: flatSupport,
    });
    expect(() =>
      mechanicalMeasurements(measured, { ...cleanRun, captures: cleanRun.captures.slice(0, 2) }),
    ).toThrow(/captures must be/);
  });
});
