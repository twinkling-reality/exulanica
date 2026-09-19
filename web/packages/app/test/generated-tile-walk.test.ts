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
import {
  GENERATED_TILE_OPENING_ATTRIBUTE,
  GENERATED_TILE_POSE_ATTRIBUTE,
  GENERATED_TILE_WORLD_ATTRIBUTE,
  prepareBakedTileWalk,
  prepareGeneratedTileEvaluation,
  worldLine,
} from '../src/composition/generated-tile.js';
import type { LoadedGeneratedTile } from '@exulanica/atlas-react/generated-tile';
import type { AppEnvironment } from '../src/composition/session-state.js';

// Relative to web/, where the suite runs.
const GOLDEN = resolve('packages/app/src/dev/tiles/tile-conformance.owd');
const TEXTURES = resolve('../assets/textures');
// THE GOLDEN'S OWN CITY AND COORDINATE, read from its container rather than invented: the row this
// test serves must agree with the bytes it serves, because the page now chooses a walk's neighbours
// from what the container says about itself and refuses a row that disagrees with it.
const CITY = 'd0219dae956352ef4a56e32030cb6ab1a80bfa5a63fd288e9aacccfb71966a60';
const KEY = '603b9404-e384-444a-815d-ae34af219969';

const golden = new Uint8Array(readFileSync(GOLDEN));
const goldenSha256 = createHash('sha256').update(golden).digest('hex');

/** A second tile for the walk's world: the golden restated as (1,0), one digit of a canonical header. */
const EAST_KEY = '7f0f0d5a-2c31-4d0e-9a44-1b5c2d3e4f50';
const east = (() => {
  const copy = new Uint8Array(golden);
  const headerBytes = new DataView(copy.buffer).getUint32(4, true);
  const header = new TextDecoder().decode(copy.subarray(8, 8 + headerBytes));
  // Anchored on the tile record: every record is listed before it and one of them carries the same
  // field name, so a plain search would edit somebody else's tile.
  const at = header.indexOf('"tile_x":', header.indexOf('"tile":{"fields":'));
  copy[8 + at + '"tile_x":'.length] = '1'.charCodeAt(0);
  return copy;
})();
const eastSha256 = createHash('sha256').update(east).digest('hex');

