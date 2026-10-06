import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { StylePieceRefusal, readStylePiece } from '../src/style-piece.js';

// Relative to web/, where the suite runs: the table the pieces' writer reads.
const TABLE = JSON.parse(readFileSync('../assets/colour/srgb8-linear16.v1.json', 'utf8')).values as number[];

const BRICK = [216, 105, 75] as const;
const CREAM = [243, 229, 206] as const;

interface Primitive {
  attributes: Record<string, number>;
  indices?: number;
  mode?: number;
}

/**
 * A binary glTF written here, independently of the pieces' writer: a floor quad in brick and a
 * wall quad in cream, eight vertices, four triangles, with 16-bit indices or `wide` 32-bit ones.
 * `edit` changes the document or the arrays before the bytes are laid out.
 */
function piece(
  edit: (parts: { colours: number[][]; indices: number[]; primitives: Primitive[]; accessors: Record<string, unknown>[] }) => void = () => {},
  wide = false,
): Uint8Array {
  const positions = [
    [0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1],
    [1, 0, 0], [1, 1, 0], [1, 1, 1], [1, 0, 1],
  ];
  const normals = [...Array(4).fill([0, 1, 0]), ...Array(4).fill([1, 0, 0])] as number[][];
  const linear = (srgb: readonly number[]): number[] => [...srgb.map((byte) => TABLE[byte]!), 65535];
  const colours = [...Array(4).fill(linear(BRICK)), ...Array(4).fill(linear(CREAM))].map((c: number[]) => [...c]);
  const indices = [0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7];
  const accessors: Record<string, unknown>[] = [
    { bufferView: 0, componentType: 5126, count: 8, type: 'VEC3' },
    { bufferView: 1, componentType: 5126, count: 8, type: 'VEC3' },
    { bufferView: 2, componentType: 5123, count: 8, type: 'VEC4', normalized: true },
    { bufferView: 3, componentType: wide ? 5125 : 5123, count: 12, type: 'SCALAR' },
  ];
  const primitives: Primitive[] = [{ attributes: { POSITION: 0, NORMAL: 1, COLOR_0: 2 }, indices: 3 }];
  edit({ colours, indices, primitives, accessors });
  const views = [
    new Uint8Array(new Float32Array(positions.flat()).buffer),
    new Uint8Array(new Float32Array(normals.flat()).buffer),
    new Uint8Array(new Uint16Array(colours.flat()).buffer),
    new Uint8Array((wide ? new Uint32Array(indices) : new Uint16Array(indices)).buffer),
  ];
  const bufferViews: { buffer: number; byteOffset: number; byteLength: number }[] = [];
  let length = 0;
  for (const view of views) {
    bufferViews.push({ buffer: 0, byteOffset: length, byteLength: view.byteLength });
    length += Math.ceil(view.byteLength / 4) * 4;
  }
  const binary = new Uint8Array(length);
  views.forEach((view, k) => binary.set(view, bufferViews[k]!.byteOffset));
  const document = { asset: { version: '2.0' }, accessors, bufferViews, buffers: [{ byteLength: length }], meshes: [{ primitives }] };
  const text = new TextEncoder().encode(JSON.stringify(document));
  const json = new Uint8Array(Math.ceil(text.byteLength / 4) * 4).fill(0x20);
  json.set(text);
  const bytes = new Uint8Array(12 + 8 + json.byteLength + 8 + binary.byteLength);
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

const refusal = (bytes: Uint8Array): string => {
  try {
    readStylePiece(bytes, TABLE);
  } catch (error) {
    if (error instanceof StylePieceRefusal) return error.message;
    throw error;
  }
  throw new Error('read');
};

describe('a palette piece, read', () => {
  it('groups its triangles by the swatch each is coloured, as sRGB bytes', () => {
    const read = readStylePiece(piece(), TABLE);
    expect(read.triangles).toBe(4);
    expect(read.bounds).toEqual([0, 0, 0, 1, 1, 1]);
    expect(read.groups.map((group) => group.srgb8)).toEqual([BRICK, CREAM]);
    const [brick, cream] = read.groups;
    expect([...brick!.indices]).toEqual([0, 1, 2, 0, 2, 3]);
    expect([...brick!.positions]).toEqual([0, 0, 0, 1, 0, 0, 1, 0, 1, 0, 0, 1]);
    expect([...brick!.normals]).toEqual([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]);
    expect([...cream!.normals]).toEqual([1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0]);
    expect([...cream!.indices]).toEqual([0, 1, 2, 0, 2, 3]);
  });

  it('reads 32-bit indices as it reads 16-bit ones', () => {
    expect(readStylePiece(piece(() => {}, true), TABLE)).toEqual(readStylePiece(piece(), TABLE));
  });

  it('refuses what is not a palette piece, by name', () => {
    const notGlb = piece();
    new DataView(notGlb.buffer).setUint32(4, 1, true);
    expect(refusal(notGlb)).toBe('not a binary glTF 2.0 container');
    expect(refusal(piece(({ primitives }) => primitives.push({ ...primitives[0]! })))).toBe('a palette piece is one primitive');
    expect(refusal(piece(({ primitives }) => { primitives[0]!.mode = 1; }))).toBe('a palette piece is triangles');
    expect(refusal(piece(({ primitives }) => { delete primitives[0]!.attributes['NORMAL']; }))).toBe('a palette piece states NORMAL');
    expect(refusal(piece(({ accessors }) => { accessors[2] = { ...accessors[2], normalized: false }; }))).toBe('COLOR_0 is VEC4 unsigned-short normalized, one per position');
    expect(refusal(piece(({ colours }) => { colours[2]![3] = 65534; }))).toBe('COLOR_0 alpha is 65535');
    expect(refusal(piece(({ colours }) => { colours[0]![0] = TABLE[216]! + 1; }))).toBe('a colour is no sRGB byte of the table');
    expect(refusal(piece(({ colours }) => { colours[2] = [...colours[4]!]; }))).toBe('a triangle is coloured by one swatch');
    expect(refusal(piece(({ indices }) => { indices[11] = 8; }))).toBe('an index names a vertex past the end');
    expect(refusal(piece(({ accessors }) => { accessors[3] = { ...accessors[3], count: 15 }; }))).toBe('an accessor reaches past its buffer view');
  });
});
