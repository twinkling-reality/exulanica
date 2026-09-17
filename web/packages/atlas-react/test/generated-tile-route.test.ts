/**
 * The product path that reads a baked tile from `/tiles`, against the answers the route really
 * gives. Every status, header and problem body asserted here was read from
 * `exulanica/api/routes/tiles.py` and the corridor lane's own run of it over a real server, and the
 * tile bytes are invented for this test.
 */

import { webcrypto } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import {
  BAKED_TILE_MEDIA_TYPE,
  TileRouteRefusal,
  fetchBakedTile,
  listBakedTiles,
  tileAt,
  type BakedTileSummary,
} from '../src/playcanvas/generated-tile/index.js';

const digest = webcrypto.subtle;
const CITY_SEED = 'a'.repeat(64);
const TILE_ID = '0f3a5f1e-1f4c-4c8a-9d2a-6b7c8e9f0a1b';
const INPUTS_DIGEST = 'b'.repeat(64);
const BYTES = new TextEncoder().encode('invented container bytes for a test, not a tile');

async function sha256(bytes: Uint8Array): Promise<string> {
  const hashed = await digest.digest('SHA-256', bytes);
  return [...new Uint8Array(hashed)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

/** The list document exactly as `BakedTile.document()` writes it. */
function document(containerSha256: string, over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    baked_tile_id: TILE_ID,
    tile_x: 3,
    tile_y: -2,
    lod: 0,
    tile_inputs_digest: INPUTS_DIGEST,
    container_sha256: containerSha256,
    container_bytes: BYTES.length,
    render_batch_sha256: 'c'.repeat(64),
    nav_envelope_sha256: 'd'.repeat(64),
    state: 'baked',
    ...over,
  };
}

/** The same tile as `listBakedTiles` returns it, which is what a caller passes back in. */
function summary(containerSha256: string, over: Partial<BakedTileSummary> = {}): BakedTileSummary {
  return {
    bakedTileId: TILE_ID, tileX: 3, tileY: -2, lod: 0,
    tileInputsDigest: INPUTS_DIGEST, containerSha256, containerBytes: BYTES.length,
    renderBatchSha256: 'c'.repeat(64), navEnvelopeSha256: 'd'.repeat(64), state: 'baked',
    ...over,
  };
}

/** The bytes route's real headers, from the route and the corridor lane's measurement. */
function served(containerSha256: string, over: Record<string, string> = {}): Response {
  return new Response(BYTES, {
    status: 200,
    headers: {
      'Content-Type': BAKED_TILE_MEDIA_TYPE,
      ETag: `"${containerSha256}"`,
      'Cache-Control': 'private, no-cache',
      'X-Content-Type-Options': 'nosniff',
      'Accept-Ranges': 'none',
      'X-Exulanica-Tile-Inputs-Digest': INPUTS_DIGEST,
      ...over,
    },
  });
}

function problem(status: number, code: string, detail: string): Response {
  return new Response(JSON.stringify({ code, detail }), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'private, no-cache' },
  });
}

interface Call { readonly url: string; readonly headers: Headers }

function recorder(answer: (url: string, headers: Headers) => Response): { fetch: typeof globalThis.fetch; calls: Call[] } {
  const calls: Call[] = [];
  const fetcher = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    const headers = new Headers(init?.headers);
    calls.push({ url, headers });
    return answer(url, headers);
  };
  return { fetch: fetcher as typeof globalThis.fetch, calls };
}

const access = (fetcher: typeof globalThis.fetch) => ({ baseUrl: 'http://127.0.0.1:8000', token: 'scratch-token', fetch: fetcher });

/** The refusal a call made, and a failure if it answered instead. */
async function refusalFrom(call: Promise<unknown>): Promise<TileRouteRefusal> {
  try {
    await call;
  } catch (error) {
    return error as TileRouteRefusal;
  }
  throw new Error('the loader answered where it had to refuse');
}

