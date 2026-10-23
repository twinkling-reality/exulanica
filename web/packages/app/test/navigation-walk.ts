/**
 * TEST SUPPORT: a tile's walk over a test's own surface, whole: the page reads where a person may walk by the walk's
 * own gate (atlas-core's `isNavigationGroundPathContinuous`), which reads each sample's slope and the step between
 * samples against the walk's limits, so a test's surface states a normal and the walk states atlas-core's defaults.
 * Its field reaches every point a test asks after.
 */
import {
  DEFAULT_CAMERA_RADIUS_AU,
  DEFAULT_MAXIMUM_SLOPE_DEGREES,
  DEFAULT_MAXIMUM_STEP_HEIGHT_AU,
  DEFAULT_SURFACE_SAMPLE_SPACING_AU,
  atlasVec3,
  type NavigationWorld,
  type SurfaceSample,
} from '@exulanica/atlas-core';

/** Level ground's normal. */
export const LEVEL = Object.freeze({ x: 0, y: 1, z: 0 });

/** A walk over `sample` (metres east and south; null where no ground is drawn). */
export function walkOver(sample: (x: number, z: number) => SurfaceSample | null): NavigationWorld {
  return {
    surface: { sample },
    eyeHeight: 1.6,
    cameraRadius: DEFAULT_CAMERA_RADIUS_AU,
    centre: atlasVec3(0, 0, 0),
    fieldRadius: 1_000_000,
    recoveryRadius: 1_000_000,
    maximumSlopeDegrees: DEFAULT_MAXIMUM_SLOPE_DEGREES,
    maximumStepHeight: DEFAULT_MAXIMUM_STEP_HEIGHT_AU,
    surfaceSampleSpacing: DEFAULT_SURFACE_SAMPLE_SPACING_AU,
    regions: [],
    obstacles: [],
    traces: [],
  };
}

/** A walk over level ground `height` metres up everywhere. */
export function levelWalk(height: number): NavigationWorld {
  return walkOver(() => ({ height, normal: LEVEL }));
}
