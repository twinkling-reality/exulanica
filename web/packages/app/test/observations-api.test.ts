/** The whole-graph inspector must never mistake a page for missing recorded evidence. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ObservationsClient } from '../src/observations-api.js';

const SCENE = '851ca35b-31c3-560c-84f9-4e142962755b';
function whole() {
  return {
    profile: 'exulanica.scene-sparse-observations/v1', scene_id: SCENE,
    provenance: 'recorded', method: 'recorded tracks', sampling: 'bounded sample',
    retained_per_image: 4096, point_count: 1,
    bounds: {
      state: 'complete', after_point_id: null as number | null, next_point_id: null as number | null,
      point_count_total: 1, point_count_returned: 1, point_count_not_returned: 0,
      observations_total: 1, observations_returned: 1,
    },
    points: [{ point_id: 4, world_xyz: ['1.5', '2', '3'], track_length: 40,
      observations_retained: 1, observations: [{ capture_id: 'capture-a', x: '12.5', y: '20',
        reprojection_error_px: '0.1', consent: { basis: 'human-screening-receipt', person_consent: 'unscreened' },
      }],
    }],
  };
}
function respond(body: unknown, status = 200) {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
const load = () => new ObservationsClient({ baseUrl: 'https://example.test', token: 'session-token' }).load(SCENE);
afterEach(() => vi.unstubAllGlobals());

describe('whole observation graph contract', () => {
  it('requests one whole graph and keeps the full track count beside retained evidence', async () => {
    const fetch = respond(whole());
    const graph = await load();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]![0]).toBe(`https://example.test/world-read/scenes/${SCENE}/observations`);
    expect(fetch.mock.calls[0]![1].headers.authorization).toBe('Bearer session-token');
    expect(graph.points).toEqual([{ pointId: 4, world: [1.5, 2, 3], trackLength: 40, observationsRetained: 1 }]);
    expect(graph.observedBy.get(4)?.[0]?.consent.personConsent).toBe('unscreened');
  });

  it('rejects a page before the inspector can treat missing points as absent evidence', async () => {
    const wire = whole();
    wire.bounds.state = 'page';
    wire.bounds.point_count_total = 2;
    wire.bounds.point_count_not_returned = 1;
    wire.bounds.next_point_id = 4;
    respond(wire);
    await expect(load()).rejects.toMatchObject({ kind: 'unreadable' });
  });

  it('rejects an answer whose completeness was never stated', async () => {
    const { bounds: _bounds, ...wire } = whole();
    respond(wire);
    await expect(load()).rejects.toMatchObject({ kind: 'unreadable' });
  });

  it.each(['point_count_total', 'point_count_returned', 'point_count_not_returned',
    'observations_total', 'observations_returned'] as const)('rejects inconsistent %s', async (field) => {
    const wire = whole(); wire.bounds[field] += 1; respond(wire);
    await expect(load()).rejects.toMatchObject({ kind: 'unreadable' });
  });

  it('rejects duplicate points that would overwrite their recorded photographs', async () => {
    const wire = whole(); wire.points.push(structuredClone(wire.points[0]!));
    wire.point_count = wire.bounds.point_count_total = wire.bounds.point_count_returned = 2;
    wire.bounds.observations_total = wire.bounds.observations_returned = 2;
    respond(wire);
    await expect(load()).rejects.toMatchObject({ kind: 'unreadable' });
  });

  it('rejects another scene instead of caching its evidence under this scene', async () => {
    const wire = whole(); wire.scene_id = '00000000-0000-0000-0000-000000000001'; respond(wire);
    await expect(load()).rejects.toMatchObject({ kind: 'unreadable' });
  });

  it.each(['', ' ', 'NaN', 'Infinity'])('rejects malformed coordinate %j', async (coordinate) => {
    const wire = whole(); wire.points[0]!.world_xyz[0] = coordinate; respond(wire);
    await expect(load()).rejects.toThrow();
  });

  it('preserves withdrawal instead of publishing an empty graph', async () => {
    respond({ code: 'tombstoned', detail: 'withdrawn' }, 410);
    await expect(load()).rejects.toMatchObject({ kind: 'withdrawn' });
  });
});
