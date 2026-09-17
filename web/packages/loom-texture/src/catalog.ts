import { join } from 'node:path';
import { RELIEF_CLASSES, SET_PROFILE_V1, SET_PROFILE_V2 } from './classes.js';
import { cavityOf, filmOf, heightRangeOf } from './controls.js';
import type { TextureSetDefinition } from './definition.js';
import { DRAFT_FOLDER, type LibrarySet, packageRoot, readLibrary } from './library.js';
import type { Maker } from './maker.js';
import { DRAFT_MAKERS } from './makers/index.js';
import { MAKER_PROFILE, type Recipe, materialClassOf } from './recipe.js';

/**
 * The published sets, as the bake reads them.
 *
 * `LIBRARY` is every entry in `library/`, checked against its maker. `CATALOG` is the same sets as
 * bake definitions: everything the container header states comes from the entry, the recipe or
 * the maker's manifest, and the per-texel pattern comes from the maker applied to the recipe.
 * Nothing about a set is stated in code any more; a set is its library file.
 */
export function definitionOf({ entry, maker }: LibrarySet): TextureSetDefinition {
  return recipeDefinition(
    {
      setId: entry.set_id,
      version: entry.version,
      title: entry.title,
      summary: entry.summary,
      licenceId: entry.licence_id,
    },
    entry.recipe,
    maker,
  );
}

/** What a container states besides the recipe: who the set is, and under which licence. */
export interface SetIdentity {
  readonly setId: string;
  readonly version: number;
  readonly title: string;
  readonly summary: string;
  readonly licenceId: string;
}

/**
 * A bake definition from an identity, a checked recipe and its maker. The one place a recipe
 * becomes what the container header states, for a published set and a workspace's own bake alike.
 */
export function recipeDefinition(
  identity: SetIdentity,
  recipe: Recipe,
  maker: Maker,
): TextureSetDefinition {
  if (maker.manifest.kind === 'model') {
    throw new Error(`${maker.manifest.maker_id} is model-made; its sets are imported as made, never baked`);
  }
  const materialClass = materialClassOf(maker.manifest);
  const relief = RELIEF_CLASSES.includes(materialClass);
  return {
    ...identity,
    seed: recipe.seed,
    family: maker.manifest.family,
    width: recipe.resolution.width,
    height: recipe.resolution.height,
    extentU: recipe.extent_mm.u,
    extentV: recipe.extent_mm.v,
    surface: maker.manifest.surface,
    containerProfile: maker.manifest.profile === MAKER_PROFILE ? SET_PROFILE_V1 : SET_PROFILE_V2,
    materialClass,
    heightRangeMm: relief ? heightRangeOf(recipe) : null,
    cavity: relief ? cavityOf(recipe) : null,
    film: materialClass === 'glazing' ? filmOf(recipe) : null,
    parameters: maker.stated(recipe),
    pattern: () => maker.pattern(recipe),
  };
}

export const LIBRARY: readonly LibrarySet[] = readLibrary();

export const CATALOG: readonly TextureSetDefinition[] = Object.freeze(LIBRARY.map(definitionOf));

/**
 * Draft sets: entries in `library-drafts/`, each naming a draft maker. They are baked by this
 * package's tests and by inspection, and published by nothing, until their makers join `MAKERS`.
 * The folder exists exactly while there are draft makers, so none means no folder to read.
 */
export const DRAFTS: readonly LibrarySet[] = DRAFT_MAKERS.length === 0
  ? Object.freeze([])
  : readLibrary(join(packageRoot(), DRAFT_FOLDER), DRAFT_MAKERS);
