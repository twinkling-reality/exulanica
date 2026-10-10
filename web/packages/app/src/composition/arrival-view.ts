/**
 * Where a person first stands in a generated town, so the first look sees what was placed there.
 *
 * A town is opened at its served arrival, facing the way the entry says a person arriving faces, and
 * a scene dressed for an arrival is laid out ahead of it, across the street. A vehicle parked at the
 * kerb in between can fill the view, so the scene stands small behind it. The view here keeps the
 * served spot where nothing parked lies between it and the placed things, and otherwise steps along
 * the footway, then back from the kerb, to the nearest spot on drawn ground whose sight line is clear;
 * it always faces the middle of the placed things. With nothing placed it looks along the street at
 * a slant, from the most open spot near (`openView`), where a caller hands the rule for that, and
 * otherwise the way the entry says. A caller may also hand what else stands at eye height (a
 * building, a trunk, a lamp post), and a sight line to the placed things is then clear of those too.
 * Where no spot near is clear (a kerb lined with parked cars), it takes the one whose nearest car in the
 * way is farthest from it, so that car stands smallest in the view. Everything is in the region's plan
 * frame: millimetres east and south.
 */
import type { OpenViewRule } from '../town-first-view.js';

export type { OpenViewRule };

/** A vehicle's footprint on the plan: its middle, half its length and width, and its heading. */
export interface PlanFootprint {
  readonly eastMm: number;
  readonly southMm: number;
  readonly halfLengthMm: number;
  readonly halfWidthMm: number;
  /** Radians from east toward south, the way its front points. */
  readonly heading: number;
}

export interface ArrivalView {
  readonly eastMm: number;
  readonly southMm: number;
  /** The renderer's yaw: 0 looks north, forward (-sin yaw, 0, -cos yaw). */
  readonly yaw: number;
  /** Whether it stepped away from the served spot to see past something parked. */
  readonly moved: boolean;
}

/** How far a step along the footway or back from the kerb goes, and the most steps each way. */
export const ARRIVAL_STEP_MM = 1500;
export const ARRIVAL_STEPS = 8;
/** Room kept round a parked vehicle's footprint so the sight line does not graze it. */
const CLEARANCE_MM = 300;
/** Where to look with nothing placed: this far ahead the way a person arriving faces. */
const AHEAD_MM = 10_000;

const yawToward = (fromEast: number, fromSouth: number, toEast: number, toSouth: number): number =>
  Math.atan2(-(toEast - fromEast), -(toSouth - fromSouth));

/** Whether the segment from a to b passes through the footprint, grown by the clearance. */
export function crosses(
  a: readonly [number, number], b: readonly [number, number], footprint: PlanFootprint,
): boolean {
  // Carry the segment into the footprint's own frame, where it is an axis-aligned box.
  const cos = Math.cos(-footprint.heading);
  const sin = Math.sin(-footprint.heading);
  const local = ([east, south]: readonly [number, number]): [number, number] => {
    const x = east - footprint.eastMm;
    const y = south - footprint.southMm;
    return [x * cos - y * sin, x * sin + y * cos];
  };
  const [ax, ay] = local(a);
  const [bx, by] = local(b);
  const hx = footprint.halfLengthMm + CLEARANCE_MM;
  const hy = footprint.halfWidthMm + CLEARANCE_MM;
  // Slab test: the part of the segment inside each pair of sides must overlap.
  let low = 0;
  let high = 1;
  for (const [start, delta, half] of [[ax, bx - ax, hx], [ay, by - ay, hy]] as const) {
    if (Math.abs(delta) < 1e-9) {
      if (Math.abs(start) > half) return false;
      continue;
    }
    let t1 = (-half - start) / delta;
    let t2 = (half - start) / delta;
    if (t1 > t2) [t1, t2] = [t2, t1];
    low = Math.max(low, t1);
    high = Math.min(high, t2);
    if (low > high) return false;
  }
  return true;
}

/** A closed plan ring of something that stands in a sight line at eye height: millimetres east and south. */
export type SightBlocker = readonly (readonly [number, number])[];

