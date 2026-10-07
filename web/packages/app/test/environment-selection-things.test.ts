// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import type { AtlasScene } from '@exulanica/atlas-core';
import type { PlacedThingRecord, ThingLayerOptions, ThingPick } from '@exulanica/atlas-react/things';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
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
    constructor(readonly options: ThingLayerOptions) { made.push(this); }
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

function mount() {
  const missing = () => new ApiError(404, 'unknown_reference', 'no such society');
  const regionEntity = { name: 'authored-region:region:starter' };
  const crowd = {
    root: { parent: regionEntity },
    setSociety: vi.fn(() => 0), clearSociety: vi.fn(), revealInhabitant: vi.fn(),
    visibleInhabitantIds: ['person-0'], inhabitantRepresentation: vi.fn(() => null),
    inhabitantDetail: vi.fn(() => 'near'), coincidentInhabitants: vi.fn(() => ['person-0']),
    societyCounts: { population: 1, outdoors: 1, indoors: 0, near: 1, far: 0, drawn: 1 },
    drawnInhabitantCount: 1, inhabitantSeatAtPlace: vi.fn(() => false), setSeatingLayout: vi.fn(), seatingMisses: [],
    // A person stands 5 m along the ray: picked only when nothing nearer stands in front.
    pickInhabitant: vi.fn((_o: unknown, _d: unknown, limit = Number.POSITIVE_INFINITY) => (limit > 5 ? 'person-0' : null)),
  };
  const controls = { state: { x: 0, y: 1.68, z: 4 }, onInteract: vi.fn() as (() => void) | null, forward: () => ({ x: 0, y: 0, z: -1 }) };
  const binding = {
    app: { app: true }, camera: { forward: { x: 0, y: 0, z: -1 } }, controls, invalidate: vi.fn(),
    regionRoots: new Map(), ownedDistrict: null, generatedTile: null, authoredSociety: crowd,
    memoryLayerVisible: false, onMemoryLayerChange: null,
  };
  const societyClient = {
    read: vi.fn(async () => { throw missing(); }), create: vi.fn(), connect: vi.fn(), advance: vi.fn(), events: vi.fn(async () => []),
  };
  const controlClient = { read: vi.fn(async () => { throw missing(); }), configure: vi.fn(), step: vi.fn() };
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
  });
  document.body.append(mounted.root);
  return { mounted, crowd, controls, canvas, shell, regionEntity };
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
});
