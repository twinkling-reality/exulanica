import type { AtlasVec3 } from './coords.js';
import { atlasVec3 } from './coords.js';
import type { IslandId } from './ids.js';
import type { MovementModel } from './rung.js';
import { rungProperties } from './rung.js';
import type { Island } from './island.js';
import type { AtlasScene } from './scene.js';

/** The grounded Atlas contract. There is no vertical movement input and no jump. */
export const DEFAULT_EYE_HEIGHT_AU = 1.62;
export const DEFAULT_CAMERA_RADIUS_AU = 0.34;
export const REGION_APPROACH_AU = 24;
export const FIELD_MARGIN_AU = 72;
export const RECOVERY_MARGIN_AU = 48;
export const DEFAULT_MAXIMUM_SLOPE_DEGREES = 12;
export const DEFAULT_MAXIMUM_STEP_HEIGHT_AU = 0.18;
export const DEFAULT_SURFACE_SAMPLE_SPACING_AU = 0.25;

export type SpatialPhase = 'between' | 'approaching' | 'dissolve' | 'inside' | 'recovery';

export interface SurfaceNormal {
  readonly x: number;
  readonly y: number;
  readonly z: number;
}

export interface SurfaceSample {
  readonly height: number;
  readonly normal: SurfaceNormal;
}

/** Renderer-neutral height contract. Reconstructed points and splats never implement this. */
export interface NavigationSurface {
  sample(x: number, z: number): SurfaceSample | null;
}

export function flatNavigationSurface(height = 0): NavigationSurface {
  return Object.freeze({
    sample: () => Object.freeze({ height, normal: Object.freeze({ x: 0, y: 1, z: 0 }) }),
  });
}

export interface CircleObstacle {
  readonly id: string;
  readonly centre: AtlasVec3;
  readonly radius: number;
}

export interface PolygonObstacle {
  readonly id: string;
  /** Closed exterior rings in Atlas x/z units. */
  readonly rings: readonly (readonly AtlasVec3[])[];
}

export interface NavigationRegion {
  readonly islandId: IslandId;
  readonly centre: AtlasVec3;
  readonly footprintRadius: number;
  readonly dissolveStartRadius: number;
  readonly approachRadius: number;
  readonly movement: MovementModel;
  /**
   * Whether `centre` is a place somebody supplied, or a position the layout solver arranged.
   * An arranged centre is a `nonmetric_arrangement` coordinate and is no place in a world whose
   * ground is measured.
   */
  readonly placement: 'located' | 'nonmetric_arrangement';
}

/**
 * One island's navigable region, from the island alone.
 *
 * Shared rather than duplicated. A region is what travel resolves against, what spatial phase is
 * classified by, and what the approach ring is measured from, so two worlds that describe the same
 * island differently would disagree about where a memory is. The owned district builds its regions
 * from this for exactly that reason: its ground and its blockers are its own, its memories are not.
 */
export function navigationRegionForIsland(island: Island): NavigationRegion {
  const footprintRadius = Math.max(2.5, island.footprintRadiusLocal * island.placement.scale);
  return Object.freeze({
    islandId: island.islandId,
    centre: island.placement.position,
    footprintRadius,
    dissolveStartRadius: footprintRadius * 0.8,
    approachRadius: footprintRadius + REGION_APPROACH_AU,
    movement: rungProperties(island.rung).movement,
    placement: island.placementLocated === true ? 'located' : 'nonmetric_arrangement',
  });
}

export interface SemanticTrace {
  readonly from: IslandId;
  readonly to: IslandId;
  readonly start: AtlasVec3;
  readonly end: AtlasVec3;
  /** Normalized confirmed overlap. Presentation strength, never a confidence score. */
  readonly strength: number;
}

export interface NavigationWorld {
  readonly surface: NavigationSurface;
  readonly eyeHeight: number;
  readonly cameraRadius: number;
  readonly centre: AtlasVec3;
  readonly fieldRadius: number;
  readonly recoveryRadius: number;
  readonly maximumSlopeDegrees: number;
  readonly maximumStepHeight: number;
  readonly surfaceSampleSpacing: number;
  readonly regions: readonly NavigationRegion[];
  readonly obstacles: readonly CircleObstacle[];
  readonly polygonObstacles?: readonly PolygonObstacle[];
  readonly traces: readonly SemanticTrace[];
}

