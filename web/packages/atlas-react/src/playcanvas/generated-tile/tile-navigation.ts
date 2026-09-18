import {
  DEFAULT_MAXIMUM_SLOPE_DEGREES,
  DEFAULT_MAXIMUM_STEP_HEIGHT_AU,
  atlasVec3,
  type NavigationSurface,
  type NavigationWorld,
  type PolygonObstacle,
  type SurfaceSample,
} from '@exulanica/atlas-core';
import {
  GRAMMAR_TABLES,
  absoluteVertices,
  type DecodedProjection,
  type GrammarTable,
  type OwdGrammar,
} from '@exulanica/loom-tess/core';
import type { CameraState } from '../controls.js';

/**
 * Where a person stands on a generated tile, and only from the tile's own `nav_envelope`.
 *
 * NAVIGATION IS NEVER DERIVED FROM WHAT IS DRAWN. Melbourne passed every budget and failed capsule
 * clearance because its ground came out of the render mesh. So this module reads the
 * `nav_envelope` projection and nothing else for support. A tile with no projection at all and a tile
 * whose projection holds no triangle both leave nothing to stand on, and the statement says WHICH: an
 * empty projection means the bake ran and produced no walkable geometry, which is a different fact
 * about the world from a container that never carried one, and a person reading the screen should not
 * have to guess. When a tile carries none, the support
 * answers "no surface" everywhere, the opening pose is a stated viewpoint rather than a stance, and
 * any attempt to walk gets the app's own "no walkable surface" notice.
 *
 * THE PLAYER is the capsule the tile's grammar states for its envelope's `capsule_clearance`
 * (city version 2: 340 mm radius, 1900 mm tall, eye at 1620 mm), because that is the capsule the
 * envelope was carved for; see {@link tileCapsule}. Support is resampled every 0.05 m along a move,
 * and the Atlas controller's own comfort limits apply (steps up to 0.18 m, slopes up to 12 degrees).
 * The capsule's height needs overhead clearance from `collision_proxy`, which no tile carries yet;
 * until it does, the world has no blockers and says so in `collisionState`.
 *
 * FRAMES. Tile records are `city_local`: x east, y north, z up, integer millimetres, and a grammar
 * that states any other frame is refused ({@link unsupportedFrame}). The renderer is metres with +Y
 * up, and a tile point (x, y, z) is drawn at (x, z, -y) / 1000: a proper rotation, so winding and
 * handedness are kept and north is the camera's yaw-0 direction.
 */

/** The one frame {@link tileToRenderer} is written for. */
export const TILE_FRAME = Object.freeze({ name: 'city_local', units: 'mm', axes: 'x_east_y_north_z_up' });

/** Why a tile's grammars state a frame this runtime cannot place, or null when every one is `city_local`. */
export function unsupportedFrame(grammars: readonly Pick<OwdGrammar, 'grammar_id' | 'grammar_version' | 'frame'>[]): string | null {
  for (const grammar of grammars) {
    const { name, units, axes } = grammar.frame;
    if (name !== TILE_FRAME.name || units !== TILE_FRAME.units || axes !== TILE_FRAME.axes) {
      return `Grammar ${grammar.grammar_id} version ${grammar.grammar_version} states frame ${name} (${units}, ${axes}); `
        + `this runtime places only ${TILE_FRAME.name} (${TILE_FRAME.units}, ${TILE_FRAME.axes}).`;
    }
  }
  return null;
}

/** The capsule a person is, in metres, as the grammar's nav_envelope contract measures it. */
export interface TileCapsule {
  readonly radiusM: number;
  readonly heightM: number;
  readonly eyeHeightM: number;
}

/**
 * The capsule every grammar of a tile states for `nav_envelope`'s `capsule_clearance`, or the reason
 * there is none to build to: a grammar this runtime has no table for, a grammar that states no such
 * measure, or two grammars that state different capsules. The numbers come from the grammar table
 * tess generates from the descriptor; nothing here restates one.
 */
