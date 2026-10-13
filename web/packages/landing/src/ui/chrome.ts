/** Public navigation and independent utility links. */
import { el } from './dom.js';
import { USE_CASES } from '../content/use-cases.js';
import { icon } from './icons.js';
import { createMenuCompanion, type MenuCompanion } from './menu-companion.js';
import type { CompanionColorVariant } from '@exulanica/presentation/companion';
import type { Surface } from '../router.js';
import type { PublicTheme } from '../theme.js';
export type { Surface } from '../router.js';

export const REPOSITORY_URL = 'https://github.com/twinkling-reality/exulanica';
export const DOCS_URL = '/docs';
export interface Chrome { readonly root: HTMLElement; setSurface(surface: Surface): void; setTheme(theme: PublicTheme): void }

interface MenuItem {
  label: string;
  href: string;
  id?: string;
  surface?: Surface;
  description?: string;
  group?: string;
}

export function buildChrome({ atlasHref = null, onToggleTheme }: { atlasHref?: string | null; onToggleTheme?: () => void } = {}): Chrome {
  const bar = el('nav', { class: 'topbar', 'aria-label': 'Primary navigation' });
  const home = el('a', { class: 'brand', id: 'path-home', href: '/', text: 'exulanica', 'aria-label': 'Exulanica home' });
  const sections = el('div', { class: 'nav-sections' });
  const utilities = el('div', { class: 'nav-utilities' });
  const themeToggle = el('button', { class: 'utility-link theme-toggle', type: 'button', 'aria-label': 'Switch to dark theme', title: 'Switch to dark theme' }, [icon('moon')]);
  themeToggle.addEventListener('click', () => onToggleTheme?.());
  utilities.append(themeToggle);
  for (const [label, href, mark] of [
    ['GitHub', REPOSITORY_URL, 'github'],
    ['Twinkling Reality', 'https://twinklingreality.com/', 'twinkling'],
  ] as const) {
    utilities.append(el('a', {
      class: 'utility-link', href, 'aria-label': `${label} (external)`, title: `${label} (external)`,
    }, [icon(mark)]));
  }

  const explore = el('a', { class: 'header-entry', hidden: '', href: atlasHref ?? '/docs/self-hosting', 'aria-label': 'Explore Exulanica' }, [
    el('span', { text: 'Explore' }),
  ]);
  utilities.append(explore);

  let opened: { trigger: HTMLButtonElement; panel: HTMLElement; companion: MenuCompanion } | null = null;
  const tracked: { link: HTMLAnchorElement; surface: Surface; trigger: HTMLButtonElement }[] = [];
  let closeTimer = 0;
  let openedByHover = false;
  const keepOpen = (): void => window.clearTimeout(closeTimer);
  const close = (restoreFocus = false): void => {
    keepOpen();
    if (!opened) return;
    const { trigger, panel, companion } = opened;
    opened = null;
    delete bar.dataset.menuOpen;
    trigger.setAttribute('aria-expanded', 'false');
    companion.setOpen(false);
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
  const sectionLinks: { link: HTMLAnchorElement; matches: (surface: Surface) => boolean }[] = [];
  const addMenu = (label: string, key: string, href: string, matches: (surface: Surface) => boolean, items: readonly MenuItem[]): void => {
    const group = el('div', { class: 'nav-group', 'data-menu': key });
    const title = el('a', { class: 'nav-section-link', href, text: label });
    sectionLinks.push({ link: title, matches });
    const trigger = el('button', {
      class: 'nav-trigger', id: `menu-${key}`, type: 'button',
      'aria-label': `Show ${label.toLowerCase()} menu`,
      'aria-expanded': 'false', 'aria-controls': `panel-${key}`,
    }, [el('span', { class: 'nav-control-mark', 'aria-hidden': 'true' })]);
    const panel = el('div', { class: 'menu-panel', id: `panel-${key}`, 'aria-labelledby': trigger.id, hidden: '' });
    const links = el('div', { class: 'menu-links' });
    const companions = el('div', { class: 'menu-companions', 'aria-hidden': 'true' });
    panel.append(links, companions);
    const color: CompanionColorVariant = key === 'use-cases' ? 'rose' : key === 'documentation' ? 'mint' : 'periwinkle';
    let lastGroup: string | undefined;
    for (const item of items) {
      if (item.group && item.group !== lastGroup) {
        links.append(el('p', { class: 'menu-group-label', text: item.group }));
        lastGroup = item.group;
      }
      const link = el('a', { class: 'menu-link', href: item.href, 'aria-label': item.label,
        ...(item.id ? { id: item.id } : {}),
      });
      link.append(el('span', { text: item.label }));
      if (item.description) link.append(el('small', { text: item.description }));
      link.addEventListener('click', (event) => {
        // Opening another tab or window leaves this page and its focused link in place.
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
        close();
      });
      links.append(link);
      if (item.surface) tracked.push({ link, surface: item.surface, trigger });
    }
    const companion = createMenuCompanion(panel, Array.from(links.querySelectorAll('a')), color);
    companions.append(companion.root);
    const open = (hover = false): void => {
      keepOpen();
      if (opened?.trigger === trigger) return;
      close();
      opened = { trigger, panel, companion };
      openedByHover = hover;
      bar.dataset.menuOpen = 'true';
      trigger.setAttribute('aria-expanded', 'true');
      panel.hidden = false;
      companion.setOpen(true);
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
    title.addEventListener('pointerenter', event => { if (event.pointerType === 'mouse') open(true); });
    title.addEventListener('pointerleave', leave);
    title.addEventListener('click', event => {
      if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && event.button === 0) close();
    });
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
    group.append(trigger, title, panel);
    sections.append(group);
  };
  addMenu('Product', 'product', '/product', surface => surface.startsWith('product'), [
    { label: 'Overview', href: '/product', id: 'path-product', surface: 'product' },
    { label: 'Capabilities', href: '/product/capabilities', surface: 'product-capabilities' },
  ]);
  addMenu('Use Cases', 'use-cases', '/use-cases', surface => surface === 'use-cases' || surface.startsWith('use-case-'), [
    ...USE_CASES.map(item => ({ label: item.title, href: `/use-cases/${item.key}`, surface: `use-case-${item.key}` as Surface })),
  ]);
  addMenu('Documentation', 'documentation', '/docs', surface => surface.startsWith('docs'), [
    { label: 'Introduction', href: '/docs', surface: 'docs' },
    { label: 'Quickstart', href: '/docs/quickstart', surface: 'docs-quickstart' },
    { label: 'Worldbuilding', href: '/docs/worlds', id: 'path-user-guide', surface: 'docs-worlds' },
    { label: 'API Reference', href: '/docs/api-reference', id: 'path-api', surface: 'docs-api-reference' },
    { label: 'Installation', href: '/docs/self-hosting', id: 'path-installation', surface: 'docs-self-hosting' },
  ]);
  home.addEventListener('click', () => close());
  bar.append(home, sections, utilities);
  return {
    root: bar,
    setTheme(theme) {
      const label = `Switch to ${theme === 'light' ? 'dark' : 'light'} theme`;
      themeToggle.setAttribute('aria-label', label);
      themeToggle.title = label;
      themeToggle.replaceChildren(icon(theme === 'light' ? 'moon' : 'sun'));
    },
    setSurface(surface) {
      close();
      explore.hidden = surface === 'title';
      sections.querySelectorAll('[data-current]').forEach((node) => node.removeAttribute('data-current'));
      for (const { link, matches } of sectionLinks) {
        const active = matches(surface);
        link.parentElement!.toggleAttribute('data-current', active);
        if (active) link.setAttribute('aria-current', link.pathname === window.location.pathname ? 'page' : 'location');
        else link.removeAttribute('aria-current');
      }
      for (const item of tracked) {
        const withinSection = item.surface === 'docs-world-api' && surface.startsWith('docs-world-api-');
        if (item.surface === surface || withinSection) {
          item.link.setAttribute('aria-current', withinSection ? 'location' : 'page');
          item.trigger.dataset['current'] = 'true';
        } else item.link.removeAttribute('aria-current');
      }
      if (surface === 'title') home.setAttribute('aria-current', 'page');
      else home.removeAttribute('aria-current');
    },
  };
}
