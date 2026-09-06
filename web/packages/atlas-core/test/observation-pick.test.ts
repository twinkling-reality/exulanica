// Click-to-evidence geometry: the cursor-to-recorded-point path, and what it refuses to answer.

import { describe, expect, it } from 'vitest';

import {
  canvasToSourcePixel,
  observationSentence,
  pickObservedPoint,
  projectToSourcePixel,
  type PickCalibration,
  type PickCamera,
  type SparseObservedPoint,
} from '../src/index.js';

const CALIBRATION: PickCalibration = { width: 640, height: 480, fx: 500, fy: 500, cx: 320, cy: 240 };

/** A camera at the origin looking down -Z, which is the renderer convention the graph delivers. */
const AT_ORIGIN: PickCamera = {
  sceneFromCameraRowMajor: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
  calibration: CALIBRATION,
  projection: 'pinhole',
};

/**
 * The same camera moved to (10, 2, 0) and yawed so it looks along -X, with world +Y still up.
 *
 * Columns of the rotation block are the camera's axes in scene space: +X right is (0, 0, -1),
 * +Y up is (0, 1, 0), and +Z is (1, 0, 0), so forward, which is -Z, is (-1, 0, 0).
 */
const MOVED: PickCamera = {
  sceneFromCameraRowMajor: [0, 0, 1, 10, 0, 1, 0, 2, -1, 0, 0, 0, 0, 0, 0, 1],
  calibration: CALIBRATION,
  projection: 'pinhole',
};

function point(pointId: number, world: readonly [number, number, number], track = 1): SparseObservedPoint {
  return { pointId, world, trackLength: track, observationsRetained: Math.min(track, 2) };
}

describe('projecting a scene point into the source photograph', () => {
  it('puts a point straight ahead at the principal point', () => {
    expect(projectToSourcePixel(AT_ORIGIN, [0, 0, -5])).toEqual({ u: 320, v: 240, depth: 5 });
  });

  it('sends +Y in the world upward in the image, not downward', () => {
    // The renderer camera has +Y up and COLMAP image axes have +V down, so the sign flips on the
    // way across. Getting this wrong gives a vertically mirrored pick that looks plausible on a
    // symmetric subject, which is why it is asserted rather than reasoned about.
    const above = projectToSourcePixel(AT_ORIGIN, [0, 1, -5]);
    expect(above?.v).toBeLessThan(240);
    const below = projectToSourcePixel(AT_ORIGIN, [0, -1, -5]);
    expect(below?.v).toBeGreaterThan(240);
  });

  it('sends +X in the world rightward in the image', () => {
    expect(projectToSourcePixel(AT_ORIGIN, [1, 0, -5])?.u).toBeGreaterThan(320);
  });

  it('refuses a point behind the camera rather than projecting it through the lens', () => {
    expect(projectToSourcePixel(AT_ORIGIN, [0, 0, 5])).toBeNull();
    expect(projectToSourcePixel(AT_ORIGIN, [0, 0, 0])).toBeNull();
  });

  it('honours a camera that is not at the origin and not axis-aligned', () => {
    // The camera stands at (10, 2, 0) looking along -X, so a point at (5, 2, 0) is five units
    // straight ahead of it and lands on the principal point.
    const projected = projectToSourcePixel(MOVED, [5, 2, 0]);
    expect(projected?.depth).toBeCloseTo(5, 9);
    expect(projected?.u).toBeCloseTo(320, 9);
    expect(projected?.v).toBeCloseTo(240, 9);
  });
});