export function tileCapsule(
  grammars: readonly Pick<OwdGrammar, 'grammar_id' | 'grammar_version'>[],
  tables: readonly GrammarTable[] = GRAMMAR_TABLES,
): TileCapsule | string {
  let capsule: TileCapsule | null = null;
  for (const grammar of grammars) {
    const name = `Grammar ${grammar.grammar_id} version ${grammar.grammar_version}`;
    const table = tables.find((candidate) =>
      candidate.grammar_id === grammar.grammar_id && candidate.grammar_version === grammar.grammar_version);
    if (table === undefined) return `${name} has no grammar table, so its capsule clearance is unknown.`;
    const measures = table.measures['nav_envelope']?.['capsule_clearance'];
    const radius = measures?.['radius_mm'];
    const height = measures?.['height_mm'];
    const eye = measures?.['eye_height_mm'];
    if (radius === undefined || height === undefined || eye === undefined) {
      return `${name} states no nav_envelope capsule_clearance radius, height and eye height.`;
    }
    const stated = { radiusM: radius / MILLIMETRES, heightM: height / MILLIMETRES, eyeHeightM: eye / MILLIMETRES };
    if (capsule !== null && (capsule.radiusM !== stated.radiusM || capsule.heightM !== stated.heightM || capsule.eyeHeightM !== stated.eyeHeightM)) {
      return `${name} states a different capsule clearance from another grammar of the same tile.`;
    }
    capsule = stated;
  }
  return capsule ?? 'The tile names no grammar, so its capsule clearance is unknown.';
}

export const SUPPORT_SAMPLE_SPACING_M = 0.05;
const MILLIMETRES = 1000;
/** Grid cell for the support index, in millimetres. A lookup, not a tolerance. */
const INDEX_CELL_MM = 1000;
/** How far outside the tile a viewpoint stands when there is nothing to stand on. */
const VIEWPOINT_STANDOFF_MM = 6000;
/** Beyond the tile's own extent, how much farther the resident field reaches. */
const FIELD_MARGIN_M = 2;

export type Vec3 = readonly [number, number, number];

/** A tile point in millimetres, in the renderer's metres. */
export function tileToRenderer(x: number, y: number, z: number): Vec3 {
  return [x / MILLIMETRES, z / MILLIMETRES, -y / MILLIMETRES];
}

/** A renderer point in metres, as tile millimetres (not rounded). */
export function rendererToTile(x: number, y: number, z: number): Vec3 {
  return [x * MILLIMETRES, -z * MILLIMETRES, y * MILLIMETRES];
}

export interface TileExtentMm {
  readonly min: Vec3;
  readonly max: Vec3;
}

interface SupportTriangle {
  readonly a: Vec3;
  readonly b: Vec3;
  readonly c: Vec3;
  /** Twice the signed plan area, positive for counter-clockwise seen from above. */
  readonly area2: number;
  readonly normal: SurfaceSample['normal'];
}

function cross2(ax: number, ay: number, bx: number, by: number): number {
  return ax * by - ay * bx;
}

/**
 * Support from a `nav_envelope` projection: the height of the highest envelope triangle over a
 * plan point, interpolated exactly on its plane, with that triangle's normal. Null off the envelope.
 *
 * Triangles with no plan area (walls) and triangles facing down support nothing and are skipped;
 * an envelope is walkable ground by contract.
 */
