import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  readStylePackManifest, resolveLookRole, resolveStylePack, splitLookRole,
  type LookFamily, type ResolvedStylePack, type StylePackContext,
} from '../src/style-pack.js';
import {
  materialOfLeaf, readSurfaceMaterials, resolveSurfaceLookRole, unknownSurfaceLeaf,
} from '../src/surface-material.js';

// Relative to web/, where the suite runs: the files a deployment ships, not copies of them.
const read = (path: string): string => readFileSync(`../assets/${path}`, 'utf8');
const CATALOG_TEXT = read('catalogs/world-kinds/surface-material.v2.json');
const materials = readSurfaceMaterials(CATALOG_TEXT);
const families = new Map<string, LookFamily>(
  (JSON.parse(read('catalogs/world-kinds/look-family.v1.json')) as { entries: { key: string; fit: LookFamily['fit']; dressing: LookFamily['dressing']; fill_minimum_permille: number; fill_maximum_permille: number }[] })
    .entries.map((entry) => [entry.key, { fit: entry.fit, dressing: entry.dressing, fillMinimumPermille: entry.fill_minimum_permille, fillMaximumPermille: entry.fill_maximum_permille }]),
);
const PACKS = ['exulanica.cozy-town', 'exulanica.finished-town', 'exulanica.toon-town'] as const;
const manifests = PACKS.map((id) => JSON.parse(read(`style-packs/packs/${id}/manifest.json`)) as { surfaces: Record<string, { texture_set?: string }> });
const context: StylePackContext = {
  families,
  textureSets: new Set(manifests.flatMap((manifest) => Object.values(manifest.surfaces).flatMap((surface) => (surface.texture_set === undefined ? [] : [surface.texture_set])))),
};
const packs = new Map<string, ResolvedStylePack>(PACKS.map((id, index) => [id, resolveStylePack([readStylePackManifest(manifests[index] as never, context)])]));
const cozy = packs.get('exulanica.cozy-town')!;
const slot = (lookRole: string) => ({ identity: 'part:00042', lookRole, positionMm: [0, 0, 0] as const, yawQuarterTurns: 0 as const, boxMm: [4000, 200, 3000] as const });
/** A pack with some surfaces more, or fewer, than the cozy town states. */
const packWith = (change: (surfaces: Record<string, ResolvedStylePack['surfaces'][string]>) => void): ResolvedStylePack => {
  const surfaces = { ...cozy.surfaces };
  change(surfaces);
  return { ...cozy, surfaces };
};

