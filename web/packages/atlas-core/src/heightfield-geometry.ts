/** Exact arithmetic for an admitted integer heightfield. Renderer floats are never authority. */
import { canonicalJson } from './style-pack.js';

export interface HeightfieldRational { readonly numerator: string; readonly denominator: string }
export interface ExactRatio { readonly n: bigint; readonly d: bigint }
export type ExactPoint = readonly [ExactRatio, ExactRatio];
export type HeightfieldPoint = readonly [number, number];
export type HeightfieldDigest = (bytes: Uint8Array) => string;

export function ratio(n: bigint, d = 1n): ExactRatio {
  if (d === 0n) throw new Error('zero rational denominator');
  if (d < 0n) { n = -n; d = -d; }
  let a = n < 0n ? -n : n, b = d;
  while (b !== 0n) { const r = a % b; a = b; b = r; }
  return Object.freeze({ n: n / a, d: d / a });
}
export const plus = (a: ExactRatio, b: ExactRatio): ExactRatio => ratio(a.n * b.d + b.n * a.d, a.d * b.d);
export const minus = (a: ExactRatio, b: ExactRatio): ExactRatio => ratio(a.n * b.d - b.n * a.d, a.d * b.d);
export const times = (a: ExactRatio, b: ExactRatio): ExactRatio => ratio(a.n * b.n, a.d * b.d);
export const divide = (a: ExactRatio, b: ExactRatio): ExactRatio => ratio(a.n * b.d, a.d * b.n);
export const compare = (a: ExactRatio, b: ExactRatio): number => { const d = a.n * b.d - b.n * a.d; return d < 0n ? -1 : d > 0n ? 1 : 0; };
export const rationalWire = (value: ExactRatio): HeightfieldRational => Object.freeze({ numerator: value.n.toString(), denominator: value.d.toString() });
export const exactPoint = ([east, south]: HeightfieldPoint): ExactPoint => [ratio(BigInt(east)), ratio(BigInt(south))];
export function cross(a: ExactPoint, b: ExactPoint, c: ExactPoint): ExactRatio {
  return minus(times(minus(b[0], a[0]), minus(c[1], a[1])), times(minus(b[1], a[1]), minus(c[0], a[0])));
}
/** Closed half-plane clipping retains boundary vertices, including line/point intersections. */
export function clipPolygon(subject: readonly ExactPoint[], edgeA: ExactPoint, edgeB: ExactPoint): ExactPoint[] {
  if (subject.length === 0) return [];
  const output: ExactPoint[] = [];
  let previous = subject[subject.length - 1]!, prior = cross(edgeA, edgeB, previous);
  for (const point of subject) {
    const side = cross(edgeA, edgeB, point);
    if ((prior.n < 0n) !== (side.n < 0n)) {
      const t = divide(prior, minus(prior, side));
      output.push([plus(previous[0], times(t, minus(point[0], previous[0]))), plus(previous[1], times(t, minus(point[1], previous[1])))]);
    }
    if (side.n >= 0n) output.push(point);
    previous = point; prior = side;
  }
  const distinct = output.filter((point, i) => i === 0 || compare(point[0], output[i - 1]![0]) !== 0 || compare(point[1], output[i - 1]![1]) !== 0);
  if (distinct.length > 1 && compare(distinct[0]![0], distinct[distinct.length - 1]![0]) === 0 && compare(distinct[0]![1], distinct[distinct.length - 1]![1]) === 0) distinct.pop();
  return distinct;
}
export function convexHull(points: readonly HeightfieldPoint[]): ExactPoint[] {
  const ordered = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]).filter((p, i, all) => i === 0 || p[0] !== all[i - 1]![0] || p[1] !== all[i - 1]![1]).map(exactPoint);
  const half = (list: readonly ExactPoint[]): ExactPoint[] => {
    const result: ExactPoint[] = [];
    for (const point of list) {
      while (result.length >= 2 && cross(result[result.length - 2]!, result[result.length - 1]!, point).n <= 0n) result.pop();
      result.push(point);
    }
    result.pop(); return result;
  };
  return [...half(ordered), ...half([...ordered].reverse())];
}

