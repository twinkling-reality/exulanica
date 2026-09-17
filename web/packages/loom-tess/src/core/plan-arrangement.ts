/**
 * THE PLAN ARRANGEMENT: A CONVEX PIECE LESS A UNION OF TRIANGLES, EXACTLY, IN RATIONALS.
 *
 * The terrain yield rule needs the part of a terrain piece that no covering triangle covers, with
 * its boundary on the coverings' own outlines. This module finds it with no rounding at all:
 *
 *   1. SEGMENTS. The piece's edges and every triangle's edges, each with integer ends. Every pair
 *      is intersected exactly: a crossing is a rational point, and where two segments run along
 *      each other the ends of each are split points of the other. Each segment is split at every
 *      such point on it, in order along it.
 *   2. OWNERS. Pieces of segments with the same two ends are one segment. It records which input
 *      rings it bounds, as a parity: the piece is owner 0 and triangle `i` is owner `i + 1`, and an
 *      owner that bounds a segment twice, as two triangles sharing an edge do not but a triangle
 *      and its own reverse would, cancels. A segment no owner bounds is dropped.
 *   3. FACES. Around every vertex the segments leaving it are ordered by angle, exactly, and each
 *      face is traced with itself on the left: from the half-edge `u -> v`, the next is the one
 *      leaving `v` just clockwise of `v -> u`. A face of positive area is bounded; each connected
 *      group of segments has one face of negative area, its outside.
 *   4. LABELS. Crossing a segment toggles each of its owners. Groups are taken largest outside
 *      first, ties by their first vertex. A group's outside takes the label of the smallest bounded
 *      face of an earlier group that holds one of its vertices, or no owner when none does: a
 *      triangle may hold the whole piece without touching it. Labels spread across segments from
 *      there.
 *   5. KEPT. A bounded face whose label holds the piece and no triangle is inside the piece and in no
 *      triangle. Its holes are the outsides of the groups whose containing face it is.
 *
 * CUT LINES may be added: horizontal segments across the piece's span at given integer heights,
 * owned by `-1`, which toggles nothing that decides a face is kept. They only divide kept faces.
 *
 * Every test is an integer sign in BigInt: nothing here can round, on any engine.
 */
import { GeometryError } from './integer-math.js';
import type { Plan } from './integer-math.js';

/** A plan point `(x / w, y / w)` with `w` positive and the three in lowest terms. */
export interface RationalPoint {
  readonly x: bigint;
  readonly y: bigint;
  readonly w: bigint;
}

/** A kept region: its counter-clockwise outer circuit and its clockwise holes. */
export interface KeptRegion {
  readonly outer: readonly RationalPoint[];
  readonly holes: readonly (readonly RationalPoint[])[];
}

type Pair = readonly [bigint, bigint];

function greatestCommonDivisor(a: bigint, b: bigint): bigint {
  let p = a < 0n ? -a : a;
  let q = b < 0n ? -b : b;
  while (q !== 0n) {
    const rest = p % q;
    p = q;
    q = rest;
  }
  return p;
}

export function rationalPoint(x: bigint, y: bigint, w: bigint, where: string): RationalPoint {
  if (w === 0n) throw new GeometryError(`${where} places a point at infinity`);
  const divisor = greatestCommonDivisor(greatestCommonDivisor(x, y), w);
  const sign = w < 0n ? -1n : 1n;
  return { x: (sign * x) / divisor, y: (sign * y) / divisor, w: (sign * w) / divisor };
}

export const integerPoint = (point: Plan): RationalPoint => ({ x: BigInt(point[0]), y: BigInt(point[1]), w: 1n });

export const keyOf = (point: RationalPoint): string => `${point.x} ${point.y} ${point.w}`;

const crossPair = (u: Pair, v: Pair): bigint => u[0] * v[1] - u[1] * v[0];
const dotPair = (u: Pair, v: Pair): bigint => u[0] * v[0] + u[1] * v[1];

/** The sign of `cross(b - a, p - a)` for rational points: positive when `p` is left of `a -> b`. */
export function sideOf(a: RationalPoint, b: RationalPoint, p: RationalPoint): bigint {
  const along: Pair = [b.x * a.w - a.x * b.w, b.y * a.w - a.y * b.w];
  const toward: Pair = [p.x * a.w - a.x * p.w, p.y * a.w - a.y * p.w];
  const value = crossPair(along, toward);
  return value > 0n ? 1n : value < 0n ? -1n : 0n;
}

