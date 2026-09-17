// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { parseTextureSetManifest, type TextureSetDigest } from '@exulanica/atlas-core';
import { TILE_LOOK_V1 } from '../src/playcanvas/generated-tile/look.js';
import {
  DECAL_DEPTH_BIAS,
  DECAL_DRAW_BUCKET,
  DECAL_SLOPE_DEPTH_BIAS,
  GLAZING_DRAW_BUCKET,
  TileTextureLibrary,
  castsShadow,
  drawBucket,
  undrawnClassReason,
} from '../src/playcanvas/generated-tile/texture-materials.js';

const subtle = webcrypto.subtle as unknown as TextureSetDigest;
const CONFORMANCE = 'packages/loom-texture/test/conformance/';
const fixtures = parseTextureSetManifest(new Uint8Array(readFileSync(`${CONFORMANCE}manifest.json`)));

describe('a decal set as a material', () => {
  it('blends by coverage, tests depth without writing it, is pulled in front of its surface, and casts no shadow', async () => {
    const device = new pc.NullGraphicsDevice(document.createElement('canvas'));
    const textures = new TileTextureLibrary(device, TILE_LOOK_V1, fixtures, async (entry) =>
      new Uint8Array(readFileSync(`${CONFORMANCE}${entry.setId}.ltex`)), subtle);
    const resolution = await textures.resolve('fixture.decal');
    if (resolution.state !== 'available' || resolution.set.classParameters.materialClass !== 'decal') throw new Error('the decal fixture draws');
    const { material, set } = resolution;
    expect(undrawnClassReason(set)).toBeNull();
    expect(material.opacityMap).toBe(material.diffuseMap);
    expect(material.opacityMapChannel).toBe('a');
    expect(material.blendType).toBe(pc.BLEND_NORMAL);
    expect(material.alphaTest).toBe(0);
    expect(material.depthTest).toBe(true);
    expect(material.depthWrite).toBe(false);
    expect(material.depthBias).toBe(DECAL_DEPTH_BIAS);
    expect(material.slopeDepthBias).toBe(DECAL_SLOPE_DEPTH_BIAS);
    expect(DECAL_DEPTH_BIAS).toBeLessThan(0);
    expect(DECAL_SLOPE_DEPTH_BIAS).toBeLessThan(0);
    // Lit with its own maps.
    expect(material.normalMap).not.toBeNull();
    expect(material.aoMap).not.toBeNull();
    expect(material.useLighting).toBe(true);
    expect(castsShadow(set)).toBe(false);
    // Plain levels: a blended coverage averages as it should, so the device builds the chain.
    const colour = material.diffuseMap as pc.Texture & { _levels: Uint8Array[] };
    expect(colour._levels).toHaveLength(1);
    textures.destroy();
  });

  it('draws after opaque and cutout surfaces and before glazing among blended surfaces', () => {
    const buckets = Object.fromEntries((['opaque', 'cutout', 'decal', 'glazing'] as const).map((materialClass) => [materialClass, drawBucket({ materialClass })]));
    expect(buckets).toEqual({ opaque: null, cutout: null, decal: DECAL_DRAW_BUCKET, glazing: GLAZING_DRAW_BUCKET });
    // The engine's back-to-front pass draws a higher bucket first, whatever the distance.
    const key = (bucket: number, distance: number): number => bucket * 1e9 + distance;
    const sorted = [
      { name: 'glazing near', key: key(GLAZING_DRAW_BUCKET, 2) },
      { name: 'decal far', key: key(DECAL_DRAW_BUCKET, 90) },
      { name: 'decal near', key: key(DECAL_DRAW_BUCKET, 1) },
      { name: 'glazing far', key: key(GLAZING_DRAW_BUCKET, 80) },
    ].sort((a, b) => b.key - a.key).map((draw) => draw.name);
    expect(sorted).toEqual(['decal far', 'decal near', 'glazing far', 'glazing near']);
  });
});
