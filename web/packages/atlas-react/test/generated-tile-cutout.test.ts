// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { parseTextureSetManifest, type TextureSetDigest } from '@exulanica/atlas-core';
import { TILE_LOOK_V1 } from '../src/playcanvas/generated-tile/look.js';
import { coveragePreservingMips, coverageShare } from '../src/playcanvas/generated-tile/cutout-coverage.js';
import { TileTextureLibrary } from '../src/playcanvas/generated-tile/texture-materials.js';
import { leafCoverageField } from './generated-tile-bench/test-cutout.js';

const subtle = webcrypto.subtle as unknown as TextureSetDigest;
const CUTOFF = 128;

/** Ordinary mip levels: every byte averaged, coverage included. What the class contract forbids. */
function boxMips(rgba: Uint8Array, size: number): Uint8Array[] {
  const levels = [rgba];
  let previous = rgba;
  for (let s = size; s > 1; s >>= 1) {
    const n = s >> 1;
    const next = new Uint8Array(n * n * 4);
    for (let y = 0; y < n; y += 1) {
      for (let x = 0; x < n; x += 1) {
        for (let channel = 0; channel < 4; channel += 1) {
          let sum = 0;
          for (const [dx, dy] of [[0, 0], [1, 0], [0, 1], [1, 1]] as const) sum += previous[((y * 2 + dy) * s + x * 2 + dx) * 4 + channel]!;
          next[(y * n + x) * 4 + channel] = Math.round(sum / 4);
        }
      }
    }
    levels.push(next);
    previous = next;
  }
  return levels;
}

describe('cutout mip levels keep their coverage', () => {
  const size = 256;
  const field = leafCoverageField(size, 900, 20260917);
  const permille = Math.floor(coverageShare(field, CUTOFF) * 1000);

  it('keeps the share of covered texels at coverage_permille on every level, to the nearest texel, where plain averaging thins out', () => {
    expect(permille).toBeGreaterThan(300);
    expect(permille).toBeLessThan(800);
    const kept = coveragePreservingMips(field, size, size, CUTOFF, permille);
    expect(kept.map((level) => Math.sqrt(level.length / 4))).toEqual([256, 128, 64, 32, 16, 8, 4, 2, 1]);
    expect(kept[0]).toBe(field);
    for (const level of kept.slice(1)) {
      const texels = level.length / 4;
      const wanted = Math.round((permille / 1000) * texels);
      // Texels tied with the last one wanted are covered with it; the leaf field has few ties.
      expect(Math.abs(coverageShare(level, CUTOFF) * texels - wanted)).toBeLessThanOrEqual(Math.max(1, texels * 0.01));
    }
    const plain = boxMips(field, size);
    const drift = plain.slice(1, 6).map((level) => Math.abs(coverageShare(level, CUTOFF) - permille / 1000));
    // The contract exists because ordinary levels do not keep it.
    expect(Math.max(...drift)).toBeGreaterThan(0.05);
  });

  it('averages colour by coverage, so empty texels do not darken the leaves', () => {
    const rgba = new Uint8Array([200, 150, 100, 255, 0, 0, 0, 0, 200, 150, 100, 255, 0, 0, 0, 0]);
    const [, top] = coveragePreservingMips(rgba, 2, 2, CUTOFF, 500);
    expect([...top!.subarray(0, 3)]).toEqual([200, 150, 100]);
  });
});

describe('a cutout set as a material', () => {
  const CONFORMANCE = 'packages/loom-texture/test/conformance/';
  const fixtures = parseTextureSetManifest(new Uint8Array(readFileSync(`${CONFORMANCE}manifest.json`)));

  it('tests coverage at the class cutoff, never blends, writes depth, and lights both faces', async () => {
    const device = new pc.NullGraphicsDevice(document.createElement('canvas'));
    const textures = new TileTextureLibrary(device, TILE_LOOK_V1, fixtures, async (entry) =>
      new Uint8Array(readFileSync(`${CONFORMANCE}${entry.setId}.ltex`)), subtle);
    const resolution = await textures.resolve('fixture.cutout');
    if (resolution.state !== 'available' || resolution.set.classParameters.materialClass !== 'cutout') throw new Error('the cutout fixture draws');
    const { material, set } = resolution;
    const parameters = set.classParameters as Extract<typeof set.classParameters, { materialClass: 'cutout' }>;
    expect(material.alphaTest).toBe(parameters.alphaCutoff / 255);
    expect(material.opacityMap).toBe(material.diffuseMap);
    expect(material.opacityMapChannel).toBe('a');
    expect(material.blendType).toBe(pc.BLEND_NONE);
    expect(material.depthWrite).toBe(true);
    expect(material.cull).toBe(pc.CULLFACE_NONE);
    expect(material.twoSidedLighting).toBe(true);
    expect(material.normalMap).not.toBeNull();
    // The colour map is uploaded with every level already built. The fixture holds two coverage values
    // in a regular pattern, so its small levels tie: a scale covers tied texels together, never fewer
    // than wanted. Its first two levels, whose texels differ, keep the share exactly.
    const colour = material.diffuseMap as pc.Texture & { _levels: Uint8Array[] };
    const width = set.entry.width;
    expect(colour._levels).toHaveLength(Math.log2(width) + 1);
    const covered = colour._levels.map((level) => Math.round(coverageShare(level, parameters.alphaCutoff) * (level.length / 4)));
    const wanted = colour._levels.map((level) => Math.round((parameters.coveragePermille / 1000) * (level.length / 4)));
    expect(covered.slice(0, 2)).toEqual(wanted.slice(0, 2));
    covered.forEach((count, level) => expect(count).toBeGreaterThanOrEqual(wanted[level]!));
    textures.destroy();
  });
});
