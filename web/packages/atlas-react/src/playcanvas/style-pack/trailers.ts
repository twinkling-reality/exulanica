import { LAND_CELL_MM } from '@exulanica/atlas-core';
import type { SiteLand } from '../generated-site/site-land.js';
import { SITE_WALKER_RADIUS_M } from '../generated-site/site-navigation.js';
import { CLIMB_STANDOFF_M, towardSun } from './climbers.js';
import { drapeLiftMm, slotRectMm, slotTopMm, type CoverSlot } from './ground-cover.js';
import { generator, seedOf } from './seeded.js';

/**
 * Where plants may hang over a terrace's edge: for a ground plane of a site on land, each side of its
 * rectangle with the stations along it, and at each station the land's lip, the top and foot of the
 * face a plant would hang down, and the drop, or why nothing hangs there.
 *
 * The drawing states no terrace and no edge: a zone is a level pad in the graded land, and the drop
 * is the land past it, a bank or a retaining cell. So the edge is read from the land. One land cell
 * inside the side is the level; stepping out, the lip is the last point still at the level, and the
 * land must have fallen one cell past it. Down the land the face goes on while each step falls faster
 * than the rule's least slope and stays on the straight line from the lip (a plant is rigid). The drop
 * is the level less the land at the face's foot. A wall or boundary box whose outer face is on the
 * side is a parapet: a plant hangs from its top straight down its outer face to the land at its foot,
 * never out over the land face below, so a plant over a bank stands against the wall and not in the
 * air before it; the drop is still the land's, and the wall's own height does not count toward it.
 * A station is left out where it is not this slot's top, where its side faces away from the
 * sun the rule asks for, and where a path or road, a box other than the wall hung over, or water lies
 * across the strip from the level to a walker's reach past the foot, or the foot is under water.
 *
 * Plants grow along runs of neighbouring stations whose lips and faces agree, as climbers grow along
 * a wall: chosen in turn until their widths cover the rule's share of the run, spaced evenly, each
 * hanging a share of the run's shortest face, so none reaches past a foot. A plant piece is authored
 * with its foot at y = 0 and its stems toward +Y, leaves toward +Z; the page lays +Y down the face.
 *
 * PRESENTATION ONLY: what this finds places plants that are drawn and never walked, picked or
 * listed. Heights are millimetres above the land's datum, in the site's frame (x east, y north). A
 * site grows at most `TRAIL_PLACEMENTS_MAX` plants, counting only plants that grow: past it the
 * plants met first keep their places and the rest are counted as left out. A run takes at most
 * `TRAIL_PER_RUN_MAX`, and a site reads at most `TRAIL_STATIONS_MAX` stations.
 */

/** The most trailing plants one site grows: a guard on the page's work, not a look's choice. */
export const TRAIL_PLACEMENTS_MAX = 2_000;

/** The most plants one run takes: a bound on a rule over a long run with narrow plants. */
export const TRAIL_PER_RUN_MAX = 64;

/**
 * The most stations one site reads, about 70 land samples each: a bound on the work of finding edges.
 * A slot whose stations would pass it is not read, and its stations are counted as untried.
 */
export const TRAIL_STATIONS_MAX = 16_000;

/** Neighbouring stations are one run while their faces turn by no more than this, millidegrees: a rigid plant spans them without floating off either. */
export const TRAIL_RUN_TURN_MDEG = 10_000;

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
  /** Where a plant hangs from: the parapet's top outer edge, else the lip. */
  readonly topMm: TrailPointMm;
  /** Where the face a plant hangs down ends: the land at the parapet's outer foot, else the last point of the land face's straight run. */
  readonly footMm: TrailPointMm;
  /** The level less the land at the foot of the land face's straight run. */
  readonly dropMm: number;
  /** The wall or boundary box the face starts on, by identity; null where the face starts at the lip. */
  readonly wall: string | null;
};

/** A side of the slot: which, the way it faces in plan (a unit vector east, north), and its stations. */
export interface TrailSide {
  readonly side: TrailSideName;
  readonly outward: readonly [number, number];
  /** The stations' spacing along the side, millimetres: each stands for that much of it, centred on it. */
  readonly stepMm: number;
  readonly stations: readonly TrailStation[];
}

