/**
 * The glyph catalog reader: canonical JSON in, a checked catalog out, or one refusal.
 *
 * The TypeScript copy of `exulanica.lettering.catalog`, checking the same things in the same order
 * for the same reasons: `json`, `shape`, `promise`, `characters`, `kerning`, `ring`, `metrics`.
 * `docs/lettering.md` says what each covers. The shared cases in
 * `test/lettering-cases.json` hold the two readers together, one case per reason.
 *
 * Nothing here parses a font. A catalog is made once by `tools/lettering`; this side only reads.
 */
import { parseCanonical } from './canonical-json.js';
import { type Part, type Point, type Ring, partsProblem } from './geometry.js';
import { refuse } from './refusal.js';

export const GLYPH_CATALOG_PROFILE = 'exulanica.lettering.glyph-catalog/v1';
/** Space, five marks, digits, capitals and small letters, in code point order. */
export const CHARACTER_SET = " &',-.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

/** TrueType stores coordinates, advances and kerning values in sixteen bits. */
const COORDINATE = [-32768, 32767] as const;
const ADVANCE = [0, 65535] as const;
const UNITS_PER_EM = [16, 16384] as const;
/** Keeps 2 * coordinate * cap height in millimetres well inside 2^53. */
const LARGEST_CAP_HEIGHT_MM = 1_000_000;
const CATALOG_ID = /^[a-z][a-z0-9_]{0,63}$/;
const HEX_40 = /^[0-9a-f]{40}$/;
const HEX_64 = /^[0-9a-f]{64}$/;
const PRINTABLE = /^[\x20-\x7e]+$/;

export interface Glyph {
  readonly character: string;
  readonly advance: number;
  readonly parts: readonly Part[];
}

export interface GlyphCatalog {
  readonly catalogId: string;
  readonly catalogVersion: number;
  readonly unitsPerEm: number;
  readonly capHeight: number;
  readonly xHeight: number;
  readonly ascender: number;
  readonly descender: number;
  readonly minimumEdge: number;
  readonly minimumCapHeightMm: number;
  readonly maximumCapHeightMm: number;
  readonly largestFailingMm: number;
  readonly family: string;
  readonly style: string;
  readonly glyphs: ReadonlyMap<string, Glyph>;
  /** Keyed by the two characters, left then right. */
  readonly kerning: ReadonlyMap<string, number>;
  readonly source: Record<string, unknown>;
}

type Document = Record<string, unknown>;

function object(value: unknown, keys: readonly string[], where: string, optional: readonly string[] = []): Document {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    refuse('shape', `${where} is not an object`);
  }
  const present = Object.keys(value as Document).sort();
  const allowed = new Set([...keys, ...optional]);
  const missing = keys.filter((key) => !present.includes(key));
  const extra = present.filter((key) => !allowed.has(key));
  if (missing.length || extra.length) {
    refuse('shape', `${where} has fields ${JSON.stringify(present)}, not ${JSON.stringify([...keys].sort())}`);
  }
  return value as Document;
}

function integer(value: unknown, where: string, low: number, high: number): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < low || value > high) {
    refuse('shape', `${where} is ${JSON.stringify(value) ?? String(value)}, not an integer from ${low} to ${high}`);
  }
  return value;
}

function text(value: unknown, where: string, pattern: RegExp = PRINTABLE): string {
  if (typeof value !== 'string' || !pattern.test(value)) {
    refuse('shape', `${where} is ${JSON.stringify(value) ?? String(value)}, not ${pattern.source}`);
  }
  return value;
}

function list(value: unknown, where: string): unknown[] {
  if (!Array.isArray(value)) refuse('shape', `${where} is not a list`);
  return value as unknown[];
}

function flatRing(value: unknown, where: string): Ring {
  const values = list(value, where);
  if (values.length < 6 || values.length % 2) {
    refuse('shape', `${where} has ${values.length} numbers, not an even count of 6 or more`);
  }
  values.forEach((number, index) => integer(number, `${where}[${index}]`, ...COORDINATE));
  const ring: Point[] = [];
  for (let index = 0; index < values.length; index += 2) {
    ring.push([values[index] as number, values[index + 1] as number]);
  }
  return ring;
}

