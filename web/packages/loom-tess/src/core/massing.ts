/**
 * THE MASSING RULE: A BUILDING'S OWN FACES, FROM ITS TIERS AND ITS ROOF, IN INTEGERS.
 *
 * A massing states everything this needs and leaves nothing to be taken by eye: storey heights from
 * a base elevation, tiers as rings with the storeys each covers, light wells as rings inside a
 * tier, a parapet height per tier, and a roof that is either a deck or a ridge between two stated
 * points. Every face here is one of those facts turned into triangles.
 *
 *   1. WALLS. Each tier's ring edge, from the floor of its first storey to the ceiling of its last.
 *      A tier stacks on the one below, so no wall crosses a storey its tier does not cover. A light
 *      well's walls run the same way, facing inward.
 *   2. DECKS. The top tier's ring is its roof, and a lower tier's ring less the ring standing on it
 *      is a terrace. Both are cut by the shared piece carve, so a terrace is what is exactly left of
 *      the tier rather than an offset taken from the setback. Light wells are cut out the same way.
 *   3. PARAPETS. A parapet stands where a deck meets the open air: along the parts of a tier's ring
 *      edges that no ring stands on, taken as intervals along each edge, in integers.
 *   4. A RIDGE ROOF. Two planes from the eave edges up to the stated ridge, and a gable on each of
 *      the two edges the ridge runs between. The grammar holds a ridge roof to a convex four-sided
 *      top tier, so each plane is one quad and needs no further cutting.
 *
 * Surface frames are the grammar's (`common`): a vertical face runs `s` along its own ring edge
 * from that edge's start with `t = base_elevation_mm - z`, and a roof, a pitched plane included,
 * takes `s = x` and `t = y` in plan.
 *
 * WHAT THIS DOES NOT DRAW, AND WHY IT DRAWS THE WALL TODAY. A facade is laid out on a tier edge and
 * covers part of it. Until a facade DRAWS, the building's own wall is what stands there, exactly as
 * terrain draws the ground until something drawn covers it. When the facade rule lands, a wall
 * yields to the facade surfaces that are drawn, by that same rule, and never to a facade record
 * that only states it will be there. Nothing is drawn twice in one place at any point.
 */
import { add, exact, floorDivide, measureAgainst, multiply, subtract } from './integer-math.js';
import type { Plan } from './integer-math.js';
import type { Piece, SurfaceExpansion } from './pieces.js';
import type { SurfaceOrientation } from './triangle-digest.js';
import { carvedPiece, twiceWalkArea } from './piece-carve.js';
import type { ObstructionWalk } from './piece-carve.js';
import { requireSimpleRing, triangulateRing } from './ring-triangulation.js';

/** A tier of a building: the storeys it covers, its ring, its light wells and its parapet. */
export interface Tier {
  readonly first_storey: number;
  readonly last_storey: number;
  readonly ring_mm: readonly Plan[];
  readonly light_wells_mm: readonly (readonly Plan[])[];
  readonly parapet_height_mm: number;
}

/** What this rule reads of a massing record. */
export interface MassingFields {
  readonly base_elevation_mm: number;
  readonly ground_storey_height_mm: number;
  readonly upper_storey_height_mm: number;
  readonly storeys: number;
  readonly tiers: readonly Tier[];
  readonly roof_form: string;
  readonly ridge_mm: readonly Plan[];
  readonly roof_rise_mm: number;
}

/** The roof form that rises to a ridge; every other form this version draws is a deck. */
const RIDGE = 'ridge';

/** The roles a building's own faces take, each owned by the massing kind in the grammar. */
const WALL = 'wall';
const ROOF = 'roof';
const PARAPET = 'parapet';

const HORIZONTAL: SurfaceOrientation = 'horizontal';
const VERTICAL: SurfaceOrientation = 'vertical';

/** `exulanica.grammar.grammars.city.massing.storey_floor_mm`. */
export function storeyFloorMm(fields: MassingFields, storey: number, where: string): number {
  if (storey === 0) return exact(fields.base_elevation_mm, where);
  return add(
    add(fields.base_elevation_mm, fields.ground_storey_height_mm, where),
    multiply(subtract(storey, 1, where), fields.upper_storey_height_mm, where),
    where,
  );
}

