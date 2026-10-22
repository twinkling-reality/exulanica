/**
 * What hides a being: one answer to "can the eye see this point", from the world's own plan.
 *
 * A town already states what stands at a standing person's eye height, as closed plan rings: every
 * building's base and each trunk and post that crosses that height (`sightBlockersOfTown`, read
 * once to choose the first view). The same rings answer for the mark and name over a being, for a
 * line of speech and for a click: a sight line is followed in plan until a ring's edge crosses it,
 * and one from a point on an edge (a walking line can lie on a frontage) is stopped there when it
 * runs into that ring.
 *
 * A made place states its plan in its drawing: every box it draws that stands across eye height (a
 * wall piece, a post, a tall thing), turned as it is drawn (`siteSightRings`). Its walls are pieces
 * with a gap where each door is, so a door there is open to the eye, and a wall of glass hides nobody
 * (the surface material catalog says what the eye sees through).
 *
 * It is the plan's answer and no more. What does not cross eye height in the plan hides nobody: a
 * parked vehicle, a bench, a bin, a canopy, another person. A doorway is not an opening in a town
 * building's ring. It is right for a viewer on foot, which is the only viewer there is. Nothing is
 * read back from the picture.
 */
import type { SightBlocker } from './arrival-view.js';

export interface Sight {
  /**
   * Whether a point of the world is seen from an eye: no ring's edge crosses the plan line between
   * them, short of the last stretch before the point (what stands that near it is the thing the
   * point is at: a door's own wall, the post a person leans on). Metres, x east and z south.
   */
  sees(eye: { readonly x: number; readonly z: number }, point: { readonly x: number; readonly z: number }): boolean;
  /**
   * How far a ray runs before something of the plan stands in it, in metres along the ray, or
   * infinity where nothing does (or the ray looks straight up or down). Metres, x east, y up, z south.
   */
  reach(origin: readonly [number, number, number], direction: readonly [number, number, number]): number;
  /**
   * How far a ray runs before a wall stands in it, a wall the eye sees through (glass) included: what
   * a body standing there faces and walks into (`openFacing`). Absent where the plan has no wall the
   * eye sees through, so `reach` answers it.
   */
  wallReach?(origin: readonly [number, number, number], direction: readonly [number, number, number]): number;
}

/**
 * What a made place puts in a sight line at a height: the plan rectangle, millimetres east and
 * south, of every box its drawing draws whose bottom is at or below `heightMm` and whose top is at
 * or above it, but a box whose look role the eye sees through (`seeThrough`, glass by the surface
 * material catalog), which hides nobody behind it. A slot's position is its base's centre in site millimetres (x east, y north), its
 * box is its width along its front, its depth and its height, and it is turned by quarter turns;
 * what is drawn as a plane, a ridge or nothing (ground, a roof, a door, a structure's own outline)
 * is no box and is left out. No family or kind of slot is named here. On land, a box's bottom is
 * read above the land under its base's centre (`groundMm`, millimetres under a site point), the
 * height a person's eye stands above the land they stand on.
 */
export function siteSightRings(
  drawing: { readonly slots: readonly {
    readonly primitive: string; readonly lookRole?: string; readonly positionMm: readonly [number, number, number];
    readonly boxMm: readonly [number, number, number]; readonly yawQuarterTurns: number;
  }[] },
  heightMm: number,
  groundMm?: (eastMm: number, northMm: number) => number,
  seeThrough?: (lookRole: string) => boolean,
): SightBlocker[] {
  const rings: SightBlocker[] = [];
  for (const slot of drawing.slots) {
    const [x, y, stated] = slot.positionMm;
    const base = groundMm === undefined ? stated : stated - groundMm(x, y);
    const [width, depth, height] = slot.boxMm;
    if (slot.primitive !== 'box' || base > heightMm || base + height < heightMm) continue;
    if (slot.lookRole !== undefined && seeThrough?.(slot.lookRole) === true) continue;
    // A quarter turn lays the width along north and south.
    const turned = slot.yawQuarterTurns % 2 !== 0;
    const east = (turned ? depth : width) / 2, north = (turned ? width : depth) / 2;
    rings.push([[x - east, -(y + north)], [x + east, -(y + north)], [x + east, -(y - north)], [x - east, -(y - north)]]);
  }
  return rings;
}

/** A made part a ray meets first: the part it belongs to, and how far along the ray, in metres. */
export interface SlotPick { readonly identity: string; readonly distance: number }