/** A station where a plant may hang. */
export type TrailKept = Extract<TrailStation, { leftOut: null }>;

/** How many stations a side of this length takes: one every `TRAIL_STATION_MM`, at least one. */
const stationsAlong = (lengthMm: number): number => Math.max(1, Math.floor(lengthMm / TRAIL_STATION_MM));

/** How many stations the finder reads round a slot's four sides. */
export function trailStationCount(slot: CoverSlot): number {
  const [west, south, east, north] = slotRectMm(slot);
  return 2 * stationsAlong(east - west) + 2 * stationsAlong(north - south);
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
  // A slot's top at a point, by cover's own rule: a draped slot stands as far above the land under each
  // point as its base stands above the land under its centre.
  const lifts = new Map<TrailSlot, number | null>([slot, ...others].map((one) => [one, drapeLiftMm(one, land)]));
  const heightAt = (one: TrailSlot, eastMm: number, northMm: number): number => slotTopMm(one, lifts.get(one) ?? null, land, eastMm, northMm);
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
    const count = stationsAlong(to - from);
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
      // The wall: a parapet whose outer face is on the side, spans the station and stands above the land at that face.
      const flush = others.find((one) => parapet(one) && Math.abs(outerOf(rects.get(one)!)) <= TRAIL_WALL_FLUSH_MM && spans(rects.get(one)!, along)) ?? null;
      const outer = flush === null ? 0 : outerOf(rects.get(flush)!);
      const [we, wn] = at(along, outer);
      const wall = flush !== null && heightAt(flush, we, wn) > ground(outer) ? flush : null;
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
      // Over a parapet a plant hangs from its top down its outer face, to the land at its foot.
      const topMm: TrailPointMm = wall === null ? lipMm : [we, wn, heightAt(wall, we, wn)];
      const footMm: TrailPointMm = wall === null ? [fe, fn, footUp] : [we, wn, ground(outer)];
      return { alongMm: along, leftOut: null, levelMm: level, lipMm, topMm, footMm, dropMm: drop, wall: wall?.identity ?? null };
    };
    const stations: TrailStation[] = [];
    for (let i = 0; i < count; i += 1) stations.push(stationAt(from + ((to - from) * (i + 0.5)) / count));
    return { side, outward, stepMm: (to - from) / count, stations };
  });
}

/** A run of neighbouring stations a plant may hang along: its side, its span along it, its stations, its shortest face. */
export interface TrailRun {
  readonly side: TrailSideName;
  readonly outward: readonly [number, number];
  /** Where the run starts and ends along the side, millimetres east or north. */
  readonly fromMm: number;
  readonly toMm: number;
  readonly stations: readonly TrailKept[];
  /** The shortest face of its stations, from top to foot, millimetres. */
  readonly leastFaceMm: number;
}

/** Down a station's face from its top to its foot, site millimetres (east, north, up), and its length. */
function faceOf(station: TrailKept): { readonly down: readonly [number, number, number]; readonly lengthMm: number } {
  const v = [0, 1, 2].map((k) => station.footMm[k]! - station.topMm[k]!) as [number, number, number];
  const lengthMm = Math.hypot(v[0], v[1], v[2]);
  return { down: [v[0] / lengthMm, v[1] / lengthMm, v[2] / lengthMm], lengthMm };
}

/**
 * A side's runs: its kept stations next to each other whose lips lie within `TRAIL_STRAIGHT_WITHIN_MM`
 * of each other out from the side and up, that hang from the same wall or none, and whose faces turn
 * by at most `TRAIL_RUN_TURN_MDEG`.
 */
