/**
 * The street rules, held to what they state on every segment and curb of the conformance fixture:
 * surfaces by role and orientation, counter-clockwise from their front, inside their record's
 * extent, meeting each other on shared edges, and measured in the segment's own frame.
 */
import { describe, expect, it } from 'vitest';
import type { Piece } from '../src/core/expand.js';
import { curbSurfaces, segmentSurfaces } from '../src/core/streets.js';
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
        const drawn = curbSurfaces(curb, segment, 'case');
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
      const result = curbSurfaces(curb, segment, 'case');
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
    const result = curbSurfaces(curb, segment, 'case');
    if (result.state !== 'drawn') throw new Error('not drawn');
    const back = points(result.pieces[2]!).filter((point) => point[1] === block.boundary_mm[0][1]);
    expect(back).toHaveLength(2);
    for (const point of back) expect(point[2]).toBe(block.grade_elevation_mm);
  });
});
