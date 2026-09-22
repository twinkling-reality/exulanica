// @vitest-environment happy-dom
/**
 * Fog is mixed in the space the sky is drawn in, toward the colour the sky shows at eye level.
 *
 * These pin the parts a unit can see: the order of the installed end chunk, the sky's own rule
 * for its eye-level colour, and the fog colour the binding takes from it. Whether the look is
 * right is a rendering question, answered by capturing the running app, not here.
 */
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { composeAtlasWorld, makeScene } from '@exulanica/atlas-core';
import { ORIGIN_LANDSCAPE, SURVEY_RELIEF, unitRgb } from '@exulanica/presentation';
import { installDisplaySpaceFog, skyColourAtEyeLevel } from '../src/playcanvas/atlas-binding.js';
import { createComposedWorld } from '../src/playcanvas/composed-world.js';

function device(): pc.GraphicsDevice {
  return new pc.NullGraphicsDevice(document.createElement('canvas'));
}

/**
 * A device as the binding has it when it installs the chunk: after `app.init`, which is where the
 * engine registers its default chunks, overwriting whatever was there. Installing before that
 * would be undone by it, so the test takes the same order production does.
 */
function initialisedDevice(): pc.GraphicsDevice {
  const target = device();
  const app = new pc.AppBase(document.createElement('canvas'));
  const options = new pc.AppOptions();
  options.graphicsDevice = target;
  app.init(options);
  return target;
}

/** Where in a chunk fog is applied, relative to tone mapping. */
function fogAfterToneMap(chunk: string): boolean {
  const toneMap = chunk.indexOf('toneMap(');
  const fog = chunk.search(/fog_color|addFog\(/u);
  if (toneMap < 0 || fog < 0) throw new Error('chunk names neither a tone map nor fog');
  return fog > toneMap;
}

describe('the lit end chunk once display-space fog is installed', () => {
  it('fogs after tone mapping and encoding, in both shading languages', () => {
    const target = initialisedDevice();
    const glsl = pc.ShaderChunks.get(target, pc.SHADERLANGUAGE_GLSL);
    const wgsl = pc.ShaderChunks.get(target, pc.SHADERLANGUAGE_WGSL);
    // The control: the engine's own chunk fogs first. Without it the assertion below could not
    // tell an installed chunk from one that was never replaced.
    expect(fogAfterToneMap(glsl.get('endPS'))).toBe(false);
    expect(fogAfterToneMap(wgsl.get('endPS'))).toBe(false);

    installDisplaySpaceFog(target);

    for (const chunk of [glsl.get('endPS'), wgsl.get('endPS')]) {
      expect(fogAfterToneMap(chunk)).toBe(true);
      expect(chunk.indexOf('gammaCorrectOutput(')).toBeLessThan(chunk.search(/fog_color/u));
      // The fog colour is encoded exactly as the output is, so a fully fogged pixel is the
      // authored colour, and the engine's own fog factor still decides how much of it.
      expect(chunk).toMatch(/gammaCorrectOutput\((uniform\.)?fog_color \* dBlendModeFogFactor\)/u);
      expect(chunk).toContain('getFogFactor()');
    }
  });

  it('leaves another device on the engine default', () => {
    installDisplaySpaceFog(initialisedDevice());
    expect(fogAfterToneMap(pc.ShaderChunks.get(initialisedDevice(), pc.SHADERLANGUAGE_GLSL).get('endPS')))
      .toBe(false);
  });

  it('would be undone if it ran before the engine registers its defaults', () => {
    // Why the binding installs it after `app.init` and not earlier.
    const target = device();
    installDisplaySpaceFog(target);
    const app = new pc.AppBase(document.createElement('canvas'));
    const options = new pc.AppOptions();
    options.graphicsDevice = target;
    app.init(options);
    expect(fogAfterToneMap(pc.ShaderChunks.get(target, pc.SHADERLANGUAGE_GLSL).get('endPS')))
      .toBe(false);
  });
});

describe('the colour the sky shows at eye level, and the fog colour taken from it', () => {
  const world = (profile = ORIGIN_LANDSCAPE) => {
    const target = device();
    const app = new pc.AppBase(document.createElement('canvas'));
    const options = new pc.AppOptions();
    options.graphicsDevice = target;
    options.componentSystems = [pc.RenderComponentSystem];
    app.init(options);
    const composed = createComposedWorld(target, composeAtlasWorld(makeScene([], 1, 1)), profile);
    app.root.addChild(composed.entity);
    return { app, composed };
  };
  const clearOf = (hex: string) => new pc.Color(...unitRgb(hex));

  it('is paper in the default look, whose sky is a diffuse canvas meeting the horizon at paper', () => {
    const { app, composed } = world(ORIGIN_LANDSCAPE);
    expect(ORIGIN_LANDSCAPE.field.atmosphere).toBe('diffuse-canvas');
    expect(composed.skyHorizonColour()).toEqual(unitRgb(ORIGIN_LANDSCAPE.palette.paper));
    expect(skyColourAtEyeLevel(composed, clearOf(ORIGIN_LANDSCAPE.palette.sky)))
      .toEqual(unitRgb(ORIGIN_LANDSCAPE.palette.paper));
    app.destroy();
  });

  it('is the clear colour in survey relief, which draws no sky of its own', () => {
    const { app, composed } = world(ORIGIN_LANDSCAPE);
    composed.setProfile(SURVEY_RELIEF);
    expect(composed.skyHorizonColour()).toBeNull();
    // Survey relief's fog and sky are different authored colours, which is why putting the sky
    // through the fog's pipeline could not join them: the fog has to take the sky's colour.
    expect(SURVEY_RELIEF.palette.haze).not.toBe(SURVEY_RELIEF.palette.sky);
    expect(skyColourAtEyeLevel(composed, clearOf(SURVEY_RELIEF.palette.sky)))
      .toEqual(unitRgb(SURVEY_RELIEF.palette.sky));
    // And back again: the rule follows the profile both ways.
    composed.setProfile(ORIGIN_LANDSCAPE);
    expect(composed.skyHorizonColour()).toEqual(unitRgb(ORIGIN_LANDSCAPE.palette.paper));
    app.destroy();
  });

  it('is the haze shelf when the same sky is a layered horizon', () => {
    const layered = { ...ORIGIN_LANDSCAPE, field: { ...ORIGIN_LANDSCAPE.field, atmosphere: 'layered-horizon' as const } };
    const { app, composed } = world(layered);
    expect(composed.skyHorizonColour()).toEqual(unitRgb(ORIGIN_LANDSCAPE.palette.haze));
    app.destroy();
  });

  it('falls back to the clear colour whenever the sky is not drawn: the Map, or a render root that is off', () => {
    const { app, composed } = world(ORIGIN_LANDSCAPE);
    composed.setMapActive(true);
    expect(composed.skyHorizonColour()).toBeNull();
    composed.setMapActive(false);
    expect(composed.skyHorizonColour()).not.toBeNull();
    // The city and the generated tile switch the composed world's render root off.
    const root = new pc.Entity('render-root');
    app.root.addChild(root);
    composed.entity.reparent(root);
    root.enabled = false;
    expect(composed.skyHorizonColour()).toBeNull();
    expect(skyColourAtEyeLevel(composed, new pc.Color(0.79, 0.85, 0.88))).toEqual([0.79, 0.85, 0.88]);
    app.destroy();
  });
});
