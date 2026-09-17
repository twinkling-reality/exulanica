/**
 * The type fence, demonstrated by compiling probes, not asserted.
 *
 * Each probe is compiled by `tsc` against a throwaway tsconfig that extends one of this package's
 * three real ones, so the `lib` and `types` settings under test are exactly the shipped ones. A
 * positive control per project proves the harness compiles clean code, so a failing probe fails
 * because of the fence and not because the harness is broken.
 */
import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { PACKAGE_ROOT, scratch } from './support.js';

const TSC = join(PACKAGE_ROOT, '..', '..', 'node_modules', 'typescript', 'bin', 'tsc');

interface Probe {
  readonly name: string;
  readonly source: string;
  /** The TypeScript error code the fence must raise, or undefined for a positive control. */
  readonly error?: string;
}

function compile(project: 'core' | 'node' | 'browser', probes: readonly Probe[]): Map<string, string> {
  const directory = scratch(`fence-${project}`);
  // An ES module, as this package is, so `verbatimModuleSyntax` reads the probes the same way.
  writeFileSync(join(directory, 'package.json'), '{"type":"module"}');
  for (const probe of probes) writeFileSync(join(directory, `${probe.name}.ts`), probe.source);
  writeFileSync(
    join(directory, 'tsconfig.json'),
    JSON.stringify({
      extends: join(PACKAGE_ROOT, `tsconfig.${project}.json`),
      compilerOptions: {
        noEmit: true,
        composite: false,
        declaration: false,
        declarationMap: false,
        sourceMap: false,
        rootDir: directory,
        tsBuildInfoFile: null,
        // Type roots resolve from a tsconfig's own directory; point them where the real one looks.
        // This changes where `types` are found, never which ones the project allows.
        typeRoots: [join(PACKAGE_ROOT, '..', '..', 'node_modules', '@types')],
      },
      include: [],
      files: probes.map((probe) => join(directory, `${probe.name}.ts`)),
    }),
  );
  let output = '';
  try {
    execFileSync(process.execPath, [TSC, '-p', join(directory, 'tsconfig.json')], { encoding: 'utf8' });
  } catch (error) {
    output = String((error as { stdout?: string }).stdout);
  }
  // An error with no file in front of it is the harness failing, not a probe: refuse to read on.
  const global = output.split('\n').filter((line) => /^error TS\d+/.test(line));
  expect(global, output).toEqual([]);
  const errors = new Map<string, string>();
  for (const line of output.split('\n')) {
    const match = /([a-z_]+)\.ts\(\d+,\d+\): error (TS\d+)/.exec(line);
    if (match !== null) errors.set(match[1]!, `${errors.get(match[1]!) === undefined ? '' : `${errors.get(match[1]!)} `}${match[2]!}`);
  }
  return errors;
}

function expectFence(project: 'core' | 'node' | 'browser', probes: readonly Probe[]): void {
  const errors = compile(project, probes);
  for (const probe of probes) {
    if (probe.error === undefined) expect(errors.get(probe.name), `${project} ${probe.name}`).toBeUndefined();
    else expect(`${errors.get(probe.name)}`, `${project} ${probe.name}`).toContain(probe.error);
  }
}

describe('the lib and types fence', () => {
  it('makes every host name a compile error in core', () => {
    expectFence('core', [
      { name: 'clean', source: 'export const clean = (a: Uint8Array): number => a.length;' },
      { name: 'node_crypto', source: "import { createHash } from 'node:crypto';\nexport const probe = createHash;", error: 'TS2307' },
      { name: 'node_fs', source: "import { readFileSync } from 'fs';\nexport const probe = readFileSync;", error: 'TS2307' },
      { name: 'buffer', source: 'export const probe = Buffer.alloc(1);', error: 'TS2591' },
      { name: 'process', source: 'export const probe = process.argv;', error: 'TS2591' },
      { name: 'document', source: 'export const probe = document.title;', error: 'TS2584' },
      { name: 'window', source: 'export const probe = window;', error: 'TS2304' },
      { name: 'text_encoder', source: 'export const probe = new TextEncoder();', error: 'TS2304' },
      { name: 'web_crypto', source: 'export const probe = crypto.subtle;', error: 'TS2304' },
    ]);
  }, 60_000);

  it('keeps the DOM out of the node entry', () => {
    expectFence('node', [
      { name: 'clean', source: "import { createHash } from 'node:crypto';\nexport const probe = createHash;" },
      { name: 'document', source: 'export const probe = document.title;', error: 'TS2584' },
      { name: 'html_element', source: 'export type Probe = HTMLElement;', error: 'TS2304' },
    ]);
  }, 60_000);

  it('keeps Node out of the browser entry', () => {
    expectFence('browser', [
      { name: 'clean', source: "export const probe = (b: Uint8Array): Promise<ArrayBuffer> => crypto.subtle.digest('SHA-256', new Uint8Array(b));" },
      { name: 'node_crypto', source: "import { createHash } from 'node:crypto';\nexport const probe = createHash;", error: 'TS2307' },
      { name: 'buffer', source: 'export const probe = Buffer.alloc(1);', error: 'TS2591' },
      { name: 'process', source: 'export const probe = process.argv;', error: 'TS2591' },
    ]);
  }, 60_000);
});
