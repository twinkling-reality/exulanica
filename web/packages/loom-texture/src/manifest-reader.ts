import { canonicalJson } from './canonical-json.js';
import {
  type Channel,
  MATERIAL_CLASSES,
  type MaterialClass,
  SET_PROFILES,
  SET_PROFILE_V1,
  type SetProfile,
  allowedChannels,
  channelsOf,
  isMaterialClass,
  isSetProfile,
} from './classes.js';
import {
  ContainerRefusal,
  type ContainerRefusalReason,
  MEDIA_TYPE,
  type ReadContainer,
  TRUTH,
  readContainer,
} from './container.js';
import { sha256Hex } from './digest.js';
import { SET_ID_PATTERN } from './library.js';
import { LICENCE_ID } from './licence.js';
import { StrictJsonError, parseStrictJsonBytes } from './strict-json.js';

/**
 * THE MANIFEST AS A READER HOLDS IT, AND A CONTAINER HELD TO ITS ENTRY.
 *
 * Three runtimes read `assets/textures/manifest.json` and the containers it pins: the backend
 * (`exulanica/materials/manifest.py` and `exulanica/world/texture_assets.py`), the browser
 * (`atlas-core`'s `texture-set.ts`) and this package. Each is written from the stated layout rather
 * than copied from another, and `test/texture-set-cases.json` holds all three to the same outcome
 * for every case: accepted, or refused for the same one of five reasons.
 *
 *   - `manifest`: the manifest document, or an entry in it, is not what a manifest may say.
 *   - `byte-size` and `digest`: the bytes are not the ones the entry pins.
 *   - `container`: the file's framing (magic, lengths, padding, where the maps end).
 *   - `header`: what the header says, including where it disagrees with the entry.
 *
 * `exulanica.texture-manifest/v1` lists v1 containers only, and every one is `opaque`. v2 adds two
 * fields to each entry, `container_profile` and `material_class`, and its `channels` must be one of
 * the layouts that pair allows.
 */
export const MANIFEST_PROFILE_V1 = 'exulanica.texture-manifest/v1';
export const MANIFEST_PROFILE_V2 = 'exulanica.texture-manifest/v2';

export type TextureSetRefusalReason = 'manifest' | 'byte-size' | 'digest' | ContainerRefusalReason;

/** A manifest or a set a reader will not read, and the one reason why. */
export class TextureSetRefusal extends Error {
  constructor(
    readonly reason: TextureSetRefusalReason,
    message: string,
  ) {
    super(message);
    this.name = 'TextureSetRefusal';
  }
}

function refuse(reason: TextureSetRefusalReason, message: string): never {
  throw new TextureSetRefusal(reason, message);
}

/** One entry, read field for field. */
export interface ManifestEntryRead {
  readonly setId: string;
  readonly version: number;
  readonly contentSha256: string;
  readonly byteSize: number;
  readonly width: number;
  readonly height: number;
  readonly extentUMm: number;
  readonly extentVMm: number;
  readonly licenceId: string;
  readonly licenceSha256: string;
  readonly containerProfile: SetProfile;
  readonly materialClass: MaterialClass;
  readonly channels: readonly Channel[];
}

const V1_ENTRY_KEYS = [
  'byte_size',
  'channels',
  'content_sha256',
  'extent_mm',
  'licence_id',
  'licence_sha256',
  'resolution',
  'set_id',
  'version',
];
const V2_ENTRY_KEYS = [...V1_ENTRY_KEYS, 'container_profile', 'material_class'].sort();
const HEX64 = /^[0-9a-f]{64}$/;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const positive = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value > 0;

function sameKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const present = Object.keys(value).sort();
  const wanted = [...keys].sort();
  return present.length === wanted.length && present.every((key, index) => key === wanted[index]);
}

function pair(value: unknown, first: string, second: string): [number, number] | null {
  return isRecord(value) && sameKeys(value, [first, second]) && positive(value[first]) && positive(value[second])
    ? [value[first] as number, value[second] as number]
    : null;
}

