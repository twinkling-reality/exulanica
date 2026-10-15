import type { LandWater, StylePackCover } from '@exulanica/atlas-core';

/**
 * What grows on a made place's grounds: the plant pieces a look's `cover` names for a surface look
 * role, scattered over each slot of that role, the same every time for the same seed and slot.
 *
 * A piece grows only where its slot is the top of what is drawn at its point: nowhere another slot
 * stands on it (a building, a seat, a tree's slot) or another plane's surface lies above its own there
 * (a path laid over a lawn, a pond's water over the floor of its basin), and on land nowhere a body of
 * the land's water stands above the ground. Heights are compared at the piece's own point, so a lawn
 * that rises out of a basin grows to the water's edge. On a draped slot it stands on the land under its
 * own point.
 *
 * PRESENTATION ONLY. Cover is drawn on a ground; it is not a part of the world, is never walked,
 * picked or listed, and hides nobody. A site grows at most `COVER_PLACEMENTS_MAX` pieces: past it the
 * slots met first keep theirs and the rest grow none, so a dense rule on a wide ground cannot bring a
 * page to its knees.
 */

/** The most cover pieces one site grows: a guard on the page's work, not a look's choice. */
export const COVER_PLACEMENTS_MAX = 40_000;

/** A slot as the scatter reads it: its identity (the seed's second half) and its rectangle in plan. */
export interface CoverSlot {
  readonly identity: string;
  readonly lookRole: string;
  readonly positionMm: readonly number[];
  readonly boxMm: readonly number[];
  readonly yawQuarterTurns: number;
  /** The engine's primitive: a plane is a ground a higher plane may lie over; anything else stands on it. */
  readonly primitive?: string;
  /** A slot that follows the land, whose cover stands on the land under each piece. */
  readonly drape?: true;
}

/** The land under a site, where it stands on land: its height at a site point in millimetres, and its water. */
export interface CoverLand {
  readonly groundMm: (eastMm: number, northMm: number) => number;
  readonly waters: readonly LandWater[];
}

/** Whether a body of the land's water stands above the ground at a site point. */
function wetAt(land: CoverLand, eastMm: number, northMm: number): boolean {
  const ground = land.groundMm(eastMm, northMm);
  return land.waters.some((body) => ground < body.levelMm && (
    body.kind === 'sea'
    || (body.kind === 'lake' && Math.hypot(eastMm - body.centreMm[0], northMm - body.centreMm[1]) <= body.radiusMm)
    || (body.kind === 'pond' && eastMm >= body.rectMm[0] && eastMm <= body.rectMm[2] && northMm >= body.rectMm[1] && northMm <= body.rectMm[3])));
}

/** One piece grown: where it stands and the height of its foot, renderer metres. */
export interface GrownPoint extends CoverPoint {
  readonly upM: number;
}

/** A site's cover: its pieces, how many slots grow any, and how many pieces the guard left out. */
export interface GrownCover {
  readonly points: readonly GrownPoint[];
  readonly slots: number;
  readonly leftOut: number;
}

/**
 * One piece to grow: which, where in plan (metres east and north), its turn about up and its scale,
 * and a draw in [0, 1) that chooses among the piece's variants.
 */
export interface CoverPoint {
  readonly piece: string;
  readonly eastM: number;
  readonly northM: number;
  readonly yaw: number;
  readonly scale: number;
  readonly pick: number;
}

/**
 * The rule for a slot: its own look role's, else the rule of the role it is drawn in (`drawnAs`: the
 * pack's surface its leaf resolved to, its family's `default` among them, or the catalog material's
 * role), else none. A slot drawn in a surface the pack states for its own leaf takes its own rule alone.
 */
export function coverRuleOf(cover: Readonly<Record<string, StylePackCover>>, lookRole: string, drawnAs: string | null = null): StylePackCover | null {
  return cover[lookRole] ?? (drawnAs === null ? null : cover[drawnAs] ?? null);
}

/** A 32-bit hash of the rule's seed and the slot's identity: the generator's start. */
function seedOf(seed: number, identity: string): number {
  let h = (seed ^ 0x9e3779b9) >>> 0;
  for (let i = 0; i < identity.length; i += 1) {
    h = Math.imul(h ^ identity.charCodeAt(i), 0x85ebca6b) >>> 0;
    h = (h ^ (h >>> 13)) >>> 0;
  }
  return h;
}

