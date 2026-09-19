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
  type DrawnEntry,
  type MaterialRef,
  type OwdHeader,
  type OwdRecord,
  type SurfaceOrientation,
} from '@exulanica/loom-tess/core';
import type { GeneratedTileAttachment, GeneratedTileHost, GeneratedTileMetrics, GeneratedTileMount } from './binding-contract.js';
import { applyTileEnvironment } from './environment.js';
import { obstructionRings, type ObstructionRings } from './obstruction-rings.js';
import { composedObstructionRings, type StatingTile } from './walk-world.js';
import { TILE_LOOK_V1, type TileLook } from './look.js';
import { buildSurfaceMesh } from './surface-mesh.js';
import {
  TileTextureUploads,
  castsShadow,
  drawBucket,
  prepareTextureSet,
  surfaceUv,
  unavailableUv,
  undrawnClassReason,
  type PreparedTextureSet,
  type TileMaterialReference,
} from './texture-materials.js';
import {
  rendererToTile,
  tileCapsule,
  tileNavigation,
  type NavigationTile,
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
 * WHAT IS DRAWN. Only `render_batch`, and only its drawn entries, each exactly as stored. A drawn
 * entry is made of surfaces (owd/3): contiguous runs of its triangles, sharing no vertex, each with
 * one grammar role, one material and one orientation. A surface is textured when its material is a
 * `surface_material` record that states its placement (version 2) and whose texture set is pinned and
 * verifies; its UVs come from the container's own surface coordinates through `surfaceUv`. A surface
 * whose material is `none-exists` (exact geometry no material record dresses) is drawn, as the stated
 * unavailable surface, and so is a surface whose material cannot be resolved or whose set's material
 * class this runtime does not draw; the reason is kept.
 * Surfaces are batched by what they are drawn with, so a set is still one draw. An `unavailable`
 * entry is geometry the tessellator has not produced yet: it has no triangles and is listed with the
 * needs tess stated.
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

/** A surface whose material is `none-exists`: no surface_material record dresses its record's role. */
export const MATERIAL_NONE_EXISTS_REASON = 'No surface_material record dresses this surface: the tile states that none exists.';
export const MATERIAL_PLACEMENT_UNSTATED =
  'The cited surface_material is version 1, which does not state how its texture is placed; version 2 does.';

/**
 * One surface of a drawn record: a contiguous run of its triangles with one grammar role, one material
 * and one orientation (a kerb's vertical face and its horizontal top are two). Drawing is per surface;
 * identity, picking and selection stay with the record that holds it.
 */
export interface GeneratedTileSurface {
  readonly role: string;
  readonly orientation: SurfaceOrientation;
  readonly state: 'textured' | 'unavailable';
  readonly textureSetId: string | null;
  /** Why the surface is drawn as unavailable, or null when it is textured. */
  readonly reason: string | null;
  readonly firstVertex: number;
  readonly vertexCount: number;
  readonly firstTriangle: number;
  readonly triangleCount: number;
}

export type GeneratedTileRange =
  | {
      readonly record: number;
      readonly kind: string;
      /** The identity the record states, or null when it states none. */
      readonly identity: string | null;
      readonly state: 'drawn';
      readonly firstTriangle: number;
      readonly triangleCount: number;
      readonly extentMm: TileExtentMm;
      /** Its surfaces in triangle order, covering the record's triangles exactly. */
      readonly surfaces: readonly GeneratedTileSurface[];
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
  /**
   * NEIGHBOURING TILES WHOSE GROUND THIS WALK MAY REACH, as whole containers.
   *
   * A tile is 128,000 mm across and the route rule asks for 125,000 plus a 6,000 stopping margin, so
   * ground for a whole route does not fit on the tile a route is laid on. These are composed into
   * the navigation world and into nothing else: NOT drawn, NOT picked, NOT measured, and no record
   * of theirs reaches the page's list of what is undressed. Each is verified against its own digest
   * exactly as the tile is, because it is ground a person stands on.
   *
   * ONLY THE `nav_envelope` OF EACH IS READ. A caller that can serve a container's sections
   * separately should serve only those: measured on the corridor, a neighbour's navigation is
   * 1,969,322 bytes against 11,630,504 for its container, and the float `position` section is
   * exactly fround(position_mm / 1000) so it need not be sent at all.
   */
  readonly neighbours?: readonly NeighbourTileSource[];
}

/** One neighbouring tile's container, named so a refusal can say which tile was refused. */
export interface NeighbourTileSource {
  readonly name: string;
  readonly bytes: Uint8Array;
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
  /**
   * The route obstruction rings this tile states, and any it refused.
   *
   * Stated so a caller can report the count and the records it came from rather than counting the
   * navigation world's obstacles and hoping they are the same thing. A refusal carries its reason,
   * because a set that quietly got smaller is the thing nobody notices.
   */
  readonly routeObstructions: ObstructionRings;
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

/** One surface of a drawn entry as tess's container states it. */
type DrawnSurface = NonNullable<DrawnEntry['surfaces']>[number];

/** Where a textured surface's texture goes: the record's placement and the set it names. */
export interface SurfacePlacement {
  readonly reference: TileMaterialReference;
  readonly entry: TextureSetManifestEntry;
}

interface Plan {
  readonly ranges: GeneratedTileRange[];
  /** The placement of every textured surface. */
  readonly placements: Map<GeneratedTileSurface, SurfacePlacement>;
  readonly prepared: Map<string, PreparedTextureSet>;
}

async function plan(
  decoded: DecodedOwd,
  render: DecodedProjection,
  sources: GeneratedTileSources,
  digest: TextureSetDigest,
): Promise<Plan> {
  const records = decoded.header.records;
  const readMaterial = (material: MaterialRef): TileMaterialReference | string =>
    material.state === MATERIAL_NONE_EXISTS ? MATERIAL_NONE_EXISTS_REASON : materialReference(records[material.record]!);
  const surfacesOf = (entry: DrawnEntry): readonly DrawnSurface[] => {
    // tess's decoder requires surfaces on every drawn entry of a projection that carries surfaces.
    if (entry.surfaces === undefined || entry.surfaces.length === 0) {
      throw new GeneratedTileRefusal(`The render_batch entry of record ${entry.record} states no surfaces.`);
    }
    return entry.surfaces;
  };
  const setIds = new Set<string>();
  for (const entry of render.header.entries) {
    if (entry.state !== 'drawn') continue;
    for (const surface of surfacesOf(entry)) {
      const read = readMaterial(surface.material);
      if (typeof read !== 'string') setIds.add(read.textureSetId);
    }
  }
  const prepared = new Map<string, PreparedTextureSet>();
  for (const result of await Promise.all(
    [...setIds].sort().map((setId) => prepareTextureSet(sources.manifest, setId, sources.fetchSet, digest)),
  )) prepared.set(result.setId, result);

  const placements = new Map<GeneratedTileSurface, SurfacePlacement>();
  const ranges: GeneratedTileRange[] = [];
  for (const entry of render.header.entries) {
    const record = records[entry.record]!;
    const identity = record.identity === IDENTITY_NOT_STATED ? null : record.identity;
    switch (entry.state) {
      case 'drawn': {
        const surfaces = surfacesOf(entry).map((surface): GeneratedTileSurface => {
          const read = readMaterial(surface.material);
          const set = typeof read === 'string' ? undefined : prepared.get(read.textureSetId);
          const reason = typeof read === 'string'
            ? read
            : set === undefined
              ? `Texture set ${read.textureSetId} was not prepared.`
              // A set that is refused, or whose material class this runtime does not draw, is unavailable.
              : set.state === 'refused' ? set.reason : undrawnClassReason(set.set);
          const drawn: GeneratedTileSurface = {
            role: surface.role,
            orientation: surface.orientation,
            state: reason === null ? 'textured' : 'unavailable',
            textureSetId: typeof read === 'string' ? null : read.textureSetId,
            reason,
            firstVertex: surface.first_vertex,
            vertexCount: surface.vertex_count,
            firstTriangle: surface.first_triangle,
            triangleCount: surface.triangle_count,
          };
          if (typeof read !== 'string' && set?.state === 'decoded' && reason === null) {
            placements.set(drawn, { reference: read, entry: set.set.entry });
          }
          return drawn;
        });
        ranges.push({
          record: entry.record,
          kind: record.kind,
          identity,
          state: 'drawn',
          firstTriangle: entry.first_triangle,
          triangleCount: entry.triangle_count,
          extentMm: { min: entry.extent_mm.min, max: entry.extent_mm.max },
          surfaces,
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
  return { ranges, placements, prepared };
}

/** One draw's geometry, ready for `buildSurfaceMesh`: renderer-frame metres, normals, final UVs. */
export interface TileSurfaceBatch {
  /** The texture set every surface in the batch is drawn with, or '' for the unavailable surfaces. */
  readonly key: string;
  readonly positions: number[];
  readonly normals: number[];
  readonly uvs: number[];
  readonly indices: number[];
  readonly triangles: number;
}

/**
 * Every drawn surface of a tile, batched by what it is drawn with: one batch per texture set, and one
 * for all unavailable surfaces, in key order. A textured surface is placed by its own material record
 * through `surfaceUv`; an unavailable one by the pattern's size and its own orientation. Normals are
 * computed per surface, over that surface's own triangles, so a kerb's vertical face never bends the
 * normals of its horizontal top. Positions are the payload's metres from the projection origin,
 * rotated into the renderer frame as (x, z, -y).
 */
export function batchTileSurfaces(
  render: Pick<DecodedProjection, 'position' | 'index'>,
  surfaceMm: ArrayLike<number>,
  ranges: readonly GeneratedTileRange[],
  placements: ReadonlyMap<GeneratedTileSurface, SurfacePlacement>,
  look: TileLook,
): TileSurfaceBatch[] {
  const batches = new Map<string, { -readonly [K in keyof TileSurfaceBatch]: TileSurfaceBatch[K] }>();
  for (const range of ranges) {
    if (range.state !== 'drawn') continue;
    for (const surface of range.surfaces) {
      const placement = placements.get(surface);
      if (surface.state === 'textured' && placement === undefined) {
        throw new Error(`The ${surface.role} surface of record ${range.record} is textured and has no placement`);
      }
      const key = placement === undefined ? '' : placement.entry.setId;
      let batch = batches.get(key);
      if (batch === undefined) {
        batch = { key, positions: [], normals: [], uvs: [], indices: [], triangles: 0 };
        batches.set(key, batch);
      }
      const place = (s: number, t: number): readonly [number, number] =>
        placement === undefined
          ? unavailableUv(s, t, look, surface.orientation)
          : surfaceUv(s, t, placement.reference, placement.entry);
      const first = batch.positions.length / 3;
      const remap = new Map<number, number>();
      const local: number[] = [];
      const surfaceIndices: number[] = [];
      const lastVertex = surface.firstVertex + surface.vertexCount;
      for (let corner = surface.firstTriangle * 3; corner < (surface.firstTriangle + surface.triangleCount) * 3; corner += 1) {
        const vertex = render.index[corner]!;
        if (vertex < surface.firstVertex || vertex >= lastVertex) {
          throw new Error(`A triangle of the ${surface.role} surface of record ${range.record} uses a vertex outside the surface`);
        }
        let mapped = remap.get(vertex);
        if (mapped === undefined) {
          mapped = local.length / 3;
          remap.set(vertex, mapped);
          local.push(render.position[vertex * 3]!, render.position[vertex * 3 + 2]!, -render.position[vertex * 3 + 1]!);
          batch.uvs.push(...place(surfaceMm[vertex * 2]!, surfaceMm[vertex * 2 + 1]!));
        }
        surfaceIndices.push(mapped);
      }
      batch.positions.push(...local);
      batch.normals.push(...pc.calculateNormals(local, surfaceIndices));
      for (const index of surfaceIndices) batch.indices.push(first + index);
      batch.triangles += surface.triangleCount;
    }
  }
  return [...batches.keys()].sort().map((key) => batches.get(key)!);
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
  const { ranges, placements, prepared } = await plan(decoded, render, sources, digest);
  // ROUTE obstruction rings, built from the container's own records with tess's own reader, so the
  // rings a walk is routed around are the rings the bake made. They are stated ON THE TILE and NOT in
  // the navigation world: `resolveGroundMovement` collides against `polygonObstacles` by
  // construction, so carrying them there made a bench stop a walker, measured 2026-09-18. They choose
  // which way a walk faces and stop no body; a route rule reads them from here. A region that bounds
  // nothing or names no record is refused rather than repaired, and the refusals are carried so a
  // caller can say what was dropped instead of serving a quietly smaller set.
  const neighbours: NavigationTile[] = [];
  const stating: StatingTile[] = [{ tile: sources.name, header: decoded.header }];
  for (const source of sources.neighbours ?? []) {
    let near: DecodedOwd;
    try {
      near = await verifyOwd(source.bytes, sha256);
    } catch (error) {
      if (error instanceof OwdError) throw new GeneratedTileRefusal(`Neighbour ${source.name} refused: ${error.message}`);
      throw error;
    }
    const nearFrame = unsupportedFrame(near.header.grammars);
    if (nearFrame !== null) throw new GeneratedTileRefusal(`Neighbour ${source.name} refused: ${nearFrame}`);
    // A NEIGHBOUR CARVED FOR ANOTHER BODY IS NOT GROUND FOR THIS ONE. An envelope is carved to a
    // capsule, so composing one carved to a different radius would put a walker on ground that was
    // cleared for somebody else and stop it somewhere the rule cannot explain.
    const nearCapsule = tileCapsule(near.header.grammars);
    if (typeof nearCapsule === 'string') throw new GeneratedTileRefusal(`Neighbour ${source.name} refused: ${nearCapsule}`);
    if (nearCapsule.radiusM !== capsule.radiusM || nearCapsule.heightM !== capsule.heightM || nearCapsule.eyeHeightM !== capsule.eyeHeightM) {
      throw new GeneratedTileRefusal(
        `Neighbour ${source.name} refused: its envelope is carved for a capsule of ${nearCapsule.radiusM} m by `
        + `${nearCapsule.heightM} m, and ${sources.name} for one of ${capsule.radiusM} m by ${capsule.heightM} m.`,
      );
    }
    const envelope = near.projections.find((projection) => projection.header.name === 'nav_envelope');
    if (envelope === undefined) throw new GeneratedTileRefusal(`Neighbour ${source.name} refused: it carries no nav_envelope.`);
    neighbours.push({ tile: source.name, projection: envelope });
    stating.push({ tile: source.name, header: near.header });
  }
  // COMPOSED ACROSS THE WORLD'S TILES, the drawn one first so a building both state is attributed
  // to the street underfoot. Still never collision: see `obstruction-rings.ts`.
  const composed = composedObstructionRings(stating);
  const rings = obstructionRings(composed.rings, composed.disagreed);
  const navigation = tileNavigation(
    decoded.projections.find((projection) => projection.header.name === 'nav_envelope'),
    renderExtent(ranges),
    capsule,
    neighbours,
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
    routeObstructions: rings,
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
      return attachTile(host, tile, render, surface, placements, prepared);
    },
  };
  return tile;
}

function attachTile(
  host: GeneratedTileHost,
  tile: LoadedGeneratedTile,
  render: DecodedProjection,
  surfaceMm: Float64Array,
  placements: ReadonlyMap<GeneratedTileSurface, SurfacePlacement>,
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

  // One draw per texture set, and one for every unavailable surface.
  const batches = batchTileSurfaces(render, surfaceMm, tile.ranges, placements, look);

  const meshes: pc.Mesh[] = [];
  for (const batch of batches) {
    let material: pc.Material = uploads.unavailableMaterial;
    let shadows = true;
    let bucket: number | null = null;
    if (batch.key !== '') {
      const resolution = uploads.adopt(prepared.get(batch.key)!);
      if (resolution.state !== 'available') throw new Error(`Texture set ${batch.key} was prepared and then refused`);
      material = resolution.material;
      shadows = castsShadow(resolution.set);
      bucket = drawBucket(resolution.set);
      // Glazing transmits what the scene drew behind it, which needs the colour copied before it draws.
      if (resolution.set.materialClass === 'glazing') environment.requestSceneColor();
    }
    // The UV is already final, so the builder is handed it as the surface pair and passes it on.
    const mesh = buildSurfaceMesh(device, { ...batch, surfaceMm: batch.uvs }, (u, v) => [u, v]);
    meshes.push(mesh);
    const entity = new pc.Entity(batch.key === '' ? 'generated-tile:unavailable-surfaces' : `generated-tile:${batch.key}`);
    const instance = new pc.MeshInstance(mesh, material, entity);
    // Decal before glazing among blended surfaces; within one set, triangles draw in record order.
    if (bucket !== null) instance.drawBucket = bucket;
    entity.addComponent('render', {
      meshInstances: [instance],
      castShadows: shadows,
      receiveShadows: batch.key !== '',
    });
    root.addChild(entity);
  }

  const metrics: GeneratedTileMetrics = {
    tileName: tile.name,
    triangles: batches.reduce((total, batch) => total + batch.triangles, 0),
    drawBatches: batches.length,
    transferredBytes: tile.transferredBytes,
    decodedTextureBytes: uploads.decodedTextureBytes,
    unavailableSurfaces: tile.ranges.reduce((count, range) =>
      count + (range.state === 'drawn' ? range.surfaces.filter((surface) => surface.state === 'unavailable').length : 0), 0),
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
