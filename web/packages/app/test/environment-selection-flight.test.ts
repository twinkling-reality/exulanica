// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import type { AtlasScene } from '@exulanica/atlas-core';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import type { SavedWorldFlight, SavedWorldFlightStatus } from '../src/composition/saved-world-flight.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import type { AlternateVersion } from '../src/world-objects-api.js';

/*
 * The open saved world's flight lives as long as the world is open: it starts when the world is
 * attached, is drawn from its first step again after an edit, and stops when the world closes. A
 * page given no flight draws none, and nothing else about the world changes.
 */

const WORLD = 'world:authored:saved';
const version = {
  schemaVersion: 2, versionId: 'version', worldId: WORLD, sourceSnapshotId: 'snapshot', parentVersionId: null,
  title: 'My world', origin: 'authored', styleVersionId: 'style', stateSha256: '1'.repeat(64), editSeq: 0,
  sourceInvalidated: false, createdBy: 'actor', createdAt: '2026-09-25T00:00:00Z',
  objects: [], elementOverrides: [], environmentInstances: [], edits: [],
} as unknown as AlternateVersion;

type FlightFactory = (world: {
  worldId: string;
  versionId: string;
  regionId: string;
  onStatus: (status: SavedWorldFlightStatus) => void;
}) => SavedWorldFlight;

function mount(flight?: FlightFactory) {
  const missing = () => new ApiError(404, 'unknown_reference', 'no such society');
  const crowd = {
    setSociety: vi.fn(() => 0), clearSociety: vi.fn(), visibleInhabitantIds: [],
    societyCounts: { population: 0, outdoors: 0, indoors: 0, near: 0, far: 0, drawn: 0 },
    drawnInhabitantCount: 0, setSeatingLayout: vi.fn(), seatingMisses: [],
  };
  const controls = { state: { x: 0, y: 1.68, z: 4 }, onInteract: null, forward: () => ({ x: 0, y: 0, z: -1 }) };
  const binding = {
    controls, camera: { forward: { x: 0, y: 0, z: -1 } }, invalidate: vi.fn(),
    ownedDistrict: null, generatedTile: null, authoredSociety: crowd,
    memoryLayerVisible: false, onMemoryLayerChange: null,
  };
  const canvas = document.createElement('canvas');
  const mounted = mountEnvironmentSelection({
    env: { canvas, preview: false } as unknown as AppEnvironment,
    state: {
      atlas: { binding },
      activeWorldEntry: { worldId: WORLD, authoredVersionId: 'version', title: 'My world',
        authoredScene: { region: { regionId: 'region:starter' } } },
    } as unknown as SessionState,
    scene: { islands: [] } as unknown as AtlasScene,
    credentials: { baseUrl: 'https://example.test', token: 'token' },
    showStatus: vi.fn(), admissionId: null,
    worldClient: { connect: vi.fn(async () => ({ assets: [], version })), assets: vi.fn(() => []) } as never,
    societyClient: { read: vi.fn(async () => { throw missing(); }), events: vi.fn(async () => []) } as never,
    societyControlClient: { read: vi.fn(async () => { throw missing(); }) } as never,
    ...(flight === undefined ? {} : { flight }),
  });
  document.body.append(mounted.root);
  return Object.assign(mounted, { canvas });
}

describe('a saved world flight', () => {
  it('starts with the world, starts again after an edit, and stops when the world closes', async () => {
    const flight = { start: vi.fn(async () => {}), poll: vi.fn(), restart: vi.fn(async () => {}), stop: vi.fn(), status: {} };
    const factory = vi.fn<FlightFactory>(() => flight as unknown as SavedWorldFlight);
    const mounted = mount(factory);
    await mounted.begin();
    expect(factory).toHaveBeenCalledWith({
      worldId: WORLD, versionId: 'version', regionId: 'region:starter', onStatus: expect.any(Function),
    });
    expect(flight.start).toHaveBeenCalledOnce();
    // A refusal is said in words in the inhabitants panel, and stated on the canvas by its code.
    const onStatus = factory.mock.calls[0]![0].onStatus;
    const words = "Flight stopped: this world's objects would host more flyers than one world may hold.";
    onStatus({
      state: 'refused', flyers: 0, lateHome: 0, failure: 'too_many_flyers',
      unplaced: [{ objectId: 'tree', kind: 'small_bird', count: 3, reason: 'home_perch_unusable' }],
      undrawnKinds: ['small_bird: cc0.small-bird-wing is missing'], refusalWords: words,
    });
    const line = mounted.root.querySelector<HTMLElement>('.world-inhabitants-flight');
    expect([line?.hidden, line?.textContent]).toEqual([false, words]);
    expect({ ...mounted.canvas.dataset }).toMatchObject({
      flightState: 'refused', flightFailure: 'too_many_flyers', flightFlyers: '0',
      flightUnplaced: 'tree:home_perch_unusable', flightUndrawn: 'small_bird: cc0.small-bird-wing is missing',
    });
    onStatus({
      state: 'flying', flyers: 3, lateHome: 0, failure: null, unplaced: [], undrawnKinds: [], refusalWords: null,
    });
    expect([line?.hidden, line?.textContent]).toEqual([true, '']);
    await mounted.afterAuthoredEdit('version');
    expect(flight.restart).toHaveBeenCalledOnce();
    await mounted.afterAuthoredEdit('another-version');
    expect(flight.restart).toHaveBeenCalledOnce();
    mounted.dispose();
    expect(flight.stop).toHaveBeenCalledOnce();
    expect(mounted.canvas.dataset.flightState).toBeUndefined();
  });

  it('draws no flight where the page is given none', async () => {
    const mounted = mount();
    await mounted.begin();
    await mounted.afterAuthoredEdit('version');
    mounted.dispose();
  });
});
