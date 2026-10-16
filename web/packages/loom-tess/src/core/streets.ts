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
 * STRAIGHT IN PLAN. A centreline or a kerb line is a RUN: two points or more, every piece running
 * the same way as the whole line, so it is straight in plan and may bend only in height (a town
 * laid on its land climbs between its junctions' mouths). Its height at a point is read on the piece
 * the point's position falls in, `z_i + floor((z_{i+1} - z_i) * (p - p_i) / (p_{i+1} - p_i))`, and
 * past either end on the end piece, so a line of two points is read exactly as before. A line that
 * bends in plan, a kerb line not running with its centreline, or a line that bends in height inside
 * its segment's strip is the `bent_street` waiting state and draws nothing.
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
 * THE CURB'S CORNER, which the curb stating `corner_radius_mm` owns up to its follower's tangent
 * point (`exulanica.grammar.grammars.city.corners`). `P` is where this curb's walk round its face
 * ends and `Q` where its follower's begins; the arc is the fillet arc rule's, about the centre that
 * rule finds, and it carries the heights of `P` and `Q` by the same bisection the arc's points are
 * placed by.
 *   1. The kerb face runs along that arc and rises `kerb_height_mm`, facing the carriageway.
 *   2. The kerb top lies between the arc and the back arc, `kerb_width_mm` further toward the
 *      centre, which is radius `r - kerb_width_mm` at a convex corner.
 *   3. THE FOOTWAY WEDGE IS THE PIE SLICE LESS THE BLOCKS THE CURB NAMES. The slice runs from the
 *      back arc in to the centre, between the two tangent points' normals, which is everything
 *      between them that is not carriageway and not kerb. What of it is the building's is the
 *      block's own ring, which the grammar holds to pass exactly through the frontage corner `F`
 *      where the two frontage lines meet, so carving by the block gives the wedge the corner rule
 *      describes without this rule placing `F` at all. That matters beyond tidiness: on a corner
 *      whose radius is large against its footway, `F` lies OUTSIDE the arc, the frontage lines
 *      never meet inside the slice, and the wedge is two pieces rather than one. Measured on the
 *      corridor's five tiles: 8 of 48 convex corners with both widths under the radius are that
 *      shape. A rule that placed `F` and walked to it would draw a ring that crosses itself there.
 *      A curb that names no block keeps the whole slice, which is the corner rule's own answer
 *      where a width reaches the radius and the frontage lines never enter the slice at all.
 *   4. The wedge stands at the kerb top's height along the back arc and rises by the curb's
 *      crossfall everywhere else, which is what its box allows.
 *   A CONCAVE CORNER IS NOT DRAWN and says so: the grammar states it as the same partition with the
 *   arc's side reversed, and no corner on the corridor is concave, so there is nothing to hold a
 *   rule for it to. It waits on `concave_corner` rather than being guessed at.
 *
 * THE CURB, its straight part, away from the carriageway along the side's normal:
 *   1. The kerb face is the vertical quad from the kerb line up `kerb_height_mm`, facing the
 *      carriageway. `s` is along the centreline and `t = base - z`, with the kerb line as base.
 *   2. The kerb top is the horizontal quad `kerb_width_mm` wide at the top of the face.
 *   3. The footway is the horizontal quad `footway_width_mm` wide behind the kerb top, rising to
 *      `floor(footway_width_mm * footway_crossfall_millionths / 10^6)` above it at its back.
 *   Kerb top and footway take `s` along the centreline and `t` across it.
 *
 * THE JUNCTION, its carriageway fill inside the kerb arcs, horizontal, `s = x` and `t = y`:
 *   1. Legs are taken in the junction's order, counter-clockwise from +x. A leg's outward direction
 *      runs from the node along its segment; its outward-left and outward-right curbs are the
 *      segment's left and right curbs when the segment starts at the node, and the other way round
 *      when it ends there.
 *   2. The ring runs, for each leg: across its mouth, the segment rule's five points at the node's
 *      end of its strip from outward-right to outward-left; back along the outward-left kerb line to
 *      its end nearest the node, `Q`; then round the corner to the next leg. That corner belongs to
 *      the next leg's outward-right curb, which must name this leg's outward-left curb as its next
 *      curb: its walk ends at `P`, nearest the node. With radius 0, `P` is `Q`. Otherwise the ring
 *      takes the fillet arc rule's points from `Q` back to `P`, with the least power of two
 *      segments whose chords keep within the projection's resolution (`filletSegmentsWithin`).
 *   3. Repeated consecutive points are dropped, and the ring is cut by the ring rule.
 *   A leg whose segment, curbs or node the tile does not carry needs `junction_legs`.
 *
 * Every triangle is counter-clockwise seen from its front: from above for a horizontal surface,
 * from the carriageway for a kerb face.
 */
import type { Piece, SurfaceExpansion } from './pieces.js';
import { alongByCornerRule, filletArc, filletCentre, filletSegmentsWithin } from './fillet-arc.js';
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
import { openRegions } from './piece-carve.js';
import { triangulateRing } from './ring-triangulation.js';

export type StreetFields = { readonly [name: string]: unknown };

/** What a street rule gives: surfaces to draw, or the rule it waits on, one of `Need`. */
export type StreetResult<Need extends string> =
  | { readonly state: 'drawn'; readonly pieces: readonly Piece[] }
  | { readonly state: 'waiting'; readonly need: Need };

/** What a segment's strip waits on. */
export type StripNeed = 'bent_street' | 'street_curbs';

/** A line of a record, straight in plan: two points or more. */
type Run = readonly Space[];

const plan = (point: Space): Plan => [point[0], point[1]];

function between(from: Plan, to: Plan, where: string): Plan {
  return [subtract(to[0], from[0], where), subtract(to[1], from[1], where)];
}

function moved(point: Plan, by: Plan, where: string): Plan {
  return [add(point[0], by[0], where), add(point[1], by[1], where)];
}

/**
 * A line of a record that is straight in plan: two points or more, every piece running the same way
 * as the whole line. Undefined for one of fewer points or one that bends in plan.
 */
function straightRun(points: unknown, where: string): Run | undefined {
  const line = points as readonly Space[];
  if (line.length < 2) return undefined;
  if (line.length === 2) return line;
  const whole = between(plan(line[0]!), plan(line[line.length - 1]!), where);
  for (let index = 0; index + 1 < line.length; index += 1) {
    const piece = between(plan(line[index]!), plan(line[index + 1]!), where);
    if (crossVectors(whole, piece, where) !== 0) return undefined;
    if (dot(whole, piece, where) <= 0) return undefined;
  }
  return line;
}

/** The first and last points of a run: its ends in plan. */
const runEnds = (line: Run): readonly [Space, Space] => [line[0]!, line[line.length - 1]!];

/** Whether every piece of `line` runs with `direction`: parallel and the same way. */
function runsWith(direction: Plan, line: Run, where: string): boolean {
  for (let index = 0; index + 1 < line.length; index += 1) {
    const piece = between(plan(line[index]!), plan(line[index + 1]!), where);
    if (crossVectors(direction, piece, where) !== 0) return false;
    if (dot(direction, piece, where) <= 0) return false;
  }
  return true;
}

/** The unit normals of a direction, unscaled: left `(-dy, dx)` and right `(dy, -dx)`. */
const leftOf = (direction: Plan): Plan => [-direction[1], direction[0]];
const rightOf = (direction: Plan): Plan => [direction[1], -direction[0]];

/**
 * The height at `point` on a run, by positions along `direction`: on the piece the point's position
 * falls in (the end piece past either end), `z_i + floor((z_{i+1} - z_i) * p / p1)`, with `p` and
 * `p1` the positions of the point and of the piece's far end from its near end,
 * `dot(point - start, direction)`. A run of two points is one piece, read as it always was.
 */
function heightOn(line: Run, direction: Plan, point: Plan, where: string): number {
  let at = 0;
  for (let index = 1; index + 1 < line.length; index += 1) {
    if (dot(between(plan(line[index]!), point, where), direction, where) >= 0) at = index;
  }
  const [near, far] = [line[at]!, line[at + 1]!];
  const end = dot(between(plan(near), plan(far), where), direction, where);
  const here = dot(between(plan(near), point, where), direction, where);
  if (end === 0) throw new GeometryError(`${where} measures a height on a line of no length`);
  return add(near[2], floorDivide(multiply(subtract(far[2], near[2], where), here, where), end, where), where);
}

/**
 * The height at `point` on a record's line, as every street rule reads it: on the piece the point's
 * position falls in, positions along the line's own first-to-last direction (any direction the line
 * runs with gives the same reading). Undefined for a line that bends in plan.
 */
export function heightAlong(points: unknown, point: Plan, where: string): number | undefined {
  const line = straightRun(points, where);
  if (line === undefined) return undefined;
  const [first, last] = runEnds(line);
  return heightOn(line, between(plan(first), plan(last), where), point, where);
}

/** Whether any point inside a run lies strictly between two positions along `direction`. */
function bendsBetween(line: Run, direction: Plan, origin: Plan, low: number, high: number, where: string): boolean {
  for (let index = 1; index + 1 < line.length; index += 1) {
    const at = dot(between(origin, plan(line[index]!), where), direction, where);
    if (low < at && at < high) return true;
  }
  return false;
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

/** One end of a segment's strip: its five points across, from the left kerb line to the right. */
export interface StripEnd {
  readonly left: Space;
  readonly leftGutter: Space;
  readonly crown: Space;
  readonly rightGutter: Space;
  readonly right: Space;
}

/** A segment's straight frame and the two ends of its strip, or the rule it waits on. */
export type SegmentEnds =
  | {
      readonly state: 'ends';
      readonly origin: Plan;
      readonly direction: Plan;
      readonly start: StripEnd;
      readonly end: StripEnd;
    }
  | Extract<StreetResult<StripNeed>, { state: 'waiting' }>;

/**
 * Where a segment's strip starts and ends, by the segment rule's first three steps. The junction
 * rule takes its mouths from here, so a strip and the junction it opens into share their points.
 */
export function segmentEnds(
  segment: StreetFields,
  left: StreetFields | undefined,
  right: StreetFields | undefined,
  where: string,
): SegmentEnds {
  if (left === undefined) return { state: 'waiting', need: 'street_curbs' };
  if (right === undefined) return { state: 'waiting', need: 'street_curbs' };
  const centre = straightRun(segment.centreline_mm, where);
  const leftLine = straightRun(left.kerb_line_mm, where);
  const rightLine = straightRun(right.kerb_line_mm, where);
  const bent = { state: 'waiting', need: 'bent_street' } as const;
  if (centre === undefined) return bent;
  if (leftLine === undefined) return bent;
  if (rightLine === undefined) return bent;
  const origin = plan(centre[0]!);
  const direction = between(origin, plan(runEnds(centre)[1]), where);
  if (!runsWith(direction, leftLine, where)) return bent;
  if (!runsWith(direction, rightLine, where)) return bent;
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
  const crown = (a: Space, b: Space): Space => {
    const middle: Plan = [floorDivide(add(a[0], b[0], where), 2, where), floorDivide(add(a[1], b[1], where), 2, where)];
    return [middle[0], middle[1], heightOn(centre, direction, middle, where)];
  };
  const gutterLine = (kerb: Space, towardCrown: Plan, crownPoint: Space, gutter: number): Space => {
    const at = moved(plan(kerb), alongByCornerRule(towardCrown, gutter, where), where);
    const rise = floorDivide(multiply(subtract(crownPoint[2], kerb[2], where), multiply(gutter, 2, where), where), width, where);
    return [at[0], at[1], add(kerb[2], rise, where)];
  };
  const stripEnd = (leftPoint: Space, rightPoint: Space): StripEnd => {
    const crownPoint = crown(leftPoint, rightPoint);
    return {
      left: leftPoint,
      leftGutter: gutterLine(leftPoint, rightOf(direction), crownPoint, left.gutter_width_mm as number),
      crown: crownPoint,
      rightGutter: gutterLine(rightPoint, leftOf(direction), crownPoint, right.gutter_width_mm as number),
      right: rightPoint,
    };
  };
  const [left0, right0] = endPoints(runEnds(leftLine)[0], runEnds(rightLine)[0], true);
  const [left1, right1] = endPoints(runEnds(leftLine)[1], runEnds(rightLine)[1], false);
  const [low, high] = [position(plan(left0)), position(plan(left1))];
  if (low >= high) return { state: 'waiting', need: 'street_curbs' };
  // A line may bend in height at the strip's ends and beyond them, never inside it: the strip is one
  // slope from end to end.
  for (const line of [centre, leftLine, rightLine]) {
    if (bendsBetween(line, direction, origin, low, high, where)) return bent;
  }
  return { state: 'ends', origin, direction, start: stripEnd(left0, right0), end: stripEnd(left1, right1) };
}

/** The segment's carriageway and gutter surfaces, between its two curbs' kerb lines. */
export function segmentSurfaces(
  segment: StreetFields,
  left: StreetFields | undefined,
  right: StreetFields | undefined,
  where: string,
): StreetResult<StripNeed> {
  const ends = segmentEnds(segment, left, right, where);
  if (ends.state !== 'ends') return ends;
  const { origin, direction, start: s, end: e } = ends;
  const width = segment.carriageway_width_mm as number;
  const leftGutter = left!.gutter_width_mm as number;
  const rightGutter = right!.gutter_width_mm as number;
  const pieces: Piece[] = [];
  const addQuad = (points: Space[], triangles: number[], quad: readonly Space[]): void => {
    const base = points.length;
    points.push(...quad);
    triangles.push(...QUAD.map((corner) => base + corner));
  };
  const carriageway: Space[] = [];
  const carriagewayTriangles: number[] = [];
  if (multiply(leftGutter, 2, where) < width) addQuad(carriageway, carriagewayTriangles, [s.crown, e.crown, e.leftGutter, s.leftGutter]);
  if (multiply(rightGutter, 2, where) < width) addQuad(carriageway, carriagewayTriangles, [s.rightGutter, e.rightGutter, e.crown, s.crown]);
  if (carriageway.length > 0) {
    pieces.push(piece(horizontal(carriageway, origin, direction, where), carriagewayTriangles, 'carriageway', 'horizontal'));
  }
  const gutters: Space[] = [];
  const gutterTriangles: number[] = [];
  if (leftGutter > 0) addQuad(gutters, gutterTriangles, [s.leftGutter, e.leftGutter, e.left, s.left]);
  if (rightGutter > 0) addQuad(gutters, gutterTriangles, [s.right, e.right, e.rightGutter, s.rightGutter]);
  if (gutters.length > 0) {
    pieces.push(piece(horizontal(gutters, origin, direction, where), gutterTriangles, 'gutter', 'horizontal'));
  }
  if (pieces.length === 0) throw new GeometryError(`${where} has a carriageway of no width`);
  return { state: 'drawn', pieces };
}

/**
 * A curb's straight part: its kerb face, its kerb top and its footway, piece by piece along its kerb
 * line. The step between its footway and a lot behind it at another height is the terrain's to close
 * (`lot-steps.ts`).
 */
export function curbSurfaces(
  curb: StreetFields,
  segment: StreetFields,
  corners: readonly CornerContext[],
  approaches: readonly ApproachContext[],
  where: string,
): StreetResult<'bent_street' | CornerNeed> {
  const centre = straightRun(segment.centreline_mm, where);
  const line = straightRun(curb.kerb_line_mm, where);
  if (centre === undefined) return { state: 'waiting', need: 'bent_street' };
  if (line === undefined) return { state: 'waiting', need: 'bent_street' };
  const origin = plan(centre[0]!);
  const direction = between(origin, plan(runEnds(centre)[1]), where);
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
  const built: { readonly [name: string]: Built } = {
    face: { vertices: [], coordinates: [], triangles: [] },
    top: { vertices: [], coordinates: [], triangles: [] },
    footway: { vertices: [], coordinates: [], triangles: [] },
  };
  // The walk round the face runs from the kerb line's start for a left curb, from its end for a
  // right one: a mitre at the walk's end is the corner this curb turns, one at its start the corner
  // that turns into it, and each gives way on the piece that reaches it.
  const turnedMitre = corners.length === 0 ? undefined : cornerMitre(curb, corners[0]!.follower, where);
  const metMitre = approaches.length === 0 ? undefined : cornerMitre(approaches[0]!.owner, curb, where);
  const pieces = line.length - 1;
  for (let index = 0; index < pieces; index += 1) {
    const [k0, k1] = [line[index]!, line[index + 1]!];
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
    appended(built.face!, { vertices: faceVertices, coordinates: faceCoordinates, triangles: [...QUAD] });
    const topQuad: Space[] = onLeft ? [top0, top1, back1, back0] : [back0, back1, top1, top0];
    appended(built.top!, { ...horizontal(topQuad, origin, direction, where), triangles: [...QUAD] });
    // THE FOOTWAY IS A RING IN WALK ORDER, not a quad, because either end of it may GIVE WAY TO A
    // MITRE. Where a corner's width reaches its radius, this strip and the one it meets would both
    // cover the ground beyond the arc's centre; the corner rule gives each the side of the line from
    // that centre to the frontage corner that its own length runs along. Both those points lie on
    // this strip's own edges by construction, the centre on its end normal and the frontage corner on
    // its frontage line, so the clip adds no point either strip has to find: it replaces the corner of
    // the quad with the two the corner rule names, and the two strips meet on the line between them.
    // Each piece of a kerb line that bends in height is its own ring, so no triangle spans a bend.
    const [walkStartIndex, walkEndIndex] = onLeft ? [0, 1] : [1, 0];
    const reachesWalkEnd = onLeft ? index === pieces - 1 : index === 0;
    const reachesWalkStart = onLeft ? index === 0 : index === pieces - 1;
    const backs = [back0, back1];
    const fronts = [footway0, footway1];
    const turnedHere = reachesWalkEnd ? turnedMitre : undefined;
    const metHere = reachesWalkStart ? metMitre : undefined;
    const [from, to] = [[k0, k1][walkStartIndex]!, [k0, k1][walkEndIndex]!];
    // A footway whose kerb line climbs or falls stands on its own heights up to a ramp into each
    // mitred corner it meets: the mitre's points stand at the corner's level, which one ring would
    // carry along the whole strip. Each ramp is its own ring, and so is the strip between them. A
    // level kerb line, or a strip whose two ramps would cross, keeps its one ring.
    const sloping = line.some((point) => point[2] !== line[0]![2]);
    let endRamp = sloping && turnedHere !== undefined ? rampStart(from, to, turnedHere.frontage, where) : undefined;
    let startRamp = sloping && metHere !== undefined ? rampStart(to, from, metHere.frontage, where) : undefined;
    if (endRamp !== undefined && startRamp !== undefined && !before(from, to, startRamp, endRamp)) {
      endRamp = undefined;
      startRamp = undefined;
    }
    // The kerb top's back and the footway's far edge, across the strip from a point of the kerb line.
    const across = (onKerb: Plan): readonly [Space, Space] => {
      const kerb: Space = [onKerb[0], onKerb[1], heightOn(line, direction, onKerb, where)];
      return [out(kerb, kerbWidth, height), out(kerb, add(kerbWidth, footwayWidth, where), add(height, rise, where))];
    };
    const ringOf = (points: readonly Space[]): void => {
      const kept = points.filter((point, at) => !samePoint(point, points[(at + points.length - 1) % points.length]!));
      appended(built.footway!, {
        ...horizontal(kept, origin, direction, where),
        triangles: [...triangulateRing(kept.map(plan), where)],
      });
    };
    const startEdge = startRamp === undefined ? undefined : across(startRamp);
    const endEdge = endRamp === undefined ? undefined : across(endRamp);
    if (startEdge !== undefined) ringOf([backs[walkStartIndex]!, startEdge[0], startEdge[1], metHere!.frontage, metHere!.centre]);
    if (endEdge !== undefined) ringOf([endEdge[0], backs[walkEndIndex]!, turnedHere!.centre, turnedHere!.frontage, endEdge[1]]);
    const ring: Space[] = [
      startEdge === undefined ? backs[walkStartIndex]! : startEdge[0],
      endEdge === undefined ? backs[walkEndIndex]! : endEdge[0],
    ];
    if (endEdge !== undefined) ring.push(endEdge[1]);
    else if (turnedHere === undefined) ring.push(fronts[walkEndIndex]!);
    else ring.push(turnedHere.centre, turnedHere.frontage);
    if (startEdge !== undefined) ring.push(startEdge[1]);
    else if (metHere === undefined) ring.push(fronts[walkStartIndex]!);
    else ring.push(metHere.frontage, metHere.centre);
    ringOf(ring);
  }
  for (const corner of corners) {
    const turned = curbCorner(curb, corner, origin, direction, where);
    if (turned.state === 'waiting') return turned;
    for (const name of ['face', 'top', 'footway']) appended(built[name]!, turned.parts[name as 'face']);
  }
  // One surface per role and orientation, however many corners the curb turns into its followers.
  return {
    state: 'drawn',
    pieces: [
      piece(built.face!, built.face!.triangles, 'kerb', 'vertical'),
      piece(built.top!, built.top!.triangles, 'kerb', 'horizontal'),
      piece(built.footway!, built.footway!.triangles, 'footway', 'horizontal'),
    ],
  };
}

/**
 * Where a footway whose kerb line climbs or falls begins its ramp into the mitred corner at `far`:
 * the point of the kerb line from `near` to `far` (a piece along x or along y, walked toward `far`)
 * as far before the mitre's frontage corner as `far` lies beyond it, so the ramp is as long as the
 * stretch of strip the mitre gives the corner. Undefined where the piece runs along neither axis or
 * that point does not lie strictly between `near` and the frontage corner.
 */
function rampStart(near: Space, far: Space, frontage: Space, where: string): Plan | undefined {
  const axis = near[1] === far[1] ? 0 : near[0] === far[0] ? 1 : undefined;
  if (axis === undefined) return undefined;
  const start = subtract(multiply(2, frontage[axis], where), far[axis], where);
  const inside = near[axis] < frontage[axis]
    ? near[axis] < start && start < frontage[axis]
    : frontage[axis] < start && start < near[axis];
  if (!inside) return undefined;
  return axis === 0 ? [start, near[1]] : [near[0], start];
}

/** Whether, walking a piece along x or along y from `near` to `far`, `first` comes before `second`. */
function before(near: Space, far: Space, first: Plan, second: Plan): boolean {
  const axis = near[1] === far[1] ? 0 : 1;
  return near[axis] < far[axis] ? first[axis] < second[axis] : second[axis] < first[axis];
}

/** What a curb's corner waits on when this version does not draw it. */
export type CornerNeed = 'concave_corner';

/**
 * Where the two straight strips that meet at a corner give way to each other, when the corner
 * mitres: `centre` is the arc's centre, on both strips' end normals, and `frontage` is the corner
 * `F` where the two frontage lines meet, floored to millimetres. `height` is what the corner's
 * OWNER puts the footway at there, which both strips take, so the two cannot disagree at a point
 * they share. Undefined when no width reaches the radius, where the frontage lines never enter the
 * slice and the strips do not overlap.
 */
export interface CornerMitre {
  readonly centre: Space;
  readonly frontage: Space;
}

/** A corner's share of each of the curb's three surfaces, or the rule it waits on. */
export type CornerResult =
  | {
      readonly state: 'drawn';
      readonly parts: { readonly face: Built; readonly top: Built; readonly footway: Built };
      readonly mitre: CornerMitre | undefined;
    }
  | { readonly state: 'waiting'; readonly need: CornerNeed };

/** The curb whose corner ENDS at this one's start: the one that states the radius and owns it. */
export interface ApproachContext {
  readonly owner: StreetFields;
}

/** What a curb's corner needs of the tile beyond the curb itself. */
export interface CornerContext {
  /** The curb this one is followed by round the face, which the tile must carry. */
  readonly follower: StreetFields;
  /** The rings of the blocks the curb names, which are the building side of its frontage. */
  readonly blocks: readonly (readonly Plan[])[];
  /** The resolution the projection states, which the arc's chords keep within. */
  readonly resolutionMm: number;
}

/**
 * The surfaces of the corner a curb turns into its follower: the kerb face along the arc, the kerb
 * top, and the footway wedge. Empty when the curb states no radius. `origin` and `direction` are
 * the owning segment's, since every one of these surfaces takes the segment's along-centreline
 * coordinate, which the grammar fixes for a curb's surfaces however the kerb turns.
 */
export function curbCorner(
  curb: StreetFields,
  corner: CornerContext,
  origin: Plan,
  direction: Plan,
  where: string,
): CornerResult {
  const radius = curb.corner_radius_mm as number;
  const nothing: Built = { vertices: [], coordinates: [], triangles: [] };
  if (radius === 0) return { state: 'drawn', parts: { face: nothing, top: nothing, footway: nothing }, mitre: undefined };
  const [beforeP, p] = walkEnd(curb);
  const [q, afterQ] = walkStart(corner.follower);
  const into = between(plan(beforeP), plan(p), where);
  const out = between(plan(q), plan(afterQ), where);
  const turning = crossVectors(into, out, where);
  if (turning === 0) throw new GeometryError(`${where} states a radius on a corner that runs straight on`);
  if (turning < 0) return { state: 'waiting', need: 'concave_corner' };
  const kerbWidth = curb.kerb_width_mm as number;
  if (radius <= kerbWidth) throw new GeometryError(`${where} has a convex corner radius that leaves its kerb top no back arc`);
  const height = curb.kerb_height_mm as number;
  const footwayWidth = curb.footway_width_mm as number;
  const rise = floorDivide(multiply(footwayWidth, curb.footway_crossfall_millionths as number, where), CORNER_LENGTH_SCALE, where);
  const segments = filletSegmentsWithin(p, into, q, out, radius, corner.resolutionMm, segmentBound(radius), where);
  const arc = filletArc(p, into, q, out, radius, segments, where);
  const centre = filletCentre(p, into, q, out, radius, where);
  const back = arc.map((point): Space => {
    const at = moved(centre, alongByCornerRule(between(centre, plan(point), where), subtract(radius, kerbWidth, where), where), where);
    return [at[0], at[1], add(point[2], height, where)];
  });

  // The face, seen from the carriageway, which is outside the arc: each chord from its far end to
  // its near one, so the quad reads the same way round as the straight part's.
  const faceVertices: Space[] = [];
  const faceTriangles: number[] = [];
  for (let step = 0; step + 1 < arc.length; step += 1) {
    const [a, b] = [arc[step + 1]!, arc[step]!];
    const first = faceVertices.length;
    faceVertices.push(a, b, [b[0], b[1], add(b[2], height, where)], [a[0], a[1], add(a[2], height, where)]);
    for (const index of QUAD) faceTriangles.push(first + index);
  }
  const topVertices: Space[] = [];
  const topTriangles: number[] = [];
  for (let step = 0; step + 1 < arc.length; step += 1) {
    const first = topVertices.length;
    const [a, b] = [arc[step]!, arc[step + 1]!];
    topVertices.push([a[0], a[1], add(a[2], height, where)], [b[0], b[1], add(b[2], height, where)], back[step + 1]!, back[step]!);
    for (const index of QUAD) topTriangles.push(first + index);
  }

  // The wedge: the slice from the back arc in to the centre, less the blocks the curb names. Its
  // height is the kerb top's on the back arc and a crossfall above it everywhere else, so a point
  // the carve makes inside the slice takes the raised height, and only the back arc's own points
  // keep the kerb top's.
  const onBack = new Map<string, number>();
  for (const point of back) onBack.set(`${String(point[0])} ${String(point[1])}`, point[2]);
  const apex = add(floorDivide(add(p[2], q[2], where), 2, where), height, where);
  const reach = add(kerbWidth, footwayWidth, where);
  const follower = add(corner.follower.kerb_width_mm as number, corner.follower.footway_width_mm as number, where);
  // A corner MITRES when a width reaches the radius: the frontage lines then never enter the slice,
  // the slice runs to the centre, and the two straight strips, which would overlap beyond it, give
  // way to each other on the line from the centre to the frontage corner. Otherwise the frontage
  // lines cut the slice, and what they cut off is the building's: the blocks the curb names carve
  // it where the tile carries them, and the frontage quadrilateral carves it whether or not it
  // does, so a block the tile does not carry cannot let a footway run into a building.
  const mitre = cornerMitre(curb, corner.follower, where);
  const mitres = mitre !== undefined;
  const frontage = frontageCorner(p, into, q, out, reach, follower, where);
  const taken: (readonly Plan[])[] = [...corner.blocks];
  if (!mitres) {
    taken.push([
      moved(plan(p), alongByCornerRule(leftOf(into), reach, where), where),
      frontage,
      moved(plan(q), alongByCornerRule(leftOf(out), follower, where), where),
      [centre[0], centre[1]],
    ]);
  }
  // The wedge stands at the kerb top's height on the back arc, and a crossfall above it elsewhere:
  // the full crossfall on the frontage, which is a footway width from the back arc, and the
  // crossfall of its own distance at the centre, which is nearer than that whenever a corner
  // mitres. Both are what the corner rule's box allows, and the second is what the strips that
  // meet there take, so the wedge and the strips cannot disagree at the centre.
  const atCentre = mitre === undefined
    ? add(apex, floorDivide(multiply(subtract(radius, kerbWidth, where), curb.footway_crossfall_millionths as number, where), CORNER_LENGTH_SCALE, where), where)
    : mitre.centre[2];
  const centreKey = `${String(centre[0])} ${String(centre[1])}`;
  const slice: Plan[] = [...back.map(plan), [centre[0], centre[1]]];
  const wedgeVertices: Space[] = [];
  const wedgeTriangles: number[] = [];
  for (const walk of openRegions(slice, taken, where)) {
    const first = wedgeVertices.length;
    for (const point of walk) {
      const key = `${String(point[0])} ${String(point[1])}`;
      const kerbTop = onBack.get(key);
      let z = add(apex, rise, where);
      if (kerbTop !== undefined) z = kerbTop;
      else if (key === centreKey) z = atCentre;
      wedgeVertices.push([point[0], point[1], z]);
    }
    for (const index of triangulateRing(walk, where)) wedgeTriangles.push(first + index);
  }
  return {
    state: 'drawn',
    parts: {
      face: { ...vertical(faceVertices, origin, direction, p[2], where), triangles: faceTriangles },
      top: { ...horizontal(topVertices, origin, direction, where), triangles: topTriangles },
      footway: { ...horizontal(wedgeVertices, origin, direction, where), triangles: wedgeTriangles },
    },
    mitre,
  };
}

/**
 * The mitre of the corner `curb` turns into `follower`, or undefined when it turns none, when it
 * turns the other way, or when no width reaches the radius and the two strips do not overlap. Read
 * by the corner itself and by BOTH strips that meet on it, so the three take the same two points.
 */
export function cornerMitre(curb: StreetFields, follower: StreetFields, where: string): CornerMitre | undefined {
  const radius = curb.corner_radius_mm as number;
  if (radius === 0) return undefined;
  const [beforeP, p] = walkEnd(curb);
  const [q, afterQ] = walkStart(follower);
  const into = between(plan(beforeP), plan(p), where);
  const out = between(plan(q), plan(afterQ), where);
  if (crossVectors(into, out, where) <= 0) return undefined;
  const kerbWidth = curb.kerb_width_mm as number;
  const reach = add(kerbWidth, curb.footway_width_mm as number, where);
  const other = add(follower.kerb_width_mm as number, follower.footway_width_mm as number, where);
  if (reach < radius && other < radius) return undefined;
  const crossfall = curb.footway_crossfall_millionths as number;
  const apex = add(floorDivide(add(p[2], q[2], where), 2, where), curb.kerb_height_mm as number, where);
  const rise = floorDivide(multiply(curb.footway_width_mm as number, crossfall, where), CORNER_LENGTH_SCALE, where);
  const centre = filletCentre(p, into, q, out, radius, where);
  const frontage = frontageCorner(p, into, q, out, reach, other, where);
  return {
    centre: [centre[0], centre[1], add(apex, floorDivide(multiply(subtract(radius, kerbWidth, where), crossfall, where), CORNER_LENGTH_SCALE, where), where)],
    frontage: [frontage[0], frontage[1], add(apex, rise, where)],
  };
}

/**
 * The frontage corner `F`: where the line a `reach` to the left of the piece arriving at `p` meets
 * the line a `follower` reach to the left of the piece leaving `q`, each axis floored, which is how
 * every other point of a corner is placed. The grammar holds `F` to be a corner of the block ring
 * where the curb has a block, and there it is a whole number of millimetres; where it is not, both
 * strips and the wedge take the same floored point, so they meet on it whatever it rounded from.
 */
function frontageCorner(p: Space, into: Plan, q: Space, out: Plan, reach: number, follower: number, where: string): Plan {
  const first = moved(plan(p), alongByCornerRule(leftOf(into), reach, where), where);
  const second = moved(plan(q), alongByCornerRule(leftOf(out), follower, where), where);
  const numerator = crossVectors(between(first, second, where), out, where);
  const denominator = crossVectors(into, out, where);
  return [
    add(first[0], floorDivide(multiply(into[0], numerator, where), denominator, where), where),
    add(first[1], floorDivide(multiply(into[1], numerator, where), denominator, where), where),
  ];
}

/** One surface being built: its vertices, their surface coordinates, and its triangles over them. */
interface Built {
  readonly vertices: number[];
  readonly coordinates: number[];
  readonly triangles: number[];
}

/** Another surface's vertices and triangles, added to one being built, indices moved along. */
function appended(into: Built, from: Built): void {
  const first = into.vertices.length / 3;
  for (const value of from.vertices) into.vertices.push(value);
  for (const value of from.coordinates) into.coordinates.push(value);
  for (const index of from.triangles) into.triangles.push(first + index);
}

/** Vertices with vertical surface coordinates: `s` along the centreline and `t = base - z`. */
function vertical(points: readonly Space[], origin: Plan, direction: Plan, base: number, where: string): Measured {
  const vertices: number[] = [];
  const coordinates: number[] = [];
  for (const point of points) {
    vertices.push(point[0], point[1], point[2]);
    coordinates.push(measureAgainst(origin, direction, plan(point), where).along, subtract(base, point[2], where));
  }
  return { vertices, coordinates };
}

/** How a street rule finds the records a record names: carried records only. */
export interface StreetLookup {
  /** The carried record with this identity, or undefined when the tile does not carry it. */
  readonly record: (identity: string) => StreetFields | undefined;
  /** A segment's carried curbs by side. */
  readonly curbs: (segment: string) => { readonly left: StreetFields | undefined; readonly right: StreetFields | undefined };
}

const samePoint = (a: Space, b: Space): boolean => a[0] === b[0] && a[1] === b[1] && a[2] === b[2];

/**
 * A curb's kerb line in the order a counter-clockwise walk round its face takes it, read by the
 * corner rule at its two ends as the grammar's corners are (`corners.corner_of`): the walk's last
 * piece arrives at `P`, its first piece leaves `Q`. A kerb line that bends in plan has no walk.
 */
function walkOf(curb: StreetFields): Run {
  const line = straightRun(curb.kerb_line_mm, `curb ${String(curb.identity)}`);
  if (line === undefined) throw new GeometryError(`curb ${String(curb.identity)} has a kerb line that bends in plan`);
  return curb.side === 'left' ? line : [...line].reverse();
}

/** The piece a curb's walk arrives at its end `P` along: the point before `P`, and `P`. */
function walkEnd(curb: StreetFields): readonly [Space, Space] {
  const walk = walkOf(curb);
  return [walk[walk.length - 2]!, walk[walk.length - 1]!];
}

/** The piece a curb's walk leaves its start `Q` along: `Q`, and the point after it. */
function walkStart(curb: StreetFields): readonly [Space, Space] {
  const walk = walkOf(curb);
  return [walk[0]!, walk[1]!];
}

/** The power of two a fillet's segments may not pass: the least one at or above its radius. */
function segmentBound(radius: number): number {
  let bound = 1;
  while (bound < radius) bound *= 2;
  return bound;
}

/** The junction's carriageway fill, by the junction rule. */
export function junctionSurface(junction: StreetFields, lookup: StreetLookup, resolutionMm: number, where: string): StreetResult<StripNeed | 'junction_legs'> {
  const legsNeeded = { state: 'waiting', need: 'junction_legs' } as const;
  const node = lookup.record(junction.node_identity as string);
  if (node === undefined) return legsNeeded;
  const nodePlan: Plan = [node.x_mm as number, node.y_mm as number];
  interface Leg { readonly mouth: readonly Space[]; readonly outwardLeft: StreetFields; readonly outwardRight: StreetFields }
  const legs: Leg[] = [];
  for (const identity of junction.segment_identities as readonly string[]) {
    const segment = lookup.record(identity);
    if (segment === undefined) return legsNeeded;
    const { left, right } = lookup.curbs(identity);
    if (left === undefined) return legsNeeded;
    if (right === undefined) return legsNeeded;
    const ends = segmentEnds(segment, left, right, where);
    if (ends.state !== 'ends') return ends;
    const [first, last] = runEnds(straightRun(segment.centreline_mm, where)!);
    const atStart = first[0] === nodePlan[0] && first[1] === nodePlan[1];
    const atEnd = last[0] === nodePlan[0] && last[1] === nodePlan[1];
    if (atStart === atEnd) throw new GeometryError(`${where}: segment ${identity} does not meet the junction's node at one end`);
    const e = atStart ? ends.start : ends.end;
    legs.push(atStart
      ? { mouth: [e.right, e.rightGutter, e.crown, e.leftGutter, e.left], outwardLeft: left, outwardRight: right }
      : { mouth: [e.left, e.leftGutter, e.crown, e.rightGutter, e.right], outwardLeft: right, outwardRight: left });
  }
  const ring: Space[] = [];
  const push = (point: Space): void => {
    if (ring.length > 0 && samePoint(ring[ring.length - 1]!, point)) return;
    ring.push(point);
  };
  for (const [index, leg] of legs.entries()) {
    const next = legs[(index + 1) % legs.length]!;
    for (const point of leg.mouth) push(point);
    const a = leg.outwardLeft;
    const b = next.outwardRight;
    const [q, afterQ] = walkStart(a);
    const [beforeP, p] = walkEnd(b);
    push(q);
    if ((b.next_curb_identity as readonly string[])[0] !== a.identity) return legsNeeded;
    const radius = b.corner_radius_mm as number;
    if (radius === 0) {
      if (!samePoint(p, q)) throw new GeometryError(`${where}: a corner of no radius whose tangent points differ`);
      continue;
    }
    const into = between(plan(beforeP), plan(p), where);
    const out = between(plan(q), plan(afterQ), where);
    const segments = filletSegmentsWithin(p, into, q, out, radius, resolutionMm, segmentBound(radius), where);
    const arc = filletArc(p, into, q, out, radius, segments, where);
    for (let step = segments - 1; step > 0; step -= 1) push(arc[step]!);
    push(p);
  }
  if (ring.length > 1 && samePoint(ring[0]!, ring[ring.length - 1]!)) ring.pop();
  const triangles = triangulateRing(ring.map(plan), where);
  const vertices: number[] = [];
  const coordinates: number[] = [];
  for (const point of ring) {
    vertices.push(point[0], point[1], point[2]);
    coordinates.push(point[0], point[1]);
  }
  return {
    state: 'drawn',
    pieces: [{ vertices, triangles, surface: { role: 'carriageway', orientation: 'horizontal', coordinates } }],
  };
}
