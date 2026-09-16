import { describe, expect, it } from 'vitest';
import { LIBRARY, definitionOf } from '../src/catalog.js';
import { encodeContainer } from '../src/container.js';
import type { LibrarySet } from '../src/library.js';
import { bakeMaps, sampleFields } from '../src/maps.js';
import {
  type Control,
  type Expression,
  type ParameterValue,
  type Recipe,
  evaluate,
  recipeProblems,
} from '../src/recipe.js';
import { FIELD_NAMES, rollMismatches } from './support.js';

/**
 * Whatever a maker accepts, it can bake.
 *
 * A published recipe is one point in each maker's space. A person, or a model proposing recipes,
 * will reach the corners, so every control is pushed to each end of its range (and every choice to
 * each option) one at a time, on a small frame. Where a change breaks a module equality, the
 * extent is repaired from the equality, because that is what a person changing a brick's length
 * would also change. Every variant the validator accepts must then bake without throwing, encode
 * into a canonical header, and tile by construction. Variants the validator refuses are counted,
 * and most of each maker's corners must be reachable, or the sweep proves little.
 */
const SIDE = 32;
const SHIFT: readonly [number, number] = [-SIDE - 5, 2 * SIDE + 3];

function extremes(control: Control): ParameterValue[] {
  switch (control.kind) {
    case 'integer':
      return [control.minimum, control.maximum];
    case 'integer_list':
      return [
        Array.from({ length: Math.max(1, control.minimum_items) }, () => control.minimum),
        Array.from({ length: control.maximum_items }, () => control.maximum),
      ];
    case 'choice':
      return [...control.options];
    case 'srgb':
      return [
        [0, 0, 0],
        [255, 255, 255],
      ];
    case 'srgb_list':
      return [
        Array.from({ length: control.minimum_items }, () => [0, 0, 0] as const),
        Array.from({ length: control.maximum_items }, () => [255, 255, 255] as const),
      ];
  }
}

const mentionsExtent = (expression: Expression): boolean =>
  'extent' in expression
  || ('sum' in expression && expression.sum.some(mentionsExtent))
  || ('product' in expression && expression.product.some(mentionsExtent));

/** A variant on a small frame, with each extent a module equality pins recomputed. */
function variant(source: LibrarySet, key: string, value: ParameterValue): Recipe {
  const base = source.entry.recipe;
  const { width, height } = base.resolution;
  const shorter = Math.min(width, height);
  const draft: Recipe = {
    ...base,
    resolution: { width: (width / shorter) * SIDE, height: (height / shorter) * SIDE },
    parameters: { ...base.parameters, [key]: value },
  };
  const extent = { ...draft.extent_mm };
  for (const constraint of source.maker.manifest.constraints) {
    if (constraint.kind !== 'equal' || !('extent' in constraint.right)) continue;
    if (mentionsExtent(constraint.left)) continue;
    const pinned = evaluate(constraint.left, draft);
    if (pinned !== null && pinned > 0) extent[constraint.right.extent] = pinned;
  }
  return { ...draft, extent_mm: extent };
}

function checkBakes(source: LibrarySet, recipe: Recipe, label: string): void {
  const def = definitionOf({ ...source, entry: { ...source.entry, recipe } });
  const maps = bakeMaps(def);
  expect(() => encodeContainer(def, maps, '0'.repeat(64)), label).not.toThrow();
  const [du, dv] = SHIFT;
  const base = sampleFields(def);
  const shifted = sampleFields(def, { offsetU: du, offsetV: dv });
  const planes = Object.fromEntries(
    FIELD_NAMES.map((name) => [name, [base[name], shifted[name], 1] as const]),
  );
  expect(rollMismatches(def.width, def.height, planes, du, dv), label).toEqual(
    Object.fromEntries(FIELD_NAMES.map((name) => [name, 0])),
  );
}

describe('every maker bakes whatever it accepts', () => {
  for (const source of LIBRARY) {
    const { manifest } = source.maker;
    it(`${manifest.maker_id}, at the corners of every control`, () => {
      let baked = 0;
      const refused: string[] = [];
      for (const control of manifest.controls) {
        for (const value of extremes(control)) {
          const recipe = variant(source, control.key, value);
          const label = `${manifest.maker_id} ${control.key} = ${JSON.stringify(value)}`;
          const problems = recipeProblems(recipe, manifest);
          if (problems.length > 0) {
            refused.push(`${label}: ${problems.join('; ')}`);
            continue;
          }
          checkBakes(source, recipe, label);
          baked += 1;
        }
      }
      expect(baked, refused.join('\n')).toBeGreaterThanOrEqual(0.75 * (baked + refused.length));
    }, 120_000);
  }
});
