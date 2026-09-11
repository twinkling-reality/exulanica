import { describe, expect, it } from 'vitest';

import {
  UNMEASURED_FAN_GAP_DEG, UNMEASURED_FAN_MAX_SWEEP_DEG, frameFraction, horizontalFovDeg, unmeasuredFan,
  type UnmeasuredFanInput,
} from '../src/unmeasured-fan.js';

/** The three maps of the first personal place, MEASURED 2026-09-11 from their OPM headers. */
const FIRST_PLACE: UnmeasuredFanInput[] = [
  { position: [0, 0, 0], fovYDeg: 57.726, aspect: 0.75 },
  { position: [0, 0, 0], fovYDeg: 77.503, aspect: 0.75 },
  { position: [0, 0, 0], fovYDeg: 48.707, aspect: 0.75 },
];

function apply(m: readonly number[], p: readonly [number, number, number]): [number, number, number] {
  return [
    m[0]! * p[0] + m[1]! * p[1] + m[2]! * p[2] + m[3]!,
    m[4]! * p[0] + m[5]! * p[1] + m[6]! * p[2] + m[7]!,
    m[8]! * p[0] + m[9]! * p[1] + m[10]! * p[2] + m[11]!,
  ];
}

/** Degrees left of -Z, positive to the left, for a direction in the scene. */
function yawOf(direction: readonly [number, number, number]): number {
  return (Math.atan2(-direction[0], -direction[2]) * 180) / Math.PI;
}

describe('unmeasuredFan', () => {
  it('turns one photograph to face straight ahead from the standpoint', () => {
    const [only] = unmeasuredFan([{ position: [0.2, 1.1, -0.3], fovYDeg: 60, aspect: 1.5 }]);
    expect(only).not.toBeNull();
    const at = apply(only!, [0.2, 1.1, -0.3]);
    at.forEach((value) => expect(value).toBeCloseTo(0, 12));
    expect(yawOf([only![2]! * -1, 0, only![10]! * -1])).toBeCloseTo(0, 9);
  });

  it('gives each photograph its own slice, left to right, centred and never overlapping', () => {
    const fan = unmeasuredFan(FIRST_PLACE);
    expect(fan.every((m) => m !== null)).toBe(true);
    const widths = FIRST_PLACE.map(horizontalFovDeg);
    const centres = fan.map((m) => yawOf([-m![2]!, 0, -m![10]!]));
    expect(centres[0]!).toBeGreaterThan(centres[1]!);
    expect(centres[1]!).toBeGreaterThan(centres[2]!);
    for (let i = 0; i + 1 < centres.length; i += 1) {
      const gap = (centres[i]! - widths[i]! / 2) - (centres[i + 1]! + widths[i + 1]! / 2);
      expect(gap).toBeCloseTo(UNMEASURED_FAN_GAP_DEG, 9);
    }
    const left = centres[0]! + widths[0]! / 2;
    const right = centres[2]! - widths[2]! / 2;
    expect(left).toBeCloseTo(-right, 9);
  });

  it('returns rigid transforms that keep up up', () => {
    for (const m of unmeasuredFan(FIRST_PLACE)) {
      const r = [0, 1, 2].map((row) => [0, 1, 2].map((column) => m![row * 4 + column]!));
      for (let a = 0; a < 3; a += 1) {
        for (let b = 0; b < 3; b += 1) {
          const dot = r.reduce((sum, row) => sum + row[a]! * row[b]!, 0);
          expect(dot).toBeCloseTo(a === b ? 1 : 0, 12);
        }
      }
      expect([m![4], m![5], m![6]]).toEqual([0, 1, 0]);
      expect(m!.slice(12)).toEqual([0, 0, 0, 1]);
    }
  });

  it('leaves out, rather than wraps round, photographs beyond the sweep', () => {
    const many = Array.from({ length: 12 }, () => FIRST_PLACE[0]!);
    const fan = unmeasuredFan(many);
    const fitted = fan.filter((m) => m !== null).length;
    const width = horizontalFovDeg(FIRST_PLACE[0]!);
    expect(fitted).toBe(Math.floor((UNMEASURED_FAN_MAX_SWEEP_DEG + UNMEASURED_FAN_GAP_DEG)
      / (width + UNMEASURED_FAN_GAP_DEG)));
    expect(fan.slice(fitted).every((m) => m === null)).toBe(true);
    expect(fan.slice(0, fitted).every((m) => m !== null)).toBe(true);
  });

  it('falls back to a camera-like width for a field of view no camera has', () => {
    expect(horizontalFovDeg({ position: [0, 0, 0], fovYDeg: Number.NaN, aspect: 1 })).toBe(60);
    expect(horizontalFovDeg({ position: [0, 0, 0], fovYDeg: 200, aspect: 1 })).toBe(60);
    expect(horizontalFovDeg({ position: [0, 0, 0], fovYDeg: 90, aspect: 1 })).toBeCloseTo(90, 9);
  });
});

describe('frameFraction', () => {
  const frame = { fovYDeg: 90, aspect: 0.5 };

  it('is 0 straight down the camera axis and 1 on the frame edge', () => {
    expect(frameFraction([0, 0, -1], frame)).toBe(0);
    expect(frameFraction([0, 1, -1], frame)).toBeCloseTo(1, 12);
    expect(frameFraction([0.5, 0, -1], frame)).toBeCloseTo(1, 12);
  });

  it('takes the tighter of the two axes, because the frame is a rectangle', () => {
    expect(frameFraction([0.25, 0.9, -1], frame)).toBeCloseTo(0.9, 12);
    expect(frameFraction([0.45, 0.1, -1], frame)).toBeCloseTo(0.9, 12);
  });

  it('answers nothing for a direction behind the camera or a frame no camera has', () => {
    expect(frameFraction([0, 0, 1], frame)).toBeNull();
    expect(frameFraction([0, 0, -1], { fovYDeg: 0, aspect: 1 })).toBeNull();
    expect(frameFraction([0, 0, -1], { fovYDeg: 60, aspect: 0 })).toBeNull();
  });
});
