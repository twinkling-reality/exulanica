import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { STREET_FURNITURE_KIND, streetFurnitureOf } from '../src/playcanvas/generated-tile/street-furniture.js';

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
