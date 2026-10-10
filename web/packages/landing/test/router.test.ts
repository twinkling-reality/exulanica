// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createRouter, resolveRoute, ROUTES, type Navigation } from '../src/router.js';

let router: ReturnType<typeof createRouter> | undefined;
beforeEach(() => {
  window.history.replaceState(null, '', '/');
  document.body.replaceChildren();
});
afterEach(() => { router?.destroy(); router = undefined; });

function fixture(path = '/') {
  window.history.replaceState(null, '', path);
  let scroll = 0;
  const navigate = vi.fn<(navigation: Navigation) => void>();
  router = createRouter({ onNavigate: navigate, readScroll: () => scroll });
  const follow = (href: string, properties: MouseEventInit = {}, attributes: Record<string, string> = {}) => {
    const link = document.createElement('a');
    link.href = href;
    for (const [name, value] of Object.entries(attributes)) link.setAttribute(name, value);
    document.body.append(link);
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0, ...properties });
    // Observe router ownership, then stop Happy DOM from performing a real network navigation.
    let intercepted = false;
    document.addEventListener('click', (dispatched) => {
      intercepted = dispatched.defaultPrevented;
      dispatched.preventDefault();
    }, { once: true });
    link.dispatchEvent(event);
    return { defaultPrevented: intercepted };
  };
  return { navigate, follow, setScroll(value: number) { scroll = value; } };
}

