/**
 * The runtime is empty of vocabulary, proved by reading its source, not by a sentence.
 *
 * The precedent is the backend's model-manifest test, which fails when a model identifier leaks
 * into a `.py` file. This walks every file in `src/core` with the TypeScript parser and fails on:
 *
 *   - a word from the repository's own vocabulary sources: the city catalogs, the pinned texture
 *     sets, the owned district's seven material names, the society's roles and names, and a
 *     short list of typology, era, material, use and element words written below;
 *   - a numeric literal outside a short list whose every member has a stated structural reason;
 *   - a `||` or `??` (the shape of a fallback that supplies a value a record does not carry), a
 *     `default:` branch, and a default parameter or destructuring default;
 *   - a clock, a random source, locale or `Intl` code, `for ... in`, `Object.values` or
 *     `Object.entries`, an `Object.keys` whose result is not sorted on the spot, `**`, and every
 *     `Math` member except `fround` (correctly rounded by specification, and used only for the
 *     float32 payload, which no digest reads);
 *   - an import that is not a relative `./*.js` module inside `src/core`.
 *
 * `src/core/record-shapes.ts` is exempt from the word and number rules, and only from those. Its
 * numbers and closed values are the grammar's own, and `tests/test_bake_determinism.py` holds them
 * to the grammar field by field. The detector itself is tested against planted violations first,
 * so a scan that stopped finding things would fail rather than pass.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import { NEEDS, PROJECTIONS, RECORD_SHAPES, TILE_SHAPE } from '../src/core/index.js';
import { ENTRY_STATES } from '../src/core/triangle-digest.js';
import { PACKAGE_ROOT, REPOSITORY_ROOT } from './support.js';

const CORE = join(PACKAGE_ROOT, 'src', 'core');
const EXEMPT_FROM_WORDS_AND_NUMBERS = new Set(['record-shapes.ts']);

/**
 * Numbers core may write anywhere: 0 and 1 (counting), 2 (a pair, two surface coordinates, two
 * samples to an edge) and 3 (three components, three corners).
 */
const ANYWHERE = new Set([0, 1, 2, 3]);
/**
 * Numbers core may write only as the initialiser of a named top-level constant, each for a reason:
 * 4 bytes in an int32, float32 or uint32; 8 bytes in a preamble or an int64; 9 coordinates in a
 * triangle; 6 surface coordinates in a triangle; 16, ADR-0010's alignment; 1000 millimetres in a
 * metre; 0x20 and 0x7e, printable ASCII's bounds; 0x7fffffff and 0x100000000, int32's largest value
 * and uint32's size.
 */
const NAMED_ONLY = new Set([4, 6, 8, 9, 16, 1000, 0x20, 0x7e, 0x7fffffff, 0x100000000]);

/** Typology, era, material, use and element words, beyond what the data files name. */
const WRITTEN_WORDS = [
  'terrace', 'terraced', 'rowhouse', 'tenement', 'brownstone', 'townhouse', 'tower', 'skyscraper',
  'warehouse', 'mansion', 'villa', 'bungalow', 'cottage', 'apartment', 'detached',
  'victorian', 'georgian', 'edwardian', 'regency', 'deco', 'modernist', 'brutalist', 'prewar',
  'postwar', 'interwar', 'colonial', 'gothic',
  'brick', 'stone', 'limestone', 'sandstone', 'granite', 'marble', 'concrete', 'asphalt', 'glass',
  'steel', 'iron', 'copper', 'timber', 'wood', 'stucco', 'plaster', 'terracotta', 'slate', 'cobble',
  'cafe', 'bakery', 'restaurant', 'grocer', 'pharmacy', 'shop', 'retail', 'office', 'residential',
  'commercial', 'industrial', 'civic',
  'window', 'windows', 'sill', 'lintel', 'pilaster', 'mullion', 'awning', 'fascia', 'transom',
  'cornice', 'glazing', 'balcony', 'dormer', 'chimney', 'gable', 'hipped', 'mansard', 'gambrel',
  'oak', 'maple', 'linden', 'unresolved',
];

