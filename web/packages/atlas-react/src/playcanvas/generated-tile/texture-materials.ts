import * as pc from 'playcanvas';
import {
  TextureSetRefusal,
  decodeTextureSet,
  type DecodedTextureSet,
  type TextureMapName,
  type TextureSetDigest,
  type TextureSetManifest,
  type TextureSetManifestEntry,
} from '@exulanica/atlas-core';
import { coveragePreservingMips } from './cutout-coverage.js';
import type { TileLook } from './look.js';
import { createUnavailableMaterial } from './unavailable-surface.js';

/**
 * Physically based materials from baked texture sets.
 *
 * ONE MATERIAL PER SET, AND THE SCALE IS IN THE VERTICES. A set's maps are uploaded once and shared
 * by every surface that names it. What differs between two surfaces of the same set, their size and
 * the record's own scale and rotation, is resolved into each vertex's UV by {@link surfaceUv}, so a
 * street with fourteen brick buildings is one brick draw, not fourteen.
 *
 * THE UV RULE. A surface coordinate is millimetres on the surface, measured the way the set's
 * header says its placement runs: for a vertical set, `s` along the wall and `t` downward; for a
 * horizontal set, `s` along the run and `t` across it. The texture repeats once per physical extent,
 * so a wall `w` mm wide repeats the tile `w / extent_u_mm` times at a record size of one. The
 * record's size factor multiplies the repeat LENGTH (2,000,000 draws the set twice as large), and
 * its rotation and offsets place the texture on the surface, all in millimetres before dividing by
 * the repeat length, so a non-square set (the kerb is 1800 by 450 mm) keeps its proportions under
 * rotation. There is no other scale anywhere, and no constant that guesses one.
 *
 * WHAT A SET BECOMES. A set is drawn by its material class and by nothing else. This runtime draws
 * `opaque`, `cutout` and `glazing` sets, of either container profile; `decal` is the stated
 * unavailable surface with the reason {@link undrawnClassReason} gives, and glazing is never drawn as
 * opaque. For an opaque set, base_color is uploaded as sRGB; normal, orm and height as linear
 * bytes. A glazing set is metallic-roughness with metalness 0 plus glTF's transmission and index of
 * refraction: it reflects the environment and the sun by angle, transmits what the scene drew behind
 * it (a copy the environment keeps when glazing is drawn), tinted by its base colour and blurred by
 * its roughness, lights the film its maps carry where transmission is below full, writes no depth and
 * casts no shadow. The film its class object declares is for laying more film by position, which this
 * runtime does not do yet. A cutout set is drawn as glTF's `alphaMode: MASK` with `doubleSided: true`: its
 * base_color_coverage map is uploaded as sRGB colour with linear coverage, every mip level built by
 * `coveragePreservingMips` so the share of covered texels stays the set's `coverage_permille` at any
 * distance; each sample is tested against `alpha_cutoff / 255` and nothing is blended; depth is
 * written; the shadow pass applies the same test; and both faces are lit, a back face with its normal
 * reversed. A two-component normal (a procedural v2 set) gets its z rebuilt where it is uploaded,
 * z = sqrt(max(0, 1 - x * x - y * y)), in arithmetic that enters no digest; a model-made set that
 * produced no normal map draws without one. The orm map drives three material inputs from its three
 * channels: occlusion (red), roughness (green, inverted into PlayCanvas's gloss) and metalness (blue).
 * The height map is uploaded only when the look turns parallax on and the set ships one, so an unused
 * map costs no memory.
 *
 * A SET THAT DOES NOT RESOLVE draws the stated unavailable surface, with the refusal's reason kept
 * for whoever reports it. There is no default set, no flat colour and no retry with a looser check.
 */

/**
 * The material record fields a renderer reads. Everything else in the record is world data.
 *
 * Read as the city vocabulary states them for surface_material v2 (final wording, 2026-09-16):
 * `repeat_size_millionths`, `uv_rotation_urad`, `uv_offset_u_mm` and `uv_offset_v_mm`.
 */
export interface TileMaterialReference {
  readonly textureSetId: string;
  /** One repeat covers `extent * repeatSizeMillionths / 10^6` mm: 2,000,000 draws the set twice as large. */
  readonly repeatSizeMillionths: number;
  /** Theta in microradians; a positive theta turns +s toward +t. */
  readonly rotationUrad: number;
  /** Millimetres along the texture's own u and v axes, applied after the rotation. */
  readonly offsetUMm: number;
  readonly offsetVMm: number;
}

