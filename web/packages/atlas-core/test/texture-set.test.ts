import { createHash, webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  TextureSetRefusal,
  decodeTextureSet,
  parseTextureSetManifest,
  textureSetBlobPath,
  type TextureSetManifestEntry,
  type TextureSetRefusalReason,
} from '../src/texture-set.js';

const TEXTURES = new URL('../../../../assets/textures/', import.meta.url);
const manifestBytes = new Uint8Array(readFileSync(new URL('manifest.json', TEXTURES)));
const manifest = parseTextureSetManifest(manifestBytes);
const subtle = webcrypto.subtle as unknown as Parameters<typeof decodeTextureSet>[2];

interface PythonMap {
  readonly name: string;
  readonly byte_offset: number;
  readonly byte_length: number;
  readonly sha256: string;
  readonly first_bytes: readonly number[];
  readonly last_bytes: readonly number[];
}
interface PythonSet {
  readonly set_id: string;
  readonly version: number;
  readonly content_sha256: string;
  readonly byte_size: number;
  readonly header_sha256: string;
  readonly width: number;
  readonly height: number;
  readonly extent_u_mm: number;
  readonly extent_v_mm: number;
  readonly height_range_mm: number | null;
  readonly maps: readonly PythonMap[];
}
/** Written by `texture-set-python-decode.py.txt` from the backend's strict reader. */
const python = JSON.parse(readFileSync(new URL('./texture-set-python-decode.json', import.meta.url), 'utf8')) as {
  readonly profile: string;
  readonly sets: readonly PythonSet[];
};

const sha = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');
const blob = (entry: TextureSetManifestEntry): Uint8Array =>
  new Uint8Array(readFileSync(new URL(textureSetBlobPath(entry), TEXTURES)));
const entry = (setId: string): TextureSetManifestEntry => {
  const found = manifest.byId.get(setId);
  if (found === undefined) throw new Error(`${setId} is not in the manifest`);
  return found;
};
/** A manifest that pins these exact bytes: what a bad container needs to get past the digest. */
const repinned = (base: TextureSetManifestEntry, bytes: Uint8Array): TextureSetManifestEntry =>
  ({ ...base, contentSha256: sha(bytes), byteSize: bytes.byteLength });
const headerLength = (bytes: Uint8Array): number => new DataView(bytes.buffer, bytes.byteOffset).getUint32(4, true);
const ascii = (value: string): Uint8Array => new TextEncoder().encode(value);

function replaceOnce(bytes: Uint8Array, from: string, to: string): Uint8Array {
  const text = new TextDecoder('latin1').decode(bytes.subarray(0, 8 + headerLength(bytes)));
  const at = text.indexOf(from);
  if (at < 0 || text.indexOf(from, at + 1) >= 0) throw new Error(`${from} is not in the header exactly once`);
  const out = new Uint8Array(bytes);
  out.set(ascii(to), at);
  return out;
}

async function refusal(promise: Promise<unknown>): Promise<TextureSetRefusalReason> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof TextureSetRefusal) return error.reason;
    throw error;
  }
  throw new Error('the set was accepted');
}

function manifestRefusal(value: unknown): TextureSetRefusalReason {
  try {
    parseTextureSetManifest(typeof value === 'string' ? ascii(value) : ascii(JSON.stringify(value)));
  } catch (error) {
    if (error instanceof TextureSetRefusal) return error.reason;
    throw error;
  }
  throw new Error('the manifest was accepted');
}

// The smallest committed set keeps the refusal cases quick; brick carries the byte offsets below.
const KERB = 'cc0.kerb-stone';
const BRICK = 'cc0.brick-running-bond';

