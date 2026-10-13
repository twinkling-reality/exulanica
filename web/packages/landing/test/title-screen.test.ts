// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { buildChrome } from '../src/ui/chrome.js';
import { WORLD_SCENES } from '../src/ui/world-scenes.js';
import { buildTitle } from '../src/ui/title.js';

function setup(atlasHref: string | null = null) {
  const options = { atlasHref };
  const chrome = buildChrome();
  document.body.append(chrome.root);
  chrome.setSurface('title');
  return { ...chrome, options };
}
const click = (root: HTMLElement, id: string) => root.querySelector<HTMLButtonElement>(`#${id}`)!.click();

describe('the public invitation and navigation', () => {
  beforeEach(() => { document.body.replaceChildren(); window.history.replaceState(null, '', '/'); });
  afterEach(() => { document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })); vi.useRealTimers(); });

  it('offers a product introduction without promising hosted signup', () => {
    for (const atlasHref of [null, 'https://atlas.example/session']) {
      const title = buildTitle({ atlasHref });
      expect(title.getAttribute('aria-labelledby')).toBe(title.querySelector('h1')?.id);
      expect(title.querySelector('.field-form')?.getAttribute('aria-hidden')).toBe('true');
      expect(title.querySelectorAll('.hero-actions a')).toHaveLength(1);
      expect(title.querySelectorAll('[aria-controls="home-preview"]')).toHaveLength(WORLD_SCENES.length);
      expect(title.querySelector('#hero-entry')?.getAttribute('href')).toBe(atlasHref ?? '/docs/self-hosting');
      expect(title.querySelector('#hero-entry')?.textContent).toBe(atlasHref ? 'Open Exulanica' : 'Run Exulanica');
    }
  });

  it('replaces the resting invitation with selected world details and restores it on dismissal', () => {
    const title = buildTitle({ atlasHref: 'https://atlas.example/' });
    document.body.append(title);
    const world = title.querySelector<HTMLButtonElement>('.world-choice')!;
    world.focus();
    expect(title.hasAttribute('data-world-preview')).toBe(true);
    expect(title.querySelector<HTMLElement>('.hero-content')?.inert).toBe(true);
    expect(title.querySelector<HTMLElement>('.hero-actions')?.inert).toBe(true);
    const preview = title.querySelector<HTMLElement>('.world-center-preview')!;
    expect(preview.hidden).toBe(false);
    expect(preview.querySelector('.context-visual')).toBeNull();
    expect(preview.querySelector('h2')?.textContent).toBe(WORLD_SCENES[0]!.name);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(title.hasAttribute('data-world-preview')).toBe(false);
    expect(title.querySelector<HTMLElement>('.hero-content')?.inert).toBe(false);
    expect(title.querySelector<HTMLElement>('.hero-actions')?.inert).toBe(false);
    expect(document.activeElement).toBe(world);
  });

  it('keeps home and creator links available and does not invent an application destination', () => {
    const chrome = setup();
    expect(chrome.root.getAttribute('aria-label')).toBe('Primary navigation');
    expect(chrome.root.querySelector('#path-home')?.getAttribute('href')).toBe('/');
    expect(chrome.root.querySelector('a[href="https://twinklingreality.com/"]')?.getAttribute('aria-label')).toBe('Twinkling Reality (external)');
    expect(chrome.root.querySelector('a[aria-label="GitHub (external)"]')).not.toBeNull();
    expect(chrome.root.querySelector('#path-enter')).toBeNull();
    expect(chrome.root.querySelector('#path-start')).toBeNull();
    expect(chrome.root.querySelector('.nav-utilities .icon-github')).not.toBeNull();
    expect(chrome.root.querySelector('.nav-utilities .icon-twinkling')).not.toBeNull();
    chrome.setSurface('product');
    expect(chrome.root.querySelector('#path-start')).toBeNull();
    chrome.setSurface('docs');
    expect(chrome.root.querySelector('#path-start')).toBeNull();
  });

  it('links to setup without inventing an application destination', () => {
    const chrome = setup('https://atlas.example/session');
    expect(chrome.root.querySelector('#path-installation')?.getAttribute('href')).toBe('/docs/self-hosting');
    chrome.setSurface('product');
    expect(chrome.root.querySelector('#path-enter')).toBeNull();
  });

  it('keeps section destinations independent of mouse, touch and keyboard disclosure', () => {
    const chrome = setup();
    const links = [...chrome.root.querySelectorAll<HTMLAnchorElement>('.nav-section-link')];
    expect(links.map(link => link.getAttribute('href'))).toEqual(['/product', '/use-cases', '/docs']);
    const trigger = chrome.root.querySelector<HTMLButtonElement>('#menu-documentation')!;
    expect(trigger.getAttribute('aria-label')).toBe('Show documentation menu');
    links[2]!.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'touch' }));
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    trigger.click();
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(links[2]!.getAttribute('href')).toBe('/docs');
    trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    expect(document.activeElement?.getAttribute('href')).toBe('/docs');
  });

  it('restores focus when Escape closes the developer menu', () => {
    const chrome = setup();
    click(chrome.root, 'menu-documentation');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(chrome.root.querySelector<HTMLElement>('#panel-documentation')?.hidden).toBe(true);
    expect(document.activeElement?.id).toBe('menu-documentation');
  });

  it('supports keyboard entry, normal links, and closing when focus leaves the group', () => {
    const chrome = setup();
    const trigger = chrome.root.querySelector<HTMLButtonElement>('#menu-documentation')!;
    trigger.focus();
    trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    expect(document.activeElement?.getAttribute('href')).toBe('/docs');
    chrome.root.querySelector<HTMLAnchorElement>('#path-api')!.focus();
    expect(chrome.root.querySelector<HTMLElement>('#panel-documentation')?.hidden).toBe(false);
    chrome.root.querySelector<HTMLAnchorElement>('#path-home')!.focus();
    expect(chrome.root.querySelector<HTMLElement>('#panel-documentation')?.hidden).toBe(true);
  });

  it('moves one decorative companion between measured rows for mouse and keyboard attention', () => {
    const chrome = setup();
    const panel = chrome.root.querySelector<HTMLElement>('#panel-documentation')!;
    const track = panel.querySelector<HTMLElement>('.menu-companions')!;
    const companion = track.querySelector<SVGSVGElement>('svg')!;
    const first = panel.querySelector<HTMLAnchorElement>('#path-installation')!;
    const second = panel.querySelector<HTMLAnchorElement>('#path-api')!;
    vi.spyOn(track, 'getBoundingClientRect').mockReturnValue(new DOMRect(200, 100, 28, 180));
    vi.spyOn(first, 'getBoundingClientRect').mockReturnValue(new DOMRect(10, 110, 190, 44));
    // Unequal row heights exercise layout-driven placement, including a wrapped label.
    vi.spyOn(second, 'getBoundingClientRect').mockReturnValue(new DOMRect(10, 176, 190, 70));
    click(chrome.root, 'menu-documentation');
    expect(track.querySelectorAll('svg')).toHaveLength(1);
    expect(companion.getAttribute('aria-hidden')).toBe('true');
    expect(companion.dataset.state).toBe('resting');
    first.focus();
    expect(companion.style.getPropertyValue('--companion-target-y')).toBe('20px');
    expect(companion.dataset.state).toBe('attending');
    second.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }));
    expect(companion.style.getPropertyValue('--companion-target-y')).toBe('99px');
    expect(document.activeElement).toBe(first);
    panel.dispatchEvent(new PointerEvent('pointerleave', { pointerType: 'mouse' }));
    expect(companion.style.getPropertyValue('--companion-target-y')).toBe('20px');
    second.focus();
    expect(companion.style.getPropertyValue('--companion-target-y')).toBe('99px');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(companion.dataset.state).toBe('resting');
    expect(document.activeElement?.id).toBe('menu-documentation');
  });

  it('keeps the focused dropdown destination visible when opening another tab or window', () => {
    const chrome = setup();
    click(chrome.root, 'menu-documentation');
    const link = chrome.root.querySelector<HTMLAnchorElement>('#path-installation')!;
    link.focus();
    for (const modifier of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }]) {
      link.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, ...modifier }));
      expect(chrome.root.querySelector<HTMLElement>('#panel-documentation')?.hidden).toBe(false);
      expect(document.activeElement).toBe(link);
    }
  });

  it('opens on mouse hover and holds the menu across the gap into its links', () => {
    vi.useFakeTimers();
    const chrome = setup();
    const trigger = chrome.root.querySelector('#menu-documentation')!;
    const panel = chrome.root.querySelector<HTMLElement>('#panel-documentation')!;
    trigger.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }));
    expect(panel.hidden).toBe(false);
    trigger.dispatchEvent(new PointerEvent('pointerleave', { pointerType: 'mouse' }));
    vi.advanceTimersByTime(150);
    panel.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }));
    vi.advanceTimersByTime(300);
    expect(panel.hidden).toBe(false);
    panel.dispatchEvent(new PointerEvent('pointerleave', { pointerType: 'mouse' }));
    vi.advanceTimersByTime(250);
    expect(panel.hidden).toBe(true);
  });

  it('keeps the first click after hover open, and supports tap toggling without touch hover', () => {
    const chrome = setup();
    const trigger = chrome.root.querySelector<HTMLButtonElement>('#menu-documentation')!;
    const panel = chrome.root.querySelector<HTMLElement>('#panel-documentation')!;
    trigger.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'touch' }));
    expect(panel.hidden).toBe(true);
    trigger.click();
    expect(panel.hidden).toBe(false);
    trigger.click();
    expect(panel.hidden).toBe(true);
    trigger.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }));
    trigger.click();
    expect(panel.hidden).toBe(false);
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    expect(panel.hidden).toBe(true);
  });

  it.each(['product', 'use-cases', 'documentation'])('supports hover and keyboard entry in the %s dropdown', key => {
    const chrome = setup();
    const trigger = chrome.root.querySelector<HTMLButtonElement>(`#menu-${key}`)!;
    const panel = chrome.root.querySelector<HTMLElement>(`#panel-${key}`)!;
    trigger.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }));
    expect(panel.hidden).toBe(false);
    expect(panel.querySelectorAll('.menu-companions svg')).toHaveLength(1);
    trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    expect(document.activeElement).toBe(panel.querySelector('a'));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(panel.hidden).toBe(true);
    expect(document.activeElement).toBe(trigger);
  });

  it('offers distinct Product overview and capability destinations', () => {
    const chrome = setup();
    const explore = chrome.root.querySelector<HTMLAnchorElement>('.header-entry')!;
    chrome.setSurface('title');
    expect(explore.hidden).toBe(true);
    expect(chrome.root.querySelector('[data-menu="product"] button')).not.toBeNull();
    expect(chrome.root.querySelectorAll('.nav-utilities a.utility-link')).toHaveLength(2);
    expect(chrome.root.querySelector('.nav-utilities button[aria-label="Switch to dark theme"]')).not.toBeNull();
    const children = [...chrome.root.querySelectorAll<HTMLAnchorElement>('[data-menu="product"] .menu-link')];
    const hubs = [...chrome.root.querySelectorAll<HTMLAnchorElement>('.nav-section-link')].map(link => link.getAttribute('href'));
    expect(new Set(children.map(link => link.getAttribute('href'))).size).toBe(children.length);
    for (const link of children.filter(link => link.id !== 'path-product' && link.getAttribute('href') !== '/docs')) expect(hubs).not.toContain(link.getAttribute('href'));
    window.history.replaceState(null, '', '/product');
    chrome.setSurface('product');
    expect(explore.hidden).toBe(false);
    expect(chrome.root.querySelector('#path-product')?.getAttribute('aria-current')).toBe('page');
  });

  it('marks section destinations and the containing API section', () => {
    const chrome = setup();
    chrome.setSurface('use-cases');
    expect(chrome.root.querySelector('.nav-section-link[href="/use-cases"]')?.hasAttribute('aria-current')).toBe(true);
    window.history.replaceState(null, '', '/docs/api-reference');
    chrome.setSurface('docs-api-reference');
    expect(chrome.root.querySelector('#path-api')?.getAttribute('aria-current')).toBe('page');
    expect(chrome.root.querySelector('#menu-documentation')?.getAttribute('data-current')).toBe('true');
    expect(chrome.root.querySelector('.nav-section-link[href="/use-cases"]')?.hasAttribute('aria-current')).toBe(false);
  });

  it('closes after following a destination and marks the containing group as current', () => {
    const chrome = setup();
    click(chrome.root, 'menu-documentation');
    chrome.root.querySelector<HTMLAnchorElement>('#path-installation')!.click();
    expect(chrome.root.querySelector('#path-installation')?.getAttribute('href')).toBe('/docs/self-hosting');
    expect(chrome.root.querySelector<HTMLElement>('#panel-documentation')?.hidden).toBe(true);
    chrome.setSurface('docs-self-hosting');
    expect(chrome.root.querySelector('#path-installation')?.getAttribute('aria-current')).toBe('page');
    expect(chrome.root.querySelector('#menu-documentation')?.getAttribute('data-current')).toBe('true');
    chrome.setSurface('title');
    expect(chrome.root.querySelector('#menu-documentation')?.hasAttribute('data-current')).toBe(false);
  });
});
