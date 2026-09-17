/**
 * Exact integer tests on rings: tess's ring rule, holes, parts, and whether two glyphs touch.
 *
 * The TypeScript copy of `exulanica.lettering.geometry`, which is itself the copy of the ring rule
 * `exulanica.grammar.geometry.require_ring` and `loom-tess`'s `requireSimpleRing` state: at least
 * three vertices, no zero-length edge, no spike, a positive twice area, and no two edges touching
 * anywhere except the vertex adjacent edges share. The shared cases hold this copy and the Python
 * one to the same answers.
 *
 * Every test is the sign of an integer product. A double holds every integer up to 2^53 exactly,
 * and a catalog's coordinates are sixteen-bit, so a cross product of differences is at most about
 * 2^34 and never rounds. `assertSafe` states that rather than assuming it.
 */

export class GeometryError extends Error {}

export type Point = readonly [number, number];
export type Ring = readonly Point[];
/** An outer ring and its holes, all counter-clockwise. */
export interface Part {
  readonly outer: Ring;
  readonly holes: readonly Ring[];
}

function assertSafe(value: number, where: string): number {
  if (!Number.isSafeInteger(value)) {
    throw new GeometryError(`${where} is ${String(value)}, not an integer a double holds exactly`);
  }
  return value;
}

export function cross(o: Point, a: Point, b: Point): number {
  return assertSafe((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]), 'a cross product');
}

export function twiceArea(ring: Ring): number {
  let total = 0;
  for (let index = 0; index < ring.length; index += 1) {
    const here = ring[index]!;
    const next = ring[(index + 1) % ring.length]!;
    total = assertSafe(total + here[0] * next[1] - next[0] * here[1], 'a ring area');
  }
  return total;
}

const sign = (value: number): number => (value > 0 ? 1 : value < 0 ? -1 : 0);

export function onSegment(p: Point, a: Point, b: Point): boolean {
  if (cross(a, b, p) !== 0) return false;
  return (
    Math.min(a[0], b[0]) <= p[0]
    && p[0] <= Math.max(a[0], b[0])
    && Math.min(a[1], b[1]) <= p[1]
    && p[1] <= Math.max(a[1], b[1])
  );
}

/** Whether the closed segments `p1 p2` and `q1 q2` share any point. */
export function segmentsMeet(p1: Point, p2: Point, q1: Point, q2: Point): boolean {
  const d1 = sign(cross(q1, q2, p1));
  const d2 = sign(cross(q1, q2, p2));
  const d3 = sign(cross(p1, p2, q1));
  const d4 = sign(cross(p1, p2, q2));
  if (d1 * d2 < 0 && d3 * d4 < 0) return true;
  if (d1 === 0 && onSegment(p1, q1, q2)) return true;
  if (d2 === 0 && onSegment(p2, q1, q2)) return true;
  if (d3 === 0 && onSegment(q1, p1, p2)) return true;
  return d4 === 0 && onSegment(q2, p1, p2);
}

type Edge = { readonly a: Point; readonly b: Point; readonly index: number; readonly tag: number };

function edgesOf(ring: Ring, tag: number): Edge[] {
  return ring.map((a, index) => ({ a, b: ring[(index + 1) % ring.length]!, index, tag }));
}

/**
 * Edge pairs whose closed bounding boxes overlap, by a sweep in x: within one ring when `second`
 * is undefined, else across the two. The sweep only skips pairs whose boxes cannot overlap, so it
 * changes which pair is reported first, never whether one is.
 */
function* candidatePairs(first: Edge[], second?: Edge[]): Generator<readonly [Edge, Edge]> {
  const across = second !== undefined;
  const all = across ? [...first, ...second] : first;
  const sorted = [...all].sort((one, two) => {
    const lowOne = Math.min(one.a[0], one.b[0]);
    const lowTwo = Math.min(two.a[0], two.b[0]);
    if (lowOne !== lowTwo) return lowOne - lowTwo;
    if (one.tag !== two.tag) return one.tag - two.tag;
    return one.index - two.index;
  });
  let active: { high: number; low: number; top: number; edge: Edge }[] = [];
  for (const edge of sorted) {
    const xLow = Math.min(edge.a[0], edge.b[0]);
    const xHigh = Math.max(edge.a[0], edge.b[0]);
    const yLow = Math.min(edge.a[1], edge.b[1]);
    const yHigh = Math.max(edge.a[1], edge.b[1]);
    active = active.filter((item) => item.high >= xLow);
    for (const item of active) {
      if (across && item.edge.tag === edge.tag) continue;
      if (item.low <= yHigh && yLow <= item.top) yield [item.edge, edge];
    }
    active.push({ high: xHigh, low: yLow, top: yHigh, edge });
  }
}

