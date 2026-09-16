import { lstatSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { canonicalBytes } from '../canonical-json.js';
import { sha256Hex } from '../digest.js';
import { packageRoot } from '../library.js';

/**
 * What this package's source was when it baked, as one digest a bake receipt can carry.
 *
 * The object is every file the bake can read, by path and sha256: `package.json`, `src/`,
 * `library/` and `licences/`, recursively, in path order, dot files left out (they are editor and
 * checkout state, not code). A link is refused rather than followed, so the digest names the files
 * that are there. The backend's bake worker computes the same object from the same directory
 * (`exulanica/world/material_bakes.py`) and refuses a bake whose claim differs, so a receipt names
 * code that was on disk when the bytes were made.
 */
export const SOURCE_PROFILE = 'exulanica.loom-texture-source/v1';
export const SOURCE_ROOTS = ['package.json', 'src', 'library', 'licences'] as const;

export interface SourceFile {
  readonly path: string;
  readonly sha256: string;
}

function walk(root: string, relative: string, into: SourceFile[]): void {
  const absolute = join(root, ...relative.split('/'));
  const stat = lstatSync(absolute);
  if (stat.isSymbolicLink()) throw new Error(`${relative} is a link; the source digest follows none`);
  if (stat.isDirectory()) {
    for (const name of readdirSync(absolute)) {
      if (!name.startsWith('.')) walk(root, `${relative}/${name}`, into);
    }
    return;
  }
  if (!stat.isFile()) throw new Error(`${relative} is not a file`);
  into.push({ path: relative, sha256: sha256Hex(new Uint8Array(readFileSync(absolute))) });
}

export function sourceFiles(root: string = packageRoot()): readonly SourceFile[] {
  const files: SourceFile[] = [];
  for (const top of SOURCE_ROOTS) walk(root, top, files);
  // Code-point order, which for these ASCII paths is also Python's `sorted`.
  return files.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
}

export function packageSourceDigest(root: string = packageRoot()): string {
  return sha256Hex(canonicalBytes({ profile: SOURCE_PROFILE, files: sourceFiles(root) }));
}
