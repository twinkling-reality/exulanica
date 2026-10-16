import { LAND_CELL_MM } from '@exulanica/atlas-core';
import type { SiteLand } from '../generated-site/site-land.js';
import { SITE_WALKER_RADIUS_M } from '../generated-site/site-navigation.js';
import { towardSun } from './climbers.js';
import { slotRectMm, type CoverSlot } from './ground-cover.js';

/**
 * Where plants may hang over a terrace's edge: for a ground plane of a site on land, each side of its
 * rectangle with the stations along it, and at each station the land's lip, the top and foot of the
 * face a plant would hang down, and the drop, or why nothing hangs there.
 *
 * The drawing states no terrace and no edge: a zone is a level pad in the graded land, and the drop
 * is the land past it, a bank or a retaining cell. So the edge is read from the land. One land cell
 * inside the side is the level; stepping out, the lip is the last point still at the level, and the
 * land must have fallen one cell past it. A wall or boundary box whose outer face is on the side
 * starts the face at its top; else the face starts at the lip. Down the land the face goes on while
 * each step falls faster than the rule's least slope and stays on the straight line from the lip (a
 * plant is rigid). The drop is the level less the land at the foot; a wall's own height does not
 * count. A station is left out where it is not this slot's top, where its side faces away from the
 * sun the rule asks for, and where a path or road, a box other than the wall hung over, or water lies
 * across the strip from the level to a walker's reach past the foot, or the foot is under water.
 *
 * PRESENTATION ONLY: what this finds places plants that are drawn and never walked, picked or
 * listed. Heights are millimetres above the land's datum, in the site's frame (x east, y north).
 */

/** A drop shallower than this grows nothing by default: more than three 180 mm kerb steps, so a step or a kerb never trails. */
export const TRAIL_DROP_LEAST_MM = 600;

/**
 * A face falls faster than this by default, per mille: steeper than the 250 a person walks, and a
 * graded bank's 500 is a face.
 */
export const TRAIL_SLOPE_LEAST_PERMILLE = 400;

/** The spacing of stations along a side: half a land cell, so a run's ends fall within a quarter cell of where the edge's land changes. */
export const TRAIL_STATION_MM = 500;

/** The step the land is read at across an edge: a quarter land cell, so each cell's fall is read at its own slope. */
export const TRAIL_STEP_MM = 250;

/** The land is at the level within this: a graded pad's heights are whole millimetres and its draping layers a few. */
export const TRAIL_LEVEL_WITHIN_MM = 10;

/** How far past a side the lip is looked for: two land cells, as a pad's grading meets the bank within the cell its edge falls in. */
export const TRAIL_LIP_REACH_MM = 2 * LAND_CELL_MM;

/** The longest face, across the plan from its lip: a bound on the work of one station (about 70 land samples). */
export const TRAIL_FACE_REACH_MM = 16_000;

/** A face is straight while no point of it lies farther than this from the line from its lip: a rigid plant neither floats nor cuts in by more. */
export const TRAIL_STRAIGHT_WITHIN_MM = 50;

/** A wall or boundary box starts the face where its outer face lies within this of the side: a parapet's outer face is on its zone's edge. */
export const TRAIL_WALL_FLUSH_MM = 50;

/** Halvings of the step that brackets the lip: 250 mm halved five times is under 8 mm, within the level's own tolerance. */
const LIP_HALVINGS = 5;

/** The walker's reach in millimetres: a plant hanging within it of a path is walked through. */
const WALKER_MM = SITE_WALKER_RADIUS_M * 1000;

/** A slot as the edge finder reads it: cover's, with its family and the building it is a piece of. */
export interface TrailSlot extends CoverSlot {
  readonly family: string;
  /** The building a slot is a piece of; a wall with none is a parapet or a boundary. */
  readonly structure?: string;
}

/** The land as the edge finder reads it: its height and where scenery may stand. */
export type TrailLand = Pick<SiteLand, 'groundMm' | 'dryAt'>;

