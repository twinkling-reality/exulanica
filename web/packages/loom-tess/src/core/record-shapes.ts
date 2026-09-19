/**
 * THE RECORD SHAPES THIS TESSELLATOR READS: THE GRAMMAR'S OWN TABLE, NOT A TRANSCRIPTION OF IT.
 *
 * A grammar describes every record kind as data (`exulanica.grammar.shapes.describe_shapes`): each
 * field with its kind, bounds, counts and closed values, each named rule, how the record's own
 * identity is derived and which field states its extent. `city-v2.ts` is that table, generated
 * from the grammar's files and held equal to them by test. This module types it and looks things
 * up in it; `document.ts` interprets it field by field. Nothing here is chosen by this package.
 *
 * WHAT A TABLE DOES NOT CARRY, stated so nobody assumes it. A named rule (`rules`) is a Python
 * check across fields or records, and a table names it without saying what it checks. Core does
 * not check named rules. The grammar's document validator does, and an expander that depends on
 * one of them checks the fact it depends on itself, refusing rather than drawing.
 *
 * A tile names grammars by id and version, and core reads only the versions it has a table for.
 * Adding a grammar version is a new generated table, a rule per record kind in `expand.ts`, and a
 * bump of `TESSELLATOR_SOURCE_VERSION`, which the bake stage's parameters carry.
 *
 * AND EVERY READER THAT TAKES ONE ANSWER OUT OF THE WHOLE LIST, which the paragraph above left
 * out for as long as the list had one member. A list of one makes every reader of it look right.
 * Two readers took the tile record's shape from `GRAMMAR_TABLES[0]`, so a second version would
 * have been read against whichever table sat first whatever version the document pinned, and
 * every bound value would have agreed; they now take it from the pin the tile record itself
 * states (`document.tileTableOf`). The others are written down here rather than left to be found
 * again: a shape a table declares is reached through that table (`tileShapeOf`,
 * `semanticsShapeOf`), and a value belonging to the contract rather than to a version is held
 * equal across every table before it is stated once (`PROJECTIONS`, `PLANE`, and in `bake.ts` the
 * tile record's fixed bounds and every record kind's version).
 */
import { CITY_V2 } from './city-v2.js';
import { CITY_V3 } from './city-v3.js';
import { FIELD_KINDS } from './grammar-table.js';
import type { FieldShape, GrammarTable, NavigationRow, RecordShape } from './grammar-table.js';

export { FIELD_KINDS } from './grammar-table.js';
export type { FieldKind, FieldShape, GrammarFrame, GrammarTable, IdentityRule, NavigationRow, RecordShape } from './grammar-table.js';

/** Integers a JavaScript reader holds exactly. `exulanica.grammar.records.MAX_SAFE_INTEGER`. */
export const MAX_SAFE_INTEGER = Number.MAX_SAFE_INTEGER;

/** `exulanica.grammar.records.KEY_PATTERN`. */
export const KEY_PATTERN = /^[a-z][a-z0-9_]*$/;
/** `exulanica.grammar.records._IDENTITY`: a canonical lowercase UUID string. */
export const IDENTITY_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
/** `exulanica.grammar.records._HEX64` and `exulanica.grammar.seed._SEED`. */
export const HEX64_PATTERN = /^[0-9a-f]{64}$/;
/** `exulanica.grammar.textures.TEXTURE_SET_ID`. */
export const TEXTURE_SET_ID_PATTERN = /^[a-z][a-z0-9.-]*$/;

/**
 * Every grammar version this tessellator reads, oldest first.
 *
 * A DOCUMENT IS READ AGAINST THE VERSION IT PINS, never against this list's first entry: city
 * version 2 wrote no coordinate unit and version 3 states one (ADR-0024), so the two tile shapes
 * differ and a reader that took either for the other would report a field as the fault when the
 * fault is a version. `document.tileTableOf` is what resolves it, and the order here decides
 * nothing.
 */
export const GRAMMAR_TABLES: readonly GrammarTable[] = [CITY_V2, CITY_V3];

export class ShapeTableError extends Error {}

/** The table for one grammar version, or undefined when this tessellator reads no such version. */
export function tableFor(grammarId: unknown, grammarVersion: unknown): GrammarTable | undefined {
  return GRAMMAR_TABLES.find(
    (table) => table.grammar_id === grammarId && table.grammar_version === grammarVersion,
  );
}

/** A top-level record kind of `table`, or undefined. */
export function recordShapeOf(table: GrammarTable, kind: string): RecordShape | undefined {
  return table.shapes.records.find((shape) => shape.kind === kind);
}

/**
 * What `table`'s navigation table says a record kind is to a person walking. A kind it leaves out is
 * refused: the table is to state every kind.
 */
export function navigationRowOf(table: GrammarTable, kind: string): NavigationRow {
  const row = table.navigation.find((candidate) => candidate.kind === kind);
  if (row === undefined) throw new ShapeTableError(`the ${table.grammar_id} navigation table states nothing for ${kind}`);
  return row;
}

