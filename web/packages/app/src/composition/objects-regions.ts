/**
 * Where an authored object may stand and where it lands, for the objects surface.
 *
 * One factory over the surface's dependencies and its two reads of the version it holds (the saved
 * generated ground and the authorized district binding). These functions keep no state of their
 * own; `mountObjects` binds them once, before anything it runs at mount.
 */

import { generatedObjectHeight, type GeneratedObjectGround } from './generated-object-ground.js';
import {
  DISPLAY_EYE_HEIGHT,
  identityDisplayFrame,
  atlasVec3,
  type IslandId,
  type SceneDisplayFrame,
} from '@exulanica/atlas-core';
import {
  AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M,
  DEFAULT_PLACEMENT_DISTANCE_MM,
  MM_PER_METRE,
  placementLandingPose,
  placementPoseAtAtlasPoint,
  placementPoseBeforeVisitor,
  regionPointFromAtlas,
  type RegionPose,
} from '@exulanica/atlas-react/playcanvas';

import type { DistrictObjectPlacement, ObjectRegion, ObjectsDependencies } from './objects-types.js';
import type { AppEnvironment, SessionState } from './session-state.js';

/** The scene of a region whose only surface is its declared floor. */
const DECLARED_FLOOR_SCENE = 'declared-floor';

/** The functions that decide where an object may stand and where it lands, over one mount. */
export function objectRegions(
  deps: ObjectsDependencies,
  env: AppEnvironment,
  state: SessionState,
  currentGeneratedGround: () => GeneratedObjectGround | null,
  currentDistrict: () => DistrictObjectPlacement | null,
) {
  /**
   * The region an object is placed in: the one the visitor is STANDING IN, or none.
   *
   * Nearest by ground-plane distance among the regions that actually draw reconstructed geometry,
   * because an object placed in a region with nothing in it would stand on an absent floor.
   *
   * NEAREST IS NOT ENOUGH, and the browser check is what proved it. A visitor standing in a region
   * with no reconstruction still has a nearest reconstructed region, on the other side of the
   * world. Placing there converts their position into that region's frame and drops the object
   * onto THAT region's ground, so it lands at a height they are not standing at and disappears the
   * moment the distant region falls back to a stub. The person sees nothing and is told the
   * placement succeeded, which is the worst of the available outcomes.
   */
  function placementRegion(): ObjectRegion | null {
    const authored = authoredObjectRegion();
    const authoredPose = state.atlas?.binding.playerPose();
    if (authored !== null && authoredPose !== undefined && authoredContains(
      authoredPose.position.x * MM_PER_METRE,
      authoredPose.position.z * MM_PER_METRE,
    )) return authored;
    const district = currentDistrict();
    const visitor = state.atlas?.binding.playerPose();
    if (district !== null && visitor !== undefined && districtContains(district, visitor.position.x * MM_PER_METRE, visitor.position.z * MM_PER_METRE)) {
      const island = regionOf(district.regionId);
      if (island !== null) return { ...island, sceneId: 'authored-district' };
    }
    const drawn = drawnRegions();
    if (drawn.length === 0) return null;
    const pose = state.atlas?.binding.playerPose();
    if (pose === undefined) return drawn[0]!;
    let best: ObjectRegion | null = null;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const candidate of drawn) {
      const distance = Math.hypot(
        candidate.placement.position.x - pose.position.x,
        candidate.placement.position.z - pose.position.z,
      );
      const reach = candidate.footprintRadiusLocal * candidate.placement.scale * 1.5;
      // On a declared floor, standing in a region is standing on its floor, however far its
      // photographs reach.
      const standing = deps.declaredFloor === undefined
        ? distance <= reach
        : floorHolds(regionPointFromAtlas(candidate.placement, [pose.position.x, pose.position.y, pose.position.z]));
      if (distance < bestDistance && standing) {
        bestDistance = distance;
        best = candidate;
      }
    }
    return best;
  }

  function drawnRegions(): readonly ObjectRegion[] {
    const scenes = new Map<IslandId, string>();
    for (const placed of state.placedPointMaps ?? []) scenes.set(placed.islandId, placed.sceneId);
    for (const trained of state.trainedGeometry) scenes.set(trained.islandId, trained.sceneId);
    for (const islandId of state.pointMaps?.keys() ?? []) {
      if (!scenes.has(islandId)) scenes.set(islandId, `legacy:${islandId}`);
    }
    const reconstructed = deps.scene.islands.flatMap((island) => {
      const sceneId = scenes.get(island.islandId)
        ?? (deps.declaredFloor === undefined ? undefined : DECLARED_FLOOR_SCENE);
      return sceneId === undefined ? [] : [{
        regionId: island.islandId,
        placement: island.placement,
        footprintRadiusLocal: island.footprintRadiusLocal,
        sceneId,
      }];
    });
    const authored = authoredObjectRegion();
    return authored === null ? reconstructed : [authored, ...reconstructed];
  }

  function regionOf(regionId: string): ObjectRegion | null {
    const authored = authoredObjectRegion();
    if (authored !== null && String(authored.regionId) === regionId) return authored;
    const island = deps.scene.islands.find((item) => String(item.islandId) === regionId);
    if (island === undefined) return null;
    const district = currentDistrict();
    if (district?.regionId === regionId) {
      const [x, y, z] = district.translationMm;
      return {
        regionId: island.islandId,
        placement: { position: atlasVec3(x / MM_PER_METRE, y / MM_PER_METRE, z / MM_PER_METRE), yaw: 0, scale: 1 },
        footprintRadiusLocal: island.footprintRadiusLocal,
        sceneId: 'authored-district',
      };
    }
    // A live district without its authorized binding cannot fall back to an arbitrary memory root.
    if (deps.districtPlacement !== undefined && !env.preview && !drawnRegions().some(item => String(item.regionId) === regionId)) return null;
    return {
      regionId: island.islandId,
      placement: island.placement,
      footprintRadiusLocal: island.footprintRadiusLocal,
      sceneId: drawnRegions().find((item) => item.regionId === island.islandId)?.sceneId ?? 'unavailable',
    };
  }

  function authoredObjectRegion(): ObjectRegion | null {
    const region = deps.authoredRegion;
    if (region === undefined) {
      const generated = currentGeneratedGround();
      return generated === null ? null : {
        regionId: generated.regionId as IslandId,
        placement: { position: atlasVec3(0, 0, 0), yaw: 0, scale: 1 },
        footprintRadiusLocal: generated.navigation.fieldRadius,
        sceneId: 'generated-region',
      };
    }
    return {
      regionId: region.regionId as IslandId,
      placement: {
        position: atlasVec3(0, region.elevationMm / MM_PER_METRE, 0), yaw: 0, scale: 1,
      },
      /*
       * How far from the region origin somebody still counts as standing at this region.
       *
       * For a bounded ground that is the inscribed circle of its rectangle. For a ground with no
       * extent it is the distance the renderer supports, because there is no nearer place the
       * region stops being under your feet. The value stays finite either way: it is compared
       * against real distances, and an infinity would be a number no refusal could read back.
       */
      footprintRadiusLocal: region.kind === 'endless'
        ? AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M
        : Math.min(region.halfWidthMm, region.halfDepthMm) / MM_PER_METRE,
      sceneId: 'authored-starter',
    };
  }

  /**
   * Whether this world will draw and save an object at that spot on its authored ground.
   *
   * A bounded ground answers with its own declared rectangle: outside it there is no described
   * surface. An endless ground has no rectangle, so the only honest limit left is how far this
   * renderer can still draw a position, which is what
   * `AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M` states and what the walking surface uses too.
   * Both remain a browser constraint. `docs/saved-world-entry.md` says so: the general authored
   * object API validates region ownership and transforms and enforces neither bound.
   */
  /** Whether a region-local point, in millimetres, is on its region's declared floor. */
  function floorHolds(point: readonly [number, number, number] | readonly [number, number]): boolean {
    const floor = deps.declaredFloor;
    if (floor === undefined) return false;
    const [xMm, zMm] = point.length === 3 ? [point[0], point[2]] : [point[0], point[1]];
    return Math.abs(xMm) <= floor.halfExtentMm && Math.abs(zMm) <= floor.halfExtentMm;
  }

  function authoredContains(xMm: number, zMm: number): boolean {
    const region = deps.authoredRegion;
    if (region === undefined) {
      const generated = currentGeneratedGround();
      return generated !== null && generatedObjectHeight(generated, xMm, zMm) !== null;
    }
    if (region.kind === 'endless') {
      return Math.hypot(xMm, zMm) <= AUTHORED_ENDLESS_GROUND_SUPPORTED_RADIUS_M * MM_PER_METRE;
    }
    return Math.abs(xMm) <= region.halfWidthMm && Math.abs(zMm) <= region.halfDepthMm;
  }

  function districtContains(district: DistrictObjectPlacement, xMm: number, zMm: number): boolean {
    const [west, north, east, south] = district.boundsMm;
    return xMm >= west && xMm <= east && zMm >= north && zMm <= south;
  }

  /**
   * A region's display frame, or the identity when it has none.
   *
   * The frame is not part of an object's transform: the contract poses objects region-local and
   * the renderer draws them there directly. It is still read HERE, for one question only, which
   * is whether `y = 0` in that region is a measured ground or an arbitrary origin.
   */
  function frameFor(sceneId: string): SceneDisplayFrame {
    return state.displayFrames.get(sceneId) ?? identityDisplayFrame();
  }

  /** True when this region's ground was estimated from recovered cameras rather than assumed. */
  function groundIsMeasured(sceneId: string): boolean {
    return frameFor(sceneId).cameraCount > 0;
  }

  /**
   * What counts as the ground in a region, in region-local millimetres.
   *
   * A display frame derived from recovered cameras puts the estimated ground at `y = 0`, so an
   * object placed there stands on the same surface the geometry does. A region with no recovered
   * cameras has the IDENTITY frame, whose origin is the scene's own arbitrary one, and placing at
   * `y = 0` there drops the object under the floor the visitor is walking on. In that case the
   * ground is taken to be the visitor's own feet, which is an approximation and is said to be one
   * on the confirmation the person reads.
   */
  function groundMmIn(
    region: ObjectRegion,
    sceneId: string,
    pose: { readonly position: { readonly x: number; readonly y: number; readonly z: number } },
  ): number {
    if (sceneId === 'authored-starter') return 0;
    if (sceneId === 'generated-region') {
      const generated = currentGeneratedGround();
      return generated === null ? Number.NaN : generatedObjectHeight(generated, pose.position.x * 1000, pose.position.z * 1000) ?? Number.NaN;
    }
    if (sceneId === 'authored-district') return -(currentDistrict()?.translationMm[1] ?? 0);
    // Every region of a world made from photographs stands on its declared floor.
    if (deps.declaredFloor !== undefined) return deps.declaredFloor.elevationMm;
    if (groundIsMeasured(sceneId)) return 0;
    return regionPointFromAtlas(
      region.placement,
      [pose.position.x, pose.position.y - DISPLAY_EYE_HEIGHT, pose.position.z],
    )[1];
  }

  /**
   * Where a new object lands: on an engaged anchor, or a step in front of the visitor.
   *
   * The focused anchor is what "the focused point" means in this application: there is no picked
   * world point, and `engageFocusedAnchor` is the one public read of what the reticle has settled
   * on. When nothing is engaged, the object goes on the ground ahead, facing the person.
   */
  function placementPose(region: ObjectRegion, sceneId: string): RegionPose | null {
    const binding = state.atlas?.binding;
    if (binding === undefined) return null;
    const pose = binding.playerPose();
    const ground = groundMmIn(region, sceneId, pose);
    const index = sceneId === 'authored-district' || sceneId === 'authored-starter' || sceneId === 'generated-region'
      ? null : binding.engageFocusedAnchor();
    if (index !== null) {
      const at = index * 3;
      const positions = binding.table.atlasPositions;
      if (at + 2 < positions.length) {
        return placementPoseAtAtlasPoint(
          region.placement,
          [positions[at]!, positions[at + 1]!, positions[at + 2]!],
          pose,
          ground,
        );
      }
    }
    const candidate = placementPoseBeforeVisitor(region.placement, pose, DEFAULT_PLACEMENT_DISTANCE_MM, ground);
    if (sceneId !== 'generated-region') return candidate;
    const generated = currentGeneratedGround();
    const height = generated === null ? null : generatedObjectHeight(generated, candidate.xMm, candidate.zMm);
    return height === null ? null : { ...candidate, yMm: height };
  }

  /**
   * Draw the pose held for confirmation on the ground: the same `RegionPose` preview and apply
   * send. The field mark is the world field's placement landing, not the Map visitor triangle.
   */
  function showPlacementLandingMark(region: ObjectRegion, pose: RegionPose): void {
    state.atlas?.binding.field.setPlacementLandingPose(placementLandingPose(region.placement, pose));
  }

  function clearPlacementLandingMark(): void {
    state.atlas?.binding.field.setPlacementLandingPose(null);
  }

  return {
    placementRegion,
    drawnRegions,
    regionOf,
    floorHolds,
    authoredContains,
    districtContains,
    groundIsMeasured,
    groundMmIn,
    placementPose,
    showPlacementLandingMark,
    clearPlacementLandingMark,
  };
}
