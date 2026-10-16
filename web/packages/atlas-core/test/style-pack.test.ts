import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  STYLE_PACK_MAX_REPEAT_COPIES,
  StylePackRefusal,
  canonicalJson,
  canonicalStylePackBytes,
  fit,
  readStylePackManifest,
  repeatCoordinate,
  repeatPart,
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
  it('refuses textures of 65 pictures of their own with the message it always gave, and counts a picture once by its digest', () => {
    const refused = (): unknown => readStylePackManifest(CASES.cases.find((c) => c.name.startsWith('textures drawing with 65'))!.manifest, context);
    expect(refused).toThrow(new StylePackRefusal('range', 'files', 'draws with 65 pictures; at most 64'));
    expect(() => named('65 texture map files carrying 64 pictures, one picture in two files')).not.toThrow();
  });
});

describe('a variant that repeats a zone', () => {
  const base = CASES.cases[0]!;
  const window = (stretch: unknown, repeat: unknown): unknown => {
    const manifest = structuredClone(base.manifest) as { modules: Record<string, { variants: Record<string, unknown>[] }> };
    Object.assign(manifest.modules['window.default']!.variants[0]!, { stretch_mm: stretch, repeat_mm: repeat });
    return manifest;
  };
  const refusal = (manifest: unknown): { reason: string; path: string } | null => {
    try {
      readStylePackManifest(manifest, context);
      return null;
    } catch (error) {
      if (!(error instanceof StylePackRefusal)) throw error;
      return { reason: error.reason, path: error.path };
    }
  };
  it('is read on a fill family, and a variant stating none keeps its bytes', () => {
    const read = readStylePackManifest(window([null, [40, 80], null], [[60, 940], null, [60, 1540]]), context);
    expect(read.modules['window.default']!.variants[0]!.repeat_mm).toEqual([[60, 940], null, [60, 1540]]);
    expect(sha256(canonicalStylePackBytes(readStylePackManifest(base.manifest, context)))).toBe(base.expect.sha256);
  });
  it('is refused as the Python reader refuses it, by reason and path', () => {
    const car = structuredClone(base.manifest) as { modules: Record<string, { variants: Record<string, unknown>[] }> };
    car.modules['vehicle.car']!.variants[0]!['repeat_mm'] = [[500, 3700], null, null];
    expect(refusal(car)).toEqual({ reason: 'reference', path: 'modules.vehicle.car.variants[0].repeat_mm' });
    expect(refusal(window([null, [40, 80], null], [[60, 1100], null, null]))).toEqual({ reason: 'range', path: 'modules.window.default.variants[0].repeat_mm[0]' });
    expect(refusal(window([null, [40, 80], null], [[500, 500], null, null]))).toEqual({ reason: 'range', path: 'modules.window.default.variants[0].repeat_mm[0]' });
    expect(refusal(window([null, [40, 80], null], [null, [40, 80], null]))).toEqual({ reason: 'shape', path: 'modules.window.default.variants[0].repeat_mm[1]' });
    expect(refusal(window([null, [40, 80], null], [[60, 940]]))).toEqual({ reason: 'shape', path: 'modules.window.default.variants[0].repeat_mm' });
  });
});

