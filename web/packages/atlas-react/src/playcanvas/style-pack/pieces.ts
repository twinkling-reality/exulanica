import * as pc from 'playcanvas';
import {
  isTexturedPiece, readStylePiece, readTexturedPiece, swatchKeyOf,
  type ResolvedModule, type ResolvedStylePack, type StylePackFile, type TexturedPiece, type TexturedWrap,
} from '@exulanica/atlas-core';
import type { RenderShading } from '../generated-tile/look.js';
import { applyShading } from '../generated-tile/shading.js';
import { decodeBrowserPicture, type DecodePicture, type DecodedPicture } from './site-textures.js';

/**
 * A style pack's pieces, loaded for drawing.
 *
 * Each piece file a pack's modules name is fetched by the caller (a committed pack's files ship with
 * the page; a library pack's come from the store), held here to the size and sha256 its manifest
 * states, read as a palette piece and uploaded as one mesh per swatch. A group's swatch is named by
 * KEY, looked up in the palette of the manifest that stated the module, so a pack drawn on another
 * recolours a base pack's pieces by restating a swatch under the same key.
 *
 * Bytes that are not what the manifest states, or a piece coloured outside its palette, are refused
 * by name; nothing partial is kept. The library owns its meshes until `dispose`, whatever dressings
 * draw them.
 *
 * A textured piece (its container holds images) is read with `readTexturedPiece` instead, and its
 * variant's second level of detail is fetched beside it, held to its manifest the same way. Each
 * image is decoded once per digest; the upload makes one texture per image and use (colour in sRGB,
 * a normal map linear) and one material per material of each level, in the pack's shading, and the
 * library destroys them with its meshes, so a drawing's textures go with the drawing.
 */

export class PackPieceRefusal extends Error {
  override readonly name = 'PackPieceRefusal';
}

export interface LoadedPieceGroup {
  /** The swatch key this group is drawn in. */
  readonly swatch: string;
  /** The group uploaded, for drawing the piece as it is (instanced). */
  readonly mesh: pc.Mesh;
  /** The group's triangles, for placing the piece stretched (baked). Metres, glTF axes. */
  readonly positions: Float32Array;
  readonly normals: Float32Array;
  readonly indices: Uint32Array;
}

/** One primitive of a textured piece, uploaded with its material. */
export interface LoadedTexturedPrimitive {
  readonly mesh: pc.Mesh;
  readonly material: pc.StandardMaterial;
  /** The primitive's triangles, metres, glTF axes, for a seat's contact copy. */
  readonly positions: Float32Array;
  readonly normals: Float32Array;
  readonly indices: Uint32Array;
}

/** A textured piece's levels of detail, uploaded: the first always, the second where its variant states one. */
export interface LoadedTexturedLevels {
  readonly lod0: readonly LoadedTexturedPrimitive[];
  readonly lod1: readonly LoadedTexturedPrimitive[] | null;
}

export interface LoadedPiece {
  /** A palette piece's triangles by swatch; none for a textured piece. */
  readonly groups: readonly LoadedPieceGroup[];
  readonly triangles: number;
  /** Metres, glTF axes: [minX, minY, minZ, maxX, maxY, maxZ]. */
  readonly bounds: readonly [number, number, number, number, number, number];
  /** A textured piece's levels, drawn instanced; absent for a palette piece. */
  readonly textured?: LoadedTexturedLevels;
}

export interface PackPieces {
  /** The piece a module's file is, as that module's manifest colours it. */
  get(module: ResolvedModule, file: StylePackFile): LoadedPiece | undefined;
  readonly count: number;
  /** Bytes the textured pieces' images take decoded, RGBA8 before mipmaps. */
  readonly decodedTextureBytes: number;
  dispose(): void;
}


/** How the caller fetches a file a manifest names. */
export type PieceBytes = (file: StylePackFile) => Promise<Uint8Array<ArrayBuffer>>;