function readSource(value: unknown): Document {
  const source = object(
    value,
    ['repository', 'commit', 'path', 'url', 'file', 'sha256', 'byte_size', 'family', 'style', 'font_version', 'licence'],
    'source',
  );
  for (const key of ['repository', 'path', 'url', 'file', 'family', 'style', 'font_version']) {
    text(source[key], `source.${key}`);
  }
  text(source['commit'], 'source.commit', HEX_40);
  text(source['sha256'], 'source.sha256', HEX_64);
  integer(source['byte_size'], 'source.byte_size', 1, 2 ** 31 - 1);
  const licence = object(source['licence'], ['spdx', 'copyright', 'file', 'url', 'sha256'], 'licence');
  if (licence['spdx'] !== 'OFL-1.1') {
    refuse('shape', `source.licence.spdx is ${JSON.stringify(licence['spdx'])}, not "OFL-1.1"`);
  }
  const lines = list(licence['copyright'], 'source.licence.copyright');
  if (!lines.length) refuse('shape', 'source.licence.copyright has no line');
  lines.forEach((line, index) => text(line, `source.licence.copyright[${index}]`));
  text(licence['file'], 'source.licence.file');
  text(licence['url'], 'source.licence.url');
  text(licence['sha256'], 'source.licence.sha256', HEX_64);
  return source;
}

function shape(document: unknown): Document {
  const root = object(
    document,
    [
      'profile',
      'catalog_id',
      'catalog_version',
      'source',
      'tool',
      'units_per_em',
      'metrics',
      'conversion',
      'cap_height_mm',
      'scan',
      'glyphs',
      'kerning',
    ],
    'the catalog',
  );
  if (root['profile'] !== GLYPH_CATALOG_PROFILE) {
    refuse('shape', `profile is ${JSON.stringify(root['profile'])}, not ${JSON.stringify(GLYPH_CATALOG_PROFILE)}`);
  }
  text(root['catalog_id'], 'catalog_id', CATALOG_ID);
  integer(root['catalog_version'], 'catalog_version', 1, 2 ** 31 - 1);
  readSource(root['source']);
  const tool = object(root['tool'], ['name', 'rules_version', 'fonttools'], 'tool');
  text(tool['name'], 'tool.name');
  integer(tool['rules_version'], 'tool.rules_version', 1, 2 ** 31 - 1);
  text(tool['fonttools'], 'tool.fonttools');
  integer(root['units_per_em'], 'units_per_em', ...UNITS_PER_EM);
  const metrics = object(root['metrics'], ['cap_height', 'x_height', 'ascender', 'descender'], 'metrics');
  integer(metrics['cap_height'], 'metrics.cap_height', 1, COORDINATE[1]);
  for (const key of ['x_height', 'ascender', 'descender']) {
    integer(metrics[key], `metrics.${key}`, ...COORDINATE);
  }
  const conversion = object(
    root['conversion'],
    [
      'flattening_tolerance_cap_height_divisor',
      'minimum_edge_cap_height_divisor',
      'minimum_edge',
      'vertices_removed',
      'largest_shift',
    ],
    'conversion',
  );
  for (const key of ['flattening_tolerance_cap_height_divisor', 'minimum_edge_cap_height_divisor']) {
    integer(conversion[key], `conversion.${key}`, 1, LARGEST_CAP_HEIGHT_MM);
  }
  integer(conversion['minimum_edge'], 'conversion.minimum_edge', 1, COORDINATE[1]);
  integer(conversion['vertices_removed'], 'conversion.vertices_removed', 0, 2 ** 31 - 1);
  integer(conversion['largest_shift'], 'conversion.largest_shift', 0, COORDINATE[1]);
  const promise = object(root['cap_height_mm'], ['minimum', 'maximum'], 'cap_height_mm');
  for (const key of ['minimum', 'maximum']) {
    integer(promise[key], `cap_height_mm.${key}`, 1, LARGEST_CAP_HEIGHT_MM);
  }
  const scan = object(root['scan'], ['from_mm', 'largest_failing_mm'], 'scan', ['failure']);
  integer(scan['from_mm'], 'scan.from_mm', 1, LARGEST_CAP_HEIGHT_MM);
  integer(scan['largest_failing_mm'], 'scan.largest_failing_mm', 0, LARGEST_CAP_HEIGHT_MM);
  if ('failure' in scan) text(scan['failure'], 'scan.failure');
  list(root['glyphs'], 'glyphs').forEach((glyph, index) => {
    const where = `glyphs[${index}]`;
    const read = object(glyph, ['character', 'advance', 'parts'], where);
    if (typeof read['character'] !== 'string' || [...(read['character'] as string)].length !== 1) {
      refuse('shape', `${where}.character is not one character`);
    }
    integer(read['advance'], `${where}.advance`, ...ADVANCE);
    list(read['parts'], `${where}.parts`).forEach((part, partIndex) => {
      const partWhere = `${where}.parts[${partIndex}]`;
      const readPart = object(part, ['outer', 'holes'], partWhere);
      flatRing(readPart['outer'], `${partWhere}.outer`);
      list(readPart['holes'], `${partWhere}.holes`).forEach((hole, holeIndex) =>
        flatRing(hole, `${partWhere}.holes[${holeIndex}]`),
      );
    });
  });
  list(root['kerning'], 'kerning').forEach((pair, index) => {
    const where = `kerning[${index}]`;
    if (!Array.isArray(pair) || pair.length !== 3) refuse('shape', `${where} is not [left, right, value]`);
    for (const side of [0, 1]) {
      const character: unknown = (pair as unknown[])[side];
      if (typeof character !== 'string' || [...character].length !== 1) {
        refuse('shape', `${where}[${side}] is not one character`);
      }
    }
    integer((pair as unknown[])[2], `${where}[2]`, ...COORDINATE);
  });
  return root;
}

