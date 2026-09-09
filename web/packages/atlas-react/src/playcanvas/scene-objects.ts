/**
 * Authored objects: a verified GLB container, placed on the same ground the reconstruction stands
 * on, and one bounded motion over it.
 *
 * This is the renderer half of product-direction.md's first milestone rows 3 and 4. Until it
 * existed the renderer loaded exactly two things, a point map and a verified SOG splat, and both
 * of them are *recovered* geometry. An authored object is the first thing in the world that was
 * never photographed, so every decision here is about keeping those two categories apart while
 * letting them share a floor.
 *
 * **The same boundary as `scene-splats.ts`, for the same reason.** A container is decoded from an
 * `ArrayBuffer` this module fetched through the authenticated transport and checked against the
 * descriptor that named it; the loader is handed bytes, never a URL. `createSceneSplatAsset`
 * exists because PlayCanvas's SOG decoder would otherwise fetch textures the caller never
 * authorized, and `createObjectContainerAsset` exists because PlayCanvas's glTF parser will do
 * exactly the same thing for a `buffers[].uri` or an `images[].uri`
 * (`playcanvas@2.21.4` `loadBuffers` and `createImages` both call `http.get` on a non-data URI).
 * So the container is validated BEFORE the parser sees it, and a container carrying an external
 * reference is refused rather than loaded with one texture missing.
 *
 * **The digest is required here, not optional.** `fetchAuthenticatedAsset` checks a SHA-256 when
 * the descriptor carries one and skips the check when it does not. For an authored object there
 * is no descriptor without one: `fetchVerifiedObjectAsset` refuses a reference with no digest,
 * refuses a byte count that disagrees, and refuses outright when `crypto.subtle` is unavailable,
 * which is the same trade `geometry-api.ts` refuses to make for reconstruction bytes. Decoding
 * unverified bytes because the page was served over a non-secure context would put a container
 * nobody checked into the same scene as geometry everybody did.
 *
 * **Region-local coordinates, composed with the region's display frame.** An object is persisted
 * as `scene_from_object`: a transform in the region's own recovered frame, exactly like a trained
 * scene's `sceneFromAssetRowMajor`. The renderer composes it with that region's
 * `SceneDisplayFrame` before it becomes an entity transform, so the object lands in the same
 * upright, ground-levelled, walking-scale frame `display-frame.ts` put the geometry in and stands
 * on the same floor. Persisting the DISPLAY-space transform instead would have been one fewer
 * multiply and would have detached the object from its region the first time a new capture
 * changed the recovered cameras: the floor would move and the object would not.
 *
 * **Atlas space is converted to a region frame HERE and nowhere else.** `coords.ts` says there is
 * no `atlasToLocal` and there must never be one, because an island's atlas position is a layout
 * artifact rather than a place (risk R-48). Placing an object where a visitor is standing needs
 * that conversion anyway, so it lives in the renderer binding, which is the one layer already
 * permitted to read atlas positions as geometry, and it produces a PRESENTATION transform rather
 * than an answer to "where in the capture is this". Nothing it returns is a claim about the world
 * the photographs came from.
 *
 * **Nothing here writes.** The runtime places, moves, removes and animates entities that a surface
 * has already committed through the confirmation surface and the world-objects client. Trigger,
 * stop and reset are runtime state and are deliberately not persisted: `display-frame.ts` is
 * presentation and so is a phase in a sine.
 */

import * as pc from 'playcanvas';
import {
  BEHAVIOUR_REGISTRY,
  BoundedMotion,
  composeDisplayFrame,
  motionTransform,
  type IslandId,
  type IslandPlacement,
  type SceneDisplayFrame,
} from '@exulanica/atlas-core';
import type { CameraPose } from '@exulanica/atlas-core';

import { fetchAuthenticatedAsset, type AuthenticatedAssetFetchOptions } from './physical-residency.js';

/** The only container an authored object may name. A file extension is not a container. */
export const AUTHORED_OBJECT_CONTAINER = 'glb/2.0';

/** How far in front of the visitor a placement lands when no anchor is engaged, in display units. */
export const DEFAULT_PLACEMENT_DISTANCE = 2.5;

