import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { SURFACE_FINISH } from '../src/surface-finish.js';

/*
 * The page draws a made place's grounds and water with the finish the catalog states, figure for
 * figure, and makes no reflection camera while the catalog states no reflection strength.
 */
const CATALOG = JSON.parse(readFileSync(
  new URL('../../../../assets/catalogs/world-kinds/surface-finish.v1.json', import.meta.url), 'utf8',
)) as { entries: { key: string; value: number }[] };
const stated = (key: string) => CATALOG.entries.find((entry) => entry.key === key)!.value;

describe('the surface finish the page hands its sites', () => {
  it('is the catalog\'s, figure for figure', () => {
    expect(SURFACE_FINISH.groundVariation).toBe(stated('ground_variation_share'));
    expect(SURFACE_FINISH.groundBroadM).toBe(stated('ground_broad_m'));
    expect(SURFACE_FINISH.wetDarkening).toBe(stated('wet_darkening_share'));
    expect(SURFACE_FINISH.waterRipple).toBe(stated('water_ripple_share'));
    expect(SURFACE_FINISH.reflectionSizePx).toBe(stated('reflection_size_px'));
    expect(Object.keys(SURFACE_FINISH)).toHaveLength(CATALOG.entries.length);
  });

  it('states no reflection in this version, so no reflection camera is made', () => {
    expect(SURFACE_FINISH.reflectionStrength).toBe(0);
  });
});
