import { readdirSync } from 'node:fs';
import { join, relative } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';
import { canonicalJson } from '../src/canonical-json.js';
import { CATALOG } from '../src/catalog.js';
import { decodeContainer } from '../src/container.js';
import { LICENCE_TEXT } from '../src/licence.js';
import {
  ATTRIBUTES_FILE,
  ATTRIBUTES_TEXT,
  BLOB_DIRECTORY,
  MANIFEST_FILE,
  MANIFEST_PROFILE,
  type ManifestEntry,
  type Publication,
  SET_ID_PATTERN,
  publish,
  sha256Hex,
} from '../src/publish.js';
import { PUBLISHED, readPublished } from './support.js';

/**
 * The committed `assets/textures/` is exactly what the source bakes.
 *
 * This is the claim a migration relies on when it names these digests: the bytes are reproducible
 * from this package on any machine, so a digest is a statement about source, not about a file
 * somebody once uploaded. The whole catalog is rebaked here and compared byte for byte with the
 * committed files. A recipe edit that forgot `pnpm texture` fails here; a rebake that changed
 * bytes without bumping a version fails in `tests/test_texture_set_migration.py`, against the pins.
 */
let publication: Publication;
let manifest: { profile: string; sets: ManifestEntry[] };

beforeAll(() => {
  manifest = JSON.parse(new TextDecoder().decode(readPublished(MANIFEST_FILE))) as typeof manifest;
  publication = publish(CATALOG);
}, 180_000);

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
