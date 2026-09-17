import * as pc from 'playcanvas';
import { sunDirection, type Rgb, type TileLook } from './look.js';

/**
 * The light a generated street stands in, built from one {@link TileLook}.
 *
 * Four things, each the architecture table's target and each measured by the test bench rather
 * than asserted: a sun with cascaded shadows; linear fog whose onset is inside 40 to 60 m; an
 * environment probe, prefiltered from a sky gradient the look describes, that lights every surface
 * and colours its reflections; and screen-space ambient occlusion, which is the contact shadowing at
 * kerb, doorway and cornice.
 *
 * Everything this module changes on the app and the camera is recorded first and put back by
 * `dispose`, so mounting a tile and unmounting it leaves the scene exactly as it was. The lights
 * already in the scene are disabled while the tile is mounted, not destroyed.
 */

export interface TileEnvironment {
  readonly look: TileLook;
  readonly sun: pc.Entity;
  readonly frame: pc.CameraFrame;
  /** GPU bytes held by the probe's cubemap and atlas. */
  readonly residentBytes: number;
  dispose(): void;
}

const TONE_MAPPING: Readonly<Record<TileLook['toneMapping'], number>> = {
  aces: pc.TONEMAP_ACES,
  aces2: pc.TONEMAP_ACES2,
  neutral: pc.TONEMAP_NEUTRAL,
  filmic: pc.TONEMAP_FILMIC,
  linear: pc.TONEMAP_LINEAR,
};

const colour = ([r, g, b]: Rgb): pc.Color => new pc.Color(r, g, b);

/** The six faces PlayCanvas expects, in order: +X, -X, +Y, -Y, +Z, -Z. */
function faceDirection(face: number, u: number, v: number): readonly [number, number, number] {
  switch (face) {
    case 0: return [1, -v, -u];
    case 1: return [-1, -v, u];
    case 2: return [u, 1, v];
    case 3: return [u, -1, -v];
    case 4: return [u, -v, 1];
    default: return [-u, -v, -1];
  }
}

/** The sky the look describes, as linear RGB for a world direction. */
export function skyRadiance(look: TileLook, direction: readonly [number, number, number]): Rgb {
  const [x, y, z] = direction;
  const up = y / Math.hypot(x, y, z);
  const mix = (a: Rgb, b: Rgb, t: number): Rgb => [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
  ];
  return up >= 0
    ? mix(look.sky.horizon, look.sky.zenith, Math.sqrt(up))
    : mix(look.sky.horizon, look.sky.ground, Math.min(1, -up * 4));
}

function gradientCubemap(device: pc.GraphicsDevice, look: TileLook): pc.Texture {
  const size = look.environment.sourceSize;
  const faces: Uint8Array[] = [];
  for (let face = 0; face < 6; face += 1) {
    const texels = new Uint8Array(size * size * 4);
    for (let row = 0; row < size; row += 1) {
      for (let column = 0; column < size; column += 1) {
        const u = ((column + 0.5) / size) * 2 - 1;
        const v = ((row + 0.5) / size) * 2 - 1;
        const radiance = skyRadiance(look, faceDirection(face, u, v));
        const at = (row * size + column) * 4;
        texels[at] = Math.round(radiance[0] * 255);
        texels[at + 1] = Math.round(radiance[1] * 255);
        texels[at + 2] = Math.round(radiance[2] * 255);
        texels[at + 3] = 255;
      }
    }
    faces.push(texels);
  }
  return new pc.Texture(device, {
    name: 'generated-tile-sky',
    cubemap: true,
    width: size,
    height: size,
    format: pc.PIXELFORMAT_RGBA8,
    mipmaps: false,
    minFilter: pc.FILTER_LINEAR,
    magFilter: pc.FILTER_LINEAR,
    addressU: pc.ADDRESS_CLAMP_TO_EDGE,
    addressV: pc.ADDRESS_CLAMP_TO_EDGE,
    levels: [faces],
  });
}

