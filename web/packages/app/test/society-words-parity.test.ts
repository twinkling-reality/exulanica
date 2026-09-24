// The page restates three server facts: the playback speeds the server accepts, the reason codes its
// society engine records, and how many events one read returns. Each copy is held to its source here.
import { readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { PLAYBACK_SPEEDS } from '../src/society-control-api.js';
import { SOCIETY_EVENT_WINDOW } from '../src/society-api.js';
import { REASON_WORDS } from '../src/ui/world-inhabitants.js';

const WORLD = new URL('../../../../exulanica/world/', import.meta.url);
const python = (name: string): string => readFileSync(new URL(name, WORLD), 'utf8');
const API_SNAPSHOT = new URL('../../../../tests/snapshots/api-openapi.json', import.meta.url);

describe('the page\'s copies of society facts', () => {
  it('offers exactly the speeds the server accepts', () => {
    const declared = /^SPEEDS = \(([^)]*)\)$/m.exec(python('society_controls.py'));
    expect(declared, 'SPEEDS in exulanica/world/society_controls.py').not.toBeNull();
    expect([...PLAYBACK_SPEEDS]).toEqual(declared![1]!.split(',').map((speed) => Number(speed.trim())));
  });

  it('has words only for reason codes the society modules record', () => {
    const sources = readdirSync(WORLD).filter((name) => /^society_.*\.py$/.test(name)).map(python).join('\n');
    // A positive control: a code the planner is known to record is found by the same search.
    expect(sources).toContain('"restore_need"');
    const stale = Object.keys(REASON_WORDS).filter((code) => !sources.includes(`"${code}"`));
    expect(stale, 'reason codes with words that no society module records').toEqual([]);
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
