import { describe, expect, it } from 'vitest';

import { ExulanicaClient, adaptSnapshot } from '../src/index.js';
import type { GraphPayload } from '../src/index.js';
import { GROUP, PAYLOAD, WITH_UNGROUPED } from './graph-payload.js';

/**
 * A made world's regions against the groups the grouping holds now.
 *
 * Scene grouping never retires a row it wrote before, so a place photographed again is held by
 * the group the world was made from AND a later group holding the new photograph too. The default
 * puts every photograph in the later group, whose id is no region of the world. The world's own
 * regions come from `GET /world/source-media` and are read through the client, the way the app
 * reads them, rather than handed to the adapter.
 */
describe('a world made from photographs keeps its regions as islands', () => {
  const madeGroup = { ...GROUP, group_id: 'region-made', capture_ids: ['c1', 'c2'] };
  const laterGroup = {
    ...GROUP, group_id: 'group-later', capture_ids: ['c1', 'c2', 'c4'], member_count: 3,
  };
  const regrouped: GraphPayload = { ...PAYLOAD, scene_groups: [madeGroup, laterGroup] };
  const madeRegions = new Map([['c1', 'region-made'], ['c2', 'region-made']]);

  const clientServing = (
    payload: GraphPayload,
    worldRegions?: () => ReadonlyMap<string, string> | undefined,
  ) => {
    const reads: string[] = [];
    const client = new ExulanicaClient({
      baseUrl: 'https://example.invalid',
      token: 't',
      ...(worldRegions === undefined ? {} : { worldRegions }),
      fetch: async (url) => {
        reads.push(new URL(String(url)).pathname);
        return new Response(JSON.stringify(payload), {
          status: 200, headers: { 'content-type': 'application/json' },
        });
      },
    });
    return { client, reads };
  };

  it('loses the made region to the later group when nothing names the world (the control)', async () => {
    const { client } = clientServing(regrouped);
    const snapshot = await client.snapshot();
    expect(snapshot.islands.map((island) => island.islandId)).toEqual(['group-later']);
  });

  it('keeps the photographs the world holds in its region, and the rest in their group', async () => {
    const { client } = clientServing(regrouped, () => madeRegions);
    const snapshot = await client.snapshot();
    expect(snapshot.islands.map((island) => [island.islandId, island.captureIds])).toEqual([
      ['region-made', ['c1', 'c2']],
      ['group-later', ['c4']],
    ]);
    expect(snapshot.occurrences.map((row) => row.islandId)).toEqual(['region-made', 'region-made']);
    expect(snapshot.entities[0]!.islandIds).toEqual(['region-made']);
  });

  it('keeps a made photograph the groups no longer hold in the region it was placed in', async () => {
    const { client } = clientServing(
      { ...WITH_UNGROUPED, scene_groups: [madeGroup] },
      () => new Map([...madeRegions, ['c3', 'region-made']]),
    );
    const snapshot = await client.snapshot();
    expect(snapshot.occurrences.map((row) => row.islandId))
      .toEqual(['region-made', 'region-made', 'region-made']);
    expect(snapshot.islands.map((island) => island.islandId)).toEqual(['region-made']);
  });

  it('draws exactly what the grouping draws when the world was made from the groups there are', async () => {
    // The guard against the rule changing the ordinary case: nothing regrouped, so the world's
    // region IS the group, and it keeps the group's spread, rung and times.
    const { client } = clientServing(PAYLOAD, () => new Map([['c1', 'g1'], ['c2', 'g1']]));
    expect(await client.snapshot()).toEqual(adaptSnapshot(PAYLOAD));
  });

  it('asks for the regions at every read, because the world is opened after the session', async () => {
    let regions: ReadonlyMap<string, string> | undefined;
    const { client, reads } = clientServing(regrouped, () => regions);
    expect((await client.snapshot()).islands.map((island) => island.islandId))
      .toEqual(['group-later']);
    regions = madeRegions;
    expect((await client.snapshot()).islands.map((island) => island.islandId))
      .toEqual(['region-made', 'group-later']);
    expect(reads).toEqual(['/graph', '/graph']);
  });

  it('refuses an island rule and a world\'s regions together', () => {
    expect(() => new ExulanicaClient({
      baseUrl: 'https://example.invalid', token: 't',
      islandOf: (captureId) => captureId as never,
      worldRegions: () => madeRegions,
    })).toThrow(TypeError);
  });
});
