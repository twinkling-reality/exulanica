// @vitest-environment happy-dom

import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import type { AtlasScene } from '@exulanica/atlas-core';
import type { AttachedMarksOptions, MarkedSubject, PlacedThingRecord, ThingLayerOptions } from '@exulanica/atlas-react/things';
import { mountEnvironmentSelection, type SelectedPerson, type ShownVisitorNotice } from '../src/composition/environment-selection.js';
import { parseSociety, type SocietySnapshot } from '../src/society-api.js';
import { parseSocietyControl } from '../src/society-control-api.js';
import type { SocietyEvent } from '../src/society-api.js';
import type { SocietyModels } from '../src/society-models-api.js';
import type { AlternateVersion } from '../src/world-objects-api.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';

/*
 * A notice when somebody crosses into a saved world's society of things, leaves or is turned away,
 * through Selected's mount as the app wires it: nothing for what happened before the page looked,
 * an arrival held until the door names its bridge, "See who" opening the visitor's card with what
 * its state says it is. Event shapes and reasons are the society of things' own
 * (docs/synthetic-society-contract.md); the bridge's words are the door's entry.
 */

const KNIGHT = { kind: 'knight', version: 1, sha256: 'a'.repeat(64) };
const QWEN = { provider: 'nebius', modelId: 'Qwen/Qwen3-235B-A22B-Instruct-2507', name: 'Qwen3 235B Instruct' };

