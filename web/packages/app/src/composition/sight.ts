/**
 * What hides a being: one answer to "can the eye see this point", from the world's own plan.
 *
 * A town already states what stands at a standing person's eye height, as closed plan rings: every
 * building's base and each trunk and post that crosses that height (`sightBlockersOfTown`, read
 * once to choose the first view). The same rings answer for the mark and name over a being, for a
 * line of speech and for a click: a sight line is followed in plan until a ring's edge crosses it.
 *
 * It is the plan's answer and no more. What does not cross eye height in the plan hides nobody: a
 * parked vehicle, a bench, a bin, a canopy, another person. A doorway is not an opening in a
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
