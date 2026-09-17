/**
 * TEST-ONLY TEXTURE. Never shipped, never published, never a placeholder for road paint.
 *
 * A worn white lane line in the shape of a v2 procedural `decal` set, so the decal binding can be
 * measured on the bench before the texture lane publishes its road paint: 256 x 64 texels over
 * 1000 x 250 mm (the proposal's road paint sizing), a 120 mm band of paint across the middle whose
 * coverage wears in small patches, flat normals and a matte surface.
 */

import { TEXTURE_SET_ALPHA_CUTOFF, TEXTURE_SET_LICENCE_ID, TEXTURE_SET_PROFILE_V2, type DecodedTextureSet } from '@exulanica/atlas-core';

export function testDecalSet(width = 256, height = 64, extentUMm = 1000, extentVMm = 250): DecodedTextureSet {
  const texels = width * height;
  const colour = new Uint8Array(texels * 4);
  let covered = 0;
  for (let y = 0; y < height; y += 1) {
    const vMm = ((y + 0.5) / height) * extentVMm;
    const inBand = Math.abs(vMm - extentVMm / 2) <= 60;
    for (let x = 0; x < width; x += 1) {
      const at = (y * width + x) * 4;
      // Wear: small patches where the paint thins, periodic along u so the set tiles.
      const wear = (Math.sin((2 * Math.PI * 7 * x) / width) * Math.sin((2 * Math.PI * 3 * y) / height) + 1) / 2;
      const coverage = inBand ? Math.round(255 * (wear > 0.85 ? 0.55 : 1)) : 0;
      colour[at] = 236; colour[at + 1] = 234; colour[at + 2] = 226; colour[at + 3] = coverage;
      if (coverage >= TEXTURE_SET_ALPHA_CUTOFF) covered += 1;
    }
  }
  const normal = new Uint8Array(texels * 2).fill(128);
  const orm = new Uint8Array(texels * 3);
  for (let texel = 0; texel < texels; texel += 1) { orm[texel * 3] = 255; orm[texel * 3 + 1] = 200; orm[texel * 3 + 2] = 0; }
  const channels = Object.freeze([
    { map: 'base_color_coverage', components: 4, holds: ['red', 'green', 'blue', 'coverage'], srgb: true },
    { map: 'normal', components: 2, holds: ['normal_x', 'normal_y'], srgb: false },
    { map: 'orm', components: 3, holds: ['occlusion', 'roughness', 'metalness'], srgb: false },
  ] as const);
  return Object.freeze({
    entry: Object.freeze({
      setId: 'test.worn-lane-line', version: 1, contentSha256: '0'.repeat(64), byteSize: colour.length + normal.length + orm.length,
      width, height, channels, extentUMm, extentVMm, licenceId: TEXTURE_SET_LICENCE_ID, licenceSha256: '0'.repeat(64),
      containerProfile: TEXTURE_SET_PROFILE_V2, materialClass: 'decal',
    }),
    profile: TEXTURE_SET_PROFILE_V2,
    materialClass: 'decal',
    makerKind: 'procedural',
    classParameters: Object.freeze({ materialClass: 'decal', coveragePermille: Math.floor((covered * 1000) / texels) }),
    surface: 'horizontal',
    title: 'Test worn lane line (bench only)',
    heightRangeMm: 2,
    channels,
    maps: Object.freeze({ base_color_coverage: colour, normal, orm }),
  });
}