export type TileTextureResolution =
  | { readonly state: 'available'; readonly setId: string; readonly material: pc.StandardMaterial; readonly set: DecodedTextureSet }
  | { readonly state: 'unavailable'; readonly setId: string; readonly material: pc.StandardMaterial; readonly reason: string };

const MILLIONTHS = 1_000_000;

/**
 * UV for a surface point `s`, `t` millimetres from the surface's own origin. THE ONE PLACE the
 * record's texture placement is interpreted; a change to its meaning changes only this function.
 *
 * Exactly the city vocabulary's formula, with theta the record's rotation (a positive theta turns
 * +s toward +t) and repeat the set's physical extent times the record's size factor:
 *
 *   u = (cos(theta) * s - sin(theta) * t + offset_u) / repeat_u
 *   v = (sin(theta) * s + cos(theta) * t + offset_v) / repeat_v
 *
 * Returns a float pair for the render payload only. Nothing digested reads it.
 */
export function surfaceUv(
  sMm: number,
  tMm: number,
  reference: TileMaterialReference,
  entry: Pick<TextureSetManifestEntry, 'extentUMm' | 'extentVMm'>,
): readonly [number, number] {
  const size = reference.repeatSizeMillionths / MILLIONTHS;
  const angle = reference.rotationUrad / MILLIONTHS;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return [
    (cos * sMm - sin * tMm + reference.offsetUMm) / (entry.extentUMm * size),
    (sin * sMm + cos * tMm + reference.offsetVMm) / (entry.extentVMm * size),
  ];
}

/**
 * UV for the unavailable pattern, which repeats once per `look.unavailable.tileMm`. The word in it
 * reads upright: on a vertical face `t` already points down the image; on a horizontal one `t` runs
 * away from a viewer facing along it, so the image's top is laid that way.
 */
export function unavailableUv(
  sMm: number,
  tMm: number,
  look: TileLook,
  orientation: 'vertical' | 'horizontal' = 'vertical',
): readonly [number, number] {
  const size = look.unavailable.tileMm;
  return [sMm / size, (orientation === 'horizontal' ? -tMm : tMm) / size];
}

/**
 * Tangents for normal-mapped geometry, in the sets' convention.
 *
 * PlayCanvas derives its bitangent toward increasing v. A set's normal map says +Y points toward
 * row 0, which is decreasing v, so the handedness is flipped here once. The rendered check in the
 * test bench compares shading against the height map's own slope to prove the sign.
 */
export function setTangents(positions: number[], normals: number[], uvs: number[], indices: number[]): number[] {
  const tangents = pc.calculateTangents(positions, normals, uvs, indices);
  for (let index = 3; index < tangents.length; index += 4) tangents[index] = -tangents[index]!;
  return tangents;
}

function rgbToRgba(rgb: Uint8Array): Uint8Array {
  const texels = rgb.length / 3;
  const out = new Uint8Array(texels * 4);
  for (let texel = 0, from = 0, to = 0; texel < texels; texel += 1, from += 3, to += 4) {
    out[to] = rgb[from]!;
    out[to + 1] = rgb[from + 1]!;
    out[to + 2] = rgb[from + 2]!;
    out[to + 3] = 255;
  }
  return out;
}

/** Why a decoded set is not drawn by this runtime, or null when its class is one it draws. */
export function undrawnClassReason(set: Pick<DecodedTextureSet, 'materialClass'>): string | null {
  return set.materialClass === 'decal' ? `material class ${set.materialClass} is not drawn by this runtime` : null;
}

/** Whether surfaces of this class cast shadows: glazing casts none. */
export function castsShadow(set: Pick<DecodedTextureSet, 'materialClass'>): boolean {
  return set.materialClass !== 'glazing';
}

/** The transmission and roughness map as RGBA: transmission in red, roughness in green. */
export function transmissionRoughnessTexels(bytes: Uint8Array): Uint8Array {
  const texels = bytes.length / 2;
  const out = new Uint8Array(texels * 4);
  for (let texel = 0; texel < texels; texel += 1) {
    out[texel * 4] = bytes[texel * 2]!;
    out[texel * 4 + 1] = bytes[texel * 2 + 1]!;
    out[texel * 4 + 3] = 255;
  }
  return out;
}