function groundDistance(a: AtlasVec3, b: AtlasVec3): number {
  return Math.hypot(a.x - b.x, a.z - b.z);
}

export function isNavigationPositionClear(
  world: NavigationWorld,
  position: AtlasVec3,
  radius = world.cameraRadius,
): boolean {
  return world.obstacles.every(
    (obstacle) => groundDistance(position, obstacle.centre) >= obstacle.radius + radius,
  ) && (world.polygonObstacles ?? []).every(
    (obstacle) => !polygonContainsOrTouches(obstacle, position, radius),
  );
}

/**
 * Build the local resident field from stable scene placements.
 *
 * The circle footprint is a broad-phase slice. Long-term authored footprint SDFs replace it
 * without changing the surface, collision, phase, or renderer contracts.
 */
export function buildNavigationWorld(
  scene: AtlasScene,
  surface: NavigationSurface = flatNavigationSurface(),
): NavigationWorld {
  let cx = 0;
  let cz = 0;
  for (const island of scene.islands) {
    cx += island.placement.position.x;
    cz += island.placement.position.z;
  }
  const count = Math.max(scene.islands.length, 1);
  const centre = atlasVec3(cx / count, 0, cz / count);

  const regions: NavigationRegion[] = [];
  const obstacles: CircleObstacle[] = [];
  let contentRadius = 18;
  for (let index = 0; index < scene.islands.length; index += 1) {
    const island = scene.islands[index]!;
    const region = navigationRegionForIsland(island);
    regions.push(region);
    contentRadius = Math.max(
      contentRadius,
      groundDistance(centre, island.placement.position) + region.footprintRadius,
    );
    /*
     * No blocker per region any more.
     *
     * There used to be one: a 1.75 unit circle standing in for the source photograph that hung
     * over every no-geometry region. The photograph is gone from the 3D world, and a collider with
     * nothing drawn at it is worse than either, because it stops a walk with no visible cause.
     * Regions that do have a body get their collision from that body.
     */
  }

  const traces: SemanticTrace[] = [];
  for (let i = 0; i < scene.islands.length; i += 1) {
    const a = scene.islands[i]!;
    for (let j = i + 1; j < scene.islands.length; j += 1) {
      const b = scene.islands[j]!;
      let shared = 0;
      for (const entity of a.layoutEntities) if (b.layoutEntities.has(entity)) shared += 1;
      if (shared === 0) continue;
      const denominator = Math.sqrt(Math.max(1, a.layoutEntities.size * b.layoutEntities.size));
      traces.push(Object.freeze({
        from: a.islandId,
        to: b.islandId,
        start: a.placement.position,
        end: b.placement.position,
        strength: Math.min(1, shared / denominator),
      }));
    }
  }

  const fieldRadius = Math.max(90, contentRadius + FIELD_MARGIN_AU);
  return Object.freeze({
    surface,
    eyeHeight: DEFAULT_EYE_HEIGHT_AU,
    cameraRadius: DEFAULT_CAMERA_RADIUS_AU,
    centre,
    fieldRadius,
    recoveryRadius: fieldRadius + RECOVERY_MARGIN_AU,
    maximumSlopeDegrees: DEFAULT_MAXIMUM_SLOPE_DEGREES,
    maximumStepHeight: DEFAULT_MAXIMUM_STEP_HEIGHT_AU,
    surfaceSampleSpacing: DEFAULT_SURFACE_SAMPLE_SPACING_AU,
    regions: Object.freeze(regions),
    obstacles: Object.freeze(obstacles),
    traces: Object.freeze(traces),
  });
}

export interface SpatialClassification {
  readonly phase: SpatialPhase;
  readonly islandId: IslandId | null;
  /** Signed distance to the nearest footprint: negative is inside. */
  readonly footprintDistance: number;
}

