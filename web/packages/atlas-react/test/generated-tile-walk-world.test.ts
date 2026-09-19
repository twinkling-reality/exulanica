/**
 * Which tiles a walk's world is, and fetching them.
 *
 * The corridor is the shape under test: five tiles in one row, (0,0) to (4,0), 128,000 mm across,
 * and a route of 125,000 mm with a 6,000 mm stopping margin starting on the middle tile's west edge.
 * The numbers are the corridor's own and the route rule's own, not invented sizes.
 */

import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { beforeAll, describe, expect, it } from 'vitest';
import { bakeTile, decodeOwd } from '@exulanica/loom-tess/core';
import {
  BAKED_TILE_MEDIA_TYPE,
  TileRouteRefusal,
  composedObstructionRings,
  fetchWalkWorld,
  tileName,
  tilePlacement,
  walkWorldTiles,
  type BakedTileSummary,
  type TileRouteAccess,
} from '../src/playcanvas/generated-tile/index.js';

/** The conformance fixture's own city, read from its container rather than invented. */
const FIXTURE_CITY = 'd0219dae956352ef4a56e32030cb6ab1a80bfa5a63fd288e9aacccfb71966a60';
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
const STANDING = { tileX: 2, tileY: 0 };
const plan = (tiles: readonly BakedTileSummary[] = CORRIDOR) =>
  walkWorldTiles(tiles, { standingOn: STANDING, startMm: START, reachMm: REACH_MM, lod: 0, tileSizeMm: TILE_SIZE_MM });

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
    expect(() => walkWorldTiles(CORRIDOR, { standingOn: STANDING, startMm: START, reachMm: REACH_MM, lod: 0, tileSizeMm: 0 }))
      .toThrow(TileRouteRefusal);
  });

  it('takes the reach from the whole square when the walk states no pose', () => {
    // An unstated walk opens at this runtime's default, which is decided AFTER the world exists, so
    // there is no point to measure from. A square is the superset of every point in it, so this can
    // only over-fetch, which is the safe direction: tile (4,0) joins because it is a tile away from
    // (2,0)'s eastern edge, where a pose on the western edge could never reach it.
    const stated = plan();
    const unstated = walkWorldTiles(CORRIDOR, { standingOn: STANDING, reachMm: REACH_MM, lod: 0, tileSizeMm: TILE_SIZE_MM });
    expect(place(unstated.neighbours)).toEqual([[1, 0], [3, 0], [0, 0], [4, 0]]);
    expect(place(stated.neighbours)).toEqual([[1, 0], [0, 0], [3, 0]]);
    expect(unstated.neighbours.length).toBeGreaterThan(stated.neighbours.length);
  });

  it('refuses a stated pose that is not on the tile it says it stands on', () => {
    expect(() => walkWorldTiles(CORRIDOR, {
      standingOn: STANDING, startMm: [640_000, 64_000], reachMm: REACH_MM, lod: 0, tileSizeMm: TILE_SIZE_MM,
    })).toThrow(/is not on tile \(2,0\)/);
  });

  it('reads only the level of detail the walk is at', () => {
    const mixed = [...CORRIDOR, summary(3, 0, { lod: 1, containerSha256: 'e'.repeat(64) })];
    expect(plan(mixed).neighbours.every((tile) => tile.lod === 0)).toBe(true);
  });
});

