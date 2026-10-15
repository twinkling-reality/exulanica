/**
 * The street rules on land: lines straight in plan that bend only in height, as city grammar version
 * 6 lays a town's streets between its junctions' mouths, the risers between a footway and the lots
 * behind it, and the steps between lots at other heights.
 *
 * The heights along a line are held to the GRAMMAR's reading of it (`lifted-lines.json`, written by
 * `tests/fixtures/city-v6/build_lifted_lines.py` from a generated town), not to a second reading
 * written here, so the two languages cannot drift apart unnoticed.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { lotSteps } from '../src/core/lot-steps.js';
import type { Piece } from '../src/core/pieces.js';
import { cornerMitre, curbCorner, curbSurfaces, heightAlong, segmentSurfaces } from '../src/core/streets.js';
import type { CornerContext } from '../src/core/streets.js';
import { fixtureObject, recordsOf } from './support.js';

type Fields = Record<string, any>;
type Point = [number, number, number];

/** Heights a graded patch spans: every height these cases stand at. */
const SPAN: [number, number] = [-10_000, 10_000];

const LIFTED = JSON.parse(readFileSync(new URL('./fixtures/lifted-lines.json', import.meta.url), 'utf8'));

function points(piece: Piece): Point[] {
  const out: Point[] = [];
  for (let index = 0; index < piece.vertices.length; index += 3) {
    out.push([piece.vertices[index]!, piece.vertices[index + 1]!, piece.vertices[index + 2]!]);
  }
  return out;
}

function triangles(piece: Piece): [Point, Point, Point][] {
  const at = points(piece);
  const out: [Point, Point, Point][] = [];
  for (let index = 0; index < piece.triangles.length; index += 3) {
    out.push([at[piece.triangles[index]!]!, at[piece.triangles[index + 1]!]!, at[piece.triangles[index + 2]!]!]);
  }
  return out;
}

function normal(a: Point, b: Point, c: Point): Point {
  const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
  return [u[1]! * v[2]! - u[2]! * v[1]!, u[2]! * v[0]! - u[0]! * v[2]!, u[0]! * v[1]! - u[1]! * v[0]!];
}

// A street 80 m long along +x on land: level at 1 m at its west node out to its mouth at 10 m, a
// straight climb of 1.2 m to its east mouth at 70 m, level beyond. Its kerbs stand 100 mm below the
// crown. The south kerb runs mouth to mouth; the north one reaches past both mouths (four points);
// the third, for the corner case, past one.
const segment: Fields = {
  identity: 'segment-on-land',
  carriageway_width_mm: 7_000,
  centreline_mm: [[0, 0, 1_000], [10_000, 0, 1_000], [70_000, 0, 2_200], [80_000, 0, 2_200]],
};
const curbFields = (side: string, line: Point[]): Fields => ({
  identity: `curb-${side}`,
  segment_identity: segment.identity,
  side,
  kerb_line_mm: line,
  kerb_height_mm: 150,
  kerb_width_mm: 300,
  footway_width_mm: 2_700,
  footway_crossfall_millionths: 20_000,
  gutter_width_mm: 500,
  corner_radius_mm: 0,
  next_curb_identity: [],
  block_identity: [],
});
const north = curbFields('left', [[5_000, 3_500, 900], [10_000, 3_500, 900], [70_000, 3_500, 2_100], [75_000, 3_500, 2_100]]);
const south = curbFields('right', [[10_000, -3_500, 900], [70_000, -3_500, 2_100]]);
/** The north footway's back edge: the kerb line plus the kerb and the footway. */
const BACK = 3_500 + 300 + 2_700;
/** The footway's back edge stands this far above the kerb line: the kerb and the crossfall. */
const UP = 150 + Math.floor((2_700 * 20_000) / 1_000_000);

