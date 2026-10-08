import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  StylePackRefusal,
  canonicalJson,
  canonicalStylePackBytes,
  fit,
  readStylePackManifest,
  resolveLookRole,
  resolveStylePack,
  stretchCoordinate,
  swatchKeyOf,
  variantIndex,
  type LookFamily,
  type StylePackContext,
  type StylePackManifest,
} from '../src/style-pack.js';

// Relative to web/, where the suite runs. The same file the Python reader runs.
const CASES = JSON.parse(readFileSync('../assets/style-packs/manifest-cases.v1.json', 'utf8')) as {
  context: { families: Record<string, { fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }>; texture_sets: string[] };
  cases: { name: string; manifest: unknown; expect: { sha256?: string; refusal?: string; path?: string } }[];
};
const families = new Map<string, LookFamily>(Object.entries(CASES.context.families).map(([key, value]) => [key, {
  fit: value.fit, dressing: value.dressing, fillMinimumPermille: value.fill_minimum_permille, fillMaximumPermille: value.fill_maximum_permille,
}]));
const context: StylePackContext = { families, textureSets: new Set(CASES.context.texture_sets) };
const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');
const named = (name: string): StylePackManifest =>
  readStylePackManifest(CASES.cases.find((c) => c.name === name)!.manifest, context);

describe('the shared style pack cases', () => {
  for (const testCase of CASES.cases) {
    it(testCase.name, () => {
      if (testCase.expect.sha256 !== undefined) {
        // The Python reader wrote this digest: both readers write the same canonical bytes.
        expect(sha256(canonicalStylePackBytes(readStylePackManifest(testCase.manifest, context)))).toBe(testCase.expect.sha256);
        return;
      }
      let refusal: StylePackRefusal | null = null;
      try {
        readStylePackManifest(testCase.manifest, context);
      } catch (error) {
        if (!(error instanceof StylePackRefusal)) throw error;
        refusal = error;
      }
      expect(refusal, 'the manifest was accepted').not.toBeNull();
      expect({ reason: refusal!.reason, path: refusal!.path }).toEqual({ reason: testCase.expect.refusal, path: testCase.expect.path });
    });
  }
  it('runs a valid and a refused case of every reason', () => {
    const reasons = new Set(CASES.cases.map((c) => c.expect.refusal ?? 'valid'));
    expect([...reasons].sort()).toEqual(['duplicate', 'licence', 'range', 'reference', 'shape', 'valid']);
  });
});

describe('canonical bytes', () => {
  it('sorts keys, drops whitespace and escapes past ASCII as Python does', () => {
    // Python: json.dumps({"b": 1, "a": "é☃", "c": [True, None]}, sort_keys=True, separators=(",", ":"))
    expect(canonicalJson({ b: 1, a: 'é☃', c: [true, null] })).toBe('{"a":"\\u00e9\\u2603","b":1,"c":[true,null]}');
  });
  it('refuses a fraction', () => {
    expect(() => canonicalJson({ a: 0.5 })).toThrow(StylePackRefusal);
  });
});