/** How far a sight line from `from` along the unit direction `toward` runs before a ring's edge, at most `reach`. */
export function openDistance(
  from: readonly [number, number], toward: readonly [number, number], rings: readonly SightBlocker[], reach: number,
): number {
  let nearest = reach;
  for (const ring of rings) {
    for (let i = 0; i < ring.length; i += 1) {
      const a = ring[i]!;
      const b = ring[(i + 1) % ring.length]!;
      const ex = b[0] - a[0];
      const ey = b[1] - a[1];
      const across = toward[0] * ey - toward[1] * ex;
      if (Math.abs(across) < 1e-9) continue;
      const t = ((a[0] - from[0]) * ey - (a[1] - from[1]) * ex) / across;
      const u = ((a[0] - from[0]) * toward[1] - (a[1] - from[1]) * toward[0]) / across;
      if (t > 0 && u >= 0 && u <= 1 && t < nearest) nearest = t;
    }
  }
  return nearest;
}

/** A parked vehicle's footprint, grown by the clearance, as a plan ring. */
function footprintRing(footprint: PlanFootprint): SightBlocker {
  const cos = Math.cos(footprint.heading);
  const sin = Math.sin(footprint.heading);
  const hx = footprint.halfLengthMm + CLEARANCE_MM;
  const hy = footprint.halfWidthMm + CLEARANCE_MM;
  return ([[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]] as const).map(([x, y]) => [
    footprint.eastMm + x * cos - y * sin, footprint.southMm + x * sin + y * cos,
  ] as const);
}

/**
 * How open a view is: the mean, over a fan of sight lines about where it looks, of how far each
 * runs before something stands in it, as a share of the reach; a quarter of that where something
 * stands in the viewer's face, within `faceMm` on the middle lines.
 */
export function viewOpenness(
  from: readonly [number, number], toward: readonly [number, number], rings: readonly SightBlocker[], rule: OpenViewRule,
): number {
  const lines = Math.max(1, Math.round(rule.sightLines));
  const base = Math.atan2(toward[1], toward[0]);
  let sum = 0;
  let inFace = false;
  for (let i = 0; i < lines; i += 1) {
    const offset = lines === 1 ? 0 : -rule.fanHalf + (2 * rule.fanHalf * i) / (lines - 1);
    const run = openDistance(from, [Math.cos(base + offset), Math.sin(base + offset)], rings, rule.reachMm);
    sum += run / rule.reachMm;
    // The middle third of the fan is dead ahead.
    if (Math.abs(offset) <= rule.fanHalf / 3 && run < rule.faceMm) inFace = true;
  }
  const mean = sum / lines;
  return inFace ? mean / 4 : mean;
}

/**
 * The first view of a town with nothing placed in it: from the served spot or a few steps from it
 * (back from the kerb, off the line people walk, and along the footway), looking along the street
 * at a slant one way or the other, whichever spot and way is most open. It never looks straight
 * across at the wall opposite, and takes a view with something in its face only when every view has
 * one. Standing off the walking line is preferred where the ground lets a person stand there; of
 * equally open views the one nearest the served spot is taken, and of those the first found.
 */
