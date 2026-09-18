/**
 * The street rules, held to what they state on every segment and curb of the conformance fixture:
 * surfaces by role and orientation, counter-clockwise from their front, inside their record's
 * extent, meeting each other on shared edges, and measured in the segment's own frame.
 *
 * THE CORNER is held to the partition the grammar states rather than to a shape this test redraws:
 * every point of it lies in the slice between the two tangent points' normals, no point of the
 * footway lies inside a block the curb names, and the curb still draws ONE surface per role and
 * orientation however many corners it turns. A test that rebuilt the wedge from the same fields
 * would agree with the rule by construction and could not fail.
 */
import { describe, expect, it } from 'vitest';
import type { Piece } from '../src/core/pieces.js';
import { curbSurfaces, junctionSurface, segmentSurfaces } from '../src/core/streets.js';
import type { CornerContext, StreetLookup } from '../src/core/streets.js';
import { fixtureObject, recordsOf } from './support.js';

type Fields = Record<string, any>;
type Point = [number, number, number];

const fixture = fixtureObject();
const segments: Fields[] = recordsOf(fixture, 'city.street_segment').map((record: any) => record.fields);
const curbs: Fields[] = recordsOf(fixture, 'city.curb_edge').map((record: any) => record.fields);
const curbOf = (segment: Fields, side: string): Fields | undefined =>
  curbs.find((curb) => curb.segment_identity === segment.identity && curb.side === side);

function points(piece: Piece): Point[] {
  const out: Point[] = [];
  for (let index = 0; index < piece.vertices.length; index += 3) {
    out.push([piece.vertices[index]!, piece.vertices[index + 1]!, piece.vertices[index + 2]!]);
  }
  return out;
}

/** The triangle's normal, unnormalised. */
function normal(a: Point, b: Point, c: Point): Point {
  const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
  return [u[1]! * v[2]! - u[2]! * v[1]!, u[2]! * v[0]! - u[0]! * v[2]!, u[0]! * v[1]! - u[1]! * v[0]!];
}

function triangles(piece: Piece): [Point, Point, Point][] {
  const at = points(piece);
  const out: [Point, Point, Point][] = [];
  for (let index = 0; index < piece.triangles.length; index += 3) {
    out.push([at[piece.triangles[index]!]!, at[piece.triangles[index + 1]!]!, at[piece.triangles[index + 2]!]!]);
  }
  return out;
}

const insideExtent = (extent: Fields, point: Point): boolean =>
  extent.min_x_mm <= point[0] && point[0] <= extent.max_x_mm
  && extent.min_y_mm <= point[1] && point[1] <= extent.max_y_mm
  && extent.min_z_mm <= point[2] && point[2] <= extent.max_z_mm;

const planArea = (piece: Piece): number =>
  triangles(piece).reduce((sum, [a, b, c]) => sum + ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2, 0);

