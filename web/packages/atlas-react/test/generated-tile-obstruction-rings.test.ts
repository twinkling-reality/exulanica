/**
 * Route obstruction rings, from what a tile's records state into the navigation world.
 *
 * Rings written by hand here rather than baked, because what is under test is the mapping: the frame
 * conversion, the identity carried into the id, and what happens to a region that bounds nothing.
 */

import { describe, expect, it } from 'vitest';
import { obstructionRings, type StatedObstructionRing } from '../src/playcanvas/generated-tile/index.js';

/** A square metre of bench at the tile's origin corner, in integer millimetres of the tile frame. */
const bench: StatedObstructionRing = {
  kind: 'city.street_furniture',
  identity: 'bench-7',
  statedBy: 'the tile',
  ring: [[1000, 2000], [2000, 2000], [2000, 3000], [1000, 3000]],
};

describe('carrying a tile\'s route obstruction rings', () => {
  it('names the record the ring came from, because a run record binds identities and not shapes', () => {
    const { obstacles, refused } = obstructionRings([bench]);
    expect(refused).toEqual([]);
    expect(obstacles).toHaveLength(1);
    expect(obstacles[0]!.id).toBe('city.street_furniture:bench-7');
  });

  it('puts the ring in the renderer\'s frame: x east in metres, z south, flat at the datum', () => {
    const [obstacle] = obstructionRings([bench]).obstacles;
    // The tile frame is x east, y north, z up in millimetres; the renderer is x east, y up, z south
    // in metres. So (1000, 2000) mm is (1, 0, -2) m and a ring's own height is nothing.
    expect(obstacle!.rings).toHaveLength(1);
    expect(obstacle!.rings[0]!.map((at) => [at.x, at.y, at.z])).toEqual([
      [1, 0, -2], [2, 0, -2], [2, 0, -3], [1, 0, -3],
    ]);
  });

  it('refuses a region that bounds nothing, and says so rather than thinning the set silently', () => {
    const line: StatedObstructionRing = { statedBy: 'the tile', kind: 'city.street_tree', identity: 'tree-2', ring: [[0, 0], [1000, 0]] };
    const { obstacles, refused } = obstructionRings([bench, line]);
    expect(obstacles).toHaveLength(1);
    expect(refused).toEqual([{
      kind: 'city.street_tree',
      identity: 'tree-2',
      statedBy: 'the tile',
      reason: 'a plan ring needs 3 corners to bound anything and this states 2',
    }]);
  });

  it('refuses a region that names no record, since an id that names nothing cannot be bound', () => {
    const anonymous: StatedObstructionRing = { ...bench, identity: '' };
    const { obstacles, refused } = obstructionRings([anonymous]);
    expect(obstacles).toEqual([]);
    expect(refused[0]!.reason).toBe('the region names no record identity');
  });

  it('carries every ring a tile states, in the order the tile states them', () => {
    const second: StatedObstructionRing = { ...bench, identity: 'bench-8' };
    const { obstacles } = obstructionRings([bench, second]);
    expect(obstacles.map((obstacle) => obstacle.id))
      .toEqual(['city.street_furniture:bench-7', 'city.street_furniture:bench-8']);
  });
});
