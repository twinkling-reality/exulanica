import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, resolve } from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';
import { previewCrowdSize } from '../src/composition/character.js';

// Relative to web/, where the suite runs.
const APP = resolve('packages/app');
const VITE = join(APP, 'node_modules/vite/bin/vite.js');
const CHARACTERS = resolve('../assets/characters');
/** What only the development character source carries. */
const MARKER = 'No committed character container has digest';
/** The first bytes of a committed body container: its header and the start of its glTF JSON. */
const BODY_PREFIX = readFileSync(join(CHARACTERS, 'makehuman-people-v1/bases/feminine.glb')).subarray(0, 96);
const scratch: string[] = [];
afterAll(() => {
  for (const directory of scratch) rmSync(directory, { recursive: true, force: true });
});

function files(root: string): string[] {
  return readdirSync(root).flatMap((name) => {
    const path = join(root, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

function buildApp(mode: 'production' | 'development') {
  const outDir = mkdtempSync(join(tmpdir(), `exulanica-characters-${mode}-`));
  scratch.push(outDir);
  execFileSync(process.execPath, [VITE, 'build', '--mode', mode, '--outDir', outDir, '--emptyOutDir', '--logLevel', 'error'], {
    cwd: APP,
    env: { ...process.env, NODE_ENV: mode },
    stdio: 'pipe',
  });
  const emitted = files(outDir);
  return {
    names: emitted.map((path) => relative(outDir, path)),
    text: emitted.filter((path) => /\.(?:js|html|css|json)$/.test(path)).map((path) => readFileSync(path, 'utf8')).join('\n'),
    holdsBodyBytes: emitted.some((path) => readFileSync(path).includes(BODY_PREFIX)),
  };
}

describe('development character sources: who may ask', () => {
  it('mount the crowd evaluation only on the development preview, for a sane count', () => {
    expect(previewCrowdSize('?preview=1&crowd=24', true)).toBe(24);
    expect(previewCrowdSize('?preview=1&crowd=24', false)).toBe(0);
    for (const refused of ['0', '129', '-3', '2.5', '1e2', 'many', '', '012']) {
      expect(previewCrowdSize(`?preview=1&crowd=${refused}`, true), refused).toBe(0);
    }
  });
});

describe('character containers: never bundled into a production build', () => {
  it('emits no container, no container bytes and no development source in production', () => {
    const production = buildApp('production');
    expect(production.names.some((name) => name.endsWith('index.html'))).toBe(true);
    expect(production.names.filter((name) => name.endsWith('.glb'))).toEqual([]);
    expect(production.holdsBodyBytes).toBe(false);
    expect(production.text.includes(MARKER)).toBe(false);
  }, 180_000);

  it('would carry them if the development branch were reachable (the control)', () => {
    const development = buildApp('development');
    expect(development.names.filter((name) => name.endsWith('.glb')).length).toBeGreaterThan(90);
    expect(development.holdsBodyBytes).toBe(true);
    expect(development.text.includes(MARKER)).toBe(true);
  }, 180_000);
});
