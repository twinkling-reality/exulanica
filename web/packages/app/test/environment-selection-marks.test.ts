// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import type { AtlasScene } from '@exulanica/atlas-core';
import type { AttachedMarksOptions, MarkedSubject, PlacedThingRecord, ThingLayerOptions } from '@exulanica/atlas-react/things';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import { parseSociety, type SocietySnapshot } from '../src/society-api.js';
import { parseSocietyControl } from '../src/society-control-api.js';
import type { SocietyModels } from '../src/society-models-api.js';
import type { AlternateVersion } from '../src/world-objects-api.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';

/*
 * Who runs each person of a saved world's society, marked over them: a model the models read says
 * is asked marks its person AI by its short name, a visitor is marked by the bridge it crossed
 * through as the door lists it, and nobody else wears a mark. The expected marks are the words
 * agreed with the card (CARD's design, section 3): "AI" and the model's first word; "from" a game;
 * "from outside" for a bridge the door does not list.
 */

const KNIGHT = { kind: 'knight', version: 1, sha256: 'a'.repeat(64) };
const QWEN = { provider: 'nebius', modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507', name: 'Qwen3 235B Instruct' };

const { FakeLayer, FakeMarks, marksMade, bridgeReads } = vi.hoisted(() => {
  class Layer {
    placed: readonly PlacedThingRecord[] = [];
    readonly maker = { library: { list: { kinds: [{ kind: 'knight', version: 1, sha256: 'a'.repeat(64), label: 'knight' }], looks: [] } } };
    constructor(readonly options: ThingLayerOptions) {}
    setSociety() {}
    async setPlaced(things: readonly PlacedThingRecord[]) { this.placed = things; }
    pick() { return null; }
    setPicked() {}
    get drawn() { return []; }
    get misses() { return []; }
    destroy() {}
  }
  const made: InstanceType<typeof Marks>[] = [];
  class Marks {
    readonly sets: ReadonlyMap<string, MarkedSubject>[] = [];
    destroyed = false;
    constructor(readonly options: AttachedMarksOptions) { made.push(this); }
    set(subjects: ReadonlyMap<string, MarkedSubject>) { (this.sets as ReadonlyMap<string, MarkedSubject>[]).push(subjects); }
    destroy() { this.destroyed = true; }
  }
  return { FakeLayer: Layer, FakeMarks: Marks, marksMade: made, bridgeReads: { count: 0 } };
});
vi.mock('@exulanica/atlas-react/things', async (original) => ({
  ...(await original<typeof import('@exulanica/atlas-react/things')>()),
  ThingLayer: FakeLayer,
  AttachedMarks: FakeMarks,
}));
vi.mock('../src/things-library.js', () => ({ openThingLibrary: vi.fn(async () => ({ library: true })) }));
vi.mock('../src/door-bridges-api.js', () => ({
  DoorBridgesClient: class {
    async read() {
      bridgeReads.count += 1;
      return new Map([['blockgame', { bridge: 'blockgame', label: 'Block Game', game: 'Block Game', runBy: 'server', ai: false }]]);
    }
  },
}));

const WORLD = 'world:authored:saved';
const version = {
  schemaVersion: 5, versionId: 'version', worldId: WORLD, sourceSnapshotId: 'snapshot', parentVersionId: null,
  title: 'My world', origin: 'authored', styleVersionId: 'style', stateSha256: '1'.repeat(64), editSeq: 2,
  sourceInvalidated: false, createdBy: 'actor', createdAt: '2026-10-07T00:00:00Z',
  objects: [], elementOverrides: [], environmentInstances: [], edits: [], things: [],
} as unknown as AlternateVersion;

const person = (id: string, extra: Record<string, unknown>) => ({
  id, synthetic: true, position_mm: [2000, 4000], display_name: id, role: 'steward', goal: null, route: null,
  motion_path_mm: [[2000, 4000]],
  action: { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'awaiting_goal' },
  explanation: { summary: 'Waits (simulated).', event_ids: [] }, ...extra,
});

/** A society of things: a knight a model runs, a person their routine runs, and two visitors. */
const society = (): SocietySnapshot => parseSociety({
  society_id: 'society', version_id: 'version', branch_id: 'version', place_id: 'derived-place',
  population_size: 4, current_tick: 3, state_sha256: '3'.repeat(64), input_seq: 1, input_sha256: 'b'.repeat(64),
  state: { profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'version', tick: 3, input_seq: 1,
    input_sha256: 'b'.repeat(64),
    inhabitants: [
      person('knight-0', { kind: KNIGHT, came_by: 'placed', placed_id: 'knight-1' }),
      person('routine-0', { came_by: 'populated' }),
      person('player-0', { came_by: 'crossed', crossing: { arrival_id: 'arrival-1', bridge: 'blockgame', grant_id: 'grant-1' } }),
      person('stranger-0', { came_by: 'crossed', crossing: { arrival_id: 'arrival-2', bridge: 'elsewhere', grant_id: 'grant-2' } }),
    ],
    things: [] },
  places: {
    input_seq: 1, input_sha256: 'b'.repeat(64), availability: 'available', unavailable_reason: null,
    walkable_area: { source: 'declared', centre_mm: [0, 0], half_width_mm: 12000, half_depth_mm: 12000 },
    clearance_mm: 450, targets: [], unavailable_affordances: [],
  },
});

/** The models read: Qwen asked for the knight; a model chosen for the routine person but not asked. */
const models = (): SocietyModels => ({
  societyId: 'society', takesModelChoices: true, hostRefusal: null, modelPeopleMaximum: 8, models: [],
  choices: [
    { subjectId: 'knight-0', model: QWEN, choiceSeq: 1, refusal: null },
    { subjectId: 'routine-0', model: QWEN, choiceSeq: 2, refusal: 'model_not_asked_here' },
  ],
  latest: [], byModel: [], decisionsCounted: 0, decisionsMaximum: 0,
});

function mount() {
  const missing = () => new ApiError(404, 'unknown_reference', 'no such society');
  const crowd = {
    root: { parent: { name: 'authored-region:region:starter' } },
    setSociety: vi.fn(() => 0), clearSociety: vi.fn(), revealInhabitant: vi.fn(), setFigures: vi.fn(), societyJumps: [],
    visibleInhabitantIds: [], inhabitantRepresentation: vi.fn(() => null),
    inhabitantDetail: vi.fn(() => 'near'), coincidentInhabitants: vi.fn(() => []),
    societyCounts: { population: 4, outdoors: 4, indoors: 0, near: 4, far: 0, drawn: 4 },
    drawnInhabitantCount: 4, inhabitantSeatAtPlace: vi.fn(() => false), setSeatingLayout: vi.fn(), seatingMisses: [],
    pickInhabitant: vi.fn(() => null), anchorOf: vi.fn(() => false),
    // A looks read asks the crowd again for its things' figures.
    refreshFigures: vi.fn(),
  };
  const stage = document.createElement('div');
  const overlayRoot = document.createElement('div');
  stage.append(overlayRoot);
  const controls = { state: { x: 0, y: 1.68, z: 4 }, onInteract: vi.fn() as (() => void) | null, forward: () => ({ x: 0, y: 0, z: -1 }) };
  const binding = {
    app: { app: true }, camera: { forward: { x: 0, y: 0, z: -1 } }, controls, invalidate: vi.fn(),
    regionRoots: new Map(), ownedDistrict: null, generatedTile: null, authoredSociety: crowd,
    memoryLayerVisible: false, onMemoryLayerChange: null, overlay: { root: overlayRoot },
  };
  const societyClient = { read: vi.fn(async () => society()), create: vi.fn(), connect: vi.fn(), advance: vi.fn(), events: vi.fn(async () => []) };
  const control = () => parseSocietyControl({
    profile: 'exulanica.society-control/v1', society_id: 'society', branch_id: 'version', persisted: false,
    revision: 0, mode: 'paused', speed: 1, base_tick_interval_ms: 1000, tick_interval_ms: 1000,
    interval_semantics: 'minimum_wait_after_batch_completion', last_batch_execution: null,
    simulated_seconds_per_tick: 60, max_catchup_ticks: 3, next_due_at: null, reason: null,
    lease_expires_at: null, last_event_seq: 0, current_tick: 3, state_sha256: '3'.repeat(64),
    play_ineligible_reason: null, play_eligible: true,
  }, 'version');
  const controlClient = { read: vi.fn(async () => control()), configure: vi.fn(), step: vi.fn() };
  const worldClient = { connect: vi.fn(async () => ({ assets: [], version })), assets: vi.fn(() => []) };
  const modelsClient = { read: vi.fn(async () => { if (modelsAnswer === null) throw missing(); return modelsAnswer; }), choose: vi.fn() };
  let modelsAnswer: SocietyModels | null = models();
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
    // No look is chosen for any thing here.
    thingLooksClient: { read: vi.fn(async () => new Map()) },
  });
  document.body.append(mounted.root);
  return { mounted, crowd, canvas, stage };
}

