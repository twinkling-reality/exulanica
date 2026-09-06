import * as pc from 'playcanvas';
import type { IslandId } from '@exulanica/atlas-core';
import { validateSceneTransform } from './scene-point-maps.js';

export interface TrainedSceneGeometry {
  readonly sceneId: string;
  readonly islandId: IslandId;
  readonly artifactId: string;
  readonly bytes: ArrayBuffer;
  readonly sceneFromAssetRowMajor: readonly number[];
  readonly bounds: { readonly min: readonly number[]; readonly max: readonly number[] };
  readonly pointCount: number;
}

/** Reject incomplete SOG bundles before PlayCanvas can fall back to fetching missing textures. */
export function validateSogBundle(bytes: ArrayBuffer): { readonly pointCount: number } {
  const data = new DataView(bytes);
  const length = bytes.byteLength;
  const requireRange = (offset: number, size: number): void => {
    if (!Number.isSafeInteger(offset) || offset < 0 || size < 0 || offset + size > length) {
      throw new TypeError('SOG archive contains an invalid byte range');
    }
  };
  requireRange(length - 22, 22);
  const end = length - 22;
  if (data.getUint32(end, true) !== 0x06054b50 || data.getUint16(end + 20, true) !== 0) {
    throw new TypeError('SOG requires a complete ZIP archive without comments');
  }
  const count = data.getUint16(end + 10, true);
  const directorySize = data.getUint32(end + 12, true);
  let offset = data.getUint32(end + 16, true);
  if (count < 1 || count > 32 || data.getUint16(end + 4, true) !== 0
    || data.getUint16(end + 6, true) !== 0 || data.getUint16(end + 8, true) !== count
    || offset + directorySize !== end) {
    throw new TypeError('SOG archive directory is invalid or unsupported');
  }
  const files = new Map<string, Uint8Array>();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  for (let index = 0; index < count; index += 1) {
    requireRange(offset, 46);
    if (data.getUint32(offset, true) !== 0x02014b50) throw new TypeError('Invalid SOG directory entry');
    const size = data.getUint32(offset + 20, true);
    const nameLength = data.getUint16(offset + 28, true);
    const extraLength = data.getUint16(offset + 30, true);
    const commentLength = data.getUint16(offset + 32, true);
    const local = data.getUint32(offset + 42, true);
    const flags = data.getUint16(offset + 8, true);
    const entrySize = 46 + nameLength + extraLength + commentLength;
    requireRange(offset, entrySize);
    const name = decoder.decode(new Uint8Array(bytes, offset + 46, nameLength));
    // The pinned production compressor writes ZIP STORE; no implicit network references, paths,
    // duplicate names, encryption, or alternate decompressor are accepted at this boundary.
    if (!/^[a-zA-Z0-9_-]+\.(json|webp)$/.test(name) || files.has(name)
      || (flags & ~0x0808) !== 0 || data.getUint16(offset + 10, true) !== 0
      || data.getUint32(offset + 24, true) !== size) {
      throw new TypeError('SOG must contain unique, uncompressed local members');
    }
    requireRange(local, 30);
    const localNameLength = data.getUint16(local + 26, true);
    const localExtraLength = data.getUint16(local + 28, true);
    const body = local + 30 + localNameLength + localExtraLength;
    requireRange(local + 30, localNameLength + localExtraLength);
    requireRange(body, size);
    if (data.getUint32(local, true) !== 0x04034b50
      || decoder.decode(new Uint8Array(bytes, local + 30, localNameLength)) !== name
      || data.getUint16(local + 6, true) !== flags || data.getUint16(local + 8, true) !== 0
      || ((flags & 8) === 0 && (data.getUint32(local + 18, true) !== size || data.getUint32(local + 22, true) !== size))
      || body + size > offset) {
      throw new TypeError('SOG local member disagrees with its directory');
    }
    if ((flags & 8) !== 0) {
      // The pinned compressor streams ZIP STORE with UTF-8 and a signed size/CRC descriptor.
      requireRange(body + size, 16);
      if (data.getUint32(body + size, true) !== 0x08074b50
        || data.getUint32(body + size + 4, true) !== data.getUint32(offset + 16, true)
        || data.getUint32(body + size + 8, true) !== size
        || data.getUint32(body + size + 12, true) !== size) {
        throw new TypeError('SOG streamed member descriptor is inconsistent');
      }
    }
    files.set(name, new Uint8Array(bytes, body, size));
    offset += entrySize;
  }
  if (offset !== end) throw new TypeError('SOG directory length is inconsistent');
  const metadata = files.get('meta.json');
  if (metadata === undefined || metadata.byteLength > 1_000_000) throw new TypeError('SOG metadata is missing or too large');
  const meta = JSON.parse(decoder.decode(metadata)) as Record<string, unknown>;
  if (meta['version'] !== 2 || !Number.isSafeInteger(meta['count']) || (meta['count'] as number) <= 0) {
    throw new TypeError('SOG requires version 2 metadata and a positive splat count');
  }
  for (const [key, expected] of [['means', 2], ['scales', 1], ['quats', 1], ['sh0', 1], ['shN', 2]] as const) {
    const section = meta[key] as { files?: unknown } | undefined;
    if (section === undefined && key === 'shN') continue;
    const names = section?.files;
    if (!Array.isArray(names) || names.length !== expected || names.some((name) =>
      typeof name !== 'string' || !name.endsWith('.webp') || !files.has(name))) {
      throw new TypeError(`SOG ${key} references missing or external texture bytes`);
    }
  }
  return Object.freeze({ pointCount: meta['count'] as number });
}

