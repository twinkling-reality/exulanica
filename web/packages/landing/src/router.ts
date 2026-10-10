/** Public URLs are ordinary links, with client navigation for this site's known pages. */
export const ROUTES = [
  { path: '/', surface: 'title', title: 'Exulanica' },
  { path: '/about', surface: 'purpose', title: 'About | Exulanica' },
  { path: '/worlds', surface: 'capabilities', title: 'Worlds | Exulanica' },
  { path: '/developers', surface: 'developers', title: 'Developers | Exulanica' },
  { path: '/research', surface: 'research', title: 'Research | Exulanica' },
  { path: '/roadmap', surface: 'roadmap', title: 'Product direction | Exulanica' },
  { path: '/waitlist', surface: 'waitlist', title: 'Join Waitlist | Exulanica' },
  { path: '/docs', surface: 'docs', title: 'Documentation | Exulanica' },
  { path: '/docs/world-api', surface: 'docs-world-api', title: 'World API | Exulanica' },
  { path: '/docs/agents', surface: 'docs-agents', title: 'Agent integrations | Exulanica' },
] as const;

export type Surface = typeof ROUTES[number]['surface'] | 'not-found';
export interface Route { readonly path: string; readonly surface: Surface; readonly title: string }
const legacy: Readonly<Record<string, string>> = {
  '#title': '/', '#purpose': '/about', '#capabilities': '/worlds',
  '#developers': '/developers', '#research': '/research', '#waitlist': '/waitlist',
};
const cleanPath = (path: string): string => path.replace(/\/+$/, '') || '/';

export function resolveRoute(url: URL): Route {
  const path = legacy[url.hash] ?? cleanPath(url.pathname);
  return ROUTES.find((route) => route.path === path)
    ?? { path, surface: 'not-found', title: 'Page not found | Exulanica' };
}

export interface Navigation {
  readonly route: Route;
  readonly anchor: string;
  readonly restoreScroll: number | null;
  readonly restoreFocus?: HTMLElement;
}

/** Modified clicks, downloads, external destinations and article anchors stay browser-owned. */
export function createRouter(options: {
  onNavigate(navigation: Navigation): void;
  readScroll(): number;
}): { destroy(): void } {
  const focusTargets = new Map<string, HTMLElement>();
  const positions = new Map<string, number>();
  let sequence = 0;
  const key = (): string => `landing-${Date.now()}-${sequence++}`;
  let currentKey = key();
  let currentRoute: Route | null = null;
  let currentHref = window.location.href;
  const previousRestoration = window.history.scrollRestoration;
  window.history.scrollRestoration = 'manual';
  window.history.replaceState({ ...window.history.state, landingKey: currentKey }, '');

  const render = (restoreScroll: number | null): void => {
    const url = new URL(window.location.href);
    const route = resolveRoute(url);
    const legacyPath = legacy[url.hash];
    if (legacyPath) {
      url.pathname = legacyPath;
      url.hash = '';
      window.history.replaceState(window.history.state, '', url);
    }
    currentHref = window.location.href;
    document.title = route.title;
    currentRoute = route;
    const savedFocus = focusTargets.get(currentKey)
      ?? (typeof window.history.state?.landingFocusId === 'string' ? document.getElementById(window.history.state.landingFocusId) : null);
    options.onNavigate({ route, anchor: url.hash, restoreScroll, ...(restoreScroll !== null && savedFocus ? { restoreFocus: savedFocus } : {}) });
  };
  const remember = (): void => { positions.set(currentKey, options.readScroll()); };
  const click = (event: MouseEvent): void => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
    const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a[href]') : null;
    if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
    const url = new URL(link.href, window.location.href);
    const route = resolveRoute(url);
    if (url.origin !== window.location.origin || route.surface === 'not-found' || !['http:', 'https:'].includes(url.protocol)) {
      if (link.dataset.returnFocus) {
        const source = new URL(window.location.href);
        if (link.dataset.returnWorld) source.searchParams.set('world', link.dataset.returnWorld);
        window.history.replaceState({
          ...window.history.state, landingFocusId: link.dataset.returnFocus, landingScroll: options.readScroll(),
        }, '', source);
      }
      return;
    }
    const isLegacy = Boolean(legacy[url.hash]);
    if (!isLegacy && cleanPath(url.pathname) === cleanPath(window.location.pathname) && url.hash) {
      remember();
      return;
    }
    event.preventDefault();
    if (url.href === window.location.href) {
      // A menu closes before this handler runs, so move focus out of its now-hidden link.
      render(options.readScroll());
      return;
    }
    remember();
    const target = link.dataset.returnFocus ? document.getElementById(link.dataset.returnFocus) : link;
    if (target) focusTargets.set(currentKey, target);
    currentKey = key();
    window.history.pushState({ landingKey: currentKey, landingFrom: currentRoute?.path }, '', url);
    render(null);
  };
  const pop = (): void => {
    remember();
    const savedKey: unknown = window.history.state?.landingKey;
    currentKey = typeof savedKey === 'string' ? savedKey : key();
    window.history.replaceState({ ...window.history.state, landingKey: currentKey }, '');
    const url = new URL(window.location.href);
    const route = resolveRoute(url);
    // A new native fragment entry has no router key. Let its default anchor scrolling finish.
    if (typeof savedKey !== 'string' && route.surface === currentRoute?.surface && url.hash && !legacy[url.hash]) {
      currentHref = window.location.href;
      return;
    }
    render(positions.get(currentKey) ?? (typeof window.history.state?.landingFocusId === 'string' ? window.history.state.landingScroll ?? 0 : null));
  };
  const hash = (): void => {
    if (window.location.href === currentHref) return;
    if (legacy[window.location.hash]) { remember(); render(null); return; }
    // Browsers that only emit hashchange still give each native fragment its own scroll record.
    currentKey = key();
    window.history.replaceState({ ...window.history.state, landingKey: currentKey }, '');
    currentHref = window.location.href;
  };
  document.addEventListener('click', click);
  window.addEventListener('popstate', pop);
  window.addEventListener('hashchange', hash);
  render(typeof window.history.state?.landingFocusId === 'string' ? window.history.state.landingScroll ?? 0 : null);
  return {
    destroy() {
      document.removeEventListener('click', click);
      window.removeEventListener('popstate', pop);
      window.removeEventListener('hashchange', hash);
      window.history.scrollRestoration = previousRestoration;
    },
  };
}
