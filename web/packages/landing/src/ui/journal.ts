import { editorialCover } from './editorial-optics.js';
import { readingTools } from './reading-tools.js';
import { articleMarkdown } from '../content/markdown.js';
import { el } from './dom.js';
import { JOURNAL, type JournalPost, type JournalSource } from '../content/journal.js';
import { buildSiteFooter } from './site-footer.js';
import { source, table } from './docs/elements.js';
import '../site-pages.css';

function sourceLink(item: JournalSource): HTMLAnchorElement {
  if (item.href) return el('a', { href: item.href, text: `${item.title} ↗` });
  return source(item.path ?? '', item.title);
}
function story(post: JournalPost, index: number): HTMLElement {
  const minutes = Math.max(1, Math.ceil(articleMarkdown(post).split(/\s+/).length / 220));
  return el('a', { class: `journal-story${index === 0 ? ' journal-lead' : ''}`, href: `/blog/${post.slug}` }, [
    editorialCover(index),
    el('div', { class: 'story-meta' }, [el('span', { text: post.subject }), el('span', { text: `${minutes} min read` })]),
    el('div', { class: 'story-copy' }, [el('h2', { text: post.title }), el('p', { text: post.description })]),
    el('span', { class: 'story-read', text: 'Read article ↗', 'aria-hidden': 'true' }),
  ]);
}
export function buildJournal(): HTMLElement {
  return el('section', { id: 'journal', class: 'pane site-pane journal-pane', tabindex: '-1', 'aria-labelledby': 'journal-title' }, [
    el('div', { class: 'site-page' }, [
      el('header', { class: 'journal-hero' }, [el('h1', { id: 'journal-title', text: 'Blog' }), el('p', { class: 'journal-introduction', text: 'No posts yet.' })]),
      ...(JOURNAL.length === 0 ? [] : [el('div', { class: 'journal-list' }, [story(JOURNAL[0]!, 0), el('div', { class: 'journal-secondary' }, JOURNAL.slice(1).map((post, index) => story(post, index + 1)))])]),
      buildSiteFooter(),
    ]),
  ]);
}
export function buildJournalArticle(post: JournalPost): HTMLElement {
  const id = `journal-${post.slug}`;
  return el('section', { id, class: 'pane site-pane journal-article-pane', tabindex: '-1', 'aria-labelledby': `${id}-title` }, [
    el('div', { class: 'site-page' }, [
      el('header', { class: 'essay-header' }, [
        el('div', { class: 'essay-heading-copy' }, [
        el('a', { class: 'text-link', href: '/blog', text: '← Blog' }),
        el('h1', { id: `${id}-title`, text: post.title }), el('p', { class: 'essay-description', text: post.description }),
        readingTools(() => articleMarkdown(post), `/blog/${post.slug}`),
        ]),
        el('div', { class: 'essay-art' }, [editorialCover(JOURNAL.findIndex(item => item.slug === post.slug))]),
      ]),
      el('div', { class: 'essay-layout' }, [
        el('aside', { class: 'essay-rail' }, [el('nav', { 'aria-label': 'In this essay' }, post.sections.map(section => el('a', { href: `/blog/${post.slug}#${id}-${section.id}`, text: section.title })))]),
        el('article', { class: 'essay-body' }, [
          el('p', { class: 'essay-opening', text: post.opening }),
          ...post.sections.map(section => el('section', { id: `${id}-${section.id}` }, [el('h2', { text: section.title }), ...section.paragraphs.map(text => el('p', { text })), ...(section.evidence ? [el('figure', { class: 'essay-evidence' }, [table(section.evidence.headers, section.evidence.rows), el('figcaption', { text: section.evidence.caption })])] : [])])),
          ...(post.sources.length === 0 ? [] : [el('section', { class: 'essay-sources' }, [el('h2', { text: 'Sources' }), ...post.sources.map(item => el('div', {}, [sourceLink(item), el('p', { text: item.detail })]))])]),
        ]),
      ]),
      el('nav', { class: 'essay-next', 'aria-label': 'Continue reading' }, JOURNAL.filter(item => item.slug !== post.slug).map(item => el('a', { href: `/blog/${item.slug}` }, [el('span', { text: item.subject }), el('strong', { text: `${item.title} ↗` })]))),
      buildSiteFooter(),
    ]),
  ]);
}
