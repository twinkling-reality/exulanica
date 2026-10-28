// @vitest-environment happy-dom
import { expect, it } from 'vitest';
import { CAPABILITY_MOTION, createCapabilitySequence } from '../src/ui/capability-sequence.js';
import { buildCapabilityConcept, capabilityConceptRenderer } from '../src/ui/capability-concept.js';
import { PRODUCT_CAPABILITIES } from '../src/content/product.js';

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

it('keeps every particle study within its stage and settles before rollover', () => {
  const palettes = new Set<string>();
  for (const item of PRODUCT_CAPABILITIES) {
    const svg = buildCapabilityConcept(item.concept);
    const render = capabilityConceptRenderer(svg);
    const initial = svg.innerHTML;
    palettes.add([...new Set([...svg.querySelectorAll('circle')].map(dot => dot.getAttribute('fill')))].sort().join(','));
    for (const time of [1200, 3200, CAPABILITY_MOTION.phases.complete]) {
      render(time, false, { x: 220, y: 160 });
      expect(svg.innerHTML).not.toBe(initial);
      for (const dot of svg.querySelectorAll('circle')) {
        const x = Number(dot.getAttribute('cx')), y = Number(dot.getAttribute('cy')), r = Number(dot.getAttribute('r'));
        expect(x - r).toBeGreaterThanOrEqual(0);
        expect(x + r).toBeLessThanOrEqual(440);
        expect(y - r).toBeGreaterThanOrEqual(0);
        expect(y + r).toBeLessThanOrEqual(320);
      }
    }
    render(CAPABILITY_MOTION.phases.complete, false);
    const settled = svg.innerHTML;
    render(CAPABILITY_MOTION.duration - 1, false);
    expect(svg.innerHTML).toBe(settled);
    render(0, true, { x: 180, y: 120 });
    expect(svg.innerHTML).toBe(settled);
    expect(svg.querySelector('path, polygon, rect, text')).toBeNull();
  }
  expect(palettes.size).toBe(PRODUCT_CAPABILITIES.length);
});
