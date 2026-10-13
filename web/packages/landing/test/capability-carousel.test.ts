// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { buildProductCapabilities } from '../src/ui/product.js';
import { CAPABILITY_MOTION, createCapabilitySequence } from '../src/ui/capability-sequence.js';
import { buildCapabilityConcept, capabilityConceptRenderer, capabilityConceptPose } from '../src/ui/capability-concept.js';
import { PRODUCT_CAPABILITIES } from '../src/content/product.js';
import { CAPABILITY_PARTICLES } from '../src/content/capability-scenes.js';

beforeEach(() => vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance', 'setTimeout', 'clearTimeout'] }));
afterEach(async () => {
  document.body.replaceChildren();
  await Promise.resolve();
  window.history.replaceState(null, '', '/');
  delete document.documentElement.dataset.reducedMotion;
  Reflect.deleteProperty(document, 'visibilityState');
  vi.restoreAllMocks();
  vi.clearAllTimers();
  vi.useRealTimers();
});
const mount = async () => {
  const pane = buildProductCapabilities();
  document.body.append(pane);
  await Promise.resolve();
  return pane;
};
const selected = (pane: HTMLElement) => pane.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')!;
const playback = (pane: HTMLElement) => pane.querySelector<HTMLButtonElement>('.concept-timeline')!;
const elapsed = (pane: HTMLElement) => Number(pane.querySelector<HTMLElement>('.capability-sheet')!.dataset.elapsed);
const advance = (time: number) => vi.advanceTimersByTime(time);
const pointer = (pane: HTMLElement, type: string, pointerType = 'mouse') => pane.querySelector('.capability-sheet')!.dispatchEvent(new PointerEvent(type, { pointerType }));

it('keeps manual selection, diagram, guide and numbering together and resets the sequence', async () => {
  const pane = await mount();
  advance(2400);
  pane.querySelector<HTMLButtonElement>('#compare')!.click();
  expect(elapsed(pane)).toBe(0);
  expect(selected(pane).textContent).toContain('Experiments');
  expect(pane.querySelector('.capability-detail-content h2')?.textContent).toBe('Experiments');
  expect(pane.querySelector('.concept-counter')?.textContent).toBe('04 / 05');
  expect(pane.querySelector('.capability-detail-content p')?.textContent).toContain('same saved world');
  expect(pane.querySelector('a.capability-guide')?.getAttribute('href')).toBe('/docs/comparisons');
  expect(pane.querySelector('.concept-frame:not([hidden]) [data-concept]')?.getAttribute('data-concept')).toBe('comparison');
  advance(CAPABILITY_MOTION.duration - 16);
  expect(selected(pane).id).toBe('compare');
  advance(16);
  expect(selected(pane).id).toBe('product-source');
  expect(pane.querySelector('.capability-detail-content h2')?.textContent).toBe('Integrations');
});

it('supports arrows, Home and End with one tab stop and matching panel label', async () => {
  const pane = await mount();
  for (const [key, id] of [['End', 'product-source'], ['ArrowRight', 'configurations'], ['ArrowUp', 'product-source'], ['Home', 'configurations'], ['ArrowDown', 'agents']] as const) {
    selected(pane).dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
    expect(selected(pane).id).toBe(id);
    expect(document.activeElement).toBe(selected(pane));
    expect(pane.querySelector('[role="tabpanel"]')?.getAttribute('aria-labelledby')).toBe(id);
    expect(pane.querySelectorAll('[role="tab"][tabindex="0"]')).toHaveLength(1);
    expect(pane.querySelectorAll('.concept-frame:not([hidden])')).toHaveLength(1);
  }
  advance(CAPABILITY_MOTION.duration * 2);
  expect(selected(pane).id).toBe('compare');
});

it('plays a manually selected sequence after real pointer and focus interaction', async () => {
  const pane = await mount();
  const button = pane.querySelector<HTMLButtonElement>('#models')!;
  pointer(pane, 'pointerenter');
  pointer(pane, 'pointerdown');
  button.focus();
  document.dispatchEvent(new PointerEvent('pointerup', { pointerType: 'mouse' }));
  button.click();
  const initial = pane.querySelector('.concept-frame:not([hidden])')!.innerHTML;
  advance(3200);
  expect(elapsed(pane)).toBe(3200);
  expect(pane.querySelector('.concept-frame:not([hidden])')!.innerHTML).not.toBe(initial);
  expect(document.activeElement).toBe(button);
  pane.querySelector<HTMLAnchorElement>('a.capability-guide')!.focus();
  advance(3200);
  expect(elapsed(pane)).toBe(3200);
  playback(pane).click();
  button.click();
  expect(elapsed(pane)).toBe(0);
  advance(1600);
  expect(elapsed(pane)).toBe(1600);
});

it('holds timeline and diagram time on pause and resumes the remaining duration', async () => {
  const pane = await mount();
  advance(2400);
  playback(pane).click();
  const position = elapsed(pane);
  const progress = pane.querySelector<HTMLElement>('.concept-progress')!.style.transform;
  const diagram = pane.querySelector('.concept-frame:not([hidden])')!.innerHTML;
  expect(pane.querySelector<HTMLElement>('.capability-sheet')!.dataset.playback).toBe('paused');
  expect(playback(pane).getAttribute('aria-label')).toBe('Play capability sequence');
  advance(CAPABILITY_MOTION.duration * 2);
  expect(elapsed(pane)).toBe(position);
  expect(pane.querySelector<HTMLElement>('.concept-progress')!.style.transform).toBe(progress);
  expect(pane.querySelector('.concept-frame:not([hidden])')!.innerHTML).toBe(diagram);
  playback(pane).click();
  advance(CAPABILITY_MOTION.duration - position - 16);
  expect(selected(pane).id).toBe('configurations');
  advance(16);
  expect(selected(pane).id).toBe('agents');
});

it('stores elapsed time through hover, focus and touch interaction', async () => {
  const pane = await mount();
  advance(1600);
  pointer(pane, 'pointerenter');
  advance(8000);
  expect(elapsed(pane)).toBe(1600);
  pointer(pane, 'pointerleave');
  pane.querySelector<HTMLAnchorElement>('a.capability-guide')!.focus();
  advance(8000);
  expect(elapsed(pane)).toBe(1600);
  pane.focus();
  pointer(pane, 'pointerdown', 'touch');
  advance(8000);
  expect(elapsed(pane)).toBe(1600);
  document.dispatchEvent(new PointerEvent('pointerup', { pointerType: 'touch' }));
  advance(1600);
  expect(elapsed(pane)).toBe(3200);
});

it('suspends through routed inactivity, hidden documents and window inactivity', async () => {
  const pane = await mount();
  advance(1600);
  for (const attribute of ['inert', 'hidden']) {
    pane.setAttribute(attribute, '');
    await Promise.resolve();
    advance(8000);
    expect(elapsed(pane)).toBe(1600);
    pane.removeAttribute(attribute);
    await Promise.resolve();
  }
  let visibility = 'hidden';
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });
  document.dispatchEvent(new Event('visibilitychange'));
  advance(8000);
  expect(elapsed(pane)).toBe(1600);
  visibility = 'visible';
  document.dispatchEvent(new Event('visibilitychange'));
  window.dispatchEvent(new Event('blur'));
  advance(8000);
  expect(elapsed(pane)).toBe(1600);
  window.dispatchEvent(new Event('focus'));
  advance(1600);
  expect(elapsed(pane)).toBe(3200);
});

