import { describe, expect, it } from 'vitest';
import {
  ecefToGoogleLocal,
  googleLocalFrame,
  googleLocalToEcef,
  googleRenderOrigin,
  localTileTransform,
} from '../src/playcanvas/google-tiles-frame.js';

describe('Google geographic display frame', () => {
  it('round trips a local metre offset without changing source geography', () => {
    const frame = googleLocalFrame(-74.006, 40.7128, 12);
    const point = [125.25, 17.5, -83.75] as const;
    const roundTrip = ecefToGoogleLocal(frame, googleLocalToEcef(frame, point));
    expect(roundTrip[0]).toBeCloseTo(point[0], 7);
    expect(roundTrip[1]).toBeCloseTo(point[1], 7);
    expect(roundTrip[2]).toBeCloseTo(point[2], 7);
  });

  it('converts ECEF translation to small local values before rendering', () => {
    const frame = googleLocalFrame(-74.006, 40.7128);
    const ecef = googleLocalToEcef(frame, [20, 5, -40]);
    const transform = localTileTransform(frame, [
      1, 0, 0, 0,
      0, 1, 0, 0,
      0, 0, 1, 0,
      ecef[0], ecef[1], ecef[2], 1,
    ]);
    expect(transform[12]).toBeCloseTo(20, 7);
    expect(transform[13]).toBeCloseTo(5, 7);
    expect(transform[14]).toBeCloseTo(-40, 7);
  });

  it('rebases only transient renderer coordinates', () => {
    const previous = [0, 0, 0] as const;
    expect(googleRenderOrigin([100, 0, 100], previous)).toBe(previous);
    expect(googleRenderOrigin([700, 9, -530], previous)).toEqual([768, 0, -512]);
  });
});
