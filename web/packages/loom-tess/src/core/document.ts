/**
 * THE TILE DOCUMENT, AND THE REFUSING VALIDATOR THAT READS IT.
 *
 * A tile document is what a bake reads: canonical JSON, integers and printable ASCII only, in the
 * grammar's own record vocabulary. The grammar owns the envelope,
 * `exulanica.grammar.grammars.city.document`, profile 2:
 *
 *     {
 *       "profile": "exulanica.tile-document/v2",
 *       "tile": <the city.tile record payload>,
 *       "grammars": [
 *         {
 *           "grammar_id": <key>, "grammar_version": <int>,
 *           "descriptor_sha256": <hex64 of the descriptor file's bytes>,
 *           "declared_semantics": {"subject_kind", "admissible_uses", "plane"},
 *           "subject_identity": <the admitted identity every record identity derives from>,
 *           "owned": [<record payload>, ...],
 *           "halo": [<record payload>, ...]
 *         }, ...
 *       ]
 *     }
 *
 * A record payload is exactly what `exulanica.grammar.records.record_payload` returns:
 * `{"kind", "version", "fields"}`, with nested records as plain objects of their fields. `grammars`
 * states exactly the pins `tile.grammar_versions` states, in the same order, so the digest that
 * keys the bake covers every grammar and every descriptor the records came from. `owned` and `halo`
 * are each sorted by kind, then version, then identity, each identity once, and no identity is in
 * both. A bake draws owned records only and reads halo records for context.
 *
 * THERE IS NO DEFAULT BRANCH. An unknown key is an error, a missing key is an error, an integer
 * out of its grammar bound is an error, an unknown record kind or grammar version is an error, and
 * a repeated identity is an error. Every field is checked against the grammar's table
 * (`record-shapes.ts`) by its kind. Nothing here fills a value in, and nothing here knows what any
 * value means: a key is checked for its spelling, never looked up.
 *
 * WHAT THIS DOES NOT CHECK, stated so nobody assumes it. Each is checked by the grammar's
 * `validate_city_document`, against the descriptor `descriptor_sha256` pins and the catalogs the
 * tile's `catalog_digest` pins:
 *   - the grammar's named rules (`record-shapes.ts` says why core cannot);
 *   - that a ring is simple and counter-clockwise, beyond holding enough integer pairs;
 *   - that a reference resolves, or that an identity is its rule's derivation;
 *   - that a key resolves in a catalog. Core carries no catalog, by design;
 *   - that the declared semantics are the ones the descriptor states;
 *   - that membership follows the tile's ownership and halo rules. Core reads the membership the
 *     document states, and draws owned records only.
 */
import { CanonicalJsonError, compareCodeUnits, parseCanonical } from './canonical-json.js';
import type { CanonicalValue } from './canonical-json.js';
import {
  HEX64_PATTERN,
  IDENTITY_PATTERN,
  KEY_PATTERN,
  nestedShapeOf,
  recordShapeOf,
  SEMANTICS_SHAPE,
  tableFor,
  TEXTURE_SET_ID_PATTERN,
  TILE_RECORD_KIND,
  TILE_SHAPE,
} from './record-shapes.js';
import type { FieldShape, GrammarTable, ProjectionName, RecordShape } from './record-shapes.js';
import { GRAMMAR_TABLES } from './record-shapes.js';

export const TILE_DOCUMENT_PROFILE = 'exulanica.tile-document/v2';

/** The two lists a grammar entry holds its records in. */
export const MEMBERSHIPS = ['owned', 'halo'] as const;
export type Membership = (typeof MEMBERSHIPS)[number];

export class TileDocumentError extends Error {}

export interface RecordPayload {
  readonly kind: string;
  readonly version: number;
  readonly fields: { readonly [name: string]: CanonicalValue };
}

export interface DeclaredSemantics {
  readonly subject_kind: string;
  readonly admissible_uses: readonly ProjectionName[];
  readonly plane: string;
}

export interface GrammarEntry {
  readonly grammar_id: string;
  readonly grammar_version: number;
  readonly descriptor_sha256: string;
  readonly declared_semantics: DeclaredSemantics;
  readonly subject_identity: string;
  readonly owned: readonly RecordPayload[];
  readonly halo: readonly RecordPayload[];
}

export interface TileDocument {
  readonly tile: RecordPayload;
  readonly grammars: readonly GrammarEntry[];
}

function fail(where: string, why: string): never {
  throw new TileDocumentError(`${where}: ${why}`);
}

type JsonObject = { readonly [key: string]: unknown };

function objectAt(value: unknown, where: string): JsonObject {
  if (typeof value !== 'object') fail(where, 'is not an object');
  if (value === null) fail(where, 'is not an object');
  if (Array.isArray(value)) fail(where, 'is not an object');
  return value as JsonObject;
}

