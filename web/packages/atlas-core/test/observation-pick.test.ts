// Click-to-evidence in the browser: where a click lands in the photograph, and what it is told.
//
// The pick itself runs on the server now, and its geometry cases moved with it to
// `tests/test_observation_pick.py`. What stays here is the half that still runs in the browser.

import { describe, expect, it } from 'vitest';

import {
  canvasToSourcePixel,
  observationSentence,
  type PickCalibration,
  type PickResult,
} from '../src/index.js';

const CALIBRATION: PickCalibration = { width: 640, height: 480, fx: 500, fy: 500, cx: 320, cy: 240 };

function result(trackLength: number, observationsRetained: number): PickResult {
  return {
    point: { pointId: 1, world: [0, 0, -5], trackLength, observationsRetained },
    pixelDistance: 0,
    depth: 5,
    projection: 'pinhole',
  };
}

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

describe('what the viewer is told', () => {
  it('says only the true count when nothing was truncated', () => {
    expect(observationSentence(result(1, 1))).toBe('1 photograph observed this point.');
  });

  it('never lets a bounded sample read as a complete one', () => {
    // A viewer told "2 photographs" for a point forty photographs observed would be misled by
    // omission, so both numbers appear whenever they differ.
    const sentence = observationSentence(result(40, 2));
    expect(sentence).toContain('40 photographs observed this point');
    expect(sentence).toContain('2 photographs of them are retained');
    expect(sentence).toContain('bounded sample');
  });
});
