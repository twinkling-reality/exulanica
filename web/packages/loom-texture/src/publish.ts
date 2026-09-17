import { canonicalBytes } from './canonical-json.js';
import { LIBRARY, definitionOf } from './catalog.js';
import {
  type Channel,
  type MaterialClass,
  SET_PROFILE_V1,
  type SetProfile,
  V1_LAYOUT,
  channelsOf,
  classLayout,
} from './classes.js';
import { encodeContainer, encodeContainerV2 } from './container.js';
import type { TextureSetDefinition } from './definition.js';
import { sha256Hex } from './digest.js';
import {
  type LibrarySet,
  SET_ID_PATTERN,
  VERSIONED_OR_DIGESTED,
  WORKSPACE_SET_ID_PREFIX,
} from './library.js';
import { LICENCE_ID, licenceBytes } from './licence.js';
import { MAKERS } from './makers/index.js';
import { MANIFEST_PROFILE_V2 } from './manifest-reader.js';
import { bakeClassMaps, bakeMaps } from './maps.js';
import {
  BAKE_PIPELINE,
  BAKE_PIPELINE_V2,
  CATALOG_FILE,
  ObjectStore,
  OBJECT_DIRECTORY,
  OBJECT_EXTENSION,
  bakeReceipt,
  catalogDocument,
  libraryEntryObject,
} from './objects.js';

export { sha256Hex } from './digest.js';
export { SET_ID_PATTERN } from './library.js';

/**
 * Bake the library into the files `assets/textures/` holds, as bytes, without touching a disk.
 *
 * The directory is content-addressed: each set is `blobs/<sha256>.ltex`, the licence text is
 * `blobs/<sha256>.txt`, every maker manifest, recipe, library entry and bake receipt is
 * `objects/<sha256>.json` (see `objects.ts`), and two indexes sit at the top. `catalog.json`
 * accounts for every set with a receipt. `manifest.json` is the index the backend, the grammar's
 * catalog loader and the browser all read:
 *
 *   {"profile": "exulanica.texture-manifest/v2", "sets": [entry, ...]}
 *
 * with `sets` sorted by `set_id`, each id once, and each entry holding exactly `set_id`,
 * `version`, `content_sha256`, `byte_size`, `resolution`, `channels`, `extent_mm`, `licence_id`,
 * `licence_sha256`, `container_profile` and `material_class`. A set baked before material classes
 * is `exulanica.texture-set/v1` and `opaque`, and its `channels` are the v1 layout; any other set's
 * are its class's layout. The file is canonical JSON with no trailing newline, so its bytes are a
 * function of its content and nothing else.
 *
 * `version` and `content_sha256` are replay inputs: the grammar pins both into its catalog
 * digest. A rebake that changes a set's bytes without bumping its version is a replay bug.
 */
export const MANIFEST_PROFILE = MANIFEST_PROFILE_V2;
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

export interface ManifestEntry {
  readonly set_id: string;
  readonly version: number;
  readonly content_sha256: string;
  readonly byte_size: number;
  readonly resolution: { readonly width: number; readonly height: number };
  readonly channels: readonly Channel[];
  readonly extent_mm: { readonly u: number; readonly v: number };
  readonly licence_id: string;
  readonly licence_sha256: string;
  readonly container_profile: SetProfile;
  readonly material_class: MaterialClass;
}

export interface PublishedSet {
  readonly definition: TextureSetDefinition;
  readonly container: Uint8Array;
  readonly entry: ManifestEntry;
  readonly path: string;
}

/** A published library set, and the digests of the objects that account for it. */
export interface PublishedLibrarySet extends PublishedSet {
  readonly source: LibrarySet;
  readonly makerSha256: string;
  readonly recipeSha256: string;
  readonly entrySha256: string;
  readonly receiptSha256: string;
}

export interface Publication {
  readonly sets: readonly PublishedLibrarySet[];
  readonly licence: { readonly bytes: Uint8Array; readonly sha256: string; readonly path: string };
  readonly manifest: Uint8Array;
  readonly catalog: Uint8Array;
  /** Every object, by digest. */
  readonly objects: ReadonlyMap<string, Uint8Array>;
  /** Every file the output directory holds, by path relative to it. */
  readonly files: ReadonlyMap<string, Uint8Array>;
}

const positive = (value: number): boolean => Number.isSafeInteger(value) && value > 0;

