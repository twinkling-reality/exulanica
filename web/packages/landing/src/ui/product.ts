import { el } from './dom.js';
import { buildCapabilityCarousel } from './capability-carousel.js';
import { withSectionAtmosphere } from './ambient-field.js';
import '../site-pages.css';
import '../product.css';
import '../feature-pages.css';

export function buildProduct(): HTMLElement {
  return withSectionAtmosphere(el('section', { id: 'product', class: 'pane site-pane feature-pane product-purpose-pane', tabindex: '-1', 'aria-labelledby': 'product-title' }, [
    el('article', { class: 'site-page purpose-sheet' }, [
      el('p', { class: 'purpose-label', text: 'Purpose' }),
      el('div', { class: 'purpose-line', 'aria-hidden': 'true' }),
      el('div', { class: 'product-intro purpose-copy', id: 'purpose' }, [
        el('h1', { id: 'product-title', text: 'Worlds for AI Agents' }),
        el('p', { class: 'purpose-lead', text: 'Discover, use, and understand open-source AI through worlds you create.' }),
        el('p', { class: 'purpose-description' }, [
          'Exulanica brings worldbuilding and open models into one place. Build a setting, choose the models that act within it, and explore how their decisions shape what happens. Our aim is to connect imagination with experimentation, helping you make something your own while learning what different models can do. ',
          el('a', { class: 'purpose-more', href: '/product/capabilities', 'aria-label': 'Learn more about Exulanica’s capabilities' }, [
            el('span', { class: 'purpose-more-label', text: 'Learn More' }),
            el('span', { class: 'purpose-more-icon', text: '↗', 'aria-hidden': 'true' }),
          ]),
        ]),
      ]),
    ]),
  ]), 'product');
}

export function buildProductCapabilities(): HTMLElement {
  const pane = withSectionAtmosphere(el('section', { id: 'product-capabilities', class: 'pane site-pane feature-pane capability-pane', tabindex: '-1', 'aria-labelledby': 'product-capabilities-title' }), 'product');
  pane.append(buildCapabilityCarousel(pane));
  return pane;
}
