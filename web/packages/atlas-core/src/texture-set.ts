/**
 * The browser's reader for baked texture sets: `assets/textures/manifest.json` and the `.ltex`
 * containers it pins.
 *
 * ONE READER PER RUNTIME. The baker (`loom-texture`) has its own reference reader and the backend
 * has `exulanica/world/texture_assets.py`; neither can ship here, the first because it is fenced as
 * offline-only and the second because it is Python. This file is the third runtime's reader, not a
 * copy of either: it is written from the container's own stated layout, and
 * `test/texture-set.test.ts` holds its decoded maps to the Python reader's output, digest for digest.
 *
 * WHAT IT REFUSES, AND WHY IT REFUSES RATHER THAN DEGRADES. A set is bytes a renderer uploads as
 * surfaces a person reads as brick or stone. Bytes that do not hash to the manifest's pin, a
 * container whose header says something the manifest does not, or a layout this reader was not
 * written for are not a lower-quality texture, they are a different claim, so each one is a
 * {@link TextureSetRefusal} and the caller draws its stated unavailable surface. There is no
 * default set and no fallback colour anywhere in this module.
 *
 * **Without `crypto.subtle` there is no texture at all.** The same posture as the app's geometry
 * reader: a page with no `SubtleCrypto` cannot check a pin, so every set is refused, before a single
 * byte is parsed. The digest is passed in only so a test can take it away.
 *
 * Pure: no DOM, no Node, no renderer. The maps it returns are views over the caller's bytes.
 */

export const TEXTURE_MANIFEST_PROFILE = 'exulanica.texture-manifest/v1';
export const TEXTURE_SET_PROFILE = 'exulanica.texture-set/v1';
export const TEXTURE_SET_MEDIA_TYPE = 'application/vnd.exulanica.texture-set';
export const TEXTURE_SET_MAGIC = 'LTX1';
/** The plane every set declares. Generated, never observed. */
export const TEXTURE_SET_TRUTH = 'invented';
/** The one licence the published sets carry; the backend refuses any other in the manifest. */
export const TEXTURE_SET_LICENCE_ID = 'CC0-1.0';
/**
 * The normal map convention the material binding is written for. A set declaring another one is
 * refused rather than drawn with its relief inverted.
 */
export const TEXTURE_SET_NORMAL_CONVENTION =
  'glTF: +X toward increasing u, +Y toward row 0, +Z out of the surface';

const ALIGNMENT = 16;
const PREAMBLE = 8;
const MAXIMUM_DEPTH = 64;
const SET_ID = /^[a-z][a-z0-9.-]*$/;
const HEX64 = /^[0-9a-f]{64}$/;
const PRINTABLE = /^[\x20-\x7e]*$/;

export type TextureMapName = 'base_color' | 'normal' | 'orm' | 'height';

/** The stated packing of every map, in stored order. Structure only; the prose is the baker's. */
const LAYOUT: readonly {
  readonly name: TextureMapName;
  readonly components: number;
  readonly holds: readonly string[];
  readonly srgb: boolean;
  readonly keys: string;
}[] = [
  { name: 'base_color', components: 3, holds: ['red', 'green', 'blue'], srgb: true,
    keys: 'byte_length byte_offset components decode holds name srgb' },
  { name: 'normal', components: 3, holds: ['normal_x', 'normal_y', 'normal_z'], srgb: false,
    keys: 'byte_length byte_offset components convention decode holds name space srgb' },
  { name: 'orm', components: 3, holds: ['occlusion', 'roughness', 'metalness'], srgb: false,
    keys: 'byte_length byte_offset components decode holds name srgb' },
  { name: 'height', components: 1, holds: ['height'], srgb: false,
    keys: 'byte_length byte_offset components decode holds name srgb' },
];

export type TextureSetRefusalReason =
  | 'manifest'
  | 'digest-unavailable'
  | 'byte-size'
  | 'digest'
  | 'container'
  | 'header';

/** A set that is not drawn, and the one reason why. */
export class TextureSetRefusal extends Error {
  constructor(readonly reason: TextureSetRefusalReason, message: string) {
    super(message);
    this.name = 'TextureSetRefusal';
  }
}

export interface TextureSetChannel {
  readonly map: TextureMapName;
  readonly components: number;
  readonly holds: readonly string[];
  readonly srgb: boolean;
}

/** One manifest entry, validated field for field. */
export interface TextureSetManifestEntry {
  readonly setId: string;
  readonly version: number;
  readonly contentSha256: string;
  readonly byteSize: number;
  readonly width: number;
  readonly height: number;
  readonly channels: readonly TextureSetChannel[];
  readonly extentUMm: number;
  readonly extentVMm: number;
  readonly licenceId: string;
  readonly licenceSha256: string;
}