export function navEnvelopeSupport(projection: DecodedProjection): { readonly surface: NavigationSurface; readonly extent: TileExtentMm; readonly triangles: number } {
  const vertices = absoluteVertices(projection);
  const triangles: SupportTriangle[] = [];
  const cells = new Map<string, number[]>();
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  const at = (vertex: number): Vec3 => [vertices[vertex * 3]!, vertices[vertex * 3 + 1]!, vertices[vertex * 3 + 2]!];
  for (let corner = 0; corner < projection.index.length; corner += 3) {
    const a = at(projection.index[corner]!);
    const b = at(projection.index[corner + 1]!);
    const c = at(projection.index[corner + 2]!);
    const area2 = cross2(b[0] - a[0], b[1] - a[1], c[0] - a[0], c[1] - a[1]);
    if (area2 <= 0) continue;
    const ux = b[0] - a[0]; const uy = b[1] - a[1]; const uz = b[2] - a[2];
    const vx = c[0] - a[0]; const vy = c[1] - a[1]; const vz = c[2] - a[2];
    const nx = uy * vz - uz * vy;
    const ny = uz * vx - ux * vz;
    const nz = ux * vy - uy * vx;
    const length = Math.hypot(nx, ny, nz);
    // Tile normal (nx, ny, nz) in the renderer frame is (nx, nz, -ny).
    const normal = Object.freeze({ x: nx / length, y: nz / length, z: -ny / length });
    const index = triangles.length;
    triangles.push({ a, b, c, area2, normal });
    for (const point of [a, b, c]) {
      for (let axis = 0; axis < 3; axis += 1) {
        min[axis] = Math.min(min[axis]!, point[axis]!);
        max[axis] = Math.max(max[axis]!, point[axis]!);
      }
    }
    const x0 = Math.floor(Math.min(a[0], b[0], c[0]) / INDEX_CELL_MM);
    const x1 = Math.floor(Math.max(a[0], b[0], c[0]) / INDEX_CELL_MM);
    const y0 = Math.floor(Math.min(a[1], b[1], c[1]) / INDEX_CELL_MM);
    const y1 = Math.floor(Math.max(a[1], b[1], c[1]) / INDEX_CELL_MM);
    for (let cx = x0; cx <= x1; cx += 1) {
      for (let cy = y0; cy <= y1; cy += 1) {
        const key = `${cx}:${cy}`;
        const list = cells.get(key);
        if (list === undefined) cells.set(key, [index]);
        else list.push(index);
      }
    }
  }
  if (triangles.length === 0) throw new Error('The nav_envelope has no walkable triangle');
  const surface: NavigationSurface = Object.freeze({
    sample(rendererX: number, rendererZ: number): SurfaceSample | null {
      const x = rendererX * MILLIMETRES;
      const y = -rendererZ * MILLIMETRES;
      const list = cells.get(`${Math.floor(x / INDEX_CELL_MM)}:${Math.floor(y / INDEX_CELL_MM)}`);
      if (list === undefined) return null;
      let best: { height: number; normal: SurfaceSample['normal'] } | null = null;
      for (const index of list) {
        const { a, b, c, area2, normal } = triangles[index]!;
        // Barycentric weights from plan sub-areas; a point on an edge belongs to the triangle.
        const wa = cross2(b[0] - x, b[1] - y, c[0] - x, c[1] - y) / area2;
        const wb = cross2(c[0] - x, c[1] - y, a[0] - x, a[1] - y) / area2;
        const wc = 1 - wa - wb;
        if (wa < 0 || wb < 0 || wc < 0) continue;
        const height = (wa * a[2] + wb * b[2] + wc * c[2]) / MILLIMETRES;
        if (best === null || height > best.height) best = { height, normal };
      }
      return best === null ? null : Object.freeze(best);
    },
  });
  return {
    surface,
    extent: { min: [min[0]!, min[1]!, min[2]!], max: [max[0]!, max[1]!, max[2]!] },
    triangles: triangles.length,
  };
}

const NO_SURFACE: NavigationSurface = Object.freeze({ sample: () => null });

export type TileSupportState =
  | { readonly state: 'nav_envelope'; readonly triangles: number }
  | { readonly state: 'unavailable'; readonly reason: string };

export type TileCollisionState = { readonly state: 'unavailable'; readonly reason: string };

export interface TileNavigation {
  readonly world: NavigationWorld;
  readonly start: CameraState;
  readonly support: TileSupportState;
  readonly collisionState: TileCollisionState;
  /** True when `start` is a place to look from, not a place to stand. */
  readonly viewpointOnly: boolean;
  /** The capsule the grammar states, which the world's eye height and radius are built to. */
  readonly capsule: TileCapsule;
}

