import { describe, expect, it } from 'vitest';
import { ORBIT_COUNT, ORBIT_PERIOD, orbitPose } from '../src/ui/world-orbit-geometry.js';

describe('projected world orbit', () => {
  it('closes every track without changing its perspective or material', () => {
    for (let index = 0; index < ORBIT_COUNT; index += 1) {
      const start = orbitPose(index, 3, 390, 844);
      const end = orbitPose(index, 3 + ORBIT_PERIOD, 390, 844);
      for (const key of ['x', 'y', 'ax', 'ay', 'bx', 'by', 'material'] as const) expect(end[key]).toBeCloseTo(start[key], 8);
    }
  });
  it('keeps projection invertible for image sampling and native selection', () => {
    for (const [width, height] of [[320,700],[390,844],[1440,900],[2000,1100]]) {
      for (let time = 0; time < ORBIT_PERIOD; time += 3) {
        for (let index = 0; index < ORBIT_COUNT; index += 1) {
          const p = orbitPose(index,time,width!,height!);
          expect(Number.isFinite(p.x + p.y)).toBe(true);
          expect(p.ax * p.by - p.ay * p.bx).toBeGreaterThan(100);
        }
      }
    }
  });
});
