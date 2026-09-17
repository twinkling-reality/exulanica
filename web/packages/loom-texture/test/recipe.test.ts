import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';
import { canonicalJson } from '../src/canonical-json.js';
import { DRAFTS, LIBRARY } from '../src/catalog.js';
import {
  formatLibrarySource,
  libraryEntryProblems,
  readLibrary,
} from '../src/library.js';
import { DRAFT_MAKERS, MAKERS, makerFor } from '../src/makers/index.js';
import {
  type MakerManifest,
  type Recipe,
  checkRecipe,
  defaultRecipe,
  evaluate,
  manifestProblems,
  recipeProblems,
} from '../src/recipe.js';
import { StrictJsonError, parseStrictJsonBytes } from '../src/strict-json.js';

/**
 * Recipes and maker manifests are data, and data is checked.
 *
 * The shared cases in `recipe-cases.json` are the specification both validators are held to: this
 * file runs them against `src/recipe.ts` and `src/strict-json.ts`, and
 * `tests/test_material_objects.py` runs the same file against `exulanica.materials`. A case lists
 * the exact problems, in order, so the two languages cannot drift into refusing different objects,
 * or different bytes, or explaining a refusal differently.
 */
type Step = readonly (string | number)[];

interface Change {
  readonly path: Step;
  readonly value?: unknown;
  readonly remove?: boolean;
}

interface RecipeCase {
  readonly name: string;
  readonly set: string;
  readonly manifest_changes?: readonly Change[];
  readonly changes: readonly Change[];
  readonly problems: readonly string[];
}

interface ManifestCase {
  readonly name: string;
  readonly maker: string;
  readonly changes: readonly Change[];
  readonly problems: readonly string[];
}

interface DocumentCase {
  readonly name: string;
  readonly text?: string;
  readonly hex?: string;
  readonly problem: string | null;
}

const CASES_PATH = fileURLToPath(new URL('./recipe-cases.json', import.meta.url));
const CASES_TEXT = readFileSync(CASES_PATH, 'utf8');
const CASES = JSON.parse(CASES_TEXT) as {
  readonly recipes: readonly RecipeCase[];
  readonly manifests: readonly ManifestCase[];
  readonly documents: readonly DocumentCase[];
};

/**
 * Apply changes to a copy. The same rules as `_apply_changes` in the backend's test, and anything
 * the two could read differently is refused: an index is a whole number no larger than the list
 * (equal to it only to append), a removal names something that is there, and no key is
 * `__proto__`, which JavaScript assignment would not store as a key at all.
 */
function applyChanges(base: unknown, changes: readonly Change[]): unknown {
  let root: unknown = structuredClone(base);
  for (const change of changes) {
    const keys = Object.keys(change).sort().join();
    if (keys !== 'path,value' && !(keys === 'path,remove' && change.remove === true)) {
      throw new Error(`a change has a path and either a value or remove: true, not ${keys}`);
    }
    if (change.path.includes('__proto__')) throw new Error('a change never names __proto__');
    if (change.path.length === 0) {
      root = structuredClone(change.value);
      continue;
    }
    let parent = root as Record<string | number, unknown>;
    for (const step of change.path.slice(0, -1)) {
      parent = parent[step] as Record<string | number, unknown>;
    }
    const last = change.path[change.path.length - 1]!;
    if (Array.isArray(parent)) {
      const limit = change.remove === true ? parent.length - 1 : parent.length;
      if (typeof last !== 'number' || !Number.isInteger(last) || last < 0 || last > limit) {
        throw new Error(`no index ${String(last)} to change`);
      }
      if (change.remove === true) parent.splice(last, 1);
      else parent[last] = structuredClone(change.value);
    } else if (typeof last !== 'string') {
      throw new Error(`an object is changed by key, not by ${String(last)}`);
    } else if (change.remove === true) {
      if (!Object.prototype.hasOwnProperty.call(parent, last)) {
        throw new Error(`nothing to remove at ${last}`);
      }
      delete parent[last];
    } else {
      parent[last] = structuredClone(change.value);
    }
  }
  return root;
}

function documentBytes(testCase: DocumentCase): Uint8Array {
  if ((testCase.text === undefined) === (testCase.hex === undefined)) {
    throw new Error(`${testCase.name} gives exactly one of text and hex`);
  }
  return testCase.hex !== undefined
    ? new Uint8Array(Buffer.from(testCase.hex, 'hex'))
    : new TextEncoder().encode(testCase.text);
}

const libraryRecipe = (setId: string): { recipe: Recipe; manifest: MakerManifest } => {
  const source = LIBRARY.find((candidate) => candidate.entry.set_id === setId);
  if (source === undefined) throw new Error(`no published set ${setId}`);
  return { recipe: source.entry.recipe, manifest: source.maker.manifest };
};

