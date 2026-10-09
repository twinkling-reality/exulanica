/**
 * Where a person first stands in a generated town, so the first look sees what was placed there.
 *
 * A town is opened at its served arrival, facing the way the entry says a person arriving faces, and
 * a scene dressed for an arrival is laid out ahead of it, across the street. A vehicle parked at the
 * kerb in between can fill the view, so the scene stands small behind it. The view here keeps the
 * served spot where nothing parked lies between it and the placed things, and otherwise steps along
 * the footway, then back from the kerb, to the nearest spot on drawn ground whose sight line is clear;
 * it always faces the middle of the placed things. With nothing placed it looks the way the entry says.
 * Where no spot near is clear (a kerb lined with parked cars), it takes the one whose nearest car in the
 * way is farthest from it, so that car stands smallest in the view. Everything is in the region's plan
 * frame: millimetres east and south.
 */

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

export function arrivalView(input: {
  readonly eastMm: number;
  readonly southMm: number;
  readonly facing: readonly [east: number, south: number];
  /** The placed things' plan points; none looks the way the entry says. */
  readonly targets: readonly (readonly [number, number])[];
  readonly parked: readonly PlanFootprint[];
  /** Whether a person may stand at a plan point (the drawn ground holds it). */
  readonly ground: (eastMm: number, southMm: number) => boolean;
}): ArrivalView {
  const { eastMm, southMm, facing } = input;
  const length = Math.hypot(facing[0], facing[1]) || 1;
  const ahead: [number, number] = [facing[0] / length, facing[1] / length];
  const aim: [number, number] = input.targets.length === 0
    ? [eastMm + ahead[0] * AHEAD_MM, southMm + ahead[1] * AHEAD_MM]
    : [
      input.targets.reduce((sum, [east]) => sum + east, 0) / input.targets.length,
      input.targets.reduce((sum, [, south]) => sum + south, 0) / input.targets.length,
    ];
  const blocking = (east: number, south: number): PlanFootprint[] =>
    input.parked.filter((footprint) => crosses([east, south], aim, footprint));
  const clear = (east: number, south: number): boolean => blocking(east, south).length === 0;
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