it('finishes the final stagger before rollover and retains one readable description', async () => {
  const pane = await mount();
  const completion = (CAPABILITY_PARTICLES.bands - 1) * CAPABILITY_MOTION.stagger + CAPABILITY_MOTION.assembly;
  expect(completion).toBeLessThan(CAPABILITY_MOTION.duration - CAPABILITY_MOTION.transition);
  expect(CAPABILITY_MOTION.phases.complete).toBeLessThan(CAPABILITY_MOTION.duration - CAPABILITY_MOTION.transition);
  advance(Math.ceil(CAPABILITY_MOTION.phases.complete / 16) * 16);
  const art = pane.querySelector('.concept-frame:not([hidden]) .concept-art')!;
  const settled = art.innerHTML;
  advance(CAPABILITY_MOTION.duration - elapsed(pane) - 16);
  expect(art.innerHTML).toBe(settled);
  advance(16);
  expect(selected(pane).id).toBe('agents');
  expect(pane.querySelectorAll('.concept-frame:not([hidden])')).toHaveLength(1);
  expect(pane.querySelectorAll('.capability-detail-content')).toHaveLength(1);
});

it('settles reduced motion and keeps every capability manually usable', async () => {
  const pane = await mount();
  advance(1200);
  document.documentElement.dataset.reducedMotion = 'true';
  await Promise.resolve();
  const position = elapsed(pane);
  advance(14000);
  expect(elapsed(pane)).toBe(position);
  expect(playback(pane).disabled).toBe(true);
  for (const id of ['models', 'compare', 'product-source', 'configurations']) {
    pane.querySelector<HTMLButtonElement>(`#${id}`)!.click();
    expect(selected(pane).id).toBe(id);
    expect(pane.querySelectorAll('.concept-frame:not([hidden])')).toHaveLength(1);
  }
  expect(pane.querySelector('.concept-frame:not([hidden]) svg')?.getAttribute('data-phase')).toBe('settled');
});