describe('listing a city', () => {
  it('reads every field the route documents, and carries the credential', async () => {
    const container = await sha256(BYTES);
    const { fetch, calls } = recorder(() => new Response(JSON.stringify({ city_seed: CITY_SEED, tiles: [document(container)] }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }));
    const tiles = await listBakedTiles(access(fetch), { citySeed: CITY_SEED, lod: 0 });
    expect(tiles).toHaveLength(1);
    expect(tiles[0]).toMatchObject({
      bakedTileId: TILE_ID, tileX: 3, tileY: -2, lod: 0,
      containerSha256: container, containerBytes: BYTES.length, state: 'baked',
      tileInputsDigest: INPUTS_DIGEST,
    });
    expect(calls[0]!.url).toBe(`http://127.0.0.1:8000/tiles?city_seed=${CITY_SEED}&lod=0`);
    expect(calls[0]!.headers.get('Authorization')).toBe('Bearer scratch-token');
  });

  it('refuses a seed that is not 64 hex characters before it asks anything', async () => {
    const { fetch, calls } = recorder(() => new Response('never', { status: 200 }));
    await expect(listBakedTiles(access(fetch), { citySeed: 'nonsense' })).rejects.toThrow(TileRouteRefusal);
    expect(calls).toHaveLength(0);
  });

  it('refuses a list whose entry is missing a digest rather than reading a tile it cannot check', async () => {
    const { fetch } = recorder(() => new Response(JSON.stringify({
      tiles: [document('a'.repeat(64), { container_sha256: 'not a digest' })],
    }), { status: 200 }));
    await expect(listBakedTiles(access(fetch), { citySeed: CITY_SEED })).rejects.toMatchObject({ code: 'malformed_list' });
  });

  it('finds a tile by coordinate, and answers null where the city has none', () => {
    const tiles = [{ tileX: 3, tileY: -2, lod: 0 } as BakedTileSummary];
    expect(tileAt(tiles, { tileX: 3, tileY: -2, lod: 0 })).toBe(tiles[0]);
    expect(tileAt(tiles, { tileX: 3, tileY: -2, lod: 1 })).toBeNull();
  });
});

