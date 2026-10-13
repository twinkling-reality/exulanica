import { el } from './dom.js';
import { icon } from './icons.js';
import { DOCUMENTS, searchDocumentation, type SearchResult } from './docs/catalog.js';
import '../documentation-search.css';

let controller: { dialog: HTMLDialogElement; open: (opener: HTMLElement) => void } | undefined;
const shortcut = () => /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ K' : 'Ctrl K';

export function buildDocumentationSearch(): HTMLButtonElement {
  const trigger = el('button', { type: 'button', class: 'docs-search-trigger', 'aria-haspopup': 'dialog', 'aria-controls': 'documentation-search' }, [
    icon('search'), el('span', { text: 'Search Docs' }), el('kbd', { text: shortcut() }),
  ]);
  trigger.addEventListener('click', () => openDocumentationSearch(trigger));
  return trigger;
}

export function openDocumentationSearch(opener: HTMLElement): void {
  if (!controller?.dialog.isConnected) controller = createSearch();
  controller.open(opener);
}

function highlighted(text: string, query: string): DocumentFragment {
  const fragment = document.createDocumentFragment();
  const terms = query.match(/[\p{L}\p{N}_]+/gu) ?? [];
  if (!terms.length) { fragment.append(text); return fragment; }
  const escaped = terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = new RegExp(`(${escaped.join('|')})`, 'giu');
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    fragment.append(text.slice(cursor, match.index), el('mark', { text: match[0] }));
    cursor = match.index! + match[0].length;
  }
  fragment.append(text.slice(cursor));
  return fragment;
}

function createSearch() {
  let opener: HTMLElement;
  let selected = 0;
  let links: HTMLAnchorElement[] = [];
  let restoreFocus = true;
  const dialog = el('dialog', { id: 'documentation-search', class: 'documentation-search', 'aria-label': 'Search documentation' });
  const input = el('input', { type: 'text', placeholder: 'Search documentation…', 'aria-label': 'Search documentation', role: 'combobox', 'aria-autocomplete': 'list', 'aria-controls': 'documentation-search-results', 'aria-expanded': 'true', autocomplete: 'off', spellcheck: 'false' });
  const clear = el('button', { type: 'button', class: 'documentation-search-clear', 'aria-label': 'Clear search', hidden: '' }, [el('span', { text: 'Clear' })]);
  const close = el('button', { type: 'button', class: 'documentation-search-close', 'aria-label': 'Close search' }, [el('kbd', { text: 'Esc' }), icon('close')]);
  const label = el('p', { class: 'documentation-search-label', id: 'documentation-search-label' });
  const results = el('div', { class: 'documentation-search-results', id: 'documentation-search-results', role: 'listbox', 'aria-labelledby': label.id });
  const status = el('span', { class: 'documentation-search-status', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true' });
  const empty = el('div', { class: 'documentation-search-empty', hidden: '' });
  const hints = el('footer', { class: 'documentation-search-hints' }, [
    el('span', {}, [el('kbd', { text: '↑ ↓' }), 'Navigate']),
    el('span', {}, [el('kbd', { text: '↵' }), 'Open']),
    el('span', {}, [el('kbd', { text: 'Esc' }), 'Close']),
  ]);
  dialog.append(el('div', { class: 'documentation-search-field' }, [icon('search'), input, clear, close]),
    el('div', { class: 'documentation-search-body' }, [label, results, empty]), hints, status);
  document.body.append(dialog);

  function select(index: number, scroll = false) {
    selected = index;
    links.forEach((link, i) => link.setAttribute('aria-selected', String(i === selected)));
    if (links[selected]) {
      input.setAttribute('aria-activedescendant', links[selected]!.id);
      if (scroll) links[selected]!.scrollIntoView({ block: 'nearest' });
    } else input.removeAttribute('aria-activedescendant');
  }
  function render() {
    const query = input.value.trim();
    const suggestions: SearchResult[] = DOCUMENTS.filter(entry => ['quickstart', 'worlds', 'world-api', 'agents'].includes(entry.key)).map(entry => ({
      title: entry.label, page: entry.group, group: entry.group, href: entry.href,
      text: entry.description, excerpt: entry.description, kind: 'page',
    }));
    const matches = query ? searchDocumentation(query) : suggestions;
    label.textContent = query ? matches.length > 12 ? `Showing 12 of ${matches.length} results` : `${matches.length} ${matches.length === 1 ? 'result' : 'results'}` : 'Suggested Guides';
    clear.hidden = !input.value;
    results.replaceChildren();
    links = matches.slice(0, 12).map((match, index) => {
      const title = el('strong'); title.append(highlighted(match.title, query));
      const excerpt = el('span', { class: 'documentation-search-excerpt' }); excerpt.append(highlighted(match.excerpt, query));
      const link = el('a', { id: `documentation-search-result-${index}`, href: match.href, role: 'option', tabindex: '-1', class: 'documentation-search-result', 'aria-selected': 'false' }, [
        el('span', { class: 'documentation-search-result-text' }, [el('span', { class: 'documentation-search-context', text: match.kind === 'page' ? match.group : match.page }), title, excerpt]),
        el('span', { class: 'documentation-search-enter', 'aria-hidden': 'true', text: '↵' }),
      ]);
      link.addEventListener('pointermove', () => select(index));
      link.addEventListener('click', event => {
        if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        restoreFocus = false; dialog.close();
      });
      results.append(link);
      return link;
    });
    results.hidden = !matches.length;
    input.setAttribute('aria-expanded', String(Boolean(matches.length)));
    empty.hidden = Boolean(matches.length);
    if (!matches.length) empty.replaceChildren(el('strong', { text: 'No results found' }), el('p', { text: 'Try a guide name, a topic, or an API path.' }));
    status.textContent = query ? `${label.textContent} for ${query}` : 'Suggested guides';
    select(0);
    results.scrollTop = 0;
  }
  input.addEventListener('input', render);
  input.addEventListener('keydown', event => {
    if (event.isComposing) return;
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && links.length) {
      event.preventDefault(); select((selected + (event.key === 'ArrowDown' ? 1 : -1) + links.length) % links.length, true);
    } else if (event.key === 'Enter' && links[selected]) { event.preventDefault(); links[selected]!.click(); }
  });
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const controls = [input, ...(clear.hidden ? [] : [clear]), close];
    const first = controls[0]!, last = controls[controls.length - 1]!;
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  clear.addEventListener('click', () => { input.value = ''; render(); input.focus(); });
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener('close', () => { if (restoreFocus && opener?.isConnected && !opener.closest('[inert]')) opener.focus(); });
  return { dialog, open: (trigger: HTMLElement) => {
    if (dialog.open) { input.focus(); return; }
    opener = trigger; restoreFocus = true; input.value = ''; render(); dialog.showModal(); input.focus();
  } };
}