/** `exulanica.grammar.grammars.city.massing.tier_top_mm`: the ceiling of a tier's last storey. */
export function tierTopMm(fields: MassingFields, tier: Tier, where: string): number {
  return storeyFloorMm(fields, add(tier.last_storey, 1, where), where);
}

/** A ring turned counter-clockwise, which is how every piece here is built. */
function leftTurning(ring: readonly Plan[], where: string): readonly Plan[] {
  return twiceWalkArea(ring, where) < 0 ? [...ring].reverse() : ring;
}

/** One surface of a record: its triangles, and the plan and frame coordinates of each vertex. */
class Surface {
  readonly vertices: number[] = [];
  readonly triangles: number[] = [];
  readonly coordinates: number[] = [];

  constructor(readonly role: string, readonly orientation: SurfaceOrientation) {}

  /** A corner, at a height, with its own surface coordinates. */
  corner(point: Plan, height: number, s: number, t: number): number {
    const index = this.vertices.length / 3;
    this.vertices.push(point[0], point[1], height);
    this.coordinates.push(s, t);
    return index;
  }

  face(...corners: readonly number[]): void {
    for (let corner = 1; corner + 1 < corners.length; corner += 1) {
      this.triangles.push(corners[0]!, corners[corner]!, corners[corner + 1]!);
    }
  }

  piece(): Piece | undefined {
    if (this.triangles.length === 0) return undefined;
    const surface: SurfaceExpansion = { role: this.role, orientation: this.orientation, coordinates: this.coordinates };
    return { vertices: this.vertices, triangles: this.triangles, surface };
  }
}

/**
 * A vertical band along a plan segment, from `base` to `top`, facing out of the counter-clockwise
 * walk it belongs to.
 */
function band(into: Surface, from: Plan, to: Plan, base: number, top: number, datum: number, where: string): void {
  if (top <= base) return;
  if (from[0] === to[0] && from[1] === to[1]) return;
  const direction: Plan = [subtract(to[0], from[0], where), subtract(to[1], from[1], where)];
  const run = measureAgainst(from, direction, to, where).along;
  const [low, high] = [subtract(datum, base, where), subtract(datum, top, where)];
  into.face(
    into.corner(from, base, 0, low),
    into.corner(to, base, run, low),
    into.corner(to, top, run, high),
    into.corner(from, top, 0, high),
  );
}

/** A ring as counter-clockwise triangles, which is what the carve takes as an obstruction. */
function ringWalks(ring: readonly Plan[], where: string): ObstructionWalk[] {
  const turned = leftTurning(requireSimpleRing(ring, where), where);
  const cut = triangulateRing(turned, where);
  const out: ObstructionWalk[] = [];
  for (let corner = 0; corner + 2 < cut.length; corner += 3) {
    out.push([turned[cut[corner]!]!, turned[cut[corner + 1]!]!, turned[cut[corner + 2]!]!]);
  }
  return out;
}

/** Whether a counter-clockwise ring turns only left, so the carve can take it whole. */
function convex(ring: readonly Plan[], where: string): boolean {
  return ring.every((here, index) => {
    const before = ring[(index + ring.length - 1) % ring.length]!;
    const after = ring[(index + 1) % ring.length]!;
    return subtract(
      multiply(subtract(here[0], before[0], where), subtract(after[1], here[1], where), where),
      multiply(subtract(here[1], before[1], where), subtract(after[0], here[0], where), where),
      where,
    ) >= 0;
  });
}

/**
 * A tier's ring less every ring standing on it, as convex integer walks. A convex ring is carved
 * whole, which loses nothing: the rings are the generator's own integers and meet on integer
 * points, so every face has integer corners and the carve's rounding never fires. A ring that turns
 * in is cut into triangles first, and each face then rounds to the lattice by under a millimetre,
 * which is the shared carve's stated cost.
 */
