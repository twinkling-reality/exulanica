/**
 * A world's land as the server realizes it (`exulanica.grammar.landform`): chunks of near land a
 * person walks, and the backdrop drawn to the horizon. Pure readers and arithmetic; nothing here
 * draws. A world that states no land has neither, and nothing here is asked.
 *
 * Frame: millimetres east and north of the world's south-west corner, heights above the datum
 * (the sea's level). A scene draws east as x, up as y and north as minus z.
 *
 * - A chunk (`exulanica.landform-chunk/v1`) is 129 samples a side, 1 m apart, rows from its
 *   south-west corner, on the city's 128 m tile grid; each cell is split along its south-west to
 *   north-east diagonal. `groundHeightMm` interpolates on those triangles in floating point for
 *   drawing feet and things; `landChunkGeometry` gives the chunk as exact heightfield geometry for
 *   contact, where floats are never authority. The conformance vectors hold the two together.
 * - The backdrop (`exulanica.landform-backdrop/v1`) is a coarse grid to the horizon, drawn only,
 *   never walked. Its samples on the near land's edge are the near land's own, so the two meet;
 *   `backdropMeshData` sinks its samples inside the near land under it and splits it into blocks
 *   a renderer can cull.
 */
import { canonicalJson } from './style-pack.js';
import type { HeightfieldDigest, HeightfieldGeometryDocument } from './heightfield-geometry.js';

export const LAND_CHUNK_PROFILE = 'exulanica.landform-chunk/v1';
export const LAND_BACKDROP_PROFILE = 'exulanica.landform-backdrop/v1';
export const LAND_CHUNK_MM = 128_000;
export const LAND_CELL_MM = 1_000;
export const LAND_SAMPLES_PER_SIDE = LAND_CHUNK_MM / LAND_CELL_MM + 1;
/** The exact sheet's height bound, the near land's. */
export const LAND_NEAR_BOUND_MM = 64_000;
const BACKDROP_MOST_SAMPLES = 1_000_000;

export class LandformError extends Error {
  constructor(readonly where: string, detail: string) { super(`${where}: ${detail}`); }
}
function require(okay: boolean, where: string, detail: string): asserts okay {
  if (!okay) throw new LandformError(where, detail);
}
function fields(raw: unknown, names: string, where: string): Record<string, unknown> {
  require(raw !== null && typeof raw === 'object' && !Array.isArray(raw), where, 'is an object');
  const row = raw as Record<string, unknown>;
  require(Object.keys(row).sort().join(' ') === names.split(' ').sort().join(' '), where, `states exactly ${names}`);
  return row;
}
function integer(raw: unknown, low: number, high: number, where: string): number {
  require(typeof raw === 'number' && Number.isSafeInteger(raw) && raw >= low && raw <= high, where, `is a whole number from ${low} to ${high}`);
  return raw;
}
function integers(raw: unknown, count: number | null, low: number, high: number, where: string): number[] {
  require(Array.isArray(raw) && (count === null || raw.length === count), where, count === null ? 'is a list' : `lists ${count} values`);
  return (raw as unknown[]).map((value, i) => integer(value, low, high, `${where}[${i}]`));
}
function checked(raw: unknown, digest: HeightfieldDigest, expected: string | undefined, where: string): string {
  const actual = digest(new TextEncoder().encode(canonicalJson(raw)));
  if (expected !== undefined) require(actual === expected, where, 'is the document its digest names');
  return actual;
}

export interface LandChunk {
  readonly chunkX: number;
  readonly chunkY: number;
  readonly cellMm: number;
  readonly samplesPerSide: number;
  readonly heightMm: Int32Array;
  readonly sha256: string;
}

export function readLandChunk(raw: unknown, digest: HeightfieldDigest, expectedSha256?: string): LandChunk {
  const row = fields(raw, 'profile chunk cell_mm samples_per_side height_mm', 'chunk');
  require(row['profile'] === LAND_CHUNK_PROFILE, 'chunk.profile', `is ${LAND_CHUNK_PROFILE}`);
  const [chunkX, chunkY] = integers(row['chunk'], 2, -4096, 4096, 'chunk.chunk');
  require(row['cell_mm'] === LAND_CELL_MM && row['samples_per_side'] === LAND_SAMPLES_PER_SIDE, 'chunk.cell_mm', `a v1 chunk is ${LAND_SAMPLES_PER_SIDE} samples a side, ${LAND_CELL_MM} mm apart`);
  const heights = integers(row['height_mm'], LAND_SAMPLES_PER_SIDE ** 2, -LAND_NEAR_BOUND_MM, LAND_NEAR_BOUND_MM, 'chunk.height_mm');
  const sha256 = checked(raw, digest, expectedSha256, 'chunk');
  return Object.freeze({ chunkX: chunkX!, chunkY: chunkY!, cellMm: LAND_CELL_MM, samplesPerSide: LAND_SAMPLES_PER_SIDE, heightMm: Int32Array.from(heights), sha256 });
}