export function validateTrainedSceneGeometry(value: TrainedSceneGeometry): void {
  const m = value.sceneFromAssetRowMajor;
  validateSceneTransform(m, Math.hypot(m[0]!, m[4]!, m[8]!));
  for (const bound of [value.bounds.min, value.bounds.max]) {
    if (bound.length !== 3 || bound.some((number) => !Number.isFinite(number))) {
      throw new TypeError('Trained scene bounds must be finite three-component vectors');
    }
  }
  if (value.bounds.min.some((number, index) => number > value.bounds.max[index]!)) {
    throw new TypeError('Trained scene bounds are inverted');
  }
}

export function trainedSceneFootprint(value: TrainedSceneGeometry): number {
  validateTrainedSceneGeometry(value);
  const m = value.sceneFromAssetRowMajor;
  let radius = 0;
  for (const x of [value.bounds.min[0]!, value.bounds.max[0]!]) {
    for (const y of [value.bounds.min[1]!, value.bounds.max[1]!]) {
      for (const z of [value.bounds.min[2]!, value.bounds.max[2]!]) {
        radius = Math.max(radius, Math.hypot(m[0]! * x + m[1]! * y + m[2]! * z + m[3]!,
          m[8]! * x + m[9]! * y + m[10]! * z + m[11]!));
      }
    }
  }
  return Math.max(0.1, radius);
}

/**
 * The proof lens over trained Gaussian geometry, as a per-component work-buffer modifier.
 *
 * WHY THIS AND NOT THE FRAGMENT CHUNK. Unified gsplat rendering draws every splat component
 * through one shared work buffer, so a fragment uniform cannot differ between two regions in the
 * same frame: a lens delivered there would colour the whole world by whichever region wrote last.
 * The work buffer is filled per component (`GSplatUnifiedRenderer.renderSplat` applies that
 * component's own `parameters` before each splat's quad render), so `modifySplatColor` is the one
 * hook where a per-region value is genuinely per region. That is the difference between a lens and
 * a lie about which surface is which.
 *
 * THE PRICE IS A RE-RENDER, WHICH IS WHY THE VALUE IS PUSHED AND NOT POLLED. The work buffer is
 * only refilled when something asks it to, so the binding sets `WORKBUFFER_UPDATE_ONCE` on the
 * frame the lens value changes and leaves it on AUTO otherwise. A lens that re-rendered the work
 * buffer every frame would cost the whole scene's splats continuously to display a value that
 * changes when a visitor presses a button.
 *
 * `uProofLens` carries the same four numbers as the point-map shader's `uLens`: a colour resolved
 * in `@exulanica/presentation` and a tint strength. All zero is off, and off is an exact identity
 * because `mix(c, anything, 0.0)` is `c`.
 */
export const PROOF_LENS_SPLAT_MODIFIER = Object.freeze({
  glsl: /* glsl */ `
uniform vec4 uProofLens;
void modifySplatCenter(inout vec3 center) {}
void modifySplatRotationScale(vec3 originalCenter, vec3 modifiedCenter, inout vec4 rotation, inout vec3 scale) {}
void modifySplatColor(vec3 center, inout vec4 color) {
    float luma = dot(color.rgb, vec3(0.2126, 0.7152, 0.0722));
    vec3 hue = uProofLens.rgb / max(dot(uProofLens.rgb, vec3(0.2126, 0.7152, 0.0722)), 0.004);
    color.rgb = mix(color.rgb, clamp(hue * luma, 0.0, 1.0), uProofLens.a);
}
`,
  wgsl: /* wgsl */ `
uniform uProofLens : vec4f;
fn modifySplatCenter(center : ptr<function, vec3f>) {}
fn modifySplatRotationScale(originalCenter : vec3f, modifiedCenter : vec3f, rotation : ptr<function, vec4f>, scale : ptr<function, vec3f>) {}
fn modifySplatColor(center : vec3f, color : ptr<function, vec4f>) {
    let luma : f32 = dot((*color).rgb, vec3f(0.2126, 0.7152, 0.0722));
    let hue : vec3f = uniform.uProofLens.rgb / max(dot(uniform.uProofLens.rgb, vec3f(0.2126, 0.7152, 0.0722)), 0.004);
    (*color) = vec4f(mix((*color).rgb, clamp(hue * luma, vec3f(0.0), vec3f(1.0)), uniform.uProofLens.a), (*color).a);
}
`,
});

/** Native SOG decoder, supplied only authenticated, digest-verified, self-contained bytes. */
export async function createSceneSplatAsset(app: pc.AppBase, value: TrainedSceneGeometry): Promise<pc.Asset> {
  validateTrainedSceneGeometry(value);
  validateSogBundle(value.bytes);
  const filename = `${value.artifactId}.sog`;
  const asset = new pc.Asset(`reconstruction:${value.artifactId}`, 'gsplat', {
    url: `verified-scene/${filename}`, filename, contents: value.bytes,
  });
  app.assets.add(asset);
  let timeout: ReturnType<typeof globalThis.setTimeout> | undefined;
  try {
    await new Promise<void>((resolve, reject) => {
      timeout = globalThis.setTimeout(() => reject(new Error('Trained scene decoding timed out')), 60_000);
      asset.once('load', () => resolve());
      asset.once('error', (error: unknown) => reject(error));
      app.assets.load(asset);
    });
    if (asset.resource === null || asset.resource === undefined) throw new Error('Trained scene produced no renderer resource');
    return asset;
  } catch (error) {
    asset.unload();
    app.assets.remove(asset);
    throw error;
  } finally { globalThis.clearTimeout(timeout); }
}
