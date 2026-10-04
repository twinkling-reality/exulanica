import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The interface typefaces ship unmodified under a Reserved Font Name: every file in the folder is
 * recorded in SOURCE.json and named in THIRD_PARTY_NOTICES.md with its size and digest, and
 * OFL.txt declares exactly the reserved name. The expected values come from those records, not
 * from the files.
 */
const HERE = dirname(fileURLToPath(import.meta.url));
const FOLDER = join(HERE, '../src/fonts/ibm-plex');
const ROOT = join(HERE, '../../../..');
const REPO_PATH = 'web/packages/presentation/src/fonts/ibm-plex';

interface SourceFile { readonly path: string; readonly sha256: string; readonly bytes: number }
const source = JSON.parse(readFileSync(join(FOLDER, 'SOURCE.json'), 'utf8')) as {
  readonly licence: string; readonly files: readonly SourceFile[];
};
const notices = readFileSync(join(ROOT, 'THIRD_PARTY_NOTICES.md'), 'utf8');
const digest = (name: string) => createHash('sha256').update(readFileSync(join(FOLDER, name))).digest('hex');

describe('the interface typefaces', () => {
  it('records every file in the folder, at its size and digest', () => {
    const present = readdirSync(FOLDER).filter((name) => name !== 'SOURCE.json').sort();
    expect(source.files.map((file) => file.path).sort()).toEqual(present);
    for (const file of source.files) {
      expect(readFileSync(join(FOLDER, file.path)).length, file.path).toBe(file.bytes);
      expect(digest(file.path), file.path).toBe(file.sha256);
    }
  });

  it('names each file in the notices with the same size and digest', () => {
    for (const file of source.files) {
      const row = `| \`${REPO_PATH}/${file.path}\` | ${file.bytes.toLocaleString('en-US')} | \`${file.sha256}\` |`;
      expect(notices, file.path).toContain(row);
    }
  });

  it('declares exactly the reserved name the records state', () => {
    const first = readFileSync(join(FOLDER, 'OFL.txt'), 'utf8').split('\n')[0] ?? '';
    expect(first).toBe('Copyright © 2017 IBM Corp. with Reserved Font Name "Plex"');
    expect(source.licence).toBe('SIL Open Font License 1.1, Reserved Font Name "Plex"');
  });
});
