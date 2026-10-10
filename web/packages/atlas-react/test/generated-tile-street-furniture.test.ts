import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  ENTRANCE_KIND, STREET_FURNITURE_KIND, STREET_TREE_KIND, doorsOf, doorsOfRecords, sightBlockersOf, sightBlockersOfRecords,
  streetFurnitureOf,
} from '../src/playcanvas/generated-tile/street-furniture.js';

/*
 * The conformance tile's container against the document it was baked from
 * (packages/loom-tess/test/fixtures/tile-conformance.json): every piece of street furniture the
 * document states is read out of the container at the document's own figures, carried from the
 * tile's east and north into the society's east and south.
 */
interface StatedPart {
  readonly offset_x_mm: number; readonly offset_y_mm: number; readonly offset_z_mm: number;
  readonly size_x_mm: number; readonly size_y_mm: number; readonly size_z_mm: number;
}
interface StatedRecord {
  readonly kind: string;
  readonly fields: {
    readonly identity: string; readonly x_mm: number; readonly y_mm: number;
    readonly facing_dx_mm: number; readonly facing_dy_mm: number; readonly parts: readonly StatedPart[];
  };
}
// Tests run from web/.
const DOCUMENT = JSON.parse(readFileSync(resolve('packages/loom-tess/test/fixtures/tile-conformance.json'), 'utf8')) as {
  grammars: { owned: StatedRecord[]; halo: StatedRecord[] }[];
};
const STATED = DOCUMENT.grammars.flatMap((grammar) => [...grammar.owned, ...grammar.halo])
  .filter((record) => record.kind === 'city.street_furniture');
const CONTAINER = new Uint8Array(readFileSync(resolve('packages/app/src/dev/tiles/tile-conformance.owd')));

describe('a town tile\'s street furniture', () => {
  it('is every piece its document states, once, where and as the document states it', () => {
    // Positive control: the document states furniture, and one piece that faces neither east nor north.
    expect(STATED.length).toBeGreaterThan(3);
    expect(STATED.some((record) => record.fields.facing_dy_mm !== 0)).toBe(true);
    expect(STREET_FURNITURE_KIND).toBe('city.street_furniture');
    const read = streetFurnitureOf(CONTAINER);
    expect(read.map((item) => item.identity).sort()).toEqual(STATED.map((record) => record.fields.identity).sort());
    for (const record of STATED) {
      const item = read.find((one) => one.identity === record.fields.identity)!;
      expect(item.eastMm).toBe(record.fields.x_mm);
      // North in the tile is negative south in the society's plan.
      expect(item.southMm).toBe(-record.fields.y_mm);
      expect(item.facing[0]).toBe(record.fields.facing_dx_mm);
      expect(item.facing[1] + record.fields.facing_dy_mm).toBe(0);
      expect(item.parts).toEqual(record.fields.parts.map((part) => ({
        alongMm: part.offset_x_mm, leftMm: part.offset_y_mm, bottomMm: part.offset_z_mm,
        sizeAlongMm: part.size_x_mm, sizeLeftMm: part.size_y_mm, heightMm: part.size_z_mm,
      })));
    }
  });
});

/*
 * What stands in a sight line at a standing person's eye height, 1.6 m: of the same document's
 * furniture and trees, every part whose bottom is at or below that height and whose top is at or
 * above it. The count and the rectangles are worked here from the document's own figures and the
 * grammar's frame rule (+x the way a record faces, +y to its left, a tree facing east), for the
 * records that face an axis, where the turn is exact.
 */
const EYE_MM = 1_600;
const STANDING = DOCUMENT.grammars.flatMap((grammar) => [...grammar.owned, ...grammar.halo])
  .filter((record) => record.kind === 'city.street_furniture' || record.kind === 'city.street_tree');

