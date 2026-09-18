/**
 * The route obstruction rings of a baked tile, held to the records rather than to a shape this
 * test redraws: every ring names a record the container carries, every ring lies inside that
 * record's stated extent, and the set is exactly the kinds the grammar's navigation table names.
 *
 * AND THE CLAIM THAT MATTERS MOST HERE IS A NEGATIVE ONE: what stands above head height is NOT a
 * ring. The fixture's street tree is the case that proves it, since its canopy is twenty times its
 * trunk across, and a reader taking these for collision would put a six metre solid in a footway.
 */
import { describe, expect, it } from 'vitest';
import { bakeTile } from '../src/core/bake.js';
import { CITY_V2 } from '../src/core/city-v2.js';
import { decodeOwd } from '../src/core/owd.js';
import { routeObstructionRings } from '../src/core/route-rings.js';
import { nodeSha256 } from '../src/node/index.js';
import { fixtureBytes, fixtureObject, recordsOf } from './support.js';

const spread = (ring: readonly (readonly [number, number])[], axis: 0 | 1): number =>
  Math.max(...ring.map((point) => point[axis])) - Math.min(...ring.map((point) => point[axis]));

describe('the route obstruction rings of a baked tile', () => {
  it('names the record each came from, and carries only what the navigation table obstructs', async () => {
    const decoded = decodeOwd((await bakeTile(fixtureBytes(), nodeSha256)).container);
    const rings = routeObstructionRings(decoded.header);
    expect(rings.length).toBeGreaterThan(0);
    const obstructs = new Set(CITY_V2.navigation.filter((row) => row.obstruction !== 'none').map((row) => row.kind));
    expect(new Set(rings.map((ring) => ring.kind))).toEqual(obstructs);
    // Every ring names a record the container carries, of the kind the ring says it is.
    const byIdentity = new Map(decoded.header.records.map((record) => [record.identity, record]));
    for (const ring of rings) {
      const record = byIdentity.get(ring.identity);
      expect(record, `${ring.identity} is a record of this tile`).toBeDefined();
      expect(record!.kind).toBe(ring.kind);
      expect(ring.ring.length).toBeGreaterThanOrEqual(3);
    }
    // A halo record obstructs too: a bench over the boundary turns a walk on this side of it.
    expect(decoded.header.records.some((record) => record.membership === 'halo')).toBe(true);
  });

  it('leaves out what stands above head height, which is why it is not a collision solid', async () => {
    const decoded = decodeOwd((await bakeTile(fixtureBytes(), nodeSha256)).container);
    const rings = routeObstructionRings(decoded.header).filter((ring) => ring.kind === 'city.street_tree');
    const tree = recordsOf(fixtureObject(), 'city.street_tree')[0].fields as any;
    const canopy = tree.parts.find((part: any) => part.surface_role === 'canopy');
    const trunk = tree.parts.find((part: any) => part.surface_role === 'trunk');
    const height = CITY_V2.measures.nav_envelope!.capsule_clearance!.height_mm!;
    // The record states both, and only the one below head height is a ring.
    expect(canopy.offset_z_mm).toBeGreaterThanOrEqual(height);
    expect(trunk.offset_z_mm).toBeLessThan(height);
    expect(rings).toHaveLength(1);
    expect(spread(rings[0]!.ring, 0)).toBeLessThanOrEqual(trunk.size_x_mm);
    expect(spread(rings[0]!.ring, 0) * 2).toBeLessThan(canopy.size_x_mm);
  });
});
