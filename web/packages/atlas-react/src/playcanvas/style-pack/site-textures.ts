import * as pc from 'playcanvas';
import { TEXTURE_SET_PROFILE_V2 } from '@exulanica/atlas-core';
import type { DecodedTextureSet, ResolvedStylePack, StylePackFile, StylePackSwatch, TextureSetChannel, TextureSetManifestEntry } from '@exulanica/atlas-core';
import type { SiteSlot } from '../generated-site/site-drawing.js';
import type { TileLook } from '../generated-tile/look.js';
import {
  castsShadow, drawBucket, setTangents, surfaceUv, unavailableUv,
  TileTextureUploads, type PreparedTextureSet, type TileTextureResolution,
} from '../generated-tile/texture-materials.js';
import { applyUp } from './swatch-material.js';

const PLACEMENT = { textureSetId: '', repeatSizeMillionths: 1_000_000, rotationUrad: 0, offsetUMm: 0, offsetVMm: 0 };

/** Millimetres along the declared frame; thickness faces use a nondegenerate physical projection. */
export function siteSurfaceMm(slot: SiteSlot, pointMm: readonly number[], normal: readonly number[]): readonly [number, number] {
  const angle = slot.yawQuarterTurns * Math.PI / 2;
  const across = [Math.cos(angle), -Math.sin(angle), 0];
  const forward = [Math.sin(angle), Math.cos(angle), 0];
  const dot = (a: readonly number[], b: readonly number[]): number => a.reduce((sum, value, i) => sum + value * b[i]!, 0);
  const delta = pointMm.map((value, i) => value - slot.positionMm[i]!);
  const horizontal = Math.abs(normal[2]!) > 0.5;
  if (slot.uvFrame !== undefined) {
    const frame = slot.uvFrame;
    const u = frame.uAxisMm.map(value => value / 1000), v = frame.vAxisMm.map(value => value / 1000);
    if (Math.abs(dot(normal, u)) < 0.5 && Math.abs(dot(normal, v)) < 0.5) {
      const offset = pointMm.map((value, i) => value - frame.originMm[i]!);
      return [dot(offset, u), v[2]! === 0 ? dot(offset, v) : -dot(offset, v)];
    }
  }
  if (horizontal || slot.primitive === 'plane' || slot.family === 'roof') {
    return [dot(delta, across) + slot.boxMm[0] / 2, dot(delta, forward) + slot.boxMm[1] / 2];
  }
  const side = Math.abs(dot(normal, across)) > 0.5;
  return [side ? dot(delta, forward) + slot.boxMm[1] / 2 : dot(delta, across) + slot.boxMm[0] / 2,
    slot.boxMm[2] - delta[2]!];
}

/** A copy of the drawn mesh with physical UVs. Positions, indices and bounds are unchanged. */
export function siteTextureMesh(device: pc.GraphicsDevice, original: pc.Mesh, slot: SiteSlot, resolution: TileTextureResolution, look: TileLook, node: pc.GraphNode, root: pc.GraphNode): pc.Mesh {
  const positions: number[] = [], normals: number[] = [], indices: number[] = [], uvs: number[] = [];
  original.getPositions(positions);
  original.getNormals(normals);
  original.getIndices(indices);
  const matrix = new pc.Mat4().mul2(root.getWorldTransform().clone().invert(), node.getWorldTransform());
  const point = new pc.Vec3(), direction = new pc.Vec3();
  for (let i = 0; i < positions.length; i += 3) {
    matrix.transformPoint(point.set(positions[i]!, positions[i + 1]!, positions[i + 2]!), point);
    matrix.transformVector(direction.set(normals[i]!, normals[i + 1]!, normals[i + 2]!), direction).normalize();
    const [s, t] = siteSurfaceMm(slot, [point.x * 1000, -point.z * 1000, point.y * 1000], [direction.x, -direction.z, direction.y]);
    uvs.push(...(resolution.state === 'available'
      ? surfaceUv(s, t, PLACEMENT, resolution.set.entry)
      : unavailableUv(s, t, look, slot.primitive === 'plane' ? 'horizontal' : 'vertical')));
  }
  const mesh = new pc.Mesh(device);
  mesh.setPositions(positions);
  mesh.setNormals(normals);
  mesh.setUvs(0, uvs);
  mesh.setVertexStream(pc.SEMANTIC_TANGENT, setTangents(positions, normals, uvs, indices), 4);
  mesh.setIndices(indices);
  mesh.update(pc.PRIMITIVE_TRIANGLES);
  return mesh;
}

