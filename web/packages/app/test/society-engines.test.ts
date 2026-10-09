import { readFileSync } from 'node:fs';
import type { OwnedSocietyState } from '@exulanica/atlas-react/playcanvas';
import { describe, expect, it } from 'vitest';
import { SOCIETY_ENGINES_V3_JSON } from '../src/society-engines.generated.js';
import {
  DEFAULT_SOCIETY_ENGINE,
  SOCIETY_ENGINES,
  engineCreatedOver,
  readEngineTable,
  societyEngine,
  type SocietyEngineProfile,
} from '../src/society-engines.js';
import { parseSociety } from '../src/society-api.js';

/*
 * The browser reads which society engines exist, and what each can do, from the backend's own
 * table. These pin that the generated copy is that file byte for byte, that the parser takes its
 * reader and its population bounds from it, and that an engine it does not state is refused by
 * name rather than read as one it resembles.
 */

const TABLE = new URL('../../../../exulanica/world/society-engines.v3.json', import.meta.url);
const SECOND = new URL('../../../../exulanica/world/society-engines.v2.json', import.meta.url);

// The display keeps its own union of profiles in atlas-react, which cannot import this package;
// the typecheck holds it to the engine table's union, so a new engine cannot reach one and not
// the other.
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
const displayNamesEveryEngine: Same<NonNullable<OwnedSocietyState['profile']>, SocietyEngineProfile> = true;

const inhabitant = (i: number, goal: unknown = null) => ({
  id: `person-${i}`, synthetic: true, position_mm: [i, 0], display_name: `Person ${i}`, role: 'steward',
  goal, route: null, motion_path_mm: [[i, 0]],
  action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
  explanation: { summary: 'Awaiting a supported goal.', event_ids: [] },
});
const purposeful = (profile: string, population: number, goal: unknown = null) => ({
  society_id: 'society', version_id: 'branch', branch_id: 'branch', place_id: 'place',
  population_size: population, current_tick: 2, state_sha256: 'a'.repeat(64), input_seq: 2, input_sha256: 'b'.repeat(64),
  state: { profile, society_id: 'society', branch_id: 'branch', tick: 2, input_seq: 2, input_sha256: 'b'.repeat(64),
    inhabitants: Array.from({ length: population }, (_, i) => inhabitant(i, i === 0 ? goal : null)) },
});

describe('the society engine table', () => {
  it('is the backend file byte for byte, and every engine it states is readable here', () => {
    expect(SOCIETY_ENGINES_V3_JSON).toBe(readFileSync(TABLE, 'utf8'));
    const names = (JSON.parse(readFileSync(TABLE, 'utf8')) as { engines: { engine: string }[] }).engines.map((row) => row.engine);
    expect(SOCIETY_ENGINES.map((engine) => engine.engine)).toEqual(names);
    expect(names).toContain(DEFAULT_SOCIETY_ENGINE);
    expect(displayNamesEveryEngine).toBe(true);
  });

  it('reads the engine a saved world holding things takes, and the second table by the same reader', () => {
    const table = JSON.parse(readFileSync(TABLE, 'utf8')) as {
      creates_holding_things: { engine: string; grounds: string[] };
    };
    const third = readEngineTable(readFileSync(TABLE, 'utf8'));
    expect(third.holdingThings).toEqual(table.creates_holding_things && {
      engine: table.creates_holding_things.engine, grounds: table.creates_holding_things.grounds });
    expect(societyEngine(third.holdingThings?.engine).stateFamily).toBe('things');
    // A world published under the second table reads as it did: the same engines and grounds, and
    // no engine for a world holding things.
    const second = readEngineTable(readFileSync(SECOND, 'utf8'));
    expect(second.holdingThings).toBeNull();
    expect(second.creates).toEqual(third.creates);
    expect(second.engines).toEqual(third.engines);
  });

  it('reads which engine each ground is created with, and which engines an owner chooses models in', () => {
    const table = JSON.parse(readFileSync(TABLE, 'utf8')) as {
      creates: Record<string, { engine: string }>;
      engines: { engine: string; creatable: boolean; owner_model_choice: boolean }[];
    };
    expect(engineCreatedOver('saved_world')).toBe(table.creates['saved_world']!.engine);
    expect(engineCreatedOver('district')).toBe(table.creates['district']!.engine);
    const saved = societyEngine(engineCreatedOver('saved_world'));
    expect(saved.creatable && saved.savedWorld).toBe(true);
    // A town, a saved world whose records state its homes, gets the engine the table names for it.
    expect(engineCreatedOver('town')).toBe(table.creates['town']!.engine);
    const town = societyEngine(engineCreatedOver('town'));
    expect(town.creatable && town.savedWorld && town.stateFamily === 'living').toBe(true);
    expect(SOCIETY_ENGINES.map((engine) => [engine.engine, engine.creatable, engine.ownerModelChoice])).toEqual(
      table.engines.map((row) => [row.engine, row.creatable, row.owner_model_choice]));
  });

  it('refuses an engine it does not state, by name', () => {
    expect(() => societyEngine('exulanica-society/v9')).toThrow('Unknown society engine "exulanica-society/v9"');
    expect(() => parseSociety(purposeful('exulanica-society/v9', 8))).toThrow('exulanica-society/v9');
  });

  it('reads a v3 society with the purposeful reader, which it could not before', () => {
    const snapshot = parseSociety(purposeful('exulanica-society/v3', 8));
    expect(snapshot.populationSize).toBe(8);
    expect(snapshot.state.inhabitants).toHaveLength(8);
  });

  it('holds each engine to its own population bounds', () => {
    // A saved world's purposeful society may hold eight; the legacy engine may not.
    expect(parseSociety(purposeful('exulanica-society/v2', 8)).populationSize).toBe(8);
    const legacy = societyEngine('exulanica-society/v1');
    expect([legacy.populationMinimum, legacy.populationMaximum]).toEqual([100, 512]);
    expect(() => parseSociety(purposeful('exulanica-society/v2', 513))).toThrow('Invalid society response');
  });

  it('reads a walk that makes room at a busy destination, which names no target', () => {
    const making = { kind: 'make_room', target_id: null, reason: 'making_room' };
    expect(parseSociety(purposeful('exulanica-society/v2', 8, making)).state.inhabitants[0]?.goal).toEqual(making);
    expect(() => parseSociety(purposeful('exulanica-society/v2', 8, { ...making, target_id: 't' })))
      .toThrow('Invalid society goal');
  });
});

describe('a society of things', () => {
  const things = (inhabitants: number, population: number) => {
    const row = purposeful('exulanica-society/v7', inhabitants);
    return { ...row, population_size: population };
  };

  it('is read with the purposeful reader, its people as many as come and go within its bound', () => {
    expect(societyEngine('exulanica-society/v7').stateFamily).toBe('things');
    // Begun with six of its ground's people, it holds eight once a placed being and a visitor came.
    expect(parseSociety(things(8, 6)).state.inhabitants).toHaveLength(8);
    expect(parseSociety(things(4, 6)).state.inhabitants).toHaveLength(4);
    expect(() => parseSociety(things(513, 6))).toThrow('Invalid society response');
    // Any other engine still holds exactly its population.
    expect(() => parseSociety({ ...purposeful('exulanica-society/v2', 8), population_size: 6 })).toThrow('Invalid society response');
  });
});
