import { describe, expect, it } from 'vitest';
import { pickSiteSlot } from '../src/composition/sight.js';

/*
 * Which made part a ray meets, by arithmetic on a drawing a test states (site millimetres: x east,
 * y north, z up): a house 8 m by 6 m and 5 m tall 20 m north and 10 m east of the corner, one of its
 * walls standing in front of it, a bench 10 m north, a pond (a plane) and a path (a plane nobody may
 * change), and a shed turned a quarter. Rays are metres, x east, y up, z south.
 */
const slot = (identity: string, primitive: string, position: [number, number, number], box: [number, number, number], yawQuarterTurns = 0, structure?: string) =>
  ({ identity, primitive, positionMm: position, boxMm: box, yawQuarterTurns, ...(structure === undefined ? {} : { structure }) });
const drawing = {
  slots: [
    slot('house', 'box', [10000, 20000, 0], [8000, 6000, 5000]),
    slot('house:wall:front', 'box', [10000, 16500, 0], [8000, 300, 3000], 0, 'house'),
    slot('bench', 'box', [5000, 10000, 0], [2000, 500, 450]),
    slot('pond', 'plane', [-10000, 15000, 0], [6000, 4000, 0]),
    slot('path', 'plane', [0, 5000, 0], [2000, 30000, 0]),
    slot('shed', 'box', [20000, 5000, 0], [6000, 2000, 3000], 1),
    slot('zone-wall', 'box', [-20000, 10000, 0], [300, 10000, 2000]),
    slot('kiosk', 'box', [-25000, 10000, 0], [2000, 2000, 2500]),
  ],
};
const changeable = new Set(['house', 'bench', 'pond', 'shed', 'kiosk']);
const pickable = (identity: string) => changeable.has(identity);
const towards = (from: [number, number, number], to: [number, number, number]): [number, number, number] => {
  const d = [to[0] - from[0], to[1] - from[1], to[2] - from[2]] as [number, number, number];
  const length = Math.hypot(...d);
  return d.map((v) => v / length) as [number, number, number];
};

describe('pointing at a made part of a site world', () => {
  it('names the part a ray meets first, a building by its own pieces', () => {
    const eye: [number, number, number] = [10, 1.6, 0];
    // Straight north at eye height: the house's front wall, which names the house, 16.35 m away.
    const met = pickSiteSlot(drawing, eye, [0, 0, -1], pickable);
    expect(met?.identity).toBe('house');
    expect(met?.distance).toBeCloseTo(16.35, 6);
  });

  it('takes the nearest when a ray passes through two', () => {
    // From the corner towards the house, low enough to pass through the bench on the way.
    const eye: [number, number, number] = [0, 0.3, 0];
    const met = pickSiteSlot(drawing, eye, towards(eye, [10, 0.3, -20]), pickable);
    expect(met?.identity).toBe('bench');
  });

  it('meets a pond lying on the ground, and never a part nobody may change', () => {
    expect(pickSiteSlot(drawing, [-10, 10, -15], [0, -1, 0], pickable)?.identity).toBe('pond');
    expect(pickSiteSlot(drawing, [0, 10, -5], [0, -1, 0], pickable)).toBeNull();
  });

  it('does not point through a wall nobody may change at the part behind it', () => {
    // West along a line 10 m north: the zone's wall, 20 m west of the corner, stands before the kiosk at 25 m.
    expect(pickSiteSlot(drawing, [-15, 1, -10], [-1, 0, 0], pickable)).toBeNull();
    // Over the wall's top, the kiosk is met.
    expect(pickSiteSlot(drawing, [-15, 2.2, -10], [-1, 0, 0], pickable)?.identity).toBe('kiosk');
    // Standing inside a box nobody may change (here the wall itself, as under a canopy) hides nothing.
    expect(pickSiteSlot(drawing, [-20, 1, -10], [-1, 0, 0], pickable)?.identity).toBe('kiosk');
  });

  it('reads a turned part across its turned sides, and nothing above every part', () => {
    // Turned a quarter: 2 m east to west and 6 m north to south about its centre (20 m east, 5 m north).
    expect(pickSiteSlot(drawing, [20, 10, -7.5], [0, -1, 0], pickable)?.identity).toBe('shed');
    expect(pickSiteSlot(drawing, [22.5, 10, -5], [0, -1, 0], pickable)).toBeNull();
    expect(pickSiteSlot(drawing, [10, 20, 0], [0, 0, -1], pickable)).toBeNull();
  });
});