export interface TextureSetManifest {
  readonly profile: typeof TEXTURE_MANIFEST_PROFILE;
  /** In manifest order. */
  readonly sets: readonly TextureSetManifestEntry[];
  /** A material record's set id resolves here or it does not resolve. */
  readonly byId: ReadonlyMap<string, TextureSetManifestEntry>;
}

/** How the set is laid on a surface, as its header states it. */
export type TextureSetSurface = 'vertical' | 'horizontal';

export interface DecodedTextureSet {
  readonly entry: TextureSetManifestEntry;
  readonly surface: TextureSetSurface;
  readonly title: string;
  /** Millimetres of relief the height map's 0 to 255 spans. */
  readonly heightRangeMm: number;
  /** Row 0 first, interleaved within each map, one byte per component. Views, not copies. */
  readonly maps: Readonly<Record<TextureMapName, Uint8Array>>;
}

/** The one digest this reader needs. Structurally `SubtleCrypto`, so the browser's is accepted. */
export interface TextureSetDigest {
  digest(algorithm: 'SHA-256', data: Uint8Array): Promise<ArrayBuffer>;
}

type Json = null | boolean | number | string | readonly Json[] | { readonly [key: string]: Json };

function refuse(reason: TextureSetRefusalReason, message: string): never {
  throw new TextureSetRefusal(reason, message);
}

function canonical(value: Json): string {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number') return String(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  const object = value as { readonly [key: string]: Json };
  return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${canonical(object[key]!)}`).join(',')}}`;
}

/** Only what both languages serialise identically: safe integers, printable ASCII, bounded depth. */
function portable(value: unknown, depth: number): value is Json {
  if (depth > MAXIMUM_DEPTH) return false;
  if (value === null || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isSafeInteger(value);
  if (typeof value === 'string') return PRINTABLE.test(value);
  if (Array.isArray(value)) return value.every((item) => portable(item, depth + 1));
  if (typeof value !== 'object') return false;
  return Object.entries(value).every(([key, item]) => PRINTABLE.test(key) && portable(item, depth + 1));
}

/**
 * Parse bytes that must already be canonical JSON. A fraction, a repeated key, an escape the
 * canonical form would not write or any whitespace changes the re-serialised text, so every one of
 * them is refused by the one comparison at the end.
 */
function canonicalDocument(bytes: Uint8Array, reason: TextureSetRefusalReason, where: string): Json {
  let text: string;
  let parsed: unknown;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    parsed = JSON.parse(text);
  } catch {
    return refuse(reason, `${where} is not JSON`);
  }
  if (!portable(parsed, 0)) refuse(reason, `${where} holds a value outside safe integers and printable ASCII`);
  if (canonical(parsed) !== text) refuse(reason, `${where} is not canonical JSON, so its bytes are not its content`);
  return parsed;
}

function record(value: Json | undefined, keys: string, where: string, reason: TextureSetRefusalReason): { readonly [key: string]: Json } {
  if (value === null || value === undefined || typeof value !== 'object' || Array.isArray(value)) {
    return refuse(reason, `${where} is not an object`);
  }
  const actual = Object.keys(value).sort().join(' ');
  const expected = keys.split(' ').sort().join(' ');
  if (actual !== expected) refuse(reason, `${where} has keys ${actual}, not exactly ${expected}`);
  return value as { readonly [key: string]: Json };
}

function positive(value: Json | undefined, where: string, reason: TextureSetRefusalReason): number {
  if (typeof value !== 'number' || value <= 0) refuse(reason, `${where} is not a positive integer`);
  return value;
}

function nonNegative(value: Json | undefined, where: string, reason: TextureSetRefusalReason): number {
  if (typeof value !== 'number' || value < 0) refuse(reason, `${where} is not a non-negative integer`);
  return value;
}

function text(value: Json | undefined, where: string, reason: TextureSetRefusalReason): string {
  if (typeof value !== 'string' || value.trim().length === 0) refuse(reason, `${where} is not non-empty text`);
  return value;
}

function sameJson(a: Json | undefined, b: Json): boolean {
  return a !== undefined && canonical(a) === canonical(b);
}

