// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AtlasScene } from '@exulanica/atlas-core';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import type { AlternateVersion } from '../src/world-objects-api.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import { parseSociety, type SocietyEvent, type SocietySnapshot } from '../src/society-api.js';
import { parseSocietyControl } from '../src/society-control-api.js';

/*
 * Watching a person's own world live: the page reads the playback control about every two seconds,
 * reads the society only when the tick moved, and hands each new minute to the crowd with the
 * host's pace and how late the page learns of it. The server is a set of test transports holding
 * the state a playing host would produce.
 */

const WORLD = 'world:authored:watched';
const object = (objectId: string, title: string, xMm: number, zMm: number) => ({
  objectId,
  asset: { assetKey: `cc0.${objectId}`, title, summary: '', mediaType: 'model/gltf-binary',
    contentSha256: 'c'.repeat(64), byteSize: 1, licenceId: 'CC0-1.0', licenceSha256: 'd'.repeat(64), availability: 'available' },
  regionId: 'region:starter',
  transform: { coordinateSpace: 'region_local', coordinateUnit: 'millimetre', xMm, yMm: 0, zMm, yawMicroradians: 0, scaleMilli: 1000 },
  origin: { kind: 'authored', role: 'fictional' }, behaviour: null, removed: false,
});
const versionWith = (objects: readonly ReturnType<typeof object>[]) => ({
  schemaVersion: 2, versionId: 'version', worldId: WORLD, sourceSnapshotId: 'snapshot', parentVersionId: null,
  title: 'My world', origin: 'authored', styleVersionId: 'style', stateSha256: '1'.repeat(64), editSeq: objects.length,
  sourceInvalidated: false, createdBy: 'actor', createdAt: '2026-09-24T00:00:00Z',
  objects, elementOverrides: [], environmentInstances: [], edits: [],
} as unknown as AlternateVersion);

/** Ada walks east one metre a minute; the input a state consumed is `inputSeq`. */
const society = (tick: number, inputSeq = 1): SocietySnapshot => parseSociety({
  society_id: 'society', version_id: 'version', branch_id: 'version', place_id: 'derived-place',
  population_size: 1, current_tick: tick, state_sha256: String(tick % 10).repeat(64), input_seq: inputSeq,
  input_sha256: 'b'.repeat(64),
  state: { profile: 'exulanica-society/v2', society_id: 'society', branch_id: 'version', tick, input_seq: inputSeq,
    input_sha256: 'b'.repeat(64), movement_budget_mm_per_tick: 60_000, inhabitants: [{
      id: 'ada', synthetic: true, position_mm: [tick * 1000, 0], display_name: 'Ada', role: 'steward',
      goal: null, route: null, motion_path_mm: tick ? [[(tick - 1) * 1000, 0], [tick * 1000, 0]] : [[0, 0]],
      action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
      explanation: { summary: 'Ada (simulated) waits.', event_ids: [] } }] },
  places: {
    input_seq: inputSeq, input_sha256: 'b'.repeat(64), availability: 'available', unavailable_reason: null,
    walkable_area: null, clearance_mm: 450, targets: [], unavailable_affordances: [],
  },
});
/** The event a walking minute records: the path Ada walked in it. */
const walked = (tick: number): SocietyEvent => ({
  event_id: `event-${tick}`, subject_id: 'ada', tick, event_kind: 'route_progressed', document_sha256: 'e'.repeat(64),
  document: { synthetic: true, summary: 'Ada (simulated): moved.', order: 0,
    motion_path_mm: [[(tick - 1) * 1000, 0], [tick * 1000, 0]] },
});
const HOST_INTERVAL_MS = 4_000;
const control = (tick: number, mode: 'playing' | 'paused', host: unknown) => parseSocietyControl({
  profile: 'exulanica.society-control/v1', society_id: 'society', branch_id: 'version', persisted: true,
  revision: mode === 'playing' ? 1 : 2, mode, speed: 2, base_tick_interval_ms: 8000, tick_interval_ms: HOST_INTERVAL_MS,
  interval_semantics: 'minimum_wait_after_batch_completion', last_batch_execution: null,
  simulated_seconds_per_tick: 60, max_catchup_ticks: 3, next_due_at: null, reason: null,
  lease_expires_at: null, last_event_seq: 0, current_tick: tick, state_sha256: String(tick % 10).repeat(64),
  play_ineligible_reason: null, play_eligible: true, host_playback: host,
}, 'version');
const RUNNING = { running: true, interval_ms: HOST_INTERVAL_MS, reason: null };