describe('resolving a look role', () => {
  const root = named('a complete pack with no base');
  const dusk = named('a pack drafted on a base, stating only what it changes');

  it('applies a base chain: the nearer pack wins, anything it leaves out is the base\'s', () => {
    const pack = resolveStylePack([dusk, root]);
    expect(pack.swatches.get('brick')!.srgb8).toEqual([150, 70, 60]);
    expect(pack.swatches.get('cream')!.srgb8).toEqual([243, 226, 194]);
    expect(pack.light.default_preset).toBe('day');
    expect(pack.shading.model).toBe('toon');
    expect(pack.edge).toEqual(root.edge);
    expect(pack.surfaces['wall.brick_running_bond']).toEqual({ swatch: 'brick', up: null });
    expect(pack.surfaces['path.footway']).toEqual(root.surfaces['path.footway']);
    expect(() => resolveStylePack([root, dusk])).toThrow(/does not name/);
    expect(() => resolveStylePack([dusk])).toThrow(/ends at a pack that names a base/);
  });

  it('draws a generated look through its base: its new pieces, and everything else the base\'s', () => {
    const generated = named('a generated pack drawn on a base, stating only its new pieces');
    const pack = resolveStylePack([generated, root]);
    expect(pack.light).toEqual(root.light);
    expect(pack.shading).toEqual(root.shading);
    expect(pack.edge).toEqual(root.edge);
    expect(pack.surfaces).toEqual(root.surfaces);
    expect([...pack.swatches.keys()]).toEqual(root.palette.swatches.map((swatch) => swatch.key));
    for (const role of Object.keys(generated.modules)) {
      const module = pack.modules[role]!;
      expect(module.stated).toBe(0);
      for (const variant of module.variants) expect(module.files.has(variant.file)).toBe(true);
    }
    for (const role of Object.keys(root.modules).filter((role) => !(role in generated.modules))) {
      expect(pack.modules[role]!.stated).toBe(1);
    }
    // A generated piece is coloured from the base's palette: the look it was made in.
    const swatch = root.palette.swatches[0]!;
    expect(swatchKeyOf(pack, pack.modules['fixture.well']!, swatch.srgb8)).toBe(swatch.key);
  });

  it('dresses the leaf, then the family default, then nothing', () => {
    const pack = resolveStylePack([root]);
    const slot = (lookRole: string, boxMm: readonly [number, number, number] = [1000, 120, 1600]) =>
      ({ identity: 'part:00042', lookRole, positionMm: [0, 0, 0] as const, yawQuarterTurns: 0 as const, boxMm });
    const brick = resolveLookRole(pack, slot('wall.brick_running_bond'), families);
    expect(brick).toMatchObject({ kind: 'surface', role: 'wall.brick_running_bond', swatch: { key: 'brick' }, up: { key: 'roof_tile' } });
    expect(resolveLookRole(pack, slot('wall.limestone'), families)).toMatchObject({ kind: 'surface', role: 'wall.default', swatch: { key: 'cream' } });
    expect(resolveLookRole(pack, slot('window.sash'), families)).toMatchObject({ kind: 'module', role: 'window.default', scale: [1, 1, 1] });
    expect(resolveLookRole(pack, slot('road.carriageway'), families)).toBeNull();
    expect(resolveLookRole(pack, slot('character.default'), families)).toBeNull();
  });

  it('picks a variant by the part\'s identity, the same in every runtime', () => {
    // FNV-1a of "car-17|car" is 2408239426 (computed in Python): variant 0 of 2; "part:00042|sash" is 1666020787: 1 of 2.
    expect(variantIndex('car-17', 'car', 2)).toBe(0);
    expect(variantIndex('part:00042', 'sash', 2)).toBe(1);
    expect(variantIndex('part:00042', 'sash', 8)).toBe(3);
    expect(variantIndex('é', 'leaf', 3)).toBe(0);
  });

  it('stretches a window between its frame bars, refuses a hole smaller than its frame, then tries the next variant', () => {
    const pack = resolveStylePack([root]);
    const slotOf = (boxMm: readonly [number, number, number]) => ({ identity: 'w', lookRole: 'window.sash', positionMm: [0, 0, 0] as const, yawQuarterTurns: 0 as const, boxMm });
    // The case window (1000 by 120 by 1600) stretches across 60 to 940, in depth 40 to 80, up 60 to 1540.
    expect(resolveLookRole(pack, slotOf([2600, 243, 3000]), families)).toMatchObject({
      kind: 'module', role: 'window.default', scale: [1, 1, 1],
      stretch: [{ low: 60, high: 940, length: 2480, box: 2600 }, { low: 60, high: 1540, length: 2880, box: 3000 }, { low: 40, high: 80, length: 163, box: 243 }],
    });
    // Its bars and its depth outside the gap take 120 by 80 by 120: a hole that size leaves no zone.
    expect(resolveLookRole(pack, slotOf([120, 120, 1600]), families)).toBeNull();
    expect(resolveLookRole(pack, slotOf([1000, 80, 1600]), families)).toBeNull();
    const car = resolveLookRole(pack, { identity: 'car-17', lookRole: 'vehicle.car', positionMm: [0, 0, 0], yawQuarterTurns: 0, boxMm: [2100, 900, 750] }, families);
    // Variant 0 (4200 by 1800 by 1500) contained in half its size: a uniform 0.5.
    expect(car).toMatchObject({ kind: 'module', variant: 0, scale: [0.5, 0.5, 0.5], file: { path: 'pieces/car-a.glb' }, lod1: { path: 'pieces/car-a-far.glb' } });
  });
});

describe('fitting a piece to a slot', () => {
  const contain: LookFamily = { fit: 'contain', dressing: 'module', fillMinimumPermille: 0, fillMaximumPermille: 0 };
  const fill: LookFamily = { fit: 'fill', dressing: 'module', fillMinimumPermille: 800, fillMaximumPermille: 1250 };
  const tile: LookFamily = { fit: 'tile', dressing: 'module', fillMinimumPermille: 0, fillMaximumPermille: 0 };
  it('contains uniformly by the tightest axis', () => {
    expect(fit(contain, [2000, 1000, 1000], [1000, 1000, 1000])).toEqual({ scale: [0.5, 0.5, 0.5], stretch: [null, null, null], copies: 1 });
  });
  it('fills each axis within 0.8 to 1.25, else refuses', () => {
    expect(fit(fill, [1000, 100, 2000], [1200, 100, 1800])).toEqual({ scale: [1.2, 0.9, 1], stretch: [null, null, null], copies: 1 });
    expect(fit(fill, [1000, 100, 2000], [1300, 100, 1800])).toBeNull();
    expect(fit(fill, [1000, 100, 2000], [1000, 79, 2000])).toBeNull();
  });
  it('stretches a stated zone to any length the slot leaves it, and scales the other axes within bounds', () => {
    // Width stretches between 100 and 900; depth and height scale.
    expect(fit(fill, [1000, 100, 2000], [3000, 110, 1800], [[100, 900], null, null])).toEqual({
      scale: [1, 0.9, 1.1], stretch: [{ low: 100, high: 900, length: 2800, box: 3000 }, null, null], copies: 1,
    });
    // A slot narrower than the fixed 200 mm, or exactly that, leaves the zone no length.
    expect(fit(fill, [1000, 100, 2000], [200, 100, 2000], [[100, 900], null, null])).toBeNull();
    // The stretch does not free an axis that scales: 1300 deep against 100 is refused.
    expect(fit(fill, [1000, 100, 2000], [3000, 1300, 2000], [[100, 900], null, null])).toBeNull();
  });
  it('moves what lies past a zone with it and keeps what lies before it', () => {
    const stretch = { low: 100, high: 900, length: 2800, box: 3000 };
    expect([0, 100, 500, 900, 1000].map((p) => stretchCoordinate(stretch, p))).toEqual([0, 100, 1500, 2900, 3000]);
  });
  it('tiles copies along the width, each scaled to share it exactly', () => {
    // 4,500 mm of fence from 1,000 mm panels: 5 copies (4.5 rounds to 5... by Math.round: 5), each 0.9 wide.
    expect(fit(tile, [1000, 50, 1200], [4500, 50, 1200])).toEqual({ scale: [0.9, 1, 1], stretch: [null, null, null], copies: 5 });
  });
});
