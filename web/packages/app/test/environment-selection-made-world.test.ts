// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import type { AtlasScene } from '@exulanica/atlas-core';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import type { AlternateVersion } from '../src/world-objects-api.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import { parseSociety, type SocietySnapshot } from '../src/society-api.js';
import { parseSocietyControl } from '../src/society-control-api.js';
import { parseSocietyModels } from '../src/society-models-api.js';
import { engineCreatedOver } from '../src/society-engines.js';

/*
 * A world made from photographs holds inhabitants too. Its entry names the floor every region
 * has, and no authored scene; its people live in one region: the one their society was brought
 * into, else the one the world opens in, the page's own pick. The crowd is hung from that
 * region's island, and People nearby and who decides for them are the saved world's own.
 */

const WORLD = 'world:personal:made';
const version = {
  schemaVersion: 2, versionId: 'version', worldId: WORLD, sourceSnapshotId: 'snapshot', parentVersionId: null,
  title: 'From my photographs', origin: 'authored', styleVersionId: 'style', stateSha256: '1'.repeat(64), editSeq: 0,
  sourceInvalidated: false, createdBy: 'actor', createdAt: '2026-09-27T00:00:00Z',
  objects: [], elementOverrides: [], environmentInstances: [], edits: [],
} as unknown as AlternateVersion;

const society = (regionId: string): SocietySnapshot => parseSociety({
  society_id: 'society', version_id: 'version', branch_id: 'version', place_id: 'derived-place', region_id: regionId,
  population_size: 8, current_tick: 0, state_sha256: '0'.repeat(64), input_seq: 1, input_sha256: 'b'.repeat(64),
  state: { profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'version', tick: 0, input_seq: 1,
    input_sha256: 'b'.repeat(64), inhabitants: Array.from({ length: 8 }, (_, i) => ({
      id: `person-${i}`, synthetic: true, position_mm: [2000 * i, 4000], display_name: `Person ${i}`, role: 'steward',
      goal: null, route: null, motion_path_mm: [[2000 * i, 4000]],
      action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
      explanation: { summary: `Person ${i} (simulated) waits.`, event_ids: [] } })) },
});
const control = () => parseSocietyControl({
  profile: 'exulanica.society-control/v1', society_id: 'society', branch_id: 'version', persisted: false,
  revision: 0, mode: 'paused', speed: 1, base_tick_interval_ms: 1000, tick_interval_ms: 1000,
  interval_semantics: 'minimum_wait_after_batch_completion', last_batch_execution: null,
  simulated_seconds_per_tick: 60, max_catchup_ticks: 3, next_due_at: null, reason: null,
  lease_expires_at: null, last_event_seq: 0, current_tick: 0, state_sha256: '0'.repeat(64),
  play_ineligible_reason: null, play_eligible: true,
}, 'version');
const models = () => parseSocietyModels({
  profile: 'exulanica.society-models/v1', society_id: 'society', engine: 'exulanica-society/v2',
  takes_model_choices: true, host_refusal: null,
  contract: { versions: {}, sha256: 'c'.repeat(64), model_people_maximum: 8 },
  models: [], choices: [], latest: [], by_model: [], decisions_read: { counted: 0, maximum: 2000 },
});

