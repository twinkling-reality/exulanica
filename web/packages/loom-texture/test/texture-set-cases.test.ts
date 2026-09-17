import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { canonicalBytes } from '../src/canonical-json.js';
import {
  MANIFEST_PROFILE_V2,
  TextureSetRefusal,
  checkTextureSet,
  readTextureManifest,
} from '../src/manifest-reader.js';
import { CASES_FILE, FIXTURE_DIRECTORY, conformanceFiles } from './conformance.js';

/**
 * The shared texture set cases, run against this package's reader. The backend and the browser run
 * the same file; see `conformance.ts` for what the cases are and why each has exactly one defect.
 */
const HERE = fileURLToPath(new URL('.', import.meta.url));

type Change = { path: (string | number)[]; value?: unknown; remove?: true };
interface Cases {
  manifest: string;
  manifests: { name: string; changes: Change[]; reason: string | null }[];
  containers: { name: string; container: string; entry: Record<string, unknown>; reason: string | null }[];
}

const cases = JSON.parse(readFileSync(join(HERE, CASES_FILE), 'utf8')) as Cases;

function applyChanges(document: unknown, changes: readonly Change[]): unknown {
  const copy = JSON.parse(JSON.stringify(document)) as unknown;
  for (const change of changes) {
    let parent = copy as Record<string | number, unknown>;
    for (const step of change.path.slice(0, -1)) parent = parent[step] as Record<string | number, unknown>;
    const last = change.path.at(-1)!;
    if (change.remove) {
      if (Array.isArray(parent)) parent.splice(last as number, 1);
      else delete parent[last];
    } else {
      parent[last] = change.value;
    }
  }
  return copy;
}

/** null when `run` accepts, or the reason it refused with. Anything but a refusal fails the test. */
function outcome(run: () => unknown): string | null {
  try {
    run();
    return null;
  } catch (error) {
    if (error instanceof TextureSetRefusal) return error.reason;
    throw error;
  }
}

describe('the committed conformance files', () => {
  it('are exactly what conformance.ts generates, and nothing else', () => {
    const generated = conformanceFiles();
    for (const [path, bytes] of generated) {
      expect(Buffer.from(readFileSync(join(HERE, path))).equals(Buffer.from(bytes)), path).toBe(true);
    }
    const committed = (readdirSync(join(HERE, FIXTURE_DIRECTORY), { recursive: true, withFileTypes: true }))
      .filter((entry) => entry.isFile())
      .map((entry) => join(entry.parentPath, entry.name).slice(HERE.length))
      .sort();
    const expected = [...generated.keys()].filter((path) => path !== CASES_FILE).sort();
    expect(committed).toEqual(expected);
  });
});

describe('texture-set-cases.json against the loom-texture reader', () => {
  const manifest = JSON.parse(readFileSync(join(HERE, cases.manifest), 'utf8')) as unknown;

  for (const testCase of cases.manifests) {
    it(`manifest: ${testCase.name}`, () => {
      const bytes = canonicalBytes(applyChanges(manifest, testCase.changes) as object);
      expect(outcome(() => readTextureManifest(bytes))).toBe(testCase.reason);
    });
  }

  for (const testCase of cases.containers) {
    it(`container: ${testCase.name}`, () => {
      const [entry] = readTextureManifest(canonicalBytes({ profile: MANIFEST_PROFILE_V2, sets: [testCase.entry] }));
      const bytes = new Uint8Array(readFileSync(join(HERE, testCase.container)));
      expect(outcome(() => checkTextureSet(bytes, entry!))).toBe(testCase.reason);
    });
  }

  it('covers every reason a reader gives, and each kind of container a reader accepts', () => {
    expect(new Set(cases.containers.map((testCase) => testCase.reason))).toEqual(
      new Set([null, 'byte-size', 'digest', 'container', 'header']),
    );
    expect(new Set(cases.manifests.map((testCase) => testCase.reason))).toEqual(new Set([null, 'manifest']));
    const accepted = cases.containers.filter((testCase) => testCase.reason === null);
    expect(new Set(accepted.map((testCase) => `${testCase.entry.container_profile} ${testCase.entry.material_class}`))).toEqual(
      new Set([
        'exulanica.texture-set/v1 opaque',
        'exulanica.texture-set/v2 opaque',
        'exulanica.texture-set/v2 cutout',
        'exulanica.texture-set/v2 decal',
        'exulanica.texture-set/v2 glazing',
      ]),
    );
  });
});
