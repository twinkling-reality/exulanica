import { describe, expect, it } from 'vitest';
import { DRAFTS, LIBRARY, definitionOf } from '../src/catalog.js';
import { SET_PROFILE_V1 } from '../src/classes.js';
import { encodeContainer, encodeContainerV2 } from '../src/container.js';
import type { LibrarySet } from '../src/library.js';
import { bakeClassMaps, bakeMaps, sampleFields } from '../src/maps.js';
import {
  type Control,
  type ParameterValue,
  type Recipe,
  recipeProblems,
} from '../src/recipe.js';
import { repairRecipe } from '../src/repair.js';
import { FIELD_NAMES, rollMismatches } from './support.js';

/**
 * Whatever a maker accepts, it can bake.
 *
 * A published recipe is one point in each maker's space. A person, or a model proposing recipes,
 * will reach the corners, so every control is pushed to each end of its range (and every choice to
 * each option) one at a time, on a small frame. The variant is then repaired the way a person
 * making that change would repair it (`src/repair.ts`): a count an `even` rule needs even is
 * raised by one, an extent a module rule pins is recomputed, and one a proportion rule pins is
 * divided out.
 * Every variant the validator accepts must bake without throwing, encode a canonical header, tile
 * by construction, and state each of its integer controls, if it states one at all, under that
 * control's own key with that control's value, which is what the backend checks a header against.
 * Variants the validator refuses are counted, and most of each maker's corners must be reachable.
 * Draft makers, whose sets are not published yet, are held to all of this from their draft entries.
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

/** A variant on a small frame, repaired as `src/repair.ts` repairs one. */
function variant(source: LibrarySet, key: string, value: ParameterValue): Recipe {
  const base = source.entry.recipe;
  const { width, height } = base.resolution;
  const shorter = Math.min(width, height);
  return repairRecipe(source.maker, {
    ...base,
    resolution: { width: (width / shorter) * SIDE, height: (height / shorter) * SIDE },
    parameters: { ...base.parameters, [key]: value },
  });
}

/** Each stated integer control, under its own key, has the recipe's value. */
function checkStated(source: LibrarySet, recipe: Recipe, label: string): void {
  const stated = source.maker.stated(recipe);
  for (const control of source.maker.manifest.controls) {
    if (control.kind !== 'integer' || !(control.key in stated)) continue;
    expect(stated[control.key], `${label}: stated ${control.key}`).toBe(recipe.parameters[control.key]);
  }
}

function checkBakes(source: LibrarySet, recipe: Recipe, label: string): void {
  checkStated(source, recipe, label);
  const def = definitionOf({ ...source, entry: { ...source.entry, recipe } });
  if (def.containerProfile === SET_PROFILE_V1) {
    expect(() => encodeContainer(def, bakeMaps(def), '0'.repeat(64)), label).not.toThrow();
  } else {
    expect(() => encodeContainerV2(def, bakeClassMaps(def), '0'.repeat(64)), label).not.toThrow();
  }
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
  it('states its published recipes\' integer controls under their own keys, or not at all', () => {
    for (const source of [...LIBRARY, ...DRAFTS]) {
      checkStated(source, source.entry.recipe, source.entry.set_id);
    }
  });

  for (const source of [...LIBRARY, ...DRAFTS]) {
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
