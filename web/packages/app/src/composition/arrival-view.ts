/**
 * Where a person first stands in a generated town, so the first look sees what was placed there.
 *
 * A town is opened at its served arrival, facing the way the entry says a person arriving faces, and
 * a scene dressed for an arrival is laid out ahead of it, across the street. A vehicle parked at the
 * kerb in between can fill the view, so the scene stands small behind it. The view here keeps the
 * served spot where nothing parked lies between it and the placed things, and otherwise steps along
 * the footway, then back from the kerb, to the nearest spot on drawn ground whose sight line is clear;
 * it always faces the middle of the placed things. With nothing placed it looks along the street at
 * a slant (`openView`), where a caller hands the rule for that, and otherwise the way the entry
 * says: from the spot near and the way along the street that hold most of the town's life, its seats
 * and doors, with nothing at eye height dead ahead, and the most open of equally alive views. That
 * choice reads the town's own records and nothing that arrives later: parked vehicles do not enter
 * it, so a town opens the same way every time. A caller may also hand what else stands at eye height
 * (a building, a trunk, a lamp post), and a sight line to the placed things is then clear of those too,
 * with nothing of them dead ahead nearer than the distance a rule states, so a view is never of a wall a
 * few steps away. Where no spot near is clear (a kerb lined with parked cars), it takes the one whose
 * nearest car in the way is farthest from it, so that car stands smallest in the view. Where no spot near
 * the footway sees the placed things at all, they stand inside or close against a building: it steps out
 * toward and across the street to the nearest spot that sees them, and where none does, it takes the
 * town's own first view, as for a town with nothing placed. Everything is in the region's plan frame:
 * millimetres east and south.
 */
import { FIRST_VIEW_DEFAULTS, type LifeViewRule, type OpenViewRule, type PlacedViewRule } from '../town-first-view.js';

export type { LifeViewRule, OpenViewRule, PlacedViewRule };

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

const yawToward = (fromEast: number, fromSouth: number, toEast: number, toSouth: number): number =>
  Math.atan2(-(toEast - fromEast), -(toSouth - fromSouth));

