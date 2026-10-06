// @vitest-environment happy-dom
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { readStylePackManifest, resolveStylePack, type LookFamily, type ResolvedStylePack, type StylePackFile } from '@exulanica/atlas-core';
import { PackPieceRefusal, dressSlots, loadPackPieces, type PieceSlot } from '../src/playcanvas/style-pack/index.js';
import { attachTileInk } from '../src/playcanvas/generated-tile/ink.js';

// Relative to web/, where the suite runs.
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8'));
const TABLE = JSON.parse(readFileSync('../assets/colour/srgb8-linear16.v1.json', 'utf8')).values as number[];
const families = new Map<string, LookFamily>(Object.entries(CASES.context.families as Record<string, { fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }>)
  .map(([key, value]) => [key, { fit: value.fit, dressing: value.dressing, fillMinimumPermille: value.fill_minimum_permille, fillMaximumPermille: value.fill_maximum_permille }]));
const context = { families, textureSets: new Set<string>(CASES.context.texture_sets) };
const caseManifest = (name: string): Record<string, unknown> => structuredClone(CASES.cases.find((c: { name: string }) => c.name === name).manifest);

const BRICK = [216, 105, 75];
const CREAM = [243, 226, 194];

/**
 * A palette piece written here, apart from the pieces' writer: a window 1 m wide, 0.12 m deep and
 * 1.6 m tall about its base centre, its front a cream quad and its sill a brick one that runs from
 * its left edge to 0.2 m right of centre, so a mirror image is told apart.
 */
function windowPiece(sill: readonly number[] = BRICK): Uint8Array<ArrayBuffer> {
  return paletteGlb([
    { points: [[-0.5, 0, 0.06], [0.5, 0, 0.06], [0.5, 1.6, 0.06], [-0.5, 1.6, 0.06]], normal: [0, 0, 1], srgb: CREAM },
    { points: [[-0.5, 0.05, -0.06], [-0.5, 0.05, 0.06], [0.2, 0.05, 0.06], [0.2, 0.05, -0.06]], normal: [0, 1, 0], srgb: sill },
  ]);
}

/** Quads, each one colour with one normal, as a palette piece. */
function paletteGlb(quads: readonly { points: number[][]; normal: number[]; srgb: readonly number[] }[]): Uint8Array<ArrayBuffer> {
  const positions = quads.flatMap((quad) => quad.points.flat());
  const normals = quads.flatMap((quad) => Array(4).fill(quad.normal).flat() as number[]);
  const colours = quads.flatMap((quad) => Array(4).fill([...quad.srgb.map((byte) => TABLE[byte]!), 65535]).flat() as number[]);
  const indices = quads.flatMap((_, q) => [0, 1, 2, 0, 2, 3].map((corner) => corner + q * 4));
  const views = [new Float32Array(positions), new Float32Array(normals), new Uint16Array(colours), new Uint16Array(indices)].map((view) => new Uint8Array(view.buffer));
  const offsets: number[] = [];
  let length = 0;
  for (const view of views) {
    offsets.push(length);
    length += Math.ceil(view.byteLength / 4) * 4;
  }
  const binary = new Uint8Array(length);
  views.forEach((view, k) => binary.set(view, offsets[k]));
  const vertices = quads.length * 4;
  const document = {
    asset: { version: '2.0' },
    accessors: [
      { bufferView: 0, componentType: 5126, count: vertices, type: 'VEC3' },
      { bufferView: 1, componentType: 5126, count: vertices, type: 'VEC3' },
      { bufferView: 2, componentType: 5123, count: vertices, type: 'VEC4', normalized: true },
      { bufferView: 3, componentType: 5123, count: quads.length * 6, type: 'SCALAR' },
    ],
    bufferViews: views.map((view, k) => ({ buffer: 0, byteOffset: offsets[k], byteLength: view.byteLength })),
    buffers: [{ byteLength: length }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0, NORMAL: 1, COLOR_0: 2 }, indices: 3 }] }],
  };
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

/** The complete case pack with its window file stated as `piece`. */
function townPack(piece: Uint8Array): ReturnType<typeof readStylePackManifest> {
  const manifest = caseManifest('a complete pack with no base');
  const files = manifest['files'] as { path: string; sha256: string; bytes: number }[];
  const window = files.find((file) => file.path === 'pieces/window.glb')!;
  window.sha256 = createHash('sha256').update(piece).digest('hex');
  window.bytes = piece.byteLength;
  return readStylePackManifest(manifest, context);
}

/** An application on a null device, so entities can take render components. */
function device(): pc.GraphicsDevice {
  const canvas = document.createElement('canvas');
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  return app.graphicsDevice;
}

const served = (bytes: Uint8Array<ArrayBuffer>) => async (_file: StylePackFile): Promise<Uint8Array<ArrayBuffer>> => bytes;

