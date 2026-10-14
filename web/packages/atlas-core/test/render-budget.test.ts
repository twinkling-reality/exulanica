import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { RENDER_CAP_RANGES, RENDER_FORMS, capsAtLevel, readRenderBudget, renderCapsFor } from '../src/render-budget.js';

// Relative to web/, where the suite runs: the file a deployment ships, and the version before it.
const text = readFileSync('../assets/catalogs/world-kinds/render-budget.v2.json', 'utf8');
const V1 = readFileSync('../assets/catalogs/world-kinds/render-budget.v1.json', 'utf8');
const BUDGET = readRenderBudget(text);
const CEILINGS = {
  sunShadowCascades: RENDER_CAP_RANGES.sun_shadow_cascades.most,
  sunShadowResolutionPx: RENDER_CAP_RANGES.sun_shadow_resolution_px.most,
  sunShadowDistanceM: RENDER_CAP_RANGES.sun_shadow_distance_m.most,
  contactShadowSamples: RENDER_CAP_RANGES.contact_shadow_samples.most,
  contactShadowScale: RENDER_CAP_RANGES.contact_shadow_scale_permille.most / 1000,
  msaaSamples: RENDER_CAP_RANGES.msaa_samples.most,
  renderScale: RENDER_CAP_RANGES.render_scale_permille.most / 1000,
};

describe('the render budget catalog', () => {
  it('states every scene form at the ceilings and only full quality, so version 2 changes no look', () => {
    expect(BUDGET.version).toBe(2);
    expect([...BUDGET.byForm.keys()]).toEqual([...RENDER_FORMS]);
    expect(BUDGET.levels).toEqual([{ level: 0, caps: {} }]);
    expect(CEILINGS.msaaSamples).toBe(4);
    for (const form of RENDER_FORMS) {
      expect(renderCapsFor(BUDGET, form)).toEqual({ form, ...CEILINGS });
      expect(capsAtLevel(BUDGET, form, 0)).toBe(renderCapsFor(BUDGET, form));
    }
  });

  it('still reads version 1, which leaves the frame\'s caps at their ceilings and states only full quality', () => {
    const first = readRenderBudget(V1);
    expect(first.version).toBe(1);
    expect(first.levels).toEqual([{ level: 0, caps: {} }]);
    for (const form of RENDER_FORMS) expect(renderCapsFor(first, form)).toEqual({ form, ...CEILINGS });
    const document = JSON.parse(V1) as { entries: { caps: Record<string, unknown> }[] };
    const [open, ...rest] = document.entries;
    const msaa = { most: 2, class: 'chosen', reason: 'r' };
    expect(() => readRenderBudget(JSON.stringify({ ...document, entries: [{ ...open, caps: { ...open!.caps, msaa_samples: msaa } }, ...rest] })))
      .toThrow('open_site caps an unknown value "msaa_samples"');
    expect(() => readRenderBudget(JSON.stringify({ ...document, levels: [] }))).toThrow('levels are stated from version 2');
    expect(() => readRenderBudget(JSON.stringify({ ...document, catalog_version: 3 }))).toThrow('catalog_version must be 1 or 2');
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
    expect(() => readRenderBudget(withCaps({ sharpness_permille: { most: 2, class: 'chosen', reason: 'r' } }))).toThrow('open_site caps an unknown value "sharpness_permille"');
    expect(() => readRenderBudget(withCaps({ msaa_samples: { ...caps['msaa_samples'], most: 3, class: 'chosen' } })))
      .toThrow('open_site.msaa_samples.most must be one of 1, 2, 4');
    expect(() => readRenderBudget(withCaps({ render_scale_permille: { ...caps['render_scale_permille'], most: 400, class: 'chosen' } })))
      .toThrow('open_site.render_scale_permille.most is 400, below the look\'s floor of 500');
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

  it('reads quality levels in order, each lower one lowering something, and draws a form within the least of its cap and its level\'s', () => {
    const document = JSON.parse(text) as { entries: { key: string; caps: Record<string, Record<string, unknown>> }[]; levels: Record<string, unknown>[] };
    const full = document.levels[0]!;
    const cap = (most: number) => ({ most, class: 'chosen', reason: 'r' });
    const lower = { level: 1, reason: 'r', caps: { msaa_samples: cap(2), render_scale_permille: cap(700), sun_shadow_cascades: cap(2) } };
    const withLevels = (...levels: unknown[]) => JSON.stringify({ ...document, levels });
    expect(() => readRenderBudget(withLevels())).toThrow('levels must list level 0 at least');
    expect(() => readRenderBudget(withLevels(lower))).toThrow('level 0 must be numbered 0, in order');
    expect(() => readRenderBudget(withLevels({ ...full, caps: { msaa_samples: cap(2) } }))).toThrow('level 0 is full quality and caps nothing');
    expect(() => readRenderBudget(withLevels(full, { ...lower, caps: {} }))).toThrow('level 1 caps nothing');
    expect(() => readRenderBudget(withLevels(full, { ...lower, reason: '' }))).toThrow('level 1 gives no reason');
    expect(() => readRenderBudget(withLevels(full, { ...lower, caps: { haze: cap(1) } }))).toThrow('level 1 caps an unknown value "haze"');
    expect(() => readRenderBudget(withLevels(full, { ...lower, caps: { msaa_samples: cap(8) } }))).toThrow('level 1.msaa_samples.most is 8, above');
    // A town whose own cap is lower than the level's keeps its own.
    const town = document.entries.find((entry) => entry.key === 'town_tiles')!;
    town.caps['sun_shadow_cascades'] = { ...town.caps['sun_shadow_cascades'], most: 1, class: 'chosen' };
    const laddered = readRenderBudget(withLevels(full, lower));
    expect(capsAtLevel(laddered, 'open_site', 1)).toEqual({ form: 'open_site', ...CEILINGS, msaaSamples: 2, renderScale: 0.7, sunShadowCascades: 2 });
    expect(capsAtLevel(laddered, 'town_tiles', 1)).toMatchObject({ sunShadowCascades: 1, msaaSamples: 2, renderScale: 0.7 });
    expect(() => capsAtLevel(laddered, 'open_site', 2)).toThrow('no level 2; the levels are 0 to 1');
    expect(() => capsAtLevel(BUDGET, 'harbour', 0)).toThrow('no caps for the form "harbour"');
  });
});
