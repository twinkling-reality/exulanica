import type { AtlasVec3 } from './coords.js';
import { atlasVec3 } from './coords.js';
import type { AnchorId, IslandId } from './ids.js';
import {
  isNavigationGroundPathContinuous,
  isNavigationLineVisible,
  isNavigationPathClear,
  isNavigationPositionClear,
  type NavigationPose,
  type NavigationWorld,
} from './navigation.js';
import type { AtlasScene } from './scene.js';
import { anchorAtlasPosition, buildAnchorTable } from './scene.js';

export const DIRECT_NAVIGATION_DURATION_MS = 1200;

export type DirectNavigationTarget =
  | { readonly kind: 'island'; readonly islandId: IslandId }
  | { readonly kind: 'anchor'; readonly anchorId: AnchorId };

export type DirectNavigationFailureReason =
  | 'unknown-target'
  | 'outside-resident-field'
  | 'no-safe-surface'
  | 'occluded';

export type DirectNavigationResolution =
  | {
      readonly ok: true;
      readonly target: DirectNavigationTarget;
      readonly islandId: IslandId;
      readonly pose: NavigationPose;
      readonly targetPosition: AtlasVec3;
    }
  | {
      readonly ok: false;
      readonly target: DirectNavigationTarget;
      readonly reason: DirectNavigationFailureReason;
    };

export interface DirectNavigationTransition {
  readonly target: DirectNavigationTarget;
  readonly islandId: IslandId;
  readonly from: NavigationPose;
  readonly to: NavigationPose;
  readonly durationMs: number;
}

function poseLookingAt(position: AtlasVec3, target: AtlasVec3): NavigationPose {
  const dx = target.x - position.x;
  const dy = target.y - position.y;
  const dz = target.z - position.z;
  const horizontal = Math.max(Math.hypot(dx, dz), 1e-9);
  return Object.freeze({
    position,
    yaw: Math.atan2(-dx, -dz),
    pitch: Math.atan2(dy, horizontal),
  });
}

function candidateAngles(target: AtlasVec3, current: AtlasVec3): readonly number[] {
  const dx = current.x - target.x;
  const dz = current.z - target.z;
  const base = Math.hypot(dx, dz) < 1e-6 ? Math.PI / 2 : Math.atan2(dz, dx);
  return Object.freeze([
    base,
    base + Math.PI / 4,
    base - Math.PI / 4,
    base + Math.PI / 2,
    base - Math.PI / 2,
    base + (3 * Math.PI) / 4,
    base - (3 * Math.PI) / 4,
    base + Math.PI,
  ]);
}

/**
 * How many standing distances to try before giving up on a target.
 *
 * The authored distance is always rung zero, so wherever a vantage already resolved it resolves to
 * the same pose and the arrival is unchanged. The rungs above it exist for one case: a region whose
 * own centre is inside a building. On the Flatiron district that is not hypothetical, region
 * `...0703` stands inside `doitt_id:307647`, a 29.5 by 33.4 metre block, and its authored ring of
 * 2.8 metres is entirely interior, so all eight angles failed and travel reported no safe surface
 * about ground that is merely occupied.
 */
const OUTWARD_SEARCH_RUNGS = 6;

/**
 * What the search found, or what it ran out of.
 *
 * The reason travels with the result rather than being recomputed by a second function. An earlier
 * version asked a separate helper "was there ground?" to choose between `occluded` and
 * `no-safe-surface`, and the two walked different distances, so a target the search had given up on
 * at the first ring was explained by ground six rings further out. One sweep, one answer.
 */
interface PoseSearch {
  readonly pose: NavigationPose | null;
  /** Ground was reached, and every candidate on it was refused for a reason other than footing. */
  readonly sawReachableGround: boolean;
}

/**
 * Find somewhere to stand, from the authored distance outward to a caller-supplied limit.
 *
 * The limit matters more than the ladder. Stepping outward without one would answer "reachable" by
 * depositing someone far enough away that the thing they asked to see is a few pixels, which is a
 * worse lie than refusing. Callers pass the distance at which they are still at the target.
 */
