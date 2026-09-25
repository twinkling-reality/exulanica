// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import type { AtlasScene } from '@exulanica/atlas-core';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import type { AlternateVersion } from '../src/world-objects-api.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import { parseSociety, type SocietySnapshot } from '../src/society-api.js';
import { parseSocietyControl } from '../src/society-control-api.js';

/*
 * The inspector over a person in a saved world who is talking with somebody, or standing a while:
 * its words name the other person from the state it shows, and its recorded details never call a
 * walk to stand or to talk "making room".
 */

const WORLD = 'world:authored:saved';
const version = {
  schemaVersion: 2, versionId: 'version', worldId: WORLD, sourceSnapshotId: 'snapshot', parentVersionId: null,
  title: 'My world', origin: 'authored', styleVersionId: 'style', stateSha256: '1'.repeat(64), editSeq: 0,
  sourceInvalidated: false, createdBy: 'actor', createdAt: '2026-09-25T00:00:00Z',
  objects: [], elementOverrides: [], environmentInstances: [], edits: [],
} as unknown as AlternateVersion;

const talking = (partner: string) => ({
  goal: { kind: 'talk', target_id: null, reason: 'stopped_to_talk', partner_id: partner, duration_ticks: 4 },
  action: { kind: 'talk', status: 'active', target_id: null, remaining_ticks: 2, reason: 'talking' },
});
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

async function inspect(held: SocietySnapshot) {
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
    worldClient: { connect: vi.fn(async () => ({ assets: [], version })) } as never,
    societyClient: { read: vi.fn(async () => held), create: vi.fn(), connect: vi.fn(), advance: vi.fn(),
      events: vi.fn(async () => []), requestAction: vi.fn() } as never,
    societyControlClient: { read: vi.fn(async () => control), configure: vi.fn(), step: vi.fn() } as never,
  });
  document.body.append(mounted.root);
  await mounted.begin();
  for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
  controls.onInteract?.();
  const inspector = mounted.root.querySelector<HTMLElement>('.living-world-inspector')!;
  const details = [...inspector.querySelectorAll('dt')].map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]);
  const activity = inspector.querySelector('.living-world-activity')?.textContent;
  mounted.dispose();
  return { activity, details };
}

describe('the inspector over a person talking or standing', () => {
  it('names the person they are talking with, from the state it shows', async () => {
    const { activity, details } = await inspect(society(talking('person-1'), talking('person-0')));
    expect(activity).toBe('Talking with Bo, 2 more simulated minutes. Because they met and stopped to talk.');
    expect(details).toContainEqual(['Goal / destination', 'talk: stopped_to_talk']);
  });

  it('never calls standing a while making room', async () => {
    const { activity, details } = await inspect(society(standing, standing));
    expect(activity).toBe('Standing a while, 3 more simulated minutes. Because they stopped to stand a while.');
    expect(details).toContainEqual(['Goal / destination', 'stand: stopping_a_while']);
    expect(details).not.toContainEqual(['Goal / destination', 'Making room at a busy place']);
  });
});