/** How thick a plane (a pond, a field) is to a ray, in millimetres: a ray along the ground still meets it. */
const PLANE_THICKNESS_MM = 100;

/**
 * The made part a ray meets first among the drawing's slots that `pickable` admits: the nearest box
 * or plane it enters, named by the part it belongs to (a building's own pieces name it by
 * `structure`), or null when it meets none or when a box nobody may change stands in front (a
 * zone's wall hides the part behind it; a plane nobody may change, the ground or a path, hides
 * nothing, and nor does a box the ray starts inside, as a canopy over the person does). The ray is in the frame the workspace's rays are in
 * (metres, x east, y up, z south, from the site's corner). A slot stands on its base's centre (site
 * millimetres, x east, y north, z up) with its height above that, turned by quarter turns; a plane
 * is a thin slab at its base. A slot that follows the land is read at its stated base, the land's
 * height at its centre, which is close enough to point at it.
 */
export function pickSiteSlot(
  drawing: { readonly slots: readonly {
    readonly identity: string; readonly structure?: string; readonly primitive: string;
    readonly positionMm: readonly [number, number, number]; readonly boxMm: readonly [number, number, number];
    readonly yawQuarterTurns: number;
  }[] },
  origin: readonly [number, number, number],
  direction: readonly [number, number, number],
  pickable: (identity: string) => boolean,
): SlotPick | null {
  let best: SlotPick | null = null;
  let hidden = Number.POSITIVE_INFINITY;
  for (const slot of drawing.slots) {
    if (slot.primitive !== 'box' && slot.primitive !== 'plane') continue;
    const identity = slot.structure ?? slot.identity;
    const mine = pickable(identity);
    if (!mine && slot.primitive !== 'box') continue;
    const [x, y, z] = slot.positionMm;
    const [width, depth, height] = slot.boxMm;
    // A quarter turn lays the width along north and south.
    const turned = slot.yawQuarterTurns % 2 !== 0;
    const east = (turned ? depth : width) / 2, north = (turned ? width : depth) / 2;
    const [bottom, top] = slot.primitive === 'plane' ? [z - PLANE_THICKNESS_MM / 2, z + PLANE_THICKNESS_MM / 2] : [z, z + height];
    const min = [(x - east) / 1000, bottom / 1000, -(y + north) / 1000] as const;
    const max = [(x + east) / 1000, top / 1000, -(y - north) / 1000] as const;
    if (!mine && origin.every((v, axis) => v >= min[axis]! && v <= max[axis]!)) continue;
    const distance = slabEntry(origin, direction, min, max);
    if (distance === null) continue;
    if (!mine) hidden = Math.min(hidden, distance);
    else if (best === null || distance < best.distance) best = { identity, distance };
  }
  return best !== null && best.distance <= hidden ? best : null;
}

/** Where a ray enters an axis-aligned box (metres along the ray, 0 when it starts inside), or null. */
function slabEntry(
  origin: readonly [number, number, number], direction: readonly [number, number, number],
  min: readonly [number, number, number], max: readonly [number, number, number],
): number | null {
  let near = 0, far = Infinity;
  for (let axis = 0; axis < 3; axis += 1) {
    const from = origin[axis]!, along = direction[axis]!, low = min[axis]!, high = max[axis]!;
    if (Math.abs(along) < 1e-12) {
      if (from < low || from > high) return null;
      continue;
    }
    let enter = (low - from) / along, leave = (high - from) / along;
    if (enter > leave) [enter, leave] = [leave, enter];
    near = Math.max(near, enter); far = Math.min(far, leave);
    if (near > far) return null;
  }
  return near;
}

/**
 * Hold what hides a being on the session for the world about to be mounted: none from now, and the
 * world's own once it states its plan. What stands within `marginMm` of a point is the thing the
 * point is at (`planSight`).
 */
export function holdSight(
  session: { worldSight: Sight | null }, marginMm: number,
): (blockers: readonly SightBlocker[], seenThrough?: readonly SightBlocker[]) => void {
  session.worldSight = null;
  return (blockers, seenThrough = []) => {
    session.worldSight = planSight(blockers, marginMm, seenThrough);
  };
}

/**
 * The side of the squares the edges are sorted into, so a sight line is tried against the edges
 * near it and not every edge of the town. Not a bound: any size gives the same answers, and this
 * one is a little over a building's front.
 */
