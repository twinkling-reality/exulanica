import { describe, expect, it } from 'vitest';
import {
  authoredPlacementTransform,
  printDepthOnFlatGround,
} from '../src/playcanvas/authored-point-maps.js';
import type { PointMap } from '../src/playcanvas/opm.js';

/**
 * The arithmetic behind a placed depth estimate, which is the half that can be checked without a
 * GPU. What is drawn is checked in a real browser against a real WebGL2 device; the two halves are
 * separate on purpose, because a test that mocked a graphics device would be checking the mock.
 */

/** Just enough of a container for the two functions under test. */
function map(fovYDeg: number): PointMap {
  return { header: { viewpoint: { fovYDeg } } } as unknown as PointMap;
}

describe('an authored placement transform', () => {
  it('divides the wire units once and turns yaw into degrees', () => {
    const placed = authoredPlacementTransform({
      xMm: 1200, yMm: 1650, zMm: -450, yawMicroradians: 1_570_796, scaleMilli: 1000,
    });
    expect(placed.position).toEqual([1.2, 1.65, -0.45]);
    expect(placed.yawDegrees).toBeCloseTo(90, 4);
    expect(placed.scale).toBe(1);
  });

  it('carries a scale that is a multiple, not a measurement', () => {
    expect(authoredPlacementTransform({
      xMm: 0, yMm: 0, zMm: 0, yawMicroradians: 0, scaleMilli: 2500,
    }).scale).toBe(2.5);
  });
});

describe('the print depth over flat authored ground', () => {
  /**
   * The property this exists for: a frame tall enough to reach the ground before the wanted depth
   * is pulled in until its lower edge clears, rather than being buried. Measured on the first
   * personal place, a 77.5 degree frame at its 5.3 m median had its lower quarter under the floor.
   */
  it('pulls a tall frame in until its lower edge clears the ground', () => {
    const eyeHeight = 1.65;
    const depth = printDepthOnFlatGround(map(77.5), eyeHeight, 1, 5.3);
    expect(depth).toBeLessThan(5.3);
    const tanY = Math.tan((77.5 * Math.PI) / 360);
    // At the answer the lower edge sits exactly on the ground, never under it.
    expect(eyeHeight - depth * tanY).toBeCloseTo(0, 6);
  });

  it('leaves a narrow frame at the depth that was asked for', () => {
    expect(printDepthOnFlatGround(map(20), 1.65, 1, 3)).toBe(3);
  });

  it('shrinks with the placement scale, because a scaled print is a taller frame', () => {
    const wide = printDepthOnFlatGround(map(60), 1.65, 1, 100);
    expect(printDepthOnFlatGround(map(60), 1.65, 2, 100)).toBeCloseTo(wide / 2, 6);
  });

  it('draws a print flat at the standpoint rather than buried when it sits on the ground', () => {
    expect(printDepthOnFlatGround(map(60), 0, 1, 5)).toBe(0);
    expect(printDepthOnFlatGround(map(60), -1, 1, 5)).toBe(0);
  });

  it('gives back what was asked for when the frame says nothing usable', () => {
    for (const fov of [0, 180, Number.NaN]) {
      expect(printDepthOnFlatGround(map(fov), 1.65, 1, 4)).toBe(4);
    }
  });
});
