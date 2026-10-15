import {
  LAND_CHUNK_MM, LAND_SURFACE_GROUND, landBandAt, landNoiseShift,
  type LandChunk, type LandSurfaces, type LandWater, type StylePackLandCover,
} from '@exulanica/atlas-core';
import type { CoverPoint } from './ground-cover.js';
import { generator, seedOf } from './seeded.js';

/**
 * What grows on the land itself: a look's `land_cover`, scattered over the near land a site stands
 * on by the surface role the land is drawn in at each point (`landBandAt`: `land`, the ground it is
 * drawn in, or a band of the land's surface catalog such as sand, planting or rock), and within each
 * rule's slope, height and reach of the place. The same every time for the same seed and land.
 *
 * Only the near chunks grow any, never the backdrop. A piece grows nowhere a site slot lies (the
 * place's own grounds grow their own cover), nowhere the land is wet (`dryAt`: the sea's edge, lakes,
 * ponds and a cascade's pools), and nowhere within `FALL_CLEAR_MM` of a fall.
 *
 * PRESENTATION ONLY, as cover is: not a part of the world, never walked, picked or listed, and it
 * hides nobody. A site grows at most `LAND_COVER_PLACEMENTS_MAX` pieces, counting only pieces that
 * grow, nearest chunks first; finding them tries at most `LAND_COVER_TRIES_MAX` points, grown or not.
 */

/** The most land cover pieces one site grows: a guard on the page's work, not a look's choice. */
export const LAND_COVER_PLACEMENTS_MAX = 60_000;

/** The most points the land cover's scatter tries, grown or not: a bound on the work of finding where it grows. */
export const LAND_COVER_TRIES_MAX = 4 * LAND_COVER_PLACEMENTS_MAX;

/** How far either side of a fall nothing grows, millimetres: a fall is a sheet on a pool's edge with no depth. */
export const FALL_CLEAR_MM = 1000;

/** The run a slope is measured over, millimetres: one cell of the land, as the shader's smooth normal reads it. */
const SLOPE_RUN_MM = 1000;

/** The land a site stands on, as land cover reads it. */
export interface LandCoverLand {
  readonly chunks: readonly LandChunk[];
  /** The land's height under a site point, millimetres east and north. */
  readonly groundMm: (eastMm: number, northMm: number) => number;
  /** Whether a point is dry land: on the near land, above the sea's edge and out of every lake, pond and pool. */
  readonly dryAt: (eastMm: number, northMm: number) => boolean;
  readonly waters: readonly LandWater[];
  /** The land's surface catalog the land is drawn in; none, every point is the land's own ground. */
  readonly surfaces: LandSurfaces | null;
}

/** Where land cover may not grow and how far from the place it reaches: the place's rectangle and its slots' rectangles in plan, millimetres. */
export interface LandCoverOptions {
  readonly placeMm: readonly [number, number, number, number];
  readonly keepOutMm: readonly (readonly [number, number, number, number])[];
  readonly most?: number;
  readonly tries?: number;
}

/** One land cover piece: its point, piece, turn, scale and pick, the height of its foot, and the surface role it grew in. */
export interface LandCoverPoint extends CoverPoint {
  readonly upM: number;
  readonly role: string;
}

/** What the land grew: its pieces, how many grew in each surface role, the pieces the guard left out, and the points never tried. */
export interface GrownLandCover {
  readonly points: readonly LandCoverPoint[];
  readonly byRole: Readonly<Record<string, number>>;
  readonly leftOut: number;
  readonly untried: number;
}

/** The side of a cell of the grid the kept-out rectangles are found by, millimetres: a bound on the work, not a look. */
const GRID_MM = 8000;

/** The land's slope at a site point, rise per run in per mille, from central differences over one cell each way. */
export function landSlopePermille(groundMm: (eastMm: number, northMm: number) => number, eastMm: number, northMm: number): number {
  const gx = (groundMm(eastMm + SLOPE_RUN_MM, northMm) - groundMm(eastMm - SLOPE_RUN_MM, northMm)) / (2 * SLOPE_RUN_MM);
  const gy = (groundMm(eastMm, northMm + SLOPE_RUN_MM) - groundMm(eastMm, northMm - SLOPE_RUN_MM)) / (2 * SLOPE_RUN_MM);
  return 1000 * Math.hypot(gx, gy);
}

/** How far a point lies outside a rectangle in plan, millimetres; 0 inside it. */
function outside([x0, y0, x1, y1]: readonly [number, number, number, number], x: number, y: number): number {
  return Math.hypot(Math.max(0, x0 - x, x - x1), Math.max(0, y0 - y, y - y1));
}

/**
 * Grow `landCover` over the near land, rules in their keys' order and chunks nearest the place first,
 * at most `most` pieces from at most `tries` points tried.
 */
