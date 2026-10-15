import { STYLE_PACK_CLIMB_WALLS, type StylePackClimb } from '@exulanica/atlas-core';

/**
 * What climbs a made place's buildings: the plant pieces a look's `climb` names for a structure look
 * role, rooted at the foot of the faces of each building's box the rule lists, the same every time
 * for the same seed and building.
 *
 * Along each face that passes the rule's sun test, plants are chosen in turn, each reaching a height
 * drawn between the rule's least and most share of the building's height, until their widths cover
 * the rule's share of the face; they stand evenly spaced along it, each turned to face out. A plant
 * piece is authored against a wall in the plane z = 0 behind it (its leaves toward +Z), so the page
 * sets its back just proud of the face.
 *
 * PRESENTATION ONLY. A climbing plant is drawn on a wall; it is not a part of the world, is never
 * walked, picked or listed, and hides nobody. A face is the box's face: a plant on a front stands
 * before its door, which is why a rule names its walls. A site grows at most
 * `CLIMB_PLACEMENTS_MAX` plants, counting only plants that grow: past it the plants met first keep
 * their places and the rest are counted as left out. A face takes at most `CLIMB_PER_FACE_MAX`.
 */

/** The most climbing plants one site grows: a guard on the page's work, not a look's choice. */
export const CLIMB_PLACEMENTS_MAX = 4_000;

/** The most plants one face takes: a bound on a rule over a long face with narrow plants. */
export const CLIMB_PER_FACE_MAX = 64;

/** How far a plant's back stands in front of its face, metres: clear of the wall, so neither flickers through the other. */
export const CLIMB_STANDOFF_M = 0.03;

type Wall = (typeof STYLE_PACK_CLIMB_WALLS)[number];

/** A slot as the climbers read it: a building's identity, look role, base centre, front and box. */
export interface ClimbSlot {
  readonly identity: string;
  readonly lookRole: string;
  readonly family: string;
  /** Base centre, millimetres: east, north, up. */
  readonly positionMm: readonly number[];
  /** Width along the front, depth, height, millimetres. */
  readonly boxMm: readonly number[];
  readonly yawQuarterTurns: number;
}

/** One plant to grow: which, where its foot meets its face, which way it faces, how high it reaches. */
export interface ClimbPoint {
  readonly piece: string;
  /** A draw in [0, 1) that chooses among the piece's variants. */
  readonly pick: number;
  /** The face's outward direction in plan, a unit vector (east, north). */
  readonly outward: readonly [number, number];
  /** Where the middle of the plant's foot meets the face, metres: east, north, up. */
  readonly footM: readonly [number, number, number];
  readonly heightM: number;
}

/** A site's climbing plants, how many buildings grow any, and how many the guard left out. */
export interface GrownClimb {
  readonly points: readonly ClimbPoint[];
  readonly buildings: number;
  readonly leftOut: number;
}

/** A face of a building's box: which way it looks, its middle at the base in plan, its length, millimetres. */
export interface BoxFace {
  readonly outward: readonly [number, number];
  readonly centreMm: readonly [number, number];
  readonly lengthMm: number;
}

/** A slot's front in plan by its quarter turns, counterclockwise seen from above (as the site dresser's). */
const FRONTS: readonly (readonly [number, number])[] = [[0, 1], [-1, 0], [0, -1], [1, 0]];

/**
 * The four faces of a slot's box. `right` and `left` are as a viewer facing the front sees them,
 * the side a piece's +X points to; the front is the slot's front.
 */
export function boxFaces(slot: ClimbSlot): Readonly<Record<Wall, BoxFace>> {
  const [fe, fn] = FRONTS[((slot.yawQuarterTurns % 4) + 4) % 4]!;
  const [width, depth] = [slot.boxMm[0]!, slot.boxMm[1]!];
  const [x, y] = [slot.positionMm[0]!, slot.positionMm[1]!];
  // Adding zero writes a negative zero as zero, so a face reads the same however it was turned to.
  const face = ([e, n]: readonly [number, number], reach: number, lengthMm: number): BoxFace => ({
    outward: [e + 0, n + 0], centreMm: [x + e * reach + 0, y + n * reach + 0], lengthMm,
  });
  return {
    front: face([fe, fn], depth / 2, width),
    back: face([-fe, -fn], depth / 2, width),
    right: face([-fn, fe], width / 2, depth),
    left: face([fn, -fe], width / 2, depth),
  };
}

