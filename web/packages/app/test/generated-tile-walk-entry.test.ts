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
      .toEqual({ kind: 'coordinate', citySeed: CITY, tileX: 2, tileY: 0, lod: 0 });
  });

  it('reads a negative coordinate and a stated level of detail', () => {
    const search = `?preview=1&city=${CITY}&tile_x=-3&tile_y=7&lod=2`;
    expect(bakedTileRequest(search, isAtlasPreview(search, true)))
      .toEqual({ kind: 'coordinate', citySeed: CITY, tileX: -3, tileY: 7, lod: 2 });
  });

  it('takes a key as the shortcut, and prefers it when a search carries both', () => {
    const search = `?preview=1&baked_tile=${KEY}&city=${CITY}&tile_x=2&tile_y=0`;
    expect(bakedTileRequest(search, isAtlasPreview(search, true))).toEqual({ kind: 'key', bakedTileId: KEY });
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

  it('cannot be confused with the committed golden path', () => {
    const golden = '?preview=1&tile=tile-conformance';
    expect(generatedTileEvaluationName(golden, true)).toBe('tile-conformance');
    expect(bakedTileRequest(golden, true)).toBeNull();
    const fetched = `?preview=1&city=${CITY}&tile_x=2&tile_y=0`;
    expect(generatedTileEvaluationName(fetched, true)).toBeNull();
    expect(bakedTileRequest(fetched, true)).not.toBeNull();
  });
});