it('opens every existing capability fragment and responds to later fragment navigation', async () => {
  window.history.replaceState(null, '', '/product/capabilities#compare');
  const pane = await mount();
  expect(selected(pane).id).toBe('compare');
  for (const id of ['configurations', 'models', 'product-source']) {
    window.history.replaceState(null, '', `/product/capabilities#${id}`);
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(selected(pane).id).toBe(id);
    expect(elapsed(pane)).toBe(0);
  }
});

it('initializes from the platform reduced-motion preference', async () => {
  const media = window.matchMedia.bind(window);
  vi.spyOn(window, 'matchMedia').mockImplementation(query => {
    const result = media(query);
    if (query === '(prefers-reduced-motion: reduce)') Object.defineProperty(result, 'matches', { value: true });
    return result;
  });
  const pane = await mount();
  advance(CAPABILITY_MOTION.duration * 2);
  expect(selected(pane).id).toBe('configurations');
  expect(playback(pane).disabled).toBe(true);
  pane.querySelector<HTMLButtonElement>('#compare')!.click();
  expect(selected(pane).id).toBe('compare');
});

it('restarts rapid manual selections without retaining an earlier transition', async () => {
  const pane = await mount();
  advance(CAPABILITY_MOTION.duration + 160);
  for (const id of ['compare', 'configurations', 'product-source', 'models']) pane.querySelector<HTMLButtonElement>(`#${id}`)!.click();
  expect(pane.querySelectorAll('.concept-frame:not([hidden])')).toHaveLength(1);
  expect(selected(pane).id).toBe('models');
  expect(elapsed(pane)).toBe(0);
  advance(CAPABILITY_MOTION.duration);
  expect(selected(pane).id).toBe('compare');
});

it('cancels its frame and disconnects global listeners when its host is removed', async () => {
  const pane = await mount();
  pane.remove();
  await Promise.resolve();
  const raf = vi.spyOn(window, 'requestAnimationFrame');
  window.dispatchEvent(new Event('focus'));
  document.dispatchEvent(new Event('visibilitychange'));
  window.dispatchEvent(new HashChangeEvent('hashchange'));
  expect(raf).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});

it('handles repeated suspension and selection without competing elapsed-time origins', () => {
  const clock = createCapabilitySequence(4);
  clock.setRunning(true, 0);
  expect(clock.setRunning(false, 1800)).toEqual({ index: 0, elapsed: 1800 });
  clock.setRunning(false, 9000);
  clock.setRunning(true, 10000);
  clock.setRunning(true, 11000);
  expect(clock.advance(12000)).toEqual({ index: 0, elapsed: 3800 });
  clock.select(2, 12000);
  expect(clock.advance(12000 + CAPABILITY_MOTION.duration)).toEqual({ index: 3, elapsed: 0 });
});

it('runs an explicit play request while the timeline retains keyboard focus', async () => {
  const pane = await mount();
  advance(1200);
  playback(pane).focus();
  expect(playback(pane).getAttribute('aria-label')).toBe('Pause capability sequence');
  pointer(pane,'pointerenter');
  // Hover/focus holds time but does not flip the action under the user's click.
  playback(pane).click();
  expect(playback(pane).getAttribute('aria-label')).toBe('Play capability sequence');
  advance(1200);
  expect(elapsed(pane)).toBe(1200);
  playback(pane).click();
  advance(1200);
  expect(elapsed(pane)).toBe(2400);
  playback(pane).click();
  advance(2400);
  expect(elapsed(pane)).toBe(2400);
  playback(pane).click();
  advance(1200);
  expect(elapsed(pane)).toBe(3600);
  pane.querySelector<HTMLButtonElement>('#models')!.focus();
  advance(1200);
  expect(elapsed(pane)).toBe(3600);
});