const MAX_CONTAINER_BYTES = 32 * 1024 * 1024;
const MAX_JSON_CHUNK_BYTES = 4 * 1024 * 1024;
const GLB_MAGIC = 0x46546c67;
const CHUNK_JSON = 0x4e4f534a;
const CHUNK_BIN = 0x004e4942;

/**
 * Extensions whose decoder is fetched at load time rather than shipped in this build.
 *
 * Listed by name rather than caught by "anything unknown in `extensionsUsed`", because an
 * unrequired extension is by specification ignorable and refusing every one of them would refuse
 * ordinary exporter output over a field the parser is entitled to skip. These three are not
 * ignorable: each one is what a mesh or a texture is actually encoded with.
 */
const CODEC_EXTENSIONS: ReadonlySet<string> = new Set([
  'KHR_draco_mesh_compression',
  'EXT_meshopt_compression',
  'KHR_texture_basisu',
]);

export interface AuthoredObjectAssetReference {
  readonly assetId: string;
  readonly container: typeof AUTHORED_OBJECT_CONTAINER;
  /** Stable authenticated API path, never a bearer URL and never a remote origin. */
  readonly path: string;
  readonly contentSha256: string;
  readonly byteSize: number;
}

/** A pose in a region's display frame: the walking-scale, upright, ground-levelled space. */
export interface DisplayPose {
  readonly x: number;
  readonly y: number;
  readonly z: number;
  /** Facing, radians about display +Y. */
  readonly yaw: number;
}

export interface AuthoredObjectBehaviour {
  readonly behaviourId: string;
  readonly parameters: unknown;
}

export interface PlacedAuthoredObject {
  readonly objectId: string;
  readonly islandId: IslandId;
  readonly sceneId: string;
  readonly asset: AuthoredObjectAssetReference;
  /** Region-local. Composed with the region's display frame before it becomes a transform. */
  readonly sceneFromObjectRowMajor: readonly number[];
  readonly behaviour: AuthoredObjectBehaviour | null;
}

export interface GlbSummary {
  readonly jsonBytes: number;
  readonly binaryBytes: number;
  readonly meshCount: number;
  readonly nodeCount: number;
  readonly imageCount: number;
}

export type BehaviourControl = 'trigger' | 'stop' | 'reset';

export interface ObjectPlacementOutcome {
  readonly objectId: string;
  readonly motion: 'attached' | 'none';
  /** Anything the visitor must be told, in words. Empty when nothing needed saying. */
  readonly notices: readonly string[];
}

// -- verification ------------------------------------------------------------------------------

/**
 * Reject a container the glTF parser would complete over the network, before it sees it.
 *
 * The rejections are not a general glTF validation and do not try to be. They are exactly the
 * places `playcanvas@2.21.4` reaches outside the bytes in hand:
 *
 * - `buffers[].uri`. `loadBuffers` fetches any non-data URI, absolute or relative to the asset.
 * - `images[].uri`. `createImages` does the same, and adds `crossOrigin: "anonymous"`.
 * - a codec extension. This is the one that is easy to miss, because it is not a URI at all. A
 *   primitive carrying `KHR_draco_mesh_compression` reaches `createDracoMesh`, which asks
 *   `WasmModule` for a decoder and, unconfigured, fetches `draco.wasm.js` and `draco.wasm.wasm`
 *   relative to the page and runs the result in a Worker through `URL.createObjectURL`. That is
 *   an unverified EXECUTABLE fetched because of something written inside the container, which is
 *   a worse version of the fetch this whole boundary exists to prevent. The transcoded texture
 *   and mesh-compression extensions do the same for their own decoders.
 * - any other `extensionsRequired`. A required extension this build has not reviewed either
 *   changes what the bytes mean or is dropped silently, and a silently dropped mesh renders an
 *   authored object as nothing at all rather than as a refusal.
 *
 * A data URI is not an external reference and would be safe to allow. It is refused anyway: a
 * self-contained GLB puts its buffer in the BIN chunk, so a data URI here means the container was
 * produced by a path this build has not seen, and admitting it would mean the byte count in the
 * descriptor no longer bounds what gets decoded.
 */
