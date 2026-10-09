// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import type { AtlasScene } from '@exulanica/atlas-core';
import type { PlacedThingRecord, ThingLayerOptions, ThingPick } from '@exulanica/atlas-react/things';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import { THING_LOOK_CHOSEN_EVENT } from '../src/composition/things.js';
import { parseSociety, type SocietySnapshot } from '../src/society-api.js';
import { parseSocietyControl } from '../src/society-control-api.js';
import type { AlternateVersion } from '../src/world-objects-api.js';
import type { ThingLookChoice } from '../src/thing-looks-api.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';

/*
 * The looks chosen for a society of things' things are read when the society is first drawn: a
 * person wears theirs in the crowd, which is asked again, and a placed thing in the layer. A read
 * that fails says so on the canvas and dresses nothing.
 */

const { FakeLayer, layers } = vi.hoisted(() => {
  const made: InstanceType<typeof Fake>[] = [];
  class Fake {
    placed: readonly PlacedThingRecord[] = [];
    /** How far along the ray the fake's thing stands, metres. */
    distance = 3;
    /** The maker the crowd's figures read the library's looks from. */
    readonly maker = { library: { list: { kinds: [], looks: [] }, heldLook: async (sha256: string) => ({ key: 'workspace-look', version: 4, sha256 }) } };
    society: unknown = null;
    constructor(readonly options: ThingLayerOptions) { made.push(this); }
    setSociety(state: unknown) { this.society = state; }
    readonly looks: [string, unknown][] = [];
    async setLook(placedId: string, look: unknown) { this.looks.push([placedId, look]); }
    async setPlaced(things: readonly PlacedThingRecord[]) { this.placed = things; }
    pick() { return this.placed.length === 0 ? null : { pick: { placedId: this.placed[0]!.thingId, thingId: null, subjectId: null }, distance: this.distance }; }
    setPicked(_pick: ThingPick | null) {}
    get drawn() { return this.placed.map((one) => ({ placedId: one.thingId, lookKind: 'static', look: 'primitive-well/v1' })); }
    get misses() { return []; }
    destroy() {}
  }
  return { FakeLayer: Fake, layers: made };
});
vi.mock('@exulanica/atlas-react/things', async (original) => ({
  ...(await original<typeof import('@exulanica/atlas-react/things')>()),
  ThingLayer: FakeLayer,
}));
vi.mock('../src/things-library.js', () => ({ openThingLibrary: vi.fn(async () => ({ library: true })) }));

const WORLD = 'world:authored:saved';
const KIND = { kind: 'well', version: 1, sha256: 'a'.repeat(64) };
const version = {
  schemaVersion: 5, versionId: 'version', worldId: WORLD, sourceSnapshotId: 'snapshot', parentVersionId: null,
  title: 'My world', origin: 'authored', styleVersionId: 'style', stateSha256: '1'.repeat(64), editSeq: 2,
  sourceInvalidated: false, createdBy: 'actor', createdAt: '2026-10-06T00:00:00Z',
  objects: [], elementOverrides: [], environmentInstances: [], edits: [],
  things: [{
    thingId: 'well-1', kind: KIND, regionId: 'region:starter',
    transform: { coordinateSpace: 'region_local', coordinateUnit: 'millimetre', xMm: 0, yMm: 0, zMm: -3000, yawMicroradians: 0, scaleMilli: 1000 },
    origin: { kind: 'authored', role: 'fictional' }, removed: false,
  }],
} as unknown as AlternateVersion;