function openView(
  input: {
    readonly eastMm: number; readonly southMm: number;
    readonly ground: (eastMm: number, southMm: number) => boolean;
  },
  ahead: readonly [number, number], rings: readonly SightBlocker[], rule: OpenViewRule,
): ArrivalView {
  const across: readonly [number, number] = [-ahead[1], ahead[0]];
  const turned = (angle: number): readonly [number, number] => [
    ahead[0] * Math.cos(angle) - ahead[1] * Math.sin(angle), ahead[0] * Math.sin(angle) + ahead[1] * Math.cos(angle),
  ];
  let best: { view: ArrivalView; score: number; moved: number } | null = null;
  const backSteps = rule.backStepMm > 0 ? Math.floor(rule.backMaximumMm / rule.backStepMm) : 0;
  const alongSteps = rule.alongStepMm > 0 ? Math.floor(rule.alongMaximumMm / rule.alongStepMm) : 0;
  for (let back = 0; back <= backSteps; back += 1) {
    for (let step = 0; step <= alongSteps; step += 1) {
      for (const side of step === 0 ? [1] : [1, -1]) {
        const along = side * step * rule.alongStepMm;
        const behind = back * rule.backStepMm;
        const east = input.eastMm + across[0] * along - ahead[0] * behind;
        const south = input.southMm + across[1] * along - ahead[1] * behind;
        if ((back > 0 || step > 0) && !input.ground(east, south)) continue;
        for (const way of [1, -1]) {
          const toward = turned(way * rule.slant);
          // Off the line people walk is worth a little: walkers then cross the view, not the viewer.
          const score = viewOpenness([east, south], toward, rings, rule) + (back > 0 ? 0.05 : 0);
          const moved = Math.hypot(along, behind);
          if (best === null || score > best.score + rule.tie || (Math.abs(score - best.score) <= rule.tie && moved < best.moved)) {
            best = {
              view: { eastMm: east, southMm: south, yaw: Math.atan2(-toward[0], -toward[1]), moved: back > 0 || step > 0 },
              score, moved,
            };
          }
        }
      }
    }
  }
  return best!.view;
}

export function arrivalView(input: {
  readonly eastMm: number;
  readonly southMm: number;
  readonly facing: readonly [east: number, south: number];
  /** The placed things' plan points; none looks the way the entry says. */
  readonly targets: readonly (readonly [number, number])[];
  readonly parked: readonly PlanFootprint[];
  /** Whether a person may stand at a plan point (the drawn ground holds it). */
  readonly ground: (eastMm: number, southMm: number) => boolean;
  /**
   * What else stands in a sight line at eye height: buildings, trunks, lamp posts. Absent, parked
   * vehicles alone are looked past, as before.
   */
  readonly blockers?: readonly SightBlocker[];
  /**
   * How to choose the view where nothing is placed. Absent, such a town is looked at the way its
   * entry says, straight across the road, as before.
   */
  readonly open?: OpenViewRule;
}): ArrivalView {
  const { eastMm, southMm, facing } = input;
  const length = Math.hypot(facing[0], facing[1]) || 1;
  const ahead: [number, number] = [facing[0] / length, facing[1] / length];
  if (input.targets.length === 0 && input.open !== undefined) {
    return openView(input, ahead, [...(input.blockers ?? []), ...input.parked.map(footprintRing)], input.open);
  }
  const aim: [number, number] = input.targets.length === 0
    ? [eastMm + ahead[0] * AHEAD_MM, southMm + ahead[1] * AHEAD_MM]
    : [
      input.targets.reduce((sum, [east]) => sum + east, 0) / input.targets.length,
      input.targets.reduce((sum, [, south]) => sum + south, 0) / input.targets.length,
    ];
  const blocking = (east: number, south: number): PlanFootprint[] =>
    input.parked.filter((footprint) => crosses([east, south], aim, footprint));
  /**
   * Whether nothing else at eye height stands between a spot and the placed things. With nothing
   * placed there is no such sight line: the view is the way the entry says, past parked cars alone.
   */
  const unblocked = (east: number, south: number): boolean => {
    const rings = input.targets.length === 0 ? [] : input.blockers ?? [];
    if (rings.length === 0) return true;
    const reach = Math.hypot(aim[0] - east, aim[1] - south);
    if (reach === 0) return true;
    return openDistance([east, south], [(aim[0] - east) / reach, (aim[1] - south) / reach], rings, reach) >= reach;
  };
  const clear = (east: number, south: number): boolean => blocking(east, south).length === 0 && unblocked(east, south);
  /** How far the nearest car in the way stands from a spot (its middle); infinite with none. */
  const nearestBlock = (east: number, south: number): number =>
    Math.min(...blocking(east, south).map((footprint) => Math.hypot(footprint.eastMm - east, footprint.southMm - south)));
  const served: ArrivalView = { eastMm, southMm, yaw: yawToward(eastMm, southMm, aim[0], aim[1]), moved: false };
  if (clear(eastMm, southMm)) return served;
  // Along the footway (across the way a person faces) first, nearest first, then back from the kerb.
  const across: [number, number] = [-ahead[1], ahead[0]];
  const candidates: [number, number, number][] = [];
  for (let back = 0; back <= 3; back += 1) {
    for (let step = 1; step <= ARRIVAL_STEPS; step += 1) {
      for (const side of [1, -1]) {
        const along = side * step * ARRIVAL_STEP_MM;
        const behind = back * ARRIVAL_STEP_MM;
        candidates.push([
          eastMm + across[0] * along - ahead[0] * behind,
          southMm + across[1] * along - ahead[1] * behind,
          Math.hypot(along, behind),
        ]);
      }
    }
    if (back > 0) candidates.push([eastMm - ahead[0] * back * ARRIVAL_STEP_MM, southMm - ahead[1] * back * ARRIVAL_STEP_MM, back * ARRIVAL_STEP_MM]);
  }
  candidates.sort((a, b) => a[2] - b[2]);
  const standing = candidates.filter(([east, south]) => input.ground(east, south));
  for (const [east, south] of standing) {
    if (clear(east, south)) {
      return { eastMm: east, southMm: south, yaw: yawToward(east, south, aim[0], aim[1]), moved: true };
    }
  }
  // Nothing clear near: the spot whose nearest car in the way is farthest (the served one included).
  let best: [number, number, number] = [eastMm, southMm, nearestBlock(eastMm, southMm)];
  for (const [east, south] of standing) {
    const distance = nearestBlock(east, south);
    if (distance > best[2] + 500) best = [east, south, distance];
  }
  if (best[0] === eastMm && best[1] === southMm) return served;
  return { eastMm: best[0], southMm: best[1], yaw: yawToward(best[0], best[1], aim[0], aim[1]), moved: true };
}

