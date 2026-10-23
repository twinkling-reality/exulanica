import {
  DEFAULT_MAXIMUM_SLOPE_DEGREES,
  DEFAULT_MAXIMUM_STEP_HEIGHT_AU,
  DISPLAY_EYE_HEIGHT,
  LAND_CELL_MM,
  LAND_WALK_GRADE_PERMILLE,
  SupportNavigationError,
  atlasVec3,
  siteTopCellHeld,
  terrainGroundPose,
  type TerrainOccupancyProof,
  type NavigationSurface,
  type NavigationWorld,
  type PolygonObstacle,
  type SurfaceSample,
} from '@exulanica/atlas-core';
import type { CameraState } from '../controls.js';
import { isTerrainSiteDrawing, type SiteDrawing, type StructuredSiteDrawing, type SiteRectMm } from './site-drawing.js';
import type { SiteLand } from './site-land.js';

/**
 * Where a person walks in a site world, from its canonical walk or explicit support network.
 *
 * A version 1 site's floor is level: a person stands on it wherever it is stated and nowhere beyond it, so
 * walking off the site's edge recovers them. Every box the drawing says a person keeps out of (a
 * wall piece between openings, a blocking fixture, water) is a polygon obstacle the movement
 * resolver collides against, so a person comes into a building through its door and walks round
 * its furniture. Nothing drawn is read for this: the drawing states both. Version 2 carries named supports,
 * solid/headroom clearance and explicit connectors; speculative sampling stays on its entry
 * surface while accepted movement carries the active surface and connector.
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
/**
 * The steepest a person walks on a site's graded land and on a volume's top round it: the land's
 * walking grade, 1 in 4 (about 14 degrees), the grade the server grades that land to, in place of
 * the default 12 degrees. A site's edge eases onto the land beyond it at up to that grade, so a
 * lower limit can leave the band at a gate unwalkable and a person arriving outside it unable to
 * walk in.
 */
const LAND_WALK_SLOPE_DEGREES = (Math.atan(LAND_WALK_GRADE_PERMILLE / 1000) * 180) / Math.PI;

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
export function siteSurface(drawing: StructuredSiteDrawing): NavigationSurface {
  const floor = drawing.walk.floorMm;
  return Object.freeze({
    sample: (east: number, south: number) => (onRect(floor, east, south) ? LEVEL : null),
  });
}

/** How far apart the land is read either side of a point for its slope, metres: half a cell. */
const LAND_SLOPE_STEP_M = 0.5;

/**
 * Whether a site point, metres east and south, lies in a cell a volume's top is drawn as land over:
 * the open top round the site, which a person may walk to its rim and no further.
 */
function onTopCells(land: SiteLand, east: number, south: number): boolean {
  if (land.top === null) return false;
  const [x0, y0] = land.top.originMm;
  const column = Math.floor((east * MILLIMETRES - x0) / LAND_CELL_MM), row = Math.floor((-south * MILLIMETRES - y0) / LAND_CELL_MM);
  return column >= 0 && row >= 0 && column < land.top.columns - 1 && row < land.top.rows - 1
    && siteTopCellHeld(land.section.rockCells, row, column);
}

/**
 * The floor of a site on land: the graded land wherever the site states its floor, its height
 * and its slope read from the land, and none off it, so walking off the site's edge recovers a
 * person as on level ground. On a volume's top, the open top round the site is floor too, out to
 * the cells drawn as land, so a person walks from the gate to the rim and never past it.
 */
export function siteLandSurface(drawing: StructuredSiteDrawing, land: SiteLand): NavigationSurface {
  const floor = drawing.walk.floorMm;
  const h = LAND_SLOPE_STEP_M;
  return Object.freeze({
    sample: (east: number, south: number): SurfaceSample | null => {
      if (!onRect(floor, east, south) && !onTopCells(land, east, south)) return null;
      const dx = (land.groundM(east + h, south) - land.groundM(east - h, south)) / (2 * h);
      const dz = (land.groundM(east, south + h) - land.groundM(east, south - h)) / (2 * h);
      const length = Math.hypot(dx, 1, dz);
      return Object.freeze({ height: land.groundM(east, south), normal: Object.freeze({ x: -dx / length, y: 1 / length, z: -dz / length }) });
    },
  });
}

