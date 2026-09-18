/**
 * THE NAVIGATION PROJECTION TILES THE PLANE IT COVERS, measured over the whole projection rather
 * than along one route.
 *
 * WHY THIS EXISTS. A walker's sampler asks, at a plan point, which triangle holds it. A mesh that
 * tiles answers for every point inside its outline; one that does not has points inside its outline
 * that no triangle holds, and the sampler is right to refuse them. On 2026-09-18 a walk stopped and
 * a crack was the first explanation offered. It was not the cause. But nobody could say so, because
 * nothing measured whether this mesh has cracks at all.
 *
 * THE MEASUREMENT. Along a line of constant x, the triangles crossing it cover intervals in y.
 * Merge them, and a gap with cover on both sides along the line is a candidate. The same along
 * constant y. Each triangle's span at a line is SOLVED from its edges rather than sampled, so a gap
 * of a thousandth of a millimetre is found as surely as one of thirty.
 *
 * A GRAZE IS NOT A GAP, AND THIS IS THE TRAP THE MEASUREMENT EXISTS TO AVOID. A line that runs
 * along a ragged boundary reads as covered, uncovered, covered, because the boundary juts past the
 * line in two places and falls back between them. Nothing is missing: the uncovered part is OUTSIDE
 * the surface rather than absent from it. The first version of this scan called 79 of those a crack
 * in the corridor tile, up to 56 mm wide, and every one was a graze: the widest sat at exactly one
 * value of x between two 1 mm slivers, with no gap at all one millimetre to either side.
 *
 * So a gap counts only when it PERSISTS: a gap overlapping it must also appear on a neighbouring
 * line. A band of missing plane shows on as many lines as it is long; a graze shows on one.
 *
 * A DISCARDED FILTER, recorded because a clean result reads as if it went smoothly. The first
 * attempt at separating a graze from a gap asked whether the plane was covered one millimetre to
 * either side of the gap's midpoint. That point is inside a clearance hole of the capsule's own
 * radius, so the filter deleted all 1,824 real holes in the fixture. It was caught by the count
 * going to zero, which a clearance carve cannot do, and not by reading the filter.
 *
 * WHAT IT CANNOT SEE, stated so an absence from it is not read as wider than it is:
 *   - it scans lines at a spacing, so a gap shorter than that spacing is dropped along with grazes;
 *   - it says nothing about height, only about cover in plan;
 *   - a gap it finds is interior along its own line, which is why persistence is required.
 */
import { describe, expect, it } from 'vitest';
import { bakeTile } from '../src/core/bake.js';
import { CITY_V2 } from '../src/core/city-v2.js';
import { nodeSha256 } from '../src/node/index.js';
import { absoluteVertices, decodeOwd } from '../src/core/owd.js';
import type { DecodedOwd } from '../src/core/owd.js';
import { fixtureBytes } from './support.js';

type Corner = [number, number];
interface Gap { readonly axis: 0 | 1; readonly line: number; readonly from: number; readonly to: number }

/** Every triangle of a projection in plan, in the container's own frame, as this test reads it. */
function planTriangles(projection: any): Corner[][] {
  const absolute = absoluteVertices(projection);
  const origin = projection.header.origin_mm as number[];
  const out: Corner[][] = [];
  for (let triangle = 0; triangle < projection.header.triangle_count; triangle += 1) {
    out.push([0, 1, 2].map((at) => {
      const vertex = projection.index[triangle * 3 + at]!;
      return [absolute[vertex * 3]! - origin[0]!, absolute[vertex * 3 + 1]! - origin[1]!] as Corner;
    }));
  }
  return out;
}