function safePoseAround(
  world: NavigationWorld,
  target: AtlasVec3,
  current: AtlasVec3,
  distance: number,
  requireLineOfSight: boolean,
  maximumDistance: number = distance,
  /**
   * Whether solid bodies between here and there disqualify a destination.
   *
   * The ground underfoot is checked either way: `isNavigationGroundPathContinuous` still has to
   * hold, so a hole, a cliff or the edge of the admitted field refuses travel exactly as before.
   * What this drops is only the blockers standing on that ground.
   *
   * It stays on for an anchor, where travel is a short move to a source body already in front of
   * you. It comes off for a region, and not as a preference: `sampleDirectNavigationTransition`
   * interpolates the pose linearly from here to there, so the transition passes over whatever lies
   * between no matter what this returns. The blocker half never governed the motion; it only
   * decided whether the destination was offered.
   *
   * On open archipelago ground the distinction almost never showed, since a straight line to a
   * region rarely met the one coarse blocker per island. Over an owned district it is the whole
   * story. Measured on the Flatiron district, across all three regions that have ground: of the 81
   * candidate standing points with a surface and outside any building, the blocker test rejected
   * every single one, 47 and 24 and 10, because a straight line of 200-plus metres across a city
   * always crosses a block. Requiring an unobstructed corridor to a place you are flown to refused
   * the whole archival landscape to enforce a property of walking there.
   */
  requireUnblockedPath = true,
): PoseSearch {
  const span = Math.max(0, maximumDistance - distance);
  const rungs = span < 1e-6 ? 1 : OUTWARD_SEARCH_RUNGS;
  let sawReachableGround = false;
  for (let rung = 0; rung < rungs; rung += 1) {
    const radius = rungs === 1 ? distance : distance + (span * rung) / (rungs - 1);
    /*
     * Whether this rung failed because something is STANDING on reachable ground.
     *
     * The ladder only exists to walk out from under a body, so it may only advance for that
     * reason. A rung that failed because the ground runs out is a different fact and must end the
     * search: stepping further out to get around a hole would answer a request to stand at a
     * region by standing on the far side of a discontinuity the world says is not crossable.
     */
    let blockedOnReachableGround = false;
    for (const angle of candidateAngles(target, current)) {
      const x = target.x + Math.cos(angle) * radius;
      const z = target.z + Math.sin(angle) * radius;
      if (Math.hypot(x - world.centre.x, z - world.centre.z) > world.fieldRadius) continue;
      const sample = world.surface.sample(x, z);
      if (sample === null) continue;
      const position = atlasVec3(x, sample.height + world.eyeHeight, z);
      // The ground between here and there is required either way. Only the bodies on it are not.
      if (!isNavigationGroundPathContinuous(world, current, position)) continue;
      // Footing exists and can be walked to. Anything that refuses it from here on is a body or a
      // sightline, never the floor, which is what separates `occluded` from `no-safe-surface`.
      sawReachableGround = true;
      // Where you are put down is still held to everything: real ground, inside the field, and
      // not inside a body. Only the corridor to it is relaxed.
      if (!isNavigationPositionClear(world, position)) { blockedOnReachableGround = true; continue; }
      if (requireUnblockedPath && !isNavigationPathClear(world, current, position)) continue;
      if (requireLineOfSight && !isNavigationLineVisible(world, position, target)) continue;
      return Object.freeze({ pose: poseLookingAt(position, target), sawReachableGround });
    }
    if (!blockedOnReachableGround) break;
  }
  return Object.freeze({ pose: null, sawReachableGround });
}