describe('fetching a container', () => {
  it('verifies the bytes against the digest, and reports what crossed the network', async () => {
    const container = await sha256(BYTES);
    const { fetch, calls } = recorder(() => served(container));
    const tile = await fetchBakedTile(access(fetch), {
      bakedTileId: TILE_ID, expect: summary(container), digest,
    });
    expect(tile.containerSha256).toBe(container);
    expect(tile.origin).toBe('fetched');
    expect(tile.transferredBytes).toBe(BYTES.length);
    expect(tile.tileInputsDigest).toBe(INPUTS_DIGEST);
    expect(calls[0]!.url).toBe(`http://127.0.0.1:8000/tiles/${TILE_ID}/bytes`);
    expect(calls[0]!.headers.get('Authorization')).toBe('Bearer scratch-token');
  });

  it('refuses bytes whose digest is not the one the route named, with both digests said', async () => {
    const container = await sha256(BYTES);
    const wrong = 'e'.repeat(64);
    const { fetch } = recorder(() => served(wrong));
    const refusal = await refusalFrom(fetchBakedTile(access(fetch), { bakedTileId: TILE_ID, digest }));
    expect(refusal).toBeInstanceOf(TileRouteRefusal);
    expect(refusal.code).toBe('digest_mismatch');
    expect(refusal.message).toContain(container);
    expect(refusal.message).toContain(wrong);
  });

  it('refuses a container that arrives with no digest to check it against', async () => {
    const { fetch } = recorder(() => new Response(BYTES, { status: 200, headers: { 'Content-Type': BAKED_TILE_MEDIA_TYPE } }));
    await expect(fetchBakedTile(access(fetch), { bakedTileId: TILE_ID, digest }))
      .rejects.toMatchObject({ code: 'unnamed_container' });
  });

  it('asks for nothing at all when it already holds the digest the list names', async () => {
    const container = await sha256(BYTES);
    const { fetch, calls } = recorder(() => { throw new Error('the loader must not ask'); });
    const tile = await fetchBakedTile(access(fetch), {
      bakedTileId: TILE_ID,
      expect: summary(container),
      held: { containerSha256: container, bytes: BYTES },
      digest,
    });
    expect(tile.origin).toBe('held');
    expect(tile.transferredBytes).toBe(0);
    expect(calls).toHaveLength(0);
  });

  it('sends If-None-Match and uses what it holds if the route ever answers 304', async () => {
    const container = await sha256(BYTES);
    const { fetch, calls } = recorder(() => new Response(null, { status: 304, headers: { ETag: `"${container}"` } }));
    const tile = await fetchBakedTile(access(fetch), {
      bakedTileId: TILE_ID, held: { containerSha256: container, bytes: BYTES }, digest,
    });
    expect(calls[0]!.headers.get('If-None-Match')).toBe(`"${container}"`);
    expect(tile.origin).toBe('not-modified');
    expect(tile.transferredBytes).toBe(0);
    expect(tile.bytes).toBe(BYTES);
  });

  it('skips a faulted tile without a request, because the list already said so', async () => {
    const { fetch, calls } = recorder(() => served('f'.repeat(64)));
    await expect(fetchBakedTile(access(fetch), {
      bakedTileId: TILE_ID,
      expect: summary('a'.repeat(64), { state: 'nondeterminism_detected' }),
      digest,
    })).rejects.toMatchObject({ code: 'nondeterminism_detected' });
    expect(calls).toHaveLength(0);
  });

  it('treats an unknown key and a permissionless credential alike, on the pair the route keeps stable', async () => {
    // MEASURED against the running route: the two share a status and a code and differ in detail,
    // because the permission floor refuses an id-addressed route before the route function runs.
    // The pair a caller may rely on is the status and the code, so that is what the loader reports,
    // and it never turns either answer into a claim about which one it was.
    const forbidden = await refusalFrom(fetchBakedTile(
      access(recorder(() => problem(404, 'unknown_reference', 'nothing at this address is available to this credential')).fetch),
      { bakedTileId: TILE_ID, digest },
    ));
    const unknown = await refusalFrom(fetchBakedTile(
      access(recorder(() => problem(404, 'unknown_reference', 'no such baked tile')).fetch),
      { bakedTileId: TILE_ID, digest },
    ));
    expect(forbidden.status).toBe(404);
    expect(forbidden.code).toBe('unknown_reference');
    expect(unknown.status).toBe(forbidden.status);
    expect(unknown.code).toBe(forbidden.code);
    for (const refusal of [forbidden, unknown]) {
      expect(refusal.message).not.toMatch(/permission|forbidden|not allowed|unauthorised|unauthorized/i);
    }
  });

  it('carries the route\'s own code for a fault, a missing file and a ceiling', async () => {
    const cases = [
      [409, 'nondeterminism_detected'],
      [409, 'bytes_missing'],
      [429, 'tile_quota_exceeded'],
      [503, 'tiles_unavailable'],
      [401, 'unauthenticated'],
    ] as const;
    for (const [status, code] of cases) {
      const { fetch } = recorder(() => problem(status, code, 'refused'));
      const refusal = await refusalFrom(fetchBakedTile(access(fetch), { bakedTileId: TILE_ID, digest }));
      expect(refusal.code).toBe(code);
      expect(refusal.status).toBe(status);
    }
  });

  it('refuses bytes served as something other than a container', async () => {
    const container = await sha256(BYTES);
    const { fetch } = recorder(() => served(container, { 'Content-Type': 'text/html' }));
    await expect(fetchBakedTile(access(fetch), { bakedTileId: TILE_ID, digest }))
      .rejects.toMatchObject({ code: 'wrong_media_type' });
  });

  it('refuses a container whose length is not the length its row records', async () => {
    const container = await sha256(BYTES);
    const { fetch } = recorder(() => served(container));
    await expect(fetchBakedTile(access(fetch), {
      bakedTileId: TILE_ID,
      expect: summary(container, { containerBytes: BYTES.length + 1 }),
      digest,
    })).rejects.toMatchObject({ code: 'wrong_length' });
  });
});
