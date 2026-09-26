// The Compare view has words for every code the server gives a comparison: each set of words is
// held here to the Python source that states the codes.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { ARM_ROLES, VERDICT_CODES } from '../src/society-comparison-api.js';
import {
  EXCLUDED_WORDS,
  FAILURE_WORDS,
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
});