const hex = (digest: ArrayBuffer): string => [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');

const keyOf = (module: ResolvedModule, file: StylePackFile): string => `${String(module.stated)}:${file.sha256}`;

/** A textured piece's levels, read, with every image decoded and named by its digest. */
export interface FetchedTexturedLevels {
  readonly lod0: TexturedPiece;
  readonly lod1: TexturedPiece | null;
  /** Each level's images' digests, in the order of its images. */
  readonly lod0Images: readonly string[];
  readonly lod1Images: readonly string[];
}

/** A piece fetched, held to its manifest and read: its triangles by swatch key, not yet uploaded. */
export interface FetchedPiece {
  readonly groups: readonly Omit<LoadedPieceGroup, 'mesh'>[];
  readonly triangles: number;
  readonly bounds: LoadedPiece['bounds'];
  readonly textured?: FetchedTexturedLevels;
}

/** A pack's pieces fetched, keyed by the manifest that stated each and its digest. */
export interface FetchedPieces {
  readonly pieces: ReadonlyMap<string, FetchedPiece>;
  /** Every textured piece's decoded images by digest; empty for a pack of palette pieces. */
  readonly pictures?: ReadonlyMap<string, DecodedPicture>;
}

/**
 * Fetch and read the pieces of the modules `roles` names (every variant's level-of-detail 0 file),
 * in the resolved `pack`, without a renderer. `table` is the 256 values of
 * `exulanica.srgb8-linear16/v1`. Every piece is checked before any is kept.
 */
export async function fetchPackPieces(
  pack: ResolvedStylePack,
  roles: readonly string[],
  table: readonly number[],
  bytesOf: PieceBytes,
  decode: DecodePicture = decodeBrowserPicture,
): Promise<FetchedPieces> {
  const wanted = new Map<string, { module: ResolvedModule; file: StylePackFile }>();
  for (const role of roles) {
    const module = pack.modules[role];
    if (module === undefined) continue;
    for (const variant of module.variants) {
      const file = module.files.get(variant.file)!;
      wanted.set(keyOf(module, file), { module, file });
    }
  }
  const pieces = new Map<string, FetchedPiece>();
  const pictures = new Map<string, Promise<DecodedPicture>>();
  const held = async (file: StylePackFile): Promise<Uint8Array<ArrayBuffer>> => {
    const bytes = await bytesOf(file);
    if (bytes.byteLength !== file.bytes) throw new PackPieceRefusal(`${file.path} is ${String(bytes.byteLength)} bytes; its manifest states ${String(file.bytes)}`);
    const digest = hex(await crypto.subtle.digest('SHA-256', bytes));
    if (digest !== file.sha256) throw new PackPieceRefusal(`${file.path} is not the bytes its manifest names`);
    return bytes;
  };
  /** Each image of a textured level decoded once by digest; the level's digests in image order. */
  const decoded = async (piece: TexturedPiece, path: string): Promise<string[]> => Promise.all(piece.images.map(async (image) => {
    const digest = hex(await crypto.subtle.digest('SHA-256', image.bytes as Uint8Array<ArrayBuffer>));
    if (!pictures.has(digest)) {
      pictures.set(digest, decode(image.bytes, image.mediaType).catch(() => {
        throw new PackPieceRefusal(`${path} holds a picture the page cannot decode`);
      }));
    }
    return digest;
  }));
  const texturedOf = (bytes: Uint8Array, path: string): TexturedPiece => {
    try {
      return readTexturedPiece(bytes);
    } catch (error) {
      throw new PackPieceRefusal(`${path}: ${(error as Error).message}`);
    }
  };
  const settled = await Promise.allSettled([...wanted].map(async ([key, { module, file }]) => {
    const bytes = await held(file);
    if (isTexturedPiece(bytes)) {
      const lod0 = texturedOf(bytes, file.path);
      // The second level of the variant this file is the first level of, where it states one.
      const variant = module.variants.find((one) => one.file === file.path);
      const second = variant?.lod1 === null || variant?.lod1 === undefined ? undefined : module.files.get(variant.lod1);
      const secondBytes = second === undefined ? null : await held(second);
      if (second !== undefined && secondBytes !== null && !isTexturedPiece(secondBytes)) {
        throw new PackPieceRefusal(`${second.path} is a textured piece's second level, and is not textured`);
      }
      const lod1 = second === undefined || secondBytes === null ? null : texturedOf(secondBytes, second.path);
      const [lod0Images, lod1Images] = await Promise.all([decoded(lod0, file.path), lod1 === null ? [] : decoded(lod1, second!.path)]);
      pieces.set(key, { groups: [], triangles: lod0.triangles, bounds: lod0.bounds, textured: { lod0, lod1, lod0Images, lod1Images } });
      return;
    }
    const piece = readStylePiece(bytes, table);
    const groups = piece.groups.map((group) => {
      const swatch = swatchKeyOf(pack, module, group.srgb8);
      if (swatch === null) throw new PackPieceRefusal(`${file.path} is coloured ${group.srgb8.join(',')}, no swatch of its pack`);
      return { swatch, positions: group.positions, normals: group.normals, indices: group.indices };
    });
    pieces.set(key, { groups, triangles: piece.triangles, bounds: piece.bounds });
  }));
  const failed = settled.find((outcome): outcome is PromiseRejectedResult => outcome.status === 'rejected');
  if (failed !== undefined) throw failed.reason;
  const ready = new Map<string, DecodedPicture>();
  for (const [digest, picture] of pictures) ready.set(digest, await picture);
  return pictures.size === 0 ? { pieces } : { pieces, pictures: ready };
}

const ADDRESS: Readonly<Record<TexturedWrap, number>> = Object.freeze({ repeat: pc.ADDRESS_REPEAT, clamp: pc.ADDRESS_CLAMP_TO_EDGE, mirror: pc.ADDRESS_MIRRORED_REPEAT });

/** One textured level's primitives uploaded, its materials made, its textures shared by `texture`. */
function uploadTextured(
  device: pc.GraphicsDevice,
  piece: TexturedPiece,
  images: readonly string[],
  texture: (digest: string, srgb: boolean, wrapS: TexturedWrap, wrapT: TexturedWrap) => pc.Texture,
  shading: RenderShading | null,
  name: string,
  made: { meshes: pc.Mesh[]; materials: pc.StandardMaterial[] },
): LoadedTexturedPrimitive[] {
  const materials = piece.materials.map((stated, k) => {
    const material = new pc.StandardMaterial();
    material.name = `${name}:material:${String(k)}`;
    const colour = texture(images[stated.baseColour.image]!, true, stated.baseColour.wrapS, stated.baseColour.wrapT);
    // As the engine's own glTF reader makes a material: roughness as inverted gloss, the base colour
    // factor in gamma, the colour's alpha cut out under the cutoff and never blended.
    material.useMetalness = true;
    material.glossInvert = true;
    material.gloss = stated.roughness;
    material.metalness = stated.metalness;
    material.diffuse.set(stated.baseColourFactor[0], stated.baseColourFactor[1], stated.baseColourFactor[2]).gamma();
    material.diffuseMap = colour;
    if (stated.alphaCutoff !== null) {
      material.opacityMap = colour;
      material.opacityMapChannel = 'a';
      material.alphaTest = stated.alphaCutoff;
    }
    material.blendType = pc.BLEND_NONE;
    if (stated.normal !== null) {
      material.normalMap = texture(images[stated.normal.image]!, false, stated.normal.wrapS, stated.normal.wrapT);
      material.bumpiness = stated.normal.scale;
    }
    material.twoSidedLighting = stated.doubleSided;
    material.cull = stated.doubleSided ? pc.CULLFACE_NONE : pc.CULLFACE_BACK;
    if (shading !== null) applyShading(material, shading);
    material.update();
    made.materials.push(material);
    return material;
  });
  return piece.primitives.map((primitive) => {
    const mesh = new pc.Mesh(device);
    mesh.setPositions(primitive.positions);
    mesh.setNormals(primitive.normals);
    mesh.setUvs(0, primitive.uvs);
    mesh.setIndices(primitive.indices);
    mesh.update(pc.PRIMITIVE_TRIANGLES);
    mesh.incRefCount();
    made.meshes.push(mesh);
    return { mesh, material: materials[primitive.material]!, positions: primitive.positions, normals: primitive.normals, indices: primitive.indices };
  });
}

/**
 * Upload fetched pieces as one mesh per swatch each, and each textured piece's levels with their
 * materials in `shading` (none: the engine's own) and their textures. The library owns them all until
 * `dispose`.
 */
export function uploadPackPieces(device: pc.GraphicsDevice, fetched: FetchedPieces, shading: RenderShading | null = null): PackPieces {
  const loaded = new Map<string, LoadedPiece>();
  const textures = new Map<string, pc.Texture>();
  const made = { meshes: [] as pc.Mesh[], materials: [] as pc.StandardMaterial[] };
  let decodedTextureBytes = 0;
  const texture = (digest: string, srgb: boolean, wrapS: TexturedWrap, wrapT: TexturedWrap): pc.Texture => {
    const key = `${digest}:${srgb ? 'srgb' : 'linear'}:${wrapS}:${wrapT}`;
    let found = textures.get(key);
    if (found === undefined) {
      const picture = fetched.pictures?.get(digest);
      if (picture === undefined) throw new PackPieceRefusal(`a textured piece's picture ${digest} was not decoded`);
      found = new pc.Texture(device, {
        name: `style-pack:texture:${digest.slice(0, 12)}:${srgb ? 'srgb' : 'linear'}`,
        width: picture.width,
        height: picture.height,
        format: srgb ? pc.PIXELFORMAT_SRGBA8 : pc.PIXELFORMAT_RGBA8,
        mipmaps: true,
        minFilter: pc.FILTER_LINEAR_MIPMAP_LINEAR,
        magFilter: pc.FILTER_LINEAR,
        addressU: ADDRESS[wrapS],
        addressV: ADDRESS[wrapT],
        anisotropy: Math.min(8, device.maxAnisotropy),
        levels: [picture.rgba],
      });
      decodedTextureBytes += picture.width * picture.height * 4;
      textures.set(key, found);
    }
    return found;
  };
  for (const [key, piece] of fetched.pieces) {
    if (piece.textured !== undefined) {
      const { lod0, lod1, lod0Images, lod1Images } = piece.textured;
      const name = `style-pack:textured:${key}`;
      loaded.set(key, {
        groups: [],
        triangles: piece.triangles,
        bounds: piece.bounds,
        textured: {
          lod0: uploadTextured(device, lod0, lod0Images, texture, shading, `${name}:lod0`, made),
          lod1: lod1 === null ? null : uploadTextured(device, lod1, lod1Images, texture, shading, `${name}:lod1`, made),
        },
      });
      continue;
    }
    const groups = piece.groups.map((group) => {
      const mesh = new pc.Mesh(device);
      mesh.setPositions(group.positions);
      mesh.setNormals(group.normals);
      mesh.setIndices(group.indices);
      mesh.update(pc.PRIMITIVE_TRIANGLES);
      // The library holds every mesh, so a dressing's instances going away never destroys one.
      mesh.incRefCount();
      return { ...group, mesh };
    });
    loaded.set(key, { groups, triangles: piece.triangles, bounds: piece.bounds });
  }
  let disposed = false;
  return {
    get: (module, file) => loaded.get(keyOf(module, file)),
    get count() {
      return loaded.size;
    },
    get decodedTextureBytes() {
      return decodedTextureBytes;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      for (const piece of loaded.values()) {
        for (const group of piece.groups) {
          group.mesh.decRefCount();
          group.mesh.destroy();
        }
      }
      for (const mesh of made.meshes) {
        mesh.decRefCount();
        mesh.destroy();
      }
      for (const material of made.materials) material.destroy();
      for (const one of textures.values()) one.destroy();
      made.meshes.length = 0;
      made.materials.length = 0;
      textures.clear();
      loaded.clear();
    },
  };
}

/** Fetch, read and upload the pieces of the modules `roles` names, as `fetchPackPieces` then `uploadPackPieces`. */
export async function loadPackPieces(
  device: pc.GraphicsDevice,
  pack: ResolvedStylePack,
  roles: readonly string[],
  table: readonly number[],
  bytesOf: PieceBytes,
  decode: DecodePicture = decodeBrowserPicture,
  shading: RenderShading | null = null,
): Promise<PackPieces> {
  return uploadPackPieces(device, await fetchPackPieces(pack, roles, table, bytesOf, decode), shading);
}