export function trailRuns(side: TrailSide): TrailRun[] {
  const runs: TrailRun[] = [];
  const across = side.outward[0] !== 0 ? 0 : 1;
  const tilt = (station: TrailKept): number => {
    const { down } = faceOf(station);
    return (Math.atan2(Math.hypot(down[0], down[1]), -down[2]) * 180_000) / Math.PI;
  };
  let current: TrailKept[] = [];
  const close = (): void => {
    if (current.length === 0) return;
    const half = side.stepMm / 2;
    runs.push({
      side: side.side, outward: side.outward,
      fromMm: current[0]!.alongMm - half, toMm: current[current.length - 1]!.alongMm + half,
      stations: current, leastFaceMm: Math.min(...current.map((one) => faceOf(one).lengthMm)),
    });
    current = [];
  };
  for (const station of side.stations) {
    if (station.leftOut !== null) { close(); continue; }
    const last = current[current.length - 1];
    if (last !== undefined && !(
      Math.abs(station.lipMm[across] - last.lipMm[across]) <= TRAIL_STRAIGHT_WITHIN_MM
      && Math.abs(station.lipMm[2] - last.lipMm[2]) <= TRAIL_STRAIGHT_WITHIN_MM
      && station.wall === last.wall
      && Math.abs(tilt(station) - tilt(last)) <= TRAIL_RUN_TURN_MDEG)) close();
    current.push(station);
  }
  close();
  return runs;
}

/** A trail rule as its manifest states it: its plant pieces, the share of a run they cover, how much of the face each hangs, its seed and figures. */
export interface TrailRule extends TrailFigures {
  readonly pieces: readonly string[];
  readonly share_permille: number;
  readonly hang_permille: readonly [number, number];
  readonly seed: number;
}

/** One plant to hang: which, where along its side, how wide, where it hangs from, which way the face runs, how far it hangs. */
export interface TrailPoint {
  readonly piece: string;
  /** A draw in [0, 1) that chooses among the piece's variants. */
  readonly pick: number;
  readonly side: TrailSideName;
  /** The middle of the plant along its side, millimetres east or north. */
  readonly alongMm: number;
  readonly widthMm: number;
  /** Where the plant hangs from, metres: east, north, up. */
  readonly topM: readonly [number, number, number];
  /** Down the face, a unit vector: east, north, up. */
  readonly down: readonly [number, number, number];
  /** The face's normal away from the land, a unit vector: east, north, up. */
  readonly normal: readonly [number, number, number];
  readonly hangM: number;
  /** The wall it hangs over, by identity, or null. */
  readonly wall: string | null;
}

/**
 * A site's trailing plants, how many slots grow any, how many hang over a wall, how many the guard
 * left out, and how many stations the bound on stations never read.
 */
export interface GrownTrail {
  readonly points: readonly TrailPoint[];
  readonly terraces: number;
  readonly walled: number;
  readonly leftOut: number;
  readonly untried: number;
}

/** Where and how much a site's trailing plants grow: their pieces' sizes, the sun and the guards. */
export interface TrailOptions {
  /** The authored size (width, depth, height, millimetres) of the variant `pick` chooses of a plant role; null when the pack has none. */
  readonly sizeOf: (piece: string, pick: number) => readonly [number, number, number] | null;
  /** The sun's azimuth the look is drawn with, degrees; a rule's sun test passes every side when none. */
  readonly sunAzimuthDeg?: number | null;
  /** The most plants grown; `TRAIL_PLACEMENTS_MAX` when absent. */
  readonly most?: number;
  /** The most stations read; `TRAIL_STATIONS_MAX` when absent. */
  readonly stations?: number;
}

/**
 * Hang each ruled slot's plants over its edges, in the order given: one generator a slot from the
 * rule's seed and the slot's identity, its sides in the finder's order, along each run plants chosen
 * in turn until their widths cover the rule's share of it, spaced evenly, each hanging the run's
 * shortest face times a share drawn in the rule's `hang_permille`; at most `most` in all.
 */
