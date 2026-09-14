import { el } from './dom.js';

/** Presentation only: existing nodes retain their listeners and contract ownership. */
export function buildWorldWorkspace(parts: {
  root: HTMLElement;
  onOpen?: () => void;
  title: HTMLElement;
  fixture: HTMLElement;
  source: HTMLElement;
  selected: HTMLElement;
  reason: HTMLElement;
  inspector: HTMLElement;
  inhabitants: HTMLElement;
  camera: readonly HTMLElement[];
  tools: readonly HTMLElement[];
  authoring: HTMLElement;
}) {
  const { root } = parts;
  root.classList.add('world-workspace');
  root.setAttribute('aria-label', 'World exploration');
  parts.title.textContent = 'Your world';
  const availability = el('span', { class: 'world-source-label', role: 'status', text: 'Loading world details…' });
  const nearbyState = el('p', { class: 'world-help', role: 'status', text: 'Loading nearby people…' });
  const heading = el('header', { class: 'world-heading' }, [
    el('span', { class: 'world-brand', text: 'Exulanica' }), parts.title,
    el('span', { class: 'world-source-label', text: 'NYC source forms · provisional surfaces' }),
    parts.fixture, availability,
  ]);
  const panels = new Map<string, HTMLElement>();
  const buttons = new Map<string, HTMLButtonElement>();
  let active: string | null = null;
  const close = (restore = true) => {
    const previous = active;
    active = null;
    for (const panel of panels.values()) panel.hidden = true;
    for (const button of buttons.values()) button.setAttribute('aria-expanded', 'false');
    root.removeAttribute('data-panel');
    if (restore && previous) (buttons.get(previous) ?? buttons.get('nearby'))?.focus();
  };
  const open = (name: string, focus = true) => {
    if (document.pointerLockElement != null) document.exitPointerLock();
    parts.onOpen?.();
    close(false);
    active = name;
    root.dataset['panel'] = name;
    const panel = panels.get(name)!;
    panel.hidden = false;
    buttons.get(name)?.setAttribute('aria-expanded', 'true');
    if (focus) panel.querySelector<HTMLElement>('button')?.focus();
  };
  const addPanel = (name: string, label: string, children: Node[]) => {
    const back = el('button', { type: 'button', class: 'world-panel-close', text: 'Close', 'aria-label': `Close ${label.toLowerCase()}` });
    back.addEventListener('click', () => close());
    const panel = el('section', { class: 'world-panel', id: `world-panel-${name}`, hidden: true, 'aria-label': label }, [
      el('header', { class: 'world-panel-heading' }, [el('h2', { text: label }), back]), ...children,
    ]);
    panels.set(name, panel);
    return panel;
  };
  const nearby = addPanel('nearby', 'Nearby', [
    el('p', { text: 'Meet the fictional people and explore the places around you.' }),
    parts.inhabitants, nearbyState,
    el('p', { class: 'world-help', text: 'You can also aim at a person or object and press E to inspect it.' }),
  ]);
  const details = addPanel('details', 'World details', [parts.source, parts.reason, ...parts.tools]);
  const authoring = addPanel('authoring', 'Create in this world', [
    el('p', { text: 'Select a source building with E, then preview an edit before applying it.' }), parts.authoring,
  ]);
  const inspection = addPanel('inspection', 'Selected in the world', [parts.selected, parts.inspector]);
  const nav = el('nav', { class: 'world-local-nav', 'aria-label': 'Explore this place' });
  for (const [name, label] of [['nearby', 'Nearby'], ['authoring', 'Create'], ['details', 'World details']] as const) {
    const button = el('button', { type: 'button', text: label, 'aria-expanded': 'false', 'aria-controls': `world-panel-${name}` });
    button.addEventListener('click', () => active === name ? close() : open(name));
    buttons.set(name, button);
    nav.append(button);
  }
  const view = el('nav', { class: 'world-viewbar', 'aria-label': 'World camera' }, [...parts.camera]);
  root.append(el('div', { class: 'world-place' }, [heading, nav]), nearby, details, authoring, inspection, view);
  const listeners = new AbortController();
  window.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || document.pointerLockElement != null || active === null) return;
    // A native select owns its own Escape; the next Escape can close this panel.
    if (event.target instanceof HTMLSelectElement) return;
    event.preventDefault(); event.stopImmediatePropagation(); close();
  }, { capture: true, signal: listeners.signal });
  document.addEventListener('pointerlockchange', () => {
    if (document.pointerLockElement != null) close(false);
  }, { signal: listeners.signal });
  return {
    nearby, details, authoring,
    setPlace(name: string) { parts.title.textContent = name; },
    setAvailability(ready: boolean) {
      availability.textContent = ready ? '' : 'World details unavailable. Open World details for the reason.';
      availability.hidden = ready;
      if (!ready) nearbyState.textContent = 'Nearby people are unavailable in this view.';
    },
    setNearby(count: number) {
      nearbyState.hidden = count > 0;
      nearbyState.textContent = 'No people are in the nearby display. Move through the world to explore.';
    },
    inspect() { if (active !== 'inspection') open('inspection'); },
    close,
    dispose() { listeners.abort(); },
  };
}