function mount(options: { readonly stored: string | null; readonly livesIn: string }) {
  const missing = () => new ApiError(404, 'unknown_reference', 'no such society');
  let held: SocietySnapshot | null = options.stored === null ? null : society(options.stored);
  // One root per drawn region; neither region holds a point map, as in a world of photographs.
  const regionRoots = new Map(['region-a', 'region-b'].map((id) => [id, { name: `island:${id}` }] as const));
  const crowd = {
    // The crowd already hung from the region it lives in, as `hostRegionSociety` finds it.
    root: { parent: regionRoots.get(options.livesIn)! },
    setSociety: vi.fn(() => 8), clearSociety: vi.fn(), revealInhabitant: vi.fn(),
    visibleInhabitantIds: ['person-0'], inhabitantRepresentation: vi.fn(() => null),
    inhabitantDetail: vi.fn(() => 'near'), coincidentInhabitants: vi.fn(() => ['person-0']),
    societyCounts: { population: 8, outdoors: 8, indoors: 0, near: 1, far: 0, drawn: 1 },
    drawnInhabitantCount: 1, pickInhabitant: vi.fn(() => 'person-0'), inhabitantSeatAtPlace: vi.fn(() => false),
    setSeatingLayout: vi.fn(), seatingMisses: [],
  };
  const controls = { state: { x: 0, y: 1.68, z: 4 }, onInteract: vi.fn() as (() => void) | null, forward: () => ({ x: 0, y: 0, z: -1 }) };
  const binding = {
    controls, camera: { forward: { x: 0, y: 0, z: -1 } }, invalidate: vi.fn(), device: {}, islands: [], regionRoots,
    ownedDistrict: null, generatedTile: null, authoredSociety: crowd,
    memoryLayerVisible: false, onMemoryLayerChange: null,
  };
  const societyClient = {
    read: vi.fn(async () => { if (held === null) throw missing(); return held; }),
    create: vi.fn(async (_version: string, _place: string | null, regionId: string) => { held = society(regionId); return held; }),
    connect: vi.fn(), advance: vi.fn(), events: vi.fn(async () => []),
  };
  const controlClient = { read: vi.fn(async () => { if (held === null) throw missing(); return control(); }), configure: vi.fn(), step: vi.fn() };
  const worldClient = { connect: vi.fn(async () => ({ assets: [], version })), assets: vi.fn(() => []) };
  const modelsClient = { read: vi.fn(async () => models()), choose: vi.fn(async () => undefined) };
  const canvas = document.createElement('canvas');
  const mounted = mountEnvironmentSelection({
    env: { canvas, preview: false } as unknown as AppEnvironment,
    state: {
      atlas: { binding },
      // Two placements in region-b: the world opens there, the page's own pick.
      placementRegionIds: ['region-b', 'region-b', 'region-a'],
      activeWorldEntry: { worldId: WORLD, authoredVersionId: 'version', title: 'From my photographs',
        authoredScene: null, declaredFloor: { halfExtentMm: 12_000, elevationMm: 0 } },
    } as unknown as SessionState,
    scene: { islands: [{ islandId: 'region-a' }, { islandId: 'region-b' }] } as unknown as AtlasScene,
    credentials: { baseUrl: 'https://example.test', token: 'token' },
    showStatus: vi.fn(), admissionId: null,
    worldClient: worldClient as never, societyClient: societyClient as never, societyControlClient: controlClient as never,
    societyModelsClient: modelsClient as never,
  });
  document.body.append(mounted.root);
  const panel = () => mounted.root.querySelector<HTMLElement>('section.world-inhabitants')!;
  return { mounted, crowd, societyClient, modelsClient, panel };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('a world made from photographs holds inhabitants in one of its places', () => {
  it('brings them into the place the world opens in, with the saved world\'s engine and panels', async () => {
    const { mounted, crowd, societyClient, modelsClient, panel } = mount({ stored: null, livesIn: 'region-b' });
    await mounted.begin();
    expect(panel().dataset['state']).toBe('absent');
    [...panel().querySelectorAll('button')].find((b) => b.textContent === 'Bring in inhabitants')!.click();
    for (let i = 0; i < 6; i += 1) await settle();
    expect(societyClient.create).toHaveBeenCalledWith('version', null, 'region-b', engineCreatedOver('saved_world'));
    expect(crowd.setSociety).toHaveBeenCalled();
    expect(panel().dataset['state']).toBe('present');
    await vi.waitFor(() => expect(modelsClient.read).toHaveBeenCalledWith('version'));
    const who = mounted.root.querySelector<HTMLElement>('section.society-models');
    await vi.waitFor(() => expect(who!.hidden).toBe(false));
    mounted.dispose();
  });

  it('keeps people in the place their society lives in, whichever place the world opens in', async () => {
    const { mounted, crowd, societyClient, panel } = mount({ stored: 'region-a', livesIn: 'region-a' });
    await mounted.begin();
    for (let i = 0; i < 4; i += 1) await settle();
    expect(societyClient.create).not.toHaveBeenCalled();
    expect(panel().dataset['state']).toBe('present');
    expect(crowd.setSociety).toHaveBeenCalled();
    mounted.dispose();
  });

  it('says nobody can be shown where the place their society lives in is not drawn', async () => {
    // The binding holds a crowd somewhere else: the page never moves it to another island.
    const { mounted, societyClient, panel } = mount({ stored: 'region-a', livesIn: 'region-b' });
    await mounted.begin();
    for (let i = 0; i < 4; i += 1) await settle();
    expect(societyClient.create).not.toHaveBeenCalled();
    expect(panel().textContent).toContain('not drawn here');
    mounted.dispose();
  });
});
