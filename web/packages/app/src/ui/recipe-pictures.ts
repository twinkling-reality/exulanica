/**
 * Recipes with a picture shipped in `public/your-worlds/<key>.jpg`: a frame of a town made from
 * the recipe, captured from the running application. Your worlds shows one on a world that has no
 * picture of its own yet, and Create a world on the recipe's button.
 */
export const RECIPE_PICTURES: ReadonlySet<string> = new Set(['small_town', 'market_town']);

export const recipePicture = (recipeKey: string): string | null =>
  RECIPE_PICTURES.has(recipeKey) ? `/your-worlds/${recipeKey}.jpg` : null;
