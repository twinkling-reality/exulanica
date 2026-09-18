// @vitest-environment happy-dom

/**
 * The walk page's product path, end to end, with a route standing in for the corridor lane's server.
 *
 * The container here is the committed golden's bytes served AS IF fetched from `/tiles`, which is the
 * only way to exercise the whole path before a corridor street bakes: the corridor lane's development
 * server serves a stand-in that is not a container at all. What this proves is that a tile fetched
 * from the route, checked against the digest its row records, draws exactly as the committed golden
 * draws, and that the page says on screen where the container came from.
 */

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { bakedTileRequest } from '../src/config.js';
import { prepareBakedTileWalk } from '../src/composition/generated-tile.js';
import type { AppEnvironment } from '../src/composition/session-state.js';

// Relative to web/, where the suite runs.
const GOLDEN = resolve('packages/app/src/dev/tiles/tile-conformance.owd');
const TEXTURES = resolve('../assets/textures');
const CITY = '23a5f1075cb3b4438e63fb570ffc33cecc191be782d3e03b068ab7fcd9a2bd8d';
const KEY = '603b9404-e384-444a-815d-ae34af219969';

const golden = new Uint8Array(readFileSync(GOLDEN));
const goldenSha256 = createHash('sha256').update(golden).digest('hex');

/** A file the development page asks for by URL, read from the repository instead. */
function fileFor(url: string): Uint8Array | null {
  const path = url.split('?')[0]!.replace(/^https?:\/\/[^/]+/, '');
  const onDisk = path.startsWith('/@fs') ? path.slice('/@fs'.length) : null;
  if (onDisk !== null) return new Uint8Array(readFileSync(onDisk));
  if (path.includes('/assets/textures/')) {
    return new Uint8Array(readFileSync(resolve(TEXTURES, path.slice(path.indexOf('/assets/textures/') + '/assets/textures/'.length))));
  }
  return null;
}

/** Bytes as a body: this lib's `BodyInit` takes an `ArrayBuffer`, and `slice` gives it its own. */
function body(bytes: Uint8Array): ArrayBuffer {
  return bytes.slice().buffer as ArrayBuffer;
}

function shell(): HTMLElement {
  const element = document.createElement('div');
  document.body.append(element);
  return element;
}

