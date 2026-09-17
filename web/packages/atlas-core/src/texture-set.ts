/**
 * The browser's reader for baked texture sets: `assets/textures/manifest.json` and the `.ltex`
 * containers it pins.
 *
 * ONE READER PER RUNTIME. The baker (`loom-texture`) has its own reference reader and the backend
 * has `exulanica/world/texture_assets.py`; neither can ship here, the first because it is fenced as
 * offline-only and the second because it is Python. This file is the third runtime's reader, not a
 * copy of either: it is written from the container's own stated layout. `test/texture-set.test.ts`
 * holds its decoded maps to the Python reader's output, digest for digest, and
 * `test/texture-set-cases.test.ts` runs the shared case file every reader runs
 * (`web/packages/loom-texture/test/texture-set-cases.json`), requiring the same outcome for each.
 *
 * TWO PROFILES OF EACH. `exulanica.texture-manifest/v1` lists `exulanica.texture-set/v1` containers
 * only, and every one is the four-map `opaque` layout. `exulanica.texture-manifest/v2` adds each
 * entry's `container_profile` and `material_class`, and a v2 container states its class, its
 * maker's kind and exactly that pair's layout (see {@link containerLayout}).
 *
 * MATERIAL CLASSES. A set is drawn by its class and by nothing else: `opaque`, `cutout`, `decal` or
 * `glazing`, with glTF 2.0's meanings. The list is closed; a class, profile or maker kind this reader
 * was not written for is a refusal, never a guess. Whether a renderer draws a class is the renderer's
 * decision, not this reader's: a set that reads is a set, whatever its class.
 *
 * WHAT IT REFUSES, AND WHY IT REFUSES RATHER THAN DEGRADES. A set is bytes a renderer uploads as
 * surfaces a person reads as brick or stone. Bytes that do not hash to the manifest's pin, a
 * container whose header says something the manifest does not, or a layout this reader was not
 * written for are not a lower-quality texture, they are a different claim, so each one is a
 * {@link TextureSetRefusal} with one of the shared reasons (`manifest`, `byte-size`, `digest`,
 * `container`, `header`), and the caller draws its stated unavailable surface. There is no default
 * set and no fallback colour anywhere in this module.
 *
 * **Without `crypto.subtle` there is no texture at all.** The same posture as the app's geometry
 * reader: a page with no `SubtleCrypto` cannot check a pin, so every set is refused, before a single
 * byte is parsed. The digest is passed in only so a test can take it away.
 *
 * Pure: no DOM, no Node, no renderer. The maps it returns are views over the caller's bytes.
 */

export const TEXTURE_MANIFEST_PROFILE_V1 = 'exulanica.texture-manifest/v1';
export const TEXTURE_MANIFEST_PROFILE_V2 = 'exulanica.texture-manifest/v2';
export const TEXTURE_SET_PROFILE_V1 = 'exulanica.texture-set/v1';
export const TEXTURE_SET_PROFILE_V2 = 'exulanica.texture-set/v2';
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

export type TextureManifestProfile = typeof TEXTURE_MANIFEST_PROFILE_V1 | typeof TEXTURE_MANIFEST_PROFILE_V2;
export type TextureSetProfile = typeof TEXTURE_SET_PROFILE_V1 | typeof TEXTURE_SET_PROFILE_V2;

/** Closed and append-only. A class not listed here is refused wherever it appears. */
export const MATERIAL_CLASSES = ['opaque', 'cutout', 'decal', 'glazing'] as const;
export type MaterialClass = (typeof MATERIAL_CLASSES)[number];

/**
 * How a set's texels came to be. A procedural set rebakes exactly, so it may leave out what a rebake
 * restores; a model-made set ships every map its model produced.
 */
export const MAKER_KINDS = ['procedural', 'model'] as const;
export type MakerKind = (typeof MAKER_KINDS)[number];

/** A cutout's coverage threshold in a byte: glTF's default `alphaCutoff` of 0.5. */
export const TEXTURE_SET_ALPHA_CUTOFF = 128;
/** Glazing's index of refraction, in millionths: glTF's `KHR_materials_ior` default of 1.5. */
export const TEXTURE_SET_GLAZING_IOR_MILLIONTHS = 1_500_000;

