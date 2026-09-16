import { LIBRARY } from '../catalog.js';

/**
 * A dataset plan: the whole specification of a synthetic training set, as data.
 *
 * Pairs of (picture, recipe) for a future model that proposes a recipe from a picture. Every
 * recipe is a published recipe varied within its maker's own rules and baked by the maker itself;
 * every picture is that bake, lit and cropped. Nothing is observed: no photograph, scan or
 * download goes in, and the manifest the export writes says `"truth": "invented"`.
 *
 * The plan is canonical JSON with a profile, like every other object here. Its digest is the
 * dataset's identity together with the three generator versions below; the same plan and the
 * same versions give the same bytes on any machine.
 */
export const PLAN_PROFILE = 'exulanica.texture-dataset-plan/v1';
export const DATASET_PROFILE = 'exulanica.texture-dataset/v1';
/** How a plan becomes recipes. Any change that moves a sampled value is a new sampler. */
export const SAMPLER = 'exulanica.texture-dataset-sampler/v1';
/** How a bake becomes a picture. Any change that moves a pixel is a new renderer. */
export const RENDERER = 'exulanica.texture-dataset-render/v1';

export interface Variation {
  /** How often, in thousandths, a control keeps its published value. */
  readonly keep_permille: number;
  /** How far an integer may move from its published value, in thousandths of its range. */
  readonly window_permille: number;
  /** How often, in thousandths, a choice keeps its published option. */
  readonly choice_keep_permille: number;
  /** How far a colour, or a whole palette, moves together, in sRGB steps. */
  readonly colour_shift: number;
  /** How far each channel moves on top of that, in sRGB steps. */
  readonly colour_jitter: number;
}

export interface Lighting {
  /**
   * How high the light sits: the height of its unit direction, in thousandths, from the lowest to
   * the highest allowed. Keeping it below 1000 keeps the light off the viewing axis, where a flat
   * polished surface would turn into one highlight.
   */
  readonly elevation_permille: readonly [number, number];
  readonly intensity_permille: readonly [number, number];
  readonly ambient_permille: readonly [number, number];
  /** Per-channel gain, a slight colour cast, in thousandths. */
  readonly gain_permille: readonly [number, number];
}

export interface DatasetPlan {
  readonly profile: typeof PLAN_PROFILE;
  readonly name: string;
  readonly seed: number;
  /** Published set ids whose recipes are varied, in the order records are written. */
  readonly sets: readonly string[];
  readonly records_per_set: number;
  /** Texels along a baked tile's longer side, a power of two. */
  readonly bake_size: number;
  /** Pixels along each side of a picture, a power of two no larger than `bake_size`. */
  readonly image_size: number;
  /** Tries per record before the plan is declared unsatisfiable. */
  readonly attempts: number;
  readonly variation: Variation;
  readonly lighting: Lighting;
}

const NAME = /^[a-z][a-z0-9.-]*$/;
const PLAN_KEYS = [
  'profile',
  'name',
  'seed',
  'sets',
  'records_per_set',
  'bake_size',
  'image_size',
  'attempts',
  'variation',
  'lighting',
];
const VARIATION_KEYS = [
  'keep_permille',
  'window_permille',
  'choice_keep_permille',
  'colour_shift',
  'colour_jitter',
];
const LIGHTING_KEYS = [
  'elevation_permille',
  'intensity_permille',
  'ambient_permille',
  'gain_permille',
];

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const isInteger = (value: unknown, low: number, high: number): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= low && value <= high;
const isPowerOfTwo = (value: number): boolean => value > 0 && (value & (value - 1)) === 0;

function sameKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const present = Object.keys(value).sort();
  const wanted = [...keys].sort();
  return present.length === wanted.length && present.every((key, index) => key === wanted[index]);
}

function isRange(value: unknown, low: number, high: number): boolean {
  return Array.isArray(value)
    && value.length === 2
    && isInteger(value[0], low, high)
    && isInteger(value[1], low, high)
    && value[0] <= value[1];
}

/** Why `candidate` is not a dataset plan this package can export, or an empty list. */
export function planProblems(candidate: unknown): string[] {
  if (!isObject(candidate) || !sameKeys(candidate, PLAN_KEYS)) {
    return [`a dataset plan has exactly ${PLAN_KEYS.join(', ')}`];
  }
  const problems: string[] = [];
  if (candidate.profile !== PLAN_PROFILE) problems.push(`profile is ${PLAN_PROFILE}`);
  if (typeof candidate.name !== 'string' || !NAME.test(candidate.name)) {
    problems.push('name is lowercase letters, digits, dots and hyphens, starting with a letter');
  }
  if (!isInteger(candidate.seed, 0, 0xffffffff)) problems.push('seed is an unsigned 32-bit integer');
  const published = new Set(LIBRARY.map((source) => source.entry.set_id));
  const sets = candidate.sets;
  if (!Array.isArray(sets) || sets.length === 0 || new Set(sets).size !== sets.length
    || !sets.every((setId) => typeof setId === 'string' && published.has(setId))) {
    problems.push('sets are distinct published set ids, at least one');
  }
  if (!isInteger(candidate.records_per_set, 1, 100_000)) {
    problems.push('records_per_set is from 1 to 100000');
  }
  const bake = candidate.bake_size;
  if (!isInteger(bake, 16, 1024) || !isPowerOfTwo(bake)) {
    problems.push('bake_size is a power of two from 16 to 1024');
  }
  const image = candidate.image_size;
  if (!isInteger(image, 8, 1024) || !isPowerOfTwo(image)
    || (isInteger(bake, 16, 1024) && image > bake)) {
    problems.push('image_size is a power of two from 8, no larger than bake_size');
  }
  if (!isInteger(candidate.attempts, 1, 1000)) problems.push('attempts is from 1 to 1000');
  const variation = candidate.variation;
  if (!isObject(variation) || !sameKeys(variation, VARIATION_KEYS)
    || !isInteger(variation.keep_permille, 0, 1000)
    || !isInteger(variation.window_permille, 0, 1000)
    || !isInteger(variation.choice_keep_permille, 0, 1000)
    || !isInteger(variation.colour_shift, 0, 255)
    || !isInteger(variation.colour_jitter, 0, 255)) {
    problems.push(
      `variation has exactly ${VARIATION_KEYS.join(', ')}: thousandths, and sRGB steps to 255`,
    );
  }
  const lighting = candidate.lighting;
  if (!isObject(lighting) || !sameKeys(lighting, LIGHTING_KEYS)
    || !isRange(lighting.elevation_permille, 1, 1000)
    || !isRange(lighting.intensity_permille, 0, 4000)
    || !isRange(lighting.ambient_permille, 0, 1000)
    || !isRange(lighting.gain_permille, 500, 1500)) {
    problems.push(
      `lighting has exactly ${LIGHTING_KEYS.join(', ')}: low-high ranges in thousandths, the `
        + 'elevation within 1 to 1000',
    );
  }
  return problems;
}

/** Refuse, naming every problem, or return the plan typed. */
export function checkPlan(candidate: unknown): DatasetPlan {
  const problems = planProblems(candidate);
  if (problems.length > 0) throw new Error(`not a dataset plan: ${problems.join('; ')}`);
  return candidate as DatasetPlan;
}
