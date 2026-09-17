import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DRAFT_MAKER_DIRECTORY, draftMakerFiles } from './draft-makers.js';

/**
 * Write the draft makers' manifests beside this file. The directory is replaced whole, so a maker
 * that has been published, or dropped, leaves no file behind.
 *
 * From `web/`: node_modules/.bin/tsx packages/loom-texture/test/write-draft-makers.ts
 */
const HERE = dirname(fileURLToPath(import.meta.url));

rmSync(join(HERE, DRAFT_MAKER_DIRECTORY), { recursive: true, force: true });
const files = draftMakerFiles();
for (const [path, bytes] of files) {
  mkdirSync(dirname(join(HERE, path)), { recursive: true });
  writeFileSync(join(HERE, path), bytes);
}
process.stdout.write(`wrote ${files.size} draft maker manifests under ${DRAFT_MAKER_DIRECTORY}/\n`);
