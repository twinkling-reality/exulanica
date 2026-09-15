// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { buildChrome, STATION_COLOR } from '../src/ui/chrome.js';
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
    const onResearch = vi.fn();
    const onWaitlist = vi.fn();
    const onDevelopers = vi.fn();
    const chrome = buildChrome({
      atlasHref: 'https://atlas.example/session',
      onHome,
      onPurpose,
      onCapabilities,
      onResearch,
      onWaitlist,
      onDevelopers,
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

    chrome.setSurface('research');
    expect(chrome.root.querySelector('#path-research')?.getAttribute('aria-current')).toBe('page');
    expect(marker?.dataset['target']).toBe('path-resources');
  });

  it('opens Resources as one keyboard-operable station and restores focus on Escape', () => {
    const chrome = buildChrome({
      atlasHref: 'https://atlas.example/session',
      onHome: vi.fn(),
      onPurpose: vi.fn(),
      onCapabilities: vi.fn(),
      onResearch: vi.fn(),
      onWaitlist: vi.fn(),
      onDevelopers: vi.fn(),
    });
    document.body.append(chrome.root);
    chrome.setSurface('title');

    const resources = chrome.root.querySelector<HTMLButtonElement>('#path-resources');
    const disclosure = chrome.root.querySelector<HTMLElement>('#resource-links');
    const back = chrome.root.querySelector<HTMLButtonElement>('#resource-back');
    const docs = chrome.root.querySelector<HTMLAnchorElement>('#resource-docs');
    const research = chrome.root.querySelector<HTMLAnchorElement>('#path-research');
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
    expect(research?.tagName).toBe('A');
    expect(research?.getAttribute('href')).toBe('#research');
    expect(github?.tagName).toBe('A');
    expect(purpose?.hidden).toBe(true);
    expect(
      Array.from(
        disclosure?.querySelectorAll<HTMLElement>('.destination') ?? [],
        (node) => node.textContent?.trim(),
      ),
    ).toEqual(['Back', 'Documentation', 'Research', 'Developers', 'GitHub']);

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
      onResearch: vi.fn(),
      onWaitlist: vi.fn(),
      onDevelopers: vi.fn(),
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

  /*
   * The one dead control on the page, kept on purpose.
   *
   * Everything else is live or absent, and the disabled Enter Exulanica station was removed for
   * exactly the reason this one exists. It is scaffolding: the route and the slot are in place
   * before the writing is. If this test fails because somebody enabled the entry, check that the
   * Developers page actually has copy first, then delete this test with the disabled line.
   */
  it('keeps Developers scaffolded and visibly unavailable', () => {
    const chrome = buildChrome({
      atlasHref: 'https://atlas.example/session',
      onHome: vi.fn(),
      onPurpose: vi.fn(),
      onCapabilities: vi.fn(),
      onResearch: vi.fn(),
      onWaitlist: vi.fn(),
      onDevelopers: vi.fn(),
    });
    document.body.append(chrome.root);
    chrome.setSurface('title');

    const developers = chrome.root.querySelector<HTMLButtonElement>('#path-developers');
    expect(developers?.tagName).toBe('BUTTON');
    expect(developers?.disabled).toBe(true);
    // The label is the whole accessible name; the reason is a separate description.
    expect(developers?.textContent?.trim()).toBe('Developers');
    expect(developers?.getAttribute('aria-describedby')).toBe('developers-pending');
    expect(chrome.root.querySelector('#developers-pending')?.textContent).toBe('Not written yet');
    // It is a station without a Companion colour or face, because nothing can stand on it.
    expect(STATION_COLOR['path-developers']).toBeUndefined();
  });

  it('uses the public product name in the desktop boundary', () => {
    const boundary = buildViewportBoundary();
    expect(boundary.root.querySelector('.boundary-eyebrow')?.textContent).toBe('Exulanica');
  });

  /*
   * The disconnected build used to lead with a greyed Enter Exulanica and a line saying the world
   * was not connected. An unusable control is not made honest by a caption under it, so the
   * station is absent instead and the waitlist leads. Nothing in the column is ever dead.
   */
  it('offers the waitlist instead of a dead entry when no world is connected', () => {
    const chrome = buildChrome({
      atlasHref: null,
      onHome: vi.fn(),
      onPurpose: vi.fn(),
      onCapabilities: vi.fn(),
      onResearch: vi.fn(),
      onWaitlist: vi.fn(),
      onDevelopers: vi.fn(),
    });
    const marker = chrome.root.querySelector<SVGSVGElement>('.companion-menu-marker');

    chrome.setSurface('title');
    expect(chrome.root.querySelector('#path-enter')).toBeNull();
    expect(chrome.root.querySelector('[role="status"]')).toBeNull();

    const waitlist = chrome.root.querySelector<HTMLAnchorElement>('#path-waitlist');
    expect(waitlist?.tagName).toBe('A');
    expect(waitlist?.getAttribute('href')).toBe('#waitlist');
    expect(waitlist?.classList.contains('destination-primary')).toBe(true);
    expect(waitlist?.hidden).toBe(false);
    expect(marker?.dataset['target']).toBe('path-waitlist');

    expect(
      Array.from(
        chrome.root.querySelectorAll<HTMLElement>('.destinations > .destination'),
        (node) => (node.hidden ? null : node.textContent?.trim()),
      ).filter(Boolean),
    ).toEqual(['Join the waitlist', 'Purpose', 'Capabilities', 'Resources']);
  });

  it('leads with Enter Exulanica and builds no waitlist station when a world is connected', () => {
    const chrome = buildChrome({
      atlasHref: 'https://atlas.example/session',
      onHome: vi.fn(),
      onPurpose: vi.fn(),
      onCapabilities: vi.fn(),
      onResearch: vi.fn(),
      onWaitlist: vi.fn(),
      onDevelopers: vi.fn(),
    });
    chrome.setSurface('title');
    const atlas = chrome.root.querySelector<HTMLAnchorElement>('#path-enter');
    expect(atlas?.classList.contains('destination-primary')).toBe(true);
    // Two ways in, when only one of them exists, is the thing this replaced.
    expect(chrome.root.querySelector('#path-waitlist')).toBeNull();
    expect(
      chrome.root.querySelector<SVGSVGElement>('.companion-menu-marker')?.dataset['target'],
    ).toBe('path-enter');
  });
});