/** The first ring-rule test `ring` fails, in words, or null. */
export function ringProblem(ring: Ring): string | null {
  const count = ring.length;
  if (count < 3) return 'has fewer than three vertices';
  for (let index = 0; index < count; index += 1) {
    const a = ring[index]!;
    const b = ring[(index + 1) % count]!;
    if (a[0] === b[0] && a[1] === b[1]) return `edge ${index} has zero length`;
  }
  for (let index = 0; index < count; index += 1) {
    const a = ring[(index + count - 1) % count]!;
    const b = ring[index]!;
    const c = ring[(index + 1) % count]!;
    const forward = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]);
    if (cross(a, b, c) === 0 && forward < 0) return `vertex ${index} is a spike`;
  }
  if (twiceArea(ring) <= 0) return 'is not counter-clockwise with a positive area';
  for (const [one, two] of candidatePairs(edgesOf(ring, 0))) {
    const low = Math.min(one.index, two.index);
    const high = Math.max(one.index, two.index);
    if (high - low < 2 || (low === 0 && high === count - 1)) continue;
    if (segmentsMeet(one.a, one.b, two.a, two.b)) return `edges ${low} and ${high} meet`;
  }
  return null;
}

export type RingSide = 'inside' | 'outside' | 'boundary';

export function pointInRing(point: Point, ring: Ring): RingSide {
  const count = ring.length;
  for (let index = 0; index < count; index += 1) {
    if (onSegment(point, ring[index]!, ring[(index + 1) % count]!)) return 'boundary';
  }
  let inside = false;
  for (let index = 0; index < count; index += 1) {
    const a = ring[index]!;
    const b = ring[(index + 1) % count]!;
    if (a[1] > point[1] !== b[1] > point[1]) {
      const left = (point[0] - a[0]) * (b[1] - a[1]);
      const right = (point[1] - a[1]) * (b[0] - a[0]);
      if (b[1] > a[1] && left < right) inside = !inside;
      if (b[1] < a[1] && left > right) inside = !inside;
    }
  }
  return inside ? 'inside' : 'outside';
}

/** Whether any edge of one ring shares a point with any edge of the other. */
export function ringsMeet(first: Ring, second: Ring): boolean {
  for (const [one, two] of candidatePairs(edgesOf(first, 0), edgesOf(second, 1))) {
    if (segmentsMeet(one.a, one.b, two.a, two.b)) return true;
  }
  return false;
}

/** Whether a vertex of another part, whose edges meet none of this part's, lies off its area. */
function offPart(point: Point, part: Part): boolean {
  const where = pointInRing(point, part.outer);
  if (where === 'outside') return true;
  return where === 'inside' && part.holes.some((hole) => pointInRing(point, hole) === 'inside');
}

function partsMeet(first: Part, second: Part): boolean {
  const ringsFirst = [first.outer, ...first.holes];
  const ringsSecond = [second.outer, ...second.holes];
  if (ringsFirst.some((a) => ringsSecond.some((b) => ringsMeet(a, b)))) return true;
  return !offPart(second.outer[0]!, first) || !offPart(first.outer[0]!, second);
}

/**
 * The first way a glyph's parts break the rule tess triangulates by, in words, or null: every ring
 * passes the ring rule, a hole lies strictly inside its outer ring, two holes of a part share no
 * point, and two parts share no point (a part may sit inside another's hole).
 */
export function partsProblem(parts: readonly Part[]): string | null {
  for (const [index, part] of parts.entries()) {
    const problem = ringProblem(part.outer);
    if (problem) return `part ${index} outer ring ${problem}`;
    for (const [holeIndex, hole] of part.holes.entries()) {
      const holeProblem = ringProblem(hole);
      if (holeProblem) return `part ${index} hole ${holeIndex} ${holeProblem}`;
      if (ringsMeet(hole, part.outer) || hole.some((v) => pointInRing(v, part.outer) !== 'inside')) {
        return `part ${index} hole ${holeIndex} is not strictly inside its outer ring`;
      }
    }
    for (const [holeIndex, hole] of part.holes.entries()) {
      for (let other = holeIndex + 1; other < part.holes.length; other += 1) {
        const second = part.holes[other]!;
        if (
          ringsMeet(hole, second)
          || pointInRing(hole[0]!, second) !== 'outside'
          || pointInRing(second[0]!, hole) !== 'outside'
        ) {
          return `part ${index} holes ${holeIndex} and ${other} meet`;
        }
      }
    }
  }
  for (const [index, part] of parts.entries()) {
    for (let other = index + 1; other < parts.length; other += 1) {
      if (partsMeet(part, parts[other]!)) return `parts ${index} and ${other} meet`;
    }
  }
  return null;
}

function box(parts: readonly Part[]): readonly [number, number, number, number] {
  const xs = parts.flatMap((part) => part.outer.map((point) => point[0]));
  const ys = parts.flatMap((part) => part.outer.map((point) => point[1]));
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

/** Whether two placed glyphs share any point: an edge in common or an area overlapping. */
export function glyphsTouch(first: readonly Part[], second: readonly Part[]): boolean {
  const a = box(first);
  const b = box(second);
  if (a[2] < b[0] || b[2] < a[0] || a[3] < b[1] || b[3] < a[1]) return false;
  return first.some((one) => second.some((two) => partsMeet(one, two)));
}