export function validateGlbContainer(bytes: ArrayBuffer): GlbSummary {
  const length = bytes.byteLength;
  if (length < 20 || length > MAX_CONTAINER_BYTES) {
    throw new TypeError('An authored object container must be between 20 bytes and 32 MB');
  }
  if (length % 4 !== 0) throw new TypeError('A GLB container must be a whole number of 4-byte words');
  const data = new DataView(bytes);
  if (data.getUint32(0, true) !== GLB_MAGIC) throw new TypeError('This is not a GLB container');
  if (data.getUint32(4, true) !== 2) throw new TypeError('An authored object requires glTF binary version 2');
  if (data.getUint32(8, true) !== length) {
    throw new TypeError('The GLB header length disagrees with the bytes that arrived');
  }

  const chunks: { readonly type: number; readonly start: number; readonly length: number }[] = [];
  let offset = 12;
  while (offset < length) {
    if (offset + 8 > length) throw new TypeError('A GLB chunk header runs past the end of the container');
    const chunkLength = data.getUint32(offset, true);
    const type = data.getUint32(offset + 4, true);
    if (chunkLength % 4 !== 0 || offset + 8 + chunkLength > length) {
      throw new TypeError('A GLB chunk length is unaligned or runs past the end of the container');
    }
    chunks.push({ type, start: offset + 8, length: chunkLength });
    offset += 8 + chunkLength;
  }
  if (offset !== length) throw new TypeError('The GLB chunk table does not fill the container');
  if (chunks.length < 1 || chunks.length > 2) throw new TypeError('A GLB container must hold one or two chunks');
  const json = chunks[0]!;
  const binary = chunks[1] ?? null;
  if (json.type !== CHUNK_JSON) throw new TypeError('The first GLB chunk must be the JSON chunk');
  if (binary !== null && binary.type !== CHUNK_BIN) throw new TypeError('The second GLB chunk must be the BIN chunk');
  if (json.length === 0 || json.length > MAX_JSON_CHUNK_BYTES) {
    throw new TypeError('The GLB JSON chunk is empty or too large');
  }

  let gltf: Record<string, unknown>;
  try {
    const text = new TextDecoder('utf-8', { fatal: true })
      .decode(new Uint8Array(bytes, json.start, json.length));
    const parsed: unknown = JSON.parse(text);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      throw new TypeError('not an object');
    }
    gltf = parsed as Record<string, unknown>;
  } catch {
    throw new TypeError('The GLB JSON chunk is not a valid glTF document');
  }

  const asset = gltf['asset'];
  const assetVersion = typeof asset === 'object' && asset !== null
    ? (asset as Record<string, unknown>)['version']
    : undefined;
  if (assetVersion !== '2.0') throw new TypeError('An authored object requires a glTF 2.0 asset version');

  const required = gltf['extensionsRequired'];
  if (Array.isArray(required) && required.length > 0) {
    throw new TypeError(
      `This container requires unreviewed glTF extensions: ${required.map(String).join(', ')}`,
    );
  }
  const used = gltf['extensionsUsed'];
  if (Array.isArray(used)) {
    const codecs = used.map(String).filter((name) => CODEC_EXTENSIONS.has(name));
    if (codecs.length > 0) {
      throw new TypeError(
        `This container is compressed with ${codecs.join(', ')}, which would fetch and run a `
        + 'decoder this build has not verified.',
      );
    }
  }

  const list = (key: string): readonly Record<string, unknown>[] => {
    const value = gltf[key];
    if (value === undefined) return [];
    if (!Array.isArray(value)) throw new TypeError(`The GLB ${key} list is not an array`);
    return value.map((item) => {
      if (typeof item !== 'object' || item === null || Array.isArray(item)) {
        throw new TypeError(`A GLB ${key} entry is not an object`);
      }
      return item as Record<string, unknown>;
    });
  };

  const buffers = list('buffers');
  const images = list('images');
  for (const [key, entries] of [['buffer', buffers], ['image', images]] as const) {
    for (const entry of entries) {
      if ('uri' in entry) {
        throw new TypeError(
          `This container references an external ${key}. An authored object must be self-contained.`,
        );
      }
    }
  }
  for (const image of images) {
    if (typeof image['bufferView'] !== 'number') {
      throw new TypeError('A GLB image resolves to neither a buffer view nor bytes in this container');
    }
  }
  if (binary === null && buffers.length > 0) {
    throw new TypeError('This container declares buffers and carries no BIN chunk');
  }
  for (const buffer of buffers) {
    const declared = buffer['byteLength'];
    if (!Number.isSafeInteger(declared) || (declared as number) < 0
      || (declared as number) > (binary?.length ?? 0)) {
      throw new TypeError('A GLB buffer declares a length its BIN chunk cannot hold');
    }
  }

  return Object.freeze({
    jsonBytes: json.length,
    binaryBytes: binary?.length ?? 0,
    meshCount: list('meshes').length,
    nodeCount: list('nodes').length,
    imageCount: images.length,
  });
}