describe('fetching a walk\'s world', () => {
  // REAL CONTAINERS, because the fetch now reads each one's own account of which tile it is. The
  // fixture bakes to tile (0,0); the others are that container with `tile_x` restated, which is one
  // character of a canonical header and so leaves every section offset exactly where it was. Their
  // GEOMETRY is still tile (0,0)'s, which is why nothing here walks on them: what is under test is
  // which containers are asked for, which are already held, and what is refused.
  let baked: Uint8Array;
  beforeAll(async () => {
    baked = (await bakeTile(new Uint8Array(readFileSync('packages/loom-tess/test/fixtures/tile-conformance.json')), sha256)).container;
  }, 60_000);

  async function sha256(bytes: Uint8Array): Promise<string> {
    const hashed = await digest.digest('SHA-256', bytes);
    return [...new Uint8Array(hashed)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  }

  /** The same container saying it is another tile: one digit, in place, so no offset moves. */
  function asTile(tileX: number): Uint8Array {
    const copy = new Uint8Array(baked);
    const headerBytes = new DataView(copy.buffer, copy.byteOffset).getUint32(4, true);
    const header = new TextDecoder().decode(copy.subarray(8, 8 + headerBytes));
    // ANCHORED ON THE TILE RECORD, not on the first `tile_x` in the file: the header lists every
    // record before it, and a record of its own carries that field, so a plain search edits somebody
    // else's. The edit is then READ BACK, because an edit that silently did nothing would leave
    // every row pointing at tile (0,0) and the test would be about a container nobody meant.
    const record = header.indexOf('"tile":{"fields":');
    expect(record).toBeGreaterThan(0);
    const at = header.indexOf('"tile_x":', record);
    expect(at).toBeGreaterThan(record);
    const digit = at + '"tile_x":'.length;
    expect(header[digit + 1]).toBe(',');
    copy[8 + digit] = String(tileX).charCodeAt(0);
    expect(tilePlacement(copy).tileX).toBe(tileX);
    return copy;
  }

  const access = (fetch: typeof globalThis.fetch): TileRouteAccess => ({ baseUrl: 'https://api.test', token: 't', fetch });

  async function corridorOf(bytesFor: (tileX: number) => Uint8Array) {
    const rows: BakedTileSummary[] = [];
    const served = new Map<string, Uint8Array>();
    for (const tile of CORRIDOR) {
      const bytes = bytesFor(tile.tileX);
      served.set(tile.bakedTileId, bytes);
      rows.push({ ...tile, containerSha256: await sha256(bytes), containerBytes: bytes.byteLength });
    }
    return { rows, served };
  }

  const serving = (served: ReadonlyMap<string, Uint8Array>, asked: string[]): typeof globalThis.fetch =>
    (async (input: RequestInfo | URL) => {
      const url = String(input);
      asked.push(url);
      const id = [...served.keys()].find((key) => url.includes(key))!;
      const bytes = served.get(id)!;
      return new Response(bytes.slice().buffer as ArrayBuffer, {
        status: 200,
        headers: { 'Content-Type': BAKED_TILE_MEDIA_TYPE, ETag: `"${await sha256(bytes)}"` },
      });
    }) as typeof globalThis.fetch;

  it('asks the route for each neighbour and reports what crossed the network', async () => {
    const { rows, served } = await corridorOf(asTile);
    const asked: string[] = [];
    const world = await fetchWalkWorld(access(serving(served, asked)), plan(rows), { digest, citySeed: FIXTURE_CITY });
    expect(world.neighbours.map((neighbour) => neighbour.name)).toEqual(['tile (1,0)', 'tile (0,0)', 'tile (3,0)']);
    expect(asked.length).toBe(3);
    expect(world.transferredBytes).toBe(world.neighbours.reduce((total, n) => total + n.bytes.byteLength, 0));
    expect(world.neighbours.map((n) => n.containerSha256)).toEqual(
      ['tile (1,0)', 'tile (0,0)', 'tile (3,0)'].map((name) => rows.find((row) => tileName(row) === name)!.containerSha256));
    expect(world.absent.length).toBe(4);
  });

  it('costs no request at all for a neighbour already held at the digest its row names', async () => {
    const { rows, served } = await corridorOf(asTile);
    const held = new Map(rows.map((row) => [row.containerSha256, {
      containerSha256: row.containerSha256, bytes: served.get(row.bakedTileId)!,
    }]));
    const asked: string[] = [];
    const world = await fetchWalkWorld(access(serving(served, asked)), plan(rows), { digest, citySeed: FIXTURE_CITY, held });
    expect(asked).toEqual([]);
    expect(world.transferredBytes).toBe(0);
    expect(world.neighbours.length).toBe(3);
  });

  it('refuses a row whose container says it is a different tile', async () => {
    // Every row served the SAME container, the one that says it is (0,0). It is whole, it is
    // exactly the bytes its row's digest names, and for two of the three rows it is the wrong
    // ground: this is the only check between here and standing on another part of the city.
    const { rows, served } = await corridorOf(() => baked);
    await expect(fetchWalkWorld(access(serving(served, [])), plan(rows), { digest, citySeed: FIXTURE_CITY }))
      .rejects.toThrow(/says it is tile \(0,0\)/);
  });

  it('refuses a container that belongs to another city, which the coordinates alone do not settle', async () => {
    // A listing is asked for ONE city, so its rows are that city's by construction. The containers
    // are not: a row of this city pointing at (3,0) of another agrees about (3,0) and is somebody
    // else's street, and every other check this fetch makes would pass it.
    const { rows, served } = await corridorOf(asTile);
    await expect(fetchWalkWorld(access(serving(served, [])), plan(rows), { digest, citySeed: 'f'.repeat(64) }))
      .rejects.toThrow(/is listed for city f{64} and the container it served belongs to d0219dae/);
  });

  it('stops the walk when a tile the store says it has cannot be served', async () => {
    const { rows } = await corridorOf(asTile);
    const refusing: typeof globalThis.fetch = (async () => new Response(
      JSON.stringify({ code: 'unknown_reference', detail: 'no such key' }),
      { status: 404, headers: { 'Content-Type': 'application/problem+json' } },
    )) as typeof globalThis.fetch;
    await expect(fetchWalkWorld(access(refusing), plan(rows), { digest, citySeed: FIXTURE_CITY })).rejects.toBeInstanceOf(TileRouteRefusal);
  });
});

describe('the obstacles of a world of several tiles', () => {
  /**
   * A header carrying records and no usable grammar, so the records are compared and no ring is
   * built from them. What is under test is the DEDUPLICATION and the disagreement it cannot resolve,
   * both of which happen before any ring exists.
   */
  const stating = (tile: string, records: { kind: string; identity: string; sha256: string }[]) => ({
    tile,
    header: { grammars: [], records: records.map((record) => ({ ...record, grammar: 0, membership: 'halo', version: 2, fields: {} })) },
  }) as unknown as Parameters<typeof composedObstructionRings>[0][number];

  const massing = (identity: string, sha256: string) => ({ kind: 'city.massing', identity, sha256: sha256.padEnd(64, '0') });

  let container: Uint8Array;
  beforeAll(async () => {
    const hash = async (bytes: Uint8Array): Promise<string> => {
      const hashed = await digest.digest('SHA-256', bytes);
      return [...new Uint8Array(hashed)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
    };
    container = (await bakeTile(new Uint8Array(readFileSync('packages/loom-tess/test/fixtures/tile-conformance.json')), hash)).container;
  }, 60_000);

  it('says which tile stated every ring, on rings a real container really makes', () => {
    const composed = composedObstructionRings([{ tile: 'the tile', header: decodeOwd(container).header }]);
    expect(composed.rings.length).toBeGreaterThan(0);
    expect([...new Set(composed.rings.map((ring) => ring.statedBy))]).toEqual(['the tile']);
  });

  /**
   * WHAT THIS FILE CANNOT COVER, said here rather than left looking covered. The RUNTIME composing a
   * neighbour's records into the set is not exercised anywhere in this repository: it commits one
   * container, and a second tile's bytes would have to be baked, so a neighbour either duplicates
   * this one (and is correctly deduplicated to nothing) or fails verification. THE PAGE'S LIVE TEST
   * is what exercises it, by reading the ring set off a LOADED TILE rather than by composing one
   * itself: a test that composes rings itself proves the composer works and says nothing about
   * whether the loader was given the neighbours.
   */
  it('keeps one copy of a building two tiles both state, and says nothing disagreed', () => {
    // The ordinary case: a tile's HALO copy and its neighbour's OWNED copy are the same bytes.
    const composed = composedObstructionRings([
      stating('the tile', [massing('m1', 'aaaa'), massing('m2', 'bbbb')]),
      stating('tile (1,0)', [massing('m1', 'aaaa'), massing('m3', 'cccc')]),
    ]);
    expect(composed.disagreed).toEqual([]);
  });

  it('reports a record two tiles state differently, rather than leaving both copies unexplained', () => {
    // A HALO COPY IS A STAND-IN FOR A TILE YOU DO NOT HAVE. If one were ever written as a REDUCED
    // form of its original, the digests would stop matching, both copies would enter the set, and a
    // building described twice is the shape that once stopped a walker 344 mm from a bench. This is
    // the only thing that can tell anyone it happened.
    const composed = composedObstructionRings([
      stating('the tile', [massing('m1', 'aaaa')]),
      stating('tile (1,0)', [massing('m1', 'dddd')]),
    ]);
    expect(composed.disagreed).toEqual([
      { kind: 'city.massing', identity: 'm1', kept: 'the tile', against: 'tile (1,0)' },
    ]);
  });
});