describe('a line straight in plan that bends in height', () => {
  it("is read at the heights the grammar's own profile gives along it", () => {
    expect(LIFTED.lines.length).toBeGreaterThan(0);
    const bent = LIFTED.lines.filter((line: any) => line.points.length > 2);
    expect(bent.length, 'the fixture holds lines with bends').toBeGreaterThan(0);
    let read = 0;
    for (const line of LIFTED.lines) {
      for (const [x, y, z] of line.samples) {
        expect(heightAlong(line.points, [x, y], 'case'), `${JSON.stringify(line.points)} at ${x} ${y}`).toBe(z);
        read += 1;
      }
    }
    expect(read).toBeGreaterThan(100);
  });

  it('draws a strip that climbs from one mouth to the other, its crown at the line\'s heights', () => {
    const result = segmentSurfaces(segment, north, south, 'case');
    if (result.state !== 'drawn') throw new Error(`waits on ${result.need}`);
    const crowns = points(result.pieces[0]!).filter((point) => point[1] === 0);
    expect(new Set(crowns.map((point) => `${point[0]} ${point[2]}`))).toEqual(new Set(['10000 1000', '70000 2200']));
  });

  it('draws a curb piece by piece, so no footway triangle spans a bend', () => {
    const result = curbSurfaces(north, segment, [], [], 'case');
    if (result.state !== 'drawn') throw new Error(`waits on ${result.need}`);
    expect(result.pieces.map((piece) => [piece.surface!.role, piece.surface!.orientation])).toEqual([
      ['kerb', 'vertical'],
      ['kerb', 'horizontal'],
      ['footway', 'horizontal'],
    ]);
    const bends = [5_000, 10_000, 70_000, 75_000];
    for (const triangle of triangles(result.pieces[2]!)) {
      const xs = triangle.map((point) => point[0]);
      const within = bends.slice(0, -1).some((low, index) => xs.every((x) => low <= x && x <= bends[index + 1]!));
      expect(within, `${JSON.stringify(triangle)} spans a bend`).toBe(true);
      expect(normal(...triangle)[2]).toBeGreaterThan(0);
    }
    // The face runs from the kerb line up the kerb height wherever the line stands.
    const face = result.pieces[0]!;
    points(face).forEach((point, index) => {
      const t = face.surface!.coordinates[index * 2 + 1]!;
      expect(t).toBe(heightAlong(north.kerb_line_mm, [point[0], point[1]], 'case')! - point[2]);
    });
  });

  it('waits where a line bends in height inside its strip, or bends in plan', () => {
    const inside = { ...segment, centreline_mm: [[0, 0, 1_000], [10_000, 0, 1_000], [40_000, 0, 1_900], [70_000, 0, 2_200], [80_000, 0, 2_200]] };
    expect(segmentSurfaces(inside, north, south, 'case')).toEqual({ state: 'waiting', need: 'bent_street' });
    const kinked = { ...south, kerb_line_mm: [[10_000, -3_500, 900], [40_000, -3_400, 1_500], [70_000, -3_500, 2_100]] };
    expect(segmentSurfaces(segment, north, kinked, 'case')).toEqual({ state: 'waiting', need: 'bent_street' });
  });
});

describe('a corner between curbs whose kerb lines bend in height', () => {
  // Today's fixture: a corner owner and its follower, both two points. A follower given a third
  // point on its own line, at its own height, is the same kerb: the corner must read it from its
  // end pieces as the grammar does (`corners.corner_of`) and come out the same, where reading it as
  // a two-point line threw.
  const fixture = fixtureObject();
  const curbs: Fields[] = recordsOf(fixture, 'city.curb_edge').map((record: any) => record.fields);
  const segments: Fields[] = recordsOf(fixture, 'city.street_segment').map((record: any) => record.fields);
  const midpointAdded = (curb: Fields): Fields => {
    const [a, b] = curb.kerb_line_mm as Point[];
    const middle: Point = [Math.floor((a![0] + b![0]) / 2), Math.floor((a![1] + b![1]) / 2), a![2]];
    expect(a![2]).toBe(b![2]);
    return { ...curb, kerb_line_mm: [a, middle, b] };
  };

  it('turns into a follower of three points exactly as into the same follower of two', () => {
    const turning = curbs.filter((curb) => curb.corner_radius_mm !== 0);
    expect(turning.length).toBeGreaterThan(0);
    for (const curb of turning) {
      const follower = curbs.find((candidate) => candidate.identity === curb.next_curb_identity[0])!;
      const segmentOf = segments.find((candidate) => candidate.identity === curb.segment_identity)!;
      const blocks = (curb.block_identity as string[]).map((block) =>
        (recordsOf(fixture, 'city.block').find((record: any) => record.fields.identity === block) as any).fields.boundary_mm);
      const corner = (with_: Fields): CornerContext => ({ follower: with_, blocks, resolutionMm: 1 });
      const [start, end] = segmentOf.centreline_mm as Point[];
      const direction: [number, number] = [end![0] - start![0], end![1] - start![1]];
      const before = curbCorner(curb, corner(follower), [start![0], start![1]], direction, 'case');
      const after = curbCorner(curb, corner(midpointAdded(follower)), [start![0], start![1]], direction, 'case');
      expect(after).toEqual(before);
      // And from the owner's side: the corner leaves the owner's walk at its last point, read from
      // its last piece, however many points its line holds.
      const owned = curbCorner(midpointAdded(curb), corner(midpointAdded(follower)), [start![0], start![1]], direction, 'case');
      expect(owned).toEqual(before);
      expect(cornerMitre(midpointAdded(curb), midpointAdded(follower), 'case')).toEqual(cornerMitre(curb, follower, 'case'));
    }
  });
});

