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
import { add, exact, measureAgainst, multiply, subtract } from './integer-math.js';
import type { Plan } from './integer-math.js';
import { faceOn, HORIZONTAL, piecesOf, runOf, Surface, VERTICAL } from './faces.js';
import type { FaceCover } from './faces.js';
import type { Piece } from './pieces.js';
import { leftTurning, openRegions } from './piece-carve.js';
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

/**
 * The parts of one tier edge's wall that no facade draws over, as rectangles in the edge's frame.
 * The boundaries of every cover, and the wall's own, cut the wall into cells; a cell no cover holds
 * is drawn. Cells that meet share their whole edge, so nothing cracks between them.
 */
function openWall(
  run: number,
  base: number,
  top: number,
  covers: readonly FaceCover[],
): [number, number, number, number][] {
  if (covers.length === 0) return [[0, run, base, top]];
  const cuts = (low: number, high: number, values: readonly number[]): number[] => {
    const inside = values.filter((value) => value > low && value < high);
    return [low, ...inside.sort((first, second) => first - second), high]
      .filter((value, index, all) => index === 0 ? true : value !== all[index - 1]);
  };
  const along = cuts(0, run, covers.flatMap((cover) => [cover.low, cover.high]));
  const up = cuts(base, top, covers.flatMap((cover) => [cover.base, cover.top]));
  const open: [number, number, number, number][] = [];
  for (let u = 0; u + 1 < along.length; u += 1) {
    for (let z = 0; z + 1 < up.length; z += 1) {
      const cell: [number, number, number, number] = [along[u]!, along[u + 1]!, up[z]!, up[z + 1]!];
      const held = covers.some((cover) =>
        cover.low <= cell[0] && cell[1] <= cover.high && cover.base <= cell[2] && cell[3] <= cover.top);
      if (!held) open.push(cell);
    }
  }
  return open;
}

/**
 * A building's own faces, by the rule above: its walls, its roofs and terraces, and its parapets.
 * `covered` names the parts of its tier edges that facades draw over, which its own walls give up.
 */
export function massingPieces(fields: MassingFields, covered: readonly FaceCover[], where: string): Piece[] {
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

    ring.forEach((point, corner) => {
      const next = ring[(corner + 1) % ring.length]!;
      const run = runOf(point, next, where);
      const covers = covered.filter((cover) => cover.tier === index && cover.edge === corner);
      for (const [low, high, from, to] of openWall(run, base, top, covers)) {
        faceOn(walls, { from: point, to: next, run }, low, high, from, to, 0, datum, where);
      }
    });
    for (const well of tier.light_wells_mm) {
      const turned = leftTurning(requireSimpleRing(well, where), where);
      // A well's walls face into the well, so its walk is taken the other way round.
      const inward = [...turned].reverse();
      inward.forEach((point, corner) => {
        const next = inward[(corner + 1) % inward.length]!;
        const run = runOf(point, next, where);
        faceOn(walls, { from: point, to: next, run }, 0, run, base, top, 0, datum, where);
      });
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
        const run = runOf(point, next, where);
        for (const [low, high] of openAlong(point, next, standing, where)) {
          faceOn(parapets, { from: point, to: next, run }, low, high, top, crown, 0, datum, where);
        }
      });
    }
  });
  return piecesOf([walls, roof, parapets]);
}
