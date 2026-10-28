import { readingTools } from './reading-tools.js';
import { documentMarkdown } from '../content/markdown.js';
import { el } from './dom.js';
import { icon } from './icons.js';
import { action } from './action.js';
import { DOCUMENTS, documentId, type DocumentationKind } from './docs/catalog.js';
import { buildDocumentationSearch, openDocumentationSearch } from './documentation-search.js';
import '../documentation.css';

export type { DocumentationKind } from './docs/catalog.js';

/** Desktop rails become native disclosures on narrow screens. */
function disclosure(label: string, className: string, body: HTMLElement, breakpoint: number): HTMLDetailsElement {
  const details = el('details', { class: className }, [el('summary', { text: label }), body]);
  const compact = window.matchMedia(`(max-width: ${breakpoint}px)`);
  const sync = () => { details.open = !compact.matches; };
  sync(); compact.addEventListener('change', sync);
  details.addEventListener('click', event => {
    if (compact.matches && (event.target as Element).closest('a')) details.open = false;
  });
  return details;
}

export function buildDocumentation(kind: DocumentationKind): HTMLElement {
  const entry = DOCUMENTS.find(item => item.key === kind)!;
  const page = entry.build();
  const id = documentId(kind);
  const isApi = kind.startsWith('world-api') || kind === 'api-reference';
  const isOperation = kind.startsWith('world-api-');
  const grouped = new Map<string, typeof DOCUMENTS[number][]>();
  for (const item of DOCUMENTS.filter(item => item.group !== 'API Operations' && (!isApi || item.group === 'Developer Tools'))) {
    const items = grouped.get(item.group) ?? [];
    items.push(item);
    grouped.set(item.group, items);
  }
  const links = [...grouped.entries()].map(([group, items]) => el('div', { class: 'docs-nav-group' }, [
    el('p', { class: 'docs-nav-label', text: group }),
    ...items.map(item => el('a', { href: item.href, text: item.label, ...(item.key === kind ? { 'aria-current': 'page' } : {}) })),
  ]));
  const sidebar = disclosure('Documentation', 'docs-navigation', el('nav', { class: 'docs-sidebar', 'aria-label': 'Documentation' }, [
    ...(isApi ? [el('a', { href: '/docs', class: 'docs-nav-back' }, [icon('arrow'), el('span', { text: 'All guides' })])] : []), ...links,
  ]), 760);
  const chapters = page.chapters.map(chapter => el('section', { id: `${id}-${chapter.key}`, class: 'docs-chapter', tabindex: '-1' }, [
    el('h2', {}, isOperation && chapter.key === 'request' ? [chapter.title] : [el('a', { class: 'docs-section-link', href: `${entry.href}#${id}-${chapter.key}`, text: chapter.title })]), ...chapter.nodes,
  ]));
  const sequence = DOCUMENTS.filter(item => isOperation ? item.group === 'API Operations' : item.group !== 'API Operations');
  const position = sequence.indexOf(entry);
  const pager = el('nav', { class: 'docs-pager', 'aria-label': 'More documentation' });
  for (const [index, label] of [[position - 1, 'Previous'], [position + 1, 'Next']] as const) {
    const adjacent = sequence[index];
    if (adjacent) {
      const link = action(adjacent.label, adjacent.href, true);
      link.classList.add(label.toLowerCase());
      link.setAttribute('aria-label', `${label}: ${adjacent.label}`);
      link.rel = label === 'Previous' ? 'prev' : 'next';
      const direction = icon('arrow');
      direction.classList.add('docs-pager-direction');
      link.append(direction);
      pager.append(link);
    }
  }
  const article = el('article', { class: 'docs-article' }, [
    el('header', { class: 'docs-heading' }, [
      el('div', { class: 'docs-heading-row' }, [el('h1', { id: `${id}-title`, text: page.title }), readingTools(() => documentMarkdown(page), entry.href)]),
      el('p', { text: page.introduction }),
    ]), ...chapters,
    el('footer', { class: 'docs-footer' }, [pager]),
  ]);
  const tocLinks = page.chapters.map(chapter => el('a', { href: `${entry.href}#${id}-${chapter.key}`, text: chapter.title }));
  const contents = disclosure('On this page', 'docs-outline', el('nav', { class: 'docs-contents', 'aria-label': 'On this page' }, [
    el('p', { class: 'docs-nav-label', text: 'On this page' }), ...tocLinks,
  ]), 1120);
  if (isApi) sidebar.append(contents);
  const searchControl = buildDocumentationSearch();
  const navigation = el('div', { class: 'docs-navigation-rail' }, [searchControl, sidebar]);
  const pane = el('section', { id, class: `pane documentation-pane${isApi ? ' api-reference-pane' : ''}${isOperation ? ' api-operation-pane' : ''}`, tabindex: '-1', 'aria-labelledby': `${id}-title` }, [
    el('div', { class: 'docs-layout' }, isApi ? [navigation, article] : [navigation, contents, article]),
  ]);
  document.addEventListener('keydown', event => {
    if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey) && pane.isConnected && !pane.inert && document.documentElement.dataset.surface === id) {
      event.preventDefault(); openDocumentationSearch(searchControl);
    }
  });
  const revealOperation = () => {
    if (kind !== 'api-reference' || !window.location.hash) return;
    let target: HTMLElement | null;
    try { target = document.getElementById(decodeURIComponent(window.location.hash.slice(1))); } catch { return; }
    if (target instanceof HTMLDetailsElement && pane.contains(target) && target.classList.contains('api-catalog-operation')) target.open = true;
  };
  window.addEventListener('hashchange', revealOperation);
  // Router entry focuses the pane before scrolling to a deep link.
  pane.addEventListener('focus', revealOperation);
  let scheduled = false;
  const updateSection = () => {
    scheduled = false;
    const top = pane.getBoundingClientRect().top + 40;
    let current = 0;
    chapters.forEach((chapter, index) => { if (chapter.getBoundingClientRect().top <= top) current = index; });
    tocLinks.forEach((link, index) => { if (index === current) link.setAttribute('aria-current', 'location'); else link.removeAttribute('aria-current'); });
  };
  tocLinks[0]?.setAttribute('aria-current', 'location');
  pane.addEventListener('scroll', () => { if (!scheduled) { scheduled = true; requestAnimationFrame(updateSection); } }, { passive: true });
  return pane;
}
