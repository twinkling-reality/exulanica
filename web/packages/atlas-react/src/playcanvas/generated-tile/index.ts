/**
 * @exulanica/atlas-react/generated-tile
 *
 * The browser path that draws a baked generated tile with its texture sets. A separate entry from
 * `./playcanvas` on purpose: the app reaches it only from its development evaluation route, and a
 * production build that never imports it carries none of it.
 */

export type {
  GeneratedTileAttachment,
  GeneratedTileHost,
  GeneratedTileMetrics,
  GeneratedTileMount,
} from './binding-contract.js';
export type { Rgb, TileContactShadowMode, TileLook, TileShadowFilter, TileToneMapping } from './look.js';
export { TILE_LOOK_ID, TILE_LOOK_V1, TileLookError, sunDirection, validateTileLook } from './look.js';
export type { PreparedTextureSet, TileMaterialReference, TileTextureResolution } from './texture-materials.js';
export {
  TileTextureLibrary,
  TileTextureUploads,
  prepareTextureSet,
  setTangents,
  DECAL_DEPTH_BIAS,
  DECAL_DRAW_BUCKET,
  DECAL_SLOPE_DEPTH_BIAS,
  GLAZING_DRAW_BUCKET,
  castsShadow,
  drawBucket,
  normalTexels,
  transmissionRoughnessTexels,
  surfaceUv,
  unavailableUv,
  undrawnClassReason,
} from './texture-materials.js';
export { coveragePreservingMips, coverageShare } from './cutout-coverage.js';
export { GLAZING_FRESNEL_CHUNK, GLAZING_FRESNEL_GLSL, GLAZING_FRESNEL_WGSL, glazingReflectance } from './glazing-fresnel.js';
export type { SurfaceBatch } from './surface-mesh.js';
export { buildSurfaceMesh, validateSurfaceBatch } from './surface-mesh.js';
export type { TileEnvironment } from './environment.js';
export { applyTileEnvironment, skyRadiance } from './environment.js';
export { createUnavailableMaterial, unavailablePatternTexels } from './unavailable-surface.js';
export type {
  DrawnTileRange,
  GeneratedTileRange,
  GeneratedTileSources,
  GeneratedTileSurface,
  LoadedGeneratedTile,
  SurfacePlacement,
  TilePick,
  TileSurfaceBatch,
} from './tile-runtime.js';
export {
  GeneratedTileRefusal,
  MATERIAL_NONE_EXISTS_REASON,
  MATERIAL_PLACEMENT_UNSTATED,
  batchTileSurfaces,
  loadGeneratedTile,
} from './tile-runtime.js';
export type {
  ComposedSupport,
  ComposedTile,
  NavigationTile,
  TileCapsule,
  TileCollisionState,
  TileExtentMm,
  TileNavigation,
  TileSupportState,
} from './tile-navigation.js';
export {
  SUPPORT_SAMPLE_SPACING_M,
  TILE_FRAME,
  composedSupport,
  navEnvelopeSupport,
  rendererToTile,
  tileCapsule,
  tileNavigation,
  tileToRenderer,
  unsupportedFrame,
} from './tile-navigation.js';
export type { BakedTileSummary, FetchedTile, HeldTile, TileBytesOrigin, TileRouteAccess } from './tile-route.js';
export {
  BAKED_TILE_MEDIA_TYPE,
  BAKED_TILE_SERVED_STATE,
  TileRouteRefusal,
  fetchBakedTile,
  listBakedTiles,
  tileAt,
} from './tile-route.js';
export type { AbsentTile, FetchedWalkWorld, TileCoordinate, WalkWorldPlan } from './walk-world.js';
export { fetchWalkWorld, tileName, walkWorldTiles } from './walk-world.js';
export type { CapturedPose, TileCaptureSession } from './capture.js';
export { beginTileCapture } from './capture.js';
export type { ObstructionRings, RefusedObstructionRing, StatedObstructionRing } from './obstruction-rings.js';
export { obstructionRings } from './obstruction-rings.js';