export function classifySpatialPhase(world: NavigationWorld, position: AtlasVec3): SpatialClassification {
  if (groundDistance(position, world.centre) > world.fieldRadius) {
    return Object.freeze({ phase: 'recovery', islandId: null, footprintDistance: Infinity });
  }
  let nearest: NavigationRegion | null = null;
  let nearestDistance = Infinity;
  for (const region of world.regions) {
    const d = groundDistance(position, region.centre) - region.footprintRadius;
    if (d < nearestDistance) {
      nearestDistance = d;
      nearest = region;
    }
  }
  if (nearest === null) {
    return Object.freeze({ phase: 'between', islandId: null, footprintDistance: Infinity });
  }
  const radial = nearestDistance + nearest.footprintRadius;
  const phase: SpatialPhase =
    nearestDistance > REGION_APPROACH_AU
      ? 'between'
      : nearestDistance > 0
        ? 'approaching'
        : radial >= nearest.dissolveStartRadius
          ? 'dissolve'
          : 'inside';
  return Object.freeze({ phase, islandId: phase === 'between' ? null : nearest.islandId, footprintDistance: nearestDistance });
}

interface CollisionResult {
  readonly position: AtlasVec3;
  readonly collided: boolean;
}

function pushOutside(position: AtlasVec3, obstacle: CircleObstacle, radius: number): AtlasVec3 {
  const dx = position.x - obstacle.centre.x;
  const dz = position.z - obstacle.centre.z;
  const d = Math.hypot(dx, dz);
  const required = obstacle.radius + radius;
  if (d >= required) return position;
  const nx = d < 1e-9 ? 1 : dx / d;
  const nz = d < 1e-9 ? 0 : dz / d;
  return atlasVec3(obstacle.centre.x + nx * required, position.y, obstacle.centre.z + nz * required);
}

/** Continuous circle sweep with one tangential slide, sufficient for the coarse foundational proxy. */
function collideAndSlide(
  startInput: AtlasVec3,
  targetInput: AtlasVec3,
  obstacles: readonly CircleObstacle[],
  cameraRadius: number,
): CollisionResult {
  let start = startInput;
  let target = targetInput;
  let collided = false;

  for (const obstacle of obstacles) {
    start = pushOutside(start, obstacle, cameraRadius);
  }

  for (let pass = 0; pass < 3; pass += 1) {
    const vx = target.x - start.x;
    const vz = target.z - start.z;
    const a = vx * vx + vz * vz;
    if (a < 1e-12) break;
    let hit: { obstacle: CircleObstacle; t: number } | null = null;
    for (const obstacle of obstacles) {
      const radius = obstacle.radius + cameraRadius;
      const ox = start.x - obstacle.centre.x;
      const oz = start.z - obstacle.centre.z;
      const b = 2 * (ox * vx + oz * vz);
      const c = ox * ox + oz * oz - radius * radius;
      const disc = b * b - 4 * a * c;
      if (disc < 0) continue;
      const t = (-b - Math.sqrt(disc)) / (2 * a);
      if (t < 0 || t > 1 || (hit !== null && t >= hit.t)) continue;
      hit = { obstacle, t };
    }
    if (hit === null) {
      start = target;
      break;
    }

    collided = true;
    const safeT = Math.max(0, hit.t - 1e-4);
    const contact = atlasVec3(start.x + vx * safeT, target.y, start.z + vz * safeT);
    const dx = contact.x - hit.obstacle.centre.x;
    const dz = contact.z - hit.obstacle.centre.z;
    const len = Math.max(Math.hypot(dx, dz), 1e-9);
    const nx = dx / len;
    const nz = dz / len;
    const rx = target.x - contact.x;
    const rz = target.z - contact.z;
    const inward = Math.min(0, rx * nx + rz * nz);
    start = contact;
    target = atlasVec3(contact.x + rx - inward * nx, target.y, contact.z + rz - inward * nz);
  }

  return Object.freeze({ position: start, collided });
}

function pointSegmentDistance(
  point: AtlasVec3,
  a: AtlasVec3,
  b: AtlasVec3,
): number {
  const dx = b.x - a.x;
  const dz = b.z - a.z;
  const length2 = dx * dx + dz * dz;
  const t = length2 < 1e-12 ? 0 : Math.max(
    0,
    Math.min(1, ((point.x - a.x) * dx + (point.z - a.z) * dz) / length2),
  );
  return Math.hypot(point.x - (a.x + t * dx), point.z - (a.z + t * dz));
}

