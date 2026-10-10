/**
 * @exulanica/atlas-react/generated-site
 *
 * The browser path that draws a world made from a world kind: it reads the site's served drawing
 * (`exulanica.site-drawing/v1`), builds where a person walks from it and draws its slots as the
 * engine's primitives under the generated tile's light. A separate entry from `./playcanvas`, as
 * the generated tile's is, so a page that opens no such world carries none of it.
 */

export type {
  SiteDrawing,
  SiteFit,
  SitePrimitive,
  SiteRectMm,
  SiteSlot,
  SiteUvFrame,
} from './site-drawing.js';
export { SITE_DRAWING_PROFILE, SiteDrawingError, parseSiteDrawing } from './site-drawing.js';
export { SITE_WALKER_RADIUS_M, siteNavigationWorld, siteStart, siteSurface } from './site-navigation.js';
export type { DrawnSiteSlots } from './site-primitives.js';
export { drawSiteSlots, slotColour } from './site-primitives.js';
export type { RoofInput, RoofMesh, ShapedRoofs } from './site-roofs.js';
export { ridgeAxis, roofMesh, shapeRoofs } from './site-roofs.js';
export type { GeneratedSiteMount, SiteDresser, SiteMountOptions } from './site-mount.js';
export { SITE_BEYOND_DROP_M, baseGroundSlot, siteMount } from './site-mount.js';