describe('a pack\'s pieces, loaded', () => {
  it('reads each piece once, checked against its manifest, as one mesh per swatch named by key', async () => {
    const bytes = windowPiece();
    const pack = resolveStylePack([townPack(bytes)]);
    const pieces = await loadPackPieces(device(), pack, ['window.default'], TABLE, served(bytes));
    const module = pack.modules['window.default']!;
    const piece = pieces.get(module, module.files.get('pieces/window.glb')!)!;
    expect(pieces.count).toBe(1);
    expect(piece.groups.map((group) => group.swatch)).toEqual(['cream', 'brick']);
    expect(piece.triangles).toBe(4);
    expect([...piece.bounds].map((value) => Math.round(value * 1000))).toEqual([-500, 0, -60, 500, 1600, 60]);
    pieces.dispose();
  });

  it('refuses bytes that are not the ones its manifest names, and keeps nothing', async () => {
    const bytes = windowPiece();
    const pack = resolveStylePack([townPack(bytes)]);
    const altered = bytes.slice();
    altered[altered.byteLength - 1] = altered[altered.byteLength - 1]! ^ 1;
    await expect(loadPackPieces(device(), pack, ['window.default'], TABLE, served(altered))).rejects.toThrow(new PackPieceRefusal('pieces/window.glb is not the bytes its manifest names'));
    await expect(loadPackPieces(device(), pack, ['window.default'], TABLE, served(bytes.slice(0, 64)))).rejects.toThrow(/is 64 bytes; its manifest states/);
  });

  it('refuses a piece coloured outside its pack\'s palette', async () => {
    const bytes = windowPiece([1, 2, 3]);
    const pack = resolveStylePack([townPack(bytes)]);
    await expect(loadPackPieces(device(), pack, ['window.default'], TABLE, served(bytes))).rejects.toThrow(new PackPieceRefusal('pieces/window.glb is coloured 1,2,3, no swatch of its pack'));
  });
});