function pointInRing(point: AtlasVec3, ring: readonly AtlasVec3[]): boolean {
  let inside = false;
  for (let index = 0, prior = ring.length - 1; index < ring.length; prior = index++) {
    const a = ring[index]!;
    const b = ring[prior]!;
    if (
      (a.z > point.z) !== (b.z > point.z) &&
      point.x < (b.x - a.x) * (point.z - a.z) / (b.z - a.z) + a.x
    ) inside = !inside;
  }
  return inside;
}

function polygonContainsOrTouches(
  obstacle: PolygonObstacle,
  point: AtlasVec3,
  radius: number,
): boolean {
  for (const ring of obstacle.rings) {
    if (pointInRing(point, ring)) return true;
    for (let index = 1; index < ring.length; index += 1) {
      if (pointSegmentDistance(point, ring[index - 1]!, ring[index]!) < radius) return true;
    }
  }
  return false;
}

/**
 * Conservative swept capsule resolution against exact footprint edges.
 *
 * Sampling is bounded to at most half a capsule radius, so a move cannot tunnel through an edge.
 * The final binary search places the capsule immediately before first contact and preserves a
 * tangential slide on the remaining displacement.
 */
function collidePolygonsAndSlide(
  startInput: AtlasVec3,
  targetInput: AtlasVec3,
  obstacles: readonly PolygonObstacle[],
  radius: number,
): CollisionResult {
  let start = startInput;
  let target = targetInput;
  let collided = false;
  for (let pass = 0; pass < 3; pass += 1) {
    const distance = groundDistance(start, target);
    const steps = Math.max(1, Math.ceil(distance / Math.max(radius * 0.5, 0.05)));
    let hitStep = -1;
    let hitObstacle: PolygonObstacle | null = null;
    for (let step = 1; step <= steps && hitStep < 0; step += 1) {
      const t = step / steps;
      const sample = atlasVec3(
        start.x + (target.x - start.x) * t,
        target.y,
        start.z + (target.z - start.z) * t,
      );
      for (const obstacle of obstacles) {
        if (polygonContainsOrTouches(obstacle, sample, radius)) {
          hitStep = step;
          hitObstacle = obstacle;
          break;
        }
      }
    }
    if (hitStep < 0 || hitObstacle === null) return Object.freeze({ position: target, collided });
    collided = true;
    let low = (hitStep - 1) / steps;
    let high = hitStep / steps;
    for (let iteration = 0; iteration < 12; iteration += 1) {
      const middle = (low + high) / 2;
      const sample = atlasVec3(
        start.x + (target.x - start.x) * middle,
        target.y,
        start.z + (target.z - start.z) * middle,
      );
      if (polygonContainsOrTouches(hitObstacle, sample, radius)) high = middle;
      else low = middle;
    }
    const contact = atlasVec3(
      start.x + (target.x - start.x) * low,
      target.y,
      start.z + (target.z - start.z) * low,
    );
    let nearestA: AtlasVec3 | null = null;
    let nearestB: AtlasVec3 | null = null;
    let nearest = Infinity;
    for (const ring of hitObstacle.rings) {
      for (let index = 1; index < ring.length; index += 1) {
        const a = ring[index - 1]!;
        const b = ring[index]!;
        const value = pointSegmentDistance(contact, a, b);
        if (value < nearest) {
          nearest = value;
          nearestA = a;
          nearestB = b;
        }
      }
    }
    if (nearestA === null || nearestB === null) return Object.freeze({ position: contact, collided });
    const edgeX = nearestB.x - nearestA.x;
    const edgeZ = nearestB.z - nearestA.z;
    const edgeLength = Math.max(Math.hypot(edgeX, edgeZ), 1e-9);
    const tangentX = edgeX / edgeLength;
    const tangentZ = edgeZ / edgeLength;
    const remainingX = target.x - contact.x;
    const remainingZ = target.z - contact.z;
    const along = remainingX * tangentX + remainingZ * tangentZ;
    start = contact;
    target = atlasVec3(contact.x + tangentX * along, target.y, contact.z + tangentZ * along);
  }
  return Object.freeze({ position: start, collided });
}

