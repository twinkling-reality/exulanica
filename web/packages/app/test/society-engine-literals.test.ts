import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/*
 * The page asks the engine table what an engine can do and which engine a new society is created
 * with (`society-engines.ts`); it never names an engine where a capability or the table decides.
 * The only engine names in the app's source are the generated copy of the table and the readers
 * of the living society's own documents, each listed here with its count and why. A new name
 * anywhere fails, and so does a count that falls: lower it here, so the list only shrinks.
 */

const SOURCE = fileURLToPath(new URL('../src/', import.meta.url));
const ENGINE_NAME = /['"`]exulanica-society\/v\d+/g;

/** Files that may name an engine, how many times, and why each is not a capability. */
const NAMED: Readonly<Record<string, readonly [number, string]>> = {
  'society-api.ts': [1, 'the living state reader types the state it parses as the living engine\'s'],
  'society-preview-presentation.ts': [
    2,
    'the development preview parses a recording the living engine made, and says so of its state',
  ],
};

function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sources(path);
    return entry.name.endsWith('.ts') && !entry.name.endsWith('.generated.ts') ? [path] : [];
  });
}

export function engineNames(directory: string): Record<string, number> {
  const found: Record<string, number> = {};
  for (const path of sources(directory)) {
    const count = readFileSync(path, 'utf8').match(ENGINE_NAME)?.length ?? 0;
    if (count > 0) found[relative(directory, path)] = count;
  }
  return found;
}

describe('engine names in the page', () => {
  it('appear only where the living engine reads its own documents', () => {
    expect(engineNames(SOURCE)).toEqual(Object.fromEntries(Object.entries(NAMED).map(([file, [count]]) => [file, count])));
  });

  it('are found in every quote style, in nested files, and never in the generated table', () => {
    // The positive control: a planted tree, so an empty result for a real file means it names none.
    const planted = mkdtempSync(join(tmpdir(), 'engine-names-'));
    try {
      mkdirSync(join(planted, 'ui'));
      writeFileSync(join(planted, 'ui', 'asks.ts'),
        "const a = 'exulanica-society/v2'; const b = \"exulanica-society/v3\"; const c = `exulanica-society/v4`;");
      writeFileSync(join(planted, 'table.generated.ts'), "const t = 'exulanica-society/v2';");
      writeFileSync(join(planted, 'clean.ts'), 'const nothing = 1;');
      expect(engineNames(planted)).toEqual({ [join('ui', 'asks.ts')]: 3 });
    } finally {
      rmSync(planted, { recursive: true, force: true });
    }
  });

  it('are each listed with a reason', () => {
    for (const [file, [count, why]] of Object.entries(NAMED)) {
      expect(count, file).toBeGreaterThan(0);
      expect(why.split(' ').length, file).toBeGreaterThanOrEqual(5);
    }
  });
});
