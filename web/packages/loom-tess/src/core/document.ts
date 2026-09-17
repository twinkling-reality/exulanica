/**
 * THE TILE DOCUMENT, AND THE REFUSING VALIDATOR THAT READS IT.
 *
 * A tile document is what a bake reads: canonical JSON, integers and printable ASCII only, in the
 * grammar's own record vocabulary.
 *
 *     {
 *       "profile": "exulanica.tile-document/v1",
 *       "tile": <the city.tile record payload>,
 *       "grammars": [
 *         {
 *           "grammar_id": <key>, "grammar_version": <int>,
 *           "descriptor_sha256": <hex64 of the descriptor file's bytes>,
 *           "declared_semantics": {"subject_kind", "admissible_uses", "plane"},
 *           "records": [<record payload>, ...]
 *         }, ...
 *       ]
 *     }
 *
 * A record payload is exactly what `exulanica.grammar.records.record_payload` returns:
 * `{"kind", "version", "fields"}`, with tuples as arrays and `DeclaredSemantics` as a plain
 * object. `grammars` is sorted by id and names exactly the pairs `tile.grammar_versions` names,
 * in the same order, so the digest that keys the bake covers every grammar the records came from.
 *
 * THERE IS NO DEFAULT BRANCH. An unknown key is an error, a missing key is an error, an integer
 * out of its grammar bound is an error, an unknown record kind is an error, and a record repeated
 * byte for byte is an error. Nothing here fills a value in, and nothing here knows what any value
 * means: a key is checked for its spelling, never looked up.
 *
 * WHAT THIS DOES NOT CHECK, stated so nobody assumes it:
 *   - that a record kind belongs to a stage of the grammar it is listed under, or that the
 *     declared semantics are the ones the descriptor file states. Core cannot read a descriptor
 *     or a grammar's stages; the Python side checks both, against `descriptor_sha256`;
 *   - that a key resolves in a catalog. Core carries no catalog, by design;
 *   - that a subject lies in this tile. Ownership by parcel centroid needs the tile grid and a
 *     centroid, and neither is a record field yet.
 */
import { CanonicalJsonError, compareCodeUnits, parseCanonical } from './canonical-json.js';
import type { CanonicalValue } from './canonical-json.js';
import {
  HEX64_PATTERN,
  IDENTITY_PATTERN,
  KEY_PATTERN,
  PLANE,
  PROJECTIONS,
  RECORD_SHAPES,
  SEMANTICS_FIELDS,
  TEXTURE_SET_ID_PATTERN,
  TILE_SHAPE,
} from './record-shapes.js';
import type { FieldShape, ProjectionName, RecordShape } from './record-shapes.js';

export const TILE_DOCUMENT_PROFILE = 'exulanica.tile-document/v1';

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
  readonly records: readonly RecordPayload[];
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
  if (typeof value !== 'object' || value === null) fail(where, 'is not an object');
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

function pairAt(value: unknown, where: string): readonly [unknown, unknown] {
  const pair = arrayAt(value, where);
  if (pair.length !== 2) fail(where, 'is not a pair');
  return [pair[0], pair[1]];
}

export function validateSemantics(value: unknown, where: string): DeclaredSemantics {
  const semantics = objectAt(value, where);
  exactKeys(semantics, SEMANTICS_FIELDS, where);
  const subjectKind = stringMatching(semantics.subject_kind, KEY_PATTERN, 'a key', `${where}.subject_kind`);
  if (semantics.plane !== PLANE) fail(`${where}.plane`, `is not ${JSON.stringify(PLANE)}`);
  const uses = arrayAt(semantics.admissible_uses, `${where}.admissible_uses`);
  const admitted: ProjectionName[] = [];
  uses.forEach((use, index) => {
    const at = `${where}.admissible_uses[${index}]`;
    const name = PROJECTIONS.find((projection) => projection === use);
    if (name === undefined) fail(at, `is not one of ${JSON.stringify(PROJECTIONS)}`);
    if (admitted.includes(name)) fail(at, 'repeats a use');
    admitted.push(name);
  });
  return { subject_kind: subjectKind, admissible_uses: admitted, plane: PLANE };
}

