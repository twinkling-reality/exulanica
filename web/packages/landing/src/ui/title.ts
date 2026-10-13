/** Two ordered loops of circular image planes around a small product description and one invitation. */
import { el } from './dom.js';
import { buildWorldShowcase } from './world-showcase.js';
import '../hero.css';

export function buildTitle(options: { atlasHref: string | null } = { atlasHref: null }): HTMLElement {
  const root = el('section', { id: 'title', class: 'pane pane-title', tabindex: '-1', 'aria-labelledby': 'title-wordmark' });
  const content = el('div', { class: 'hero-content' }, [
    el('h1', { class: 'hero-heading', id: 'title-wordmark' }, [
      el('span', { class: 'hero-statement', text: 'Create virtual worlds' }),
      el('span', { text: 'and bring them to life' }),
      el('span', { text: 'with open-source AI.' }),
    ]),
  ]);
  const actions = el('div', { class: 'hero-actions' }, [
    el('a', { class: 'primary-action', id: 'hero-entry', href: options.atlasHref ?? '/docs/self-hosting', text: options.atlasHref ? 'Open Exulanica' : 'Run Exulanica' }),
  ]);
  root.append(el('div', { class: 'hero-stage' }, [
    buildWorldShowcase({ ...options, portals: true, onSelectionChange(selected) {
      root.toggleAttribute('data-world-preview', selected);
      content.setAttribute('aria-hidden', String(selected));
      if (content.inert !== selected) content.inert = selected;
      if (actions.inert !== selected) actions.inert = selected;
    } }), content, actions,
  ]));
  return root;
}