describe('public page routing', () => {
  it('resolves every direct page and displays an honest unknown route', () => {
    for (const route of ROUTES) expect(resolveRoute(new URL(route.path, 'https://exulanica.com'))).toEqual(route);
    expect(resolveRoute(new URL('https://exulanica.com/docs/agents/')).surface).toBe('docs-agents');
    expect(resolveRoute(new URL('https://exulanica.com/roadmap')).surface).toBe('roadmap');
    expect(resolveRoute(new URL('https://exulanica.com/missing')).surface).toBe('not-found');
    const { navigate } = fixture('/missing');
    expect(navigate.mock.lastCall?.[0].route.surface).toBe('not-found');
    expect(document.title).toBe('Page not found | Exulanica');
  });

  it('opens a deep article directly and retains its section anchor', () => {
    const { navigate } = fixture('/docs/world-api#authorization');
    expect(navigate.mock.lastCall?.[0]).toMatchObject({
      route: { surface: 'docs-world-api' }, anchor: '#authorization', restoreScroll: null,
    });
    expect(document.title).toBe('World API | Exulanica');
  });

  it('uses history for internal links and updates the document title', () => {
    const { navigate, follow } = fixture();
    expect(follow('/developers').defaultPrevented).toBe(true);
    expect(window.location.pathname).toBe('/developers');
    expect(document.title).toBe('Developers | Exulanica');
    expect(navigate).toHaveBeenCalledTimes(2);
    follow('/docs/agents');
    expect(navigate.mock.lastCall?.[0].route.surface).toBe('docs-agents');
  });

  it('canonicalizes legacy surface hashes without treating article fragments as routes', () => {
    const { follow, navigate } = fixture('/#waitlist');
    expect(window.location.pathname).toBe('/waitlist');
    expect(window.location.hash).toBe('');
    expect(navigate.mock.lastCall?.[0].route.surface).toBe('waitlist');
    follow('#developers');
    expect(window.location.pathname).toBe('/developers');
    follow('/docs');
    const calls = navigate.mock.calls.length;
    expect(follow('#getting-started').defaultPrevented).toBe(false);
    expect(navigate).toHaveBeenCalledTimes(calls);
  });

  it('refocuses a reselected page without adding history or losing scroll', () => {
    const { follow, navigate, setScroll } = fixture('/docs');
    const state = window.history.state;
    setScroll(220);
    expect(follow('/docs').defaultPrevented).toBe(true);
    expect(window.history.state).toEqual(state);
    expect(navigate.mock.lastCall?.[0]).toMatchObject({ route: { surface: 'docs' }, restoreScroll: 220 });
  });

  it('records native fragment entries so Back restores their previous reading positions', () => {
    const { follow, navigate, setScroll } = fixture('/docs');
    const baseState = window.history.state;
    setScroll(90);
    expect(follow('#getting-started').defaultPrevented).toBe(false);
    window.history.pushState(null, '', '/docs#getting-started');
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    const anchorState = window.history.state;
    expect(anchorState.landingKey).not.toBe(baseState.landingKey);
    setScroll(600);
    follow('/developers');
    window.history.replaceState(anchorState, '', '/docs#getting-started');
    window.dispatchEvent(new PopStateEvent('popstate', { state: anchorState }));
    expect(navigate.mock.lastCall?.[0]).toMatchObject({ route: { surface: 'docs' }, restoreScroll: 600 });
    setScroll(600);
    window.history.replaceState(baseState, '', '/docs');
    window.dispatchEvent(new PopStateEvent('popstate', { state: baseState }));
    expect(navigate.mock.lastCall?.[0]).toMatchObject({ route: { surface: 'docs' }, restoreScroll: 90 });
  });

  it('leaves browser-owned link gestures and destinations alone', () => {
    const { follow, navigate } = fixture();
    for (const event of [
      follow('/docs', { ctrlKey: true }), follow('/docs', { metaKey: true }),
      follow('/docs', { shiftKey: true }), follow('/docs', { altKey: true }),
      follow('/docs', { button: 1 }), follow('/docs', {}, { target: '_blank' }),
      follow('/docs', {}, { download: '' }), follow('https://github.com/twinkling-reality/exulanica'),
      follow('/configured-app'),
    ]) expect(event.defaultPrevented).toBe(false);
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it('restores page scroll positions when traversing history', () => {
    const { navigate, follow, setScroll } = fixture('/docs');
    const docsState = window.history.state;
    setScroll(320);
    follow('/docs/agents');
    const agentsState = window.history.state;
    setScroll(140);
    // Dispatch the browser's traversal boundary with the state belonging to that entry.
    window.history.replaceState(docsState, '', '/docs');
    window.dispatchEvent(new PopStateEvent('popstate', { state: docsState }));
    expect(navigate.mock.lastCall?.[0]).toMatchObject({ route: { surface: 'docs' }, restoreScroll: 320 });
    setScroll(320);
    window.history.replaceState(agentsState, '', '/docs/agents');
    window.dispatchEvent(new PopStateEvent('popstate', { state: agentsState }));
    expect(navigate.mock.lastCall?.[0]).toMatchObject({ route: { surface: 'docs-agents' }, restoreScroll: 140 });
  });

  it('restores the preview control after the waitlist fallback', () => {
    const { follow, navigate } = fixture('/');
    const source = document.createElement('button'); source.id = 'home-market-town';
    document.body.append(source);
    const homeState = window.history.state;
    follow('/waitlist?world=market-town', {}, { 'data-return-focus': source.id });
    window.history.replaceState(homeState, '', '/');
    window.dispatchEvent(new PopStateEvent('popstate'));
    expect(navigate.mock.lastCall?.[0].restoreFocus).toBe(source);
    expect(resolveRoute(new URL('https://exulanica.com/worlds/market-town')).surface).toBe('not-found');
  });

  it('restores the selected circle after a full-document app handoff', () => {
    const { follow, setScroll } = fixture('/worlds');
    const source = document.createElement('button'); source.id = 'worlds-small-town';
    document.body.append(source);
    setScroll(250);
    expect(follow('https://app.example/?recipe=small_town', {}, { 'data-return-focus': source.id, 'data-return-world': 'small-town' }).defaultPrevented).toBe(false);
    expect(window.location.search).toBe('?world=small-town');
    const saved = window.history.state;
    router?.destroy();
    window.history.replaceState(saved, '', '/worlds');
    const navigate = vi.fn();
    router = createRouter({ onNavigate: navigate, readScroll: () => 250 });
    expect(navigate.mock.lastCall?.[0]).toMatchObject({ restoreFocus: source, restoreScroll: 250 });
    window.dispatchEvent(new PopStateEvent('popstate'));
    expect(navigate.mock.lastCall?.[0]).toMatchObject({ restoreFocus: source, restoreScroll: 250 });
  });

  it('disposes listeners without leaving navigation interception behind', () => {
    const { follow, navigate } = fixture();
    router?.destroy();
    expect(follow('/docs').defaultPrevented).toBe(false);
    expect(navigate).toHaveBeenCalledTimes(1);
  });
});
