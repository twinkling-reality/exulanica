/** The inspector's two reads: counts for a scene, and one click resolved by the server. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ObservationsClient, type ResolveRequest } from '../src/observations-api.js';

const SCENE = '45ad50b7-aea4-52b4-b6f4-2811b93deb88';
const CAPTURE = '01a0722d-8c7b-791e-b304-ee9c31019f1c';
const REQUEST: ResolveRequest = {
  captureId: CAPTURE, u: 2136, v: 1424.5, tolerancePx: 32.5, occlusionBandPx: 8.125,
};

function summary() {
  return {
    profile: 'exulanica.scene-observation-summary/v1', scene_id: SCENE,
    provenance: 'recorded', method: 'recorded tracks', sampling: 'bounded sample',
    retained_per_image: 4096, point_count_total: 112156, observations_total: 860160,
    note: 'counts only',
  };
}

function observation(captureId: string) {
  return {
    capture_id: captureId, x: '12.500000000000', y: '20.000000000000',
    reprojection_error_px: '0.100000000000',
    consent: { basis: 'human-screening-receipt', person_consent: 'unscreened' },
  };
}

function hit() {
  return {
    profile: 'exulanica.scene-observation-resolve/v1', scene_id: SCENE,
    point_count_total: 112156,
    query: {
      capture_id: CAPTURE, u: '2136.000000000000', v: '1424.500000000000',
      tolerance_px: '32.500000000000', occlusion_band_px: '8.125000000000',
      projection: 'pinhole-approximation',
    },
    state: 'hit' as string,
    point: {
      point_id: 55410, world_xyz: ['1.5', '2', '3'] as [string, string, string], track_length: 40,
      observations_retained: 2, pixel_distance: '3.210000000000', depth: '4.000000000000',
      observations: [observation(CAPTURE), observation('01a0722d-8c7b-791e-b304-ee9c31019f1d')],
    } as Record<string, unknown> | null,
  };
}

function respond(body: unknown, status = 200) {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
const client = () => new ObservationsClient({ baseUrl: 'https://example.test', token: 'session-token' });
afterEach(() => vi.unstubAllGlobals());

describe('the observation summary', () => {
  it('asks for counts, not the graph, and carries the sample bound', async () => {
    const fetch = respond(summary());
    const counts = await client().summary(SCENE);
    expect(fetch.mock.calls[0]![0]).toBe(`https://example.test/world-read/scenes/${SCENE}/observations/summary`);
    expect(fetch.mock.calls[0]![1].headers.authorization).toBe('Bearer session-token');
    expect(counts).toMatchObject({ pointCount: 112156, observationCount: 860160, retainedPerImage: 4096 });
  });

  it.each([
    ['another scene', { scene_id: '00000000-0000-0000-0000-000000000001' }],
    ['no points', { point_count_total: 0 }],
    ['fewer observations than points', { observations_total: 3 }],
    ['an unknown profile', { profile: 'exulanica.scene-sparse-observations/v1' }],
  ])('refuses counts for %s', async (_label, change) => {
    respond({ ...summary(), ...change });
    await expect(client().summary(SCENE)).rejects.toMatchObject({ kind: 'unreadable' });
  });

  it('preserves withdrawal instead of reporting a scene with nothing recorded', async () => {
    respond({ code: 'tombstoned', detail: 'withdrawn' }, 410);
    await expect(client().summary(SCENE)).rejects.toMatchObject({ kind: 'withdrawn' });
  });
});

describe('one click, resolved by the server', () => {
  it('sends the cursor in the photograph and reads one point with who observed it', async () => {
    const fetch = respond(hit());
    const answer = await client().resolve(SCENE, REQUEST);
    const url = new URL(fetch.mock.calls[0]![0] as string);
    expect(url.pathname).toBe(`/world-read/scenes/${SCENE}/observations/resolve`);
    expect(Object.fromEntries(url.searchParams)).toEqual({
      capture_id: CAPTURE, u: '2136', v: '1424.5', tolerance_px: '32.5', occlusion_band_px: '8.125',
    });
    expect(answer.pointCount).toBe(112156);
    expect(answer.hit?.point).toEqual({ pointId: 55410, world: [1.5, 2, 3], trackLength: 40, observationsRetained: 2 });
    expect(answer.hit?.pixelDistance).toBeCloseTo(3.21, 12);
    expect(answer.hit?.projection).toBe('pinhole-approximation');
    expect(answer.hit?.observedBy.map((item) => item.captureId)).toHaveLength(2);
    expect(answer.hit?.observedBy[0]?.consent.personConsent).toBe('unscreened');
  });

  it('reads a miss as an answer rather than as a failure', async () => {
    const wire = hit(); wire.state = 'miss'; wire.point = null; respond(wire);
    const answer = await client().resolve(SCENE, REQUEST);
    expect(answer.hit).toBeNull();
    expect(answer.pointCount).toBe(112156);
  });

  it.each([
    ['a hit with no point', (wire: ReturnType<typeof hit>) => { wire.point = null; }],
    ['a miss that carries a point', (wire: ReturnType<typeof hit>) => { wire.state = 'miss'; }],
    ['another photograph', (wire: ReturnType<typeof hit>) => { wire.query.capture_id = CAPTURE.replace(/c$/u, 'e'); }],
    ['another scene', (wire: ReturnType<typeof hit>) => { wire.scene_id = '00000000-0000-0000-0000-000000000001'; }],
    ['a retained count the rows do not carry', (wire: ReturnType<typeof hit>) => { wire.point!.observations_retained = 3; }],
    ['a track shorter than its retained rows', (wire: ReturnType<typeof hit>) => { wire.point!.track_length = 1; }],
    ['one photograph listed twice', (wire: ReturnType<typeof hit>) => {
      wire.point!.observations = [observation(CAPTURE), observation(CAPTURE)];
    }],
    ['a point outside the tolerance it names', (wire: ReturnType<typeof hit>) => { wire.point!.pixel_distance = '40'; }],
    ['a point behind the camera', (wire: ReturnType<typeof hit>) => { wire.point!.depth = '-1'; }],
    ['an unknown projection', (wire: ReturnType<typeof hit>) => { wire.query.projection = 'fisheye'; }],
  ])('refuses %s rather than attributing photographs on it', async (_label, corrupt) => {
    const wire = hit(); corrupt(wire); respond(wire);
    await expect(client().resolve(SCENE, REQUEST)).rejects.toMatchObject({ kind: 'unreadable' });
  });

  it.each(['', ' ', 'NaN', 'Infinity'])('refuses malformed coordinate %j', async (coordinate) => {
    const wire = hit(); (wire.point!.world_xyz as string[])[0] = coordinate; respond(wire);
    await expect(client().resolve(SCENE, REQUEST)).rejects.toThrow();
  });

  it('never sends a cursor that is not a number', async () => {
    const fetch = respond(hit());
    await expect(client().resolve(SCENE, { ...REQUEST, u: Number.NaN })).rejects.toMatchObject({ kind: 'unreadable' });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('names a photograph the scene holds no camera for as the problem', async () => {
    respond({ code: 'unknown_view', detail: 'no recovered camera' }, 404);
    await expect(client().resolve(SCENE, REQUEST)).rejects.toMatchObject({ kind: 'unresolvable' });
  });

  it('keeps every other 404 as the undistinguished answer it is', async () => {
    respond({ code: 'unknown_reference', detail: 'no observation graph for this scene' }, 404);
    await expect(client().resolve(SCENE, REQUEST)).rejects.toMatchObject({ kind: 'none-recorded' });
  });
});
