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
 *
 * A world on a placed volume's top is drawn as `exulanica.landscape-drawing/v2`: version 1's fields
 * and the graded top's digest (`topSha256`, the site drawing's), where the site stands in the
 * landscape (`siteFrame`: the placement, the site's south-west corner in the landscape's frame and
 * its turn), and the land below (`ground`: the landscape's own land as 128 m chunks and a backdrop by
 * digest, and its water). A page whose frame is the site's places the landscape at the inverse of
 * the site frame ({@link landscapeToSiteMm}).
 */
import { canonicalJson } from './style-pack.js';
import type { HeightfieldDigest } from './heightfield-geometry.js';
import { LAND_CHUNK_MM, readLandWater, type LandWater } from './landform.js';

export const LANDSCAPE_DRAWING_PROFILE = 'exulanica.landscape-drawing/v1';
export const TOP_LANDSCAPE_DRAWING_PROFILE = 'exulanica.landscape-drawing/v2';
export const VOLUME_CHUNK_PROFILE = 'exulanica.volume-chunk/v1';
/** The newest volume rules the server realizes chunks by. */
export const VOLUME_RULES_VERSION = 4;
/** Every volume rules version a chunk this page reads may name: they share one chunk format. */
const VOLUME_RULES_READ: readonly number[] = Object.freeze([1, 2, 3, VOLUME_RULES_VERSION]);
/** A chunk's side. */
export const VOLUME_CHUNK_MM = 32_000;
/** The cells a chunk is realized at, finest first: a level of detail each. */
export const VOLUME_LEVELS_MM: readonly number[] = Object.freeze([500, 1_000, 2_000, 4_000]);
/** A normal's length. */
export const VOLUME_NORMAL_ONE = 32_767;
/** The looks a vertex names, by index, and the looks a volume's faces may be dressed in. */
export const VOLUME_LOOKS: readonly string[] = Object.freeze(['rock', 'wall']);
/** The looks a volume's upward faces may be dressed in: the volume catalog's words. */
const VOLUME_TOP_LOOKS: readonly string[] = Object.freeze(['moss', 'grass', 'rock', 'sand']);
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
function word(raw: unknown, words: readonly string[], where: string): string {
  require(typeof raw === 'string' && words.includes(raw), where, `is one of ${words.join(', ')}`);
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
  /** The look its faces are dressed in; rock where the drawing names none. */
  readonly look: string;
  /** The look its upward faces are dressed in; none where the drawing names none, so they are its rock. */
  readonly topLook: string | null;
  readonly chunks: readonly VolumeChunkRef[];
  readonly tops: readonly VolumeTopRef[];
}

/** Where a site on a placed volume's top stands in its landscape's frame. */
export interface LandscapeSiteFrame {
  /** The placement the site stands on. */
  readonly placement: string;
  /** The site's south-west corner in the landscape's frame, millimetres east, north and up. */
  readonly atMm: readonly [number, number, number];
  /** The site's turn in the landscape, the placement's: counterclockwise seen from above. */
  readonly yawMdeg: number;
}

/** The land below a site on a volume's top, by digest, in the landscape's frame. */
export interface LandscapeGround {
  readonly landSha256: string;
  readonly chunkMm: number;
  readonly chunks: readonly { readonly chunk: readonly [number, number]; readonly sha256: string }[];
  readonly backdropSha256: string;
  readonly water: readonly LandWater[];
}

export interface LandscapeDrawing {
  readonly profile: string;
  readonly worldId: string;
  readonly receiptSha256: string;
  readonly siteDrawingSha256: string;
  readonly landSha256: string;
  readonly landscapeSha256: string;
  readonly landscapeRulesVersion: number;
  readonly volumes: readonly PlacedVolume[];
  /** For a site on a volume's top (version 2): the graded top's digest, else null. */
  readonly topSha256: string | null;
  /** For a site on a volume's top (version 2): where it stands, else null. */
  readonly siteFrame: LandscapeSiteFrame | null;
  /** For a site on a volume's top (version 2): the land below, else null. */
  readonly ground: LandscapeGround | null;
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
  // A drawing names a volume's looks together, or (made before it named them) neither.
  const named = 'id volume_sha256 input_sha256 at_mm yaw_mdeg chunks tops';
  const looked = raw !== null && typeof raw === 'object' && ('look' in raw || 'top_look' in raw);
  const row = fields(raw, looked ? `${named} look top_look` : named, where);
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
    look: looked ? word(row['look'], VOLUME_LOOKS, `${where}.look`) : 'rock',
    topLook: looked ? word(row['top_look'], VOLUME_TOP_LOOKS, `${where}.top_look`) : null,
    chunks: Object.freeze(chunks),
    tops: Object.freeze(tops),
  });
}

/** How far a site frame's corner may lie from the landscape's origin, each axis. */
const SITE_FRAME_MOST_MM = 2_000_000;
const GROUND_CHUNK_MOST = 4_096;

function siteFrame(raw: unknown, where: string): LandscapeSiteFrame {
  const row = fields(raw, 'placement at_mm yaw_mdeg', where);
  const [x, y, z] = integers(row['at_mm'], 3, -SITE_FRAME_MOST_MM, SITE_FRAME_MOST_MM, `${where}.at_mm`);
  return Object.freeze({
    placement: text(row['placement'], KEY, `${where}.placement`),
    atMm: Object.freeze([x!, y!, z!] as const),
    yawMdeg: integer(row['yaw_mdeg'], 0, 359_999, `${where}.yaw_mdeg`),
  });
}

