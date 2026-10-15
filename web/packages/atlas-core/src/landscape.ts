/**
 * A world's landscape as the server realizes it (`exulanica.grammar.landscape` and
 * `exulanica.grammar.volumes`): the landscape drawing, which names each volume placed round a site
 * and the digests of its chunks and walkable tops, and a volume chunk, one cube of a volume's
 * surface as triangles. Pure readers; nothing here draws.
 *
 * Frame: a chunk's positions are millimetres in its volume's own frame (east, north, up). A placed
 * volume stands at `atMm` in the world's frame turned by `yawMdeg` counterclockwise seen from
 * above, so a world point is `atMm + R(yaw) p`. A scene draws east as x, up as y and north as minus
 * z. Every bound is the server's; a document that breaks one, or is not the one its digest names,
 * is refused by where it broke it.
 */
import { canonicalJson } from './style-pack.js';
import type { HeightfieldDigest } from './heightfield-geometry.js';

export const LANDSCAPE_DRAWING_PROFILE = 'exulanica.landscape-drawing/v1';
export const VOLUME_CHUNK_PROFILE = 'exulanica.volume-chunk/v1';
/** The volume rules a chunk this page reads was realized by. */
export const VOLUME_RULES_VERSION = 1;
/** A chunk's side. */
export const VOLUME_CHUNK_MM = 32_000;
/** The cells a chunk is realized at, finest first: a level of detail each. */
export const VOLUME_LEVELS_MM: readonly number[] = Object.freeze([500, 1_000, 2_000, 4_000]);
/** A normal's length. */
export const VOLUME_NORMAL_ONE = 32_767;
/** The looks a vertex names, by index. */
export const VOLUME_LOOKS: readonly string[] = Object.freeze(['rock', 'wall']);
/** The finest cell a page draws a volume at unless told otherwise: the landscape's default. */
export const VOLUME_DRAWN_FINEST_MM = 2_000;
/** A placement's origin, each axis: the landscape catalog's bound. */
const PLACED_LOW_MM = -200_000;
const PLACED_HIGH_MM = 1_024_000;
const CHUNK_INDEX_MOST = 1 << 20;
const DIGEST = /^[0-9a-f]{64}$/;
const KEY = /^[a-z][a-z0-9_]*$/;
const TOP = /^top:(0|[1-9][0-9]*)$/;