const words = (text: string): string[] =>
  text
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .toLowerCase()
    .split(/[^a-z]+/)
    .filter((word) => word.length > 1);

function readJson(path: string): unknown {
  return JSON.parse(readFileSync(path, 'utf8'));
}

function stringsIn(value: unknown, skip: ReadonlySet<string>): string[] {
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.flatMap((item) => stringsIn(item, skip));
  if (typeof value === 'object' && value !== null) {
    return Object.keys(value)
      .sort()
      .filter((key) => !skip.has(key))
      .flatMap((key) => stringsIn((value as Record<string, unknown>)[key], skip));
  }
  return [];
}

/** Every schema word core legitimately spells: record kinds, field names, projections, needs. */
function schemaWords(): Set<string> {
  const tokens = [
    ...[TILE_SHAPE, ...RECORD_SHAPES].flatMap((shape) => [shape.kind, ...Object.keys(shape.fields)]),
    ...PROJECTIONS,
    ...Object.keys(NEEDS),
    ...ENTRY_STATES,
  ];
  return new Set(tokens.flatMap(words));
}

/** The vocabulary the repository actually holds, read from where it is held. */
function vocabulary(): Set<string> {
  const found = new Set<string>(WRITTEN_WORDS);
  const catalogs = join(REPOSITORY_ROOT, 'assets', 'catalogs');
  for (const name of readdirSync(catalogs).filter((file) => file.endsWith('.json')).sort()) {
    const catalog = readJson(join(catalogs, name)) as { entries: unknown[] };
    for (const text of stringsIn(catalog.entries, new Set(['licence']))) words(text).forEach((w) => found.add(w));
  }
  const manifest = readJson(join(REPOSITORY_ROOT, 'assets', 'textures', 'manifest.json')) as {
    sets: { set_id: string }[];
  };
  for (const set of manifest.sets) words(set.set_id.replace(/^cc0\./, '')).forEach((w) => found.add(w));
  const district = readJson(
    join(REPOSITORY_ROOT, 'assets', 'owned-world', 'flatiron', 'flatiron-owned-district.json'),
  ) as { materials: { name: string }[] };
  for (const material of district.materials) words(material.name).forEach((w) => found.add(w));
  const society = readFileSync(join(REPOSITORY_ROOT, 'exulanica', 'world', 'society.py'), 'utf8');
  for (const tuple of ['ROLES', 'FIRST_NAMES', 'LAST_NAMES']) {
    const match = new RegExp(`^${tuple}: Final = \\(([^)]*)\\)`, 'm').exec(society);
    if (match === null) throw new Error(`society.py no longer declares ${tuple} where this test reads it`);
    for (const literal of match[1]!.matchAll(/"([^"]+)"/g)) words(literal[1]!).forEach((w) => found.add(w));
  }
  for (const word of schemaWords()) found.delete(word);
  return found;
}

const FORBIDDEN_CALLS = new Set(['Date', 'performance', 'Intl', 'setTimeout', 'setInterval', 'require']);
const FORBIDDEN_MEMBERS = new Set(['random', 'toLocaleString', 'localeCompare', 'toLocaleUpperCase', 'toLocaleLowerCase', 'now']);

function numericValue(node: ts.NumericLiteral | ts.BigIntLiteral): number {
  return Number(node.text.replace(/n$/, ''));
}

function isNamedTopLevelConstant(node: ts.Node): boolean {
  const declaration = node.parent;
  if (!ts.isVariableDeclaration(declaration)) return false;
  if (declaration.initializer !== node) return false;
  const list = declaration.parent;
  if (!ts.isVariableDeclarationList(list)) return false;
  if ((list.flags & ts.NodeFlags.Const) === 0) return false;
  return ts.isVariableStatement(list.parent) && ts.isSourceFile(list.parent.parent);
}