describe('the steps at a frontage, between a footway and the lot behind it', () => {
  // A lot behind the north footway, counter-clockwise, its frontage the edge on the back line.
  const ring = (from: number, to: number): [number, number][] => [[from, BACK], [to, BACK], [to, BACK + 20_000], [from, BACK + 20_000]];
  const tile: [number, number, number, number] = [0, 0, 128_000, 128_000];
  const stepsOf = (kerbLine: Point[], from: number, to: number, gradeMm: number): Piece => {
    const steps = lotSteps([{ ring: ring(from, to), gradeMm, frontages: [{ edgeOrdinal: 0, kerbLine, upMm: UP }] }], tile, SPAN, 'case');
    return { vertices: steps.vertices, triangles: steps.triangles, surface: { role: 'terrain', orientation: 'vertical', coordinates: steps.coordinates } };
  };
  /** The footway's back edge at x on a kerb line. */
  const backAt = (line: Point[], x: number): number => heightAlong(line, [x, 3_500], 'case')! + UP;
  const descending: Point[] = [[5_000, 3_500, 2_100], [10_000, 3_500, 2_100], [70_000, 3_500, 900], [75_000, 3_500, 900]];

  it('adds none on a level patch, which stands at the datum below every lot and footway', () => {
    // A town on level ground: its lots stand a few centimetres above a footway of another crossfall,
    // and its terrain at the datum states none of those heights, so it closes no step.
    const lots = [{ ring: ring(20_000, 40_000), gradeMm: 2_400, frontages: [{ edgeOrdinal: 0, kerbLine: north.kerb_line_mm, upMm: UP }] }];
    expect(lotSteps(lots, tile, [0, 0], 'case').triangles).toHaveLength(0);
    expect(lotSteps(lots, tile, SPAN, 'case').triangles.length).toBeGreaterThan(0);
  });

  it('adds none for a lot level with its footway', () => {
    expect(stepsOf(north.kerb_line_mm, 1_000, 9_000, 900 + UP).triangles).toHaveLength(0);
  });

  it('stands from the footway\'s top up to a lot above it, on the frontage line, facing the street', () => {
    const grade = backAt(north.kerb_line_mm, 40_000);
    const step = stepsOf(north.kerb_line_mm, 20_000, 40_000, grade);
    expect(step.triangles.length).toBeGreaterThan(0);
    for (const triangle of triangles(step)) {
      expect(normal(...triangle)[2]).toBe(0);
      expect(normal(...triangle)[1], 'faces the street, south').toBeLessThan(0);
    }
    // Its foot is the footway's back edge, never above it and less than a millimetre below where a
    // floor rounds it, and its head the lot's grade: nothing of it overlaps the footway or the kerb.
    for (const point of points(step)) {
      expect(point[1]).toBe(BACK);
      if (point[2] !== grade) {
        expect(point[2]).toBeLessThanOrEqual(backAt(north.kerb_line_mm, point[0]));
        expect(point[2]).toBeGreaterThanOrEqual(backAt(north.kerb_line_mm, point[0]) - 1);
      }
    }
  });

  it('turns round where the footway climbs past the lot, facing whichever side is lower', () => {
    const grade = backAt(north.kerb_line_mm, 40_000);
    const step = stepsOf(north.kerb_line_mm, 30_000, 50_000, grade);
    for (const triangle of triangles(step)) {
      const lotHigher = triangle.every((point) => point[0] <= 40_000);
      expect(Math.sign(normal(...triangle)[1])).toBe(lotHigher ? -1 : 1);
    }
    expect(new Set(triangles(step).map((triangle) => Math.sign(normal(...triangle)[1])))).toEqual(new Set([-1, 1]));
  });

  it('turns round where the footway falls past the lot, as where it climbs past it', () => {
    const grade = backAt(descending, 40_000);
    const step = stepsOf(descending, 30_000, 50_000, grade);
    expect(new Set(triangles(step).map((triangle) => Math.sign(normal(...triangle)[1])))).toEqual(new Set([-1, 1]));
  });

  it('is cut where the kerb line bends, so each part is one plane', () => {
    const grade = backAt(north.kerb_line_mm, 75_000) + 500;
    const step = stepsOf(north.kerb_line_mm, 60_000, 74_000, grade);
    const feet = points(step).filter((point) => point[2] !== grade).map((point) => point[0]);
    expect(feet).toContain(70_000);
  });

  it('is cut where the kerb line ends, past which the footway is level at the end\'s height', () => {
    // A corner lot's frontage runs on past its curb's kerb line, beside the corner's own footway,
    // and the line climbs right to its end: the step's foot follows the footway on both sides.
    const climbing: Point[] = [[5_000, 3_500, 2_100], [75_000, 3_500, 900]];
    const grade = backAt(climbing, 60_000);
    const feet = points(stepsOf(climbing, 60_000, 80_000, grade)).filter((point) => point[2] !== grade);
    expect(feet.map((point) => point[0])).toContain(75_000);
    for (const point of feet) {
      if (point[0] >= 75_000) expect(point[2]).toBe(900 + UP);
      else expect(Math.abs(point[2] - backAt(climbing, point[0]))).toBeLessThanOrEqual(1);
    }
  });
});