function nearestRegionEntry(world: NavigationWorld, from: AtlasVec3): AtlasVec3 {
  let nearest = world.regions[0];
  let distance = Infinity;
  for (const region of world.regions) {
    const d = groundDistance(from, region.centre);
    if (d < distance) {
      distance = d;
      nearest = region;
    }
  }
  if (nearest === undefined) return atlasVec3(world.centre.x, world.eyeHeight, world.centre.z);
  const dx = world.centre.x - nearest.centre.x;
  const dz = world.centre.z - nearest.centre.z;
  const len = Math.hypot(dx, dz);
  const nx = len < 1e-9 ? 0 : dx / len;
  const nz = len < 1e-9 ? 1 : dz / len;
  const sample = world.surface.sample(
    nearest.centre.x + nx * (nearest.footprintRadius + 2),
    nearest.centre.z + nz * (nearest.footprintRadius + 2),
  );
  const height = sample?.height ?? 0;
  return atlasVec3(
    nearest.centre.x + nx * (nearest.footprintRadius + 2),
    height + world.eyeHeight,
    nearest.centre.z + nz * (nearest.footprintRadius + 2),
  );
}

export interface GroundMovementInput {
  readonly current: AtlasVec3;
  readonly desired: AtlasVec3;
  readonly lastSafe: AtlasVec3 | null;
}

export interface GroundMovementResolution {
  readonly position: AtlasVec3;
  readonly lastSafe: AtlasVec3;
  readonly spatial: SpatialClassification;
  readonly collided: boolean;
  readonly recovered: boolean;
  readonly recoveryReason: 'outside-field' | 'no-surface' | 'unsafe-surface' | null;
}

type SurfacePathFailure = 'no-surface' | 'unsafe-surface';

function surfaceSlopeDegrees(normal: SurfaceNormal): number {
  const length = Math.hypot(normal.x, normal.y, normal.z);
  if (length < 1e-9 || normal.y <= 0) return 180;
  return (Math.acos(Math.max(-1, Math.min(1, normal.y / length))) * 180) / Math.PI;
}

function surfacePathFailure(
  world: NavigationWorld,
  from: AtlasVec3,
  to: AtlasVec3,
): SurfacePathFailure | null {
  const distance = groundDistance(from, to);
  const steps = Math.max(1, Math.ceil(distance / world.surfaceSampleSpacing));
  let previous: SurfaceSample | null = null;
  for (let index = 0; index <= steps; index += 1) {
    const t = index / steps;
    const sample = world.surface.sample(
      from.x + (to.x - from.x) * t,
      from.z + (to.z - from.z) * t,
    );
    if (sample === null) return 'no-surface';
    if (
      !Number.isFinite(sample.height) ||
      surfaceSlopeDegrees(sample.normal) > world.maximumSlopeDegrees
    ) return 'unsafe-surface';
    if (
      previous !== null &&
      Math.abs(sample.height - previous.height) > world.maximumStepHeight
    ) return 'unsafe-surface';
    previous = sample;
  }
  return null;
}

/**
 * Whether the ground itself runs all the way, ignoring anything standing on it.
 *
 * The weaker half of the path gate, and the half that is about the world rather than about
 * walking. A hole, a cliff, or an edge of the admitted field means there is nowhere to be along
 * the way, and that is true however you cross it. A building means only that you cannot walk
 * through it.
 */
export function isNavigationGroundPathContinuous(
  world: NavigationWorld,
  from: AtlasVec3,
  to: AtlasVec3,
): boolean {
  return groundDistance(to, world.centre) <= world.fieldRadius
    && surfacePathFailure(world, from, to) === null;
}

/** Full grounded path gate used by both locomotion and direct travel. */
export function isNavigationPathClear(
  world: NavigationWorld,
  from: AtlasVec3,
  to: AtlasVec3,
): boolean {
  if (!isNavigationGroundPathContinuous(world, from, to)) return false;
  if (collideAndSlide(from, to, world.obstacles, world.cameraRadius).collided) return false;
  return !collidePolygonsAndSlide(
    from,
    to,
    world.polygonObstacles ?? [],
    world.cameraRadius,
  ).collided;
}