it('keeps every particle study within its stage and settles before rollover', () => {
  const palettes = new Set<string>();
  for (const item of PRODUCT_CAPABILITIES) {
    const svg = buildCapabilityConcept(item.concept);
    const render = capabilityConceptRenderer(svg);
    const initial = svg.innerHTML;
    palettes.add([...new Set([...svg.querySelectorAll('circle')].map(dot => dot.getAttribute('fill')))].sort().join(','));
    for (const time of [1200,3200,CAPABILITY_MOTION.phases.complete]) {
      render(time,false,{x:220,y:160});
      expect(svg.innerHTML).not.toBe(initial);
      for (const dot of svg.querySelectorAll('circle')) {
        const x = Number(dot.getAttribute('cx')), y = Number(dot.getAttribute('cy')), r = Number(dot.getAttribute('r'));
        expect(x - r).toBeGreaterThanOrEqual(0);
        expect(x + r).toBeLessThanOrEqual(440);
        expect(y - r).toBeGreaterThanOrEqual(0);
        expect(y + r).toBeLessThanOrEqual(320);
      }
    }
    render(CAPABILITY_MOTION.phases.complete,false);
    const settled = svg.innerHTML;
    render(CAPABILITY_MOTION.duration - 1,false);
    expect(svg.innerHTML).toBe(settled);
    render(0,true,{x:180,y:120});
    expect(svg.innerHTML).toBe(settled);
    expect(svg.querySelector('path, polygon, rect, text')).toBeNull();
  }
  expect(palettes.size).toBe(PRODUCT_CAPABILITIES.length);
});

it('reacts to a pointer while holding timeline time and restores the stored pose on exit', async () => {
  const pane = await mount();
  advance(1600);
  pointer(pane,'pointerenter');
  const svg = pane.querySelector<SVGSVGElement>('.concept-frame:not([hidden]) svg')!;
  vi.spyOn(svg,'getBoundingClientRect').mockReturnValue({left:0,top:0,width:440,height:320} as DOMRect);
  const pose = () => [...svg.querySelectorAll('circle')].sort((a,b) => Number(a.dataset.particle) - Number(b.dataset.particle)).map(dot => ['cx','cy','r','opacity'].map(attr => dot.getAttribute(attr)));
  const stored = pose();
  const stage = pane.querySelector('.capability-stage')!;
  stage.dispatchEvent(new PointerEvent('pointermove',{pointerType:'mouse',clientX:220,clientY:100}));
  advance(16);
  expect(elapsed(pane)).toBe(1600);
  expect(pose()).not.toEqual(stored);
  stage.dispatchEvent(new PointerEvent('pointerleave',{pointerType:'mouse'}));
  expect(pose()).toEqual(stored);
  expect(vi.getTimerCount()).toBe(0);
  document.documentElement.dataset.reducedMotion = 'true';
  await Promise.resolve();
  const staticPose = svg.innerHTML;
  stage.dispatchEvent(new PointerEvent('pointermove',{pointerType:'mouse',clientX:220,clientY:100}));
  advance(16);
  expect(svg.innerHTML).toBe(staticPose);
});

it('preserves the visible particle positions through interrupted section transitions', async () => {
  const pane = await mount();
  const pose = () => capabilityConceptPose(pane.querySelector<SVGSVGElement>('.concept-frame:not([hidden]) svg')!).map(({color,...position}) => position);
  advance(1600);
  const outgoing = pose();
  pane.querySelector<HTMLButtonElement>('#compare')!.click();
  expect(elapsed(pane)).toBe(0);
  expect(pose()).toEqual(outgoing);
  expect(pane.querySelector('[role="tablist"]')?.getAttribute('aria-orientation')).toBe('horizontal');
  advance(CAPABILITY_MOTION.transition / 2);
  const midTransition = pose();
  expect(midTransition).not.toEqual(outgoing);
  playback(pane).click();
  advance(CAPABILITY_MOTION.duration);
  expect(pose()).toEqual(midTransition);
  pane.querySelector<HTMLButtonElement>('#models')!.click();
  expect(pose()).toEqual(midTransition);
  advance(CAPABILITY_MOTION.transition);
  expect(pose()).not.toEqual(midTransition);
  expect(pane.querySelectorAll('.concept-frame:not([hidden])')).toHaveLength(1);
  expect(pane.querySelectorAll('.capability-detail-content')).toHaveLength(1);
});