const CELL_MM = 16_000;
/** How far a click's ray is followed in plan: past where anyone is drawn large enough to click. */
const REACH_MM = 2_000_000;
/** How near an edge a point is on it, in millimetres: well under anything a plan states. */
const ON_EDGE_MM = 1;

/**
 * The sight a plan of rings gives. `marginMm` is how near its end a sight line may be crossed and
 * the point still be seen (the town first-view catalog's `sight_margin_mm`, the same fact there).
 * `seenThrough` are walls the eye sees through (glass): they hide nobody, and stand only in what a
 * body faces (`wallReach`).
 */
export function planSight(rings: readonly SightBlocker[], marginMm: number, seenThrough: readonly SightBlocker[] = []): Sight {
  const sight = ringSight(rings, marginMm);
  if (seenThrough.length === 0) return sight;
  const walls = ringSight([...rings, ...seenThrough], marginMm);
  return { sees: sight.sees, reach: sight.reach, wallReach: walls.reach };
}

/** The sight every ring in a plan hides by. */
function ringSight(rings: readonly SightBlocker[], marginMm: number): Sight {
  // Every ring edge, five numbers each (ax, ay, bx, by, and the sign of its ring's turning, which
  // says which side of it the ring's inside is), and the squares each lies across.
  const edges: number[] = [];
  const cells = new Map<number, number[]>();
  const key = (cx: number, cy: number): number => cx * 1_048_576 + cy;
  for (const ring of rings) {
    let turning = 0;
    for (let i = 0; i < ring.length; i += 1) turning += ring[i]![0] * ring[(i + 1) % ring.length]![1] - ring[(i + 1) % ring.length]![0] * ring[i]![1];
    for (let i = 0; i < ring.length; i += 1) {
      const a = ring[i]!;
      const b = ring[(i + 1) % ring.length]!;
      if (![a[0], a[1], b[0], b[1]].every(Number.isFinite) || (a[0] === b[0] && a[1] === b[1])) continue;
      const index = edges.length / 5;
      edges.push(a[0], a[1], b[0], b[1], Math.sign(turning));
      const x0 = Math.floor(Math.min(a[0], b[0]) / CELL_MM), x1 = Math.floor(Math.max(a[0], b[0]) / CELL_MM);
      const y0 = Math.floor(Math.min(a[1], b[1]) / CELL_MM), y1 = Math.floor(Math.max(a[1], b[1]) / CELL_MM);
      for (let cx = x0; cx <= x1; cx += 1) {
        for (let cy = y0; cy <= y1; cy += 1) {
          const held = cells.get(key(cx, cy));
          if (held === undefined) cells.set(key(cx, cy), [index]);
          else held.push(index);
        }
      }
    }
  }

  /** How far along the unit direction a line from a plan point runs before an edge, at most `reach`. */
  const open = (fx: number, fy: number, tx: number, ty: number, reach: number): number => {
    let nearest = reach;
    let cx = Math.floor(fx / CELL_MM), cy = Math.floor(fy / CELL_MM);
    const stepX = tx > 0 ? 1 : -1, stepY = ty > 0 ? 1 : -1;
    // How far along the line the next square begins, each way, and how far apart squares are along it.
    const deltaX = tx === 0 ? Number.POSITIVE_INFINITY : CELL_MM / Math.abs(tx);
    const deltaY = ty === 0 ? Number.POSITIVE_INFINITY : CELL_MM / Math.abs(ty);
    let nextX = tx === 0 ? Number.POSITIVE_INFINITY : ((tx > 0 ? (cx + 1) * CELL_MM - fx : fx - cx * CELL_MM)) / Math.abs(tx);
    let nextY = ty === 0 ? Number.POSITIVE_INFINITY : ((ty > 0 ? (cy + 1) * CELL_MM - fy : fy - cy * CELL_MM)) / Math.abs(ty);
    let entered = 0;
    // An edge found in a square may lie in a later one too: the nearest is kept, and the walk ends
    // once the squares still ahead begin beyond it.
    while (entered <= nearest) {
      const held = cells.get(key(cx, cy));
      if (held !== undefined) {
        for (const index of held) {
          const ax = edges[index * 5]!, ay = edges[index * 5 + 1]!;
          const ex = edges[index * 5 + 2]! - ax, ey = edges[index * 5 + 3]! - ay;
          const across = tx * ey - ty * ex;
          if (Math.abs(across) < 1e-9) continue;
          const t = ((ax - fx) * ey - (ay - fy) * ex) / across;
          const u = ((ax - fx) * ty - (ay - fy) * tx) / across;
          if (u < 0 || u > 1) continue;
          // A line from a point on an edge (someone standing on a building's line) is stopped there
          // when it runs into the ring, and not when it runs out of it.
          if (Math.abs(t) <= ON_EDGE_MM) {
            if (across * edges[index * 5 + 4]! < 0) nearest = 0;
          } else if (t > 0 && t < nearest) nearest = t;
        }
      }
      if (nextX < nextY) {
        entered = nextX;
        nextX += deltaX;
        cx += stepX;
      } else {
        entered = nextY;
        nextY += deltaY;
        cy += stepY;
      }
    }
    return nearest;
  };

  return {
    sees(eye, point) {
      const dx = (point.x - eye.x) * 1000, dy = (point.z - eye.z) * 1000;
      const length = Math.hypot(dx, dy);
      const reach = length - marginMm;
      if (!(reach > 0)) return true;
      return open(eye.x * 1000, eye.z * 1000, dx / length, dy / length, reach) >= reach;
    },
    reach(origin, direction) {
      const whole = Math.hypot(direction[0], direction[1], direction[2]);
      const flat = Math.hypot(direction[0], direction[2]);
      if (!(whole > 0) || !(flat / whole > 1e-6)) return Number.POSITIVE_INFINITY;
      const met = open(origin[0] * 1000, origin[2] * 1000, direction[0] / flat, direction[2] / flat, REACH_MM);
      // A plan distance comes back to the ray's own by how far the ray leans from the plan.
      return met >= REACH_MM ? Number.POSITIVE_INFINITY : met / 1000 * (whole / flat);
    },
  };
}

