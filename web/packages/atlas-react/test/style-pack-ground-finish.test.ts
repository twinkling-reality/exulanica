// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { withBorder } from '../src/playcanvas/style-pack/border-material.js';
import { FINISH_WATERS_MOST, applySeaFinish, finishRuns, readSurfaceFinish, setFinishWaters, withFinish, type WaterRect } from '../src/playcanvas/style-pack/ground-finish.js';
import * as pc from 'playcanvas';

/*
 * The surface finish is read from its catalog, refused by what is wrong with it, and set after a
 * material's own colour function without replacing it, so a pattern, an up swatch and a ground
 * border keep working whatever order they are set in.
 */

const CATALOG = JSON.parse(readFileSync('../assets/catalogs/world-kinds/surface-finish.v1.json', 'utf8')) as {
  profile: string;
  entries: { key: string; value: number; unit: string; class: string; reason: string }[];
};
const stated = (key: string) => CATALOG.entries.find((entry) => entry.key === key)!.value;

describe('the surface finish catalog', () => {
  it('is read figure for figure, every figure with a class and a reason', () => {
    const finish = readSurfaceFinish(CATALOG);
    expect(finish.groundVariation).toBe(stated('ground_variation_share'));
    expect(finish.wetBandM).toBe(stated('wet_band_m'));
    expect(finish.waterDeepM).toBe(stated('water_deep_m'));
    expect(finish.reflectionStrength).toBe(stated('reflection_strength_share'));
    expect(Object.keys(finish)).toHaveLength(CATALOG.entries.length);
    for (const entry of CATALOG.entries) expect([entry.key, entry.reason.length > 0, entry.class]).toEqual([entry.key, true, 'chosen_default']);
  });

  it('refuses another profile, an entry it does not read, a wrong unit, a figure out of range, a missing reason and a missing entry', () => {
    const changed = (edit: (doc: typeof CATALOG) => void) => {
      const doc = JSON.parse(JSON.stringify(CATALOG)) as typeof CATALOG;
      edit(doc);
      return () => readSurfaceFinish(doc);
    };
    expect(changed((doc) => { doc.profile = 'exulanica.surface-finish/v0'; })).toThrow(/is not exulanica.surface-finish\/v1/);
    expect(changed((doc) => { doc.entries.push({ ...doc.entries[0]!, key: 'glow_share' }); })).toThrow(/does not read: glow_share/);
    expect(changed((doc) => { doc.entries[0]!.unit = 'metre'; })).toThrow(/is not in share/);
    expect(changed((doc) => { doc.entries[0]!.value = 0.9; })).toThrow(/is not a figure from 0 to 0.5/);
    expect(changed((doc) => { doc.entries.find((e) => e.key === 'reflection_size_px')!.value = 300.5; })).toThrow(/whole figure/);
    expect(changed((doc) => { doc.entries[1]!.reason = ''; })).toThrow(/no class or no reason/);
    expect(changed((doc) => { doc.entries.pop(); })).toThrow(/states no /);
  });
});

/** A colour chunk shaped as the swatch, pattern and engine chunks are: one colour function. */
const CHUNK = 'uniform vec3 material_diffuse;\nvoid getAlbedo() {\n\tdAlbedo = material_diffuse.rgb;\n}\n';
const count = (text: string, of: string) => text.split(of).length - 1;

describe('a finish set into a colour chunk', () => {
  it('renames the chunk\'s own colour function and calls it first, leaving one colour function', () => {
    const ground = withFinish(CHUNK, 'ground');
    expect(count(ground, 'void getAlbedo() {')).toBe(1);
    expect(count(ground, 'void exuFinishBase() {')).toBe(1);
    expect(ground.indexOf('exuFinishBase();')).toBeGreaterThan(ground.indexOf('void getAlbedo() {'));
    expect(ground).toContain('dAlbedo = material_diffuse.rgb;');
    const water = withFinish(CHUNK, 'water');
    expect(water).toContain('uniform vec4 exuFinishWaterTone;');
    expect(water).not.toContain('uniform vec4 exuFinishGround;');
  });

  it('is set once, and composes with a ground border in either order', () => {
    expect(withFinish(withFinish(CHUNK, 'ground'), 'ground')).toBe(withFinish(CHUNK, 'ground'));
    for (const both of [withBorder(withFinish(CHUNK, 'ground')), withFinish(withBorder(CHUNK), 'ground')]) {
      expect(count(both, 'void getAlbedo() {')).toBe(1);
      expect(count(both, 'exuBorderCut();')).toBe(1);
      expect(count(both, 'exuFinishBase();')).toBe(1);
      expect(count(both, 'uniform vec4 exuFinishGround;')).toBe(1);
    }
  });

  it('refuses a chunk with no one colour function, as a finish set into nothing would draw none', () => {
    expect(() => withFinish('void getEmission() {}', 'ground')).toThrow(/no one colour function/);
  });
});

