// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import type { AtlasScene } from '@exulanica/atlas-core';
import type { AttachedMarksOptions, MarkedSubject, PlacedThingRecord, ThingLayerOptions, ThingLine } from '@exulanica/atlas-react/things';
import { mountEnvironmentSelection, type SelectedPerson, type ShownVisitorNotice } from '../src/composition/environment-selection.js';
import { AN_AI_MODEL } from '../src/composition/thing-marks.js';
import { parseSociety, type SocietySnapshot } from '../src/society-api.js';
import { parseSocietyControl } from '../src/society-control-api.js';
import type { SocietyEvent } from '../src/society-api.js';
import type { SocietyModels } from '../src/society-models-api.js';
import type { AlternateVersion } from '../src/world-objects-api.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';

// The saved world's mounts also ask the host for what this file is not about: its model
// assignments, its things' looks, a played being's turn. The host here is made up, so those reads
// fail at once, as a failed lookup made them fail before the suite refused the network
// (web/vitest.setup.ts).
vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('fetch failed'); }));

/*
 * The lines a society of things' beings say, drawn over them through Selected's mount as the app
 * wires it: nothing said before the page looked, each new line once, oldest first, opening with the
 * line's own mark (a model's line an AI's, naming the model asked for its speaker; a game player's
 * line its game's). Event shapes are the society of things' own (docs/synthetic-society-contract.md,
 * the said event); the bridge's words are the door's entry; the model's name the models read's.
 */

