// The page restates four server facts: the playback speeds the server accepts, the reason codes its
// society engine records, what a purposeful society's people can be doing, and how many events one
// read returns. Each copy is held to its source here.
import { readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { PLAYBACK_SPEEDS } from '../src/society-control-api.js';
import { PURPOSEFUL_ACTIVITIES, SOCIETY_EVENT_WINDOW } from '../src/society-api.js';
import { REASON_WORDS } from '../src/ui/world-inhabitants.js';

const WORLD = new URL('../../../../exulanica/world/', import.meta.url);
const python = (name: string): string => readFileSync(new URL(name, WORLD), 'utf8');
const API_SNAPSHOT = new URL('../../../../tests/snapshots/api-openapi.json', import.meta.url);
const SOCIETY_CATALOGS = new URL('../../../../assets/catalogs/society/', import.meta.url);

/** The codes `REASON_CODES` in society_planner.py states, read from the source that states them. */
function reasonCodes(): string[] {
  const block = /^REASON_CODES: Final = frozenset\(\s*\{([^}]*)\}\s*\)$/m.exec(python('society_planner.py'));
  expect(block, 'REASON_CODES in exulanica/world/society_planner.py').not.toBeNull();
  return [...block![1]!.matchAll(/"([a-z_]+)"/g)].map((match) => match[1]!);
}

describe('the page\'s copies of society facts', () => {
  it('offers exactly the speeds the server accepts', () => {
    const declared = /^SPEEDS = \(([^)]*)\)$/m.exec(python('society_controls.py'));
    expect(declared, 'SPEEDS in exulanica/world/society_controls.py').not.toBeNull();
    expect([...PLAYBACK_SPEEDS]).toEqual(declared![1]!.split(',').map((speed) => Number(speed.trim())));
  });

  it('has words for exactly the reason codes the planner states it records', () => {
    const codes = reasonCodes();
    // A positive control: codes the planner is known to record are found by the same reading.
    expect(codes).toEqual(expect.arrayContaining(['restore_need', 'stopped_to_talk', 'partner_left']));
    expect(Object.keys(REASON_WORDS).sort()).toEqual([...codes].sort());
  });

  it('reads exactly the activities the purposeful routine catalogs state, in every version', () => {
    const stated = new Set<string>();
    const files = readdirSync(SOCIETY_CATALOGS).filter((name) => /^society-purposeful-activity\.v\d+\.json$/.test(name));
    // A positive control: the released routine and the one new inputs record are both read.
    expect(files.length).toBeGreaterThanOrEqual(2);
    for (const name of files) {
      const catalog = JSON.parse(readFileSync(new URL(name, SOCIETY_CATALOGS), 'utf8')) as {
        entries: { key: string; setting: string; affordance: string }[];
      };
      for (const entry of catalog.entries) stated.add(entry.setting === 'object' ? entry.affordance : entry.key);
    }
    expect([...PURPOSEFUL_ACTIVITIES].sort()).toEqual([...stated].sort());
  });

  it('reads events in windows exactly as large as the events route allows', () => {
    const snapshot = JSON.parse(readFileSync(API_SNAPSHOT, 'utf8')) as {
      paths: Record<string, { get?: { parameters?: { name: string; schema?: { maximum?: number } }[] } }>;
    };
    const route = snapshot.paths['/world/versions/{version_id}/society/events'];
    expect(route, 'the events route in tests/snapshots/api-openapi.json').toBeDefined();
    const limit = route!.get?.parameters?.find((parameter) => parameter.name === 'limit');
    expect(limit?.schema?.maximum, 'the events route\'s limit maximum').toBe(SOCIETY_EVENT_WINDOW);
  });
});
