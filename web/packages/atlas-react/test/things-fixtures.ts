/**
 * The shipped things documents served as the host's thing library serves them: kinds and looks as
 * their canonical bytes (sorted keys, no white space, UTF-8), which their digests name, and the body
 * plans catalog as its file. Built from the committed catalogs, never from the code under test.
 */
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readThingLibrary, type ThingLibraryList } from '../src/playcanvas/things/documents.js';

// Paths as text: a page environment replaces the global URL, which the file system then refuses.
const THINGS = join(dirname(fileURLToPath(String(import.meta.url))), '../../../../assets/catalogs/things');

export const readThingsFile = (path: string): Buffer => readFileSync(join(THINGS, path));
export const thingsJson = (path: string): Record<string, unknown> => JSON.parse(readThingsFile(path).toString('utf8')) as Record<string, unknown>;
export const thingsFiles = (dir: string): string[] =>
  readdirSync(join(THINGS, dir)).filter((name) => name.endsWith('.json')).sort().map((name) => `${dir}/${name}`);

export const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');

export function canonicalBytes(value: unknown): Uint8Array {
  const sorted = (v: unknown): unknown => Array.isArray(v)
    ? v.map(sorted)
    : typeof v === 'object' && v !== null
      ? Object.fromEntries(Object.keys(v).sort().map((key) => [key, sorted((v as Record<string, unknown>)[key])]))
      : v;
  return new TextEncoder().encode(JSON.stringify(sorted(value)));
}

export interface ServedLibrary {
  readonly list: ThingLibraryList;
  readonly bytes: ReadonlyMap<string, Uint8Array>;
  /** A kind's reference as a placed thing names it. */
  kindRef(kind: string, version: number): { kind: string; version: number; sha256: string };
  fetch(digest: string): Promise<ArrayBuffer>;
}

export function servedLibrary(): ServedLibrary {
  const bytes = new Map<string, Uint8Array>();
  const kinds = thingsFiles('kinds').map((path) => {
    const doc = thingsJson(path);
    const raw = canonicalBytes(doc);
    bytes.set(sha256(raw), raw);
    return { kind: doc['kind'], version: doc['version'], sha256: sha256(raw), label: doc['label'], class: doc['class'], body_plan: (doc['body'] as { plan: string }).plan, looks: doc['looks'] };
  });
  const looks = thingsFiles('looks').map((path) => {
    const doc = thingsJson(path);
    const raw = canonicalBytes(doc);
    bytes.set(sha256(raw), raw);
    return { look: doc['look'], version: doc['version'], sha256: sha256(raw), label: doc['label'], body_plan: doc['body_plan'], look_kind: doc['look_kind'], container: doc['container'] };
  });
  const plans = new Uint8Array(readThingsFile('body-plans.v1.json'));
  bytes.set(sha256(plans), plans);
  const list = readThingLibrary({ profile: 'exulanica.thing-library/v1', kinds, looks, body_plans: { sha256: sha256(plans) } });
  return {
    list,
    bytes,
    kindRef(kind, version) {
      const entry = list.kinds.find((one) => one.kind === kind && one.version === version)!;
      return { kind, version, sha256: entry.sha256 };
    },
    async fetch(digest) {
      const held = bytes.get(digest);
      if (held === undefined) throw new Error(`no bytes for ${digest}`);
      return held.buffer.slice(held.byteOffset, held.byteOffset + held.byteLength) as ArrayBuffer;
    },
  };
}

/**
 * Wait until `ready()` holds. A figure is made after its library reads and their digest checks,
 * which take as long as the machine lets them: a test that counts a fixed number of turns of the
 * event loop instead reads a figure that is not there yet on a busy machine. Fails by name after
 * `limitMs`, so a figure that is never made says what was waited for.
 */
export async function until(ready: () => boolean, what: string, limitMs = 10_000): Promise<void> {
  const started = Date.now();
  while (!ready()) {
    if (Date.now() - started > limitMs) throw new Error(`waited ${limitMs} ms for ${what}`);
    await new Promise((resolve) => setTimeout(resolve, 1));
  }
}