describe('the segment rule', () => {
  it('draws a carriageway and a gutter on every fixture segment, upward, inside its extent', () => {
    expect(segments).toHaveLength(3);
    for (const segment of segments) {
      const result = segmentSurfaces(segment, curbOf(segment, 'left'), curbOf(segment, 'right'), 'case');
      if (result.state !== 'drawn') throw new Error(`segment ${segment.identity} waits on ${result.need}`);
      expect(result.pieces.map((piece) => [piece.surface!.role, piece.surface!.orientation])).toEqual([
        ['carriageway', 'horizontal'],
        ['gutter', 'horizontal'],
      ]);
      for (const piece of result.pieces) {
        for (const triangle of triangles(piece)) expect(normal(...triangle)[2]).toBeGreaterThan(0);
        for (const point of points(piece)) expect(insideExtent(segment.extent, point), `${point}`).toBe(true);
      }
    }
  });

  it('spans where both kerb lines exist, the carriageway width across, on the camber plane', () => {
    // Market Street west: the north kerb stops at 50750 for the corner, the south kerb runs on to
    // the node, so the strip is 30750 mm long and 9500 mm wide.
    const west = segments.find((segment) => segment.segment_ordinal === 0)!;
    const result = segmentSurfaces(west, curbOf(west, 'left'), curbOf(west, 'right'), 'case');
    if (result.state !== 'drawn') throw new Error('not drawn');
    const [carriageway, gutter] = result.pieces;
    expect(planArea(carriageway!) + planArea(gutter!)).toBe(30750 * 9500);
    expect(planArea(gutter!)).toBe(30750 * 300 * 2);
    const xs = [...points(carriageway!), ...points(gutter!)].map((point) => point[0]);
    expect([Math.min(...xs), Math.max(...xs)]).toEqual([20000, 50750]);
    // Crown at 0, kerb lines at -95, the gutter lines 300 mm in: -95 + floor(95 * 600 / 9500) = -89.
    const heights = new Map(points(carriageway!).map((point) => [point[1], point[2]]));
    expect(heights.get(40000)).toBe(0);
    expect(heights.get(44450)).toBe(-89);
    expect(heights.get(35550)).toBe(-89);
    // s along the centreline from the start node, t across it, left positive.
    const coordinates = carriageway!.surface!.coordinates;
    points(carriageway!).forEach((point, index) => {
      expect([coordinates[index * 2], coordinates[index * 2 + 1]]).toEqual([point[0] - 20000, point[1] - 40000]);
    });
  });

  it('meets its curbs on the kerb lines, with no gap', () => {
    for (const segment of segments) {
      const result = segmentSurfaces(segment, curbOf(segment, 'left'), curbOf(segment, 'right'), 'case');
      if (result.state !== 'drawn') throw new Error('not drawn');
      const gutterPoints = points(result.pieces[1]!).map((point) => point.join(' '));
      for (const side of ['left', 'right']) {
        const curb = curbOf(segment, side)!;
        const drawn = curbSurfaces(curb, segment, [], [], 'case');
        if (drawn.state !== 'drawn') throw new Error('not drawn');
        const facePoints = points(drawn.pieces[0]!);
        const bottoms = facePoints.filter((point) => point[2] === curb.kerb_line_mm[0][2]);
        // Every gutter point on this kerb line lies on the kerb face's bottom edge.
        const onLine = gutterPoints.filter((key) => {
          const [x, y] = key.split(' ').map(Number);
          const [start, end] = curb.kerb_line_mm;
          return (x! - start[0]) * (end[1] - start[1]) === (y! - start[1]) * (end[0] - start[0]);
        });
        expect(onLine.length).toBeGreaterThan(0);
        const [low, high] = [Math.min(...bottoms.map((point) => point[0] + point[1])), Math.max(...bottoms.map((point) => point[0] + point[1]))];
        for (const key of onLine) {
          const [x, y] = key.split(' ').map(Number);
          expect(x! + y!).toBeGreaterThanOrEqual(low);
          expect(x! + y!).toBeLessThanOrEqual(high);
        }
      }
    }
  });

  it('waits on its curbs and on a bent line rather than guessing', () => {
    const west = segments.find((segment) => segment.segment_ordinal === 0)!;
    expect(segmentSurfaces(west, undefined, curbOf(west, 'right'), 'case')).toEqual({ state: 'waiting', need: 'street_curbs' });
    const bent = { ...west, centreline_mm: [[20000, 40000, 0], [40000, 40100, 0], [60000, 40000, 0]] };
    expect(segmentSurfaces(bent, curbOf(west, 'left'), curbOf(west, 'right'), 'case')).toEqual({ state: 'waiting', need: 'bent_street' });
  });
});

describe('the curb rule, straight parts', () => {
  it('draws a kerb face toward the carriageway, a kerb top and a footway on every fixture curb', () => {
    expect(curbs).toHaveLength(6);
    for (const curb of curbs) {
      const segment = segments.find((candidate) => candidate.identity === curb.segment_identity)!;
      const result = curbSurfaces(curb, segment, [], [], 'case');
      if (result.state !== 'drawn') throw new Error(`curb ${curb.identity} waits on ${result.need}`);
      expect(result.pieces.map((piece) => [piece.surface!.role, piece.surface!.orientation])).toEqual([
        ['kerb', 'vertical'],
        ['kerb', 'horizontal'],
        ['footway', 'horizontal'],
      ]);
      const [face, top, footway] = result.pieces;
      const [start, end] = segment.centreline_mm;
      const direction: [number, number] = [end[0] - start[0], end[1] - start[1]];
      const outward: [number, number] = curb.side === 'left' ? [-direction[1], direction[0]] : [direction[1], -direction[0]];
      for (const triangle of triangles(face!)) {
        const n = normal(...triangle);
        expect(n[2] === 0, 'a kerb face is vertical').toBe(true);
        expect(n[0] * outward[0]! + n[1] * outward[1]!).toBeLessThan(0);
      }
      for (const piece of [top!, footway!]) {
        for (const triangle of triangles(piece)) expect(normal(...triangle)[2]).toBeGreaterThan(0);
      }
      for (const piece of result.pieces) {
        for (const point of points(piece)) expect(insideExtent(curb.extent, point), `${curb.identity} ${point}`).toBe(true);
      }
      // The face runs from the kerb line up the kerb height; t = base - z.
      const faceT = face!.surface!.coordinates.filter((_value, index) => index % 2 === 1);
      expect(new Set(faceT)).toEqual(new Set([0, -curb.kerb_height_mm]));
      const topZ = new Set(points(top!).map((point) => point[2]));
      expect(topZ).toEqual(new Set([curb.kerb_line_mm[0][2] + curb.kerb_height_mm]));
    }
  });

  it("brings the footway to its block frontage line at the block's grade", () => {
    const block = recordsOf(fixture, 'city.block')[0].fields;
    const curb = curbs.find((candidate) => candidate.block_identity.includes(block.identity) && candidate.side === 'left'
      && candidate.kerb_line_mm[0][1] === candidate.kerb_line_mm[1][1])!;
    const segment = segments.find((candidate) => candidate.identity === curb.segment_identity)!;
    const result = curbSurfaces(curb, segment, [], [], 'case');
    if (result.state !== 'drawn') throw new Error('not drawn');
    const back = points(result.pieces[2]!).filter((point) => point[1] === block.boundary_mm[0][1]);
    expect(back).toHaveLength(2);
    for (const point of back) expect(point[2]).toBe(block.grade_elevation_mm);
  });
});

