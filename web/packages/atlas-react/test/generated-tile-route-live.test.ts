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
import { TileRouteRefusal, fetchBakedTile, listBakedTiles } from '../src/playcanvas/generated-tile/index.js';

const baseUrl = process.env['EXULANICA_TILE_ROUTE'];
const token = process.env['EXULANICA_TILE_TOKEN'];
const citySeed = process.env['EXULANICA_TILE_CITY'];
const live = baseUrl !== undefined && token !== undefined && citySeed !== undefined;
/** A credential that authenticates but does not hold `tiles.materialise`, where one was named. */
const permissionless = process.env['EXULANICA_TILE_TOKEN_NO_PERMISSION'];

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