function mount(options: { mode: 'playing' | 'paused'; host: unknown }) {
  const server = { tick: 5, inputSeq: 1, mode: options.mode, events: [] as SocietyEvent[] };
  let version = versionWith([object('plate', 'Marker plate', 3000, 5000)]);
  const crowd = {
    setSociety: vi.fn((_state: unknown, _observer: unknown, _timing?: unknown) => 1), clearSociety: vi.fn(),
    revealInhabitant: vi.fn(), visibleInhabitantIds: ['ada'], inhabitantRepresentation: vi.fn(() => null),
    inhabitantDetail: vi.fn(() => 'near'), coincidentInhabitants: vi.fn(() => ['ada']),
    societyCounts: { population: 1, outdoors: 1, indoors: 0, near: 1, far: 0, drawn: 1 },
    drawnInhabitantCount: 1, pickInhabitant: vi.fn(() => 'ada'),
    societyJumps: [] as readonly unknown[],
  };
  const controls = { state: { x: 0, y: 1.68, z: 4 }, onInteract: null, forward: () => ({ x: 0, y: 0, z: -1 }) };
  const binding = {
    controls, camera: { forward: { x: 0, y: 0, z: -1 } }, invalidate: vi.fn(),
    ownedDistrict: null, generatedTile: null, authoredSociety: crowd, memoryLayerVisible: false, onMemoryLayerChange: null,
  };
  const societyClient = {
    read: vi.fn(async () => society(server.tick, server.inputSeq)),
    events: vi.fn(async () => server.events),
    create: vi.fn(), connect: vi.fn(), advance: vi.fn(), requestAction: vi.fn(),
  };
  const controlClient = {
    read: vi.fn(async () => control(server.tick, server.mode, options.host)),
    configure: vi.fn(async (_control: unknown, mode: 'playing' | 'paused') => {
      server.mode = mode;
      return control(server.tick, mode, options.host);
    }),
    step: vi.fn(),
  };
  const worldClient = { connect: vi.fn(async () => ({ assets: [], version })) };
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
    worldClient: worldClient as never, societyClient: societyClient as never, societyControlClient: controlClient as never,
  });
  document.body.append(mounted.root);
  const panel = () => mounted.root.querySelector<HTMLElement>('section.world-inhabitants')!;
  const line = (selector: string) => {
    const node = panel().querySelector<HTMLElement>(selector)!;
    return node.hidden ? null : node.textContent;
  };
  const drawnTicks = () => crowd.setSociety.mock.calls.map(([state]) => (state as { tick: number }).tick);
  const place = (objects: readonly ReturnType<typeof object>[]) => { version = versionWith(objects); };
  return { mounted, server, crowd, societyClient, controlClient, panel, line, drawnTicks, place };
}

beforeEach(() => { vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] }); });
afterEach(() => { vi.useRealTimers(); document.body.replaceChildren(); });

