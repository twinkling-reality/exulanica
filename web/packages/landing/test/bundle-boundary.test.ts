import { fileURLToPath } from 'node:url';

import { build } from 'vite';
import { describe, expect, it } from 'vitest';

/**
 * What the public page's bundle is allowed to contain.
 *
 * The signed-out surface draws one small Companion avatar in the corner, and for months it paid for
 * the entire world style vocabulary to do it. `index.ts` re-exports `world-profiles.js`, which
 * constructs the world style registry at module scope, and a module-scope constructor call cannot
 * be dropped as unused: one named import from the barrel shipped the registry and the five modules
 * behind it, 25,600 of 55,898 attributed bytes executing on every cold load. Importing
 * `@exulanica/presentation/companion` instead halved the bundle.
 *
 * Nothing about that fix is self-enforcing. Anyone adding a second Companion symbol would reach for
 * the barrel, the import would look identical to the one it replaced, and the 25 kB would come back
 * with no test failing and nothing visible on the page. So the property is asserted here against
 * the build's own sourcemap rather than left as a thing to remember.
 *
 * `web/.dependency-cruiser.cjs` refuses the barrel import statically, which is the faster failure.
 * This is the slower one that does not care how the module arrived.
 */
const ROOT = fileURLToPath(new URL('..', import.meta.url));

async function bundledSources(): Promise<readonly string[]> {
  const result = await build({
    root: ROOT,
    logLevel: 'silent',
    build: { write: false, sourcemap: true, target: 'es2022' },
  });
  const outputs = Array.isArray(result) ? result : [result];
  const sources: string[] = [];
  for (const bundle of outputs) {
    if (!('output' in bundle)) continue;
    for (const chunk of bundle.output) {
      if (chunk.type === 'chunk' && chunk.map) sources.push(...chunk.map.sources);
    }
  }
  return sources;
}

describe("the signed-out page's bundle", () => {
  it(
    'draws the Companion without carrying the world style vocabulary',
    async () => {
      const sources = await bundledSources();

      /*
       * Before asserting anything is absent, prove the build produced a bundle and the sourcemap
       * was read. An empty list satisfies every absence check in this file and would mean nothing.
       */
      expect(sources.length).toBeGreaterThan(0);
      expect(sources.some((s) => s.endsWith('/src/main.ts'))).toBe(true);

      /*
       * And prove the presentation package really is in there, so the absence below is a statement
       * about which of its modules arrive rather than about whether any of them do.
       */
      const presentation = sources.filter((s) => s.includes('/presentation/src/'));
      expect(presentation.map((s) => s.split('/presentation/src/')[1]).sort()).toEqual([
        'companion-appearance.ts',
        'companion-avatar-blueprint.ts',
      ]);

      expect(sources.filter((s) => /world-style|world-profiles/.test(s))).toEqual([]);
    },
    /*
     * This runs a real production build. It took well under a second on its own, and the number
     * below is for a machine already running a full suite beside it rather than for the build.
     */
    60_000,
  );
});