/** The navigation world a person exploring a site walks in. */
export function siteNavigationWorld(drawing: SiteDrawing, occupancy: TerrainOccupancyProof | (() => TerrainOccupancyProof) = {status: 'unavailable'}, land?: SiteLand): NavigationWorld {
  if (isTerrainSiteDrawing(drawing)) {
    const {east, south} = drawing.boundsMm;
    const reach = Math.hypot(east[1] - east[0], south[1] - south[0]) / 2000;
    return Object.freeze({
      terrain: Object.freeze({source: Object.freeze({worldId: drawing.worldId, receiptSha256: drawing.receiptSha256}),
        get occupancy() { return typeof occupancy === 'function' ? occupancy() : occupancy; }, contact: drawing.terrain,
        entryMm: Object.freeze([drawing.arrival.positionMm[0], drawing.arrival.positionMm[2]]) as readonly [number, number]}),
      // A terrain refusal never obtains a sampled or level substitute floor.
      surface: Object.freeze({sample: () => null}),
      eyeHeight: DISPLAY_EYE_HEIGHT, cameraRadius: SITE_WALKER_RADIUS_M,
      centre: atlasVec3((east[0] + east[1]) / 2000, 0, (south[0] + south[1]) / 2000),
      fieldRadius: reach, recoveryRadius: reach + FIELD_MARGIN_M,
      maximumSlopeDegrees: DEFAULT_MAXIMUM_SLOPE_DEGREES, maximumStepHeight: DEFAULT_MAXIMUM_STEP_HEIGHT_AU,
      surfaceSampleSpacing: SUPPORT_SAMPLE_SPACING_M,
      regions: Object.freeze([]), obstacles: Object.freeze([]), polygonObstacles: Object.freeze([]), traces: Object.freeze([]),
    });
  }
  const support = drawing.support;
  // On a volume's top a person walks the whole drawn top, so the field reaches its lattice's edge.
  const top = land?.top ?? null;
  const floorBounds = top === null ? drawing.walk.floorMm : [
    Math.min(drawing.walk.floorMm[0], top.originMm[0]),
    Math.min(drawing.walk.floorMm[1], top.originMm[1]),
    Math.max(drawing.walk.floorMm[2], top.originMm[0] + (top.columns - 1) * LAND_CELL_MM),
    Math.max(drawing.walk.floorMm[3], top.originMm[1] + (top.rows - 1) * LAND_CELL_MM),
  ];
  const bounds = support === undefined ? floorBounds : [
    Math.min(...support.document.surfaces.map(s => s.rect_mm[0])),
    -Math.max(...support.document.surfaces.map(s => s.rect_mm[3])),
    Math.max(...support.document.surfaces.map(s => s.rect_mm[2])),
    -Math.min(...support.document.surfaces.map(s => s.rect_mm[1])),
  ];
  const [x0, y0, x1, y1] = bounds as readonly [number, number, number, number];
  const centreEast = (x0 + x1) / 2 / MILLIMETRES;
  const centreSouth = -(y0 + y1) / 2 / MILLIMETRES;
  const reach = Math.hypot(x1 - x0, y1 - y0) / 2 / MILLIMETRES;
  if (support !== undefined && (support.document.actor.radius_mm !== 340 || support.document.actor.height_mm !== 1800)) {
    throw new Error('The support network does not bind the 340 mm / 1800 mm person actor.');
  }
  return Object.freeze({
    ...(support === undefined ? {} : { support }),
    surface: support === undefined ? (land === undefined ? siteSurface(drawing) : siteLandSurface(drawing, land)) : Object.freeze({ sample: (east: number, south: number) => {
      try { return Object.freeze({ height: support.at(support.entry, [east * MILLIMETRES, south * MILLIMETRES]) / MILLIMETRES, normal: LEVEL.normal }); }
      catch (error) { if (!(error instanceof SupportNavigationError)) throw error; return null; }
    } }),
    eyeHeight: DISPLAY_EYE_HEIGHT,
    cameraRadius: SITE_WALKER_RADIUS_M,
    centre: atlasVec3(centreEast, 0, centreSouth),
    fieldRadius: reach,
    recoveryRadius: reach + FIELD_MARGIN_M,
    maximumSlopeDegrees: support === undefined && land !== undefined ? LAND_WALK_SLOPE_DEGREES : DEFAULT_MAXIMUM_SLOPE_DEGREES,
    maximumStepHeight: DEFAULT_MAXIMUM_STEP_HEIGHT_AU,
    surfaceSampleSpacing: SUPPORT_SAMPLE_SPACING_M,
    regions: Object.freeze([]),
    obstacles: Object.freeze([]),
    polygonObstacles: Object.freeze(support === undefined ? [
      ...drawing.walk.blockersMm.map((rect, index) => ring(rect, `site-blocker:${index}`)),
      ...drawing.walk.keepOutMm.map((rect, index) => ring(rect, `site-keep-out:${index}`)),
    ] : []),
    traces: Object.freeze([]),
  });
}

/**
 * Where a person opens in a site world: the drawing's arrival, eye high above the floor, facing
 * the way it states. The renderer's yaw 0 looks north with forward (-sin yaw, 0, -cos yaw), so a
 * facing of (x east, y north) is yaw = atan2(-x, y).
 */
export function siteStart(drawing: SiteDrawing, navigationWorld: NavigationWorld): CameraState {
  if (isTerrainSiteDrawing(drawing)) {
    const [east, , south] = drawing.arrival.positionMm;
    const accepted = terrainGroundPose(navigationWorld, [east, south]);
    const height = drawing.arrival.contact.height_mm;
    return {x: east / 1000, z: south / 1000,
      y: accepted?.position.y ?? Number(height.numerator) / Number(height.denominator) / 1000 + navigationWorld.eyeHeight,
      yaw: Math.atan2(-drawing.arrival.facingMm[0], -drawing.arrival.facingMm[1]), pitch: 0,
      ...(accepted === null ? {} : {terrain: accepted.state})};
  }
  const [x, y, z] = drawing.arrival.positionMm;
  const [facingEast, facingNorth] = drawing.arrival.facingMm;
  return {
    x: x / MILLIMETRES,
    y: drawing.support === undefined ? z / MILLIMETRES + navigationWorld.eyeHeight
      : drawing.support.at(drawing.support.entry, [x, -y]) / MILLIMETRES + navigationWorld.eyeHeight,
    ...(drawing.support === undefined ? {} : { support: drawing.support.entry }),
    z: -y / MILLIMETRES,
    yaw: Math.atan2(-facingEast, facingNorth),
    pitch: 0,
  };
}
