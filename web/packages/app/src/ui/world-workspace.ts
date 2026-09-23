import { el } from './dom.js';

/** Presentation only: existing nodes retain their listeners and contract ownership. */
export function buildWorldWorkspace(parts: {
  root: HTMLElement;
  onOpen?: () => void;
  preview?: boolean;
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
  const availability = el('span', { class: 'world-source-label', role: 'status', text: 'Loading…' });
  const nearbyState = el('p', { class: 'world-help', role: 'status', text: 'Loading nearby people…' });
  const heading = el('header', { class: 'world-heading' }, [
    el('div', { class: 'world-heading-meta' }, [
      el('span', { class: 'world-brand', text: 'Exulanica' }),
      parts.fixture,
      availability,
    ]),
    parts.title,
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
  const nearby = addPanel('nearby', 'People nearby', [
    parts.inhabitants, nearbyState,
    el('p', { class: 'world-help', text: 'Aim at a person or object and press E to inspect it.' }),
  ]);
  const previewNotice = el('p', {
    class: 'world-preview-notice',
    text: 'Development preview. Synthetic and recorded content is not saved and does not establish model or deployment evidence.',
    hidden: !parts.preview,
  });
  const details = addPanel('details', 'About this place', [
    previewNotice,
    parts.source,
    parts.reason,
    el('div', { class: 'world-panel-camera', 'aria-label': 'World camera controls' }, [...parts.camera]),
    ...parts.tools,
  ]);
  const authoring = addPanel('authoring', 'Create', [
    el('p', { text: 'Select a source building with E, then preview an edit before applying it.' }), parts.authoring,
  ]);
  const inspection = addPanel('inspection', 'Selected in the world', [parts.selected, parts.inspector]);
  const nav = el('nav', { class: 'world-local-nav', 'aria-label': 'Explore this place' });
  for (const [name, label] of [['nearby', 'Nearby'], ['authoring', 'Create'], ['details', 'About']] as const) {
    const button = el('button', { type: 'button', text: label, 'aria-expanded': 'false', 'aria-controls': `world-panel-${name}` });
    button.addEventListener('click', () => active === name ? close() : open(name));
    buttons.set(name, button);
    nav.append(button);
  }
  const arrival = el('div', {
    class: 'world-arrival',
    role: 'status',
    'aria-live': 'polite',
  }, [heading]);
  let welcomeVisible = true;
  let placeReady = false;
  let arrivalPlayed = false;
  /**
   * The world's name, once, and never over somebody being spoken to.
   *
   * First-use guidance owns the arriving moment. While it has anything on the screen, the shell
   * carries a phase other than `done`, and this title waits rather than animating underneath it.
   */
  const guidancePending = (): boolean => {
    const phase = root.closest('#shell')?.getAttribute('data-first-use') ?? null;
    return phase !== null && phase !== 'done';
  };
  const showArrival = () => {
    if (arrivalPlayed || welcomeVisible || !placeReady || guidancePending()) return;
    arrivalPlayed = true;
    arrival.removeAttribute('data-shown');
    void arrival.offsetWidth;
    arrival.setAttribute('data-shown', '');
  };
  root.append(arrival, nav, nearby, details, authoring, inspection);
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
    setPlace(name: string) {
      parts.title.textContent = name;
      placeReady = true;
      showArrival();
    },
    setWelcomeVisible(visible: boolean) {
      welcomeVisible = visible;
      // Re-checked on every call rather than on a change, because the thing this waits for is the
      // guidance phase, which moves without this flag moving with it.
      if (visible) arrival.removeAttribute('data-shown');
      else showArrival();
    },
    setAvailability(ready: boolean) {
      availability.textContent = ready ? '' : 'Data unavailable';
      availability.hidden = ready;
      if (!ready) nearbyState.textContent = 'Nearby people are unavailable in this view.';
    },
    /** `saidElsewhere`: another section of this panel already says nobody is here. */
    setNearby(count: number, saidElsewhere = false) {
      nearbyState.hidden = count > 0 || saidElsewhere;
      nearbyState.textContent = 'No people are in the nearby display. Move through the world to explore.';
    },
    openPanel(name: 'nearby' | 'authoring' | 'details') { open(name); },
    inspect() { if (active !== 'inspection') open('inspection'); },
    close,
    dispose() { listeners.abort(); },
  };
}