describe('watching a saved world live', () => {
  it('reads the control about every two seconds and the society only when the tick moved', async () => {
    const { mounted, server, societyClient, controlClient, drawnTicks } = mount({ mode: 'playing', host: RUNNING });
    await mounted.begin();
    const controlReads = controlClient.read.mock.calls.length;
    const societyReads = societyClient.read.mock.calls.length;
    expect(drawnTicks()).toEqual([5]);
    // Half the host's 4 s interval, and no slower than two seconds: nothing changed, one cheap read.
    await vi.advanceTimersByTimeAsync(1_999);
    expect(controlClient.read.mock.calls.length).toBe(controlReads);
    await vi.advanceTimersByTimeAsync(1);
    expect(controlClient.read.mock.calls.length).toBe(controlReads + 1);
    expect(societyClient.read.mock.calls.length).toBe(societyReads);
    server.tick = 6;
    await vi.advanceTimersByTimeAsync(2_000);
    expect(societyClient.read.mock.calls.length).toBe(societyReads + 1);
    expect(drawnTicks()).toEqual([5, 6]);
    mounted.dispose();
  });

  it('hands the crowd the host pace and how late the page learns of each minute', async () => {
    const { mounted, server, crowd } = mount({ mode: 'playing', host: RUNNING });
    await mounted.begin();
    server.tick = 6;
    await vi.advanceTimersByTimeAsync(2_000);
    const timing = crowd.setSociety.mock.calls.at(-1)![2] as { intervalMs: number; startLagMs: number };
    expect(timing.intervalMs).toBe(HOST_INTERVAL_MS);
    // The poll period plus the reads it took, measured by the page (no time passes in these transports).
    expect(timing.startLagMs).toBe(2_000);
    mounted.dispose();
  });

  it('walks minutes it never read along the paths their events record, oldest first', async () => {
    const { mounted, server, drawnTicks, crowd } = mount({ mode: 'playing', host: RUNNING });
    await mounted.begin();
    server.tick = 8;
    server.events = [walked(8), walked(7), walked(6)];
    await vi.advanceTimersByTimeAsync(2_000);
    expect(drawnTicks()).toEqual([5, 6, 7, 8]);
    const paths = crowd.setSociety.mock.calls.slice(1).map(([state]) =>
      (state as { inhabitants: { motion_path_mm: unknown }[] }).inhabitants[0]!.motion_path_mm);
    expect(paths).toEqual([[[5000, 0], [6000, 0]], [[6000, 0], [7000, 0]], [[7000, 0], [8000, 0]]]);
    mounted.dispose();
  });

  it('says so when the crowd moves someone without walking', async () => {
    const { mounted, server, crowd, line } = mount({ mode: 'playing', host: RUNNING });
    await mounted.begin();
    expect(line('.world-inhabitants-moved')).toBeNull();
    crowd.societyJumps = [{ inhabitantId: 'ada', reason: 'minutes-not-read', tick: 9, unreadTicks: 3, metres: 3 }];
    server.tick = 9;
    await vi.advanceTimersByTimeAsync(2_000);
    expect(line('.world-inhabitants-moved')).toBe(
      'Someone moved without walking: this page missed 3 simulated minutes, so they are shown where they are now.');
    mounted.dispose();
  });

  it('puts Play and Pause beside the people and leaves About a pointer, not a second control', async () => {
    const { mounted, panel, controlClient, server } = mount({ mode: 'playing', host: RUNNING });
    await mounted.begin();
    const play = [...panel().querySelectorAll('button')].find((button) => !button.hidden && button.textContent === 'Pause')!;
    expect(play).toBeDefined();
    expect([...panel().querySelectorAll('button')].find((button) => button.textContent === 'Advance one minute')!.hidden).toBe(true);
    const about = [...mounted.root.querySelectorAll('details')].find((node) => node.querySelector('summary')?.textContent === 'Living world simulation')!;
    expect(about.textContent).toContain('Play, pause and pace are in People nearby');
    expect([...about.querySelectorAll('button')].map((button) => button.textContent)).toEqual(['Refresh persisted society']);
    play.click();
    await vi.advanceTimersByTimeAsync(0);
    expect(controlClient.configure).toHaveBeenCalledWith(expect.anything(), 'paused', 2);
    expect(server.mode).toBe('paused');
    // Paused, nothing is read on its own any more.
    const reads = controlClient.read.mock.calls.length;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(controlClient.read.mock.calls.length).toBe(reads);
    mounted.dispose();
  });

  it('never polls a world its host does not play, and says why in the server\'s words', async () => {
    const reason = 'This host does not play this workspace.';
    const { mounted, controlClient, panel } = mount({ mode: 'playing', host: { running: false, interval_ms: HOST_INTERVAL_MS, reason } });
    await mounted.begin();
    const reads = controlClient.read.mock.calls.length;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(controlClient.read.mock.calls.length).toBe(reads);
    expect(panel().textContent).toContain(`${reason} Advance one minute at a time instead.`);
    mounted.dispose();
  });

  it('says when people will notice an object placed while they are here, from the server\'s tick and input', async () => {
    const { mounted, server, place, line } = mount({ mode: 'playing', host: RUNNING });
    await mounted.begin();
    place([object('plate', 'Marker plate', 3000, 5000), object('bench', 'Bench', 1000, 2000)]);
    await mounted.afterAuthoredEdit('version');
    expect(line('.world-inhabitants-notice')).toBe('They notice Bench at simulated minute 6, the next one.');
    // The next minute consumes the input the edit queued.
    server.tick = 6;
    server.inputSeq = 2;
    await vi.advanceTimersByTimeAsync(2_000);
    expect(line('.world-inhabitants-notice')).toBe('They noticed Bench at simulated minute 6.');
    mounted.dispose();
  });
});
