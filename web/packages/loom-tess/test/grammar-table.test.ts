/**
 * The grammar table core reads is the grammar's own, not a transcription: the generated module
 * equals what the grammar's files state, and `tests/test_bake_determinism.py` holds it to
 * `describe_shapes` itself. Regenerate with `pnpm exec tsx packages/loom-tess/test/write-grammar-table.ts`.
 *
 * AND EVERY READER THAT TAKES ONE ANSWER OUT OF THE WHOLE LIST is held here to address a table by
 * what it carries rather than by where it sits. Asserting the list's contents, which the first
 * test does, says nothing about them: it fires when a second table arrives and the obvious way to
 * quiet it leaves every reader of the list exactly as wrong as it was. So each of those readers is
 * given the two REAL tables below, which since ADR-0024 differ in their tile record shape and not
 * only in a version number, and the property asserted is the one an index cannot satisfy: THE
 * ANSWER DOES NOT CHANGE WHEN THE LIST IS REVERSED. Where a case needs a version this tessellator
 * does NOT read, the table for it is derived from `CITY_V3` rather than typed, so it is the real
 * thing with one field moved and not this test's idea of what a table looks like.
 */
import { describe, expect, it } from 'vitest';
import { BAKE_PARAMETERS, boundOf, recordShapeVersions } from '../src/core/bake.js';
import { CITY_V2 } from '../src/core/city-v2.js';
import { CITY_V3 } from '../src/core/city-v3.js';
import {
  coordinateUnitOf,
  declaresCoordinateUnit,
  TileDocumentError,
  tileTableOf,
  UNIT_FIXED_BY_VERSION,
} from '../src/core/document.js';
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

/** `CITY_V3` at another grammar version, optionally with one change to its tile record shape. */
function cityAt(version: number, changeTileShape?: (shape: any) => void): GrammarTable {
  const table = JSON.parse(JSON.stringify(CITY_V3));
  table.grammar_version = version;
  if (changeTileShape !== undefined) {
    changeTileShape(table.shapes.records.find((shape: any) => shape.kind === TILE_RECORD_KIND));
  }
  return table as GrammarTable;
}

/** A version past the newest, for the cases about a version this tessellator does not read. */
const NEXT_VERSION = CITY_V3.grammar_version + 1;
/** The two REAL tables, which differ in their tile shape and not only in a version number. */
const TWO_TABLES: readonly GrammarTable[] = GRAMMAR_TABLES;

/** The fixture's tile record, and the pin in it that states which version that record is written in. */
function tileRecordPinned(version: number): any {
  const tile = fixtureObject().tile;
  const pins = tile.fields.grammar_versions.filter((pin: any) => pin.grammar_id === TILE_GRAMMAR_ID);
  expect(pins, 'the fixture states one pin for the tile record own grammar').toHaveLength(1);
  pins[0].grammar_version = version;
  return tile;
}

