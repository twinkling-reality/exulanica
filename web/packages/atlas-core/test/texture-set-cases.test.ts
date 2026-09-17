import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  TEXTURE_MANIFEST_PROFILE_V2,
  TextureSetRefusal,
  decodeTextureSet,
  parseTextureSetManifest,
  type DecodedTextureSet,
  type TextureSetDigest,
} from '../src/texture-set.js';

/**
 * The shared texture set cases, run against the browser's reader. The texture lane's baker, the
 * backend and this reader all run `web/packages/loom-texture/test/texture-set-cases.json` and must
 * agree on every outcome: accepted, or refused for the same one reason. The file and its fixtures are
 * read by path from the texture package's test folder, which is not an import, so nothing that ships
 * depends on the offline package.
 */

// Relative to web/, where the suite runs.
const CASES = 'packages/loom-texture/test/texture-set-cases.json';
const HERE = dirname(CASES);
const subtle = webcrypto.subtle as unknown as TextureSetDigest;

type Change = { readonly path: readonly (string | number)[]; readonly value?: unknown; readonly remove?: true };
interface Cases {
  readonly manifest: string;
  readonly manifests: readonly { readonly name: string; readonly changes: readonly Change[]; readonly reason: string | null }[];
  readonly containers: readonly {
    readonly name: string;
    readonly container: string;
    readonly entry: Record<string, unknown>;
    readonly reason: string | null;
  }[];
}

const cases = JSON.parse(readFileSync(CASES, 'utf8')) as Cases;

/** Canonical JSON as every reader of these files writes it: sorted keys, no whitespace. */
function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  const object = value as Record<string, unknown>;
  return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${canonical(object[key])}`).join(',')}}`;
}

const bytesOf = (value: unknown): Uint8Array => new TextEncoder().encode(canonical(value));

function applyChanges(document: unknown, changes: readonly Change[]): unknown {
  const copy = JSON.parse(JSON.stringify(document)) as unknown;
  for (const change of changes) {
    let parent = copy as Record<string | number, unknown>;
    for (const step of change.path.slice(0, -1)) parent = parent[step] as Record<string | number, unknown>;
    const last = change.path.at(-1)!;
    if (change.remove === true) {
      if (Array.isArray(parent)) parent.splice(last as number, 1);
      else delete parent[last];
    } else {
      parent[last] = change.value;
    }
  }
  return copy;
}

/** null when the reader accepts, or the reason it refused with. Anything but a refusal fails the test. */
async function outcome(run: () => unknown): Promise<string | null> {
  try {
    await run();
    return null;
  } catch (error) {
    if (error instanceof TextureSetRefusal) return error.reason;
    throw error;
  }
}

async function decodeCase(testCase: Cases['containers'][number]): Promise<DecodedTextureSet> {
  const manifest = parseTextureSetManifest(bytesOf({ profile: TEXTURE_MANIFEST_PROFILE_V2, sets: [testCase.entry] }));
  const bytes = new Uint8Array(readFileSync(join(HERE, testCase.container)));
  return decodeTextureSet(bytes, manifest.sets[0]!, subtle);
}

describe('texture-set-cases.json against the browser reader', () => {
  const fixture = JSON.parse(readFileSync(join(HERE, cases.manifest), 'utf8')) as unknown;

  it('reads the fixture manifest from its committed bytes', () => {
    expect(parseTextureSetManifest(new Uint8Array(readFileSync(join(HERE, cases.manifest)))).sets).toHaveLength(6);
  });

  for (const testCase of cases.manifests) {
    it(`manifest: ${testCase.name}`, async () => {
      const bytes = bytesOf(applyChanges(fixture, testCase.changes));
      expect(await outcome(() => parseTextureSetManifest(bytes))).toBe(testCase.reason);
    });
  }

  for (const testCase of cases.containers) {
    it(`container: ${testCase.name}`, async () => {
      expect(await outcome(() => decodeCase(testCase))).toBe(testCase.reason);
    });
  }

  it('covers every reason a reader gives, and each kind of container a reader accepts', () => {
    expect(new Set(cases.containers.map((testCase) => testCase.reason)))
      .toEqual(new Set([null, 'byte-size', 'digest', 'container', 'header']));
    expect(new Set(cases.manifests.map((testCase) => testCase.reason))).toEqual(new Set([null, 'manifest']));
    const accepted = cases.containers.filter((testCase) => testCase.reason === null);
    expect(new Set(accepted.map((testCase) => `${String(testCase.entry['container_profile'])} ${String(testCase.entry['material_class'])}`)))
      .toEqual(new Set([
        'exulanica.texture-set/v1 opaque',
        'exulanica.texture-set/v2 opaque',
        'exulanica.texture-set/v2 cutout',
        'exulanica.texture-set/v2 decal',
        'exulanica.texture-set/v2 glazing',
      ]));
  });

  it('decodes each accepted container to its class, maker kind, class parameters and maps, as its own header states them', async () => {
    for (const testCase of cases.containers.filter((candidate) => candidate.reason === null)) {
      const decoded = await decodeCase(testCase);
      const bytes = new Uint8Array(readFileSync(join(HERE, testCase.container)));
      const length = new DataView(bytes.buffer, bytes.byteOffset).getUint32(4, true);
      const header = JSON.parse(new TextDecoder().decode(bytes.subarray(8, 8 + length))) as Record<string, unknown>;
      const maps = header['maps'] as readonly { readonly name: string; readonly byte_offset: number; readonly byte_length: number }[];
      expect(decoded.profile, testCase.name).toBe(header['profile']);
      expect(decoded.materialClass).toBe(header['material_class'] ?? 'opaque');
      expect(decoded.makerKind).toBe(header['maker_kind'] ?? 'procedural');
      expect(decoded.heightRangeMm).toBe(header['height_range_mm'] ?? null);
      expect(Object.keys(decoded.maps)).toEqual(maps.map((item) => item.name));
      expect(decoded.channels.map((channel) => channel.map)).toEqual(maps.map((item) => item.name));
      for (const item of maps) {
        const view = decoded.maps[item.name as keyof typeof decoded.maps]!;
        expect([view.byteOffset - bytes.byteOffset, view.byteLength]).toEqual([item.byte_offset, item.byte_length]);
      }
      const stated = (header['class'] ?? {}) as Record<string, unknown>;
      switch (decoded.classParameters.materialClass) {
        case 'opaque':
          expect(stated).toEqual({});
          break;
        case 'cutout':
          expect(stated).toEqual({
            alpha_cutoff: decoded.classParameters.alphaCutoff,
            coverage_permille: decoded.classParameters.coveragePermille,
            double_sided: decoded.classParameters.doubleSided,
          });
          break;
        case 'decal':
          expect(stated).toEqual({ coverage_permille: decoded.classParameters.coveragePermille });
          break;
        case 'glazing':
          expect(stated).toEqual({ double_sided: decoded.classParameters.doubleSided, ior_millionths: decoded.classParameters.iorMillionths });
          break;
      }
    }
  });
});
