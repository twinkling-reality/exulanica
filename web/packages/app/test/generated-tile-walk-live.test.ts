// @vitest-environment happy-dom

/**
 * THE PAGE AGAINST A RUNNING TILE ROUTE, and the only place the composed world can ever be observed.
 *
 * Skipped unless `EXULANICA_TILE_ROUTE`, `EXULANICA_TILE_TOKEN` and `EXULANICA_TILE_CITY` name a
 * server to ask, so it never runs in a suite and no credential is ever committed. Run it as:
 *
 *     EXULANICA_TILE_ROUTE=http://127.0.0.1:8000 EXULANICA_TILE_TOKEN=... \
 *     EXULANICA_TILE_CITY=<64 hex> npx vitest run --root packages/app test/generated-tile-walk-live
 *
 * WHY IT MUST EXIST RATHER THAN BEING COVERED BY THE STUBBED WALK TEST. This repository commits
 * exactly one container, so every attempt to serve a second ends in a correct refusal before a world
 * is ever built. `stoodOnOnly`, `transferredBytes` and `absent` therefore have NEVER EXECUTED in
 * their populated form: the right-hand side of every ternary in `stateWorld` is unrun code, and no
 * fixture can reach it. Only a real store holding real neighbours can.
 *
 * AND WHY IT CHECKS THE ATTRIBUTE AGAINST THE NETWORK RATHER THAN AGAINST THE SENTENCE BESIDE IT.
 * Both are derived from one `world` object by two mappings, so their agreement catches a typo in one
 * and cannot catch a shared misunderstanding of what `world` holds: two operands, one source, a test
 * that cannot fail. WHAT WAS ACTUALLY REQUESTED is a separate record of the same events.
 *
 * The page derives its own base URL from `window.location`, which a test process does not share with
 * a server, so the interceptor below REWRITES the page's own API path onto the live route and reads
 * the committed texture library from disk. Everything it rewrites, it records.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import { fetchBakedTile, listBakedTiles, tilePlacement } from '@exulanica/atlas-react/generated-tile';
import { bakedTileRequest } from '../src/config.js';
import { GENERATED_TILE_WORLD_ATTRIBUTE, prepareBakedTileWalk } from '../src/composition/generated-tile.js';
import type { AppEnvironment } from '../src/composition/session-state.js';

const baseUrl = process.env['EXULANICA_TILE_ROUTE'];
const token = process.env['EXULANICA_TILE_TOKEN'];
const citySeed = process.env['EXULANICA_TILE_CITY'];
const live = baseUrl !== undefined && token !== undefined && citySeed !== undefined;
const TEXTURES = resolve('../assets/textures');

/** A file the development page asks for by URL, read from the repository instead. */
function fileFor(url: string): Uint8Array | null {
  const path = url.split('?')[0]!.replace(/^https?:\/\/[^/]+/, '');
  const onDisk = path.startsWith('/@fs') ? path.slice('/@fs'.length) : null;
  if (onDisk !== null) return new Uint8Array(readFileSync(onDisk));
  if (path.includes('/assets/textures/')) {
    return new Uint8Array(readFileSync(resolve(TEXTURES, path.slice(path.indexOf('/assets/textures/') + '/assets/textures/'.length))));
  }
  if (path.includes('/dev/tiles/')) {
    return new Uint8Array(readFileSync(resolve('packages/app/src/dev/tiles', path.slice(path.lastIndexOf('/') + 1))));
  }
  return null;
}

