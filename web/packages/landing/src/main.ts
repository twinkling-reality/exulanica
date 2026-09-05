/**
 * Exulanica's signed-out title, Purpose, and Capabilities surfaces.
 *
 * The Atlas itself has one composition root in `@exulanica/app`. The landing page does not build a
 * second Atlas, second Companion, or scripted formation journey. Entering follows the configured
 * Atlas destination, so development, preview, and deployment all cross the same explicit boundary.
 */

import '@exulanica/presentation/tokens.css';
import './style.css';

import { atlasDestinationFromEnvironment } from './atlas-destination.js';
import { readEnv, watchReducedMotion } from './env.js';
import { buildChrome, type Surface } from './ui/chrome.js';
import { buildCapabilities } from './ui/capabilities.js';
import { buildPurpose } from './ui/purpose.js';
import { buildTitle } from './ui/title.js';
import { createSurfaceTransition } from './ui/surface-transition.js';
import { boundaryReason, buildViewportBoundary, readViewport } from './ui/viewport-boundary.js';

const overlay = document.getElementById('overlay');
if (!overlay) throw new Error('landing: expected #overlay in the document');

const env = readEnv();
const destination = atlasDestinationFromEnvironment(window.location.href);
const title = buildTitle();
const purpose = buildPurpose();
const capabilities = buildCapabilities();
const chrome = buildChrome({
  atlasHref: destination?.href ?? null,
  onHome: () => go('title'),
  onPurpose: () => go('purpose'),
  onCapabilities: () => go('capabilities'),
});

// Keep the same decorative world mounted while the text planes travel through it.
const landscape = document.createElement('div');
landscape.className = 'landing-landscape';
landscape.setAttribute('aria-hidden', 'true');
const artwork = title.querySelector('.title-artwork');
if (artwork) landscape.append(artwork);
// Decoration has no focus stops; the title still precedes navigation.
overlay.append(landscape, title, chrome.root, purpose, capabilities);

const PANES: Readonly<Record<Surface, HTMLElement>> = { title, purpose, capabilities };
const transition = createSurfaceTransition(PANES, () => env.reducedMotion, landscape);
let surface: Surface = 'title';
const surfaceFromHash = (): Surface => {
  if (window.location.hash === '#purpose') return 'purpose';
  if (window.location.hash === '#capabilities') return 'capabilities';
  return 'title';
};
go(surfaceFromHash());
window.addEventListener('hashchange', () => {
  const next = surfaceFromHash();
  if (next !== surface) go(next);
});

/** Show a signed-out surface without constructing or pretending to enter an Atlas. */
function go(next: Surface): void {
  surface = next;
  document.documentElement.dataset['surface'] = next;
  document.documentElement.dataset['ground'] = 'light';
  document.documentElement.dataset['theme'] = 'landing-light';
  chrome.setSurface(next);

  transition.show(next);
  const shown = PANES[next];
  if (next === 'title') {
    shown.focus({ preventScroll: true });
  } else if (!chrome.root.contains(document.activeElement)) {
    // Pointer/keyboard activation leaves focus on its destination naturally. This branch covers
    // programmatic entry without dropping focus into the article ahead of visible navigation.
    document.getElementById('path-home')?.focus({ preventScroll: true });
  }
}

/**
 * The one title-screen shortcut.
 *
 * Modified presses are left to the browser, and a focused control keeps its native keyboard
 * behavior. Entering Atlas clicks the same link as pointer input. Single-letter global shortcuts
 * are deliberately absent so character-key input is never captured unexpectedly.
 */
window.addEventListener('keydown', (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (document.documentElement.dataset['blocked'] === 'true') return;
  const active = document.activeElement;
  if (active instanceof HTMLElement && active.closest('button, a, input, textarea, select')) return;

  const follow = (id: string): void => document.getElementById(id)?.click();
  switch (event.key.toLowerCase()) {
    case 'enter':
      if (surface !== 'title' || destination === null) return;
      event.preventDefault();
      follow('path-enter');
      return;
    default:
  }
});

const boundary = buildViewportBoundary();
document.body.append(boundary.root);

let lastReason: string | null | undefined;
function checkViewport(): void {
  const reason = boundaryReason(readViewport());
  if (reason === lastReason) return;
  lastReason = reason;
  boundary.apply(reason);
}
checkViewport();

window.addEventListener('resize', () => {
  checkViewport();
  transition.refresh();
});
window.matchMedia('(pointer: coarse)').addEventListener('change', checkViewport);

watchReducedMotion((reduced) => {
  env.reducedMotion = reduced;
  if (reduced) transition.finish();
  document.documentElement.dataset['reducedMotion'] = reduced ? 'true' : 'false';
});
document.documentElement.dataset['reducedMotion'] = env.reducedMotion ? 'true' : 'false';