/** The same shape `geometry-api.ts` requires of a reconstruction path, for the same reason. */
export function safeObjectAssetPath(value: string): boolean {
  return value.startsWith('/world-objects/')
    && !value.includes('://')
    && !value.includes('?')
    && !value.includes('#');
}

/**
 * Authenticated, digest-verified container bytes.
 *
 * The hash is checked by `fetchAuthenticatedAsset` against the DESCRIPTOR, never against the
 * response's own `ETag`, which would be checking the response against itself. The byte count is
 * checked here afterwards, because `fetchAuthenticatedAsset` accepts an `expectedBytes` and does
 * not act on it: only `PhysicalResidencyRuntime` does, and this path does not run through it. The
 * count is worth keeping even though a wrong length already fails the hash, for the reason
 * `geometry-api.ts` gives: a truncated transfer and a substituted artifact are different facts,
 * and only one of them is worth retrying.
 */
export async function fetchVerifiedObjectAsset(
  islandId: IslandId,
  reference: AuthoredObjectAssetReference,
  signal: AbortSignal,
  options: AuthenticatedAssetFetchOptions,
): Promise<ArrayBuffer> {
  if (reference.container !== AUTHORED_OBJECT_CONTAINER) {
    throw new TypeError(`“${String(reference.container)}” is not a container this build can open`);
  }
  if (!safeObjectAssetPath(reference.path)) {
    throw new TypeError('An authored object asset must be read from a local authenticated path');
  }
  if (!/^[0-9a-f]{64}$/.test(reference.contentSha256)) {
    throw new TypeError('An authored object needs a SHA-256 in the descriptor before it can be loaded');
  }
  if (!Number.isSafeInteger(reference.byteSize) || reference.byteSize <= 0) {
    throw new TypeError('An authored object needs a byte count in the descriptor before it can be loaded');
  }
  if (globalThis.crypto?.subtle === undefined) {
    throw new TypeError(
      'This page cannot verify content hashes, so no authored object is loaded. '
      + 'A secure context is required.',
    );
  }

  const fetched = await fetchAuthenticatedAsset(
    {
      islandId,
      stage: 'full',
      path: reference.path,
      availability: 'available',
      expectedSha256: reference.contentSha256,
      expectedBytes: reference.byteSize,
      fallback: 'stub',
    },
    signal,
    options,
  );
  if (fetched.bytes.byteLength !== reference.byteSize) {
    throw new TypeError(
      `The object is ${reference.byteSize} bytes and ${fetched.bytes.byteLength} arrived.`,
    );
  }
  validateGlbContainer(fetched.bytes);
  return fetched.bytes;
}

