import { describe, expect, it } from 'vitest';
import {
  ROUTE_RULE,
  SupportSamples,
  TriangleTable,
  classify,
  measureCapsule,
  measureWalk,
  planRoute,
  resampleTrace,
  sampleQueryPoints,
  type TracePose,
} from '../src/index.js';
import { flatSupport, street } from './fixtures.js';

const BOUNDS = [-50, -60, 250, 60] as const;

function straightWalk(from: number, to: number, z = 0, y = 1.62, steps = 240): TracePose[] {
  const poses: TracePose[] = [];
  for (let i = 0; i <= steps; i += 1) poses.push({ x: from + ((to - from) * i) / steps, y, z });
  return poses;
}

async function walked(options: Parameters<typeof street>[0], poses: TracePose[]) {
  const scene = street(options);
  const table = new TriangleTable(scene.meshes);
  const samples = resampleTrace(poses, 0.05);
  const points = new Float64Array([...table.centroidQueryPoints(), ...sampleQueryPoints(samples)]);
  const support = new SupportSamples(points, await flatSupport(points));
  const classification = classify(table, scene.prisms, support);
  return { scene, table, samples, support, classification };
}

describe('the route rule', () => {
  it('walks down the street from the arrival pose', () => {
    const { prisms } = street();
    const plan = planRoute([5, 0], prisms, BOUNDS);
    expect(plan.headingMillidegrees).toBe(270_000);
    expect(plan.forward[0]).toBeCloseTo(1);
    expect(plan.forward[1]).toBeCloseTo(0);
    expect(plan.frontageBothSidesSamples).toBe(plan.frontageSamples);
    expect(plan.meanFrontageSkewMillionths).toBe(0);
    expect(plan.candidatesTried).toBe(720);
    expect(plan.clearRunMm).toBeGreaterThanOrEqual(ROUTE_RULE.lengthMm + ROUTE_RULE.stopMarginMm);
  });

  it('is the same plan every time', () => {
    const { prisms } = street();
    expect(planRoute([5, 0], prisms, BOUNDS)).toEqual(planRoute([5, 0], prisms, BOUNDS));
  });

  it('refuses when no heading clears the route length', () => {
    const { prisms } = street();
    expect(() => planRoute([5, 0], prisms, [-10, -60, 100, 60])).toThrow(/cannot be walked/);
  });
});

describe('resampling', () => {
  it('samples every 0.05 m and keeps both ends', () => {
    const samples = resampleTrace(straightWalk(0, 1), 0.05);
    expect(samples).toHaveLength(21);
    expect(samples[0]!.x).toBe(0);
    expect(samples.at(-1)!.x).toBeCloseTo(1);
    expect(samples[10]!.s).toBeCloseTo(0.5);
  });
});

describe('the walk measurement', () => {
  const plan = planRoute([5, 0], street().prisms, BOUNDS);

  it('passes a straight walk at eye height over drawn ground', async () => {
    const poses = straightWalk(5, 130);
    const { table, samples, support, classification } = await walked({}, poses);
    const result = measureWalk(plan, poses, samples, table, classification, support);
    expect(result.walkedDisplacementMm).toBe(125_000);
    expect(result.maxLateralDeviationMm).toBe(0);
    expect(result.routeSupportGapSamples).toBe(0);
    expect(result.maxEyeHeightErrorMm).toBe(0);
    expect(result.traceSamples).toBe(2501);
  });

  it('counts a hole in the drawn ground as a gap', async () => {
    const poses = straightWalk(5, 130);
    const { table, samples, support, classification } = await walked({ groundHole: true }, poses);
    const result = measureWalk(plan, poses, samples, table, classification, support);
    expect(result.routeSupportGapSamples).toBe(99);
  });

  it('measures an eye that is not at 1.62 m', async () => {
    const poses = straightWalk(5, 130, 0, 1.8);
    const { table, samples, support, classification } = await walked({}, poses);
    const result = measureWalk(plan, poses, samples, table, classification, support);
    expect(result.maxEyeHeightErrorMm).toBe(180);
  });
});

describe('the capsule', () => {
  it('clears an open street and touches a pole on the route', async () => {
    const poses = straightWalk(5, 130);
    const open = await walked({}, poses);
    const clear = measureCapsule(open.samples, open.table, open.classification, open.scene.prisms);
    expect(clear.capsuleSamplesChecked).toBe(clear.capsuleSamples);
    expect(clear.capsuleTriangleContactSamples).toBe(0);
    expect(clear.capsuleRingContactSamples).toBe(0);
    const blocked = await walked({ poleOnRoute: true }, poses);
    const touched = measureCapsule(blocked.samples, blocked.table, blocked.classification, blocked.scene.prisms);
    expect(touched.capsuleTriangleContactSamples).toBeGreaterThan(0);
    expect(touched.contactExamples[0]!.meshOrPrism).toBe('pole');
  });

  it('touches a ring the route passes too close to, and skips no sample silently', async () => {
    const poses = straightWalk(5, 130, 9.8);
    const near = await walked({}, poses);
    const result = measureCapsule(near.samples, near.table, near.classification, near.scene.prisms);
    expect(result.capsuleRingContactSamples).toBe(result.capsuleSamples);
    const holed = await walked({ groundHole: true }, straightWalk(5, 130));
    const partial = measureCapsule(holed.samples, holed.table, holed.classification, holed.scene.prisms);
    expect(partial.capsuleSamplesChecked).toBeLessThan(partial.capsuleSamples);
  });
});
