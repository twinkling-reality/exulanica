import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { DRAFTS } from '../src/catalog.js';
import { DRAFT_MAKER_DIRECTORY, draftMakerFiles } from './draft-makers.js';

/**
 * The committed draft maker manifests are exactly what `draft-makers.ts` generates, so the backend's
 * test reads the manifests the package's makers really have. See `draft-makers.ts` for why they exist.
 */
const HERE = fileURLToPath(new URL('.', import.meta.url));

describe('the committed draft maker manifests', () => {
  it('are exactly what draft-makers.ts generates, and nothing else', () => {
    const generated = draftMakerFiles();
    for (const [path, bytes] of generated) {
      expect(Buffer.from(readFileSync(join(HERE, path))).equals(Buffer.from(bytes)), path).toBe(true);
    }
    const directory = join(HERE, DRAFT_MAKER_DIRECTORY);
    const committed = existsSync(directory)
      ? readdirSync(directory).map((name) => `${DRAFT_MAKER_DIRECTORY}/${name}`).sort()
      : [];
    expect(committed).toEqual([...generated.keys()].sort());
  });

  it('include the maker of every draft set', () => {
    const generated = draftMakerFiles();
    for (const { entry } of DRAFTS) {
      const { id, version } = entry.recipe.maker;
      expect(generated.has(`${DRAFT_MAKER_DIRECTORY}/${id}.v${version}.json`), entry.set_id).toBe(true);
    }
  });
});