/** A society of things holding the placed well, with one person: what a v7 read answers. */
const thingsSociety = (): SocietySnapshot => parseSociety({
  society_id: 'society', version_id: 'version', branch_id: 'version', place_id: 'derived-place',
  population_size: 1, current_tick: 3, state_sha256: '3'.repeat(64), input_seq: 1, input_sha256: 'b'.repeat(64),
  state: { profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'version', tick: 3, input_seq: 1,
    input_sha256: 'b'.repeat(64),
    inhabitants: [{
      id: 'person-0', synthetic: true, position_mm: [2000, 4000], display_name: 'Knight', role: 'steward',
      goal: null, route: null, motion_path_mm: [[2000, 4000]],
      action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
      explanation: { summary: 'The knight (simulated) waits.', event_ids: [] },
      kind: KIND, came_by: 'placed', placed_id: 'knight-1',
    }],
    things: [{ id: 't-well', placed_id: 'well-1', kind: KIND, position_mm: [0, -3000], yaw_microradians: 0, held_by: null }] },
  places: {
    input_seq: 1, input_sha256: 'b'.repeat(64), availability: 'available', unavailable_reason: null,
    walkable_area: { source: 'declared', centre_mm: [0, 0], half_width_mm: 12000, half_depth_mm: 12000 },
    clearance_mm: 450, targets: [], unavailable_affordances: [],
  },
});

function mount(withSociety: boolean, looksClient: { read: (versionId: string) => Promise<ReadonlyMap<string, ThingLookChoice>> }, society: () => SocietySnapshot = thingsSociety) {
  const missing = () => new ApiError(404, 'unknown_reference', 'no such society');
  const regionEntity = { name: 'authored-region:region:starter' };
  const crowd = {
    root: { parent: regionEntity },
    setSociety: vi.fn(() => 0), clearSociety: vi.fn(), revealInhabitant: vi.fn(), setFigures: vi.fn(), societyJumps: [],
    visibleInhabitantIds: ['person-0'], inhabitantRepresentation: vi.fn(() => null),
    inhabitantDetail: vi.fn(() => 'near'), coincidentInhabitants: vi.fn(() => ['person-0']),
    societyCounts: { population: 1, outdoors: 1, indoors: 0, near: 1, far: 0, drawn: 1 },
    drawnInhabitantCount: 1, inhabitantSeatAtPlace: vi.fn(() => false), setSeatingLayout: vi.fn(), seatingMisses: [],
    // A person stands 5 m along the ray: picked only when nothing nearer stands in front.
    pickInhabitant: vi.fn((_o: unknown, _d: unknown, limit = Number.POSITIVE_INFINITY) => (limit > 5 ? 'person-0' : null)),
    refreshFigures: vi.fn(),
  };
  const controls = { state: { x: 0, y: 1.68, z: 4 }, onInteract: vi.fn() as (() => void) | null, forward: () => ({ x: 0, y: 0, z: -1 }) };
  const binding = {
    app: { app: true }, camera: { forward: { x: 0, y: 0, z: -1 } }, controls, invalidate: vi.fn(),
    regionRoots: new Map(), ownedDistrict: null, generatedTile: null, authoredSociety: crowd,
    memoryLayerVisible: false, onMemoryLayerChange: null,
  };
  const societyClient = {
    read: vi.fn(async () => { if (!withSociety) throw missing(); return society(); }),
    create: vi.fn(), connect: vi.fn(), advance: vi.fn(), events: vi.fn(async () => []),
  };
  const control = () => parseSocietyControl({
    profile: 'exulanica.society-control/v1', society_id: 'society', branch_id: 'version', persisted: false,
    revision: 0, mode: 'paused', speed: 1, base_tick_interval_ms: 1000, tick_interval_ms: 1000,
    interval_semantics: 'minimum_wait_after_batch_completion', last_batch_execution: null,
    simulated_seconds_per_tick: 60, max_catchup_ticks: 3, next_due_at: null, reason: null,
    lease_expires_at: null, last_event_seq: 0, current_tick: 3, state_sha256: '3'.repeat(64),
    play_ineligible_reason: null, play_eligible: true,
  }, 'version');
  const controlClient = { read: vi.fn(async () => { if (!withSociety) throw missing(); return control(); }), configure: vi.fn(), step: vi.fn() };
  const worldClient = { connect: vi.fn(async () => ({ assets: [], version })), assets: vi.fn(() => []) };
  const modelsClient = { read: vi.fn(async () => { throw missing(); }), choose: vi.fn() };
  const canvas = document.createElement('canvas');
  const shell = document.createElement('div');
  const mounted = mountEnvironmentSelection({
    env: { canvas, shell, preview: false, systemReducedMotion: { matches: false } } as unknown as AppEnvironment,
    state: {
      atlas: { binding },
      activeWorldEntry: { worldId: WORLD, authoredVersionId: 'version', title: 'My world',
        authoredScene: { region: { regionId: 'region:starter' } } },
    } as unknown as SessionState,
    scene: { islands: [] } as unknown as AtlasScene,
    credentials: { baseUrl: 'https://example.test', token: 'token' },
    showStatus: vi.fn(), admissionId: null,
    worldClient: worldClient as never, societyClient: societyClient as never, societyControlClient: controlClient as never,
    societyModelsClient: modelsClient as never,
    thingLooksClient: looksClient,
  });
  document.body.append(mounted.root);
  return { mounted, crowd, controls, canvas, shell, regionEntity };
}