const ALIGNMENT = 16;
const PREAMBLE = 8;
const MAXIMUM_DEPTH = 64;
const SET_ID = /^[a-z][a-z0-9.-]*$/;
const HEX64 = /^[0-9a-f]{64}$/;
const PRINTABLE = /^[\x20-\x7e]*$/;

export type TextureMapName = 'base_color' | 'base_color_coverage' | 'normal' | 'orm' | 'transmission_roughness' | 'height';

/** One map exactly as a header describes it, less where it lies. */
interface MapDescriptor {
  readonly name: TextureMapName;
  readonly components: number;
  readonly holds: readonly string[];
  readonly srgb: boolean;
  readonly decode: string;
  /** Normal maps state their space and convention; no other map does. */
  readonly tangent: boolean;
}

const map = (name: TextureMapName, holds: readonly string[], srgb: boolean, decode: string, tangent = false): MapDescriptor =>
  Object.freeze({ name, components: holds.length, holds: Object.freeze([...holds]), srgb, decode, tangent });

/** Every map a container may hold, as the texture package states them. The decode words are part of the layout. */
const MAPS = {
  baseColor: map('base_color', ['red', 'green', 'blue'], true, 'sRGB transfer function to linear reflectance'),
  baseColorCoverage: map('base_color_coverage', ['red', 'green', 'blue', 'coverage'], true,
    'red, green and blue: sRGB transfer function to linear reflectance; coverage: b / 255, linear, 0 where nothing covers'),
  normalXyz: map('normal', ['normal_x', 'normal_y', 'normal_z'], false, 'n = 2 * b / 255 - 1 per component, then normalise', true),
  normalXy: map('normal', ['normal_x', 'normal_y'], false,
    'x = 2 * b / 255 - 1, and y likewise; z = sqrt(max(0, 1 - x * x - y * y)); then normalise', true),
  orm: map('orm', ['occlusion', 'roughness', 'metalness'], false,
    'b / 255, linear; occlusion 255 is unoccluded; roughness is perceptual'),
  transmissionRoughness: map('transmission_roughness', ['transmission', 'roughness'], false,
    'b / 255, linear; transmission 255 passes all the light the surface does not reflect; roughness is perceptual'),
  height: map('height', ['height'], false, 'mm = b * height_range_mm / 255, above the lowest point the set can hold'),
} as const;

/** `exulanica.texture-set/v1`: the only v1 layout, and every v1 set is `opaque`. */
const V1_LAYOUT: readonly MapDescriptor[] = Object.freeze([MAPS.baseColor, MAPS.normalXyz, MAPS.orm, MAPS.height]);

/** Which maps a model produced beyond its class's required ones. */
interface Produced { readonly normal: boolean; readonly height: boolean }

/**
 * The one layout a v2 container of this class and maker kind holds. Procedural: the class's colour
 * map, a two-component normal unless it is glazing, and its surface map; no height map, because it
 * rebakes. Model-made: the colour map, a three-component normal if the model produced one, the
 * surface map, and the height map if the model produced one.
 */
function containerLayout(materialClass: MaterialClass, makerKind: MakerKind, produced: Produced): readonly MapDescriptor[] {
  const colour = materialClass === 'cutout' || materialClass === 'decal' ? MAPS.baseColorCoverage : MAPS.baseColor;
  const surface = materialClass === 'glazing' ? MAPS.transmissionRoughness : MAPS.orm;
  if (makerKind === 'procedural') {
    return materialClass === 'glazing' ? [MAPS.baseColor, MAPS.transmissionRoughness] : [colour, MAPS.normalXy, MAPS.orm];
  }
  return [colour, ...(produced.normal ? [MAPS.normalXyz] : []), surface, ...(produced.height ? [MAPS.height] : [])];
}