/** How a person standing still is turned when nothing says which way they face (`openFacing`). */
export interface StandingFacingRule {
  /**
   * How far the eye must run ahead before something of the plan stands in it: a wall nearer reads as
   * standing nose to it (a town's footway line can lie 0.4 m off a shopfront), and a footway with
   * its kerb is about this wide, so a way across it to the street is open.
   */
  readonly openMm: number;
  /** How many ways, evenly apart, are tried: eight is along and across a street and the slants between. */
  readonly ways: number;
}

export const STANDING_FACING_DEFAULTS: StandingFacingRule = Object.freeze({ openMm: 3_000, ways: 8 });

/**
 * The way a person standing at a world point faces when nothing says (the crowd has not seen them
 * walk and nobody placed them facing a way): of the rule's ways, evenly apart and starting from the
 * one `key` draws so that neighbours face differently, the first whose sight line runs at least the
 * rule's distance before the plan stands in it; where none does, the most open, the first of equals.
 * Someone who stopped facing `preferred`, the way they walked, keeps it while it is open, and else
 * turns to the open way nearest it (of equals, the first the key draws).
 * A crowd facing: radians, 0 north, forward (-sin, -cos) along x east and z south, in metres.
 */
export function openFacing(
  sight: Sight, at: { readonly x: number; readonly z: number }, key: string, rule: StandingFacingRule = STANDING_FACING_DEFAULTS,
  preferred: number | null = null,
): number {
  // A wall the eye sees through is still a wall to stand facing.
  const openAlong = (facing: number): number => (sight.wallReach ?? sight.reach)([at.x, 0, at.z], [-Math.sin(facing), 0, -Math.cos(facing)]) * 1000;
  if (preferred !== null && openAlong(preferred) >= rule.openMm) return preferred;
  // FNV-1a over the key: the same person starts from the same way on every load.
  let drawn = 0x811c9dc5;
  for (let i = 0; i < key.length; i += 1) drawn = Math.imul(drawn ^ key.charCodeAt(i), 0x01000193) >>> 0;
  let most = 0, mostOpen = -1, nearest: number | null = null, nearestTurn = Number.POSITIVE_INFINITY;
  for (let step = 0; step < rule.ways; step += 1) {
    const turn = (((drawn + step) % rule.ways) * 2 * Math.PI) / rule.ways;
    const facing = Math.atan2(Math.sin(turn), Math.cos(turn));
    const open = openAlong(facing);
    if (open >= rule.openMm) {
      if (preferred === null) return facing;
      // How far they would turn from the way they walked, either way round.
      const away = Math.abs(Math.atan2(Math.sin(facing - preferred), Math.cos(facing - preferred)));
      if (away < nearestTurn - 1e-9) [nearest, nearestTurn] = [facing, away];
    }
    if (open > mostOpen) [most, mostOpen] = [facing, open];
  }
  return nearest ?? most;
}