function arrayAt(value: unknown, where: string): readonly unknown[] {
  if (!Array.isArray(value)) fail(where, 'is not an array');
  return value;
}

function exactKeys(value: JsonObject, expected: readonly string[], where: string): void {
  const present = Object.keys(value).sort(compareCodeUnits);
  const wanted = [...expected].sort(compareCodeUnits);
  const unknown = present.filter((key) => !wanted.includes(key));
  const missing = wanted.filter((key) => !present.includes(key));
  if (unknown.length > 0) fail(where, `unknown keys ${JSON.stringify(unknown)}`);
  if (missing.length > 0) fail(where, `missing keys ${JSON.stringify(missing)}`);
}

function integerAt(value: unknown, where: string, min?: number, max?: number): number {
  if (typeof value !== 'number') fail(where, 'is not an integer');
  if (!Number.isSafeInteger(value)) fail(where, 'is not a safe integer');
  if (min !== undefined) {
    if (value < min) fail(where, `is ${value}, below its minimum ${min}`);
  }
  if (max !== undefined) {
    if (value > max) fail(where, `is ${value}, above its maximum ${max}`);
  }
  return value;
}

function stringMatching(value: unknown, pattern: RegExp, what: string, where: string): string {
  if (typeof value !== 'string') fail(where, `is not ${what}`);
  if (!pattern.test(value)) fail(where, `is not ${what}: ${JSON.stringify(value)}`);
  return value;
}

/** `exulanica.grammar.records.require_text`: not empty, and no space at either end. */
function textAt(value: unknown, where: string): string {
  if (typeof value !== 'string') fail(where, 'is not text');
  if (value.length === 0) fail(where, 'is empty text');
  if (value.trim() !== value) fail(where, 'is text with surrounding space');
  return value;
}

function choiceAt(value: unknown, values: readonly string[], where: string): string {
  if (typeof value !== 'string') fail(where, `is not one of ${JSON.stringify(values)}`);
  if (!values.includes(value)) fail(where, `is not one of ${JSON.stringify(values)}`);
  return value;
}

function valuesOf(field: FieldShape, where: string): readonly string[] {
  if (field.values === undefined) fail(where, 'is a choice with no closed values in its table');
  return field.values;
}

function nestedOf(table: GrammarTable, field: FieldShape, where: string): RecordShape {
  if (field.shape === undefined) fail(where, 'is a record with no shape in its table');
  return nestedShapeOf(table, field.shape);
}

/** A point: `dimension` integers. */
function pointAt(value: unknown, dimension: number, where: string): readonly number[] {
  const point = arrayAt(value, where);
  if (point.length !== dimension) fail(where, `does not have ${dimension} coordinates`);
  point.forEach((coordinate, axis) => integerAt(coordinate, `${where}[${axis}]`));
  return point as readonly number[];
}

/** `exulanica.grammar.geometry.require_ring`'s least vertex count. */
const SMALLEST_RING = 3;

/** A ring: at least three plan points, `(x, y)`. Whether it is simple is the grammar's check. */
function ringAt(value: unknown, where: string, minimum: number, maximum?: number): void {
  const ring = arrayAt(value, where);
  if (ring.length < minimum) fail(where, `has fewer than ${minimum} vertices`);
  if (maximum !== undefined) {
    if (ring.length > maximum) fail(where, `has more than ${maximum} vertices`);
  }
  ring.forEach((point, index) => pointAt(point, 2, `${where}[${index}]`));
}

function scalarAt(value: unknown, where: string): void {
  if (typeof value === 'string') {
    stringMatching(value, KEY_PATTERN, 'a key', where);
    return;
  }
  integerAt(value, where);
}

