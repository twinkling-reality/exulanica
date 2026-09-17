import * as pc from 'playcanvas';
import {
  TextureSetRefusal,
  decodeTextureSet,
  type DecodedTextureSet,
  type TextureSetDigest,
  type TextureSetManifest,
  type TextureSetManifestEntry,
} from '@exulanica/atlas-core';
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
 * so a wall `w` mm wide repeats the tile `w / extent_u_mm` times at a record scale of one. The
 * record's `uv_scale_millionths` multiplies the repeat frequency, and `uv_rotation_urad` turns the
 * texture on the surface, both applied in millimetres before dividing by the extent, so a
 * non-square set (the kerb is 1800 by 450 mm) keeps its proportions under rotation. There is no
 * other scale anywhere, and no constant that guesses one.
 *
 * WHAT A SET BECOMES. base_color is uploaded as sRGB; normal, orm and height as linear bytes. The
 * orm map drives three material inputs from its three channels: occlusion (red), roughness (green,
 * inverted into PlayCanvas's gloss) and metalness (blue). The height map is uploaded only when the
 * look turns parallax on, so an unused map costs no memory.
 *
 * A SET THAT DOES NOT RESOLVE draws the stated unavailable surface, with the refusal's reason kept
 * for whoever reports it. There is no default set, no flat colour and no retry with a looser check.
 */

/** The material record fields a renderer reads. Everything else in the record is world data. */
export interface TileMaterialReference {
  readonly textureSetId: string;
  readonly uvScaleMillionths: number;
  readonly uvRotationUrad: number;
}

export type TileTextureResolution =
  | { readonly state: 'available'; readonly setId: string; readonly material: pc.StandardMaterial; readonly set: DecodedTextureSet }
  | { readonly state: 'unavailable'; readonly setId: string; readonly material: pc.StandardMaterial; readonly reason: string };

const MILLIONTHS = 1_000_000;

/**
 * UV for a surface point `s`, `t` millimetres from the surface's own origin.
 *
 * Returns a float pair for the render payload only. Nothing digested reads it.
 */
export function surfaceUv(
  sMm: number,
  tMm: number,
  reference: TileMaterialReference,
  entry: Pick<TextureSetManifestEntry, 'extentUMm' | 'extentVMm'>,
): readonly [number, number] {
  const scale = reference.uvScaleMillionths / MILLIONTHS;
  const angle = reference.uvRotationUrad / MILLIONTHS;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return [
    (scale * (cos * sMm - sin * tMm)) / entry.extentUMm,
    (scale * (sin * sMm + cos * tMm)) / entry.extentVMm,
  ];
}

/** UV for the unavailable pattern, which repeats once per `look.unavailable.tileMm`. */
export function unavailableUv(sMm: number, tMm: number, look: TileLook): readonly [number, number] {
  return [sMm / look.unavailable.tileMm, tMm / look.unavailable.tileMm];
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

export class TileTextureLibrary {
  private readonly uploads = new Map<string, Promise<Uploaded | { readonly refused: string }>>();
  private readonly settled = new Map<string, Uploaded>();
  private unavailable: ReturnType<typeof createUnavailableMaterial> | null = null;
  private destroyed = false;

  constructor(
    private readonly device: pc.GraphicsDevice,
    private readonly look: TileLook,
    private readonly manifest: TextureSetManifest,
    /** Fetch a pinned set's bytes. The library verifies them; the fetcher need not. */
    private readonly fetchSet: (entry: TextureSetManifestEntry) => Promise<Uint8Array>,
    private readonly digest?: TextureSetDigest | null,
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

  get resolvedSetIds(): readonly string[] {
    return [...this.settled.keys()].sort();
  }

  async resolve(setId: string): Promise<TileTextureResolution> {
    if (this.destroyed) throw new Error('The texture library has been destroyed');
    const entry = this.manifest.byId.get(setId);
    if (entry === undefined) {
      return { state: 'unavailable', setId, material: this.unavailableMaterial,
        reason: `Texture set ${setId} is not pinned by the texture manifest.` };
    }
    let pending = this.uploads.get(setId);
    if (pending === undefined) {
      pending = this.upload(entry);
      this.uploads.set(setId, pending);
    }
    const result = await pending;
    if ('refused' in result) {
      return { state: 'unavailable', setId, material: this.unavailableMaterial, reason: result.refused };
    }
    return { state: 'available', setId, material: result.material, set: result.set };
  }

  private async upload(entry: TextureSetManifestEntry): Promise<Uploaded | { readonly refused: string }> {
    let set: DecodedTextureSet;
    try {
      const bytes = await this.fetchSet(entry);
      set = this.digest === undefined
        ? await decodeTextureSet(bytes, entry)
        : await decodeTextureSet(bytes, entry, this.digest);
    } catch (error) {
      if (error instanceof TextureSetRefusal) return { refused: `Texture set ${entry.setId} refused: ${error.message}` };
      return { refused: `Texture set ${entry.setId} could not be read: ${error instanceof Error ? error.message : String(error)}` };
    }
    if (this.destroyed) return { refused: 'The texture library was destroyed while the set loaded.' };
    const { width, height } = entry;
    const anisotropy = this.look.surface.anisotropy;
    const texture = (map: string, format: number, levels: Uint8Array): pc.Texture => new pc.Texture(this.device, {
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
      levels: [levels],
    });
    // sRGB8 without alpha cannot generate mipmaps on WebGL2, so every colour map carries an
    // opaque alpha channel.
    const baseColor = texture('base_color', pc.PIXELFORMAT_SRGBA8, rgbToRgba(set.maps.base_color));
    const normal = texture('normal', pc.PIXELFORMAT_RGBA8, rgbToRgba(set.maps.normal));
    const orm = texture('orm', pc.PIXELFORMAT_RGBA8, rgbToRgba(set.maps.orm));
    const textures = [baseColor, normal, orm];
    let residentBytes = 3 * mippedBytes(width, height, 4);

    const material = new pc.StandardMaterial();
    material.name = `generated-tile:${entry.setId}`;
    material.useMetalness = true;
    material.diffuse = new pc.Color(1, 1, 1);
    material.diffuseMap = baseColor;
    material.normalMap = normal;
    material.bumpiness = this.look.surface.normalStrength;
    material.aoMap = orm;
    material.aoMapChannel = 'r';
    material.gloss = 1;
    material.glossMap = orm;
    material.glossMapChannel = 'g';
    material.glossInvert = true;
    material.metalness = 1;
    material.metalnessMap = orm;
    material.metalnessMapChannel = 'b';
    material.useSkybox = true;
    material.cull = pc.CULLFACE_BACK;
    if (this.look.surface.parallax) {
      const heightMap = texture('height', pc.PIXELFORMAT_R8, set.maps.height);
      textures.push(heightMap);
      residentBytes += mippedBytes(width, height, 1);
      material.heightMap = heightMap;
      material.heightMapFactor = this.look.surface.parallaxFactor;
    }
    material.update();
    const uploaded = { set, material, textures, residentBytes };
    this.settled.set(entry.setId, uploaded);
    return uploaded;
  }

  destroy(): void {
    this.destroyed = true;
    for (const upload of this.settled.values()) {
      upload.material.destroy();
      for (const texture of upload.textures) texture.destroy();
    }
    this.settled.clear();
    this.uploads.clear();
    if (this.unavailable !== null) {
      this.unavailable.material.destroy();
      this.unavailable.texture.destroy();
      this.unavailable = null;
    }
  }
}