/** The corner a curb turns, read from the fixture the way the expander reads it. */
function cornerOf(curb: Fields): CornerContext | undefined {
  const identity = (curb.next_curb_identity as string[])[0];
  if (identity === undefined) return undefined;
  if (curb.corner_radius_mm === 0) return undefined;
  const follower = curbs.find((candidate) => candidate.identity === identity)!;
  const rings = (curb.block_identity as string[]).map((block) =>
    (recordsOf(fixture, 'city.block').find((record: any) => record.fields.identity === block) as any).fields.boundary_mm as [number, number][]);
  return { follower, blocks: rings, resolutionMm: 1 };
}

/** Whether any triangle of one footway meets any triangle of another, interiors only. */
function footwaysMeet(first: Piece, second: Piece): boolean {
  const twice = (a: Point, b: Point, c: number[]): number =>
    (b[0] - a[0]) * (c[1]! - a[1]) - (b[1] - a[1]) * (c[0]! - a[0]);
  const turned = (walk: [Point, Point, Point]): Point[] =>
    twice(walk[0], walk[1], walk[2]) >= 0 ? [...walk] : [walk[0], walk[2], walk[1]];
  const apart = (edges: Point[], other: Point[]): boolean => edges.some((from, index) => {
    const to = edges[(index + 1) % edges.length]!;
    return other.every((point) => twice(from, to, point) <= 0);
  });
  for (const a of triangles(first)) {
    for (const b of triangles(second)) {
      const [x, y] = [turned(a), turned(b)];
      if (!apart(x, y) && !apart(y, x)) return true;
    }
  }
  return false;
}

/** Whether a plan point lies inside a ring, by crossings. */
function insideRing(ring: readonly (readonly [number, number])[], x: number, y: number): boolean {
  let inside = false;
  ring.forEach((here, index) => {
    const next = ring[(index + 1) % ring.length]!;
    if ((here[1] > y) !== (next[1] > y) && x < here[0] + (y - here[1]) * (next[0] - here[0]) / (next[1] - here[1])) {
      inside = !inside;
    }
  });
  return inside;
}

