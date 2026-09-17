import * as pc from 'playcanvas';
import type { TextureSetDigest, TextureSetManifest, TextureSetManifestEntry } from '@exulanica/atlas-core';
import {
  IDENTITY_NOT_STATED,
  OwdError,
  verifyOwd,
  type DecodedOwd,
  type DecodedProjection,
  type OwdHeader,
} from '@exulanica/loom-tess/core';
import type { GeneratedTileAttachment, GeneratedTileHost, GeneratedTileMetrics, GeneratedTileMount } from './binding-contract.js';
import { applyTileEnvironment } from './environment.js';
import { TILE_LOOK_V1, type TileLook } from './look.js';
import { buildSurfaceMesh } from './surface-mesh.js';
import { TileTextureLibrary, unavailableUv } from './texture-materials.js';
import { rendererToTile, tileNavigation, tileToRenderer, type TileExtentMm, type TileNavigation, type Vec3 } from './tile-navigation.js';

/**
 * One baked `.owd` tile, drawn.
 *
 * THE CONTAINER IS READ THROUGH TESS'S OWN CODE. `verifyOwd` decodes the layout and then bakes the
 * header's own records again, requiring every byte to match, so what is drawn is exactly what its
 * records say. There is no second reader here and nothing is repaired.
 *
 * WHAT IS DRAWN. Only `render_batch`, and only its drawn ranges, each exactly as stored. A drawn
 * range is textured when it cites a `surface_material` record whose texture set resolves AND the
 * container says where on the surface each vertex lies. Otherwise it is the stated unavailable
 * surface, with the reason kept. A range that is not drawn (unavailable, not admitted) has no
 * geometry at all, and is listed with the needs the tessellator stated. No vertex is invented and
 * no default mesh stands in for a missing one.
 *
 * WHAT IS KEPT FOR PICKING. Every triangle maps back to its record: the range table answers "which
 * record is this triangle" and "what is that record's extent", and `pick` answers it for a ray.
 *
 * `.owd` version 1 (loom-tess 5d0f15de) carries no per-vertex surface coordinates, so no range can
 * be textured yet; every drawn range reads as unavailable, and says why.
 */

export const SURFACE_COORDINATES_NOT_CARRIED =
  'The container carries no surface coordinates, so no texture set can be placed on this range.';
export const MATERIAL_NOT_CITED = 'The range cites no surface_material record.';