/** Resolve a deterministic safe region entry or exact anchor vantage inside the resident field. */
export function resolveDirectNavigation(
  scene: AtlasScene,
  world: NavigationWorld,
  target: DirectNavigationTarget,
  current: AtlasVec3,
): DirectNavigationResolution {
  if (target.kind === 'island') {
    const island = scene.islands.find((value) => value.islandId === target.islandId);
    if (island === undefined) return Object.freeze({ ok: false, target, reason: 'unknown-target' });
    const region = world.regions.find((value) => value.islandId === target.islandId);
    if (region === undefined) {
      return Object.freeze({ ok: false, target, reason: 'outside-resident-field' });
    }
    const sample = world.surface.sample(region.centre.x, region.centre.z);
    const targetPosition = atlasVec3(
      region.centre.x,
      (sample?.height ?? region.centre.y) + world.eyeHeight * 0.45,
      region.centre.z,
    );
    const distance = Math.max(1, Math.min(region.footprintRadius * 0.55, region.footprintRadius - 0.8));
    // Out to the region's own approach ring and no further. Past that the world's own vocabulary
    // stops calling it this region, so a pose there would not be an arrival at it.
    const search = safePoseAround(
      world, targetPosition, current, distance, false, region.approachRadius, false,
    );
    if (search.pose !== null) {
      return Object.freeze({
        ok: true, target, islandId: island.islandId, pose: search.pose, targetPosition,
      });
    }
    // Say which of the two it is. A region built over and a region with no floor under it are
    // different facts, and the interface repeats whichever one this returns back to the person.
    return Object.freeze({
      ok: false,
      target,
      reason: search.sawReachableGround ? 'occluded' : 'no-safe-surface',
    });
  }

  const table = buildAnchorTable(scene);
  const index = table.indexOf.get(target.anchorId);
  if (index === undefined) return Object.freeze({ ok: false, target, reason: 'unknown-target' });
  const anchor = table.anchors[index]!;
  const island = scene.islands.find((value) => value.islandId === anchor.islandId);
  const region = world.regions.find((value) => value.islandId === anchor.islandId);
  if (island === undefined || region === undefined) {
    return Object.freeze({ ok: false, target, reason: 'outside-resident-field' });
  }
  const targetPosition = anchorAtlasPosition(table, index);
  const distance = Math.max(2.4, table.focusRadii[index]! + 1.8);
  const search = safePoseAround(world, targetPosition, current, distance, true);
  if (search.pose !== null) {
    return Object.freeze({
      ok: true, target, islandId: island.islandId, pose: search.pose, targetPosition,
    });
  }
  // Distinguish a missing surface from an occluded target for truthful recovery copy.
  return Object.freeze({
    ok: false,
    target,
    reason: search.sawReachableGround ? 'occluded' : 'no-safe-surface',
  });
}

export function planDirectNavigationTransition(
  resolution: Extract<DirectNavigationResolution, { readonly ok: true }>,
  from: NavigationPose,
  reducedMotion: boolean,
): DirectNavigationTransition {
  return Object.freeze({
    target: resolution.target,
    islandId: resolution.islandId,
    from: Object.freeze({ ...from }),
    to: resolution.pose,
    durationMs: reducedMotion ? 0 : DIRECT_NAVIGATION_DURATION_MS,
  });
}

const shortestAngle = (from: number, to: number): number =>
  ((((to - from) % (Math.PI * 2)) + Math.PI * 3) % (Math.PI * 2)) - Math.PI;

/** Sample the same transition for rendering and tests. Endpoints are exact, not asymptotic. */
export function sampleDirectNavigationTransition(
  transition: DirectNavigationTransition,
  elapsedMs: number,
): NavigationPose {
  const raw = transition.durationMs === 0 ? 1 : Math.max(0, Math.min(1, elapsedMs / transition.durationMs));
  const t = raw < 0.5 ? 4 * raw * raw * raw : 1 - Math.pow(-2 * raw + 2, 3) / 2;
  const from = transition.from;
  const to = transition.to;
  if (raw === 1) return to;
  if (raw === 0) return from;
  return Object.freeze({
    position: atlasVec3(
      from.position.x + (to.position.x - from.position.x) * t,
      from.position.y + (to.position.y - from.position.y) * t,
      from.position.z + (to.position.z - from.position.z) * t,
    ),
    yaw: from.yaw + shortestAngle(from.yaw, to.yaw) * t,
    pitch: from.pitch + (to.pitch - from.pitch) * t,
  });
}
