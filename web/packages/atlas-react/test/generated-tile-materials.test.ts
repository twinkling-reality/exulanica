// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { parseTextureSetManifest, textureSetBlobPath, type TextureSetDigest } from '@exulanica/atlas-core';
import { TILE_LOOK_V1 } from '../src/playcanvas/generated-tile/look.js';
import {
  TileTextureLibrary,
  normalTexels,
  prepareTextureSet,
  setTangents,
  surfaceUv,
  unavailableUv,
} from '../src/playcanvas/generated-tile/texture-materials.js';
import { unavailablePatternTexels } from '../src/playcanvas/generated-tile/unavailable-surface.js';
import { buildSurfaceMesh, validateSurfaceBatch } from '../src/playcanvas/generated-tile/surface-mesh.js';

// Relative to web/, where the suite runs: under happy-dom, import.meta.url is not a file URL.
const TEXTURES = '../assets/textures/';
const manifest = parseTextureSetManifest(new Uint8Array(readFileSync(`${TEXTURES}manifest.json`)));
const subtle = webcrypto.subtle as unknown as TextureSetDigest;
const KERB = manifest.byId.get('cc0.kerb-stone')!;
const unit = { textureSetId: KERB.setId, repeatSizeMillionths: 1_000_000, rotationUrad: 0, offsetUMm: 0, offsetVMm: 0 };

function device(): pc.GraphicsDevice {
  return new pc.NullGraphicsDevice(document.createElement('canvas'));
}

function library(fetchSet: (setId: string) => Uint8Array, look = TILE_LOOK_V1) {
  const fetched: string[] = [];
  const value = new TileTextureLibrary(device(), look, manifest, async (entry) => {
    fetched.push(entry.setId);
    return fetchSet(entry.setId);
  }, subtle);
  return { library: value, fetched };
}

const committed = (setId: string): Uint8Array =>
  new Uint8Array(readFileSync(`${TEXTURES}${textureSetBlobPath(manifest.byId.get(setId)!)}`));

describe('generated tile UV rule', () => {
  it('repeats a set once per physical extent, from the extent and nothing else', () => {
    // The kerb set is 1800 by 450 mm: a 9 m run repeats five times along u.
    expect(surfaceUv(9000, 0, unit, KERB)).toEqual([5, 0]);
    expect(surfaceUv(0, 900, unit, KERB)).toEqual([0, 2]);
    const brick = manifest.byId.get('cc0.brick-running-bond')!;
    const [u] = surfaceUv(6000, 0, { ...unit, textureSetId: brick.setId }, brick);
    expect(u).toBeCloseTo(6000 / brick.extentUMm, 12);
  });

  it('applies the record size to the repeat length, so a larger size repeats less often', () => {
    // 2,000,000: one repeat covers 3600 by 900 mm, so a 9 m run repeats two and a half times.
    const doubled = surfaceUv(9000, 450, { ...unit, repeatSizeMillionths: 2_000_000 }, KERB);
    expect(doubled[0]).toBeCloseTo(2.5, 12);
    expect(doubled[1]).toBeCloseTo(0.5, 12);
    const halved = surfaceUv(9000, 450, { ...unit, repeatSizeMillionths: 500_000 }, KERB);
    expect(halved[0]).toBeCloseTo(10, 12);
    expect(halved[1]).toBeCloseTo(2, 12);
  });

  it('rotates by the city vocabulary\'s formula, in millimetres, keeping the set\'s proportions', () => {
    // u = cos*s - sin*t, v = sin*s + cos*t: a quarter turn carries +s onto +t.
    const quarter = { ...unit, rotationUrad: 1_570_796 };
    const fromT = surfaceUv(0, 1800, quarter, KERB);
    expect(fromT[0]).toBeCloseTo(-1, 5);
    expect(fromT[1]).toBeCloseTo(0, 5);
    // 450 mm along s lands on v, where one repeat of the 1800 by 450 mm set is 450 mm.
    const fromS = surfaceUv(450, 0, quarter, KERB);
    expect(fromS[0]).toBeCloseTo(0, 5);
    expect(fromS[1]).toBeCloseTo(1, 5);
  });

  it('shifts by the offsets along the texture\'s own axes, after the rotation', () => {
    const shifted = surfaceUv(0, 0, { ...unit, offsetUMm: 900, offsetVMm: 225 }, KERB);
    expect(shifted).toEqual([0.5, 0.5]);
    const turnedAndShifted = surfaceUv(0, 1800, { ...unit, rotationUrad: 1_570_796, offsetUMm: 900, offsetVMm: 0 }, KERB);
    expect(turnedAndShifted[0]).toBeCloseTo(-0.5, 5);
    const sized = surfaceUv(0, 0, { ...unit, repeatSizeMillionths: 2_000_000, offsetUMm: 900, offsetVMm: 0 }, KERB);
    expect(sized[0]).toBeCloseTo(0.25, 12);
  });

  it('lays the unavailable pattern at the look\'s own physical size, upright on walls and ground', () => {
    const size = TILE_LOOK_V1.unavailable.tileMm;
    expect(unavailableUv(size * 3, size, TILE_LOOK_V1)).toEqual([3, 1]);
    expect(unavailableUv(size * 3, size, TILE_LOOK_V1, 'vertical')).toEqual([3, 1]);
    // On the ground, t runs away from a viewer facing along it, and the image's top goes that way.
    expect(unavailableUv(size * 3, size, TILE_LOOK_V1, 'horizontal')).toEqual([3, -1]);
  });

  it('flips PlayCanvas tangent handedness once, so +Y of a normal map points toward row 0', () => {
    const positions = [0, 0, 0, 1, 0, 0, 1, 1, 0];
    const normals = [0, 0, 1, 0, 0, 1, 0, 0, 1];
    // v grows downward, as a wall's surface coordinate does.
    const uvs = [0, 1, 1, 1, 1, 0];
    const indices = [0, 1, 2];
    const engine = pc.calculateTangents(positions, normals, uvs, indices);
    const ours = setTangents(positions, normals, uvs, indices);
    for (let at = 0; at < engine.length; at += 4) {
      expect(ours.slice(at, at + 3)).toEqual(engine.slice(at, at + 3));
      expect(ours[at + 3]).toBe(-engine[at + 3]!);
    }
  });
});