/** The society at a later minute, when a visitor has crossed in beside the knight. */
const withVisitor = (tick: number): SocietySnapshot => {
  const before = thingsSociety();
  const knight = before.state.inhabitants[0]!;
  return parseSociety({
    society_id: 'society', version_id: 'version', branch_id: 'version', place_id: 'derived-place',
    population_size: 2, current_tick: tick, state_sha256: String(tick).repeat(64), input_seq: 1, input_sha256: 'b'.repeat(64),
    state: { profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'version', tick, input_seq: 1,
      input_sha256: 'b'.repeat(64),
      inhabitants: [knight, { ...knight, id: 'visitor-1', display_name: 'Traveller', came_by: 'crossed', placed_id: null }],
      things: before.state.things },
    places: {
      input_seq: 1, input_sha256: 'b'.repeat(64), availability: 'available', unavailable_reason: null,
      walkable_area: { source: 'declared', centre_mm: [0, 0], half_width_mm: 12000, half_depth_mm: 12000 },
      clearance_mm: 450, targets: [], unavailable_affordances: [],
    },
  });
};

const LOOK = { key: 'stone-well', version: 1, sha256: 'd'.repeat(64) };
const MANNEQUIN = { key: 'kaykit-mannequin', version: 1, sha256: 'e'.repeat(64) };
const settle = async () => { for (let i = 0; i < 12; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); };

