/**
 * The developer surface, scaffolded and deliberately empty.
 *
 * The route, the pane and the navigation entry exist so that writing this page later is a change
 * to one file rather than a change to routing, chrome, transitions and tests at once. Nothing is
 * written yet, and nothing here should be invented: what this page will eventually describe is
 * recorded in docs/capabilities/world-api.md and docs/world-memory-package.md, where World Read
 * serves scene and place bundles and World Write records generation receipts. General object
 * editing, alternate world versions and simulation are roadmap items there, not shipped surface,
 * so copy added here has to keep that separation or it becomes the claim the docs refuse to make.
 *
 * Its station is disabled until there is something to read. See `.destination:disabled` for what
 * that looks like, and the note on chrome.ts about why a dead control is a deliberate exception
 * here rather than the rule it otherwise follows.
 */

import { el } from './dom.js';

export function buildDevelopers(): HTMLElement {
  return el(
    'section',
    {
      id: 'developers',
      class: 'pane pane-information pane-developers',
      tabindex: '-1',
      'aria-labelledby': 'developers-title',
    },
    [el('h1', { id: 'developers-title', class: 'sr-only', text: 'Developers' })],
  );
}