describe('the surface material catalog', () => {
  it('is read whole, each material wearable by look families that take a surface', () => {
    expect(materials.materials.length).toBeGreaterThanOrEqual(30);
    for (const material of materials.materials) {
      for (const family of material.families) {
        expect(['surface', 'both'], `${material.key} names ${family}`).toContain(families.get(family)?.dressing);
      }
      expect(material.swatch).toMatchObject({ key: `material:${material.key}`, emission_permille: 0 });
    }
    expect([...materials.families].sort()).toEqual(['boundary', 'ground', 'path', 'road', 'roof', 'wall', 'water']);
  });

  it('is version 2, which moved six colours of version 1 and nothing else; version 1 is kept beside it and still read', () => {
    const first = readSurfaceMaterials(read('catalogs/world-kinds/surface-material.v1.json'));
    expect([first.version, materials.version]).toEqual([1, 2]);
    const moved: string[] = [];
    expect(materials.materials.map((material) => material.key)).toEqual(first.materials.map((material) => material.key));
    materials.materials.forEach((material, index) => {
      const before = first.materials[index]!;
      // Everything a leaf is read by is the same in both versions: only what a material is drawn in may differ.
      expect({ ...material, swatch: null }, material.key).toEqual({ ...before, swatch: null });
      expect({ ...material.swatch, srgb8: null }, material.key).toEqual({ ...before.swatch, srgb8: null });
      if (material.swatch.srgb8.join() !== before.swatch.srgb8.join()) moved.push(material.key);
    });
    expect(moved.sort()).toEqual(['adobe', 'forest_floor', 'sand', 'soil', 'thatch', 'timber']);
  });

  it('gives no word to two materials one family may wear, so no entry is unreachable', () => {
    const taken = new Map<string, string>();
    for (const material of materials.materials) {
      for (const family of material.families) {
        for (const word of material.words) {
          const key = `${family}.${word}`;
          expect(taken.get(key), `${key} names ${taken.get(key)} and ${material.key}`).toBeUndefined();
          taken.set(key, material.key);
        }
      }
    }
  });

  it('refuses a file that is not the catalog, and an entry that is not a material, by name', () => {
    const document = JSON.parse(CATALOG_TEXT) as { catalog_id: string; entries: Record<string, unknown>[] };
    const changed = (change: (entries: Record<string, unknown>[]) => void, id = document.catalog_id): string => {
      const entries = document.entries.map((entry) => ({ ...entry }));
      change(entries);
      return JSON.stringify({ ...document, catalog_id: id, entries });
    };
    expect(() => readSurfaceMaterials(changed(() => {}, 'look-family'))).toThrow(/not the surface material catalog/);
    expect(() => readSurfaceMaterials(changed((entries) => { entries[1]!['key'] = entries[0]!['key']; }))).toThrow(/stated twice/);
    expect(() => readSurfaceMaterials(changed((entries) => { entries[0]!['srgb8'] = [0, 256, 0]; }))).toThrow(/srgb8\[1\]/);
    expect(() => readSurfaceMaterials(changed((entries) => { entries[0]!['words'] = []; }))).toThrow(/words/);
    expect(() => readSurfaceMaterials(changed((entries) => { entries[0]!['families'] = ['Ground']; }))).toThrow(/not a key/);
    expect(() => readSurfaceMaterials(changed((entries) => { entries[0]!['family_default'] = ['wall']; }))).toThrow(/may not be worn by/);
    expect(() => readSurfaceMaterials(changed((entries) => { entries[0]!['plain'] = ''; }))).toThrow(/plain/);
    expect(() => readSurfaceMaterials(changed((entries) => { entries[0]!['reason'] = ' '; }))).toThrow(/reason/);
    expect(() => readSurfaceMaterials(changed((entries) => { entries[0]!['roughness_permille'] = 1001; }))).toThrow(/roughness_permille/);
  });
});

