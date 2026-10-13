import { el } from './dom.js';
import { icon } from './icons.js';
import { bindCopyFeedback, copyGlyph } from './copy-feedback.js';

/** Copy and export use the same Markdown source as the published document. */
export function readingTools(markdown: () => string, path: string): HTMLElement {
  const status = el('span', { class: 'reading-status', role: 'status', 'aria-live': 'polite' });
  const label = el('span', { text: 'Copy Page' });
  const copy = el('button', { type: 'button', 'aria-label': 'Copy page as Markdown' }, [copyGlyph(), label]);
  bindCopyFeedback(copy, label, status, markdown, {
    success: 'Markdown copied',
    failure: 'Copy blocked. Open View Markdown to select the text.',
    errorClass: 'reading-status-error',
  });
  if (!path.startsWith('/docs')) {
    copy.replaceChildren(label);
    return el('div', { class: 'reading-tools', 'aria-label': 'Read and share' }, [copy, el('a', { href: `${path}.md`, text: 'Markdown', 'aria-label': 'Read this page as Markdown' }), status]);
  }
  const menuId = `page-actions-${path.replace(/[^a-z0-9]/gi, '-')}`;
  const toggle = el('button', { class: 'reading-menu-toggle', type: 'button', 'aria-label': 'More page actions', 'aria-expanded': 'false', 'aria-controls': menuId, 'aria-haspopup': 'menu' }, [icon('chevron')]);
  const menuCopy = el('button', { type: 'button', role: 'menuitem' }, [icon('copy'), el('span', { text: 'Copy Page' })]);
  const view = el('a', { role: 'menuitem', href: `${path}.md`, 'aria-label': 'Read this page as Markdown' }, [icon('document'), el('span', { text: 'View Markdown' })]);
  const download = el('a', { role: 'menuitem', href: `${path}.md`, download: `${path.split('/').at(-1) || 'documentation'}.md`, 'aria-label': 'Download this page as Markdown' }, [icon('download'), el('span', { text: 'Download Markdown' })]);
  const menu = el('div', { id: menuId, class: 'reading-menu', role: 'menu', 'aria-label': 'Page actions', hidden: '' }, [menuCopy, view, download]);
  const root = el('div', { class: 'reading-tools reading-tools-compact', 'aria-label': 'Read and share' }, [el('div', { class: 'reading-button-group' }, [copy, toggle]), menu, status]);
  const items = [menuCopy, view, download];
  const close = (restoreFocus = false) => {
    menu.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
    document.removeEventListener('pointerdown', outside);
    if (restoreFocus) toggle.focus({ preventScroll: true });
  };
  const outside = (event: PointerEvent) => { if (event.target instanceof Node && !root.contains(event.target)) close(); };
  const open = (focusIndex?: number) => {
    status.classList.remove('reading-status-error');
    menu.hidden = false;
    toggle.setAttribute('aria-expanded', 'true');
    document.addEventListener('pointerdown', outside);
    if (focusIndex !== undefined) items[focusIndex]?.focus();
  };
  toggle.addEventListener('click', () => { if (menu.hidden) open(0); else close(); });
  toggle.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); open(event.key === 'ArrowDown' ? 0 : items.length - 1); }
  });
  root.addEventListener('keydown', event => {
    if (menu.hidden) return;
    if (event.key === 'Escape') { event.preventDefault(); close(true); return; }
    if (!menu.contains(event.target as Node)) return;
    const index = items.indexOf(event.target as typeof menuCopy);
    let next: number;
    if (event.key === 'ArrowDown') next = (index + 1) % items.length;
    else if (event.key === 'ArrowUp') next = (index - 1 + items.length) % items.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = items.length - 1;
    else return;
    event.preventDefault(); items[next]?.focus();
  });
  root.addEventListener('focusout', event => {
    // A modified press can blur the source without focusing another control in this document.
    // Outside pointer presses already close the menu; preserve native link activation on blur.
    if (event.relatedTarget instanceof Node && !root.contains(event.relatedTarget)) close();
  });
  menuCopy.addEventListener('click', () => { close(true); copy.click(); });
  for (const link of [view, download]) link.addEventListener('click', event => {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    close(true);
  });
  return root;
}
