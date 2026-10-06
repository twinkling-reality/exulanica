import {
  DEFAULT_MAXIMUM_SLOPE_DEGREES,
  DEFAULT_MAXIMUM_STEP_HEIGHT_AU,
  DISPLAY_EYE_HEIGHT,
  atlasVec3,
  type NavigationSurface,
  type NavigationWorld,
  type PolygonObstacle,
  type SurfaceSample,
} from '@exulanica/atlas-core';
import type { CameraState } from '../controls.js';
import type { SiteDrawing, SiteRectMm } from './site-drawing.js';

/**
 * Where a person walks in a site world, from its drawing's `walk` and nothing else.
 *
 * The site's floor is level: a person stands on it wherever it is stated and nowhere beyond it, so
 * walking off the site's edge recovers them. Every box the drawing says a person keeps out of (a
 * wall piece between openings, a blocking fixture, water) is a polygon obstacle the movement
 * resolver collides against, so a person comes into a building through its door and walks round
 * its furniture. Nothing drawn is read for this: the drawing states both.
 *
 * The renderer's frame is east, up and south in metres; the site's is x east, y north and z up in
 * millimetres from its south-west corner, which is the region's origin. So a site point (x, y) is
 * the renderer's (x / 1000, -y / 1000).
 */

const MILLIMETRES = 1000;
/**
 * The walker's radius: the society's walking capsule, 340 mm, so the person exploring fits through
 * every door and gap the site's people walk through and no narrower one.
 */
export const SITE_WALKER_RADIUS_M = 0.34;
/** How far beyond the site's corners the field reaches before a walker is brought back. */
const FIELD_MARGIN_M = 2;
/** The step a site's floor is sampled at for support: 50 mm, finer than any opening it states. */
const SUPPORT_SAMPLE_SPACING_M = 0.05;

const LEVEL: SurfaceSample = Object.freeze({ height: 0, normal: Object.freeze({ x: 0, y: 1, z: 0 }) });

/** Whether a renderer point lies on a site rectangle, in metres east and south. */
function onRect(rect: SiteRectMm, east: number, south: number): boolean {
  const x = east * MILLIMETRES;
  const y = -south * MILLIMETRES;
  return x >= rect[0] && x <= rect[2] && y >= rect[1] && y <= rect[3];
}

/** A site rectangle as one closed ring in the renderer's frame. */
function ring(rect: SiteRectMm, id: string): PolygonObstacle {
  const [x0, y0, x1, y1] = rect.map((v) => v / MILLIMETRES) as unknown as [number, number, number, number];
  return Object.freeze({
    id,
    rings: Object.freeze([Object.freeze([
      atlasVec3(x0, 0, -y0),
      atlasVec3(x1, 0, -y0),
      atlasVec3(x1, 0, -y1),
      atlasVec3(x0, 0, -y1),
    ])]),
  });
}

/** The level floor a site states: support on it, none off it. */
export function siteSurface(drawing: SiteDrawing): NavigationSurface {
  const floor = drawing.walk.floorMm;
  return Object.freeze({
    sample: (east: number, south: number) => (onRect(floor, east, south) ? LEVEL : null),
  });
}

/** The navigation world a person exploring a site walks in. */
export function siteNavigationWorld(drawing: SiteDrawing): NavigationWorld {
  const [x0, y0, x1, y1] = drawing.walk.floorMm;
  const centreEast = (x0 + x1) / 2 / MILLIMETRES;
  const centreSouth = -(y0 + y1) / 2 / MILLIMETRES;
  const reach = Math.hypot(x1 - x0, y1 - y0) / 2 / MILLIMETRES;
  return Object.freeze({
    surface: siteSurface(drawing),
    eyeHeight: DISPLAY_EYE_HEIGHT,
    cameraRadius: SITE_WALKER_RADIUS_M,
    centre: atlasVec3(centreEast, 0, centreSouth),
    fieldRadius: reach,
    recoveryRadius: reach + FIELD_MARGIN_M,
    maximumSlopeDegrees: DEFAULT_MAXIMUM_SLOPE_DEGREES,
    maximumStepHeight: DEFAULT_MAXIMUM_STEP_HEIGHT_AU,
    surfaceSampleSpacing: SUPPORT_SAMPLE_SPACING_M,
    regions: Object.freeze([]),
    obstacles: Object.freeze([]),
    polygonObstacles: Object.freeze([
      ...drawing.walk.blockersMm.map((rect, index) => ring(rect, `site-blocker:${index}`)),
      ...drawing.walk.keepOutMm.map((rect, index) => ring(rect, `site-keep-out:${index}`)),
    ]),
    traces: Object.freeze([]),
  });
}

/**
 * Where a person opens in a site world: the drawing's arrival, eye high above the floor, facing
 * the way it states. The renderer's yaw 0 looks north with forward (-sin yaw, 0, -cos yaw), so a
 * facing of (x east, y north) is yaw = atan2(-x, y).
 */
export function siteStart(drawing: SiteDrawing, navigationWorld: NavigationWorld): CameraState {
  const [x, y, z] = drawing.arrival.positionMm;
  const [facingEast, facingNorth] = drawing.arrival.facingMm;
  return {
    x: x / MILLIMETRES,
    y: z / MILLIMETRES + navigationWorld.eyeHeight,
    z: -y / MILLIMETRES,
    yaw: Math.atan2(-facingEast, facingNorth),
    pitch: 0,
  };
}