describe.runIf(live)('the page against a running tile route', { timeout: 120_000 }, () => {
  const access = { baseUrl: `${baseUrl ?? ''}`, token: token ?? '' };
  const digest = webcrypto.subtle;
  let asked: string[] = [];

  beforeEach(() => {
    asked = [];
    vi.stubEnv('VITE_EXULANICA_TOKEN', token ?? '');
    const real = globalThis.fetch.bind(globalThis);
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = String(input);
      const api = `${window.location.origin}/api`;
      if (url.startsWith(api)) {
        const onward = `${baseUrl ?? ''}${url.slice(api.length)}`;
        asked.push(onward);
        return real(onward, init);
      }
      const file = fileFor(url);
      if (file !== null) return new Response(file.slice().buffer as ArrayBuffer, { status: 200 });
      return new Response('not here', { status: 404 });
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    document.body.replaceChildren();
  });

  it('composes a world of real neighbours and states it as data that matches what crossed the wire', async () => {
    const tiles = await listBakedTiles(access, { citySeed: citySeed ?? '' });
    const wanted = tiles.find((tile) => tile.state === 'baked');
    expect(wanted, `city ${citySeed ?? ''} has a baked tile`).toBeDefined();
    // ONE EXTRA FETCH OF THE TILE, on purpose: the reach must come from the container's own
    // `tile_size_mm` rather than from a route length this file has no business knowing, and the page
    // is handed the reach before it has read anything. A reach of one tile is the smallest that
    // certainly touches a neighbour.
    const sized = await fetchBakedTile(access, { bakedTileId: wanted!.bakedTileId, expect: wanted!, digest });
    const placement = tilePlacement(sized.bytes);

    const search = `?preview=1&city=${placement.citySeed}&tile_x=${placement.tileX}&tile_y=${placement.tileY}`
      + `&lod=${placement.lod}&walk_reach_mm=${placement.tileSizeMm}`;
    const request = bakedTileRequest(search, true);
    expect(request?.reachMm).toBe(placement.tileSizeMm);

    const element = document.createElement('div');
    document.body.append(element);
    await prepareBakedTileWalk({ shell: element, preview: true } as unknown as AppEnvironment, request!);

    const stated: {
      reach: string;
      drawnAndStoodOn: { name: string; containerSha256: string };
      stoodOnOnly: { tile: string; tileX: number; tileY: number; containerSha256: string }[];
      transferredBytes: number;
      absent: { tileX: number; tileY: number; reason: string }[];
    } = JSON.parse(element.getAttribute(GENERATED_TILE_WORLD_ATTRIBUTE)!);

    // THE BRANCH NO FIXTURE CAN REACH. A city of one tile would leave this empty and the run would
    // have proved nothing, so it fails instead of passing quietly.
    expect(stated.reach).toBe('stated');
    expect(stated.stoodOnOnly.length, `city ${citySeed ?? ''} served no neighbour, so nothing was composed`)
      .toBeGreaterThan(0);

    // AGAINST THE NETWORK, not against the sentence beside it. Every container the attribute says
    // was STOOD ON ONLY was fetched from the route, and the one it says was DRAWN was fetched too.
    const fetchedIds = asked.flatMap((url) => /\/tiles\/([0-9a-fA-F-]{36})\/bytes/.exec(url)?.[1] ?? []);
    // BY COORDINATE, NOT BY PARSING THE DISPLAY NAME. The name is for a person; a check that had to
    // read numbers back out of `tile (3,0)` would be binding a string this codebase formats, which is
    // the fault the attribute exists to avoid, one level down.
    const rowFor = (at: { readonly tileX: number; readonly tileY: number }) =>
      tiles.find((row) => row.tileX === at.tileX && row.tileY === at.tileY && row.lod === placement.lod)!;
    for (const stoodOn of stated.stoodOnOnly) {
      const row = rowFor(stoodOn);
      expect(row, `${stoodOn.tile} is listed`).toBeDefined();
      expect(stoodOn.containerSha256, `${stoodOn.tile} states the digest its row records`).toBe(row.containerSha256);
      expect(fetchedIds, `${stoodOn.tile} was fetched`).toContain(row.bakedTileId);
    }
    expect(stated.drawnAndStoodOn.containerSha256).toBe(wanted!.containerSha256);
    expect(fetchedIds).toContain(wanted!.bakedTileId);
    // Nothing is both drawn and only stood on.
    expect(stated.stoodOnOnly.map((tile) => tile.containerSha256)).not.toContain(stated.drawnAndStoodOn.containerSha256);
    // The bytes the page says it moved for the neighbours are the neighbours' own recorded lengths.
    expect(stated.transferredBytes).toBe(stated.stoodOnOnly.reduce((total, tile) => total + rowFor(tile).containerBytes, 0));

    // Absent squares, against the listing rather than hard-coded: the city's shape is the city's fact.
    for (const square of stated.absent) {
      const row = tiles.find((tile) => tile.tileX === square.tileX && tile.tileY === square.tileY && tile.lod === placement.lod);
      if (square.reason === 'no_row') expect(row).toBeUndefined();
      else expect(row?.state).toBe(square.reason);
    }

    // eslint-disable-next-line no-console
    console.log(JSON.stringify({
      standingOn: `(${placement.tileX},${placement.tileY})`,
      reachMm: placement.tileSizeMm,
      stated,
      ownContainerBytes: sized.bytes.length,
      worldBytes: stated.transferredBytes + sized.bytes.length,
      routeRequests: asked.length,
    }, null, 1));
  });
});