/** Native container handler, supplied only authenticated, digest-verified, self-contained bytes. */
export async function createObjectContainerAsset(
  app: pc.AppBase,
  assetId: string,
  bytes: ArrayBuffer,
): Promise<pc.Asset> {
  validateGlbContainer(bytes);
  const filename = `${assetId}.glb`;
  const asset = new pc.Asset(`authored-object:${assetId}`, 'container', {
    url: `verified-object/${filename}`, filename, contents: bytes,
  });
  app.assets.add(asset);
  let timeout: ReturnType<typeof globalThis.setTimeout> | undefined;
  try {
    await new Promise<void>((resolve, reject) => {
      timeout = globalThis.setTimeout(() => reject(new Error('Authored object decoding timed out')), 30_000);
      asset.once('load', () => resolve());
      // `AssetRegistry` fires this with a plain STRING when no handler is registered for the
      // type. Rejecting with the raw value would reach the caller's `instanceof Error` branch
      // as false and turn a registration fault into a generic decoder sentence.
      asset.once('error', (error: unknown) => reject(
        error instanceof Error ? error : new Error(String(error)),
      ));
      app.assets.load(asset);
    });
    if (asset.resource === null || asset.resource === undefined) {
      throw new Error('The authored object produced no renderer resource');
    }
    return asset;
  } catch (error) {
    asset.unload();
    app.assets.remove(asset);
    throw error;
  } finally { globalThis.clearTimeout(timeout); }
}

// -- placement geometry ------------------------------------------------------------------------

/** `display_from_object` for a pose in a region's display frame. Uniform scale 1: walking size. */
export function displayFromObject(pose: DisplayPose): readonly number[] {
  const c = Math.cos(pose.yaw);
  const s = Math.sin(pose.yaw);
  return Object.freeze([
    c, 0, s, pose.x,
    0, 1, 0, pose.y,
    -s, 0, c, pose.z,
    0, 0, 0, 1,
  ]);
}

/**
 * The inverse of a row-major similarity: a uniform scale times a proper rotation, plus an offset.
 *
 * Written out rather than a general 4x4 inverse because a display frame is a similarity by
 * construction and a general inverse would silently accept a matrix that is not one.
 */
export function invertSimilarity(m: readonly number[]): readonly number[] {
  const scale = Math.hypot(m[0]!, m[4]!, m[8]!);
  if (!Number.isFinite(scale) || scale < 1e-9) {
    throw new TypeError('A display frame must be an invertible similarity');
  }
  // Rotation is the linear part over the scale; its inverse is its transpose over the scale.
  const inverse = [
    m[0]! / (scale * scale), m[4]! / (scale * scale), m[8]! / (scale * scale),
    m[1]! / (scale * scale), m[5]! / (scale * scale), m[9]! / (scale * scale),
    m[2]! / (scale * scale), m[6]! / (scale * scale), m[10]! / (scale * scale),
  ];
  const t = [m[3]!, m[7]!, m[11]!];
  return Object.freeze([
    inverse[0]!, inverse[1]!, inverse[2]!,
    -(inverse[0]! * t[0]! + inverse[1]! * t[1]! + inverse[2]! * t[2]!),
    inverse[3]!, inverse[4]!, inverse[5]!,
    -(inverse[3]! * t[0]! + inverse[4]! * t[1]! + inverse[5]! * t[2]!),
    inverse[6]!, inverse[7]!, inverse[8]!,
    -(inverse[6]! * t[0]! + inverse[7]! * t[1]! + inverse[8]! * t[2]!),
    0, 0, 0, 1,
  ]);
}

export function multiplyRowMajor4(a: readonly number[], b: readonly number[]): readonly number[] {
  const out = new Array<number>(16).fill(0);
  for (let row = 0; row < 4; row += 1) {
    for (let col = 0; col < 4; col += 1) {
      let sum = 0;
      for (let k = 0; k < 4; k += 1) sum += a[row * 4 + k]! * b[k * 4 + col]!;
      out[row * 4 + col] = sum;
    }
  }
  return Object.freeze(out);
}

/**
 * What a surface persists for a pose the visitor chose: `scene_from_object`.
 *
 * The renderer composes the region's display frame back onto this, so the round trip is exact in
 * structure: `display_from_scene * scene_from_object` is the pose that went in.
 */
export function objectTransformForDisplayPose(
  frame: SceneDisplayFrame,
  pose: DisplayPose,
): readonly number[] {
  return multiplyRowMajor4(
    invertSimilarity(frame.displayFromSceneRowMajor),
    displayFromObject(pose),
  );
}

