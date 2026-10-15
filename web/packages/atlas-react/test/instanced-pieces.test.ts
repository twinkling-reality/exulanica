// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { PIECE_DRAWING_DEFAULTS, readStylePackManifest, resolveStylePack, type LookFamily, type StylePackFile } from '@exulanica/atlas-core';
import { dressSlots, fetchPackPieces, growByPlaced, uploadPackPieces, type PieceSlot } from '../src/playcanvas/style-pack/index.js';

// Relative to web/, where the suite runs.
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8'));
const TABLE = JSON.parse(readFileSync('../assets/colour/srgb8-linear16.v1.json', 'utf8')).values as number[];
const families = new Map<string, LookFamily>(Object.entries(CASES.context.families as Record<string, { fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }>)
  .map(([key, value]) => [key, { fit: value.fit, dressing: value.dressing, fillMinimumPermille: value.fill_minimum_permille, fillMaximumPermille: value.fill_maximum_permille }]));
const context = { families, textureSets: new Set<string>(CASES.context.texture_sets) };
const SHADING = { model: 'pbr' as const, toon: null, ink: null };
/** The case pack's first swatch: a palette piece's quads are coloured in it. */
const SWATCH = [216, 105, 75];

/** A car-sized piece: a box 4.2 by 1.5 by 1.8 m about its base centre, an odd quad on its +x side so a mirror shows. */
const QUADS: readonly { points: number[][]; normal: number[] }[] = [
  { points: [[-2.1, 0, 0.9], [2.1, 0, 0.9], [2.1, 1.5, 0.9], [-2.1, 1.5, 0.9]], normal: [0, 0, 1] },
  { points: [[2.1, 0, -0.9], [-2.1, 0, -0.9], [-2.1, 1.5, -0.9], [2.1, 1.5, -0.9]], normal: [0, 0, -1] },
  { points: [[2.1, 0.2, 0.9], [2.1, 0.2, -0.3], [2.1, 1.1, -0.3], [2.1, 1.1, 0.9]], normal: [1, 0, 0] },
  { points: [[-2.1, 1.5, 0.9], [2.1, 1.5, 0.9], [2.1, 1.5, -0.9], [-2.1, 1.5, -0.9]], normal: [0, 1, 0] },
];

/** The GLB container around a document and its binary views. */
function container(document: Record<string, unknown>, parts: readonly Uint8Array[], views: readonly { byteOffset: number }[], length: number): Uint8Array<ArrayBuffer> {
  const binary = new Uint8Array(length);
  parts.forEach((part, k) => binary.set(part, views[k]!.byteOffset));
  const text = new TextEncoder().encode(JSON.stringify(document));
  const json = new Uint8Array(Math.ceil(text.byteLength / 4) * 4).fill(0x20);
  json.set(text);
  const bytes = new Uint8Array(28 + json.byteLength + binary.byteLength);
  const out = new DataView(bytes.buffer);
  out.setUint32(0, 0x46546c67, true);
  out.setUint32(4, 2, true);
  out.setUint32(8, bytes.byteLength, true);
  out.setUint32(12, json.byteLength, true);
  out.setUint32(16, 0x4e4f534a, true);
  bytes.set(json, 20);
  out.setUint32(20 + json.byteLength, binary.byteLength, true);
  out.setUint32(24 + json.byteLength, 0x004e4942, true);
  bytes.set(binary, 28 + json.byteLength);
  return bytes;
}

function views(arrays: readonly Uint8Array[]): { parts: Uint8Array[]; views: { buffer: number; byteOffset: number; byteLength: number }[]; length: number } {
  let length = 0;
  const out: { buffer: number; byteOffset: number; byteLength: number }[] = [];
  for (const array of arrays) {
    out.push({ buffer: 0, byteOffset: length, byteLength: array.byteLength });
    length += Math.ceil(array.byteLength / 4) * 4;
  }
  return { parts: [...arrays], views: out, length };
}

const geometry = (scale = 1) => ({
  positions: QUADS.flatMap((quad) => quad.points.flat().map((value) => value * scale)),
  normals: QUADS.flatMap((quad) => Array(4).fill(quad.normal).flat() as number[]),
  indices: QUADS.flatMap((_, q) => [0, 1, 2, 0, 2, 3].map((corner) => corner + q * 4)),
});

