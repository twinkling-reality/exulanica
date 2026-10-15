/**
 * A style pack's textured piece, read: its primitives by material, and each material's images.
 *
 * A piece whose container holds images is a textured piece (`docs/style-pack-contract.md`, section
 * 4); one that holds none is a palette piece (`style-piece.ts`). A textured piece is drawn as it is,
 * cut out where its colour's alpha falls under its material's cutoff; a pack's swatches never
 * recolour it. The server has already admitted it, held it to its family's budget and walked every
 * byte of every image; this reader takes it apart for drawing and refuses the rest by name, the same
 * way the server's reader does (`exulanica/world/style_pack_pieces.py`, `read_textured_piece`):
 *
 * - one mesh, drawn by the scene's one node with no transform of its own;
 * - each primitive triangles, with float `POSITION` and `NORMAL` and float `TEXCOORD_0`, nothing
 *   else, its indices unsigned short or int, whole triangles, and a material;
 * - each material a base colour texture on the first texture coordinates, optionally a normal
 *   texture, factors for base colour, metalness and roughness, alpha opaque or cut out by a cutoff
 *   (never blended) and whether both sides are drawn;
 * - each image embedded in the binary chunk as PNG or JPEG.
 *
 * Positions are glTF metres (+Y up, +Z front), the pivot at the base centre. Pure: no DOM, no
 * renderer; images are handed back as bytes for the caller to decode.
 */

export class TexturedPieceRefusal extends Error {
  override readonly name = 'TexturedPieceRefusal';
}

export type TexturedImageMedia = 'image/png' | 'image/jpeg';

export interface TexturedPieceImage {
  readonly bytes: Uint8Array;
  readonly mediaType: TexturedImageMedia;
}

/** How a texture repeats across its coordinates: glTF's wrap modes. */
export type TexturedWrap = 'repeat' | 'clamp' | 'mirror';

export interface TexturedPieceMaterial {
  /** The image its base colour reads, by index into the piece's images, and how it wraps. */
  readonly baseColour: { readonly image: number; readonly wrapS: TexturedWrap; readonly wrapT: TexturedWrap };
  /** A tangent-space normal image, or none. */
  readonly normal: { readonly image: number; readonly scale: number; readonly wrapS: TexturedWrap; readonly wrapT: TexturedWrap } | null;
  /** Linear RGBA the base colour texture is multiplied by. */
  readonly baseColourFactor: readonly [number, number, number, number];
  readonly metalness: number;
  readonly roughness: number;
  /** The alpha under which the surface is cut away, or null for an opaque one. */
  readonly alphaCutoff: number | null;
  readonly doubleSided: boolean;
}

export interface TexturedPiecePrimitive {
  readonly material: number;
  readonly positions: Float32Array;
  readonly normals: Float32Array;
  readonly uvs: Float32Array;
  readonly indices: Uint32Array;
}

export interface TexturedPiece {
  readonly primitives: readonly TexturedPiecePrimitive[];
  readonly materials: readonly TexturedPieceMaterial[];
  readonly images: readonly TexturedPieceImage[];
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
const WRAPS: Readonly<Record<number, TexturedWrap>> = Object.freeze({ 10497: 'repeat', 33071: 'clamp', 33648: 'mirror' });
const MEDIA: readonly string[] = ['image/png', 'image/jpeg'];
const ATTRIBUTES = 'NORMAL POSITION TEXCOORD_0';
const MATERIAL_KEYS = new Set(['name', 'pbrMetallicRoughness', 'normalTexture', 'alphaMode', 'alphaCutoff', 'doubleSided']);
const PBR_KEYS = new Set(['baseColorFactor', 'baseColorTexture', 'metallicFactor', 'roughnessFactor']);

const refuse = (detail: string): never => {
  throw new TexturedPieceRefusal(detail);
};

interface Accessor {
  readonly bufferView: number;
  readonly byteOffset?: number;
  readonly componentType: number;
  readonly count: number;
  readonly type: string;
}
interface Document {
  readonly scene?: number;
  readonly scenes?: { readonly nodes?: readonly number[] }[];
  readonly nodes?: Record<string, unknown>[];
  readonly meshes?: { readonly primitives: { attributes: Record<string, number>; indices?: number; mode?: number; material?: number }[] }[];
  readonly accessors?: Accessor[];
  readonly bufferViews?: { byteOffset?: number; byteLength: number; byteStride?: number }[];
  readonly materials?: Record<string, unknown>[];
  readonly textures?: { source?: number; sampler?: number }[];
  readonly samplers?: { wrapS?: number; wrapT?: number }[];
  readonly images?: { bufferView?: number; mimeType?: string; uri?: string }[];
}

/** The container's JSON and binary chunks, or a refusal; reads no accessor. */
function chunks(bytes: Uint8Array): { document: Document; bin: Uint8Array } {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (bytes.byteLength < 20 || view.getUint32(0, true) !== GLB_MAGIC || view.getUint32(4, true) !== 2) refuse('not a binary glTF 2.0 container');
  const jsonLength = view.getUint32(12, true);
  if (view.getUint32(16, true) !== JSON_CHUNK) refuse('the first chunk is not JSON');
  if (20 + jsonLength > bytes.byteLength) refuse('the JSON chunk runs past the container');
  const document = JSON.parse(new TextDecoder().decode(bytes.subarray(20, 20 + jsonLength))) as Document;
  const binAt = 20 + jsonLength;
  if (binAt + 8 > bytes.byteLength) return { document, bin: new Uint8Array(0) };
  if (view.getUint32(binAt + 4, true) !== BIN_CHUNK) refuse('the second chunk is not binary');
  return { document, bin: bytes.subarray(binAt + 8, binAt + 8 + view.getUint32(binAt, true)) };
}

/** Whether a piece is a textured piece: its container holds images. Reads the JSON chunk only. */
export function isTexturedPiece(bytes: Uint8Array): boolean {
  return (chunks(bytes).document.images ?? []).length > 0;
}

const unit = (value: unknown, what: string, fallback: number): number => {
  if (value === undefined) return fallback;
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1) refuse(`${what} is a number from 0 to 1`);
  return value as number;
};