describe('the waters a finish measures from', () => {
  const material = () => {
    const values = new Map<string, unknown>();
    return { values, setParameter: (name: string, value: unknown) => values.set(name, value) };
  };

  it('are the largest few, each its rectangle, and the rest off', () => {
    const rects: WaterRect[] = Array.from({ length: FINISH_WATERS_MOST + 2 }, (_, i) => [0, 0, i + 1, 1]);
    const held = material();
    setFinishWaters(held as never, rects);
    expect(held.values.get('exuFinishWaterCount')).toBe(FINISH_WATERS_MOST);
    expect(held.values.get('exuFinishWater0')).toEqual([0, 0, FINISH_WATERS_MOST + 2, 1]);
    const none = material();
    setFinishWaters(none as never, []);
    expect(none.values.get('exuFinishWaterCount')).toBe(0);
    expect(none.values.get(`exuFinishWater${FINISH_WATERS_MOST - 1}`)).toEqual([0, 0, 0, 0]);
  });

  it('are measured only on the WebGL2 device the finish is written for', () => {
    expect(finishRuns({ isWebGPU: false } as never)).toBe(true);
    expect(finishRuns({ isWebGPU: true } as never)).toBe(false);
  });
});

const CATALOG_V2 = JSON.parse(readFileSync('../assets/catalogs/world-kinds/surface-finish.v2.json', 'utf8')) as typeof CATALOG;

describe('the surface finish catalog, version 2', () => {
  it('reads version 1 figure for figure with the sea and lakes of land at their depths, and version 1 with none', () => {
    const v2 = readSurfaceFinish(CATALOG_V2);
    const stated2 = (key: string) => CATALOG_V2.entries.find((entry) => entry.key === key)!.value;
    expect(v2.waterDepthFullM).toBe(stated2('water_depth_full_m'));
    expect(v2.waterShoreFadeM).toBe(stated2('water_shore_fade_m'));
    expect(Object.keys(v2)).toHaveLength(CATALOG_V2.entries.length);
    // Every version 1 figure is the same in version 2.
    const v1 = readSurfaceFinish(CATALOG);
    expect({ ...v2, waterDepthFullM: undefined, waterShoreFadeM: undefined }).toEqual({ ...v1, waterDepthFullM: undefined, waterShoreFadeM: undefined });
    expect(v1.waterDepthFullM).toBeUndefined();
  });

  it('refuses a depth figure in version 1, and version 2 without one', () => {
    const extra = CATALOG_V2.entries.find((entry) => entry.key === 'water_shore_fade_m')!;
    expect(() => readSurfaceFinish({ ...CATALOG, entries: [...CATALOG.entries, extra] })).toThrow(/does not read: water_shore_fade_m/);
    expect(() => readSurfaceFinish({ ...CATALOG_V2, entries: CATALOG_V2.entries.filter((entry) => entry !== extra) })).toThrow(/states no water_shore_fade_m/);
    expect(() => readSurfaceFinish({ ...CATALOG_V2, entries: CATALOG_V2.entries.map((entry) => (entry === extra ? { ...entry, value: 3 } : entry)) })).toThrow(/water_shore_fade_m is not a figure from 0 to 2/);
  });
});

describe('the sea and lakes of a site on land', () => {
  it('take their depth from the scene behind them, never its colour, and keep one colour function', () => {
    const sea = withFinish(CHUNK, 'sea');
    expect(count(sea, 'void getAlbedo() {')).toBe(1);
    expect(sea).toContain('smoothstep(0.0, exuFinishSea.x, exuSeaDepth())');
    expect(sea).not.toContain('exuFinishDepth(p))');
    expect(sea).toContain('#include "screenDepthPS"');
    expect(sea).not.toContain('uSceneColorMap');
    // Set once: a chunk that carries it is left as it is.
    expect(withFinish(sea, 'sea')).toBe(sea);
  });

  it('are blended over the scene and fade in at their shore, and are left as they are with no depth figures', () => {
    const device = new pc.NullGraphicsDevice(document.createElement('canvas'));
    // A material with its own colour chunk, as a pack's swatch has.
    const material = new pc.StandardMaterial();
    material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).set('diffusePS', CHUNK);
    expect(applySeaFinish(device, material, readSurfaceFinish(CATALOG_V2))).toBe(true);
    const glsl = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
    expect(glsl.get('opacityPS')).toContain('dAlpha = smoothstep(0.0, max(exuFinishSea.y, 0.0001), exuSeaDepth());');
    // The depth helper is declared once, whichever chunk comes first.
    for (const chunk of [glsl.get('opacityPS')!, glsl.get('diffusePS')!]) expect(chunk).toContain('#ifndef EXU_SEA_DEPTH');
    expect(material.blendType).toBe(pc.BLEND_NORMAL);
    expect(material.depthWrite).toBe(false);
    const plain = new pc.StandardMaterial();
    expect(applySeaFinish(device, plain, readSurfaceFinish(CATALOG))).toBe(false);
    expect(plain.getShaderChunks(pc.SHADERLANGUAGE_GLSL).has('opacityPS')).toBe(false);
    expect(plain.blendType).toBe(pc.BLEND_NONE);
  });
});