describe('texture set reader, conformance with the backend reader', () => {
  it('reads the committed manifest and names the same sets the Python fixture decoded', () => {
    expect(python.profile).toBe('exulanica.texture-set-python-decode/v1');
    expect(manifest.sets.map((set) => set.setId).sort()).toEqual(python.sets.map((set) => set.set_id));
    expect(python.sets.length).toBeGreaterThanOrEqual(2);
  });

  it.each(python.sets.map((set) => [set.set_id, set] as const))(
    '%s decodes to the maps the Python reader decodes, byte for byte',
    async (_setId, expected) => {
      const pinned = entry(expected.set_id);
      expect({
        version: pinned.version, contentSha256: pinned.contentSha256, byteSize: pinned.byteSize,
        width: pinned.width, height: pinned.height, extentUMm: pinned.extentUMm, extentVMm: pinned.extentVMm,
      }).toEqual({
        version: expected.version, contentSha256: expected.content_sha256, byteSize: expected.byte_size,
        width: expected.width, height: expected.height, extentUMm: expected.extent_u_mm, extentVMm: expected.extent_v_mm,
      });
      const bytes = blob(pinned);
      const decoded = await decodeTextureSet(bytes, pinned, subtle);
      expect(decoded.heightRangeMm).toBe(expected.height_range_mm);
      expect(sha(bytes.subarray(8, 8 + headerLength(bytes)))).toBe(expected.header_sha256);
      expect(Object.keys(decoded.maps)).toEqual(expected.maps.map((map) => map.name));
      for (const map of expected.maps) {
        const view = decoded.maps[map.name as keyof typeof decoded.maps]!;
        expect(view.byteOffset - bytes.byteOffset).toBe(map.byte_offset);
        expect(view.byteLength).toBe(map.byte_length);
        expect(sha(view)).toBe(map.sha256);
        expect([...view.subarray(0, 6)]).toEqual(map.first_bytes);
        expect([...view.subarray(view.byteLength - 6)]).toEqual(map.last_bytes);
      }
    },
  );

  it('states each set\'s placement, which the material binding orients its UVs by', async () => {
    const surfaces = await Promise.all(manifest.sets.map(async (set) =>
      [set.setId, (await decodeTextureSet(blob(set), set, subtle)).surface] as const));
    expect(Object.fromEntries(surfaces)).toEqual({
      'cc0.awning-canvas': 'horizontal',
      'cc0.brick-running-bond': 'vertical',
      'cc0.broadleaf-foliage': 'vertical',
      'cc0.carriageway-asphalt': 'horizontal',
      'cc0.cast-concrete': 'vertical',
      'cc0.float-glazing': 'vertical',
      'cc0.footway-paving': 'horizontal',
      'cc0.kerb-stone': 'horizontal',
      'cc0.limestone-ashlar': 'vertical',
      'cc0.painted-render': 'vertical',
      'cc0.painted-timber': 'vertical',
      'cc0.road-paint-white': 'horizontal',
      'cc0.road-paint-yellow': 'horizontal',
      'cc0.sign-panel': 'vertical',
      'cc0.storefront-metal': 'vertical',
      'cc0.tree-bark': 'vertical',
      'cc0.tree-pit-soil': 'horizontal',
    });
  });
});

describe('texture set reader, refusals', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('refuses every set when crypto.subtle is missing, before reading a byte', async () => {
    const pinned = entry(KERB);
    expect(await refusal(decodeTextureSet(blob(pinned), pinned, null))).toBe('digest-unavailable');
    expect(await refusal(decodeTextureSet(new Uint8Array(0), pinned, null))).toBe('digest-unavailable');
    vi.stubGlobal('crypto', undefined);
    expect(await refusal(decodeTextureSet(blob(pinned), pinned))).toBe('digest-unavailable');
  });

  it('uses the page\'s own crypto.subtle when none is passed', async () => {
    const pinned = entry(KERB);
    vi.stubGlobal('crypto', webcrypto);
    await expect(decodeTextureSet(blob(pinned), pinned)).resolves.toMatchObject({ surface: 'horizontal' });
  });

  it('refuses bytes whose digest is not the pin', async () => {
    const pinned = entry(KERB);
    const bytes = blob(pinned);
    const flipped = new Uint8Array(bytes);
    flipped[flipped.length - 1] = flipped[flipped.length - 1]! ^ 1;
    expect(await refusal(decodeTextureSet(flipped, pinned, subtle))).toBe('digest');
    const wrongPin = { ...pinned, contentSha256: pinned.contentSha256.replace(/^./, (c) => (c === '0' ? '1' : '0')) };
    expect(await refusal(decodeTextureSet(bytes, wrongPin, subtle))).toBe('digest');
  });

  it('refuses truncated bytes, whether or not a manifest pinned them', async () => {
    const pinned = entry(KERB);
    const truncated = blob(pinned).subarray(0, pinned.byteSize - 1);
    expect(await refusal(decodeTextureSet(truncated, pinned, subtle))).toBe('byte-size');
    expect(await refusal(decodeTextureSet(truncated, repinned(pinned, truncated), subtle))).toBe('container');
    const preamble = blob(pinned).subarray(0, 5);
    expect(await refusal(decodeTextureSet(preamble, repinned(pinned, preamble), subtle))).toBe('container');
    const headerOnly = blob(pinned).subarray(0, 100);
    expect(await refusal(decodeTextureSet(headerOnly, repinned(pinned, headerOnly), subtle))).toBe('container');
  });

  it('refuses trailing bytes after the last map', async () => {
    const pinned = entry(KERB);
    const bytes = blob(pinned);
    const longer = new Uint8Array(bytes.byteLength + 1);
    longer.set(bytes);
    expect(await refusal(decodeTextureSet(longer, repinned(pinned, longer), subtle))).toBe('container');
  });

  it('refuses a wrong magic', async () => {
    const pinned = entry(KERB);
    const bytes = new Uint8Array(blob(pinned));
    bytes.set(ascii('LTX2'), 0);
    expect(await refusal(decodeTextureSet(bytes, repinned(pinned, bytes), subtle))).toBe('container');
  });

  it('refuses padding that is not spaces', async () => {
    const pinned = entry(KERB);
    const bytes = new Uint8Array(blob(pinned));
    // Kerb's header is 2068 bytes, so four spaces pad the preamble and header to 2080.
    expect(8 + headerLength(bytes)).toBe(2076);
    expect([...bytes.subarray(2076, 2080)]).toEqual([0x20, 0x20, 0x20, 0x20]);
    bytes[2079] = 0;
    expect(await refusal(decodeTextureSet(bytes, repinned(pinned, bytes), subtle))).toBe('container');
  });

  it('refuses a header that disagrees with its manifest entry', async () => {
    const pinned = entry(KERB);
    const bytes = blob(pinned);
    for (const disagreeing of [
      { ...pinned, version: 2 },
      { ...pinned, extentUMm: pinned.extentUMm + 1 },
      { ...pinned, extentVMm: pinned.extentVMm - 1 },
      { ...pinned, width: pinned.width * 2, height: pinned.height / 2 },
      { ...pinned, setId: 'cc0.kerb-stone-2' },
      { ...pinned, licenceSha256: '0'.repeat(64) },
    ]) {
      expect(await refusal(decodeTextureSet(bytes, disagreeing, subtle))).toBe('header');
    }
  });

  it('refuses a header whose bytes are not canonical, or whose layout this reader was not written for', async () => {
    const pinned = entry(KERB);
    const bytes = blob(pinned);
    // Same length, so every offset still agrees and the JSON still parses: only the canonical
    // form differs. The escape writes "F" as F in place of "Flame-".
    const escaped = replaceOnce(bytes, '"summary":"Flame-', '"summary":"\\u0046');
    const spaced = replaceOnce(bytes, '"title":"Kerb', '"title": "erb');
    const fractionalSeed = replaceOnce(bytes, '"seed":20260916', '"seed":2026091.');
    const mirroredNormal = replaceOnce(bytes, '+Y toward row 0', '-Y toward row 0');
    const objectSpace = replaceOnce(bytes, '"space":"tangent"', '"space":"objects"');
    const noPlacement = replaceOnce(bytes, '"surface":"horizontal"', '"surface":"horizontel"');
    const wrongTruth = replaceOnce(bytes, '"truth":"invented"', '"truth":"observed"');
    for (const altered of [escaped, spaced, fractionalSeed, mirroredNormal, objectSpace, noPlacement, wrongTruth]) {
      expect(altered.byteLength).toBe(bytes.byteLength);
      expect(await refusal(decodeTextureSet(altered, repinned(pinned, altered), subtle))).toBe('header');
    }
  });

  it('refuses a map declared at an offset other than the one its predecessors end at', async () => {
    const pinned = entry(BRICK);
    const bytes = blob(pinned);
    const moved = replaceOnce(bytes, '"byte_offset":3148000', '"byte_offset":3148001');
    expect(await refusal(decodeTextureSet(moved, repinned(pinned, moved), subtle))).toBe('header');
  });
});