const settle = async () => { for (let i = 0; i < 12; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); };

describe('marks over the people of a saved world\'s society', () => {
  it('marks a model\'s person AI, a visitor by its bridge, and nobody else', async () => {
    const { mounted, crowd, canvas, stage } = mount();
    await mounted.begin();
    await settle();
    const marks = marksMade.at(-1)!;
    // Drawn into the element the world shows through, over the society the binding draws.
    expect(marks.options.parent).toBe(stage);
    expect(marks.options.anchors()).toBe(crowd);
    const subjects = marks.sets.at(-1)!;
    expect(Object.fromEntries(subjects)).toEqual({
      'knight-0': { mark: { kind: 'ai', short: 'Qwen3', full: 'Qwen3 235B Instruct' }, label: 'knight', spoken: 'run by an AI model, Qwen3 235B Instruct' },
      'player-0': { mark: { kind: 'from', label: 'from Block Game', full: 'A person playing Block Game' }, label: null, spoken: 'A person playing Block Game' },
      'stranger-0': { mark: { kind: 'from', label: 'from outside', full: 'Someone from outside this world' }, label: null, spoken: 'Someone from outside this world' },
    });
    expect(canvas.dataset['thingMarks']).toBe('3');
    // The door is asked once for a bridge it has not named, not on every refresh.
    expect(bridgeReads.count).toBe(1);
    // A pill picks its person as aiming does.
    marks.options.onPick('knight-0');
    expect(crowd.revealInhabitant).toHaveBeenCalledWith('knight-0');
    expect(marks.options.selected()).toBe('knight-0');
    mounted.dispose();
    expect(marks.destroyed).toBe(true);
    expect(canvas.dataset['thingMarks']).toBeUndefined();
  });
});
