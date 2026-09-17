import * as pc from 'playcanvas';
import type { TextureSetDigest, TextureSetManifest, TextureSetManifestEntry } from '@exulanica/atlas-core';
import {
  IDENTITY_NOT_STATED,
  MATERIAL_NONE_EXISTS,
  OwdError,
  absoluteSurfaceCoordinates,
  absoluteVertices,
  verifyOwd,
  type DecodedOwd,
  type DecodedProjection,
  type OwdHeader,
  type OwdRecord,
  type SurfaceOrientation,
} from '@exulanica/loom-tess/core';
import type { GeneratedTileAttachment, GeneratedTileHost, GeneratedTileMetrics, GeneratedTileMount } from './binding-contract.js';
import { applyTileEnvironment } from './environment.js';
import { TILE_LOOK_V1, type TileLook } from './look.js';
import { buildSurfaceMesh } from './surface-mesh.js';
import {
  TileTextureUploads,
  prepareTextureSet,
  surfaceUv,
  unavailableUv,
  type PreparedTextureSet,
  type TileMaterialReference,
} from './texture-materials.js';
import {
  rendererToTile,
  tileCapsule,
  tileNavigation,
  tileToRenderer,
  unsupportedFrame,
  type TileExtentMm,
  type TileNavigation,
  type Vec3,
} from './tile-navigation.js';

/**
 * One baked `.owd` tile, drawn.
 *
 * THE CONTAINER IS READ THROUGH TESS'S OWN CODE. `verifyOwd` decodes the layout and then bakes the
 * header's own records again, requiring every byte to match, so what is drawn is exactly what its
 * records say. There is no second reader here and nothing is repaired.
 *
 * WHAT IS DRAWN. Only `render_batch`, and only its drawn ranges, each exactly as stored. A drawn
 * range is textured when it cites a `surface_material` record that states its placement (version 2)
 * and whose texture set is pinned and verifies; its UVs come from the container's own surface
 * coordinates through `surfaceUv`. A drawn range whose material is `none-exists` (exact geometry no
 * material record dresses) is drawn, as the stated unavailable surface, and so is a range whose
 * material cannot be resolved; the reason is kept. An `unavailable` entry is geometry the
 * tessellator has not produced yet: it has no triangles and is listed with the needs tess stated.
 * A `halo` entry is context from a neighbouring record, never drawn and never listed. No vertex is
 * invented and no default mesh stands in for a missing one.
 *
 * WHAT IS KEPT FOR PICKING. Every triangle maps back to its record: `rangeAtTriangle` answers
 * "which record is this triangle", each range carries its record's extent, and `pick` answers both
 * for a ray.
 *
 * Every texture set a tile cites is fetched and verified while the tile loads, before the renderer
 * exists, so an attached tile is complete on its first frame.
 */

/** A drawn range whose material is `none-exists`: no surface_material record dresses it. */
export const MATERIAL_NONE_EXISTS_REASON = 'No surface_material record dresses this range: the tile states that none exists.';
export const MATERIAL_PLACEMENT_UNSTATED =
  'The cited surface_material is version 1, which does not state how its texture is placed; version 2 does.';

export type GeneratedTileRange =
  | {
      readonly record: number;
      readonly kind: string;
      /** The identity the record states, or null when it states none. */
      readonly identity: string | null;
      readonly state: 'drawn';
      readonly surface: 'textured' | 'unavailable';
      readonly orientation: SurfaceOrientation | null;
      readonly textureSetId: string | null;
      readonly reason: string | null;
      readonly firstTriangle: number;
      readonly triangleCount: number;
      readonly extentMm: TileExtentMm;
    }
  | {
      readonly record: number;
      readonly kind: string;
      readonly identity: string | null;
      readonly state: 'unavailable' | 'not_admitted';
      readonly reason: string;
      readonly needs: readonly string[];
    };

export type DrawnTileRange = Extract<GeneratedTileRange, { readonly state: 'drawn' }>;

export class GeneratedTileRefusal extends Error {
  override readonly name = 'GeneratedTileRefusal';
}

export interface GeneratedTileSources {
  readonly name: string;
  readonly bytes: Uint8Array;
  readonly manifest: TextureSetManifest;
  readonly fetchSet: (entry: TextureSetManifestEntry) => Promise<Uint8Array>;
  readonly look?: TileLook;
  /** The page's `crypto.subtle` by default; null refuses every tile. */
  readonly digest?: TextureSetDigest | null;
}