/** Gaps a single line finds on one axis, before the persistence test. */
function gapsOnAxis(triangles: readonly Corner[][], axis: 0 | 1, spacing: number): Gap[] {
  const other = axis === 0 ? 1 : 0;
  let low = Infinity;
  let high = -Infinity;
  for (const corners of triangles) {
    for (const point of corners) { low = Math.min(low, point[axis]); high = Math.max(high, point[axis]); }
  }
  // A sweep rather than a list per line: one triangle here spans eleven metres, and an entry per
  // line it crosses exhausts the heap on a street tile.
  const entering = new Map<number, number[]>();
  const leaving = new Map<number, number[]>();
  const push = (into: Map<number, number[]>, line: number, triangle: number): void => {
    const list = into.get(line);
    if (list === undefined) into.set(line, [triangle]); else list.push(triangle);
  };
  triangles.forEach((corners, triangle) => {
    push(entering, Math.ceil(Math.min(...corners.map((p) => p[axis])) / spacing), triangle);
    push(leaving, Math.floor(Math.max(...corners.map((p) => p[axis])) / spacing) + 1, triangle);
  });
  const active = new Set<number>();
  const found: Gap[] = [];
  for (let line = Math.ceil(low / spacing); line <= Math.floor(high / spacing); line += 1) {
    for (const triangle of entering.get(line) ?? []) active.add(triangle);
    for (const triangle of leaving.get(line) ?? []) active.delete(triangle);
    if (active.size < 2) continue;
    const at = line * spacing;
    const spans: [number, number][] = [];
    for (const triangle of active) {
      const corners = triangles[triangle]!;
      const values: number[] = [];
      for (let edge = 0; edge < 3; edge += 1) {
        const a = corners[edge]!;
        const b = corners[(edge + 1) % 3]!;
        if (a[axis] === b[axis]) {
          if (a[axis] === at) values.push(a[other], b[other]);
          continue;
        }
        if (at < Math.min(a[axis], b[axis]) || at > Math.max(a[axis], b[axis])) continue;
        values.push(a[other] + (b[other] - a[other]) * (at - a[axis]) / (b[axis] - a[axis]));
      }
      if (values.length === 0) continue;
      const from = Math.min(...values);
      const to = Math.max(...values);
      if (to > from) spans.push([from, to]);
    }
    if (spans.length < 2) continue;
    spans.sort((one, two) => one[0] - two[0]);
    let reach = spans[0]![1];
    for (const next of spans.slice(1)) {
      if (next[0] > reach) found.push({ axis, line: at, from: reach, to: next[0] });
      if (next[1] > reach) reach = next[1];
    }
  }
  return found;
}

/** Only the gaps a neighbouring line agrees about, so a graze along a ragged boundary is dropped. */
function persisting(gaps: readonly Gap[], spacing: number): Gap[] {
  const byLine = new Map<string, Gap[]>();
  for (const gap of gaps) {
    const at = `${String(gap.axis)}:${String(Math.round(gap.line / spacing))}`;
    const list = byLine.get(at);
    if (list === undefined) byLine.set(at, [gap]); else list.push(gap);
  }
  const overlaps = (gap: Gap, step: number): boolean =>
    (byLine.get(`${String(gap.axis)}:${String(Math.round(gap.line / spacing) + step)}`) ?? [])
      .some((other) => other.from < gap.to && gap.from < other.to);
  return gaps.filter((gap) => overlaps(gap, 1) || overlaps(gap, -1));
}

/**
 * The width below which a reported gap is this scan's own arithmetic rather than the mesh.
 *
 * A span's ends are solved by interpolating along an edge in doubles, so two spans that meet EXACTLY
 * can be solved to values one unit in the last place apart, and the merge then reports a gap of
 * that. Measured on the conformance fixture: four such, all 7.276e-12 mm, at coordinates near
 * 45,348, which is one unit in the last place there. This floor is a few of those, derived from the
 * largest coordinate in the mesh rather than chosen: about 5e-10 mm on this fixture, nine orders of
 * magnitude below the millimetre a walker is measured in and four above the rounding it excludes.
 */
function roundingFloor(triangles: readonly Corner[][]): number {
  let largest = 0;
  for (const corners of triangles) {
    for (const point of corners) largest = Math.max(largest, Math.abs(point[0]), Math.abs(point[1]));
  }
  return largest * Number.EPSILON * 16;
}

/** Every band of plane inside the projection that no triangle holds, by the rule above. */
function holesOf(triangles: readonly Corner[][], spacing: number): Gap[] {
  const floor = roundingFloor(triangles);
  const found = [...gapsOnAxis(triangles, 0, spacing), ...gapsOnAxis(triangles, 1, spacing)]
    .filter((gap) => gap.to - gap.from > floor);
  return persisting(found, spacing);
}

const SPACING_MM = 1;

/**
 * THE NARROWEST HOLE A CLEARANCE CARVE CAN SHOW AT THIS SPACING, derived rather than chosen.
 *
 * Every hole this projection is supposed to have is a region a capsule is kept out of, and every
 * such region's corners are arcs of at least the capsule's radius (`ring-clearance.ts`). A scan line
 * misses the tangent of such an arc by under one spacing, and a chord of a circle of radius `r` at
 * depth `d` is `2 * sqrt(2 * r * d - d * d)` long. So a hole narrower than that is not an arc of a
 * clearance region, and the only other thing it can be is a crack.
 */
const capsule = CITY_V2.measures.nav_envelope!.capsule_clearance!.radius_mm!;
const NARROWEST_CLEARANCE_CHORD_MM = 2 * Math.sqrt(2 * capsule * SPACING_MM - SPACING_MM * SPACING_MM);