export function growLandCover(
  landCover: Readonly<Record<string, StylePackLandCover>>,
  land: LandCoverLand,
  { placeMm, keepOutMm, most = LAND_COVER_PLACEMENTS_MAX, tries = LAND_COVER_TRIES_MAX }: LandCoverOptions,
): GrownLandCover {
  const points: LandCoverPoint[] = [];
  const byRole: Record<string, number> = {};
  let leftOut = 0;
  let untried = 0;
  let tried = 0;
  const keys = Object.keys(landCover).sort();
  if (keys.length === 0) return { points, byRole, leftOut, untried };
  const grid = new Map<string, number[]>();
  keepOutMm.forEach((rect, index) => {
    for (let gx = Math.floor(rect[0] / GRID_MM); gx <= Math.floor(rect[2] / GRID_MM); gx += 1) {
      for (let gy = Math.floor(rect[1] / GRID_MM); gy <= Math.floor(rect[3] / GRID_MM); gy += 1) {
        const key = `${String(gx)}|${String(gy)}`;
        const cell = grid.get(key);
        if (cell === undefined) grid.set(key, [index]);
        else cell.push(index);
      }
    }
  });
  const kept = (x: number, y: number): boolean => (grid.get(`${String(Math.floor(x / GRID_MM))}|${String(Math.floor(y / GRID_MM))}`) ?? [])
    .some((index) => outside(keepOutMm[index]!, x, y) === 0);
  const falls = land.waters.filter((water) => water.kind === 'fall');
  const nearFall = (x: number, y: number): boolean => falls.some((fall) => outside(fall.rectMm, x, y) <= FALL_CLEAR_MM);
  const sea = land.waters.some((water) => water.kind === 'sea');
  const middle = [(placeMm[0] + placeMm[2]) / 2, (placeMm[1] + placeMm[3]) / 2] as const;
  const chunks = [...land.chunks].sort((a, b) => {
    const da = Math.hypot((a.chunkX + 0.5) * LAND_CHUNK_MM - middle[0], (a.chunkY + 0.5) * LAND_CHUNK_MM - middle[1]);
    const db = Math.hypot((b.chunkX + 0.5) * LAND_CHUNK_MM - middle[0], (b.chunkY + 0.5) * LAND_CHUNK_MM - middle[1]);
    return da - db || a.chunkX - b.chunkX || a.chunkY - b.chunkY;
  });
  const hectares = (LAND_CHUNK_MM / 1000) ** 2 / 10_000;
  for (const key of keys) {
    const rule = landCover[key]!;
    const role = rule.role;
    const [least, most_] = rule.scale_permille;
    for (const chunk of chunks) {
      const count = Math.max(0, Math.round(hectares * rule.density_per_ha));
      const room = Math.max(0, tries - tried);
      untried += Math.max(0, count - room);
      const drawn = Math.min(count, room);
      tried += drawn;
      const next = generator(seedOf(rule.seed, `${key}|${String(chunk.chunkX)},${String(chunk.chunkY)}`));
      for (let i = 0; i < drawn; i += 1) {
        const eastMm = (chunk.chunkX + next()) * LAND_CHUNK_MM;
        const northMm = (chunk.chunkY + next()) * LAND_CHUNK_MM;
        const piece = rule.pieces[Math.floor(next() * rule.pieces.length) % rule.pieces.length]!;
        const yaw = next() * 2 * Math.PI;
        const scale = (least + (most_ - least) * next()) / 1000;
        const pick = next();
        if (rule.within_mm !== undefined && outside(placeMm, eastMm, northMm) > rule.within_mm) continue;
        if (kept(eastMm, northMm) || !land.dryAt(eastMm, northMm) || nearFall(eastMm, northMm)) continue;
        const heightMm = land.groundMm(eastMm, northMm);
        if (rule.height_mm !== undefined && (heightMm < rule.height_mm[0] || heightMm > rule.height_mm[1])) continue;
        const slope = landSlopePermille(land.groundMm, eastMm, northMm);
        if (rule.slope_permille !== undefined && (slope < rule.slope_permille[0] || slope > rule.slope_permille[1])) continue;
        const drawnIn = land.surfaces === null ? LAND_SURFACE_GROUND
          : landBandAt(land.surfaces, 'near', slope, heightMm, landNoiseShift(land.surfaces.noise, eastMm / 1000, -northMm / 1000), sea);
        if (drawnIn !== role) continue;
        if (points.length >= most) {
          leftOut += 1;
          continue;
        }
        points.push({ piece, eastM: eastMm / 1000, northM: northMm / 1000, yaw, scale, pick, upM: heightMm / 1000, role });
        byRole[role] = (byRole[role] ?? 0) + 1;
      }
    }
  }
  return { points, byRole, leftOut, untried };
}
