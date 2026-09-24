import { describe, expect, it } from 'vitest';
import type { PointMap } from '../src/playcanvas/opm.js';
import {
  POINT_FRAGMENT_GLSL,
  POINT_VERTEX_GLSL,
  POINT_VERTEX_WGSL,
} from '../src/playcanvas/point-shader.js';
import {
  scenePointMapForward,
  scenePointMapViewpoint,
  validateScenePointMapPlacement,
  type PlacedScenePointMap,
} from '../src/playcanvas/scene-point-maps.js';
import {
  STANDPOINT_EDGE_FRACTION,
  STANDPOINT_MAX_OTHERS,
  planStandpoint,
  standpointTransform,
} from '../src/playcanvas/standpoint-scene.js';

/**
 * A joined standpoint, as the arithmetic that can be checked without a GPU. What is drawn is
 * checked in a real browser against a real WebGL2 device, as the authored point maps are; a test
 * that mocked a graphics device would be checking the mock.
 */

/** A turn by `yaw` degrees about +Y, row major. */
function yaw(degrees: number): number[] {
  const a = (degrees * Math.PI) / 180;
  return [Math.cos(a), 0, Math.sin(a), 0, 1, 0, -Math.sin(a), 0, Math.cos(a)];
}

/** `R diag(a, a, b)` as the server writes it, row major 4 x 4, no translation. */
function matrix(rotation: readonly number[], lateral: number, depth: number): number[] {
  const out: number[] = [];
  for (let row = 0; row < 3; row += 1) {
    out.push(rotation[row * 3]! * lateral, rotation[row * 3 + 1]! * lateral, rotation[row * 3 + 2]! * depth, 0);
  }
  return [...out, 0, 0, 0, 1];
}

/** A container of `count` points at depths `near` to `far` ahead of a camera at the origin. */
function map(near: number, far: number, fovYDeg = 60, aspect = 4 / 3): PointMap {
  const depths = [near, (near + far) / 2, far];
  const position = new Float32Array(depths.flatMap((depth) => [0, 0, -depth]));
  return {
    position,
    header: {
      pointCount: depths.length,
      viewpoint: { position: [0, 0, 0], forward: [0, 0, -1], up: [0, 1, 0], fovYDeg, aspect },
      bounds: { min: [0, 0, -far], max: [0, 0, -near] },
    },
  } as unknown as PointMap;
}

function member(artifactId: string, degrees: number, depth = 1, lateral = 1, points = map(2, 20)): PlacedScenePointMap {
  return {
    sceneId: 'scene-1',
    artifactId,
    captureId: `capture-${artifactId}`,
    islandId: 'island-1' as PlacedScenePointMap['islandId'],
    map: points,
    sceneFromOpmRowMajor: matrix(yaw(degrees), depth * lateral, depth),
    localUnitsToSceneUnits: depth,
    arrangement: 'standpoint',
  };
}

describe('a standpoint transform', () => {
  it('takes the server’s matrix apart into the rotation and the two scales it was made of', () => {
    const taken = standpointTransform(matrix(yaw(30), 1.1 * 0.95, 1.1));
    expect(taken.lateral).toBeCloseTo(1.045, 12);
    expect(taken.depth).toBeCloseTo(1.1, 12);
    taken.rotationRowMajor.forEach((value, index) => expect(value).toBeCloseTo(yaw(30)[index]!, 12));
    // The quaternion is the same turn: half the angle about +Y.
    const [x, y, z, w] = taken.rotation;
    expect([x, z]).toEqual([0, 0].map(() => expect.closeTo(0, 12)));
    expect(Math.atan2(y, w) * 2 * (180 / Math.PI)).toBeCloseTo(30, 9);
  });

  it('refuses a matrix that is not the promised shape', () => {
    const good = matrix(yaw(10), 1, 1);
    const reflected = matrix([-1, 0, 0, 0, 1, 0, 0, 0, 1], 1, 1);
    const unequal = [...good];
    unequal[1] = unequal[1]! * 2;
    unequal[5] = unequal[5]! * 2;
    unequal[9] = unequal[9]! * 2;
    const moved = [...good];
    moved[12] = 1;
    for (const bad of [reflected, unequal, moved, good.slice(0, 15), good.map(() => Number.NaN)]) {
      expect(() => standpointTransform(bad)).toThrow(TypeError);
    }
  });

  it('is what a scene point map validates a standpoint member against, and a similarity is not', () => {
    const joined = member('a', 25, 1.2, 0.9);
    expect(() => validateScenePointMapPlacement(joined)).not.toThrow();
    // The same non-uniform matrix passed off as a fitted placement is refused as one.
    expect(() => validateScenePointMapPlacement({ ...joined, arrangement: 'recovered' })).toThrow(TypeError);
    // Every camera stands at the standpoint, facing as it was measured to face.
    expect(scenePointMapViewpoint(joined)).toEqual([0, 0, 0]);
    const forward = scenePointMapForward(joined);
    expect(Math.hypot(...forward)).toBeCloseTo(1, 12);
    expect(Math.atan2(-forward[0], -forward[2]) * (180 / Math.PI)).toBeCloseTo(25, 9);
  });
});