/** Mulberry32: small, fast and the same in every browser. */
function generator(start: number): () => number {
  let state = start >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** How many pieces `rule` grows on `slot` by its density, before anything stands on them. */
export function coverCount(slot: CoverSlot, rule: StylePackCover): number {
  return Math.max(0, Math.round((slot.boxMm[0]! / 1000) * (slot.boxMm[1]! / 1000) * rule.density_per_100m2 / 100));
}

/**
 * The pieces `rule` grows on `slot`, at most `room` of them: as many as its density gives its area,
 * each centred inside the slot's rectangle, a piece, a turn and a scale drawn from the seed.
 */
export function scatterCover(slot: CoverSlot, rule: StylePackCover, room: number): CoverPoint[] {
  const odd = slot.yawQuarterTurns % 2 !== 0;
  const widthM = (odd ? slot.boxMm[1]! : slot.boxMm[0]!) / 1000;
  const depthM = (odd ? slot.boxMm[0]! : slot.boxMm[1]!) / 1000;
  const count = Math.max(0, Math.min(room, coverCount(slot, rule)));
  const next = generator(seedOf(rule.seed, slot.identity));
  const [least, most] = rule.scale_permille;
  const points: CoverPoint[] = [];
  for (let i = 0; i < count; i += 1) {
    points.push({
      eastM: slot.positionMm[0]! / 1000 + (next() - 0.5) * widthM,
      northM: slot.positionMm[1]! / 1000 + (next() - 0.5) * depthM,
      piece: rule.pieces[Math.floor(next() * rule.pieces.length) % rule.pieces.length]!,
      yaw: next() * 2 * Math.PI,
      scale: (least + (most - least) * next()) / 1000,
      pick: next(),
    });
  }
  return points;
}

/** The matrix that stands a piece at `point`, `upM` high: turned about up and scaled, in renderer metres (east, up, south). */
export function coverMatrix(point: CoverPoint, upM: number): Float32Array {
  const c = Math.cos(point.yaw) * point.scale;
  const s = Math.sin(point.yaw) * point.scale;
  return new Float32Array([
    c, 0, -s, 0,
    0, point.scale, 0, 0,
    s, 0, c, 0,
    point.eastM, upM, -point.northM, 1,
  ]);
}

/** A slot's rectangle in plan, millimetres: west, south, east, north. */
function rectOf(slot: CoverSlot): readonly [number, number, number, number] {
  const odd = slot.yawQuarterTurns % 2 !== 0;
  const east = (odd ? slot.boxMm[1]! : slot.boxMm[0]!) / 2;
  const north = (odd ? slot.boxMm[0]! : slot.boxMm[1]!) / 2;
  const [x, y] = slot.positionMm;
  return [x! - east, y! - north, x! + east, y! + north];
}

/** The side of a cell of the grid the covering rectangles are found by, millimetres: a bound on the work, not a look. */
const GRID_MM = 4000;

/** Where and how much a site's cover grows: the land under it, which slots may grow any, and the guard. */
export interface CoverOptions {
  readonly land?: CoverLand | null;
  /** Whether a slot grows its rule's cover at all (a slot drawn as a surface); every ruled slot when absent. */
  readonly grows?: (slot: CoverSlot) => boolean;
  /** The look role a slot is drawn in, whose rule it takes when its own role has none; none when absent. */
  readonly drawnAs?: (slot: CoverSlot) => string | null;
  readonly most?: number;
}

/**
 * Grow `cover` over a site's `slots`, at most `most` pieces in all: each slot's rule's pieces, kept
 * where nothing of `slots` stands on its slot or lies above it, and where no water of the land, if
 * any, stands above the ground.
 */
export function growCover(
  slots: readonly CoverSlot[],
  cover: Readonly<Record<string, StylePackCover>>,
  { land = null, grows = () => true, drawnAs = () => null, most = COVER_PLACEMENTS_MAX }: CoverOptions = {},
): GrownCover {
  const points: GrownPoint[] = [];
  let grown = 0;
  let leftOut = 0;
  const ruled = slots.flatMap((slot) => {
    const rule = coverRuleOf(cover, slot.lookRole, drawnAs(slot));
    return rule === null || !grows(slot) ? [] : [{ slot, rule }];
  });
  if (ruled.length === 0) return { points, slots: 0, leftOut };
  // Every slot's rectangle, in the grid cells it touches.
  const rects = slots.map(rectOf);
  const grid = new Map<string, number[]>();
  rects.forEach((rect, index) => {
    for (let gx = Math.floor(rect[0] / GRID_MM); gx <= Math.floor(rect[2] / GRID_MM); gx += 1) {
      for (let gy = Math.floor(rect[1] / GRID_MM); gy <= Math.floor(rect[3] / GRID_MM); gy += 1) {
        const key = `${String(gx)}|${String(gy)}`;
        const cell = grid.get(key);
        if (cell === undefined) grid.set(key, [index]);
        else cell.push(index);
      }
    }
  });
  const indexOf = new Map(slots.map((slot, index) => [slot, index]));
  // A draped slot stands as far above the land under each point as its base stands above the land under its centre.
  const lift = slots.map((slot) => land === null || slot.drape !== true ? null : slot.positionMm[2]! - land.groundMm(slot.positionMm[0]!, slot.positionMm[1]!));
  /** The height of a slot's top at a point, millimetres. */
  const heightAt = (index: number, eastMm: number, northMm: number): number => {
    const slot = slots[index]!;
    const top = slot.primitive === 'plane' ? 0 : slot.boxMm[2]!;
    const raised = lift[index];
    return (raised === null || raised === undefined ? slot.positionMm[2]! : land!.groundMm(eastMm, northMm) + raised) + top;
  };
  /** Whether another slot stands on `own` at a point, or another plane's surface lies above its own there. */
  const covered = (own: number, eastMm: number, northMm: number, height: number): boolean => {
    for (const index of grid.get(`${String(Math.floor(eastMm / GRID_MM))}|${String(Math.floor(northMm / GRID_MM))}`) ?? []) {
      if (index === own) continue;
      const rect = rects[index]!;
      if (eastMm < rect[0] || eastMm > rect[2] || northMm < rect[1] || northMm > rect[3]) continue;
      if (slots[index]!.primitive !== 'plane' || heightAt(index, eastMm, northMm) > height) return true;
    }
    return false;
  };
  let growing = 0;
  for (const { slot, rule } of ruled) {
    const room = Math.max(0, most - grown);
    const count = coverCount(slot, rule);
    leftOut += Math.max(0, count - room);
    const scattered = scatterCover(slot, rule, room);
    const own = indexOf.get(slot)!;
    let kept = 0;
    for (const point of scattered) {
      const eastMm = point.eastM * 1000;
      const northMm = point.northM * 1000;
      const upMm = heightAt(own, eastMm, northMm);
      if (covered(own, eastMm, northMm, upMm)) continue;
      if (land !== null && wetAt(land, eastMm, northMm)) continue;
      points.push({ ...point, upM: upMm / 1000 });
      kept += 1;
    }
    grown += scattered.length;
    if (kept > 0) growing += 1;
  }
  return { points, slots: growing, leftOut };
}
