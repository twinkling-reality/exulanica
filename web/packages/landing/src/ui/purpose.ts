/** A quiet, single-paragraph purpose surface. */

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
        text: 'We record more of our lives than ever, yet much of what makes those moments ours remains scattered: the people who connect them, the places we return to, and how we change over time. Exulanica is being built to bring those fragments into a connected personal world, shaped by the media you keep and the context only you can give. A world you can revisit, add to, and carry forward, preserving the relationships that give individual moments meaning.',
      }),
    ]),
  ]);
}
