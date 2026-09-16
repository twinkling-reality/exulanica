import type { WorldStyleParameterDefinition } from '@exulanica/atlas-core';
import {
  MIN_SURFACE_PRESENCE,
  contrastRatio,
  deriveWorldUiColors,
  interfacePaletteFromWorld,
  mixHex,
  perceptualColour,
  worldSilhouetteTone,
  type WorldArtProfile,
  type WorldArtProfileSource,
  type WorldAtmosphereForm,
  type WorldInterfacePalette,
  type WorldPalette,
  type WorldSurfaceForm,
  type WorldUiColors,
  type WorldUiRecipe,
  type WorldUiStyle,
} from './world-style-model.js';
import {
  MEDIA_SAMPLE_EDGE,
  readSourceLight,
  sourceLightParameters,
  type MediaSample,
  type SourceLightReading,
} from './media-palette.js';
import { WORLD_STYLE_MODULES } from './world-style-modules.js';
import {
  WorldStyleRegistry,
  type WorldStyleParameters,
} from './world-style-registry.js';
import {
  WORLD_STYLE_RECIPES,
  WORLD_STYLE_REGISTRY_DOCUMENT,
  worldStyleControlFromDocument,
  type WorldArtAppearanceSource,
  type WorldStyleRecipeV1,
  type WorldStyleRegistryDocument,
} from './world-style-recipes.js';

export type WorldArtProfileId = string;
export type {
  MediaSample,
  SourceLightReading,
  WorldArtAppearanceSource,
  WorldArtProfile,
  WorldArtProfileSource,
  WorldAtmosphereForm,
  WorldInterfacePalette,
  WorldPalette,
  WorldSurfaceForm,
  WorldStyleParameters,
  WorldStyleRecipeV1,
  WorldStyleRegistryDocument,
  WorldUiColors,
  WorldUiRecipe,
  WorldUiStyle,
};
export {
  MEDIA_SAMPLE_EDGE,
  MIN_SURFACE_PRESENCE,
  WORLD_STYLE_MODULES,
  WORLD_STYLE_RECIPES,
  WORLD_STYLE_REGISTRY_DOCUMENT,
  WorldStyleRegistry,
  contrastRatio,
  deriveWorldUiColors,
  interfacePaletteFromWorld,
  mixHex,
  readSourceLight,
  sourceLightParameters,
  perceptualColour,
  worldSilhouetteTone,
  worldStyleControlFromDocument,
};

export const WORLD_STYLE_REGISTRY = new WorldStyleRegistry({
  recipes: WORLD_STYLE_RECIPES,
  modules: WORLD_STYLE_MODULES,
  defaultProfile: {
    profileId: WORLD_STYLE_REGISTRY_DOCUMENT.default_profile.profile_id,
    profileVersion: WORLD_STYLE_REGISTRY_DOCUMENT.default_profile.profile_version,
  },
});

/** The authored Aeroheart base and developer comparison stay topology-compatible. */
export const ORIGIN_LANDSCAPE = WORLD_STYLE_REGISTRY.profile('origin-landscape', 1);
export const SURVEY_RELIEF = WORLD_STYLE_REGISTRY.profile('survey-relief', 1);

export const WORLD_ART_PROFILES: Readonly<Record<string, WorldArtProfile>> = Object.freeze(
  Object.fromEntries(WORLD_STYLE_RECIPES.map((recipe) => [
    recipe.profile.profileId,
    WORLD_STYLE_REGISTRY.profile(recipe.profile.profileId, recipe.profile.profileVersion),
  ])),
);

export const DEFAULT_WORLD_ART_PROFILE = ORIGIN_LANDSCAPE;
export const WORLD_STYLE_CATALOG = WORLD_STYLE_REGISTRY.catalog();

export function worldStyleControls(
  id: string,
  version = 1,
): readonly WorldStyleParameterDefinition[] {
  return WORLD_STYLE_REGISTRY.controls(id, version);
}

export function resolveWorldStyleParameters(
  id: string,
  supplied: Readonly<Record<string, unknown>> = {},
  version = 1,
): WorldStyleParameters {
  return WORLD_STYLE_REGISTRY.resolveParameters(id, version, supplied);
}

export function worldArtProfile(
  id: string,
  version = 1,
  supplied?: Readonly<Record<string, unknown>>,
): WorldArtProfile {
  return WORLD_STYLE_REGISTRY.profile(id, version, supplied);
}

export function worldStyleRecipe(id: string, version = 1): WorldStyleRecipeV1 | null {
  return WORLD_STYLE_REGISTRY.recipe(id, version);
}

export function productWorldStyleIds(): readonly string[] {
  return Object.freeze(WORLD_STYLE_REGISTRY.productRecipes().map((recipe) => recipe.profile.profileId));
}

export function productWorldStyleReferences(): readonly Readonly<{
  profileId: string;
  profileVersion: number;
}>[] {
  return Object.freeze(WORLD_STYLE_REGISTRY.productRecipes().map((recipe) => Object.freeze({
    profileId: recipe.profile.profileId,
    profileVersion: recipe.profile.profileVersion,
  })));
}
