import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/*
 * The people catalog reaches the page from the host, by digest (`character/served.ts`). The
 * generated `catalog-data.ts` and `looks-data.ts` stay as fixtures for tests and for
 * `scripts/prepare_character_people.py --verify-only`; a production module importing either would
 * put a compiled catalog back in the bundle, so no source module outside them may.
 */
const PACKAGES = resolve('packages');
const COMPILED = /from\s+['"][^'"]*(?:catalog-data|looks-data)(?:\.js)?['"]/;

function sources(root: string): string[] {
  return readdirSync(root).flatMap((name) => {
    const path = join(root, name);
    if (name === 'node_modules' || name === 'dist') return [];
    return statSync(path).isDirectory() ? sources(path) : /\.tsx?$/.test(name) ? [path] : [];
  });
}

describe('the compiled character catalog', () => {
  it('is imported by no production module, only by tests', () => {
    const importers = ['atlas-react/src', 'app/src']
      .flatMap((dir) => sources(join(PACKAGES, dir)))
      .filter((path) => !/character\/(?:catalog|looks)-data\.ts$/.test(path))
      .filter((path) => COMPILED.test(readFileSync(path, 'utf8')))
      .map((path) => relative(PACKAGES, path));
    expect(importers).toEqual([]);
  });

  it('would be caught (the control): the fixture importers are found', () => {
    const tests = sources(join(PACKAGES, 'atlas-react/test')).filter((path) => COMPILED.test(readFileSync(path, 'utf8')));
    expect(tests.length).toBeGreaterThan(3);
  });
});