describe('the steps between lots', () => {
  // Two lots behind the north footway, sharing the edge at x = 30 m, counter-clockwise rings.
  const west = { ring: [[20_000, BACK], [30_000, BACK], [30_000, BACK + 20_000], [20_000, BACK + 20_000]] as [number, number][], gradeMm: 2_000, frontages: [] };
  const east = { ring: [[30_000, BACK], [40_000, BACK], [40_000, BACK + 20_000], [30_000, BACK + 20_000]] as [number, number][], gradeMm: 2_600, frontages: [] };
  const tile: [number, number, number, number] = [0, 0, 128_000, 128_000];
  const asPiece = (steps: ReturnType<typeof lotSteps>): Piece => ({ vertices: steps.vertices, triangles: steps.triangles, surface: { role: 'terrain', orientation: 'vertical', coordinates: steps.coordinates } });

  it('stand on the shared edge from the lower grade to the higher, facing the lower lot', () => {
    const piece = asPiece(lotSteps([west, east], tile, SPAN, 'case'));
    expect(triangles(piece)).toHaveLength(2);
    for (const triangle of triangles(piece)) {
      expect(normal(...triangle)[0], 'faces the lower lot, west').toBeLessThan(0);
      for (const point of triangle) {
        expect(point[0]).toBe(30_000);
        expect([2_000, 2_600]).toContain(point[2]);
      }
    }
    expect(lotSteps([west, { ...east, gradeMm: 2_000 }], tile, SPAN, 'case').triangles).toHaveLength(0);
  });

  it('meet the frontage steps of both lots on one vertical edge, in planes across each other', () => {
    const frontage = { edgeOrdinal: 0, kerbLine: north.kerb_line_mm, upMm: UP };
    const both = asPiece(lotSteps([{ ...west, frontages: [frontage] }, { ...east, frontages: [frontage] }], tile, SPAN, 'case'));
    const between = triangles(both).filter((triangle) => triangle.every((point) => point[0] === 30_000));
    const fronts = triangles(both).filter((triangle) => triangle.every((point) => point[1] === BACK));
    expect(between.length).toBeGreaterThan(0);
    expect(fronts.length).toBeGreaterThan(0);
    // No triangle lies in both planes, and the corner's vertical edge reaches both grades.
    expect(between.some((triangle) => fronts.includes(triangle))).toBe(false);
    const atCorner = new Set(points(both).filter((point) => point[0] === 30_000 && point[1] === BACK).map((point) => point[2]));
    expect(atCorner.has(2_000) && atCorner.has(2_600)).toBe(true);
  });

  it('on a tile edge, are drawn by the one tile whose half-open span holds them', () => {
    const across = { ring: [[100_000, 128_000 - 10_000], [110_000, 128_000 - 10_000], [110_000, 128_000], [100_000, 128_000]] as [number, number][], gradeMm: 1_000, frontages: [] };
    const beyond = { ring: [[100_000, 128_000], [110_000, 128_000], [110_000, 138_000], [100_000, 138_000]] as [number, number][], gradeMm: 1_500, frontages: [] };
    expect(lotSteps([across, beyond], tile, SPAN, 'case').triangles).toHaveLength(0);
    // One quad, two triangles of three indices each.
    expect(lotSteps([across, beyond], [0, 128_000, 128_000, 256_000], SPAN, 'case').triangles).toHaveLength(2 * 3);
  });
});