describe('generated tile materials from texture sets', () => {
  it('binds base colour, normal and the three orm channels, and leaves the height map unused', async () => {
    const { library: lib } = library(committed);
    const resolved = await lib.resolve(KERB.setId);
    expect(resolved.state).toBe('available');
    const material = resolved.material;
    expect(material.diffuseMap?.format).toBe(pc.PIXELFORMAT_SRGBA8);
    expect(material.normalMap?.format).toBe(pc.PIXELFORMAT_RGBA8);
    expect(material.bumpiness).toBe(TILE_LOOK_V1.surface.normalStrength);
    expect(material.aoMap).toBe(material.glossMap);
    expect(material.metalnessMap).toBe(material.aoMap);
    expect([material.aoMapChannel, material.glossMapChannel, material.metalnessMapChannel]).toEqual(['r', 'g', 'b']);
    expect(material.glossInvert).toBe(true);
    expect(material.useMetalness).toBe(true);
    expect(material.heightMap).toBeNull();
    expect(material.diffuseMap?.addressU).toBe(pc.ADDRESS_REPEAT);
    expect(material.diffuseMap?.mipmaps).toBe(true);
    // 1024 by 256, RGBA, three maps with mip chains.
    let chain = 0;
    for (let w = 1024, h = 256; ; w = Math.max(1, w >> 1), h = Math.max(1, h >> 1)) {
      chain += w * h * 4;
      if (w === 1 && h === 1) break;
    }
    expect(lib.decodedTextureBytes).toBe(3 * chain);
    lib.destroy();
  });

  it('uploads each set once however many surfaces name it', async () => {
    const { library: lib, fetched } = library(committed);
    const [a, b] = await Promise.all([lib.resolve(KERB.setId), lib.resolve(KERB.setId)]);
    expect(a.material).toBe(b.material);
    expect(fetched).toEqual([KERB.setId]);
    lib.destroy();
  });

  it('draws the stated unavailable surface for an unpinned id, bad bytes, or a failed fetch', async () => {
    const { library: lib } = library((setId) => {
      if (setId === 'cc0.brick-running-bond') throw new Error('network down');
      const bytes = new Uint8Array(committed(setId));
      bytes[bytes.length - 1] = bytes[bytes.length - 1]! ^ 1;
      return bytes;
    });
    const unpinned = await lib.resolve('cc0.invented-marble');
    const tampered = await lib.resolve(KERB.setId);
    const failed = await lib.resolve('cc0.brick-running-bond');
    for (const resolution of [unpinned, tampered, failed]) {
      expect(resolution.state).toBe('unavailable');
      expect(resolution.material).toBe(lib.unavailableMaterial);
    }
    expect(unpinned.state === 'unavailable' && unpinned.reason).toMatch(/not pinned/);
    expect(tampered.state === 'unavailable' && tampered.reason).toMatch(/refused: .* hashes to/);
    expect(failed.state === 'unavailable' && failed.reason).toMatch(/could not be read: network down/);
    expect(lib.decodedTextureBytes).toBe(0);
    const pattern = lib.unavailableMaterial;
    expect(pattern.useLighting).toBe(false);
    expect(pattern.diffuseMap).toBeNull();
    expect(pattern.emissiveMap).not.toBeNull();
    lib.destroy();
  });

  it('refuses every set on a page without crypto.subtle', async () => {
    const lib = new TileTextureLibrary(device(), TILE_LOOK_V1, manifest, async () => committed(KERB.setId), null);
    const resolved = await lib.resolve(KERB.setId);
    expect(resolved.state).toBe('unavailable');
    expect(resolved.state === 'unavailable' && resolved.reason).toMatch(/no crypto\.subtle/);
    lib.destroy();
  });

  it('uploads the height map only when the look turns parallax on', async () => {
    const look = { ...TILE_LOOK_V1, surface: { ...TILE_LOOK_V1.surface, parallax: true, parallaxFactor: 0.01 } };
    const { library: lib } = library(committed, look);
    const resolved = await lib.resolve(KERB.setId);
    expect(resolved.material.heightMap?.format).toBe(pc.PIXELFORMAT_R8);
    expect(resolved.material.heightMapFactor).toBe(0.01);
    lib.destroy();
  });
});