/**
 * A parked vehicle's footprint from its traffic samples at one second: its axles' plan points in the
 * road records' frame (east, north), stretched by its overhangs, carried into the region's (east, south).
 */
export function parkedFootprint(vehicle: {
  readonly frontAxleMm: readonly number[];
  readonly rearAxleMm: readonly number[];
  readonly dimensionsMm: { readonly width: number; readonly frontOverhang: number; readonly rearOverhang: number };
}, index = 0): PlanFootprint | null {
  const fx = vehicle.frontAxleMm[index * 2];
  const fn = vehicle.frontAxleMm[index * 2 + 1];
  const rx = vehicle.rearAxleMm[index * 2];
  const rn = vehicle.rearAxleMm[index * 2 + 1];
  if (fx === undefined || fn === undefined || rx === undefined || rn === undefined) return null;
  const [front, rear] = [[fx, -fn], [rx, -rn]] as const;
  const wheelbase = Math.hypot(front[0] - rear[0], front[1] - rear[1]);
  const heading = Math.atan2(front[1] - rear[1], front[0] - rear[0]);
  const along: [number, number] = wheelbase > 0
    ? [(front[0] - rear[0]) / wheelbase, (front[1] - rear[1]) / wheelbase] : [Math.cos(heading), Math.sin(heading)];
  const nose = [front[0] + along[0] * vehicle.dimensionsMm.frontOverhang, front[1] + along[1] * vehicle.dimensionsMm.frontOverhang];
  const tail = [rear[0] - along[0] * vehicle.dimensionsMm.rearOverhang, rear[1] - along[1] * vehicle.dimensionsMm.rearOverhang];
  return {
    eastMm: (nose[0]! + tail[0]!) / 2,
    southMm: (nose[1]! + tail[1]!) / 2,
    halfLengthMm: Math.hypot(nose[0]! - tail[0]!, nose[1]! - tail[1]!) / 2,
    halfWidthMm: vehicle.dimensionsMm.width / 2,
    heading,
  };
}
