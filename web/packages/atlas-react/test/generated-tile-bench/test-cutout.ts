/**
 * TEST-ONLY TEXTURE. Never shipped, never published, never a placeholder for foliage.
 *
 * A procedural leaf coverage field in the shape of a v2 `cutout` set, so the cutout binding can be
 * measured on the bench before the texture lane publishes its foliage set: overlapping soft discs of
 * coverage over a tiling square, with flat normals and a matte surface. Its coverage is measured the
 * way a reader measures it, and the set is handed to the runtime as a decoded set, not a container.
 */

import {
  TEXTURE_SET_ALPHA_CUTOFF,
  TEXTURE_SET_LICENCE_ID,
  TEXTURE_SET_PROFILE_V2,
  type DecodedTextureSet,
} from '@exulanica/atlas-core';

/** The share of texels at or above the class cutoff, in thousandths, floored, as a reader measures it. */
export function measuredCoveragePermille(rgba: Uint8Array): number {
  let covered = 0;
  for (let at = 3; at < rgba.length; at += 4) if (rgba[at]! >= TEXTURE_SET_ALPHA_CUTOFF) covered += 1;
  return Math.floor((covered * 1000) / (rgba.length / 4));
}

/** Overlapping soft discs of coverage over a tiling square, deterministic for a seed. RGBA, sRGB colour. */
export function leafCoverageField(size: number, discs: number, seed: number): Uint8Array {
  let state = seed >>> 0;
  const random = (): number => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 2 ** 32;
  };
  const alpha = new Float64Array(size * size);
  const shade = new Float64Array(size * size);
  for (let disc = 0; disc < discs; disc += 1) {
    const cx = random() * size;
    const cy = random() * size;
    const radius = size * (0.01 + random() * 0.03);
    const tone = random();
    const reach = Math.ceil(radius);
    for (let dy = -reach; dy <= reach; dy += 1) {
      for (let dx = -reach; dx <= reach; dx += 1) {
        const falloff = 1 - Math.hypot(dx, dy) / radius;
        if (falloff <= 0) continue;
        const x = (((Math.floor(cx) + dx) % size) + size) % size;
        const y = (((Math.floor(cy) + dy) % size) + size) % size;
        const value = Math.min(1, falloff * 2.2);
        if (value > alpha[y * size + x]!) {
          alpha[y * size + x] = value;
          shade[y * size + x] = tone;
        }
      }
    }
  }
  const rgba = new Uint8Array(size * size * 4);
  for (let texel = 0; texel < size * size; texel += 1) {
    const tone = shade[texel]!;
    rgba[texel * 4] = Math.round(45 + tone * 40);
    rgba[texel * 4 + 1] = Math.round(90 + tone * 50);
    rgba[texel * 4 + 2] = Math.round(30 + tone * 20);
    rgba[texel * 4 + 3] = Math.round(alpha[texel]! * 255);
  }
  return rgba;
}

/**
 * The leaf field as a decoded v2 cutout set: 512 texels over 2000 mm, as the proposal sizes foliage.
 * `discs` sets how dense the leaves are; each density is its own set id.
 */
export function testCutoutSet(size = 512, extentMm = 2000, discs = Math.round((size * size) / 290)): DecodedTextureSet {
  const colour = leafCoverageField(size, discs, 20260917);
  const texels = size * size;
  const normal = new Uint8Array(texels * 2).fill(128);
  const orm = new Uint8Array(texels * 3);
  for (let texel = 0; texel < texels; texel += 1) {
    orm[texel * 3] = 255;
    orm[texel * 3 + 1] = 190;
    orm[texel * 3 + 2] = 0;
  }
  const channels = Object.freeze([
    { map: 'base_color_coverage', components: 4, holds: ['red', 'green', 'blue', 'coverage'], srgb: true },
    { map: 'normal', components: 2, holds: ['normal_x', 'normal_y'], srgb: false },
    { map: 'orm', components: 3, holds: ['occlusion', 'roughness', 'metalness'], srgb: false },
  ] as const);
  const coveragePermille = measuredCoveragePermille(colour);
  return Object.freeze({
    entry: Object.freeze({
      setId: `test.leaf-coverage-field-${discs}`,
      version: 1,
      contentSha256: '0'.repeat(64),
      byteSize: colour.length + normal.length + orm.length,
      width: size,
      height: size,
      channels,
      extentUMm: extentMm,
      extentVMm: extentMm,
      licenceId: TEXTURE_SET_LICENCE_ID,
      licenceSha256: '0'.repeat(64),
      containerProfile: TEXTURE_SET_PROFILE_V2,
      materialClass: 'cutout',
    }),
    profile: TEXTURE_SET_PROFILE_V2,
    materialClass: 'cutout',
    makerKind: 'procedural',
    classParameters: Object.freeze({ materialClass: 'cutout', alphaCutoff: TEXTURE_SET_ALPHA_CUTOFF, coveragePermille, doubleSided: true }),
    surface: 'vertical',
    title: 'Test leaf coverage field (bench only)',
    heightRangeMm: 20,
    channels,
    maps: Object.freeze({ base_color_coverage: colour, normal, orm }),
  });
}
