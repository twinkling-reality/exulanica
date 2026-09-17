/**
 * TEST-ONLY TEXTURE AND BACKING. Never shipped, never published, never a placeholder for a shop window.
 *
 * `testGlazingSet` is clean float glass in the shape of a v2 procedural `glazing` set, so the glazing
 * binding can be measured on the bench before the texture lane publishes its glazing set: a faint green
 * tint, full transmission and nearly smooth, with an optional share of film patches. `backingTexels` is
 * a high-contrast checker for a test-only surface drawn at a stated depth behind the pane, standing in
 * for what the grammar will state lies behind glazing (a vitrine or an interior backing), which it does
 * not yet carry.
 */

import {
  TEXTURE_SET_GLAZING_IOR_MILLIONTHS,
  TEXTURE_SET_LICENCE_ID,
  TEXTURE_SET_PROFILE_V2,
  type DecodedTextureSet,
} from '@exulanica/atlas-core';

/** How far behind the pane the test backing stands, in metres. */
export const TEST_BACKING_DEPTH_M = 0.6;

/** Clean glass: tint (246, 250, 247), transmission 255, roughness 5 (20 in 1000), film patches over `filmShare` of texels. */
export function testGlazingSet(size = 512, extentMm = 2000, filmShare = 0): DecodedTextureSet {
  const texels = size * size;
  const colour = new Uint8Array(texels * 3);
  const transmissionRoughness = new Uint8Array(texels * 2);
  const film = [150, 144, 132];
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const texel = y * size + x;
      // Film in soft patches: a smooth periodic field, covered where it rises above a share.
      const field = (Math.sin((2 * Math.PI * 3 * x) / size) * Math.sin((2 * Math.PI * 2 * y) / size) + 1) / 2;
      const covered = filmShare <= 0 ? 0 : Math.max(0, Math.min(1, (field - (1 - filmShare)) / 0.15));
      const tint = [246, 250, 247];
      for (let channel = 0; channel < 3; channel += 1) {
        colour[texel * 3 + channel] = Math.round(tint[channel]! + (film[channel]! - tint[channel]!) * covered);
      }
      transmissionRoughness[texel * 2] = Math.round(255 * (1 - covered));
      transmissionRoughness[texel * 2 + 1] = Math.round(5 + (166 - 5) * covered);
    }
  }
  const channels = Object.freeze([
    { map: 'base_color', components: 3, holds: ['red', 'green', 'blue'], srgb: true },
    { map: 'transmission_roughness', components: 2, holds: ['transmission', 'roughness'], srgb: false },
  ] as const);
  return Object.freeze({
    entry: Object.freeze({
      setId: `test.clean-glazing-${Math.round(filmShare * 100)}`,
      version: 1,
      contentSha256: '0'.repeat(64),
      byteSize: colour.length + transmissionRoughness.length,
      width: size,
      height: size,
      channels,
      extentUMm: extentMm,
      extentVMm: extentMm,
      licenceId: TEXTURE_SET_LICENCE_ID,
      licenceSha256: '0'.repeat(64),
      containerProfile: TEXTURE_SET_PROFILE_V2,
      materialClass: 'glazing',
    }),
    profile: TEXTURE_SET_PROFILE_V2,
    materialClass: 'glazing',
    makerKind: 'procedural',
    classParameters: Object.freeze({
      materialClass: 'glazing', iorMillionths: TEXTURE_SET_GLAZING_IOR_MILLIONTHS, doubleSided: false,
      filmSrgb: Object.freeze([150, 144, 132]) as unknown as readonly [number, number, number], filmRoughnessPermille: 650,
    }),
    surface: 'vertical',
    title: 'Test clean glazing (bench only)',
    heightRangeMm: null,
    channels,
    maps: Object.freeze({ base_color: colour, transmission_roughness: transmissionRoughness }),
  });
}

/** A black and white checker of `cells` squares a side, RGBA: the test backing's pattern. */
export function backingTexels(size: number, cells: number): Uint8Array {
  const out = new Uint8Array(size * size * 4);
  const cell = size / cells;
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const white = (Math.floor(x / cell) + Math.floor(y / cell)) % 2 === 0;
      const at = (y * size + x) * 4;
      out[at] = out[at + 1] = out[at + 2] = white ? 225 : 25;
      out[at + 3] = 255;
    }
  }
  return out;
}
