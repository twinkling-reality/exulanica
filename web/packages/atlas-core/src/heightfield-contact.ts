/** Complete conservative swept-square contact against one admitted heightfield realization. */
import { canonicalJson } from './style-pack.js';
import {
  candidateCells, checkedHeightfieldDocument, clipPolygon, compare, convexHull,
  exactPoint, freezeHeightfield, heightfieldIdentity, heightfieldInteger, heightfieldObject,
  heightfieldPosition, heightfieldSha, heightfieldTriangle, pointContact, ratio,
  rationalWire, requireHeightfield, triangleHeight,
  type ExactPoint, type ExactRatio, type ExactTriangle, type HeightfieldDigest,
  type HeightfieldGeometry, type HeightfieldPoint, type HeightfieldPointContact, type HeightfieldRational,
} from './heightfield-geometry.js';

export const HEIGHTFIELD_PERSON_POLICY = 'person-square-680x1800-dry350-slope6248-v1';
export type HeightfieldObstruction =
  | { readonly kind: 'unknown'; readonly obstruction_id: string }
  | { readonly kind: 'aabb'; readonly obstruction_id: string; readonly bounds_mm: readonly [number, number, number, number, number, number] };
export interface HeightfieldContactDocument {
  readonly profile: 'exulanica.heightfield-contact/v1';
  readonly geometry_sha256: string;
  readonly component_id: string;
  readonly policy: typeof HEIGHTFIELD_PERSON_POLICY;
  readonly obstructions: readonly HeightfieldObstruction[];
}
export type HeightfieldRefusal = 'outside_domain' | 'segment_limit' | 'work_limit' | 'unknown_obstruction' | 'wet' | 'steep' | 'obstructed' | 'not_flat';
export interface HeightfieldContactResult {
  readonly status: 'clear' | 'blocked' | 'unavailable';
  readonly reason: HeightfieldRefusal | null;
  readonly contact: HeightfieldPointContact | null;
  readonly height_range_mm: readonly [HeightfieldRational, HeightfieldRational] | null;
  readonly triangles: number;
}
export interface HeightfieldContact {
  readonly sha256: string;
  readonly geometry: HeightfieldGeometry;
  readonly data: HeightfieldContactDocument;
  document(): HeightfieldContactDocument;
}
export function readHeightfieldContact(raw: unknown, geometry: HeightfieldGeometry, digest: HeightfieldDigest, expectedSha256?: string): HeightfieldContact {
  const row = heightfieldObject(raw, 'profile geometry_sha256 component_id policy obstructions', 'contact');
  requireHeightfield(row['profile'] === 'exulanica.heightfield-contact/v1', 'profile', 'names heightfield contact v1');
  requireHeightfield(heightfieldSha(row['geometry_sha256'], 'geometry_sha256') === geometry.sha256, 'geometry_sha256', 'binds the admitted realization');
  requireHeightfield(heightfieldIdentity(row['component_id'], 'component_id') === geometry.data.component_id, 'component_id', 'binds the admitted component');
  requireHeightfield(row['policy'] === HEIGHTFIELD_PERSON_POLICY, 'policy', 'names the bounded person policy');
  const obstructions = row['obstructions'];
  requireHeightfield(Array.isArray(obstructions) && obstructions.length <= 512, 'obstructions', 'contains at most 512 conservative proxies');
  let previous = '';
  for (const rawObstruction of obstructions) {
    requireHeightfield(rawObstruction !== null && typeof rawObstruction === 'object' && !Array.isArray(rawObstruction), 'obstruction', 'is an object');
    const kind = (rawObstruction as Record<string, unknown>)['kind'];
    requireHeightfield(kind === 'aabb' || kind === 'unknown', 'obstruction.kind', 'is aabb or unknown');
    const obstruction = heightfieldObject(rawObstruction, kind === 'aabb' ? 'kind obstruction_id bounds_mm' : 'kind obstruction_id', 'obstruction');
    const id = heightfieldIdentity(obstruction['obstruction_id'], 'obstruction_id');
    requireHeightfield(previous < id, 'obstruction_id', 'is unique and in lexical order'); previous = id;
    if (kind === 'aabb') {
      const bounds = obstruction['bounds_mm'];
      requireHeightfield(Array.isArray(bounds) && bounds.length === 6, 'bounds_mm', 'states east/up/south minimum and maximum');
      const checked = bounds.map(value => heightfieldInteger(value, -512000, 512000, 'bounds_mm'));
      for (let i = 0; i < 3; i++) requireHeightfield(checked[i]! <= checked[i + 3]!, 'bounds_mm', 'has ordered closed extents');
    }
  }
  const sha256 = checkedHeightfieldDocument(raw, digest, 131072, expectedSha256);
  const data = freezeHeightfield(JSON.parse(canonicalJson(raw)) as HeightfieldContactDocument);
  return Object.freeze({ sha256, geometry, data, document: () => JSON.parse(canonicalJson(data)) as HeightfieldContactDocument });
}
interface Piece { readonly triangle: ExactTriangle; readonly polygon: readonly ExactPoint[]; readonly bounds: readonly [ExactRatio, ExactRatio, ExactRatio, ExactRatio] }
function result(reason: HeightfieldRefusal | null, contact: HeightfieldPointContact | null = null, range: readonly [ExactRatio, ExactRatio] | null = null, triangles = 0): HeightfieldContactResult {
  return freezeHeightfield({ status: reason === null ? 'clear' : reason === 'unknown_obstruction' || reason === 'work_limit' ? 'unavailable' : 'blocked', reason, contact, height_range_mm: range === null ? null : [rationalWire(range[0]), rationalWire(range[1])], triangles });
}
function clippedTo(polygon: readonly ExactPoint[], boundary: readonly ExactPoint[]): readonly ExactPoint[] {
  let clipped = polygon;
  for (let i = 0; i < boundary.length && clipped.length > 0; i++) clipped = clipPolygon(clipped, boundary[i]!, boundary[(i + 1) % boundary.length]!);
  return clipped;
}
function footprint([east, south]: HeightfieldPoint, half: number): HeightfieldPoint[] {
  return [[east - half, south - half], [east + half, south - half], [east + half, south + half], [east - half, south + half]];
}
function query(contact: HeightfieldContact, start: HeightfieldPoint, end: HeightfieldPoint, half: number, height: number, patch: boolean): HeightfieldContactResult {
  const from = heightfieldPosition(start), to = heightfieldPosition(end);
  const dx = BigInt(to[0]) - BigInt(from[0]), dz = BigInt(to[1]) - BigInt(from[1]);
  if (!patch && dx * dx + dz * dz > 2000n * 2000n) return result('segment_limit');
  const eastLow = Math.min(from[0], to[0]) - half, eastHigh = Math.max(from[0], to[0]) + half;
  const southLow = Math.min(from[1], to[1]) - half, southHigh = Math.max(from[1], to[1]) + half;
  const geometry = contact.geometry, data = geometry.data;
  // The convex rectangular domain covers the entire hull exactly iff it covers these extrema.
  if (eastLow < data.east_mm[0]! || eastHigh > data.east_mm[data.east_mm.length - 1]! || southLow < data.south_mm[0]! || southHigh > data.south_mm[data.south_mm.length - 1]!) return result('outside_domain');
  const rows = candidateCells(data.south_mm, southLow, southHigh), columns = candidateCells(data.east_mm, eastLow, eastHigh);
  const candidateTriangles = rows.length * columns.length * 2;
  if (candidateTriangles > 4096 || candidateTriangles * (1 + contact.data.obstructions.length) > 262144) return result('work_limit');
  if (contact.data.obstructions.some(o => o.kind === 'unknown')) return result('unknown_obstruction');
  const polygon = convexHull([...footprint(from, half), ...footprint(to, half)]), pieces: Piece[] = [];
  let low: ExactRatio | undefined, high: ExactRatio | undefined;
  for (const row of rows) for (const column of columns) for (const triangleIndex of [0, 1]) {
    const triangle = heightfieldTriangle(geometry, row, column, triangleIndex);
    const clipped = clippedTo(polygon, triangle.polygon);
    if (clipped.length === 0) continue;
    let pieceLow = triangleHeight(triangle, clipped[0]!), pieceHigh = pieceLow;
    for (const point of clipped.slice(1)) { const h = triangleHeight(triangle, point); if (compare(h, pieceLow) < 0) pieceLow = h; if (compare(h, pieceHigh) > 0) pieceHigh = h; }
    let x0 = clipped[0]![0], x1 = x0, z0 = clipped[0]![1], z1 = z0;
    for (const [x, z] of clipped.slice(1)) {
      if (compare(x, x0) < 0) x0 = x; if (compare(x, x1) > 0) x1 = x;
      if (compare(z, z0) < 0) z0 = z; if (compare(z, z1) > 0) z1 = z;
    }
    pieces.push({ triangle, polygon: clipped, bounds: [x0, z0, x1, z1] });
    if (low === undefined || compare(pieceLow, low) < 0) low = pieceLow;
    if (high === undefined || compare(pieceHigh, high) > 0) high = pieceHigh;
  }
  if (low === undefined || high === undefined) throw new Error('admitted domain has no swept coverage');
  const endpoint = pointContact(geometry, to), range = [low, high] as const;
  const answered = (reason: HeightfieldRefusal | null) => result(reason, endpoint, range, pieces.length);
  if (compare(low, ratio(350n)) < 0) return answered('wet');
  if (patch) { if (compare(low, high) !== 0 || low.d !== 1n) return answered('not_flat'); }
  else if (pieces.some(({ triangle: { normal: [east, up, south] } }) => (east * east + south * south) * 10000n ** 2n > up * up * 6248n ** 2n)) return answered('steep');
  for (const piece of pieces) for (const obstruction of contact.data.obstructions) {
    if (obstruction.kind !== 'aabb') continue;
    const [x0, y0, z0, x1, y1, z1] = obstruction.bounds_mm;
    // A centre-grounded upright body extends above neighbouring lower triangles. The whole
    // swept floor envelope covers that body; extruding each piece alone could miss its head.
    if (compare(low, ratio(BigInt(y1))) > 0 || compare(ratio(BigInt(y0)), { n: high.n + BigInt(height) * high.d, d: high.d }) > 0) continue;
    if (compare(piece.bounds[0], ratio(BigInt(x1))) > 0 || compare(piece.bounds[2], ratio(BigInt(x0))) < 0 || compare(piece.bounds[1], ratio(BigInt(z1))) > 0 || compare(piece.bounds[3], ratio(BigInt(z0))) < 0) continue;
    // Unit directed lines retain all four constraints even for a zero-thickness box.
    const edges: readonly (readonly [HeightfieldPoint, HeightfieldPoint])[] = [
      [[x0, z0], [x0 + 1, z0]], [[x1, z0], [x1, z0 + 1]],
      [[x1, z1], [x1 - 1, z1]], [[x0, z1], [x0, z1 - 1]],
    ];
    let overlap = piece.polygon;
    for (const [a, b] of edges) overlap = clipPolygon(overlap, exactPoint(a), exactPoint(b));
    if (overlap.length > 0) return answered('obstructed');
  }
  return answered(null);
}
export function sweep(contact: HeightfieldContact, start: HeightfieldPoint, end: HeightfieldPoint): HeightfieldContactResult { return query(contact, start, end, 340, 1800, false); }
export function at(contact: HeightfieldContact, position: HeightfieldPoint): HeightfieldContactResult { return sweep(contact, position, position); }
export function passivePatch(contact: HeightfieldContact, position: HeightfieldPoint, halfWidthMm: number, heightMm: number): HeightfieldContactResult {
  const half = heightfieldInteger(halfWidthMm, 1, 256000, 'half_width_mm'), height = heightfieldInteger(heightMm, 1, 128000, 'height_mm');
  return query(contact, position, position, half, height, true);
}
