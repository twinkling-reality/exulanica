/**
 * Exulanica's signed-out title, Purpose, Capabilities, Research, Waitlist, and Developers surfaces.
 *
 * The Atlas itself has one composition root in `@exulanica/app`. The landing page does not build a
 * second Atlas, second Companion, or scripted formation journey. Entering follows the configured
 * Atlas destination, so development, preview, and deployment all cross the same explicit boundary.
 */

import '@exulanica/presentation/tokens.css';
import './style.css';

import { atlasDestinationFromEnvironment } from './atlas-destination.js';
import { waitlistDestinationFromEnvironment } from './waitlist-destination.js';
import { readEnv, watchReducedMotion } from './env.js';
import { buildChrome } from './ui/chrome.js';
import { createRouter, type Surface, type Navigation } from './router.js';
import { buildDocumentation } from './ui/documentation.js';
import { el } from './ui/dom.js';
import { buildCapabilities } from './ui/capabilities.js';
import { buildPurpose } from './ui/purpose.js';
import { buildResearch } from './ui/research.js';
import { buildRoadmap } from './ui/roadmap.js';
import { buildWaitlist } from './ui/waitlist.js';
import { buildDevelopers } from './ui/developers.js';
import { WORLD_SCENES, retiredWorldDestination } from './ui/world-scenes.js';
import { enterPage } from './ui/page-entry.js';
import { buildTitle } from './ui/title.js';
import { createSurfaceTransition } from './ui/surface-transition.js';

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
  const title = buildTitle({ atlasHref: destination?.href ?? null });
  const purpose = buildPurpose();
  const capabilities = buildCapabilities({ atlasHref: destination?.href ?? null });
  const research = buildResearch();
  const roadmap = buildRoadmap();
  const developers = buildDevelopers();
  const waitlist = buildWaitlist({
    endpoint: waitlistDestinationFromEnvironment(landingRootHref),
  });
  const chrome = buildChrome();
  const docs = buildDocumentation('index');
  const worldApiDocs = buildDocumentation('world-api');
  const agentDocs = buildDocumentation('agents');
  const notFound = el('section', {
    class: 'pane pane-information', id: 'not-found', tabindex: '-1', 'aria-labelledby': 'not-found-title',
  }, [el('article', { class: 'reading-space' }, [
    el('h1', { id: 'not-found-title', class: 'page-heading', text: 'Page not found' }),
    el('p', { class: 'reading-copy', text: 'This address does not match a page on Exulanica.' }),
    el('a', { class: 'reading-link', href: '/', text: 'Return to Exulanica' }),
  ])]);

  // Navigation precedes the active page in keyboard and reading order.
  overlay!.append(chrome.root, title, purpose, capabilities, research, roadmap, waitlist, developers, docs, worldApiDocs, agentDocs, notFound);

  const PANES: Readonly<Record<Surface, HTMLElement>> = {
    title,
    purpose,
    capabilities,
    research,
    roadmap,
    waitlist,
    developers,
    docs,
    'docs-world-api': worldApiDocs,
    'docs-agents': agentDocs,
    'not-found': notFound,
  };
  const transition = createSurfaceTransition(PANES, () => env.reducedMotion);
  let surface: Surface = 'title';
  let navigationVersion = 0;
  let firstEntry = true;
  for (const pane of Object.values(PANES)) pane.addEventListener('scroll', () => { if (!pane.inert) chrome.root.dataset.scrolled = String(pane.scrollTop > 24); }, { passive: true });
  createRouter({
    readScroll: () => PANES[surface].scrollTop,
    onNavigate: go,
  });

  /** Show and focus the destination, then restore its own reading position or article anchor. */
  function go({ route, anchor, restoreScroll, restoreFocus }: Navigation): void {
    const next = route.surface;
    surface = next;
    document.documentElement.dataset['surface'] = next;
    document.documentElement.dataset['ground'] = 'light';
    document.documentElement.dataset['theme'] = 'landing-light';
    chrome.setSurface(next);
    transition.show(next);
    const shown = PANES[next];
    const selectedWorld = WORLD_SCENES.find(scene => scene.id === new URLSearchParams(location.search).get('world'));
    const returnLink = waitlist.querySelector<HTMLAnchorElement>('.waitlist-return')!;
    returnLink.href = selectedWorld ? `/worlds?world=${selectedWorld.id}` : '/worlds';
    returnLink.querySelector('.secondary-label')!.textContent = selectedWorld ? `Back to ${selectedWorld.title}` : 'Explore worlds';
    returnLink.classList.toggle('action-back', Boolean(selectedWorld));
    shown.scrollTop = restoreScroll ?? 0;
    chrome.root.dataset.scrolled = String(shown.scrollTop > 24);
    shown.focus({ preventScroll: true });
    if (restoreFocus && shown.contains(restoreFocus)) restoreFocus.focus({ preventScroll: true });
    if (firstEntry) { enterPage(shown, chrome.root, () => env.reducedMotion); firstEntry = false; }
    if ((next === 'capabilities' || next === 'title') && selectedWorld) {
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
   * behavior. Joining the waitlist clicks the same link as pointer input. Single-letter global shortcuts
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