/** The height of a chunk's land at a point (mm east and north of the world's corner), or null outside it. */
export function chunkHeightMm(chunk: LandChunk, eastMm: number, northMm: number): number | null {
  const n = chunk.samplesPerSide;
  const gx = (eastMm - chunk.chunkX * LAND_CHUNK_MM) / chunk.cellMm;
  const gy = (northMm - chunk.chunkY * LAND_CHUNK_MM) / chunk.cellMm;
  if (!(gx >= 0 && gy >= 0 && gx <= n - 1 && gy <= n - 1)) return null;
  const i = Math.min(n - 2, Math.floor(gx)), j = Math.min(n - 2, Math.floor(gy));
  const fx = gx - i, fy = gy - j, h = chunk.heightMm;
  const h00 = h[j * n + i]!, h10 = h[j * n + i + 1]!, h01 = h[(j + 1) * n + i]!, h11 = h[(j + 1) * n + i + 1]!;
  return fx >= fy ? h00 + (h10 - h00) * fx + (h11 - h10) * fy : h00 + (h11 - h01) * fx + (h01 - h00) * fy;
}

/** The near land: chunks by their place on the tile grid, asked where a person's feet are. */
export class NearLand {
  readonly #chunks = new Map<string, LandChunk>();
  constructor(chunks: readonly LandChunk[]) {
    for (const chunk of chunks) {
      const key = `${chunk.chunkX},${chunk.chunkY}`;
      require(!this.#chunks.has(key), 'near', `states chunk (${key}) once`);
      this.#chunks.set(key, chunk);
    }
  }
  get chunks(): readonly LandChunk[] { return [...this.#chunks.values()]; }
  /**
   * The land's height under a point, or null where no chunk is held: the caller keeps what it had.
   * A point on a chunk's west or south edge is also on its neighbour's, which holds the same samples.
   */
  groundHeightMm(eastMm: number, northMm: number): number | null {
    const cx = Math.floor(eastMm / LAND_CHUNK_MM), cy = Math.floor(northMm / LAND_CHUNK_MM);
    const xs = eastMm === cx * LAND_CHUNK_MM ? [cx, cx - 1] : [cx];
    const ys = northMm === cy * LAND_CHUNK_MM ? [cy, cy - 1] : [cy];
    for (const y of ys) for (const x of xs) {
      const chunk = this.#chunks.get(`${x},${y}`);
      if (chunk !== undefined) return chunkHeightMm(chunk, eastMm, northMm);
    }
    return null;
  }
}

/** A chunk as exact heightfield geometry in its own frame (the server's `landform_contact.py`). */
export function landChunkGeometry(chunk: LandChunk): HeightfieldGeometryDocument {
  const n = chunk.samplesPerSide, cell = chunk.cellMm;
  const heights: number[] = [];
  for (let j = 0; j < n; j += 1) for (let i = 0; i < n; i += 1) heights.push(chunk.heightMm[(n - 1 - j) * n + i]!);
  return {
    profile: 'exulanica.heightfield-geometry/v1',
    component_id: `landform:chunk:${chunk.chunkX}:${chunk.chunkY}`,
    frame: 'region-local-east-up-south-mm',
    east_mm: Array.from({ length: n }, (_, k) => k * cell),
    south_mm: Array.from({ length: n }, (_, k) => -LAND_CHUNK_MM + k * cell),
    height_mm: heights,
    diagonal: 'a-c-b,b-c-d',
    provenance: { kind: 'generated', source_sha256: chunk.sha256, generator_id: 'exulanica.landform', generator_version: 1, input_sha256: chunk.sha256 },
  };
}

/** A world point in a chunk's own sheet frame: east from its west edge, south from its north edge. */
export function landChunkLocal(chunk: LandChunk, eastMm: number, northMm: number): readonly [number, number] {
  return [eastMm - chunk.chunkX * LAND_CHUNK_MM, chunk.chunkY * LAND_CHUNK_MM - northMm];
}

export type LandWater =
  | { readonly id: string; readonly kind: 'sea'; readonly levelMm: number; readonly side: string }
  | { readonly id: string; readonly kind: 'lake'; readonly levelMm: number; readonly centreMm: readonly [number, number]; readonly radiusMm: number }
  | { readonly id: string; readonly kind: 'pond'; readonly levelMm: number; readonly rectMm: readonly [number, number, number, number] };

function readWater(raw: unknown, where: string): LandWater {
  require(raw !== null && typeof raw === 'object' && !Array.isArray(raw), where, 'is an object');
  const kind = (raw as Record<string, unknown>)['kind'];
  const bound = 10_000_000;
  if (kind === 'sea') {
    const row = fields(raw, 'id kind level_mm side', where);
    require(typeof row['side'] === 'string', `${where}.side`, 'is a side');
    return Object.freeze({ id: String(row['id']), kind, levelMm: integer(row['level_mm'], -bound, bound, `${where}.level_mm`), side: row['side'] as string });
  }
  if (kind === 'lake') {
    const row = fields(raw, 'id kind level_mm centre_mm radius_mm', where);
    const [x, y] = integers(row['centre_mm'], 2, -bound, bound, `${where}.centre_mm`);
    return Object.freeze({ id: String(row['id']), kind, levelMm: integer(row['level_mm'], -bound, bound, `${where}.level_mm`), centreMm: [x!, y!] as const, radiusMm: integer(row['radius_mm'], 1, bound, `${where}.radius_mm`) });
  }
  require(kind === 'pond', `${where}.kind`, 'is sea, lake or pond');
  const row = fields(raw, 'id kind level_mm rect_mm', where);
  const [x0, y0, x1, y1] = integers(row['rect_mm'], 4, -bound, bound, `${where}.rect_mm`);
  return Object.freeze({ id: String(row['id']), kind: 'pond' as const, levelMm: integer(row['level_mm'], -bound, bound, `${where}.level_mm`), rectMm: [x0!, y0!, x1!, y1!] as const });
}

export interface LandBackdrop {
  readonly nearMm: readonly [number, number, number, number];
  readonly xMm: readonly number[];
  readonly yMm: readonly number[];
  readonly heightMm: Int32Array;
  readonly water: readonly LandWater[];
  readonly sha256: string;
}

export function readLandBackdrop(raw: unknown, digest: HeightfieldDigest, expectedSha256?: string): LandBackdrop {
  const row = fields(raw, 'profile near_mm x_mm y_mm height_mm water', 'backdrop');
  require(row['profile'] === LAND_BACKDROP_PROFILE, 'backdrop.profile', `is ${LAND_BACKDROP_PROFILE}`);
  const far = 100_000_000;
  const [x0, y0, x1, y1] = integers(row['near_mm'], 4, -far, far, 'backdrop.near_mm');
  const xMm = integers(row['x_mm'], null, -far, far, 'backdrop.x_mm');
  const yMm = integers(row['y_mm'], null, -far, far, 'backdrop.y_mm');
  for (const [name, axis] of [['x_mm', xMm], ['y_mm', yMm]] as const) {
    require(axis.length >= 2 && axis.every((v, i) => i === 0 || v > axis[i - 1]!), `backdrop.${name}`, 'rises strictly');
  }
  require(xMm.length * yMm.length <= BACKDROP_MOST_SAMPLES, 'backdrop', 'holds at most a million samples');
  const heights = integers(row['height_mm'], xMm.length * yMm.length, -far, far, 'backdrop.height_mm');
  require(Array.isArray(row['water']), 'backdrop.water', 'is a list');
  const water = (row['water'] as unknown[]).map((body, i) => readWater(body, `backdrop.water[${i}]`));
  const sha256 = checked(raw, digest, expectedSha256, 'backdrop');
  return Object.freeze({ nearMm: [x0!, y0!, x1!, y1!] as const, xMm, yMm, heightMm: Int32Array.from(heights), water, sha256 });
}

export interface BackdropBlock {
  /** Metres, scene frame: x east, y up, z minus north. */
  readonly positions: Float32Array;
  readonly indices: Uint32Array;
}

/**
 * The backdrop as triangle blocks to draw: at most `blocks` by `blocks` of them, so a renderer can
 * cull the ones behind the camera, each cell split along its south-west to north-east diagonal and
 * wound to face up. Samples strictly inside the near land are sunk by `sinkMm`, under it.
 */
export function backdropMeshData(backdrop: LandBackdrop, options: { readonly sinkMm?: number; readonly blocks?: number } = {}): BackdropBlock[] {
  const sink = options.sinkMm ?? 3000, blocks = Math.max(1, Math.floor(options.blocks ?? 4));
  const { xMm, yMm, heightMm, nearMm } = backdrop, nx = xMm.length, ny = yMm.length;
  const spans = (cells: number) => Array.from({ length: Math.min(blocks, cells) }, (_, b) => [Math.floor(b * cells / Math.min(blocks, cells)), Math.floor((b + 1) * cells / Math.min(blocks, cells))] as const);
  const out: BackdropBlock[] = [];
  for (const [j0, j1] of spans(ny - 1)) for (const [i0, i1] of spans(nx - 1)) {
    const w = i1 - i0 + 1, positions = new Float32Array(w * (j1 - j0 + 1) * 3);
    for (let j = j0; j <= j1; j += 1) for (let i = i0; i <= i1; i += 1) {
      const x = xMm[i]!, y = yMm[j]!, inside = x > nearMm[0] && x < nearMm[2] && y > nearMm[1] && y < nearMm[3];
      const k = ((j - j0) * w + (i - i0)) * 3;
      positions[k] = x / 1000; positions[k + 1] = (heightMm[j * nx + i]! - (inside ? sink : 0)) / 1000; positions[k + 2] = -y / 1000;
    }
    const indices = new Uint32Array((i1 - i0) * (j1 - j0) * 6);
    let q = 0;
    for (let j = 0; j < j1 - j0; j += 1) for (let i = 0; i < i1 - i0; i += 1) {
      const sw = j * w + i, se = sw + 1, nw = sw + w, ne = nw + 1;
      indices[q++] = sw; indices[q++] = se; indices[q++] = ne; indices[q++] = sw; indices[q++] = ne; indices[q++] = nw;
    }
    out.push({ positions, indices });
  }
  return out;
}