/** A picture decoded to its size and its texels, four bytes each, row 0 first. */
export interface DecodedPicture {
  readonly width: number;
  readonly height: number;
  readonly rgba: Uint8Array;
}

/** Decodes one picture of a pack: its bytes and the media type its manifest states. */
export type DecodePicture = (bytes: Uint8Array, mediaType: string) => Promise<DecodedPicture>;

/**
 * The browser's decode: no colour conversion and no premultiplied alpha, so a normal or roughness
 * map keeps the bytes it was made with and a colour map its sRGB bytes.
 */
export const decodeBrowserPicture: DecodePicture = async (bytes, mediaType) => {
  const bitmap = await createImageBitmap(new Blob([bytes as Uint8Array<ArrayBuffer>], { type: mediaType }), { colorSpaceConversion: 'none', premultiplyAlpha: 'none' });
  try {
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
    const context = canvas.getContext('2d');
    if (context === null) throw new Error('This browser cannot read a picture');
    context.drawImage(bitmap, 0, 0);
    const data = context.getImageData(0, 0, bitmap.width, bitmap.height).data;
    return { width: bitmap.width, height: bitmap.height, rgba: new Uint8Array(data.buffer, data.byteOffset, data.byteLength) };
  } finally {
    bitmap.close();
  }
};

/** The id a pack's own texture is drawn under, apart from every library set's. */
export const packTextureSetId = (key: string): string => `pack:${key}`;

const PACK_CHANNELS = {
  base_color: { map: 'base_color', components: 3, holds: ['red', 'green', 'blue'], srgb: true },
  normal: { map: 'normal', components: 3, holds: ['normal_x', 'normal_y', 'normal_z'], srgb: false },
  orm: { map: 'orm', components: 3, holds: ['occlusion', 'roughness', 'metalness'], srgb: false },
} as const satisfies Record<string, TextureSetChannel>;

/**
 * A texture a pack carries, fetched and decoded into the set the library's draw takes: its colour
 * map, its normal map if it has one, and its roughness as an unoccluded, non-metal surface map
 * (fully rough where it states no roughness map), repeating over its stated extent. The fetcher holds
 * each picture to its digest; this holds it to its size and the maps to one size, else refuses.
 */
export async function preparePackTexture(
  pack: ResolvedStylePack,
  key: string,
  bytesOf: (file: StylePackFile) => Promise<Uint8Array>,
  decode: DecodePicture = decodeBrowserPicture,
): Promise<PreparedTextureSet> {
  const setId = packTextureSetId(key);
  const resolved = pack.textures.get(key);
  if (resolved === undefined) return { state: 'refused', setId, reason: `The pack carries no texture ${key}` };
  try {
    let transferredBytes = 0;
    const read = async (path: string): Promise<DecodedPicture> => {
      const file = resolved.files.get(path);
      if (file === undefined) throw new Error(`${path} is not a file of its pack`);
      const bytes = await bytesOf(file);
      if (bytes.byteLength !== file.bytes) throw new Error(`${path} is ${String(bytes.byteLength)} bytes; its manifest states ${String(file.bytes)}`);
      transferredBytes += bytes.byteLength;
      return decode(bytes, file.media_type);
    };
    const { texture } = resolved;
    const colour = await read(texture.colour);
    const normal = texture.normal === null ? null : await read(texture.normal);
    const roughness = texture.roughness === null ? null : await read(texture.roughness);
    const { width, height } = colour;
    for (const map of [normal, roughness]) {
      if (map !== null && (map.width !== width || map.height !== height)) throw new Error(`its maps are not one size`);
    }
    const texels = width * height;
    const rgb = (picture: DecodedPicture): Uint8Array => {
      const out = new Uint8Array(texels * 3);
      for (let i = 0; i < texels; i += 1) {
        out[i * 3] = picture.rgba[i * 4]!; out[i * 3 + 1] = picture.rgba[i * 4 + 1]!; out[i * 3 + 2] = picture.rgba[i * 4 + 2]!;
      }
      return out;
    };
    const orm = new Uint8Array(texels * 3);
    for (let i = 0; i < texels; i += 1) {
      orm[i * 3] = 255;
      orm[i * 3 + 1] = roughness === null ? 255 : roughness.rgba[i * 4]!;
      orm[i * 3 + 2] = 0;
    }
    const channels: readonly TextureSetChannel[] = [PACK_CHANNELS.base_color, ...(normal === null ? [] : [PACK_CHANNELS.normal]), PACK_CHANNELS.orm];
    const colourFile = resolved.files.get(texture.colour)!;
    const entry: TextureSetManifestEntry = {
      setId, version: 1, contentSha256: colourFile.sha256, byteSize: transferredBytes, width, height, channels,
      extentUMm: texture.extent_mm[0], extentVMm: texture.extent_mm[1],
      licenceId: pack.chain[0]!.licence.id, licenceSha256: '', containerProfile: TEXTURE_SET_PROFILE_V2, materialClass: 'opaque',
    };
    const set: DecodedTextureSet = {
      entry, profile: TEXTURE_SET_PROFILE_V2, materialClass: 'opaque', makerKind: 'model', classParameters: { materialClass: 'opaque' },
      surface: 'horizontal', title: key, heightRangeMm: null, channels,
      maps: { base_color: rgb(colour), ...(normal === null ? {} : { normal: rgb(normal) }), orm },
    };
    return { state: 'decoded', setId, set, transferredBytes };
  } catch (error) {
    return { state: 'refused', setId, reason: `Texture ${key} could not be read: ${error instanceof Error ? error.message : String(error)}` };
  }
}

