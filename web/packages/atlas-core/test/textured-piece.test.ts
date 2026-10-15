import { describe, expect, it } from 'vitest';
import {
  PIECE_DRAWING_DEFAULTS, TexturedPieceRefusal, isTexturedPiece, pieceDrawingOf, readStylePiece, readTexturedPiece,
} from '../src/index.js';

/** The first bytes of a PNG and of a JPEG: the reader hands images back undecoded. */
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3, 4]);
const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 5, 6, 7]);

interface Quad { readonly points: number[][]; readonly normal: number[]; readonly material: number }

/**
 * A textured piece written here, apart from the tree maker's writer: quads by material, one
 * primitive a material, the images embedded after the geometry. `edit` may change the document
 * before it is written, to make each refusal.
 */
function texturedGlb(quads: readonly Quad[], images: readonly { bytes: Uint8Array; mimeType: string }[], edit?: (document: Record<string, any>) => void): Uint8Array {
  const materials = [...new Set(quads.map((quad) => quad.material))].sort();
  const parts: Uint8Array[] = [];
  const views: { byteOffset: number; byteLength: number }[] = [];
  let length = 0;
  const add = (bytes: Uint8Array): number => {
    views.push({ byteOffset: length, byteLength: bytes.byteLength });
    parts.push(bytes);
    length += Math.ceil(bytes.byteLength / 4) * 4;
    return views.length - 1;
  };
  const accessors: Record<string, unknown>[] = [];
  const primitives = materials.map((material) => {
    const own = quads.filter((quad) => quad.material === material);
    const positions = own.flatMap((quad) => quad.points.flat());
    const normals = own.flatMap((quad) => Array(4).fill(quad.normal).flat() as number[]);
    const uvs = own.flatMap(() => [0, 0, 0, 1, 1, 1, 1, 0]);
    const indices = own.flatMap((_, q) => [0, 1, 2, 0, 2, 3].map((corner) => corner + q * 4));
    const at = accessors.length;
    accessors.push(
      { bufferView: add(new Uint8Array(new Float32Array(positions).buffer)), componentType: 5126, count: own.length * 4, type: 'VEC3' },
      { bufferView: add(new Uint8Array(new Float32Array(normals).buffer)), componentType: 5126, count: own.length * 4, type: 'VEC3' },
      { bufferView: add(new Uint8Array(new Float32Array(uvs).buffer)), componentType: 5126, count: own.length * 4, type: 'VEC2' },
      { bufferView: add(new Uint8Array(new Uint16Array(indices).buffer)), componentType: 5123, count: indices.length, type: 'SCALAR' },
    );
    return { attributes: { POSITION: at, NORMAL: at + 1, TEXCOORD_0: at + 2 }, indices: at + 3, material, mode: 4 };
  });
  const imageViews = images.map((image) => add(image.bytes));
  const document: Record<string, any> = {
    asset: { version: '2.0' },
    scene: 0,
    scenes: [{ nodes: [0] }],
    nodes: [{ mesh: 0 }],
    meshes: [{ primitives }],
    accessors,
    bufferViews: views.map((view) => ({ buffer: 0, ...view })),
    buffers: [{ byteLength: length }],
    images: images.map((image, k) => ({ bufferView: imageViews[k], mimeType: image.mimeType })),
    samplers: [{ wrapS: 33071, wrapT: 10497 }],
    textures: images.map((_, k) => ({ source: k, sampler: 0 })),
    materials: [
      { pbrMetallicRoughness: { baseColorTexture: { index: 0 }, baseColorFactor: [0.5, 0.75, 1, 1], metallicFactor: 0, roughnessFactor: 0.9 }, normalTexture: { index: 1, scale: 0.8 } },
      { pbrMetallicRoughness: { baseColorTexture: { index: 0 }, roughnessFactor: 0.7 }, alphaMode: 'MASK', alphaCutoff: 0.4, doubleSided: true },
    ].slice(0, materials.length),
  };
  edit?.(document);
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

/** A trunk quad in bark and a leaf card quad, 1 m wide, the leaf from 1 to 3 m up. */
const TREE: readonly Quad[] = [
  { points: [[-0.1, 0, 0], [-0.1, 1.2, 0], [0.1, 1.2, 0], [0.1, 0, 0]], normal: [0, 0, 1], material: 0 },
  { points: [[-0.5, 3, 0.2], [-0.5, 1, 0.2], [0.5, 1, 0.2], [0.5, 3, 0.2]], normal: [0, 0, 1], material: 1 },
];
const IMAGES = [{ bytes: PNG, mimeType: 'image/png' }, { bytes: JPEG, mimeType: 'image/jpeg' }];

describe('a textured piece', () => {
  it('reads each material\'s primitive, its images and factors, as the server reads them', () => {
    const piece = readTexturedPiece(texturedGlb(TREE, IMAGES));
    expect(piece.triangles).toBe(4);
    expect(piece.primitives.map((primitive) => primitive.material)).toEqual([0, 1]);
    expect([...piece.primitives[1]!.indices]).toEqual([0, 1, 2, 0, 2, 3]);
    expect([...piece.primitives[1]!.uvs]).toEqual([0, 0, 0, 1, 1, 1, 1, 0]);
    expect([...piece.bounds].map((value) => Math.round(value * 1000))).toEqual([-500, 0, 0, 500, 3000, 200]);
    expect(piece.images.map((image) => [image.mediaType, [...image.bytes]])).toEqual([['image/png', [...PNG]], ['image/jpeg', [...JPEG]]]);
    expect(piece.materials[0]).toEqual({
      baseColour: { image: 0, wrapS: 'clamp', wrapT: 'repeat' },
      normal: { image: 1, scale: 0.8, wrapS: 'clamp', wrapT: 'repeat' },
      baseColourFactor: [0.5, 0.75, 1, 1], metalness: 0, roughness: 0.9, alphaCutoff: null, doubleSided: false,
    });
    expect(piece.materials[1]).toMatchObject({ normal: null, baseColourFactor: [1, 1, 1, 1], metalness: 1, roughness: 0.7, alphaCutoff: 0.4, doubleSided: true });
  });

  it('is told from a palette piece by its images, and neither reader takes the other\'s piece', () => {
    const bytes = texturedGlb(TREE, IMAGES);
    expect(isTexturedPiece(bytes)).toBe(true);
    expect(isTexturedPiece(texturedGlb(TREE, IMAGES, (document) => {
      delete document['images'];
      delete document['textures'];
      delete document['samplers'];
    }))).toBe(false);
    expect(() => readStylePiece(bytes, Array.from({ length: 256 }, (_, k) => k * 257))).toThrow('a palette piece is one primitive');
  });

  const refusals: readonly [string, (document: Record<string, any>) => void][] = [
    ['a textured piece\'s node draws its mesh with no transform', (d) => { d['nodes'][0].translation = [0, 1, 0]; }],
    ['a textured piece is drawn by one node', (d) => { d['nodes'].push({ mesh: 0 }); d['scenes'][0].nodes.push(1); }],
    ['a textured piece is one mesh', (d) => { d['meshes'].push(d['meshes'][0]); }],
    ['meshes[0].primitives[0] states POSITION, NORMAL and TEXCOORD_0 and nothing else', (d) => { d['meshes'][0].primitives[0].attributes.COLOR_0 = 1; }],
    ['materials[1] is opaque or cut out, never blended', (d) => { d['materials'][1].alphaMode = 'BLEND'; }],
    ['materials[0] holds base colour, normal and factors only, not emissiveFactor', (d) => { d['materials'][0].emissiveFactor = [1, 0, 0]; }],
    ['materials[0] holds base colour, normal and factors only, not metallicRoughnessTexture', (d) => { d['materials'][0].pbrMetallicRoughness.metallicRoughnessTexture = { index: 0 }; }],
    ['materials[0].baseColorTexture reads the first texture coordinates', (d) => { d['materials'][0].pbrMetallicRoughness.baseColorTexture.texCoord = 1; }],
    ['images[0] is embedded', (d) => { d['images'][0] = { uri: 'leaf.png', mimeType: 'image/png' }; }],
    ['images[1] is image/png or image/jpeg', (d) => { d['images'][1].mimeType = 'image/webp'; }],
    ['materials[0].baseColorTexture names no image', (d) => { d['textures'][0].source = 9; }],
    ['materials[1].alphaCutoff is a number from 0 to 1', (d) => { d['materials'][1].alphaCutoff = 2; }],
  ];
  for (const [reason, edit] of refusals) {
    it(`refuses: ${reason}`, () => {
      expect(() => readTexturedPiece(texturedGlb(TREE, IMAGES, edit))).toThrow(new TexturedPieceRefusal(reason));
    });
  }

  it('refuses an index past the last vertex', () => {
    const bytes = texturedGlb(TREE, IMAGES, (document) => { document['accessors'][3].count = 6; });
    const view = new DataView(bytes.buffer);
    // The first primitive's indices are its fourth view: the first index points past the quad.
    const json = view.getUint32(12, true);
    const document = JSON.parse(new TextDecoder().decode(bytes.subarray(20, 20 + json))) as { bufferViews: { byteOffset: number }[] };
    view.setUint16(28 + json + document.bufferViews[3]!.byteOffset, 99, true);
    expect(() => readTexturedPiece(bytes)).toThrow(new TexturedPieceRefusal('an index names a vertex past the end'));
  });
});

describe('the figures textured pieces are drawn with', () => {
  it('are today\'s defaults when none is stated, and a stated one within its range otherwise', () => {
    expect(pieceDrawingOf()).toBe(PIECE_DRAWING_DEFAULTS);
    expect(pieceDrawingOf({ shadowReachM: 40 })).toEqual({ ...PIECE_DRAWING_DEFAULTS, shadowReachM: 40 });
  });
  it('refuse an unknown figure or one out of its range, by name', () => {
    expect(() => pieceDrawingOf({ lodDistance: 3 } as never)).toThrow('piece drawing: unknown figure "lodDistance"');
    expect(() => pieceDrawingOf({ cellSizeM: 4 })).toThrow('piece drawing: cellSizeM is a number from 8 to 512');
    expect(() => pieceDrawingOf({ hysteresisPermille: Number.NaN })).toThrow('piece drawing: hysteresisPermille is a number from 0 to 500');
  });
});