/** The display-space pose a persisted `scene_from_object` describes, for a nudge to start from. */
export function displayPoseOfObject(
  frame: SceneDisplayFrame,
  sceneFromObjectRowMajor: readonly number[],
): DisplayPose {
  const m = composeDisplayFrame(frame, sceneFromObjectRowMajor);
  return Object.freeze({
    x: m[3]!,
    y: m[7]!,
    z: m[11]!,
    // The rotation is about display +Y by construction; reading it back needs no decomposition.
    yaw: Math.atan2(m[2]!, m[0]!),
  });
}

/**
 * An atlas-space point, read as a position in a region's display frame.
 *
 * THIS IS THE R-48 CONVERSION AND IT IS CONFINED TO THIS FILE. `coords.ts` refuses to carry an
 * `atlasToLocal` because an island's atlas position is a layout artifact rather than a place. It
 * is legitimate here for the same reason atlas-space distance is legitimate in the layout solver:
 * the renderer binding is a presentation layer and the result is a presentation transform. A
 * caller must not read what comes back as a location inside the captured world.
 *
 * The island's placement is a yaw, a uniform scale and an offset, so the inverse is written out
 * directly rather than by inverting a general matrix that could not have been one.
 */
export function displayPointFromAtlas(
  placement: IslandPlacement,
  atlas: readonly [number, number, number],
): readonly [number, number, number] {
  const scale = placement.scale;
  if (!Number.isFinite(scale) || Math.abs(scale) < 1e-9) {
    throw new TypeError('A region placement must have a non-zero scale');
  }
  const dx = (atlas[0] - placement.position.x) / scale;
  const dy = (atlas[1] - placement.position.y) / scale;
  const dz = (atlas[2] - placement.position.z) / scale;
  const c = Math.cos(-placement.yaw);
  const s = Math.sin(-placement.yaw);
  return Object.freeze([c * dx + s * dz, dy, -s * dx + c * dz] as [number, number, number]);
}

/**
 * Where a placement lands when the visitor has engaged nothing: a step in front of them, on the
 * region's ground.
 *
 * `groundY` is the height that counts as the ground, in the region's display frame, and the
 * caller supplies it because only the caller knows which frame it has. With a frame derived from
 * recovered cameras the answer is `0`: that is exactly where `display-frame.ts` put the low
 * quantile of the geometry's bounds. With the IDENTITY frame it is not, and this is the case the
 * browser check found. A scene with no recovered cameras gets the identity frame, whose `y = 0`
 * is the scene's own arbitrary origin; an object placed there sinks under the floor the visitor
 * is standing on and is never seen. Passing the visitor's own foot height instead keeps the
 * object where they are looking, and the surface has to stop claiming it stands on measured
 * ground, because it does not.
 *
 * The facing is the visitor's own, so a placed object faces the person who placed it.
 */
export function placementPoseBeforeVisitor(
  placement: IslandPlacement,
  pose: CameraPose,
  distance: number = DEFAULT_PLACEMENT_DISTANCE,
  groundY = 0,
): DisplayPose {
  const local = displayPointFromAtlas(placement, [pose.position.x, pose.position.y, pose.position.z]);
  const heading = displayPointFromAtlas(
    placement,
    [
      pose.position.x + pose.forward.x,
      pose.position.y + pose.forward.y,
      pose.position.z + pose.forward.z,
    ],
  );
  let fx = heading[0] - local[0];
  let fz = heading[2] - local[2];
  const planar = Math.hypot(fx, fz);
  // Looking straight up or down leaves no horizontal heading to step along; face display -Z.
  if (planar < 1e-6) { fx = 0; fz = -1; } else { fx /= planar; fz /= planar; }
  return Object.freeze({
    x: local[0] + fx * distance,
    y: groundY,
    z: local[2] + fz * distance,
    yaw: Math.atan2(fx, fz),
  });
}

/** Where a placement lands on an engaged anchor: at its foot, facing the visitor. */
export function placementPoseAtAtlasPoint(
  placement: IslandPlacement,
  atlas: readonly [number, number, number],
  pose: CameraPose,
  groundY = 0,
): DisplayPose {
  const target = displayPointFromAtlas(placement, atlas);
  const viewer = displayPointFromAtlas(placement, [pose.position.x, pose.position.y, pose.position.z]);
  const dx = viewer[0] - target[0];
  const dz = viewer[2] - target[2];
  const planar = Math.hypot(dx, dz);
  return Object.freeze({
    x: target[0],
    y: groundY,
    z: target[2],
    yaw: planar < 1e-6 ? 0 : Math.atan2(dx / planar, dz / planar),
  });
}