/**
 * The normal map as RGBA bytes: a three-component map is widened as stored; a two-component map gets
 * its z rebuilt from x and y, since a tangent-space normal points out of its surface. The renderer
 * normalises what it samples.
 */
export function normalTexels(set: DecodedTextureSet): Uint8Array | null {
  const normal = set.maps.normal;
  if (normal === undefined) return null;
  const components = set.channels.find((channel) => channel.map === 'normal')!.components;
  if (components === 3) return rgbToRgba(normal);
  const texels = normal.length / 2;
  const out = new Uint8Array(texels * 4);
  for (let texel = 0; texel < texels; texel += 1) {
    const x = normal[texel * 2]!;
    const y = normal[texel * 2 + 1]!;
    const nx = (2 * x) / 255 - 1;
    const ny = (2 * y) / 255 - 1;
    const nz = Math.sqrt(Math.max(0, 1 - nx * nx - ny * ny));
    out[texel * 4] = x;
    out[texel * 4 + 1] = y;
    out[texel * 4 + 2] = Math.round(((nz + 1) / 2) * 255);
    out[texel * 4 + 3] = 255;
  }
  return out;
}

/** Transmission inputs PlayCanvas's StandardMaterial has at runtime and its type declarations leave out. */
type TransmissiveMaterial = pc.StandardMaterial & {
  refractionMap: pc.Texture | null;
  refractionMapChannel: string;
  useDynamicRefraction: boolean;
  thickness: number;
};

/** A map the upload needs, which the set's layout must hold. */
function requiredMap(set: DecodedTextureSet, name: TextureMapName): Uint8Array {
  const bytes = set.maps[name];
  if (bytes === undefined) throw new Error(`Texture set ${set.entry.setId} holds no ${name} map`);
  return bytes;
}

/** Resident bytes of a mipmapped texture: the base level and a third again for the chain. */
function mippedBytes(width: number, height: number, bytesPerTexel: number): number {
  let total = 0;
  for (let w = width, h = height; ; w = Math.max(1, w >> 1), h = Math.max(1, h >> 1)) {
    total += w * h * bytesPerTexel;
    if (w === 1 && h === 1) return total;
  }
}

interface Uploaded {
  readonly set: DecodedTextureSet;
  readonly material: pc.StandardMaterial;
  readonly textures: readonly pc.Texture[];
  readonly residentBytes: number;
}

/** A set fetched and held to its pin, or the reason it was not. No device is needed for either. */
export type PreparedTextureSet =
  | { readonly state: 'decoded'; readonly setId: string; readonly set: DecodedTextureSet; readonly transferredBytes: number }
  | { readonly state: 'refused'; readonly setId: string; readonly reason: string };

/**
 * Fetch one pinned set and verify it against the manifest. Separate from the upload so a tile can
 * have every set it names checked before the renderer exists, and draw complete on its first frame.
 */
export async function prepareTextureSet(
  manifest: TextureSetManifest,
  setId: string,
  /** Fetch a pinned set's bytes. The reader verifies them; the fetcher need not. */
  fetchSet: (entry: TextureSetManifestEntry) => Promise<Uint8Array>,
  digest?: TextureSetDigest | null,
): Promise<PreparedTextureSet> {
  const entry = manifest.byId.get(setId);
  if (entry === undefined) {
    return { state: 'refused', setId, reason: `Texture set ${setId} is not pinned by the texture manifest.` };
  }
  try {
    const bytes = await fetchSet(entry);
    const set = digest === undefined ? await decodeTextureSet(bytes, entry) : await decodeTextureSet(bytes, entry, digest);
    return { state: 'decoded', setId, set, transferredBytes: bytes.byteLength };
  } catch (error) {
    if (error instanceof TextureSetRefusal) return { state: 'refused', setId, reason: `Texture set ${setId} refused: ${error.message}` };
    return { state: 'refused', setId, reason: `Texture set ${setId} could not be read: ${error instanceof Error ? error.message : String(error)}` };
  }
}

/** Uploads of prepared sets, and the unavailable surface. Synchronous: no fetch, no digest. */
export class TileTextureUploads {
  private readonly settled = new Map<string, Uploaded>();
  private unavailable: ReturnType<typeof createUnavailableMaterial> | null = null;
  protected destroyed = false;
  private transferred = 0;