/** Resolve one intended planar move against surface, coarse blockers, soft bounds, and recovery. */
export function resolveGroundMovement(
  world: NavigationWorld,
  input: GroundMovementInput,
): GroundMovementResolution {
  const desiredDistance = groundDistance(input.desired, world.centre);
  const rawSample = world.surface.sample(input.desired.x, input.desired.z);
  if (rawSample === null || desiredDistance > world.recoveryRadius) {
    const fallback = input.lastSafe ?? nearestRegionEntry(world, input.current);
    return Object.freeze({
      position: fallback,
      lastSafe: fallback,
      spatial: classifySpatialPhase(world, fallback),
      collided: false,
      recovered: true,
      recoveryReason: rawSample === null ? 'no-surface' : 'outside-field',
    });
  }

  let x = input.desired.x;
  let z = input.desired.z;
  if (desiredDistance > world.fieldRadius) {
    // Resistance, not an invisible wall. The hard recovery envelope remains farther out.
    const dx = x - world.centre.x;
    const dz = z - world.centre.z;
    const compressed = world.fieldRadius + (desiredDistance - world.fieldRadius) * 0.22;
    x = world.centre.x + (dx / desiredDistance) * compressed;
    z = world.centre.z + (dz / desiredDistance) * compressed;
  }
  const sample = world.surface.sample(x, z);
  const target = sample === null ? null : atlasVec3(x, sample.height + world.eyeHeight, z);
  const pathFailure = target === null ? 'no-surface' : surfacePathFailure(world, input.current, target);
  if (sample === null || target === null || pathFailure !== null) {
    const fallback = input.lastSafe ?? nearestRegionEntry(world, input.current);
    return Object.freeze({
      position: fallback,
      lastSafe: fallback,
      spatial: classifySpatialPhase(world, fallback),
      collided: false,
      recovered: true,
      recoveryReason: pathFailure ?? 'no-surface',
    });
  }
  const circleCollision = collideAndSlide(
    input.current,
    target,
    world.obstacles,
    world.cameraRadius,
  );
  const polygonCollision = collidePolygonsAndSlide(
    input.current,
    circleCollision.position,
    world.polygonObstacles ?? [],
    world.cameraRadius,
  );
  const collision = Object.freeze({
    position: polygonCollision.position,
    collided: circleCollision.collided || polygonCollision.collided,
  });
  const resolvedPathFailure = surfacePathFailure(world, input.current, collision.position);
  if (resolvedPathFailure !== null) {
    const fallback = input.lastSafe ?? nearestRegionEntry(world, input.current);
    return Object.freeze({
      position: fallback,
      lastSafe: fallback,
      spatial: classifySpatialPhase(world, fallback),
      collided: collision.collided,
      recovered: true,
      recoveryReason: resolvedPathFailure,
    });
  }
  const finalSample = world.surface.sample(collision.position.x, collision.position.z) ?? sample;
  const position = atlasVec3(collision.position.x, finalSample.height + world.eyeHeight, collision.position.z);
  const safe = groundDistance(position, world.centre) <= world.fieldRadius;
  const lastSafe = safe ? position : (input.lastSafe ?? nearestRegionEntry(world, position));
  return Object.freeze({
    position,
    lastSafe,
    spatial: classifySpatialPhase(world, position),
    collided: collision.collided,
    recovered: false,
    recoveryReason: null,
  });
}

/**
 * Coarse line-of-sight against the same blockers used by locomotion.
 *
 * This intentionally ignores points and splats. A source body may occlude focus; reconstructed
 * samples may not invent solid walls.
 */
export function isNavigationLineVisible(
  world: NavigationWorld,
  from: AtlasVec3,
  to: AtlasVec3,
): boolean {
  const vx = to.x - from.x;
  const vz = to.z - from.z;
  const length2 = vx * vx + vz * vz;
  if (length2 < 1e-12) return true;
  for (const obstacle of world.obstacles) {
    const t = Math.max(
      0,
      Math.min(
        1,
        ((obstacle.centre.x - from.x) * vx + (obstacle.centre.z - from.z) * vz) / length2,
      ),
    );
    const x = from.x + vx * t;
    const z = from.z + vz * t;
    if (Math.hypot(x - obstacle.centre.x, z - obstacle.centre.z) < obstacle.radius) return false;
  }
  return true;
}

