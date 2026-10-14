import { isScenePreview, scenePreviewAddress } from './front-door-routes.mjs';
import type { SavedWorldEntry } from '/src/world-entry-api.ts';

// The front door's live background: the app drawing the chosen saved world in an inert frame, its
// camera turning gently. The camera moves; the world's own time does not.

const READY = 'exulanica.front-door.scene-ready';
const previewPage = isScenePreview(new URL(location.href));
const live = new URLSearchParams(location.search).get('livePreview') === '1';

/** Whether this page is a scene preview. The workspace's world view never mounts in one. */
export function scenePreviewPage(): boolean {
  return previewPage;
}

// A preview has no write path, including during the app's own start-up, and shows the world alone.
if (previewPage) {
  document.body.classList.add('ux-capture-world');
  const original = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (method !== 'GET') {
      console.warn('Read-only world preview refused a ' + method + ' request.');
      return Promise.resolve(new Response(JSON.stringify({ detail: 'The world preview is read-only.' }), { status: 405, headers: { 'Content-Type': 'application/json' } }));
    }
    return original(input, init);
  };
}

/** Camera motion in the preview's own renderer, held to the saved world it was asked for. */
export function mountScenePreview({ state, renderer }): void {
  if (!live || window.parent === window) return;
  const entry = state.activeWorldEntry, binding = renderer.atlas?.binding;
  if (!entry || !binding) return;
  const pose = { ...binding.controls.state };
  const pins = { entryId: entry.entryId, versionId: entry.authoredVersionId, styleVersionId: entry.styleVersionId, stateSha: entry.authoredStateSha256 };
  let frame = 0;
  const origin = performance.now();
  const tick = (now: number) => {
    if (!document.hidden) {
      const elapsed = (now - origin) / 1000;
      binding.controls.setView({ ...pose, yaw: pose.yaw + Math.sin(elapsed / 13) * .035, pitch: pose.pitch + Math.sin(elapsed / 19) * .006 }, 'altitude');
      binding.invalidate();
    }
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  requestAnimationFrame(() => requestAnimationFrame(() => window.parent.postMessage({ type: READY, ...pins }, location.origin)));
  window.addEventListener('pagehide', () => cancelAnimationFrame(frame), { once: true });
}

/** The background: the chosen world's picture while its live preview loads, then the live preview. */
export function createScenePreview(root: HTMLElement) {
  const field = document.createElement('div'); field.className = 'ux-entry-image'; field.setAttribute('aria-hidden', 'true'); root.prepend(field);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let enabled = !previewPage && !reduced.matches, selected: SavedWorldEntry | null = null;
  let still: HTMLElement | null = null, current: HTMLIFrameElement | null = null, waiting: HTMLIFrameElement | null = null;
  let disposed = false, sequence = 0;
  const retire = (node: HTMLElement | null) => {
    if (!node) return;
    node.style.opacity = '0'; setTimeout(() => node.remove(), 650);
  };
  const stopLive = () => { current?.remove(); waiting?.remove(); current = null; waiting = null; root.dataset.nativePreview = 'paused'; };
  const startLive = () => {
    if (!selected || !enabled || disposed) return;
    waiting?.remove();
    const iframe = document.createElement('iframe'); iframe.className = 'ux-entry-live'; iframe.title = selected.title; iframe.tabIndex = -1; iframe.inert = true;
    iframe.src = scenePreviewAddress(selected.entryId, location.origin); iframe.style.opacity = '0';
    waiting = iframe; field.append(iframe); root.dataset.nativePreview = 'loading';
  };
  const receive = (event: MessageEvent) => {
    if (event.origin !== location.origin || !selected || event.data?.type !== READY) return;
    if (event.source !== waiting?.contentWindow) return;
    const data = event.data;
    if (data.entryId !== selected.entryId || data.versionId !== selected.authoredVersionId || data.styleVersionId !== selected.styleVersionId || data.stateSha !== selected.authoredStateSha256) return;
    const old = current; current = waiting; waiting = null; current!.style.opacity = '1'; retire(old); root.dataset.nativePreview = 'ready';
  };
  window.addEventListener('message', receive);
  const preference = () => { if (reduced.matches) { enabled = false; stopLive(); } };
  reduced.addEventListener('change', preference);
  return {
    get enabled() { return enabled; },
    select(entry: SavedWorldEntry, picture: string | null) {
      selected = entry; const serial = ++sequence;
      const next = document.createElement('div'); next.className = 'ux-entry-still'; next.style.backgroundImage = picture ? `url("${picture}")` : 'none'; next.style.opacity = '0'; field.append(next);
      const prior = still; still = next;
      requestAnimationFrame(() => { if (serial !== sequence || disposed) { next.remove(); return; } next.style.opacity = '1'; retire(prior); });
      if (current) retire(current); current = null;
      startLive();
    },
    toggle() { enabled = !enabled; if (enabled) startLive(); else stopLive(); return enabled; },
    dispose() { disposed = true; ++sequence; stopLive(); window.removeEventListener('message', receive); reduced.removeEventListener('change', preference); field.remove(); },
  };
}
