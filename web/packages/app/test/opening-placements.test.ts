// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ExulanicaClient, type GraphPayload } from '@exulanica/graph-client';
import { openingIsland } from '@exulanica/atlas-react/playcanvas';

import { buildScene } from '../src/scene.js';
import type { AlternateVersion } from '../src/world-objects-api.js';

/**
 * A made world opens where the person's things are, read from the version the page already reads.
 *
 * The made place photographed again is held by two live groups, so its island carries no single
 * group's time and sorts after the place the addition made. Island order stays as it is (it also
 * decides the layout and the island cut); the opening region is chosen from the version's
 * placements instead.
 */

const read = vi.hoisted(() => ({
  version: null as unknown,
  failure: null as Error | null,
  created: [] as unknown[],
}));

vi.mock('../src/world-objects-api.js', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/world-objects-api.js')>();
  return {
    ...actual,
    WorldObjectsClient: class {
      async readVersion() {
        if (read.failure !== null) throw read.failure;
        return read.version;
      }
    },
  };
});

vi.mock('@exulanica/atlas-react/playcanvas', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@exulanica/atlas-react/playcanvas')>();
  return {
    ...actual,
    AtlasBinding: {
      create: async (options: unknown) => {
        read.created.push(options);
        throw new Error('the options were captured');
      },
    },
  };
});

const { loadAuthoredPointMaps, placementRegionIds } = await import(
  '../src/composition/session-and-geometry.js'
);
const { createSessionState } = await import('../src/composition/session-state.js');
const { mountAtlas } = await import('../src/atlas.js');

beforeEach(() => {
  read.version = null;
  read.failure = null;
  read.created = [];
});

const placed = (regionId: string, removed = false) => ({ regionId, removed });

/** A version holding these placements; nothing else in it is read by the opening rule. */
function version(placements: {
  objects?: readonly ReturnType<typeof placed>[];
  environment?: readonly ReturnType<typeof placed>[];
  estimates?: readonly ReturnType<typeof placed>[];
}): AlternateVersion {
  return {
    objects: placements.objects ?? [],
    environmentInstances: placements.environment ?? [],
    pointMapInstances: (placements.estimates ?? []).map((row) => ({ ...row, availability: 'withdrawn' })),
  } as unknown as AlternateVersion;
}

describe('the placements a version names', () => {
  it('names the region of every placement the person made and has not removed', () => {
    expect(placementRegionIds(version({
      objects: [placed('region-kept'), placed('region-new', true)],
      environment: [placed('region-kept')],
      estimates: [placed('region-third')],
    }))).toEqual(['region-kept', 'region-kept', 'region-third']);
  });

  it('are read from the version the page reads before the renderer, and are unknown when it fails', async () => {
    const state = createSessionState();
    state.activeWorldEntry = { worldId: 'world:made', authoredVersionId: 'version-1' } as never;
    const where = { baseUrl: 'https://example.invalid', token: 't' };

    read.version = version({ objects: [placed('region-kept')] });
    await loadAuthoredPointMaps(state, where);
    expect(state.placementRegionIds).toEqual(['region-kept']);

    read.failure = new Error('the read failed');
    await loadAuthoredPointMaps(state, where);
    expect(state.placementRegionIds).toBeUndefined();
  });

  it('reach the binding the renderer creates', async () => {
    const scene = buildScene((await clientServing(ADDED).snapshot()), 1).scene;
    await expect(mountAtlas(
      document.createElement('canvas'), document.createElement('div'), scene, undefined,
      { theme: 'light' as never, fieldOfView: 70, mouseSensitivity: 1, placementRegionIds: ['region-kept'] },
    )).rejects.toThrow('the options were captured');
    expect((read.created[0] as { placementRegionIds?: unknown }).placementRegionIds)
      .toEqual(['region-kept']);
  });
});

const group = (groupId: string, captureIds: readonly string[], hour: number) => ({
  group_id: groupId, ordinal: 0, capture_ids: [...captureIds],
  first_utc: `2026-09-24T${String(hour).padStart(2, '0')}:00:00+00:00`,
  last_utc: `2026-09-24T${String(hour).padStart(2, '0')}:03:00+00:00`,
  member_count: captureIds.length, positioned_member_count: 0, radius_m: null,
  centroid_lat_e7: null, centroid_lon_e7: null, rung: null, rung_capture_count: 0,
});

const KEPT = ['c1', 'c2', 'c3'];

/** The made place photographed again as c4, and a new place of `fresh`; both group rows of the made place are live. */
function added(fresh: readonly string[]): GraphPayload {
  return {
    state_version: 4, entities: [], occurrences: [], proposals: [],
    scene_groups: [
      group('region-kept', KEPT, 9),
      group('group-later', [...KEPT, 'c4'], 12),
      group('region-new', fresh, 12),
    ],
    reconstruction_scenes: [], never_same: [], deleted_entity_ids: [],
  };
}
const ADDED = added(['c5', 'c6', 'c7']);

function clientServing(payload: GraphPayload): ExulanicaClient {
  const regions = new Map<string, string>([
    ...[...KEPT, 'c4'].map((capture) => [capture, 'region-kept'] as const),
    ...payload.scene_groups.find((row) => row.group_id === 'region-new')!.capture_ids
      .map((capture) => [capture, 'region-new'] as const),
  ]);
  return new ExulanicaClient({
    baseUrl: 'https://example.invalid',
    token: 't',
    worldRegions: () => regions,
    fetch: async () => new Response(JSON.stringify(payload), {
      status: 200, headers: { 'content-type': 'application/json' },
    }),
  });
}

describe('a made world after photographs were added', () => {
  const cube = version({ objects: [placed('region-kept')] });

  it('orders the place the addition made first (the reason a rule is needed)', async () => {
    const { scene } = buildScene(await clientServing(ADDED).snapshot(), 1);
    expect(scene.islands.map((island) => island.islandId)).toEqual(['region-new', 'region-kept']);
  });

  it('opens where the object stands, and leaves the island order as it was', async () => {
    const { scene } = buildScene(await clientServing(ADDED).snapshot(), 1);
    const order = scene.islands.map((island) => [island.islandId, island.placement]);

    expect(openingIsland(scene, placementRegionIds(cube))?.islandId).toBe('region-kept');
    expect(scene.islands.map((island) => [island.islandId, island.placement])).toEqual(order);
  });

  it('still opens there after an addition larger than the place the object stands in', async () => {
    const fresh = Array.from({ length: 9 }, (_, index) => `n${index}`);
    const { scene } = buildScene(await clientServing(added(fresh)).snapshot(), 1);

    expect(scene.islands[0]!.islandId).toBe('region-new');
    expect(openingIsland(scene, placementRegionIds(cube))?.islandId).toBe('region-kept');
  });

  it('opens in the first island when the object was removed', async () => {
    const { scene } = buildScene(await clientServing(ADDED).snapshot(), 1);
    const removed = version({ objects: [placed('region-kept', true)] });
    expect(openingIsland(scene, placementRegionIds(removed))?.islandId).toBe('region-new');
  });
});