/** Whether rational `p` lies on the closed segment from integer `a` to integer `b`. */
export function onIntegerSegment(p: RationalPoint, a: Plan, b: Plan): boolean {
  const start = integerPoint(a);
  const end = integerPoint(b);
  if (sideOf(start, end, p) !== 0n) return false;
  const direction: Pair = [end.x - start.x, end.y - start.y];
  const reach = dotPair([p.x - start.x * p.w, p.y - start.y * p.w], direction);
  return reach >= 0n && reach <= dotPair(direction, direction) * p.w;
}

/** The points of segment `a b` where segment `c d` meets it, all four ends integers. */
export function meetings(a: Pair, b: Pair, c: Pair, d: Pair, where: string): RationalPoint[] {
  const r: Pair = [b[0] - a[0], b[1] - a[1]];
  const s: Pair = [d[0] - c[0], d[1] - c[1]];
  const q: Pair = [c[0] - a[0], c[1] - a[1]];
  let denominator = crossPair(r, s);
  if (denominator !== 0n) {
    let alongFirst = crossPair(q, s);
    let alongSecond = crossPair(q, r);
    if (denominator < 0n) {
      denominator = -denominator;
      alongFirst = -alongFirst;
      alongSecond = -alongSecond;
    }
    if (alongFirst < 0n) return [];
    if (alongFirst > denominator) return [];
    if (alongSecond < 0n) return [];
    if (alongSecond > denominator) return [];
    return [rationalPoint(a[0] * denominator + r[0] * alongFirst, a[1] * denominator + r[1] * alongFirst, denominator, where)];
  }
  if (crossPair(r, q) !== 0n) return [];
  const length = dotPair(r, r);
  return [c, d]
    .filter((end) => {
      const reach = dotPair([end[0] - a[0], end[1] - a[1]], r);
      return reach >= 0n && reach <= length;
    })
    .map((end) => ({ x: end[0], y: end[1], w: 1n }));
}

/** `-1`, `0` or `1` as the rational parameter of `p` along `a -> b` is less, equal or greater than `q`'s. */
function compareAlong(a: Pair, direction: Pair, p: RationalPoint, q: RationalPoint): number {
  const reachP = dotPair([p.x - a[0] * p.w, p.y - a[1] * p.w], direction) * q.w;
  const reachQ = dotPair([q.x - a[0] * q.w, q.y - a[1] * q.w], direction) * p.w;
  return reachP < reachQ ? -1 : reachP > reachQ ? 1 : 0;
}

interface Segment {
  readonly from: RationalPoint;
  readonly to: RationalPoint;
  readonly owners: Set<number>;
}

interface HalfEdge {
  readonly from: string;
  readonly to: string;
  readonly segment: number;
  twin: number;
  face: number;
}

/** A fraction `n / d` with `d` positive. */
interface Fraction {
  readonly n: bigint;
  readonly d: bigint;
}

function addFractions(a: Fraction, b: Fraction): Fraction {
  const n = a.n * b.d + b.n * a.d;
  const d = a.d * b.d;
  const divisor = greatestCommonDivisor(n, d);
  return divisor === 0n ? { n: 0n, d: 1n } : { n: n / divisor, d: d / divisor };
}

const lessFraction = (a: Fraction, b: Fraction): boolean => a.n * b.d < b.n * a.d;

/** Twice the signed area of a circuit of rational points. */
function circuitTwiceArea(circuit: readonly RationalPoint[]): Fraction {
  let total: Fraction = { n: 0n, d: 1n };
  circuit.forEach((here, index) => {
    const next = circuit[(index + 1) % circuit.length]!;
    total = addFractions(total, { n: here.x * next.y - here.y * next.x, d: here.w * next.w });
  });
  return total;
}

/** Whether rational `p` is inside a circuit it is not on, by crossings of a ray toward +x. */
function insideCircuit(p: RationalPoint, circuit: readonly RationalPoint[]): boolean {
  let inside = false;
  circuit.forEach((a, index) => {
    const b = circuit[(index + 1) % circuit.length]!;
    const aAbove = a.y * p.w > p.y * a.w;
    const bAbove = b.y * p.w > p.y * b.w;
    if (aAbove === bAbove) return;
    const side = sideOf(a, b, p);
    if (bAbove && side > 0n) inside = !inside;
    if (aAbove && side < 0n) inside = !inside;
  });
  return inside;
}

/** Whether the half-plane test puts direction `d` in the upper half, from angle 0 inclusive to pi exclusive. */
function upperHalf(d: Pair): boolean {
  if (d[1] > 0n) return true;
  if (d[1] < 0n) return false;
  return d[0] > 0n;
}

