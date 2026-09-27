// Every page table of words keyed by codes the server states has words for exactly those codes,
// read from the one place the server states them. A code added there fails here until the page
// can say it; a word left here for a code the server dropped fails too.
import { readFileSync, readdirSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { HISTORY_WORDS } from '../src/ui/detail.js';
import { AXIS_WORDS, EASING_WORDS } from '../src/ui/object-placement.js';
import { CITY_RECORD_WORDS } from '../src/ui/representation-inspector.js';
import { REFUSAL_WORDS } from '../src/ui/society-directed-action.js';
import { PRESENCE_WORDS, UNREACHABLE, UNUSABLE_WORDS } from '../src/ui/world-inhabitants.js';

/** The repository, from the web workspace vitest runs in, as the other page tests read it. */
const REPOSITORY = `${process.cwd()}/..`;
const read = (path: string): string => readFileSync(`${REPOSITORY}/${path}`, 'utf8');

/** The string members of a Python `NAME: Final = frozenset({...})`, read from its source. */
function frozensetOf(path: string, name: string): string[] {
  const block = new RegExp(`^${name}: Final = frozenset\\(\\s*\\{([^}]*)\\}\\s*\\)`, 'm').exec(read(path));
  expect(block, `${name} in ${path}`).not.toBeNull();
  return [...block![1]!.matchAll(/"([a-z_]+)"/g)].map((match) => match[1]!);
}

const sorted = (values: Iterable<string>): string[] => [...values].sort();

describe('the page\'s words for server codes', () => {
  it('say why a presence request was refused, for exactly the stated names', () => {
    const stated = frozensetOf('exulanica/world/society_presence.py', 'PRESENCE_REFUSALS');
    expect(stated).toEqual(expect.arrayContaining(['already_here', 'engine_keeps_its_people']));
    // A stale request is refused by the application's own handler, by this one name.
    expect(read('exulanica/api/app.py')).toContain('"stale_society_state"');
    expect(sorted(Object.keys(PRESENCE_WORDS))).toEqual(sorted([...stated, 'stale_society_state']));
  });

  it('say why a directed request was refused or went stale, for exactly the stated names', () => {
    const stated = frozensetOf('exulanica/world/society_actions.py', 'ACTION_REFUSALS');
    expect(stated).toEqual(expect.arrayContaining(['inhabitant_already_there', 'destination_full']));
    expect(sorted(Object.keys(REFUSAL_WORDS))).toEqual(sorted(stated));
  });

  it('say why an object offers no activity, for exactly the reasons a saved world\'s input records', () => {
    const source = read('exulanica/world/society_input_policy.py');
    const constant = (name: string): string => {
      const found = new RegExp(`^${name} = "([a-z_]+)"$`, 'm').exec(source);
      expect(found, `${name} in society_input_policy.py`).not.toBeNull();
      return found![1]!;
    };
    const v3 = /AUTHORED_GROUND_INPUT_V3: frozenset\(\{([^}]*)\}\)/.exec(source);
    expect(v3, 'LOCAL_RECORD_REASONS for authored-ground v3').not.toBeNull();
    const reasons = v3![1]!.split(',').map((name) => constant(name.trim()));
    expect(reasons).toContain(UNREACHABLE);
    expect(sorted([...Object.keys(UNUSABLE_WORDS), UNREACHABLE])).toEqual(sorted(reasons));
  });

  it('name each axis and easing the bounded-path behaviour allows', () => {
    const seed = read('exulanica/migrations/0042_authored_world_objects.sql');
    const choices = (parameter: string): string[] => {
      const found = new RegExp(`"${parameter}":\\{"kind":"choice","choices":\\[([^\\]]*)\\]`).exec(seed);
      expect(found, `${parameter} in the bounded-path registry row`).not.toBeNull();
      return [...found![1]!.matchAll(/"([a-z]+)"/g)].map((match) => match[1]!);
    };
    expect(sorted(Object.keys(AXIS_WORDS))).toEqual(sorted(choices('axis')));
    expect(sorted(Object.keys(EASING_WORDS))).toEqual(sorted(choices('easing')));
  });

  it('name each city record kind the city shapes catalog states', () => {
    const catalog = JSON.parse(read('exulanica/grammar/grammars/city/city-shapes.v2.json')) as {
      records: { kind: string }[];
    };
    expect(catalog.records.length).toBeGreaterThan(0);
    expect(sorted(Object.keys(CITY_RECORD_WORDS))).toEqual(sorted(catalog.records.map((r) => r.kind)));
  });

  it('name each identity history event the server\'s enum holds', () => {
    const migrations = readdirSync(`${REPOSITORY}/exulanica/migrations`).filter((name) => name.endsWith('.sql'));
    const stated = new Set<string>();
    for (const name of migrations) {
      const sql = read(`exulanica/migrations/${name}`);
      const created = /create type identity_event_type as enum \(([^)]*)\)/.exec(sql);
      if (created !== null) for (const value of created[1]!.matchAll(/'([a-z_]+)'/g)) stated.add(value[1]!);
      for (const added of sql.matchAll(/alter type identity_event_type add value if not exists '([a-z_]+)'/g)) {
        stated.add(added[1]!);
      }
    }
    expect([...stated]).toEqual(expect.arrayContaining(['entity_created', 'entity_renamed']));
    expect(sorted(Object.keys(HISTORY_WORDS))).toEqual(sorted(stated));
  });
});
