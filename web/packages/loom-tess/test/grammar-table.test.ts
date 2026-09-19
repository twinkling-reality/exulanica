/**
 * The grammar table core reads is the grammar's own, not a transcription: the generated module
 * equals what the grammar's files state, and `tests/test_bake_determinism.py` holds it to
 * `describe_shapes` itself. Regenerate with `pnpm exec tsx packages/loom-tess/test/write-grammar-table.ts`.
 *
 * AND EVERY READER THAT TAKES ONE ANSWER OUT OF THE WHOLE LIST is held here to address a table by
 * what it carries rather than by where it sits. Asserting the list's contents, which the first
 * test does, says nothing about them: it fires when a second table arrives and the obvious way to
 * quiet it leaves every reader of the list exactly as wrong as it was. So each of those readers is
 * given a list of two below, built from `CITY_V2` itself so the second table is the real thing
 * with one field moved rather than this test's reading of what a table looks like, and the
 * property asserted is the one an index cannot satisfy: THE ANSWER DOES NOT CHANGE WHEN THE LIST
 * IS REVERSED.
 */
import { describe, expect, it } from 'vitest';
import { BAKE_PARAMETERS, boundOf, recordShapeVersions } from '../src/core/bake.js';
import { CITY_V2 } from '../src/core/city-v2.js';
import { TileDocumentError, tileTableOf } from '../src/core/document.js';
import { baseRingOf, TessellationError } from '../src/core/expand.js';
import {
  agreedAcrossTables,
  GRAMMAR_TABLES,
  navigationRowOf,
  PLANE,
  PROJECTIONS,
  ShapeTableError,
  TILE_GRAMMAR_ID,
  TILE_RECORD_KIND,
  tileShapeOf,
} from '../src/core/record-shapes.js';
import type { GrammarTable } from '../src/core/record-shapes.js';
import { fixtureObject, recordsOf } from './support.js';
import { grammarTableFromSources } from './grammar-table-sources.js';

/** `CITY_V2` at another grammar version, optionally with one change to its tile record shape. */
function cityAt(version: number, changeTileShape?: (shape: any) => void): GrammarTable {
  const table = JSON.parse(JSON.stringify(CITY_V2));
  table.grammar_version = version;
  if (changeTileShape !== undefined) {
    changeTileShape(table.shapes.records.find((shape: any) => shape.kind === TILE_RECORD_KIND));
  }
  return table as GrammarTable;
}

const NEXT_VERSION = CITY_V2.grammar_version + 1;
const CITY_NEXT = cityAt(NEXT_VERSION);
const TWO_TABLES: readonly GrammarTable[] = [CITY_V2, CITY_NEXT];

/** The fixture's tile record, and the pin in it that states which version that record is written in. */
function tileRecordPinned(version: number): any {
  const tile = fixtureObject().tile;
  const pins = tile.fields.grammar_versions.filter((pin: any) => pin.grammar_id === TILE_GRAMMAR_ID);
  expect(pins, 'the fixture states one pin for the tile record own grammar').toHaveLength(1);
  pins[0].grammar_version = version;
  return tile;
}

describe('the grammar table', () => {
  it('is exactly the city grammar version 2 shape table and descriptor frame', () => {
    expect(JSON.parse(JSON.stringify(CITY_V2))).toEqual(grammarTableFromSources());
    // This one fires on a second table and cannot say whether its readers are ready for it. The
    // tests below are what say that, and this line is here for the generated table alone.
    expect(GRAMMAR_TABLES).toEqual([CITY_V2]);
  });

  it('gives the projections, the plane and the tile shape from the table itself', () => {
    expect(PROJECTIONS).toEqual(['render_batch', 'collision_proxy', 'nav_envelope', 'pick_geometry', 'export_gltf']);
    expect(PLANE).toBe('invented');
    expect(tileShapeOf(CITY_V2).kind).toBe('city.tile');
    expect(tileShapeOf(CITY_V2).version).toBe(2);
    expect(TILE_GRAMMAR_ID).toBe('city');
  });

  it('states what every record kind is to a person walking, and tess reads the base ring of every kind that covers one', () => {
    for (const shape of CITY_V2.shapes.records) {
      expect(navigationRowOf(CITY_V2, shape.kind!).kind).toBe(shape.kind);
    }
    expect(() => navigationRowOf(CITY_V2, 'city.nothing')).toThrow(ShapeTableError);
    const covers = CITY_V2.navigation.filter((row) => row.ground === 'cover');
    expect(covers.map((row) => [row.kind, row.cover])).toEqual([['city.massing', 'base_ring']]);
    // A building stands on its lowest tier's ring, which the grammar reads as its footprint.
    const building = recordsOf(fixtureObject(), 'city.massing')[0].fields;
    expect(baseRingOf('city.massing', building)).toEqual(building.tiers[0].ring_mm);
    expect(() => baseRingOf('city.parcel', {})).toThrow(TessellationError);
  });
});

