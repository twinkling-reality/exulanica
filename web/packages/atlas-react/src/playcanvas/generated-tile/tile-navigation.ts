import {
  DEFAULT_MAXIMUM_SLOPE_DEGREES,
  DEFAULT_MAXIMUM_STEP_HEIGHT_AU,
  atlasVec3,
  type NavigationSurface,
  type NavigationWorld,
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
 * A WORLD IS MORE THAN ONE TILE, AND WALKABLE IS NOT DRAWN. A tile is 128,000 mm across and the
 * route rule asks for 125,000 plus a 6,000 stopping margin, so the ground a route needs does not fit
 * in the tile a route is laid on. The neighbours' `nav_envelope` projections are composed into one
 * world for that reason, and for that reason only: THE COMPOSED WORLD IS WALKABLE PAST THE EDGE AND
 * NOT DRAWN PAST IT, AND THE ENDPOINT FRAME IS THEREFORE NOT JUDGEABLE. A camera at the end of a
 * route looks east at ground it can stand on and at no street at all, because nothing of the
 * neighbour's `render_batch` is loaded, and a person scoring that frame would be answering a
 * question about the edge of the loaded world while believing they were answering one about a city.
 * Drawing the neighbour is a separate piece and it must exist before any capture is put to a judge.
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

/** One tile's walkable envelope in a composed world, with the name a refusal would use. */
export interface NavigationTile {
  readonly tile: string;
  readonly projection: DecodedProjection;
}

/** What one tile put into the composed ground, so a caller can add the parts up and check. */
export interface ComposedTile {
  readonly tile: string;
  /** What this tile alone covers, which is what fixes a stance when this is the tile being walked. */
  readonly extent: TileExtentMm;
  /** Triangles the projection declares, which is the number a container's own header states. */
  readonly stated: number;
  /** Of those, the ones that hold a person up: plan area, facing up. */
  readonly walkable: number;
}

export interface ComposedSupport {
  readonly surface: NavigationSurface;
  readonly extent: TileExtentMm;
  readonly triangles: number;
  readonly tiles: readonly ComposedTile[];
}

/**
 * Support from one or more `nav_envelope` projections: the height of the highest envelope triangle
 * over a plan point, interpolated exactly on its plane, with that triangle's normal. Null off the
 * envelope.
 *
 * Triangles with no plan area (walls) and triangles facing down support nothing and are skipped;
 * an envelope is walkable ground by contract.
 *
 * WHY MORE THAN ONE, AND WHY THIS IS A UNION AND NOT A MERGE. A tile is 128,000 mm across and the
 * route rule asks for 125,000 plus a 6,000 stopping margin, so a route laid east to west can never
 * have ground for its whole length inside one tile, whatever pose is chosen. The tiles either side
 * hold that ground already, at the same bake, and a tile's coordinates are ABSOLUTE city
 * millimetres: measured across the corridor's five, the terrains run 0 to 128,000, 128,000 to
 * 256,000 and so on to 640,000, abutting exactly with no gap and no overlap. So composition needs no
 * transform and no reconciliation. Every triangle goes into one index in one frame and the highest
 * one over a plan point wins, exactly as it does within a tile, because a curb top over a road is
 * the same question whichever tile owns the curb.
 *
 * WHAT IT IS NOT is the halo. Every container already carries its neighbours' records, 2,076 of them
 * against 2,073 owned on the corridor's middle tile, and every one is state `halo` in both
 * projections. Drawing those instead would put the same ground in the world twice, the neighbour's
 * halo copy and the neighbour's own owned copy, with two supports at one plan point and nothing to
 * say which is the answer. Halo exists so a tile can know its neighbours in order to carve against
 * them, not in order to draw them.
 *
 * MEASURED AT THE SEAM, corridor tiles (2,0) and (3,0) across x 384,000, 513 stations 250 mm apart:
 * every station supported on both sides, largest step 49.000 mm, mean 10.16. The control is the same
 * measurement at a join INSIDE one tile, where its terrain meets its own street: 192.987 mm, four
 * times worse, and open ground with nothing joining reads 0.000 over 189 stations, so the instrument
 * can return zero and a reading that is not zero means something. A seam is not a special place.
 */
export function composedSupport(tiles: readonly NavigationTile[]): ComposedSupport {
  const triangles: SupportTriangle[] = [];
  const cells = new Map<string, number[]>();
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  const composed: ComposedTile[] = [];
  for (const { tile, projection } of tiles) {
    const vertices = absoluteVertices(projection);
    const before = triangles.length;
    const low = [Infinity, Infinity, Infinity];
    const high = [-Infinity, -Infinity, -Infinity];
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
          low[axis] = Math.min(low[axis]!, point[axis]!);
          high[axis] = Math.max(high[axis]!, point[axis]!);
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
    composed.push({
      tile,
      extent: { min: [low[0]!, low[1]!, low[2]!], max: [high[0]!, high[1]!, high[2]!] },
      stated: projection.header.triangle_count,
      walkable: triangles.length - before,
    });
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
    tiles: composed,
  };
}

/** The support one tile's envelope gives on its own, which is the composed ground of a world of one. */
export function navEnvelopeSupport(projection: DecodedProjection): ComposedSupport {
  return composedSupport([{ tile: 'the tile', projection }]);
}

const NO_SURFACE: NavigationSurface = Object.freeze({ sample: () => null });

export type TileSupportState =
  | { readonly state: 'nav_envelope'; readonly triangles: number; readonly tiles: readonly ComposedTile[] }
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

function world(surface: NavigationSurface, centre: readonly [number, number], radius: number, capsule: TileCapsule): NavigationWorld {
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
    // EMPTY, AND IT MUST STAY EMPTY UNTIL SOMETHING IN THIS TILE REALLY BLOCKS A BODY. MEASURED
    // 2026-09-18: route obstruction rings were carried here, and `resolveGroundMovement` collides
    // against this field by construction, with no flag and no opt-out, so a bench stopped a walker
    // 344 mm from its edge against a stated capsule radius of 340. Route rings choose which way a
    // walk faces and stop nothing; they are stated on the loaded tile instead, where a route rule
    // reads them and the movement resolver never sees them. A field named `polygonObstacles` means
    // one thing to everything that reads it, and putting something else in it does not change what
    // the readers do.
    polygonObstacles: Object.freeze([]),
    traces: Object.freeze([]),
  });
}