function readEntry(value: unknown, profile: string, where: string): ManifestEntryRead {
  const keys = profile === MANIFEST_PROFILE_V1 ? V1_ENTRY_KEYS : V2_ENTRY_KEYS;
  if (!isRecord(value) || !sameKeys(value, keys)) refuse('manifest', `${where} has exactly ${keys.join(', ')}`);
  const setId = value.set_id;
  if (typeof setId !== 'string' || !SET_ID_PATTERN.test(setId)) {
    refuse('manifest', `${where}: set_id is not a texture set id`);
  }
  if (!positive(value.version) || !positive(value.byte_size)) {
    refuse('manifest', `${where}: version and byte_size are positive integers`);
  }
  for (const field of ['content_sha256', 'licence_sha256']) {
    const digest = value[field];
    if (typeof digest !== 'string' || !HEX64.test(digest)) {
      refuse('manifest', `${where}: ${field} is 64 lowercase hex characters`);
    }
  }
  const resolution = pair(value.resolution, 'width', 'height');
  if (resolution === null) refuse('manifest', `${where}: resolution is a positive width and height`);
  const extent = pair(value.extent_mm, 'u', 'v');
  if (extent === null) refuse('manifest', `${where}: extent_mm is a positive whole-millimetre u and v`);
  if (value.licence_id !== LICENCE_ID) {
    refuse('manifest', `${where}: licence_id is ${LICENCE_ID}; the manifest lists published sets only`);
  }
  let containerProfile: SetProfile = SET_PROFILE_V1;
  let materialClass: MaterialClass = 'opaque';
  if (profile !== MANIFEST_PROFILE_V1) {
    if (!isSetProfile(value.container_profile)) {
      refuse('manifest', `${where}: container_profile is one of ${SET_PROFILES.join(', ')}`);
    }
    if (!isMaterialClass(value.material_class)) {
      refuse('manifest', `${where}: material_class is one of ${MATERIAL_CLASSES.join(', ')}`);
    }
    containerProfile = value.container_profile;
    materialClass = value.material_class;
  }
  const allowed = allowedChannels(containerProfile, materialClass);
  if (allowed.length === 0) {
    refuse('manifest', `${where}: a container of profile ${containerProfile} is opaque, never ${materialClass}`);
  }
  const channels = value.channels;
  let stated: string | null;
  try {
    stated = canonicalJson(channels as object);
  } catch {
    stated = null;
  }
  if (!Array.isArray(channels) || !allowed.some((layout) => canonicalJson(layout) === stated)) {
    refuse('manifest', `${where}: channels are not a container layout of profile ${containerProfile} and class ${materialClass}, map for map`);
  }
  return {
    setId,
    version: value.version,
    contentSha256: value.content_sha256 as string,
    byteSize: value.byte_size,
    width: resolution[0],
    height: resolution[1],
    extentUMm: extent[0],
    extentVMm: extent[1],
    licenceId: LICENCE_ID,
    licenceSha256: value.licence_sha256 as string,
    containerProfile,
    materialClass,
    channels: channels as Channel[],
  };
}

/** Read a manifest from its bytes, strictly. Every refusal is reason `manifest`. */
export function readTextureManifest(bytes: Uint8Array): ManifestEntryRead[] {
  let document: unknown;
  try {
    document = parseStrictJsonBytes(bytes);
  } catch (error) {
    if (error instanceof StrictJsonError) refuse('manifest', `the texture manifest: ${error.message}`);
    throw error;
  }
  let canonical: string | null;
  try {
    canonical = canonicalJson(document as object);
  } catch {
    canonical = null;
  }
  if (canonical !== new TextDecoder().decode(bytes)) {
    refuse('manifest', 'the texture manifest is not canonical JSON, so its bytes are not its content');
  }
  if (!isRecord(document) || !sameKeys(document, ['profile', 'sets'])) {
    refuse('manifest', 'the texture manifest is an object with exactly profile and sets');
  }
  const profile = document.profile;
  if (profile !== MANIFEST_PROFILE_V1 && profile !== MANIFEST_PROFILE_V2) {
    refuse('manifest', `the texture manifest's profile is ${MANIFEST_PROFILE_V1} or ${MANIFEST_PROFILE_V2}`);
  }
  const sets = document.sets;
  if (!Array.isArray(sets) || sets.length === 0) refuse('manifest', 'the texture manifest lists no sets');
  const entries = sets.map((entry: unknown, index: number) => readEntry(entry, profile, `sets[${index}]`));
  for (let index = 1; index < entries.length; index += 1) {
    if (!(entries[index - 1]!.setId < entries[index]!.setId)) {
      refuse('manifest', 'the texture manifest lists its sets sorted by set_id, each id once');
    }
  }
  return entries;
}

/**
 * Hold a container to its manifest entry, and read it.
 *
 * In this order, each refusing on its own: the byte count must be the pinned one; the sha256 must be
 * the pinned one; the container must be exactly what the baker writes; and its header must say what
 * the entry says.
 */
export function checkTextureSet(bytes: Uint8Array, entry: ManifestEntryRead): ReadContainer {
  const where = entry.setId;
  if (bytes.length !== entry.byteSize) {
    refuse('byte-size', `${where} is ${bytes.length} bytes; its pin is ${entry.byteSize}`);
  }
  const digest = sha256Hex(bytes);
  if (digest !== entry.contentSha256) {
    refuse('digest', `${where} hashes to ${digest}; its pin is ${entry.contentSha256}`);
  }
  let read: ReadContainer;
  try {
    read = readContainer(bytes);
  } catch (error) {
    if (error instanceof ContainerRefusal) refuse(error.reason, `${where}: ${error.message}`);
    throw error;
  }
  const expected: Readonly<Record<string, unknown>> = {
    profile: entry.containerProfile,
    material_class: read.profile === SET_PROFILE_V1 ? undefined : entry.materialClass,
    media_type: MEDIA_TYPE,
    truth: TRUTH,
    set_id: entry.setId,
    version: entry.version,
    resolution: { width: entry.width, height: entry.height },
    extent_mm: { u: entry.extentUMm, v: entry.extentVMm },
    licence: { id: entry.licenceId, sha256: entry.licenceSha256 },
  };
  for (const [key, value] of Object.entries(expected)) {
    if (value === undefined) continue;
    if (read.header[key] === undefined || canonicalJson(read.header[key] as object) !== canonicalJson(value as object)) {
      refuse('header', `${where}: header ${key} is not what the manifest pins`);
    }
  }
  if (read.materialClass !== entry.materialClass) {
    refuse('header', `${where}: the container is ${read.materialClass}; the manifest says ${entry.materialClass}`);
  }
  if (canonicalJson(channelsOf(read.layout)) !== canonicalJson(entry.channels)) {
    refuse('header', `${where}: the manifest's channels are not the header's maps`);
  }
  return read;
}