function checkField(shape: FieldShape, value: unknown, where: string): void {
  switch (shape.type) {
    case 'int':
      integerAt(value, where, shape.min, shape.max);
      return;
    case 'key':
      stringMatching(value, KEY_PATTERN, 'a lowercase key', where);
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
    case 'enum':
      if (typeof value !== 'string') fail(where, `is not one of ${JSON.stringify(shape.values)}`);
      if (!shape.values.includes(value)) fail(where, `is not one of ${JSON.stringify(shape.values)}`);
      return;
    case 'ints':
      arrayAt(value, where).forEach((item, index) => integerAt(item, `${where}[${index}]`, shape.min));
      return;
    case 'increasing_ints': {
      let previous: number | undefined;
      arrayAt(value, where).forEach((item, index) => {
        const current = integerAt(item, `${where}[${index}]`, shape.min);
        if (previous !== undefined) {
          if (current <= previous) fail(where, 'is not strictly increasing');
        }
        previous = current;
      });
      return;
    }
    case 'int_pairs':
    case 'ring': {
      const pairs = arrayAt(value, where);
      if (pairs.length < shape.min_count) fail(where, `has fewer than ${shape.min_count} pairs`);
      pairs.forEach((item, index) => {
        const [first, second] = pairAt(item, `${where}[${index}]`);
        integerAt(first, `${where}[${index}][0]`);
        integerAt(second, `${where}[${index}][1]`);
      });
      return;
    }
    case 'setbacks':
      arrayAt(value, where).forEach((item, index) => {
        const [storey, depth] = pairAt(item, `${where}[${index}]`);
        integerAt(storey, `${where}[${index}] storey`);
        integerAt(depth, `${where}[${index}] depth_mm`, 1);
      });
      return;
    case 'parameters': {
      const names: string[] = [];
      arrayAt(value, where).forEach((item, index) => {
        const [name, parameter] = pairAt(item, `${where}[${index}]`);
        names.push(stringMatching(name, KEY_PATTERN, 'a key', `${where}[${index}] name`));
        if (typeof parameter === 'string') {
          stringMatching(parameter, KEY_PATTERN, 'a key', `${where}[${index}] value`);
        } else {
          integerAt(parameter, `${where}[${index}] value`);
        }
      });
      requireSortedUnique(names, where);
      return;
    }
    case 'grammar_versions': {
      const ids: string[] = [];
      const pairs = arrayAt(value, where);
      if (pairs.length === 0) fail(where, 'is empty');
      pairs.forEach((item, index) => {
        const [id, version] = pairAt(item, `${where}[${index}]`);
        ids.push(stringMatching(id, KEY_PATTERN, 'a key', `${where}[${index}] id`));
        integerAt(version, `${where}[${index}] version`, 1);
      });
      requireSortedUnique(ids, where);
      return;
    }
    case 'semantics':
      validateSemantics(value, where);
      return;
  }
}

function requireSortedUnique(names: readonly string[], where: string): void {
  names.forEach((name, index) => {
    if (index > 0) {
      if (compareCodeUnits(names[index - 1]!, name) >= 0) {
        fail(where, 'is not sorted by name with each name once');
      }
    }
  });
}

function checkRule(rule: RecordShape['rules'][number], fields: JsonObject, where: string): void {
  switch (rule) {
    case 'grid_sample_count': {
      const samples = (fields.columns as number) * (fields.rows as number);
      if (!Number.isSafeInteger(samples)) fail(where, 'has more grid samples than an integer holds');
      if ((fields.height_mm as readonly unknown[]).length !== samples) {
        fail(`${where}.height_mm`, `does not hold columns * rows = ${samples} samples`);
      }
      if ((fields.slope_millionths as readonly unknown[]).length !== samples) {
        fail(`${where}.slope_millionths`, `does not hold columns * rows = ${samples} samples`);
      }
      return;
    }
    case 'distinct_segment_nodes':
      if (fields.start_node === fields.end_node) fail(where, 'joins a node to itself');
      return;
    case 'curb_edge_not_self':
      if (fields.next_curb_ordinal === fields.curb_ordinal) fail(where, 'follows itself');
      return;
    case 'ring_not_closed': {
      const ring = fields.boundary_mm as readonly (readonly number[])[];
      const first = ring[0]!;
      const last = ring[ring.length - 1]!;
      if (first[0] === last[0]) {
        if (first[1] === last[1]) fail(`${where}.boundary_mm`, 'is closed by repeating its first point');
      }
      return;
    }
    case 'setback_storeys_below_top': {
      const storeys = fields.storeys as number;
      let previous = 0;
      (fields.setbacks as readonly (readonly number[])[]).forEach((setback, index) => {
        const storey = setback[0]!;
        integerAt(storey, `${where}.setbacks[${index}] storey`, previous + 1, storeys - 1);
        previous = storey;
      });
      return;
    }
  }
}