describe('canvas coordinates to source pixels', () => {
  it('round-trips a canvas of exactly the source aspect ratio', () => {
    const canvas = { width: 640, height: 480 };
    expect(canvasToSourcePixel(CALIBRATION, canvas, { x: 0, y: 0 })).toEqual({ u: 0, v: 0 });
    expect(canvasToSourcePixel(CALIBRATION, canvas, { x: 640, y: 480 })).toEqual({ u: 640, v: 480 });
    expect(canvasToSourcePixel(CALIBRATION, canvas, { x: 320, y: 240 })).toEqual({ u: 320, v: 240 });
  });

  it('reports a click in a wide canvas margin as outside the photograph rather than at its edge', () => {
    // Vertical coverage is fitted to the image; a wider canvas exposes more of the world
    // horizontally. That extra margin is a real place the photograph does not cover, and
    // clamping it to the frame edge would report a click outside the frame as a click inside it.
    const wide = { width: 960, height: 480 };
    expect(canvasToSourcePixel(CALIBRATION, wide, { x: 0, y: 0 }).u).toBeLessThan(0);
    expect(canvasToSourcePixel(CALIBRATION, wide, { x: 960, y: 0 }).u).toBeGreaterThan(640);
    // Vertical coverage is unchanged by canvas width.
    expect(canvasToSourcePixel(CALIBRATION, wide, { x: 0, y: 480 }).v).toBe(480);
  });

  it('refuses a canvas with no area', () => {
    expect(() => canvasToSourcePixel(CALIBRATION, { width: 0, height: 480 }, { x: 0, y: 0 })).toThrow(
      RangeError,
    );
  });
});

describe('picking a recorded point', () => {
  it('selects the point under the cursor', () => {
    const points = [point(1, [0, 0, -5]), point(2, [2, 0, -5])];
    const picked = pickObservedPoint(AT_ORIGIN, points, { u: 322, v: 241 });
    expect(picked?.point.pointId).toBe(1);
    expect(picked?.pixelDistance).toBeLessThan(4);
    expect(picked?.depth).toBeCloseTo(5, 9);
  });

  it('answers null when nothing recorded is near the cursor', () => {
    // A real answer, not a failure. It means no photograph's recorded observations reach this part
    // of the view, which is the honest state for a plain surface with few matched features.
    expect(pickObservedPoint(AT_ORIGIN, [point(1, [0, 0, -5])], { u: 10, v: 10 })).toBeNull();
  });

  it('respects an explicit tolerance', () => {
    const points = [point(1, [0, 0, -5])];
    expect(pickObservedPoint(AT_ORIGIN, points, { u: 350, v: 240 })).toBeNull();
    expect(
      pickObservedPoint(AT_ORIGIN, points, { u: 350, v: 240 }, { tolerancePx: 40 })?.point.pointId,
    ).toBe(1);
  });

  it('prefers the nearer point when two lie on the same ray', () => {
    // A background point a fraction of a pixel closer to the cursor must not beat the foreground
    // surface occluding it.
    const near = point(1, [0, 0, -5]);
    const far = point(2, [0, 0, -50]);
    const picked = pickObservedPoint(AT_ORIGIN, [far, near], { u: 320, v: 240 });
    expect(picked?.point.pointId).toBe(1);
    expect(picked?.depth).toBeCloseTo(5, 9);
  });

  it('ignores points behind the camera entirely', () => {
    const picked = pickObservedPoint(AT_ORIGIN, [point(1, [0, 0, 5]), point(2, [0, 0, -5])], {
      u: 320,
      v: 240,
    });
    expect(picked?.point.pointId).toBe(2);
  });

  it('is deterministic when two points coincide exactly', () => {
    const picked = pickObservedPoint(
      AT_ORIGIN,
      [point(9, [0, 0, -5]), point(3, [0, 0, -5])],
      { u: 320, v: 240 },
    );
    expect(picked?.point.pointId).toBe(3);
  });

  it('carries the projection label forward rather than discarding it', () => {
    const approximate: PickCamera = { ...AT_ORIGIN, projection: 'pinhole-approximation' };
    expect(
      pickObservedPoint(approximate, [point(1, [0, 0, -5])], { u: 320, v: 240 })?.projection,
    ).toBe('pinhole-approximation');
  });
});

describe('what the viewer is told', () => {
  it('says only the true count when nothing was truncated', () => {
    const result = pickObservedPoint(AT_ORIGIN, [point(1, [0, 0, -5], 1)], { u: 320, v: 240 })!;
    expect(observationSentence(result)).toBe('1 photograph observed this point.');
  });

  it('never lets a bounded sample read as a complete one', () => {
    // A viewer told "2 photographs" for a point forty photographs observed would be misled by
    // omission, so both numbers appear whenever they differ.
    const result = pickObservedPoint(AT_ORIGIN, [point(1, [0, 0, -5], 40)], { u: 320, v: 240 })!;
    const sentence = observationSentence(result);
    expect(sentence).toContain('40 photographs observed this point');
    expect(sentence).toContain('2 photographs of them are retained');
    expect(sentence).toContain('bounded sample');
  });
});