function checkDefinition(def: TextureSetDefinition): void {
  const problems: string[] = [];
  if (!SET_ID_PATTERN.test(def.setId)) problems.push('set id does not match ^[a-z][a-z0-9.-]*$');
  if (VERSIONED_OR_DIGESTED.test(def.setId)) {
    problems.push('a set id never carries a version or digest');
  }
  if (WORKSPACE_SET_ID_PREFIX.test(def.setId)) {
    problems.push('a set id beginning ws. names a workspace bake, which is never published');
  }
  if (def.licenceId !== LICENCE_ID) {
    problems.push(`a published set is under ${LICENCE_ID}, not ${def.licenceId}`);
  }
  if (!positive(def.version)) problems.push('version is a positive integer');
  if (!Number.isSafeInteger(def.seed) || def.seed < 0 || def.seed > 0xffffffff) {
    problems.push('seed is an unsigned 32-bit integer');
  }
  for (const [name, value] of Object.entries({
    width: def.width,
    height: def.height,
    extentU: def.extentU,
    extentV: def.extentV,
    ...(def.materialClass === 'glazing' ? {} : { heightRangeMm: def.heightRangeMm }),
  })) {
    if (value === null || !positive(value)) problems.push(`${name} is a positive integer, got ${value}`);
  }
  if (def.materialClass === 'glazing' && (def.heightRangeMm !== null || def.cavity !== null)) {
    problems.push('a glazing set bakes no height field, so it states no height range or cavity');
  }
  if ((def.film !== null) !== (def.materialClass === 'glazing')) {
    problems.push('a glazing set declares its film, and a set of any other class declares none');
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
    channels: channelsOf(
      def.containerProfile === SET_PROFILE_V1 ? V1_LAYOUT : classLayout(def.materialClass, 'procedural'),
    ),
    extent_mm: { u: def.extentU, v: def.extentV },
    licence_id: def.licenceId,
    licence_sha256: licenceSha256,
    container_profile: def.containerProfile,
    material_class: def.materialClass,
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
  const container = def.containerProfile === SET_PROFILE_V1
    ? encodeContainer(def, bakeMaps(def), licenceSha256)
    : encodeContainerV2(def, bakeClassMaps(def), licenceSha256);
  const entry = manifestEntry(def, container, licenceSha256);
  return {
    definition: def,
    container,
    entry,
    path: `${BLOB_DIRECTORY}/${entry.content_sha256}${SET_EXTENSION}`,
  };
}

export const objectPath = (digest: string): string =>
  `${OBJECT_DIRECTORY}/${digest}${OBJECT_EXTENSION}`;

export function publish(library: readonly LibrarySet[] = LIBRARY): Publication {
  const licence = licenceBytes();
  const licenceSha256 = sha256Hex(licence);
  const store = new ObjectStore();
  const makers = MAKERS.map((maker) => ({
    maker,
    row: {
      maker_id: maker.manifest.maker_id,
      version: maker.manifest.version,
      object_sha256: store.put(maker.manifest),
    },
  }));
  const sets = library.map((source): PublishedLibrarySet => {
    const published = publishSet(definitionOf(source), licenceSha256);
    const maker = makers.find((candidate) => candidate.maker === source.maker);
    if (maker === undefined) {
      throw new Error(`${source.entry.set_id} names a maker this package does not publish`);
    }
    const recipeSha256 = store.put(source.entry.recipe);
    const entrySha256 = store.put(libraryEntryObject(source.entry, recipeSha256));
    const receiptSha256 = store.put(
      bakeReceipt({
        pipeline: published.definition.containerProfile === SET_PROFILE_V1 ? BAKE_PIPELINE : BAKE_PIPELINE_V2,
        makerSha256: maker.row.object_sha256,
        entrySha256,
        recipeSha256,
        licenceSha256,
        contentSha256: published.entry.content_sha256,
        byteSize: published.entry.byte_size,
      }),
    );
    return {
      ...published,
      source,
      makerSha256: maker.row.object_sha256,
      recipeSha256,
      entrySha256,
      receiptSha256,
    };
  });
  const manifest = manifestBytes(sets.map((set) => set.entry));
  const catalog = canonicalBytes(
    catalogDocument(
      sha256Hex(manifest),
      makers.map(({ row }) => row),
      sets.map((set) => ({
        set_id: set.entry.set_id,
        version: set.entry.version,
        content_sha256: set.entry.content_sha256,
        receipt_sha256: set.receiptSha256,
      })),
    ),
  );
  const objects = store.entries();
  const licencePath = `${BLOB_DIRECTORY}/${licenceSha256}${LICENCE_EXTENSION}`;
  // Content first and indexes last, in the order the CLI writes them.
  const files = new Map<string, Uint8Array>();
  files.set(ATTRIBUTES_FILE, new TextEncoder().encode(ATTRIBUTES_TEXT));
  files.set(licencePath, licence);
  for (const set of sets) files.set(set.path, set.container);
  for (const [digest, bytes] of objects) files.set(objectPath(digest), bytes);
  files.set(MANIFEST_FILE, manifest);
  files.set(CATALOG_FILE, catalog);
  return {
    sets,
    licence: { bytes: licence, sha256: licenceSha256, path: licencePath },
    manifest,
    catalog,
    objects,
    files,
  };
}