/** Whether the segment from a to b passes through the footprint, grown by `clearanceMm` all round. */
export function crosses(
  a: readonly [number, number], b: readonly [number, number], footprint: PlanFootprint,
  clearanceMm: number = FIRST_VIEW_DEFAULTS.placed.parkedClearanceMm,
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
  const hx = footprint.halfLengthMm + clearanceMm;
  const hy = footprint.halfWidthMm + clearanceMm;
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

/**
 * How many buildings show their fronts in a view: those whose face along the street (`street`, a unit
 * plan direction; within a tenth of a right angle's tangent of it) is the first thing at eye height
 * at least `least` of the view's sight lines meet, the lines `step` apart across `fanHalf` either
 * side of `toward` and followed `reach` far. `fronts` are the buildings' outlines, `rings` everything
 * that stands at eye height, those outlines among it.
 */
export function frontsInView(
  from: readonly [number, number], toward: readonly [number, number], fronts: readonly SightBlocker[],
  rings: readonly SightBlocker[], street: readonly [number, number], fanHalf: number, step: number, reach: number,
  least = 1,
): number {
  const met = new Map<number, number>();
  const lines = Math.floor(fanHalf / step);
  for (let line = -lines; line <= lines; line += 1) {
    const angle = line * step;
    const way = [toward[0] * Math.cos(angle) - toward[1] * Math.sin(angle), toward[0] * Math.sin(angle) + toward[1] * Math.cos(angle)] as const;
    const nearest = openDistance(from, way, rings, reach);
    for (let index = 0; index < fronts.length; index += 1) {
      const ring = fronts[index]!;
      for (let i = 0; i < ring.length; i += 1) {
        const a = ring[i]!;
        const b = ring[(i + 1) % ring.length]!;
        const ex = b[0] - a[0];
        const ey = b[1] - a[1];
        if (Math.abs(ex * street[1] - ey * street[0]) * 10 > Math.abs(ex * street[0] + ey * street[1])) continue;
        const across = way[0] * ey - way[1] * ex;
        if (Math.abs(across) < 1e-9) continue;
        const t = ((a[0] - from[0]) * ey - (a[1] - from[1]) * ex) / across;
        const u = ((a[0] - from[0]) * way[1] - (a[1] - from[1]) * way[0]) / across;
        if (t > 0 && u >= 0 && u <= 1 && t <= nearest) {
          met.set(index, (met.get(index) ?? 0) + 1);
          break;
        }
      }
    }
  }
  return [...met.values()].filter((lines) => lines >= least).length;
}

/** A parked vehicle's footprint, grown by `clearanceMm` all round, as a plan ring. */
function footprintRing(footprint: PlanFootprint, clearanceMm: number): SightBlocker {
  const cos = Math.cos(footprint.heading);
  const sin = Math.sin(footprint.heading);
  const hx = footprint.halfLengthMm + clearanceMm;
  const hy = footprint.halfWidthMm + clearanceMm;
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
 * Where a town's life is, on the plan: its seats and its doors, millimetres east and south. A person
 * who sits stays for minutes, and walks begin and end at doors.
 */
export interface TownLife {
  readonly seats: readonly (readonly [number, number])[];
  readonly doors: readonly (readonly [number, number])[];
}

/**
 * The seats among a town's street furniture, by shape and not by name: the middle of every part
 * whose top stands at sitting height above its furniture's base and whose plan is wide and deep
 * enough to sit on, turned as its record faces.
 */
export function seatsOf(
  furniture: readonly {
    readonly eastMm: number; readonly southMm: number; readonly facing: readonly [number, number];
    readonly parts: readonly {
      readonly alongMm: number; readonly leftMm: number; readonly bottomMm: number;
      readonly sizeAlongMm: number; readonly sizeLeftMm: number; readonly heightMm: number;
    }[];
  }[],
  rule: LifeViewRule,
): (readonly [number, number])[] {
  const seats: (readonly [number, number])[] = [];
  for (const item of furniture) {
    const length = Math.hypot(item.facing[0], item.facing[1]);
    if (!(length > 0)) continue;
    // East and south are a left-handed pair seen from above, so left of (e, s) is (s, -e).
    const along = [item.facing[0] / length, item.facing[1] / length] as const;
    const left = [along[1], -along[0]] as const;
    for (const part of item.parts) {
      const top = part.bottomMm + part.heightMm;
      if (top < rule.seatTopMinimumMm || top > rule.seatTopMaximumMm) continue;
      if (Math.min(part.sizeAlongMm, part.sizeLeftMm) < rule.seatSpanMinimumMm) continue;
      seats.push([
        item.eastMm + part.alongMm * along[0] + part.leftMm * left[0],
        item.southMm + part.alongMm * along[1] + part.leftMm * left[1],
      ]);
    }
  }
  return seats;
}

/**
 * How near anything of the rings stands inside the wedge `half` either side of the unit direction
 * `toward` from `from`: the least distance to any part of a ring's edge that lies in the wedge, or
 * infinity where none does. The whole wedge is tested, not sampled lines, so a thin post is found.
 */
export function nearestInWedge(
  from: readonly [number, number], toward: readonly [number, number], half: number, rings: readonly SightBlocker[],
): number {
  const slope = Math.tan(half);
  let nearest = Number.POSITIVE_INFINITY;
  for (const ring of rings) {
    for (let i = 0; i < ring.length; i += 1) {
      const a = ring[i]!;
      const b = ring[(i + 1) % ring.length]!;
      // In the view's own frame: x ahead, y to one side.
      const ax = (a[0] - from[0]) * toward[0] + (a[1] - from[1]) * toward[1];
      const ay = -(a[0] - from[0]) * toward[1] + (a[1] - from[1]) * toward[0];
      const bx = (b[0] - from[0]) * toward[0] + (b[1] - from[1]) * toward[1];
      const by = -(b[0] - from[0]) * toward[1] + (b[1] - from[1]) * toward[0];
      // The wedge is the two half planes x * slope - y >= 0 and x * slope + y >= 0: keep the part
      // of the edge inside both.
      let low = 0;
      let high = 1;
      for (const sign of [1, -1]) {
        const atA = ax * slope - sign * ay;
        const atB = bx * slope - sign * by;
        if (atA < 0 && atB < 0) { low = 1; high = 0; break; }
        if (atA < 0) low = Math.max(low, atA / (atA - atB));
        else if (atB < 0) high = Math.min(high, atA / (atA - atB));
      }
      if (low > high) continue;
      // The nearest point of that part to the viewer.
      const dx = bx - ax;
      const dy = by - ay;
      const span = dx * dx + dy * dy;
      const foot = span === 0 ? low : Math.min(high, Math.max(low, -(ax * dx + ay * dy) / span));
      const distance = Math.hypot(ax + dx * foot, ay + dy * foot);
      if (distance < nearest) nearest = distance;
    }
  }
  return nearest;
}

/** A seat or a door seen from a spot: the unit direction to it and what it counts for there. */
interface SeenLife { readonly toward: readonly [number, number]; readonly weight: number }

/**
 * What of a town's life is seen from a spot, whichever way one looks: every seat and door within
 * the far distance, and not nearer than the least, whose sight line nothing at eye height crosses,
 * each with what it counts for at its distance (a seat for `seatWeight` doors; whole up to the near
 * distance, then less). One at the viewer's feet counts nothing, so no view is taken for standing
 * behind a bench.
 */
function lifeSeenFrom(
  from: readonly [number, number], life: TownLife, rings: readonly SightBlocker[], rule: LifeViewRule,
): SeenLife[] {
  const seen: SeenLife[] = [];
  for (const [points, worth] of [[life.seats, rule.seatWeight], [life.doors, 1]] as const) {
    for (const point of points) {
      const distance = Math.hypot(point[0] - from[0], point[1] - from[1]);
      if (distance > rule.farMm || distance < rule.leastMm || distance === 0) continue;
      const toward = [(point[0] - from[0]) / distance, (point[1] - from[1]) / distance] as const;
      if (openDistance(from, toward, rings, distance) < distance - rule.sightMarginMm) continue;
      const fade = distance <= rule.nearMm ? 1 : (rule.farMm - distance) / (rule.farMm - rule.nearMm);
      seen.push({ toward, weight: worth * fade });
    }
  }
  return seen;
}

/**
 * How alive a view is: what the seats and doors seen from its spot count for, summed over those
 * inside the fan about where it looks. One near door is 1.
 */
export function viewLife(
  from: readonly [number, number], toward: readonly [number, number], life: TownLife, rings: readonly SightBlocker[],
  rule: OpenViewRule & { readonly life: LifeViewRule },
): number {
  return lifeInFan(lifeSeenFrom(from, life, rings, rule.life), toward, rule.fanHalf);
}

/** What the life seen from a spot counts for inside the fan `fanHalf` either side of `toward`. */
function lifeInFan(seen: readonly SeenLife[], toward: readonly [number, number], fanHalf: number): number {
  const inFan = Math.cos(fanHalf);
  return seen.reduce((sum, one) => (one.toward[0] * toward[0] + one.toward[1] * toward[1] >= inFan ? sum + one.weight : sum), 0);
}

/** How far a point is from the nearest part of a ring's edge. */
function distanceToRing(point: readonly [number, number], ring: SightBlocker): number {
  let nearest = Number.POSITIVE_INFINITY;
  for (let i = 0; i < ring.length; i += 1) {
    const a = ring[i]!;
    const b = ring[(i + 1) % ring.length]!;
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const span = dx * dx + dy * dy;
    const foot = span === 0 ? 0 : Math.min(1, Math.max(0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / span));
    nearest = Math.min(nearest, Math.hypot(a[0] + dx * foot - point[0], a[1] + dy * foot - point[1]));
  }
  return nearest;
}

/**
 * The first view of a town with nothing placed in it: from the served spot or a few steps from it
 * (back from the kerb, off the line people walk, and along the footway), looking along the street
 * at a slant one way or the other. It never looks straight across at the wall opposite.
 *
 * Under a rule that states how life is judged (version 2 of the catalog and later), the view taken
 * has nothing at eye height dead ahead (across its middle third, for a seafront view of version 5)
 * nearer than the rule's floor and, where the rule states a
 * least distance (version 3), no seat nearer than that inside its fan (where every view has one or
 * the other, the one with the most room before it, each against what the rule asks); of those the
 * most of the town's life in view; of equally alive views the most open, and of equally open ones
 * the nearest the served spot, the first found. Only what the caller hands of the town's own
 * records is read: `rings` holds no parked vehicle.
 *
 * Under a rule that does not (version 1), whichever spot and way is most open, a view with something
 * in its face only when every view has one. Standing off the walking line is preferred where the
 * ground lets a person stand there; of equally open views the nearest is taken, the first found.
 */
/**
 * The seafront view a first view is, if any: where the entry names a direction to look toward and the
 * arrival faces away from it (a town by the sea arriving on its shore street's seaward footway, facing
 * across the street to the land side's fronts with the sea behind) and the rule states a seafront view
 * (version 5). It turns the seafront slant from straight across instead of the rule's slant, so the
 * view runs along the shore with the fronts on the land side and the open view on the other, and
 * keeps its middle third clear, not dead ahead alone. It takes the spot and way with the most
 * buildings' fronts in view, then the most of the town's doors; its seats do not count.
 */
function seafrontOf(
  ahead: readonly [number, number], rule: OpenViewRule, toward: readonly [number, number] | undefined,
): OpenViewRule['seafront'] {
  const length = toward === undefined ? 0 : Math.hypot(toward[0], toward[1]);
  if (toward === undefined || rule.seafront === undefined || length === 0) return undefined;
  // How far the arrival faces from straight away from the named direction, the way inland.
  const inland = Math.acos(Math.max(-1, Math.min(1, -(ahead[0] * toward[0] + ahead[1] * toward[1]) / length)));
  return inland <= rule.seafront.facingMost ? rule.seafront : undefined;
}

function openView(
  input: {
    readonly eastMm: number; readonly southMm: number;
    readonly ground: (eastMm: number, southMm: number) => boolean;
    readonly toward?: readonly [east: number, south: number];
    readonly fronts?: readonly SightBlocker[];
  },
  ahead: readonly [number, number], rings: readonly SightBlocker[], rule: OpenViewRule, life: TownLife,
): ArrivalView {
  if (rule.life !== undefined) return liveliestView(input, ahead, rings, { ...rule, life: rule.life }, life);
  const across: readonly [number, number] = [-ahead[1], ahead[0]];
  const turned = (angle: number): readonly [number, number] => [
    ahead[0] * Math.cos(angle) - ahead[1] * Math.sin(angle), ahead[0] * Math.sin(angle) + ahead[1] * Math.cos(angle),
  ];
  const slant = seafrontOf(ahead, rule, input.toward)?.slant ?? rule.slant;
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
          const toward = turned(way * slant);
          // Off the line people walk is worth a little: walkers then cross the view, not the viewer.
          const score = viewOpenness([east, south], toward, rings, rule) + (back > 0 ? rule.offLineBonus ?? FIRST_VIEW_DEFAULTS.offLineBonus : 0);
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

/**
 * How near the nearest seat stands inside the fan `fanHalf` either side of `toward`, or infinity
 * where none does: a seat that near is furniture at the viewer's feet, whatever stands beyond it.
 */
export function nearestSeatInFan(
  from: readonly [number, number], toward: readonly [number, number], fanHalf: number,
  seats: readonly (readonly [number, number])[],
): number {
  const inFan = Math.cos(fanHalf);
  let nearest = Number.POSITIVE_INFINITY;
  for (const seat of seats) {
    const distance = Math.hypot(seat[0] - from[0], seat[1] - from[1]);
    if (distance === 0 || distance >= nearest) continue;
    if (((seat[0] - from[0]) * toward[0] + (seat[1] - from[1]) * toward[1]) / distance >= inFan) nearest = distance;
  }
  return nearest;
}

/** One spot and way the first view could take, with what it is judged by. */
interface JudgedView {
  readonly view: ArrivalView;
  /**
   * How much room the view has before it, as a share of what the rule asks: the nearest thing at
   * eye height dead ahead against the centre floor, and the nearest seat in the fan against the
   * least distance, whichever is the less. Clear at 1 or more.
   */
  readonly room: number;
  readonly clear: boolean;
  /**
   * How many buildings show their fronts in a seafront view (`frontsInView`), up to the least it asks
   * for; 0 for any other view.
   */
  readonly fronts: number;
  readonly life: number;
  readonly open: number;
  readonly moved: number;
}

/** The first view under a rule that judges by the town's life: see `openView`. */
function liveliestView(
  input: {
    readonly eastMm: number; readonly southMm: number;
    readonly ground: (eastMm: number, southMm: number) => boolean;
    readonly toward?: readonly [east: number, south: number];
    readonly fronts?: readonly SightBlocker[];
  },
  ahead: readonly [number, number], every: readonly SightBlocker[],
  rule: OpenViewRule & { readonly life: LifeViewRule }, life: TownLife,
): ArrivalView {
  const across: readonly [number, number] = [-ahead[1], ahead[0]];
  const turned = (angle: number): readonly [number, number] => [
    ahead[0] * Math.cos(angle) - ahead[1] * Math.sin(angle), ahead[0] * Math.sin(angle) + ahead[1] * Math.cos(angle),
  ];
  // A seafront view turns its own slant and keeps its middle third clear, where dead ahead is tested,
  // and takes the spot and way with the most buildings' fronts across the street in view, up to the
  // least it asks for and stepping as far along the footway as it says, then the most of the town's
  // doors, each a front's, and not its seats: a bench on the promenade is not the town.
  const seafront = seafrontOf(ahead, rule, input.toward);
  const fronts = input.fronts ?? [];
  const slant = seafront?.slant ?? rule.slant;
  const centreHalf = seafront?.centreHalf ?? rule.life.centreHalf;
  const alongMaximumMm = seafront?.alongMaximumMm ?? rule.alongMaximumMm;
  const judgedLife: TownLife = seafront === undefined ? life : { seats: [], doors: life.doors };
  // Only what stands within sight of any spot the view may take is tested, so a larger town costs no more.
  const within = Math.max(rule.reachMm, rule.life.farMm) + Math.hypot(alongMaximumMm, rule.backMaximumMm);
  const rings = every.filter((ring) => distanceToRing([input.eastMm, input.southMm], ring) <= within);
  const better = (a: JudgedView, b: JudgedView): boolean => {
    if (a.clear !== b.clear) return a.clear;
    if (!a.clear && a.room !== b.room) return a.room > b.room;
    if (a.fronts !== b.fronts) return a.fronts > b.fronts;
    if (Math.abs(a.life - b.life) > rule.life.tie) return a.life > b.life;
    if (Math.abs(a.open - b.open) > rule.tie) return a.open > b.open;
    return a.moved < b.moved;
  };
  let best: JudgedView | null = null;
  const backSteps = rule.backStepMm > 0 ? Math.floor(rule.backMaximumMm / rule.backStepMm) : 0;
  const alongSteps = rule.alongStepMm > 0 ? Math.floor(alongMaximumMm / rule.alongStepMm) : 0;
  for (let back = 0; back <= backSteps; back += 1) {
    for (let step = 0; step <= alongSteps; step += 1) {
      for (const side of step === 0 ? [1] : [1, -1]) {
        const along = side * step * rule.alongStepMm;
        const behind = back * rule.backStepMm;
        const spot = [
          input.eastMm + across[0] * along - ahead[0] * behind, input.southMm + across[1] * along - ahead[1] * behind,
        ] as const;
        if ((back > 0 || step > 0) && !input.ground(spot[0], spot[1])) continue;
        const seen = lifeSeenFrom(spot, judgedLife, rings, rule.life);
        for (const way of [1, -1]) {
          const toward = turned(way * slant);
          const centre = nearestInWedge(spot, toward, centreHalf, rings) / rule.life.centreFloorMm;
          // A seat nearer than the least distance does not count as life, and a view that has one
          // inside its fan stands behind a bench: it is passed over as one with a post dead ahead is.
          const feet = rule.life.leastMm > 0
            ? nearestSeatInFan(spot, toward, rule.fanHalf, life.seats) / rule.life.leastMm : Number.POSITIVE_INFINITY;
          const room = Math.min(centre, feet);
          const judged: JudgedView = {
            view: { eastMm: spot[0], southMm: spot[1], yaw: Math.atan2(-toward[0], -toward[1]), moved: back > 0 || step > 0 },
            room,
            clear: room >= 1,
            fronts: seafront === undefined ? 0 : Math.min(
              seafront.frontsLeast,
              frontsInView(
                spot, toward, fronts, rings, across, seafront.frontHalf, seafront.frontStep, rule.life.farMm, seafront.frontLinesLeast,
              ),
            ),
            life: lifeInFan(seen, toward, rule.fanHalf),
            // Off the line people walk is worth a little: walkers then cross the view, not the viewer.
            open: viewOpenness(spot, toward, rings, rule) + (back > 0 ? rule.offLineBonus ?? FIRST_VIEW_DEFAULTS.offLineBonus : 0),
            moved: Math.hypot(along, behind),
          };
          if (best === null || better(judged, best)) best = judged;
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
   * The outlines of the town's buildings, among `blockers`, whose fronts a seafront view counts. Absent,
   * none: a seafront view is then chosen by the town's doors.
   */
  readonly fronts?: readonly SightBlocker[];
  /**
   * How to choose the view where nothing is placed. Absent, such a town is looked at the way its
   * entry says, straight across the road, as before.
   */
  readonly open?: OpenViewRule;
  /** The town's seats and doors, which a rule that judges by life chooses that view by. Absent, none. */
  readonly life?: TownLife;
  /**
   * A direction the town's first view looks toward, a plan vector east then south (the sea of a town
   * on land that holds one): with nothing placed and the arrival facing it, a rule of version 5 looks
   * along the shore at its seafront slant.
   */
  readonly toward?: readonly [east: number, south: number];
}): ArrivalView {
  const { eastMm, southMm, facing } = input;
  const length = Math.hypot(facing[0], facing[1]) || 1;
  const ahead: [number, number] = [facing[0] / length, facing[1] / length];
  /** The town's own first view, chosen as for a town with nothing placed in it. */
  const townView = (rule: OpenViewRule): ArrivalView => {
    // A rule that judges by life reads the town's own records alone: what is parked is the traffic's
    // state at the second of opening, read with a limit, and would make two openings differ.
    const clearance = (rule.placed ?? FIRST_VIEW_DEFAULTS.placed).parkedClearanceMm;
    const rings = rule.life === undefined
      ? [...(input.blockers ?? []), ...input.parked.map((one) => footprintRing(one, clearance))] : input.blockers ?? [];
    return openView(input, ahead, rings, rule, input.life ?? { seats: [], doors: [] });
  };
  if (input.targets.length === 0 && input.open !== undefined) return townView(input.open);
  // How the view steps to a spot that sees the placed things: the rule's figures, else the defaults.
  const placed = input.open?.placed ?? FIRST_VIEW_DEFAULTS.placed;
  const aim: [number, number] = input.targets.length === 0
    ? [eastMm + ahead[0] * FIRST_VIEW_DEFAULTS.aimAheadMm, southMm + ahead[1] * FIRST_VIEW_DEFAULTS.aimAheadMm]
    : [
      input.targets.reduce((sum, [east]) => sum + east, 0) / input.targets.length,
      input.targets.reduce((sum, [, south]) => sum + south, 0) / input.targets.length,
    ];
  const blocking = (east: number, south: number): PlanFootprint[] =>
    input.parked.filter((footprint) => crosses([east, south], aim, footprint, placed.parkedClearanceMm));
  /**
   * Whether a spot sees the placed things by the town's own records: nothing else at eye height stands
   * between them and, where the rule states how near something may stand dead ahead (version 2 of the
   * catalog and later), nothing stands there nearer than that, so the view is never of a wall a few
   * steps away with the things against it or inside it. With nothing placed there is no such sight
   * line: the view is the way the entry says, past parked cars alone.
   */
  const sees = (east: number, south: number): boolean => {
    const reach = Math.hypot(aim[0] - east, aim[1] - south);
    // A spot on the placed things, or nearer them than the rule lets a seat or a door count as life in
    // view, has them at its feet: it is no view of them, and on them it would face nowhere.
    if (input.targets.length > 0 && (reach === 0 || reach < (input.open?.life?.leastMm ?? 0))) return false;
    const rings = input.targets.length === 0 ? [] : input.blockers ?? [];
    if (rings.length === 0) return true;
    if (reach === 0) return true;
    const toward: [number, number] = [(aim[0] - east) / reach, (aim[1] - south) / reach];
    if (openDistance([east, south], toward, rings, reach) < reach) return false;
    const life = input.open?.life;
    return life === undefined || nearestInWedge([east, south], toward, life.centreHalf, rings) >= life.centreFloorMm;
  };
  const clear = (east: number, south: number): boolean => blocking(east, south).length === 0 && sees(east, south);
  /** How far the nearest car in the way stands from a spot (its middle); infinite with none. */
  const nearestBlock = (east: number, south: number): number =>
    Math.min(...blocking(east, south).map((footprint) => Math.hypot(footprint.eastMm - east, footprint.southMm - south)));
  const served: ArrivalView = { eastMm, southMm, yaw: yawToward(eastMm, southMm, aim[0], aim[1]), moved: false };
  if (clear(eastMm, southMm)) return served;
  const moved = ([east, south]: readonly [number, number, number]): ArrivalView =>
    ({ eastMm: east, southMm: south, yaw: yawToward(east, south, aim[0], aim[1]), moved: true });
  // Along the footway (across the way a person faces) first, nearest first, then back from the kerb.
  const across: [number, number] = [-ahead[1], ahead[0]];
  const candidates: [number, number, number][] = [];
  for (let back = 0; back <= placed.stepsBack; back += 1) {
    for (let step = 1; step <= placed.stepsAlong; step += 1) {
      for (const side of [1, -1]) {
        const along = side * step * placed.stepMm;
        const behind = back * placed.stepMm;
        candidates.push([
          eastMm + across[0] * along - ahead[0] * behind,
          southMm + across[1] * along - ahead[1] * behind,
          Math.hypot(along, behind),
        ]);
      }
    }
    if (back > 0) candidates.push([eastMm - ahead[0] * back * placed.stepMm, southMm - ahead[1] * back * placed.stepMm, back * placed.stepMm]);
  }
  candidates.sort((a, b) => a[2] - b[2]);
  const standing = candidates.filter(([east, south]) => input.ground(east, south));
  for (const spot of standing) {
    if (clear(spot[0], spot[1])) return moved(spot);
  }
  const seeing = standing.filter(([east, south]) => sees(east, south));
  if (seeing.length === 0 && !sees(eastMm, southMm)) {
    // No spot near the footway sees the placed things at all: they stand inside or close against what
    // the town's records stand at eye height. Out toward and across the street, nearest first, to a
    // spot that sees them past every parked car; where none does, the town's own first view, so the
    // first look is always at the town and never at a wall.
    const out: [number, number, number][] = [];
    for (let outward = placed.stepMm; outward <= placed.outReachMm; outward += placed.stepMm) {
      for (let step = 0; step <= placed.stepsAlong; step += 1) {
        for (const side of step === 0 ? [1] : [1, -1]) {
          const along = side * step * placed.stepMm;
          out.push([eastMm + across[0] * along + ahead[0] * outward, southMm + across[1] * along + ahead[1] * outward, Math.hypot(along, outward)]);
        }
      }
    }
    out.sort((a, b) => a[2] - b[2]);
    const spot = out.find(([east, south]) => input.ground(east, south) && clear(east, south));
    if (spot !== undefined) return moved(spot);
    if (input.open !== undefined) return townView(input.open);
    return served;
  }
  // Every spot near that sees them has a parked car in the way: the one whose nearest car in the way
  // is farthest (the served one included where it sees them), so that car stands smallest in the view.
  let best: [number, number, number] | null = sees(eastMm, southMm) ? [eastMm, southMm, nearestBlock(eastMm, southMm)] : null;
  for (const [east, south] of seeing) {
    const distance = nearestBlock(east, south);
    if (best === null || distance > best[2] + placed.parkedFartherMm) best = [east, south, distance];
  }
  if (best === null || (best[0] === eastMm && best[1] === southMm)) return served;
  return moved(best);
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