function manifestEntry(value: Json, index: number): TextureSetManifestEntry {
  const where = `manifest sets[${index}]`;
  const entry = record(value, 'byte_size channels content_sha256 extent_mm licence_id licence_sha256 resolution set_id version', where, 'manifest');
  const setId = entry['set_id'];
  if (typeof setId !== 'string' || !SET_ID.test(setId)) refuse('manifest', `${where} set_id is not a texture set id`);
  for (const field of ['content_sha256', 'licence_sha256']) {
    const digest = entry[field];
    if (typeof digest !== 'string' || !HEX64.test(digest)) refuse('manifest', `${where} ${field} is not 64 lowercase hex`);
  }
  if (entry['licence_id'] !== TEXTURE_SET_LICENCE_ID) refuse('manifest', `${where} licence_id is not ${TEXTURE_SET_LICENCE_ID}`);
  const resolution = record(entry['resolution'], 'height width', `${where} resolution`, 'manifest');
  const extent = record(entry['extent_mm'], 'u v', `${where} extent_mm`, 'manifest');
  const channels = entry['channels'];
  if (!Array.isArray(channels) || channels.length !== LAYOUT.length) refuse('manifest', `${where} channels are not the four stated maps`);
  const parsedChannels = LAYOUT.map((layout, at): TextureSetChannel => {
    const channel = record(channels[at], 'components holds map srgb', `${where} channels[${at}]`, 'manifest');
    if (channel['map'] !== layout.name || channel['components'] !== layout.components ||
        channel['srgb'] !== layout.srgb || !sameJson(channel['holds'], layout.holds)) {
      refuse('manifest', `${where} channels[${at}] is not ${layout.name} as packed`);
    }
    return Object.freeze({ map: layout.name, components: layout.components, holds: layout.holds, srgb: layout.srgb });
  });
  return Object.freeze({
    setId,
    version: positive(entry['version'], `${where} version`, 'manifest'),
    contentSha256: entry['content_sha256'] as string,
    byteSize: positive(entry['byte_size'], `${where} byte_size`, 'manifest'),
    width: positive(resolution['width'], `${where} resolution width`, 'manifest'),
    height: positive(resolution['height'], `${where} resolution height`, 'manifest'),
    channels: Object.freeze(parsedChannels),
    extentUMm: positive(extent['u'], `${where} extent_mm u`, 'manifest'),
    extentVMm: positive(extent['v'], `${where} extent_mm v`, 'manifest'),
    licenceId: TEXTURE_SET_LICENCE_ID,
    licenceSha256: entry['licence_sha256'] as string,
  });
}

/** Read `manifest.json` from its bytes, strictly. Every refusal is reason `manifest`. */
export function parseTextureSetManifest(bytes: Uint8Array): TextureSetManifest {
  const document = record(canonicalDocument(bytes, 'manifest', 'the texture manifest'), 'profile sets', 'the texture manifest', 'manifest');
  if (document['profile'] !== TEXTURE_MANIFEST_PROFILE) refuse('manifest', `the texture manifest does not declare ${TEXTURE_MANIFEST_PROFILE}`);
  const sets = document['sets'];
  if (!Array.isArray(sets) || sets.length === 0) refuse('manifest', 'the texture manifest lists no sets');
  const entries = sets.map(manifestEntry);
  const byId = new Map<string, TextureSetManifestEntry>();
  for (const entry of entries) {
    if (byId.has(entry.setId)) refuse('manifest', `the texture manifest lists ${entry.setId} twice`);
    byId.set(entry.setId, entry);
  }
  return Object.freeze({ profile: TEXTURE_MANIFEST_PROFILE, sets: Object.freeze(entries), byId });
}

/** Where a pinned set's bytes live, relative to the published texture directory. */
export function textureSetBlobPath(entry: TextureSetManifestEntry): string {
  return `blobs/${entry.contentSha256}.ltex`;
}

function ambientDigest(): TextureSetDigest | null {
  const scope = globalThis as unknown as { readonly crypto?: { readonly subtle?: TextureSetDigest } };
  return scope.crypto?.subtle ?? null;
}

function hex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/**
 * Hold a container to its manifest entry and decode it.
 *
 * In this order, each step refusing on its own: a digest must exist; the byte count must be the
 * pinned one; the SHA-256 must be the pinned one; then the container must be exactly what the
 * baker writes, and its header must say what the manifest says.
 */
export async function decodeTextureSet(
  bytes: Uint8Array,
  entry: TextureSetManifestEntry,
  digest: TextureSetDigest | null = ambientDigest(),
): Promise<DecodedTextureSet> {
  if (digest === null) {
    refuse('digest-unavailable', 'this page has no crypto.subtle, so no texture set can be checked against its pin');
  }
  if (bytes.byteLength !== entry.byteSize) {
    refuse('byte-size', `${entry.setId} is ${bytes.byteLength} bytes; its pin is ${entry.byteSize}`);
  }
  const actual = hex(await digest.digest('SHA-256', bytes));
  if (actual !== entry.contentSha256) {
    refuse('digest', `${entry.setId} hashes to ${actual}; its pin is ${entry.contentSha256}`);
  }
  return decodeContainer(bytes, entry);
}

