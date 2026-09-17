/**
 * THE STREET RULES: A SEGMENT'S CARRIAGEWAY AND GUTTERS, AND A CURB'S KERB AND FOOTWAY.
 *
 * The grammar writes a street's geometry once (`exulanica.grammar.grammars.city.streets`): the
 * segment's centreline is the crown line, each curb's kerb line is the foot of its kerb face at
 * gutter level, digitised in the segment's direction, and every width is a record field. These
 * rules turn that into surfaces, in integers, with no angle:
 *
 * THE MEASURE. Every point is placed or measured by the grammar's corner rule measure: `r` along a
 * vector is `floor(v * r * S / isqrt(|v|^2 * S^2))` on each axis (`alongByCornerRule`), and a
 * point's place against a line is `along` and `across` it, floored the same way (`measureAgainst`),
 * with `S = 10^6`.
 *
 * STRAIGHT ONLY, FOR NOW. A centreline or a kerb line of more than one piece, or a kerb line not
 * running with its centreline, needs `bent_street`, a rule not yet built, and draws nothing.
 *
 * THE SEGMENT.
 *   1. The strip runs where both kerb lines exist along the centreline. At each end, the kerb line
 *      that ends nearer the middle sets the end; the other side's point is that kerb point plus the
 *      carriageway width across, toward the other side, and its height is its own kerb line's,
 *      interpolated by `floor((z1 - z0) * (p - p0) / (p1 - p0))` on the positions along the
 *      centreline, `p = dot(point - start, direction)`.
 *   2. The crown point at each end is the floored midpoint of the two kerb points, at the
 *      centreline's height, interpolated the same way.
 *   3. Each side's gutter line is its kerb point plus `gutter_width_mm` across toward the crown,
 *      at `z_kerb + floor((z_crown - z_kerb) * 2 * gutter / carriageway width)`, on the camber plane.
 *   4. The carriageway surface is the two quads from crown to gutter line, and the gutter surface
 *      the two quads from gutter line to kerb line, both horizontal. A quad of no width is left out.
 *   5. Surface coordinates: `s` along the centreline from its start, `t` across it, left positive.
 *
 * THE CURB, its straight part, away from the carriageway along the side's normal:
 *   1. The kerb face is the vertical quad from the kerb line up `kerb_height_mm`, facing the
 *      carriageway. `s` is along the centreline and `t = base - z`, with the kerb line as base.
 *   2. The kerb top is the horizontal quad `kerb_width_mm` wide at the top of the face.
 *   3. The footway is the horizontal quad `footway_width_mm` wide behind the kerb top, rising to
 *      `floor(footway_width_mm * footway_crossfall_millionths / 10^6)` above it at its back.
 *   Kerb top and footway take `s` along the centreline and `t` across it.
 *
 * Every triangle is counter-clockwise seen from its front: from above for a horizontal surface,
 * from the carriageway for a kerb face.
 *
 * Not yet wired into a bake. It changes no container until an expander calls it.
 */
import type { Piece, SurfaceExpansion } from './expand.js';
import { alongByCornerRule } from './fillet-arc.js';
import {
  add,
  CORNER_LENGTH_SCALE,
  crossVectors,
  dot,
  floorDivide,
  GeometryError,
  measureAgainst,
  multiply,
  subtract,
} from './integer-math.js';
import type { Plan, Space } from './integer-math.js';

export type StreetFields = { readonly [name: string]: unknown };

/** What a street rule gives: surfaces to draw, or the rule it waits on. */
export type StreetResult =
  | { readonly state: 'drawn'; readonly pieces: readonly Piece[] }
  | { readonly state: 'waiting'; readonly need: 'bent_street' | 'street_curbs' };

/** A straight line of a record: exactly two points, or undefined for a bent one. */
function straight(points: unknown): readonly [Space, Space] | undefined {
  const line = points as readonly Space[];
  if (line.length !== 2) return undefined;
  return [line[0]!, line[1]!];
}

const plan = (point: Space): Plan => [point[0], point[1]];

function between(from: Plan, to: Plan, where: string): Plan {
  return [subtract(to[0], from[0], where), subtract(to[1], from[1], where)];
}

function moved(point: Plan, by: Plan, where: string): Plan {
  return [add(point[0], by[0], where), add(point[1], by[1], where)];
}

/** Whether `line` runs with `direction`: parallel and the same way. */
function runsWith(direction: Plan, line: readonly [Space, Space], where: string): boolean {
  const piece = between(plan(line[0]), plan(line[1]), where);
  if (crossVectors(direction, piece, where) !== 0) return false;
  return dot(direction, piece, where) > 0;
}

/** The unit normals of a direction, unscaled: left `(-dy, dx)` and right `(dy, -dx)`. */
const leftOf = (direction: Plan): Plan => [-direction[1], direction[0]];
const rightOf = (direction: Plan): Plan => [direction[1], -direction[0]];