describe('the corner rule', () => {
  it('turns both of the fixture\'s corners, keeping one surface per role and orientation', () => {
    const turning = curbs.filter((curb) => curb.corner_radius_mm !== 0);
    // One corner has a block to give ground up to and one has none, which are the two cases.
    expect(turning).toHaveLength(2);
    expect(turning.map((curb) => (curb.block_identity as string[]).length)).toEqual([1, 0]);
    for (const curb of turning) {
      const segment = segments.find((candidate) => candidate.identity === curb.segment_identity)!;
      const corner = cornerOf(curb)!;
      const straight = curbSurfaces(curb, segment, [], [], 'case');
      const turned = curbSurfaces(curb, segment, [corner], [], 'case');
      if (straight.state !== 'drawn' || turned.state !== 'drawn') throw new Error('a curb is not drawn');
      expect(turned.pieces.map((piece) => [piece.surface!.role, piece.surface!.orientation])).toEqual([
        ['kerb', 'vertical'],
        ['kerb', 'horizontal'],
        ['footway', 'horizontal'],
      ]);
      // The corner is additive: the straight part's own triangles are still all there.
      for (const [index, piece] of turned.pieces.entries()) {
        expect(piece.triangles.length).toBeGreaterThan(straight.pieces[index]!.triangles.length);
        expect(piece.surface!.coordinates.length).toBe(piece.vertices.length / 3 * 2);
      }
      // Every horizontal triangle is wound upward, and every point lies inside the curb's extent.
      for (const piece of turned.pieces) {
        if (piece.surface!.orientation === 'horizontal') {
          for (const [a, b, c] of triangles(piece)) expect(normal(a, b, c)[2]).toBeGreaterThan(0);
        }
        for (const point of points(piece)) expect(insideExtent(curb.extent as Fields, point)).toBe(true);
      }
      // And no footway triangle stands on ground a block the curb names has taken.
      const rings = corner.blocks as [number, number][][];
      for (const [a, b, c] of triangles(turned.pieces[2]!)) {
        const at: [number, number] = [(a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3];
        for (const ring of rings) expect(insideRing(ring, at[0], at[1]), `${JSON.stringify(at)} is inside a block`).toBe(false);
      }
    }
  });

  it('gives way on the mitre where a footway reaches the radius, so two strips never overlap', () => {
    // A right-angled corner of radius 10 m with a 13.2 m reach, which is the shape the corridor has
    // sixteen of: the two straight strips would both cover the ground beyond the arc's centre.
    // Every number below is chosen so the mitre's two points are whole millimetres this test can
    // write down: the centre is the radius along the first curb's end normal, and the frontage
    // corner is where the two frontage lines, each a reach to the left of its kerb line, meet.
    const widths = { kerb_height_mm: 150, kerb_width_mm: 200, footway_width_mm: 13000, footway_crossfall_millionths: 20000 };
    const first: Fields = { identity: 'first', side: 'left', corner_radius_mm: 10000, next_curb_identity: ['second'],
      kerb_line_mm: [[-20000, 0, 0], [0, 0, 0]], ...widths };
    const second: Fields = { identity: 'second', side: 'left', corner_radius_mm: 0, next_curb_identity: [],
      kerb_line_mm: [[10000, 10000, 0], [10000, 30000, 0]], ...widths };
    const along: Fields = { centreline_mm: [[-20000, -3000, 0], [0, -3000, 0]] };
    const up: Fields = { centreline_mm: [[13000, 10000, 0], [13000, 30000, 0]] };
    const corner: CornerContext = { follower: second, blocks: [], resolutionMm: 1 };
    const footwayOf = (result: ReturnType<typeof curbSurfaces>): Piece => {
      if (result.state !== 'drawn') throw new Error(`a curb waits on ${result.need}`);
      return result.pieces[2]!;
    };
    const mitred = [
      footwayOf(curbSurfaces(first, along, [corner], [], 'case')),
      footwayOf(curbSurfaces(second, up, [], [{ owner: first }], 'case')),
    ];
    const plain = [
      footwayOf(curbSurfaces(first, along, [], [], 'case')),
      footwayOf(curbSurfaces(second, up, [], [], 'case')),
    ];
    // Both strips take the same two points: the centre on their shared normals, and the frontage
    // corner where a 13.2 m reach from each kerb line meets.
    for (const piece of mitred) {
      const at = points(piece).map((point) => [point[0], point[1]]);
      expect(at).toContainEqual([0, 10000]);
      expect(at).toContainEqual([-3200, 13200]);
    }
    // The strip is a ring of five where a mitre cuts one of its corners, and of four where none
    // does. The first curb's piece carries its corner's wedge as well, so only the second is bare.
    expect(points(mitred[1]!)).toHaveLength(5);
    expect(points(plain[1]!)).toHaveLength(4);
    // And the strips no longer cover the same ground. Without the mitre they do, which is the
    // control: a test that cannot fail on the unmitred pair would not be testing the mitre.
    expect(footwaysMeet(plain[0]!, plain[1]!)).toBe(true);
    expect(footwaysMeet(mitred[0]!, mitred[1]!)).toBe(false);
  });

  it('waits on the rule for a corner that turns the other way', () => {
    const curb = curbs.find((candidate) => candidate.corner_radius_mm !== 0)!;
    const segment = segments.find((candidate) => candidate.identity === curb.segment_identity)!;
    const corner = cornerOf(curb)!;
    // The follower's kerb line reversed turns the corner the other way, which is a concave one.
    const reversed = { ...corner.follower, kerb_line_mm: [...(corner.follower.kerb_line_mm as unknown[])].reverse() };
    const result = curbSurfaces(curb, segment, [{ ...corner, follower: reversed }], [], 'case');
    expect(result).toEqual({ state: 'waiting', need: 'concave_corner' });
  });
});

describe('the junction rule', () => {
  const carried = new Map<string, Fields>(
    [...fixture.grammars[0].owned, ...fixture.grammars[0].halo].map((record: any) => [record.fields.identity, record.fields]),
  );
  const lookup: StreetLookup = {
    record: (identity) => carried.get(identity),
    curbs: (segment) => ({
      left: curbs.find((curb) => curb.segment_identity === segment && curb.side === 'left'),
      right: curbs.find((curb) => curb.segment_identity === segment && curb.side === 'right'),
    }),
  };
  const junction = recordsOf(fixture, 'city.junction')[0].fields;

  it('fills the carriageway inside the kerb arcs, upward, inside the junction extent', () => {
    const result = junctionSurface(junction, lookup, 1, 'case');
    if (result.state !== 'drawn') throw new Error(`waits on ${result.need}`);
    expect(result.pieces).toHaveLength(1);
    const [fill] = result.pieces;
    expect([fill!.surface!.role, fill!.surface!.orientation]).toEqual(['carriageway', 'horizontal']);
    for (const triangle of triangles(fill!)) expect(normal(...triangle)[2]).toBeGreaterThan(0);
    for (const point of points(fill!)) expect(insideExtent(junction.extent, point), `${point}`).toBe(true);
    // The box from mouth to mouth, 18500 by 15500, less a quarter disc of radius 6000 at each of
    // the two corners: within the two arcs' length times the rule's two millimetres of rounding.
    const ideal = 18500 * 15500 - 2 * (Math.PI * 6000 * 6000) / 4;
    expect(Math.abs(planArea(fill!) - ideal)).toBeLessThan(2 * 9425 * 2);
    // s = x and t = y.
    points(fill!).forEach((point, index) => {
      expect([fill!.surface!.coordinates[index * 2], fill!.surface!.coordinates[index * 2 + 1]]).toEqual([point[0], point[1]]);
    });
  });

  it('opens onto each leg at exactly the points its strip ends on', () => {
    const result = junctionSurface(junction, lookup, 1, 'case');
    if (result.state !== 'drawn') throw new Error('not drawn');
    const fill = new Set(points(result.pieces[0]!).map((point) => point.join(' ')));
    for (const identity of junction.segment_identities) {
      const segment = carried.get(identity)!;
      const strip = segmentSurfaces(segment, lookup.curbs(identity).left, lookup.curbs(identity).right, 'case');
      if (strip.state !== 'drawn') throw new Error('not drawn');
      const node = carried.get(junction.node_identity)!;
      const nodeEnd = strip.pieces.flatMap(points).filter((point) => {
        const [start] = segment.centreline_mm;
        const startsAtNode = start[0] === node.x_mm && start[1] === node.y_mm;
        const along = (point[0] - start[0]) * (segment.centreline_mm[1][0] - start[0]) + (point[1] - start[1]) * (segment.centreline_mm[1][1] - start[1]);
        const all = strip.pieces.flatMap(points).map((other) => (other[0] - start[0]) * (segment.centreline_mm[1][0] - start[0]) + (other[1] - start[1]) * (segment.centreline_mm[1][1] - start[1]));
        return along === (startsAtNode ? Math.min(...all) : Math.max(...all));
      });
      expect(nodeEnd.length).toBeGreaterThan(0);
      for (const point of nodeEnd) expect(fill.has(point.join(' ')), `${identity} ${point}`).toBe(true);
    }
  });

  it('meets the kerb arcs from both tangent points, and uses more segments at a finer resolution', () => {
    const fine = junctionSurface(junction, lookup, 1, 'case');
    const coarse = junctionSurface(junction, lookup, 50, 'case');
    if (fine.state !== 'drawn' || coarse.state !== 'drawn') throw new Error('not drawn');
    expect(points(fine.pieces[0]!).length).toBeGreaterThan(points(coarse.pieces[0]!).length);
    for (const tangent of ['50750 44750 -95', '56750 50750 -95', '63250 50750 -95', '69250 44750 -95']) {
      expect(points(coarse.pieces[0]!).map((point) => point.join(' '))).toContain(tangent);
    }
  });

  it('waits on a leg the tile does not carry', () => {
    const partial: StreetLookup = { ...lookup, record: (identity) => (identity === junction.segment_identities[1] ? undefined : carried.get(identity)) };
    expect(junctionSurface(junction, partial, 1, 'case')).toEqual({ state: 'waiting', need: 'junction_legs' });
  });
});