const KNIGHT = { kind: 'knight', version: 1, sha256: 'a'.repeat(64) };
const QWEN = { provider: 'nebius', modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507', name: 'Qwen3 235B Instruct' };

const { FakeLayer, FakeMarks, bridgeReads } = vi.hoisted(() => {
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
  class Marks {
    static last: Marks | null = null;
    readonly sets: ReadonlyMap<string, MarkedSubject>[] = [];
    readonly lines: ThingLine[] = [];
    destroyed = false;
    constructor(readonly options: AttachedMarksOptions) { Marks.last = this; }
    set(subjects: ReadonlyMap<string, MarkedSubject>) { (this.sets as ReadonlyMap<string, MarkedSubject>[]).push(subjects); }
    showLine(line: ThingLine) { this.lines.push(line); }
    showDecision() {}
    destroy() { this.destroyed = true; }
  }
  return { FakeLayer: Layer, FakeMarks: Marks, bridgeReads: { count: 0, answer: Promise.resolve() as Promise<void> } };
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
      await bridgeReads.answer;
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

const crossed = (id: string) => person(id, { kind: KNIGHT, came_by: 'crossed', placed_id: null, crossing: { arrival_id: `arrival-${id}`, bridge: 'blockgame', grant_id: 'grant-1' } });

/** What the server holds now: the society's people and things at a tick, and its latest events. */
const server = {
  tick: 3,
  people: [person('knight-0', { kind: KNIGHT, came_by: 'placed', placed_id: 'knight-1' })] as Record<string, unknown>[],
  things: [] as Record<string, unknown>[],
  events: [] as SocietyEvent[],
};
const society = (): SocietySnapshot => parseSociety({
  society_id: 'society', version_id: 'version', branch_id: 'version', place_id: 'derived-place',
  population_size: server.people.length, current_tick: server.tick, state_sha256: String(server.tick).repeat(64), input_seq: 1, input_sha256: 'b'.repeat(64),
  state: { profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'version', tick: server.tick, input_seq: 1,
    input_sha256: 'b'.repeat(64), inhabitants: server.people, things: server.things },
  places: {
    input_seq: 1, input_sha256: 'b'.repeat(64), availability: 'available', unavailable_reason: null,
    walkable_area: { source: 'declared', centre_mm: [0, 0], half_width_mm: 12000, half_depth_mm: 12000 },
    clearance_mm: 450, targets: [], unavailable_affordances: [],
  },
});

let order = 0;
const event = (kind: string, subject: string, reason: string, thing: Record<string, unknown>): SocietyEvent => {
  order += 1;
  return {
    event_id: `event-${order}`, subject_id: subject, tick: server.tick, event_kind: kind, document_sha256: 'e'.repeat(64),
    document: { synthetic: true, summary: 'Knight (simulated).', reason, order, thing },
  } as SocietyEvent;
};

/** The models read: Qwen asked for the knight; a model chosen for the routine person but not asked. */
const models = (): SocietyModels => ({
  societyId: 'society', takesModelChoices: true, hostRefusal: null, modelPeopleMaximum: 8,
  models: [{ ...QWEN, description: 'A model offered here.', providerDescription: 'Nebius', mechanism: 'tool_call', price: null, refusal: null }] as unknown as SocietyModels['models'],
  choices: [
    { subjectId: 'knight-0', model: QWEN, choiceSeq: 1, refusal: null },
    { subjectId: 'routine-0', model: QWEN, choiceSeq: 2, refusal: 'model_not_asked_here' },
  ],
  latest: [], byModel: [], decisionsCounted: 0, decisionsMaximum: 0,
});

function mount() {
  const notices: ShownVisitorNotice[] = [];
  const showStatus = vi.fn();
  const missing = () => new ApiError(404, 'unknown_reference', 'no such society');
  const crowd = {
    root: { parent: { name: 'authored-region:region:starter' } },
    setSociety: vi.fn(() => 0), clearSociety: vi.fn(), revealInhabitant: vi.fn(), setFigures: vi.fn(), societyJumps: [],
    visibleInhabitantIds: [], inhabitantRepresentation: vi.fn(() => null),
    inhabitantDetail: vi.fn(() => 'near'), coincidentInhabitants: vi.fn(() => []),
    societyCounts: { population: 4, outdoors: 4, indoors: 0, near: 4, far: 0, drawn: 4 },
    drawnInhabitantCount: 4, inhabitantSeatAtPlace: vi.fn(() => false), setSeatingLayout: vi.fn(), seatingMisses: [],
    pickInhabitant: vi.fn(() => null), anchorOf: vi.fn(() => false),
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
  const societyClient = { read: vi.fn(async () => society()), create: vi.fn(), connect: vi.fn(), advance: vi.fn(), events: vi.fn(async () => server.events) };
  const control = () => parseSocietyControl({
    profile: 'exulanica.society-control/v1', society_id: 'society', branch_id: 'version', persisted: false,
    revision: 0, mode: 'paused', speed: 1, base_tick_interval_ms: 1000, tick_interval_ms: 1000,
    interval_semantics: 'minimum_wait_after_batch_completion', last_batch_execution: null,
    simulated_seconds_per_tick: 60, max_catchup_ticks: 3, next_due_at: null, reason: null,
    lease_expires_at: null, last_event_seq: 0, current_tick: server.tick, state_sha256: String(server.tick).repeat(64),
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
    showStatus, admissionId: null, onVisitorNotice: (notice) => { notices.push(notice); },
    worldClient: worldClient as never, societyClient: societyClient as never, societyControlClient: controlClient as never,
    societyModelsClient: modelsClient as never,
  });
  document.body.append(mounted.root);
  const shown: { id: string; about: SelectedPerson }[] = [];
  mounted.useInhabitantView({
    root: document.createElement('section'),
    show: (id, about) => { shown.push({ id, about }); return true; },
    hide: () => undefined,
  });
  return { mounted, notices, shown, showStatus };
}

const settle = async () => { for (let i = 0; i < 12; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); };

const refresh = async () => {
  [...document.querySelectorAll('button')].find((button) => button.textContent === 'Refresh persisted society')!.click();
  await settle();
};

const said = (
  subject: string, line: string, decider: 'model' | 'external', to: string | null, fromNumber: number, toNumber: number | null,
  model: { provider: string; model_id: string } | null = null,
) =>
  event('said', subject, 'chose_to_say', {
    line, to, to_kind: to === null ? null : KNIGHT, to_number: toNumber, from_kind: KNIGHT, from_number: fromNumber,
    heard_by: to === null ? [] : [to], decider, ...(model === null ? {} : { model }),
  });

describe('lines said in a saved world', () => {
  it('draws each new line once over its speaker, oldest first, with the line\'s own mark and nothing said before the page looked', async () => {
    server.people = [
      person('knight-0', { kind: KNIGHT, came_by: 'placed', placed_id: 'knight-1' }),
      crossed('player-0'),
      person('knight-2', { kind: KNIGHT, came_by: 'placed', placed_id: 'knight-3' }),
    ];
    // Said before the page looked: never drawn.
    server.events = [said('knight-0', 'Old words.', 'model', null, 1, null)];
    const { mounted } = mount();
    await mounted.begin();
    await settle();
    const marks = FakeMarks.last!;
    expect(marks.lines).toEqual([]);
    // A new minute: the player greets the knight, then the knight answers; the window still holds the old line.
    server.tick = 4;
    server.events = [
      ...server.events,
      said('knight-0', 'Well met, traveller.', 'model', 'player-0', 1, 2, { provider: QWEN.provider, model_id: QWEN.modelId }),
      said('player-0', 'Hello there!', 'external', 'knight-0', 2, 1),
    ];
    await refresh();
    expect(marks.lines.map((line) => [line.subjectId, line.text])).toEqual([
      ['knight-0', 'Well met, traveller.'],
      ['player-0', 'Hello there!'],
    ]);
    const [knight, player] = marks.lines;
    // A model's line wears the AI mark naming the model its own event names, by the models read's served name.
    expect(knight!.mark).toEqual({ kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct' });
    // Three knights are drawn, so each is told apart by its number; the model is named after.
    expect(knight!.header).toBe('knight 1 to knight 2 · Qwen3 235B Instruct');
    expect(knight!.spoken).toBe('run by an AI model, Qwen3 235B Instruct');
    // A game player's line wears the game's mark, as the door names it.
    expect(player!.mark).toEqual({ kind: 'from', label: 'from Block Game', full: 'From Block Game, decided from outside' });
    expect(player!.header).toBe('knight 2 to knight 1');
    // Read again with nothing new: nothing drawn twice.
    await refresh();
    expect(marks.lines).toHaveLength(2);
    mounted.dispose();
  });

  it('marks a model\'s line AI, naming no model its event does not name, even one asked for its speaker now', async () => {
    // Qwen is asked for knight-0 now, but this line's event names no model: the line claims none.
    server.people = [person('knight-0', { kind: KNIGHT, came_by: 'placed', placed_id: 'knight-1' })];
    server.events = [];
    const { mounted } = mount();
    await mounted.begin();
    await settle();
    server.tick = 5;
    server.events = [said('knight-0', 'A fine day.', 'model', null, 1, null)];
    await refresh();
    const [line] = FakeMarks.last!.lines;
    expect(line!.mark).toBe(AN_AI_MODEL);
    expect(line!.header).toBe('knight');
    expect(line!.spoken).toBe('run by an AI model');
    mounted.dispose();
  });
});
