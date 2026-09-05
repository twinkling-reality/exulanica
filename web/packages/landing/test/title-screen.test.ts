// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { buildChrome } from '../src/ui/chrome.js';
import { buildTitle } from '../src/ui/title.js';
import { buildViewportBoundary } from '../src/ui/viewport-boundary.js';

describe('the Exulanica title screen', () => {
  beforeEach(() => document.body.replaceChildren());

  it('presents one primary wordmark and one decorative gradient field', () => {
    const title = buildTitle();

    expect(title.querySelector('h1')?.textContent).toBe('Exulanica');
    expect(title.getAttribute('aria-labelledby')).toBe('title-wordmark');
    expect(title.querySelector('.proposition')?.textContent).toBe(
      'A personal world memory model',
    );
    expect(title.querySelectorAll('.title-artwork')).toHaveLength(1);
    expect(title.querySelector('.title-artwork')?.getAttribute('aria-hidden')).toBe('true');
    expect(title.querySelectorAll('img')).toHaveLength(0);
    expect(title.querySelector('.publisher-mark')?.textContent).toBe(
      '© 2026 Twinkling Reality',
    );
  });

  it('keeps the title menu semantic and preserves the keyboard destination ids', () => {
    const onHome = vi.fn();
    const onPurpose = vi.fn();
    const onCapabilities = vi.fn();
    const chrome = buildChrome({
      atlasHref: 'https://atlas.example/session',
      onHome,
      onPurpose,
      onCapabilities,
    });
    document.body.append(chrome.root);

    const atlas = chrome.root.querySelector<HTMLAnchorElement>('#path-enter');
    const purpose = chrome.root.querySelector<HTMLAnchorElement>('#path-purpose');
    const capabilities = chrome.root.querySelector<HTMLAnchorElement>('#path-capabilities');
    const resources = chrome.root.querySelector<HTMLButtonElement>('#path-resources');
    const home = chrome.root.querySelector<HTMLAnchorElement>('#path-home');
    const marker = chrome.root.querySelector<SVGSVGElement>('.companion-menu-marker');

    expect(chrome.root.tagName).toBe('NAV');
    expect(chrome.root.getAttribute('aria-label')).toBe('Primary navigation');
    expect(atlas?.textContent).toContain('Enter Exulanica');
    expect(atlas?.href).toBe('https://atlas.example/session');
    expect(purpose?.tagName).toBe('A');
    expect(purpose?.getAttribute('href')).toBe('#purpose');
    expect(capabilities?.tagName).toBe('A');
    expect(capabilities?.getAttribute('href')).toBe('#capabilities');
    expect(resources?.tagName).toBe('BUTTON');
    expect(resources?.getAttribute('aria-controls')).toBe('resource-links');
    expect(chrome.root.querySelectorAll('.companion-menu-marker')).toHaveLength(1);
    expect(marker?.getAttribute('aria-hidden')).toBe('true');
    expect(marker?.getAttribute('focusable')).toBe('false');
    expect(marker?.hasAttribute('tabindex')).toBe(false);
    expect(marker?.querySelectorAll('.companion-menu-wake')).toHaveLength(1);

    chrome.setSurface('title');
    expect(home?.hidden).toBe(true);
    expect(atlas?.hidden).toBe(false);
    expect(
      Array.from(
        chrome.root.querySelectorAll<HTMLElement>('.destinations > .destination'),
        (node) => node.hidden ? null : node.textContent?.trim(),
      ).filter(Boolean),
    ).toEqual(['Enter Exulanica', 'Purpose', 'Capabilities', 'Resources']);
    expect(purpose?.hasAttribute('aria-current')).toBe(false);
    expect(marker?.dataset['target']).toBe('path-enter');

    purpose?.dispatchEvent(new PointerEvent('pointerenter'));
    expect(marker?.dataset['target']).toBe('path-purpose');
    expect(marker?.dataset['motion']).toMatch(/^down-/);
    capabilities?.dispatchEvent(new FocusEvent('focus'));
    atlas?.dispatchEvent(new PointerEvent('pointerenter'));
    expect(marker?.dataset['target']).toBe('path-capabilities');
    expect(marker?.dataset['state']).toBe('attending');
    expect(marker?.dataset['motion']).toMatch(/^down-/);
    capabilities?.dispatchEvent(new FocusEvent('blur'));
    expect(marker?.dataset['target']).toBe('path-enter');
    expect(marker?.dataset['motion']).toMatch(/^up-/);

    chrome.setSurface('purpose');
    expect(home?.hidden).toBe(false);
    expect(atlas?.hidden).toBe(true);
    expect(
      Array.from(
        chrome.root.querySelectorAll<HTMLElement>('.destinations > .destination'),
        (node) => node.hidden ? null : node.textContent?.trim(),
      ).filter(Boolean),
    ).toEqual(['Return', 'Purpose', 'Capabilities', 'Resources']);
    expect(purpose?.getAttribute('aria-current')).toBe('page');
    expect(capabilities?.hasAttribute('aria-current')).toBe(false);
    expect(marker?.dataset['target']).toBe('path-purpose');

    chrome.setSurface('capabilities');
    expect(purpose?.hasAttribute('aria-current')).toBe(false);
    expect(capabilities?.getAttribute('aria-current')).toBe('page');
    expect(marker?.dataset['target']).toBe('path-capabilities');
  });

  it('opens Resources as one keyboard-operable station and restores focus on Escape', () => {
    const chrome = buildChrome({
      atlasHref: 'https://atlas.example/session',
      onHome: vi.fn(),
      onPurpose: vi.fn(),
      onCapabilities: vi.fn(),
    });
    document.body.append(chrome.root);
    chrome.setSurface('title');

    const resources = chrome.root.querySelector<HTMLButtonElement>('#path-resources');
    const disclosure = chrome.root.querySelector<HTMLElement>('#resource-links');
    const back = chrome.root.querySelector<HTMLButtonElement>('#resource-back');
    const docs = chrome.root.querySelector<HTMLAnchorElement>('#resource-docs');
    const github = chrome.root.querySelector<HTMLAnchorElement>('#resource-github');
    const purpose = chrome.root.querySelector<HTMLAnchorElement>('#path-purpose');
    const marker = chrome.root.querySelector<SVGSVGElement>('.companion-menu-marker');

    expect(resources?.getAttribute('aria-expanded')).toBe('false');
    expect(disclosure?.hidden).toBe(true);
    expect(chrome.root.querySelectorAll('#path-docs, #path-github')).toHaveLength(0);

    resources?.click();
    expect(resources?.getAttribute('aria-expanded')).toBe('true');
    expect(disclosure?.hidden).toBe(false);
    expect(back?.tagName).toBe('BUTTON');
    expect(docs?.tagName).toBe('A');
    expect(github?.tagName).toBe('A');
    expect(purpose?.hidden).toBe(true);
    expect(
      Array.from(
        disclosure?.querySelectorAll<HTMLElement>('.destination') ?? [],
        (node) => node.textContent?.trim(),
      ),
    ).toEqual(['Back', 'Documentation', 'GitHub']);

    docs?.dispatchEvent(new FocusEvent('focusin', { bubbles: true, relatedTarget: resources }));
    purpose?.dispatchEvent(new PointerEvent('pointerenter'));
    expect(marker?.dataset['target']).toBe('path-resources');
    expect(github?.tagName).toBe('A');

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(disclosure?.hidden).toBe(true);
    expect(resources?.getAttribute('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(resources);
    expect(purpose?.hidden).toBe(false);
  });

  it('dismisses Resources on an outside pointer press without opening it on hover', () => {
    const chrome = buildChrome({
      atlasHref: 'https://atlas.example/session',
      onHome: vi.fn(),
      onPurpose: vi.fn(),
      onCapabilities: vi.fn(),
    });
    document.body.append(chrome.root);
    chrome.setSurface('title');

    const resources = chrome.root.querySelector<HTMLButtonElement>('#path-resources');
    const disclosure = chrome.root.querySelector<HTMLElement>('#resource-links');
    const back = chrome.root.querySelector<HTMLButtonElement>('#resource-back');

    resources?.dispatchEvent(new PointerEvent('pointerenter'));
    expect(disclosure?.hidden).toBe(true);
    resources?.click();
    back?.click();
    expect(disclosure?.hidden).toBe(true);
    expect(document.activeElement).toBe(resources);
    resources?.click();
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    expect(disclosure?.hidden).toBe(true);
    expect(resources?.getAttribute('aria-expanded')).toBe('false');
  });

  it('uses the public product name in the desktop boundary', () => {
    const boundary = buildViewportBoundary();
    expect(boundary.root.querySelector('.boundary-eyebrow')?.textContent).toBe('Exulanica');
  });

  it('keeps the entry station when the world destination is disconnected', () => {
    const chrome = buildChrome({
      atlasHref: null,
      onHome: vi.fn(),
      onPurpose: vi.fn(),
      onCapabilities: vi.fn(),
    });
    const marker = chrome.root.querySelector<SVGSVGElement>('.companion-menu-marker');

    chrome.setSurface('title');
    const atlas = chrome.root.querySelector<HTMLButtonElement>('#path-enter');
    expect(atlas?.tagName).toBe('BUTTON');
    expect(atlas?.textContent).toContain('Enter Exulanica');
    expect(atlas?.disabled).toBe(true);
    expect(atlas?.getAttribute('aria-describedby')).toBe('atlas-status');
    expect(chrome.root.querySelector('[role="status"]')?.textContent).toContain('not connected');
    expect(marker?.dataset['target']).toBe('path-enter');
  });
});
