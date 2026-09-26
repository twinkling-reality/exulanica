// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import type { AtlasScene } from '@exulanica/atlas-core';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import type { AlternateVersion } from '../src/world-objects-api.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import { parseSociety, type SocietySnapshot } from '../src/society-api.js';
import { parseSocietyControl } from '../src/society-control-api.js';

/*
 * A Companion citation opened in the inspector: the cited words show beside the person it names,
 * and only while that person stays selected. Selecting somebody else forgets them, so re-selecting
 * the first person shows their own words alone. Mounted as environment-selection-talk.test.ts
 * mounts a saved world.
 */

const WORLD = 'world:authored:saved';
const version = {
  schemaVersion: 2, versionId: 'version', worldId: WORLD, sourceSnapshotId: 'snapshot', parentVersionId: null,
  title: 'My world', origin: 'authored', styleVersionId: 'style', stateSha256: '1'.repeat(64), editSeq: 0,
  sourceInvalidated: false, createdBy: 'actor', createdAt: '2026-09-25T00:00:00Z',
  objects: [], elementOverrides: [], environmentInstances: [], edits: [],
} as unknown as AlternateVersion;

const standing = {
  goal: { kind: 'stand', target_id: null, reason: 'stopping_a_while' },
  action: { kind: 'stand', status: 'active', target_id: null, remaining_ticks: 3, reason: 'standing_a_while' },
};

const society = (first: Record<string, unknown>, second: Record<string, unknown>): SocietySnapshot => parseSociety({
  society_id: 'society', version_id: 'version', branch_id: 'version', place_id: 'derived-place',
  population_size: 2, current_tick: 5, state_sha256: '5'.repeat(64), input_seq: 1, input_sha256: 'b'.repeat(64),
  state: { profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'version', tick: 5, input_seq: 1,
    input_sha256: 'b'.repeat(64), inhabitants: [['person-0', 'Ada', first], ['person-1', 'Bo', second]].map(
      ([id, name, state]) => ({
        id, synthetic: true, position_mm: [2000, 4000], display_name: name, role: 'steward', route: null,
        motion_path_mm: [[2000, 4000]], explanation: { summary: `${name} (simulated).`, event_ids: [] },
        ...(state as Record<string, unknown>),
      })) },
  places: {
    input_seq: 1, input_sha256: 'b'.repeat(64), availability: 'available', unavailable_reason: null,
    walkable_area: { source: 'declared', centre_mm: [0, 0], half_width_mm: 12000, half_depth_mm: 12000 },
    clearance_mm: 450, targets: [], unavailable_affordances: [],
  },
});

const control = parseSocietyControl({
  profile: 'exulanica.society-control/v1', society_id: 'society', branch_id: 'version', persisted: false,
  revision: 0, mode: 'paused', speed: 1, base_tick_interval_ms: 1000, tick_interval_ms: 1000,
  interval_semantics: 'minimum_wait_after_batch_completion', last_batch_execution: null,
  simulated_seconds_per_tick: 60, max_catchup_ticks: 3, next_due_at: null, reason: null,
  lease_expires_at: null, last_event_seq: 0, current_tick: 5, state_sha256: '5'.repeat(64),
  play_ineligible_reason: null, play_eligible: true,
}, 'version');

async function mount(held: SocietySnapshot) {
  const crowd = {
    setSociety: vi.fn(() => 2), clearSociety: vi.fn(), revealInhabitant: vi.fn(),
    visibleInhabitantIds: ['person-0', 'person-1'], inhabitantRepresentation: vi.fn(() => null),
    inhabitantDetail: vi.fn(() => 'near'), coincidentInhabitants: vi.fn(() => ['person-0']),
    societyCounts: { population: 2, outdoors: 2, indoors: 0, near: 2, far: 0, drawn: 2 },
    drawnInhabitantCount: 2, pickInhabitant: vi.fn(() => 'person-0'), inhabitantSeatAtPlace: vi.fn(() => false),
    setSeatingLayout: vi.fn(), seatingMisses: [],
  };
  const controls = { state: { x: 0, y: 1.68, z: 4 }, onInteract: vi.fn() as (() => void) | null, forward: () => ({ x: 0, y: 0, z: -1 }) };
  const binding = {
    controls, camera: { forward: { x: 0, y: 0, z: -1 } }, invalidate: vi.fn(),
    ownedDistrict: null, generatedTile: null, authoredSociety: crowd,
    memoryLayerVisible: false, onMemoryLayerChange: null,
  };
  const mounted = mountEnvironmentSelection({
    env: { canvas: document.createElement('canvas'), preview: false } as unknown as AppEnvironment,
    state: {
      atlas: { binding },
      activeWorldEntry: { worldId: WORLD, authoredVersionId: 'version', title: 'My world',
        authoredScene: { region: { regionId: 'region:starter' } } },
    } as unknown as SessionState,
    scene: { islands: [] } as unknown as AtlasScene,
    credentials: { baseUrl: 'https://example.test', token: 'token' },
    showStatus: vi.fn(), admissionId: null,
    worldClient: { connect: vi.fn(async () => ({ assets: [], version })), assets: vi.fn(() => []) } as never,
    societyClient: { read: vi.fn(async () => held), create: vi.fn(), connect: vi.fn(), advance: vi.fn(),
      events: vi.fn(async () => []), requestAction: vi.fn() } as never,
    societyControlClient: { read: vi.fn(async () => control), configure: vi.fn(), step: vi.fn() } as never,
  });
  document.body.append(mounted.root);
  await mounted.begin();
  for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
  const activity = () => mounted.root.querySelector('.living-world-inspector .living-world-activity')?.textContent ?? '';
  const picker = mounted.root.querySelector<HTMLSelectElement>('select[aria-label="Inspect nearby inhabitant"]')!;
  const pick = (id: string) => {
    picker.value = id;
    picker.dispatchEvent(new Event('change'));
  };
  return { mounted, activity, pick };
}

const cited = {
  token: 'EVENTAAAA1', resultKind: 'simulation_event' as const, versionId: 'version', inhabitantId: 'person-0',
  eventId: 'event-1', tick: 3, line: 'Simulated minute 3: [inhabitant A] began what they came to do, because they have arrived.',
};
const references = { inhabitants: { '[inhabitant A]': { versionId: 'version', inhabitantId: 'person-0' } } };

describe('a Companion citation opened in the inspector', () => {
  it('shows the cited words beside the person it names, drawn from the society shown', async () => {
    const { mounted, activity } = await mount(society(standing, standing));
    mounted.showSimulation(cited, references);
    expect(activity()).toContain('From the simulation: Simulated minute 3: Ada began what they came to do');
    mounted.dispose();
  });

  it('forgets them once somebody else is selected, so the same person shows only their own words', async () => {
    const { mounted, activity, pick } = await mount(society(standing, standing));
    mounted.showSimulation(cited, references);
    pick('person-1');
    pick('person-0');
    expect(activity()).toBe('Standing a while, 3 more simulated minutes. Because they stopped to stand a while.');
    mounted.dispose();
  });
});