export interface TilePick {
  readonly range: DrawnTileRange;
  readonly triangle: number;
  /** Along the ray, in metres. */
  readonly distance: number;
}

export interface LoadedGeneratedTile extends GeneratedTileMount {
  readonly name: string;
  readonly header: OwdHeader;
  readonly look: TileLook;
  readonly ranges: readonly GeneratedTileRange[];
  readonly navigation: TileNavigation;
  /** The tile's bytes and every texture set it cites. */
  readonly transferredBytes: number;
  /** The record a render_batch triangle belongs to. */
  rangeAtTriangle(triangle: number): DrawnTileRange | null;
  /** The nearest drawn triangle along a renderer-space ray, and its record. */
  pick(origin: Vec3, direction: Vec3): TilePick | null;
}

function ambientDigest(): TextureSetDigest | null {
  const scope = globalThis as unknown as { readonly crypto?: { readonly subtle?: TextureSetDigest } };
  return scope.crypto?.subtle ?? null;
}

function hexOf(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

const integerField = (record: OwdRecord, name: string): number | null => {
  const value = record.fields[name];
  return typeof value === 'number' && Number.isSafeInteger(value) ? value : null;
};

/** How a cited material record places its texture, or why it cannot. */
function materialReference(record: OwdRecord): TileMaterialReference | string {
  const setId = record.fields['texture_set_id'];
  if (typeof setId !== 'string') return 'The cited surface_material names no texture set.';
  if (record.version !== 2) return MATERIAL_PLACEMENT_UNSTATED;
  const repeat = integerField(record, 'repeat_size_millionths');
  const rotation = integerField(record, 'uv_rotation_urad');
  const offsetU = integerField(record, 'uv_offset_u_mm');
  const offsetV = integerField(record, 'uv_offset_v_mm');
  if (repeat === null || rotation === null || offsetU === null || offsetV === null || repeat <= 0) {
    return 'The cited surface_material does not state its repeat size, rotation and offsets.';
  }
  return { textureSetId: setId, repeatSizeMillionths: repeat, rotationUrad: rotation, offsetUMm: offsetU, offsetVMm: offsetV };
}

interface Plan {
  readonly ranges: GeneratedTileRange[];
  /** The placement of every textured range, by record. */
  readonly references: Map<number, TileMaterialReference>;
  readonly prepared: Map<string, PreparedTextureSet>;
}

async function plan(
  decoded: DecodedOwd,
  render: DecodedProjection,
  sources: GeneratedTileSources,
  digest: TextureSetDigest,
): Promise<Plan> {
  const records = decoded.header.records;
  const references = new Map<number, TileMaterialReference>();
  const cited = new Map<number, string>();
  for (const entry of render.header.entries) {
    if (entry.state !== 'drawn') continue;
    const material = entry.material;
    // tess's decoder requires a material on every drawn range of a projection that carries surfaces.
    if (material === undefined) throw new GeneratedTileRefusal(`A render_batch range of record ${entry.record} states no material.`);
    if (material.state === MATERIAL_NONE_EXISTS) { cited.set(entry.record, MATERIAL_NONE_EXISTS_REASON); continue; }
    const reference = materialReference(records[material.record]!);
    if (typeof reference === 'string') cited.set(entry.record, reference);
    else references.set(entry.record, reference);
  }
  const setIds = [...new Set([...references.values()].map((reference) => reference.textureSetId))].sort();
  const prepared = new Map<string, PreparedTextureSet>();
  for (const result of await Promise.all(
    setIds.map((setId) => prepareTextureSet(sources.manifest, setId, sources.fetchSet, digest)),
  )) prepared.set(result.setId, result);

  const ranges: GeneratedTileRange[] = [];
  for (const entry of render.header.entries) {
    const record = records[entry.record]!;
    const identity = record.identity === IDENTITY_NOT_STATED ? null : record.identity;
    switch (entry.state) {
      case 'drawn': {
        const reference = references.get(entry.record);
        const set = reference === undefined ? undefined : prepared.get(reference.textureSetId);
        const refused = set?.state === 'refused' ? set.reason : null;
        if (refused !== null) references.delete(entry.record);
        ranges.push({
          record: entry.record,
          kind: record.kind,
          identity,
          state: 'drawn',
          surface: reference !== undefined && refused === null ? 'textured' : 'unavailable',
          orientation: entry.surface ?? null,
          textureSetId: reference?.textureSetId ?? null,
          reason: refused ?? cited.get(entry.record) ?? null,
          firstTriangle: entry.first_triangle,
          triangleCount: entry.triangle_count,
          extentMm: { min: entry.extent_mm.min, max: entry.extent_mm.max },
        });
        break;
      }
      case 'unavailable':
        ranges.push({
          record: entry.record, kind: record.kind, identity, state: 'unavailable', needs: entry.needs,
          reason: `Not drawn yet: its geometry waits on ${entry.needs.join(', ')}.`,
        });
        break;
      case 'not_admitted':
        ranges.push({
          record: entry.record, kind: record.kind, identity, state: 'not_admitted', needs: [],
          reason: 'Not drawn: its grammar does not admit render_batch.',
        });
        break;
      // Not a surface of this projection, or context from a neighbour: neither is drawn or listed.
      case 'not_in_projection':
      case 'halo':
        break;
      default:
        throw new GeneratedTileRefusal(`A render_batch entry has a state this runtime was not written for: ${String((entry as { state: unknown }).state)}.`);
    }
  }
  return { ranges, references, prepared };
}

function renderExtent(ranges: readonly GeneratedTileRange[]): TileExtentMm {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (const range of ranges) {
    if (range.state !== 'drawn') continue;
    for (let axis = 0; axis < 3; axis += 1) {
      min[axis] = Math.min(min[axis]!, range.extentMm.min[axis]!);
      max[axis] = Math.max(max[axis]!, range.extentMm.max[axis]!);
    }
  }
  if (!Number.isFinite(min[0])) throw new GeneratedTileRefusal('The tile draws nothing in render_batch.');
  return { min: [min[0]!, min[1]!, min[2]!], max: [max[0]!, max[1]!, max[2]!] };
}

/** Ray against an axis-aligned box, both in tile millimetres: the entry distance, or null. */
function rayBox(origin: Vec3, direction: Vec3, box: TileExtentMm): number | null {
  let near = 0;
  let far = Infinity;
  for (let axis = 0; axis < 3; axis += 1) {
    const d = direction[axis]!;
    const o = origin[axis]!;
    if (d === 0) {
      if (o < box.min[axis]! || o > box.max[axis]!) return null;
      continue;
    }
    const a = (box.min[axis]! - o) / d;
    const b = (box.max[axis]! - o) / d;
    near = Math.max(near, Math.min(a, b));
    far = Math.min(far, Math.max(a, b));
    if (near > far) return null;
  }
  return near;
}

/** Ray against a triangle (Moller and Trumbore), both sides, in tile millimetres. */
function rayTriangle(origin: Vec3, direction: Vec3, a: Vec3, b: Vec3, c: Vec3): number | null {
  const e1 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const e2 = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
  const p = [direction[1] * e2[2]! - direction[2] * e2[1]!, direction[2] * e2[0]! - direction[0] * e2[2]!, direction[0] * e2[1]! - direction[1] * e2[0]!];
  const det = e1[0]! * p[0]! + e1[1]! * p[1]! + e1[2]! * p[2]!;
  if (det === 0) return null;
  const t = [origin[0] - a[0], origin[1] - a[1], origin[2] - a[2]];
  const u = (t[0]! * p[0]! + t[1]! * p[1]! + t[2]! * p[2]!) / det;
  if (u < 0 || u > 1) return null;
  const q = [t[1]! * e1[2]! - t[2]! * e1[1]!, t[2]! * e1[0]! - t[0]! * e1[2]!, t[0]! * e1[1]! - t[1]! * e1[0]!];
  const v = (direction[0] * q[0]! + direction[1] * q[1]! + direction[2] * q[2]!) / det;
  if (v < 0 || u + v > 1) return null;
  const distance = (e2[0]! * q[0]! + e2[1]! * q[1]! + e2[2]! * q[2]!) / det;
  return distance >= 0 ? distance : null;
}

/**
 * Verify and read a baked tile, with every texture set it cites. Refuses, with a reason, rather
 * than drawing anything unchecked.
 */
export async function loadGeneratedTile(sources: GeneratedTileSources): Promise<LoadedGeneratedTile> {
  const digest = sources.digest === undefined ? ambientDigest() : sources.digest;
  if (digest === null) {
    throw new GeneratedTileRefusal('This page has no crypto.subtle, so no tile can be checked against its own records.');
  }
  const sha256 = async (bytes: Uint8Array): Promise<string> => hexOf(await digest.digest('SHA-256', bytes));
  let decoded: DecodedOwd;
  try {
    decoded = await verifyOwd(sources.bytes, sha256);
  } catch (error) {
    if (error instanceof OwdError) throw new GeneratedTileRefusal(`Tile ${sources.name} refused: ${error.message}`);
    throw error;
  }
  const frame = unsupportedFrame(decoded.header.grammars);
  if (frame !== null) throw new GeneratedTileRefusal(`Tile ${sources.name} refused: ${frame}`);
  const capsule = tileCapsule(decoded.header.grammars);
  if (typeof capsule === 'string') throw new GeneratedTileRefusal(`Tile ${sources.name} refused: ${capsule}`);
  const render = decoded.projections.find((projection) => projection.header.name === 'render_batch');
  if (render === undefined) throw new GeneratedTileRefusal(`Tile ${sources.name} carries no render_batch.`);
  const surface = absoluteSurfaceCoordinates(render);
  if (surface === undefined) throw new GeneratedTileRefusal(`Tile ${sources.name} carries no surface coordinates.`);
  const { ranges, references, prepared } = await plan(decoded, render, sources, digest);
  const navigation = tileNavigation(
    decoded.projections.find((projection) => projection.header.name === 'nav_envelope'),
    renderExtent(ranges),
    capsule,
  );
  const drawn = ranges.filter((range): range is DrawnTileRange => range.state === 'drawn')
    .sort((a, b) => a.firstTriangle - b.firstTriangle);
  const vertices = absoluteVertices(render);
  const look = sources.look ?? TILE_LOOK_V1;
  let setBytes = 0;
  for (const set of prepared.values()) if (set.state === 'decoded') setBytes += set.transferredBytes;

  const rangeAtTriangle = (triangle: number): DrawnTileRange | null => {
    let low = 0;
    let high = drawn.length - 1;
    while (low <= high) {
      const middle = (low + high) >> 1;
      const range = drawn[middle]!;
      if (triangle < range.firstTriangle) high = middle - 1;
      else if (triangle >= range.firstTriangle + range.triangleCount) low = middle + 1;
      else return range;
    }
    return null;
  };

  const tile: LoadedGeneratedTile = {
    name: sources.name,
    header: decoded.header,
    look,
    ranges,
    navigation,
    navigationWorld: navigation.world,
    start: navigation.start,
    transferredBytes: sources.bytes.byteLength + setBytes,
    rangeAtTriangle,
    pick(origin: Vec3, direction: Vec3): TilePick | null {
      const o = rendererToTile(origin[0], origin[1], origin[2]);
      // A direction is rotated, not translated or scaled: millimetres per metre cancel in the distance.
      const d = rendererToTile(direction[0], direction[1], direction[2]);
      const at = (vertex: number): Vec3 => [vertices[vertex * 3]!, vertices[vertex * 3 + 1]!, vertices[vertex * 3 + 2]!];
      let best: TilePick | null = null;
      for (const range of drawn) {
        const entry = rayBox(o, d, range.extentMm);
        if (entry === null || (best !== null && entry > best.distance)) continue;
        for (let triangle = range.firstTriangle; triangle < range.firstTriangle + range.triangleCount; triangle += 1) {
          const hit = rayTriangle(o, d, at(render.index[triangle * 3]!), at(render.index[triangle * 3 + 1]!), at(render.index[triangle * 3 + 2]!));
          if (hit !== null && (best === null || hit < best.distance)) best = { range, triangle, distance: hit };
        }
      }
      return best;
    },
    attach(host: GeneratedTileHost): GeneratedTileAttachment {
      return attachTile(host, tile, render, surface, references, prepared);
    },
  };
  return tile;
}

function attachTile(
  host: GeneratedTileHost,
  tile: LoadedGeneratedTile,
  render: DecodedProjection,
  surface: Float64Array,
  references: ReadonlyMap<number, TileMaterialReference>,
  prepared: ReadonlyMap<string, PreparedTextureSet>,
): GeneratedTileAttachment {
  const device = host.app.graphicsDevice;
  const look = tile.look;
  const environment = applyTileEnvironment(host.app, host.camera, look);
  const uploads = new TileTextureUploads(device, look);
  const root = new pc.Entity(`generated-tile:${tile.name}`);
  const origin = render.header.origin_mm;
  if (origin.length === 3) root.setLocalPosition(...tileToRenderer(origin[0], origin[1], origin[2]));
  host.environmentRoot.addChild(root);

  // One batch per texture set, and one for every unavailable surface. Each vertex carries its final
  // UV: a textured range is placed by the record it cites, an unavailable one by the pattern's size.
  interface Batch { positions: number[]; normals: number[]; uvs: number[]; indices: number[]; material: pc.Material }
  const batches = new Map<string, Batch>();
  let triangles = 0;
  for (const range of tile.ranges) {
    if (range.state !== 'drawn') continue;
    const key = range.surface === 'textured' ? range.textureSetId! : '';
    let batch = batches.get(key);
    if (batch === undefined) {
      let material: pc.Material = uploads.unavailableMaterial;
      if (key !== '') {
        const resolution = uploads.adopt(prepared.get(key)!);
        if (resolution.state !== 'available') throw new Error(`Texture set ${key} was prepared and then refused`);
        material = resolution.material;
      }
      batch = { positions: [], normals: [], uvs: [], indices: [], material };
      batches.set(key, batch);
    }
    const set = key === '' ? null : prepared.get(key)!;
    const reference = references.get(range.record);
    const place = (s: number, t: number): readonly [number, number] =>
      set !== null && set.state === 'decoded' && reference !== undefined
        ? surfaceUv(s, t, reference, set.set.entry)
        : unavailableUv(s, t, look, range.orientation ?? 'vertical');
    const first = batch.positions.length / 3;
    const remap = new Map<number, number>();
    const local: number[] = [];
    const rangeIndices: number[] = [];
    for (let corner = range.firstTriangle * 3; corner < (range.firstTriangle + range.triangleCount) * 3; corner += 1) {
      const vertex = render.index[corner]!;
      let mapped = remap.get(vertex);
      if (mapped === undefined) {
        mapped = local.length / 3;
        remap.set(vertex, mapped);
        // Payload metres from the origin, rotated into the renderer frame: (x, z, -y).
        local.push(render.position[vertex * 3]!, render.position[vertex * 3 + 2]!, -render.position[vertex * 3 + 1]!);
        batch.uvs.push(...place(surface[vertex * 2]!, surface[vertex * 2 + 1]!));
      }
      rangeIndices.push(mapped);
    }
    batch.positions.push(...local);
    batch.normals.push(...pc.calculateNormals(local, rangeIndices));
    for (const index of rangeIndices) batch.indices.push(first + index);
    triangles += range.triangleCount;
  }

  const meshes: pc.Mesh[] = [];
  const keys = [...batches.keys()].sort();
  for (const key of keys) {
    const batch = batches.get(key)!;
    // The UV is already final, so the builder is handed it as the surface pair and passes it on.
    const mesh = buildSurfaceMesh(device, { ...batch, surfaceMm: batch.uvs }, (u, v) => [u, v]);
    meshes.push(mesh);
    const entity = new pc.Entity(key === '' ? 'generated-tile:unavailable-surfaces' : `generated-tile:${key}`);
    entity.addComponent('render', {
      meshInstances: [new pc.MeshInstance(mesh, batch.material, entity)],
      castShadows: true,
      receiveShadows: key !== '',
    });
    root.addChild(entity);
  }

  const metrics: GeneratedTileMetrics = {
    tileName: tile.name,
    triangles,
    drawBatches: keys.length,
    transferredBytes: tile.transferredBytes,
    decodedTextureBytes: uploads.decodedTextureBytes,
    unavailableSurfaces: tile.ranges.filter((range) => range.state === 'drawn' && range.surface === 'unavailable').length,
    lookId: look.id,
    lookVersion: look.version,
  };
  let disposed = false;
  return {
    metrics,
    dispose() {
      if (disposed) return;
      disposed = true;
      root.destroy();
      for (const mesh of meshes) mesh.destroy();
      uploads.destroy();
      environment.dispose();
    },
  };
}
