import { DOCUMENTATION_ROUTES } from './ui/docs/catalog.js';
import { ENDPOINTS } from './ui/docs/worldApi.js';
import { USE_CASES } from './content/use-cases.js';
import { JOURNAL } from './content/journal.js';
/** Public URLs are ordinary links, with client navigation for known pages. */
export const ROUTES = [
  { path: '/', surface: 'title', title: 'Exulanica' },
  { path: '/product', surface: 'product', title: 'Overview | Exulanica' },
  { path: '/product/capabilities', surface: 'product-capabilities', title: 'Capabilities | Exulanica' },
  { path: '/use-cases', surface: 'use-cases', title: 'Use Cases | Exulanica' },
  ...USE_CASES.map(item => ({ path: `/use-cases/${item.key}`, surface: `use-case-${item.key}` as const, title: `${item.title} | Exulanica` })),
  ...JOURNAL.map(post => ({ path: `/blog/${post.slug}`, surface: `journal-${post.slug}` as const, title: `${post.title} | Exulanica` })),
  ...DOCUMENTATION_ROUTES,
] as const;
export type Surface = typeof ROUTES[number]['surface'] | 'not-found';
export interface Route { readonly path: string; readonly surface: Surface; readonly title: string }
const legacy: Readonly<Record<string, string>> = {
  '#title': '/', '#purpose': '/product#purpose', '#capabilities': '/product/capabilities#configurations',
  '#developers': '/docs', '#research': '/product#purpose', '#waitlist': '/docs/self-hosting',
};
export const REDIRECTS: Readonly<Record<string, string>> = {
  '/docs/sources': '/docs/assets',
  '/about': '/product#purpose',
  '/product/how-it-works': '/product/capabilities',
  ...Object.fromEntries(JOURNAL.map(post => [`/journal/${post.slug}`, `/blog/${post.slug}`])),
  '/blog/a-different-day': '/product#purpose',
  '/journal/a-different-day': '/product#purpose',
  '/blog/the-world-decides': '/product#purpose',
  '/journal/the-world-decides': '/product#purpose',
  '/blog/a-world-worth-returning-to': '/product#purpose',
  '/journal/a-world-worth-returning-to': '/product#purpose',
  '/blog/need-relief-and-the-hour': '/product#purpose',
  '/journal/need-relief-and-the-hour': '/product#purpose',
  '/blog/turns-the-world-did-not-apply': '/product#purpose',
  '/journal/turns-the-world-did-not-apply': '/product#purpose',
  '/blog/the-town-comparison-that-finished': '/product#purpose',
  '/journal/the-town-comparison-that-finished': '/product#purpose',
  '/blog/reading-the-run-again': '/product#purpose',
  '/journal/reading-the-run-again': '/product#purpose',
  '/blog/why-a-world': '/product#purpose',
  '/journal/why-a-world': '/product#purpose',
  '/blog/what-exulanica-does': '/product#purpose',
  '/journal/what-exulanica-does': '/product#purpose',
  '/worlds': '/product/capabilities#configurations', '/developers': '/docs',
  '/blog': '/product#purpose', '/site-information': '/product#purpose',
  '/research': '/product#purpose', '/journal': '/product#purpose', '/roadmap': '/product#purpose', '/waitlist': '/docs/self-hosting',
};
const cleanPath = (path: string): string => path.replace(/\/+$/, '') || '/';
function canonicalURL(url: URL): URL {
  const result = new URL(url.href);
  const useCase = cleanPath(url.pathname) === '/use-cases' ? USE_CASES.find(item => url.hash === `#${item.legacyKey}`) : undefined;
  if (useCase) { result.pathname = `/use-cases/${useCase.key}`; result.hash = ''; return result; }
  if (cleanPath(url.pathname) === '/use-cases' && url.hash === '#future-applications') { result.hash = ''; return result; }
  const aboutAnchor = cleanPath(url.pathname) === '/about'
    ? ({ '#why-open-models': '/product/capabilities#models', '#understanding-the-results': '/product/capabilities#compare', '#source-code': '/product/capabilities#product-source' } as Record<string, string>)[url.hash]
    : undefined;
  const productAnchor = cleanPath(url.pathname) === '/product'
    ? ({ '#examples': '/product/capabilities#configurations', '#how-it-works': '/product/capabilities#configurations', '#configurations': '/product/capabilities#configurations', '#models': '/product/capabilities#models', '#compare': '/product/capabilities#compare', '#product-source': '/product/capabilities#product-source', '#access': '/docs' } as Record<string, string>)[url.hash]
    : undefined;
  const movedChapter = cleanPath(url.pathname) === '/docs/worlds'
    ? ({ '#docs-worlds-models': '/docs/models#docs-models-models', '#docs-worlds-compare': '/docs/comparisons#docs-comparisons-compare' } as Record<string, string>)[url.hash]
    : cleanPath(url.pathname) === '/docs/world-api' && url.hash === '#docs-world-api-responses' ? '/docs/errors#docs-errors-responses' : undefined;
  if (movedChapter) { const target = new URL(movedChapter, url); result.pathname = target.pathname; result.hash = target.hash; return result; }
  const oldOperation = cleanPath(url.pathname) === '/docs/world-api' ? ENDPOINTS.find(item => url.hash === `#docs-world-api-${item.key}`) : undefined;
  if (oldOperation) { result.pathname = `/docs/world-api/${oldOperation.key}`; result.hash = ''; return result; }
  const destination = aboutAnchor ?? productAnchor ?? legacy[url.hash] ?? REDIRECTS[cleanPath(url.pathname)];
  if (destination) {
    const target = new URL(destination, url);
    result.pathname = target.pathname;
    result.hash = target.hash || (legacy[url.hash] ? '' : url.hash);
  } else result.pathname = cleanPath(url.pathname);
  return result;
}
export function resolveRoute(url: URL): Route {
  const path = canonicalURL(url).pathname;
  return ROUTES.find(route => route.path === path)
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
    const url = canonicalURL(new URL(window.location.href));
    const route = resolveRoute(url);
    if (url.href !== window.location.href) window.history.replaceState(window.history.state, '', url);
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
    const isLegacy = Boolean(legacy[url.hash]) || route.path !== cleanPath(url.pathname);
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