/** The piece as a palette piece, one swatch. */
function palettePiece(): Uint8Array<ArrayBuffer> {
  const { positions, normals, indices } = geometry();
  const colours = QUADS.flatMap(() => Array(4).fill([...SWATCH.map((byte) => TABLE[byte]!), 65535]).flat() as number[]);
  const laid = views([new Float32Array(positions), new Float32Array(normals), new Uint16Array(colours), new Uint16Array(indices)].map((a) => new Uint8Array(a.buffer)));
  const vertices = QUADS.length * 4;
  return container({
    asset: { version: '2.0' },
    accessors: [
      { bufferView: 0, componentType: 5126, count: vertices, type: 'VEC3' },
      { bufferView: 1, componentType: 5126, count: vertices, type: 'VEC3' },
      { bufferView: 2, componentType: 5123, count: vertices, type: 'VEC4', normalized: true },
      { bufferView: 3, componentType: 5123, count: indices.length, type: 'SCALAR' },
    ],
    bufferViews: laid.views,
    buffers: [{ byteLength: laid.length }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0, NORMAL: 1, COLOR_0: 2 }, indices: 3 }] }],
  }, laid.parts, laid.views, laid.length);
}

/** The same piece textured: one cut-out material, its picture a PNG header (the test's decoder ignores it). `shrink` makes a second level. */
function texturedPiece(shrink = 1): Uint8Array<ArrayBuffer> {
  const { positions, normals, indices } = geometry(shrink);
  const uvs = QUADS.flatMap(() => [0, 0, 0, 1, 1, 1, 1, 0]);
  const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, shrink === 1 ? 1 : 2]);
  const laid = views([new Float32Array(positions), new Float32Array(normals), new Float32Array(uvs), new Uint16Array(indices), png].map((a) => new Uint8Array(a.buffer)));
  const vertices = QUADS.length * 4;
  return container({
    asset: { version: '2.0' }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ mesh: 0 }],
    accessors: [
      { bufferView: 0, componentType: 5126, count: vertices, type: 'VEC3' },
      { bufferView: 1, componentType: 5126, count: vertices, type: 'VEC3' },
      { bufferView: 2, componentType: 5126, count: vertices, type: 'VEC2' },
      { bufferView: 3, componentType: 5123, count: indices.length, type: 'SCALAR' },
    ],
    bufferViews: laid.views,
    buffers: [{ byteLength: laid.length }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0, NORMAL: 1, TEXCOORD_0: 2 }, indices: 3, material: 0 }] }],
    images: [{ bufferView: 4, mimeType: 'image/png' }],
    textures: [{ source: 0 }],
    materials: [{ pbrMetallicRoughness: { baseColorTexture: { index: 0 }, metallicFactor: 0, roughnessFactor: 0.8 }, alphaMode: 'MASK', alphaCutoff: 0.5, doubleSided: true }],
  }, laid.parts, laid.views, laid.length);
}

/** The case pack with only `car-a` (and its far level) for its cars, the files given. */
function carPack(files: Readonly<Record<string, Uint8Array>>) {
  const manifest = structuredClone(CASES.cases.find((c: { name: string }) => c.name === 'a complete pack with no base').manifest);
  manifest.modules['vehicle.car'].variants = manifest.modules['vehicle.car'].variants.filter((variant: { file: string }) => variant.file === 'pieces/car-a.glb');
  manifest.files = manifest.files.filter((file: { path: string }) => file.path !== 'pieces/car-b.glb');
  // The same piece as a run a boundary tiles along its width, so copies are placed too.
  manifest.modules['boundary.default'] = { variants: [{ file: 'pieces/car-a.glb', lod1: 'pieces/car-a-far.glb', size_mm: [4200, 1800, 1500], stretch_mm: [null, null, null] }] };
  for (const file of manifest.files as { path: string; sha256: string; bytes: number }[]) {
    const bytes = files[file.path]!;
    file.sha256 = createHash('sha256').update(bytes).digest('hex');
    file.bytes = bytes.byteLength;
  }
  return resolveStylePack([readStylePackManifest(manifest, context)]);
}

function app(): pc.AppBase {
  const canvas = document.createElement('canvas');
  const one = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
  options.componentSystems = [pc.RenderComponentSystem];
  one.init(options);
  return one;
}

const decode = async () => ({ width: 4, height: 4, rgba: new Uint8Array(4 * 4 * 4) });