async function fixtureProjections(bytes: Uint8Array = fixtureBytes()): Promise<DecodedOwd> {
  return decodeOwd((await bakeTile(bytes, nodeSha256)).container);
}

describe('the conformance fixture\'s navigation projection', () => {
  it('holds no band of plane narrower than a clearance arc can be, which is what a crack looks like', async () => {
    const decoded = await fixtureProjections();
    const nav = decoded.projections.find((projection) => projection.header.name === 'nav_envelope')!;
    const triangles = planTriangles(nav);
    const holes = holesOf(triangles, SPACING_MM);
    // The scan must be seen to find something before its narrow silence means anything: these are
    // the clearance regions the carve is supposed to leave.
    expect(holes.length).toBeGreaterThan(0);
    const narrow = holes.filter((gap) => gap.to - gap.from < NARROWEST_CLEARANCE_CHORD_MM);
    const naming = narrow.slice(0, 5).map((gap) =>
      `${(gap.to - gap.from).toFixed(4)} mm on ${gap.axis === 0 ? 'x' : 'y'} = ${String(gap.line)} from ${gap.from.toFixed(3)}`);
    expect(narrow.length, `narrower than ${NARROWEST_CLEARANCE_CHORD_MM.toFixed(1)} mm: ${naming.join('; ')}`).toBe(0);
  }, 120_000);

  it('finds a crack when there is one, at the width there is one, which is why the silence counts', async () => {
    const decoded = await fixtureProjections();
    const nav = decoded.projections.find((projection) => projection.header.name === 'nav_envelope')!;
    const triangles = planTriangles(nav);
    const before = holesOf(triangles, SPACING_MM).length;
    // Move one triangle of a footway aside. Nothing else changes, so every new gap is the crack.
    const planted = triangles.map((corners, index) =>
      index === 4147 ? corners.map((point): Corner => [point[0] + 32, point[1]]) : corners);
    const holes = holesOf(planted, SPACING_MM);
    const narrow = holes.filter((gap) => gap.to - gap.from < NARROWEST_CLEARANCE_CHORD_MM);
    expect(holes.length).toBeGreaterThan(before);
    // The planted displacement is 32 mm, and the scan reports it at its own width.
    const widest = Math.max(...narrow.map((gap) => gap.to - gap.from));
    expect(widest).toBeCloseTo(32, 6);
    // And it sees far narrower than that too, so the bound above is not the limit of the instrument.
    expect(narrow.filter((gap) => gap.to - gap.from < 10).length).toBeGreaterThan(0);
  }, 120_000);

  it('calls a ragged boundary no gap at all, which is what it got wrong the first time', () => {
    // The shape the carve makes and the shape that fooled the first version of this scan: a
    // surface cut into bands one millimetre tall, whose left end is at 101 except in two bands
    // where it reaches one millimetre further out, to 100. Nothing is missing from it; every band
    // meets the next along a shared line. But the line x = 100 is covered in those two bands and
    // outside the surface between them, so it reads as covered, uncovered, covered.
    const left = (row: number): number => (row === 0 || row === 50 ? 100 : 101);
    const bands: Corner[][] = [];
    for (let row = 0; row < 60; row += 1) {
      bands.push([[left(row), row], [200, row], [200, row + 1]]);
      bands.push([[left(row), row], [200, row + 1], [left(row), row + 1]]);
    }
    const single = [...gapsOnAxis(bands, 0, SPACING_MM), ...gapsOnAxis(bands, 1, SPACING_MM)]
      .filter((gap) => gap.to - gap.from > roundingFloor(bands));
    // The scan does read grazes here, so this case exercises the filter rather than being empty.
    expect(single.length).toBeGreaterThan(0);
    expect(single.every((gap) => gap.to - gap.from < NARROWEST_CLEARANCE_CHORD_MM)).toBe(true);
    // And every one of them is dropped, because none is agreed by a neighbouring line.
    expect(persisting(single, SPACING_MM)).toEqual([]);
    // Break the same staircase by moving one band aside, and the filter keeps what is then real.
    const cracked = bands.map((corners, index) =>
      index >= 40 && index < 60 ? corners.map((point): Corner => [point[0], point[1] + 4]) : corners);
    const kept = persisting(
      [...gapsOnAxis(cracked, 0, SPACING_MM), ...gapsOnAxis(cracked, 1, SPACING_MM)]
        .filter((gap) => gap.to - gap.from > roundingFloor(cracked)),
      SPACING_MM,
    );
    expect(kept.length).toBeGreaterThan(0);
  });
});
