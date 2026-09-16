import { hash3, pick } from '../hash.js';
import { clamp, floorDiv } from '../integer.js';
import type { LibrarySet } from '../library.js';
import { type Control, type ParameterValue, type Recipe, recipeProblems } from '../recipe.js';
import { repairRecipe } from '../repair.js';
import type { DatasetPlan, Variation } from './plan.js';

/**
 * Recipes for a dataset: a published recipe, varied within its maker's rules.
 *
 * Every draw is a hash of (slot, attempt, purpose) under the record's own seed, so a record's
 * recipe depends on nothing but the plan and its index, and adding a control to one maker moves
 * no value another control already had. A control keeps its published value some of the time and
 * otherwise moves within a window of its range around that value; colours move together and then
 * a little per channel, so a brick stays a brick-coloured brick. The varied recipe is repaired as a
 * person would repair it (`repair.ts`), framed at the plan's bake size, and checked by the same
 * validator every recipe passes. A refused attempt is counted and retried with the next attempt
 * number, and a plan whose variation no attempt satisfies is refused rather than thinned out.
 */
const SEED_SLOT = 1_000_000;
/** Slots at and above this one belong to the view and the light (see `render.ts`). */
export const VIEW_SLOT = 1_000_001;
export const LIGHT_SLOT = 1_000_002;

const KEEP = 1;
const VALUE = 2;
const SHIFT = 3;
const CHANNEL = 4;
/** List items take purposes from here up, eight per item. */
const ITEM = 16;

/** An integer in [low, high] from a 32-bit hash, exact for any span below 2^21. */
export function pickWide(h: number, low: number, high: number): number {
  return low + Math.floor((h * (high - low + 1)) / 4294967296);
}

type Draw = (purpose: number) => number;

function varyInteger(
  minimum: number,
  maximum: number,
  base: number,
  keep: number,
  value: number,
  variation: Variation,
): number {
  if (pick(keep, 0, 999) < variation.keep_permille) return base;
  const window = floorDiv((maximum - minimum) * variation.window_permille, 1000);
  return pickWide(value, Math.max(minimum, base - window), Math.min(maximum, base + window));
}

function varyColour(
  base: readonly number[],
  shift: number,
  draw: Draw,
  first: number,
  variation: Variation,
): [number, number, number] {
  const channel = (index: number): number =>
    clamp(
      base[index]! + shift
        + pickWide(draw(first + index), -variation.colour_jitter, variation.colour_jitter),
      0,
      255,
    );
  return [channel(0), channel(1), channel(2)];
}

function vary(control: Control, base: ParameterValue, draw: Draw, variation: Variation): ParameterValue {
  switch (control.kind) {
    case 'integer':
      return varyInteger(
        control.minimum,
        control.maximum,
        base as number,
        draw(KEEP),
        draw(VALUE),
        variation,
      );
    case 'integer_list':
      return (base as readonly number[]).map((item, index) =>
        varyInteger(
          control.minimum,
          control.maximum,
          item,
          draw(ITEM + index * 8),
          draw(ITEM + index * 8 + 1),
          variation,
        ),
      );
    case 'choice':
      return pick(draw(KEEP), 0, 999) < variation.choice_keep_permille
        ? base
        : control.options[pickWide(draw(VALUE), 0, control.options.length - 1)]!;
    case 'srgb': {
      if (pick(draw(KEEP), 0, 999) < variation.keep_permille) return base;
      const shift = pickWide(draw(SHIFT), -variation.colour_shift, variation.colour_shift);
      return varyColour(base as readonly number[], shift, draw, CHANNEL, variation);
    }
    case 'srgb_list': {
      if (pick(draw(KEEP), 0, 999) < variation.keep_permille) return base;
      const shift = pickWide(draw(SHIFT), -variation.colour_shift, variation.colour_shift);
      return (base as readonly (readonly number[])[]).map((colour, index) =>
        varyColour(colour, shift, draw, ITEM + index * 8 + 2, variation),
      );
    }
  }
}

/**
 * Texels for a tile: the plan's bake size along the longer extent, and along the shorter the
 * power of two, down to 16, that keeps texels closest to square.
 */
export function frameResolution(
  extent: { readonly u: number; readonly v: number },
  bakeSize: number,
): { width: number; height: number } {
  const longer = Math.max(extent.u, extent.v);
  const shorter = Math.min(extent.u, extent.v);
  let best = bakeSize;
  for (let texels = bakeSize; texels >= 16; texels = floorDiv(texels, 2)) {
    if (Math.abs(texels * longer - bakeSize * shorter) < Math.abs(best * longer - bakeSize * shorter)) {
      best = texels;
    }
  }
  return extent.u >= extent.v
    ? { width: bakeSize, height: best }
    : { width: best, height: bakeSize };
}

export interface SampledRecipe {
  readonly recipe: Recipe;
  /** Attempts used, the accepted one included. */
  readonly attempts: number;
}

/** The recipe for one record, or a refusal naming the set whose variation cannot be satisfied. */
export function sampleRecipe(
  plan: DatasetPlan,
  source: LibrarySet,
  recordSeed: number,
): SampledRecipe {
  const base = source.entry.recipe;
  const { manifest } = source.maker;
  for (let attempt = 0; attempt < plan.attempts; attempt += 1) {
    const parameters: Record<string, ParameterValue> = {};
    manifest.controls.forEach((control, slot) => {
      const draw: Draw = (purpose) => hash3(slot, attempt, purpose, recordSeed);
      parameters[control.key] = vary(control, base.parameters[control.key]!, draw, plan.variation);
    });
    const varied = repairRecipe(source.maker, {
      ...base,
      seed: hash3(SEED_SLOT, attempt, 0, recordSeed),
      parameters,
    });
    const recipe: Recipe = {
      ...varied,
      resolution: frameResolution(varied.extent_mm, plan.bake_size),
    };
    if (recipeProblems(recipe, manifest).length === 0) return { recipe, attempts: attempt + 1 };
  }
  throw new Error(
    `${source.entry.set_id}: no attempt of ${plan.attempts} gave a valid recipe; the plan's `
      + 'variation is wider than this maker allows',
  );
}