const SHAPES_BY_KIND: ReadonlyMap<string, RecordShape> = new Map(
  RECORD_SHAPES.map((shape) => [shape.kind, shape]),
);

/** The shape a record kind is validated against, or a refusal naming the kinds that exist. */
export function shapeOf(kind: string): RecordShape {
  const shape = SHAPES_BY_KIND.get(kind);
  if (shape === undefined) {
    fail(`record kind ${JSON.stringify(kind)}`, `is not one of ${JSON.stringify([...SHAPES_BY_KIND.keys()])}`);
  }
  return shape;
}

/** One record payload, validated against its kind's shape, or against `expected` when given. */
export function validateRecord(value: unknown, where: string, expected?: RecordShape): RecordPayload {
  const record = objectAt(value, where);
  exactKeys(record, ['fields', 'kind', 'version'], where);
  if (typeof record.kind !== 'string') fail(`${where}.kind`, 'is not a string');
  const shape = expected === undefined ? shapeOf(record.kind) : expected;
  if (record.kind !== shape.kind) fail(`${where}.kind`, `is not ${JSON.stringify(shape.kind)}`);
  integerAt(record.version, `${where}.version`, shape.version, shape.version);
  const fields = objectAt(record.fields, `${where}.fields`);
  const names = Object.keys(shape.fields);
  exactKeys(fields, names, `${where}.fields`);
  for (const name of names) checkField(shape.fields[name]!, fields[name], `${where}.fields.${name}`);
  for (const rule of shape.rules) checkRule(rule, fields, `${where}.fields`);
  return record as unknown as RecordPayload;
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
  const tile = validateRecord(document.tile, 'tile', TILE_SHAPE);
  const declared = tile.fields.grammar_versions as readonly (readonly [string, number])[];
  const grammarsIn = arrayAt(document.grammars, 'grammars');
  if (grammarsIn.length !== declared.length) {
    fail('grammars', 'does not name exactly the grammars tile.grammar_versions names');
  }
  const seen = new Set<string>();
  const grammars = grammarsIn.map((value, index): GrammarEntry => {
    const where = `grammars[${index}]`;
    const entry = objectAt(value, where);
    exactKeys(
      entry,
      ['declared_semantics', 'descriptor_sha256', 'grammar_id', 'grammar_version', 'records'],
      where,
    );
    const [declaredId, declaredVersion] = declared[index]!;
    if (entry.grammar_id !== declaredId) fail(`${where}.grammar_id`, `is not ${JSON.stringify(declaredId)}`);
    if (entry.grammar_version !== declaredVersion) {
      fail(`${where}.grammar_version`, `is not ${declaredVersion}`);
    }
    const descriptor = stringMatching(
      entry.descriptor_sha256,
      HEX64_PATTERN,
      '64 lowercase hexadecimal characters',
      `${where}.descriptor_sha256`,
    );
    const semantics = validateSemantics(entry.declared_semantics, `${where}.declared_semantics`);
    const records = arrayAt(entry.records, `${where}.records`).map((record, recordIndex) => {
      const payload = validateRecord(record, `${where}.records[${recordIndex}]`);
      // Canonical bytes are the record's identity for this check: the parser already proved the
      // whole document canonical, so equal JSON text is equal records.
      const text = JSON.stringify(payload);
      if (seen.has(text)) fail(`${where}.records[${recordIndex}]`, 'repeats a record exactly');
      seen.add(text);
      return payload;
    });
    return {
      grammar_id: declaredId,
      grammar_version: declaredVersion,
      descriptor_sha256: descriptor,
      declared_semantics: semantics,
      records,
    };
  });
  return { tile, grammars };
}

export { CanonicalJsonError };
