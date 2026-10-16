/**
 * THE STEPS ROUND A LOT. A town laid on its land stands each lot level at its own grade, while the
 * footways in front of it climb along their streets and the lots beside it stand at their own grades.
 * Every one of those surfaces is drawn at its height and the terrain is cut away under them, so where
 * two meet at other heights the ground between them is a step, and the step is the terrain's to
 * close: a vertical surface from the lower height up to the higher, facing the lower side.
 *
 *   1. BETWEEN LOTS: where two lots' edges lie on one line and overlap along it by more than a point,
 *      the step stands on the overlap from the lower lot's grade to the higher's, facing the lower
 *      lot.
 *   2. AT A FRONTAGE: along each edge of a lot that is a frontage, the step stands between the
 *      footway's back edge (its curb's kerb line there, the line's end height past either end, where
 *      the footway is its corner's, plus the kerb and the footway's crossfall) and the lot's grade,
 *      facing the street where the lot stands higher and the lot where the footway does. The edge is
 *      cut where the kerb line bends or ends (past its end the footway is level at the end's height)
 *      and where the two heights cross, so each part is one plane. A kerb line is a run, each piece
 *      running the way of the whole line, so no two of its points share a place along the edge; a
 *      line with a repeated point is refused by name where its curb is read. A frontage whose curb
 *      the tile does not carry draws none.
 *   3. Lots are rings of axis-aligned edges in the city grammar; an edge that is not is refused by
 *      name rather than clipped by a rule this module does not state. Each part of a step is drawn by
 *      the terrain patch whose tile holds it: along the edge within the tile's closed span, across it
 *      within the half-open span, so a step on a tile's edge is drawn once.
 *   4. A terrain patch closes a step only within the heights it states. A patch graded for its
 *      lots (city grammar version 6) stands each lot's pad at its grade and each street at its
 *      footways' level, so its heights span every step round them; a level patch (versions 3 to 5)
 *      stands at the datum below every lot and footway, spans none, and draws exactly what it drew,
 *      leaving the few centimetres a lot stands above a footway of another crossfall as they were.
 *   5. `s` runs along the edge from its start and `t = -z`.
 *
 * A step between lots ends where their shared edge ends, which on a frontage line is where each
 * lot's frontage step begins, so the two meet on a vertical edge in planes across each other and
 * never overlap. Lots of one grade level with their footways, as every lot of a town on level ground
 * is, have no step at all, and a terrain patch draws exactly what it drew before.
 */
import type { Plan } from './integer-math.js';
import { add, crossVectors, dot, floorDivide, GeometryError, measureAgainst, multiply, subtract } from './integer-math.js';
import { heightAlong } from './streets.js';

/** One frontage of a lot: the ring edge it is, and the curb across its footway. */
export interface LotFrontage {
  readonly edgeOrdinal: number;
  /** The curb's kerb line, or undefined when the tile does not carry the curb. */
  readonly kerbLine: readonly (readonly [number, number, number])[] | undefined;
  /** How far the footway's back edge stands above the kerb line: the kerb and the crossfall. */
  readonly upMm: number;
}

/** A lot as a step reads it: its ring, the height it stands level at, and its frontages. */
export interface SteppedLot {
  readonly ring: readonly Plan[];
  readonly gradeMm: number;
  readonly frontages: readonly LotFrontage[];
}

/** The steps a tile's terrain draws: vertices, surface coordinates and triangles over them. */
export interface Steps {
  readonly vertices: number[];
  readonly coordinates: number[];
  readonly triangles: number[];
}

type Tile = readonly [number, number, number, number];
/** The lowest and highest heights the terrain patch states: a step outside them is not its own. */
type Heights = readonly [number, number];

const least = (a: number, b: number): number => (a < b ? a : b);
const most = (a: number, b: number): number => (a > b ? a : b);

/** Twice the signed area of a ring in plan: positive for a counter-clockwise ring. */
function twiceArea(ring: readonly Plan[], where: string): number {
  let sum = 0;
  for (const [index, here] of ring.entries()) {
    const next = ring[(index + 1) % ring.length]!;
    sum = add(sum, subtract(multiply(here[0], next[1], where), multiply(next[0], here[1], where), where), where);
  }
  return sum;
}

/** A ring's edge `index`, in the order that keeps the ring's inside on its left. */
function edgeOf(ring: readonly Plan[], index: number, where: string): readonly [Plan, Plan] {
  const a = ring[index]!;
  const b = ring[(index + 1) % ring.length]!;
  return twiceArea(ring, where) > 0 ? [a, b] : [b, a];
}

