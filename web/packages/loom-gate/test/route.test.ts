import { describe, expect, it } from 'vitest';
import {
  ROUTE_RULE,
  SupportSamples,
  TriangleTable,
  classify,
  firstContact,
  measureCapsule,
  measureWalk,
  planRoute,
  resampleTrace,
  sampleQueryPoints,
  type RouteRing,
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

  it('decides exactly what it decided before it counted anything', () => {
    // Every field MEASURED on the commit before `candidatesWithFrontage` existed, so this is a
    // before and after rather than an argument that a counter must be inert. The counter is a
    // diagnostic: it separates the rule running from the rule deciding, and if adding it had moved
    // a heading by one step the gate would have been tuned by the lane that runs it.
    const { rule, candidatesWithFrontage, ...decided } = planRoute([5, 0], street().prisms, BOUNDS);
    expect(decided).toEqual({
      start: [5, 0],
      headingMillidegrees: 270_000,
      yaw: 4.71238898038469,
      forward: [1, 1.8369701987210297e-16],
      right: [-1.8369701987210297e-16, 1],
      clearRunMm: 245_000,
      frontageSamples: 126,
      frontageBothSidesSamples: 126,
      meanFrontageSkewMillionths: 0,
      candidatesTried: 720,
      candidatesQualified: 17,
    });
    // And the counter says something: all seventeen qualifying headings had frontage on both sides
    // here, so on this fixture frontage is what decided.
    expect(candidatesWithFrontage).toBe(17);
    expect(rule).toBe(ROUTE_RULE);
  });

  it('counts no candidate with frontage when nothing stands beside the walk', () => {
    // The degenerate case the counter exists for: rings the walk never passes on both sides. The
    // rule still returns a heading, and the count says frontage did not choose it.
    const aside: RouteRing[] = [
      { id: 'far', ring: [[200, 40], [204, 40], [204, 44], [200, 44], [200, 40]] },
    ];
    const plan = planRoute([5, 0], aside, BOUNDS);
    expect(plan.candidatesQualified).toBeGreaterThan(0);
    expect(plan.candidatesWithFrontage).toBe(0);
    expect(plan.frontageBothSidesSamples).toBe(0);
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

describe('a start lying exactly on the walkable field boundary', () => {
  // MEASURED 2026-09-18 on a generated tile, whose runtime opens a walk at the middle of its
  // nav_envelope's southern edge, which IS the field's south face. `firstContact` tested all four
  // faces and kept a crossing only where t was strictly positive, so the face the walker stood on
  // gave t of zero and was skipped: 117 southward headings of 720 "cleared" 132 m off the tile and
  // qualified. 153 qualified there against the 36 that qualify one millimetre inside.
  const RINGS: RouteRing[] = [];
  const FIELD = [0, -128, 128, 0] as const;
  const ON_THE_SOUTH_EDGE: [number, number] = [64, 0];

  it('is bounded at nothing by the face it is leaving through', () => {
    // Due south from the south edge, heading 180000 millidegrees: forward is (0, +1), straight out.
    const out = firstContact(ON_THE_SOUTH_EDGE, [0, 1], 0.34, [], FIELD, 5_000);
    expect(out).toBe(0);
  });

  it('CROSSES THE WHOLE FIELD when it points inward from that same face', () => {
    // The case a loosened inequality gets wrong, and the reason the faces are chosen rather than
    // the comparison. Today's code passes this by skipping the south face entirely; tomorrow's must
    // pass it because it bounds by the NORTH face, which is the one this ray leaves by.
    const inward = firstContact(ON_THE_SOUTH_EDGE, [0, -1], 0.34, [], FIELD, 5_000);
    expect(inward).toBeCloseTo(128, 9);
  });

  it('bounds a heading that leaves through a side face at that side', () => {
    const east = firstContact(ON_THE_SOUTH_EDGE, [1, 0], 0.34, [], FIELD, 5_000);
    expect(east).toBeCloseTo(64, 9);
  });

  it('qualifies no heading that walks off the field, with no ring anywhere', () => {
    // With no rings at all the only thing that can bound a heading is the field, so this counts
    // exactly the headings the field admits. Every heading pointing south of the two side faces
    // leaves immediately and must not qualify.
    const plan = planRoute(ON_THE_SOUTH_EDGE, RINGS, FIELD);
    expect(plan.candidatesTried).toBe(720);
    const required = ROUTE_RULE.lengthMm + ROUTE_RULE.stopMarginMm;
    expect(plan.clearRunMm).toBeGreaterThanOrEqual(required);
    // A qualifying heading from the middle of the south edge has to reach a far face 131 m away,
    // which only the northward diagonals do in a field 128 m across.
    expect(plan.candidatesQualified).toBeGreaterThan(0);
    for (let millidegrees = 151_000; millidegrees <= 209_000; millidegrees += ROUTE_RULE.headingStepMillidegrees) {
      const yaw = (millidegrees / 1000) * (Math.PI / 180);
      const forward: [number, number] = [-Math.sin(yaw), -Math.cos(yaw)];
      expect(firstContact(ON_THE_SOUTH_EDGE, forward, 0.34, [], FIELD, 5_000)).toBeLessThan(required / 1000);
    }
  });
});
