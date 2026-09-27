// The Compare view has words for every code the server gives a comparison: each set of words is
// held here to the Python source that states the codes.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  ANSWERING_MECHANISMS,
  ANSWERING_SOURCES,
  ARM_ROLES,
  GROUP_SOURCES,
  VERDICT_CODES,
} from '../src/society-comparison-api.js';
import {
  ANSWERING_SOURCE_WORDS,
  EXCLUDED_WORDS,
  FAILURE_WORDS,
  GROUP_SOURCE_WORDS,
  MECHANISM_WORDS,
  NOT_JUDGED_WORDS,
  VERDICT_WORDS,
} from '../src/ui/society-comparison.js';

const REPOSITORY = new URL('../../../../', import.meta.url);
const python = (path: string): string => readFileSync(new URL(path, REPOSITORY), 'utf8');

/**
 * The codes of one tuple or set a Python module states, read from the module: every quoted
 * identifier from its name to the bracket that closes it at the start of a line.
 */
function stated(path: string, name: string): string[] {
  const source = python(path);
  const start = source.indexOf(`${name}: Final = `);
  expect(start, `${name} in ${path}`).toBeGreaterThan(-1);
  const end = source.slice(start).search(/\n[)}]/);
  expect(end, `the end of ${name} in ${path}`).toBeGreaterThan(-1);
  return [...source.slice(start, start + end).matchAll(/"([a-z_]+)"/g)].map((match) => match[1]!);
}

/** One string constant a Python module states on a line of its own. */
function constant(path: string, name: string): string {
  const found = new RegExp(`^${name}: Final = "([a-z_]+)"$`, 'm').exec(python(path));
  expect(found, `${name} in ${path}`).not.toBeNull();
  return found![1]!;
}

const CLAIM = 'exulanica/world/society_comparison_claim.py';

describe('the Compare view\'s words for the codes a comparison records', () => {
  it('has words for exactly the verdicts the server gives, and the reasons one is not judged', () => {
    const verdicts = stated(CLAIM, 'VERDICTS');
    // A positive control: verdicts the server is known to give are found by the same reading.
    expect(verdicts).toEqual(expect.arrayContaining(['different', 'no_measured_difference']));
    expect([...VERDICT_CODES]).toEqual(verdicts);
    expect(Object.keys(VERDICT_WORDS).sort()).toEqual([...verdicts].sort());
    const reasons = stated(CLAIM, 'NOT_JUDGED_REASONS');
    expect(reasons).toContain('development_seeds');
    expect(Object.keys(NOT_JUDGED_WORDS).sort()).toEqual([...reasons].sort());
  });

  it('has words for exactly the ways a run fails and a seed carries no score', () => {
    const failures = stated('exulanica/api/society_comparison_runner.py', 'RUN_FAILURE_CODES');
    expect(failures).toContain('process_budget_spent');
    expect(Object.keys(FAILURE_WORDS).sort()).toEqual([...failures].sort());
    expect(Object.keys(EXCLUDED_WORDS)).toEqual([
      constant('exulanica/world/society_score.py', 'BELOW_FLOOR'),
    ]);
  });

  it('reads exactly the arm roles the server states', () => {
    const roles = stated('exulanica/world/society_comparison_result.py', 'ARM_ROLES');
    expect(roles).toContain('control');
    expect([...ARM_ROLES]).toEqual(roles);
  });

  it('reads, and has words for, exactly the places a comparison\'s group comes from', () => {
    const sources = stated('exulanica/world/society_comparison_result.py', 'GROUP_SOURCES');
    expect(sources).toContain('owner_choice');
    expect([...GROUP_SOURCES]).toEqual(sources);
    expect(Object.keys(GROUP_SOURCE_WORDS).sort()).toEqual([...sources].sort());
  });

  it('reads, and has words for, exactly the ways a model is asked and whose order that is', () => {
    const answering = stated('exulanica/world/society_comparison_result.py', 'ANSWERING_SOURCES');
    expect(answering).toContain('model');
    expect([...ANSWERING_SOURCES]).toEqual(answering);
    expect(Object.keys(ANSWERING_SOURCE_WORDS).sort()).toEqual([...answering].sort());
    // The mechanisms are the manifest's enum, one quoted value per member.
    const manifest = python('exulanica/models/manifest.py');
    const start = manifest.indexOf('class AnsweringMechanism(StrEnum):');
    expect(start).toBeGreaterThan(-1);
    const body = manifest.slice(start, start + manifest.slice(start).search(/\n\n\n/));
    const mechanisms = [...body.matchAll(/^ {4}[A-Z_]+ = "([a-z_]+)"$/gm)].map((match) => match[1]!);
    expect(mechanisms).toContain('json_schema');
    expect([...ANSWERING_MECHANISMS].sort()).toEqual([...mechanisms].sort());
    expect(Object.keys(MECHANISM_WORDS).sort()).toEqual([...mechanisms].sort());
  });
});
