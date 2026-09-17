import { describe, expect, it } from 'vitest';
import { SLOWEST_WALK_CADENCE, gaitFor } from '../src/playcanvas/character/person.js';

const walk = 1.12, run = 2.55;
/** How fast a planted foot moves backward under a blend at a cadence, for the idle, walk and run points. */
function footSpeed(blend: number, cadence: number): number {
  const clip = blend <= walk ? (blend / walk) * walk : walk + ((blend - walk) / (run - walk)) * (run - walk);
  return clip * cadence;
}

describe('gait for a resolved ground speed', () => {
  it('stands still at rest and never mixes standing into a walk at walking pace', () => {
    expect(gaitFor(0, walk, run)).toEqual({ blend: 0, cadence: 1 });
    for (const speed of [walk * SLOWEST_WALK_CADENCE, 0.8, 1.0, walk]) {
      const gait = gaitFor(speed, walk, run);
      expect(gait.blend, `blend at ${speed}`).toBe(walk);
    }
  });

  it('moves a planted foot exactly as fast as the ground at every speed', () => {
    for (let speed = 0.05; speed < 4.5; speed += 0.05) {
      const gait = gaitFor(speed, walk, run);
      expect(footSpeed(gait.blend, gait.cadence), `speed ${speed.toFixed(2)}`).toBeCloseTo(speed, 9);
      expect(gait.cadence).toBeGreaterThanOrEqual(SLOWEST_WALK_CADENCE);
    }
  });

  it('changes gait continuously as speed changes', () => {
    let previous = gaitFor(0.001, walk, run);
    for (let speed = 0.002; speed < 4.5; speed += 0.001) {
      const gait = gaitFor(speed, walk, run);
      expect(Math.abs(gait.blend - previous.blend), `blend jump at ${speed.toFixed(3)}`).toBeLessThan(0.01);
      expect(Math.abs(gait.cadence - previous.cadence), `cadence jump at ${speed.toFixed(3)}`).toBeLessThan(0.01);
      previous = gait;
    }
  });
});
