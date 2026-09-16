import { cavityOf, heightRangeOf } from './controls.js';
import type { TextureSetDefinition } from './definition.js';
import { type LibrarySet, readLibrary } from './library.js';

/**
 * The published sets, as the bake reads them.
 *
 * `LIBRARY` is every entry in `library/`, checked against its maker. `CATALOG` is the same sets as
 * bake definitions: everything the container header states comes from the entry, the recipe or
 * the maker's manifest, and the per-texel pattern comes from the maker applied to the recipe.
 * Nothing about a set is stated in code any more; a set is its library file.
 */
export function definitionOf({ entry, maker }: LibrarySet): TextureSetDefinition {
  const { recipe } = entry;
  return {
    setId: entry.set_id,
    version: entry.version,
    seed: recipe.seed,
    family: maker.manifest.family,
    title: entry.title,
    summary: entry.summary,
    width: recipe.resolution.width,
    height: recipe.resolution.height,
    extentU: recipe.extent_mm.u,
    extentV: recipe.extent_mm.v,
    surface: maker.manifest.surface,
    heightRangeMm: heightRangeOf(recipe),
    cavity: cavityOf(recipe),
    parameters: maker.stated(recipe),
    pattern: () => maker.pattern(recipe),
  };
}

export const LIBRARY: readonly LibrarySet[] = readLibrary();

export const CATALOG: readonly TextureSetDefinition[] = Object.freeze(LIBRARY.map(definitionOf));
