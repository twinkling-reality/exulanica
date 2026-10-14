// @vitest-environment happy-dom
/**
 * A look drawn within a scene form's render budget: lowered to each cap and never raised, the same
 * look where the caps are its ceilings, still a valid look at the lowest caps, and the caps of the
 * scene's own form applied by the site mount and by the tile runtime.
 */
import { createHash, webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { RENDER_CAP_RANGES, parseTextureSetManifest, readRenderBudget, renderCapsFor, type RenderBudget, type RenderCaps, type TextureSetDigest } from '@exulanica/atlas-core';
import { bakeTile } from '@exulanica/loom-tess/core';
import * as pc from 'playcanvas';
import { beforeAll, describe, expect, it } from 'vitest';
import { loadGeneratedTile } from '../src/playcanvas/generated-tile/tile-runtime.js';
import { budgetedLook } from '../src/playcanvas/generated-tile/budgeted-look.js';
import { parseStructuredSiteDrawing, siteMount } from '../src/playcanvas/generated-site/index.js';
import { TILE_LOOK_V1, validateRenderLook, validateTileLook, type TileLook } from '../src/playcanvas/generated-tile/look.js';
import { renderLookOfPreset } from '../src/playcanvas/style-pack/preset-look.js';

// Relative to web/, where the suite runs: the files a deployment ships.
const text = readFileSync('../assets/catalogs/world-kinds/render-budget.v1.json', 'utf8');
const BUDGET = readRenderBudget(text);
const COZY = JSON.parse(readFileSync('../assets/style-packs/packs/exulanica.cozy-town/manifest.json', 'utf8')) as {
  light: { default_preset: string; presets: Record<string, never> }; shading: never; edge: never;
};
const RENDER_LOOK: TileLook = renderLookOfPreset(COZY.light.presets[COZY.light.default_preset]!, COZY.shading, COZY.edge);

const range = RENDER_CAP_RANGES;
const capsAt = (end: 'least' | 'most'): RenderCaps => ({
  form: 'open_site',
  sunShadowCascades: range.sun_shadow_cascades[end],
  sunShadowResolutionPx: range.sun_shadow_resolution_px[end],
  sunShadowDistanceM: range.sun_shadow_distance_m[end],
  contactShadowSamples: range.contact_shadow_samples[end],
  contactShadowScale: range.contact_shadow_scale_permille[end] / 1000,
});

/** A budget whose one form is lowered, read through the catalog's own reader. */
function lowered(form: string, changes: Record<string, number>): RenderBudget {
  const document = JSON.parse(text) as { entries: { key: string; caps: Record<string, Record<string, unknown>> }[] };
  for (const entry of document.entries) {
    if (entry.key !== form) continue;
    for (const [key, most] of Object.entries(changes)) entry.caps[key] = { ...entry.caps[key], most, class: 'chosen' };
  }
  return readRenderBudget(JSON.stringify(document));
}

describe('a look within its caps', () => {
  it('is the same look at the ceilings, for the tile look and a pack\'s render look', () => {
    for (const look of [TILE_LOOK_V1, RENDER_LOOK]) {
      expect(budgetedLook(look, capsAt('most'))).toBe(look);
      for (const form of ['open_site', 'indoor_site', 'terrain']) expect(budgetedLook(look, renderCapsFor(BUDGET, form))).toBe(look);
    }
  });

  it('is lowered to each cap and never raised, leaving everything else as chosen', () => {
    const caps = { ...capsAt('most'), sunShadowCascades: 2, sunShadowResolutionPx: 1024, contactShadowScale: 0.5 };
    const look = budgetedLook(RENDER_LOOK, caps);
    expect(look.sun.shadow).toEqual({ ...RENDER_LOOK.sun.shadow, cascades: 2, resolution: 1024 });
    expect(look.contactShadow).toEqual({ ...RENDER_LOOK.contactShadow, scale: 0.5 });
    expect({ ...look, sun: null, contactShadow: null }).toEqual({ ...RENDER_LOOK, sun: null, contactShadow: null });
    expect(look.sky).toBe(RENDER_LOOK.sky);
    // The tile look asks for 3 cascades over 90 m: a cap of 4 and 400 m leaves both as they are.
    expect(budgetedLook(TILE_LOOK_V1, { ...capsAt('most'), sunShadowCascades: 4, sunShadowDistanceM: 400 })).toBe(TILE_LOOK_V1);
    expect(Object.isFrozen(look) && Object.isFrozen(look.sun.shadow) && Object.isFrozen(look.contactShadow)).toBe(true);
  });

  it('is still a valid look of either descriptor at the lowest caps, and the ceilings are the validators\' own', () => {
    expect(() => validateTileLook(budgetedLook(TILE_LOOK_V1, capsAt('least')))).not.toThrow();
    expect(() => validateRenderLook(budgetedLook(RENDER_LOOK, capsAt('least')))).not.toThrow();
    const shadow = (look: TileLook, change: Record<string, number>) => ({ ...look, sun: { ...look.sun, shadow: { ...look.sun.shadow, ...change } } });
    const contact = (look: TileLook, change: Record<string, number>) => ({ ...look, contactShadow: { ...look.contactShadow, ...change } });
    for (const [look, validate] of [[TILE_LOOK_V1, validateTileLook], [RENDER_LOOK, validateRenderLook]] as const) {
      expect(() => validate(shadow(look, { cascades: range.sun_shadow_cascades.most, resolution: range.sun_shadow_resolution_px.most, distanceM: range.sun_shadow_distance_m.most }))).not.toThrow();
      expect(() => validate(contact(look, { samples: range.contact_shadow_samples.most, scale: range.contact_shadow_scale_permille.most / 1000 }))).not.toThrow();
      expect(() => validate(shadow(look, { cascades: range.sun_shadow_cascades.most + 1 }))).toThrow();
      expect(() => validate(shadow(look, { resolution: 8192 }))).toThrow();
      expect(() => validate(shadow(look, { distanceM: range.sun_shadow_distance_m.most + 1 }))).toThrow();
      expect(() => validate(contact(look, { samples: range.contact_shadow_samples.most + 1 }))).toThrow();
      expect(() => validate(contact(look, { scale: range.contact_shadow_scale_permille.most / 1000 + 0.001 }))).toThrow();
    }
  });
});

function yard(enclosure: 'open' | 'indoor') {
  return parseStructuredSiteDrawing({
    profile: 'exulanica.site-drawing/v1',
    world_id: 'world-1',
    receipt_sha256: 'a'.repeat(64),
    kind: { kind: 'fixture_yard', version: 1, label: 'Yard' },
    extent: { widthMm: 10_000, depthMm: 12_000, enclosure },
    arrival: { positionMm: [5000, 4000, 0], facingMm: [0, 1] },
    slots: [{
      identity: 'ground', part: 'ground', label: 'ground', lookRole: 'ground.tilled_soil', positionMm: [5000, 6000, 0],
      yawQuarterTurns: 0, boxMm: [10_000, 12_000, 0], front: '+y', fit: 'surface', primitive: 'plane',
    }],
    walk: { floorMm: [0, 0, 10_000, 12_000], blockersMm: [], keepOutMm: [] },
    seats: [],
  });
}

function nullApp() {
  const canvas = document.createElement('canvas');
  canvas.width = 0;
  canvas.height = 0;
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = new pc.NullGraphicsDevice(canvas);
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
  app.init(options);
  const camera = new pc.Entity('camera');
  camera.addComponent('camera');
  app.root.addChild(camera);
  const environmentRoot = new pc.Entity('environment');
  app.root.addChild(environmentRoot);
  return { app, camera, environmentRoot };
}

describe('a site drawn within the budget', () => {
  const sunOf = (enclosure: 'open' | 'indoor', renderBudget?: RenderBudget) => {
    const host = nullApp();
    const attachment = siteMount(yard(enclosure), { servedBytes: 1, look: RENDER_LOOK, ...(renderBudget === undefined ? {} : { renderBudget }) }).attach(host);
    const light = (host.app.root.findByName('generated-tile-sun') as pc.Entity).light!;
    const seen = { cascades: light.numCascades, resolution: light.shadowResolution, distance: light.shadowDistance };
    attachment.dispose();
    return seen;
  };

  it('takes the caps of its own form, and draws the look as chosen at the ceilings or with no budget', () => {
    const chosen = { cascades: RENDER_LOOK.sun.shadow.cascades, resolution: RENDER_LOOK.sun.shadow.resolution, distance: RENDER_LOOK.sun.shadow.distanceM };
    expect(sunOf('open')).toEqual(chosen);
    expect(sunOf('open', BUDGET)).toEqual(chosen);
    const indoorLow = lowered('indoor_site', { sun_shadow_cascades: 1, sun_shadow_resolution_px: 1024 });
    expect(sunOf('open', indoorLow)).toEqual(chosen);
    expect(sunOf('indoor', indoorLow)).toEqual({ ...chosen, cascades: 1, resolution: 1024 });
  });
});

describe('a town tile drawn within the budget', () => {
  const FIXTURE = 'packages/loom-tess/test/fixtures/tile-conformance.json';
  const manifest = parseTextureSetManifest(new Uint8Array(readFileSync('../assets/textures/manifest.json')));
  const subtle = webcrypto.subtle as unknown as TextureSetDigest;
  const sha256 = async (bytes: Uint8Array): Promise<string> => createHash('sha256').update(bytes).digest('hex');
  const noSets = async (): Promise<Uint8Array> => { throw new Error('this test fetches no texture set'); };
  let baked: Uint8Array;
  beforeAll(async () => {
    baked = (await bakeTile(new Uint8Array(readFileSync(FIXTURE)), sha256)).container;
  }, 60_000);
  const sunOf = (tile: { attach: (host: ReturnType<typeof nullApp>) => { dispose(): void } }) => {
    const host = nullApp();
    const attachment = tile.attach(host);
    const light = (host.app.root.findByName('generated-tile-sun') as pc.Entity).light!;
    const seen = { cascades: light.numCascades, resolution: light.shadowResolution, distance: light.shadowDistance };
    attachment.dispose();
    return seen;
  };
  const load = (renderBudget?: RenderBudget) => loadGeneratedTile({
    name: 'tile-conformance', bytes: baked, manifest, fetchSet: noSets, digest: subtle, look: RENDER_LOOK,
    ...(renderBudget === undefined ? {} : { renderBudget }),
  });

  it('takes the town form\'s caps in its light, in any look it is relit in, and leaves its own look as chosen', async () => {
    const chosen = { cascades: RENDER_LOOK.sun.shadow.cascades, resolution: RENDER_LOOK.sun.shadow.resolution, distance: RENDER_LOOK.sun.shadow.distanceM };
    expect(sunOf(await load())).toEqual(chosen);
    expect(sunOf(await load(BUDGET))).toEqual(chosen);
    expect(sunOf(await load(lowered('open_site', { sun_shadow_cascades: 1 })))).toEqual(chosen);
    const town = await load(lowered('town_tiles', { sun_shadow_cascades: 1, sun_shadow_resolution_px: 1024 }));
    expect(sunOf(town)).toEqual({ ...chosen, cascades: 1, resolution: 1024 });
    // The look the tile's surfaces are uploaded in is the one chosen; only the light is budgeted.
    expect(town.look).toBe(RENDER_LOOK);
    expect(sunOf(town.inLook(TILE_LOOK_V1))).toEqual({ cascades: 1, resolution: 1024, distance: TILE_LOOK_V1.sun.shadow.distanceM });
  }, 60_000);
});
