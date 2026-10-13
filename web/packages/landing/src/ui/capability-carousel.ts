import { PRODUCT_CAPABILITIES } from '../content/product.js';
import { CAPABILITY_PARTICLES, CAPABILITY_SCENES } from '../content/capability-scenes.js';
import { el } from './dom.js';
import { buildCapabilityConcept, capabilityConceptRenderer, capabilityConceptPose, type CapabilityPointer, type CapabilityPose } from './capability-concept.js';
import { CAPABILITY_MOTION, capabilityEase, createCapabilitySequence } from './capability-sequence.js';

/** One active-time clock owns selection, progress, copy and the particle artwork. */
export function buildCapabilityCarousel(host: HTMLElement): HTMLElement {
  const items = PRODUCT_CAPABILITIES;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const concepts = items.map(item => buildCapabilityConcept(item.concept));
  const renderConcepts = concepts.map(capabilityConceptRenderer);
  const frames = concepts.map(svg => el('div', { class: 'concept-frame', hidden: '' }, [svg]));
  const counter = el('span', { class: 'concept-counter', 'aria-hidden': 'true' });
  const fill = el('span', { class: 'concept-progress' });
  const playback = el('button', {
    class: 'concept-timeline', type: 'button', 'aria-describedby': 'capability-playback-help',
  }, [
    el('span', { class: 'concept-track', 'aria-hidden': 'true' }, [fill]),
    el('span', { class: 'concept-playback-glyph', 'aria-hidden': 'true' }),
  ]);
  const stage = el('div', { class: 'capability-stage', 'aria-hidden': 'true' }, frames);
  const title = el('h2', { class: 'capability-active-title' });
  const copy = el('p', { class: 'capability-description' });
  const guide = el('a', { class: 'capability-guide' });
  const detail = el('div', { class: 'capability-detail-content' }, [title, copy, guide]);
  // Invisible, inert copies reserve the tallest catalog entry at the actual available width.
  const measures = items.map(item => el('div', { class: 'capability-detail-measure', 'aria-hidden': 'true', inert: '' }, [
    el('h2', { class: 'capability-active-title', text: item.title }),
    el('p', { class: 'capability-description', text: item.copy }),
    el('span', { class: 'capability-guide', text: `${item.action} ↗` }),
  ]));
  const panel = el('div', { id: 'capability-detail', class: 'capability-detail', role: 'tabpanel', tabindex: '0' }, [detail, ...measures]);
  const buttons = items.map(item => el('button', {
    id: item.id, class: 'capability-selector', role: 'tab', type: 'button',
    'aria-controls': panel.id, 'aria-selected': 'false', tabindex: '-1',
  }, [
    el('span', { text: item.title }),
  ]));
  const tabs = el('div', { class: 'capability-selectors', role: 'tablist', 'aria-label': 'Capabilities', 'aria-orientation': 'horizontal' }, buttons);
  const root = el('article', { class: 'site-page capability-sheet' }, [
    el('h1', { id: 'product-capabilities-title', class: 'capability-label', text: 'Capabilities' }),
    tabs,
    el('div', { class: 'capability-body' }, [
      el('div', { class: 'capability-content' }, [
        panel, el('div', { class: 'concept-controls' }, [counter, playback]),
      ]),
      el('div', { class: 'capability-visual' }, [stage]),
    ]),
    el('span', { id: 'capability-playback-help', class: 'capability-sr-only', text: 'Play or pause the timeline. Selecting a capability starts its sequence. Further interaction holds playback. With reduced motion, select any capability to explore it.' }),
  ]);
  root.style.setProperty('--capability-ease', `cubic-bezier(${CAPABILITY_MOTION.easing.join(',')})`);
  root.style.setProperty('--capability-diagram-ratio', `${CAPABILITY_PARTICLES.width} / ${CAPABILITY_PARTICLES.height}`);
  const sequence = createCapabilitySequence(items.length);
  const events = new AbortController();
  const signal = events.signal;
  let selected = -1;
  let elapsed = 0;
  let raf = 0;
  let running = false;
  let paused = false;
  let playRequested = false;
  let hovered = false;
  let focused = false;
  let pressed = false;
  let background = false;
  let disposed = false;
  let connected = host.isConnected;
  let mounted = connected;
  let fragment = '';
  let pointer: CapabilityPointer = null;
  let origin: CapabilityPose | undefined;
  const reducedMotion = () => reduced.matches || document.documentElement.dataset.reducedMotion === 'true';
  const available = () => host.isConnected && !host.inert && !host.hidden && document.visibilityState !== 'hidden' && !background;

  const paint = (state: { index: number; elapsed: number }): void => {
    const motionOff = reducedMotion();
    if (state.index !== selected) {
      // Keep the outgoing point positions while the next field enters on the same clock.
      origin = selected < 0 || motionOff ? undefined : capabilityConceptPose(concepts[selected]!);
      selected = state.index;
      pointer = null;
      const item = items[selected]!;
      frames.forEach((frame, index) => { frame.hidden = index !== selected; });
      buttons.forEach((button, index) => {
        button.setAttribute('aria-selected', String(index === selected));
        button.tabIndex = index === selected ? 0 : -1;
      });
      panel.setAttribute('aria-labelledby', item.id);
      root.style.setProperty('--capability-accent', CAPABILITY_SCENES[item.concept].color);
      title.textContent = item.title;
      copy.textContent = item.copy;
      guide.href = item.href;
      guide.textContent = `${item.action} ↗`;
      counter.textContent = `${String(selected + 1).padStart(2, '0')} / ${String(items.length).padStart(2, '0')}`;
    }
    elapsed = state.elapsed;
    root.dataset.elapsed = String(elapsed);
    fill.style.transform = `scaleX(${motionOff ? 0 : elapsed / CAPABILITY_MOTION.duration})`;
    // A shallow fade at each edge keeps the stage occupied; copy switches in one layer.
    const edge = Math.min(elapsed, CAPABILITY_MOTION.duration - elapsed);
    const entrance = motionOff ? 1 : capabilityEase(edge / CAPABILITY_MOTION.transition);
    concepts[selected]!.querySelector<SVGElement>('.concept-art')!.style.opacity = String(.65 + .35 * entrance);
    renderConcepts[selected]!(elapsed, motionOff, pointer, origin);
  };
  const updatePlayback = (): void => {
    const motionOff = reducedMotion();
    root.dataset.motion = running ? 'playing' : 'paused';
    root.dataset.playback = running ? 'playing' : 'paused';
    playback.disabled = motionOff;
    playback.dataset.paused = String(paused);
    // Temporary interaction holds must not change the action during a pointer click.
    playback.setAttribute('aria-label', motionOff ? 'Automatic playback disabled for reduced motion' : paused ? 'Play capability sequence' : 'Pause capability sequence');
  };
  const tick = (now: number): void => {
    raf = 0;
    if (disposed) return;
    paint(sequence.advance(now));
    if (running) raf = requestAnimationFrame(tick);
  };
  const sync = (): void => {
    if (disposed) return;
    const next = available() && !reducedMotion() && !paused && !pressed && (playRequested || (!hovered && !focused));
    paint(sequence.setRunning(next, performance.now()));
    running = next;
    updatePlayback();
    if (raf) cancelAnimationFrame(raf);
    raf = running ? requestAnimationFrame(tick) : 0;
  };
  const select = (next: number): void => {
    // Selection explicitly starts playback even while the selected tab retains focus.
    // A subsequent hover, press or focus change can hold the new sequence.
    if (selected >= 0 && !reducedMotion()) origin = capabilityConceptPose(concepts[selected]!);
    paused = false;
    playRequested = true;
    paint(sequence.select(next, performance.now()));
    sync();
  };
  const selectFragment = (): void => {
    if (window.location.hash === fragment) return;
    fragment = window.location.hash;
    const chapter = items.findIndex(item => fragment === `#${item.id}`);
    if (chapter >= 0) select(chapter);
  };
  buttons.forEach((button, index) => {
    button.addEventListener('click', () => select(index), { signal });
    button.addEventListener('keydown', event => {
      const next = event.key === 'ArrowDown' || event.key === 'ArrowRight' ? (selected + 1) % items.length
        : event.key === 'ArrowUp' || event.key === 'ArrowLeft' ? (selected + items.length - 1) % items.length
          : event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : null;
      if (next === null) return;
      event.preventDefault();
      buttons[next]!.focus();
      select(next);
    }, { signal });
  });
  playback.addEventListener('click', () => {
    paused = !paused;
    // An explicit play request can continue while this control retains keyboard focus.
    playRequested = !paused;
    sync();
  }, { signal });
  root.addEventListener('pointerenter', event => { if (event.pointerType === 'mouse') { playRequested = false; hovered = true; sync(); } }, { signal });
  root.addEventListener('pointerleave', () => { pointer = null; hovered = false; sync(); }, { signal });
  stage.addEventListener('pointermove', event => {
    if (event.pointerType === 'touch' || reducedMotion() || !available()) return;
    const bounds = concepts[selected]!.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    pointer = { x: (event.clientX - bounds.left) * CAPABILITY_PARTICLES.width / bounds.width, y: (event.clientY - bounds.top) * CAPABILITY_PARTICLES.height / bounds.height };
    // Pointer updates share the existing frame slot, including while elapsed time is held.
    if (!raf) raf = requestAnimationFrame(tick);
  }, { signal });
  stage.addEventListener('pointerleave', () => { pointer = null; sync(); }, { signal });
  root.addEventListener('pointerdown', event => { if (!playback.contains(event.target as Node)) playRequested = false; pressed = true; sync(); }, { signal });
  const release = () => { if (pressed) { pressed = false; sync(); } };
  document.addEventListener('pointerup', release, { signal });
  document.addEventListener('pointercancel', release, { signal });
  root.addEventListener('focusin', event => { if (event.target !== playback) playRequested = false; focused = true; sync(); }, { signal });
  root.addEventListener('focusout', event => { focused = event.relatedTarget instanceof Node && root.contains(event.relatedTarget); sync(); }, { signal });
  document.addEventListener('visibilitychange', sync, { signal });
  window.addEventListener('blur', () => { background = true; release(); sync(); }, { signal });
  window.addEventListener('focus', () => { background = false; sync(); }, { signal });
  window.addEventListener('pagehide', () => { background = true; sync(); }, { signal });
  window.addEventListener('pageshow', () => { background = false; sync(); }, { signal });
  window.addEventListener('hashchange', selectFragment, { signal });
  host.addEventListener('focus', () => { selectFragment(); sync(); }, { signal });
  reduced.addEventListener('change', sync, { signal });
  const hostObserver = new MutationObserver(sync);
  hostObserver.observe(host, { attributes: true, attributeFilter: ['inert', 'hidden'] });
  const preferenceObserver = new MutationObserver(sync);
  preferenceObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-reduced-motion'] });
  const connectionObserver = new MutationObserver(() => {
    if (host.isConnected === connected) return;
    connected = host.isConnected;
    if (connected) { mounted = true; sync(); }
    else if (mounted) {
      disposed = true;
      cancelAnimationFrame(raf);
      events.abort();
      hostObserver.disconnect();
      preferenceObserver.disconnect();
      connectionObserver.disconnect();
    }
  });
  connectionObserver.observe(document.body, { childList: true, subtree: true });
  paint(sequence.select(0, performance.now()));
  selectFragment();
  queueMicrotask(sync);
  return root;
}
