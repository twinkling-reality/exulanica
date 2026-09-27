// No page builds words from a server code by replacing its underscores. A code's words come from a
// table keyed by the codes the server states, held to them by a parity test, or from a catalog the
// server reads too; a code the page has no words for is named as such rather than respelled.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

/** The repository, from the web workspace vitest runs in, as the other page tests read it. */
const WEB = process.cwd();

/** The spelling this test keeps out: a string's underscores replaced by spaces. */
const RESPELLED = /\.replace(?:All)?\(\s*(?:\/_\/g|'_'|"_")\s*,\s*(?:' '|" ")\s*\)/;

/**
 * Sites held elsewhere, each with its reason. This list may only shrink.
 *   - society-comparison.ts: the Compare view's words for a person's reason codes belong with the
 *     comparison record's own vocabulary, a change of its own.
 *   - environment-selection.ts: the v4 living inspector's role and action reasons belong to the
 *     district stack, which states no one set of those codes to hold a table to.
 *   - character-studio.ts: a look's colour slots are the material names of its character asset,
 *     which states no label for any of them; labelling them is a change to those assets.
 */
const HELD_ELSEWHERE: ReadonlyMap<string, number> = new Map([
  ['packages/app/src/composition/environment-selection.ts', 2],
  ['packages/app/src/ui/character-studio.ts', 2],
  ['packages/app/src/ui/society-comparison.ts', 1],
]);

function sources(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (name === 'node_modules' || name === 'dist') return [];
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

/** Each source file's count of lines that respell a code. */
function respelled(files: readonly string[]): Map<string, number> {
  const found = new Map<string, number>();
  for (const file of files) {
    const count = readFileSync(file, 'utf8').split('\n').filter((line) => RESPELLED.test(line)).length;
    if (count > 0) found.set(relative(WEB, file), count);
  }
  return found;
}

describe('words built from codes', () => {
  it('are built nowhere on the page but the sites held elsewhere', () => {
    const packages = readdirSync(join(WEB, 'packages')).map((name) => join(WEB, 'packages', name, 'src'));
    const files = packages.filter((path) => {
      try { return statSync(path).isDirectory(); } catch { return false; }
    }).flatMap(sources);
    // A positive control: the scan reads the page's own sources.
    expect(files.some((file) => file.endsWith('ui/detail.ts'))).toBe(true);
    expect(respelled(files)).toEqual(HELD_ELSEWHERE);
  });

  it('finds a respelled code wherever one is written', () => {
    expect(RESPELLED.test("text: status.replace(/_/g, ' '),")).toBe(true);
    expect(RESPELLED.test("label: name.replaceAll('_', ' '),")).toBe(true);
    expect(RESPELLED.test("key.replaceAll('_', '-')")).toBe(false);
  });
});
