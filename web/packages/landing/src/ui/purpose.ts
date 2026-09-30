/** The product purpose in one uninterrupted reading line. */

import { el } from './dom.js';

export function buildPurpose(): HTMLElement {
  return el('section', {
    id: 'purpose',
    class: 'pane pane-information pane-purpose',
    tabindex: '-1',
    'aria-labelledby': 'purpose-title',
  }, [
    el('article', { class: 'reading-space' }, [
      el('h1', { id: 'purpose-title', class: 'sr-only', text: 'Purpose' }),
      el('p', {
        class: 'reading-copy',
        text: 'Build a world. Let open models decide what its people do. Swap a model, run the same saved world again, and see the difference. Exulanica keeps the world, its sources, and each validated decision available to inspect.',
      }),
    ]),
  ]);
}
