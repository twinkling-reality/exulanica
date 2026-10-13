import { fileURLToPath } from 'node:url';

import { build } from 'vite';
import { describe, expect, it } from 'vitest';

/**
 * Assert the public bundle boundary against the production sourcemap. Static import rules
 * catch direct dependency violations; this also catches world code arriving transitively.
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
    'keeps the public page free of application rendering and world style code',
    async () => {
      const sources = await bundledSources();

      /*
       * Before asserting anything is absent, prove the build produced a bundle and the sourcemap
       * was read. An empty list satisfies every absence check in this file and would mean nothing.
       */
      expect(sources.length).toBeGreaterThan(0);
      expect(sources.some((s) => s.endsWith('/src/main.ts'))).toBe(true);

      expect(sources.filter((source) => /atlas-react|playcanvas|three\//.test(source))).toEqual([]);

      expect(sources.filter((s) => /world-style|world-profiles/.test(s))).toEqual([]);
    },
    /*
     * This runs a real production build. It took well under a second on its own, and the number
     * below is for a machine already running a full suite beside it rather than for the build.
     */
    60_000,
  );
});