/** A nested shape of `table` by name. A table that names a shape it does not hold is refused. */
export function nestedShapeOf(table: GrammarTable, name: string): RecordShape {
  const shape = table.shapes.nested.find((candidate) => candidate.shape === name);
  if (shape === undefined) throw new ShapeTableError(`the ${table.grammar_id} table names no shape ${name}`);
  return shape;
}

function requireRecordShape(table: GrammarTable, kind: string): RecordShape {
  const shape = recordShapeOf(table, kind);
  if (shape === undefined) throw new ShapeTableError(`the ${table.grammar_id} table has no ${kind}`);
  return shape;
}

function requireField(shape: RecordShape, name: string): FieldShape {
  const field = shape.fields.find((candidate) => candidate.name === name);
  if (field === undefined) throw new ShapeTableError(`${shape.shape} has no field ${name}`);
  return field;
}

function valuesOf(field: FieldShape): readonly string[] {
  if (field.values === undefined) throw new ShapeTableError(`${field.name} has no closed values`);
  return field.values;
}

/** The record kind that heads a tile document. */
export const TILE_RECORD_KIND = 'city.tile';
/** The record kind a drawn range's material reference must name. */
export const MATERIAL_RECORD_KIND = 'city.surface_material';

/** `table`'s tile record shape, which a tile document written in that version is read against. */
export function tileShapeOf(table: GrammarTable): RecordShape {
  return requireRecordShape(table, TILE_RECORD_KIND);
}

/** The shape a grammar entry's declared semantics are read against, in that entry's own table. */
export function semanticsShapeOf(table: GrammarTable): RecordShape {
  return nestedShapeOf(table, 'DeclaredSemantics');
}

/**
 * The grammar whose table declares the tile record kind, read from the tables rather than taken
 * from the kind's spelling. It is what says WHICH pin of a tile record states that record's own
 * version, so a tessellator whose tables disagreed about it could not read a tile document at all
 * and is refused here instead of at the first document.
 */
export const TILE_GRAMMAR_ID: string = (() => {
  const ids: string[] = [];
  for (const table of GRAMMAR_TABLES) {
    if (recordShapeOf(table, TILE_RECORD_KIND) === undefined) continue;
    if (!ids.includes(table.grammar_id)) ids.push(table.grammar_id);
  }
  if (ids.length !== 1) throw new ShapeTableError(`${TILE_RECORD_KIND} is declared by ${JSON.stringify(ids)}, and a tile document heads with one grammar's tile record`);
  return ids[0]!;
})();

/**
 * The one list every table this tessellator reads states, refused when they differ.
 *
 * ADMISSIBLE USES AND THE PLANE BELONG TO THE CONTRACT rather than to a grammar version
 * (`exulanica.grammar.contract`), so stating them once is a fact about every table. It is written
 * as a check because it was a single table's answer for as long as there was a single table, and
 * nothing would have said so on the day a second one stated something else.
 */
export function agreedAcrossTables(
  tables: readonly GrammarTable[],
  read: (table: GrammarTable) => readonly string[],
  what: string,
): readonly string[] {
  const stated = tables.map(read);
  if (stated.length === 0) throw new ShapeTableError(`this tessellator reads no grammar, so it states no ${what}`);
  // Any of them, once they are known to be the same list. This is not an index into a list whose
  // order means something; it is the agreed value, and the loop above is what earns it.
  const agreed = stated[0]!;
  for (const value of stated) {
    if (value.length !== agreed.length) throw new ShapeTableError(`the grammars this tessellator reads state different ${what}`);
    if (value.some((item, index) => item !== agreed[index])) throw new ShapeTableError(`the grammars this tessellator reads state different ${what}`);
  }
  return agreed;
}

/**
 * `exulanica.grammar.contract.ADMISSIBLE_USES`, in the grammar's order, read from the declared
 * semantics shape. These are the named projections of the target architecture; a grammar's
 * declared semantics list the ones its output is admitted to, and this tessellator emits a
 * projection for a record only when they do.
 */
export const PROJECTIONS: readonly string[] = agreedAcrossTables(
  GRAMMAR_TABLES,
  (table) => valuesOf(requireField(semanticsShapeOf(table), 'admissible_uses')),
  'admissible uses',
);
export type ProjectionName = string;

/** `exulanica.grammar.contract.PLANE`, the one plane a grammar may declare. */
export const PLANE: string = agreedAcrossTables(
  GRAMMAR_TABLES,
  (table) => valuesOf(requireField(semanticsShapeOf(table), 'plane')),
  'planes',
)[0]!;

// Held at load: a table whose references do not resolve cannot be read at all.
for (const table of GRAMMAR_TABLES) {
  for (const shape of [...table.shapes.records, ...table.shapes.nested]) {
    for (const field of shape.fields) {
      if (!FIELD_KINDS.includes(field.kind)) throw new ShapeTableError(`${shape.shape}.${field.name} has an unknown kind`);
      if (field.shape !== undefined) nestedShapeOf(table, field.shape);
    }
    if (shape.identity !== undefined) requireField(shape, shape.identity.field);
    if (shape.extent_field !== undefined) requireField(shape, shape.extent_field);
  }
  requireRecordShape(table, MATERIAL_RECORD_KIND);
}