  constructor(
    private readonly device: pc.GraphicsDevice,
    private readonly look: TileLook,
  ) {}

  /** The unlit pattern every unresolved surface shares. */
  get unavailableMaterial(): pc.StandardMaterial {
    this.unavailable ??= createUnavailableMaterial(this.device, this.look);
    return this.unavailable.material;
  }

  /** GPU bytes held by uploaded sets, mip chains included. The budget's decoded texture figure. */
  get decodedTextureBytes(): number {
    let total = 0;
    for (const upload of this.settled.values()) total += upload.residentBytes;
    return total;
  }

  /** Container bytes of every set uploaded here. */
  get transferredBytes(): number {
    return this.transferred;
  }

  get resolvedSetIds(): readonly string[] {
    return [...this.settled.keys()].sort();
  }

  /** Upload a set already prepared, synchronously, once per set. */
  adopt(prepared: PreparedTextureSet): TileTextureResolution {
    if (this.destroyed) throw new Error('The texture library has been destroyed');
    if (prepared.state === 'refused') {
      return { state: 'unavailable', setId: prepared.setId, material: this.unavailableMaterial, reason: prepared.reason };
    }
    const undrawn = undrawnClassReason(prepared.set);
    if (undrawn !== null) {
      return { state: 'unavailable', setId: prepared.setId, material: this.unavailableMaterial, reason: undrawn };
    }
    let uploaded = this.settled.get(prepared.setId);
    if (uploaded === undefined) {
      uploaded = this.upload(prepared.set);
      this.settled.set(prepared.setId, uploaded);
      this.transferred += prepared.transferredBytes;
    }
    return { state: 'available', setId: prepared.setId, material: uploaded.material, set: uploaded.set };
  }

