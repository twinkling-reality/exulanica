/**
 * A style pack's piece, read: a palette piece's triangles grouped by the swatch each is coloured.
 *
 * A piece is an `exulanica.static-glb/v1` container the server has already admitted, prepared and
 * held to its digest. A palette piece (as GEN's writer and the authored packs' builder write them)
 * is one mesh of triangles with `POSITION`, `NORMAL` and `COLOR_0`, where `COLOR_0` is `VEC4`
 * unsigned-short normalized and every RGB triple is exactly one swatch of the palette in the
 * encoding `exulanica.srgb8-linear16/v1`. This reader takes such a piece apart by swatch, so the
 * page can draw each swatch's triangles with that swatch's material, and a pack drawn on another
 * can recolour a piece by changing a swatch.
 *
 * It reads only what it needs and refuses the rest by name: not a binary glTF, more than one
 * primitive, a primitive that is not triangles, an attribute missing or of another layout, an alpha
 * other than 65535, or a colour that is no swatch. Positions are glTF metres (+Y up, +Z front).
 *
 * Pure: no DOM, no renderer.
 */

export class StylePieceRefusal extends Error {
  override readonly name = 'StylePieceRefusal';
}

export interface StylePieceGroup {
  /** The swatch these triangles are coloured, by the srgb8 bytes it encodes. */
  readonly srgb8: readonly [number, number, number];
  readonly positions: Float32Array;
  readonly normals: Float32Array;
  readonly indices: Uint32Array;
}

export interface StylePiece {
  readonly groups: readonly StylePieceGroup[];
  readonly triangles: number;
  /** Bounds of the positions, metres: [minX, minY, minZ, maxX, maxY, maxZ]. */
  readonly bounds: readonly [number, number, number, number, number, number];
}

const GLB_MAGIC = 0x46546c67;
const JSON_CHUNK = 0x4e4f534a;
const BIN_CHUNK = 0x004e4942;
const FLOAT = 5126;
const USHORT = 5123;
const UINT = 5125;
const TRIANGLES = 4;

const refuse = (detail: string): never => {
  throw new StylePieceRefusal(detail);
};

interface Accessor {
  readonly bufferView: number;
  readonly byteOffset?: number;
  readonly componentType: number;
  readonly count: number;
  readonly type: string;
  readonly normalized?: boolean;
}