// Each case decodes the committed golden and its texture sets from disk, so the default 5 s is tight.
describe('walking a tile fetched from the product route', { timeout: 30_000 }, () => {
  let asked: string[] = [];

  beforeEach(() => {
    asked = [];
    vi.stubEnv('VITE_EXULANICA_TOKEN', 'a-token-this-test-invented');
    vi.stubGlobal('fetch', async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      asked.push(url);
      if (url.includes('/tiles?')) {
        return new Response(JSON.stringify({
          city_seed: CITY,
          tiles: [{
            baked_tile_id: KEY, tile_x: 2, tile_y: 0, lod: 0,
            tile_inputs_digest: 'b'.repeat(64), container_sha256: goldenSha256, container_bytes: golden.length,
            render_batch_sha256: 'c'.repeat(64), nav_envelope_sha256: 'd'.repeat(64), state: 'baked',
          }],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes(`/tiles/${KEY}/bytes`)) {
        return new Response(body(golden), {
          status: 200,
          headers: {
            'Content-Type': 'application/vnd.exulanica.owd',
            ETag: `"${goldenSha256}"`,
            'X-Exulanica-Tile-Inputs-Digest': 'b'.repeat(64),
          },
        });
      }
      const file = fileFor(url);
      if (file !== null) return new Response(body(file), { status: 200 });
      return new Response('not here', { status: 404 });
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    document.body.replaceChildren();
  });

  it('fetches by coordinate, checks the container against its row and draws what the golden draws', async () => {
    const request = bakedTileRequest(`?preview=1&city=${CITY}&tile_x=2&tile_y=0`, true);
    expect(request).not.toBeNull();
    const element = shell();
    const tile = await prepareBakedTileWalk({ shell: element, preview: true } as unknown as AppEnvironment, request!);

    expect(tile.ranges.length).toBeGreaterThan(0);
    expect(asked.some((url) => url.includes('/tiles?city_seed='))).toBe(true);
    expect(asked.some((url) => url.includes(`/tiles/${KEY}/bytes`))).toBe(true);

    const statement = element.querySelector('.generated-tile-evaluation');
    expect(statement?.textContent).toContain('fetched from /tiles');
    expect(statement?.textContent).toContain(goldenSha256);
    expect(statement?.textContent).toContain('committed library');
  });

  it('opens at a stated pose, faces where the facing points, and says the pose was stated', async () => {
    const element = shell();
    const tile = await prepareBakedTileWalk(
      { shell: element, preview: true } as unknown as AppEnvironment,
      { kind: 'key', bakedTileId: KEY, pose: { xMm: 4000, yMm: 3000, facingDx: 1, facingDy: 0 } },
    );
    // The tile frame has x east and y north in millimetres; the renderer has x east and z south in
    // metres, and yaw 0 looks north, so a facing of (1, 0) is a quarter turn clockwise from north.
    expect(tile.start.x).toBeCloseTo(4, 6);
    expect(tile.start.z).toBeCloseTo(-3, 6);
    expect(tile.start.yaw).toBeCloseTo(-Math.PI / 2, 6);
    expect(element.querySelector('.generated-tile-evaluation')?.textContent)
      .toContain('Opened at a stated pose: 4000, 3000 mm, facing (1, 0)');
  });

  it('says plainly when nobody stated a pose, so an arbitrary frame cannot look like a chosen one', async () => {
    const element = shell();
    await prepareBakedTileWalk(
      { shell: element, preview: true } as unknown as AppEnvironment,
      { kind: 'key', bakedTileId: KEY, pose: null },
    );
    expect(element.querySelector('.generated-tile-evaluation')?.textContent)
      .toContain("Opened at this runtime's default pose");
  });

  it('refuses a container whose bytes are not the digest its row records, and draws nothing', async () => {
    vi.stubGlobal('fetch', async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      if (url.includes(`/tiles/${KEY}/bytes`)) {
        return new Response(body(new Uint8Array([...golden, 0])), {
          status: 200,
          headers: { 'Content-Type': 'application/vnd.exulanica.owd', ETag: `"${goldenSha256}"` },
        });
      }
      if (url.includes('/tiles?')) {
        return new Response(JSON.stringify({ city_seed: CITY, tiles: [] }), { status: 200 });
      }
      const file = fileFor(url);
      return file === null ? new Response('not here', { status: 404 }) : new Response(body(file), { status: 200 });
    });
    const element = shell();
    await expect(prepareBakedTileWalk(
      { shell: element, preview: true } as unknown as AppEnvironment,
      { kind: 'key', bakedTileId: KEY, pose: null },
    )).rejects.toThrow(/hashes to/);
    expect(element.querySelector('.generated-tile-evaluation')).toBeNull();
  });

  it('refuses without a development token rather than asking the route anonymously', async () => {
    vi.stubEnv('VITE_EXULANICA_TOKEN', '');
    const element = shell();
    await expect(prepareBakedTileWalk(
      { shell: element, preview: true } as unknown as AppEnvironment,
      { kind: 'key', bakedTileId: KEY, pose: null },
    )).rejects.toThrow(/No development token/);
    expect(asked).toHaveLength(0);
  });

  it('refuses off the development preview route', async () => {
    const element = shell();
    await expect(prepareBakedTileWalk(
      { shell: element, preview: false } as unknown as AppEnvironment,
      { kind: 'key', bakedTileId: KEY, pose: null },
    )).rejects.toThrow(/development preview route/);
    expect(asked).toHaveLength(0);
  });
});