async function loaded(textured: boolean, host: pc.AppBase, far = 0.5) {
  const files: Record<string, Uint8Array<ArrayBuffer>> = {
    'pieces/car-a.glb': textured ? texturedPiece() : palettePiece(),
    'pieces/car-a-far.glb': textured ? texturedPiece(far) : palettePiece(),
    'pieces/window.glb': palettePiece(),
  };
  const pack = carPack(files);
  const fetched = await fetchPackPieces(pack, ['vehicle.car', 'boundary.default'], TABLE, async (file: StylePackFile) => files[file.path]!, decode);
  return { pack, pieces: uploadPackPieces(host.graphicsDevice, fetched, SHADING) };
}

/** Slots at several turns, sizes and heights; the last on a slope's height. */
const SLOTS: readonly PieceSlot[] = [
  { identity: 'a', lookRole: 'vehicle.car', positionMm: [0, 0, 0], front: [0, 1], boxMm: [4200, 1800, 1500] },
  { identity: 'b', lookRole: 'vehicle.car', positionMm: [12_000, -3000, 0], front: [-1, 0], boxMm: [2100, 1800, 1500] },
  { identity: 'c', lookRole: 'vehicle.car', positionMm: [-7000, 9000, 250], front: [0.6, 0.8], boxMm: [8400, 3600, 3000] },
  { identity: 'd', lookRole: 'vehicle.car', positionMm: [30_000, 40_000, 4375], front: [0, -1], boxMm: [4200, 900, 1500] },
  // Three copies along a 13 m run, each drawn out a little to share it, facing a diagonal: copies sit
  // symmetrically about the centre, so only a front with both parts tells a wrong turn of the shift.
  { identity: 'e', lookRole: 'boundary.default', positionMm: [-20_000, -15_000, 0], front: [0.8, -0.6], boxMm: [13_000, 1800, 1500] },
];

/** Every placed corner of the instanced pieces, from the instance buffers and the uploaded meshes. */
function instancedCorners(parent: pc.Entity): number[] {
  const out: number[] = [];
  for (const render of parent.findComponents('render') as pc.RenderComponent[]) {
    if (!render.entity.name.startsWith('style-pack:instanced:') || render.entity.name.endsWith(':pieces')) continue;
    const instance = render.meshInstances.find((one) => one.visible)!;
    const matrices = new Float32Array(instance.instancingData!.vertexBuffer!.lock());
    const positions: number[] = [];
    instance.mesh.getPositions(positions);
    const indices: number[] = [];
    instance.mesh.getIndices(indices);
    for (let at = 0; at < matrices.length; at += 16) {
      const m = matrices.subarray(at, at + 16);
      for (const v of indices) {
        const [x, y, z] = [positions[v * 3]!, positions[v * 3 + 1]!, positions[v * 3 + 2]!];
        for (let k = 0; k < 3; k += 1) out.push(m[k]! * x + m[4 + k]! * y + m[8 + k]! * z + m[12 + k]!);
      }
    }
  }
  return out;
}

/** Every baked corner of the palette pieces, in order. */
function bakedCorners(parent: pc.Entity): number[] {
  const render = (parent.findByName('style-pack:pieces') as pc.Entity).render!;
  const positions: number[] = [];
  render.meshInstances[0]!.mesh.getPositions(positions);
  return positions;
}

/** Corners as sorted triples, so two drawings' orders need not agree. */
const triples = (values: readonly number[]): string[] => {
  const out: string[] = [];
  for (let i = 0; i < values.length; i += 3) out.push(values.slice(i, i + 3).map((v) => (Math.round(v * 1e5) / 1e5).toFixed(5)).join(','));
  return out.sort();
};

