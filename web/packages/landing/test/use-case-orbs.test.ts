// @vitest-environment happy-dom
import { afterEach, expect, it } from 'vitest';
import { buildUseCases } from '../src/ui/use-cases.js';
import { USE_CASES } from '../src/content/use-cases.js';
import { createOrbState } from '../src/ui/use-case-orb-state.js';

afterEach(() => document.body.replaceChildren());

it('integrates one active clock, smooths emphasis, and never catches up after suspension', () => {
  const state = createOrbState([2.4, 6.8, 11.2]);
  state.advance(0); state.advance(30);
  const before = state.values.map(value => value.phase);
  state.select(1); state.advance(60);
  expect(state.values[1]!.emphasis).toBeGreaterThan(0);
  expect(state.values[0]!.emphasis).toBe(0);
  expect(state.values[1]!.phase - before[1]!).toBeGreaterThan(state.values[0]!.phase - before[0]!);
  const held = state.values.map(value => value.phase);
  state.suspend(); state.advance(10000);
  expect(state.values.map(value => value.phase)).toEqual(held);
  state.advance(20000);
  expect(state.values[1]!.phase - held[1]!).toBeLessThan(1 / 30);
});

it('lists each use case as a plain destination, without decorative orbs', () => {
  const host = buildUseCases();
  document.body.append(host);
  const destinations = host.querySelectorAll<HTMLAnchorElement>('.use-case-destination');
  expect(destinations).toHaveLength(USE_CASES.length);
  expect(host.querySelector('.use-case-orb')).toBeNull();
  for (const item of USE_CASES) {
    const link = [...destinations].find(node => node.pathname === `/use-cases/${item.key}`)!;
    expect(link.querySelector('h2')?.textContent).toBe(item.title);
    expect(link.textContent).toContain(item.summary);
  }
});