  private upload(set: DecodedTextureSet): Uploaded {
    const entry = set.entry;
    const { width, height } = entry;
    const anisotropy = this.look.surface.anisotropy;
    // One level lets the device build the chain; a full chain is uploaded exactly as given.
    const texture = (map: string, format: number, levels: Uint8Array | readonly Uint8Array[]): pc.Texture => new pc.Texture(this.device, {
      name: `${entry.setId}:${map}`,
      width,
      height,
      format,
      mipmaps: true,
      anisotropy,
      addressU: pc.ADDRESS_REPEAT,
      addressV: pc.ADDRESS_REPEAT,
      minFilter: pc.FILTER_LINEAR_MIPMAP_LINEAR,
      magFilter: pc.FILTER_LINEAR,
      levels: levels instanceof Uint8Array ? [levels] : [...levels],
    });
    if (undrawnClassReason(set) !== null) throw new Error(`Texture set ${entry.setId} is ${set.materialClass}, which this runtime does not draw`);
    const cutout = set.classParameters.materialClass === 'cutout' ? set.classParameters : null;
    // sRGB8 without alpha cannot generate mipmaps on WebGL2, so every colour map carries an alpha
    // channel: opaque for an opaque set, the coverage for a cutout, whose chain keeps its coverage.
    const baseColor = cutout === null
      ? texture('base_color', pc.PIXELFORMAT_SRGBA8, rgbToRgba(requiredMap(set, 'base_color')))
      : texture('base_color_coverage', pc.PIXELFORMAT_SRGBA8, coveragePreservingMips(
        requiredMap(set, 'base_color_coverage'), width, height, cutout.alphaCutoff, cutout.coveragePermille,
      ));
    const normalBytes = normalTexels(set);
    const normal = normalBytes === null ? null : texture('normal', pc.PIXELFORMAT_RGBA8, normalBytes);
    const glazing = set.classParameters.materialClass === 'glazing' ? set.classParameters : null;
    // Glazing holds transmission and roughness where the other classes hold occlusion, roughness and metalness.
    const surface = glazing === null
      ? texture('orm', pc.PIXELFORMAT_RGBA8, rgbToRgba(requiredMap(set, 'orm')))
      : texture('transmission_roughness', pc.PIXELFORMAT_RGBA8, transmissionRoughnessTexels(requiredMap(set, 'transmission_roughness')));
    const textures = [baseColor, ...(normal === null ? [] : [normal]), surface];
    let residentBytes = textures.length * mippedBytes(width, height, 4);

    const material = new pc.StandardMaterial();
    material.name = `generated-tile:${entry.setId}`;
    material.useMetalness = true;
    material.diffuse = new pc.Color(1, 1, 1);
    material.diffuseMap = baseColor;
    if (normal !== null) {
      material.normalMap = normal;
      material.bumpiness = this.look.surface.normalStrength;
    }
    material.gloss = 1;
    material.glossMap = surface;
    material.glossMapChannel = 'g';
    material.glossInvert = true;
    if (glazing === null) {
      material.aoMap = surface;
      material.aoMapChannel = 'r';
      material.metalness = 1;
      material.metalnessMap = surface;
      material.metalnessMapChannel = 'b';
    } else {
      // glTF metallic-roughness with metalness 0, KHR_materials_transmission and KHR_materials_ior.
      // Reflection is specular with reflectance ((n - 1) / (n + 1))^2 by angle; what was drawn behind
      // the pane is seen through it, tinted by the base colour, times the transmission map; where
      // transmission is below full, the rest is the film the base colour and roughness maps carry,
      // lit like an opaque surface. Drawn after the opaque scene, depth tested, no depth write.
      const glass = material as TransmissiveMaterial;
      glass.metalness = 0;
      glass.refraction = 1;
      glass.refractionMap = surface;
      glass.refractionMapChannel = 'r';
      glass.refractionIndex = 1_000_000 / glazing.iorMillionths;
      glass.useDynamicRefraction = true;
      // A pane is thin: the view through it is not displaced.
      glass.thickness = 0;
      glass.blendType = pc.BLEND_NORMAL;
      glass.depthWrite = false;
    }
    material.useSkybox = true;
    material.cull = glazing !== null && glazing.doubleSided ? pc.CULLFACE_NONE : pc.CULLFACE_BACK;
    if (cutout !== null) {
      // glTF alphaMode MASK: tested, never blended, depth written, in the shadow pass as well.
      material.opacityMap = baseColor;
      material.opacityMapChannel = 'a';
      material.alphaTest = cutout.alphaCutoff / 255;
      material.blendType = pc.BLEND_NONE;
      material.depthWrite = true;
      // glTF doubleSided: both faces drawn and lit, a back face with its normal reversed.
      material.cull = cutout.doubleSided ? pc.CULLFACE_NONE : pc.CULLFACE_BACK;
      material.twoSidedLighting = cutout.doubleSided;
    }
    if (this.look.surface.parallax && set.maps.height !== undefined) {
      const heightMap = texture('height', pc.PIXELFORMAT_R8, requiredMap(set, 'height'));
      textures.push(heightMap);
      residentBytes += mippedBytes(width, height, 1);
      material.heightMap = heightMap;
      material.heightMapFactor = this.look.surface.parallaxFactor;
    }
    material.update();
    return { set, material, textures, residentBytes };
  }

  destroy(): void {
    this.destroyed = true;
    for (const upload of this.settled.values()) {
      upload.material.destroy();
      for (const texture of upload.textures) texture.destroy();
    }
    this.settled.clear();
    if (this.unavailable !== null) {
      this.unavailable.material.destroy();
      this.unavailable.texture.destroy();
      this.unavailable = null;
    }
  }
}

/** Uploads that fetch and verify their own sets from a manifest, once per set. */
export class TileTextureLibrary extends TileTextureUploads {
  private readonly pending = new Map<string, Promise<PreparedTextureSet>>();

  constructor(
    device: pc.GraphicsDevice,
    look: TileLook,
    private readonly manifest: TextureSetManifest,
    /** Fetch a pinned set's bytes. The library verifies them; the fetcher need not. */
    private readonly fetchSet: (entry: TextureSetManifestEntry) => Promise<Uint8Array>,
    private readonly digest?: TextureSetDigest | null,
  ) {
    super(device, look);
  }

  /** Fetch, verify and upload, once per set. */
  async resolve(setId: string): Promise<TileTextureResolution> {
    if (this.destroyed) throw new Error('The texture library has been destroyed');
    let prepared = this.pending.get(setId);
    if (prepared === undefined) {
      prepared = prepareTextureSet(this.manifest, setId, this.fetchSet, this.digest);
      this.pending.set(setId, prepared);
    }
    const result = await prepared;
    if (this.destroyed) throw new Error('The texture library was destroyed while the set loaded');
    return this.adopt(result);
  }
}
