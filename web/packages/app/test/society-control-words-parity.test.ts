// The page has its own words for every code the playback control states about a world: why its host
// does not play it, and why open models are not asked for its people. Each set is held here to the
// Python source that states the codes, so a code added there fails until the page can say it.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { HOST_PLAYBACK_WORDS, MODEL_MINDS_WHY, MODEL_MINDS_WORDS } from '../src/ui/world-inhabitants.js';

const REPOSITORY = new URL('../../../../', import.meta.url);
const python = (path: string): string => readFileSync(new URL(path, REPOSITORY), 'utf8');

/** The keys of a mapping a Python module states, from its name to the brace closing it at a line's start. */
function keys(path: string, opening: string): string[] {
  const source = python(path);
  const start = source.indexOf(opening);
  expect(start, `${opening} in ${path}`).toBeGreaterThan(-1);
  const end = source.slice(start).search(/\n}/);
  expect(end, `the end of ${opening} in ${path}`).toBeGreaterThan(-1);
  // A key opens its line, quoted, followed by a colon; the sentences are never one identifier.
  return [...source.slice(start, start + end).matchAll(/^\s+"([a-z_]+)":/gm)].map((match) => match[1]!);
}

/** The codes a field of the control read admits, from its Literal in the route module. */
function literal(path: string, field: string): string[] {
  const source = python(path);
  const start = source.indexOf(`    ${field}: `);
  expect(start, `${field} in ${path}`).toBeGreaterThan(-1);
  const end = source.slice(start).search(/\| None/);
  return [...source.slice(start, start + end).matchAll(/"([a-z_]+)"/g)].map((match) => match[1]!);
}

describe('the page\'s words for the codes the playback control states', () => {
  it('has words for exactly the reasons a host does not play a world', () => {
    const codes = keys('exulanica/api/society_control_worker.py', 'HOST_PLAYBACK_REFUSALS = {');
    // A positive control: codes the host is known to state are found by the same reading.
    expect(codes).toEqual(expect.arrayContaining(['no_playback_worker', 'guest_towns_full']));
    expect(Object.keys(HOST_PLAYBACK_WORDS).sort()).toEqual([...codes].sort());
    expect(literal('exulanica/api/routes/society_control.py', 'host_playback_code').sort()).toEqual([...codes].sort());
  });

  it('has words for exactly the reasons open models are not asked for the people here', () => {
    const codes = keys('exulanica/api/routes/society_control.py', 'MODEL_MINDS_REASONS: Final = {');
    expect(codes).toEqual(['spending_cap_reached']);
    expect(Object.keys(MODEL_MINDS_WORDS).sort()).toEqual([...codes].sort());
    expect(Object.keys(MODEL_MINDS_WHY).sort()).toEqual([...codes].sort());
    expect(literal('exulanica/api/routes/society_control.py', 'model_minds_code').sort()).toEqual([...codes].sort());
  });
});