// -- the runtime -------------------------------------------------------------------------------

interface Resident {
  readonly object: PlacedAuthoredObject;
  readonly asset: pc.Asset;
  readonly entity: pc.Entity;
  readonly authored: readonly number[];
  readonly motion: BoundedMotion | null;
}

/**
 * Every authored object currently in the world, and the phase of each one's motion.
 *
 * Held by the binding and advanced from its update, so an object's motion runs on the same clock
 * as everything else and stops when the tab does. It owns no transport: bytes arrive already
 * fetched and verified, which is what keeps the class testable with no network and makes the
 * verification a separate, separately tested boundary.
 */
export class SceneObjectRuntime {
  readonly #app: pc.AppBase;
  readonly #roots: ReadonlyMap<IslandId, pc.Entity>;
  readonly #resident = new Map<string, Resident>();
  #destroyed = false;

  constructor(app: pc.AppBase, roots: ReadonlyMap<IslandId, pc.Entity>) {
    this.#app = app;
    this.#roots = roots;
  }

  get objectIds(): readonly string[] {
    return Object.freeze([...this.#resident.keys()]);
  }

  has(objectId: string): boolean {
    return this.#resident.has(objectId);
  }

  motionStateOf(objectId: string): string | null {
    const resident = this.#resident.get(objectId);
    if (resident === undefined) return null;
    return resident.motion?.state ?? 'none';
  }

  /**
   * Put a verified container in a region, and attach its behaviour if the registry supports it.
   *
   * An unsupported behaviour id does NOT stop the placement. The object is real, its geometry
   * verified, and refusing to draw it because a motion could not be resolved would hide a
   * successful edit behind a failed one. It comes back as a notice instead, and the caller is
   * required by the milestone to put that notice on the status line.
   */
  async place(
    object: PlacedAuthoredObject,
    bytes: ArrayBuffer,
    frame: SceneDisplayFrame,
  ): Promise<ObjectPlacementOutcome> {
    if (this.#destroyed) throw new Error('the authored object runtime is destroyed');
    const root = this.#roots.get(object.islandId);
    if (root === undefined) {
      throw new TypeError('That region is not drawn in this world, so nothing can be placed in it');
    }
    this.remove(object.objectId);

    const notices: string[] = [];
    let motion: BoundedMotion | null = null;
    if (object.behaviour !== null) {
      const read = BEHAVIOUR_REGISTRY.readParameters(
        object.behaviour.behaviourId,
        object.behaviour.parameters,
      );
      if (read.ok) {
        motion = new BoundedMotion(read.parameters);
        if (read.clamped.length > 0) {
          notices.push(
            `This object's ${read.clamped.join(' and ')} was outside the supported range and is `
            + 'drawn at the nearest supported value.',
          );
        }
      } else {
        notices.push(read.reason);
      }
    }

    const asset = await createObjectContainerAsset(this.#app, object.asset.assetId, bytes);
    let entity: pc.Entity | undefined;
    try {
      const resource = asset.resource as pc.ContainerResource;
      entity = resource.instantiateRenderEntity({});
      if (entity === null || entity === undefined) {
        throw new TypeError('This container holds nothing that can be drawn');
      }
      entity.name = `authored-object:${object.objectId}`;
      const authored = composeDisplayFrame(frame, object.sceneFromObjectRowMajor);
      applyRowMajorTransform(entity, authored);
      root.addChild(entity);
      this.#resident.set(object.objectId, { object, asset, entity, authored, motion });
    } catch (error) {
      entity?.destroy();
      asset.unload();
      this.#app.assets.remove(asset);
      throw error;
    }

    return Object.freeze({
      objectId: object.objectId,
      motion: motion === null ? 'none' : 'attached',
      notices: Object.freeze(notices),
    });
  }

  /** Move a resident object to a new authored transform. Its motion returns to rest, exactly. */
  setTransform(
    objectId: string,
    sceneFromObjectRowMajor: readonly number[],
    frame: SceneDisplayFrame,
  ): boolean {
    const resident = this.#resident.get(objectId);
    if (resident === undefined) return false;
    const authored = composeDisplayFrame(frame, sceneFromObjectRowMajor);
    resident.motion?.reset();
    const next: Resident = {
      ...resident,
      object: Object.freeze({ ...resident.object, sceneFromObjectRowMajor }),
      authored,
    };
    this.#resident.set(objectId, next);
    applyRowMajorTransform(next.entity, authored);
    return true;
  }

  remove(objectId: string): boolean {
    const resident = this.#resident.get(objectId);
    if (resident === undefined) return false;
    this.#resident.delete(objectId);
    this.#dispose(resident);
    return true;
  }

  /**
   * Trigger, stop or reset. Returns the refusal when there is nothing to control, so the caller
   * can say so rather than leaving a pressed button with no visible effect.
   */
  control(objectId: string, action: BehaviourControl): { ok: true } | { ok: false; reason: string } {
    const resident = this.#resident.get(objectId);
    if (resident === undefined) {
      return Object.freeze({ ok: false as const, reason: 'That object is not in this world.' });
    }
    if (resident.motion === null) {
      return Object.freeze({
        ok: false as const,
        reason: 'This object carries no supported motion, so there is nothing to run.',
      });
    }
    if (action === 'trigger') resident.motion.trigger();
    else if (action === 'stop') resident.motion.stop();
    else resident.motion.reset();
    // Reset must land on the authored transform exactly, so it is re-applied from the authored
    // matrix rather than recomputed from the motion's offset.
    applyRowMajorTransform(
      resident.entity,
      motionTransform(resident.authored, resident.motion.offset),
    );
    return Object.freeze({ ok: true as const });
  }

  /**
   * Follow the region's residency, exactly as `sourceFirst` does.
   *
   * An authored object is drawn only where its region's body is. Without this it would keep
   * standing in a region that has fallen back to a stub, which is an object hanging in the air
   * over ground that is not being drawn: the one impression this whole placement path exists to
   * avoid. On the Map vantage nothing region-local is drawn at all.
   */
  setResidency(allocated: ReadonlyMap<IslandId, string>, map: boolean): void {
    for (const resident of this.#resident.values()) {
      resident.entity.enabled = !map && (allocated.get(resident.object.islandId) ?? 'stub') !== 'stub';
    }
  }

  /** One frame of motion. Objects with no behaviour, and stopped ones, cost one map iteration. */
  update(deltaSeconds: number): void {
    if (this.#destroyed) return;
    for (const resident of this.#resident.values()) {
      const motion = resident.motion;
      if (motion === null || motion.state !== 'running') continue;
      motion.advance(deltaSeconds);
      applyRowMajorTransform(resident.entity, motionTransform(resident.authored, motion.offset));
    }
  }

  destroy(): void {
    if (this.#destroyed) return;
    this.#destroyed = true;
    for (const resident of this.#resident.values()) this.#dispose(resident);
    this.#resident.clear();
  }

  #dispose(resident: Resident): void {
    resident.entity.destroy();
    resident.asset.unload();
    this.#app.assets.remove(resident.asset);
  }
}

/**
 * A row-major transform as PlayCanvas local TRS.
 *
 * The same decomposition `atlas-binding.ts` applies to a trained scene's placement, repeated here
 * rather than shared because the binding's copy is private to it and an exported one would be a
 * second public transform contract for the same three lines.
 */
function applyRowMajorTransform(entity: pc.Entity, m: readonly number[]): void {
  const scale = Math.hypot(m[0]!, m[4]!, m[8]!);
  const rotation = new pc.Mat4().set([
    m[0]! / scale, m[4]! / scale, m[8]! / scale, 0,
    m[1]! / scale, m[5]! / scale, m[9]! / scale, 0,
    m[2]! / scale, m[6]! / scale, m[10]! / scale, 0,
    0, 0, 0, 1,
  ]);
  entity.setLocalPosition(m[3]!, m[7]!, m[11]!);
  entity.setLocalRotation(new pc.Quat().setFromMat4(rotation));
  entity.setLocalScale(scale, scale, scale);
}
