/**
 * BUILDING A SURFACE OF FLAT FACES, IN INTEGERS, IN THE GRAMMAR'S OWN FRAMES.
 *
 * What the massing rule and the facade rule share: a surface is a role, an orientation and a run of
 * triangles, and every vertex carries the surface coordinates the grammar fixes for that role and
 * orientation (`common`). A vertical face runs `s` along its own edge from that edge's start and
 * takes `t = base - z`, pointing down; a horizontal one takes `s = x` and `t = y` in plan.
 *
 * Points along an edge are measured by the corner rule, in millimetres, exactly as the grammar
 * measures a piece's length, and a point at a distance along or across an edge is floored onto the
 * lattice: the answer is integers, never a rounded fraction of a metre.
 */
import { alongByCornerRule } from './fillet-arc.js';
import { triangulateRing } from './ring-triangulation.js';
import { add, floorDivide, measureAgainst, multiply, subtract } from './integer-math.js';
import type { Plan } from './integer-math.js';
import type { Piece, SurfaceExpansion } from './pieces.js';
import type { SurfaceOrientation } from './triangle-digest.js';

/**
 * One rectangle of a tier edge, in that edge's own frame, that a face draws over: the building's
 * own wall gives up exactly this and keeps the rest.
 */
export interface FaceCover {
  readonly tier: number;
  readonly edge: number;
  readonly low: number;
  readonly high: number;
  readonly base: number;
  readonly top: number;
}

export const HORIZONTAL: SurfaceOrientation = 'horizontal';
export const VERTICAL: SurfaceOrientation = 'vertical';

/** An edge a face is laid out along, with the length the corner rule measures it at. */
export interface FaceEdge {
  readonly from: Plan;
  readonly to: Plan;
  readonly run: number;
}

/** One surface of a record: its triangles, and each vertex's position and surface coordinates. */
export class Surface {
  readonly vertices: number[] = [];
  readonly triangles: number[] = [];
  readonly coordinates: number[] = [];

  constructor(readonly role: string, readonly orientation: SurfaceOrientation) {}

  /** A corner at a height, with its own surface coordinates. */
  corner(point: Plan, height: number, s: number, t: number): number {
    const index = this.vertices.length / 3;
    this.vertices.push(point[0], point[1], height);
    this.coordinates.push(s, t);
    return index;
  }