function openRegions(ring: readonly Plan[], standing: readonly (readonly Plan[])[], where: string): Plan[][] {
  const obstructions: ObstructionWalk[] = [];
  for (const other of standing) {
    for (const walk of ringWalks(other, where)) obstructions.push(walk);
  }
  if (obstructions.length === 0) {
    const cut = triangulateRing(ring, where);
    const whole: Plan[][] = [];
    for (let corner = 0; corner + 2 < cut.length; corner += 3) {
      whole.push([ring[cut[corner]!]!, ring[cut[corner + 1]!]!, ring[cut[corner + 2]!]!]);
    }
    return whole;
  }
  if (convex(ring, where)) return carvedPiece(ring, obstructions, ring, where);
  const cut = triangulateRing(ring, where);
  const walks: Plan[][] = [];
  for (let corner = 0; corner + 2 < cut.length; corner += 3) {
    const piece: Plan[] = [ring[cut[corner]!]!, ring[cut[corner + 1]!]!, ring[cut[corner + 2]!]!];
    for (const walk of carvedPiece(piece, obstructions, piece, where)) walks.push(walk);
  }
  return walks;
}

/** Whether a point lies on the closed segment from `from` to `to`, exactly. */
function onSegment(from: Plan, to: Plan, point: Plan, where: string): boolean {
  const side = subtract(
    multiply(subtract(to[0], from[0], where), subtract(point[1], from[1], where), where),
    multiply(subtract(to[1], from[1], where), subtract(point[0], from[0], where), where),
    where,
  );
  if (side !== 0) return false;
  const within = (low: number, high: number, value: number): boolean => {
    if (low <= high) return low <= value && value <= high;
    return high <= value && value <= low;
  };
  return within(from[0], to[0], point[0]) && within(from[1], to[1], point[1]);
}

/**
 * The parts of one ring edge that no ring standing on the tier covers, as intervals along the edge.
 * A ring above meets the edge along whole sub-segments, both rings being the generator's own
 * integers, so subtracting intervals is exact.
 */
function openAlong(from: Plan, to: Plan, standing: readonly (readonly Plan[])[], where: string): [number, number][] {
  const direction: Plan = [subtract(to[0], from[0], where), subtract(to[1], from[1], where)];
  const run = measureAgainst(from, direction, to, where).along;
  const covered: [number, number][] = [];
  for (const ring of standing) {
    ring.forEach((point, index) => {
      const next = ring[(index + 1) % ring.length]!;
      if (!onSegment(from, to, point, where)) return;
      if (!onSegment(from, to, next, where)) return;
      const low = measureAgainst(from, direction, point, where).along;
      const high = measureAgainst(from, direction, next, where).along;
      covered.push(low <= high ? [low, high] : [high, low]);
    });
  }
  covered.sort((first, second) => first[0] - second[0]);
  const open: [number, number][] = [];
  let at = 0;
  for (const [low, high] of covered) {
    if (low > at) open.push([at, low]);
    if (high > at) at = high;
  }
  if (at < run) open.push([at, run]);
  return open;
}

/** The point at a distance along a plan segment, floored onto the lattice. */
function alongEdge(from: Plan, to: Plan, distance: number, run: number, where: string): Plan {
  if (distance === 0) return from;
  if (distance >= run) return to;
  const axis = (index: 0 | 1): number => add(
    from[index],
    floorDivide(multiply(subtract(to[index], from[index], where), distance, where), run, where),
    where,
  );
  return [axis(0), axis(1)];
}

/**
 * A ridge roof on a convex four-sided top tier. The ridge runs between the floored midpoints of two
 * opposite edges, `roof_rise_mm` above the wall top: those two edges carry gables and the other two
 * each carry one plane, drawn as two triangles since four corners that far apart need not be
 * coplanar.
 */