/** The direction toward the sun in plan (east, north), from its azimuth as the render look states it. */
export function towardSun(azimuthDeg: number): readonly [number, number] {
  const azimuth = (azimuthDeg * Math.PI) / 180;
  // The look's light travels along (-sin, -cos) of its azimuth in (east, south): toward it is the reverse.
  return [Math.sin(azimuth), -Math.cos(azimuth)];
}

/** The rule for a building: its own look role's, else its family's default, else none. */
export function climbRuleOf(climb: Readonly<Record<string, StylePackClimb>>, lookRole: string): StylePackClimb | null {
  return climb[lookRole] ?? climb[`${lookRole.split('.')[0]!}.default`] ?? null;
}

/** A 32-bit hash of the rule's seed and the building's identity: the generator's start. */
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

/** Where and how much a site's climbing plants grow: their pieces' sizes, the sun and the guard. */
export interface ClimbOptions {
  /** The authored size (width, depth, height, millimetres) of the variant `pick` chooses of a plant role; null when the pack has none. */
  readonly sizeOf: (piece: string, pick: number) => readonly [number, number, number] | null;
  /** The sun's azimuth the look is drawn with, degrees; a rule's sun test passes every face when none. */
  readonly sunAzimuthDeg?: number | null;
  /** The most plants grown; `CLIMB_PLACEMENTS_MAX` when absent. */
  readonly most?: number;
}

/**
 * Grow `climb` on a site's buildings (its slots of the structure family whose look role has a rule):
 * on each face the rule lists and the sun test passes, plants until their widths cover the rule's
 * share of the face, spaced evenly along it, at most `most` in all.
 */
export function growClimbers(
  slots: readonly ClimbSlot[],
  climb: Readonly<Record<string, StylePackClimb>>,
  { sizeOf, sunAzimuthDeg = null, most = CLIMB_PLACEMENTS_MAX }: ClimbOptions,
): GrownClimb {
  const points: ClimbPoint[] = [];
  let leftOut = 0;
  let buildings = 0;
  const sun = sunAzimuthDeg === null ? null : towardSun(sunAzimuthDeg);
  for (const slot of slots) {
    if (slot.family !== 'structure') continue;
    const rule = climbRuleOf(climb, slot.lookRole);
    if (rule === null) continue;
    const next = generator(seedOf(rule.seed, slot.identity));
    const faces = boxFaces(slot);
    const heightMm = slot.boxMm[2]!;
    const [least, most_] = rule.height_permille;
    let grew = 0;
    for (const wall of rule.walls) {
      const face = faces[wall];
      if (face === undefined) continue;
      if (rule.sun_within_mdeg !== undefined && sun !== null) {
        const cosine = face.outward[0] * sun[0] + face.outward[1] * sun[1];
        const angle = (Math.acos(Math.max(-1, Math.min(1, cosine))) * 180_000) / Math.PI;
        if (angle > rule.sun_within_mdeg) continue;
      }
      const wanted = (face.lengthMm * rule.share_permille) / 1000;
      const chosen: { piece: string; pick: number; widthMm: number; reachMm: number }[] = [];
      let covered = 0;
      while (covered < wanted && chosen.length < CLIMB_PER_FACE_MAX) {
        const piece = rule.pieces[Math.floor(next() * rule.pieces.length) % rule.pieces.length]!;
        const pick = next();
        const reachMm = (heightMm * (least + (most_ - least) * next())) / 1000;
        const size = sizeOf(piece, pick);
        if (size === null || !(size[2] > 0)) break;
        const widthMm = (size[0] * reachMm) / size[2];
        if (covered + widthMm > face.lengthMm) break;
        chosen.push({ piece, pick, widthMm, reachMm });
        covered += widthMm;
      }
      // The face's length less the plants', shared evenly before, between and after them.
      const gap = (face.lengthMm - covered) / (chosen.length + 1);
      // Along the face, the way a piece facing out has its +X: the right of a viewer facing the face.
      const along = [-face.outward[1], face.outward[0]] as const;
      let at = -face.lengthMm / 2 + gap;
      for (const plant of chosen) {
        const middle = at + plant.widthMm / 2;
        at += plant.widthMm + gap;
        if (points.length >= most) {
          leftOut += 1;
          continue;
        }
        points.push({
          piece: plant.piece,
          pick: plant.pick,
          outward: face.outward,
          footM: [
            (face.centreMm[0] + along[0] * middle) / 1000,
            (face.centreMm[1] + along[1] * middle) / 1000,
            slot.positionMm[2]! / 1000,
          ],
          heightM: plant.reachMm / 1000,
        });
        grew += 1;
      }
    }
    if (grew > 0) buildings += 1;
  }
  return { points, buildings, leftOut };
}
