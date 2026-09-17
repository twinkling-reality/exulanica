import { mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { FIXTURE_DIRECTORY, conformanceFiles } from './conformance.js';

/**
 * Write the conformance fixtures and `texture-set-cases.json` beside this file. The fixture directory
 * is replaced whole, so a case that no longer exists leaves no file behind.
 *
 * From `web/`: node_modules/.bin/tsx packages/loom-texture/test/write-conformance.ts
 */
const HERE = dirname(fileURLToPath(import.meta.url));

rmSync(join(HERE, FIXTURE_DIRECTORY), { recursive: true, force: true });
const files = conformanceFiles();
for (const [path, bytes] of files) {
  mkdirSync(dirname(join(HERE, path)), { recursive: true });
  writeFileSync(join(HERE, path), bytes);
}
const written = readdirSync(join(HERE, FIXTURE_DIRECTORY), { recursive: true }).length;
process.stdout.write(`wrote ${files.size} files (${written} entries under ${FIXTURE_DIRECTORY}/)\n`);
