import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { crc32 } from 'node:zlib';
import { describe, expect, it, vi } from 'vitest';
import type * as pc from 'playcanvas';
import { createSceneSplatAsset, storedSogBundle, trainedSceneFootprint, validateSogBundle,
  validateTrainedSceneGeometry, withoutViewBands, type TrainedSceneGeometry } from '../src/playcanvas/scene-splats.js';

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

/** An archive's members as its central directory names them: body and stated checksum, read as the engine reads. */
function members(bytes: ArrayBuffer): Map<string, { body: Uint8Array; crc: number }> {
  const data = new DataView(bytes);
  const end = bytes.byteLength - 22;
  const found = new Map<string, { body: Uint8Array; crc: number }>();
  let at = data.getUint32(end + 16, true);
  for (let index = 0; index < data.getUint16(end + 10, true); index += 1) {
    const nameLength = data.getUint16(at + 28, true);
    const local = data.getUint32(at + 42, true);
    const body = local + 30 + data.getUint16(local + 26, true) + data.getUint16(local + 28, true);
    const name = new TextDecoder().decode(new Uint8Array(bytes, at + 46, nameLength));
    found.set(name, { body: new Uint8Array(bytes, body, data.getUint32(at + 20, true)), crc: data.getUint32(at + 16, true) });
    at += 46 + nameLength + data.getUint16(at + 30, true) + data.getUint16(at + 32, true);
  }
  return found;
}

/** The fixture with view-dependent bands added: two textures and their `shN` section, as a trainer's SOG carries. */
function banded(): ArrayBuffer {
  const plain = members(fixture());
  const meta = JSON.parse(new TextDecoder().decode(plain.get('meta.json')!.body)) as Record<string, unknown>;
  meta['shN'] = { mins: -1, maxs: 1, files: ['shN_centroids.webp', 'shN_labels.webp'] };
  const map = new Map<string, Uint8Array>();
  for (const [name, { body }] of plain) map.set(name, name === 'meta.json' ? new TextEncoder().encode(JSON.stringify(meta)) : body);
  map.set('shN_centroids.webp', new Uint8Array([82, 73, 70, 70, 1, 2, 3]));
  map.set('shN_labels.webp', new Uint8Array([82, 73, 70, 70, 4, 5, 6]));
  return storedSogBundle(map);
}

describe('a SOG at its base colour', () => {
  it('leaves out the view-dependent bands and keeps every other member byte for byte', () => {
    const input = banded();
    expect(validateSogBundle(input)).toEqual({ pointCount: 512 });
    expect([...members(input).keys()]).toContain('shN_labels.webp');
    const output = withoutViewBands(input);
    expect(validateSogBundle(output)).toEqual({ pointCount: 512 });
    const before = members(fixture());
    const after = members(output);
    expect([...after.keys()]).toEqual([...before.keys()]);
    for (const [name, { body, crc }] of after) {
      expect(crc, name).toBe(crc32(body));
      if (name !== 'meta.json') expect(Buffer.from(body).equals(Buffer.from(before.get(name)!.body)), name).toBe(true);
    }
    const decode = (bytes: Uint8Array): unknown => JSON.parse(new TextDecoder().decode(bytes));
    expect(decode(after.get('meta.json')!.body)).toEqual(decode(before.get('meta.json')!.body));
  });

  it('hands on a bundle that carries no bands as it is', () => {
    const bytes = fixture();
    expect(withoutViewBands(bytes)).toBe(bytes);
  });

  it('is what the native loader is given when asked for the base colour, and the stored bytes otherwise', async () => {
    const value = geometry(banded());
    const given: ArrayBuffer[] = [];
    const assets = { add: vi.fn(), remove: vi.fn(), load: vi.fn((asset: pc.Asset) => {
      given.push((asset.file as { contents: ArrayBuffer }).contents);
      asset.resource = { destroy: vi.fn() };
      asset.fire('load', asset);
    }) };
    await createSceneSplatAsset({ assets } as unknown as pc.AppBase, value, 'base');
    await createSceneSplatAsset({ assets } as unknown as pc.AppBase, value);
    expect([...members(given[0]!).keys()].some((name) => name.startsWith('shN'))).toBe(false);
    expect(given[1]).toBe(value.bytes);
  });
});