describe('textured pieces drawn instanced', () => {
  it('stand exactly where the bake stands the same piece, at every turn, size and height', async () => {
    const host = app();
    const baked = await loaded(false, host);
    const bakedRoot = new pc.Entity('baked');
    const palette = dressSlots(bakedRoot, SLOTS, baked.pack, families, baked.pieces, SHADING);
    expect(palette.instanced).toBeNull();
    const instancedHost = await loaded(true, host);
    const instancedRoot = new pc.Entity('instanced');
    const textured = dressSlots(instancedRoot, SLOTS, instancedHost.pack, families, instancedHost.pieces, SHADING);
    expect(textured.placed).toBe(palette.placed);
    expect(textured.undressed).toEqual([]);
    // Four cars and three copies of the run.
    expect(textured.instanced!.instances).toBe(7);
    const a = triples(bakedCorners(bakedRoot));
    const b = triples(instancedCorners(instancedRoot));
    expect(b.length).toBe(a.length);
    // Rounded to 10 micrometres: the bake and the matrix agree well inside 1e-6 m on these numbers.
    expect(b).toEqual(a);
    palette.dispose();
    textured.dispose();
    baked.pieces.dispose();
    instancedHost.pieces.dispose();
  });

  it('puts placements in cells, each culled by bounds that hold all its pieces as placed, at both levels', async () => {
    const host = app();
    // A second level wider than the first: the cell's bounds must hold it too.
    const { pack, pieces } = await loaded(true, host, 1.5);
    const root = new pc.Entity('root');
    const dressing = dressSlots(root, SLOTS, pack, families, pieces, SHADING);
    // Cells of 128 m on renderer east and south: a and b share the cell at the origin; c (7 m west,
    // 9 m north), d (40 m north) and the run e (20 m west, 15 m south) each stand in another. Cars
    // and the run are drawn from one file, so they share cells by place alone.
    expect(dressing.instanced!.cells).toBe(4);
    const cells = (root.findComponents('render') as pc.RenderComponent[]).filter((render) => render.entity.name.startsWith('style-pack:instanced:') && !render.entity.name.endsWith(':pieces'));
    for (const render of cells) {
      for (const instance of render.meshInstances) {
        expect(instance.cull).toBe(true);
        const box = (instance as unknown as { _customAabb: pc.BoundingBox })._customAabb;
        const matrices = new Float32Array(instance.instancingData!.vertexBuffer!.lock());
        for (let at = 0; at < matrices.length; at += 16) {
          const placed = { min: [Infinity, Infinity, Infinity], max: [-Infinity, -Infinity, -Infinity] };
          growByPlaced(placed, [-2.1 * 1.5, 0, -0.9 * 1.5, 2.1 * 1.5, 1.5 * 1.5, 0.9 * 1.5], matrices.subarray(at, at + 16));
          for (let k = 0; k < 3; k += 1) {
            expect(placed.min[k]).toBeGreaterThanOrEqual([box.getMin().x, box.getMin().y, box.getMin().z][k]! - 1e-6);
            expect(placed.max[k]).toBeLessThanOrEqual([box.getMax().x, box.getMax().y, box.getMax().z][k]! + 1e-6);
          }
        }
      }
    }
    dressing.dispose();
    pieces.dispose();
  });

  it('chooses each cell\'s level by distance with hysteresis, casts from the first level within reach only, and allocates nothing as the camera moves', async () => {
    const host = app();
    const camera = new pc.Entity('camera');
    host.root.addChild(camera);
    const { pack, pieces } = await loaded(true, host);
    const root = new pc.Entity('root');
    host.root.addChild(root);
    const before = (host as unknown as { _callbacks: Map<string, unknown[]> })._callbacks.get('update')?.length ?? 0;
    const drawing = { ...PIECE_DRAWING_DEFAULTS, lod1BeyondPerMetre: 9, hysteresisPermille: 100, shadowReachM: 11, cellSizeM: 48 };
    // One car at the origin, 1.5 m tall: its second level from 13.5 m, its first again under 12.15 m.
    const dressing = dressSlots(root, [SLOTS[0]!], pack, families, pieces, SHADING, undefined, undefined, { app: host, camera, drawing });
    const instanced = dressing.instanced!;
    const cell = (root.findComponents('render') as pc.RenderComponent[]).find((render) => render.entity.name.startsWith('style-pack:instanced:') && !render.entity.name.endsWith(':pieces'))!;
    const [first, second] = [cell.meshInstances[0]!, cell.meshInstances[1]!];
    const at = (distance: number): readonly [number, number] => {
      // The box reaches 2.1 m east of the slot's centre for a car facing north; stand east of it.
      camera.setPosition(2.1 + distance, 0.5, 0);
      instanced.update();
      return instanced.drawsAtLevel;
    };
    const buffers = host.graphicsDevice.buffers.size;
    expect(at(10)).toEqual([1, 0]);
    expect([first.castShadow, second.castShadow]).toEqual([true, false]);
    expect(at(15)).toEqual([0, 1]);
    expect([first.visible, second.visible, first.castShadow, second.castShadow]).toEqual([false, true, false, false]);
    expect(at(13)).toEqual([0, 1]);
    expect(at(12)).toEqual([1, 0]);
    // Within its first level again, but past the shadow reach.
    expect(first.castShadow).toBe(false);
    for (let step = 0; step < 50; step += 1) at(5 + step);
    expect(host.graphicsDevice.buffers.size).toBe(buffers);
    // Its camera listener goes with the drawing: a look swap leaves none behind.
    const listeners = (): number => (host as unknown as { _callbacks: Map<string, unknown[]> })._callbacks.get('update')?.length ?? 0;
    expect(listeners()).toBe(before + 1);
    dressing.dispose();
    expect(listeners()).toBe(before);
    pieces.dispose();
  });

  it('gives back every buffer it made, and destroys a texture only when the pieces that hold it go', async () => {
    const host = app();
    const device = host.graphicsDevice;
    const before = device.buffers.size;
    const { pack, pieces } = await loaded(true, host);
    const root = new pc.Entity('root');
    const dressing = dressSlots(root, SLOTS, pack, families, pieces, SHADING);
    const textures = new Set((root.findComponents('render') as pc.RenderComponent[])
      .flatMap((render) => render.meshInstances.map((instance) => (instance.material as pc.StandardMaterial).diffuseMap))
      .filter((texture): texture is pc.Texture => texture !== null));
    // The two levels' pictures differ by a byte: two textures, both sRGB colour.
    expect(textures.size).toBe(2);
    expect([...textures].map((texture) => texture.format)).toEqual([pc.PIXELFORMAT_SRGBA8, pc.PIXELFORMAT_SRGBA8]);
    expect(pieces.decodedTextureBytes).toBe(2 * 4 * 4 * 4);
    // A second drawing of the same pieces, as a look swap attaches before the old goes.
    const again = dressSlots(new pc.Entity('again'), SLOTS, pack, families, pieces, SHADING);
    dressing.dispose();
    expect([...textures].every((texture) => texture.device !== null)).toBe(true);
    again.dispose();
    pieces.dispose();
    expect([...textures].every((texture) => texture.device === null)).toBe(true);
    expect(device.buffers.size).toBe(before);
  });

  it('hands a seat\'s contact the same triangles drawn instanced as baked', async () => {
    const host = app();
    const capture = async (textured: boolean): Promise<{ positions: readonly number[]; normals: readonly number[] }> => {
      const { pack, pieces } = await loaded(textured, host);
      let got: { positions: readonly number[]; normals: readonly number[] } | null = null;
      const dressing = dressSlots(new pc.Entity('root'), [SLOTS[2]!], pack, families, pieces, SHADING, {
        identities: new Set(['c']), maximumVertices: 100_000,
        triangles: (_identity, positions, normals) => { got = { positions, normals }; },
      });
      dressing.dispose();
      pieces.dispose();
      return got!;
    };
    const baked = await capture(false);
    const instanced = await capture(true);
    expect(instanced.positions.length).toBe(baked.positions.length);
    instanced.positions.forEach((value, k) => expect(Math.abs(value - baked.positions[k]!)).toBeLessThan(1e-6));
    instanced.normals.forEach((value, k) => expect(Math.abs(value - baked.normals[k]!)).toBeLessThan(1e-6));
  });

  it('leaves a slot whose textured piece would have to stretch to its primitive', async () => {
    const host = app();
    const files: Record<string, Uint8Array<ArrayBuffer>> = { 'pieces/car-a.glb': palettePiece(), 'pieces/car-a-far.glb': palettePiece(), 'pieces/window.glb': texturedPiece() };
    const pack = carPack(files);
    const fetched = await fetchPackPieces(pack, ['window.default'], TABLE, async (file) => files[file.path]!, decode);
    const pieces = uploadPackPieces(host.graphicsDevice, fetched, SHADING);
    const window: PieceSlot = { identity: 'w', lookRole: 'window.default', positionMm: [0, 0, 0], front: [0, 1], boxMm: [1200, 160, 1800] };
    const dressing = dressSlots(new pc.Entity('root'), [window], pack, families, pieces, SHADING);
    expect(dressing.undressed).toEqual(['w']);
    expect(dressing.instanced).toBeNull();
    dressing.dispose();
    pieces.dispose();
  });
});
