import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { readStylePackManifest, resolveStylePack, type LookFamily, type ResolvedStylePack, type StylePackContext, type StylePackLightPreset } from '../src/style-pack.js';
import {
  WorldSettingRefusal,
  applyWorldSetting,
  canonicalWorldSettingBytes,
  contrastPermille,
  drawnWorldSettingBytes,
  openLight,
  readWorldSetting,
  readWorldSettingRules,
} from '../src/world-setting.js';

// Relative to web/, where the suite runs. The same files the Python reader runs (tests/test_world_settings.py).
const read = (path: string): unknown => JSON.parse(readFileSync(`../assets/${path}`, 'utf8'));
const CASES = read('style-packs/settings/setting-cases.v1.json') as {
  packs: Record<string, unknown[]>;
  cases: { name: string; pack: string; setting: unknown; expect: { sha256?: string; drawn_sha256?: string; refusal?: string; path?: string } }[];
};
const SHARED = read('style-packs/manifest-cases.v1.json') as {
  context: { families: Record<string, { fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }>; texture_sets: string[] };
};
const families = new Map<string, LookFamily>(Object.entries(SHARED.context.families).map(([key, value]) => [key, {
  fit: value.fit, dressing: value.dressing, fillMinimumPermille: value.fill_minimum_permille, fillMaximumPermille: value.fill_maximum_permille,
}]));
const context: StylePackContext = { families, textureSets: new Set(SHARED.context.texture_sets) };
const rules = readWorldSettingRules(read('style-packs/settings/setting-rules.v1.json'), read('colour/srgb8-linear16.v1.json'));
const sha256 = (bytes: Uint8Array): string => createHash('sha256').update(bytes).digest('hex');
const pack = (name: string): ResolvedStylePack => resolveStylePack(CASES.packs[name]!.map((manifest) => readStylePackManifest(manifest, context)));

describe('the shared world setting cases', () => {
  for (const testCase of CASES.cases) {
    it(testCase.name, () => {
      if (testCase.expect.sha256 !== undefined) {
        // The Python reader wrote both digests: the same canonical setting, and the same pack as drawn.
        const setting = readWorldSetting(testCase.setting, rules);
        expect(sha256(canonicalWorldSettingBytes(setting))).toBe(testCase.expect.sha256);
        expect(sha256(drawnWorldSettingBytes(applyWorldSetting(pack(testCase.pack), setting, families, rules)))).toBe(testCase.expect.drawn_sha256);
        return;
      }
      let refusal: WorldSettingRefusal | null = null;
      try {
        applyWorldSetting(pack(testCase.pack), readWorldSetting(testCase.setting, rules), families, rules);
      } catch (error) {
        if (!(error instanceof WorldSettingRefusal)) throw error;
        refusal = error;
      }
      expect(refusal, 'the setting was accepted').not.toBeNull();
      expect({ reason: refusal!.reason, path: refusal!.path }).toEqual({ reason: testCase.expect.refusal, path: testCase.expect.path });
    });
  }

  it('cover a valid setting and every refusal reason', () => {
    expect(new Set(CASES.cases.map((c) => c.expect.refusal ?? 'valid'))).toEqual(new Set(['valid', 'shape', 'range', 'reference', 'duplicate', 'legibility']));
  });
});

describe('a setting applied to a pack', () => {
  const town = pack('town');
  const named = (name: string) => readWorldSetting(CASES.cases.find((c) => c.name === name)!.setting, rules);

  it('is a resolved pack whose default preset is the one the setting changes, so a caller draws it as any pack', () => {
    const applied = applyWorldSetting(town, named("the look's own evening preset, unchanged"), families, rules);
    expect(applied.light.default_preset).toBe('evening');
    expect(applied.light.presets['evening']).toEqual(town.light.presets['evening']);
    // What a setting never states is the pack's, the same objects.
    expect(applied.chain).toBe(town.chain);
    expect(applied.modules).toBe(town.modules);
    expect(applied.shading).toBe(town.shading);
  });

  it('leaves the pack it was given as it was', () => {
    const before = sha256(drawnWorldSettingBytes(town));
    applyWorldSetting(town, named('roles coloured: one the look colours, one it draws from a texture set, one it leaves undressed'), families, rules);
    applyWorldSetting(town, named('a sky: the day preset with its sun, sky, clouds and fog changed'), families, rules);
    expect(sha256(drawnWorldSettingBytes(town))).toBe(before);
  });

  it('draws a role the look draws from a texture set in the colour the setting states', () => {
    const applied = applyWorldSetting(town, named('roles coloured: one the look colours, one it draws from a texture set, one it leaves undressed'), families, rules);
    expect('texture_set' in town.surfaces['ground.tree_pit_soil']!).toBe(true);
    const surface = applied.surfaces['ground.tree_pit_soil']!;
    expect('swatch' in surface && applied.swatches.get(surface.swatch)?.srgb8).toEqual([228, 208, 164]);
    // A role the look left to its family's default is dressed too, and a restated swatch keeps its other values.
    expect(town.surfaces['ground.default']).toBeUndefined();
    expect(applied.surfaces['ground.default']).toBeDefined();
    const lit = applyWorldSetting(town, named('swatches restated: an emission alone, a colour alone, both'), families, rules);
    expect(lit.swatches.get('glass_lit')).toEqual({ ...town.swatches.get('glass_lit')!, emission_permille: 1000 });
  });
});

describe('the legibility figures', () => {
  it('open light is the sun on level ground and the sky through the exposure', () => {
    // By hand, as tests/test_world_settings.py: white's luminance is 65535, and Bhaskara's sine of 85 degrees is 996 per mille.
    const day = (CASES.packs['town']![0] as { light: { presets: Record<string, StylePackLightPreset> } }).light.presets['day']!;
    const preset: StylePackLightPreset = {
      ...day, exposure_permille: 1000,
      sun: { ...day.sun, elevation_mdeg: 85_000, colour: [255, 255, 255], intensity_permille: 1000 },
      sky: { ...day.sky, zenith: [255, 255, 255], horizon: [255, 255, 255], intensity_permille: 1000 },
      environment: { intensity_permille: 1000 },
    };
    expect(openLight(preset, rules)).toBe(Math.floor((65535 * 996) / 1000) + 65535);
  });

  it('contrast is the lighter over the darker, each raised a twentieth of white', () => {
    expect(contrastPermille([255, 255, 255], [0, 0, 0], rules)).toBe(20998);
    expect(contrastPermille([90, 120, 30], [90, 120, 30], rules)).toBe(1000);
  });
});