/**
 * The height at `point` on a straight line of a record, by positions along `direction`:
 * `z0 + floor((z1 - z0) * p / p1)`, with `p` and `p1` the positions of the point and of the line's
 * end, `dot(point - start, direction)`.
 */
function heightOn(line: readonly [Space, Space], direction: Plan, point: Plan, where: string): number {
  const end = dot(between(plan(line[0]), plan(line[1]), where), direction, where);
  const here = dot(between(plan(line[0]), point, where), direction, where);
  if (end === 0) throw new GeometryError(`${where} measures a height on a line of no length`);
  return add(line[0][2], floorDivide(multiply(subtract(line[1][2], line[0][2], where), here, where), end, where), where);
}

interface Measured {
  readonly vertices: number[];
  readonly coordinates: number[];
}

/** Vertices with horizontal surface coordinates: `s` along the centreline, `t` across it. */
function horizontal(points: readonly Space[], origin: Plan, direction: Plan, where: string): Measured {
  const vertices: number[] = [];
  const coordinates: number[] = [];
  for (const point of points) {
    vertices.push(point[0], point[1], point[2]);
    const { along, across } = measureAgainst(origin, direction, plan(point), where);
    coordinates.push(along, across);
  }
  return { vertices, coordinates };
}

function piece(measured: Measured, triangles: readonly number[], role: string, orientation: SurfaceExpansion['orientation']): Piece {
  return {
    vertices: measured.vertices,
    triangles,
    surface: { role, orientation, coordinates: measured.coordinates },
  };
}

/** The two quads of a strip, `a0 a1 b1 b0`, as triangles over four vertices given in that order. */
const QUAD = [0, 1, 2, 0, 2, 3];

/** The segment's carriageway and gutter surfaces, between its two curbs' kerb lines. */
export function segmentSurfaces(
  segment: StreetFields,
  left: StreetFields | undefined,
  right: StreetFields | undefined,
  where: string,
): StreetResult {
  if (left === undefined) return { state: 'waiting', need: 'street_curbs' };
  if (right === undefined) return { state: 'waiting', need: 'street_curbs' };
  const centre = straight(segment.centreline_mm);
  const leftLine = straight(left.kerb_line_mm);
  const rightLine = straight(right.kerb_line_mm);
  const bent: StreetResult = { state: 'waiting', need: 'bent_street' };
  if (centre === undefined) return bent;
  if (leftLine === undefined) return bent;
  if (rightLine === undefined) return bent;
  const origin = plan(centre[0]);
  const direction = between(origin, plan(centre[1]), where);
  if (!runsWith(direction, leftLine, where)) return { state: 'waiting', need: 'bent_street' };
  if (!runsWith(direction, rightLine, where)) return { state: 'waiting', need: 'bent_street' };
  const width = segment.carriageway_width_mm as number;
  const position = (point: Plan): number => dot(between(origin, point, where), direction, where);

  // Each end: the kerb that ends nearer the middle sets it, and the other side is found across.
  const endPoints = (leftPoint: Space, rightPoint: Space, laterWins: boolean): [Space, Space] => {
    const leftFirst = position(plan(leftPoint)) > position(plan(rightPoint));
    const leftSets = laterWins ? leftFirst : !leftFirst;
    if (leftSets) {
      const across = moved(plan(leftPoint), alongByCornerRule(rightOf(direction), width, where), where);
      return [leftPoint, [across[0], across[1], heightOn(rightLine, direction, across, where)]];
    }
    const across = moved(plan(rightPoint), alongByCornerRule(leftOf(direction), width, where), where);
    return [[across[0], across[1], heightOn(leftLine, direction, across, where)], rightPoint];
  };
  const [left0, right0] = endPoints(leftLine[0], rightLine[0], true);
  const [left1, right1] = endPoints(leftLine[1], rightLine[1], false);
  if (position(plan(left0)) >= position(plan(left1))) return { state: 'waiting', need: 'street_curbs' };

  const crown = (a: Space, b: Space): Space => {
    const middle: Plan = [floorDivide(add(a[0], b[0], where), 2, where), floorDivide(add(a[1], b[1], where), 2, where)];
    return [middle[0], middle[1], heightOn(centre, direction, middle, where)];
  };
  const crown0 = crown(left0, right0);
  const crown1 = crown(left1, right1);
  const gutterLine = (kerb: Space, towardCrown: Plan, crownPoint: Space, gutter: number): Space => {
    const at = moved(plan(kerb), alongByCornerRule(towardCrown, gutter, where), where);
    const rise = floorDivide(multiply(subtract(crownPoint[2], kerb[2], where), multiply(gutter, 2, where), where), width, where);
    return [at[0], at[1], add(kerb[2], rise, where)];
  };
  const leftGutter = left.gutter_width_mm as number;
  const rightGutter = right.gutter_width_mm as number;
  const leftInner0 = gutterLine(left0, rightOf(direction), crown0, leftGutter);
  const leftInner1 = gutterLine(left1, rightOf(direction), crown1, leftGutter);
  const rightInner0 = gutterLine(right0, leftOf(direction), crown0, rightGutter);
  const rightInner1 = gutterLine(right1, leftOf(direction), crown1, rightGutter);

  const pieces: Piece[] = [];
  const carriageway: Space[] = [];
  const carriagewayTriangles: number[] = [];
  const addQuad = (points: Space[], triangles: number[], quad: readonly Space[]): void => {
    const base = points.length;
    points.push(...quad);
    triangles.push(...QUAD.map((corner) => base + corner));
  };
  if (multiply(leftGutter, 2, where) < width) addQuad(carriageway, carriagewayTriangles, [crown0, crown1, leftInner1, leftInner0]);
  if (multiply(rightGutter, 2, where) < width) addQuad(carriageway, carriagewayTriangles, [rightInner0, rightInner1, crown1, crown0]);
  if (carriageway.length > 0) {
    pieces.push(piece(horizontal(carriageway, origin, direction, where), carriagewayTriangles, 'carriageway', 'horizontal'));
  }
  const gutters: Space[] = [];
  const gutterTriangles: number[] = [];
  if (leftGutter > 0) addQuad(gutters, gutterTriangles, [leftInner0, leftInner1, left1, left0]);
  if (rightGutter > 0) addQuad(gutters, gutterTriangles, [right0, right1, rightInner1, rightInner0]);
  if (gutters.length > 0) {
    pieces.push(piece(horizontal(gutters, origin, direction, where), gutterTriangles, 'gutter', 'horizontal'));
  }
  if (pieces.length === 0) throw new GeometryError(`${where} has a carriageway of no width`);
  return { state: 'drawn', pieces };
}

