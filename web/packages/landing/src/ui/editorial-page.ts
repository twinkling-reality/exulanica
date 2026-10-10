import { el } from './dom.js';
import { action } from './action.js';
import '../editorial.css';

interface EditorialSection { id: string; title: string; copy: string; href?: string; link?: string }
interface EditorialOptions {
  id: string;
  compact?: boolean;
  title: string;
  introduction: string;
  sections: readonly EditorialSection[];
  feature?: HTMLElement;
  note?: string;
  links?: readonly { href: string; label: string }[];
}

/** Reading pages use a single introduction and sections organized by responsibility. */
export function buildEditorialPage(options: EditorialOptions): HTMLElement {
  const headingId = `${options.id}-title`;
  const article = el('article', { class: 'editorial-page' }, [
    el('header', { class: 'editorial-intro' }, [
      el('div', { class: 'editorial-title' }, [
        el('h1', { id: headingId, text: options.title }),
      ]),
      el('div', { class: 'editorial-lead' }, [
        el('p', { text: options.introduction }),
        el('div', { class: 'page-actions' }, (options.links ?? []).map(link => action(link.label, link.href, true))),
      ]),
    ]),
  ]);
  if (options.compact) {
    article.classList.add('editorial-compact');
    if (options.note) article.querySelector('.editorial-lead')!.append(el('p', { class: 'compact-note', text: options.note }));
    return el('section', { id: options.id, class: 'pane pane-information pane-editorial pane-compact', tabindex: '-1', 'aria-labelledby': headingId }, [article]);
  }
  if (options.feature) article.append(options.feature);
  article.append(el('div', { class: `editorial-index editorial-index-${options.sections.length}` }, options.sections.map((section) =>
    el('section', { 'aria-labelledby': section.id }, [
      el('h2', { id: section.id, text: section.title }),
      el('p', { text: section.copy }),
      ...(section.href ? [action(section.link ?? section.title, section.href, true)] : []),
    ]))));
  if (options.note) article.append(el('p', { class: 'editorial-note', text: options.note }));
  article.append(el('footer', { class: 'editorial-footer' }, [
    el('nav', { 'aria-label': 'Further reading' }, [
      el('a', { href: '/about', text: 'About' }),
      el('a', { href: '/worlds', text: 'Worlds' }),
      el('a', { href: '/docs', text: 'Documentation' }),
    ]),
    el('span', { text: '© 2026 Exulanica' }),
  ]));
  return el('section', {
    id: options.id, class: 'pane pane-information pane-editorial', tabindex: '-1', 'aria-labelledby': headingId,
  }, [article]);
}