export class LandscapeError extends Error {
  constructor(readonly where: string, detail: string) { super(`${where}: ${detail}`); }
}
function require(okay: boolean, where: string, detail: string): asserts okay {
  if (!okay) throw new LandscapeError(where, detail);
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
function text(raw: unknown, pattern: RegExp, where: string): string {
  require(typeof raw === 'string' && pattern.test(raw), where, `matches ${pattern.source}`);
  return raw;
}
function checked(raw: unknown, digest: HeightfieldDigest, expected: string | undefined, where: string): string {
  const actual = digest(new TextEncoder().encode(canonicalJson(raw)));
  if (expected !== undefined) require(actual === expected, where, 'is the document its digest names');
  return actual;
}

export interface VolumeChunkRef {
  readonly chunk: readonly [number, number, number];
  readonly cellMm: number;
  readonly sha256: string;
}

export interface VolumeTopRef {
  readonly surface: string;
  readonly sha256: string;
}

export interface PlacedVolume {
  readonly id: string;
  readonly volumeSha256: string;
  readonly inputSha256: string;
  readonly atMm: readonly [number, number, number];
  readonly yawMdeg: number;
  readonly chunks: readonly VolumeChunkRef[];
  readonly tops: readonly VolumeTopRef[];
}

export interface LandscapeDrawing {
  readonly worldId: string;
  readonly receiptSha256: string;
  readonly siteDrawingSha256: string;
  readonly landSha256: string;
  readonly landscapeSha256: string;
  readonly landscapeRulesVersion: number;
  readonly volumes: readonly PlacedVolume[];
  readonly sha256: string;
}

function chunkRef(raw: unknown, where: string): VolumeChunkRef {
  const row = fields(raw, 'chunk cell_mm sha256', where);
  const [i, j, k] = integers(row['chunk'], 3, -CHUNK_INDEX_MOST, CHUNK_INDEX_MOST, `${where}.chunk`);
  const cellMm = integer(row['cell_mm'], 0, VOLUME_CHUNK_MM, `${where}.cell_mm`);
  require(VOLUME_LEVELS_MM.includes(cellMm), `${where}.cell_mm`, `is one of ${VOLUME_LEVELS_MM.join(', ')}`);
  return Object.freeze({ chunk: Object.freeze([i!, j!, k!] as const), cellMm, sha256: text(row['sha256'], DIGEST, `${where}.sha256`) });
}

function placedVolume(raw: unknown, where: string): PlacedVolume {
  const row = fields(raw, 'id volume_sha256 input_sha256 at_mm yaw_mdeg chunks tops', where);
  const [x, y, z] = integers(row['at_mm'], 3, PLACED_LOW_MM, PLACED_HIGH_MM, `${where}.at_mm`);
  require(Array.isArray(row['chunks']), `${where}.chunks`, 'is a list');
  require(Array.isArray(row['tops']), `${where}.tops`, 'is a list');
  const chunks = (row['chunks'] as unknown[]).map((chunk, i) => chunkRef(chunk, `${where}.chunks[${i}]`));
  const tops = (row['tops'] as unknown[]).map((top, i) => {
    const entry = fields(top, 'surface sha256', `${where}.tops[${i}]`);
    return Object.freeze({
      surface: text(entry['surface'], TOP, `${where}.tops[${i}].surface`),
      sha256: text(entry['sha256'], DIGEST, `${where}.tops[${i}].sha256`),
    });
  });
  return Object.freeze({
    id: text(row['id'], KEY, `${where}.id`),
    volumeSha256: text(row['volume_sha256'], DIGEST, `${where}.volume_sha256`),
    inputSha256: text(row['input_sha256'], DIGEST, `${where}.input_sha256`),
    atMm: Object.freeze([x!, y!, z!] as const),
    yawMdeg: integer(row['yaw_mdeg'], 0, 359_999, `${where}.yaw_mdeg`),
    chunks: Object.freeze(chunks),
    tops: Object.freeze(tops),
  });
}

/** Admit a landscape drawing, or refuse it by where it broke; with `expectedSha256`, only the one that digest names. */
export function readLandscapeDrawing(raw: unknown, digest: HeightfieldDigest, expectedSha256?: string): LandscapeDrawing {
  const row = fields(raw, 'profile world_id receipt_sha256 site_drawing_sha256 land_sha256 landscape_sha256 landscape_rules_version volumes', 'landscape');
  require(row['profile'] === LANDSCAPE_DRAWING_PROFILE, 'landscape.profile', `is ${LANDSCAPE_DRAWING_PROFILE}`);
  require(typeof row['world_id'] === 'string' && row['world_id'].length > 0 && row['world_id'].length <= 256, 'landscape.world_id', 'is a world id');
  require(Array.isArray(row['volumes']), 'landscape.volumes', 'is a list');
  const volumes = (row['volumes'] as unknown[]).map((volume, i) => placedVolume(volume, `landscape.volumes[${i}]`));
  const ids = volumes.map((volume) => volume.id);
  require(new Set(ids).size === ids.length, 'landscape.volumes', 'names each placement once');
  const sha256 = checked(raw, digest, expectedSha256, 'landscape');
  return Object.freeze({
    worldId: row['world_id'] as string,
    receiptSha256: text(row['receipt_sha256'], DIGEST, 'landscape.receipt_sha256'),
    siteDrawingSha256: text(row['site_drawing_sha256'], DIGEST, 'landscape.site_drawing_sha256'),
    landSha256: text(row['land_sha256'], DIGEST, 'landscape.land_sha256'),
    landscapeSha256: text(row['landscape_sha256'], DIGEST, 'landscape.landscape_sha256'),
    landscapeRulesVersion: integer(row['landscape_rules_version'], 1, 1_000_000, 'landscape.landscape_rules_version'),
    volumes: Object.freeze(volumes),
    sha256,
  });
}

export interface VolumeChunk {
  readonly inputSha256: string;
  readonly volumeSha256: string;
  readonly chunk: readonly [number, number, number];
  readonly cellMm: number;
  /** Positions in the volume's frame, millimetres, in threes. */
  readonly positionsMm: Int32Array;
  /** Unit normals at {@link VOLUME_NORMAL_ONE}, in threes. */
  readonly normals: Int16Array;
  /** Each vertex's look, an index into {@link VOLUME_LOOKS}. */
  readonly vertexLooks: Uint8Array;
  /** Vertex indices in threes, turned from solid toward air. */
  readonly triangles: Uint32Array;
  readonly sha256: string;
}

/** Admit a volume chunk, or refuse it by where it broke; with `expectedSha256`, only the one that digest names. */
export function readVolumeChunk(raw: unknown, digest: HeightfieldDigest, expectedSha256?: string): VolumeChunk {
  const row = fields(raw, 'profile input_sha256 volume_sha256 rules_version chunk cell_mm positions_mm normals looks vertex_looks triangles', 'volume chunk');
  require(row['profile'] === VOLUME_CHUNK_PROFILE, 'volume chunk.profile', `is ${VOLUME_CHUNK_PROFILE}`);
  require(row['rules_version'] === VOLUME_RULES_VERSION, 'volume chunk.rules_version', `is ${VOLUME_RULES_VERSION}, the volume rules this page reads`);
  const [i, j, k] = integers(row['chunk'], 3, -CHUNK_INDEX_MOST, CHUNK_INDEX_MOST, 'volume chunk.chunk');
  const cellMm = integer(row['cell_mm'], 0, VOLUME_CHUNK_MM, 'volume chunk.cell_mm');
  require(VOLUME_LEVELS_MM.includes(cellMm), 'volume chunk.cell_mm', `is one of ${VOLUME_LEVELS_MM.join(', ')}`);
  require(JSON.stringify(row['looks']) === JSON.stringify(VOLUME_LOOKS), 'volume chunk.looks', `are ${VOLUME_LOOKS.join(', ')}`);
  const low = [i!, j!, k!].map((index) => index * VOLUME_CHUNK_MM - cellMm);
  const reach = VOLUME_CHUNK_MM + 2 * cellMm;
  const rawPositions = row['positions_mm'];
  require(Array.isArray(rawPositions) && rawPositions.length % 3 === 0, 'volume chunk.positions_mm', 'is whole numbers in threes');
  const count = rawPositions.length / 3;
  const positionsMm = new Int32Array(rawPositions.length);
  for (let n = 0; n < rawPositions.length; n += 1) {
    const value = rawPositions[n];
    const axisLow = low[n % 3]!;
    require(typeof value === 'number' && Number.isSafeInteger(value) && value >= axisLow && value <= axisLow + reach, 'volume chunk.positions_mm', `vertex ${Math.floor(n / 3)} lies within its chunk and one cell round it`);
    positionsMm[n] = value;
  }
  const normals = Int16Array.from(integers(row['normals'], count * 3, -VOLUME_NORMAL_ONE, VOLUME_NORMAL_ONE, 'volume chunk.normals'));
  const vertexLooks = Uint8Array.from(integers(row['vertex_looks'], count, 0, VOLUME_LOOKS.length - 1, 'volume chunk.vertex_looks'));
  const rawTriangles = row['triangles'];
  require(Array.isArray(rawTriangles) && rawTriangles.length % 3 === 0, 'volume chunk.triangles', 'is vertex indices in threes');
  const triangles = Uint32Array.from(integers(rawTriangles, null, 0, Math.max(count - 1, 0), 'volume chunk.triangles'));
  require(triangles.length === 0 || count > 0, 'volume chunk.triangles', 'names vertices the chunk has');
  const sha256 = checked(raw, digest, expectedSha256, 'volume chunk');
  return Object.freeze({
    inputSha256: text(row['input_sha256'], DIGEST, 'volume chunk.input_sha256'),
    volumeSha256: text(row['volume_sha256'], DIGEST, 'volume chunk.volume_sha256'),
    chunk: Object.freeze([i!, j!, k!] as const),
    cellMm,
    positionsMm,
    normals,
    vertexLooks,
    triangles,
    sha256,
  });
}

/** The cell a page draws a placed volume at: the finest it names that is not finer than
 * `finestMm`, else the coarsest it names; null for a volume with no chunks. */
export function volumeDrawnCellMm(volume: PlacedVolume, finestMm: number = VOLUME_DRAWN_FINEST_MM): number | null {
  const named = [...new Set(volume.chunks.map((chunk) => chunk.cellMm))].sort((a, b) => a - b);
  if (named.length === 0) return null;
  return named.find((cell) => cell >= finestMm) ?? named[named.length - 1]!;
}

/** A volume-frame point (millimetres) placed in the world's frame (millimetres east, north, up). */
export function placedPointMm(volume: PlacedVolume, x: number, y: number, z: number): [number, number, number] {
  const turn = (volume.yawMdeg / 1000) * (Math.PI / 180);
  const cos = Math.cos(turn), sin = Math.sin(turn);
  return [volume.atMm[0] + cos * x - sin * y, volume.atMm[1] + sin * x + cos * y, volume.atMm[2] + z];
}
