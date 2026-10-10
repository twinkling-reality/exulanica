// @vitest-environment happy-dom

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import type { AtlasScene } from '@exulanica/atlas-core';
import type { AttachedMarksOptions, MarkedSubject, PlacedThingRecord, ThingDecision, ThingLayerOptions } from '@exulanica/atlas-react/things';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import { parseSociety, type SocietySnapshot } from '../src/society-api.js';
import { parseSocietyControl } from '../src/society-control-api.js';
import type { PersonDecision, SocietyModels } from '../src/society-models-api.js';
import type { AlternateVersion } from '../src/world-objects-api.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';

// The saved world's mounts also ask the host for what this file is not about: its model
// assignments, its things' looks, a played being's turn. The host here is made up, so those reads
// fail at once, as a failed lookup made them fail before the suite refused the network
// (web/vitest.setup.ts).
vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('fetch failed'); }));

/*
 * Who runs each person of a saved world's society, marked over them: a model the models read says
 * is asked marks its person AI by its whole served name, a visitor is marked by the bridge it crossed
 * through as the door lists it, and nobody else wears a mark. The expected marks are the words
 * agreed with the card (CARD's design, section 3): "AI" and the model's first word; "from" a game;
 * "from outside" for a bridge the door does not list.
 */

const KNIGHT = { kind: 'knight', version: 1, sha256: 'a'.repeat(64) };
const QWEN = { provider: 'nebius', modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507', name: 'Qwen3 235B Instruct' };

const { FakeLayer, FakeMarks, marksMade, layersMade, bridgeReads, workspace } = vi.hoisted(() => {
  const layers: InstanceType<typeof Layer>[] = [];
  /** The workspace's own kinds, as the library reads them: what was asked for, and what was forgotten. */
  const workspace = { asked: [] as string[], forgotten: [] as string[], label: 'ember drake' as string | null };
  class Layer {
    placed: readonly PlacedThingRecord[] = [];
    /** Each being the page has said the viewer plays, in order (null: nobody). */
    readonly played: (string | null)[] = [];
    readonly maker = { library: {
      list: { kinds: [{ kind: 'knight', version: 1, sha256: 'a'.repeat(64), label: 'knight' }], looks: [] },
      async kindDocument(named: { readonly sha256: string }) {
        workspace.asked.push(named.sha256);
        if (workspace.label === null) throw new Error('The workspace holds no kind at that digest.');
        return { label: workspace.label };
      },
      async forgetHeldKind(sha256: string) { workspace.forgotten.push(sha256); },
    } };
    constructor(readonly options: ThingLayerOptions) { layers.push(this); }
    setSociety() {}
    setPlayed(subjectId: string | null) { this.played.push(subjectId); }
    setDestination() {}
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
    /** Each decision the page opened under a being's name, in order. */
    readonly decisions: ThingDecision[] = [];
    destroyed = false;
    constructor(readonly options: AttachedMarksOptions) { made.push(this); }
    set(subjects: ReadonlyMap<string, MarkedSubject>) { (this.sets as ReadonlyMap<string, MarkedSubject>[]).push(subjects); }
    showDecision(decision: ThingDecision) { this.decisions.push(decision); }
    destroy() { this.destroyed = true; }
  }
  return { FakeLayer: Layer, FakeMarks: Marks, marksMade: made, layersMade: layers, bridgeReads: { count: 0 }, workspace };
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

/** What bounds the marks, read here from the catalog file by each entry's key. */
// Tests run from web/.
const STATED = new Map((JSON.parse(readFileSync(
  resolve('..', 'assets/catalogs/thing-presentation/decider-marks.v1.json'), 'utf8',
)) as { entries: { key: string; value: number }[] }).entries.map((entry) => [entry.key, entry.value]));
const DECIDER_RULE = {
  nameLeastPx: STATED.get('name_least_px'), beingLeastPx: STATED.get('being_least_px'),
  screenShare: STATED.get('screen_share_milli')! / 1000, linesAtOnce: STATED.get('lines_at_once'),
  lineBaseMs: STATED.get('line_base_ms'), linePerCharacterMs: STATED.get('line_per_character_ms'), lineMostMs: STATED.get('line_most_ms'),
};

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

/** The minute the society is read at, and whether the knight is played (and by whom), as a test sets them. */
let tick = 3;
let knightPlayed: { readonly byYou: boolean } | null = null;
/** Whether the routine's person states that they are indoors, or states nothing of it (null), as a test sets it. */
let routineIndoors: boolean | null = null;
/** Each being's latest decision as the models read serves it, as a test sets them. */
let latestDecisions: PersonDecision[] = [];
/** What the model's person is a being of, and whether it is among the people, as a test sets them. */
const DRAKE = { source: 'workspace', sha256: 'd'.repeat(64) } as const;
let modelsPersonKind: typeof KNIGHT | typeof DRAKE = KNIGHT;
let modelsPersonHere = true;

/** A society of things: a knight a model runs, a person their routine runs, and two visitors. */
const society = (): SocietySnapshot => parseSociety({
  society_id: 'society', version_id: 'version', branch_id: 'version', place_id: 'derived-place',
  population_size: 4, current_tick: tick, state_sha256: String(tick).repeat(64), input_seq: 1, input_sha256: 'b'.repeat(64),
  state: { profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'version', tick, input_seq: 1,
    input_sha256: 'b'.repeat(64),
    inhabitants: [
      ...(modelsPersonHere ? [person('knight-0', { kind: modelsPersonKind, came_by: 'placed', placed_id: 'knight-1' })] : []),
      person('routine-0', { came_by: 'populated', ...(routineIndoors === null ? {} : { location: { node_id: 'home:1', edge: null, indoors: routineIndoors } }) }),
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

/**
 * The models read: Qwen asked for the knight, or, while a person plays it, the person's choice saying
 * whether the reader is that person (THINGS 3p, UI's models client); a model chosen for the routine
 * person but not asked.
 */
const models = (): SocietyModels => ({
  societyId: 'society', takesModelChoices: true, hostRefusal: null, modelPeopleMaximum: 8, models: [],
  choices: [
    knightPlayed === null
      ? { subjectId: 'knight-0', model: QWEN, choiceSeq: 1, refusal: null }
      : { subjectId: 'knight-0', model: null, choiceSeq: 3, refusal: null, played: knightPlayed },
    { subjectId: 'routine-0', model: QWEN, choiceSeq: 2, refusal: 'model_not_asked_here' },
  ],
  latest: latestDecisions, byModel: [], decisionsCounted: 0, decisionsMaximum: 0,
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
    // A saved world with no town under it: no generated tile and no district, so nothing here can be read from city records.
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
  const modelsClient = { read: vi.fn(async () => { if (modelsAnswer === null) throw missing(); return models(); }), choose: vi.fn() };
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
      'knight-0': { mark: { kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct' }, label: 'knight', spoken: 'run by an AI model, Qwen3 235B Instruct' },
      'player-0': { mark: { kind: 'from', label: 'from Block Game', full: 'From Block Game, decided from outside' }, label: null, spoken: 'From Block Game, decided from outside' },
      'stranger-0': { mark: { kind: 'from', label: 'from outside', full: 'Someone from outside this world' }, label: null, spoken: 'Someone from outside this world' },
      // Its own routine decides for it: nothing at rest, and the answer for while it is the picked one.
      'routine-0': { mark: null, picked: { kind: 'routine', label: 'Their own routine', full: 'Their own routine decides for them' }, label: null },
    });
    // Three wear a mark; who decides for all four is counted on the canvas, and nobody here states
    // that they are indoors, so all are in the street.
    expect(canvas.dataset['thingMarks']).toBe('3');
    expect(JSON.parse(canvas.dataset['deciders']!)).toEqual({ models: 1, you: 0, played: 0, outside: 2, routine: 1, indoors: 0 });
    // What bounds the marks is the catalog's rule, handed to the overlay.
    expect(marks.options.rule).toEqual(DECIDER_RULE);
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

  it('marks the being the viewer plays You and rings it at the read that says so, and gives its mind\'s mark back after', async () => {
    tick = 3;
    knightPlayed = { byYou: true };
    const { mounted } = mount();
    await mounted.begin();
    await settle();
    const marks = marksMade.at(-1)!;
    const layer = layersMade.at(-1)!;
    // The words agreed with lane UI for Play this one; the ring is the played being's.
    expect(marks.sets.at(-1)!.get('knight-0')).toEqual({
      mark: { kind: 'person', mine: true, label: 'You', full: 'Played by you' }, label: 'knight', spoken: 'Played by you',
    });
    expect(layer.played.at(-1)).toBe('knight-0');
    // Given back: the next minute's read names its model again, and the ring goes.
    knightPlayed = null;
    tick = 4;
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Refresh persisted society')!.click();
    await settle();
    expect(marks.sets.at(-1)!.get('knight-0')!.mark).toEqual({ kind: 'ai', name: 'Qwen3 235B Instruct', full: 'Qwen3 235B Instruct' });
    expect(layer.played.at(-1)).toBeNull();
    // Another person playing it: Played, and no ring here.
    knightPlayed = { byYou: false };
    tick = 5;
    [...document.querySelectorAll('button')].find((button) => button.textContent === 'Refresh persisted society')!.click();
    await settle();
    expect(marks.sets.at(-1)!.get('knight-0')!.mark).toEqual({ kind: 'person', mine: false, label: 'Played', full: 'Played by another person' });
    expect(layer.played.at(-1)).toBeNull();
    mounted.dispose();
    knightPlayed = null;
    tick = 3;
  });

  it('counts a being indoors only where its own state says so: one that states nothing of it is in the street', async () => {
    const counted = async (): Promise<{ indoors: number; routine: number }> => {
      const { mounted, canvas } = mount();
      await mounted.begin();
      await settle();
      const counts = JSON.parse(canvas.dataset['deciders']!) as { indoors: number; routine: number };
      mounted.dispose();
      return counts;
    };
    try {
      routineIndoors = null;
      expect(await counted()).toMatchObject({ indoors: 0, routine: 1 });
      routineIndoors = false;
      expect(await counted()).toMatchObject({ indoors: 0, routine: 1 });
      // Stated indoors, it is counted so, and still one the routine decides for.
      routineIndoors = true;
      expect(await counted()).toMatchObject({ indoors: 1, routine: 1 });
    } finally {
      routineIndoors = null;
    }
  });

  it('opens each decision a minute takes up under its decider, once, and none from before the visit', async () => {
    const decided = (seq: number, extra: Partial<PersonDecision>): PersonDecision => ({
      ...QWEN, subjectId: 'knight-0', decisionSeq: seq, baseTick: seq + 1, consumedTick: null, status: 'accepted',
      reason: 'accepted', disposition: null, dispositionReason: null, chose: 'walk to the well', ...extra,
    });
    const refresh = async () => {
      [...document.querySelectorAll('button')].find((button) => button.textContent === 'Refresh persisted society')!.click();
      await settle();
    };
    try {
      // Before the visit the knight's model had already chosen, and a minute had acted on it.
      tick = 3;
      latestDecisions = [decided(1, { consumedTick: 3, disposition: 'applied' })];
      const { mounted } = mount();
      await mounted.begin();
      await settle();
      const marks = marksMade.at(-1)!;
      expect(marks.decisions).toEqual([]);
      // A new decision is asked: nothing opens until a minute takes it up.
      tick = 4;
      latestDecisions = [decided(2, { chose: 'say something to the lantern spirit' })];
      await refresh();
      expect(marks.decisions).toEqual([]);
      // The minute acted on it: it opens under the knight, saying what was chosen and holding an
      // empty place for the decider's own words, which this decision contract does not serve.
      tick = 5;
      latestDecisions = [decided(2, { chose: 'say something to the lantern spirit', consumedTick: 5, disposition: 'applied' })];
      await refresh();
      expect(marks.decisions).toEqual([{ subjectId: 'knight-0', chose: 'Chose “say something to the lantern spirit”.', said: null }]);
      // Read again with nothing new, it does not open a second time.
      await refresh();
      expect(marks.decisions.length).toBe(1);
      // A decision whose model was not followed opens at once, saying so and that the routine decided.
      tick = 6;
      latestDecisions = [decided(3, { status: 'rejected', reason: 'stale_state' })];
      await refresh();
      expect(marks.decisions.length).toBe(2);
      expect(marks.decisions[1]!.subjectId).toBe('knight-0');
      expect(marks.decisions[1]!.chose).toMatch(/^Not followed: .+\. Its routine decided\.$/u);
      mounted.dispose();
    } finally {
      latestDecisions = [];
      tick = 3;
    }
  });

  it('names a being of a kind its workspace keeps by its maker\'s word while it is here, and forgets the word when it has gone', async () => {
    tick = 3;
    modelsPersonKind = DRAKE;
    workspace.asked.length = 0;
    workspace.forgotten.length = 0;
    const refresh = async () => {
      [...document.querySelectorAll('button')].find((button) => button.textContent === 'Refresh persisted society')!.click();
      await settle();
    };
    const { mounted } = mount();
    await mounted.begin();
    await settle();
    const marks = marksMade.at(-1)!;
    // Read once from the workspace, by the kind's digest, and said over the being.
    expect(marks.sets.at(-1)!.get('knight-0')!.label).toBe('ember drake');
    expect(workspace.asked).toEqual([DRAKE.sha256]);
    tick = 4;
    await refresh();
    // Still here: nothing is asked again and nothing forgotten.
    expect(workspace.asked).toEqual([DRAKE.sha256]);
    expect(workspace.forgotten).toEqual([]);
    // Its maker erases the creature: the workspace no longer holds the kind, and the being has left.
    workspace.label = null;
    modelsPersonHere = false;
    tick = 5;
    await refresh();
    expect(marks.sets.at(-1)!.has('knight-0')).toBe(false);
    expect(workspace.forgotten).toEqual([DRAKE.sha256]);
    // Were a being of that kind listed again, the page has no word of its own left to say:
    // it asks the workspace, which holds none, and says no name.
    modelsPersonHere = true;
    tick = 6;
    await refresh();
    expect(workspace.asked).toEqual([DRAKE.sha256, DRAKE.sha256]);
    expect(marks.sets.at(-1)!.get('knight-0')!.label).toBeNull();
    mounted.dispose();
    modelsPersonKind = KNIGHT;
    workspace.label = 'ember drake';
    tick = 3;
  });
});
