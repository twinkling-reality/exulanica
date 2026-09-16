import { canonicalBytes } from './canonical-json.js';
import { sha256Hex } from './digest.js';
import type { LibraryEntry } from './library.js';

/**
 * The published objects, and the catalog that indexes them.
 *
 * `assets/textures/objects/` is a content-addressed object store. Each file is canonical JSON,
 * named for the sha256 of its bytes, and says what it is in its `profile`:
 *
 *   - `exulanica.texture-maker/v1`: a maker's manifest, its controls and constraints.
 *   - `exulanica.texture-recipe/v1`: a recipe, every control stated.
 *   - `exulanica.texture-library-entry/v1`: a recipe published as a named, versioned set.
 *   - `exulanica.texture-bake-receipt/v1`: one bake. Which maker, entry, recipe and licence went
 *     in, under which bake pipeline, and which container came out, by digest and length.
 *
 * Objects refer to each other by digest, never by path or by name, so an object can be copied into
 * any content-addressed store and its references still resolve there. `catalog.json` is the index:
 * the digest of the manifest it accounts for, every maker this package has, and one row per set
 * naming the receipt that accounts for its bytes. `manifest.json` stays exactly as the grammar lane
 * agreed it; the catalog sits beside it rather than changing it.
 *
 * Nothing here is evidence and nothing here was observed. A receipt records that source produced
 * bytes, which the published test proves again on every run by rebaking and comparing.
 */
export const LIBRARY_ENTRY_PROFILE = 'exulanica.texture-library-entry/v1';
export const BAKE_RECEIPT_PROFILE = 'exulanica.texture-bake-receipt/v1';
export const CATALOG_PROFILE = 'exulanica.texture-catalog/v1';
/**
 * The bake itself: sampling, the normal and cavity derivations, quantisation and the container.
 * Any change there that alters a byte for any valid recipe is a new pipeline, and a new version of
 * every set.
 */
export const BAKE_PIPELINE = 'exulanica.texture-bake/v1';
export const OBJECT_DIRECTORY = 'objects';
export const OBJECT_EXTENSION = '.json';
export const CATALOG_FILE = 'catalog.json';

export interface LibraryEntryObject {
  readonly profile: typeof LIBRARY_ENTRY_PROFILE;
  readonly set_id: string;
  readonly version: number;
  readonly title: string;
  readonly summary: string;
  readonly licence_id: string;
  readonly recipe_sha256: string;
}

export interface BakeReceipt {
  readonly profile: typeof BAKE_RECEIPT_PROFILE;
  readonly pipeline: typeof BAKE_PIPELINE;
  readonly maker_sha256: string;
  readonly entry_sha256: string;
  readonly recipe_sha256: string;
  readonly licence_sha256: string;
  readonly content_sha256: string;
  readonly byte_size: number;
}

export interface CatalogMaker {
  readonly maker_id: string;
  readonly version: number;
  readonly object_sha256: string;
}

export interface CatalogSet {
  readonly set_id: string;
  readonly version: number;
  readonly content_sha256: string;
  readonly receipt_sha256: string;
}

export interface CatalogDocument {
  readonly profile: typeof CATALOG_PROFILE;
  readonly manifest_sha256: string;
  readonly makers: readonly CatalogMaker[];
  readonly sets: readonly CatalogSet[];
}

export function libraryEntryObject(entry: LibraryEntry, recipeSha256: string): LibraryEntryObject {
  return {
    profile: LIBRARY_ENTRY_PROFILE,
    set_id: entry.set_id,
    version: entry.version,
    title: entry.title,
    summary: entry.summary,
    licence_id: entry.licence_id,
    recipe_sha256: recipeSha256,
  };
}

export function bakeReceipt(inputs: {
  readonly makerSha256: string;
  readonly entrySha256: string;
  readonly recipeSha256: string;
  readonly licenceSha256: string;
  readonly contentSha256: string;
  readonly byteSize: number;
}): BakeReceipt {
  return {
    profile: BAKE_RECEIPT_PROFILE,
    pipeline: BAKE_PIPELINE,
    maker_sha256: inputs.makerSha256,
    entry_sha256: inputs.entrySha256,
    recipe_sha256: inputs.recipeSha256,
    licence_sha256: inputs.licenceSha256,
    content_sha256: inputs.contentSha256,
    byte_size: inputs.byteSize,
  };
}

const byText = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

/** The catalog, with makers sorted by id then version and sets by id, each id once. */
export function catalogDocument(
  manifestSha256: string,
  makers: readonly CatalogMaker[],
  sets: readonly CatalogSet[],
): CatalogDocument {
  const sortedMakers = [...makers].sort(
    (a, b) => byText(a.maker_id, b.maker_id) || a.version - b.version,
  );
  const sortedSets = [...sets].sort((a, b) => byText(a.set_id, b.set_id));
  sortedSets.forEach((set, index) => {
    if (index > 0 && sortedSets[index - 1]!.set_id === set.set_id) {
      throw new Error(`set ${set.set_id} is catalogued twice`);
    }
  });
  return {
    profile: CATALOG_PROFILE,
    manifest_sha256: manifestSha256,
    makers: sortedMakers,
    sets: sortedSets,
  };
}

/**
 * Objects by digest. Putting the same object twice is one object; putting different bytes under
 * one digest cannot happen short of a sha256 collision, and is refused if it does.
 */
export class ObjectStore {
  readonly #objects = new Map<string, Uint8Array>();

  put(value: object): string {
    const bytes = canonicalBytes(value);
    const digest = sha256Hex(bytes);
    const held = this.#objects.get(digest);
    if (held !== undefined && !Buffer.from(held).equals(Buffer.from(bytes))) {
      throw new Error(`two different objects hash to ${digest}`);
    }
    this.#objects.set(digest, bytes);
    return digest;
  }

  /** Every object, sorted by digest. */
  entries(): ReadonlyMap<string, Uint8Array> {
    return new Map([...this.#objects].sort(([a], [b]) => byText(a, b)));
  }
}