function checkSequence(table: GrammarTable, field: FieldShape, value: unknown, where: string): void {
  const items = arrayAt(value, where);
  const least = field.count_minimum;
  if (least !== undefined) {
    if (items.length < least) fail(where, `holds fewer than ${least}`);
  }
  const most = field.count_maximum;
  if (most !== undefined) {
    if (items.length > most) fail(where, `holds more than ${most}`);
  }
  const texts: string[] = [];
  items.forEach((item, index) => {
    const at = `${where}[${index}]`;
    switch (field.kind) {
      case 'integers': {
        const current = integerAt(item, at, field.minimum, field.maximum);
        if (field.increasing !== undefined && index > 0) {
          if (current <= (items[index - 1] as number)) fail(where, 'is not strictly increasing');
        }
        return;
      }
      case 'keys':
        texts.push(stringMatching(item, KEY_PATTERN, 'a key', at));
        return;
      case 'choices':
        texts.push(choiceAt(item, valuesOf(field, where), at));
        return;
      case 'identities':
        texts.push(stringMatching(item, IDENTITY_PATTERN, 'a canonical lowercase UUID', at));
        return;
      case 'texts':
        texts.push(textAt(item, at));
        return;
      case 'points': {
        if (field.dimension === undefined) fail(where, 'is points with no dimension in its table');
        pointAt(item, field.dimension, at);
        if (index > 0) {
          if (JSON.stringify(item) === JSON.stringify(items[index - 1])) fail(where, `repeats point ${index - 1} at ${index}`);
        }
        return;
      }
      case 'rings':
        ringAt(item, at, SMALLEST_RING);
        return;
      case 'records':
        checkNested(table, nestedOf(table, field, where), item, at);
        return;
      case 'integer':
      case 'key':
      case 'choice':
      case 'text':
      case 'identity':
      case 'hex64':
      case 'seed':
      case 'texture_set_id':
      case 'scalar':
      case 'ring':
      case 'record':
        fail(where, `is a ${field.kind}, which is not a sequence`);
    }
  });
  if (new Set(texts).size !== texts.length) fail(where, 'repeats an item');
  if (field.kind === 'choices') {
    const values = valuesOf(field, where);
    const order = texts.map((item) => values.indexOf(item));
    order.forEach((position, index) => {
      if (index > 0) {
        if (position < order[index - 1]!) fail(where, `does not list its values in the order ${JSON.stringify(values)}`);
      }
    });
  }
}

function checkField(table: GrammarTable, field: FieldShape, value: unknown, where: string): void {
  switch (field.kind) {
    case 'integer':
      integerAt(value, where, field.minimum, field.maximum);
      return;
    case 'key':
      stringMatching(value, KEY_PATTERN, 'a lowercase key', where);
      return;
    case 'choice':
      choiceAt(value, valuesOf(field, where), where);
      return;
    case 'text':
      textAt(value, where);
      return;
    case 'identity':
      stringMatching(value, IDENTITY_PATTERN, 'a canonical lowercase UUID', where);
      return;
    case 'hex64':
      stringMatching(value, HEX64_PATTERN, '64 lowercase hexadecimal characters', where);
      return;
    case 'seed':
      stringMatching(value, HEX64_PATTERN, 'a seed of 64 lowercase hexadecimal characters', where);
      return;
    case 'texture_set_id':
      stringMatching(value, TEXTURE_SET_ID_PATTERN, 'a texture set id', where);
      return;
    case 'scalar':
      scalarAt(value, where);
      return;
    case 'ring': {
      const least = field.count_minimum;
      ringAt(value, where, least !== undefined && least > SMALLEST_RING ? least : SMALLEST_RING, field.count_maximum);
      return;
    }
    case 'record':
      checkNested(table, nestedOf(table, field, where), value, where);
      return;
    case 'integers':
    case 'keys':
    case 'choices':
    case 'identities':
    case 'texts':
    case 'points':
    case 'rings':
    case 'records':
      checkSequence(table, field, value, where);
  }
}

function checkFields(table: GrammarTable, shape: RecordShape, value: unknown, where: string): JsonObject {
  const fields = objectAt(value, where);
  exactKeys(fields, shape.fields.map((field) => field.name), where);
  for (const field of shape.fields) checkField(table, field, fields[field.name], `${where}.${field.name}`);
  return fields;
}

/** A nested record: a plain object of exactly its shape's fields. */
function checkNested(table: GrammarTable, shape: RecordShape, value: unknown, where: string): void {
  checkFields(table, shape, value, where);
}

/** The shape a record payload of `kind` is read against in `table`, or a refusal naming the kinds. */
export function shapeOf(table: GrammarTable, kind: string, where: string): RecordShape {
  const shape = recordShapeOf(table, kind);
  if (shape === undefined) {
    const kinds = table.shapes.records.map((candidate) => candidate.kind);
    fail(where, `record kind ${JSON.stringify(kind)} is not one of ${JSON.stringify(kinds)}`);
  }
  return shape;
}

/** One record payload, validated against its kind's shape in `table`, or against `expected`. */
export function validateRecord(
  table: GrammarTable,
  value: unknown,
  where: string,
  expected?: RecordShape,
): RecordPayload {
  const record = objectAt(value, where);
  exactKeys(record, ['fields', 'kind', 'version'], where);
  if (typeof record.kind !== 'string') fail(`${where}.kind`, 'is not a string');
  const shape = expected === undefined ? shapeOf(table, record.kind, `${where}.kind`) : expected;
  if (record.kind !== shape.kind) fail(`${where}.kind`, `is not ${JSON.stringify(shape.kind)}`);
  integerAt(record.version, `${where}.version`, shape.version, shape.version);
  checkFields(table, shape, record.fields, `${where}.fields`);
  return record as unknown as RecordPayload;
}

/** A grammar entry's declared semantics. */
export function validateSemantics(table: GrammarTable, value: unknown, where: string): DeclaredSemantics {
  checkNested(table, SEMANTICS_SHAPE, value, where);
  return value as DeclaredSemantics;
}