  /** A face of three or more corners, already in order, cut into a fan. */
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

/** Every surface that drew anything, as pieces, in the order they were given. */
export function piecesOf(surfaces: readonly Surface[]): Piece[] {
  const pieces: Piece[] = [];
  for (const surface of surfaces) {
    const piece = surface.piece();
    if (piece !== undefined) pieces.push(piece);
  }
  return pieces;
}

/** The point at a distance along a plan segment whose whole length is `run`, floored. */
export function alongEdge(from: Plan, to: Plan, distance: number, run: number, where: string): Plan {
  if (distance <= 0) return from;
  if (distance >= run) return to;
  const axis = (index: 0 | 1): number => add(
    from[index],
    floorDivide(multiply(subtract(to[index], from[index], where), distance, where), run, where),
    where,
  );
  return [axis(0), axis(1)];
}

/** The length of a plan segment, as the grammar's corner rule measures it. */
export function runOf(from: Plan, to: Plan, where: string): number {
  return measureAgainst(from, [subtract(to[0], from[0], where), subtract(to[1], from[1], where)], to, where).along;
}

/**
 * A point moved off a face by a distance, along the face's own outward direction: the right of the
 * edge, since a ring is counter-clockwise and its inside is on the left. A negative distance moves
 * into the building, which is what a recess is.
 */
export function offFace(point: Plan, from: Plan, to: Plan, distance: number, where: string): Plan {
  if (distance === 0) return point;
  const outward: Plan = [subtract(to[1], from[1], where), subtract(from[0], to[0], where)];
  const step = alongByCornerRule(outward, distance < 0 ? -distance : distance, where);
  const sign = distance < 0 ? -1 : 1;
  return [add(point[0], multiply(step[0], sign, where), where), add(point[1], multiply(step[1], sign, where), where)];
}

/**
 * A vertical face over part of an edge, from `base` to `top`, facing the way the edge does, set off
 * the edge by `depth` (negative into the building). `s` runs along the whole edge from its start,
 * so two faces of one surface that share a line share their coordinates.
 */
export function faceOn(
  into: Surface,
  edge: FaceEdge,
  low: number,
  high: number,
  base: number,
  top: number,
  depth: number,
  datum: number,
  where: string,
): void {
  if (top <= base) return;
  if (high <= low) return;
  const at = (along: number): Plan => facePoint(edge, along, depth, where);
  const [west, east] = [at(low), at(high)];
  const [bottom, crown] = [subtract(datum, base, where), subtract(datum, top, where)];
  into.face(
    into.corner(west, base, low, bottom),
    into.corner(east, base, high, bottom),
    into.corner(east, top, high, crown),
    into.corner(west, top, low, crown),
  );
}

/** Where a face's `(u, z)` point stands in plan, set off the edge by `depth`. */
export function facePoint(edge: FaceEdge, along: number, depth: number, where: string): Plan {
  return offFace(alongEdge(edge.from, edge.to, along, edge.run, where), edge.from, edge.to, depth, where);
}

/**
 * A face over a walk in the edge's own `(u, z)` plane, at one depth. The walk turns
 * counter-clockwise in that plane, which is the way round the face's own quad is built, so the face
 * it makes looks the way the edge does.
 *
 * IT IS CUT BY THE RING RULE AND NOT BY A FAN, for the reason every other caller of the carve
 * already is. A carved walk KEEPS THE POINTS ALONG ITS EDGES, so that a neighbour holding the same
 * points on a shared line meets it vertex to vertex (`piece-carve.hullKeepingEdges`). Three of those
 * in a row are collinear, and a fan from one corner turns each such run into a triangle of no area.
 * A triangle of no area has no normal, and a renderer that takes one gets a value that is not
 * finite: fifty of them reached a container here before this was written this way.
 */
export function walkOn(
  into: Surface,
  edge: FaceEdge,
  walk: readonly Plan[],
  depth: number,
  datum: number,
  where: string,
): void {
  const corners = walk.map((point) =>
    into.corner(facePoint(edge, point[0], depth, where), point[1], point[0], subtract(datum, point[1], where)));
  for (const index of triangulateRing(walk, where)) into.triangles.push(corners[index]!);
}

/**
 * THE RETURN OF A HOLE INTO THE WALL: one quad per edge of an outline in the face's `(u, z)` plane,
 * from the face at depth 0 back to `depth` millimetres inside it. Taken in the outline's own order,
 * which turns counter-clockwise, each quad runs front to front and then back, so every one of them
 * faces into the hole rather than out of it.
 *
 * WHAT THE SURFACE COORDINATES CAN SAY, AND WHAT THEY CANNOT. Both corners of a quad's depth take
 * the `(u, z)` of the outline point they were set back from, because the frame the grammar fixes for
 * every role a facade owns is the face's own run and height (`common`), and that frame has no axis
 * across the face. A return is perpendicular to the face, so it has no extent in the frame at all
 * along its depth, and a material on it is stretched over that depth. That is a property of the
 * stated frame rather than a choice made here, and inventing an axis for it would be a tessellator
 * putting a coordinate where no grammar put one.
 */
export function revealOn(
  into: Surface,
  edge: FaceEdge,
  outline: readonly Plan[],
  depth: number,
  datum: number,
  where: string,
): void {
  if (depth < 1) return;
  const inward = subtract(0, depth, where);
  const corner = (point: Plan, back: number): number => into.corner(
    facePoint(edge, point[0], back, where),
    point[1],
    point[0],
    subtract(datum, point[1], where),
  );
  outline.forEach((here, index) => {
    const next = outline[(index + 1) % outline.length]!;
    into.face(corner(here, 0), corner(next, 0), corner(next, inward), corner(here, inward));
  });
}
