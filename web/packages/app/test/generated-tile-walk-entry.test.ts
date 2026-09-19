/**
 * Who may ask for a baked tile from the product route, and how the ask is read.
 *
 * The golden path beside this one names a tile committed to this repository; this one names a
 * container fetched from `/tiles` with a credential, because a baked corridor street is never
 * committed. Both are refused off the development preview route, and a production build carries
 * neither: `generated-tile-evaluation.test.ts` builds the app and proves it.
 */

import { describe, expect, it } from 'vitest';
import { bakedTileRequest, generatedTileEvaluationName, isAtlasPreview } from '../src/config.js';

const CITY = '23a5f1075cb3b4438e63fb570ffc33cecc191be782d3e03b068ab7fcd9a2bd8d';
const KEY = '603b9404-e384-444a-815d-ae34af219969';

describe('asking for a baked tile', () => {
  it('reads a city seed and coordinate on the preview route, defaulting the level of detail to 0', () => {
    const search = `?preview=1&city=${CITY}&tile_x=2&tile_y=0`;
    expect(bakedTileRequest(search, isAtlasPreview(search, true)))
      .toEqual({ kind: 'coordinate', citySeed: CITY, tileX: 2, tileY: 0, lod: 0, pose: null, reachMm: null });
  });

  it('reads a negative coordinate and a stated level of detail', () => {
    const search = `?preview=1&city=${CITY}&tile_x=-3&tile_y=7&lod=2`;
    expect(bakedTileRequest(search, isAtlasPreview(search, true)))
      .toEqual({ kind: 'coordinate', citySeed: CITY, tileX: -3, tileY: 7, lod: 2, pose: null, reachMm: null });
  });

  it('takes a key as the shortcut, and prefers it when a search carries both', () => {
    const search = `?preview=1&baked_tile=${KEY}&city=${CITY}&tile_x=2&tile_y=0`;
    expect(bakedTileRequest(search, isAtlasPreview(search, true))).toEqual({ kind: 'key', bakedTileId: KEY, pose: null, reachMm: null });
  });

  it('asks for nothing off the preview route, and nothing at all in a production build', () => {
    const search = `?preview=1&city=${CITY}&tile_x=2&tile_y=0`;
    expect(bakedTileRequest(search, isAtlasPreview(search, false))).toBeNull();
    expect(bakedTileRequest(`?city=${CITY}&tile_x=2&tile_y=0`, isAtlasPreview('', true))).toBeNull();
  });

  it('refuses a seed, key or coordinate that is not what it claims to be', () => {
    const preview = true;
    expect(bakedTileRequest('?preview=1&city=not-a-seed&tile_x=2&tile_y=0', preview)).toBeNull();
    expect(bakedTileRequest(`?preview=1&city=${CITY.toUpperCase()}&tile_x=2&tile_y=0`, preview)).toBeNull();
    expect(bakedTileRequest('?preview=1&baked_tile=../../etc/passwd', preview)).toBeNull();
    expect(bakedTileRequest(`?preview=1&city=${CITY}&tile_x=2`, preview)).toBeNull();
    expect(bakedTileRequest(`?preview=1&city=${CITY}&tile_x=2.5&tile_y=0`, preview)).toBeNull();
    expect(bakedTileRequest(`?preview=1&city=${CITY}&tile_x=2&tile_y=0&lod=-1`, preview)).toBeNull();
    expect(bakedTileRequest(`?preview=1&city=${CITY}&tile_x=99999999&tile_y=0`, preview)).toBeNull();
  });

  it('reads a stated pose as integer millimetres and an integer facing', () => {
    const search = `?preview=1&city=${CITY}&tile_x=2&tile_y=0&pose_x_mm=320000&pose_y_mm=64500&facing_dx=-1&facing_dy=0`;
    expect(bakedTileRequest(search, true)).toEqual({
      kind: 'coordinate', citySeed: CITY, tileX: 2, tileY: 0, lod: 0,
      pose: { xMm: 320000, yMm: 64500, facingDx: -1, facingDy: 0 }, reachMm: null,
    });
  });

  it('reads how far the walk may go, which is what decides its world, and refuses a malformed one', () => {
    // The page does not know a route length: a threshold bound in retained records is stated by
    // whoever defines the walk. Absent means one tile; malformed refuses, as a malformed pose does.
    const base = `?preview=1&city=${CITY}&tile_x=2&tile_y=0`;
    expect(bakedTileRequest(`${base}&walk_reach_mm=131000`, true)?.reachMm).toBe(131_000);
    expect(bakedTileRequest(base, true)?.reachMm).toBeNull();
    expect(bakedTileRequest(`${base}&walk_reach_mm=131000.5`, true)).toBeNull();
    expect(bakedTileRequest(`${base}&walk_reach_mm=`, true)).toBeNull();
    expect(bakedTileRequest(`${base}&walk_reach_mm=-1`, true)).toBeNull();
  });

  it('states no pose when none is given, which is the runtime default', () => {
    const search = `?preview=1&city=${CITY}&tile_x=2&tile_y=0`;
    expect(bakedTileRequest(search, true)?.pose).toBeNull();
  });

  it('refuses the WHOLE request when a pose is malformed, rather than falling back to the default', () => {
    // A silent fallback is how a frame that is not reproducible ends up in a record looking like one
    // that is: the picture would look perfectly fine.
    const partial = `?preview=1&city=${CITY}&tile_x=2&tile_y=0&pose_x_mm=320000&pose_y_mm=64500&facing_dx=-1`;
    expect(bakedTileRequest(partial, true)).toBeNull();
    const float = `?preview=1&city=${CITY}&tile_x=2&tile_y=0&pose_x_mm=320000.5&pose_y_mm=64500&facing_dx=-1&facing_dy=0`;
    expect(bakedTileRequest(float, true)).toBeNull();
    const noDirection = `?preview=1&city=${CITY}&tile_x=2&tile_y=0&pose_x_mm=320000&pose_y_mm=64500&facing_dx=0&facing_dy=0`;
    expect(bakedTileRequest(noDirection, true)).toBeNull();
    const wordy = `?preview=1&city=${CITY}&tile_x=2&tile_y=0&pose_x_mm=north&pose_y_mm=64500&facing_dx=-1&facing_dy=0`;
    expect(bakedTileRequest(wordy, true)).toBeNull();
  });

  it('cannot be confused with the committed golden path', () => {
    const golden = '?preview=1&tile=tile-conformance';
    expect(generatedTileEvaluationName(golden, true)).toBe('tile-conformance');
    expect(bakedTileRequest(golden, true)).toBeNull();
    const fetched = `?preview=1&city=${CITY}&tile_x=2&tile_y=0`;
    expect(generatedTileEvaluationName(fetched, true)).toBeNull();
    expect(bakedTileRequest(fetched, true)).not.toBeNull();
  });
});