/**
 * The part of the axis-aligned segment `p` to `q` the tile holds, in the same order, or undefined.
 * Refuses a segment that is not axis-aligned.
 */
function heldBy(p: Plan, q: Plan, tile: Tile, where: string): readonly [Plan, Plan] | undefined {
  const [x0, y0, x1, y1] = tile;
  const alongX = p[1] === q[1];
  if (!alongX && p[0] !== q[0]) throw new GeometryError(`${where}: a lot's edge is not axis-aligned`);
  const across = alongX ? p[1] : p[0];
  const [acrossLow, acrossHigh] = alongX ? [y0, y1] : [x0, x1];
  if (across < acrossLow) return undefined;
  if (across >= acrossHigh) return undefined;
  const axis = alongX ? 0 : 1;
  const [spanLow, spanHigh] = alongX ? [x0, x1] : [y0, y1];
  const clamp = (point: Plan): Plan => {
    const value = least(spanHigh, most(spanLow, point[axis]!));
    return alongX ? [value, point[1]] : [point[0], value];
  };
  const [from, to] = [clamp(p), clamp(q)];
  if (from[0] === to[0] && from[1] === to[1]) return undefined;
  return [from, to];
}

/**
 * Add the vertical quad from `p` to `q`, its foot at `foot(p)` and `foot(q)`, its head at `head`,
 * counter-clockwise seen from the right of `p` to `q` where the foot is lower, from its left where
 * the head is, leaving out any triangle of no area, and the whole quad where it reaches outside the
 * patch's heights (rule 4).
 */
function addQuad(steps: Steps, p: Plan, q: Plan, footP: number, footQ: number, head: number, heights: Heights, where: string): void {
  for (const z of [footP, footQ, head]) {
    if (z < heights[0]) return;
    if (z > heights[1]) return;
  }
  const quad: (readonly [number, number, number])[] = [[p[0], p[1], footP], [q[0], q[1], footQ], [q[0], q[1], head], [p[0], p[1], head]];
  const keep: number[] = [];
  if (footQ !== head) keep.push(0, 1, 2);
  if (footP !== head) keep.push(0, 2, 3);
  if (keep.length === 0) return;
  const first = steps.vertices.length / 3;
  const direction: Plan = [subtract(q[0], p[0], where), subtract(q[1], p[1], where)];
  for (const point of quad) {
    steps.vertices.push(point[0], point[1], point[2]);
    steps.coordinates.push(measureAgainst(p, direction, [point[0], point[1]], where).along, -point[2]);
  }
  for (const corner of keep) steps.triangles.push(first + corner);
}

/** The steps between two lots at other grades along their shared edges, by rule 1. */
function betweenLots(steps: Steps, lower: SteppedLot, higher: SteppedLot, tile: Tile, heights: Heights, where: string): void {
  for (let index = 0; index < lower.ring.length; index += 1) {
    const [a, b] = edgeOf(lower.ring, index, where);
    const along: Plan = [subtract(b[0], a[0], where), subtract(b[1], a[1], where)];
    for (let other = 0; other < higher.ring.length; other += 1) {
      const [c, d] = edgeOf(higher.ring, other, where);
      const theirs: Plan = [subtract(d[0], c[0], where), subtract(d[1], c[1], where)];
      if (crossVectors(along, theirs, where) !== 0) continue;
      if (crossVectors(along, [subtract(c[0], a[0], where), subtract(c[1], a[1], where)], where) !== 0) continue;
      const length = dot(along, along, where);
      const position = (point: Plan): number => dot([subtract(point[0], a[0], where), subtract(point[1], a[1], where)], along, where);
      const low = most(0, least(position(c), position(d)));
      const high = least(length, most(position(c), position(d)));
      if (high <= low) continue;
      const at = (place: number): Plan => [
        add(a[0], floorDivide(multiply(along[0], place, where), length, where), where),
        add(a[1], floorDivide(multiply(along[1], place, where), length, where), where),
      ];
      // Run against the lower lot's own edge, its inside on that edge's left: with its foot the lower
      // grade the quad faces right of its run, into the lower lot.
      const held = heldBy(at(high), at(low), tile, where);
      if (held === undefined) continue;
      addQuad(steps, held[0], held[1], lower.gradeMm, lower.gradeMm, higher.gradeMm, heights, where);
    }
  }
}

