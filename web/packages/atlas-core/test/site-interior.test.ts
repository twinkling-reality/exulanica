import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { readSiteInterior } from '../src/site-interior.js';

// Relative to web/, where the suite runs: the file a deployment ships.
const text = readFileSync('../assets/catalogs/world-kinds/site-interior.v1.json', 'utf8');

describe('the site interior catalog', () => {
  it('states an indoor place\'s ceiling and the light under it, each a figure a person can check', () => {
    const { indoor, version } = readSiteInterior(text);
    expect(version).toBe(1);
    // A slab a hand thick; a light from nearer overhead than the horizon, dimmer than the look's sun.
    expect(indoor.ceilingThicknessMm).toBe(100);
    expect(indoor.lightTiltDegrees).toBeGreaterThan(0);
    expect(indoor.lightTiltDegrees).toBeLessThan(45);
    expect(indoor.lightSharePermille).toBeLessThan(1000);
    expect(indoor.lightSrgb8).toEqual([255, 250, 240]);
    expect(JSON.parse(text).entries[0].reason).toContain('chosen default');
  });

  it('refuses a file that is not the catalog, one that states another entry, one with no reason, and figures out of range', () => {
    const document = JSON.parse(text) as { entries: Record<string, unknown>[] };
    const withEntry = (change: Record<string, unknown>) => JSON.stringify({ ...document, entries: [{ ...document.entries[0], ...change }] });
    expect(() => readSiteInterior(JSON.stringify({ ...document, catalog_id: 'site-scenery' }))).toThrow('is not the site interior catalog');
    expect(() => readSiteInterior(withEntry({ key: 'open' }))).toThrow('the one entry indoor');
    expect(() => readSiteInterior(JSON.stringify({ ...document, entries: [document.entries[0], document.entries[0]] }))).toThrow('the one entry indoor');
    expect(() => readSiteInterior(withEntry({ reason: '' }))).toThrow('gives no reason');
    expect(() => readSiteInterior(withEntry({ ceiling_thickness_mm: 0 }))).toThrow('ceiling_thickness_mm');
    // A light along the ceiling lights no floor.
    expect(() => readSiteInterior(withEntry({ light_tilt_degrees: 90 }))).toThrow('light_tilt_degrees');
    expect(() => readSiteInterior(withEntry({ light_share_permille: 0 }))).toThrow('light_share_permille');
    expect(() => readSiteInterior(withEntry({ light_srgb8: [255, 250] }))).toThrow('three bytes');
    expect(() => readSiteInterior(withEntry({ light_srgb8: [255, 250, 256] }))).toThrow('light_srgb8[2]');
  });
});