function world(
  surface: NavigationSurface,
  centre: readonly [number, number],
  radius: number,
  capsule: TileCapsule,
  polygonObstacles: readonly PolygonObstacle[],
): NavigationWorld {
  return Object.freeze({
    surface,
    eyeHeight: capsule.eyeHeightM,
    cameraRadius: capsule.radiusM,
    centre: atlasVec3(centre[0], 0, centre[1]),
    fieldRadius: radius,
    recoveryRadius: radius + FIELD_MARGIN_M,
    maximumSlopeDegrees: DEFAULT_MAXIMUM_SLOPE_DEGREES,
    maximumStepHeight: DEFAULT_MAXIMUM_STEP_HEIGHT_AU,
    surfaceSampleSpacing: SUPPORT_SAMPLE_SPACING_M,
    regions: Object.freeze([]),
    obstacles: Object.freeze([]),
    // ROUTE obstruction rings, which choose which way a walk faces and stop no body: they have no
    // height and nothing in them blocks the capsule. Horizontal blocking waits on a collision proxy
    // that no tile materialises, and carrying these does not change that.
    polygonObstacles,
    traces: Object.freeze([]),
  });
}

function halfDiagonalM(extent: TileExtentMm): number {
  return Math.hypot(extent.max[0] - extent.min[0], extent.max[1] - extent.min[1]) / 2 / MILLIMETRES;
}

const COLLISION_PENDING: TileCollisionState = {
  state: 'unavailable',
  reason: 'The tile carries no collision_proxy, so nothing on it blocks the capsule.',
};

/**
 * The navigation a tile provides. `renderExtent` is used only to place a viewpoint when there is no
 * envelope; it never becomes support.
 */
export function tileNavigation(
  navEnvelope: DecodedProjection | undefined,
  renderExtent: TileExtentMm,
  capsule: TileCapsule,
  polygonObstacles: readonly PolygonObstacle[] = [],
): TileNavigation {
  if (navEnvelope === undefined || navEnvelope.header.triangle_count === 0) {
    // A viewpoint south of the tile, looking north at its middle, at eye height above the city datum.
    // The world's centre is that same point, so the recovery a blocked move triggers returns the
    // camera exactly where it was rather than moving it somewhere that claims to be safe ground.
    const cx = (renderExtent.min[0] + renderExtent.max[0]) / 2;
    const cy = (renderExtent.min[1] + renderExtent.max[1]) / 2;
    const cz = (renderExtent.min[2] + renderExtent.max[2]) / 2;
    const [vx, , vz] = tileToRenderer(cx, renderExtent.min[1] - VIEWPOINT_STANDOFF_MM, 0);
    const [tx, ty, tz] = tileToRenderer(cx, cy, cz);
    const pitch = Math.atan2(ty - capsule.eyeHeightM, Math.hypot(tx - vx, tz - vz));
    return {
      world: world(NO_SURFACE, [vx, vz], halfDiagonalM(renderExtent) + VIEWPOINT_STANDOFF_MM / MILLIMETRES, capsule, polygonObstacles),
      start: { x: vx, y: capsule.eyeHeightM, z: vz, yaw: 0, pitch },
      support: { state: 'unavailable', reason: navEnvelope === undefined
        ? 'The tile carries no nav_envelope projection, so there is nothing to stand on.'
        : 'The tile\'s nav_envelope is empty, so there is nothing to stand on: the projection is there, with its own digest, and it holds no triangle.' },
      collisionState: COLLISION_PENDING,
      viewpointOnly: true,
      capsule,
    };
  }
  const support = navEnvelopeSupport(navEnvelope);
  const extent = support.extent;
  const [cx, , cz] = tileToRenderer((extent.min[0] + extent.max[0]) / 2, (extent.min[1] + extent.max[1]) / 2, 0);
  // Stand on the envelope nearest the middle of its southern edge, facing north.
  const [sx, , sz] = tileToRenderer((extent.min[0] + extent.max[0]) / 2, extent.min[1], 0);
  let stance: CameraState | null = null;
  for (let step = 0; step <= 400 && stance === null; step += 1) {
    const probeZ = sz - step * SUPPORT_SAMPLE_SPACING_M;
    const sample = support.surface.sample(sx, probeZ);
    if (sample !== null) stance = { x: sx, y: sample.height + capsule.eyeHeightM, z: probeZ, yaw: 0, pitch: 0 };
  }
  if (stance === null) throw new Error('The nav_envelope has no support on its own north-south midline');
  return {
    world: world(support.surface, [cx, cz], halfDiagonalM(extent), capsule, polygonObstacles),
    start: stance,
    support: { state: 'nav_envelope', triangles: support.triangles },
    collisionState: COLLISION_PENDING,
    viewpointOnly: false,
    capsule,
  };
}