function checkPromise(root: Document): void {
  const promise = root['cap_height_mm'] as Document;
  const conversion = root['conversion'] as Document;
  const scan = root['scan'] as Document;
  const minimum = promise['minimum'] as number;
  const maximum = promise['maximum'] as number;
  const capHeight = (root['metrics'] as Document)['cap_height'] as number;
  if (minimum > maximum) {
    refuse('promise', `the promised minimum ${minimum} exceeds the maximum ${maximum}`);
  }
  if (conversion['minimum_edge_cap_height_divisor'] !== minimum) {
    refuse('promise', 'the minimum edge is not taken at the promised minimum');
  }
  if (conversion['flattening_tolerance_cap_height_divisor'] !== maximum) {
    refuse('promise', 'the flattening tolerance is not taken at the promised maximum');
  }
  const expected = Math.ceil(capHeight / minimum);
  if (conversion['minimum_edge'] !== expected) {
    refuse(
      'promise',
      `the minimum edge is ${String(conversion['minimum_edge'])}, not ceil(${capHeight} / ${minimum})`
        + ` = ${expected}: one millimetre at the smallest promised cap height`,
    );
  }
  if (scan['from_mm'] !== maximum) {
    refuse('promise', `the scan starts at ${String(scan['from_mm'])}, not at ${maximum}`);
  }
  const largest = scan['largest_failing_mm'] as number;
  if (largest >= minimum) refuse('promise', `the scan failed at ${largest} mm, inside the promise`);
  if ((largest > 0) !== ('failure' in scan)) {
    refuse('promise', 'the scan names a failure exactly when it failed at some size');
  }
}

function checkCharacters(root: Document): void {
  const characters = (root['glyphs'] as Document[]).map((glyph) => glyph['character'] as string).join('');
  if (characters !== CHARACTER_SET) {
    refuse('characters', `the glyphs are ${JSON.stringify(characters)}, not the version 1 set`);
  }
}

function readKerning(root: Document): Map<string, number> {
  const table = new Map<string, number>();
  let previous: readonly [number, number] | null = null;
  for (const entry of root['kerning'] as unknown[]) {
    const [left, right, value] = entry as [string, string, number];
    if (!CHARACTER_SET.includes(left) || !CHARACTER_SET.includes(right)) {
      refuse('kerning', `the pair ${JSON.stringify(left)} ${JSON.stringify(right)} leaves the character set`);
    }
    const order = [left.codePointAt(0)!, right.codePointAt(0)!] as const;
    if (previous !== null && (order[0] < previous[0] || (order[0] === previous[0] && order[1] <= previous[1]))) {
      refuse('kerning', `the pair ${JSON.stringify(left)} ${JSON.stringify(right)} repeats or is out of order`);
    }
    if (value === 0) {
      refuse('kerning', `the pair ${JSON.stringify(left)} ${JSON.stringify(right)} is zero, which is omitted`);
    }
    previous = order;
    table.set(left + right, value);
  }
  return table;
}

const startOf = (ring: Ring): readonly [number, number] => [ring[0]![1], ring[0]![0]];

