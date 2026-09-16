import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { LICENCE_ID } from './licence.js';
import type { Maker } from './maker.js';
import { MAKERS } from './makers/index.js';
import { type Recipe, recipeProblems } from './recipe.js';
import { StrictJsonError, parseStrictJsonBytes } from './strict-json.js';

/**
 * The published library: which recipes are published sets, and under which names.
 *
 * Each set is one file in `library/`, named for its set id, holding the id, the version, a title
 * and summary for people, the licence, and the recipe in full. That file is the only place a
 * published set is stated; the bake reads it, checks the recipe against its maker's manifest, and
 * publishes the recipe, the entry and a receipt for the bake as objects of their own.
 *
 * A version is a bake input. Any change that alters a set's bytes (a recipe value, a maker's code,
 * the container, the bake itself) must bump that set's version, because the pin a migration holds
 * is (set id, version) -> digest and a pinned pair never names new bytes. A new version also needs
 * a new migration row; `tests/test_texture_set_migration.py` fails until both agree.
 *
 * The files are JSON as people edit it, not canonical JSON: `formatLibrarySource` is the one
 * layout they are kept in, and the published objects are canonical whatever the layout. They are
 * read strictly (`strict-json.ts`), so a number written `1.0` is refused rather than read as 1.
 */
export const LIBRARY_PACKAGE = '@exulanica/loom-texture';
export const LIBRARY_FOLDER = 'library';
/** Identical to `asset_key` in migration 0042, and to `set_id` in migration 0065. */
export const SET_ID_PATTERN = /^[a-z][a-z0-9.-]*$/;
/** A set id names a surface. It never carries a version or a digest. */
export const VERSIONED_OR_DIGESTED = /v\d|[0-9a-f]{16}/;

export interface LibraryEntry {
  readonly set_id: string;
  readonly version: number;
  readonly title: string;
  readonly summary: string;
  readonly licence_id: string;
  readonly recipe: Recipe;
}

/** A library entry and the maker its recipe names, checked against each other. */
export interface LibrarySet {
  readonly entry: LibraryEntry;
  readonly maker: Maker;
}

const ENTRY_KEYS = ['set_id', 'version', 'title', 'summary', 'licence_id', 'recipe'];
const PRINTABLE = /^[\x20-\x7e]*$/;

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string =>
  typeof value === 'string' && value.trim() !== '' && PRINTABLE.test(value);

/**
 * This package's root, found by walking up to its own package.json, so the library resolves the
 * same from `src/` under tsx as from `dist/src/` after tsc.
 */
export function packageRoot(): string {
  let directory = dirname(fileURLToPath(import.meta.url));
  for (;;) {
    const manifest = join(directory, 'package.json');
    if (existsSync(manifest)
      && (JSON.parse(readFileSync(manifest, 'utf8')) as { name?: unknown }).name === LIBRARY_PACKAGE) {
      return directory;
    }
    const parent = dirname(directory);
    if (parent === directory) throw new Error(`no ${LIBRARY_PACKAGE} package.json above this module`);
    directory = parent;
  }
}

/** Why `candidate` is not a library entry, or an empty list. The recipe is checked in full. */
export function libraryEntryProblems(candidate: unknown): string[] {
  if (!isObject(candidate)) return ['a library entry is an object'];
  const present = Object.keys(candidate).sort();
  const wanted = [...ENTRY_KEYS].sort();
  if (present.length !== wanted.length || present.some((key, index) => key !== wanted[index])) {
    return [`a library entry has exactly ${ENTRY_KEYS.join(', ')}`];
  }
  const problems: string[] = [];
  const { set_id: setId, version, title, summary, licence_id: licenceId, recipe } = candidate;
  if (typeof setId !== 'string' || !SET_ID_PATTERN.test(setId) || VERSIONED_OR_DIGESTED.test(setId)) {
    problems.push('set_id names a surface: ^[a-z][a-z0-9.-]*$, with no version or digest in it');
  }
  if (typeof version !== 'number' || !Number.isSafeInteger(version) || version < 1) {
    problems.push('version is a positive integer');
  }
  if (!isText(title) || !isText(summary)) problems.push('title and summary are non-empty printable ASCII');
  if (licenceId !== LICENCE_ID) problems.push(`licence_id is ${LICENCE_ID}`);
  const named = isObject(recipe) && isObject(recipe.maker) ? recipe.maker : undefined;
  const maker = MAKERS.find(
    (candidateMaker) => named !== undefined
      && candidateMaker.manifest.maker_id === named.id
      && candidateMaker.manifest.version === named.version,
  );
  if (maker === undefined) {
    problems.push('recipe names a maker id and version this package has');
  } else {
    problems.push(...recipeProblems(recipe, maker.manifest).map((problem) => `recipe: ${problem}`));
  }
  return problems;
}

function deepFreeze<T>(value: T): T {
  if (typeof value === 'object' && value !== null) {
    for (const item of Object.values(value)) deepFreeze(item);
    Object.freeze(value);
  }
  return value;
}

/** Every entry in the library directory, checked, frozen and sorted by set id; or a refusal. */
export function readLibrary(directory: string = join(packageRoot(), LIBRARY_FOLDER)): readonly LibrarySet[] {
  const sets: LibrarySet[] = [];
  for (const name of readdirSync(directory).sort()) {
    const path = join(directory, name);
    if (!name.endsWith('.json')) throw new Error(`${path} is not a library entry; refusing`);
    let candidate: unknown;
    try {
      candidate = parseStrictJsonBytes(new Uint8Array(readFileSync(path)));
    } catch (error) {
      if (error instanceof StrictJsonError) throw new Error(`${path}: ${error.message}`);
      throw error;
    }
    const problems = libraryEntryProblems(candidate);
    if (problems.length > 0) throw new Error(`${path}: ${problems.join('; ')}`);
    const entry = deepFreeze(candidate as LibraryEntry);
    if (name !== `${entry.set_id}.json`) throw new Error(`${path} must be named ${entry.set_id}.json`);
    const maker = MAKERS.find(
      (candidateMaker) => candidateMaker.manifest.maker_id === entry.recipe.maker.id
        && candidateMaker.manifest.version === entry.recipe.maker.version,
    )!;
    sets.push({ entry, maker });
  }
  if (sets.length === 0) throw new Error(`${directory} holds no library entries`);
  return Object.freeze(sets);
}

function formatValue(value: unknown, indent: string): string {
  if (Array.isArray(value)) {
    if (value.every((item) => !Array.isArray(item) && !isObject(item))) {
      return `[${value.map((item) => JSON.stringify(item)).join(', ')}]`;
    }
    const inner = `${indent}  `;
    return `[\n${value.map((item) => `${inner}${formatValue(item, inner)}`).join(',\n')}\n${indent}]`;
  }
  if (isObject(value)) {
    const inner = `${indent}  `;
    const members = Object.entries(value).map(
      ([key, item]) => `${inner}${JSON.stringify(key)}: ${formatValue(item, inner)}`,
    );
    return members.length === 0 ? '{}' : `{\n${members.join(',\n')}\n${indent}}`;
  }
  return JSON.stringify(value);
}

/**
 * The one layout library files are kept in: two-space indentation, keys in the order given, and a
 * list of scalars (a colour, a list of positions) on one line. Ends with a newline.
 */
export function formatLibrarySource(value: unknown): string {
  return `${formatValue(value, '')}\n`;
}
