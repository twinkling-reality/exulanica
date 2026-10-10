// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { buildChrome } from '../src/ui/chrome.js';
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
  beforeEach(() => document.body.replaceChildren());
  afterEach(() => { document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })); vi.useRealTimers(); });

  it('keeps the waitlist invitation regardless of app configuration', () => {
    for (const atlasHref of [null, 'https://atlas.example/session']) {
      const title = buildTitle({ atlasHref });
      expect(title.getAttribute('aria-labelledby')).toBe(title.querySelector('h1')?.id);
      expect(title.querySelector('.field-form')?.getAttribute('aria-hidden')).toBe('true');
      expect(title.querySelectorAll('.hero-actions a')).toHaveLength(1);
      expect(title.querySelectorAll('[aria-controls="home-preview"]')).toHaveLength(2);
      expect(title.querySelector('#hero-entry')?.getAttribute('href')).toBe('/waitlist');
      expect(title.querySelector('#hero-entry')?.textContent).toBe('Join Waitlist');
    }
  });

  it('keeps home and creator links available and does not invent an application destination', () => {
    const chrome = setup();
    expect(chrome.root.getAttribute('aria-label')).toBe('Primary navigation');
    expect(chrome.root.querySelector('#path-home')?.getAttribute('href')).toBe('/');
    expect(chrome.root.querySelector('a[href="https://twinklingreality.com/"]')?.getAttribute('aria-label')).toBe('Twinkling Reality (external)');
    expect(chrome.root.querySelector('a[aria-label="GitHub (external)"]')).not.toBeNull();
    expect(chrome.root.querySelector('#path-enter')).toBeNull();
    expect(chrome.root.querySelector<HTMLAnchorElement>('#path-waitlist')?.hidden).toBe(true);
    expect(chrome.root.querySelector('.nav-utilities .icon-github')).not.toBeNull();
    expect(chrome.root.querySelector('.nav-utilities .icon-twinkling')).not.toBeNull();
    chrome.setSurface('purpose');
    expect(chrome.root.querySelector<HTMLAnchorElement>('#path-waitlist')?.hidden).toBe(false);
    chrome.setSurface('waitlist');
    expect(chrome.root.querySelector<HTMLAnchorElement>('#path-waitlist')?.hidden).toBe(true);
  });

  it('keeps the waitlist without adding app navigation in connected builds', () => {
    const chrome = setup('https://atlas.example/session');
    expect(chrome.root.querySelector('#path-waitlist')?.getAttribute('href')).toBe('/waitlist');
    chrome.setSurface('purpose');
    expect(chrome.root.querySelector('#path-enter')).toBeNull();
  });

  it('opens only one disclosure and restores focus when Escape closes it', () => {
    const chrome = setup();
    click(chrome.root, 'menu-explore');
    expect(chrome.root.querySelector<HTMLElement>('#panel-explore')?.hidden).toBe(false);
    click(chrome.root, 'menu-builders');
    expect(chrome.root.querySelector<HTMLElement>('#panel-explore')?.hidden).toBe(true);
    expect(chrome.root.querySelector('#menu-explore')?.getAttribute('aria-expanded')).toBe('false');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(chrome.root.querySelector<HTMLElement>('#panel-builders')?.hidden).toBe(true);
    expect(document.activeElement?.id).toBe('menu-builders');
  });

  it('supports keyboard entry, normal links, and closing when focus leaves the group', () => {
    const chrome = setup();
    const trigger = chrome.root.querySelector<HTMLButtonElement>('#menu-explore')!;
    trigger.focus();
    trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    expect(document.activeElement?.id).toBe('path-purpose');
    chrome.root.querySelector<HTMLAnchorElement>('#path-capabilities')!.focus();
    expect(chrome.root.querySelector<HTMLElement>('#panel-explore')?.hidden).toBe(false);
    chrome.root.querySelector<HTMLAnchorElement>('#path-home')!.focus();
    expect(chrome.root.querySelector<HTMLElement>('#panel-explore')?.hidden).toBe(true);
  });

  it('keeps the focused dropdown destination visible when opening another tab or window', () => {
    const chrome = setup();
    click(chrome.root, 'menu-builders');
    const link = chrome.root.querySelector<HTMLAnchorElement>('#path-developers')!;
    link.focus();
    for (const modifier of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }]) {
      link.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, ...modifier }));
      expect(chrome.root.querySelector<HTMLElement>('#panel-builders')?.hidden).toBe(false);
      expect(document.activeElement).toBe(link);
    }
  });

  it('opens on mouse hover and holds the menu across the gap into its links', () => {
    vi.useFakeTimers();
    const chrome = setup();
    const trigger = chrome.root.querySelector('#menu-resources')!;
    const panel = chrome.root.querySelector<HTMLElement>('#panel-resources')!;
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
    const trigger = chrome.root.querySelector<HTMLButtonElement>('#menu-resources')!;
    const panel = chrome.root.querySelector<HTMLElement>('#panel-resources')!;
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

  it('switches hovered categories without leaving multiple panels open', () => {
    const chrome = setup();
    for (const key of ['explore', 'builders', 'resources']) {
      chrome.root.querySelector(`#menu-${key}`)!.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }));
      expect([...chrome.root.querySelectorAll<HTMLElement>('.menu-panel')].filter(panel => !panel.hidden).map(panel => panel.id)).toEqual([`panel-${key}`]);
    }
  });

  it('closes after following a destination and marks the containing group as current', () => {
    const chrome = setup();
    click(chrome.root, 'menu-builders');
    chrome.root.querySelector<HTMLAnchorElement>('#path-developers')!.click();
    expect(chrome.root.querySelector('#path-developers')?.getAttribute('href')).toBe('/developers');
    expect(chrome.root.querySelector<HTMLElement>('#panel-builders')?.hidden).toBe(true);
    chrome.setSurface('developers');
    expect(chrome.root.querySelector('#path-developers')?.getAttribute('aria-current')).toBe('page');
    expect(chrome.root.querySelector('#menu-builders')?.getAttribute('data-current')).toBe('true');
    chrome.setSurface('title');
    expect(chrome.root.querySelector('#menu-builders')?.hasAttribute('data-current')).toBe(false);
  });
});