describe('a climb rule', () => {
  const base = CASES.cases[0]!;
  const structured: StylePackContext = { ...context, families: new Map([...families, ['structure', { fit: 'contain', dressing: 'both', fillMinimumPermille: 0, fillMaximumPermille: 0 }]]) };
  const RULE = { pieces: ['plant.ivy'], walls: ['back', 'left', 'right'], sun_within_mdeg: 100_000, share_permille: 400, height_permille: [300, 700], seed: 7 };
  const withPlant = (rule: Record<string, unknown>, role = 'structure.default'): unknown => {
    const manifest = structuredClone(base.manifest) as { modules: Record<string, unknown>; climb?: unknown };
    manifest.modules['plant.ivy'] = structuredClone(manifest.modules['vehicle.car']);
    manifest.climb = { [role]: rule };
    return manifest;
  };
  const refusal = (manifest: unknown): { reason: string; path: string } | null => {
    try {
      readStylePackManifest(manifest, structured);
      return null;
    } catch (error) {
      if (!(error instanceof StylePackRefusal)) throw error;
      return { reason: error.reason, path: error.path };
    }
  };
  it('is read on a structure\'s walls, and a pack stating none keeps its bytes', () => {
    expect(readStylePackManifest(withPlant(RULE), structured).climb).toEqual({ 'structure.default': RULE });
    const read = resolveStylePack([readStylePackManifest(withPlant(RULE), structured)]);
    expect(read.climb['structure.default']!.walls).toEqual(['back', 'left', 'right']);
    expect(resolveStylePack([readStylePackManifest(base.manifest, context)]).climb).toEqual({});
  });
  it('is refused as the Python reader refuses it, by reason and path', () => {
    expect(refusal(withPlant(RULE, 'fixture.bench'))).toEqual({ reason: 'reference', path: 'climb.fixture.bench' });
    expect(refusal(withPlant({ ...RULE, pieces: ['vehicle.car'] }))).toEqual({ reason: 'reference', path: 'climb.structure.default.pieces[0]' });
    expect(refusal(withPlant({ ...RULE, walls: ['back', 'back'] }))).toEqual({ reason: 'duplicate', path: 'climb.structure.default.walls' });
    expect(refusal(withPlant({ ...RULE, walls: ['roof'] }))).toEqual({ reason: 'range', path: 'climb.structure.default.walls[0]' });
    expect(refusal(withPlant({ ...RULE, walls: [] }))).toEqual({ reason: 'range', path: 'climb.structure.default.walls' });
    expect(refusal(withPlant({ ...RULE, height_permille: [800, 200] }))).toEqual({ reason: 'range', path: 'climb.structure.default.height_permille' });
    expect(refusal(withPlant({ ...RULE, sun_within_mdeg: 180_001 }))).toEqual({ reason: 'range', path: 'climb.structure.default.sun_within_mdeg' });
    expect(refusal(withPlant({ ...RULE, share_permille: 0 }))).toEqual({ reason: 'range', path: 'climb.structure.default.share_permille' });
    expect(refusal(withPlant({ ...RULE, spread: 3 }))).toEqual({ reason: 'shape', path: 'climb.structure.default' });
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
    expect(fit(contain, [2000, 1000, 1000], [1000, 1000, 1000])).toEqual({ scale: [0.5, 0.5, 0.5], stretch: [null, null, null], repeat: [null, null, null], copies: 1 });
  });
  it('fills each axis within 0.8 to 1.25, else refuses', () => {
    expect(fit(fill, [1000, 100, 2000], [1200, 100, 1800])).toEqual({ scale: [1.2, 0.9, 1], stretch: [null, null, null], repeat: [null, null, null], copies: 1 });
    expect(fit(fill, [1000, 100, 2000], [1300, 100, 1800])).toBeNull();
    expect(fit(fill, [1000, 100, 2000], [1000, 79, 2000])).toBeNull();
  });
  it('stretches a stated zone to any length the slot leaves it, and scales the other axes within bounds', () => {
    // Width stretches between 100 and 900; depth and height scale.
    expect(fit(fill, [1000, 100, 2000], [3000, 110, 1800], [[100, 900], null, null])).toEqual({
      scale: [1, 0.9, 1.1], stretch: [{ low: 100, high: 900, length: 2800, box: 3000 }, null, null], repeat: [null, null, null], copies: 1,
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
  it('repeats a zone as many whole times as leaves each copy nearest its own size, within bounds', () => {
    // A 5 m piece whose middle 3.8 m repeats (600 mm ends): 20 m leaves 18.8 m, 4.95 zones, so five
    // copies at 0.989 rather than four at 1.237; depth and height scale.
    const fitted = fit(fill, [5000, 100, 2000], [20000, 110, 1800], [null, null, null], [[600, 4400], null, null])!;
    expect(fitted.scale).toEqual([1, 0.9, 1.1]);
    expect(fitted.stretch).toEqual([null, null, null]);
    expect(fitted.repeat[0]).toMatchObject({ low: 600, high: 4400, copies: 5, box: 20000 });
    expect(fitted.repeat[0]!.scale).toBeCloseTo(18800 / 19000, 12);
    expect(fitted.repeat.slice(1)).toEqual([null, null]);
    // Height repeats on glTF y: size and box index 2.
    expect(fit(fill, [5000, 100, 2000], [5000, 100, 6000], [null, null, null], [null, null, [500, 1500]])!.repeat)
      .toMatchObject([null, { copies: 5, scale: 1 }, null]);
    // A box no larger than the fixed ends leaves the zone no room; one copy at half its size is past the bound.
    expect(fit(fill, [5000, 100, 2000], [1200, 100, 2000], [null, null, null], [[600, 4400], null, null])).toBeNull();
    expect(fit(fill, [5000, 100, 2000], [3200, 100, 2000], [null, null, null], [[600, 4400], null, null])).toBeNull();
    // The repeat leaves the other axes to their own rule: 1300 deep against 100 is still refused.
    expect(fit(fill, [5000, 100, 2000], [20000, 1300, 2000], [null, null, null], [[600, 4400], null, null])).toBeNull();
  });
  it('draws a zone at most the profile\'s number of times', () => {
    // A 100 mm zone in 7 m of room takes the most copies, 64, each 1.094 long; in 10 m, 64 would be 1.56: refused.
    expect(fit(fill, [300, 100, 2000], [7200, 100, 2000], [null, null, null], [[100, 200], null, null])!.repeat[0])
      .toMatchObject({ copies: STYLE_PACK_MAX_REPEAT_COPIES });
    expect(fit(fill, [300, 100, 2000], [10200, 100, 2000], [null, null, null], [[100, 200], null, null])).toBeNull();
  });
  it('repeats up a copy a storey where the building states its storey height, else as before', () => {
    // A storey spanning the piece's height in a 6 m building of five 1200 mm storeys: five copies,
    // each a storey tall, where the piece's own 1 m storey alone takes six.
    const whole = [null, null, [0, 1000]] as const;
    expect(fit(fill, [5000, 100, 1000], [5000, 100, 6000], [null, null, null], whole, 1200)!.repeat[1]).toMatchObject({ copies: 5, scale: 1.2 });
    expect(fit(fill, [5000, 100, 1000], [5000, 100, 6000], [null, null, null], whole)!.repeat[1]).toMatchObject({ copies: 6, scale: 1 });
    // A 900 mm storey between a 500 mm base and a 500 mm top, together one of a 6 m building's six
    // 1000 mm storeys: five copies, each exactly a storey, where alone it takes six at 926 per mille.
    const between = [null, null, [500, 1400]] as const;
    const storeyed = fit(fill, [5000, 100, 1900], [5000, 100, 6000], [null, null, null], between, 1000)!.repeat[1]!;
    expect(storeyed.copies).toBe(5);
    expect(storeyed.scale * 900).toBeCloseTo(1000, 9);
    expect(fit(fill, [5000, 100, 1900], [5000, 100, 6000], [null, null, null], between)!.repeat[1]).toMatchObject({ copies: 6 });
    // Three 2000 mm storeys would stretch each copy past the bound: the piece keeps its own count.
    expect(fit(fill, [5000, 100, 1900], [5000, 100, 6000], [null, null, null], between, 2000))
      .toEqual(fit(fill, [5000, 100, 1900], [5000, 100, 6000], [null, null, null], between));
    // A storey height counts only up: two 4700 mm storeys leave the 20 m front its five bays, not four.
    expect(fit(fill, [5000, 100, 2000], [20000, 100, 9400], [null, null, null], [[600, 4400], null, [500, 1500]], 4700)!.repeat[0])
      .toMatchObject({ copies: 5 });
  });
  it('repeats across a copy a bay where the building states its arcade\'s bays, else as before', () => {
    // A 12 m front's arcade: four bays of 2900 mm between its 200 mm end walls. A 2.4 m bay between
    // 200 mm ends draws four copies, each exactly a served bay, where alone it takes five.
    const across = [[200, 2600], null, null] as const;
    const arcaded = fit(fill, [2800, 100, 2000], [12000, 100, 2000], [null, null, null], across, undefined, 4)!.repeat[0]!;
    expect(arcaded.copies).toBe(4);
    expect(arcaded.scale * 2400).toBeCloseTo(2900, 9);
    expect(fit(fill, [2800, 100, 2000], [12000, 100, 2000], [null, null, null], across)!.repeat[0]).toMatchObject({ copies: 5 });
    // The 3.8 m bay of a 20 m front takes the stated bays whichever way they lie from its own five.
    const wide = [[600, 4400], null, null] as const;
    expect(fit(fill, [5000, 100, 2000], [20000, 100, 2000], [null, null, null], wide, undefined, 4)!.repeat[0]).toMatchObject({ copies: 4 });
    expect(fit(fill, [5000, 100, 2000], [20000, 100, 2000], [null, null, null], wide, undefined, 6)!.repeat[0]).toMatchObject({ copies: 6 });
    // Three bays would stretch each copy past the bound: the piece keeps its own count.
    expect(fit(fill, [5000, 100, 2000], [20000, 100, 2000], [null, null, null], wide, undefined, 3))
      .toEqual(fit(fill, [5000, 100, 2000], [20000, 100, 2000], [null, null, null], wide));
    // Seventy bays are past the profile's most copies: the piece keeps its own count, the most.
    expect(fit(fill, [300, 100, 2000], [7200, 100, 2000], [null, null, null], [[100, 200], null, null], undefined, 70)!.repeat[0])
      .toMatchObject({ copies: STYLE_PACK_MAX_REPEAT_COPIES });
    // Bays count only across: a 6 m storey repeat keeps its five storeys with four bays stated.
    expect(fit(fill, [5000, 100, 2000], [5000, 100, 6000], [null, null, null], [null, null, [500, 1500]], undefined, 4)!.repeat[1])
      .toMatchObject({ copies: 5, scale: 1 });
  });
  it('places each part of a repeated axis: below in place, each copy along, above after the last', () => {
    const repeat = { low: 600, high: 4400, copies: 5, scale: 18800 / 19000, box: 20000 };
    expect([0, 599, 600, 4400, 4401].map((p) => repeatPart(repeat, p))).toEqual([-1, -1, 0, 0, 1]);
    expect(repeatCoordinate(repeat, 0, -1, 0)).toBe(0);
    expect(repeatCoordinate(repeat, 600, 0, 0)).toBeCloseTo(600, 9);
    // The last copy's high edge and the part above it meet at the same place: no gap, no overlap.
    expect(repeatCoordinate(repeat, 4400, 0, 4)).toBeCloseTo(19400, 9);
    expect(repeatCoordinate(repeat, 4400, 1, 0)).toBeCloseTo(19400, 9);
    expect(repeatCoordinate(repeat, 5000, 1, 0)).toBeCloseTo(20000, 9);
    // Copy k's low edge is copy k-1's high edge.
    expect(repeatCoordinate(repeat, 600, 0, 3)).toBeCloseTo(repeatCoordinate(repeat, 4400, 0, 2), 9);
  });
  it('tiles copies along the width, each scaled to share it exactly', () => {
    // 4,500 mm of fence from 1,000 mm panels: 5 copies (4.5 rounds to 5... by Math.round: 5), each 0.9 wide.
    expect(fit(tile, [1000, 50, 1200], [4500, 50, 1200])).toEqual({ scale: [0.9, 1, 1], stretch: [null, null, null], repeat: [null, null, null], copies: 5 });
  });
});