describe('what stands at eye height in a town tile', () => {
  it('is every part of its furniture and trees that crosses that height, and no other', () => {
    expect(STREET_TREE_KIND).toBe('city.street_tree');
    const crossing = STANDING.flatMap((record) => record.fields.parts
      .filter((part) => part.offset_z_mm <= EYE_MM && part.offset_z_mm + part.size_z_mm >= EYE_MM)
      .map((part) => ({ record, part })));
    // Positive controls: something crosses eye height (a post, a trunk), and something does not
    // (a part that ends below it or begins above it), so the count below is neither all nor none.
    expect(crossing.length).toBeGreaterThan(0);
    expect(crossing.length).toBeLessThan(STANDING.flatMap((record) => record.fields.parts).length);
    const rings = sightBlockersOf(CONTAINER, EYE_MM);
    expect(rings).toHaveLength(crossing.length);
    for (const { record, part } of crossing) {
      // A tree's record states no direction: its parts' frame faces east.
      const stated = record.fields as { readonly facing_dx_mm?: number; readonly facing_dy_mm?: number };
      const dx = stated.facing_dx_mm ?? 1;
      const dy = stated.facing_dx_mm === undefined ? 0 : stated.facing_dy_mm ?? 0;
      if (dx !== 0 && dy !== 0) continue;
      const length = Math.hypot(dx, dy);
      // The part's middle in the tile's east and north, then north turned to south.
      const east = record.fields.x_mm + (part.offset_x_mm * dx - part.offset_y_mm * dy) / length;
      const north = record.fields.y_mm + (part.offset_x_mm * dy + part.offset_y_mm * dx) / length;
      const found = rings.find((ring) => {
        const middle: readonly [number, number] = [ring.reduce((sum, corner) => sum + corner[0], 0) / 4, ring.reduce((sum, corner) => sum + corner[1], 0) / 4];
        return Math.abs(middle[0] - east) < 1e-6 && Math.abs(middle[1] + north) < 1e-6;
      });
      expect(found, `${record.fields.identity} at ${east}, ${north}`).toBeDefined();
      // A rectangle of the part's two plan sizes, whichever way it is turned.
      const sides = [Math.hypot(found![1]![0] - found![0]![0], found![1]![1] - found![0]![1]), Math.hypot(found![2]![0] - found![1]![0], found![2]![1] - found![1]![1])];
      expect(sides.map((side) => Math.round(side)).sort((a, b) => a - b)).toEqual([part.size_x_mm, part.size_y_mm].sort((a, b) => a - b));
    }
  });

  it('holds nothing at a height nothing reaches', () => {
    expect(sightBlockersOf(CONTAINER, 100_000)).toEqual([]);
  });
});

/*
 * The frame rule on records written here by hand, since the document's posts and trunks stand on
 * their records' own base points and so say nothing of how an offset is turned. A record's `+x` is
 * the way it faces and `+y` is to its left; the tile's north is the plan's negative south.
 */
