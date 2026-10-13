import { el } from '../dom.js';
import { action } from '../action.js';
import { bindCopyFeedback, copyGlyph } from '../copy-feedback.js';

const REPOSITORY = 'https://github.com/twinkling-reality/exulanica';
/** Standalone destinations reuse the public secondary action. Context supplies their kind. */
export function routeLink(href: string, label: string): HTMLAnchorElement {
  const link = action(label, href, true);
  link.classList.add('docs-route-link');
  return link;
}
export const source = (path: string, label: string): HTMLAnchorElement => {
  const link = routeLink(`${REPOSITORY}/blob/main/${path}`, label);
  link.title = 'View source on GitHub';
  link.setAttribute('aria-label', label.includes('GitHub') ? label : `${label} (GitHub)`);
  return link;
};
export const p = (text: string): HTMLParagraphElement => el('p', { text });
export const inline = (text: string): HTMLElement => el('code', { text });

export function codeBlock(label: string, value: string, language = 'text', highlight = true): HTMLElement {
  const status = el('span', { class: 'docs-copy-status', role: 'status', 'aria-live': 'polite' });
  const labelNode = el('span', { text: 'Copy' });
  const button = el('button', { type: 'button', class: 'docs-copy secondary-action', 'aria-label': `Copy ${label}` }, [copyGlyph(), labelNode]);
  bindCopyFeedback(button, labelNode, status, () => value, {
    success: 'Copied', failure: 'Select the code to copy it.',
  });
  const code = el('code');
  // Token spans preserve the original text, including whitespace, for copying.
  const tokens = highlight ? value.split(/(#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:from|import|def|return|for|in|try|except|as|with|if|else|continue|true|false|null)\b)/g) : [value];
  for (const token of tokens) code.append(highlight && /^(?:#|["'])/.test(token) ? el('span', { class: token.startsWith('#') ? 'code-comment' : 'code-string', text: token }) : ((language === 'python' && /^(from|import|def|return|for|in|try|except|as|with|if|else|continue)$/.test(token)) || (language === 'json' && /^(true|false|null)$/.test(token))) ? el('span', { class: 'code-keyword', text: token }) : token);
  return el('div', { class: 'docs-code' }, [
    el('div', { class: 'docs-code-toolbar' }, [el('span', { class: 'docs-code-label', text: label }), status, button]),
    el('pre', { tabindex: '0', 'aria-label': label, 'data-language': language }, [code]),
  ]);
}

export function table(headers: string[], rows: string[][]): HTMLElement {
  return el('div', { class: 'docs-table-scroll', tabindex: '0', 'aria-label': headers.join(' and ') }, [
    el('table', {}, [
      el('thead', {}, [el('tr', {}, headers.map((text) => el('th', { scope: 'col', text })))]),
      el('tbody', {}, rows.map((row) => el('tr', {}, row.map((text) => el('td', { text }))))),
    ]),
  ]);
}

export interface Chapter { key: string; title: string; nodes: Node[] }
export interface DocumentPage { title: string; introduction: string; chapters: Chapter[]; sourcePath: string }
