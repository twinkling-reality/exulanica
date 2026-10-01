import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { parseWorldCapabilities, type WorldCapabilities } from '../src/capabilities-api.js';
import {
  ACTIONS,
  availability,
  COMMON_REFUSALS,
  refusalWords,
  UNRECOGNISED_REFUSAL,
  type ActionSpec,
} from '../src/ui/actions/registry.js';
import { ICON_NAMES } from '../src/ui/system/icon.js';

const routes = JSON.parse(readFileSync(new URL('../../../../tests/snapshots/api-routes.json', import.meta.url), 'utf8')) as
  readonly { readonly method: string; readonly path: string }[];
const ROUTE_KEYS = new Set(routes.map((route) => `${route.method} ${route.path}`));

const ALL_WORDS = (spec: ActionSpec) => [
  spec.label, spec.hint, ...Object.values(spec.refusals ?? {}).flatMap((words) => [words.happened, words.next]),
];

describe('the action registry', () => {
  it('declares each action once, with words, an icon from the set and somewhere to offer it', () => {
    const ids = ACTIONS.map((spec) => spec.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const spec of ACTIONS) {
      expect(spec.label.trim(), spec.id).not.toBe('');
      expect(spec.hint.trim(), spec.id).not.toBe('');
      expect(ICON_NAMES, spec.id).toContain(spec.icon);
      expect(spec.placement.length, spec.id).toBeGreaterThan(0);
    }
  });

  it('names only operations the API serves', () => {
    for (const spec of ACTIONS) {
      if (spec.operation !== undefined) expect(ROUTE_KEYS, spec.id).toContain(spec.operation);
    }
  });

  it('has words for every refusal it lists, and none of them carries a code or an em dash', () => {
    for (const spec of ACTIONS) {
      for (const [code, words] of Object.entries(spec.refusals ?? {})) {
        expect(words.happened.trim(), `${spec.id} ${code}`).not.toBe('');
        expect(words.next.trim(), `${spec.id} ${code}`).not.toBe('');
      }
      for (const text of ALL_WORDS(spec)) {
        expect(text, spec.id).not.toMatch(/[a-z]+_[a-z_]+/);
        expect(text, spec.id).not.toContain('\u2014');
      }
    }
    for (const words of [...Object.values(COMMON_REFUSALS), UNRECOGNISED_REFUSAL]) {
      expect(`${words.happened} ${words.next}`).not.toMatch(/[a-z]+_[a-z_]+/);
    }
  });

  it('every shortcut belongs to one action', () => {
    const keys = ACTIONS.flatMap((spec) => (spec.shortcut === undefined ? [] : [spec.shortcut]));
    expect(new Set(keys).size).toBe(keys.length);
  });
});

function world(operations: readonly Record<string, unknown>[]): WorldCapabilities {
  return parseWorldCapabilities({
    profile: 'exulanica.world-capabilities/v1',
    world_id: 'world:authored-starter:test',
    version_id: 'v1',
    kind: 'authored-starter',
    society: { held: false, engine: 'exulanica-society/v2' },
    operations,
  });
}

const descriptor = (operation: string, state: string, code: string | null, permitted = true) => ({
  operation, bind: { version_id: 'v1' }, permitted, state, code, spends: false, writes: true,
  effects: [], dependencies: [], preview: null, some_future_member: { kept: 'ignored' },
});

const spec = (id: string): ActionSpec => ACTIONS.find((candidate) => candidate.id === id)!;

describe('availability comes from the descriptors', () => {
  const advance = spec('clock.advance');

  it('is unknown before anything is read, never assumed available', () => {
    expect(availability(advance, null).state).toBe('unknown');
  });

  it('takes the descriptor state, with the action’s own words for its code', () => {
    const read = world([descriptor(advance.operation!, 'unavailable', 'society_unavailable')]);
    const found = availability(advance, read);
    expect(found.state).toBe('unavailable');
    expect(found.code).toBe('society_unavailable');
    expect(found.words?.happened).toBe('Nobody lives in this world yet.');
  });

  it('reads unsupported before permission, and permission before state', () => {
    expect(availability(advance, world([descriptor(advance.operation!, 'unsupported', 'x', false)])).state).toBe('unsupported');
    expect(availability(advance, world([descriptor(advance.operation!, 'unavailable', 'x', false)])).state).toBe('not-permitted');
    expect(availability(advance, world([descriptor(advance.operation!, 'available', null, true)])).state).toBe('available');
  });

  it('reads a state this client does not know as unknown', () => {
    expect(availability(advance, world([descriptor(advance.operation!, 'paused_for_maintenance', null)])).state).toBe('unknown');
  });

  it('local actions are available without a read', () => {
    expect(availability(spec('map.open'), null).state).toBe('available');
  });

  it('a refusal at run time gets the action’s words, then the shared words, then the generic pair', () => {
    expect(refusalWords(spec('objects.undo'), 'stale_object_base').happened).toContain('changed while you were deciding');
    expect(refusalWords(spec('objects.undo'), 'busy')).toBe(COMMON_REFUSALS['busy']);
    expect(refusalWords(spec('objects.undo'), 'something_new')).toBe(UNRECOGNISED_REFUSAL);
  });
});
