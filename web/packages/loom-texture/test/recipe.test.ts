import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';
import { canonicalJson } from '../src/canonical-json.js';
import { LIBRARY } from '../src/catalog.js';
import {
  formatLibrarySource,
  libraryEntryProblems,
  readLibrary,
} from '../src/library.js';
import { MAKERS, makerFor } from '../src/makers/index.js';
import {
  type MakerManifest,
  type Recipe,
  checkRecipe,
  defaultRecipe,
  evaluate,
  manifestProblems,
  recipeProblems,
} from '../src/recipe.js';

/**
 * Recipes and maker manifests are data, and data is checked.
 *
 * The shared cases in `recipe-cases.json` are the specification both validators are held to: this
 * file runs them against `src/recipe.ts`, and `tests/test_material_objects.py` runs the same file
 * against `exulanica.materials`. A case lists the exact problems, in order, so the two languages
 * cannot drift into refusing different objects or explaining a refusal differently.
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

const CASES_PATH = fileURLToPath(new URL('./recipe-cases.json', import.meta.url));
const CASES_TEXT = readFileSync(CASES_PATH, 'utf8');
const CASES = JSON.parse(CASES_TEXT) as {
  readonly recipes: readonly RecipeCase[];
  readonly manifests: readonly ManifestCase[];
};

/** Apply changes to a copy. The same rules as `_apply_changes` in the backend's test. */
function applyChanges(base: unknown, changes: readonly Change[]): unknown {
  let root: unknown = structuredClone(base);
  for (const change of changes) {
    const keys = Object.keys(change).sort().join();
    if (keys !== 'path,value' && !(keys === 'path,remove' && change.remove === true)) {
      throw new Error(`a change has a path and either a value or remove: true, not ${keys}`);
    }
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
      if (typeof last !== 'number' || last > parent.length) throw new Error(`no index ${last}`);
      if (change.remove === true) parent.splice(last, 1);
      else parent[last] = structuredClone(change.value);
    } else if (change.remove === true) {
      if (!(last in parent)) throw new Error(`nothing to remove at ${String(last)}`);
      delete parent[last];
    } else {
      parent[last] = structuredClone(change.value);
    }
  }
  return root;
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

  it('write no number the two languages would read differently', () => {
    const outsideStrings = CASES_TEXT.replace(/"(?:[^"\\]|\\.)*"/g, '""');
    expect(outsideStrings).not.toMatch(/\d\.0+(?!\d)|\d[eE][+-]?\d/);
    expect([...CASES_TEXT].every((character) => character <= '\x7e')).toBe(true);
  });

  it('cover every maker and every set they name', () => {
    const sets = new Set(LIBRARY.map((source) => source.entry.set_id));
    for (const testCase of CASES.recipes) expect(sets).toContain(testCase.set);
    const names = [...CASES.recipes, ...CASES.manifests].map((testCase) => testCase.name);
    expect(new Set(names).size).toBe(names.length);
  });
});

describe('maker manifests', () => {
  it('are well formed, canonical, and sorted by id', () => {
    for (const maker of MAKERS) {
      expect(manifestProblems(maker.manifest), maker.manifest.maker_id).toEqual([]);
      expect(() => canonicalJson(maker.manifest)).not.toThrow();
    }
    const ids = MAKERS.map((maker) => maker.manifest.maker_id);
    expect(ids).toEqual([...ids].sort());
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('name each family once, so a family names its maker', () => {
    const families = MAKERS.map((maker) => maker.manifest.family);
    expect(new Set(families).size).toBe(families.length);
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
