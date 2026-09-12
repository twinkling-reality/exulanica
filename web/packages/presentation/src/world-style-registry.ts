import type {
  WorldStyleCatalog,
  WorldStyleParameterDefinition,
  WorldStyleParameterValue,
  WorldStyleReference,
} from '@exulanica/atlas-core';
import { assertWorldStyleControlManifest } from './world-style-capabilities.js';
import { createWorldArtProfile, type WorldArtProfile } from './world-style-model.js';
import type { WorldStyleModule } from './world-style-modules.js';
import type { WorldStyleRecipeV1 } from './world-style-recipes.js';

export type WorldStyleParameters = Readonly<Record<string, WorldStyleParameterValue>>;

export interface WorldStyleRegistryOptions {
  readonly recipes: readonly WorldStyleRecipeV1[];
  readonly modules: readonly WorldStyleModule[];
  readonly defaultProfile: WorldStyleReference;
}

const profileKey = (profileId: string, profileVersion: number): string =>
  `${profileId}@${profileVersion}`;

function deepFreeze<T>(value: T): T {
  if (typeof value !== 'object' || value === null || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}

function validateRecipeShape(recipe: WorldStyleRecipeV1): void {
  if (recipe.schemaVersion !== 1) throw new TypeError('unsupported world style recipe schema');
  if (recipe.availability !== 'product' && recipe.availability !== 'developer') {
    throw new TypeError(`invalid world style availability: ${recipe.profile.profileId}`);
  }
  if (recipe.origin !== 'authored' && recipe.origin !== 'generated') {
    throw new TypeError(`invalid world style origin: ${recipe.profile.profileId}`);
  }
  if (recipe.modules.length === 0) {
    throw new TypeError(`world style has no capability modules: ${recipe.profile.profileId}`);
  }
  createWorldArtProfile(recipe.profile);
  assertWorldStyleControlManifest(recipe.controls);
}

function resolveParameters(
  controls: readonly WorldStyleParameterDefinition[],
  supplied: Readonly<Record<string, unknown>>,
): WorldStyleParameters {
  const values: Record<string, WorldStyleParameterValue> = {};
  for (const control of controls) {
    const candidate = supplied[control.key];
    values[control.key] = control.kind === 'range' && typeof candidate === 'number' && Number.isFinite(candidate)
      ? Math.max(control.min, Math.min(control.max, candidate))
      : control.kind === 'choice' && typeof candidate === 'string' && control.options.some((option) => option.value === candidate)
        ? candidate
        : control.kind === 'color' && typeof candidate === 'string' && /^#[0-9a-f]{6}$/i.test(candidate)
          ? candidate
          : control.kind === 'toggle' && typeof candidate === 'boolean'
            ? candidate
            : control.defaultValue;
  }
  return Object.freeze(values);
}

/**
 * Validates serialized recipes once, then compiles them through reviewed local modules. The
 * registry does not know any profile IDs and therefore needs no branching when styles are added.
 */
export class WorldStyleRegistry {
  readonly #recipes: ReadonlyMap<string, WorldStyleRecipeV1>;
  readonly #modules: ReadonlyMap<string, WorldStyleModule>;
  readonly #baseProfiles: ReadonlyMap<string, WorldArtProfile>;
  readonly #defaultKey: string;

  constructor(options: WorldStyleRegistryOptions) {
    const modules = new Map<string, WorldStyleModule>();
    for (const module of options.modules) {
      if (modules.has(module.moduleId)) throw new TypeError(`duplicate world style module: ${module.moduleId}`);
      if (!/^[a-z][a-z0-9-]*-v[1-9][0-9]*$/.test(module.moduleId)) {
        throw new TypeError(`invalid world style module ID: ${module.moduleId}`);
      }
      modules.set(module.moduleId, module);
    }

    const recipes = new Map<string, WorldStyleRecipeV1>();
    const baseProfiles = new Map<string, WorldArtProfile>();
    for (const input of options.recipes) {
      validateRecipeShape(input);
      const key = profileKey(input.profile.profileId, input.profile.profileVersion);
      if (recipes.has(key)) throw new TypeError(`duplicate world style recipe: ${key}`);

      const selectedCapabilities = new Set<string>();
      const selectedModules = new Set<string>();
      for (const moduleId of input.modules) {
        if (selectedModules.has(moduleId)) throw new TypeError(`duplicate module ${moduleId} in ${key}`);
        selectedModules.add(moduleId);
        const module = modules.get(moduleId);
        if (module === undefined) throw new TypeError(`unknown world style module ${moduleId} in ${key}`);
        for (const capability of module.capabilities) {
          if (selectedCapabilities.has(capability)) {
            throw new TypeError(`multiple modules own ${capability} in ${key}`);
          }
          selectedCapabilities.add(capability);
        }
      }

      const controlCapabilities = new Set(input.controls.map((control) => control.capability));
      for (const capability of controlCapabilities) {
        if (!selectedCapabilities.has(capability)) {
          throw new TypeError(`no selected module owns ${capability} in ${key}`);
        }
      }
      for (const capability of selectedCapabilities) {
        if (!controlCapabilities.has(capability)) {
          throw new TypeError(`module capability ${capability} has no control in ${key}`);
        }
      }

      for (const historical of input.readCompatibleBindings ?? []) {
        const capabilities = new Set<string>();
        const seenModules = new Set<string>();
        for (const moduleId of historical.modules) {
          const module = modules.get(moduleId);
          if (module === undefined || !selectedModules.has(moduleId) || seenModules.has(moduleId)) {
            throw new TypeError(`invalid historical module ${moduleId} in ${key}`);
          }
          seenModules.add(moduleId);
          for (const capability of module.capabilities) capabilities.add(capability);
        }
        const expected = Object.fromEntries(input.controls
          .filter(control => capabilities.has(control.capability))
          .map(control => [control.key, control.capability]));
        if (seenModules.size === 0 || Object.keys(expected).length !== capabilities.size ||
          Object.keys(historical.capabilityMapping).length !== capabilities.size ||
          Object.entries(expected).some(([name, capability]) => historical.capabilityMapping[name] !== capability)) {
          throw new TypeError(`invalid historical capability mapping in ${key}`);
        }
      }

      const recipe = deepFreeze(structuredClone(input));
      recipes.set(key, recipe);
      baseProfiles.set(key, createWorldArtProfile(recipe.profile));
    }

    const defaultKey = profileKey(
      options.defaultProfile.profileId,
      options.defaultProfile.profileVersion,
    );
    const defaultRecipe = recipes.get(defaultKey);
    if (defaultRecipe === undefined) throw new TypeError(`missing default world style recipe: ${defaultKey}`);
    if (defaultRecipe.availability !== 'product') {
      throw new TypeError(`default world style must be available to the product: ${defaultKey}`);
    }

    this.#recipes = recipes;
    this.#modules = modules;
    this.#baseProfiles = baseProfiles;
    this.#defaultKey = defaultKey;
  }

  recipe(profileId: string, profileVersion = 1): WorldStyleRecipeV1 | null {
    return this.#recipes.get(profileKey(profileId, profileVersion)) ?? null;
  }

  productRecipes(): readonly WorldStyleRecipeV1[] {
    return Object.freeze([...this.#recipes.values()].filter((recipe) => recipe.availability === 'product'));
  }

  controls(profileId: string, profileVersion = 1): readonly WorldStyleParameterDefinition[] {
    return (this.recipe(profileId, profileVersion) ?? this.#recipes.get(this.#defaultKey)!).controls;
  }

  resolveParameters(
    profileId: string,
    profileVersion = 1,
    supplied: Readonly<Record<string, unknown>> = {},
  ): WorldStyleParameters {
    return resolveParameters(this.controls(profileId, profileVersion), supplied);
  }

  profile(
    profileId: string,
    profileVersion = 1,
    supplied?: Readonly<Record<string, unknown>>,
  ): WorldArtProfile {
    const key = profileKey(profileId, profileVersion);
    const recipe = this.#recipes.get(key);
    if (recipe === undefined) return this.#baseProfiles.get(this.#defaultKey)!;
    if (supplied === undefined) return this.#baseProfiles.get(key)!;

    const parameters = resolveParameters(recipe.controls, supplied);
    const valuesByCapability = new Map<string, WorldStyleParameterValue>();
    for (const control of recipe.controls) {
      valuesByCapability.set(control.capability, parameters[control.key]!);
    }
    let source = recipe.profile;
    for (const moduleId of recipe.modules) {
      source = this.#modules.get(moduleId)!.apply(source, valuesByCapability);
    }
    return createWorldArtProfile(source);
  }

  catalog(): WorldStyleCatalog {
    const profiles = [...this.#recipes.values()].map((recipe) => Object.freeze({
      profileId: recipe.profile.profileId,
      profileVersion: recipe.profile.profileVersion,
      displayName: recipe.profile.displayName,
      description: recipe.profile.description,
      controls: recipe.controls,
    }));
    const defaultRecipe = this.#recipes.get(this.#defaultKey)!;
    return Object.freeze({
      defaultProfile: Object.freeze({
        profileId: defaultRecipe.profile.profileId,
        profileVersion: defaultRecipe.profile.profileVersion,
      }),
      profiles: Object.freeze(profiles),
    });
  }
}
