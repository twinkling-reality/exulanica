/** Public navigation: a home link, three disclosures, and independent utility links. */
import { el } from './dom.js';
import { icon } from './icons.js';
import type { Surface } from '../router.js';
export type { Surface } from '../router.js';

export const REPOSITORY_URL = 'https://github.com/twinkling-reality/exulanica';
export const DOCS_URL = '/docs';
export interface Chrome { readonly root: HTMLElement; setSurface(surface: Surface): void }

interface MenuItem {
  label: string;
  href: string;
  id?: string;
  surface?: Surface;
}

export function buildChrome(): Chrome {
  const bar = el('nav', { class: 'topbar', 'aria-label': 'Primary navigation' });
  const home = el('a', { class: 'brand', id: 'path-home', href: '/', text: 'exulanica', 'aria-label': 'Exulanica home' });
  const sections = el('div', { class: 'nav-sections' });
  const utilities = el('div', { class: 'nav-utilities' });
  const entry = el('a', { class: 'header-entry', id: 'path-waitlist', href: '/waitlist' }, [
    el('span', { class: 'action-label', text: 'Join Waitlist' }),
  ]);
  utilities.append(entry);
  for (const [label, href, mark] of [
    ['GitHub', REPOSITORY_URL, 'github'],
    ['Twinkling Reality', 'https://twinklingreality.com/', 'twinkling'],
  ] as const) {
    utilities.append(el('a', {
      class: 'utility-link', href, 'aria-label': `${label} (external)`, title: `${label} (external)`,
    }, [icon(mark)]));
  }

  let opened: { trigger: HTMLButtonElement; panel: HTMLElement } | null = null;
  const tracked: { link: HTMLAnchorElement; surface: Surface; trigger: HTMLButtonElement }[] = [];
  let closeTimer = 0;
  let openedByHover = false;
  const keepOpen = (): void => window.clearTimeout(closeTimer);
  const close = (restoreFocus = false): void => {
    keepOpen();
    if (!opened) return;
    const { trigger, panel } = opened;
    opened = null;
    delete bar.dataset.menuOpen;
    trigger.setAttribute('aria-expanded', 'false');
    panel.hidden = true;
    document.removeEventListener('pointerdown', outside);
    document.removeEventListener('keydown', escape);
    if (restoreFocus || panel.contains(document.activeElement)) trigger.focus({ preventScroll: true });
  };
  const outside = (event: PointerEvent): void => {
    if (!(event.target instanceof Node) || !bar.contains(event.target)) close();
  };
  const escape = (event: KeyboardEvent): void => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    close(true);
  };
  const addMenu = (label: string, key: string, items: readonly MenuItem[]): void => {
    const group = el('div', { class: 'nav-group', 'data-menu': key });
    const trigger = el('button', {
      class: 'nav-trigger', id: `menu-${key}`, type: 'button',
      'aria-expanded': 'false', 'aria-controls': `panel-${key}`,
    }, [el('span', { class: 'nav-marker', 'aria-hidden': 'true' }), el('span', { text: label })]);
    const panel = el('div', { class: 'menu-panel', id: `panel-${key}`, 'aria-labelledby': trigger.id, hidden: '' });
    const links = el('div', { class: 'menu-links' });
    panel.append(links);
    for (const item of items) {
      const link = el('a', { class: 'menu-link', href: item.href, 'aria-label': item.label,
        ...(item.id ? { id: item.id } : {}), text: item.label,
      });
      link.addEventListener('click', (event) => {
        // Opening another tab or window leaves this page and its focused link in place.
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
        close();
      });
      links.append(link);
      if (item.surface) tracked.push({ link, surface: item.surface, trigger });
    }
    const open = (hover = false): void => {
      keepOpen();
      if (opened?.trigger === trigger) return;
      close();
      opened = { trigger, panel };
      openedByHover = hover;
      bar.dataset.menuOpen = 'true';
      trigger.setAttribute('aria-expanded', 'true');
      panel.hidden = false;
      document.addEventListener('pointerdown', outside);
      document.addEventListener('keydown', escape);
    };
    const leave = (event: PointerEvent): void => {
      if (event.pointerType !== 'mouse') return;
      keepOpen();
      closeTimer = window.setTimeout(() => {
        if (opened?.trigger === trigger && !panel.contains(document.activeElement)) close();
      }, 240);
    };
    trigger.addEventListener('pointerenter', event => { if (event.pointerType === 'mouse') open(true); });
    trigger.addEventListener('pointerleave', leave);
    panel.addEventListener('pointerenter', keepOpen);
    panel.addEventListener('pointerleave', leave);
    trigger.addEventListener('click', () => {
      if (opened?.trigger === trigger && !openedByHover) close();
      else { open(); openedByHover = false; }
    });
    trigger.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowDown') return;
      event.preventDefault();
      if (opened?.trigger !== trigger) open();
      panel.querySelector<HTMLAnchorElement>('a')?.focus();
    });
    group.addEventListener('focusout', (event) => {
      if (event.relatedTarget instanceof Node && group.contains(event.relatedTarget)) return;
      if (opened?.trigger === trigger) close();
    });
    group.append(trigger, panel);
    sections.append(group);
  };
  addMenu('Platform', 'explore', [
    { label: 'About', href: '/about', id: 'path-purpose', surface: 'purpose' },
    { label: 'Worlds', href: '/worlds', id: 'path-capabilities', surface: 'capabilities' },
  ]);
  addMenu('Developers', 'builders', [
    { label: 'Overview', href: '/developers', id: 'path-developers', surface: 'developers' },
    { label: 'World API', href: '/docs/world-api', surface: 'docs-world-api' },
    { label: 'Agent Integrations', href: '/docs/agents', surface: 'docs-agents' },
  ]);
  addMenu('Resources', 'resources', [
    { label: 'Documentation', href: DOCS_URL, surface: 'docs' },
    { label: 'Research', href: '/research', id: 'path-research', surface: 'research' },
    { label: 'Roadmap', href: '/roadmap', surface: 'roadmap' },
  ]);
  home.addEventListener('click', () => close());
  bar.append(home, sections, utilities);
  return {
    root: bar,
    setSurface(surface) {
      close();
      entry.hidden = surface === 'title' || surface === 'waitlist';
      sections.querySelectorAll('[data-current]').forEach((node) => node.removeAttribute('data-current'));
      for (const item of tracked) {
        if (item.surface === surface) {
          item.link.setAttribute('aria-current', 'page');
          item.trigger.dataset['current'] = 'true';
        } else item.link.removeAttribute('aria-current');
      }
      if (surface === 'title') home.setAttribute('aria-current', 'page');
      else home.removeAttribute('aria-current');
    },
  };
}
