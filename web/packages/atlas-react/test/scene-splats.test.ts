import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { describe, expect, it, vi } from 'vitest';
import type * as pc from 'playcanvas';
import { createSceneSplatAsset, trainedSceneFootprint, validateSogBundle,
  validateTrainedSceneGeometry, type TrainedSceneGeometry } from '../src/playcanvas/scene-splats.js';

function fixture(): ArrayBuffer {
  const bytes = readFileSync(`${process.cwd()}/test-data/compressor-3.3.3-format-only.sog`);
  return Uint8Array.from(bytes).buffer;
}
function geometry(bytes = fixture()): TrainedSceneGeometry {
  return { sceneId: 'scene', islandId: 'island' as never, artifactId: 'artifact', bytes,
    pointCount: 512, bounds: { min: [-1, -2, -3], max: [1, 2, 3] },
    sceneFromAssetRowMajor: [2, 0, 0, 10, 0, 2, 0, 0, 0, 0, 2, 5, 0, 0, 0, 1] };
}

describe('native authenticated trained scene boundary', () => {
  it('accepts exact pinned compressor output with streamed STORE descriptors', () => {
    const bytes = fixture();
    expect(createHash('sha256').update(new Uint8Array(bytes)).digest('hex'))
      .toBe('cc165ad93f290bbce4492f54d469fdb9daf436cab8b671ec8ae15e87961b7ade');
    expect(validateSogBundle(bytes)).toEqual({ pointCount: 512 });
    expect(trainedSceneFootprint(geometry())).toBeCloseTo(Math.hypot(12, 11));
  });

  it('rejects missing textures before native parsing can make unauthenticated subrequests', () => {
    const bytes = fixture();
    const data = new Uint8Array(bytes);
    // Match the quoted metadata reference, not either ZIP filename header.
    const needle = new TextEncoder().encode('"means_l.webp"');
    const metadataOffset = data.findIndex((_, start) => needle.every((byte, i) => data[start + i] === byte));
    expect(metadataOffset).toBeGreaterThan(-1);
    data[metadataOffset + 1] = 'x'.charCodeAt(0);
    expect(() => validateSogBundle(bytes)).toThrow(/missing or external texture/);
  });

  it('refuses truncated archives, bad descriptors, and non-affine transforms', () => {
    expect(() => validateSogBundle(fixture().slice(0, -1))).toThrow();
    const bytes = fixture();
    const data = new DataView(bytes);
    const array = new Uint8Array(bytes);
    const at = array.findIndex((_, i) => i + 4 <= array.length && data.getUint32(i, true) === 0x08074b50);
    data.setUint32(at + 8, 1, true);
    expect(() => validateSogBundle(bytes)).toThrow(/descriptor/);
    expect(() => validateTrainedSceneGeometry({ ...geometry(),
      sceneFromAssetRowMajor: new Array(16).fill(0) })).toThrow(/affine/);
  });

  it('supplies verified bytes in memory to the native gsplat loader and keeps them owned until disposal', async () => {
    const value = geometry();
    const assets = { add: vi.fn(), remove: vi.fn(), load: vi.fn((asset: pc.Asset) => {
      expect(asset.type).toBe('gsplat');
      const file = asset.file as { contents: ArrayBuffer; url: string };
      expect(file.contents).toBe(value.bytes);
      expect(file.url).toBe('verified-scene/artifact.sog');
      asset.resource = { destroy: vi.fn() };
      asset.fire('load', asset);
    }) };
    const asset = await createSceneSplatAsset({ assets } as unknown as pc.AppBase, value);
    expect(assets.add).toHaveBeenCalledWith(asset);
    expect(assets.remove).not.toHaveBeenCalled();
  });

  it('removes failed native resources and never invokes the loader for an invalid bundle', async () => {
    const assets = { add: vi.fn(), remove: vi.fn(), load: vi.fn((asset: pc.Asset) => {
      asset.fire('error', new Error('texture decode failed'));
    }) };
    const app = { assets } as unknown as pc.AppBase;
    await expect(createSceneSplatAsset(app, geometry())).rejects.toThrow('texture decode failed');
    expect(assets.remove).toHaveBeenCalledOnce();
    assets.load.mockClear();
    await expect(createSceneSplatAsset(app, geometry(new ArrayBuffer(0)))).rejects.toThrow();
    expect(assets.load).not.toHaveBeenCalled();
  });
});
