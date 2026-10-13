import { el } from './dom.js';
export function buildSiteFooter(): HTMLElement {
  return el('footer', { class: 'site-footer' }, [
    el('a', { class: 'footer-brand', href: '/', text: 'exulanica' }),
    el('nav', { 'aria-label': 'Footer' }, [
      el('a', { href: '/product', text: 'Product' }),
      el('a', { href: '/use-cases', text: 'Use Cases' }),
      el('a', { href: '/docs', text: 'Documentation' }),
    ]),
  ]);
}
