import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  applyWorldSetting,
  readStylePackManifest,
  readWorldSetting,
  readWorldSettingRules,
  resolveStylePack,
  type LookFamily,
  type ResolvedStylePack,
  type WorldSetting,
} from '@exulanica/atlas-core';
import { renderSkyRadiance } from '../src/playcanvas/generated-tile/sky.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/index.js';

/**
 * The named parts of a world's setting, drawn over every committed look.
 *
 * The page never composes a setting: the server does. `setting-composed.v1.json` is what it
 * composes for each committed look (written by scripts/style_packs/composed_settings.py and held to
 * it by tests/test_world_settings.py), read here from the file. Each is applied to its look by the
 * browser's reader, becomes a render look the renderer accepts, and is held to the rule every look's
 * own light is held to (style-pack-authored.test.ts): a surface in shade is lit at most twice as blue
 * as red, so a shaded street never reads navy.
 */

// Relative to web/, where the suite runs.
const read = (path: string): unknown => JSON.parse(readFileSync(`../assets/${path}`, 'utf8'));
const families = new Map<string, LookFamily>((read('catalogs/world-kinds/look-family.v1.json') as {
  entries: { key: string; fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }[];
}).entries.map((entry) => [entry.key, { fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille }]));
const textureSets = new Set((read('textures/manifest.json') as { sets: { set_id: string }[] }).sets.map((set) => set.set_id));
const rules = readWorldSettingRules(read('style-packs/settings/setting-rules.v1.json'), read('colour/srgb8-linear16.v1.json'));
const COMPOSED = (read('style-packs/settings/setting-composed.v1.json') as {
  composed: { pack_id: string; parts: Record<string, string>; setting: unknown }[];
}).composed;
const packs = new Map<string, ResolvedStylePack>();
const packOf = (packId: string): ResolvedStylePack => {
  let pack = packs.get(packId);
  if (pack === undefined) {
    pack = resolveStylePack([readStylePackManifest(read(`style-packs/packs/${packId}/manifest.json`), { families, textureSets })]);
    packs.set(packId, pack);
  }
  return pack;
};
const named = (row: { pack_id: string; parts: Record<string, string> }): string =>
  `${row.pack_id.split('.')[1]} ${Object.entries(row.parts).map(([axis, key]) => `${axis}=${key}`).join(' ')}`;

/** How much bluer than red the sky lights an upward surface the sun does not reach, as the renderer lights with it. */
function shadeBlueOverRed(pack: ResolvedStylePack): number {
  const look = renderLookOfPreset(pack.light.presets[pack.light.default_preset]!, pack.shading, pack.edge);
  let red = 0;
  let blue = 0;
  for (let i = 0; i < 64; i += 1) {
    const theta = ((i + 0.5) / 64) * (Math.PI / 2);
    for (let j = 0; j < 256; j += 1) {
      const phi = ((j + 0.5) / 256) * 2 * Math.PI;
      const radiance = renderSkyRadiance(look, [Math.sin(theta) * Math.cos(phi), Math.cos(theta), Math.sin(theta) * Math.sin(phi)], true);
      red += radiance[0] * Math.cos(theta) * Math.sin(theta);
      blue += radiance[2] * Math.cos(theta) * Math.sin(theta);
    }
  }
  return blue / red;
}

describe('the named parts of a setting, composed for every committed look', () => {
  it('cover every look and every part, alone and one of each axis together', () => {
    const listed = (read('style-packs/settings/setting-parts.v1.json') as { parts: unknown[] }).parts.length;
    const looks = new Set(COMPOSED.map((row) => row.pack_id));
    expect(looks.size).toBeGreaterThanOrEqual(3);
    expect(COMPOSED.length).toBe(looks.size * (listed + 1));
  });

  for (const row of COMPOSED) {
    it(`${named(row)} is drawn by the browser's reader in light the renderer accepts, never navy in shade`, () => {
      const setting: WorldSetting = readWorldSetting(row.setting, rules);
      const applied = applyWorldSetting(packOf(row.pack_id), setting, families, rules);
      // renderLookOfPreset validates the render look, so a setting the renderer would refuse throws here.
      expect(shadeBlueOverRed(applied), named(row)).toBeLessThanOrEqual(2);
    });
  }
});