describe('drawing a set by its material class', () => {
  // The texture lane's shared v2 fixtures, one container per class, read by path.
  const CONFORMANCE = 'packages/loom-texture/test/conformance/';
  const fixtures = parseTextureSetManifest(new Uint8Array(readFileSync(`${CONFORMANCE}manifest.json`)));
  const fixtureLibrary = () => new TileTextureLibrary(device(), TILE_LOOK_V1, fixtures, async (entry) =>
    new Uint8Array(readFileSync(`${CONFORMANCE}${entry.setId}.ltex`)), subtle);

  it('draws opaque, cutout and glazing sets, and decal as the stated unavailable surface', async () => {
    const textures = fixtureLibrary();
    const drawn: Record<string, string> = {};
    for (const entry of fixtures.sets) {
      const resolution = await textures.resolve(entry.setId);
      drawn[entry.setId] = resolution.state === 'available' ? 'available' : resolution.reason;
      if (resolution.state === 'unavailable') expect(resolution.material).toBe(textures.unavailableMaterial);
    }
    expect(drawn).toEqual({
      'fixture.cutout': 'available',
      'fixture.decal': 'material class decal is not drawn by this runtime',
      'fixture.glazing': 'available',
      'fixture.legacy-opaque': 'available',
      'fixture.model-opaque': 'available',
      'fixture.opaque': 'available',
    });
    // Nothing of a class it does not draw is uploaded.
    expect(textures.resolvedSetIds).toEqual(['fixture.cutout', 'fixture.glazing', 'fixture.legacy-opaque', 'fixture.model-opaque', 'fixture.opaque']);
    textures.destroy();
  });

  it('binds a two-component normal with its z rebuilt, and a three-component normal as stored', async () => {
    const textures = fixtureLibrary();
    const procedural = await textures.resolve('fixture.opaque');
    const model = await textures.resolve('fixture.model-opaque');
    if (procedural.state !== 'available' || model.state !== 'available') throw new Error('both opaque fixtures draw');
    expect(procedural.material.normalMap).not.toBeNull();
    expect(procedural.material.heightMap).toBeNull();
    const stored = procedural.set.maps.normal!;
    const rebuilt = normalTexels(procedural.set)!;
    expect(rebuilt.length).toBe((stored.length / 2) * 4);
    for (let texel = 0; texel < stored.length / 2; texel += 1) {
      const x = (2 * stored[texel * 2]!) / 255 - 1;
      const y = (2 * stored[texel * 2 + 1]!) / 255 - 1;
      const z = Math.sqrt(Math.max(0, 1 - x * x - y * y));
      expect([...rebuilt.subarray(texel * 4, texel * 4 + 4)])
        .toEqual([stored[texel * 2], stored[texel * 2 + 1], Math.round(((z + 1) / 2) * 255), 255]);
    }
    const three = model.set.maps.normal!;
    const widened = normalTexels(model.set)!;
    expect([...widened.subarray(0, 8)]).toEqual([three[0], three[1], three[2], 255, three[3], three[4], three[5], 255]);
    textures.destroy();
  });

  it('prepares and verifies a set of any class; drawing it is the binding\'s decision', async () => {
    const glazing = await prepareTextureSet(fixtures, 'fixture.glazing', async (entry) =>
      new Uint8Array(readFileSync(`${CONFORMANCE}${entry.setId}.ltex`)), subtle);
    expect(glazing.state === 'decoded' && glazing.set.classParameters).toMatchObject({ materialClass: 'glazing', iorMillionths: 1_500_000, doubleSided: false });
    expect(glazing.state === 'decoded' && glazing.set.classParameters.materialClass === 'glazing' && glazing.set.classParameters.filmSrgb).toHaveLength(3);
  });
});

