/**
 * @exulanica/atlas-react/generated-site
 *
 * The browser path that draws a world made from a world kind: it reads the site's served drawing
 * (`exulanica.site-drawing/v1`, or `/v5` for a site on land, with its land read by digest), builds
 * where a person walks from it and draws its slots as the engine's primitives under the generated
 * tile's light. A separate entry from `./playcanvas`, as
 * the generated tile's is, so a page that opens no such world carries none of it.
 */

export type {
  SiteDrawing,
  StructuredSiteDrawing,
  TerrainSiteDrawing,
  SiteFit,
  SiteLandSection,
  SitePrimitive,
  SiteRectMm,
  SiteSlot,
  SiteUvFrame,
} from './site-drawing.js';
export { SITE_DRAWING_PROFILE, SITE_DRAWING_TERRAIN_PROFILE, SITE_DRAWING_DRESSED_TERRAIN_PROFILE, SITE_DRAWING_LAND_PROFILE, isTerrainSiteDrawing, SiteDrawingError, parseSiteDrawing, parseStructuredSiteDrawing } from './site-drawing.js';
export { SITE_WALKER_RADIUS_M, siteLandSurface, siteNavigationWorld, siteStart, siteSurface } from './site-navigation.js';
export type { DrapedSlots, DrawnSiteLand, SiteLand } from './site-land.js';
export { drapeSiteSlots, drawSiteLand, readSiteLand } from './site-land.js';
export type { DrawnSiteVolumes, SiteVolume, SiteVolumes } from './site-volumes.js';
export { VOLUME_ROCK_RGB, drawSiteVolumes, readSiteVolumes, siteVolumeChunks, volumeChunkVertices, volumeOriginM } from './site-volumes.js';
export type { DrawnSiteSlots } from './site-primitives.js';
export { drawSiteSlots, slotColour } from './site-primitives.js';
export type { RoofInput, RoofMesh, ShapedRoofs } from './site-roofs.js';
export { ridgeAxis, roofMesh, shapeRoofs } from './site-roofs.js';
export type { GeneratedSiteMount, SiteDresser, SiteMountOptions } from './site-mount.js';
export type { DrawnCeiling } from './site-interior.js';
export { SITE_CEILING, ceilingRests, drawSiteCeiling, lightFromAbove } from './site-interior.js';
export type { DrawnScenery } from './site-scenery.js';
export { SCENERY_STONES, SCENERY_TREES, drawSiteScenery, sceneryOf } from './site-scenery.js';
export { SITE_BEYOND_DROP_M, baseGroundSlot, siteMount } from './site-mount.js';

export {readTerrainDressing, prepareTerrainDressing, createDressingReadiness} from './terrain-dressing.js';
export type {PreparedDressing, TerrainDressing, TerrainDressingInstance} from './terrain-dressing.js';