describe('pieces placed in slots', () => {
  const south: PieceSlot = { identity: 'south', lookRole: 'window.arched', positionMm: [10_000, 20_000, 3_000], front: [0, -1], boxMm: [1000, 120, 1600] };
  const east: PieceSlot = { identity: 'east', lookRole: 'window.default', positionMm: [0, 0, 0], front: [1, 0], boxMm: [3000, 243, 2400] };
  const tooSmall: PieceSlot = { identity: 'too-small', lookRole: 'window.default', positionMm: [0, 0, 0], front: [1, 0], boxMm: [110, 120, 1600] };
  const car: PieceSlot = { identity: 'car', lookRole: 'vehicle.car', positionMm: [0, 0, 0], front: [1, 0], boxMm: [4400, 1850, 1550] };

  async function dressed(pack: ResolvedStylePack, bytes: Uint8Array<ArrayBuffer>, slots: readonly PieceSlot[]) {
    const pieces = await loadPackPieces(device(), pack, ['window.default'], TABLE, served(bytes));
    const parent = new pc.Entity('environment');
    const dressing = dressSlots(parent, slots, pack, families, pieces, { model: 'pbr', toon: null, ink: null });
    return { pieces, parent, dressing };
  }

  /** A baked mesh's corners and normals, as triples. */
  function corners(instance: pc.MeshInstance): { positions: number[][]; normals: number[][] } {
    const positions: number[] = [];
    const normals: number[] = [];
    instance.mesh.getPositions(positions);
    instance.mesh.getNormals(normals);
    const triples = (values: number[]) => Array.from({ length: values.length / 3 }, (_, i) => values.slice(i * 3, i * 3 + 3));
    return { positions: triples(positions), normals: triples(normals) };
  }

  const bounds = (points: number[][]) => [0, 1, 2].flatMap((axis) => [Math.min(...points.map((p) => p[axis]!)), Math.max(...points.map((p) => p[axis]!))]);
  const near = (values: number[], expected: number[]) => expected.forEach((value, i) => expect(values[i]).toBeCloseTo(value, 5));

  it('stands each piece base centre on its slot, front to the slot\'s front, a draw per swatch', async () => {
    const bytes = windowPiece();
    const { pieces, parent, dressing } = await dressed(resolveStylePack([townPack(bytes)]), bytes, [south, tooSmall, car]);
    expect(dressing.placed).toBe(1);
    // A hole narrower than the frame's two bars leaves no stretch; the car's pieces were not loaded.
    expect(dressing.undressed).toEqual(['too-small', 'car']);
    expect(dressing.draws).toBe(2);
    expect(dressing.triangles).toBe(4);
    const [entity] = parent.children as pc.Entity[];
    expect(entity!.name).toBe('style-pack:pieces');
    const instances = entity!.render!.meshInstances;
    expect(instances.map((instance) => instance.material.name)).toEqual(['style-pack:swatch:cream', 'style-pack:swatch:brick']);
    // Facing south, its own size: the cream front spans 9.5 to 10.5 m east, 3 to 4.6 m up, at 19.94 m north.
    const cream = corners(instances[0]!);
    near(bounds(cream.positions), [9.5, 10.5, 3, 4.6, -19.94, -19.94]);
    for (const n of cream.normals) near(n, [0, 0, 1]);
    dressing.dispose();
    expect(parent.children).toHaveLength(0);
    // The library's meshes outlive a dressing, and go with the library.
    const module = resolveStylePack([townPack(bytes)]).modules['window.default']!;
    const mesh = pieces.get(module, module.files.get('pieces/window.glb')!)!.groups[0]!.mesh;
    expect(mesh.vertexBuffer).not.toBeNull();
    pieces.dispose();
    expect(mesh.vertexBuffer).toBeNull();
  });

  it('stretches a piece between its frame bars to fill the hole, keeping what lies outside its zones', async () => {
    const bytes = windowPiece();
    const { parent, dressing } = await dressed(resolveStylePack([townPack(bytes)]), bytes, [east]);
    const [cream, brick] = (parent.children[0] as pc.Entity).render!.meshInstances.map(corners);
    // Facing east, 3 m wide by 2.4 m tall by 243 mm deep: the front fills the hole, its right
    // (glTF +X) to the north, which is the renderer's -Z, and stands at the slot's front face.
    near(bounds(cream!.positions), [0.1215, 0.1215, 0, 2.4, -1.5, 1.5]);
    for (const n of cream!.normals) near(n, [1, 0, 0]);
    // The sill lies 50 mm up, below the zone that starts at 60, so it stays 50 mm up; it runs the
    // slot's whole depth, and from the left edge (south, as a viewer facing east sees it) to 700 mm
    // from that edge, inside the zone: 60 + 640 x 2880 / 880 mm, which is 0.6545 m north of centre.
    near(bounds(brick!.positions), [-0.1215, 0.1215, 0.05, 0.05, -(2154.5454545 - 1500) / 1000, 1.5]);
    for (const n of brick!.normals) near(n, [0, 1, 0]);
    dressing.dispose();
  });

  it('turns a slanted face\'s normal by the stretch its triangles lie in', async () => {
    // A face sloping up to the right at 45 degrees, inside the width and height zones.
    const n = Math.SQRT1_2;
    const bytes = paletteGlb([{ points: [[-0.3, 0.2, -0.05], [-0.3, 0.2, 0.05], [0.3, 0.8, 0.05], [0.3, 0.8, -0.05]], normal: [-n, n, 0], srgb: CREAM }]);
    const { parent, dressing } = await dressed(resolveStylePack([townPack(bytes)]), bytes, [east]);
    const [face] = (parent.children[0] as pc.Entity).render!.meshInstances.map(corners);
    // Width draws out 2880 / 880 and height (2400 - 120) / 1480; a normal divides by each.
    const [x, y] = [-n / (2880 / 880), n / (2280 / 1480)];
    const length = Math.hypot(x, y);
    // glTF +X is north (the renderer's -Z) for a slot facing east.
    for (const normal of face!.normals) near(normal, [0, y / length, -x / length]);
    dressing.dispose();
  });

  it('are inked when a look that draws ink names them, and only then', async () => {
    const bytes = windowPiece();
    const { pieces, parent, dressing } = await dressed(resolveStylePack([townPack(bytes)]), bytes, [south, east]);
    const device = pieces.get(resolveStylePack([townPack(bytes)]).modules['window.default']!, resolveStylePack([townPack(bytes)]).modules['window.default']!.files.get('pieces/window.glb')!)!.groups[0]!.mesh.device;
    const tilesOnly = attachTileInk(device, parent, [0, 0, 0]);
    expect(tilesOnly.segments).toBe(0);
    tilesOnly.dispose();
    const withPieces = attachTileInk(device, parent, [0, 0, 0], undefined, ['generated-tile:', 'style-pack:pieces']);
    expect(withPieces.segments).toBeGreaterThan(0);
    expect(parent.findByName('style-pack:pieces')!.findByName('generated-tile:ink')).not.toBeNull();
    withPieces.dispose();
    dressing.dispose();
  });

  it('draws a base pack\'s pieces in the swatches a pack drawn on it restates', async () => {
    const bytes = windowPiece();
    const base = townPack(bytes);
    const dusk = readStylePackManifest(caseManifest('a pack drafted on a base, stating only what it changes'), context);
    const { parent, dressing } = await dressed(resolveStylePack([dusk, base]), bytes, [south]);
    const brick = (parent.children[0] as pc.Entity).render!.meshInstances[1]!.material as pc.StandardMaterial;
    expect(brick.name).toBe('style-pack:swatch:brick');
    expect([brick.diffuse.r, brick.diffuse.g, brick.diffuse.b]).toEqual([150 / 255, 70 / 255, 60 / 255]);
    dressing.dispose();
  });
});
