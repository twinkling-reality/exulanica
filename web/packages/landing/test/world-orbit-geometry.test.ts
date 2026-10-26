import { describe, expect, it } from 'vitest';
import { ORBIT_COUNT, ORBIT_OUTER_COUNT, ORBIT_INNER_COUNT, ORBIT_PERIOD, ORBIT_TOUCH_RADIUS, WORLD_ORBIT_SLOTS, orbitDrawn, orbitPose } from '../src/ui/world-orbit-geometry.js';
import { WORLD_SCENES } from '../src/ui/world-scenes.js';

// The title page's stage is the viewport: phones, then tablets and desktops.
const PHONES = [[320, 568], [360, 780], [375, 667], [390, 844], [430, 932], [480, 900]] as const;
const WIDER = [[600, 900], [768, 1024], [820, 1180], [1024, 768], [1280, 800], [1440, 900], [1920, 1080]] as const;

/**
 * The round area a drawn orb's link takes, as world-optics.ts sizes it (a world's never under its touch radius) and the
 * stylesheet rounds it, held within the circle of its larger half-axis.
 */
function touchArea(index: number, time: number, width: number, height: number) {
  const pose = orbitPose(index, time, width, height);
  const minimum = (WORLD_ORBIT_SLOTS as readonly number[]).includes(index) ? ORBIT_TOUCH_RADIUS : 0;
  return { x: pose.x, y: pose.y, r: Math.max(minimum, Math.hypot(pose.ax, pose.bx), Math.hypot(pose.ay, pose.by)) };
}

describe('projected world orbit', () => {
  it('retains the complete two-ring composition when the capture catalog is smaller', () => {
    // The original composition has 24 slots. Content availability must not reduce it.
    expect(ORBIT_OUTER_COUNT).toBe(12);
    expect(ORBIT_INNER_COUNT).toBe(12);
    expect(ORBIT_COUNT).toBe(24);
    expect(new Set(WORLD_ORBIT_SLOTS).size).toBe(WORLD_ORBIT_SLOTS.length);
    expect(WORLD_ORBIT_SLOTS.every(index => index >= 0 && index < ORBIT_COUNT)).toBe(true);
  });
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
          expect(p.ax * p.by - p.ay * p.bx).toBeGreaterThan(1);
          if ((WORLD_ORBIT_SLOTS as readonly number[]).includes(index)) {
            expect(p.x - Math.max(22, Math.hypot(p.ax, p.bx))).toBeGreaterThan(0);
            expect(p.x + Math.max(22, Math.hypot(p.ax, p.bx))).toBeLessThan(width!);
          }
        }
      }
    }
  });
  it('never stands one drawn orb over another at any moment of a period, on a phone, a tablet or a desktop', () => {
    for (const [width, height] of [...PHONES, ...WIDER]) {
      const drawn = Array.from({ length: ORBIT_COUNT }, (_, index) => index).filter(index => orbitDrawn(index, width, height));
      for (let time = 0; time < ORBIT_PERIOD; time += .25) {
        const areas = drawn.map(index => touchArea(index, time, width, height));
        for (const [i, a] of areas.entries()) for (const b of areas.slice(i + 1)) {
          expect(Math.hypot(a.x - b.x, a.y - b.y) < a.r + b.r, `${width}x${height} at ${time} s`).toBe(false);
        }
      }
    }
  });
  it('draws both rings where they stand apart, and on a phone the outer ring, which holds every showcase world', () => {
    for (const [width, height] of WIDER) {
      expect(Array.from({ length: ORBIT_COUNT }, (_, index) => orbitDrawn(index, width, height)).every(Boolean), `${width}x${height}`).toBe(true);
    }
    const showcase = WORLD_SCENES.flatMap((scene, index) => (scene.world ? [WORLD_ORBIT_SLOTS[index]!] : []));
    expect(showcase.length).toBeGreaterThan(0);
    for (const [width, height] of PHONES) {
      for (let index = 0; index < ORBIT_COUNT; index += 1) expect(orbitDrawn(index, width, height)).toBe(index < ORBIT_OUTER_COUNT);
      for (const slot of showcase) expect(orbitDrawn(slot, width, height), `${width}x${height} slot ${slot}`).toBe(true);
    }
  });
});
