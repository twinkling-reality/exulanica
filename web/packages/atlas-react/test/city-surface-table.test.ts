import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { CONFORMANCE_FIXTURE, SURFACE_TABLE, conformanceRows } from './write-city-surface-table.js';

interface TableTile {
  readonly name: string;
  readonly document_sha256: string;
  readonly rows: readonly (readonly [number, number, number, string])[];
}

const table = JSON.parse(readFileSync(SURFACE_TABLE, 'utf8')) as { readonly profile: string; readonly tiles: readonly TableTile[] };

describe('the city surface table', () => {
  it('is the walk surface the page stands a person on over the conformance tile, as baked now', async () => {
    // tests/test_city_surface.py holds the city grammar's integer surface to these rows, so a change
    // to the tessellator or to how the page samples its envelope that moves one fails here first,
    // and the table is written again with write-city-surface-table.ts.
    const conformance = table.tiles.find((tile) => tile.name === 'conformance')!;
    expect(conformance.document_sha256).toBe(createHash('sha256').update(readFileSync(CONFORMANCE_FIXTURE)).digest('hex'));
    expect(await conformanceRows()).toEqual(conformance.rows);
  }, 60_000);

  it('samples kerbs, footways, carriageways and a junction on both tiles', () => {
    expect(table.profile).toBe('exulanica.city-surface-table/v1');
    expect(table.tiles.map((tile) => tile.name)).toEqual(['conformance', 'small_town']);
    for (const tile of table.tiles) {
      expect(new Set(tile.rows.map((row) => row[3]))).toEqual(new Set(['city.curb_edge', 'city.street_segment', 'city.junction']));
    }
  });
});