export interface CorridorRule {
  readonly movement: 'corridor';
  readonly centreline: readonly AtlasVec3[];
  readonly halfWidth: number;
}

export interface OpenTraversalRule {
  readonly movement: 'free' | 'panels' | 'cards';
  readonly obstacles: readonly CircleObstacle[];
  readonly cameraRadius?: number;
}

export type RegionTraversalRule = CorridorRule | OpenTraversalRule;

/** Apply the reconstruction-rung local policy without granting any renderer extra freedom. */
export function constrainRegionTraversal(
  rule: RegionTraversalRule,
  current: AtlasVec3,
  desired: AtlasVec3,
): AtlasVec3 {
  if (rule.movement !== 'corridor') {
    return collideAndSlide(current, desired, rule.obstacles, rule.cameraRadius ?? DEFAULT_CAMERA_RADIUS_AU).position;
  }
  if (rule.centreline.length === 0) return current;
  if (rule.centreline.length === 1) {
    const only = rule.centreline[0]!;
    return atlasVec3(only.x, desired.y, only.z);
  }
  let closest = rule.centreline[0]!;
  let best = Infinity;
  for (let i = 0; i < rule.centreline.length - 1; i += 1) {
    const a = rule.centreline[i]!;
    const b = rule.centreline[i + 1]!;
    const vx = b.x - a.x;
    const vz = b.z - a.z;
    const length2 = vx * vx + vz * vz;
    const t = length2 < 1e-12 ? 0 : Math.max(0, Math.min(1, ((desired.x - a.x) * vx + (desired.z - a.z) * vz) / length2));
    const p = atlasVec3(a.x + vx * t, desired.y, a.z + vz * t);
    const d = groundDistance(desired, p);
    if (d < best) {
      best = d;
      closest = p;
    }
  }
  if (best <= rule.halfWidth) return atlasVec3(desired.x, desired.y, desired.z);
  const dx = desired.x - closest.x;
  const dz = desired.z - closest.z;
  const len = Math.max(Math.hypot(dx, dz), 1e-9);
  return atlasVec3(
    closest.x + (dx / len) * Math.max(0, rule.halfWidth),
    desired.y,
    closest.z + (dz / len) * Math.max(0, rule.halfWidth),
  );
}

export interface NavigationPose {
  readonly position: AtlasVec3;
  readonly yaw: number;
  readonly pitch: number;
}

export interface MapPresentationState {
  readonly mode: 'map';
  readonly ground: NavigationPose;
  readonly active: NavigationPose;
}

/** Same scene, derived overview pose. It consumes persisted presentation placement only. */
export function atlasMapPose(scene: AtlasScene): NavigationPose {
  if (scene.islands.length === 0) {
    const y = 28;
    return Object.freeze({
      position: atlasVec3(0, y, y / Math.tan((55 * Math.PI) / 180)),
      yaw: 0,
      pitch: -(55 * Math.PI) / 180,
    });
  }
  let x = 0;
  let z = 0;
  for (const island of scene.islands) {
    x += island.placement.position.x;
    z += island.placement.position.z;
  }
  x /= scene.islands.length;
  z /= scene.islands.length;
  let radius = 8;
  for (const island of scene.islands) {
    radius = Math.max(
      radius,
      Math.hypot(island.placement.position.x - x, island.placement.position.z - z) +
        island.footprintRadiusLocal * island.placement.scale,
    );
  }
  const y = Math.max(28, radius * 1.45);
  return Object.freeze({
    position: atlasVec3(x, y, z + y / Math.tan((55 * Math.PI) / 180)),
    yaw: 0,
    pitch: -(55 * Math.PI) / 180,
  });
}

export function enterAtlasMap(scene: AtlasScene, ground: NavigationPose): MapPresentationState {
  return Object.freeze({ mode: 'map', ground: Object.freeze({ ...ground }), active: atlasMapPose(scene) });
}

/** Byte-for-byte ground values; Map input never mutates this snapshot. */
export function exitAtlasMap(state: MapPresentationState): NavigationPose {
  return state.ground;
}
