import { readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';
import { canonicalJson } from '../src/canonical-json.js';
import { LIBRARY } from '../src/catalog.js';
import { decodeContainer } from '../src/container.js';
import { LIBRARY_FOLDER, formatLibrarySource, packageRoot } from '../src/library.js';
import { LICENCE_TEXT } from '../src/licence.js';
import { MAKERS } from '../src/makers/index.js';
import {
  BAKE_PIPELINE,
  BAKE_RECEIPT_PROFILE,
  type BakeReceipt,
  CATALOG_FILE,
  CATALOG_PROFILE,
  type CatalogDocument,
  LIBRARY_ENTRY_PROFILE,
  type LibraryEntryObject,
} from '../src/objects.js';
import {
  ATTRIBUTES_FILE,
  ATTRIBUTES_TEXT,
  BLOB_DIRECTORY,
  MANIFEST_FILE,
  MANIFEST_PROFILE,
  type ManifestEntry,
  type Publication,
  SET_ID_PATTERN,
  objectPath,
  publish,
  sha256Hex,
} from '../src/publish.js';
import { type MakerManifest, type Recipe, manifestProblems, recipeProblems } from '../src/recipe.js';
import { PUBLISHED, readPublished } from './support.js';

/**
 * The committed `assets/textures/` is exactly what the source bakes.
 *
 * This is the claim a migration relies on when it names these digests: the bytes are reproducible
 * from this package on any machine, so a digest is a statement about source, not about a file
 * somebody once uploaded. The whole library is rebaked here and compared byte for byte with the
 * committed files, objects and indexes included. A library edit that forgot `pnpm texture` fails
 * here; a rebake that changed bytes without bumping a version fails in
 * `tests/test_texture_set_migration.py`, against the pins.
 */
let publication: Publication;
let manifest: { profile: string; sets: ManifestEntry[] };

beforeAll(() => {
  manifest = JSON.parse(new TextDecoder().decode(readPublished(MANIFEST_FILE))) as typeof manifest;
  publication = publish(LIBRARY);
}, 180_000);

/** A committed object, read back and held to its name: canonical bytes that hash to it. */
function readObject<T>(digest: string): T {
  const bytes = readPublished(objectPath(digest));
  expect(sha256Hex(bytes), digest).toBe(digest);
  const value = JSON.parse(new TextDecoder().decode(bytes)) as T;
  expect(canonicalJson(value as object), digest).toBe(new TextDecoder().decode(bytes));
  return value;
}

describe('the published directory', () => {
  it('holds exactly the files the source bakes, byte for byte', () => {
    const committed = readdirSync(PUBLISHED, { recursive: true, withFileTypes: true })
      .filter((entry) => entry.isFile())
      .map((entry) => relative(PUBLISHED, join(entry.parentPath, entry.name)).split('\\').join('/'))
      .sort();
    expect(committed).toEqual([...publication.files.keys()].sort());
    const differing = [...publication.files].filter(
      ([path, bytes]) => !Buffer.from(readPublished(path)).equals(Buffer.from(bytes)),
    );
    expect(differing.map(([path]) => path)).toEqual([]);
  }, 180_000);

  it('has a manifest in the agreed shape', () => {
    const bytes = readPublished(MANIFEST_FILE);
    // Canonical bytes: sorted keys, no whitespace, no trailing newline.
    expect(new TextDecoder().decode(bytes)).toBe(canonicalJson(manifest));
    expect(Object.keys(manifest).sort()).toEqual(['profile', 'sets']);
    expect(manifest.profile).toBe(MANIFEST_PROFILE);
    const ids = manifest.sets.map((entry) => entry.set_id);
    expect(ids).toEqual([...ids].sort());
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.length).toBeGreaterThanOrEqual(6);
    expect(ids.length).toBeLessThanOrEqual(10);
    for (const entry of manifest.sets) {
      expect(Object.keys(entry).sort()).toEqual([
        'byte_size',
        'channels',
        'content_sha256',
        'extent_mm',
        'licence_id',
        'licence_sha256',
        'resolution',
        'set_id',
        'version',
      ]);
      expect(entry.set_id).toMatch(SET_ID_PATTERN);
      expect(Number.isSafeInteger(entry.version) && entry.version >= 1).toBe(true);
      expect(entry.content_sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(entry.licence_sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(entry.licence_id).toBe('CC0-1.0');
    }
  });

  it('pins each blob by its own digest and describes it as its header does', () => {
    for (const entry of manifest.sets) {
      const bytes = readPublished(`${BLOB_DIRECTORY}/${entry.content_sha256}.ltex`);
      expect(sha256Hex(bytes), entry.set_id).toBe(entry.content_sha256);
      expect(bytes.length).toBe(entry.byte_size);
      const { header } = decodeContainer(bytes);
      expect(header.set_id).toBe(entry.set_id);
      expect(header.version).toBe(entry.version);
      expect(header.resolution).toEqual(entry.resolution);
      expect(header.extent_mm).toEqual(entry.extent_mm);
      expect(header.licence).toEqual({ id: entry.licence_id, sha256: entry.licence_sha256 });
      expect(
        header.maps.map((m) => ({ map: m.name, components: m.components, holds: m.holds, srgb: m.srgb })),
      ).toEqual(entry.channels);
    }
  });

  it('keeps every checkout from converting the pinned bytes', () => {
    expect(new TextDecoder().decode(readPublished(ATTRIBUTES_FILE))).toBe(ATTRIBUTES_TEXT);
    expect(ATTRIBUTES_TEXT).toMatch(/^\* -text -ident -filter -working-tree-encoding$/m);
    expect(ATTRIBUTES_TEXT).toMatch(/^blobs\/\*\* binary$/m);
  });

  it('stores the licence text every set names', () => {
    const [digest] = new Set(manifest.sets.map((entry) => entry.licence_sha256));
    const bytes = readPublished(`${BLOB_DIRECTORY}/${digest}.txt`);
    expect(sha256Hex(bytes)).toBe(digest);
    expect(new TextDecoder().decode(bytes)).toBe(LICENCE_TEXT);
    expect(LICENCE_TEXT).toContain('CC0 1.0 Universal');
  });
});

describe('the catalog accounts for every set', () => {
  let catalog: CatalogDocument;

  beforeAll(() => {
    const bytes = readPublished(CATALOG_FILE);
    catalog = JSON.parse(new TextDecoder().decode(bytes)) as CatalogDocument;
    expect(new TextDecoder().decode(bytes)).toBe(canonicalJson(catalog));
  });

  it('names the manifest it describes and every maker this package has', () => {
    expect(Object.keys(catalog).sort()).toEqual(['makers', 'manifest_sha256', 'profile', 'sets']);
    expect(catalog.profile).toBe(CATALOG_PROFILE);
    expect(catalog.manifest_sha256).toBe(sha256Hex(readPublished(MANIFEST_FILE)));
    expect(catalog.makers.map((row) => `${row.maker_id}@${row.version}`)).toEqual(
      MAKERS.map((maker) => `${maker.manifest.maker_id}@${maker.manifest.version}`),
    );
    for (const row of catalog.makers) {
      const manifest = readObject<MakerManifest>(row.object_sha256);
      expect(manifestProblems(manifest), row.maker_id).toEqual([]);
      expect([manifest.maker_id, manifest.version]).toEqual([row.maker_id, row.version]);
    }
  });

  it('has one row per manifest set, and each receipt names that set\'s bytes', () => {
    expect(catalog.sets.map((row) => [row.set_id, row.version, row.content_sha256])).toEqual(
      manifest.sets.map((entry) => [entry.set_id, entry.version, entry.content_sha256]),
    );
    const makers = new Map(catalog.makers.map((row) => [row.object_sha256, row]));
    for (const row of catalog.sets) {
      expect(Object.keys(row).sort()).toEqual(['content_sha256', 'receipt_sha256', 'set_id', 'version']);
      const listed = manifest.sets.find((entry) => entry.set_id === row.set_id)!;
      const receipt = readObject<BakeReceipt>(row.receipt_sha256);
      expect(receipt).toEqual({
        profile: BAKE_RECEIPT_PROFILE,
        pipeline: BAKE_PIPELINE,
        maker_sha256: receipt.maker_sha256,
        entry_sha256: receipt.entry_sha256,
        recipe_sha256: receipt.recipe_sha256,
        licence_sha256: listed.licence_sha256,
        content_sha256: listed.content_sha256,
        byte_size: listed.byte_size,
      });
      const entry = readObject<LibraryEntryObject>(receipt.entry_sha256);
      const recipe = readObject<Recipe>(receipt.recipe_sha256);
      const maker = readObject<MakerManifest>(receipt.maker_sha256);
      expect(makers.get(receipt.maker_sha256)?.maker_id, row.set_id).toBe(recipe.maker.id);
      expect(entry.profile).toBe(LIBRARY_ENTRY_PROFILE);
      expect(entry.recipe_sha256).toBe(receipt.recipe_sha256);
      expect([entry.set_id, entry.version, entry.licence_id]).toEqual([
        row.set_id,
        row.version,
        listed.licence_id,
      ]);
      expect(recipeProblems(recipe, maker), row.set_id).toEqual([]);
      // And the container says what its entry and recipe say.
      const { header } = decodeContainer(readPublished(`${BLOB_DIRECTORY}/${row.content_sha256}.ltex`));
      expect(header.title).toBe(entry.title);
      expect(header.summary).toBe(entry.summary);
      expect(header.seed).toBe(recipe.seed);
      expect(header.resolution).toEqual(recipe.resolution);
      expect(header.extent_mm).toEqual(recipe.extent_mm);
      expect(header.family).toBe(maker.family);
      expect(header.height_range_mm).toBe(recipe.parameters.height_range_mm);
    }
  });

  it('is built from library files kept in their one layout', () => {
    const folder = join(packageRoot(), LIBRARY_FOLDER);
    const names = readdirSync(folder).sort();
    expect(names).toEqual(LIBRARY.map((source) => `${source.entry.set_id}.json`));
    for (const name of names) {
      const text = readFileSync(join(folder, name), 'utf8');
      expect(formatLibrarySource(JSON.parse(text)), name).toBe(text);
    }
  });
});