export class HeightfieldGeometryError extends Error {
  constructor(readonly code: string, readonly where: string, detail: string) { super(`${where}: ${detail}`); }
}
export function requireHeightfield(okay: boolean, where: string, detail: string): asserts okay {
  if (!okay) throw new HeightfieldGeometryError('heightfield_geometry_invalid', where, detail);
}
export function heightfieldObject(raw: unknown, fields: string, where: string): Record<string, unknown> {
  requireHeightfield(raw !== null && typeof raw === 'object' && !Array.isArray(raw), where, 'is an object');
  const row = raw as Record<string, unknown>;
  requireHeightfield(Object.keys(row).sort().join(' ') === fields.split(' ').sort().join(' '), where, 'states exactly its contract fields');
  return row;
}
export function heightfieldInteger(raw: unknown, minimum: number, maximum: number, where: string): number {
  requireHeightfield(typeof raw === 'number' && Number.isSafeInteger(raw) && raw >= minimum && raw <= maximum, where, 'is a bounded integer');
  return raw;
}
export function heightfieldIdentity(raw: unknown, where: string): string {
  requireHeightfield(typeof raw === 'string' && /^[a-z][a-z0-9_.:-]{0,127}$/.test(raw), where, 'is a bounded identity'); return raw;
}
export function heightfieldSha(raw: unknown, where: string): string {
  requireHeightfield(typeof raw === 'string' && /^[0-9a-f]{64}$/.test(raw), where, 'is a lowercase SHA-256'); return raw;
}
export function freezeHeightfield<T>(value: T): T {
  if (value !== null && typeof value === 'object') { for (const child of Object.values(value)) freezeHeightfield(child); Object.freeze(value); }
  return value;
}
export function checkedHeightfieldDocument(raw: unknown, digest: HeightfieldDigest, maximumBytes: number, expected?: string): string {
  const text = canonicalJson(raw);
  requireHeightfield(text.length <= maximumBytes, 'document', 'fits its canonical byte bound');
  const actual = heightfieldSha(digest(new TextEncoder().encode(text)), 'digest');
  if (expected !== undefined) requireHeightfield(heightfieldSha(expected, 'expected_sha256') === actual, 'expected_sha256', 'matches the canonical realization');
  return actual;
}