function ascending(starts: readonly (readonly [number, number])[]): boolean {
  for (let index = 1; index < starts.length; index += 1) {
    const before = starts[index - 1]!;
    const here = starts[index]!;
    if (before[0] > here[0] || (before[0] === here[0] && before[1] >= here[1])) return false;
  }
  return true;
}

function readGlyphs(root: Document, minimumEdge: number): Map<string, Glyph> {
  const glyphs = new Map<string, Glyph>();
  for (const glyph of root['glyphs'] as Document[]) {
    const character = glyph['character'] as string;
    const parts: Part[] = [];
    (glyph['parts'] as Document[]).forEach((part, partIndex) => {
      const where = `'${character}' part ${partIndex}`;
      const outer = flatRing(part['outer'], where);
      const holes = (part['holes'] as unknown[]).map((hole) => flatRing(hole, where));
      for (const ring of [outer, ...holes]) {
        const lowest = ring.reduce((best, point) =>
          point[1] < best[1] || (point[1] === best[1] && point[0] < best[0]) ? point : best,
        );
        if (lowest !== ring[0]) {
          refuse('ring', `${where} has a ring not starting at its lowest vertex`);
        }
        for (let index = 0; index < ring.length; index += 1) {
          const a = ring[index]!;
          const b = ring[(index + 1) % ring.length]!;
          if (Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])) < minimumEdge) {
            refuse('ring', `${where} has edge ${index} shorter than the minimum edge`);
          }
        }
      }
      if (!ascending(holes.map(startOf))) refuse('ring', `${where} has its holes out of order`);
      parts.push({ outer, holes });
    });
    if (!ascending(parts.map((part) => startOf(part.outer)))) {
      refuse('ring', `'${character}' has its parts out of order`);
    }
    if ((character === ' ') !== (parts.length === 0)) {
      refuse('ring', `'${character}' has the wrong outline: only the space has none`);
    }
    const problem = partsProblem(parts);
    if (problem) refuse('ring', `'${character}' ${problem}`);
    glyphs.set(character, { character, advance: glyph['advance'] as number, parts });
  }
  return glyphs;
}

function checkMetrics(root: Document, glyphs: ReadonlyMap<string, Glyph>): void {
  const ys = (glyph: Glyph): number[] =>
    glyph.parts.flatMap((part) => [part.outer, ...part.holes].flatMap((ring) => ring.map((p) => p[1])));
  const everything = [...glyphs.values()].flatMap(ys);
  const measured = {
    cap_height: Math.max(...ys(glyphs.get('H')!)),
    x_height: Math.max(...ys(glyphs.get('x')!)),
    ascender: Math.max(...everything),
    descender: Math.min(...everything),
  };
  const declared = root['metrics'] as Document;
  for (const [key, value] of Object.entries(measured)) {
    if (declared[key] !== value) {
      refuse('metrics', `the rings measure ${key} ${value}, not ${String(declared[key])}`);
    }
  }
}

/** A checked glyph catalog, or a `LetteringRefusal` naming the first failing check. */
export function readGlyphCatalog(raw: Uint8Array): GlyphCatalog {
  let document: unknown;
  try {
    document = parseCanonical(raw, 'the catalog');
  } catch (error) {
    refuse('json', `the catalog is not JSON with a canonical form: ${String(error)}`);
  }
  const root = shape(document);
  checkPromise(root);
  checkCharacters(root);
  const kerning = readKerning(root);
  const minimumEdge = (root['conversion'] as Document)['minimum_edge'] as number;
  const glyphs = readGlyphs(root, minimumEdge);
  checkMetrics(root, glyphs);
  const metrics = root['metrics'] as Document;
  const promise = root['cap_height_mm'] as Document;
  const source = root['source'] as Document;
  return {
    catalogId: root['catalog_id'] as string,
    catalogVersion: root['catalog_version'] as number,
    unitsPerEm: root['units_per_em'] as number,
    capHeight: metrics['cap_height'] as number,
    xHeight: metrics['x_height'] as number,
    ascender: metrics['ascender'] as number,
    descender: metrics['descender'] as number,
    minimumEdge,
    minimumCapHeightMm: promise['minimum'] as number,
    maximumCapHeightMm: promise['maximum'] as number,
    largestFailingMm: (root['scan'] as Document)['largest_failing_mm'] as number,
    family: source['family'] as string,
    style: source['style'] as string,
    glyphs,
    kerning,
    source,
  };
}
