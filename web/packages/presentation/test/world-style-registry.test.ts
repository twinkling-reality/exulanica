import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  WORLD_STYLE_MODULES,
  WORLD_STYLE_RECIPES,
  WorldStyleRegistry,
  productWorldStyleIds,
  type WorldStyleRecipeV1,
} from '../src/world-profiles.js';

const registryFrom = (recipes: readonly WorldStyleRecipeV1[]): WorldStyleRegistry =>
  new WorldStyleRegistry({
    recipes,
    modules: WORLD_STYLE_MODULES,
    defaultProfile: { profileId: 'origin-landscape', profileVersion: 1 },
  });

describe('world style recipe registry', () => {
  it('round trips recipes as inert JSON and compiles the same profiles', () => {
    const serialized = JSON.stringify(WORLD_STYLE_RECIPES);
    expect(serialized).not.toContain('function');
    const recipes = JSON.parse(serialized) as WorldStyleRecipeV1[];
    const registry = registryFrom(recipes);
    const supplied = {
      vitality: 0.2,
      glass: 0.9,
      'relationship-energy': 0.4,
      'garden-density': 0.3,
      'horizon-softness': 0.7,
      'surface-finish': 'clear-lens',
      'world-tempo': 1.25,
    };
    expect(registry.profile('origin-landscape', 1, supplied)).toEqual(
      registryFrom(WORLD_STYLE_RECIPES).profile('origin-landscape', 1, supplied),
    );
  });

  it('keeps developer comparison recipes out of product preferences', () => {
    expect(productWorldStyleIds()).toEqual(['origin-landscape']);
    expect(registryFrom(WORLD_STYLE_RECIPES).recipe('survey-relief')?.availability).toBe('developer');
  });

  it('makes every advertised developer control materially resolve through its module', () => {
    const registry = registryFrom(WORLD_STYLE_RECIPES);
    const low = registry.profile('survey-relief', 1, {
      'contour-density': 0,
      'technical-contrast': 0,
    });
    const high = registry.profile('survey-relief', 1, {
      'contour-density': 1,
      'technical-contrast': 1,
    });
    expect(low.geometry.detailCount).toBeLessThan(high.geometry.detailCount);
    expect(low.material.edgeStrength).toBeLessThan(high.material.edgeStrength);
    expect(low.palette.terrain).not.toBe(high.palette.terrain);
    expect(low.ui.colors).not.toEqual(high.ui.colors);
  });

  it('fails closed when a serialized recipe names unreviewed executable behavior', () => {
    const base = WORLD_STYLE_RECIPES[0]!;
    const invalid: WorldStyleRecipeV1 = { ...base, modules: ['unreviewed-module-v1'] };
    expect(() => registryFrom([invalid])).toThrow(/unknown world style module/);
  });

  it('fails closed when serialized visual data names an unregistered CSS treatment', () => {
    const base = WORLD_STYLE_RECIPES[0]!;
    const invalid = {
      ...base,
      profile: {
        ...base.profile,
        ui: {
          ...base.profile.ui,
          motion: { ...base.profile.ui.motion, easing: 'steps(400)' },
        },
      },
    } as WorldStyleRecipeV1;
    expect(() => registryFrom([invalid])).toThrow(/unregistered origin-landscape UI easing/);
  });

  it('rejects controls and modules whose capability contracts do not match exactly', () => {
    const base = WORLD_STYLE_RECIPES[0]!;
    const missingControl: WorldStyleRecipeV1 = {
      ...base,
      controls: base.controls.filter((control) => control.capability !== 'motion.tempo'),
    };
    expect(() => registryFrom([missingControl])).toThrow(/has no control/);
  });
});

// Read the independently maintained backend manifest. A catalog generated from the frontend
// under test cannot catch a missing module on the server.
it('matches every reviewed backend module and control contract', () => {
  const backend = JSON.parse(readFileSync(new URL(
    '../../../../exulanica/world/style-registry.v1.json', import.meta.url,
  ), 'utf8'));
  expect(backend.modules.map((module: { module_id: string; capabilities: string[] }) => ({
    moduleId: module.module_id, capabilities: [...module.capabilities].sort(),
  })).sort((a: { moduleId: string }, b: { moduleId: string }) => a.moduleId.localeCompare(b.moduleId)))
    .toEqual(WORLD_STYLE_MODULES.map(module => ({
      moduleId: module.moduleId, capabilities: [...module.capabilities].sort(),
    })).sort((a, b) => a.moduleId.localeCompare(b.moduleId)));
  for (const recipe of WORLD_STYLE_RECIPES) {
    const profile = backend.profiles.find((value: { profile_id: string; profile_version: number }) =>
      value.profile_id === recipe.profile.profileId && value.profile_version === recipe.profile.profileVersion);
    expect(profile.recipe.modules).toEqual(recipe.modules);
    expect(profile.recipe.availability).toBe(recipe.availability);
    expect(profile.recipe.origin).toBe(recipe.origin);
    const contract = (control: Record<string, unknown>) => {
      const { default_value, ...rest } = control;
      return default_value === undefined ? rest : { ...rest, defaultValue: default_value };
    };
    expect(profile.controls.map(contract)).toEqual(recipe.controls.map(control => contract({ ...control })));
  }
});


it('rejects historical bindings that invent modules or capability ownership', () => {
  for (const compatible of [
    { modules: ['unknown-module-v1'], capabilityMapping: {} },
    { modules: ['bounded-tempo-v1'], capabilityMapping: { 'world-tempo': 'world.vitality' } },
  ]) {
    const recipes = [...structuredClone(WORLD_STYLE_RECIPES)];
    recipes[0] = { ...recipes[0]!, readCompatibleBindings: [compatible] };
    expect(() => registryFrom(recipes)).toThrow(/historical/);
  }
});