/** A file the development page asks for by URL, read from the repository instead. */
function fileFor(url: string): Uint8Array | null {
  const path = url.split('?')[0]!.replace(/^https?:\/\/[^/]+/, '');
  const onDisk = path.startsWith('/@fs') ? path.slice('/@fs'.length) : null;
  if (onDisk !== null) return new Uint8Array(readFileSync(onDisk));
  if (path.includes('/dev/tiles/')) {
    return new Uint8Array(readFileSync(resolve('packages/app/src/dev/tiles', path.slice(path.lastIndexOf('/') + 1))));
  }
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
  /** Where the LIST says the golden is. The container says (0,0); a test may make the row disagree. */
  let listedTileX = 0;

  beforeEach(() => {
    asked = [];
    listedTileX = 0;
    vi.stubEnv('VITE_EXULANICA_TOKEN', 'a-token-this-test-invented');
    vi.stubGlobal('fetch', async (input: RequestInfo | URL): Promise<Response> => {
      const url = String(input);
      asked.push(url);
      if (url.includes('/tiles?')) {
        return new Response(JSON.stringify({
          city_seed: CITY,
          tiles: [{
            baked_tile_id: KEY, tile_x: listedTileX, tile_y: 0, lod: 0,
            tile_inputs_digest: 'b'.repeat(64), container_sha256: goldenSha256, container_bytes: golden.length,
            render_batch_sha256: 'c'.repeat(64), nav_envelope_sha256: 'd'.repeat(64), state: 'baked',
          }, {
            baked_tile_id: EAST_KEY, tile_x: 1, tile_y: 0, lod: 0,
            tile_inputs_digest: 'b'.repeat(64), container_sha256: eastSha256, container_bytes: east.length,
            render_batch_sha256: 'c'.repeat(64), nav_envelope_sha256: 'd'.repeat(64), state: 'baked',
          }],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      if (url.includes(`/tiles/${EAST_KEY}/bytes`)) {
        return new Response(body(east), {
          status: 200,
          headers: { 'Content-Type': 'application/vnd.exulanica.owd', ETag: `"${eastSha256}"` },
        });
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
    const request = bakedTileRequest(`?preview=1&city=${CITY}&tile_x=0&tile_y=0`, true);
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
      { kind: 'key', bakedTileId: KEY, pose: { xMm: 4000, yMm: 3000, facingDx: 1, facingDy: 0 }, reachMm: null },
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
      { kind: 'key', bakedTileId: KEY, pose: null, reachMm: null },
    );
    expect(element.querySelector('.generated-tile-evaluation')?.textContent)
      .toContain("Opened at this runtime's default pose");
  });

  it('does not claim a development tile is the committed golden, and gives the digest instead', async () => {
    // A lane baking its own tile into dev/tiles is the normal case, not the odd one: the page cannot
    // know what is committed, so it must not say "committed to this repository" about bytes it read
    // from a working tree.
    const element = shell();
    await prepareGeneratedTileEvaluation({ shell: element, preview: true } as unknown as AppEnvironment, 'tile-conformance');
    const said = element.querySelector('.generated-tile-evaluation')?.textContent ?? '';
    expect(said).toContain("served from this development server's working tree");
    expect(said).toContain(goldenSha256);
    expect(said).not.toContain('committed to this repository');
  });

  it('states the opening as data on the shell, which is what a check binds', async () => {
    // The sentence is for a person. A check that had to parse it would read a reworded default line
    // as a stated pose and pass a frame nobody stated, so the same fact is stated as data.
    const element = shell();
    await prepareBakedTileWalk(
      { shell: element, preview: true } as unknown as AppEnvironment,
      { kind: 'key', bakedTileId: KEY, pose: { xMm: 4000, yMm: 3000, facingDx: 1, facingDy: 0 }, reachMm: null },
    );
    expect(element.getAttribute(GENERATED_TILE_OPENING_ATTRIBUTE)).toBe('stated');
    expect(element.getAttribute(GENERATED_TILE_POSE_ATTRIBUTE)).toBe('4000,3000,1,0');
  });

  it('says default as data, and carries no pose attribute to be misread as one', async () => {
    const element = shell();
    await prepareBakedTileWalk(
      { shell: element, preview: true } as unknown as AppEnvironment,
      { kind: 'key', bakedTileId: KEY, pose: null, reachMm: null },
    );
    expect(element.getAttribute(GENERATED_TILE_OPENING_ATTRIBUTE)).toBe('default');
    expect(element.hasAttribute(GENERATED_TILE_POSE_ATTRIBUTE)).toBe(false);
  });

  it('lets the committed golden route state a pose too, so the check has a credential-free case', async () => {
    const element = shell();
    window.history.replaceState(null, '', '/?preview=1&tile=tile-conformance&pose_x_mm=9000&pose_y_mm=7000&facing_dx=0&facing_dy=-1');
    try {
      const tile = await prepareGeneratedTileEvaluation({ shell: element, preview: true } as unknown as AppEnvironment, 'tile-conformance');
      expect(element.getAttribute(GENERATED_TILE_OPENING_ATTRIBUTE)).toBe('stated');
      expect(element.getAttribute(GENERATED_TILE_POSE_ATTRIBUTE)).toBe('9000,7000,0,-1');
      // Facing (0, -1) is south, a half turn from yaw 0, which looks north.
      expect(Math.abs(tile.start.yaw)).toBeCloseTo(Math.PI, 6);
      expect(tile.start.x).toBeCloseTo(9, 6);
      expect(tile.start.z).toBeCloseTo(-7, 6);
    } finally {
      window.history.replaceState(null, '', '/');
    }
  });

  it('refuses a malformed pose on the golden route rather than opening at a default', async () => {
    const element = shell();
    window.history.replaceState(null, '', '/?preview=1&tile=tile-conformance&pose_x_mm=9000&pose_y_mm=7000&facing_dx=0&facing_dy=0');
    try {
      await expect(prepareGeneratedTileEvaluation({ shell: element, preview: true } as unknown as AppEnvironment, 'tile-conformance'))
        .rejects.toThrow(/refused rather than opened at a default/);
    } finally {
      window.history.replaceState(null, '', '/');
    }
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
      { kind: 'key', bakedTileId: KEY, pose: null, reachMm: null },
    )).rejects.toThrow(/hashes to/);
    expect(element.querySelector('.generated-tile-evaluation')).toBeNull();
  });

  it('refuses without a development token rather than asking the route anonymously', async () => {
    vi.stubEnv('VITE_EXULANICA_TOKEN', '');
    const element = shell();
    await expect(prepareBakedTileWalk(
      { shell: element, preview: true } as unknown as AppEnvironment,
      { kind: 'key', bakedTileId: KEY, pose: null, reachMm: null },
    )).rejects.toThrow(/No development token/);
    expect(asked).toHaveLength(0);
  });

  it('refuses off the development preview route', async () => {
    const element = shell();
    await expect(prepareBakedTileWalk(
      { shell: element, preview: false } as unknown as AppEnvironment,
      { kind: 'key', bakedTileId: KEY, pose: null, reachMm: null },
    )).rejects.toThrow(/development preview route/);
    expect(asked).toHaveLength(0);
  });

  it('asks the route for the neighbour a stated reach names, and checks it is the tile the row claims', async () => {
    // WHAT THIS CAN AND CANNOT PROVE. The walk states how far it may go, which is the only reason any
    // neighbour is asked for, and the page then lists, plans, fetches and checks: all of that runs
    // here. It cannot end with a COMPOSED world, because this repository commits exactly one
    // container and a second tile's bytes would have to be baked.
    //
    // THE NEIGHBOUR SERVED HERE IS THAT CONTAINER WITH ITS `tile_x` RESTATED, and the edit that
    // makes it claim to be (1,0) is the same edit that makes it not itself: it is refused for not
    // baking to its own records, which is the deepest of the three checks this path makes and fires
    // before the other two can. A container that is internally consistent and in the wrong place is
    // caught by the placement check instead, which `generated-tile-walk-world.test.ts` covers with
    // an unedited container under another tile's row. The wording of a composed statement is covered
    // by `worldLine` below.
    const request = bakedTileRequest(`?preview=1&city=${CITY}&tile_x=0&tile_y=0&walk_reach_mm=131000`, true);
    expect(request?.reachMm).toBe(131_000);
    const element = shell();
    await expect(prepareBakedTileWalk({ shell: element, preview: true } as unknown as AppEnvironment, request!))
      .rejects.toThrow(/^Neighbour tile \(1,0\) refused: .*not what its own records bake to/);
    expect(asked.some((url) => url.includes(`/tiles/${EAST_KEY}/bytes`))).toBe(true);
  });

  it('refuses a row that puts its container somewhere the container does not agree with', async () => {
    // A row points at bytes and the BYTES STATE THEIR OWN IDENTITY. Nothing compared them until the
    // walk's neighbours began to be chosen from what the container says about itself: a row pointing
    // at the wrong container would otherwise compose a world out of another part of the city, and
    // every tile would arrive verified, whole, and in the wrong place.
    listedTileX = 5;
    const request = bakedTileRequest(`?preview=1&city=${CITY}&tile_x=5&tile_y=0`, true);
    const element = shell();
    await expect(prepareBakedTileWalk({ shell: element, preview: true } as unknown as AppEnvironment, request!))
      .rejects.toThrow(/lists .* at \(5, 0\) level 0, and the container it served says it is \(0, 0\) level 0/);
  });

  it('refuses a container belonging to a city the walk did not ask for', async () => {
    const request = bakedTileRequest(`?preview=1&city=${'a'.repeat(64)}&tile_x=0&tile_y=0`, true);
    const element = shell();
    await expect(prepareBakedTileWalk({ shell: element, preview: true } as unknown as AppEnvironment, request!))
      .rejects.toThrow(/asked for world a{64} and the container it was served belongs to/);
  });

  it('states the world as data on the shell, so a record binds what was drawn without parsing prose', async () => {
    // The same argument the opening pose is data for. A record that grepped the statement would read
    // a reworded line as a different world, and the thing it must never get wrong is which container
    // drew the frames and which were only stood on.
    const request = bakedTileRequest(`?preview=1&city=${CITY}&tile_x=0&tile_y=0`, true);
    const element = shell();
    await prepareBakedTileWalk({ shell: element, preview: true } as unknown as AppEnvironment, request!);
    // TWO SETS AND THE DIFFERENCE IS THE READER'S. Both hold the one container here, because a walk
    // draws every neighbour it stands on; a container that were ever ground with no street would be
    // in `stoodOn` and not in `drawn`, and nothing about this shape would have to be renamed to say
    // so. `opensOn` is the one the frames are OF, which neither set carries.
    expect(JSON.parse(element.getAttribute(GENERATED_TILE_WORLD_ATTRIBUTE)!)).toEqual({
      reach: 'unstated',
      opensOn: { tile: KEY, tileX: 0, tileY: 0, containerSha256: goldenSha256 },
      drawn: [{ tile: KEY, tileX: 0, tileY: 0, containerSha256: goldenSha256 }],
      stoodOn: [{ tile: KEY, tileX: 0, tileY: 0, containerSha256: goldenSha256 }],
      neighbourTransferredBytes: 0,
      absent: [],
    });
  });

  it('says which containers were drawn and which were ground with no street, and names the squares with no ground', () => {
    const fetched = {
      neighbours: [
        { name: 'tile (1,0)', tileX: 1, tileY: 0, bytes: new Uint8Array(), containerSha256: 'aaaa1111'.padEnd(64, '0'), transferredBytes: 12 },
        { name: 'tile (3,0)', tileX: 3, tileY: 0, bytes: new Uint8Array(), containerSha256: 'bbbb2222'.padEnd(64, '0'), transferredBytes: 34 },
      ],
      transferredBytes: 46,
      absent: [{ tileX: 1, tileY: 1, reason: 'no_row' }, { tileX: 2, tileY: 1, reason: 'nondeterminism_detected' }],
    };
    const loaded = (worldTiles: { name: string; drawn: boolean; stoodOn: boolean }[]) =>
      ({ name: 'the-drawn-tile', worldTiles } as unknown as LoadedGeneratedTile);
    const composed = worldLine(fetched, loaded([
      { name: 'the-drawn-tile', drawn: true, stoodOn: true },
      { name: 'tile (1,0)', drawn: true, stoodOn: true },
      { name: 'tile (3,0)', drawn: true, stoodOn: true },
    ]));
    expect(composed).toContain('World: 3 containers, opening on the-drawn-tile');
    expect(composed).toContain('Drawn and stood on: the-drawn-tile, tile (1,0) aaaa1111, tile (3,0) bbbb2222');
    expect(composed).toContain('None is ground without a street.');
    expect(composed).toContain('46 bytes fetched for the neighbours');
    // The two absences are different facts and the line keeps them apart.
    expect(composed).toContain('No ground within reach at: (1,1) no_row, (2,1) nondeterminism_detected.');
    expect(worldLine(null, loaded([]))).toContain('World: this one tile');

    // AND THE CASE THE DIFFERENCE EXISTS FOR, which no run reaches today and which this line has to
    // be able to say the moment one does: a neighbour served its ground and not its street.
    const partial = worldLine(fetched, loaded([
      { name: 'the-drawn-tile', drawn: true, stoodOn: true },
      { name: 'tile (1,0)', drawn: true, stoodOn: true },
      { name: 'tile (3,0)', drawn: false, stoodOn: true },
    ]));
    expect(partial).toContain('Drawn and stood on: the-drawn-tile, tile (1,0) aaaa1111.');
    expect(partial).toContain('STOOD ON AND NOT DRAWN: tile (3,0) bbbb2222.');
  });

  it('asks for no neighbour and says the world is one tile when the walk states no reach', async () => {
    const request = bakedTileRequest(`?preview=1&city=${CITY}&tile_x=0&tile_y=0`, true);
    expect(request?.reachMm).toBeNull();
    const element = shell();
    await prepareBakedTileWalk({ shell: element, preview: true } as unknown as AppEnvironment, request!);

    expect(asked.some((url) => url.includes(`/tiles/${EAST_KEY}/bytes`))).toBe(false);
    const statement = element.querySelector('.generated-tile-evaluation')?.textContent ?? '';
    expect(statement).toContain('World: this one tile');
    expect(statement).toContain('stated no reach');
  });

  it('refuses a walk_reach_mm that is not a whole number, rather than falling back to one tile', () => {
    expect(bakedTileRequest(`?preview=1&city=${CITY}&tile_x=0&tile_y=0&walk_reach_mm=lots`, true)).toBeNull();
    expect(bakedTileRequest(`?preview=1&city=${CITY}&tile_x=0&tile_y=0&walk_reach_mm=-1`, true)).toBeNull();
  });
});

