import { PRODUCT_CAPABILITIES } from '../content/product.js';
import { el } from './dom.js';
import { withSectionAtmosphere } from './ambient-field.js';
import '../site-pages.css';
import '../product.css';
import '../feature-pages.css';

const CAPABILITY_FIGURES: Partial<Record<typeof PRODUCT_CAPABILITIES[number]['id'], { src: string; alt: string; caption: string }>> = {
  configurations: {
    src: '/worlds/small-town.jpg',
    alt: 'A generated town street with low buildings, trees, and benches.',
    caption: 'Small Town, a compact generated town with one high street.',
  },
  models: {
    src: '/product/model-selection.jpg',
    alt: 'A world with the model chooser open. Some people have an open model and others stay on their routine.',
    caption: 'Choose who an open model decides for. Everyone else keeps their routine.',
  },
};

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
  return withSectionAtmosphere(el('section', {
    id: 'product-capabilities',
    class: 'pane site-pane feature-pane capability-pane',
    tabindex: '-1',
    'aria-labelledby': 'product-capabilities-title',
  }, [
    el('article', { class: 'site-page work-sheet' }, [
      el('h1', { id: 'product-capabilities-title', text: 'Capabilities' }),
      el('p', { class: 'work-lead', text: 'Worlds for AI Agents. Open models for minds. Open source only for the Apache-2.0 software.' }),
      el('div', { class: 'work-rows' }, PRODUCT_CAPABILITIES.map(item => {
        const figure = CAPABILITY_FIGURES[item.id];
        const copy = el('div', { class: 'work-copy' }, [
          el('h2', { text: item.title }),
          el('p', { text: item.copy }),
          el('span', { class: 'row-label' }, [
            item.action,
            el('span', { class: 'row-label-mark', text: '↗', 'aria-hidden': 'true' }),
          ]),
        ]);
        const body = figure ? [
          copy,
          el('figure', {}, [
            el('img', { src: figure.src, alt: figure.alt, width: '1280', height: '860', loading: 'lazy' }),
            el('figcaption', { text: figure.caption }),
          ]),
        ] : [copy];
        return el('section', { id: item.id, class: figure ? 'work-row has-figure' : 'work-row' }, [
          el('a', { class: 'work-link', href: item.href }, body),
        ]);
      })),
    ]),
  ]), 'product');
}