describe('the material a leaf names', () => {
  // Every surface leaf the kind drafter wrote in the eight documents of 2026-10-10, and a few beside.
  const WRITTEN: readonly (readonly [string, string | null])[] = [
    ['ground.sand', 'sand'], ['ground.beach', 'sand'], ['ground.quay', 'paving'], ['ground.cobbles', 'cobble'],
    ['ground.forest_floor', 'forest_floor'], ['ground.clearing', 'grass'], ['ground.lake_shore', 'sand'],
    ['ground.grass', 'grass'], ['ground.wood', 'timber'], ['ground.tent_floor', 'canvas'], ['ground.metal_floor', 'metal'],
    ['ground.classroom_floor', 'floor'], ['ground.dining_floor', 'floor'], ['ground.floor', 'floor'], ['ground.tile', 'tile'],
    ['ground.wheat_field', 'crop'], ['ground.concrete', 'concrete'], ['ground.dirt', 'soil'], ['ground.playground', null],
    ['path.desert_track', 'sand'], ['path.dirt_path', 'soil'], ['path.dirt', 'soil'], ['path.quay', 'paving'],
    ['path.lane', null], ['path.corridor', null], ['path.market_aisle', null], ['path.school_path', null],
    ['water.harbour', 'harbour'], ['water.lake', 'lake'], ['water.pond', 'pond'], ['water.sea', 'sea'],
    ['wall.stone', 'stone'], ['wall.whitewash', 'plaster'], ['wall.adobe', 'adobe'], ['wall.timber', 'timber'],
    ['wall.tent', 'canvas'], ['wall.palisade', 'timber'], ['wall.metal_panel', 'metal'], ['wall.market_wall', null],
    ['roof.thatched', 'thatch'], ['roof.slate', 'slate'], ['roof.adobe', 'adobe'], ['roof.timber', 'timber'],
    ['roof.tent', 'canvas'], ['roof.tile', 'roof_tile'],
  ];

  it('is found by the leaf whole, then by its words in the order written, among what the family may wear', () => {
    for (const [role, expected] of WRITTEN) {
      const { family, leaf } = splitLookRole(role, 'role');
      expect(materialOfLeaf(materials, family, leaf)?.key ?? null, role).toBe(expected);
      expect(unknownSurfaceLeaf(materials, role), role).toBe(expected === null);
    }
  });

  it('is the whole leaf\'s before any one of its words\'', () => {
    // Two materials written for this test: one named by a compound, one by that compound's first word.
    const entry = (key: string, words: string[]) => ({ key, words, plain: key, families: ['ground'], family_default: [], srgb8: [1, 2, 3], roughness_permille: 500, metalness_permille: 0, reason: 'Written for this test.' });
    const two = readSurfaceMaterials(JSON.stringify({ catalog_id: 'surface-material', catalog_version: 1, entries: [entry('boards', ['dance']), entry('sprung', ['dance_floor'])] }));
    expect(materialOfLeaf(two, 'ground', 'dance_floor')!.key).toBe('sprung');
    expect(materialOfLeaf(two, 'ground', 'dance_hall')!.key).toBe('boards');
  });

  it('is none for a family no material serves, and a default leaf is never thrown away', () => {
    expect(materialOfLeaf(materials, 'structure', 'tent')).toBeNull();
    expect(materialOfLeaf(materials, 'fixture', 'stone_well')).toBeNull();
    expect(unknownSurfaceLeaf(materials, 'structure.tent')).toBe(false);
    expect(unknownSurfaceLeaf(materials, 'ground.default')).toBe(false);
    // The same word is a floor's tile underfoot and a clay tile on a roof; water is never ground.
    expect(materialOfLeaf(materials, 'ground', 'lake')).toBeNull();
    expect(materialOfLeaf(materials, 'ground', 'tile')!.key).not.toBe(materialOfLeaf(materials, 'roof', 'tile')!.key);
  });
});