/** The step along one frontage of a lot, by rule 2. */
function atFrontage(steps: Steps, lot: SteppedLot, frontage: LotFrontage, tile: Tile, heights: Heights, where: string): void {
  const line = frontage.kerbLine;
  if (line === undefined) return;
  const [a, b] = edgeOf(lot.ring, frontage.edgeOrdinal, where);
  const held = heldBy(a, b, tile, where);
  if (held === undefined) return;
  const [p, q] = held;
  const axis = p[1] === q[1] ? 0 : 1;
  const forward = q[axis]! > p[axis]!;
  const first = line[0]!;
  const last = line[line.length - 1]!;
  const [lineLow, lineHigh] = first[axis]! < last[axis]! ? [first, last] : [last, first];
  // The footway's back edge at a place along the edge: the kerb line's height opposite it, or its end
  // height past either end, plus the kerb and the crossfall.
  const footway = (place: number): number => {
    if (place <= lineLow[axis]!) return add(lineLow[2], frontage.upMm, where);
    if (place >= lineHigh[axis]!) return add(lineHigh[2], frontage.upMm, where);
    const point: Plan = axis === 0 ? [place, p[1]] : [p[0], place];
    return add(heightAlong(line, point, where)!, frontage.upMm, where);
  };
  const ordered = (left: number, right: number): boolean => (forward ? left < right : left > right);
  const places: number[] = [p[axis]!];
  // Every point of the kerb line inside the edge, its ends among them: the footway bends at each.
  const cuts = line.map((point) => point[axis]!).filter((place) => ordered(p[axis]!, place) && ordered(place, q[axis]!));
  cuts.sort((left, right) => (forward ? left - right : right - left));
  for (const place of [...cuts, q[axis]!]) {
    const before = places[places.length - 1]!;
    const [z0, z1] = [subtract(footway(before), lot.gradeMm, where), subtract(footway(place), lot.gradeMm, where)];
    if (multiply(z0, z1, where) < 0) {
      // Where the footway passes the lot's grade the step turns round: the place of the crossing, its
      // run times the share of the climb below it, with the climb made positive. The footway's own
      // heights are floored along its kerb line, so that place can fall a millimetre short of the
      // grade, where the part beyond it would stand on both sides of the grade and face both ways:
      // the cut is the place nearest it where the footway meets the grade exactly.
      const run = subtract(place, before, where);
      const [share, climb] = z1 > z0 ? [subtract(0, z0, where), subtract(z1, z0, where)] : [z0, subtract(z0, z1, where)];
      const estimate = add(before, floorDivide(multiply(run, share, where), climb, where), where);
      const crossing = meeting(estimate, before, place, (at) => footway(at) === lot.gradeMm, where);
      if (crossing !== before && crossing !== place) places.push(crossing);
    }
    places.push(place);
  }
  const plan = (place: number): Plan => (axis === 0 ? [place, p[1]] : [p[0], place]);
  for (let index = 0; index + 1 < places.length; index += 1) {
    const [from, to] = [places[index]!, places[index + 1]!];
    addQuad(steps, plan(from), plan(to), footway(from), footway(to), lot.gradeMm, heights, where);
  }
}

/**
 * The place strictly between `before` and `place` nearest `estimate` where `meets` holds, nearer
 * `before` first at equal distance; `estimate` itself where none does (a footway steeper than a
 * millimetre a millimetre, which no street on land climbs).
 */
function meeting(estimate: number, before: number, place: number, meets: (at: number) => boolean, where: string): number {
  const [low, high] = before < place ? [before, place] : [place, before];
  const toward = before < place ? -1 : 1;
  const reach = subtract(high, low, where);
  for (let distance = 0; distance <= reach; distance += 1) {
    for (const at of distance === 0 ? [estimate] : [add(estimate, multiply(toward, distance, where), where), subtract(estimate, multiply(toward, distance, where), where)]) {
      if (at > low && at < high && meets(at)) return at;
    }
  }
  return estimate;
}

/**
 * Every step round `lots` that the tile `[x0, y0, x1, y1]` holds within the patch's `heights`, by
 * the rules above.
 */
export function lotSteps(lots: readonly SteppedLot[], tile: Tile, heights: Heights, where: string): Steps {
  const steps: Steps = { vertices: [], coordinates: [], triangles: [] };
  for (let first = 0; first < lots.length; first += 1) {
    for (let second = first + 1; second < lots.length; second += 1) {
      const [one, other] = [lots[first]!, lots[second]!];
      if (one.gradeMm === other.gradeMm) continue;
      const [lower, higher] = one.gradeMm < other.gradeMm ? [one, other] : [other, one];
      betweenLots(steps, lower, higher, tile, heights, where);
    }
  }
  for (const lot of lots) {
    for (const frontage of lot.frontages) atFrontage(steps, lot, frontage, tile, heights, where);
  }
  return steps;
}