describe('the grammar table', () => {
  it('is exactly each city grammar version\u2019s own shape table and descriptor frame', () => {
    expect(JSON.parse(JSON.stringify(CITY_V2))).toEqual(grammarTableFromSources(2));
    expect(JSON.parse(JSON.stringify(CITY_V3))).toEqual(grammarTableFromSources(3));
    // The list's CONTENTS, which says nothing about whether its readers address a table by what it
    // carries. The tests below are what say that.
    expect(GRAMMAR_TABLES).toEqual([CITY_V2, CITY_V3]);
    expect(GRAMMAR_TABLES.map((table) => table.grammar_version)).toEqual([2, 3]);
  });

  it('gives the projections, the plane and each version\u2019s own tile shape from the table itself', () => {
    expect(PROJECTIONS).toEqual(['render_batch', 'collision_proxy', 'nav_envelope', 'pick_geometry', 'export_gltf']);
    expect(PLANE).toBe('invented');
    expect(TILE_GRAMMAR_ID).toBe('city');
    for (const table of GRAMMAR_TABLES) expect(tileShapeOf(table).kind).toBe('city.tile');
    // The two shapes are NOT the same, which is what makes reading one for the other a real error.
    expect(tileShapeOf(CITY_V2).version).toBe(2);
    expect(tileShapeOf(CITY_V3).version).toBe(3);
    const names = (table: GrammarTable): string[] => tileShapeOf(table).fields.map((field) => field.name);
    expect(names(CITY_V3).filter((name) => !names(CITY_V2).includes(name))).toEqual(['coordinate_unit']);
    expect(names(CITY_V2).filter((name) => !names(CITY_V3).includes(name))).toEqual([]);
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
    expect(tileTableOf(TWO_TABLES, tileRecordPinned(CITY_V3.grammar_version), 'tile')).toBe(CITY_V3);
    expect(tileTableOf(reversed, tileRecordPinned(CITY_V3.grammar_version), 'tile')).toBe(CITY_V3);
  });

  it('is refused when no table states the version, rather than being some other version shape', () => {
    const unread = NEXT_VERSION + 1;
    expect(() => tileTableOf(TWO_TABLES, tileRecordPinned(unread), 'tile')).toThrow(
      new RegExp(`pins city version ${unread}, and this tessellator reads \\[2,3\\]`),
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

describe('the coordinate unit a document is read in (ADR-0024)', () => {
  it('comes from the field at the version that declares it, and from the version before that', () => {
    expect(declaresCoordinateUnit(CITY_V3)).toBe(true);
    expect(declaresCoordinateUnit(CITY_V2)).toBe(false);
    // Version 3 reads its own field. Not a constant this reader holds: change the document and the
    // answer changes with it, which is what makes it a reading rather than an assumption.
    const stated = (unit: string): string =>
      coordinateUnitOf(CITY_V3, { kind: 'city.tile', version: 3, fields: { coordinate_unit: unit } } as any);
    expect(stated('millimetre')).toBe('millimetre');
    expect(stated('micrometre')).toBe('micrometre');
    // Version 2 carries no field, and millimetre is what THAT VERSION fixes, not what a reader
    // supplied on finding nothing: the record it is given states no unit at all.
    expect(coordinateUnitOf(CITY_V2, { kind: 'city.tile', version: 2, fields: {} } as any)).toBe('millimetre');
  });

  it('is refused for a version that neither states one nor has one fixed', () => {
    const unknown = cityAt(NEXT_VERSION, (shape) => {
      shape.fields = shape.fields.filter((field: any) => field.name !== 'coordinate_unit');
    });
    expect(declaresCoordinateUnit(unknown)).toBe(false);
    expect(() => coordinateUnitOf(unknown, { kind: 'city.tile', version: 4, fields: {} } as any)).toThrow(
      /states no coordinate_unit and fixes none/,
    );
  });

  it('is fixed for every version this tessellator reads that states none', () => {
    // The load-time guard in document.ts holds this, so the module would not have imported at all
    // if it were false. Asserted here so a reader can see what that guard is about.
    for (const table of GRAMMAR_TABLES) {
      const fixed = UNIT_FIXED_BY_VERSION.some(
        (entry) => entry.grammar_id === table.grammar_id && entry.grammar_version === table.grammar_version,
      );
      expect(declaresCoordinateUnit(table) || fixed, `city v${table.grammar_version}`).toBe(true);
    }
    expect(UNIT_FIXED_BY_VERSION).toEqual([{ grammar_id: 'city', grammar_version: 2, unit: 'millimetre' }]);
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

  it('states every version a record kind is read at, ascending, whatever order the tables are in', () => {
    const versions = recordShapeVersions(TWO_TABLES);
    expect(versions).toEqual(BAKE_PARAMETERS.record_shapes);
    // The one kind the two versions differ on is the one this whole change is about, and the
    // parameter has to be able to SAY that rather than take whichever table came last.
    expect(versions['city.tile']).toEqual([2, 3]);
    expect(versions['city.massing']).toEqual([2]);
    expect(recordShapeVersions([...TWO_TABLES].reverse())).toEqual(versions);
    // One table alone still states a list, so the shape of this parameter does not depend on how
    // many versions happen to be read.
    expect(recordShapeVersions([CITY_V2])['city.tile']).toEqual([2]);
  });
});
