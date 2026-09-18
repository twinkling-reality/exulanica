/**
 * A MODULE THAT SAYS NOTHING CALLS IT YET IS HELD TO THAT BY THE IMPORT GRAPH.
 *
 * Five modules in `src/core` carried the sentence "Not yet wired into a bake. It changes no
 * container until an expander calls it." On 2026-09-18 FOUR OF THE FIVE WERE FALSE, and one of them
 * was `ring-clearance.ts`, which had carved every navigation projection anybody had baked for weeks
 * and whose overshoot three people spent an afternoon measuring. `ring-triangulation.ts` was
 * imported by eight modules including the tessellator itself.
 *
 * None of the four was written carelessly. Each was TRUE WHEN WRITTEN and became false when
 * somebody else wired the module up, which is rot that nobody performs and nobody notices, because
 * the sentence is in a file the wiring did not touch.
 *
 * SO THE CLAIM IS NOW CHECKED RATHER THAN BANNED. A module may still say it is unwired, because
 * that is a useful thing for a reader to know, and this fails if anything in `src/core` imports it.
 * The claim stops being prose and becomes a statement the tree can contradict.
 *
 * WHAT THIS CANNOT SEE, and it is the same shape as every enumerating check: it matches ONE form of
 * words. A module that says "nothing calls this yet" in different words escapes it. The better
 * answer, where a reader does not need the fact, is not to make the claim at all, which is what the
 * four corrected modules now do: whether a module is called is a fact about its callers, and a
 * module is the wrong place to keep one.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { PACKAGE_ROOT } from './support.js';

const CORE = join(PACKAGE_ROOT, 'src', 'core');
const UNWIRED = 'Not yet wired into a bake';

const coreFiles = (): string[] => readdirSync(CORE).filter((name) => name.endsWith('.ts')).sort();

/** Which core modules each core module imports, by file name, from the import lines themselves. */
function importsOf(text: string): string[] {
  const found: string[] = [];
  for (const line of text.split('\n')) {
    const match = /from '\.\/([a-z0-9-]+)\.js'/.exec(line);
    if (match !== null) found.push(`${match[1]!}.ts`);
  }
  return found;
}

describe('a core module that says nothing calls it yet', () => {
  it('is imported by nothing in core, or it is saying something the tree contradicts', () => {
    const files = coreFiles();
    const importers = new Map<string, string[]>();
    for (const name of files) {
      for (const imported of importsOf(readFileSync(join(CORE, name), 'utf8'))) {
        const list = importers.get(imported);
        if (list === undefined) importers.set(imported, [name]); else if (!list.includes(name)) list.push(name);
      }
    }
    // The graph must have found something, or this test is comparing two empty sets: core's own
    // modules do import each other, and `index.ts` reaches most of them.
    expect(importers.size).toBeGreaterThan(0);
    const wrong: string[] = [];
    for (const name of files) {
      if (!readFileSync(join(CORE, name), 'utf8').includes(UNWIRED)) continue;
      const by = importers.get(name) ?? [];
      if (by.length > 0) wrong.push(`${name} says it is unwired and is imported by ${by.join(', ')}`);
    }
    expect(wrong).toEqual([]);
  });

  it('is a claim this test can actually catch, shown against a module that is wired', () => {
    // A positive control. `integer-math.ts` is imported all over core, so planting the sentence in
    // a copy of its text must be caught; a silence from the test above means nothing otherwise.
    const wired = readFileSync(join(CORE, 'integer-math.ts'), 'utf8');
    expect(wired.includes(UNWIRED)).toBe(false);
    const planted = `/**\n * ${UNWIRED}.\n */\n${wired}`;
    expect(planted.includes(UNWIRED)).toBe(true);
    const importers = coreFiles().filter((name) => importsOf(readFileSync(join(CORE, name), 'utf8')).includes('integer-math.ts'));
    expect(importers.length).toBeGreaterThan(0);
  });
});