/** The identity a record states, read from the field its shape names, or undefined for none. */
export function statedIdentity(table: GrammarTable, payload: RecordPayload): string | undefined {
  const rule = shapeOf(table, payload.kind, 'record').identity;
  if (rule === undefined) return undefined;
  return payload.fields[rule.field] as string;
}

function readList(table: GrammarTable, value: unknown, where: string): RecordPayload[] {
  const records = arrayAt(value, where).map((item, index) => {
    const at = `${where}[${index}]`;
    const payload = validateRecord(table, item, at);
    if (payload.kind === TILE_RECORD_KIND) fail(at, 'is a tile record, which heads the document instead');
    if (statedIdentity(table, payload) === undefined) fail(at, `is a ${payload.kind}, which states no identity`);
    return payload;
  });
  records.forEach((record, index) => {
    if (index > 0) {
      const before = records[index - 1]!;
      const byKind = compareCodeUnits(before.kind, record.kind);
      const byVersion = before.version - record.version;
      const byIdentity = compareCodeUnits(statedIdentity(table, before)!, statedIdentity(table, record)!);
      const order = byKind !== 0 ? byKind : byVersion !== 0 ? byVersion : byIdentity;
      if (order >= 0) fail(`${where}[${index}]`, 'is not after the record before it by kind, version and identity, each once');
    }
  });
  return records;
}

/**
 * Read and validate a tile document from its canonical bytes. Returns the document unchanged in
 * shape, or throws `TileDocumentError` or `CanonicalJsonError` naming the first problem.
 */
export function readTileDocument(bytes: Uint8Array): TileDocument {
  const parsed = parseCanonical(bytes, 'tile document');
  const document = objectAt(parsed, 'tile document');
  exactKeys(document, ['grammars', 'profile', 'tile'], 'tile document');
  if (document.profile !== TILE_DOCUMENT_PROFILE) {
    fail('tile document.profile', `is not ${JSON.stringify(TILE_DOCUMENT_PROFILE)}`);
  }
  const tileTable = GRAMMAR_TABLES[0]!;
  const tile = validateRecord(tileTable, document.tile, 'tile', TILE_SHAPE);
  const pins = tile.fields.grammar_versions as readonly JsonObject[];
  const grammarsIn = arrayAt(document.grammars, 'grammars');
  if (grammarsIn.length !== pins.length) {
    fail('grammars', 'does not state exactly the pins tile.grammar_versions states');
  }
  const identities = new Set<string>();
  const grammars = grammarsIn.map((value, index): GrammarEntry => {
    const where = `grammars[${index}]`;
    const entry = objectAt(value, where);
    exactKeys(
      entry,
      ['declared_semantics', 'descriptor_sha256', 'grammar_id', 'grammar_version', 'halo', 'owned', 'subject_identity'],
      where,
    );
    const pin = pins[index]!;
    for (const key of ['grammar_id', 'grammar_version', 'descriptor_sha256']) {
      if (entry[key] !== pin[key]) fail(`${where}.${key}`, `is not the tile's pin, ${JSON.stringify(pin[key])}`);
    }
    const table = tableFor(entry.grammar_id, entry.grammar_version);
    if (table === undefined) {
      const known = GRAMMAR_TABLES.map((candidate) => `${candidate.grammar_id} ${candidate.grammar_version}`);
      fail(where, `this tessellator reads ${JSON.stringify(known)} only`);
    }
    const semantics = validateSemantics(table, entry.declared_semantics, `${where}.declared_semantics`);
    const subject = stringMatching(entry.subject_identity, IDENTITY_PATTERN, 'a canonical lowercase UUID', `${where}.subject_identity`);
    const owned = readList(table, entry.owned, `${where}.owned`);
    const halo = readList(table, entry.halo, `${where}.halo`);
    for (const record of [...owned, ...halo]) {
      const identity = statedIdentity(table, record)!;
      if (identities.has(identity)) fail(where, `identity ${identity} is stated by two records`);
      identities.add(identity);
    }
    return {
      grammar_id: table.grammar_id,
      grammar_version: table.grammar_version,
      descriptor_sha256: pin.descriptor_sha256 as string,
      declared_semantics: semantics,
      subject_identity: subject,
      owned,
      halo,
    };
  });
  return { tile, grammars };
}

/** The table a document's grammar entry was read against. */
export function tableOf(grammar: Pick<GrammarEntry, 'grammar_id' | 'grammar_version'>): GrammarTable {
  const table = tableFor(grammar.grammar_id, grammar.grammar_version);
  if (table === undefined) fail('grammar', `${grammar.grammar_id} ${grammar.grammar_version} has no table`);
  return table;
}

export { CanonicalJsonError };