function ridgeRoof(
  fields: MassingFields,
  ring: readonly Plan[],
  top: number,
  datum: number,
  roof: Surface,
  walls: Surface,
  where: string,
): void {
  const [low, high] = [fields.ridge_mm[0]!, fields.ridge_mm[1]!];
  const crown = add(top, fields.roof_rise_mm, where);
  const at = ring.findIndex((point, index) => onSegment(point, ring[(index + 1) % ring.length]!, low, where));
  if (at < 0) throw new RangeError(`${where}: a ridge that starts on no edge of its top tier`);
  const corner = (step: number): Plan => ring[(at + step) % ring.length]!;
  // The eave edges: each runs from the gable holding one ridge end to the gable holding the other.
  for (const [from, to, near, far] of [
    [corner(1), corner(2), high, low],
    [corner(3), corner(0), low, high],
  ] as [Plan, Plan, Plan, Plan][]) {
    roof.face(
      roof.corner(from, top, from[0], from[1]),
      roof.corner(to, top, to[0], to[1]),
      roof.corner(near, crown, near[0], near[1]),
      roof.corner(far, crown, far[0], far[1]),
    );
  }
  for (const [from, to, point] of [
    [corner(0), corner(1), low],
    [corner(2), corner(3), high],
  ] as [Plan, Plan, Plan][]) {
    const direction: Plan = [subtract(to[0], from[0], where), subtract(to[1], from[1], where)];
    const run = measureAgainst(from, direction, to, where).along;
    const along = measureAgainst(from, direction, point, where).along;
    walls.face(
      walls.corner(from, top, 0, subtract(datum, top, where)),
      walls.corner(to, top, run, subtract(datum, top, where)),
      walls.corner(point, crown, along, subtract(datum, crown, where)),
    );
  }
}

/** A building's own faces, by the rule above: its walls, its roofs and terraces, and its parapets. */
export function massingPieces(fields: MassingFields, where: string): Piece[] {
  const walls = new Surface(WALL, VERTICAL);
  const roof = new Surface(ROOF, HORIZONTAL);
  const parapets = new Surface(PARAPET, VERTICAL);
  const datum = fields.base_elevation_mm;
  fields.tiers.forEach((tier, index) => {
    const ring = leftTurning(requireSimpleRing(tier.ring_mm, where), where);
    const base = storeyFloorMm(fields, tier.first_storey, where);
    const top = tierTopMm(fields, tier, where);
    const above = fields.tiers[index + 1];
    const standing: (readonly Plan[])[] = [];
    if (above !== undefined) standing.push(leftTurning(requireSimpleRing(above.ring_mm, where), where));

    ring.forEach((point, corner) => band(walls, point, ring[(corner + 1) % ring.length]!, base, top, datum, where));
    for (const well of tier.light_wells_mm) {
      const turned = leftTurning(requireSimpleRing(well, where), where);
      // A well's walls face into the well, so its walk is taken the other way round.
      const inward = [...turned].reverse();
      inward.forEach((point, corner) => band(walls, point, inward[(corner + 1) % inward.length]!, base, top, datum, where));
      standing.push(turned);
    }

    const ridged = fields.roof_form === RIDGE && index === subtract(fields.tiers.length, 1, where);
    if (ridged) {
      ridgeRoof(fields, ring, top, datum, roof, walls, where);
    } else {
      for (const walk of openRegions(ring, standing, where)) {
        const corners = walk.map((point) => roof.corner(point, top, point[0], point[1]));
        for (const index of triangulateRing(walk, where)) roof.triangles.push(corners[index]!);
      }
    }

    if (tier.parapet_height_mm > 0) {
      const crown = add(top, tier.parapet_height_mm, where);
      ring.forEach((point, corner) => {
        const next = ring[(corner + 1) % ring.length]!;
        const direction: Plan = [subtract(next[0], point[0], where), subtract(next[1], point[1], where)];
        const run = measureAgainst(point, direction, next, where).along;
        for (const [low, high] of openAlong(point, next, standing, where)) {
          band(
            parapets,
            alongEdge(point, next, low, run, where),
            alongEdge(point, next, high, run, where),
            top,
            crown,
            datum,
            where,
          );
        }
      });
    }
  });
  const pieces: Piece[] = [];
  for (const surface of [walls, roof, parapets]) {
    const piece = surface.piece();
    if (piece !== undefined) pieces.push(piece);
  }
  return pieces;
}