function halfDiagonalM(extent: TileExtentMm): number {
  return Math.hypot(extent.max[0] - extent.min[0], extent.max[1] - extent.min[1]) / 2 / MILLIMETRES;
}

/**
 * How far the field must reach from a centre to hold every corner of an extent, in metres.
 *
 * NOT the extent's own half-diagonal, which is only the answer when the centre is the extent's
 * middle. A composed world keeps its centre on the tile being walked and reaches over its
 * neighbours, so the two differ by a whole tile and a field sized to the wrong one would recover a
 * walker who had stepped onto perfectly good ground.
 */
function reachFromM(centreMm: readonly [number, number], extent: TileExtentMm): number {
  let reach = 0;
  for (const x of [extent.min[0], extent.max[0]]) {
    for (const y of [extent.min[1], extent.max[1]]) {
      reach = Math.max(reach, Math.hypot(x - centreMm[0], y - centreMm[1]));
    }
  }
  return reach / MILLIMETRES;
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
  neighbours: readonly NavigationTile[] = [],
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
      world: world(NO_SURFACE, [vx, vz], halfDiagonalM(renderExtent) + VIEWPOINT_STANDOFF_MM / MILLIMETRES, capsule),
      start: { x: vx, y: capsule.eyeHeightM, z: vz, yaw: 0, pitch },
      support: { state: 'unavailable', reason: navEnvelope === undefined
        ? 'The tile carries no nav_envelope projection, so there is nothing to stand on.'
        : 'The tile\'s nav_envelope is empty, so there is nothing to stand on: the projection is there, with its own digest, and it holds no triangle.' },
      collisionState: COLLISION_PENDING,
      viewpointOnly: true,
      capsule,
    };
  }
  const support = composedSupport([{ tile: 'the tile', projection: navEnvelope }, ...neighbours]);
  // THE TILE BEING WALKED FIXES WHERE THE WALK OPENS, AND THE NEIGHBOURS ONLY EXTEND WHAT IT CAN
  // STAND ON. Taking the centre or the stance from the composed extent would move both by half a
  // tile the moment a neighbour was loaded, so the same request would open somewhere else depending
  // on how much of the world came with it, and a pose nobody chose would be the one a frame was
  // captured from. The field's REACH is the composed one, because a walk that steps past the edge
  // onto ground this world holds must not be recovered as though it had left the world.
  const extent = support.tiles[0]!.extent;
  const middle: [number, number] = [(extent.min[0] + extent.max[0]) / 2, (extent.min[1] + extent.max[1]) / 2];
  const [cx, , cz] = tileToRenderer(middle[0], middle[1], 0);
  // Stand on the envelope nearest the middle of its southern edge, facing north.
  const [sx, , sz] = tileToRenderer(middle[0], extent.min[1], 0);
  let stance: CameraState | null = null;
  for (let step = 0; step <= 400 && stance === null; step += 1) {
    const probeZ = sz - step * SUPPORT_SAMPLE_SPACING_M;
    const sample = support.surface.sample(sx, probeZ);
    if (sample !== null) stance = { x: sx, y: sample.height + capsule.eyeHeightM, z: probeZ, yaw: 0, pitch: 0 };
  }
  if (stance === null) throw new Error('The nav_envelope has no support on its own north-south midline');
  return {
    world: world(support.surface, [cx, cz], reachFromM(middle, support.extent), capsule),
    start: stance,
    support: { state: 'nav_envelope', triangles: support.triangles, tiles: support.tiles },
    collisionState: COLLISION_PENDING,
    viewpointOnly: false,
    capsule,
  };
}