export interface SiteTextureMetrics {
  readonly transferredBytes: number;
  readonly decodedTextureBytes: number;
  readonly unavailableSurfaces: number;
}

/** Owns only the site dressing's uploads and mesh copies; never alters canonical geometry or walking. */
export class SiteTextures {
  readonly uploads: TileTextureUploads;
  readonly #restored: (() => void)[] = [];
  readonly #materials: pc.StandardMaterial[] = [];
  readonly #resolutions = new Map<string, TileTextureResolution>();
  #unavailable = 0;
  #disposed = false;

  constructor(private readonly device: pc.GraphicsDevice, private readonly look: TileLook,
    private readonly prepared: ReadonlyMap<string, PreparedTextureSet> = new Map()) {
    this.uploads = new TileTextureUploads(device, look);
  }

  /** Wear a texture set; returns whether what it now wears needs the scene's colour copied, which none does. */
  wear(instance: pc.MeshInstance, slot: SiteSlot, setId: string, up: StylePackSwatch | null, root: pc.GraphNode): boolean {
    let resolution = this.#resolutions.get(setId);
    if (resolution === undefined) {
      resolution = this.uploads.adopt(this.prepared.get(setId) ?? { state: 'refused', setId, reason: `No prepared texture set ${setId}` });
      this.#resolutions.set(setId, resolution);
    }
    const original = instance.mesh, material = instance.material, shadow = instance.castShadow, bucket = instance.drawBucket;
    const mesh = siteTextureMesh(this.device, original, slot, resolution, this.look, instance.node, root);
    instance.mesh = mesh;
    let worn = resolution.material;
    if (up !== null && resolution.state === 'available') {
      worn = worn.clone();
      applyUp(worn, up.srgb8);
      worn.update();
      this.#materials.push(worn);
    }
    instance.material = worn;
    if (resolution.state === 'available') {
      instance.castShadow = shadow && castsShadow(resolution.set);
      const nextBucket = drawBucket(resolution.set);
      if (nextBucket !== null) instance.drawBucket = nextBucket;
    } else this.#unavailable += 1;
    this.#restored.push(() => {
      instance.mesh = original; instance.material = material; instance.castShadow = shadow; instance.drawBucket = bucket;
      mesh.destroy();
    });
    // Glazing is blended over what lies behind it and needs no copy of the scene's colour.
    return false;
  }

  metrics(): SiteTextureMetrics {
    return { transferredBytes: this.uploads.transferredBytes, decodedTextureBytes: this.uploads.decodedTextureBytes, unavailableSurfaces: this.#unavailable };
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    for (const restore of this.#restored.reverse()) restore();
    for (const material of this.#materials) material.destroy();
    this.uploads.destroy();
  }
}