/** Read a palette piece. `table` is the 256 linear values of `exulanica.srgb8-linear16/v1`. */
export function readStylePiece(bytes: Uint8Array, table: readonly number[]): StylePiece {
  if (table.length !== 256) refuse('the colour table holds 256 values');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (bytes.byteLength < 20 || view.getUint32(0, true) !== GLB_MAGIC || view.getUint32(4, true) !== 2) refuse('not a binary glTF 2.0 container');
  const jsonLength = view.getUint32(12, true);
  if (view.getUint32(16, true) !== JSON_CHUNK) refuse('the first chunk is not JSON');
  const json = JSON.parse(new TextDecoder().decode(bytes.subarray(20, 20 + jsonLength))) as {
    meshes?: { primitives: { attributes: Record<string, number>; indices?: number; mode?: number }[] }[];
    accessors?: Accessor[];
    bufferViews?: { byteOffset?: number; byteLength: number; byteStride?: number }[];
  };
  const binAt = 20 + jsonLength;
  if (view.getUint32(binAt + 4, true) !== BIN_CHUNK) refuse('the second chunk is not binary');
  const bin = bytes.subarray(binAt + 8, binAt + 8 + view.getUint32(binAt, true));
  const primitives = (json.meshes ?? []).flatMap((mesh) => mesh.primitives);
  if (primitives.length !== 1) refuse('a palette piece is one primitive');
  const primitive = primitives[0]!;
  if ((primitive.mode ?? TRIANGLES) !== TRIANGLES) refuse('a palette piece is triangles');
  const accessor = (index: number | undefined, what: string): Accessor =>
    (index === undefined ? refuse(`a palette piece states ${what}`) : (json.accessors ?? [])[index] ?? refuse(`${what} names no accessor`));
  const data = (a: Accessor, components: number, size: number): DataView => {
    const bufferView = (json.bufferViews ?? [])[a.bufferView] ?? refuse('an accessor names no buffer view');
    if (bufferView.byteStride !== undefined && bufferView.byteStride !== components * size) refuse('a palette piece packs its attributes tightly');
    if ((a.byteOffset ?? 0) + a.count * components * size > bufferView.byteLength) refuse('an accessor reaches past its buffer view');
    const start = (bufferView.byteOffset ?? 0) + (a.byteOffset ?? 0);
    if (start + a.count * components * size > bin.byteLength) refuse('an accessor reaches past the binary chunk');
    return new DataView(bin.buffer, bin.byteOffset + start, a.count * components * size);
  };
  const position = accessor(primitive.attributes['POSITION'], 'POSITION');
  const normal = accessor(primitive.attributes['NORMAL'], 'NORMAL');
  const colour = accessor(primitive.attributes['COLOR_0'], 'COLOR_0');
  if (position.componentType !== FLOAT || position.type !== 'VEC3') refuse('POSITION is float VEC3');
  if (normal.componentType !== FLOAT || normal.type !== 'VEC3' || normal.count !== position.count) refuse('NORMAL is float VEC3, one per position');
  if (colour.componentType !== USHORT || colour.type !== 'VEC4' || colour.normalized !== true || colour.count !== position.count) {
    refuse('COLOR_0 is VEC4 unsigned-short normalized, one per position');
  }
  const indexAccessor = accessor(primitive.indices, 'indices');
  if ((indexAccessor.componentType !== USHORT && indexAccessor.componentType !== UINT) || indexAccessor.type !== 'SCALAR' || indexAccessor.count % 3 !== 0) {
    refuse('indices are unsigned short or int scalars, whole triangles');
  }
  const p = data(position, 3, 4);
  const n = data(normal, 3, 4);
  const c = data(colour, 4, 2);
  const indexSize = indexAccessor.componentType === USHORT ? 2 : 4;
  const ix = data(indexAccessor, 1, indexSize);
  const byLinear = new Map<number, number>();
  table.forEach((value, byte) => byLinear.set(value, byte));
  const swatchOf = (vertex: number): string => {
    if (c.getUint16(vertex * 8 + 6, true) !== 65535) refuse('COLOR_0 alpha is 65535');
    const bytes3 = [0, 1, 2].map((k) => byLinear.get(c.getUint16(vertex * 8 + k * 2, true)) ?? refuse('a colour is no sRGB byte of the table'));
    return bytes3.join(',');
  };
  const groups = new Map<string, { positions: number[]; normals: number[]; indices: number[]; remap: Map<number, number> }>();
  const bounds: [number, number, number, number, number, number] = [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];
  for (let corner = 0; corner < indexAccessor.count; corner += 3) {
    const corners = [0, 1, 2].map((k) => (indexSize === 2 ? ix.getUint16((corner + k) * 2, true) : ix.getUint32((corner + k) * 4, true)));
    if (corners.some((v) => v >= position.count)) refuse('an index names a vertex past the end');
    const key = swatchOf(corners[0]!);
    if (corners.some((v) => swatchOf(v) !== key)) refuse('a triangle is coloured by one swatch');
    let group = groups.get(key);
    if (group === undefined) {
      group = { positions: [], normals: [], indices: [], remap: new Map() };
      groups.set(key, group);
    }
    for (const v of corners) {
      let mapped = group.remap.get(v);
      if (mapped === undefined) {
        mapped = group.positions.length / 3;
        group.remap.set(v, mapped);
        for (let k = 0; k < 3; k += 1) {
          const value = p.getFloat32((v * 3 + k) * 4, true);
          group.positions.push(value);
          group.normals.push(n.getFloat32((v * 3 + k) * 4, true));
          bounds[k] = Math.min(bounds[k]!, value);
          bounds[k + 3] = Math.max(bounds[k + 3]!, value);
        }
      }
      group.indices.push(mapped);
    }
  }
  return {
    groups: [...groups.entries()].map(([key, group]) => ({
      srgb8: key.split(',').map(Number) as unknown as readonly [number, number, number],
      positions: new Float32Array(group.positions),
      normals: new Float32Array(group.normals),
      indices: new Uint32Array(group.indices),
    })),
    triangles: indexAccessor.count / 3,
    bounds,
  };
}