describe('what dresses a slot of a made place', () => {
  it('is the pack\'s own dressing for the leaf wherever the pack states one, before any material', () => {
    // The cozy town states a brick wall of its own; the catalog's brick is not asked.
    const own = resolveSurfaceLookRole(cozy, slot('wall.brick_running_bond'), families, 'either', materials);
    expect(own).toEqual(resolveLookRole(cozy, slot('wall.brick_running_bond'), families, 'either'));
    expect(own).toMatchObject({ kind: 'surface', role: 'wall.brick_running_bond' });
    // And a pack that states sand itself draws its own sand.
    const sandy = packWith((surfaces) => { surfaces['ground.sand'] = surfaces['wall.default']!; });
    expect(resolveSurfaceLookRole(sandy, slot('ground.sand'), families, 'either', materials)).toMatchObject({ kind: 'surface', role: 'ground.sand' });
  });

  it('is the leaf\'s material in the catalog\'s colour where the pack states nothing for it, not the family default', () => {
    for (const [role, material] of [['ground.sand', 'sand'], ['wall.adobe', 'adobe'], ['roof.thatched', 'thatch'], ['water.harbour', 'harbour'], ['path.desert_track', 'sand']] as const) {
      const dressed = resolveSurfaceLookRole(cozy, slot(role), families, 'either', materials);
      expect(dressed, role).toMatchObject({ kind: 'material', role: `${splitLookRole(role, 'role').family}.${material}`, material: { key: material } });
      // Positive control: the plain rule gives this leaf the family's default.
      expect(resolveLookRole(cozy, slot(role), families, 'either'), role).toMatchObject({ kind: 'surface', role: `${splitLookRole(role, 'role').family}.default` });
    }
  });

  it('is the pack\'s own surface for the material where the pack states one under family.material', () => {
    const thatched = packWith((surfaces) => { surfaces['roof.thatch'] = surfaces['wall.painted_timber']!; });
    expect(resolveSurfaceLookRole(thatched, slot('roof.thatched'), families, 'either', materials))
      .toEqual(resolveLookRole(thatched, slot('roof.thatch'), families, 'surface'));
    expect(resolveSurfaceLookRole(thatched, slot('roof.thatched'), families, 'either', materials)).toMatchObject({ kind: 'surface', role: 'roof.thatch' });
  });

  it('is the pack\'s family default where the catalog says that default is the material already, and the catalog\'s colour where the pack has none', () => {
    expect(resolveSurfaceLookRole(cozy, slot('ground.grass'), families, 'either', materials)).toMatchObject({ kind: 'surface', role: 'ground.default' });
    expect(resolveSurfaceLookRole(cozy, slot('ground.clearing'), families, 'either', materials)).toMatchObject({ kind: 'surface', role: 'ground.default' });
    const bare = packWith((surfaces) => { delete surfaces['ground.default']; });
    expect(resolveSurfaceLookRole(bare, slot('ground.grass'), families, 'either', materials)).toMatchObject({ kind: 'material', role: 'ground.grass' });
  });

  it('is the plain rule\'s answer for a leaf that names no material, a default leaf, a family no material serves and a slot that takes only a piece', () => {
    for (const role of ['ground.playground', 'wall.market_wall', 'ground.default', 'structure.tent', 'fixture.well', 'door.default', 'character.default']) {
      expect(resolveSurfaceLookRole(cozy, slot(role), families, 'either', materials), role).toEqual(resolveLookRole(cozy, slot(role), families, 'either'));
    }
    for (const role of ['ground.sand', 'roof.thatched', 'door.default']) {
      expect(resolveSurfaceLookRole(cozy, slot(role), families, 'module', materials), role).toEqual(resolveLookRole(cozy, slot(role), families, 'module'));
    }
  });
});

describe('a town', () => {
  const town = JSON.parse(read('style-packs/town-look-roles.v1.json')) as { sets: Record<string, string> };
  const roles = [...new Set(Object.values(town.sets))].sort();

  it('resolves every look role its tiles take by the leaf, then the family default, in each published pack', () => {
    expect(roles.length).toBeGreaterThanOrEqual(15);
    for (const [id, pack] of packs) {
      for (const role of roles) {
        const { family } = splitLookRole(role, 'role');
        const takesSurface = ['surface', 'both'].includes(families.get(family)!.dressing);
        // Stated here apart from the rule: the leaf's own surface, else the family's default, else nothing.
        const expected = !takesSurface ? null : pack.surfaces[role] !== undefined ? role : pack.surfaces[`${family}.default`] !== undefined ? `${family}.default` : null;
        expect(resolveLookRole(pack, slot(role), families, 'surface')?.role ?? null, `${id} ${role}`).toBe(expected);
      }
    }
  });

  it('is drawn by code that never asks the material catalog', () => {
    for (const file of ['town-surfaces.ts', 'dresser.ts', 'vehicle-bodies.ts']) {
      const source = readFileSync(`packages/atlas-react/src/playcanvas/style-pack/${file}`, 'utf8');
      expect(source, file).toContain('resolveLookRole(');
      expect(source, file).not.toMatch(/resolveSurfaceLookRole|surface-material|SurfaceMaterials/);
    }
    // And the rule a town is resolved by does not know the catalog exists.
    const rule = readFileSync('packages/atlas-core/src/style-pack.ts', 'utf8');
    expect(rule).not.toMatch(/surface-material|materialOfLeaf/);
  });
});