/** Every layout a manifest entry of this profile and class may list: the entry does not name its maker. */
function allowedLayouts(profile: TextureSetProfile, materialClass: MaterialClass): readonly (readonly MapDescriptor[])[] {
  if (profile === TEXTURE_SET_PROFILE_V1) return materialClass === 'opaque' ? [V1_LAYOUT] : [];
  const layouts = [containerLayout(materialClass, 'procedural', { normal: false, height: false })];
  for (const normal of [false, true]) {
    for (const height of [false, true]) layouts.push(containerLayout(materialClass, 'model', { normal, height }));
  }
  const seen = new Set<string>();
  return layouts.filter((layout) => {
    const key = canonical(channelsOf(layout) as unknown as Json);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

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

/** What a manifest entry states of a map: the packing, without the prose. */
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
  /** In stored order. */
  readonly channels: readonly TextureSetChannel[];
  readonly extentUMm: number;
  readonly extentVMm: number;
  readonly licenceId: string;
  readonly licenceSha256: string;
  /** `exulanica.texture-set/v1` for every entry of a v1 manifest. */
  readonly containerProfile: TextureSetProfile;
  /** `opaque` for every v1 container. */
  readonly materialClass: MaterialClass;
}

export interface TextureSetManifest {
  readonly profile: TextureManifestProfile;
  /** In manifest order, which is set id order. */
  readonly sets: readonly TextureSetManifestEntry[];
  /** A material record's set id resolves here or it does not resolve. */
  readonly byId: ReadonlyMap<string, TextureSetManifestEntry>;
}

/** How the set is laid on a surface, as its header states it. */
export type TextureSetSurface = 'vertical' | 'horizontal';

/** What a header fixes under `class`, typed by class. */
export type TextureSetClassParameters =
  | { readonly materialClass: 'opaque' }
  | { readonly materialClass: 'cutout'; readonly alphaCutoff: number; readonly coveragePermille: number; readonly doubleSided: true }
  | { readonly materialClass: 'decal'; readonly coveragePermille: number }
  | { readonly materialClass: 'glazing'; readonly iorMillionths: number; readonly doubleSided: false };

export interface DecodedTextureSet {
  readonly entry: TextureSetManifestEntry;
  readonly profile: TextureSetProfile;
  readonly materialClass: MaterialClass;
  readonly makerKind: MakerKind;
  readonly classParameters: TextureSetClassParameters;
  readonly surface: TextureSetSurface;
  readonly title: string;
  /**
   * Millimetres of relief the set's height field spans, which its normals were derived from, or null
   * when the header states none (procedural glazing, and a model-made set without a height map).
   */
  readonly heightRangeMm: number | null;
  /** The maps in stored order, as the entry lists them. */
  readonly channels: readonly TextureSetChannel[];
  /** Row 0 first, interleaved within each map, one byte per component. Views, not copies. */
  readonly maps: Readonly<Partial<Record<TextureMapName, Uint8Array>>>;
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

type JsonObject = { readonly [key: string]: Json };

function isObject(value: Json | undefined): value is JsonObject {
  return value !== null && value !== undefined && typeof value === 'object' && !Array.isArray(value);
}

function record(value: Json | undefined, keys: readonly string[], where: string, reason: TextureSetRefusalReason): JsonObject {
  if (!isObject(value)) return refuse(reason, `${where} is not an object`);
  const actual = Object.keys(value).sort().join(' ');
  const expected = [...keys].sort().join(' ');
  if (actual !== expected) refuse(reason, `${where} has keys ${actual}, not exactly ${expected}`);
  return value;
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

function oneOf<T extends string>(value: Json | undefined, allowed: readonly T[]): value is T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value);
}

function channelsOf(layout: readonly MapDescriptor[]): TextureSetChannel[] {
  return layout.map((descriptor) => ({
    map: descriptor.name, components: descriptor.components, holds: descriptor.holds, srgb: descriptor.srgb,
  }));
}

const ENTRY_KEYS_V1 = ['byte_size', 'channels', 'content_sha256', 'extent_mm', 'licence_id', 'licence_sha256', 'resolution', 'set_id', 'version'];
const ENTRY_KEYS_V2 = [...ENTRY_KEYS_V1, 'container_profile', 'material_class'];

function manifestEntry(value: Json, index: number, profile: TextureManifestProfile): TextureSetManifestEntry {
  const where = `manifest sets[${index}]`;
  const entry = record(value, profile === TEXTURE_MANIFEST_PROFILE_V1 ? ENTRY_KEYS_V1 : ENTRY_KEYS_V2, where, 'manifest');
  const setId = entry['set_id'];
  if (typeof setId !== 'string' || !SET_ID.test(setId)) refuse('manifest', `${where} set_id is not a texture set id`);
  for (const field of ['content_sha256', 'licence_sha256']) {
    const digest = entry[field];
    if (typeof digest !== 'string' || !HEX64.test(digest)) refuse('manifest', `${where} ${field} is not 64 lowercase hex`);
  }
  if (entry['licence_id'] !== TEXTURE_SET_LICENCE_ID) refuse('manifest', `${where} licence_id is not ${TEXTURE_SET_LICENCE_ID}`);
  const resolution = record(entry['resolution'], ['height', 'width'], `${where} resolution`, 'manifest');
  const extent = record(entry['extent_mm'], ['u', 'v'], `${where} extent_mm`, 'manifest');
  let containerProfile: TextureSetProfile = TEXTURE_SET_PROFILE_V1;
  let materialClass: MaterialClass = 'opaque';
  if (profile === TEXTURE_MANIFEST_PROFILE_V2) {
    const statedProfile = entry['container_profile'];
    if (!oneOf(statedProfile, [TEXTURE_SET_PROFILE_V1, TEXTURE_SET_PROFILE_V2])) {
      refuse('manifest', `${where} container_profile is not a texture set profile this reader was written for`);
    }
    const statedClass = entry['material_class'];
    if (!oneOf(statedClass, MATERIAL_CLASSES)) refuse('manifest', `${where} material_class is not one of ${MATERIAL_CLASSES.join(', ')}`);
    containerProfile = statedProfile;
    materialClass = statedClass;
  }
  const allowed = allowedLayouts(containerProfile, materialClass);
  if (allowed.length === 0) refuse('manifest', `${where} is a ${containerProfile} container, which is opaque, never ${materialClass}`);
  const channels = entry['channels'];
  const listed = allowed.map(channelsOf).find((layout) => sameJson(channels, layout as unknown as Json));
  if (listed === undefined) {
    refuse('manifest', `${where} channels are not a layout of profile ${containerProfile} and class ${materialClass}, map for map`);
  }
  return Object.freeze({
    setId,
    version: positive(entry['version'], `${where} version`, 'manifest'),
    contentSha256: entry['content_sha256'] as string,
    byteSize: positive(entry['byte_size'], `${where} byte_size`, 'manifest'),
    width: positive(resolution['width'], `${where} resolution width`, 'manifest'),
    height: positive(resolution['height'], `${where} resolution height`, 'manifest'),
    channels: Object.freeze(listed.map((channel) => Object.freeze(channel))),
    extentUMm: positive(extent['u'], `${where} extent_mm u`, 'manifest'),
    extentVMm: positive(extent['v'], `${where} extent_mm v`, 'manifest'),
    licenceId: TEXTURE_SET_LICENCE_ID,
    licenceSha256: entry['licence_sha256'] as string,
    containerProfile,
    materialClass,
  });
}

/** Read `manifest.json` from its bytes, strictly. Every refusal is reason `manifest`. */
export function parseTextureSetManifest(bytes: Uint8Array): TextureSetManifest {
  const document = record(canonicalDocument(bytes, 'manifest', 'the texture manifest'), ['profile', 'sets'], 'the texture manifest', 'manifest');
  const profile = document['profile'];
  if (!oneOf(profile, [TEXTURE_MANIFEST_PROFILE_V1, TEXTURE_MANIFEST_PROFILE_V2])) {
    refuse('manifest', `the texture manifest does not declare ${TEXTURE_MANIFEST_PROFILE_V1} or ${TEXTURE_MANIFEST_PROFILE_V2}`);
  }
  const sets = document['sets'];
  if (!Array.isArray(sets) || sets.length === 0) refuse('manifest', 'the texture manifest lists no sets');
  const entries = (sets as readonly Json[]).map((value, index) => manifestEntry(value, index, profile));
  const byId = new Map<string, TextureSetManifestEntry>();
  entries.forEach((entry, index) => {
    if (index > 0 && !(entries[index - 1]!.setId < entry.setId)) {
      refuse('manifest', `the texture manifest lists its sets sorted by set_id, each once; ${entry.setId} is out of place`);
    }
    byId.set(entry.setId, entry);
  });
  return Object.freeze({ profile, sets: Object.freeze(entries), byId });
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

/** Every key a v2 header holds, whatever its class and maker. */
const V2_HEADER_KEYS = [
  'class', 'extent_mm', 'family', 'generator', 'layout', 'licence', 'maker_kind', 'maps', 'material_class', 'media_type',
  'parameters', 'placement', 'profile', 'resolution', 'seed', 'set_id', 'summary', 'tiling', 'title', 'truth', 'version',
];

/**
 * A procedural set whose class bakes a height field (every class but glazing) states the field's
 * range and its cavity, which its normals and occlusion were derived from. A model-made set states
 * the range only when it ships the height map the range decodes.
 */
function reliefKeys(materialClass: MaterialClass, makerKind: MakerKind, shipsHeight: boolean): string[] {
  if (makerKind === 'procedural') return materialClass === 'glazing' ? [] : ['cavity', 'height_range_mm'];
  return shipsHeight ? ['height_range_mm'] : [];
}

/** The share of texels whose coverage is at least the cutoff, in thousandths, floored. */
function coveragePermille(colourCoverage: Uint8Array): number {
  const texels = colourCoverage.length / 4;
  let covered = 0;
  for (let at = 3; at < colourCoverage.length; at += 4) {
    if (colourCoverage[at]! >= TEXTURE_SET_ALPHA_CUTOFF) covered += 1;
  }
  return Math.floor((covered * 1000) / texels);
}

/** What `class` must say for this class, with a coverage the reader measured itself. */
function statedClass(materialClass: MaterialClass, coverage: number | null): { readonly json: JsonObject; readonly parameters: TextureSetClassParameters } {
  const measured = (): number => {
    if (coverage === null) throw new Error(`a ${materialClass} layout always holds a coverage channel`);
    return coverage;
  };
  switch (materialClass) {
    case 'opaque':
      return { json: {}, parameters: { materialClass } };
    case 'cutout':
      return {
        json: { alpha_cutoff: TEXTURE_SET_ALPHA_CUTOFF, coverage_permille: measured(), double_sided: true },
        parameters: { materialClass, alphaCutoff: TEXTURE_SET_ALPHA_CUTOFF, coveragePermille: measured(), doubleSided: true },
      };
    case 'decal':
      return { json: { coverage_permille: measured() }, parameters: { materialClass, coveragePermille: measured() } };
    case 'glazing':
      return {
        json: { double_sided: false, ior_millionths: TEXTURE_SET_GLAZING_IOR_MILLIONTHS },
        parameters: { materialClass, iorMillionths: TEXTURE_SET_GLAZING_IOR_MILLIONTHS, doubleSided: false },
      };
  }
}

function decodeContainer(bytes: Uint8Array, entry: TextureSetManifestEntry): DecodedTextureSet {
  const where = entry.setId;
  if (bytes.byteLength < PREAMBLE) refuse('container', `${where} is shorter than its preamble`);
  const magic = String.fromCharCode(bytes[0]!, bytes[1]!, bytes[2]!, bytes[3]!);
  if (magic !== TEXTURE_SET_MAGIC) refuse('container', `${where} is not a texture set container`);
  const headerLength = new DataView(bytes.buffer, bytes.byteOffset, PREAMBLE).getUint32(4, true);
  if (PREAMBLE + headerLength > bytes.byteLength) refuse('container', `${where}: the header runs past the end of the file`);
  const header = canonicalDocument(bytes.subarray(PREAMBLE, PREAMBLE + headerLength), 'header', `${where} header`);
  if (!isObject(header)) return refuse('header', `${where} header is not an object`);
  const h = header;

  const profile = h['profile'];
  if (!oneOf(profile, [TEXTURE_SET_PROFILE_V1, TEXTURE_SET_PROFILE_V2])) {
    refuse('header', `${where} declares a texture set profile this reader was not written for`);
  }
  const expected: Readonly<Record<string, Json>> = {
    profile: entry.containerProfile,
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

  const declared = h['maps'];
  if (!Array.isArray(declared)) return refuse('header', `${where}: the map list is not the stated layout`);
  let materialClass: MaterialClass = 'opaque';
  let makerKind: MakerKind = 'procedural';
  let layout: readonly MapDescriptor[] = V1_LAYOUT;
  if (profile === TEXTURE_SET_PROFILE_V2) {
    const stated = h['material_class'];
    if (!oneOf(stated, MATERIAL_CLASSES)) refuse('header', `${where} header material_class is not one of ${MATERIAL_CLASSES.join(', ')}`);
    const kind = h['maker_kind'];
    if (!oneOf(kind, MAKER_KINDS)) refuse('header', `${where} header maker_kind is not one of ${MAKER_KINDS.join(', ')}`);
    materialClass = stated;
    makerKind = kind;
    if (materialClass !== entry.materialClass) {
      refuse('header', `${where} is a ${materialClass} container; the manifest says ${entry.materialClass}`);
    }
    const named = (name: TextureMapName): boolean => (declared as readonly Json[]).some((item) => isObject(item) && item['name'] === name);
    const produced = { normal: named('normal'), height: named('height') };
    layout = containerLayout(materialClass, makerKind, produced);
    record(h, [...V2_HEADER_KEYS, ...reliefKeys(materialClass, makerKind, produced.height)],
      `${where} header of maker kind ${makerKind} and class ${materialClass}`, 'header');
  }

  const placement = h['placement'];
  const surface = isObject(placement) ? placement['surface'] : undefined;
  if (surface !== 'vertical' && surface !== 'horizontal') refuse('header', `${where} header states no vertical or horizontal placement`);
  nonNegative(h['seed'], `${where} header seed`, 'header');
  const title = text(h['title'], `${where} header title`, 'header');
  text(h['summary'], `${where} header summary`, 'header');
  let heightRangeMm: number | null = null;
  if (profile === TEXTURE_SET_PROFILE_V1) {
    heightRangeMm = nonNegative(h['height_range_mm'], `${where} header height_range_mm`, 'header');
  } else {
    if ('height_range_mm' in h) heightRangeMm = positive(h['height_range_mm'], `${where} header height_range_mm`, 'header');
    if ('cavity' in h) {
      const cavity = record(h['cavity'], ['depth_mm', 'radius_mm', 'strength_permille'], `${where} header cavity`, 'header');
      positive(cavity['radius_mm'], `${where} header cavity radius_mm`, 'header');
      positive(cavity['depth_mm'], `${where} header cavity depth_mm`, 'header');
      nonNegative(cavity['strength_permille'], `${where} header cavity strength_permille`, 'header');
    }
  }

  const start = Math.ceil((PREAMBLE + headerLength) / ALIGNMENT) * ALIGNMENT;
  if (start > bytes.byteLength) refuse('container', `${where}: the padding runs past the end of the file`);
  for (let at = PREAMBLE + headerLength; at < start; at += 1) {
    if (bytes[at] !== 0x20) refuse('container', `${where}: padding byte ${at} is not a space`);
  }
  if (declared.length !== layout.length) refuse('header', `${where}: the map list is not the stated layout`);
  const texels = entry.width * entry.height;
  const maps: Partial<Record<TextureMapName, Uint8Array>> = {};
  let cursor = start;
  layout.forEach((descriptor, index) => {
    const length = texels * descriptor.components;
    const described: Json = {
      name: descriptor.name,
      components: descriptor.components,
      holds: descriptor.holds,
      srgb: descriptor.srgb,
      decode: descriptor.decode,
      ...(descriptor.tangent ? { space: 'tangent', convention: TEXTURE_SET_NORMAL_CONVENTION } : {}),
      byte_offset: cursor,
      byte_length: length,
    };
    if (!sameJson((declared as readonly Json[])[index], described)) {
      refuse('header', `${where}: map ${index} is not ${descriptor.name} as the ${profile} layout packs and describes it`);
    }
    if (cursor + length > bytes.byteLength) refuse('container', `${where}: map ${descriptor.name} runs past the end of the file`);
    maps[descriptor.name] = bytes.subarray(cursor, cursor + length);
    cursor += length;
  });
  if (cursor !== bytes.byteLength) refuse('container', `${where}: the maps end at byte ${cursor}, the file at ${bytes.byteLength}`);

  let classParameters: TextureSetClassParameters = { materialClass: 'opaque' };
  if (profile === TEXTURE_SET_PROFILE_V2) {
    const colour = maps.base_color_coverage;
    const stated = statedClass(materialClass, colour === undefined ? null : coveragePermille(colour));
    if (!sameJson(h['class'], stated.json)) {
      refuse('header', `${where} header class is not what a ${materialClass} set with these texels states`);
    }
    classParameters = stated.parameters;
  }
  const channels = channelsOf(layout);
  if (!sameJson(channels as unknown as Json, entry.channels as unknown as Json)) {
    refuse('header', `${where}: the manifest's channels are not the header's maps`);
  }
  return Object.freeze({
    entry,
    profile,
    materialClass,
    makerKind,
    classParameters: Object.freeze(classParameters),
    surface,
    title,
    heightRangeMm,
    channels: entry.channels,
    maps: Object.freeze(maps),
  });
}
