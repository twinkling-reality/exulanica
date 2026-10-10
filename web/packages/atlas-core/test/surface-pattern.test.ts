import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { readSurfaceMaterials } from '../src/surface-material.js';
import { SURFACE_PATTERN_KINDS, readSurfacePatterns } from '../src/surface-pattern.js';

// Relative to web/, where the suite runs: the files a deployment ships.
const TEXT = readFileSync('../assets/catalogs/world-kinds/surface-pattern.v1.json', 'utf8');
const patterns = readSurfacePatterns(TEXT);
const materials = readSurfaceMaterials(readFileSync('../assets/catalogs/world-kinds/surface-material.v2.json', 'utf8'));

describe('the surface pattern catalog', () => {
  it('patterns every surface material, each by one of the six kinds', () => {
    expect([...patterns.byMaterial.keys()].sort()).toEqual(materials.materials.map((material) => material.key).sort());
    const used = new Set([...patterns.byMaterial.values()].map((pattern) => pattern.kind));
    expect([...used].sort()).toEqual([...SURFACE_PATTERN_KINDS].sort());
  });

  it('states a second period exactly for the kinds worked from two, and sizes a person would know', () => {
    for (const pattern of patterns.byMaterial.values()) {
      expect(pattern.periodBMm !== 0, pattern.key).toBe(pattern.kind === 'courses' || pattern.kind === 'strokes');
    }
    // A brick with its joint, and a board.
    expect(patterns.byMaterial.get('brick')).toMatchObject({ kind: 'courses', periodAMm: 230, periodBMm: 76 });
    expect(patterns.byMaterial.get('timber')).toMatchObject({ kind: 'boards', periodAMm: 180 });
    expect(patterns.byMaterial.get('thatch')!.kind).toBe('strokes');
    expect(patterns.byMaterial.get('lake')!.kind).toBe('ripples');
    expect(patterns.byMaterial.get('sand')!.kind).toBe('grain');
  });

  it('refuses a file that is not the catalog, and an entry that is not a pattern, by name', () => {
    const document = JSON.parse(TEXT) as { catalog_id: string; entries: Record<string, unknown>[] };
    const changed = (change: (entry: Record<string, unknown>, all: Record<string, unknown>[]) => void, id = document.catalog_id): string => {
      const entries = document.entries.map((entry) => ({ ...entry }));
      change(entries.find((entry) => entry['key'] === 'brick')!, entries);
      return JSON.stringify({ ...document, catalog_id: id, entries });
    };
    expect(() => readSurfacePatterns(changed(() => {}, 'roof-form'))).toThrow(/not the surface pattern catalog/);
    expect(() => readSurfacePatterns(changed((_, all) => { all[1]!['key'] = all[0]!['key']; }))).toThrow(/stated twice/);
    expect(() => readSurfacePatterns(changed((entry) => { entry['kind'] = 'herringbone'; }))).toThrow(/kind/);
    expect(() => readSurfacePatterns(changed((entry) => { entry['period_b_mm'] = 0; }))).toThrow(/second period/);
    expect(() => readSurfacePatterns(changed((entry) => { entry['kind'] = 'seams'; }))).toThrow(/second period/);
    expect(() => readSurfacePatterns(changed((entry) => { entry['period_a_mm'] = 5; }))).toThrow(/period_a_mm/);
    expect(() => readSurfacePatterns(changed((entry) => { entry['period_b_mm'] = 12; }))).toThrow(/period_b_mm/);
    expect(() => readSurfacePatterns(changed((entry) => { entry['strength_permille'] = 0; }))).toThrow(/strength_permille/);
    expect(() => readSurfacePatterns(changed((entry) => { entry['strength_permille'] = 601; }))).toThrow(/strength_permille/);
    expect(() => readSurfacePatterns(changed((entry) => { entry['reason'] = ' '; }))).toThrow(/reason/);
  });
});