describe('the shared cases', () => {
  for (const testCase of CASES.recipes) {
    it(`recipe: ${testCase.name}`, () => {
      const { recipe, manifest } = libraryRecipe(testCase.set);
      const changed = applyChanges(manifest, testCase.manifest_changes ?? []) as MakerManifest;
      expect(manifestProblems(changed), 'the changed manifest is itself well formed').toEqual([]);
      expect(recipeProblems(applyChanges(recipe, testCase.changes), changed)).toEqual(
        testCase.problems,
      );
    });
  }

  for (const testCase of CASES.manifests) {
    it(`manifest: ${testCase.name}`, () => {
      const maker = MAKERS.find((candidate) => candidate.manifest.maker_id === testCase.maker);
      expect(maker, testCase.maker).toBeDefined();
      expect(manifestProblems(applyChanges(maker!.manifest, testCase.changes))).toEqual(
        testCase.problems,
      );
    });
  }

  for (const testCase of CASES.documents) {
    it(`document: ${testCase.name}`, () => {
      let problem: string | null = null;
      try {
        parseStrictJsonBytes(documentBytes(testCase));
      } catch (error) {
        if (!(error instanceof StrictJsonError)) throw error;
        problem = error.message;
      }
      expect(problem).toBe(testCase.problem);
    });
  }

  it('write no number the two languages would read differently', () => {
    const outsideStrings = CASES_TEXT.replace(/"(?:[^"\\]|\\.)*"/g, '""');
    expect(outsideStrings).not.toMatch(/\d\.0+(?!\d)|\d[eE][+-]?\d/);
    expect([...CASES_TEXT].every((character) => character <= '\x7e')).toBe(true);
  });

  it('cover every maker and every set they name', () => {
    const sets = new Set(LIBRARY.map((source) => source.entry.set_id));
    for (const testCase of CASES.recipes) expect(sets).toContain(testCase.set);
    const names = [...CASES.recipes, ...CASES.manifests, ...CASES.documents].map(
      (testCase) => testCase.name,
    );
    expect(new Set(names).size).toBe(names.length);
  });
});

