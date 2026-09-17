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
  surfaceUv,
  unavailableUv,
} from './texture-materials.js';
export type { SurfaceBatch } from './surface-mesh.js';
export { buildSurfaceMesh, validateSurfaceBatch } from './surface-mesh.js';
export type { TileEnvironment } from './environment.js';
export { applyTileEnvironment, skyRadiance } from './environment.js';
export { createUnavailableMaterial, unavailablePatternTexels } from './unavailable-surface.js';
export type { DrawnTileRange, GeneratedTileRange, GeneratedTileSources, LoadedGeneratedTile, TilePick } from './tile-runtime.js';
export {
  GeneratedTileRefusal,
  MATERIAL_NONE_EXISTS_REASON,
  MATERIAL_PLACEMENT_UNSTATED,
  loadGeneratedTile,
} from './tile-runtime.js';
export type { TileCollisionState, TileExtentMm, TileNavigation, TileSupportState } from './tile-navigation.js';
export {
  SUPPORT_SAMPLE_SPACING_M,
  navEnvelopeSupport,
  rendererToTile,
  tileNavigation,
  tileToRenderer,
} from './tile-navigation.js';