describe('a standpoint plan', () => {
  it('gives each member the frames it cedes pixels to, and only those it can meet', () => {
    const plan = planStandpoint([member('a', 0), member('b', -40), member('c', 180)]);
    const a = plan.members.get('a')!;
    const c = plan.members.get('c')!;
    expect(a.otherCount).toBe(1);
    expect(c.otherCount).toBe(0);
    // The block for b is the rotation from a's camera into b's: R_b^T R_a, a turn of +40 degrees.
    const expected = yaw(40);
    [0, 1, 2, 4, 5, 6, 8, 9, 10].forEach((lane, index) =>
      expect(a.others[lane]).toBeCloseTo(expected[index]!, 6));
    // With b's own frame tangents beside it: 60 degrees vertical at 4:3.
    const tanY = Math.tan(Math.PI / 6);
    expect(a.others[3]).toBeCloseTo(tanY * (4 / 3), 6);
    expect(a.others[7]).toBeCloseTo(tanY, 6);
    expect(Array.from(a.others.slice(12))).toEqual(new Array((STANDPOINT_MAX_OTHERS - 1) * 12).fill(0));
  });

  it('re-projects a member’s frame onto its own rays when its focal length was corrected', () => {
    const plan = planStandpoint([member('a', 0, 1, 0.9), member('b', -30, 1, 1)]);
    const tanY = Math.tan(Math.PI / 6);
    expect(plan.members.get('a')!.frameTan[1]).toBeCloseTo(tanY * 0.9, 9);
    // And b sees a's corrected frame, not the depth model's.
    expect(plan.members.get('b')!.others[7]).toBeCloseTo(tanY * 0.9, 6);
  });

  it('stands one print where the photographs’ subjects stood and flattens every member alike', () => {
    const plan = planStandpoint([
      member('a', 0, 1, 1, map(2, 20)),
      member('b', -30, 1.5, 1, map(3, 40)),
      member('c', -60, 1, 1, map(1, 10)),
    ]);
    // Medians 11, 21.5 x 1.5 and 5.5, at scene scale: the middle one.
    expect(plan.printRadius).toBeCloseTo(11, 6);
    // The worst member's rate, in scene units: c, from 1 m to 10 m.
    expect(plan.parallaxPerUnit).toBeCloseTo(1 / 1 - 1 / 10, 6);
  });

  it('refuses a set it cannot draw as one view', () => {
    expect(() => planStandpoint([{ ...member('a', 0), arrangement: 'unmeasured-fan' }])).toThrow(TypeError);
    const crowded = Array.from({ length: STANDPOINT_MAX_OTHERS + 2 }, (_, index) => member(`m${index}`, -index * 5));
    expect(() => planStandpoint(crowded)).toThrow(/can consult/);
  });
});

describe('the standpoint shader', () => {
  it('holds exactly as many other frames as the plan lays out', () => {
    expect(POINT_FRAGMENT_GLSL).toContain(`uniform vec4 uStandpointOthers[${STANDPOINT_MAX_OTHERS * 3}];`);
    expect(POINT_FRAGMENT_GLSL).toContain(`for (int other = 0; other < ${STANDPOINT_MAX_OTHERS}; other++)`);
  });

  it('flattens every member towards one dome floored at the ground, on both graphics paths', () => {
    const glsl = POINT_VERTEX_GLSL.replace(/\s+/g, ' ');
    const wgsl = POINT_VERTEX_WGSL.replace(/\s+/g, ' ').replace(/uniform\./g, '');
    for (const source of [glsl, wgsl]) {
      expect(source).toContain('if (uRelief.w > 0.5)');
      expect(source).toContain('reach = min(reach, uViewpoint.w / down)');
      expect(source).toContain('fromEye / mix(1.0, range / reach, uRelief.y)');
    }
  });

  it('gives each direction to the frame whose centre is nearer and marks where capture ends', () => {
    const fragment = POINT_FRAGMENT_GLSL.replace(/\s+/g, ' ');
    expect(fragment).toContain('if (thereFraction < ownFraction) discard;');
    expect(fragment).toContain('bool edgeOfCapture = !continued && ownFraction > 1.0 - uStandpointEdge.x;');
    expect(fragment).toContain('if (edgeOfCapture) rgb = uStandpointEdge.yzw;');
    expect(STANDPOINT_EDGE_FRACTION).toBeGreaterThan(0);
    expect(STANDPOINT_EDGE_FRACTION).toBeLessThan(0.05);
  });
});
