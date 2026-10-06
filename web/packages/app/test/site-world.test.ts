// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DRAWING_ASKS, loadSiteWorld } from '../src/composition/site-world.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';

/**
 * A site world's drawing is made in the server's kind worker. While the worker is busy the route
 * answers 503 `kind_work_overran` or `kind_work_busy` with a `Retry-After`; the page waits that
 * long and asks again, a bounded number of times, and asks no more for any other answer.
 */

const entry = {
  entryId: 'entry-farm', worldId: 'world:generated:farm', authoredVersionId: 'version',
  generatedSite: {
    kind: 'fixture_farm', kindVersion: 1, kindLabel: 'A test farm', regionId: 'region:generated',
    arrivalMm: [48000, 0, -4000], arrivalFacingMm: [0, -1],
  },
} as unknown as SavedWorldEntry;
const access = { baseUrl: 'https://exulanica.test', token: 't' };

function refused(status: number, code: string, retryAfter?: string): Response {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (retryAfter !== undefined) headers['Retry-After'] = retryAfter;
  return new Response(JSON.stringify({ code, detail: 'words' }), { status, headers });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('loadSiteWorld', () => {
  it('waits out a drawing still being made and asks again', async () => {
    const answers = [refused(503, 'kind_work_overran', '1'), refused(503, 'kind_work_busy', '3'), refused(404, 'unknown_reference')];
    const fetched = vi.fn(async () => answers.shift() ?? refused(404, 'unknown_reference'));
    vi.stubGlobal('fetch', fetched);
    const waits: number[] = [];
    const told = vi.fn();
    await expect(loadSiteWorld(access, entry, told, async (ms) => { waits.push(ms); }))
      .rejects.toThrow('HTTP 404');
    expect(fetched).toHaveBeenCalledTimes(3);
    expect(waits).toEqual([1_000, 3_000]);
    expect(told).toHaveBeenCalledTimes(2);
  });

  it('asks a bounded number of times, and never longer apart than ten seconds', async () => {
    const fetched = vi.fn(async () => refused(503, 'kind_work_busy', '600'));
    vi.stubGlobal('fetch', fetched);
    const waits: number[] = [];
    await expect(loadSiteWorld(access, entry, () => {}, async (ms) => { waits.push(ms); }))
      .rejects.toThrow('HTTP 503');
    expect(fetched).toHaveBeenCalledTimes(DRAWING_ASKS);
    expect(waits).toEqual(Array(DRAWING_ASKS - 1).fill(10_000));
  });

  it('does not ask again when the worker could not take the work at all', async () => {
    const fetched = vi.fn(async () => refused(503, 'kind_work_unavailable', '5'));
    vi.stubGlobal('fetch', fetched);
    const waits: number[] = [];
    await expect(loadSiteWorld(access, entry, () => {}, async (ms) => { waits.push(ms); }))
      .rejects.toThrow('HTTP 503');
    expect(fetched).toHaveBeenCalledTimes(1);
    expect(waits).toEqual([]);
  });
});
