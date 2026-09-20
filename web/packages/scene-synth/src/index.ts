/**
 * @exulanica/scene-synth
 *
 * Synthetic point maps from declared primitives, for renderer and reconstruction
 * benches. The CLI writes OPM containers; nothing here is evidence.
 */

export type { Intrinsics } from './camera.js';
export { intrinsics, pixelRay, resolutionFor } from './camera.js';
export type { HonestyParams, KeepMask } from './honesty.js';
export { DEFAULT_HONESTY, computeKeepMask } from './honesty.js';
export type { PointMap } from './pointmap.js';
export { buildPointMap } from './pointmap.js';
export type { DepthBuffers, RasterOptions } from './raster.js';
export { MISS, rasterDepth } from './raster.js';
export type { Primitive, Segment, SegmentClass } from './primitives.js';
export type { AnchorSpec } from './scene.js';
export {
  ANCHORS,
  CAMERA_HEIGHT,
  FOOTPRINT_RADIUS_LOCAL,
  PRIMITIVES,
  SEGMENTS,
} from './scene.js';
export { trimToExactly } from './select.js';
export type { GenerateOptions, GenerateResult } from './generate.js';
export { DEFAULT_GENERATE, GENERATOR, POINT_LADDER, generatePointMap } from './generate.js';
export type { IslandFixtureOptions } from './island-fixture.js';
export {
  buildFixtureScene,
  buildIslandFixture,
  serializeIsland,
  serializeScene,
} from './island-fixture.js';
export * from './format/index.js';
