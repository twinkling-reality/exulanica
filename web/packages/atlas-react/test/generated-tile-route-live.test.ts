/**
 * The loader against a RUNNING tile route, rather than against a stub of one.
 *
 * Skipped unless `EXULANICA_TILE_ROUTE`, `EXULANICA_TILE_TOKEN` and `EXULANICA_TILE_CITY` name a
 * server to ask, so it never runs in a suite and no credential is ever committed. Run it as:
 *
 *     EXULANICA_TILE_ROUTE=http://127.0.0.1:8077 EXULANICA_TILE_TOKEN=... \
 *     EXULANICA_TILE_CITY=<64 hex> npx vitest run --root packages/atlas-react test/generated-tile-route-live
 *
 * What it proves is the transport and the checking, not the drawing: a development server may serve
 * a stand-in whose bytes are not a container at all, and this file neither parses nor draws them.
 */

import { webcrypto } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parseTextureSetManifest } from '@exulanica/atlas-core';
import { decodeOwd } from '@exulanica/loom-tess/core';
import {
  GeneratedTileRefusal,
  TileRouteRefusal,
  composedSupport,
  fetchBakedTile,
  fetchWalkWorld,
  listBakedTiles,
  loadGeneratedTile,
  tilePlacement,
  walkWorldTiles,
} from '../src/playcanvas/generated-tile/index.js';

const baseUrl = process.env['EXULANICA_TILE_ROUTE'];
const token = process.env['EXULANICA_TILE_TOKEN'];
const citySeed = process.env['EXULANICA_TILE_CITY'];
const live = baseUrl !== undefined && token !== undefined && citySeed !== undefined;
/** A credential that authenticates but does not hold `tiles.materialise`, where one was named. */
const permissionless = process.env['EXULANICA_TILE_TOKEN_NO_PERMISSION'];
/** A key whose stored bytes are deliberately NOT a container, where one was named. */
const notAContainer = process.env['EXULANICA_TILE_NOT_A_CONTAINER'];