export interface HeightfieldGeometryDocument {
  readonly profile: 'exulanica.heightfield-geometry/v1';
  readonly component_id: string;
  readonly frame: 'region-local-east-up-south-mm';
  readonly east_mm: readonly number[];
  readonly south_mm: readonly number[];
  readonly height_mm: readonly number[];
  readonly diagonal: 'a-c-b,b-c-d';
  readonly provenance: {
    readonly kind: 'authored' | 'generated'; readonly source_sha256: string;
    readonly generator_id: string; readonly generator_version: number; readonly input_sha256: string;
  };
}
export type HeightfieldTriangleSelector = readonly [number, number, number];
export interface HeightfieldPointContact {
  readonly geometry_sha256: string;
  readonly component_id: string;
  readonly triangle: HeightfieldTriangleSelector;
  readonly height_mm: HeightfieldRational;
  readonly normal: readonly [string, string, string];
}
export interface ExactTriangle {
  readonly selector: HeightfieldTriangleSelector;
  readonly polygon: readonly ExactPoint[];
  readonly normal: readonly [bigint, bigint, bigint];
  readonly origin: readonly [bigint, bigint, bigint];
}
export interface HeightfieldGeometry {
  readonly sha256: string;
  readonly data: HeightfieldGeometryDocument;
  document(): HeightfieldGeometryDocument;
}
export function readHeightfieldGeometry(raw: unknown, digest: HeightfieldDigest, expectedSha256?: string): HeightfieldGeometry {
  const row = heightfieldObject(raw, 'profile component_id frame east_mm south_mm height_mm diagonal provenance', 'geometry');
  requireHeightfield(row['profile'] === 'exulanica.heightfield-geometry/v1', 'profile', 'names heightfield geometry v1');
  requireHeightfield(row['frame'] === 'region-local-east-up-south-mm', 'frame', 'names the region millimetre frame');
  requireHeightfield(row['diagonal'] === 'a-c-b,b-c-d', 'diagonal', 'uses the fixed upward triangles');
  heightfieldIdentity(row['component_id'], 'component_id');
  for (const axis of ['east_mm', 'south_mm']) {
    const values = row[axis];
    requireHeightfield(Array.isArray(values) && values.length >= 2 && values.length <= 257, axis, 'contains 2 through 257 positions');
    for (let i = 0; i < values.length; i++) {
      const value = heightfieldInteger(values[i], -256000, 256000, axis);
      if (i > 0) requireHeightfield(value - (values[i - 1] as number) >= 250 && value - (values[i - 1] as number) <= 2000, axis, 'increases by 250 through 2000 mm');
    }
  }
  const heights = row['height_mm'];
  requireHeightfield(Array.isArray(heights) && heights.length === (row['east_mm'] as number[]).length * (row['south_mm'] as number[]).length, 'height_mm', 'has one row-major height per vertex');
  for (const value of heights) heightfieldInteger(value, -64000, 64000, 'height_mm');
  const provenance = heightfieldObject(row['provenance'], 'kind source_sha256 generator_id generator_version input_sha256', 'provenance');
  requireHeightfield(provenance['kind'] === 'authored' || provenance['kind'] === 'generated', 'provenance.kind', 'states authored or generated');
  heightfieldIdentity(provenance['generator_id'], 'provenance.generator_id');
  heightfieldInteger(provenance['generator_version'], 1, 2147483647, 'provenance.generator_version');
  heightfieldSha(provenance['source_sha256'], 'provenance.source_sha256');
  heightfieldSha(provenance['input_sha256'], 'provenance.input_sha256');
  const sha256 = checkedHeightfieldDocument(raw, digest, 1048576, expectedSha256);
  const data = freezeHeightfield(JSON.parse(canonicalJson(raw)) as HeightfieldGeometryDocument);
  return Object.freeze({ sha256, data, document: () => JSON.parse(canonicalJson(data)) as HeightfieldGeometryDocument });
}
export function heightfieldPosition(raw: unknown): HeightfieldPoint {
  requireHeightfield(Array.isArray(raw) && raw.length === 2, 'position', 'states east and south');
  return [heightfieldInteger(raw[0], -512000, 512000, 'east'), heightfieldInteger(raw[1], -512000, 512000, 'south')];
}
export function candidateCells(axis: readonly number[], low: number, high: number): number[] {
  const cells: number[] = [];
  for (let i = 0; i < axis.length - 1; i++) if (axis[i]! <= high && low <= axis[i + 1]!) cells.push(i);
  return cells;
}
function gcd(a: bigint, b: bigint): bigint { a = a < 0n ? -a : a; b = b < 0n ? -b : b; while (b !== 0n) { const r = a % b; a = b; b = r; } return a; }
export function heightfieldTriangle(geometry: HeightfieldGeometry, row: number, column: number, half: number): ExactTriangle {
  const d = geometry.data, width = d.east_mm.length;
  heightfieldInteger(row, 0, d.south_mm.length - 2, 'triangle.row');
  heightfieldInteger(column, 0, width - 2, 'triangle.column');
  heightfieldInteger(half, 0, 1, 'triangle.half');
  const vertex = (x: number, z: number): readonly [bigint, bigint, bigint] => [BigInt(d.east_mm[x]!), BigInt(d.height_mm[z * width + x]!), BigInt(d.south_mm[z]!)];
  const a = vertex(column, row), b = vertex(column + 1, row), c = vertex(column, row + 1), e = vertex(column + 1, row + 1);
  const vertices = half === 0 ? [a, c, b] as const : [b, c, e] as const;
  const [p, q, r] = vertices;
  const u = q.map((v, i) => v - p[i]!) as [bigint, bigint, bigint], v = r.map((n, i) => n - p[i]!) as [bigint, bigint, bigint];
  const n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]] as const;
  const factor = gcd(gcd(n[0], n[1]), n[2]);
  return { selector: [row, column, half], origin: p, normal: [n[0] / factor, n[1] / factor, n[2] / factor], polygon: [p, r, q].map(vertex => [ratio(vertex[0]), ratio(vertex[2])] as const) };
}
export function triangleHeight(triangle: ExactTriangle, point: ExactPoint): ExactRatio {
  const [east, up, south] = triangle.normal, [x, y, z] = triangle.origin;
  return minus(ratio(y), divide(plus(times(ratio(east), minus(point[0], ratio(x))), times(ratio(south), minus(point[1], ratio(z)))), ratio(up)));
}
export function pointContact(geometry: HeightfieldGeometry, position: HeightfieldPoint): HeightfieldPointContact | null {
  const [east, south] = heightfieldPosition(position), point = exactPoint([east, south]);
  for (const row of candidateCells(geometry.data.south_mm, south, south)) for (const column of candidateCells(geometry.data.east_mm, east, east)) for (const half of [0, 1]) {
    const triangle = heightfieldTriangle(geometry, row, column, half);
    if (triangle.polygon.every((a, i, all) => cross(a, all[(i + 1) % 3]!, point).n >= 0n)) return freezeHeightfield({ geometry_sha256: geometry.sha256, component_id: geometry.data.component_id, triangle: triangle.selector, height_mm: rationalWire(triangleHeight(triangle, point)), normal: triangle.normal.map(n => n.toString()) as unknown as readonly [string, string, string] });
  }
  return null;
}
