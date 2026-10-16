// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { PIECE_DRAWING_DEFAULTS, readStylePackManifest, resolveStylePack, type LookFamily, type StylePackFile } from '@exulanica/atlas-core';
import { dressSlots, fetchPackPieces, uploadPackPieces, type PieceSlot } from '../src/playcanvas/style-pack/index.js';

/**
 * A piece that repeats its bays and storeys (`repeat_mm`) is baked copy by copy: what lies below a
 * zone stays, each triangle of the zone is drawn once a copy, and what lies above follows the last
 * copy, so the piece meets its box exactly. A slot whose copies would bake more triangles than the
 * drawing's figure, or a textured piece asked to repeat, keeps its primitive.
 */

// Relative to web/, where the suite runs.
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8'));
const TABLE = JSON.parse(readFileSync('../assets/colour/srgb8-linear16.v1.json', 'utf8')).values as number[];
const families = new Map<string, LookFamily>(Object.entries(CASES.context.families as Record<string, { fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }>)
  .map(([key, value]) => [key, { fit: value.fit, dressing: value.dressing, fillMinimumPermille: value.fill_minimum_permille, fillMaximumPermille: value.fill_maximum_permille }]));
const context = { families, textureSets: new Set<string>(CASES.context.texture_sets) };
const SHADING = { model: 'pbr' as const, toon: null, ink: null };
/** The case pack's first swatch: the piece is coloured in it. */
const SWATCH = [216, 105, 75];

/**
 * A 5 m wide, 0.1 m deep, 2 m tall front: 600 mm ends about a 3.8 m bay (x from -1.9 to 1.9), a
 * 500 mm base and top about a 1 m storey (y from 0.5 to 1.5), its face cut at every zone edge; a
 * top along its crown; a marker in the bay and the storey, standing 10 mm proud of the face; and a
 * small face in the bay and the storey sloping 45 degrees across the width, whose normal a copy's
 * scale turns.
 */
const XS = [-2.5, -1.9, 1.9, 2.5];
const YS = [0, 0.5, 1.5, 2];
const QUADS: { points: number[][]; normal: number[] }[] = [];
for (let i = 0; i < 3; i += 1) {
  for (let j = 0; j < 3; j += 1) {
    const [x0, x1, y0, y1] = [XS[i]!, XS[i + 1]!, YS[j]!, YS[j + 1]!];
    QUADS.push({ points: [[x0, y0, 0.05], [x1, y0, 0.05], [x1, y1, 0.05], [x0, y1, 0.05]], normal: [0, 0, 1] });
  }
  const [x0, x1] = [XS[i]!, XS[i + 1]!];
  QUADS.push({ points: [[x0, 2, 0.05], [x1, 2, 0.05], [x1, 2, -0.05], [x0, 2, -0.05]], normal: [0, 1, 0] });
}
const MARKER_Z = 0.06;
QUADS.push({ points: [[-0.5, 0.7, MARKER_Z], [0.5, 0.7, MARKER_Z], [0.5, 1.3, MARKER_Z], [-0.5, 1.3, MARKER_Z]], normal: [0, 0, 1] });
const SLOPE: readonly [number, number] = [0.08, 0.1];
QUADS.push({ points: [[-1.2, 0.6, 0.1], [-1.0, 0.6, 0.08], [-1.0, 0.65, 0.08], [-1.2, 0.65, 0.1]], normal: [Math.SQRT1_2, 0, Math.SQRT1_2] });

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

const geometry = () => ({
  positions: QUADS.flatMap((quad) => quad.points.flat()),
  normals: QUADS.flatMap((quad) => Array(4).fill(quad.normal).flat() as number[]),
  indices: QUADS.flatMap((_, q) => [0, 1, 2, 0, 2, 3].map((corner) => corner + q * 4)),
});

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

function texturedPiece(): Uint8Array<ArrayBuffer> {
  const { positions, normals, indices } = geometry();
  const uvs = QUADS.flatMap(() => [0, 0, 0, 1, 1, 1, 1, 0]);
  const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1]);
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
    materials: [{ pbrMetallicRoughness: { baseColorTexture: { index: 0 }, metallicFactor: 0, roughnessFactor: 0.8 }, alphaMode: 'OPAQUE' }],
  }, laid.parts, laid.views, laid.length);
}