describe('texture manifest reader, refusals', () => {
  const document = JSON.parse(new TextDecoder().decode(manifestBytes)) as {
    profile: string;
    sets: Record<string, unknown>[];
  };
  const withFirstSet = (change: (set: Record<string, unknown>) => void): unknown => {
    const copy = structuredClone(document);
    change(copy.sets[0]!);
    return copy;
  };

  it('accepts the committed bytes exactly, and refuses them re-serialised with whitespace', () => {
    expect(manifest.sets).toHaveLength(17);
    expect(manifestRefusal(JSON.stringify(document, null, 1))).toBe('manifest');
    expect(manifestRefusal(`${new TextDecoder().decode(manifestBytes)}\n`)).toBe('manifest');
  });

  it('refuses a fraction, an unknown key, a missing key, a repeated set and a wrong profile', () => {
    expect(manifestRefusal(new TextDecoder().decode(manifestBytes).replace('"version":1}', '"version":1.0}'))).toBe('manifest');
    expect(manifestRefusal(withFirstSet((set) => { set['fallback'] = 'none'; }))).toBe('manifest');
    expect(manifestRefusal(withFirstSet((set) => { delete set['extent_mm']; }))).toBe('manifest');
    expect(manifestRefusal({ ...document, sets: [...document.sets, document.sets[0]] })).toBe('manifest');
    expect(manifestRefusal({ ...document, profile: 'exulanica.texture-manifest/v3' })).toBe('manifest');
    expect(manifestRefusal({ ...document, sets: [] })).toBe('manifest');
  });

  it('refuses entries that are not the real shape', () => {
    expect(manifestRefusal(withFirstSet((set) => { set['extent_mm'] = { u: 0, v: 1800 }; }))).toBe('manifest');
    expect(manifestRefusal(withFirstSet((set) => { set['licence_id'] = 'CC-BY-4.0'; }))).toBe('manifest');
    expect(manifestRefusal(withFirstSet((set) => { set['set_id'] = 'Brick'; }))).toBe('manifest');
    expect(manifestRefusal(withFirstSet((set) => { set['content_sha256'] = 'F'.repeat(64); }))).toBe('manifest');
    expect(manifestRefusal(withFirstSet((set) => {
      (set['channels'] as Record<string, unknown>[])[0]!['srgb'] = false;
    }))).toBe('manifest');
    expect(manifestRefusal(withFirstSet((set) => {
      (set['channels'] as unknown[]).pop();
    }))).toBe('manifest');
  });
});
