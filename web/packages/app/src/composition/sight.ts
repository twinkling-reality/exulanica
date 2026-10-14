/**
 * What hides a being: one answer to "can the eye see this point", from the world's own plan.
 *
 * A town already states what stands at a standing person's eye height, as closed plan rings: every
 * building's base and each trunk and post that crosses that height (`sightBlockersOfTown`, read
 * once to choose the first view). The same rings answer for the mark and name over a being, for a
 * line of speech and for a click: a sight line is followed in plan until a ring's edge crosses it.
 *
 * A made place states its plan in its drawing: every box it draws that stands across eye height (a
 * wall piece, a post, a tall thing), turned as it is drawn (`siteSightRings`). Its walls are pieces
 * with a gap where each door is, so a door there is open to the eye.
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
}

/**
 * What a made place puts in a sight line at a height: the plan rectangle, millimetres east and
 * south, of every box its drawing draws whose bottom is at or below `heightMm` and whose top is at
 * or above it. A slot's position is its base's centre in site millimetres (x east, y north), its
 * box is its width along its front, its depth and its height, and it is turned by quarter turns;
 * what is drawn as a plane, a ridge or nothing (ground, a roof, a door, a structure's own outline)
 * is no box and is left out. No family or kind of slot is named here. On land, a box's bottom is
 * read above the land under its base's centre (`groundMm`, millimetres under a site point), the
 * height a person's eye stands above the land they stand on.
 */
export function siteSightRings(
  drawing: { readonly slots: readonly {
    readonly primitive: string; readonly positionMm: readonly [number, number, number];
    readonly boxMm: readonly [number, number, number]; readonly yawQuarterTurns: number;
  }[] },
  heightMm: number,
  groundMm?: (eastMm: number, northMm: number) => number,
): SightBlocker[] {
  const rings: SightBlocker[] = [];
  for (const slot of drawing.slots) {
    const [x, y, stated] = slot.positionMm;
    const base = groundMm === undefined ? stated : stated - groundMm(x, y);
    const [width, depth, height] = slot.boxMm;
    if (slot.primitive !== 'box' || base > heightMm || base + height < heightMm) continue;
    // A quarter turn lays the width along north and south.
    const turned = slot.yawQuarterTurns % 2 !== 0;
    const east = (turned ? depth : width) / 2, north = (turned ? width : depth) / 2;
    rings.push([[x - east, -(y + north)], [x + east, -(y + north)], [x + east, -(y - north)], [x - east, -(y - north)]]);
  }
  return rings;
}

/**
 * Hold what hides a being on the session for the world about to be mounted: none from now, and the
 * world's own once it states its plan. What stands within `marginMm` of a point is the thing the
 * point is at (`planSight`).
 */
export function holdSight(
  session: { worldSight: Sight | null }, marginMm: number,
): (blockers: readonly SightBlocker[]) => void {
  session.worldSight = null;
  return (blockers) => {
    session.worldSight = planSight(blockers, marginMm);
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

/**
 * The sight a plan of rings gives. `marginMm` is how near its end a sight line may be crossed and
 * the point still be seen (the town first-view catalog's `sight_margin_mm`, the same fact there).
 */
export function planSight(rings: readonly SightBlocker[], marginMm: number): Sight {
  // Every ring edge, four numbers each (ax, ay, bx, by), and the squares each lies across.
  const edges: number[] = [];
  const cells = new Map<number, number[]>();
  const key = (cx: number, cy: number): number => cx * 1_048_576 + cy;
  for (const ring of rings) {
    for (let i = 0; i < ring.length; i += 1) {
      const a = ring[i]!;
      const b = ring[(i + 1) % ring.length]!;
      if (![a[0], a[1], b[0], b[1]].every(Number.isFinite) || (a[0] === b[0] && a[1] === b[1])) continue;
      const index = edges.length / 4;
      edges.push(a[0], a[1], b[0], b[1]);
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
          const ax = edges[index * 4]!, ay = edges[index * 4 + 1]!;
          const ex = edges[index * 4 + 2]! - ax, ey = edges[index * 4 + 3]! - ay;
          const across = tx * ey - ty * ex;
          if (Math.abs(across) < 1e-9) continue;
          const t = ((ax - fx) * ey - (ay - fy) * ex) / across;
          const u = ((ax - fx) * ty - (ay - fy) * tx) / across;
          if (t > 0 && u >= 0 && u <= 1 && t < nearest) nearest = t;
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
