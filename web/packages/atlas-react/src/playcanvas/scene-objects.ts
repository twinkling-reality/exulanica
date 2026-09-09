/**
 * Authored objects: a verified GLB container, placed region-local, and one bounded motion over it.
 *
 * This is the renderer half of product-direction.md's first milestone rows 3 and 4, and the
 * consumer of the `/world/versions` plane in `docs/world-objects-contract.md`. Until it existed
 * the renderer loaded exactly two things, a point map and a verified SOG splat, and both are
 * *recovered* geometry. An authored object is the first thing in the world that was never
 * photographed, so every decision here is about keeping those two categories apart while letting
 * them share a floor.
 *
 * **The same boundary as `scene-splats.ts`, for the same reason.** A container is decoded from an
 * `ArrayBuffer` this module fetched through the authenticated transport and checked against the
 * digest the registry row named; the loader is handed bytes, never a URL. `createSceneSplatAsset`
 * exists because PlayCanvas's SOG decoder would otherwise fetch textures the caller never
 * authorized, and `createObjectContainerAsset` exists because PlayCanvas's glTF parser will do
 * exactly the same thing for a `buffers[].uri` or an `images[].uri`
 * (`playcanvas@2.21.4` `loadBuffers` and `createImages` both call `http.get` on a non-data URI).
 * So the container is validated BEFORE the parser sees it, and one carrying an external reference
 * is refused rather than loaded with a texture missing.
 *
 * **The digest is required here, not optional.** `fetchAuthenticatedAsset` checks a SHA-256 when
 * the descriptor carries one and skips the check when it does not. For an authored object there is
 * no descriptor without one: the contract says "the asset reference is a content digest, never a
 * name and never a URL", and `content_sha256` on the embedded registry row IS the object's
 * reference. This module refuses a reference with no digest, refuses a byte count that disagrees,
 * and refuses outright when `crypto.subtle` is unavailable, which is the same trade
 * `geometry-api.ts` refuses to make for reconstruction bytes.
 *
 * **The transform is region-local fixed point, and that is the whole placement story.** The
 * contract poses an object against its region in millimetres, microradians and thousandths, and
 * says why: a reviewed recomposition may move a whole region, and "region-local means the move
 * carries them, which is what a person who placed a lantern inside a room means by placing it
 * there." The island entity's own child space IS that region frame, so an object's transform is
 * applied directly to a child of it. There is deliberately no display-frame composition on this
 * path: the display frame is how RECOVERED geometry gets into region-local space, and by the time
 * an authored object is placed, that space is already the one the geometry stands in.
 *
 * **Atlas space is converted to a region frame HERE and nowhere else.** `coords.ts` says there is
 * no `atlasToLocal` and there must never be one, because an island's atlas position is a layout
 * artifact rather than a place (risk R-48). Placing an object where a visitor is standing needs
 * that conversion anyway, so it lives in the renderer binding, which is the one layer already
 * permitted to read atlas positions as geometry, and it produces a PRESENTATION transform rather
 * than an answer to "where in the capture is this".
 *
 * **Nothing here writes.** The runtime draws, moves and animates objects a surface has already
 * committed through the confirmation surface and the world-objects client. Trigger, stop and reset
 * are runtime state and are deliberately not persisted; the contract says so in as many words.
 */

import * as pc from 'playcanvas';
import {
  BEHAVIOUR_REGISTRY,
  BoundedMotion,
  boundedPathOf,
  motionTransform,
  type CameraPose,
  type IslandId,
  type IslandPlacement,
} from '@exulanica/atlas-core';

import { fetchAuthenticatedAsset, type AuthenticatedAssetFetchOptions } from './physical-residency.js';

/** The only media type an authored object may name. A file extension is not a media type. */
export const AUTHORED_OBJECT_MEDIA_TYPE = 'model/gltf-binary';

/** How far in front of the visitor a placement lands when no anchor is engaged, in millimetres. */
export const DEFAULT_PLACEMENT_DISTANCE_MM = 2500;

/** The contract's fixed-point scales, in one place so nothing has to remember them twice. */
export const MM_PER_METRE = 1000;
export const MICRORADIANS_PER_RADIAN = 1_000_000;
export const SCALE_MILLI_UNIT = 1000;

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

/** The registry row an object embeds, reduced to what the renderer needs to fetch and check. */
export interface AuthoredObjectAssetReference {
  readonly assetKey: string;
  readonly mediaType: string;
  readonly contentSha256: string;
  readonly byteSize: number;
}