/** Read a textured piece. */
export function readTexturedPiece(bytes: Uint8Array): TexturedPiece {
  const { document, bin } = chunks(bytes);
  const nodes = document.nodes ?? [];
  const sceneNodes = (document.scenes ?? [])[document.scene ?? 0]?.nodes ?? [];
  if (nodes.length !== 1 || sceneNodes.length !== 1 || sceneNodes[0] !== 0) refuse('a textured piece is drawn by one node');
  const node = nodes[0]!;
  if (Object.keys(node).some((key) => key !== 'mesh' && key !== 'name') || node['mesh'] !== 0) refuse('a textured piece\'s node draws its mesh with no transform');
  if ((document.meshes ?? []).length !== 1) refuse('a textured piece is one mesh');
  const images = (document.images ?? []).map((image, number): TexturedPieceImage => {
    if (image.uri !== undefined || image.bufferView === undefined) refuse(`images[${number}] is embedded`);
    if (!MEDIA.includes(image.mimeType ?? '')) refuse(`images[${number}] is image/png or image/jpeg`);
    const view = (document.bufferViews ?? [])[image.bufferView!] ?? refuse(`images[${number}] names no buffer view`);
    const start = view.byteOffset ?? 0;
    if (start + view.byteLength > bin.byteLength) refuse(`images[${number}] reaches past the binary chunk`);
    return { bytes: bin.subarray(start, start + view.byteLength), mediaType: image.mimeType as TexturedImageMedia };
  });
  if (images.length === 0) refuse('a textured piece holds at least one image');
  const textureOf = (info: unknown, what: string): { image: number; wrapS: TexturedWrap; wrapT: TexturedWrap } => {
    if (typeof info !== 'object' || info === null) return refuse(`${what} names a texture`);
    const stated = info as Record<string, unknown>;
    if ((stated['texCoord'] ?? 0) !== 0) refuse(`${what} reads the first texture coordinates`);
    const index = stated['index'];
    const texture = typeof index === 'number' ? (document.textures ?? [])[index] : undefined;
    if (texture === undefined || texture.source === undefined || images[texture.source] === undefined) return refuse(`${what} names no image`);
    const sampler = texture.sampler === undefined ? {} : (document.samplers ?? [])[texture.sampler] ?? refuse(`${what} names no sampler`);
    const wrap = (value: number | undefined): TexturedWrap => WRAPS[value ?? 10497] ?? refuse(`${what}'s sampler wraps by a glTF wrap mode`);
    return { image: texture.source, wrapS: wrap(sampler.wrapS), wrapT: wrap(sampler.wrapT) };
  };
  const materials = (document.materials ?? []).map((material, number): TexturedPieceMaterial => {
    const where = `materials[${number}]`;
    for (const key of Object.keys(material)) if (!MATERIAL_KEYS.has(key)) refuse(`${where} holds base colour, normal and factors only, not ${key}`);
    const pbr = (material['pbrMetallicRoughness'] ?? refuse(`${where} states its base colour`)) as Record<string, unknown>;
    for (const key of Object.keys(pbr)) if (!PBR_KEYS.has(key)) refuse(`${where} holds base colour, normal and factors only, not ${key}`);
    const factor = pbr['baseColorFactor'] ?? [1, 1, 1, 1];
    if (!Array.isArray(factor) || factor.length !== 4) refuse(`${where}.baseColorFactor is four numbers`);
    const mode = material['alphaMode'] ?? 'OPAQUE';
    if (mode !== 'OPAQUE' && mode !== 'MASK') refuse(`${where} is opaque or cut out, never blended`);
    const normal = material['normalTexture'] as Record<string, unknown> | undefined;
    const scale = normal?.['scale'] ?? 1;
    if (typeof scale !== 'number' || !Number.isFinite(scale)) refuse(`${where}.normalTexture.scale is a number`);
    const doubleSided = material['doubleSided'] ?? false;
    if (typeof doubleSided !== 'boolean') refuse(`${where}.doubleSided is true or false`);
    return {
      baseColour: textureOf(pbr['baseColorTexture'], `${where}.baseColorTexture`),
      normal: normal === undefined ? null : { ...textureOf(normal, `${where}.normalTexture`), scale: scale as number },
      baseColourFactor: (factor as unknown[]).map((value, k) => unit(value, `${where}.baseColorFactor[${k}]`, 1)) as unknown as readonly [number, number, number, number],
      metalness: unit(pbr['metallicFactor'], `${where}.metallicFactor`, 1),
      roughness: unit(pbr['roughnessFactor'], `${where}.roughnessFactor`, 1),
      alphaCutoff: mode === 'MASK' ? unit(material['alphaCutoff'], `${where}.alphaCutoff`, 0.5) : null,
      doubleSided: doubleSided as boolean,
    };
  });
  const accessors = document.accessors ?? [];
  const views = document.bufferViews ?? [];
  const accessor = (index: number | undefined, what: string): Accessor =>
    index === undefined ? refuse(`a textured piece's primitive states ${what}`) : accessors[index] ?? refuse(`${what} names no accessor`);
  const data = (a: Accessor, components: number, size: number): DataView => {
    const view = views[a.bufferView] ?? refuse('an accessor names no buffer view');
    if (view.byteStride !== undefined && view.byteStride !== components * size) refuse('a textured piece packs its attributes tightly');
    if ((a.byteOffset ?? 0) + a.count * components * size > view.byteLength) refuse('an accessor reaches past its buffer view');
    const start = (view.byteOffset ?? 0) + (a.byteOffset ?? 0);
    if (start + a.count * components * size > bin.byteLength) refuse('an accessor reaches past the binary chunk');
    return new DataView(bin.buffer, bin.byteOffset + start, a.count * components * size);
  };
  const floats = (a: Accessor, components: number): Float32Array => {
    const view = data(a, components, 4);
    const out = new Float32Array(a.count * components);
    for (let i = 0; i < out.length; i += 1) out[i] = view.getFloat32(i * 4, true);
    return out;
  };
  const bounds: [number, number, number, number, number, number] = [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];
  let triangles = 0;
  const primitives = document.meshes![0]!.primitives.map((primitive, number): TexturedPiecePrimitive => {
    const where = `meshes[0].primitives[${number}]`;
    if ((primitive.mode ?? TRIANGLES) !== TRIANGLES) refuse(`${where} is triangles`);
    if (Object.keys(primitive.attributes).sort().join(' ') !== ATTRIBUTES) refuse(`${where} states POSITION, NORMAL and TEXCOORD_0 and nothing else`);
    const material = primitive.material;
    if (material === undefined || materials[material] === undefined) refuse(`${where} names its material`);
    const position = accessor(primitive.attributes['POSITION'], 'POSITION');
    const normal = accessor(primitive.attributes['NORMAL'], 'NORMAL');
    const uv = accessor(primitive.attributes['TEXCOORD_0'], 'TEXCOORD_0');
    if (position.componentType !== FLOAT || position.type !== 'VEC3') refuse('POSITION is float VEC3');
    if (normal.componentType !== FLOAT || normal.type !== 'VEC3' || normal.count !== position.count) refuse('NORMAL is float VEC3, one per position');
    if (uv.componentType !== FLOAT || uv.type !== 'VEC2' || uv.count !== position.count) refuse('TEXCOORD_0 is float VEC2, one per position');
    const index = accessor(primitive.indices, 'indices');
    if ((index.componentType !== USHORT && index.componentType !== UINT) || index.type !== 'SCALAR' || index.count % 3 !== 0 || index.count === 0) {
      refuse('indices are unsigned short or int scalars, whole triangles');
    }
    const size = index.componentType === USHORT ? 2 : 4;
    const view = data(index, 1, size);
    const indices = new Uint32Array(index.count);
    for (let i = 0; i < index.count; i += 1) {
      const vertex = size === 2 ? view.getUint16(i * 2, true) : view.getUint32(i * 4, true);
      if (vertex >= position.count) refuse('an index names a vertex past the end');
      indices[i] = vertex;
    }
    const positions = floats(position, 3);
    for (let i = 0; i < positions.length; i += 3) {
      for (let k = 0; k < 3; k += 1) {
        bounds[k] = Math.min(bounds[k]!, positions[i + k]!);
        bounds[k + 3] = Math.max(bounds[k + 3]!, positions[i + k]!);
      }
    }
    triangles += index.count / 3;
    return { material: material!, positions, normals: floats(normal, 3), uvs: floats(uv, 2), indices };
  });
  if (primitives.length === 0) refuse('a textured piece holds at least one primitive');
  return { primitives, materials, images, triangles, bounds };
}
