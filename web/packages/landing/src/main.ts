/**
 * Exulanica's public product, journal, and documentation surfaces.
 *
 * The Atlas itself has one composition root in `@exulanica/app`. The landing page does not build a
 * second Atlas, second Companion, or scripted formation journey. Entering follows the configured
 * Atlas destination, so development, preview, and deployment all cross the same explicit boundary.
 */

import '@exulanica/presentation/tokens.css';
import './style.css';
import './reading-system.css';

import { atlasDestinationFromEnvironment } from './atlas-destination.js';
import { updatePageMetadata } from './page-metadata.js';
import { readEnv, watchReducedMotion } from './env.js';
import { buildChrome } from './ui/chrome.js';
import { createRouter, type Surface, type Navigation } from './router.js';
import { DOCUMENTS, documentId } from './ui/docs/catalog.js';
import { buildDocumentation } from './ui/documentation.js';
import { el } from './ui/dom.js';
import { buildProduct, buildProductCapabilities } from './ui/product.js';
import { buildUseCases, buildUseCase } from './ui/use-cases.js';
import { USE_CASES } from './content/use-cases.js';
import { buildJournalArticle } from './ui/journal.js';
import { JOURNAL } from './content/journal.js';
import { WORLD_SCENES, retiredWorldDestination } from './ui/world-scenes.js';
import { enterPage } from './ui/page-entry.js';
import { buildTitle } from './ui/title.js';
import { createSurfaceTransition } from './ui/surface-transition.js';
import { createPublicTheme } from './theme.js';

const overlay = document.getElementById('overlay');
if (!overlay) throw new Error('landing: expected #overlay in the document');

// Deployment-relative destinations keep the same meaning on every public route.
const landingRootHref = new URL('/', window.location.href).href;
const destination = atlasDestinationFromEnvironment(landingRootHref);
const retiredDestination = retiredWorldDestination(window.location.pathname, destination?.href ?? null);
if (retiredDestination && destination) window.location.replace(retiredDestination);
else {
  if (retiredDestination) window.history.replaceState(null, '', retiredDestination);
  mountLanding();
}

function mountLanding(): void {
  const env = readEnv();
  const theme = createPublicTheme();
  const title = buildTitle({ atlasHref: destination?.href ?? null });
  const chrome = buildChrome({ atlasHref: destination?.href ?? null, onToggleTheme: () => theme.toggle() });
  theme.subscribe(value => chrome.setTheme(value));
  const product = buildProduct();
  const productCapabilities = buildProductCapabilities();
  const useCases = buildUseCases();
  const useCasePages = Object.fromEntries(USE_CASES.map(item => [`use-case-${item.key}`, buildUseCase(item)]));
  const articles = Object.fromEntries(JOURNAL.map(post => [`journal-${post.slug}`, buildJournalArticle(post)]));
  const documentation = Object.fromEntries(DOCUMENTS.map(entry => [documentId(entry.key), buildDocumentation(entry.key)]));
  const notFound = el('section', {
    class: 'pane pane-information', id: 'not-found', tabindex: '-1', 'aria-labelledby': 'not-found-title',
  }, [el('article', { class: 'reading-space' }, [
    el('h1', { id: 'not-found-title', class: 'page-heading', text: 'Page not found' }),
    el('p', { class: 'reading-copy', text: 'This address does not match a page on Exulanica.' }),
    el('a', { class: 'reading-link', href: '/', text: 'Return to Exulanica' }),
  ])]);

  const PANES = {
    title, product, 'product-capabilities': productCapabilities, 'use-cases': useCases, ...useCasePages, ...articles, ...documentation,
    'not-found': notFound,
  } as Readonly<Record<Surface, HTMLElement>>;
  const paneFor = (key: Surface): HTMLElement => {
    const pane = PANES[key];
    if (!pane) throw new Error(`landing: missing page for ${key}`);
    return pane;
  };
  // Navigation precedes the active page in keyboard and reading order.
  overlay!.append(chrome.root, ...Object.values(PANES));
  const transition = createSurfaceTransition(PANES, () => env.reducedMotion);
  let surface: Surface = 'title';
  let navigationVersion = 0;
  let firstEntry = true;
  // The fixed header shares the active page's available width, including native scrollbars.
  const alignHeader = (): void => {
    const pane = paneFor(surface);
    chrome.root.style.setProperty('--page-scrollbar', `${pane.offsetWidth - pane.clientWidth}px`);
  };
  const pageSizes = new ResizeObserver(alignHeader);
  Object.values(PANES).forEach(pane => pageSizes.observe(pane));
  for (const pane of Object.values(PANES)) pane.addEventListener('scroll', () => { if (!pane.inert) chrome.root.dataset.scrolled = String(pane.scrollTop > 24); }, { passive: true });
  createRouter({
    readScroll: () => paneFor(surface).scrollTop,
    onNavigate: go,
  });

  /** Show and focus the destination, then restore its own reading position or article anchor. */
  function go({ route, anchor, restoreScroll, restoreFocus }: Navigation): void {
    updatePageMetadata(route);
    const next = route.surface;
    surface = next;
    document.documentElement.dataset['surface'] = next;
    chrome.setSurface(next);
    transition.show(next);
    const shown = paneFor(next);
    alignHeader();
    const selectedWorld = WORLD_SCENES.find(scene => scene.id === new URLSearchParams(location.search).get('world'));
    shown.scrollTop = restoreScroll ?? 0;
    chrome.root.dataset.scrolled = String(shown.scrollTop > 24);
    shown.focus({ preventScroll: true });
    if (restoreFocus && shown.contains(restoreFocus)) restoreFocus.focus({ preventScroll: true });
    if (firstEntry) { enterPage(shown, chrome.root, () => env.reducedMotion); firstEntry = false; }
    if ((next === 'product' || next === 'title') && selectedWorld) {
      shown.querySelector<HTMLButtonElement>(`#${next === 'title' ? 'home' : 'worlds'}-${selectedWorld.id}`)?.focus({ preventScroll: true });
    }
    const version = ++navigationVersion;
    if (anchor && restoreScroll === null) requestAnimationFrame(() => {
      if (version !== navigationVersion) return;
      let id: string;
      try { id = decodeURIComponent(anchor.slice(1)); } catch { return; }
      const target = document.getElementById(id);
      if (target && shown.contains(target)) target.scrollIntoView({ block: 'start' });
    });
  }

  /**
   * The one title-screen shortcut.
   *
   * Modified presses are left to the browser, and a focused control keeps its native keyboard
   * behavior. The primary action clicks the same link as pointer input. Single-letter global shortcuts
   * are deliberately absent so character-key input is never captured unexpectedly.
   */
  window.addEventListener('keydown', (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const active = document.activeElement;
    if (active instanceof HTMLElement && active.closest('button, a, input, textarea, select')) return;

    const follow = (id: string): void => document.getElementById(id)?.click();
    switch (event.key.toLowerCase()) {
      case 'enter':
        if (surface !== 'title') return;
        event.preventDefault();
        follow('hero-entry');
        return;
      default:
    }
  });

  window.addEventListener('resize', () => transition.refresh());

  watchReducedMotion((reduced) => {
    env.reducedMotion = reduced;
    if (reduced) { transition.finish(); document.getAnimations().forEach(animation => animation.cancel()); }
    document.documentElement.dataset['reducedMotion'] = reduced ? 'true' : 'false';
  });
  document.documentElement.dataset['reducedMotion'] = env.reducedMotion ? 'true' : 'false';

}