describe('the table a tile record is read against', () => {
  it('is the one its own pin names, and reversing the list does not change it', () => {
    const reversed = [...TWO_TABLES].reverse();
    expect(tileTableOf(TWO_TABLES, tileRecordPinned(CITY_V2.grammar_version), 'tile')).toBe(CITY_V2);
    expect(tileTableOf(reversed, tileRecordPinned(CITY_V2.grammar_version), 'tile')).toBe(CITY_V2);
    expect(tileTableOf(TWO_TABLES, tileRecordPinned(NEXT_VERSION), 'tile')).toBe(CITY_NEXT);
    expect(tileTableOf(reversed, tileRecordPinned(NEXT_VERSION), 'tile')).toBe(CITY_NEXT);
  });

  it('is refused when no table states the version, rather than being some other version shape', () => {
    const unread = NEXT_VERSION + 1;
    expect(() => tileTableOf(TWO_TABLES, tileRecordPinned(unread), 'tile')).toThrow(
      new RegExp(`pins city version ${unread}, and this tessellator reads \\[2,${NEXT_VERSION}\\]`),
    );
    expect(() => tileTableOf(TWO_TABLES, tileRecordPinned(unread), 'tile')).toThrow(TileDocumentError);
  });

  it('is refused when the record names no pin for the grammar whose tile record it is', () => {
    const tile = fixtureObject().tile;
    tile.fields.grammar_versions = tile.fields.grammar_versions.filter(
      (pin: any) => pin.grammar_id !== TILE_GRAMMAR_ID,
    );
    expect(() => tileTableOf(TWO_TABLES, tile, 'tile')).toThrow(/names no pin for "city"/);
  });

  it('is refused when the record names two pins for it, rather than taking the first', () => {
    const tile = tileRecordPinned(CITY_V2.grammar_version);
    const pin = tile.fields.grammar_versions.find((candidate: any) => candidate.grammar_id === TILE_GRAMMAR_ID);
    tile.fields.grammar_versions.push({ ...pin, grammar_version: NEXT_VERSION });
    expect(() => tileTableOf(TWO_TABLES, tile, 'tile')).toThrow(/names 2 pins for "city"/);
  });
});

describe('a value stated once for every table', () => {
  it('is the agreed one, and a disagreement is refused rather than resolved by order', () => {
    expect(agreedAcrossTables(TWO_TABLES, (table) => [table.grammar_id], 'grammar ids')).toEqual(['city']);
    expect(() => agreedAcrossTables(TWO_TABLES, (table) => [`${table.grammar_version}`], 'versions')).toThrow(
      /state different versions/,
    );
    expect(() => agreedAcrossTables([], (table) => [table.grammar_id], 'grammar ids')).toThrow(/reads no grammar/);
  });

  it('is the tile record fixed bound every version states, and a disagreement is refused', () => {
    expect(boundOf(TWO_TABLES, 'tile_size_mm')).toBe(BAKE_PARAMETERS.tile_size_mm);
    const halved = cityAt(NEXT_VERSION, (shape) => {
      const field = shape.fields.find((candidate: any) => candidate.name === 'tile_size_mm');
      field.minimum = field.minimum / 2;
      field.maximum = field.minimum;
    });
    expect(() => boundOf([CITY_V2, halved], 'tile_size_mm')).toThrow(/fix tile_size_mm at \[128000,64000\]/);
  });

  it('is one version a record kind, and a kind read at two is refused rather than overwritten', () => {
    expect(recordShapeVersions(TWO_TABLES)).toEqual(BAKE_PARAMETERS.record_shapes);
    const bumped = cityAt(NEXT_VERSION, (shape) => {
      shape.version = shape.version + 1;
    });
    expect(() => recordShapeVersions([CITY_V2, bumped])).toThrow(/city\.tile is read at versions 2 and 3/);
    // And the order does not decide which of the two would have won.
    expect(() => recordShapeVersions([bumped, CITY_V2])).toThrow(/city\.tile is read at versions 3 and 2/);
  });
});