/** A region-local pose in the contract's own fixed-point units. */
export interface RegionPose {
  readonly xMm: number;
  readonly yMm: number;
  readonly zMm: number;
  readonly yawMicroradians: number;
  readonly scaleMilli: number;
}

export interface AuthoredObjectBehaviour {
  readonly behaviourKey: string;
  readonly behaviourVersion: number;
  readonly parameters: unknown;
}

export interface PlacedAuthoredObject {
  readonly objectId: string;
  /** The region this world draws the object in, resolved from the contract's `region_id`. */
  readonly islandId: IslandId;
  readonly asset: AuthoredObjectAssetReference;
  readonly transform: RegionPose;
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
 *   a worse version of the fetch this whole boundary exists to prevent.
 * - any other `extensionsRequired`. A required extension this build has not reviewed either
 *   changes what the bytes mean or is dropped silently, and a silently dropped mesh renders an
 *   authored object as nothing at all rather than as a refusal.
 *
 * A data URI is not an external reference and would be safe to allow. It is refused anyway: a
 * self-contained GLB puts its buffer in the BIN chunk, so a data URI here means the container was
 * produced by a path this build has not seen, and admitting it would mean the byte count in the
 * registry row no longer bounds what gets decoded. The three reviewed assets
 * `exulanica.world.assets` generates carry no `uri`, no images and no extensions at all.
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
    const decoded = new TextDecoder('utf-8', { fatal: true })
      .decode(new Uint8Array(bytes, json.start, json.length));
    const parsed: unknown = JSON.parse(decoded);
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

/** The shape `geometry-api.ts` requires of a reconstruction path, for the same reason. */
export function safeObjectAssetPath(value: string): boolean {
  return value.startsWith('/world/assets/')
    && !value.includes('://')
    && !value.includes('?')
    && !value.includes('#');
}

/** Where the reviewed bytes for one asset key live. Derived, never taken from the wire. */
export function objectAssetBytesPath(assetKey: string): string {
  return `/world/assets/${encodeURIComponent(assetKey)}/bytes`;
}

/**
 * Authenticated, digest-verified container bytes.
 *
 * The hash is checked by `fetchAuthenticatedAsset` against the REGISTRY ROW, never against the
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
  if (reference.mediaType !== AUTHORED_OBJECT_MEDIA_TYPE) {
    throw new TypeError(`“${String(reference.mediaType)}” is not a container this build can open`);
  }
  const path = objectAssetBytesPath(reference.assetKey);
  if (!safeObjectAssetPath(path)) {
    throw new TypeError('An authored object asset must be read from a local authenticated path');
  }
  if (!/^[0-9a-f]{64}$/.test(reference.contentSha256)) {
    throw new TypeError('An authored object needs a SHA-256 in the registry before it can be loaded');
  }
  if (!Number.isSafeInteger(reference.byteSize) || reference.byteSize <= 0) {
    throw new TypeError('An authored object needs a byte count in the registry before it can be loaded');
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
      path,
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
  assetKey: string,
  bytes: ArrayBuffer,
): Promise<pc.Asset> {
  validateGlbContainer(bytes);
  const filename = `${assetKey}.glb`;
  const asset = new pc.Asset(`authored-object:${assetKey}`, 'container', {
    url: `verified-object/${filename}`, filename, contents: bytes,
  });
  app.assets.add(asset);
  let timeout: ReturnType<typeof globalThis.setTimeout> | undefined;
  try {
    await new Promise<void>((resolve, reject) => {
      timeout = globalThis.setTimeout(() => reject(new Error('Authored object decoding timed out')), 30_000);
      asset.once('load', () => resolve());
      // `AssetRegistry` fires this with a plain STRING when no handler is registered for the
      // type. Rejecting with the raw value would reach the caller's `instanceof Error` branch as
      // false and turn a registration fault into a generic decoder sentence.
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

/**
 * An atlas-space point, read as a position in a region's own frame, in millimetres.
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
export function regionPointFromAtlas(
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
  return Object.freeze([
    (c * dx + s * dz) * MM_PER_METRE,
    dy * MM_PER_METRE,
    (-s * dx + c * dz) * MM_PER_METRE,
  ] as [number, number, number]);
}

/** Yaw is stored as a non-negative microradian angle, so a westward facing wraps rather than signs. */
export function yawMicroradiansOf(radians: number): number {
  if (!Number.isFinite(radians)) return 0;
  const turn = 2 * Math.PI;
  const wrapped = ((radians % turn) + turn) % turn;
  return Math.min(
    Math.round(wrapped * MICRORADIANS_PER_RADIAN),
    Math.round(turn * MICRORADIANS_PER_RADIAN),
  );
}

/**
 * Where a placement lands when the visitor has engaged nothing: a step in front of them, on the
 * region's ground.
 *
 * `groundMm` is the height that counts as the ground, and the caller supplies it because only the
 * caller knows which display frame its region has. With a frame derived from recovered cameras the
 * answer is `0`: that is exactly where `display-frame.ts` put the low quantile of the geometry's
 * bounds, and region-local space is where that frame delivers it. With the IDENTITY frame it is
 * not, and this is the case the browser check found. A scene with no recovered cameras gets the
 * identity frame, whose `y = 0` is the scene's own arbitrary origin; an object placed there sinks
 * under the floor the visitor is standing on and is never seen. Passing the visitor's own foot
 * height instead keeps the object where they are looking, and the surface has to stop claiming it
 * stands on measured ground, because it does not.
 *
 * The facing is the visitor's own, so a placed object faces the person who placed it.
 */
export function placementPoseBeforeVisitor(
  placement: IslandPlacement,
  pose: CameraPose,
  distanceMm: number = DEFAULT_PLACEMENT_DISTANCE_MM,
  groundMm = 0,
): RegionPose {
  const local = regionPointFromAtlas(
    placement,
    [pose.position.x, pose.position.y, pose.position.z],
  );
  const heading = regionPointFromAtlas(placement, [
    pose.position.x + pose.forward.x,
    pose.position.y + pose.forward.y,
    pose.position.z + pose.forward.z,
  ]);
  let fx = heading[0] - local[0];
  let fz = heading[2] - local[2];
  const planar = Math.hypot(fx, fz);
  // Looking straight up or down leaves no horizontal heading to step along; face region -Z.
  if (planar < 1e-6) { fx = 0; fz = -1; } else { fx /= planar; fz /= planar; }
  return Object.freeze({
    xMm: Math.round(local[0] + fx * distanceMm),
    yMm: Math.round(groundMm),
    zMm: Math.round(local[2] + fz * distanceMm),
    yawMicroradians: yawMicroradiansOf(Math.atan2(fx, fz)),
    scaleMilli: SCALE_MILLI_UNIT,
  });
}

/** Where a placement lands on an engaged anchor: at its foot, facing the visitor. */
export function placementPoseAtAtlasPoint(
  placement: IslandPlacement,
  atlas: readonly [number, number, number],
  pose: CameraPose,
  groundMm = 0,
): RegionPose {
  const target = regionPointFromAtlas(placement, atlas);
  const viewer = regionPointFromAtlas(
    placement,
    [pose.position.x, pose.position.y, pose.position.z],
  );
  const dx = viewer[0] - target[0];
  const dz = viewer[2] - target[2];
  const planar = Math.hypot(dx, dz);
  return Object.freeze({
    xMm: Math.round(target[0]),
    yMm: Math.round(groundMm),
    zMm: Math.round(target[2]),
    yawMicroradians: planar < 1e-6 ? 0 : yawMicroradiansOf(Math.atan2(dx / planar, dz / planar)),
    scaleMilli: SCALE_MILLI_UNIT,
  });
}

/**
 * One region pose displaced, still a legal region pose.
 *
 * Every field stays a whole number, because the wire's are: "No IEEE-754 value reaches a digest."
 * A nudge that produced 1200.0000001 mm would be refused at the transport edge with a message
 * about strict integers, and rounding here means a person's key press moves the object by a
 * millimetre-exact amount they can take back by pressing the other key.
 */
export function nudgedPose(
  pose: RegionPose,
  delta: {
    readonly xMm?: number;
    readonly yMm?: number;
    readonly zMm?: number;
    readonly yaw?: number;
  },
): RegionPose {
  return Object.freeze({
    ...pose,
    xMm: pose.xMm + Math.round(delta.xMm ?? 0),
    yMm: pose.yMm + Math.round(delta.yMm ?? 0),
    zMm: pose.zMm + Math.round(delta.zMm ?? 0),
    yawMicroradians: delta.yaw === undefined
      ? pose.yawMicroradians
      : yawMicroradiansOf(pose.yawMicroradians / MICRORADIANS_PER_RADIAN + delta.yaw),
  });
}

// -- the runtime -------------------------------------------------------------------------------

interface Resident {
  readonly object: PlacedAuthoredObject;
  readonly asset: pc.Asset;
  readonly entity: pc.Entity;
  /** Authored translation in millimetres. Held so reset can restore it without arithmetic. */
  readonly authoredMm: readonly [number, number, number];
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
   * Put a verified container in a region, and attach its behaviour if this build can run it.
   *
   * A behaviour this build cannot run does NOT stop the placement. The object is real, its
   * geometry verified, and refusing to draw it because a motion could not be resolved would hide a
   * successful edit behind a failed one. It comes back as a notice instead, and the caller is
   * required by the milestone to put that notice on the status line.
   */
  async place(object: PlacedAuthoredObject, bytes: ArrayBuffer): Promise<ObjectPlacementOutcome> {
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
        object.behaviour.behaviourKey,
        object.behaviour.behaviourVersion,
        object.behaviour.parameters,
      );
      if (read.ok) {
        motion = new BoundedMotion(boundedPathOf(read.parameters));
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

    const asset = await createObjectContainerAsset(this.#app, object.asset.assetKey, bytes);
    let entity: pc.Entity | undefined;
    try {
      const resource = asset.resource as pc.ContainerResource;
      entity = resource.instantiateRenderEntity({});
      if (entity === null || entity === undefined) {
        throw new TypeError('This container holds nothing that can be drawn');
      }
      entity.name = `authored-object:${object.objectId}`;
      const authoredMm = translationOf(object.transform);
      applyRegionPose(entity, object.transform, authoredMm);
      root.addChild(entity);
      this.#resident.set(object.objectId, { object, asset, entity, authoredMm, motion });
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

  /** Move a resident object to a new authored pose. Its motion returns to rest, exactly. */
  setTransform(objectId: string, transform: RegionPose): boolean {
    const resident = this.#resident.get(objectId);
    if (resident === undefined) return false;
    resident.motion?.reset();
    const authoredMm = translationOf(transform);
    const next: Resident = {
      ...resident,
      object: Object.freeze({ ...resident.object, transform }),
      authoredMm,
    };
    this.#resident.set(objectId, next);
    applyRegionPose(next.entity, transform, authoredMm);
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
        reason: 'This object carries no motion this build can run, so there is nothing to start.',
      });
    }
    if (action === 'trigger') resident.motion.trigger();
    else if (action === 'stop') resident.motion.stop();
    else resident.motion.reset();
    // Reset must land on the authored transform exactly, so it is re-applied from the authored
    // millimetres rather than recomputed from the motion's offset.
    applyRegionPose(
      resident.entity,
      resident.object.transform,
      motionTransform(resident.authoredMm, resident.motion.offset),
    );
    return Object.freeze({ ok: true as const });
  }