/** A trail rule's figures as its manifest states them; each absent takes its default. */
export interface TrailFigures {
  /** The least drop that grows, millimetres; `TRAIL_DROP_LEAST_MM` when absent. */
  readonly drop_mm?: number;
  /** The least slope of a face, per mille; `TRAIL_SLOPE_LEAST_PERMILLE` when absent. */
  readonly slope_permille?: number;
  /** How far from the sun a side may face, millidegrees; every side when absent. */
  readonly sun_within_mdeg?: number;
}

/** What the edge finder is told besides the rule: the sun's azimuth the look is drawn with, if any. */
export interface TrailEdgeOptions {
  /** Degrees; the rule's sun test passes every side when none. */
  readonly sunAzimuthDeg?: number | null;
}

/** The side of a slot's rectangle, by the way it faces. */
export type TrailSideName = 'south' | 'east' | 'north' | 'west';

/**
 * Why a station grows nothing: its side faces away from the sun; the level is under water or is not
 * this slot's top; the land does not fall past it; it falls too gently for a face; the drop is too
 * shallow; a path or road, a box or water lies across the strip; the foot is under water.
 */
export type TrailLeftOut = 'sun' | 'wet' | 'covered' | 'no fall' | 'no face' | 'shallow' | 'path' | 'box' | 'water' | 'wet foot';

/** A point in the site's frame, millimetres: east, north, up. */
export type TrailPointMm = readonly [number, number, number];

/** A station along a side: where it is along the side (east or north, millimetres), and what was found. */
export type TrailStation = {
  readonly alongMm: number;
  readonly leftOut: TrailLeftOut;
} | {
  readonly alongMm: number;
  readonly leftOut: null;
  /** The land one cell inside the side. */
  readonly levelMm: number;
  /** The last point out from the level still at the level. */
  readonly lipMm: TrailPointMm;
  /** Where a plant hangs from: the wall's top outer edge, else the lip. */
  readonly topMm: TrailPointMm;
  /** The last point of the face's straight run. */
  readonly footMm: TrailPointMm;
  /** The level less the land at the foot. */
  readonly dropMm: number;
  /** The wall or boundary box the face starts on, by identity; null where the face starts at the lip. */
  readonly wall: string | null;
};

/** A side of the slot: which, the way it faces in plan (a unit vector east, north), and its stations. */
export interface TrailSide {
  readonly side: TrailSideName;
  readonly outward: readonly [number, number];
  readonly stations: readonly TrailStation[];
}

/** The sides in the order they are read: a fixed order, since the plants hung on them are drawn from one seed in turn. */
const SIDES: readonly { readonly side: TrailSideName; readonly outward: readonly [number, number] }[] = [
  { side: 'south', outward: [0, -1] },
  { side: 'east', outward: [1, 0] },
  { side: 'north', outward: [0, 1] },
  { side: 'west', outward: [-1, 0] },
];

/** A rectangle in plan, millimetres: west, south, east, north. */
type Rect = readonly [number, number, number, number];

const overlaps = (a: Rect, b: Rect): boolean => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
const inside = (rect: Rect, eastMm: number, northMm: number): boolean =>
  eastMm >= rect[0] && eastMm <= rect[2] && northMm >= rect[1] && northMm <= rect[3];

/**
 * The sides of `slot` (a ground plane of a site on land) and their stations: where a plant may hang
 * over its edge down the land past it, by `figures`, and why each other station grows nothing.
 * `slots` are the drawing's slots, the ones that may stand on it, lie over it or keep a plant out.
 */
