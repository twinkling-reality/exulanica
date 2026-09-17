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
 */
import { CITY_V2 } from './city-v2.js';
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

/** Every grammar version this tessellator reads. */
export const GRAMMAR_TABLES: readonly GrammarTable[] = [CITY_V2];

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

/** The tile record's shape, which every tile document is read against first. */
export const TILE_SHAPE: RecordShape = requireRecordShape(CITY_V2, TILE_RECORD_KIND);

/** The shape a grammar entry's declared semantics are read against. */
export const SEMANTICS_SHAPE: RecordShape = nestedShapeOf(CITY_V2, 'DeclaredSemantics');

/**
 * `exulanica.grammar.contract.ADMISSIBLE_USES`, in the grammar's order, read from the declared
 * semantics shape. These are the named projections of the target architecture; a grammar's
 * declared semantics list the ones its output is admitted to, and this tessellator emits a
 * projection for a record only when they do.
 */
export const PROJECTIONS: readonly string[] = valuesOf(requireField(SEMANTICS_SHAPE, 'admissible_uses'));
export type ProjectionName = string;

/** `exulanica.grammar.contract.PLANE`, the one plane a grammar may declare. */
export const PLANE: string = valuesOf(requireField(SEMANTICS_SHAPE, 'plane'))[0]!;

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
