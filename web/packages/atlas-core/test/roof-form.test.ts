import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { readRoofForms } from '../src/roof-form.js';
import { readSurfaceMaterials } from '../src/surface-material.js';

// Relative to web/, where the suite runs: the files a deployment ships.
const TEXT = readFileSync('../assets/catalogs/world-kinds/roof-form.v1.json', 'utf8');
const forms = readRoofForms(TEXT);
const materials = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v2.json', 'utf8'));

describe('the roof form catalog', () => {
  it('shapes roofs of materials a roof may wear, each a ridge, a slab or both', () => {
    expect(forms.byMaterial.size).toBeGreaterThanOrEqual(6);
    for (const form of forms.byMaterial.values()) {
      const material = materials.materials.find((one) => one.key === form.key);
      expect(material?.families, form.key).toContain('roof');
      expect(form.ridge !== null || form.slab !== null, form.key).toBe(true);
    }
  });

  it('states a tent as a ridge that runs to the ground along the way the door faces, and thatch steeper and deeper than slate', () => {
    expect(forms.byMaterial.get('canvas')!.ridge).toMatchObject({ eaves: 'ground', runs: 'door_axis', overhangMm: 0 });
    const thatch = forms.byMaterial.get('thatch')!.ridge!;
    const slate = forms.byMaterial.get('slate')!.ridge!;
    expect(thatch.pitchPermille).toBeGreaterThan(slate.pitchPermille);
    expect(thatch.overhangMm).toBeGreaterThan(slate.overhangMm);
    expect(thatch.thicknessMm).toBeGreaterThan(slate.thicknessMm);
    // An earth roof is a slab with a parapet, and shapes no ridge.
    expect(forms.byMaterial.get('adobe')).toMatchObject({ ridge: null, slab: { parapetMm: 450 } });
  });

  it('refuses a file that is not the catalog, and an entry that shapes nothing or contradicts itself, by name', () => {
    const document = JSON.parse(TEXT) as { catalog_id: string; entries: Record<string, unknown>[] };
    const changed = (change: (entry: Record<string, unknown>, all: Record<string, unknown>[]) => void, id = document.catalog_id): string => {
      const entries = document.entries.map((entry) => ({ ...entry }));
      change(entries.find((entry) => entry['key'] === 'thatch')!, entries);
      return JSON.stringify({ ...document, catalog_id: id, entries });
    };
    expect(() => readRoofForms(changed(() => {}, 'surface-material'))).toThrow(/not the roof form catalog/);
    expect(() => readRoofForms(changed((_, all) => { all[1]!['key'] = all[0]!['key']; }))).toThrow(/stated twice/);
    expect(() => readRoofForms(changed((entry) => { entry['ridge_pitch_permille'] = 0; }))).toThrow(/ridge with no pitch/);
    expect(() => readRoofForms(changed((entry) => { entry['ridge_eaves'] = 'ground'; }))).toThrow(/runs to the ground/);
    expect(() => readRoofForms(changed((entry) => { entry['ridge_runs'] = 'sideways'; }))).toThrow(/ridge_runs/);
    expect(() => readRoofForms(changed((entry) => { entry['ridge_eaves'] = 'cloud'; }))).toThrow(/wall or ground/);
    expect(() => readRoofForms(changed((entry) => { entry['slab_parapet_mm'] = 300; }))).toThrow(/parapet/);
    expect(() => readRoofForms(changed((entry) => { entry['ridge_overhang_mm'] = -1; }))).toThrow(/ridge_overhang_mm/);
    expect(() => readRoofForms(changed((entry) => { entry['reason'] = ''; }))).toThrow(/reason/);
    expect(() => readRoofForms(changed((entry) => { Object.assign(entry, { ridge_pitch_permille: 0, ridge_overhang_mm: 0, ridge_thickness_mm: 0, ridge_runs: 'as_served' }); }))).toThrow(/shapes nothing/);
  });
});