export type GeneratedTileRange =
  | {
      readonly record: number;
      readonly kind: string;
      /** The identity the record states, or null when it states none. */
      readonly identity: string | null;
      readonly state: 'drawn';
      readonly surface: 'textured' | 'unavailable';
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

export interface LoadedGeneratedTile extends GeneratedTileMount {
  readonly name: string;
  readonly header: OwdHeader;
  readonly look: TileLook;
  readonly ranges: readonly GeneratedTileRange[];
  readonly navigation: TileNavigation;
  readonly transferredBytes: number;
  /** The record a render_batch triangle belongs to. */
  rangeAtTriangle(triangle: number): GeneratedTileRange | null;
}

function ambientDigest(): TextureSetDigest | null {
  const scope = globalThis as unknown as { readonly crypto?: { readonly subtle?: TextureSetDigest } };
  return scope.crypto?.subtle ?? null;
}

function hexOf(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

function describeNeeds(needs: readonly string[]): string {
  return `Not drawn: the record lacks ${needs.join(', ')}.`;
}

function rangesOf(decoded: DecodedOwd, render: DecodedProjection): GeneratedTileRange[] {
  const records = decoded.header.records;
  const ranges: GeneratedTileRange[] = [];
  for (const entry of render.header.entries) {
    const record = records[entry.record]!;
    const identity = record.identity === IDENTITY_NOT_STATED ? null : record.identity;
    switch (entry.state) {
      case 'drawn': {
        const cited = entry.material.state === 'record' ? records[entry.material.record]! : null;
        const setId = cited === null ? null : cited.fields['texture_set_id'];
        ranges.push({
          record: entry.record,
          kind: record.kind,
          identity,
          state: 'drawn',
          // Version 1 carries no surface coordinates, so a cited set cannot be placed either.
          surface: 'unavailable',
          textureSetId: typeof setId === 'string' ? setId : null,
          reason: cited === null ? MATERIAL_NOT_CITED : SURFACE_COORDINATES_NOT_CARRIED,
          firstTriangle: entry.first_triangle,
          triangleCount: entry.triangle_count,
          extentMm: { min: entry.extent_mm.min, max: entry.extent_mm.max },
        });
        break;
      }
      case 'unavailable':
        ranges.push({ record: entry.record, kind: record.kind, identity, state: 'unavailable', reason: describeNeeds(entry.needs), needs: entry.needs });
        break;
      case 'not_admitted':
        ranges.push({
          record: entry.record, kind: record.kind, identity, state: 'not_admitted', needs: [],
          reason: 'Not drawn: its grammar does not admit render_batch.',
        });
        break;
      case 'not_a_surface':
        break;
    }
  }
  return ranges;
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

/**
 * Verify and read a baked tile. Refuses, with a reason, rather than drawing anything unchecked.
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
  const render = decoded.projections.find((projection) => projection.header.name === 'render_batch');
  if (render === undefined) throw new GeneratedTileRefusal(`Tile ${sources.name} carries no render_batch.`);
  const ranges = rangesOf(decoded, render);
  const navigation = tileNavigation(
    decoded.projections.find((projection) => projection.header.name === 'nav_envelope'),
    renderExtent(ranges),
  );
  const byTriangle = new Map<number, GeneratedTileRange>();
  for (const range of ranges) if (range.state === 'drawn') byTriangle.set(range.firstTriangle, range);
  const drawnStarts = [...byTriangle.keys()].sort((a, b) => a - b);
  const look = sources.look ?? TILE_LOOK_V1;
  const name = sources.name;

  const tile: LoadedGeneratedTile = {
    name,
    header: decoded.header,
    look,
    ranges,
    navigation,
    navigationWorld: navigation.world,
    start: navigation.start,
    transferredBytes: sources.bytes.byteLength,
    rangeAtTriangle(triangle: number): GeneratedTileRange | null {
      let low = 0;
      let high = drawnStarts.length - 1;
      while (low <= high) {
        const middle = (low + high) >> 1;
        const start = drawnStarts[middle]!;
        const range = byTriangle.get(start)!;
        if (range.state !== 'drawn') return null;
        if (triangle < start) high = middle - 1;
        else if (triangle >= start + range.triangleCount) low = middle + 1;
        else return range;
      }
      return null;
    },
    attach(host: GeneratedTileHost): GeneratedTileAttachment {
      return attachTile(host, sources, look, render, ranges, tile);
    },
  };
  return tile;
}

interface Batch {
  readonly positions: number[];
  readonly normals: number[];
  readonly surfaceMm: number[];
  readonly indices: number[];
}

/** Plan or wall coordinates for the unavailable pattern only; never a texture set's placement. */
function patternCoordinates(position: Vec3, normal: Vec3): readonly [number, number] {
  const [x, y, z] = rendererToTile(position[0], position[1], position[2]);
  if (Math.abs(normal[1]) >= Math.SQRT1_2) return [x, -y];
  const length = Math.hypot(normal[0], normal[2]);
  // Along the wall, seen from its front, and downward.
  const along = (position[0] * -normal[2] + position[2] * normal[0]) / (length === 0 ? 1 : length);
  return [along * 1000, -z];
}

function attachTile(
  host: GeneratedTileHost,
  sources: GeneratedTileSources,
  look: TileLook,
  render: DecodedProjection,
  ranges: readonly GeneratedTileRange[],
  tile: LoadedGeneratedTile,
): GeneratedTileAttachment {
  const device = host.app.graphicsDevice;
  const environment = applyTileEnvironment(host.app, host.camera, look);
  const library = new TileTextureLibrary(device, look, sources.manifest, sources.fetchSet,
    sources.digest === undefined ? ambientDigest() : sources.digest);
  const root = new pc.Entity(`generated-tile:${tile.name}`);
  const origin = render.header.origin_mm;
  if (origin.length === 3) root.setLocalPosition(...tileToRenderer(origin[0], origin[1], origin[2]));
  host.environmentRoot.addChild(root);

  // Version 1: every drawn range is the unavailable surface, so there is one batch.
  const unavailable: Batch = { positions: [], normals: [], surfaceMm: [], indices: [] };
  const meshes: pc.Mesh[] = [];
  let triangles = 0;
  for (const range of ranges) {
    if (range.state !== 'drawn') continue;
    const first = unavailable.positions.length / 3;
    const remap = new Map<number, number>();
    const local: number[] = [];
    const rangeIndices: number[] = [];
    for (let corner = range.firstTriangle * 3; corner < (range.firstTriangle + range.triangleCount) * 3; corner += 1) {
      const vertex = render.index[corner]!;
      let mapped = remap.get(vertex);
      if (mapped === undefined) {
        mapped = local.length / 3;
        remap.set(vertex, mapped);
        const px = render.position[vertex * 3]!;
        const py = render.position[vertex * 3 + 1]!;
        const pz = render.position[vertex * 3 + 2]!;
        local.push(px, pz, -py);
      }
      rangeIndices.push(mapped);
    }
    const normals = pc.calculateNormals(local, rangeIndices);
    for (let vertex = 0; vertex < local.length / 3; vertex += 1) {
      const position: Vec3 = [local[vertex * 3]!, local[vertex * 3 + 1]!, local[vertex * 3 + 2]!];
      const normal: Vec3 = [normals[vertex * 3]!, normals[vertex * 3 + 1]!, normals[vertex * 3 + 2]!];
      unavailable.positions.push(...position);
      unavailable.normals.push(...normal);
      unavailable.surfaceMm.push(...patternCoordinates(position, normal));
    }
    for (const index of rangeIndices) unavailable.indices.push(first + index);
    triangles += range.triangleCount;
  }
  let drawBatches = 0;
  if (unavailable.indices.length > 0) {
    const mesh = buildSurfaceMesh(device, unavailable, (s, t) => unavailableUv(s, t, look));
    meshes.push(mesh);
    const entity = new pc.Entity('generated-tile:unavailable-surfaces');
    entity.addComponent('render', {
      meshInstances: [new pc.MeshInstance(mesh, library.unavailableMaterial, entity)],
      castShadows: true,
      receiveShadows: false,
    });
    root.addChild(entity);
    drawBatches += 1;
  }

  const metrics: GeneratedTileMetrics = {
    tileName: tile.name,
    triangles,
    drawBatches,
    transferredBytes: tile.transferredBytes,
    decodedTextureBytes: library.decodedTextureBytes,
    unavailableSurfaces: ranges.filter((range) => range.state === 'drawn' && range.surface === 'unavailable').length,
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
      library.destroy();
      environment.dispose();
    },
  };
}
