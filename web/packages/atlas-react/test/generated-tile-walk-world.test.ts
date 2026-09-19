/**
 * Which tiles a walk's world is, and fetching them.
 *
 * The corridor is the shape under test: five tiles in one row, (0,0) to (4,0), 128,000 mm across,
 * and a route of 125,000 mm with a 6,000 mm stopping margin starting on the middle tile's west edge.
 * The numbers are the corridor's own and the route rule's own, not invented sizes.
 */

import { webcrypto } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import {
  BAKED_TILE_MEDIA_TYPE,
  TileRouteRefusal,
  fetchWalkWorld,
  tileName,
  walkWorldTiles,
  type BakedTileSummary,
  type TileRouteAccess,
} from '../src/playcanvas/generated-tile/index.js';

const TILE_SIZE_MM = 128_000;
/** loom-gate's own `routeLengthMm` plus `stopMarginMm`. */
const REACH_MM = 125_000 + 6_000;
const digest = webcrypto.subtle;

function summary(tileX: number, tileY: number, over: Partial<BakedTileSummary> = {}): BakedTileSummary {
  const mark = `${tileX}${tileY}`.replace('-', 'f');
  return {
    bakedTileId: `0000000${tileX}-0000-4000-8000-00000000000${tileY < 0 ? 9 : tileY}`,
    tileX, tileY, lod: 0,
    tileInputsDigest: 'b'.repeat(64),
    containerSha256: mark.padEnd(64, '0'),
    containerBytes: 1_000 + tileX,
    renderBatchSha256: 'c'.repeat(64), navEnvelopeSha256: 'd'.repeat(64), state: 'baked',
    ...over,
  };
}

/** The corridor as the list route serves it: one row of five. */
const CORRIDOR = [0, 1, 2, 3, 4].map((tileX) => summary(tileX, 0));
/** The gate's walk: it starts on the west edge of tile (2,0) and runs east. */
const START: readonly [number, number] = [256_000, 64_000];
const plan = (tiles: readonly BakedTileSummary[] = CORRIDOR) =>
  walkWorldTiles(tiles, { startMm: START, reachMm: REACH_MM, lod: 0, tileSizeMm: TILE_SIZE_MM });

const place = (tiles: readonly { tileX: number; tileY: number }[]) => tiles.map((tile) => [tile.tileX, tile.tileY]);

describe('which tiles a walk\'s world is', () => {
  it('takes the tile it stands on and every one within the route\'s own reach, nearest first', () => {
    const world = plan();
    expect(place([world.own!])).toEqual([[2, 0]]);
    // (1,0) touches the start, so it is at nothing; (0,0) and (3,0) are both a tile away and the tie
    // is broken by row and then column so the answer is total and does not depend on a float.
    expect(place(world.neighbours)).toEqual([[1, 0], [0, 0], [3, 0]]);
    expect(world.neighbours.some((tile) => tile.tileX === 4)).toBe(false);
  });

  it('names every square within reach that the world has no ground for', () => {
    // The corridor is ONE ROW, so the squares north and south of it are within reach and hold
    // nothing. Saying so is the difference between "the city is that size" and a silence.
    expect(place(plan().absent)).toEqual([[1, -1], [2, -1], [1, 1], [2, 1]]);
    expect(plan().absent.map((tile) => tile.reason)).toEqual(['no_row', 'no_row', 'no_row', 'no_row']);
  });

  it('tells a square the store knows nothing about from one whose bake failed', () => {
    const faulted = CORRIDOR.map((tile) => (tile.tileX === 3 ? { ...tile, state: 'nondeterminism_detected' } : tile));
    const world = plan(faulted);
    expect(place(world.neighbours)).toEqual([[1, 0], [0, 0]]);
    const east = world.absent.find((tile) => tile.tileX === 3 && tile.tileY === 0);
    expect(east?.reason).toBe('nondeterminism_detected');
    // The two absences are different facts and the plan keeps them apart.
    expect(world.absent.filter((tile) => tile.reason === 'no_row').length).toBe(4);
  });

  it('refuses to lay out a world on a tile of no size, rather than dividing by it', () => {
    expect(() => walkWorldTiles(CORRIDOR, { startMm: START, reachMm: REACH_MM, lod: 0, tileSizeMm: 0 }))
      .toThrow(TileRouteRefusal);
  });

  it('reads only the level of detail the walk is at', () => {
    const mixed = [...CORRIDOR, summary(3, 0, { lod: 1, containerSha256: 'e'.repeat(64) })];
    expect(plan(mixed).neighbours.every((tile) => tile.lod === 0)).toBe(true);
  });
});

describe('fetching a walk\'s world', () => {
  const bytesOf = (tile: BakedTileSummary) => new TextEncoder().encode(`container for ${tileName(tile)}`);
  const access = (fetch: typeof globalThis.fetch): TileRouteAccess => ({ baseUrl: 'https://api.test', token: 't', fetch });

  const serving = (asked: string[]): typeof globalThis.fetch => (async (input: RequestInfo | URL) => {
    const url = String(input);
    asked.push(url);
    const tile = CORRIDOR.find((candidate) => url.includes(candidate.bakedTileId))!;
    const bytes = bytesOf(tile);
    const hashed = await digest.digest('SHA-256', bytes);
    const hex = [...new Uint8Array(hashed)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
    return new Response(bytes, {
      status: 200,
      headers: { 'Content-Type': BAKED_TILE_MEDIA_TYPE, ETag: `"${hex}"` },
    });
  }) as typeof globalThis.fetch;

  const hashedCorridor = async () => {
    const rows: BakedTileSummary[] = [];
    for (const tile of CORRIDOR) {
      const hashed = await digest.digest('SHA-256', bytesOf(tile));
      rows.push({
        ...tile,
        containerSha256: [...new Uint8Array(hashed)].map((b) => b.toString(16).padStart(2, '0')).join(''),
        containerBytes: bytesOf(tile).byteLength,
      });
    }
    return rows;
  };

  it('asks the route for each neighbour and reports what crossed the network', async () => {
    const rows = await hashedCorridor();
    const asked: string[] = [];
    const world = await fetchWalkWorld(access(serving(asked)), plan(rows), { digest });
    expect(world.neighbours.map((neighbour) => neighbour.name)).toEqual(['tile (1,0)', 'tile (0,0)', 'tile (3,0)']);
    expect(asked.length).toBe(3);
    expect(world.transferredBytes).toBe(world.neighbours.reduce((total, n) => total + n.bytes.byteLength, 0));
    expect(world.absent.length).toBe(4);
  });

  it('costs no request at all for a neighbour already held at the digest its row names', async () => {
    const rows = await hashedCorridor();
    const held = new Map(rows.map((tile) => [tile.containerSha256, { containerSha256: tile.containerSha256, bytes: bytesOf(tile) }]));
    const asked: string[] = [];
    const world = await fetchWalkWorld(access(serving(asked)), plan(rows), { digest, held });
    expect(asked).toEqual([]);
    expect(world.transferredBytes).toBe(0);
    expect(world.neighbours.length).toBe(3);
  });

  it('stops the walk when a tile the store says it has cannot be served', async () => {
    const rows = await hashedCorridor();
    const refusing: typeof globalThis.fetch = (async () => new Response(
      JSON.stringify({ code: 'unknown_reference', detail: 'no such key' }),
      { status: 404, headers: { 'Content-Type': 'application/problem+json' } },
    )) as typeof globalThis.fetch;
    await expect(fetchWalkWorld(access(refusing), plan(rows), { digest })).rejects.toBeInstanceOf(TileRouteRefusal);
  });
});