describe('the looks chosen for a society of things\' things', () => {
  it('reads them once the society is drawn, dresses the crowd and the layer, and asks the crowd again', async () => {
    const choices = new Map<string, ThingLookChoice>([
      ['person-0', { thingId: 'person-0', placedId: 'knight-1', look: MANNEQUIN, chosenBy: 'owner', chosenAt: '2026-10-09T14:00:00.000000Z' }],
      ['t-well', { thingId: 't-well', placedId: 'well-1', look: LOOK, chosenBy: 'owner', chosenAt: '2026-10-09T14:01:00.000000Z' }],
    ]);
    const looksClient = { read: vi.fn(async (_versionId: string) => choices as ReadonlyMap<string, ThingLookChoice>) };
    const { mounted, crowd, canvas } = mount(true, looksClient);
    await mounted.begin();
    await settle();
    expect(looksClient.read.mock.calls.map((call) => call[0])).toEqual(['version']);
    const layer = layers.at(-1)!;
    expect(layer.looks).toEqual([['knight-1', MANNEQUIN], ['well-1', LOOK]]);
    expect(crowd.refreshFigures).toHaveBeenCalledTimes(1);
    expect(canvas.dataset['thingLooksChosen']).toBe('2');
    // The crowd's figures dress the society's person in its chosen look.
    const figures = crowd.setFigures.mock.calls[0]![0] as { figureFor(person: unknown): { key: string } | null };
    const knight = thingsSociety().state.inhabitants[0]!;
    expect(figures.figureFor(knight)!.key).toContain(`|kaykit-mannequin/1/${'e'.repeat(64)}`);
    mounted.dispose();
  });

  it('reads them again each minute while the society is drawn, so a withdrawn look leaves and a choice made elsewhere arrives', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] });
    try {
      let choices = new Map<string, ThingLookChoice>([
        ['person-0', { thingId: 'person-0', placedId: 'knight-1', look: MANNEQUIN, chosenBy: 'owner', chosenAt: '2026-10-09T14:00:00.000000Z' }],
      ]);
      const looksClient = { read: vi.fn(async (_versionId: string) => choices as ReadonlyMap<string, ThingLookChoice>) };
      const { mounted, crowd, canvas } = mount(true, looksClient);
      await mounted.begin();
      await vi.advanceTimersByTimeAsync(10);
      expect(looksClient.read).toHaveBeenCalledTimes(1);
      const layer = layers.at(-1)!;
      expect(layer.looks).toEqual([['knight-1', MANNEQUIN]]);
      // No new minute is drawn: within the minute nothing is asked again.
      await vi.advanceTimersByTimeAsync(59_000);
      expect(looksClient.read).toHaveBeenCalledTimes(1);
      // Elsewhere the knight's look is withdrawn and the well is given one: the next minute's read carries both.
      choices = new Map([['t-well', { thingId: 't-well', placedId: 'well-1', look: LOOK, chosenBy: 'owner', chosenAt: '2026-10-09T14:05:00.000000Z' }]]);
      await vi.advanceTimersByTimeAsync(1_100);
      expect(looksClient.read).toHaveBeenCalledTimes(2);
      expect(layer.looks.slice(1)).toEqual([['well-1', LOOK], ['knight-1', null]]);
      expect(crowd.refreshFigures).toHaveBeenCalledTimes(2);
      expect(canvas.dataset['thingLooksChosen']).toBe('1');
      // The crowd's figures no longer name the withdrawn look: the knight wears its kind's first.
      const figures = crowd.setFigures.mock.calls[0]![0] as { figureFor(person: unknown): { key: string } | null };
      expect(figures.figureFor(thingsSociety().state.inhabitants[0]!)?.key ?? '').not.toContain('kaykit-mannequin');
      // Gone from the page: no read after it.
      mounted.dispose();
      await vi.advanceTimersByTimeAsync(120_000);
      expect(looksClient.read).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('reads them at once when a drawn minute brings in a visitor, so it arrives in the look its crossing chose', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] });
    try {
      let snapshot = thingsSociety();
      let choices = new Map<string, ThingLookChoice>();
      const looksClient = { read: vi.fn(async (_versionId: string) => choices as ReadonlyMap<string, ThingLookChoice>) };
      const { mounted, crowd } = mount(true, looksClient, () => snapshot);
      const refresh = async () => {
        [...mounted.root.querySelectorAll('button')].find((button) => button.textContent === 'Refresh persisted society')!.click();
        await vi.advanceTimersByTimeAsync(10);
      };
      await mounted.begin();
      await vi.advanceTimersByTimeAsync(10);
      expect(looksClient.read).toHaveBeenCalledTimes(1);
      // Five seconds on, the next minute brings in a visitor, whose crossing chose the mannequin.
      await vi.advanceTimersByTimeAsync(5_000);
      choices = new Map([['visitor-1', { thingId: 'visitor-1', placedId: null, look: MANNEQUIN, chosenBy: 'crossing', chosenAt: '2026-10-09T14:02:00.000000Z' }]]);
      snapshot = withVisitor(4);
      await refresh();
      expect(looksClient.read).toHaveBeenCalledTimes(2);
      const figures = crowd.setFigures.mock.calls[0]![0] as { figureFor(person: unknown): { key: string } | null };
      expect(figures.figureFor(snapshot.state.inhabitants[1]!)!.key).toContain(`|kaykit-mannequin/1/${'e'.repeat(64)}`);
      // The minute after holds the same visitor and nobody new: nothing more is read inside the minute.
      snapshot = withVisitor(5);
      await refresh();
      expect(looksClient.read).toHaveBeenCalledTimes(2);
      mounted.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it('asks again a minute after a failed read, and dresses the things then', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] });
    try {
      let failing = true;
      const choices = new Map<string, ThingLookChoice>([
        ['t-well', { thingId: 't-well', placedId: 'well-1', look: LOOK, chosenBy: 'owner', chosenAt: '2026-10-09T14:01:00.000000Z' }],
      ]);
      const looksClient = { read: vi.fn(async (_versionId: string): Promise<ReadonlyMap<string, ThingLookChoice>> => {
        if (failing) throw new Error('thing looks unavailable: HTTP 503');
        return choices;
      }) };
      const { mounted, canvas } = mount(true, looksClient);
      await mounted.begin();
      await vi.advanceTimersByTimeAsync(10);
      expect(canvas.dataset['thingLooksFailure']).toBe('thing looks unavailable: HTTP 503');
      failing = false;
      await vi.advanceTimersByTimeAsync(60_100);
      expect(looksClient.read).toHaveBeenCalledTimes(2);
      expect(layers.at(-1)!.looks).toEqual([['well-1', LOOK]]);
      mounted.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it('names a look its workspace keeps through the things\' own library', async () => {
    let named: unknown = null;
    const looksClient = { read: vi.fn(async (_versionId: string, resolve?: (sha256: string) => Promise<unknown>) => {
      named = await resolve!('e'.repeat(64));
      return new Map<string, ThingLookChoice>();
    }) };
    const { mounted } = mount(true, looksClient as never);
    await mounted.begin();
    await settle();
    expect(named).toEqual({ key: 'workspace-look', version: 4, sha256: 'e'.repeat(64) });
    mounted.dispose();
  });

  it('says on the canvas when the read fails, and dresses nothing', async () => {
    const looksClient = { read: vi.fn(async (_versionId: string): Promise<ReadonlyMap<string, ThingLookChoice>> => { throw new Error('thing looks unavailable: HTTP 503'); }) };
    const { mounted, crowd, canvas } = mount(true, looksClient);
    await mounted.begin();
    await settle();
    expect(canvas.dataset['thingLooksFailure']).toBe('thing looks unavailable: HTTP 503');
    expect(crowd.refreshFigures).not.toHaveBeenCalled();
    expect(layers.at(-1)!.looks).toEqual([]);
    mounted.dispose();
  });
});

