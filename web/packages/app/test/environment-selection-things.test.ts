// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import type { AtlasScene } from '@exulanica/atlas-core';
import type { PlacedThingRecord, ThingLayerOptions, ThingPick } from '@exulanica/atlas-react/things';
import { mountEnvironmentSelection, type SelectedThing } from '../src/composition/environment-selection.js';
import { parseSociety, type SocietySnapshot } from '../src/society-api.js';
import { parseSocietyControl } from '../src/society-control-api.js';
import { THING_PICK_EVENT, type ThingPickDetail } from '../src/composition/things.js';
import type { AlternateVersion } from '../src/world-objects-api.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';

/*
 * A saved world whose version places things: they are handed to the things layer in the frame its
 * society's region is drawn in, and aiming and pressing E picks the nearer of a thing and a person.
 */

const { FakeLayer, layers } = vi.hoisted(() => {
  const made: InstanceType<typeof Fake>[] = [];
  class Fake {
    placed: readonly PlacedThingRecord[] = [];
    /** How far along the ray the fake's thing stands, metres. */
    distance = 3;
    /** The maker the crowd's figures read the library's looks from. */
    readonly maker = { library: { list: { kinds: [], looks: [] } } };
    society: unknown = null;
    /** Play this one's ring where the played being's walk goes. */
    destination: unknown = null;
    constructor(readonly options: ThingLayerOptions) { made.push(this); }
    setPlayed(_subjectId: string | null) {}
    setDestination(point: unknown) { this.destination = point; }
    setSociety(state: unknown) { this.society = state; }
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
// A click on the world casts the same ray the reticle does, here from the page point.
const { pointerRay } = vi.hoisted(() => ({
  pointerRay: vi.fn((_source: unknown, _x: number, _y: number) => ({ origin: [0, 1.68, 4] as const, direction: [0, 0, -1] as const })),
}));
vi.mock('@exulanica/atlas-react/playcanvas', async (original) => ({
  ...(await original<typeof import('@exulanica/atlas-react/playcanvas')>()),
  pointerRay,
}));

// Play this one's routes: the minute offers the person's walk to a spot they choose (THINGS 3p.1).
const { playClient } = vi.hoisted(() => ({
  playClient: {
    start: vi.fn(async () => undefined),
    giveBack: vi.fn(async () => undefined),
    turn: vi.fn(async () => ({
      subjectId: 'person-0', baseTick: 3, lineCharactersMaximum: 120, played: true, playedByYou: true,
      quietMinutes: 5, quietLeft: 5, nextDueAt: null, minuteMs: null,
      options: [
        { label: 'wait a moment', kind: 'wait', targetId: null, beingId: null, takesLine: false, takesPoint: false },
        { label: 'walk to a spot you choose', kind: 'point', targetId: null, beingId: null, takesLine: false, takesPoint: true },
      ],
    })),
    answer: vi.fn(async () => ({ baseTick: 3, answerSeq: 1 })),
  },
}));
vi.mock('../src/society-play-api.js', async (original) => ({
  ...(await original<typeof import('../src/society-play-api.js')>()),
  SocietyPlayClient: class { constructor() { return playClient; } },
}));

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

function mount(withSociety = false, scene: { readonly nothingPlaced?: boolean; readonly everyoneIndoors?: boolean } = {}) {
  const missing = () => new ApiError(404, 'unknown_reference', 'no such society');
  const regionEntity = { name: 'authored-region:region:starter' };
  const crowd = {
    root: { parent: regionEntity },
    setSociety: vi.fn(() => 0), clearSociety: vi.fn(), revealInhabitant: vi.fn(), setFigures: vi.fn(), societyJumps: [],
    visibleInhabitantIds: scene.nothingPlaced === true ? [] : ['person-0'], inhabitantRepresentation: vi.fn(() => null),
    inhabitantDetail: vi.fn(() => 'near'), coincidentInhabitants: vi.fn(() => ['person-0']),
    societyCounts: { population: 1, outdoors: 1, indoors: 0, near: 1, far: 0, drawn: 1 },
    drawnInhabitantCount: 1, inhabitantSeatAtPlace: vi.fn(() => false), setSeatingLayout: vi.fn(), seatingMisses: [],
    // A person stands 5 m along the ray: picked only when nothing nearer stands in front.
    pickInhabitant: vi.fn((_o: unknown, _d: unknown, limit = Number.POSITIVE_INFINITY) => (limit > 5 ? 'person-0' : null)),
    // A looks read asks the crowd again for its things' figures.
    refreshFigures: vi.fn(),
  };
  const controls = {
    state: { x: 0, y: 1.68, z: 4 }, onInteract: vi.fn() as (() => void) | null, forward: () => ({ x: 0, y: 0, z: -1 }),
    onPointerPick: null as ((clientX: number, clientY: number) => boolean) | null,
  };
  const binding = {
    app: { app: true }, camera: { forward: { x: 0, y: 0, z: -1 } }, controls, invalidate: vi.fn(),
    interactionRay: () => ({ origin: [0, 1.68, 4] as const, direction: [0, 0, -1] as const }),
    regionRoots: new Map(), ownedDistrict: null, generatedTile: null, authoredSociety: crowd,
    memoryLayerVisible: false, onMemoryLayerChange: null,
  };
  const societyClient = {
    read: vi.fn(async () => {
      if (!withSociety) throw missing();
      const read = thingsSociety();
      if (scene.everyoneIndoors !== true) return read;
      // As a state that says who is indoors reaches the page: every one of its people inside.
      return { ...read, state: { ...read.state, inhabitants: read.state.inhabitants.map((person) => ({ ...person, indoors: true })) } };
    }),
    create: vi.fn(), connect: vi.fn(), advance: vi.fn(), events: vi.fn(async () => []),
  };
  const control = (mode: 'paused' | 'playing' = 'paused') => parseSocietyControl({
    profile: 'exulanica.society-control/v1', society_id: 'society', branch_id: 'version', persisted: false,
    revision: 0, mode, speed: 1, base_tick_interval_ms: 1000, tick_interval_ms: 1000,
    interval_semantics: 'minimum_wait_after_batch_completion', last_batch_execution: null,
    simulated_seconds_per_tick: 60, max_catchup_ticks: 3, next_due_at: null, reason: null,
    lease_expires_at: null, last_event_seq: 0, current_tick: 3, state_sha256: '3'.repeat(64),
    play_ineligible_reason: null, play_eligible: true,
  }, 'version');
  const controlClient = { read: vi.fn(async () => { if (!withSociety) throw missing(); return control(); }), configure: vi.fn(async () => control('playing')), step: vi.fn() };
  const placed = scene.nothingPlaced === true ? { ...version, things: [] } as unknown as AlternateVersion : version;
  const worldClient = { connect: vi.fn(async () => ({ assets: [], version: placed })), assets: vi.fn(() => []) };
  const modelsClient = { read: vi.fn(async () => { throw missing(); }), choose: vi.fn() };
  const canvas = document.createElement('canvas');
  const shell = document.createElement('div');
  const showStatus = vi.fn();
  const holdStatus = vi.fn();
  // The shell is in the page, as the application's is, so a pick raised on it reaches the document.
  document.body.replaceChildren(shell);
  const mounted = mountEnvironmentSelection({
    env: { canvas, shell, preview: false, systemReducedMotion: { matches: false } } as unknown as AppEnvironment,
    state: {
      atlas: { binding },
      activeWorldEntry: { worldId: WORLD, authoredVersionId: 'version', title: 'My world',
        authoredScene: { region: { regionId: 'region:starter' } } },
    } as unknown as SessionState,
    scene: { islands: [] } as unknown as AtlasScene,
    credentials: { baseUrl: 'https://example.test', token: 'token' },
    showStatus, holdStatus, admissionId: null,
    worldClient: worldClient as never, societyClient: societyClient as never, societyControlClient: controlClient as never,
    societyModelsClient: modelsClient as never,
    // No look is chosen for any thing here.
    thingLooksClient: { read: vi.fn(async () => new Map()) },
  });
  document.body.append(mounted.root);
  return { mounted, crowd, controls, canvas, shell, regionEntity, binding, showStatus, holdStatus };
}

describe('a saved world\'s placed things', () => {
  it('are handed to the layer in the society\'s region frame, and E picks the nearer of a thing and a person', async () => {
    const { mounted, crowd, controls, canvas, shell, regionEntity } = mount();
    await mounted.begin();
    const layer = layers.at(-1)!;
    expect(layer.placed.map((one) => [one.thingId, one.regionId, one.transform.zMm])).toEqual([['well-1', 'region:starter', -3000]]);
    expect(layer.options.regionRoot('region:starter')).toBe(regionEntity);
    expect(layer.options.regionRoot('region:elsewhere')).toBeNull();
    expect(canvas.dataset['thingsDrawn']).toBe('1');
    const heard: ThingPickDetail[] = [];
    shell.addEventListener(THING_PICK_EVENT, (event) => heard.push((event as CustomEvent<ThingPickDetail>).detail));
    // The well stands 3 m along the ray, in front of the person at 5 m: the well is picked.
    controls.onInteract!();
    expect(crowd.pickInhabitant.mock.calls.at(-1)![2]).toBe(3);
    expect(heard).toEqual([{ placedId: 'well-1', thingId: null, subjectId: null, via: 'aim' }]);
    // With the well behind the person, the person is picked and no thing event is raised.
    layer.distance = 9;
    controls.onInteract!();
    expect(heard).toHaveLength(1);
    expect(crowd.pickInhabitant.mock.results.at(-1)!.value).toBe('person-0');
    mounted.dispose();
    expect(canvas.dataset['thingsDrawn']).toBeUndefined();
  });

  it('draws a society of things\' things through the crowd by their looks, and its objects as the state says', async () => {
    const { mounted, crowd } = mount(true);
    await mounted.begin();
    for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
    const layer = layers.at(-1)!;
    expect(crowd.setSociety).toHaveBeenCalled();
    // The crowd draws the society's things by the figures the things layer makes for them, once.
    expect(crowd.setFigures).toHaveBeenCalledTimes(1);
    const figures = crowd.setFigures.mock.calls[0]![0] as { figureFor(person: unknown): unknown };
    expect(typeof figures.figureFor).toBe('function');
    // The layer is told what the state says of the things.
    expect((layer.society as { things: { placed_id: string }[] }).things.map((thing) => thing.placed_id)).toEqual(['well-1']);
    mounted.dispose();
  });

  it('picks by a click on the world as E does, never while a surface holds the world, and lets go on dispose', async () => {
    const { mounted, crowd, controls, shell, binding } = mount();
    pointerRay.mockClear();
    await mounted.begin();
    const layer = layers.at(-1)!;
    const heard: ThingPickDetail[] = [];
    shell.addEventListener(THING_PICK_EVENT, (event) => heard.push((event as CustomEvent<ThingPickDetail>).detail));
    expect(controls.onPointerPick).not.toBeNull();
    // A click over the well takes the click (no camera look) and raises the pick as a pointer's.
    expect(controls.onPointerPick!(640, 400)).toBe(true);
    expect(pointerRay).toHaveBeenLastCalledWith(binding, 640, 400);
    expect(heard).toEqual([{ placedId: 'well-1', thingId: null, subjectId: null, via: 'pointer' }]);
    // The person nearer than the well is picked instead, by the same nearest-wins rule.
    layer.distance = 9;
    expect(controls.onPointerPick!(640, 400)).toBe(true);
    expect(crowd.pickInhabitant.mock.results.at(-1)!.value).toBe('person-0');
    // While a sheet is modal on the world, a click picks nothing and is left to camera look.
    const sheet = document.createElement('section');
    sheet.setAttribute('aria-modal', 'true');
    document.body.append(sheet);
    expect(controls.onPointerPick!(640, 400)).toBe(false);
    sheet.remove();
    mounted.dispose();
    expect(controls.onPointerPick).toBeNull();
  });

  it('opens a picked thing that is nobody in Selected through the card\'s view, and stops listening on dispose', async () => {
    const { mounted, shell } = mount();
    await mounted.begin();
    const root = document.createElement('section');
    const view = { root, show: vi.fn(() => true), showThing: vi.fn((_thing: SelectedThing) => true), hide: vi.fn() };
    mounted.useInhabitantView(view);
    shell.dispatchEvent(new CustomEvent<ThingPickDetail>(THING_PICK_EVENT, {
      bubbles: true, detail: { placedId: 'well-1', thingId: null, subjectId: null, via: 'aim' },
    }));
    expect(view.showThing).toHaveBeenCalledOnce();
    expect(view.showThing.mock.calls[0]![0]).toMatchObject({ worldId: WORLD, versionId: 'version', placed: { thingId: 'well-1', kind: KIND } });
    // No society of things is drawn here, so it has no society id for its served card.
    expect(view.showThing.mock.calls[0]![0].societyThingId).toBeNull();
    expect(root.hidden).toBe(false);
    expect(mounted.root.querySelector<HTMLElement>('.living-world-inspector')!.hidden).toBe(true);
    // A thing the version no longer places, and the ring's own clearing, open nothing.
    shell.dispatchEvent(new CustomEvent<ThingPickDetail>(THING_PICK_EVENT, {
      bubbles: true, detail: { placedId: 'gone', thingId: null, subjectId: null, via: 'aim' },
    }));
    shell.dispatchEvent(new CustomEvent<ThingPickDetail>(THING_PICK_EVENT, { bubbles: true, detail: null }));
    expect(view.showThing).toHaveBeenCalledOnce();
    mounted.dispose();
    shell.dispatchEvent(new CustomEvent<ThingPickDetail>(THING_PICK_EVENT, {
      bubbles: true, detail: { placedId: 'well-1', thingId: null, subjectId: null, via: 'aim' },
    }));
    expect(view.showThing).toHaveBeenCalledOnce();
  });

  it('hands the card the id the drawn society of things gives a picked placed thing, for its served card', async () => {
    const { mounted, shell } = mount(true);
    await mounted.begin();
    for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
    const view = { root: document.createElement('section'), show: vi.fn(() => true), showThing: vi.fn((_thing: SelectedThing) => true), hide: vi.fn() };
    mounted.useInhabitantView(view);
    shell.dispatchEvent(new CustomEvent<ThingPickDetail>(THING_PICK_EVENT, {
      bubbles: true, detail: { placedId: 'well-1', thingId: null, subjectId: null, via: 'pointer' },
    }));
    // The state's thing whose placed id is the pick's: 't-well' in thingsSociety above.
    expect(view.showThing.mock.calls[0]![0]).toMatchObject({ placed: { thingId: 'well-1' }, societyThingId: 't-well' });
    mounted.dispose();
  });

  it('while a being is played, walks it to a click on open ground and rings the spot', async () => {
    const { mounted, crowd, controls } = mount(true);
    await mounted.begin();
    for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
    const layer = layers.at(-1)!;
    // The click meets neither the well nor the person: it comes down to the ground.
    layer.distance = Number.POSITIVE_INFINITY;
    layer.placed = [];
    crowd.pickInhabitant.mockImplementation(() => null);
    const groundPoint = vi.fn(() => ({ xMm: 1200, zMm: -800 }));
    Object.assign(crowd, { groundPoint });
    // Not playing, a click on open ground is left to looking around.
    expect(controls.onPointerPick!(640, 400)).toBe(false);
    await mounted.play('person-0');
    expect(controls.onPointerPick!(640, 400)).toBe(true);
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    expect(groundPoint).toHaveBeenCalledWith([0, 1.68, 4], [0, 0, -1]);
    expect(playClient.answer).toHaveBeenLastCalledWith('version', 'person-0', 3, 'walk to a spot you choose', null, { xMm: 1200, zMm: -800 });
    expect(layer.destination).toEqual({ xMm: 1200, zMm: -800 });
    mounted.dispose();
  });

  it('keeps saying how to let a paused world with people run, until this browser has seen it play', async () => {
    window.localStorage.clear();
    const first = mount(true);
    await first.mounted.begin();
    for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
    // Held, not a passing toast: a judge looking at the town still finds it.
    expect(first.holdStatus).toHaveBeenCalledWith('The world is paused. Press Play to let it run.');
    expect(first.showStatus).not.toHaveBeenCalledWith('The world is paused. Press Play to let it run.');
    first.mounted.dispose();
    // Once this browser has seen the world play, it is not said for it again.
    window.localStorage.setItem(`exulanica.paused-hint.${WORLD}`, '1');
    const again = mount(true);
    await again.mounted.begin();
    for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
    expect(again.holdStatus).not.toHaveBeenCalledWith('The world is paused. Press Play to let it run.');
    again.mounted.dispose();
  });

  it('says where the people are when nothing is placed and nobody is in sight, beside the paused line', async () => {
    window.localStorage.clear();
    const { mounted, holdStatus } = mount(true, { nothingPlaced: true });
    await mounted.begin();
    for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
    expect(holdStatus).toHaveBeenLastCalledWith(
      'The world is paused. Press Play to let it run. People are out in the town: open People to find them.');
    mounted.dispose();
    expect(holdStatus).toHaveBeenLastCalledWith(null);
  });

  it('says everyone is indoors, not out in the town, where the state says nobody is outdoors', async () => {
    window.localStorage.clear();
    const { mounted, holdStatus } = mount(true, { nothingPlaced: true, everyoneIndoors: true });
    await mounted.begin();
    for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
    expect(holdStatus).toHaveBeenLastCalledWith(
      'The world is paused. Press Play to let it run. Everyone is indoors just now: open People to see where they are.');
    expect(holdStatus).not.toHaveBeenCalledWith(expect.stringContaining('People are out in the town'));
    mounted.dispose();
  });

  it('takes the paused line away as soon as the world plays, by the Play write itself', async () => {
    window.localStorage.clear();
    const { mounted, holdStatus } = mount(true);
    await mounted.begin();
    for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
    expect(holdStatus).toHaveBeenLastCalledWith('The world is paused. Press Play to let it run.');
    await mounted.people.play();
    expect(holdStatus).toHaveBeenLastCalledWith(null);
    mounted.dispose();
  });
});