describe('the unavailable pattern', () => {
  const texels = unavailablePatternTexels(TILE_LOOK_V1);
  const colours = new Map<string, number>();
  for (let at = 0; at < texels.length; at += 4) {
    const key = `${texels[at]},${texels[at + 1]},${texels[at + 2]},${texels[at + 3]}`;
    colours.set(key, (colours.get(key) ?? 0) + 1);
  }

  it('is two tones, neither of which covers the surface alone', () => {
    const byte = (value: number): number => Math.round(value * 255);
    const ink = `${TILE_LOOK_V1.unavailable.ink.map(byte).join(',')},255`;
    const ground = `${TILE_LOOK_V1.unavailable.ground.map(byte).join(',')},255`;
    expect([...colours.keys()].sort()).toEqual([ink, ground].sort());
    const total = texels.length / 4;
    expect(colours.get(ink)! / total).toBeGreaterThan(0.25);
    expect(colours.get(ground)! / total).toBeGreaterThan(0.25);
  });

  it('writes the word into the band across its middle', () => {
    const size = Math.sqrt(texels.length / 4);
    const row = (y: number): string => {
      let out = '';
      for (let x = 0; x < size; x += 1) out += texels[(y * size + x) * 4] === texels[0] ? '#' : '.';
      return out;
    };
    // The band above the letters is plain ground; the letters' first row is not.
    expect(row(54)).not.toContain('#');
    expect(row(57)).toContain('#');
    expect(row(57).replace(/\./g, '').length).toBeGreaterThan(20);
  });
});

describe('surface batches', () => {
  const batch = {
    positions: [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0],
    normals: [0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1],
    surfaceMm: [0, 0, 1000, 0, 1000, -1000, 0, -1000],
    indices: [0, 1, 2, 0, 2, 3],
  };

  it('builds exactly the triangles it is given, with UVs and tangents', () => {
    const mesh = buildSurfaceMesh(device(), batch, (s, t) => surfaceUv(s, t, unit, KERB));
    expect(mesh.vertexBuffer?.numVertices).toBe(4);
    expect(mesh.indexBuffer[0]?.numIndices).toBe(6);
    const uvs: number[] = [];
    mesh.getUvs(0, uvs);
    expect(uvs.map((value) => Math.round(value * 1e6) / 1e6)).toEqual([0, 0, 1000 / 1800, 0, 1000 / 1800, -1000 / 450, 0, -1000 / 450].map((value) => Math.round(value * 1e6) / 1e6));
    expect(mesh.vertexBuffer?.format.elements.some((element) => element.name === pc.SEMANTIC_TANGENT)).toBe(true);
    mesh.destroy();
  });

  it('refuses a batch it would have to repair', () => {
    expect(() => validateSurfaceBatch({ ...batch, positions: batch.positions.slice(0, 11) })).toThrow(/whole vertices/);
    expect(() => validateSurfaceBatch({ ...batch, normals: batch.normals.slice(3) })).toThrow(/one normal/);
    expect(() => validateSurfaceBatch({ ...batch, surfaceMm: batch.surfaceMm.slice(2) })).toThrow(/surface coordinate/);
    expect(() => validateSurfaceBatch({ ...batch, indices: [0, 1] })).toThrow(/whole triangles/);
    expect(() => validateSurfaceBatch({ ...batch, indices: [0, 1, 4] })).toThrow(/out of range/);
    expect(() => validateSurfaceBatch({ ...batch, positions: [...batch.positions.slice(0, 11), Number.NaN] })).toThrow(/not finite/);
    expect(() => validateSurfaceBatch({ ...batch, indices: [] })).toThrow(/whole triangles/);
  });
});
