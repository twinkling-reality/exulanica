// The page has words for every code the server records about who decides for a person: each set
// of words is held here to the Python source that states the codes.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { CHOICE_REFUSAL_WORDS, DECISION_WORDS, HOST_REFUSAL_WORDS, MODEL_REFUSAL_WORDS } from '../src/ui/society-models.js';

const REPOSITORY = new URL('../../../../', import.meta.url);
const python = (path: string): string => readFileSync(new URL(path, REPOSITORY), 'utf8');

/**
 * The codes of one set or mapping a Python module states, read from the module: every quoted
 * identifier from its name to the bracket that closes it at the start of a line. A mapping's
 * values are sentences, which are never one identifier.
 */
function stated(path: string, name: string): string[] {
  const source = python(path);
  const start = source.indexOf(`${name}: Final = `);
  expect(start, `${name} in ${path}`).toBeGreaterThan(-1);
  const end = source.slice(start).search(/\n[)}]/);
  expect(end, `the end of ${name} in ${path}`).toBeGreaterThan(-1);
  return [...source.slice(start, start + end).matchAll(/"([a-z_]+)"/g)].map((match) => match[1]!);
}

describe('the page\'s words for the codes a person\'s decision records', () => {
  it('has words for exactly the reasons a receipt or its minute records', () => {
    const codes = stated('exulanica/world/society_decision_contract.py', 'DECISION_REASONS');
    // A positive control: reasons the host is known to record are found by the same reading.
    expect(codes).toEqual(expect.arrayContaining(['validated_choice', 'model_timed_out', 'place_taken_this_minute']));
    expect(Object.keys(DECISION_WORDS).sort()).toEqual([...codes].sort());
  });

  it('has words for exactly the reasons a host asks no model and a choice is refused', () => {
    const host = stated('exulanica/api/society_person_decisions.py', 'HOST_REFUSALS');
    expect(host).toContain('models_not_run_here');
    expect(Object.keys(HOST_REFUSAL_WORDS).sort()).toEqual([...host].sort());
    const model = stated('exulanica/api/society_person_decisions.py', 'MODEL_REFUSALS');
    expect(model).toContain('provider_changed');
    expect(Object.keys(MODEL_REFUSAL_WORDS).sort()).toEqual([...model].sort());
    const refusals = stated('exulanica/world/society_model_choice_repository.py', 'CHOICE_REFUSALS');
    expect(refusals).toContain('too_many_model_people');
    expect(Object.keys(CHOICE_REFUSAL_WORDS).sort()).toEqual([...refusals].sort());
  });
});