/** The case pack whose window is the front above, repeating its bay across and its storey up. */
async function loaded(host: pc.AppBase, textured = false) {
  const files: Record<string, Uint8Array<ArrayBuffer>> = {
    'pieces/car-a.glb': palettePiece(),
    'pieces/car-a-far.glb': palettePiece(),
    'pieces/car-b.glb': palettePiece(),
    'pieces/window.glb': textured ? texturedPiece() : palettePiece(),
  };
  const manifest = structuredClone(CASES.cases.find((c: { name: string }) => c.name === 'a complete pack with no base').manifest);
  manifest.modules['window.default'].variants = [{
    file: 'pieces/window.glb', lod1: null, size_mm: [5000, 100, 2000],
    stretch_mm: [null, null, null], repeat_mm: [[600, 4400], null, [500, 1500]],
  }];
  for (const file of manifest.files as { path: string; sha256: string; bytes: number }[]) {
    const bytes = files[file.path]!;
    file.sha256 = createHash('sha256').update(bytes).digest('hex');
    file.bytes = bytes.byteLength;
  }
  const pack = resolveStylePack([readStylePackManifest(manifest, context)]);
  const decode = async () => ({ width: 4, height: 4, rgba: new Uint8Array(4 * 4 * 4) });
  const fetched = await fetchPackPieces(pack, ['window.default'], TABLE, async (file: StylePackFile) => files[file.path]!, decode);
  return { pack, pieces: uploadPackPieces(host.graphicsDevice, fetched, SHADING) };
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

/** A slot at the origin facing north, so renderer east is the piece's -x and renderer south its -z. */
const slot = (boxMm: readonly [number, number, number], identity = 'w'): PieceSlot =>
  ({ identity, lookRole: 'window.sash', positionMm: [0, 0, 0], front: [0, 1], boxMm });

/** Every baked corner, (east, up, south) triples. */
function corners(parent: pc.Entity): number[][] {
  const render = (parent.findByName('style-pack:pieces') as pc.Entity).render!;
  const positions: number[] = [];
  render.meshInstances[0]!.mesh.getPositions(positions);
  const out: number[][] = [];
  for (let i = 0; i < positions.length; i += 3) out.push([positions[i]!, positions[i + 1]!, positions[i + 2]!]);
  return out;
}

/**
 * The centres of the markers' baked quads, (east, up), sorted: a marker stands 10 mm proud of the
 * face. Each of a quad's two triangles has its diagonal for its longest edge, whose middle is the
 * quad's centre, so the two name one centre.
 */
function markers(parent: pc.Entity): string[] {
  const all = corners(parent);
  const centres = new Set<string>();
  for (let i = 0; i < all.length; i += 3) {
    const triangle = [all[i]!, all[i + 1]!, all[i + 2]!];
    if (!triangle.every(([, , south]) => Math.abs(south! + MARKER_Z) < 1e-4)) continue;
    const edges = [[0, 1], [1, 2], [2, 0]].map(([a, b]) => [triangle[a!]!, triangle[b!]!] as const);
    const [a, b] = edges.reduce((longest, edge) => (Math.hypot(edge[0][0]! - edge[1][0]!, edge[0][1]! - edge[1][1]!) > Math.hypot(longest[0][0]! - longest[1][0]!, longest[0][1]! - longest[1][1]!) ? edge : longest));
    centres.add(`${((a[0]! + b[0]!) / 2).toFixed(3)},${((a[1]! + b[1]!) / 2).toFixed(3)}`);
  }
  return [...centres].sort();
}

describe('a piece that repeats its bays and storeys', () => {
  it('draws whole copies of its bay to meet a long box exactly, its ends kept', async () => {
    const host = app();
    const { pack, pieces } = await loaded(host);
    const root = new pc.Entity('root');
    // 20 m wide, 2 m tall: the storey needs no copy beyond its one; the bay five, at 18.8 / 19.
    const dressing = dressSlots(root, [slot([20_000, 100, 2000])], pack, families, pieces, SHADING);
    expect(dressing.undressed).toEqual([]);
    // 28 triangles authored: 12 in the bay drawn five times, 16 drawn once.
    expect(dressing.triangles).toBe(16 + 12 * 5);
    const all = corners(root);
    expect(Math.min(...all.map(([east]) => east!))).toBeCloseTo(-10, 5);
    expect(Math.max(...all.map(([east]) => east!))).toBeCloseTo(10, 5);
    expect(Math.max(...all.map(([, up]) => up!))).toBeCloseTo(2, 5);
    const scale = 18_800 / 19_000;
    // The marker's centre is 2.5 m from the low face: 1.9 m into the bay, in each copy k.
    const expected = [0, 1, 2, 3, 4].map((k) => `${(-(-10 + 0.6 + (k * 3.8 + 1.9) * scale)).toFixed(3)},1.000`).sort();
    expect(markers(root)).toEqual(expected);
    // The sloping face's normal turns by the copy's draw-out: drawn narrower across, it leans more.
    const render = (root.findByName('style-pack:pieces') as pc.Entity).render!;
    const normals: number[] = [];
    render.meshInstances[0]!.mesh.getNormals(normals);
    const sloped = corners(root).flatMap((corner, i) => (-corner[2]! > SLOPE[0] - 1e-4 && -corner[2]! < SLOPE[1] + 1e-4 && -corner[2]! > MARKER_Z + 1e-3 ? [i] : []));
    expect(sloped).toHaveLength(6 * 5);
    for (const i of sloped) expect(normals[i * 3]! / normals[i * 3 + 2]!).toBeCloseTo(1 / scale, 6);
    dressing.dispose();
    pieces.dispose();
  });

  it('copies a triangle in a bay and a storey once for every pair, and lifts its crown to the box', async () => {
    const host = app();
    const { pack, pieces } = await loaded(host);
    const root = new pc.Entity('root');
    // 20 m by 6 m: five bays, and 5 m of storeys over the 1 m of base and top: five storeys.
    const dressing = dressSlots(root, [slot([20_000, 100, 6000])], pack, families, pieces, SHADING);
    // The bay and storey cell, the marker and the sloping face 25 times; the rest of the bay column and the storey row
    // 5 times each; the crown over the bay 5 times; the four corner cells and the end crowns once.
    expect(dressing.triangles).toBe(2 * 25 + 2 * 25 + 2 * 25 + 4 * 5 + 4 * 5 + 2 * 5 + 8 + 4);
    expect(Math.max(...corners(root).map(([, up]) => up!))).toBeCloseTo(6, 5);
    const found = markers(root);
    expect(found).toHaveLength(25);
    expect(new Set(found).size).toBe(25);
    // The lowest marker's centre is its storey's middle: 0.5 m of base, then half a storey.
    expect(Math.min(...found.map((key) => Number(key.split(',')[1])))).toBeCloseTo(1, 4);
    expect(Math.max(...found.map((key) => Number(key.split(',')[1])))).toBeCloseTo(5, 4);
    dressing.dispose();
    pieces.dispose();
  });

  it('draws a storey a copy where the slot states its building\'s storey height', async () => {
    const host = app();
    const { pack, pieces } = await loaded(host);
    // 6.6 m of six 1100 mm storeys leaves 5.6 m over the base and under the top: five storeys of
    // 1120 mm, where the piece's own 1 m storey alone draws six.
    const root = new pc.Entity('root');
    const dressing = dressSlots(root, [{ ...slot([20_000, 100, 6600]), storeyHeightMm: 1100 }], pack, families, pieces, SHADING);
    const heights = [...new Set(markers(root).map((key) => key.split(',')[1]!))].map(Number).sort((a, b) => a - b);
    expect(heights).toEqual([0, 1, 2, 3, 4].map((k) => Number((0.5 + (k + 0.5) * 1.12).toFixed(3))));
    expect(markers(root)).toHaveLength(25);
    expect(Math.max(...corners(root).map(([, up]) => up!))).toBeCloseTo(6.6, 5);
    const plain = new pc.Entity('plain');
    const unstated = dressSlots(plain, [slot([20_000, 100, 6600])], pack, families, pieces, SHADING);
    expect(markers(plain)).toHaveLength(30);
    for (const one of [dressing, unstated]) one.dispose();
    pieces.dispose();
  });

  it('keeps the primitive for a box narrower than its ends, past the drawing\'s triangles, or a textured piece', async () => {
    const host = app();
    const camera = new pc.Entity('camera');
    host.root.addChild(camera);
    const { pack, pieces } = await loaded(host);
    // 1.2 m: no room for a bay past the two 600 mm ends.
    const narrow = dressSlots(new pc.Entity('narrow'), [slot([1200, 100, 2000])], pack, families, pieces, SHADING);
    expect(narrow.undressed).toEqual(['w']);
    // The 20 m by 2 m front bakes 76 triangles: one figure below that keeps it undressed.
    const view = (most: number) => ({ app: host, camera, drawing: { ...PIECE_DRAWING_DEFAULTS, repeatedTrianglesMost: most } });
    const over = dressSlots(new pc.Entity('over'), [slot([20_000, 100, 2000])], pack, families, pieces, SHADING, undefined, undefined, view(75));
    expect(over.undressed).toEqual(['w']);
    const within = dressSlots(new pc.Entity('within'), [slot([20_000, 100, 2000])], pack, families, pieces, SHADING, undefined, undefined, view(76));
    expect(within.undressed).toEqual([]);
    expect(within.triangles).toBe(76);
    for (const one of [narrow, over, within]) one.dispose();
    pieces.dispose();
    const textured = await loaded(host, true);
    const drawn = dressSlots(new pc.Entity('textured'), [slot([20_000, 100, 2000])], textured.pack, families, textured.pieces, SHADING);
    expect(drawn.undressed).toEqual(['w']);
    expect(drawn.instanced).toBeNull();
    drawn.dispose();
    textured.pieces.dispose();
  });
});