function decodeContainer(bytes: Uint8Array, entry: TextureSetManifestEntry): DecodedTextureSet {
  const where = entry.setId;
  if (bytes.byteLength < PREAMBLE) refuse('container', `${where} is shorter than its preamble`);
  const magic = String.fromCharCode(bytes[0]!, bytes[1]!, bytes[2]!, bytes[3]!);
  if (magic !== TEXTURE_SET_MAGIC) refuse('container', `${where} is not a texture set container`);
  const headerLength = new DataView(bytes.buffer, bytes.byteOffset, PREAMBLE).getUint32(4, true);
  if (PREAMBLE + headerLength > bytes.byteLength) refuse('container', `${where}: the header runs past the end of the file`);
  const header = canonicalDocument(bytes.subarray(PREAMBLE, PREAMBLE + headerLength), 'header', `${where} header`);
  if (header === null || typeof header !== 'object' || Array.isArray(header)) refuse('header', `${where} header is not an object`);
  const h = header as { readonly [key: string]: Json };
  if (h['profile'] !== TEXTURE_SET_PROFILE) refuse('header', `${where} does not declare ${TEXTURE_SET_PROFILE}`);
  const expected: Readonly<Record<string, Json>> = {
    media_type: TEXTURE_SET_MEDIA_TYPE,
    truth: TEXTURE_SET_TRUTH,
    set_id: entry.setId,
    version: entry.version,
    resolution: { width: entry.width, height: entry.height },
    extent_mm: { u: entry.extentUMm, v: entry.extentVMm },
    licence: { id: entry.licenceId, sha256: entry.licenceSha256 },
  };
  for (const [key, value] of Object.entries(expected)) {
    if (!sameJson(h[key], value)) refuse('header', `${where} header ${key} is not what the manifest pins`);
  }
  const placement = h['placement'];
  const surface = placement !== null && typeof placement === 'object' && !Array.isArray(placement)
    ? (placement as { readonly [key: string]: Json })['surface'] : undefined;
  if (surface !== 'vertical' && surface !== 'horizontal') refuse('header', `${where} header states no vertical or horizontal placement`);
  const heightRangeMm = nonNegative(h['height_range_mm'], `${where} header height_range_mm`, 'header');
  nonNegative(h['seed'], `${where} header seed`, 'header');
  const title = text(h['title'], `${where} header title`, 'header');
  text(h['summary'], `${where} header summary`, 'header');

  const start = Math.ceil((PREAMBLE + headerLength) / ALIGNMENT) * ALIGNMENT;
  if (start > bytes.byteLength) refuse('container', `${where}: the padding runs past the end of the file`);
  for (let at = PREAMBLE + headerLength; at < start; at += 1) {
    if (bytes[at] !== 0x20) refuse('container', `${where}: padding byte ${at} is not a space`);
  }
  const declared = h['maps'];
  if (!Array.isArray(declared) || declared.length !== LAYOUT.length) refuse('header', `${where}: the map list is not the stated layout`);
  const texels = entry.width * entry.height;
  const maps: Partial<Record<TextureMapName, Uint8Array>> = {};
  let cursor = start;
  LAYOUT.forEach((layout, index) => {
    const map = record(declared[index], layout.keys, `${where} maps[${index}]`, 'header');
    const length = texels * layout.components;
    if (map['name'] !== layout.name || map['components'] !== layout.components || map['srgb'] !== layout.srgb ||
        !sameJson(map['holds'], layout.holds) || map['byte_offset'] !== cursor || map['byte_length'] !== length) {
      refuse('header', `${where}: map ${layout.name} is not packed as stated`);
    }
    text(map['decode'], `${where} maps[${index}] decode`, 'header');
    if (layout.name === 'normal' &&
        (map['space'] !== 'tangent' || map['convention'] !== TEXTURE_SET_NORMAL_CONVENTION)) {
      refuse('header', `${where}: the normal map is not in the tangent-space convention this reader is written for`);
    }
    if (cursor + length > bytes.byteLength) refuse('container', `${where}: map ${layout.name} runs past the end of the file`);
    maps[layout.name] = bytes.subarray(cursor, cursor + length);
    cursor += length;
  });
  if (cursor !== bytes.byteLength) refuse('container', `${where}: the maps end at byte ${cursor}, the file at ${bytes.byteLength}`);
  const channels = LAYOUT.map((layout) => ({ map: layout.name, components: layout.components, holds: layout.holds, srgb: layout.srgb }));
  if (!sameJson(channels as unknown as Json, entry.channels as unknown as Json)) {
    refuse('header', `${where}: the manifest's channels are not the header's maps`);
  }
  return Object.freeze({
    entry,
    surface,
    title,
    heightRangeMm,
    maps: Object.freeze(maps as Record<TextureMapName, Uint8Array>),
  });
}