/*
 * A look chosen on a thing's card is read at once: the card raises THING_LOOK_CHOSEN_EVENT on the
 * shell once the store has recorded the choice, and the page reads the choices outside the minute,
 * then draws what the read lists, not what the card sent.
 */
describe('a look chosen on a thing\'s card', () => {
  const BLOCKY = { key: 'blocky-traveller', version: 1, sha256: 'f'.repeat(64) };
  const knightIn = (look: typeof MANNEQUIN): ReadonlyMap<string, ThingLookChoice> => new Map([
    ['person-0', { thingId: 'person-0', placedId: 'knight-1', look, chosenBy: 'owner', chosenAt: '2026-10-09T14:00:00.000000Z' }],
  ]);
  const raise = (shell: HTMLElement, detail: unknown) => shell.dispatchEvent(new CustomEvent(THING_LOOK_CHOSEN_EVENT, { detail, bubbles: true }));

  it('is read at once, inside the minute, and the thing is drawn in the look the read lists', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] });
    try {
      let choices = knightIn(MANNEQUIN);
      const looksClient = { read: vi.fn(async (_versionId: string) => choices) };
      const { mounted, crowd, shell } = mount(true, looksClient);
      document.body.append(shell);
      await mounted.begin();
      await vi.advanceTimersByTimeAsync(10);
      expect(looksClient.read).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(5_000);
      // The owner gives the knight another look on its card; the store records it, the card says so.
      choices = knightIn(BLOCKY);
      raise(shell, { thingId: 'person-0' });
      await vi.advanceTimersByTimeAsync(10);
      expect(looksClient.read).toHaveBeenCalledTimes(2);
      expect(layers.at(-1)!.looks).toEqual([['knight-1', MANNEQUIN], ['knight-1', BLOCKY]]);
      expect(crowd.refreshFigures).toHaveBeenCalledTimes(2);
      const figures = crowd.setFigures.mock.calls[0]![0] as { figureFor(person: unknown): { key: string } | null };
      expect(figures.figureFor(thingsSociety().state.inhabitants[0]!)!.key).toContain(`|blocky-traveller/1/${'f'.repeat(64)}`);
      // The minute starts again from that read: nothing more within it, the next read a minute on.
      await vi.advanceTimersByTimeAsync(59_000);
      expect(looksClient.read).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(1_100);
      expect(looksClient.read).toHaveBeenCalledTimes(3);
      mounted.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it('chosen while a read is under way, is read once more after it, however many are chosen', async () => {
    const answers: ((choices: ReadonlyMap<string, ThingLookChoice>) => void)[] = [];
    const looksClient = { read: vi.fn((_versionId: string) => new Promise<ReadonlyMap<string, ThingLookChoice>>((resolve) => { answers.push(resolve); })) };
    const { mounted, shell } = mount(true, looksClient);
    document.body.append(shell);
    await mounted.begin();
    await settle();
    // The first read is under way when two looks are chosen on cards.
    expect(looksClient.read).toHaveBeenCalledTimes(1);
    raise(shell, { thingId: 'person-0' });
    raise(shell, { thingId: 't-well' });
    await settle();
    expect(looksClient.read).toHaveBeenCalledTimes(1);
    // It answers from before the choices: one more read starts after it, and only one.
    answers[0]!(knightIn(MANNEQUIN));
    await settle();
    expect(looksClient.read).toHaveBeenCalledTimes(2);
    answers[1]!(knightIn(BLOCKY));
    await settle();
    expect(looksClient.read).toHaveBeenCalledTimes(2);
    expect(layers.at(-1)!.looks).toEqual([['knight-1', MANNEQUIN], ['knight-1', BLOCKY]]);
    // With no read under way, a look chosen is read at once.
    raise(shell, { thingId: 'person-0' });
    await settle();
    expect(looksClient.read).toHaveBeenCalledTimes(3);
    answers[2]!(knightIn(BLOCKY));
    await settle();
    mounted.dispose();
  });

  it('reads nothing for an event naming no thing, where no society of things is drawn, or once the page is gone', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'performance'] });
    try {
      const looksClient = { read: vi.fn(async (_versionId: string) => knightIn(MANNEQUIN)) };
      const { mounted, shell } = mount(true, looksClient);
      document.body.append(shell);
      await mounted.begin();
      await vi.advanceTimersByTimeAsync(10);
      expect(looksClient.read).toHaveBeenCalledTimes(1);
      raise(shell, null);
      raise(shell, { thing: 'person-0' });
      raise(shell, { thingId: 7 });
      await vi.advanceTimersByTimeAsync(10);
      expect(looksClient.read).toHaveBeenCalledTimes(1);
      mounted.dispose();
      raise(shell, { thingId: 'person-0' });
      await vi.advanceTimersByTimeAsync(10);
      expect(looksClient.read).toHaveBeenCalledTimes(1);
      // A world whose version places a thing but runs no society of things: no looks are read.
      const bare = { read: vi.fn(async (_versionId: string): Promise<ReadonlyMap<string, ThingLookChoice>> => new Map()) };
      const other = mount(false, bare);
      document.body.append(other.shell);
      await other.mounted.begin();
      await vi.advanceTimersByTimeAsync(10);
      raise(other.shell, { thingId: 'person-0' });
      await vi.advanceTimersByTimeAsync(10);
      expect(bare.read).not.toHaveBeenCalled();
      other.mounted.dispose();
    } finally {
      vi.useRealTimers();
    }
  });
});