describe('maker manifests', () => {
  it('are well formed, canonical, and sorted by id, drafts among them', () => {
    for (const maker of [...MAKERS, ...DRAFT_MAKERS]) {
      expect(manifestProblems(maker.manifest), maker.manifest.maker_id).toEqual([]);
      expect(() => canonicalJson(maker.manifest)).not.toThrow();
    }
    for (const makers of [MAKERS, DRAFT_MAKERS]) {
      const ids = makers.map((maker) => maker.manifest.maker_id);
      expect(ids).toEqual([...ids].sort());
    }
    const ids = [...MAKERS, ...DRAFT_MAKERS].map((maker) => maker.manifest.maker_id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('name each family once, so a family names its maker, drafts among them', () => {
    const families = [...MAKERS, ...DRAFT_MAKERS].map((maker) => maker.manifest.family);
    expect(new Set(families).size).toBe(families.length);
  });

  it('of a draft maker have a draft set to be tested by, and no published recipe can name one', () => {
    for (const maker of DRAFT_MAKERS) {
      const { maker_id: id, version } = maker.manifest;
      expect(DRAFTS.filter((source) => source.maker === maker).length, id).toBeGreaterThan(0);
      expect(() => makerFor(id, version), id).toThrow(`no maker ${id} version ${version}`);
      expect(LIBRARY.some((source) => source.entry.recipe.maker.id === id), id).toBe(false);
    }
    expect(DRAFTS.every((source) => DRAFT_MAKERS.includes(source.maker))).toBe(true);
  });

  it('resolve by exact id and version, or not at all', () => {
    expect(makerFor('loom.brick', 1)).toBe(MAKERS.find((m) => m.manifest.maker_id === 'loom.brick'));
    expect(() => makerFor('loom.brick', 2)).toThrow('no maker loom.brick version 2');
    expect(() => makerFor('loom.bricks', 1)).toThrow('no maker loom.bricks version 1');
  });

  it('give defaults that are a valid recipe on the published frame', () => {
    for (const { entry, maker } of LIBRARY) {
      const recipe = defaultRecipe(
        maker.manifest,
        entry.recipe.seed,
        entry.recipe.resolution,
        entry.recipe.extent_mm,
      );
      expect(recipeProblems(recipe, maker.manifest), entry.set_id).toEqual([]);
    }
  });
});

describe('recipes', () => {
  it('are refused with every problem named', () => {
    const { recipe, manifest } = libraryRecipe('cc0.brick-running-bond');
    const broken = { ...recipe, seed: -1, parameters: { ...recipe.parameters, courses: 0 } };
    expect(() => checkRecipe(broken, manifest)).toThrow(
      'not a valid loom.brick recipe: seed is an unsigned 32-bit integer; '
        + 'parameters: courses is between 1 and 256',
    );
    expect(checkRecipe(recipe, manifest)).toBe(recipe);
  });

  it('evaluate expressions exactly, and refuse to round', () => {
    const { recipe } = libraryRecipe('cc0.brick-running-bond');
    expect(evaluate({ param: 'courses' }, recipe)).toBe(24);
    expect(evaluate({ extent: 'v' }, recipe)).toBe(1800);
    expect(
      evaluate({ product: [{ param: 'courses' }, { sum: [{ param: 'unit_height_mm' }, { constant: 10 }] }] }, recipe),
    ).toBe(1800);
    expect(evaluate({ product: [{ constant: 1_073_741_824 }, { constant: 1_073_741_824 }] }, recipe)).toBeNull();
    expect(() => evaluate({ param: 'bond' }, recipe)).toThrow('not an integer control');
  });
});

describe('the library', () => {
  let scratch: string | undefined;

  afterEach(() => {
    if (scratch !== undefined) rmSync(scratch, { recursive: true, force: true });
    scratch = undefined;
  });

  const source = LIBRARY[0]!;
  const entry = JSON.parse(JSON.stringify(source.entry)) as Record<string, unknown>;

  it('refuses an entry that is not a named, licensed, valid recipe', () => {
    expect(libraryEntryProblems({ ...entry, set_id: 'cc0.brick-v2' })).toEqual([
      'set_id names a surface: ^[a-z][a-z0-9.-]*$, with no version or digest in it',
    ]);
    expect(libraryEntryProblems({ ...entry, licence_id: 'CC-BY-4.0' })).toEqual([
      'licence_id is CC0-1.0',
    ]);
    expect(libraryEntryProblems({ ...entry, version: 0, title: ' ' })).toEqual([
      'version is a positive integer',
      'title and summary are non-empty printable ASCII',
    ]);
    const recipe = entry.recipe as Recipe;
    expect(
      libraryEntryProblems({ ...entry, recipe: { ...recipe, maker: { id: 'loom.brick', version: 9 } } }),
    ).toEqual(['recipe names a maker id and version this package has']);
    expect(
      libraryEntryProblems({ ...entry, recipe: { ...recipe, seed: 1.5 } }),
    ).toEqual(['recipe: seed is an unsigned 32-bit integer']);
    expect(libraryEntryProblems({ ...entry, note: 'x' })).toEqual([
      'a library entry has exactly set_id, version, title, summary, licence_id, recipe',
    ]);
  });

  it('reads entries strictly, so a whole number written with a fraction is refused', () => {
    scratch = mkdtempSync(join(tmpdir(), 'loom-library-'));
    const text = formatLibrarySource(entry).replace('"version": 1,', '"version": 1.0,');
    expect(text).toContain('"version": 1.0,');
    writeFileSync(join(scratch, `${source.entry.set_id}.json`), text);
    expect(() => readLibrary(scratch)).toThrow('a number is written with a fraction or an exponent');
  });

  it('reads only well-named JSON entries', () => {
    scratch = mkdtempSync(join(tmpdir(), 'loom-library-'));
    writeFileSync(join(scratch, 'cc0.misnamed.json'), formatLibrarySource(entry));
    expect(() => readLibrary(scratch)).toThrow(`must be named ${source.entry.set_id}.json`);
    rmSync(join(scratch, 'cc0.misnamed.json'));
    writeFileSync(join(scratch, `${source.entry.set_id}.json`), formatLibrarySource(entry));
    writeFileSync(join(scratch, 'notes.txt'), 'a note');
    expect(() => readLibrary(scratch)).toThrow('is not a library entry');
    rmSync(join(scratch, 'notes.txt'));
    const [read] = readLibrary(scratch);
    expect(read!.entry).toEqual(source.entry);
    expect(read!.maker).toBe(source.maker);
    expect(Object.isFrozen(read!.entry.recipe.parameters)).toBe(true);
  });

  it('refuses an empty library', () => {
    scratch = mkdtempSync(join(tmpdir(), 'loom-library-'));
    expect(() => readLibrary(scratch)).toThrow('holds no library entries');
  });

  it('keeps one layout: scalar lists on a line, everything else indented', () => {
    expect(formatLibrarySource({ a: [1, 2], b: { c: [[1, 2, 3]], d: {} }, e: [] })).toBe(
      '{\n  "a": [1, 2],\n  "b": {\n    "c": [\n      [1, 2, 3]\n    ],\n    "d": {}\n  },\n  "e": []\n}\n',
    );
  });
});
