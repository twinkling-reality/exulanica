/**
 * The recipes a new world can be generated from, and making one.
 *
 * Every recipe the server offers is listed (`GET /worlds/recipes`), each as one choice; choosing
 * one asks the server to generate and save the world (`POST /worlds/generated`) and hands the saved
 * entry to `open`, which opens it the way a chosen saved world is opened. What a recipe makes is
 * the server's: the page sends the recipe's key and a title and nothing else.
 */

import type { SavedWorldEntry, WorldRecipe } from '../world-entry-api.js';
import { fill, say } from './copy.js';
import { el } from './dom.js';

export interface WorldRecipesPanel {
  readonly root: HTMLElement;
}

export function buildWorldRecipes(options: {
  readonly recipes: () => Promise<readonly WorldRecipe[]>;
  readonly make: (recipe: WorldRecipe) => Promise<SavedWorldEntry>;
  readonly open: (entry: SavedWorldEntry) => Promise<void>;
  readonly onClose: () => void;
}): WorldRecipesPanel {
  const status = el('p', { class: 'world-recipes-status', role: 'status', 'aria-live': 'polite',
    text: say('worldRecipes.loading') });
  const list = el('div', { class: 'world-recipes-list' });
  const close = el('button', { type: 'button', class: 'world-recipes-close', text: say('worldRecipes.close') });
  close.addEventListener('click', () => options.onClose());
  const root = el('section', {
    class: 'world-recipes', role: 'dialog', 'aria-label': say('worldRecipes.heading'),
  }, [
    el('h2', { text: say('worldRecipes.heading') }),
    el('p', { text: say('worldRecipes.introduction') }),
    list,
    status,
    close,
  ]);
  void options.recipes().then((recipes) => {
    status.textContent = '';
    for (const recipe of recipes) {
      const choice = el('button', {
        type: 'button', class: 'world-recipes-choice', 'data-recipe': recipe.key, text: recipe.label,
      });
      choice.addEventListener('click', () => {
        for (const button of list.querySelectorAll('button')) (button as HTMLButtonElement).disabled = true;
        status.textContent = fill('worldRecipes.making', { recipe: recipe.label });
        void options.make(recipe).then(options.open).catch((error: unknown) => {
          for (const button of list.querySelectorAll('button')) (button as HTMLButtonElement).disabled = false;
          status.textContent = fill('worldRecipes.failed', {
            reason: error instanceof Error ? error.message : String(error),
          });
        });
      });
      list.append(choice);
    }
  }).catch((error: unknown) => {
    status.textContent = fill('worldRecipes.failed', {
      reason: error instanceof Error ? error.message : String(error),
    });
  });
  return { root };
}