const { FakeLayer, FakeMarks, bridgeReads, kindReads } = vi.hoisted(() => {
  class Layer {
    placed: readonly PlacedThingRecord[] = [];
    readonly maker = { library: {
      list: { kinds: [{ kind: 'knight', version: 1, sha256: 'a'.repeat(64), label: 'knight' }], looks: [] },
      // A kind the workspace made, which no shipped list holds, is read by digest (DRAW 8).
      kindDocument: async (named: { key: string }) => {
        kindReads.count += 1;
        await kindReads.answer;
        return named.key === 'griffin' ? { kind: 'griffin', version: 1, label: 'griffin' } : null;
      },
    } };
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
    readonly sets: ReadonlyMap<string, MarkedSubject>[] = [];
    destroyed = false;
    constructor(readonly options: AttachedMarksOptions) {}
    set(subjects: ReadonlyMap<string, MarkedSubject>) { (this.sets as ReadonlyMap<string, MarkedSubject>[]).push(subjects); }
    destroy() { this.destroyed = true; }
  }
  return { FakeLayer: Layer, FakeMarks: Marks, bridgeReads: { count: 0, answer: Promise.resolve() as Promise<void> },
    kindReads: { count: 0, answer: Promise.resolve() as Promise<void> } };
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
const catalog = JSON.parse(readFileSync(`${process.cwd()}/../assets/catalogs/society-words/society-inhabitant-words.v1.json`, 'utf8')) as
  { entries: { kind: string; code: string; words: string }[] };
/** Why an event happened, as the words catalog says it. */
const because = (code: string): string => catalog.entries.find((entry) => entry.kind === 'event_reason' && entry.code === code)!.words;
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

const SWORD = { kind: 'sword', version: 3, sha256: 'c'.repeat(64) };
const crossed = (id: string) => person(id, { kind: KNIGHT, came_by: 'crossed', placed_id: null, crossing: { arrival_id: `arrival-${id}`, bridge: 'blockgame', grant_id: 'grant-1' } });

/** What the server holds now: the society's people and things at a tick, and its latest events. */
const server = {
  tick: 3,
  people: [person('knight-0', { kind: KNIGHT, came_by: 'placed', placed_id: 'knight-1' })] as Record<string, unknown>[],
  things: [] as Record<string, unknown>[],
  events: [] as SocietyEvent[],
  /** Who outside programs decide for now, as the models read lists them; nobody unless a test says. */
  outside: [] as NonNullable<SocietyModels['outside']>,
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
  societyId: 'society', takesModelChoices: true, hostRefusal: null, modelPeopleMaximum: 8, models: [],
  choices: [
    { subjectId: 'knight-0', model: QWEN, choiceSeq: 1, refusal: null },
    { subjectId: 'routine-0', model: QWEN, choiceSeq: 2, refusal: 'model_not_asked_here' },
  ],
  latest: [], byModel: [], decisionsCounted: 0, decisionsMaximum: 0, outside: server.outside,
});

function mount() {
  const notices: ShownVisitorNotice[] = [];
  const showStatus = vi.fn();
  const missing = () => new ApiError(404, 'unknown_reference', 'no such society');
  const crowd = {
    root: { parent: { name: 'authored-region:region:starter' } },
    setSociety: vi.fn(() => 0), clearSociety: vi.fn(), revealInhabitant: vi.fn(), setFigures: vi.fn(), societyJumps: [],
    visibleInhabitantIds: [] as string[], inhabitantRepresentation: vi.fn(() => null),
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
  return { mounted, notices, shown, showStatus, crowd };
}

const settle = async () => { for (let i = 0; i < 12; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); };

const refresh = async () => {
  [...document.querySelectorAll('button')].find((button) => button.textContent === 'Refresh persisted society')!.click();
  await settle();
};

describe('visitors crossing into a saved world', () => {
  it('tells of each crossing once, names its bridge, and opens the visitor\'s card from See who', async () => {
    // Before the page looks: a visitor already came and went.
    server.events = [event('thing_arrived', 'visitor-0', 'crossed_in', { kind: KNIGHT, came_by: 'crossed', crossing_id: 'c0', carried: [] })];
    const { mounted, notices, shown, showStatus } = mount();
    await mounted.begin();
    await settle();
    expect(notices).toEqual([]);
    expect(bridgeReads.count).toBe(0);

    // The next minute: a visitor crosses in holding a sword, the author places a being, and a
    // crossing is turned away at the limit.
    server.tick = 4;
    server.people = [...server.people, crossed('visitor-1')];
    server.things = [
      { id: 'sword-1', placed_id: null, kind: SWORD, position_mm: null, yaw_microradians: null, held_by: 'visitor-1' },
      { id: 'sword-2', placed_id: null, kind: SWORD, position_mm: null, yaw_microradians: null, held_by: 'knight-0' },
    ];
    server.events = [
      ...server.events,
      event('thing_arrived', 'visitor-1', 'crossed_in', { kind: KNIGHT, came_by: 'crossed', placed_id: null, crossing_id: 'c1', gate: 'gate', carried: [{ thing_id: 'sword-1', kind: SWORD }] }),
      event('thing_arrived', 'knight-2', 'placed_by_author', { kind: KNIGHT, came_by: 'placed', placed_id: 'knight-2' }),
      event('arrival_refused', 'visitor-9', 'visitor_limit', { kind: KNIGHT, came_by: 'crossed', placed_id: null, crossing_id: 'c9', gate: 'gate' }),
    ];
    // The door answers slowly: the arrival waits for it to name the bridge.
    let answer!: () => void;
    bridgeReads.answer = new Promise<void>((resolve) => { answer = resolve; });
    await refresh();
    expect(bridgeReads.count).toBe(1);
    expect(notices.map(({ message }) => message)).toEqual([]);
    answer();
    await settle();
    expect(notices.map(({ message, tone }) => ({ message, tone }))).toEqual([
      { message: 'A knight came in from Block Game.', tone: 'info' },
      { message: `A knight could not come in, because ${because('visitor_limit')}.`, tone: 'caution' },
    ]);
    expect(notices[1]!.seeWho).toBeNull();

    notices[0]!.seeWho!();
    const card = shown.at(-1)!;
    expect(card.id).toBe('visitor-1');
    expect(card.about.being).toMatchObject({
      kind: KNIGHT, cameBy: 'crossed', placedId: null,
      crossing: { bridge: 'blockgame', entry: { bridge: 'blockgame', label: 'Block Game', game: 'Block Game', runBy: 'server', ai: false }, arrivalId: 'arrival-visitor-1', decidedBy: 'program' },
      holding: [{ id: 'sword-1', kind: SWORD }],
      world: { worldId: WORLD, versionId: 'version' },
      said: [], heard: [],
    });
    // The card is handed the very input the world's marks read (markInputFor), so the two agree.
    expect(card.about.being!.mark).toEqual({
      running: null, crossing: { arrival_id: 'arrival-visitor-1', bridge: 'blockgame', grant_id: 'grant-1' },
      bridge: { bridge: 'blockgame', label: 'Block Game', game: 'Block Game', runBy: 'server', ai: false }, declared: null,
    });

    // Read again with nothing new, nothing is told again.
    await refresh();
    expect(notices).toHaveLength(2);

    // The minute it leaves, its departure names where it came from although the state no longer lists it.
    server.tick = 5;
    server.people = server.people.filter((one) => one['id'] !== 'visitor-1');
    server.things = [];
    server.events = [...server.events, event('thing_departed', 'visitor-1', 'sent_home', { kind: KNIGHT, came_by: 'crossed', placed_id: null, carried: [{ id: 'sword-1', kind: SWORD }] })];
    await refresh();
    expect(notices.at(-1)!.message).toBe(`The knight from Block Game left because ${because('sent_home')}.`);
    // See who on an arrival whose visitor has gone says so.
    notices[0]!.seeWho!();
    expect(showStatus).toHaveBeenCalledWith('They are no longer in this world.');
    mounted.dispose();
  });
});

describe('the lines a being said and heard, handed to its card', () => {
  it('fills the selected being\'s lines from the events read and its state', async () => {
    server.tick = 9;
    server.people = [
      person('knight-0', { kind: KNIGHT, came_by: 'placed', placed_id: 'knight-1',
        heard: [{ tick: 9, from: 'traveller-0', from_kind: KNIGHT, from_number: 2, to: 'knight-0', line: 'Thank you.' }] }),
      person('traveller-0', { kind: KNIGHT, came_by: 'placed', placed_id: 'traveller-1' }),
    ];
    server.things = [];
    server.events = [
      event('said', 'knight-0', 'chose_to_say', { line: 'Take it.', to: 'traveller-0', to_kind: KNIGHT, to_number: 2, from_kind: KNIGHT, from_number: 1, heard_by: ['traveller-0'], decider: 'model' }),
      event('said', 'traveller-0', 'chose_to_say', { line: 'Thank you.', to: 'knight-0', to_kind: KNIGHT, to_number: 1, from_kind: KNIGHT, from_number: 2, heard_by: ['knight-0'], decider: 'model' }),
    ];
    const { mounted, shown, crowd } = mount();
    // The People list names whom the crowd draws nearby.
    crowd.visibleInhabitantIds = ['knight-0', 'traveller-0'];
    await mounted.begin();
    await settle();
    const pick = [...document.querySelectorAll('select')].find((one) => one.getAttribute('aria-label') === 'Inspect nearby inhabitant')!;
    pick.value = 'knight-0';
    pick.dispatchEvent(new Event('change'));
    const being = shown.at(-1)!.about.being!;
    expect(being.said.map((line) => [line.line, line.toId, line.decider])).toEqual([['Take it.', 'traveller-0', 'model']]);
    // Heard from the state; who decided it from the speaker's said event in the window.
    expect(being.heard.map((line) => [line.line, line.speakerId, line.decider])).toEqual([['Thank you.', 'traveller-0', 'model']]);
    mounted.dispose();
  });
});

describe('a visitor of a kind its workspace made', () => {
  it('is announced by its own kind\'s label, read from the kind\'s document, never as a visitor', async () => {
    const GRIFFIN = { kind: 'griffin', version: 1, sha256: 'f'.repeat(64) };
    server.tick = 7;
    server.people = [person('knight-0', { kind: KNIGHT, came_by: 'placed', placed_id: 'knight-1' })];
    server.things = [];
    server.events = [];
    const { mounted, notices } = mount();
    await mounted.begin();
    await settle();
    server.tick = 8;
    server.people = [...server.people, person('griffin-0', { kind: GRIFFIN, came_by: 'crossed', placed_id: null, crossing: { arrival_id: 'a', bridge: 'blockgame', grant_id: 'g' } })];
    server.events = [event('thing_arrived', 'griffin-0', 'crossed_in', { kind: GRIFFIN, came_by: 'crossed', placed_id: null, crossing_id: 'c', gate: 'gate', carried: [] })];
    await refresh();
    expect(notices.map(({ message }) => message)).toEqual(['A griffin came in from Block Game.']);
    mounted.dispose();
  });

  it('tells nothing while a kind is still being read, even when a later minute brings another crossing', async () => {
    const GRIFFIN = { kind: 'griffin', version: 1, sha256: 'f'.repeat(64) };
    const crossedGriffin = (id: string) => person(id, { kind: GRIFFIN, came_by: 'crossed', placed_id: null, crossing: { arrival_id: `a-${id}`, bridge: 'blockgame', grant_id: 'g' } });
    const arrived = (id: string) => event('thing_arrived', id, 'crossed_in', { kind: GRIFFIN, came_by: 'crossed', placed_id: null, crossing_id: `c-${id}`, gate: 'gate', carried: [] });
    server.tick = 6;
    server.people = [person('knight-0', { kind: KNIGHT, came_by: 'placed', placed_id: 'knight-1' })];
    server.things = [];
    server.events = [];
    let release!: () => void;
    kindReads.answer = new Promise<void>((resolve) => { release = resolve; });
    const reads = kindReads.count;
    const { mounted, notices } = mount();
    await mounted.begin();
    await settle();
    server.tick = 7;
    server.people = [...server.people, crossedGriffin('griffin-0')];
    server.events = [arrived('griffin-0')];
    await refresh();
    // The second minute's crossing arrives while the griffin's document is still being read.
    server.tick = 8;
    server.people = [...server.people, crossedGriffin('griffin-1')];
    server.events = [...server.events, arrived('griffin-1')];
    await refresh();
    expect(notices).toEqual([]);
    expect(kindReads.count - reads).toBe(1);
    release();
    await settle();
    expect(notices.map(({ message }) => message)).toEqual(['A griffin came in from Block Game.', 'A griffin came in from Block Game.']);
    mounted.dispose();
  });
});

describe('why a visitor its own program decides for did something', () => {
  it('credits its own program, never a model, where a world-run being and a placed one credit their model', async () => {
    const catalog = JSON.parse(readFileSync(`${process.cwd()}/../assets/catalogs/society-words/society-inhabitant-words.v1.json`, 'utf8')) as
      { entries: { kind: string; code: string; words: string }[] };
    const words = (kind: string, code: string) => catalog.entries.find((entry) => entry.kind === kind && entry.code === code)!.words;
    const chose = { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'chosen_by_their_model' };
    server.tick = 7;
    server.people = [
      person('knight-0', { kind: KNIGHT, came_by: 'placed', placed_id: 'knight-1', action: chose }),
      person('visitor-1', { kind: KNIGHT, came_by: 'crossed', placed_id: null, action: chose, crossing: { arrival_id: 'a1', bridge: 'blockgame', grant_id: 'g1' } }),
      person('visitor-2', { kind: KNIGHT, came_by: 'crossed', placed_id: null, action: chose, crossing: { arrival_id: 'a2', bridge: 'blockgame', grant_id: 'g2', decided_by: 'world' } }),
    ];
    server.things = [];
    server.events = [];
    const { mounted, shown, crowd } = mount();
    crowd.visibleInhabitantIds = ['knight-0', 'visitor-1', 'visitor-2'];
    await mounted.begin();
    await settle();
    const pick = [...document.querySelectorAll('select')].find((one) => one.getAttribute('aria-label') === 'Inspect nearby inhabitant')!;
    const activityOf = (id: string): string => {
      pick.value = id;
      pick.dispatchEvent(new Event('change'));
      return shown.at(-1)!.about.note.activity;
    };
    const because = (reason: string) => words('phrase', 'because').replace('{reason}', reason);
    expect(activityOf('visitor-1')).toContain(because(words('phrase', 'chosen_by_their_program')));
    expect(activityOf('visitor-1')).not.toContain(words('reason', 'chosen_by_their_model'));
    expect(activityOf('visitor-2')).toContain(because(words('reason', 'chosen_by_their_model')));
    expect(activityOf('knight-0')).toContain(because(words('reason', 'chosen_by_their_model')));
    mounted.dispose();
  });
});

describe('why one of the world\'s own people a grant hands to an outside program did something', () => {
  it('credits that program, never a model, as the models read lists them', async () => {
    const catalog = JSON.parse(readFileSync(`${process.cwd()}/../assets/catalogs/society-words/society-inhabitant-words.v1.json`, 'utf8')) as
      { entries: { kind: string; code: string; words: string }[] };
    const words = (kind: string, code: string) => catalog.entries.find((entry) => entry.kind === kind && entry.code === code)!.words;
    const because = (reason: string) => words('phrase', 'because').replace('{reason}', reason);
    const chose = { kind: 'idle', status: 'active', target_id: null, remaining_ticks: 0, reason: 'chosen_by_their_model' };
    server.tick = 9;
    server.people = [person('knight-0', { kind: KNIGHT, came_by: 'placed', placed_id: 'knight-1', action: chose })];
    server.things = [];
    server.events = [];
    server.outside = [{
      subjectId: 'knight-0', came: 'run', grantId: 'grant-1', bridge: 'agents', bridgeLabel: 'Outside AI agents',
      runBy: 'owner', ai: true, connected: true, declared: { name: 'Scout', maker: 'Acme', mind: null },
    }];
    try {
      const { mounted, shown, crowd } = mount();
      crowd.visibleInhabitantIds = ['knight-0'];
      await mounted.begin();
      await settle();
      const pick = [...document.querySelectorAll('select')].find((one) => one.getAttribute('aria-label') === 'Inspect nearby inhabitant')!;
      pick.value = 'knight-0';
      pick.dispatchEvent(new Event('change'));
      expect(shown.at(-1)!.about.note.activity).toContain(because(words('phrase', 'chosen_by_their_program')));
      expect(shown.at(-1)!.about.note.activity).not.toContain(words('reason', 'chosen_by_their_model'));
      mounted.dispose();
    } finally {
      server.outside = [];
    }
   });
 });

describe('who decides for a visitor, handed to its card', () => {
  it('carries its arrival\'s word that the world decides for it, and the world\'s mark input with it', async () => {
    server.tick = 5;
    server.people = [
      person('visitor-1', { kind: KNIGHT, came_by: 'crossed', placed_id: null, crossing: { arrival_id: 'a1', bridge: 'blockgame', grant_id: 'g1' } }),
      person('visitor-2', { kind: KNIGHT, came_by: 'crossed', placed_id: null, crossing: { arrival_id: 'a2', bridge: 'blockgame', grant_id: 'g2', decided_by: 'world' } }),
    ];
    server.things = [];
    server.events = [];
    const { mounted, shown, crowd } = mount();
    crowd.visibleInhabitantIds = ['visitor-1', 'visitor-2'];
    await mounted.begin();
    await settle();
    const pick = [...document.querySelectorAll('select')].find((one) => one.getAttribute('aria-label') === 'Inspect nearby inhabitant')!;
    const beingOf = (id: string) => {
      pick.value = id;
      pick.dispatchEvent(new Event('change'));
      return shown.at(-1)!.about.being!;
    };
    expect(beingOf('visitor-1').crossing?.decidedBy).toBe('program');
    const world = beingOf('visitor-2');
    expect(world.crossing?.decidedBy).toBe('world');
    expect(world.mark.crossing).toMatchObject({ bridge: 'blockgame', decided_by: 'world' });
    mounted.dispose();
  });
});

describe('what a person who came in from outside is, in Selected', () => {
  // Root's ruling (2026-10-08 17:03, from a crossing rehearsal): a being that crossed in is never called
  // invented for this world; the sentence says where it came from, as the door lists its bridge, and
  // who decides for it here, from its arrival's record. Expected words are the catalog's own.
  it('says where each came from and who decides for it, and leaves the world\'s own people as they are', async () => {
    const words = (code: string) => catalog.entries.find((entry) => entry.kind === 'phrase' && entry.code === code)!.words;
    const fill = (text: string, values: Record<string, string>) => text.replace(/\{(\w+)\}/gu, (_all, key: string) => values[key]!);
    server.tick = 4;
    server.people = [
      person('knight-0', { kind: KNIGHT, came_by: 'placed', placed_id: 'knight-1' }),
      person('visitor-1', { kind: KNIGHT, came_by: 'crossed', placed_id: null, crossing: { arrival_id: 'a1', bridge: 'blockgame', grant_id: 'g1' } }),
      person('visitor-2', { kind: KNIGHT, came_by: 'crossed', placed_id: null, crossing: { arrival_id: 'a2', bridge: 'blockgame', grant_id: 'g2', decided_by: 'world' } }),
      person('visitor-3', { kind: KNIGHT, came_by: 'crossed', placed_id: null, crossing: { arrival_id: 'a3', bridge: 'elsewhere', grant_id: 'g3' } }),
    ];
    server.things = [];
    server.events = [];
    const { mounted, shown, crowd } = mount();
    crowd.visibleInhabitantIds = ['knight-0', 'visitor-1', 'visitor-2', 'visitor-3'];
    await mounted.begin();
    await settle();
    const pick = [...document.querySelectorAll('select')].find((one) => one.getAttribute('aria-label') === 'Inspect nearby inhabitant')!;
    const whatOf = (id: string): string => {
      pick.value = id;
      pick.dispatchEvent(new Event('change'));
      return shown.at(-1)!.about.note.description;
    };
    expect(whatOf('visitor-1')).toBe(fill(words('what_crossed_program'), { role: 'steward', from: 'Block Game' }));
    expect(whatOf('visitor-2')).toBe(fill(words('what_crossed_world'), { role: 'steward', from: 'Block Game' }));
    // A bridge the door does not list is not guessed at.
    expect(whatOf('visitor-3')).toBe(fill(words('what_crossed_program'), { role: 'steward', from: words('from_outside') }));
    for (const id of ['visitor-1', 'visitor-2', 'visitor-3']) {
      expect(whatOf(id)).not.toBe(fill(words('what'), { role: 'steward' }));
      expect(whatOf(id)).not.toMatch(/simulated/u);
    }
    expect(whatOf('knight-0')).toBe(fill(words('what'), { role: 'steward' }));
    mounted.dispose();
  });
});
