// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { GraphPayload } from '@exulanica/graph-client';

import type { SavedWorldEntry } from '../src/world-entry-api.js';

/**
 * A made world opens with its own regions as islands, whatever the scene groups say now.
 *
 * Grouping never retires a row, so after a place is photographed again the graph holds the group
 * the world was made from and a later group holding the new photograph too, and the default island
 * rule takes the later one. The world's regions arrive with its source media, after the session's
 * first graph read, so opening the world has to read the graph again with them.
 */

const ENTRY: SavedWorldEntry = {
  entryId: 'entry-1', worldId: 'world:made', title: 'Made world', sourceKind: 'personal',
  sourceSnapshotId: 'snapshot-made', sourceSnapshotSha256: 'a'.repeat(64),
  authoredScene: null, authoredVersionId: 'version-1', authoredStateSha256: 'b'.repeat(64),
  authoredEditSeq: 1, currentAuthoredStateSha256: 'b'.repeat(64),
  currentAuthoredEditSeq: 1, styleVersionId: 'style-saved', revision: 2,
  availability: 'available', unavailableReason: null, sourceAttachments: [],
  createdAt: '2026-09-24T00:00:00Z', updatedAt: '2026-09-24T00:00:00Z',
};

const group = (groupId: string, captureIds: readonly string[]) => ({
  group_id: groupId, ordinal: 0, capture_ids: [...captureIds],
  first_utc: '2026-09-24T12:00:00+00:00', last_utc: '2026-09-24T12:03:00+00:00',
  member_count: captureIds.length, positioned_member_count: 0, radius_m: null,
  centroid_lat_e7: null, centroid_lon_e7: null, rung: null, rung_capture_count: 0,
});

/** The made place {c1, c2} photographed again as c4: both group rows are live. */
const GRAPH: GraphPayload = {
  state_version: 3, entities: [], occurrences: [], proposals: [],
  scene_groups: [group('region-made', ['c1', 'c2']), group('group-later', ['c1', 'c2', 'c4'])],
  reconstruction_scenes: [], never_same: [], deleted_entity_ids: [],
};

const slot = (sourceId: string, regionId: string | null, captureIds: readonly string[]) => ({
  source_id: sourceId, slot_key: sourceId, region_id: regionId, capture_ids: [...captureIds],
  state: 'unavailable_asset', reason: 'its personal authorization or human review is no longer current',
  evidence_span_id: `span-${sourceId}`, evidence_path: null, modality: 'frame_region',
  media_type: 'image/jpeg', byte_size: 2, width: 8, height: 6,
  captured_at: '2026-09-24T12:00:00Z', captured_at_uncertainty_ms: 0, asset_reference: null,
});

const served = vi.hoisted(() => ({
  reads: [] as string[],
  topology: [] as unknown[],
}));

vi.mock('../src/world-style-api.js', () => ({
  WorldStyleContractError: class WorldStyleContractError extends Error {},
  WorldStyleClient: class WorldStyleClient {
    async connect() {
      const current = {
        versionId: 'style-saved',
        topologyDigest: 'style-topology',
        globalStyle: { profileId: 'origin-landscape', profileVersion: 1, parameters: {} },
      };
      return { state: { currentTopologyDigest: 'style-topology', current }, versions: [current] };
    }
  },
}));

vi.mock('../src/world-entry-api.js', async (importOriginal) => ({
  ...await importOriginal<typeof import('../src/world-entry-api.js')>(),
  WorldEntryClient: class WorldEntryClient {
    async entries() { return [ENTRY]; }
  },
}));

import { SourceMediaClient } from '../src/source-media-api.js';
import { createSessionState } from '../src/composition/session-state.js';
import type { AppEnvironment } from '../src/composition/session-state.js';
import { openAppSession, openWorldEntryContext } from '../src/composition/session-and-geometry.js';

const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json' },
});

beforeEach(() => {
  served.reads = [];
  served.topology = [
    slot('s1', 'region-made', ['c1']),
    slot('s2', 'region-made', ['c2']),
  ];
  vi.stubGlobal('fetch', async (input: string | URL | Request) => {
    const path = new URL(String(input)).pathname;
    served.reads.push(path);
    if (path === '/api/graph') return json(GRAPH);
    if (path === '/api/graph/sources') return json([]);
    if (path === '/api/world/source-media') return json(served.topology);
    return json({ code: 'not_found', detail: 'not served here' }, 404);
  });
});

describe('the regions a world names for its photographs', () => {
  const load = async (topology: readonly unknown[]) => {
    served.topology = [...topology];
    return new SourceMediaClient({
      baseUrl: 'https://exulanica.test/api', token: 't',
      worldId: 'world:made', sourceSnapshotId: 'snapshot-made',
    }).load('#000000');
  };

  it('are read from the world topology, available or not', async () => {
    const session = await load([slot('s1', 'region-made', ['c1']), slot('s2', 'region-room', ['c2', 'c3'])]);
    expect([...session.worldRegions]).toEqual([
      ['c1', 'region-made'], ['c2', 'region-room'], ['c3', 'region-room'],
    ]);
  });

  it('leave out a photograph the topology puts in two regions, and a slot with no region', async () => {
    const session = await load([
      slot('s1', 'region-made', ['c1', 'c2']),
      slot('s2', 'region-room', ['c2']),
      slot('s3', null, ['c5']),
    ]);
    expect([...session.worldRegions]).toEqual([['c1', 'region-made']]);
  });
});

describe('opening a made world', () => {
  const env = { preview: false } as unknown as AppEnvironment;
  const graphReads = () => served.reads.filter((path) => path === '/api/graph').length;
  const islandsOf = (state: ReturnType<typeof createSessionState>) => Object.fromEntries(
    (state.snapshot?.islands ?? []).map((island) => [island.islandId, island.captureIds]),
  );

  it('draws the photographs it was made with in its own region', async () => {
    const state = createSessionState();
    await openAppSession(env, state, 'private-token');

    expect(state.activeWorldEntry?.entryId).toBe('entry-1');
    expect(islandsOf(state)).toEqual({ 'region-made': ['c1', 'c2'], 'group-later': ['c4'] });
    // Once for the session, once more when the world's regions arrived.
    expect(graphReads()).toBe(2);
  });

  it('reads the graph no more when the same world opens again', async () => {
    const state = createSessionState();
    await openAppSession(env, state, 'private-token');
    const before = graphReads();

    await openWorldEntryContext(state, ENTRY);

    expect(graphReads()).toBe(before);
    expect(islandsOf(state)).toEqual({ 'region-made': ['c1', 'c2'], 'group-later': ['c4'] });
  });

  it('reads it again when the reopened world holds its photographs elsewhere', async () => {
    const state = createSessionState();
    await openAppSession(env, state, 'private-token');
    const before = graphReads();
    served.topology = [
      slot('s1', 'region-made', ['c1']),
      slot('s2', 'region-made', ['c2']),
      slot('s4', 'region-made', ['c4']),
    ];

    await openWorldEntryContext(state, { ...ENTRY, sourceSnapshotId: 'snapshot-advanced' });

    expect(graphReads()).toBe(before + 1);
    expect(islandsOf(state)).toEqual({ 'region-made': ['c1', 'c2', 'c4'] });
  });
});