export function applyTileEnvironment(app: pc.AppBase, camera: pc.Entity, look: TileLook): TileEnvironment {
  const scene = app.scene;
  const component = camera.camera;
  if (component === undefined || component === null) throw new Error('The tile environment needs a camera component');
  const saved = {
    exposure: scene.exposure,
    ambient: scene.ambientLight.clone(),
    fogType: scene.fog.type,
    fogStart: scene.fog.start,
    fogEnd: scene.fog.end,
    fogColour: scene.fog.color.clone(),
    envAtlas: scene.envAtlas,
    skybox: scene.skybox,
    skyboxIntensity: scene.skyboxIntensity,
    clearColour: component.clearColor.clone(),
    toneMapping: component.toneMapping,
    farClip: component.farClip,
    lights: app.root.findComponents('light')
      .map((light) => light as pc.LightComponent)
      .filter((light) => light.enabled)
      .map((light) => light.entity),
  };
  for (const light of saved.lights) light.enabled = false;

  scene.exposure = look.exposure;
  scene.ambientLight = new pc.Color(0, 0, 0);
  scene.fog.type = pc.FOG_LINEAR;
  scene.fog.start = look.fog.startM;
  scene.fog.end = look.fog.endM;
  scene.fog.color.copy(colour(look.fog.colour));
  component.clearColor = new pc.Color(...look.sky.horizon, 1);
  component.farClip = Math.max(component.farClip, look.fog.endM * 1.5);

  const device = app.graphicsDevice;
  const sky = gradientCubemap(device, look);
  const lighting = pc.EnvLighting.generateLightingSource(sky, { size: look.environment.sourceSize * 2 });
  const atlas = pc.EnvLighting.generateAtlas(lighting, { size: look.environment.atlasSize });
  scene.envAtlas = atlas;
  scene.skybox = sky;
  scene.skyboxIntensity = look.environment.intensity;
  const probeBytes = 6 * look.environment.sourceSize ** 2 * 4
    + 6 * (look.environment.sourceSize * 2) ** 2 * 4 * 4 / 3
    + look.environment.atlasSize ** 2 * 4;

  const sun = new pc.Entity('generated-tile-sun');
  sun.addComponent('light', {
    type: 'directional',
    color: colour(look.sun.colour),
    intensity: look.sun.intensity,
    castShadows: true,
    shadowResolution: look.sun.shadow.resolution,
    shadowDistance: look.sun.shadow.distanceM,
    numCascades: look.sun.shadow.cascades,
    cascadeDistribution: look.sun.shadow.cascadeDistribution,
    shadowBias: look.sun.shadow.bias,
    normalOffsetBias: look.sun.shadow.normalOffsetBias,
    shadowType: look.sun.shadow.filter === 'pcf5' ? pc.SHADOW_PCF5_32F : pc.SHADOW_PCF3_32F,
  });
  const [dx, dy, dz] = sunDirection(look);
  // A directional light shines down its local -Y axis.
  sun.setRotation(new pc.Quat().setFromDirections(new pc.Vec3(0, -1, 0), new pc.Vec3(dx, dy, dz)));
  app.root.addChild(sun);

  const frame = new pc.CameraFrame(app, component);
  frame.rendering.toneMapping = TONE_MAPPING[look.toneMapping];
  frame.rendering.samples = 4;
  frame.ssao.type = look.contactShadow.mode === 'combine' ? pc.SSAOTYPE_COMBINE : pc.SSAOTYPE_LIGHTING;
  frame.ssao.radius = look.contactShadow.radiusM;
  frame.ssao.intensity = look.contactShadow.intensity;
  frame.ssao.samples = look.contactShadow.samples;
  frame.ssao.power = look.contactShadow.power;
  frame.ssao.minAngle = look.contactShadow.minAngleDeg;
  frame.ssao.blurEnabled = look.contactShadow.blur;
  frame.ssao.scale = look.contactShadow.scale;
  frame.update();

  let disposed = false;
  return {
    look,
    sun,
    frame,
    residentBytes: probeBytes,
    dispose() {
      if (disposed) return;
      disposed = true;
      frame.destroy();
      sun.destroy();
      scene.envAtlas = saved.envAtlas;
      scene.skybox = saved.skybox;
      scene.skyboxIntensity = saved.skyboxIntensity;
      atlas.destroy();
      lighting.destroy();
      sky.destroy();
      scene.exposure = saved.exposure;
      scene.ambientLight = saved.ambient;
      scene.fog.type = saved.fogType;
      scene.fog.start = saved.fogStart;
      scene.fog.end = saved.fogEnd;
      scene.fog.color.copy(saved.fogColour);
      component.clearColor = saved.clearColour;
      component.toneMapping = saved.toneMapping;
      component.farClip = saved.farClip;
      for (const light of saved.lights) light.enabled = true;
    },
  };
}
