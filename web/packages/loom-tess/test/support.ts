import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { canonicalBytes } from '../src/core/canonical-json.js';
import type { CanonicalValue } from '../src/core/canonical-json.js';

export const PACKAGE_ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)));
export const REPOSITORY_ROOT = resolve(PACKAGE_ROOT, '..', '..', '..');
export const FIXTURE_PATH = join(PACKAGE_ROOT, 'test', 'fixtures', 'tile-conformance.json');

export const fixtureBytes = (): Uint8Array => new Uint8Array(readFileSync(FIXTURE_PATH));

/** The fixture as a mutable object, for tests that break one thing in it. */
export const fixtureObject = (): any => JSON.parse(readFileSync(FIXTURE_PATH, 'utf8'));

/** Back to canonical bytes, which is the only form the reader accepts. */
export const documentBytes = (document: unknown): Uint8Array => canonicalBytes(document as CanonicalValue);

export const recordsOf = (document: any, kind: string): any[] =>
  document.grammars[0].records.filter((record: any) => record.kind === kind);

export const scratch = (label: string): string => mkdtempSync(join(tmpdir(), `loom-tess-${label}-`));
