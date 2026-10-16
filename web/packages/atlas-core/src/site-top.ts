/**
 * A world on a placed volume's top as the server serves it (`exulanica/world/site_top.py`): the
 * volume's top land graded for the site laid out on it, `exulanica.site-top/v1`. A pure reader and
 * the height rule; nothing here draws.
 *
 * Frame: millimetres east and north of the site's south-west corner, heights above the volume's
 * level 0 (the top land's datum), whatever the volume's altitude. The heights are on the 1 m
 * lattice from `originMm`, rows from the south, the whole square of the volume's top; the site lies
 * inside it. Between lattice points a height is the server's triangle rule (each cell split along
 * its south-west to north-east diagonal, floored), and beyond the lattice the nearest edge's, so
 * the page stands everything where the server's place stands it. Every bound is the server's; a
 * document that breaks one, or is not the one its digest names, is refused by where it broke it.
 */
import { canonicalJson } from './style-pack.js';
import type { HeightfieldDigest } from './heightfield-geometry.js';
import { LAND_CELL_MM, LAND_NEAR_BOUND_MM, readLandWater, type LandWater } from './landform.js';

export const SITE_TOP_PROFILE = 'exulanica.site-top/v1';
/** The most lattice points a top states a side: a top land's square is at most 128 m. */
const SITE_TOP_MOST_SAMPLES = 129;
/** How far a top's lattice may start from the site's corner: a square's side and its offset. */
const SITE_TOP_ORIGIN_MM = 256_000;

export class SiteTopError extends Error {
  constructor(readonly where: string, detail: string) { super(`${where}: ${detail}`); }
}
function require(okay: boolean, where: string, detail: string): asserts okay {
  if (!okay) throw new SiteTopError(where, detail);
}
function integer(raw: unknown, low: number, high: number, where: string): number {
  require(typeof raw === 'number' && Number.isSafeInteger(raw) && raw >= low && raw <= high, where, `is a whole number from ${low} to ${high}`);
  return raw;
}

export interface SiteTop {
  /** The lattice's south-west point in the site's frame, millimetres. */
  readonly originMm: readonly [number, number];
  readonly columns: number;
  readonly rows: number;
  /** Heights above the volume's level 0, rows from the south. */
  readonly heightMm: Int32Array;
  readonly water: readonly LandWater[];
  readonly sha256: string;
}

/** Admit a graded top, or refuse it by where it broke; with `expectedSha256`, only the one that digest names. */
export function readSiteTop(raw: unknown, digest: HeightfieldDigest, expectedSha256?: string): SiteTop {
  require(raw !== null && typeof raw === 'object' && !Array.isArray(raw), 'site top', 'is an object');
  const row = raw as Record<string, unknown>;
  const names = 'profile cell_mm origin_mm columns rows height_mm water';
  require(Object.keys(row).sort().join(' ') === names.split(' ').sort().join(' '), 'site top', `states exactly ${names}`);
  require(row['profile'] === SITE_TOP_PROFILE, 'site top.profile', `is ${SITE_TOP_PROFILE}`);
  require(row['cell_mm'] === LAND_CELL_MM, 'site top.cell_mm', `is ${LAND_CELL_MM}`);
  const origin = row['origin_mm'];
  require(Array.isArray(origin) && origin.length === 2, 'site top.origin_mm', 'lists 2 values');
  const x0 = integer(origin[0], -SITE_TOP_ORIGIN_MM, SITE_TOP_ORIGIN_MM, 'site top.origin_mm[0]');
  const y0 = integer(origin[1], -SITE_TOP_ORIGIN_MM, SITE_TOP_ORIGIN_MM, 'site top.origin_mm[1]');
  require(x0 % LAND_CELL_MM === 0 && y0 % LAND_CELL_MM === 0, 'site top.origin_mm', 'lies on the lattice');
  const columns = integer(row['columns'], 2, SITE_TOP_MOST_SAMPLES, 'site top.columns');
  const rows = integer(row['rows'], 2, SITE_TOP_MOST_SAMPLES, 'site top.rows');
  const heights = row['height_mm'];
  require(Array.isArray(heights) && heights.length === columns * rows, 'site top.height_mm', `lists ${columns * rows} values`);
  const heightMm = new Int32Array(heights.length);
  heights.forEach((value, i) => { heightMm[i] = integer(value, -LAND_NEAR_BOUND_MM, LAND_NEAR_BOUND_MM, `site top.height_mm[${i}]`); });
  require(Array.isArray(row['water']), 'site top.water', 'is a list');
  const water = (row['water'] as unknown[]).map((body, i) => readLandWater(body, `site top.water[${i}]`));
  const actual = digest(new TextEncoder().encode(canonicalJson(raw)));
  if (expectedSha256 !== undefined) require(actual === expectedSha256, 'site top', 'is the document its digest names');
  return Object.freeze({
    originMm: Object.freeze([x0, y0] as const), columns, rows, heightMm, water: Object.freeze(water), sha256: actual,
  });
}

/** The graded top's height at a point of the site's frame, millimetres above the volume's level 0:
 * the server's triangle rule, floored, and beyond the lattice the nearest edge's. */
export function siteTopHeightMm(top: SiteTop, eastMm: number, northMm: number): number {
  const cell = LAND_CELL_MM;
  const gx = Math.floor(eastMm) - top.originMm[0], gy = Math.floor(northMm) - top.originMm[1];
  const i = Math.min(top.columns - 2, Math.max(0, Math.floor(gx / cell)));
  const j = Math.min(top.rows - 2, Math.max(0, Math.floor(gy / cell)));
  const fx = Math.min(cell, Math.max(0, gx - i * cell)), fy = Math.min(cell, Math.max(0, gy - j * cell));
  const h = top.heightMm, at = j * top.columns + i;
  const h00 = h[at]!, h10 = h[at + 1]!, h01 = h[at + top.columns]!, h11 = h[at + top.columns + 1]!;
  if (fx >= fy) return h00 + Math.floor(((h10 - h00) * fx + (h11 - h10) * fy) / cell);
  return h00 + Math.floor(((h11 - h01) * fx + (h01 - h00) * fy) / cell);
}

/** A run of a top's cells drawn as land: its row from the south, and its first and last column. */
export type SiteTopRun = readonly [number, number, number];

/** Whether a cell (its row and column from the lattice's south-west) is in one of the runs. */
export function siteTopCellHeld(runs: readonly SiteTopRun[], row: number, column: number): boolean {
  return runs.some(([r, first, last]) => r === row && column >= first && column <= last);
}
