import type { MakerManifest, Recipe } from './recipe.js';
import type { Pattern } from './sample.js';

/**
 * A maker: the code half of a texture set.
 *
 * A maker is a versioned component with one job: turn a checked recipe into a pattern the bake
 * samples. Its manifest is data and is published as an object of its own. Everything a recipe can
 * change is a control in that manifest; everything else is fixed by the maker's version. So a
 * change to a maker's code that alters any texel for an existing recipe is a new maker version, and
 * a new set version for every set that uses it.
 *
 * The makers here are procedural: they compute every texel from integers and nothing else. A
 * learned maker, or one fitted to a photograph, plugs into the same slot with a manifest of the same
 * shape, and its output is baked once and pinned exactly like these.
 */
export interface Maker {
  readonly manifest: MakerManifest;
  /** What the container header states about the module this recipe is built on. */
  stated(recipe: Recipe): Readonly<Record<string, number | string>>;
  /** The per-texel pattern the recipe describes. The recipe must already be checked. */
  pattern(recipe: Recipe): Pattern;
}