/**
 * The regions of a counter-clockwise convex `piece` that no counter-clockwise triangle of
 * `coverings` covers, by the plan arrangement rule.
 */
export function uncoveredRegions(
  piece: readonly Plan[],
  coverings: readonly (readonly [Plan, Plan, Plan])[],
  cutRows: readonly number[],
  where: string,
): KeptRegion[] {
  const inputs: { a: Pair; b: Pair; owner: number }[] = [];
  const ring = (points: readonly Plan[], owner: number): void => {
    points.forEach((point, index) => {
      const next = points[(index + 1) % points.length]!;
      inputs.push({ a: [BigInt(point[0]), BigInt(point[1])], b: [BigInt(next[0]), BigInt(next[1])], owner });
    });
  };
  ring(piece, 0);
  coverings.forEach((triangle, index) => ring(triangle, index + 1));
  const xs = piece.map((point) => BigInt(point[0]));
  const [west, east] = [xs.reduce((a, b) => (a < b ? a : b)), xs.reduce((a, b) => (a > b ? a : b))];
  for (const row of cutRows) inputs.push({ a: [west, BigInt(row)], b: [east, BigInt(row)], owner: -1 });
  const spans = inputs.map((input) => ({
    low: [input.a[0] < input.b[0] ? input.a[0] : input.b[0], input.a[1] < input.b[1] ? input.a[1] : input.b[1]],
    high: [input.a[0] > input.b[0] ? input.a[0] : input.b[0], input.a[1] > input.b[1] ? input.a[1] : input.b[1]],
  }));
  const apart = (first: number, second: number): boolean => {
    const [p, q] = [spans[first]!, spans[second]!];
    if (p.high[0]! < q.low[0]!) return true;
    if (q.high[0]! < p.low[0]!) return true;
    if (p.high[1]! < q.low[1]!) return true;
    return q.high[1]! < p.low[1]!;
  };

  // 1 and 2: split every segment where any other meets it, and merge the pieces by their ends.
  const merged = new Map<string, Segment>();
  inputs.forEach((input, index) => {
    const direction: Pair = [input.b[0] - input.a[0], input.b[1] - input.a[1]];
    const points: RationalPoint[] = [
      { x: input.a[0], y: input.a[1], w: 1n },
      { x: input.b[0], y: input.b[1], w: 1n },
    ];
    inputs.forEach((other, second) => {
      if (second === index) return;
      if (apart(index, second)) return;
      points.push(...meetings(input.a, input.b, other.a, other.b, where));
    });
    points.sort((p, q) => compareAlong(input.a, direction, p, q));
    const distinct: RationalPoint[] = [];
    for (const point of points) {
      if (distinct.length === 0) distinct.push(point);
      else if (keyOf(point) !== keyOf(distinct[distinct.length - 1]!)) distinct.push(point);
    }
    for (let position = 0; position + 1 < distinct.length; position += 1) {
      const [p, q] = [distinct[position]!, distinct[position + 1]!];
      const [low, high] = keyOf(p) < keyOf(q) ? [p, q] : [q, p];
      const key = `${keyOf(low)}|${keyOf(high)}`;
      const existing = merged.get(key);
      const segment = existing === undefined ? { from: low, to: high, owners: new Set<number>() } : existing;
      if (segment.owners.has(input.owner)) segment.owners.delete(input.owner);
      else segment.owners.add(input.owner);
      merged.set(key, segment);
    }
  });
  const segments = [...merged.values()].filter((segment) => segment.owners.size > 0);

  // 3: half-edges, ordered by angle round each vertex, traced into faces.
  const points = new Map<string, RationalPoint>();
  const halfEdges: HalfEdge[] = [];
  segments.forEach((segment, index) => {
    const [from, to] = [keyOf(segment.from), keyOf(segment.to)];
    points.set(from, segment.from);
    points.set(to, segment.to);
    halfEdges.push({ from, to, segment: index, twin: halfEdges.length + 1, face: -1 });
    halfEdges.push({ from: to, to: from, segment: index, twin: halfEdges.length - 1, face: -1 });
  });
  const leaving = new Map<string, number[]>();
  halfEdges.forEach((edge, index) => {
    const list = leaving.get(edge.from);
    if (list === undefined) leaving.set(edge.from, [index]);
    else list.push(index);
  });
  const direction = (edge: HalfEdge): Pair => {
    const [u, v] = [points.get(edge.from)!, points.get(edge.to)!];
    return [v.x * u.w - u.x * v.w, v.y * u.w - u.y * v.w];
  };
  const positionAround = new Map<number, number>();
  for (const list of leaving.values()) {
    list.sort((first, second) => {
      const [d1, d2] = [direction(halfEdges[first]!), direction(halfEdges[second]!)];
      const [upper1, upper2] = [upperHalf(d1), upperHalf(d2)];
      if (upper1 !== upper2) return upper1 ? -1 : 1;
      const turn = crossPair(d1, d2);
      return turn > 0n ? -1 : turn < 0n ? 1 : 0;
    });
    list.forEach((edge, position) => positionAround.set(edge, position));
  }
  const nextOf = (index: number): number => {
    const edge = halfEdges[index]!;
    const list = leaving.get(edge.to)!;
    const back = positionAround.get(edge.twin)!;
    return list[(back + list.length - 1) % list.length]!;
  };
  const faces: { readonly edges: readonly number[]; readonly circuit: readonly RationalPoint[]; readonly area: Fraction }[] = [];
  halfEdges.forEach((_edge, start) => {
    if (halfEdges[start]!.face >= 0) return;
    const edges: number[] = [];
    let at = start;
    while (halfEdges[at]!.face < 0) {
      halfEdges[at]!.face = faces.length;
      edges.push(at);
      at = nextOf(at);
    }
    if (at !== start) throw new GeometryError(`${where}: a face did not close on itself`);
    const circuit = edges.map((edge) => points.get(halfEdges[edge]!.from)!);
    faces.push({ edges, circuit, area: circuitTwiceArea(circuit) });
  });

  // 4: groups of connected segments, each with one outside face, labelled outside in.
  const group = new Map<string, string>();
  const findGroup = (key: string): string => {
    let root = key;
    while (group.get(root) !== root) root = group.get(root)!;
    return root;
  };
  for (const key of points.keys()) group.set(key, key);
  for (const edge of halfEdges) group.set(findGroup(edge.from), findGroup(edge.to));
  const outsides = new Map<string, number>();
  faces.forEach((face, index) => {
    if (face.area.n >= 0n) return;
    const root = findGroup(halfEdges[face.edges[0]!]!.from);
    if (outsides.has(root)) throw new GeometryError(`${where}: a group of segments has two outsides`);
    outsides.set(root, index);
  });
  // Largest outside first, ties by the group's root key, so the order is the same on every engine.
  const order = [...outsides.entries()].sort(([rootA, faceA], [rootB, faceB]) => {
    if (lessFraction(faces[faceA]!.area, faces[faceB]!.area)) return -1;
    if (lessFraction(faces[faceB]!.area, faces[faceA]!.area)) return 1;
    return rootA < rootB ? -1 : 1;
  });
  const labels = new Array<Set<number> | undefined>(faces.length).fill(undefined);
  const containing = new Map<number, number>();
  const labelled: number[] = [];
  for (const [, outside] of order) {
    let start = new Set<number>();
    const probe = faces[outside]!.circuit[0]!;
    let best: number | undefined;
    for (const candidate of labelled) {
      const face = faces[candidate]!;
      if (face.area.n <= 0n) continue;
      if (!insideCircuit(probe, face.circuit)) continue;
      if (best === undefined) best = candidate;
      else if (lessFraction(face.area, faces[best]!.area)) best = candidate;
    }
    if (best !== undefined) {
      start = new Set(labels[best]!);
      containing.set(outside, best);
    }
    labels[outside] = start;
    const queue = [outside];
    while (queue.length > 0) {
      const face = queue.shift()!;
      labelled.push(face);
      for (const edge of faces[face]!.edges) {
        const across = halfEdges[halfEdges[edge]!.twin]!.face;
        if (labels[across] !== undefined) continue;
        const label = new Set(labels[face]!);
        for (const owner of segments[halfEdges[edge]!.segment]!.owners) {
          if (label.has(owner)) label.delete(owner);
          else label.add(owner);
        }
        labels[across] = label;
        queue.push(across);
      }
    }
  }

  // 5: the kept faces, each with the outsides of the groups it contains as holes.
  const kept: KeptRegion[] = [];
  faces.forEach((face, index) => {
    if (face.area.n <= 0n) return;
    const label = labels[index]!;
    if (!label.has(0)) return;
    if ([...label].some((owner) => owner > 0)) return;
    const holes = [...containing.entries()]
      .filter(([, holder]) => holder === index)
      .map(([outside]) => faces[outside]!.circuit);
    kept.push({ outer: face.circuit, holes });
  });
  return kept;
}