export function findTrailEdges(
  slot: TrailSlot,
  land: TrailLand,
  slots: readonly TrailSlot[],
  figures: TrailFigures = {},
  { sunAzimuthDeg = null }: TrailEdgeOptions = {},
): TrailSide[] {
  const leastDrop = figures.drop_mm ?? TRAIL_DROP_LEAST_MM;
  const leastFall = ((figures.slope_permille ?? TRAIL_SLOPE_LEAST_PERMILLE) * TRAIL_STEP_MM) / 1000;
  const sun = sunAzimuthDeg === null || figures.sun_within_mdeg === undefined ? null : towardSun(sunAzimuthDeg);
  const others = slots.filter((one) => one.identity !== slot.identity);
  const rects = new Map<TrailSlot, Rect>(others.map((one) => [one, slotRectMm(one)]));
  // A draped slot stands as far above the land under each point as its base stands above the land under its centre.
  const heightAt = (one: TrailSlot, eastMm: number, northMm: number): number => {
    const top = one.primitive === 'plane' ? 0 : one.boxMm[2]!;
    if (one.drape !== true) return one.positionMm[2]! + top;
    return land.groundMm(eastMm, northMm) + one.positionMm[2]! - land.groundMm(one.positionMm[0]!, one.positionMm[1]!) + top;
  };
  // Cover's own test: another slot stands on this one at a point, or another plane's surface lies above its own there.
  const covered = (eastMm: number, northMm: number): boolean => {
    const own = heightAt(slot, eastMm, northMm);
    return others.some((one) => inside(rects.get(one)!, eastMm, northMm)
      && (one.primitive !== 'plane' || heightAt(one, eastMm, northMm) > own));
  };
  const parapet = (one: TrailSlot): boolean => (one.family === 'wall' || one.family === 'boundary') && one.primitive === 'box' && one.structure === undefined;
  const [west, south, east, north] = slotRectMm(slot);
  return SIDES.map(({ side, outward }) => {
    const acrossEast = outward[0] !== 0;
    // The side's line across the plan, and its span along it.
    const edge = side === 'west' ? west : side === 'east' ? east : side === 'south' ? south : north;
    const [from, to] = acrossEast ? [south, north] : [west, east];
    const sign = acrossEast ? outward[0] : outward[1];
    /** A site point `out` millimetres past the side (negative inside it), `along` along it. */
    const at = (along: number, out: number): readonly [number, number] => acrossEast ? [edge + sign * out, along] : [along, edge + sign * out];
    /** A rectangle from `near` to `far` past the side, `along` plus or minus `half` along it. */
    const strip = (along: number, half: number, near: number, far: number): Rect => {
      const [a, b] = [edge + sign * near, edge + sign * far];
      const [low, high] = [Math.min(a, b), Math.max(a, b)];
      return acrossEast ? [low, along - half, high, along + half] : [along - half, low, along + half, high];
    };
    /** How far past the side a rectangle's outer face lies. */
    const outerOf = (rect: Rect): number => side === 'west' ? edge - rect[0] : side === 'east' ? rect[2] - edge : side === 'south' ? edge - rect[1] : rect[3] - edge;
    const spans = (rect: Rect, along: number): boolean => acrossEast ? along >= rect[1] && along <= rect[3] : along >= rect[0] && along <= rect[2];
    const count = Math.max(1, Math.floor((to - from) / TRAIL_STATION_MM));
    const sunny = sun === null || (Math.acos(Math.max(-1, Math.min(1, outward[0] * sun[0] + outward[1] * sun[1]))) * 180_000) / Math.PI <= figures.sun_within_mdeg!;
    /** What one station finds, `along` the side. */
    const stationAt = (along: number): TrailStation => {
      if (!sunny) return { alongMm: along, leftOut: 'sun' };
      const ground = (out: number): number => { const [e, n] = at(along, out); return land.groundMm(e, n); };
      // The level: the land one cell inside the side, where this slot is the top and dry.
      const [le, ln] = at(along, -LAND_CELL_MM);
      if (!land.dryAt(le, ln)) return { alongMm: along, leftOut: 'wet' };
      if (covered(le, ln)) return { alongMm: along, leftOut: 'covered' };
      const level = ground(-LAND_CELL_MM);
      const atLevel = (out: number): boolean => Math.abs(ground(out) - level) <= TRAIL_LEVEL_WITHIN_MM;
      // The lip: the last step out still at the level, then the step that brackets it halved; the land
      // must leave the level within reach, and lie below it one cell past the lip.
      let lo = -LAND_CELL_MM;
      while (lo + TRAIL_STEP_MM <= TRAIL_LIP_REACH_MM && atLevel(lo + TRAIL_STEP_MM)) lo += TRAIL_STEP_MM;
      let hi = lo + TRAIL_STEP_MM;
      if (atLevel(hi)) return { alongMm: along, leftOut: 'no fall' };
      for (let k = 0; k < LIP_HALVINGS; k += 1) {
        const mid = (lo + hi) / 2;
        if (atLevel(mid)) lo = mid;
        else hi = mid;
      }
      const lip = lo;
      if (!(ground(lip + LAND_CELL_MM) < level - TRAIL_LEVEL_WITHIN_MM)) return { alongMm: along, leftOut: 'no fall' };
      // The wall: a parapet whose outer face is on the side and spans the station starts the face at its top.
      const wall = others.find((one) => parapet(one) && Math.abs(outerOf(rects.get(one)!)) <= TRAIL_WALL_FLUSH_MM && spans(rects.get(one)!, along)) ?? null;
      // The face: steps out from the lip while each falls faster than the least slope, cut where a point
      // leaves the straight line from the lip.
      const face: [number, number][] = [[lip, ground(lip)]];
      for (let out = lip + TRAIL_STEP_MM; out - lip <= TRAIL_FACE_REACH_MM; out += TRAIL_STEP_MM) {
        const down = ground(out);
        if (!(face[face.length - 1]![1] - down > leastFall)) break;
        face.push([out, down]);
      }
      if (face.length < 2) return { alongMm: along, leftOut: 'no face' };
      let footAt = 1;
      for (let k = 2; k < face.length; k += 1) {
        const [d0, h0] = face[0]!, [dk, hk] = face[k]!;
        const length = Math.hypot(dk - d0, hk - h0);
        if (!face.slice(1, k).every(([d, h]) => Math.abs((dk - d0) * (h - h0) - (hk - h0) * (d - d0)) / length <= TRAIL_STRAIGHT_WITHIN_MM)) break;
        footAt = k;
      }
      const [footOut, footUp] = face[footAt]!;
      // The drop: the level less the land at the foot.
      const drop = level - footUp;
      if (drop < leastDrop) return { alongMm: along, leftOut: 'shallow' };
      // Keep-outs across the strip from the level to a walker's reach past the foot, and a dry foot.
      const across = strip(along, WALKER_MM, -LAND_CELL_MM, footOut + WALKER_MM);
      for (const one of others) {
        if (one === wall || !overlaps(rects.get(one)!, across)) continue;
        if (one.family === 'water') return { alongMm: along, leftOut: 'water' };
        if (one.primitive !== 'plane') return { alongMm: along, leftOut: 'box' };
        if (one.family === 'path' || one.family === 'road') return { alongMm: along, leftOut: 'path' };
      }
      const [fe, fn] = at(along, footOut);
      if (!land.dryAt(fe, fn)) return { alongMm: along, leftOut: 'wet foot' };
      const [pe, pn] = at(along, lip);
      const lipMm: TrailPointMm = [pe, pn, ground(lip)];
      let topMm = lipMm;
      if (wall !== null) {
        const [we, wn] = at(along, outerOf(rects.get(wall)!));
        topMm = [we, wn, heightAt(wall, we, wn)];
      }
      return { alongMm: along, leftOut: null, levelMm: level, lipMm, topMm, footMm: [fe, fn, footUp], dropMm: drop, wall: wall?.identity ?? null };
    };
    const stations: TrailStation[] = [];
    for (let i = 0; i < count; i += 1) stations.push(stationAt(from + ((to - from) * (i + 0.5)) / count));
    return { side, outward, stations };
  });
}
