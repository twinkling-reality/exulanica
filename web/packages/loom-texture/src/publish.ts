import { createHash } from 'node:crypto';
import { canonicalBytes } from './canonical-json.js';
import { CATALOG } from './catalog.js';
import { MAP_LAYOUT, encodeContainer } from './container.js';
import type { TextureSetDefinition } from './definition.js';
import { LICENCE_ID, licenceBytes } from './licence.js';
import { bakeMaps } from './maps.js';

/**
 * Bake the catalog into the files `assets/textures/` holds, as bytes, without touching a disk.
 *
 * The directory is content-addressed: each set is `blobs/<sha256>.ltex`, the licence text is
 * `blobs/<sha256>.txt`, and `manifest.json` is the single index both
 * `exulanica/world/texture_assets.py` and the grammar's catalog loader read. Its shape was fixed
 * with the grammar lane before either side was written:
 *
 *   {"profile": "exulanica.texture-manifest/v1", "sets": [entry, ...]}
 *
 * with `sets` sorted by `set_id`, each id once, and each entry holding exactly `set_id`,
 * `version`, `content_sha256`, `byte_size`, `resolution`, `channels`, `extent_mm`, `licence_id`
 * and `licence_sha256`. The file is canonical JSON with no trailing newline, so its bytes are a
 * function of its content and nothing else.
 *
 * `version` and `content_sha256` are replay inputs: the grammar pins both into its catalog
 * digest. A rebake that changes a set's bytes without bumping its version is a replay bug.
 */
export const MANIFEST_PROFILE = 'exulanica.texture-manifest/v1';
export const MANIFEST_FILE = 'manifest.json';
/**
 * Every file here is pinned by digest, so no checkout may convert a line ending, expand a keyword
 * or run a filter over one: the licence text is LF-terminated, and a CRLF checkout of it is a
 * different digest. The blobs are binary outright. The manifest keeps a textual diff, because a
 * reviewer of a rebake needs to see which digest moved.
 */
export const ATTRIBUTES_FILE = '.gitattributes';
export const ATTRIBUTES_TEXT = [
  '# Pinned by digest: no line-ending conversion, keyword expansion or filter, ever.',
  '* -text -ident -filter -working-tree-encoding',
  'blobs/** binary',
  '',
].join('\n');
export const BLOB_DIRECTORY = 'blobs';
export const SET_EXTENSION = '.ltex';
export const LICENCE_EXTENSION = '.txt';
/** Identical to `asset_key` in migration 0042, and to `set_id` in migration 0065. */
export const SET_ID_PATTERN = /^[a-z][a-z0-9.-]*$/;

export interface ManifestEntry {
  readonly set_id: string;
  readonly version: number;
  readonly content_sha256: string;
  readonly byte_size: number;
  readonly resolution: { readonly width: number; readonly height: number };
  readonly channels: readonly {
    readonly map: string;
    readonly components: number;
    readonly holds: readonly string[];
    readonly srgb: boolean;
  }[];
  readonly extent_mm: { readonly u: number; readonly v: number };
  readonly licence_id: string;
  readonly licence_sha256: string;
}

export interface PublishedSet {
  readonly definition: TextureSetDefinition;
  readonly container: Uint8Array;
  readonly entry: ManifestEntry;
  readonly path: string;
}

export interface Publication {
  readonly sets: readonly PublishedSet[];
  readonly licence: { readonly bytes: Uint8Array; readonly sha256: string; readonly path: string };
  readonly manifest: Uint8Array;
  /** Every file the output directory holds, by path relative to it. */
  readonly files: ReadonlyMap<string, Uint8Array>;
}

export function sha256Hex(bytes: Uint8Array): string {
  return createHash('sha256').update(bytes).digest('hex');
}

const positive = (value: number): boolean => Number.isSafeInteger(value) && value > 0;

function checkDefinition(def: TextureSetDefinition): void {
  const problems: string[] = [];
  if (!SET_ID_PATTERN.test(def.setId)) problems.push('set id does not match ^[a-z][a-z0-9.-]*$');
  if (/v\d|[0-9a-f]{16}/.test(def.setId)) problems.push('a set id never carries a version or digest');
  if (!positive(def.version)) problems.push('version is a positive integer');
  if (!Number.isSafeInteger(def.seed) || def.seed < 0 || def.seed > 0xffffffff) {
    problems.push('seed is an unsigned 32-bit integer');
  }
  for (const [name, value] of Object.entries({
    width: def.width,
    height: def.height,
    extentU: def.extentU,
    extentV: def.extentV,
    heightRangeMm: def.heightRangeMm,
  })) {
    if (!positive(value)) problems.push(`${name} is a positive integer, got ${value}`);
  }
  if (problems.length > 0) throw new Error(`${def.setId}: ${problems.join('; ')}`);
}

export function manifestEntry(
  def: TextureSetDefinition,
  container: Uint8Array,
  licenceSha256: string,
): ManifestEntry {
  return {
    set_id: def.setId,
    version: def.version,
    content_sha256: sha256Hex(container),
    byte_size: container.length,
    resolution: { width: def.width, height: def.height },
    channels: MAP_LAYOUT.map((layout) => ({
      map: layout.name,
      components: layout.components,
      holds: layout.holds,
      srgb: layout.srgb,
    })),
    extent_mm: { u: def.extentU, v: def.extentV },
    licence_id: LICENCE_ID,
    licence_sha256: licenceSha256,
  };
}

export function manifestBytes(entries: readonly ManifestEntry[]): Uint8Array {
  const sorted = [...entries].sort((a, b) => (a.set_id < b.set_id ? -1 : a.set_id > b.set_id ? 1 : 0));
  for (let index = 1; index < sorted.length; index += 1) {
    if (sorted[index]!.set_id === sorted[index - 1]!.set_id) {
      throw new Error(`set ${sorted[index]!.set_id} is published twice`);
    }
  }
  return canonicalBytes({ profile: MANIFEST_PROFILE, sets: sorted });
}

export function publishSet(def: TextureSetDefinition, licenceSha256: string): PublishedSet {
  checkDefinition(def);
  const container = encodeContainer(def, bakeMaps(def), licenceSha256);
  const entry = manifestEntry(def, container, licenceSha256);
  return {
    definition: def,
    container,
    entry,
    path: `${BLOB_DIRECTORY}/${entry.content_sha256}${SET_EXTENSION}`,
  };
}

export function publish(catalog: readonly TextureSetDefinition[] = CATALOG): Publication {
  const licence = licenceBytes();
  const licenceSha256 = sha256Hex(licence);
  const sets = catalog.map((def) => publishSet(def, licenceSha256));
  const manifest = manifestBytes(sets.map((set) => set.entry));
  const licencePath = `${BLOB_DIRECTORY}/${licenceSha256}${LICENCE_EXTENSION}`;
  const files = new Map<string, Uint8Array>();
  files.set(ATTRIBUTES_FILE, new TextEncoder().encode(ATTRIBUTES_TEXT));
  files.set(licencePath, licence);
  for (const set of sets) files.set(set.path, set.container);
  files.set(MANIFEST_FILE, manifest);
  return {
    sets,
    licence: { bytes: licence, sha256: licenceSha256, path: licencePath },
    manifest,
    files,
  };
}