/** Every rule this test holds core to, as findings for one source text. */
export function findings(label: string, text: string, forbiddenWords: ReadonlySet<string>): string[] {
  const found: string[] = [];
  const exempt = EXEMPT_FROM_WORDS_AND_NUMBERS.has(label);
  const source = ts.createSourceFile(label, text, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TS);
  const flag = (node: ts.Node, what: string): void => {
    const { line } = source.getLineAndCharacterOfPosition(node.getStart(source));
    found.push(`${label}:${line + 1}: ${what}`);
  };
  const checkWords = (node: ts.Node, value: string): void => {
    if (exempt) return;
    for (const word of words(value)) {
      if (forbiddenWords.has(word)) flag(node, `vocabulary word "${word}"`);
    }
  };
  const visit = (node: ts.Node): void => {
    if (ts.isStringLiteralLike(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) {
      checkWords(node, node.text);
    } else if (ts.isIdentifier(node)) {
      checkWords(node, node.text);
      if (FORBIDDEN_CALLS.has(node.text)) flag(node, `${node.text} is a clock, a timer or a host lookup`);
    } else if (ts.isNumericLiteral(node) || ts.isBigIntLiteral(node)) {
      const value = numericValue(node);
      if (!exempt && !ANYWHERE.has(value)) {
        if (!NAMED_ONLY.has(value)) flag(node, `numeric literal ${node.text} is not a stated structural number`);
        else if (!isNamedTopLevelConstant(node)) flag(node, `numeric literal ${node.text} must be a named top-level constant`);
      }
    } else if (ts.isBinaryExpression(node)) {
      const operator = node.operatorToken.kind;
      if (operator === ts.SyntaxKind.BarBarToken || operator === ts.SyntaxKind.BarBarEqualsToken) flag(node, '|| fallback');
      if (operator === ts.SyntaxKind.QuestionQuestionToken || operator === ts.SyntaxKind.QuestionQuestionEqualsToken) {
        flag(node, '?? fallback');
      }
      if (operator === ts.SyntaxKind.AsteriskAsteriskToken || operator === ts.SyntaxKind.AsteriskAsteriskEqualsToken) {
        flag(node, '** is not exact on non-integers');
      }
    } else if (ts.isDefaultClause(node)) {
      flag(node, 'default branch');
    } else if (ts.isParameter(node) && node.initializer !== undefined) {
      flag(node, 'default parameter');
    } else if (ts.isBindingElement(node) && node.initializer !== undefined) {
      flag(node, 'destructuring default');
    } else if (ts.isForInStatement(node)) {
      flag(node, 'for ... in iterates in an order nobody declared');
    } else if (ts.isPropertyAccessExpression(node)) {
      const owner = node.expression.getText(source);
      const member = node.name.text;
      if (owner === 'Math' && member !== 'fround') flag(node, `Math.${member}`);
      if (owner === 'Object' && (member === 'values' || member === 'entries')) flag(node, `Object.${member}`);
      if (owner === 'Object' && member === 'keys') {
        const call = node.parent;
        const sorted = ts.isCallExpression(call)
          && ts.isPropertyAccessExpression(call.parent)
          && call.parent.name.text === 'sort';
        if (!sorted) flag(node, 'Object.keys whose order is not fixed by a sort');
      }
      if (FORBIDDEN_MEMBERS.has(member)) flag(node, `.${member}`);
    } else if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
      const specifier = node.moduleSpecifier;
      if (specifier !== undefined && ts.isStringLiteral(specifier)) {
        if (!/^\.\/[a-z-]+\.js$/.test(specifier.text)) flag(node, `import of ${specifier.text}`);
      }
      // A module specifier is a path, not vocabulary, so its words are not checked.
      return;
    } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      flag(node, 'dynamic import');
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

function coreFiles(): string[] {
  return readdirSync(CORE)
    .filter((name) => name.endsWith('.ts'))
    .sort();
}

describe('the vocabulary-emptiness scan', () => {
  const planted = new Set(['brick', 'baker']);
  const plant = (text: string): string[] => findings('planted.ts', text, planted);

  it('finds every kind of violation it claims to find', () => {
    expect(plant("export const role = 'baker';")).toHaveLength(1);
    expect(plant('export const brickCourse = 1;')).toHaveLength(1);
    expect(plant('export const bay = (value: number): number => value * 3000;')).toHaveLength(1);
    expect(plant('function f(): number { const pitch = 16; return pitch; }')).toHaveLength(1);
    expect(plant('export const f = (a?: number): number => a ?? 1;')).toHaveLength(1);
    expect(plant('export const f = (a: number): number => a || 1;')).toHaveLength(1);
    expect(plant('export const f = (a = 1): number => a;')).toHaveLength(1);
    expect(plant('export const f = ({ a = 1 }: { a?: number }): number => a;')).toHaveLength(1);
    expect(plant('export function f(a: number): number { switch (a) { default: return 1; } }')).toHaveLength(1);
    // Twice: as a Math member and as a random source by name.
    expect(plant('export const f = (): number => Math.random();')).toHaveLength(2);
    expect(plant('export const f = (a: number): number => Math.sin(a);')).toHaveLength(1);
    expect(plant('export const f = (a: number): number => Math.sqrt(a);')).toHaveLength(1);
    expect(plant('export const f = (a: number): number => a ** 2;')).toHaveLength(1);
    // Twice: the clock by name, and its reading.
    expect(plant('export const f = (): number => Date.now();')).toHaveLength(2);
    expect(plant("export const f = (a: string, b: string): number => a.localeCompare(b);")).toHaveLength(1);
    expect(plant('export const f = (o: object): unknown[] => Object.values(o);')).toHaveLength(1);
    expect(plant('export const f = (o: object): string[] => Object.keys(o);')).toHaveLength(1);
    expect(plant('export function f(o: object): void { for (const k in o) { void k; } }')).toHaveLength(1);
    expect(plant("import { readFileSync } from 'node:fs';\nexport const f = readFileSync;")).toHaveLength(1);
    expect(plant("import { x } from '../node/x.js';\nexport const f = x;")).toHaveLength(1);
    expect(plant("export const f = (): Promise<unknown> => import('./x.js');")).toHaveLength(1);
  });

  it('passes what core is allowed to write', () => {
    expect(plant('export const ELEMENT_BYTES = 4;')).toEqual([]);
    expect(plant('export const f = (o: object): string[] => Object.keys(o).sort();')).toEqual([]);
    expect(plant('export const f = (a: number): number => Math.fround(a / 3);')).toEqual([]);
    expect(plant("import { x } from './x.js';\nexport const f = x;")).toEqual([]);
  });

  it('reads a vocabulary that actually contains the repository vocabulary', () => {
    const vocabularyWords = vocabulary();
    for (const word of ['baker', 'brick', 'limestone', 'asphalt', 'glazing', 'transom', 'victorian', 'granite']) {
      expect(vocabularyWords.has(word), word).toBe(true);
    }
    // Schema words core must be able to spell are not vocabulary.
    for (const word of ['render', 'batch', 'terrain', 'material', 'surface', 'vitrine']) {
      expect(vocabularyWords.has(word), word).toBe(false);
    }
  });
});

describe('src/core', () => {
  it('holds no vocabulary, no default, no fallback, no clock and no host import', () => {
    const forbidden = vocabulary();
    const files = coreFiles();
    expect(files).toContain('owd.ts');
    const all = files.flatMap((name) =>
      findings(name, readFileSync(join(CORE, name), 'utf8'), forbidden),
    );
    expect(all, `found in ${relative(PACKAGE_ROOT, CORE)}`).toEqual([]);
  });
});
