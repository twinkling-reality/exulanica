import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { RENDER_CAP_RANGES, RENDER_FORMS, readRenderBudget, renderCapsFor } from '../src/render-budget.js';

// Relative to web/, where the suite runs: the file a deployment ships.
const text = readFileSync('../assets/catalogs/world-kinds/render-budget.v1.json', 'utf8');
const BUDGET = readRenderBudget(text);

describe('the render budget catalog', () => {
  it('states every scene form at the look\'s own ceilings, so version 1 changes no look', () => {
    expect(BUDGET.version).toBe(1);
    expect([...BUDGET.byForm.keys()]).toEqual([...RENDER_FORMS]);
    for (const form of RENDER_FORMS) {
      expect(renderCapsFor(BUDGET, form)).toEqual({
        form,
        sunShadowCascades: RENDER_CAP_RANGES.sun_shadow_cascades.most,
        sunShadowResolutionPx: RENDER_CAP_RANGES.sun_shadow_resolution_px.most,
        sunShadowDistanceM: RENDER_CAP_RANGES.sun_shadow_distance_m.most,
        contactShadowSamples: RENDER_CAP_RANGES.contact_shadow_samples.most,
        contactShadowScale: RENDER_CAP_RANGES.contact_shadow_scale_permille.most / 1000,
      });
    }
  });

  it('refuses an unknown form, a missing one, a cap above the ceiling and a cap with no reason, by name', () => {
    const document = JSON.parse(text) as { entries: Record<string, unknown>[] };
    const [open, indoor, terrain, town] = document.entries as [Record<string, unknown>, Record<string, unknown>, Record<string, unknown>, Record<string, unknown>];
    const caps = open['caps'] as Record<string, Record<string, unknown>>;
    const withCaps = (changed: Record<string, unknown>) => JSON.stringify({ ...document, entries: [{ ...open, caps: { ...caps, ...changed } }, indoor, terrain, town] });
    const withEntries = (...entries: Record<string, unknown>[]) => JSON.stringify({ ...document, entries });
    expect(() => readRenderBudget(JSON.stringify({ ...document, catalog_id: 'ground-border' }))).toThrow('is not the render budget catalog');
    expect(() => readRenderBudget(withEntries(open, indoor, terrain, town, { ...open, key: 'harbour' }))).toThrow('names the form "harbour", which is none of open_site, indoor_site, terrain, town_tiles');
    expect(() => readRenderBudget(withEntries(open, open, terrain, town))).toThrow('open_site is stated twice');
    expect(() => readRenderBudget(withEntries(open, terrain, town))).toThrow('indoor_site is not stated');
    expect(() => readRenderBudget(withEntries(open, indoor, terrain))).toThrow('town_tiles is not stated');
    expect(() => readRenderBudget(withCaps({ sun_shadow_cascades: { ...caps['sun_shadow_cascades'], most: 5 } })))
      .toThrow('open_site.sun_shadow_cascades.most is 5, above the look\'s ceiling of 4');
    expect(() => readRenderBudget(withCaps({ sun_shadow_distance_m: { ...caps['sun_shadow_distance_m'], most: 5 } })))
      .toThrow('open_site.sun_shadow_distance_m.most is 5, below the look\'s floor of 10');
    expect(() => readRenderBudget(withCaps({ sun_shadow_resolution_px: { ...caps['sun_shadow_resolution_px'], most: 3000, class: 'chosen' } })))
      .toThrow('open_site.sun_shadow_resolution_px.most must be one of 1024, 2048, 4096');
    expect(() => readRenderBudget(withCaps({ contact_shadow_samples: { ...caps['contact_shadow_samples'], most: 16 } })))
      .toThrow('open_site.contact_shadow_samples is classed as the ceiling but states 16, not 64');
    expect(() => readRenderBudget(withCaps({ contact_shadow_samples: { ...caps['contact_shadow_samples'], reason: ' ' } })))
      .toThrow('open_site.contact_shadow_samples gives no reason');
    expect(() => readRenderBudget(withCaps({ msaa_samples: { most: 2, class: 'chosen', reason: 'r' } }))).toThrow('open_site caps an unknown value "msaa_samples"');
    // A lowered cap is a measured or chosen one, read in the look's units.
    const lowered = readRenderBudget(withCaps({
      sun_shadow_cascades: { ...caps['sun_shadow_cascades'], most: 2, class: 'measured' },
      contact_shadow_scale_permille: { ...caps['contact_shadow_scale_permille'], most: 500, class: 'chosen' },
    }));
    expect(renderCapsFor(lowered, 'open_site')).toMatchObject({ sunShadowCascades: 2, contactShadowScale: 0.5 });
  });

  it('refuses caps for a form it does not know, by name', () => {
    expect(() => renderCapsFor(BUDGET, 'harbour')).toThrow('no caps for the form "harbour"; the forms are open_site, indoor_site, terrain, town_tiles');
  });
});