describe('a part that stands off its record\'s base point', () => {
  const corners = (ring: readonly (readonly [number, number])[]) =>
    ring.map(([east, south]) => [Math.round(east), Math.round(south)]).sort((a, b) => a[0]! - b[0]! || a[1]! - b[1]!);

  it('is turned with the record: ahead is the way it faces, and its left is to the left of that', () => {
    // Facing north from (10 m east, 20 m north): a post 1 m ahead (north) and 0.2 m to the left
    // (west), 100 mm deep the way the record faces and 300 mm wide across it.
    const sign = {
      kind: STREET_FURNITURE_KIND, identity: 'sign',
      fields: { x_mm: 10_000, y_mm: 20_000, facing_dx_mm: 0, facing_dy_mm: 2_000, parts: [
        { offset_x_mm: 1_000, offset_y_mm: 200, offset_z_mm: 0, size_x_mm: 100, size_y_mm: 300, size_z_mm: 3_000 },
      ] },
    };
    // Its middle is 9.8 m east and 21 m north, which is 21 m negative south; 300 mm east to west, 100 mm north to south.
    expect(sightBlockersOfRecords([sign], 1_600).map(corners)).toEqual([
      [[9_650, -21_050], [9_650, -20_950], [9_950, -21_050], [9_950, -20_950]],
    ]);
  });

  it('faces east where the record states no direction, and leaves out a part the height does not cross', () => {
    const tree = {
      kind: STREET_TREE_KIND, identity: 'tree',
      fields: { x_mm: 0, y_mm: 0, parts: [
        // A trunk 0.3 m east of the base point, and a canopy that starts above the eye.
        { offset_x_mm: 300, offset_y_mm: 0, offset_z_mm: 0, size_x_mm: 200, size_y_mm: 200, size_z_mm: 4_000 },
        { offset_x_mm: 0, offset_y_mm: 0, offset_z_mm: 2_500, size_x_mm: 3_000, size_y_mm: 3_000, size_z_mm: 2_000 },
      ] },
    };
    expect(sightBlockersOfRecords([tree], 1_600).map(corners)).toEqual([
      [[200, -100], [200, 100], [400, -100], [400, 100]],
    ]);
    // The same record a second time (a neighbour's halo copy) is read once.
    expect(sightBlockersOfRecords([tree, tree], 1_600)).toHaveLength(1);
  });
});

/*
 * A town's doors onto a footway: of the same document's entrance records, every one that names the
 * curb it opens onto, at the threshold the document states, carried into east and south.
 */
describe('a town tile\'s doors', () => {
  const ENTRANCES = (DOCUMENT.grammars.flatMap((grammar) => [...grammar.owned, ...grammar.halo]) as unknown as {
    kind: string; fields: { identity: string; threshold_x_mm: number; threshold_y_mm: number; approach_curb_identity: string[] };
  }[]).filter((record) => record.kind === 'city.entrance');

  it('are every entrance its document states that opens onto a curb, once, at the stated threshold', () => {
    expect(ENTRANCE_KIND).toBe('city.entrance');
    const onto = new Map(ENTRANCES.filter((record) => record.fields.approach_curb_identity.length > 0)
      .map((record) => [record.fields.identity, record.fields]));
    // Positive control: the document states doors onto a footway, on more than one tile's records.
    expect(onto.size).toBeGreaterThanOrEqual(3);
    expect(ENTRANCES.length).toBeGreaterThanOrEqual(onto.size);
    const read = doorsOf(CONTAINER);
    expect(read.map((door) => door.identity).sort()).toEqual([...onto.keys()].sort());
    for (const door of read) {
      expect(door.eastMm).toBe(onto.get(door.identity)!.threshold_x_mm);
      // North in the tile is negative south in the society's plan.
      expect(door.southMm).toBe(-onto.get(door.identity)!.threshold_y_mm);
    }
  });

  it('leave out a door onto a lot, a record with no threshold and any other kind, and read a halo copy once', () => {
    const entrance = (identity: string, fields: Record<string, unknown>) => ({ kind: 'city.entrance', identity, fields });
    const read = doorsOfRecords([
      entrance('street', { threshold_x_mm: 4_000, threshold_y_mm: 9_000, approach_curb_identity: ['kerb'] }),
      entrance('street', { threshold_x_mm: 4_000, threshold_y_mm: 9_000, approach_curb_identity: ['kerb'] }),
      entrance('lot', { threshold_x_mm: 1_000, threshold_y_mm: 2_000, approach_curb_identity: [] }),
      entrance('unplaced', { threshold_y_mm: 2_000, approach_curb_identity: ['kerb'] }),
      { kind: 'city.premises', identity: 'shop', fields: { threshold_x_mm: 1, threshold_y_mm: 1, approach_curb_identity: ['kerb'] } },
    ]);
    expect(read).toEqual([{ identity: 'street', eastMm: 4_000, southMm: -9_000 }]);
  });
});
