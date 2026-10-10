import type { SavedWorldEntry } from './world-entry-api.js';

/** Public recipe links express a selection, never permission to create or open a world. */
export function entryRecipe(search: string): string | null {
  const recipe = new URLSearchParams(search).get('recipe');
  return recipe !== null && /^[a-z][a-z0-9_]{0,63}$/.test(recipe) ? recipe : null;
}

/** Resolve only against entries served to this workspace, independent of their display titles. */
export function matchingRecipeEntry(entries: readonly SavedWorldEntry[], recipe: string | null): SavedWorldEntry | null {
  if (recipe === null) return null;
  return [...entries].filter(entry => entry.generatedGround?.recipeKey === recipe)
    .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt) || a.entryId.localeCompare(b.entryId))[0] ?? null;
}
