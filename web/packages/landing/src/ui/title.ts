/** Exulanica's signed-out title: one wordmark, one proposition, and one field of near-touching gradient forms. */

import { el } from './dom.js';
import { createGradientForms } from './gradient-forms/index.js';
import { HOME_FORMS } from './gradient-forms/presets.js';

export function buildTitle(): HTMLElement {
  const root = el('section', {
    id: 'title',
    class: 'pane pane-title',
    tabindex: '-1',
    'aria-labelledby': 'title-wordmark',
  });
  const artwork = el('div', { class: 'title-artwork', 'aria-hidden': 'true' });
  artwork.append(createGradientForms(HOME_FORMS).element);

  const stack = el('div', { class: 'title' });
  stack.append(
    el('h1', { class: 'wordmark', id: 'title-wordmark', text: 'Exulanica' }),
    el('p', { class: 'proposition', text: 'A personal world memory model' }),
  );

  const publisher = el('p', { class: 'publisher-mark' }, [
    el('span', { text: '© 2026 ' }),
    el('span', { text: 'Twinkling Reality' }),
  ]);

  root.append(artwork, stack, publisher);
  return root;
}