function ground(raw: unknown, where: string): LandscapeGround {
  const row = fields(raw, 'land_sha256 chunk_mm chunks backdrop_sha256 water', where);
  require(row['chunk_mm'] === LAND_CHUNK_MM, `${where}.chunk_mm`, `is ${LAND_CHUNK_MM}`);
  require(Array.isArray(row['chunks']) && row['chunks'].length > 0, `${where}.chunks`, 'is a list of at least one chunk');
  const chunks = (row['chunks'] as unknown[]).map((one, i) => {
    const chunk = fields(one, 'chunk sha256', `${where}.chunks[${i}]`);
    const [cx, cy] = integers(chunk['chunk'], 2, -GROUND_CHUNK_MOST, GROUND_CHUNK_MOST, `${where}.chunks[${i}].chunk`);
    return Object.freeze({ chunk: Object.freeze([cx!, cy!] as const), sha256: text(chunk['sha256'], DIGEST, `${where}.chunks[${i}].sha256`) });
  });
  require(new Set(chunks.map((one) => one.chunk.join(','))).size === chunks.length, `${where}.chunks`, 'names each chunk once');
  require(Array.isArray(row['water']), `${where}.water`, 'is a list');
  return Object.freeze({
    landSha256: text(row['land_sha256'], DIGEST, `${where}.land_sha256`),
    chunkMm: LAND_CHUNK_MM,
    chunks: Object.freeze(chunks),
    backdropSha256: text(row['backdrop_sha256'], DIGEST, `${where}.backdrop_sha256`),
    water: Object.freeze((row['water'] as unknown[]).map((body, i) => readLandWater(body, `${where}.water[${i}]`))),
  });
}

/** Admit a landscape drawing (version 1, or version 2 for a site on a volume's top), or refuse it
 * by where it broke; with `expectedSha256`, only the one that digest names. */
export function readLandscapeDrawing(raw: unknown, digest: HeightfieldDigest, expectedSha256?: string): LandscapeDrawing {
  const profile = raw !== null && typeof raw === 'object' ? (raw as Record<string, unknown>)['profile'] : undefined;
  const onTop = profile === TOP_LANDSCAPE_DRAWING_PROFILE;
  const named = 'profile world_id receipt_sha256 site_drawing_sha256 land_sha256 landscape_sha256 landscape_rules_version volumes';
  const row = fields(raw, onTop ? `${named} top_sha256 site_frame ground` : named, 'landscape');
  require(row['profile'] === LANDSCAPE_DRAWING_PROFILE || onTop, 'landscape.profile', `is ${LANDSCAPE_DRAWING_PROFILE} or ${TOP_LANDSCAPE_DRAWING_PROFILE}`);
  require(typeof row['world_id'] === 'string' && row['world_id'].length > 0 && row['world_id'].length <= 256, 'landscape.world_id', 'is a world id');
  require(Array.isArray(row['volumes']), 'landscape.volumes', 'is a list');
  const volumes = (row['volumes'] as unknown[]).map((volume, i) => placedVolume(volume, `landscape.volumes[${i}]`));
  const ids = volumes.map((volume) => volume.id);
  require(new Set(ids).size === ids.length, 'landscape.volumes', 'names each placement once');
  const frame = onTop ? siteFrame(row['site_frame'], 'landscape.site_frame') : null;
  if (frame !== null) require(ids.includes(frame.placement), 'landscape.site_frame.placement', 'names a placement the drawing places');
  const sha256 = checked(raw, digest, expectedSha256, 'landscape');
  return Object.freeze({
    profile: row['profile'] as string,
    worldId: row['world_id'] as string,
    receiptSha256: text(row['receipt_sha256'], DIGEST, 'landscape.receipt_sha256'),
    siteDrawingSha256: text(row['site_drawing_sha256'], DIGEST, 'landscape.site_drawing_sha256'),
    landSha256: text(row['land_sha256'], DIGEST, 'landscape.land_sha256'),
    landscapeSha256: text(row['landscape_sha256'], DIGEST, 'landscape.landscape_sha256'),
    landscapeRulesVersion: integer(row['landscape_rules_version'], 1, 1_000_000, 'landscape.landscape_rules_version'),
    volumes: Object.freeze(volumes),
    topSha256: onTop ? text(row['top_sha256'], DIGEST, 'landscape.top_sha256') : null,
    siteFrame: frame,
    ground: onTop ? ground(row['ground'], 'landscape.ground') : null,
    sha256,
  });
}

/** A landscape-frame point (millimetres east, north, up) in the frame of the site standing at
 * `frame`: the site frame's inverse, `R(-yaw) (p - atMm)`. */
export function landscapeToSiteMm(frame: LandscapeSiteFrame, x: number, y: number, z: number): [number, number, number] {
  const turn = (frame.yawMdeg / 1000) * (Math.PI / 180);
  const cos = Math.cos(turn), sin = Math.sin(turn);
  const dx = x - frame.atMm[0], dy = y - frame.atMm[1];
  return [cos * dx + sin * dy, -sin * dx + cos * dy, z - frame.atMm[2]];
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
  require(VOLUME_RULES_READ.includes(row['rules_version'] as number), 'volume chunk.rules_version', `is one of ${VOLUME_RULES_READ.join(', ')}, the volume rules this page reads`);
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