  /** One frame of motion. Objects with no behaviour, and stopped ones, cost one map iteration. */
  update(deltaSeconds: number): void {
    if (this.#destroyed) return;
    for (const resident of this.#resident.values()) {
      const motion = resident.motion;
      if (motion === null || motion.state !== 'running') continue;
      motion.advance(deltaSeconds * 1000);
      applyRegionPose(
        resident.entity,
        resident.object.transform,
        motionTransform(resident.authoredMm, motion.offset),
      );
    }
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

function translationOf(pose: RegionPose): readonly [number, number, number] {
  return Object.freeze([pose.xMm, pose.yMm, pose.zMm] as [number, number, number]);
}

/**
 * A region-local fixed-point pose as PlayCanvas local TRS, under the region's own entity.
 *
 * The translation is passed separately from the pose because the motion displaces it and the pose
 * does not change: keeping the authored pose as the source of yaw and scale means a running object
 * cannot drift in either.
 */
function applyRegionPose(
  entity: pc.Entity,
  pose: RegionPose,
  translationMm: readonly [number, number, number],
): void {
  entity.setLocalPosition(
    translationMm[0] / MM_PER_METRE,
    translationMm[1] / MM_PER_METRE,
    translationMm[2] / MM_PER_METRE,
  );
  entity.setLocalEulerAngles(
    0,
    (pose.yawMicroradians / MICRORADIANS_PER_RADIAN) * (180 / Math.PI),
    0,
  );
  const scale = pose.scaleMilli / SCALE_MILLI_UNIT;
  entity.setLocalScale(scale, scale, scale);
}