/** A curb's straight part: its kerb face, its kerb top and its footway. */
export function curbSurfaces(curb: StreetFields, segment: StreetFields, where: string): StreetResult {
  const centre = straight(segment.centreline_mm);
  const line = straight(curb.kerb_line_mm);
  if (centre === undefined) return { state: 'waiting', need: 'bent_street' };
  if (line === undefined) return { state: 'waiting', need: 'bent_street' };
  const origin = plan(centre[0]);
  const direction = between(origin, plan(centre[1]), where);
  if (!runsWith(direction, line, where)) return { state: 'waiting', need: 'bent_street' };
  const onLeft = curb.side === 'left';
  const outward = onLeft ? leftOf(direction) : rightOf(direction);
  const height = curb.kerb_height_mm as number;
  const kerbWidth = curb.kerb_width_mm as number;
  const footwayWidth = curb.footway_width_mm as number;
  const rise = floorDivide(multiply(footwayWidth, curb.footway_crossfall_millionths as number, where), CORNER_LENGTH_SCALE, where);
  const raised = (point: Space, by: number): Space => [point[0], point[1], add(point[2], by, where)];
  const out = (point: Space, distance: number, up: number): Space => {
    const at = moved(plan(point), alongByCornerRule(outward, distance, where), where);
    return [at[0], at[1], add(point[2], up, where)];
  };
  const [k0, k1] = line;
  const top0 = raised(k0, height);
  const top1 = raised(k1, height);
  const back0 = out(k0, kerbWidth, height);
  const back1 = out(k1, kerbWidth, height);
  const footway0 = out(k0, add(kerbWidth, footwayWidth, where), add(height, rise, where));
  const footway1 = out(k1, add(kerbWidth, footwayWidth, where), add(height, rise, where));

  // The face, seen from the carriageway: the kerb point on the viewer's left first.
  const [a, b] = onLeft ? [k0, k1] : [k1, k0];
  const facePoints: Space[] = [a, b, raised(b, height), raised(a, height)];
  const faceVertices: number[] = [];
  const faceCoordinates: number[] = [];
  for (const point of facePoints) {
    faceVertices.push(point[0], point[1], point[2]);
    faceCoordinates.push(
      measureAgainst(origin, direction, plan(point), where).along,
      subtract(heightOn(line, direction, plan(point), where), point[2], where),
    );
  }
  const face: Piece = {
    vertices: faceVertices,
    triangles: QUAD,
    surface: { role: 'kerb', orientation: 'vertical', coordinates: faceCoordinates },
  };
  const topQuad: Space[] = onLeft ? [top0, top1, back1, back0] : [back0, back1, top1, top0];
  const footwayQuad: Space[] = onLeft ? [back0, back1, footway1, footway0] : [footway0, footway1, back1, back0];
  return {
    state: 'drawn',
    pieces: [
      face,
      piece(horizontal(topQuad, origin, direction, where), QUAD, 'kerb', 'horizontal'),
      piece(horizontal(footwayQuad, origin, direction, where), QUAD, 'footway', 'horizontal'),
    ],
  };
}