describe.runIf(live)('against a running tile route', () => {
  const access = { baseUrl: baseUrl ?? '', token: token ?? '' };
  const digest = webcrypto.subtle;

  it('lists the city, fetches a container and finds it hashes to the digest its row records', async () => {
    const tiles = await listBakedTiles(access, { citySeed: citySeed ?? '' });
    expect(tiles.length).toBeGreaterThan(0);
    const wanted = tiles.find((tile) => tile.state === 'baked');
    expect(wanted, 'the city has a baked tile').toBeDefined();

    const first = await fetchBakedTile(access, { bakedTileId: wanted!.bakedTileId, expect: wanted!, digest });
    expect(first.origin).toBe('fetched');
    expect(first.containerSha256).toBe(wanted!.containerSha256);
    expect(first.bytes.length).toBe(wanted!.containerBytes);
    expect(first.transferredBytes).toBe(wanted!.containerBytes);

    // A reload: the digest the list names is already held, so nothing is asked for at all.
    const held = { containerSha256: first.containerSha256, bytes: first.bytes };
    const again = await fetchBakedTile(access, { bakedTileId: wanted!.bakedTileId, expect: wanted!, held, digest });
    expect(again.origin).toBe('held');
    expect(again.transferredBytes).toBe(0);

    // Without the row to compare against, the request goes out carrying If-None-Match.
    const revalidated = await fetchBakedTile(access, { bakedTileId: wanted!.bakedTileId, held, digest });
    expect(['not-modified', 'fetched']).toContain(revalidated.origin);
    expect(revalidated.containerSha256).toBe(first.containerSha256);

    // eslint-disable-next-line no-console
    console.log(JSON.stringify({
      tiles: tiles.length,
      state: wanted!.state,
      containerBytes: wanted!.containerBytes,
      containerSha256: wanted!.containerSha256,
      firstOrigin: first.origin,
      reloadOrigin: again.origin,
      revalidatedOrigin: revalidated.origin,
      revalidatedTransferred: revalidated.transferredBytes,
    }));
  });

  it.runIf(notAContainer !== undefined)('verifies bytes that are not a container, then refuses to read them as a tile', async () => {
    // The one path nothing else can show: bytes that pass every check the TRANSPORT makes (they hash
    // to the digest the row records) and are still refused, by the reader, for not being a tile.
    const tiles = await listBakedTiles(access, { citySeed: citySeed ?? '' });
    const row = tiles.find((tile) => tile.bakedTileId === notAContainer);
    // The row IS the premise: without it there is no independent digest to hold the bytes to, so its
    // absence fails the run. Comparing the fetched digest with itself would pass and prove nothing.
    expect(row, `the key in EXULANICA_TILE_NOT_A_CONTAINER is not listed for city ${citySeed ?? ''}`).toBeDefined();
    const expected = row!.containerSha256;
    const fetched = await fetchBakedTile(access, { bakedTileId: row!.bakedTileId, expect: row!, digest });
    // The transport is satisfied: the bytes are exactly what the row, read separately, names.
    expect(fetched.containerSha256).toBe(expected);

    const manifest = parseTextureSetManifest(new Uint8Array(readFileSync(resolve('../assets/textures/manifest.json'))));
    const refusal = await loadGeneratedTile({
      name: fetched.bakedTileId,
      bytes: fetched.bytes,
      manifest,
      fetchSet: () => { throw new Error('no texture set should be asked for: the container never parsed'); },
    }).then(() => null, (error: unknown) => error as Error);
    expect(refusal).toBeInstanceOf(GeneratedTileRefusal);
    // eslint-disable-next-line no-console
    console.log(JSON.stringify({ bytes: fetched.bytes.length, digestChecked: fetched.containerSha256, refusal: refusal?.message }));
  });

  it('composes a walk\'s world out of the neighbours the route really serves', async () => {
    // THE ONLY REPEATABLE EXERCISE OF NEIGHBOUR FETCHING AGAINST A REAL SERVER. Everything else that
    // composes runs against containers this repository made; this asks a store for a tile, asks it
    // for the tiles around that one, and puts the ground together. It PARSES, which the rest of this
    // file does not, because a composition that is not parsed is not a composition.
    const tiles = await listBakedTiles(access, { citySeed: citySeed ?? '' });
    const wanted = tiles.find((tile) => tile.state === 'baked');
    expect(wanted, 'the city has a baked tile').toBeDefined();
    const own = await fetchBakedTile(access, { bakedTileId: wanted!.bakedTileId, expect: wanted!, digest });
    const placement = tilePlacement(own.bytes);

    // A REACH OF ONE TILE, taken from the container's own `tile_size_mm` rather than from a route
    // length this file has no business knowing: it is the smallest reach that certainly touches a
    // neighbour, and what is under test is the fetching rather than any particular route.
    const plan = walkWorldTiles(tiles, {
      standingOn: placement,
      reachMm: placement.tileSizeMm,
      lod: placement.lod,
      tileSizeMm: placement.tileSizeMm,
    });
    // A CITY OF ONE TILE WOULD PASS THIS TEST WITHOUT COMPOSING ANYTHING, so it fails instead: a
    // green run here must mean ground was joined, not that there was none to join.
    expect(plan.neighbours.length, `city ${citySeed ?? ''} serves no baked neighbour of `
      + `(${placement.tileX},${placement.tileY}), so this run would compose nothing`).toBeGreaterThan(0);

    // THE NETWORK IS THE INDEPENDENT SOURCE. Checking the returned world against the plan it came
    // from compares two renderings of one object and cannot fail on a shared misunderstanding of
    // what either holds. What was actually REQUESTED is a separate record of the same events.
    const asked: string[] = [];
    const watched = {
      ...access,
      fetch: ((input: RequestInfo | URL, init?: RequestInit) => {
        asked.push(String(input));
        return globalThis.fetch(input, init);
      }) as typeof globalThis.fetch,
    };
    const began = Date.now();
    const world = await fetchWalkWorld(watched, plan, { digest });
    const tookMs = Date.now() - began;
    expect(world.neighbours.length).toBe(plan.neighbours.length);
    expect(world.transferredBytes).toBe(plan.neighbours.reduce((total, row) => total + row.containerBytes, 0));
    // Every neighbour named was asked for, once, and the tile already in hand was not asked for again.
    for (const row of plan.neighbours) {
      expect(asked.filter((url) => url.includes(row.bakedTileId)).length, `${row.bakedTileId} was asked for once`).toBe(1);
    }
    expect(asked.filter((url) => url.includes(wanted!.bakedTileId)).length).toBe(0);
    expect(asked.length).toBe(plan.neighbours.length);

    const envelope = (bytes: Uint8Array) =>
      decodeOwd(bytes).projections.find((projection) => projection.header.name === 'nav_envelope')!;
    const alone = composedSupport([{ tile: 'the tile', projection: envelope(own.bytes) }]);
    const composed = composedSupport([
      { tile: 'the tile', projection: envelope(own.bytes) },
      ...world.neighbours.map((neighbour) => ({ tile: neighbour.name, projection: envelope(neighbour.bytes) })),
    ]);
    // THE COUNT IS THE HALF THAT CAN FAIL, and it is measured against the parts computed SEPARATELY
    // rather than against another sum of the same list, which could not have disagreed with itself.
    const separately = world.neighbours.reduce(
      (total, neighbour) => total + composedSupport([{ tile: neighbour.name, projection: envelope(neighbour.bytes) }]).triangles,
      alone.triangles,
    );
    expect(composed.triangles).toBe(separately);
    expect(composed.triangles).toBeGreaterThan(alone.triangles);
    expect(composed.tiles[0]!.walkable).toBe(alone.triangles);
    // And the world is bigger than the tile, which is the whole reason any of this exists.
    const grew = composed.extent.max[0] > alone.extent.max[0] || composed.extent.min[0] < alone.extent.min[0]
      || composed.extent.max[1] > alone.extent.max[1] || composed.extent.min[1] < alone.extent.min[1];
    expect(grew, 'the composed world reaches past the tile it was laid on').toBe(true);

    // eslint-disable-next-line no-console
    console.log(JSON.stringify({
      standingOn: `(${placement.tileX},${placement.tileY})`,
      neighbours: world.neighbours.map((neighbour) => neighbour.name),
      absent: world.absent,
      transferredBytes: world.transferredBytes,
      ownContainerBytes: own.bytes.length,
      worldBytes: world.transferredBytes + own.bytes.length,
      tookMs,
      trianglesAlone: alone.triangles,
      trianglesComposed: composed.triangles,
      perTile: composed.tiles.map((tile) => ({ tile: tile.tile, stated: tile.stated, walkable: tile.walkable })),
    }));
  });

  it('answers an unknown key 404 unknown_reference', async () => {
    const refusal = await fetchBakedTile(access, { bakedTileId: '00000000-0000-4000-8000-000000000000', digest })
      .then(() => null, (error: unknown) => error as TileRouteRefusal);
    expect(refusal?.code).toBe('unknown_reference');
    expect(refusal?.status).toBe(404);
  });

  it.runIf(permissionless !== undefined)('answers a permissionless credential 404 unknown_reference, as it answers an unknown key', async () => {
    const tiles = await listBakedTiles(access, { citySeed: citySeed ?? '' });
    const real = tiles.find((tile) => tile.state === 'baked');
    const short = { baseUrl: access.baseUrl, token: permissionless ?? '' };
    const forbidden = await fetchBakedTile(short, { bakedTileId: real!.bakedTileId, digest })
      .then(() => null, (error: unknown) => error as TileRouteRefusal);
    const unknown = await fetchBakedTile(access, { bakedTileId: '00000000-0000-4000-8000-000000000000', digest })
      .then(() => null, (error: unknown) => error as TileRouteRefusal);
    // The pair a caller may rely on is the status and the code; the detail is the route's own.
    expect(forbidden?.status).toBe(404);
    expect(forbidden?.code).toBe('unknown_reference');
    expect(unknown?.status).toBe(forbidden?.status);
    expect(unknown?.code).toBe(forbidden?.code);
    // eslint-disable-next-line no-console
    console.log(JSON.stringify({ forbidden: forbidden?.message, unknown: unknown?.message }));
  });

  it('answers a credential the route does not know without saying what was wrong with it', async () => {
    const stranger = { baseUrl: access.baseUrl, token: 'not-a-token-this-route-knows' };
    const refusal = await fetchBakedTile(stranger, { bakedTileId: '00000000-0000-4000-8000-000000000000', digest })
      .then(() => null, (error: unknown) => error as TileRouteRefusal);
    expect(refusal).toBeInstanceOf(TileRouteRefusal);
    expect([401, 403, 404]).toContain(refusal?.status);
    // eslint-disable-next-line no-console
    console.log(JSON.stringify({ strangerStatus: refusal?.status, strangerCode: refusal?.code }));
  });
});
