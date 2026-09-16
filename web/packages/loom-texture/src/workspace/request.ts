import { canonicalBytes } from '../canonical-json.js';
import { sha256Hex } from '../digest.js';
import type { Maker } from '../maker.js';
import { MAKERS } from '../makers/index.js';
import { MAXIMUM_RESOLUTION, type Recipe, recipeProblems } from '../recipe.js';
import { WORKSPACE_LICENCE_ID } from './licence.js';

/**
 * A bake request: everything a workspace bake needs, as one canonical object.
 *
 * The backend's bake worker writes it, having already checked the recipe against the published
 * maker, and this package checks it again before it samples a texel. The worker decides every
 * word the header states: the set id (`ws.` and the recipe row's 32 hex digits), version 1, a title
 * and summary derived mechanically from the maker and the recipe digest, and the workspace licence
 * by id and digest. Nothing here writes prose.
 */
export const BAKE_REQUEST_PROFILE = 'exulanica.texture-bake-request/v1';
/** What the command prints once the container is written. */
export const BAKE_RESULT_PROFILE = 'exulanica.texture-bake-result/v1';
export const WORKSPACE_SET_ID = /^ws\.[0-9a-f]{32}$/;
export const WORKSPACE_VERSION = 1;
/** The most texels a workspace bake may hold: the published ceiling on both axes at once. */
export const MAXIMUM_WORKSPACE_TEXELS = MAXIMUM_RESOLUTION * MAXIMUM_RESOLUTION;
/** Longest title or summary, in characters. The backend derives both and stays well inside. */
export const MAXIMUM_TEXT = 200;

export interface BakeRequest {
  readonly profile: typeof BAKE_REQUEST_PROFILE;
  readonly set_id: string;
  readonly version: typeof WORKSPACE_VERSION;
  readonly title: string;
  readonly summary: string;
  readonly licence: { readonly id: typeof WORKSPACE_LICENCE_ID; readonly sha256: string };
  readonly maker_sha256: string;
  readonly recipe: Recipe;
}

export interface BakeResult {
  readonly profile: typeof BAKE_RESULT_PROFILE;
  readonly content_sha256: string;
  readonly byte_size: number;
  readonly runtime: { readonly node: string; readonly package_sha256: string };
}

const REQUEST_KEYS = [
  'profile',
  'set_id',
  'version',
  'title',
  'summary',
  'licence',
  'maker_sha256',
  'recipe',
];
const PRINTABLE = /^[\x20-\x7e]+$/;
const SHA256 = /^[0-9a-f]{64}$/;

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const has = (value: Record<string, unknown>, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(value, key);

function sameKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const present = Object.keys(value).sort();
  const wanted = [...keys].sort();
  return present.length === wanted.length && present.every((key, index) => key === wanted[index]);
}

const isText = (value: unknown): value is string =>
  typeof value === 'string'
  && PRINTABLE.test(value)
  && value.trim() === value
  && value.length <= MAXIMUM_TEXT;

/** The maker a request's recipe names, when this package has it. */
export function requestedMaker(candidate: unknown): Maker | undefined {
  if (!isObject(candidate) || !has(candidate, 'recipe') || !isObject(candidate.recipe)) return undefined;
  const named = candidate.recipe.maker;
  if (!isObject(named)) return undefined;
  return MAKERS.find(
    (maker) => maker.manifest.maker_id === named.id && maker.manifest.version === named.version,
  );
}

/** Why `candidate` is not a bake request this package will run, or an empty list. */
export function bakeRequestProblems(candidate: unknown, licenceSha256: string): string[] {
  if (!isObject(candidate) || !sameKeys(candidate, REQUEST_KEYS)) {
    return [`a bake request has exactly ${REQUEST_KEYS.join(', ')}`];
  }
  const problems: string[] = [];
  if (candidate.profile !== BAKE_REQUEST_PROFILE) problems.push(`profile is ${BAKE_REQUEST_PROFILE}`);
  if (typeof candidate.set_id !== 'string' || !WORKSPACE_SET_ID.test(candidate.set_id)) {
    problems.push('set_id is ws. and 32 lowercase hex digits');
  }
  if (candidate.version !== WORKSPACE_VERSION) problems.push(`version is ${WORKSPACE_VERSION}`);
  if (!isText(candidate.title) || !isText(candidate.summary)) {
    problems.push(`title and summary are printable ASCII, trimmed, 1 to ${MAXIMUM_TEXT} characters`);
  }
  const licence = candidate.licence;
  if (!isObject(licence) || !sameKeys(licence, ['id', 'sha256'])
    || licence.id !== WORKSPACE_LICENCE_ID || licence.sha256 !== licenceSha256) {
    problems.push(`licence is ${WORKSPACE_LICENCE_ID} with the digest of this package's text`);
  }
  if (typeof candidate.maker_sha256 !== 'string' || !SHA256.test(candidate.maker_sha256)) {
    problems.push('maker_sha256 is 64 lowercase hex digits');
  }
  const maker = requestedMaker(candidate);
  if (maker === undefined) {
    problems.push('recipe names a maker id and version this package has');
    return problems;
  }
  if (sha256Hex(canonicalBytes(maker.manifest)) !== candidate.maker_sha256) {
    problems.push('maker_sha256 is not the manifest this package would bake with');
  }
  const recipeIssues = recipeProblems(candidate.recipe, maker.manifest);
  problems.push(...recipeIssues.map((problem) => `recipe: ${problem}`));
  if (recipeIssues.length === 0) {
    const { width, height } = (candidate.recipe as unknown as Recipe).resolution;
    if (width * height > MAXIMUM_WORKSPACE_TEXELS) {
      problems.push(`recipe: a workspace bake holds at most ${MAXIMUM_WORKSPACE_TEXELS} texels`);
    }
  }
  return problems;
}