export function growTrailers(
  ruled: readonly { readonly slot: TrailSlot; readonly rule: TrailRule }[],
  land: TrailLand,
  slots: readonly TrailSlot[],
  { sizeOf, sunAzimuthDeg = null, most = TRAIL_PLACEMENTS_MAX, stations = TRAIL_STATIONS_MAX }: TrailOptions,
): GrownTrail {
  const points: TrailPoint[] = [];
  let leftOut = 0;
  let untried = 0;
  let read = 0;
  let terraces = 0;
  let walled = 0;
  for (const { slot, rule } of ruled) {
    const count = trailStationCount(slot);
    if (read + count > stations) {
      untried += count;
      continue;
    }
    read += count;
    const next = generator(seedOf(rule.seed, slot.identity));
    const [least, most_] = rule.hang_permille;
    let grew = 0;
    for (const side of findTrailEdges(slot, land, slots, rule, { sunAzimuthDeg })) {
      const across = side.outward[0] !== 0 ? 0 : 1;
      for (const run of trailRuns(side)) {
        const lengthMm = run.toMm - run.fromMm;
        const wanted = (lengthMm * rule.share_permille) / 1000;
        const chosen: { piece: string; pick: number; widthMm: number; hangMm: number }[] = [];
        let covered = 0;
        while (covered < wanted && chosen.length < TRAIL_PER_RUN_MAX) {
          const piece = rule.pieces[Math.floor(next() * rule.pieces.length) % rule.pieces.length]!;
          const pick = next();
          const hangMm = (run.leastFaceMm * (least + (most_ - least) * next())) / 1000;
          const size = sizeOf(piece, pick);
          if (size === null || !(size[2] > 0)) break;
          const widthMm = (size[0] * hangMm) / size[2];
          if (covered + widthMm > lengthMm) break;
          chosen.push({ piece, pick, widthMm, hangMm });
          covered += widthMm;
        }
        // The run's length less the plants', shared evenly before, between and after them.
        const gap = (lengthMm - covered) / (chosen.length + 1);
        let at = run.fromMm + gap;
        for (const plant of chosen) {
          const middle = at + plant.widthMm / 2;
          at += plant.widthMm + gap;
          if (points.length >= most) {
            leftOut += 1;
            continue;
          }
          // The face of the station the plant's middle stands at, its top moved along the side to the plant.
          const index = Math.min(run.stations.length - 1, Math.max(0, Math.floor((middle - run.fromMm) / side.stepMm)));
          const station = run.stations[index]!;
          const { down } = faceOf(station);
          const top = [...station.topMm];
          top[1 - across] = middle;
          // Away from the land: down the face turned a quarter up, in the plane of the side's outward and up.
          const reach = down[0] * side.outward[0] + down[1] * side.outward[1];
          points.push({
            piece: plant.piece,
            pick: plant.pick,
            side: side.side,
            alongMm: middle,
            widthMm: plant.widthMm,
            topM: [top[0]! / 1000, top[1]! / 1000, top[2]! / 1000],
            down,
            normal: [-down[2] * side.outward[0], -down[2] * side.outward[1], reach],
            hangM: plant.hangMm / 1000,
            wall: station.wall,
          });
          grew += 1;
          if (station.wall !== null) walled += 1;
        }
      }
    }
    if (grew > 0) terraces += 1;
  }
  return { points, terraces, walled, leftOut, untried };
}

/**
 * The column-major matrix that hangs a plant piece (glTF metres, bounds least x, y, z then most) at
 * `point`, in renderer metres (east, up, south): +Y down the face, +Z the face's normal away from the
 * land, +X their cross, so it turns and never mirrors; scaled whole so its height is the hang; its
 * back (its least z) set `CLIMB_STANDOFF_M` in front of the face at the plant's top.
 */
export function trailMatrix(point: TrailPoint, bounds: readonly number[]): Float32Array {
  const scale = point.hangM / bounds[4]!;
  // Site (east, north, up) to renderer (east, up, south).
  const y = [point.down[0], point.down[2], -point.down[1]] as const;
  const z = [point.normal[0], point.normal[2], -point.normal[1]] as const;
  const x = [y[1] * z[2] - y[2] * z[1], y[2] * z[0] - y[0] * z[2], y[0] * z[1] - y[1] * z[0]] as const;
  const out = CLIMB_STANDOFF_M - bounds[2]! * scale;
  const [east, north, up] = point.topM;
  return new Float32Array([
    x[0] * scale, x[1] * scale, x[2] * scale, 0,
    y[0] * scale, y[1] * scale, y[2] * scale, 0,
    z[0] * scale, z[1] * scale, z[2] * scale, 0,
    east + z[0] * out, up + z[1] * out, -north + z[2] * out, 1,
  ]);
}
