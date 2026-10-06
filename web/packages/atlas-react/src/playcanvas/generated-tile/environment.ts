import * as pc from 'playcanvas';
import { isRenderLook, sunDirection, type RenderLook, type Rgb, type TileLook, type TileLookV1 } from './look.js';
import { cubeFaceDirection, renderSkyFaces } from './sky.js';

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
 *
 * The camera frame (tone mapping and the occlusion pass) builds its render targets when it is
 * created, at the canvas's size. A page can mount a tile while its canvas is still 0 by 0, and
 * targets built then are incomplete framebuffers, so the frame is created only once the device has a
 * size: at once if it does, otherwise on the device's first resize.
 */

export interface TileEnvironment {
  readonly look: TileLook;
  readonly sun: pc.Entity;
  /** The camera frame, or null while the canvas has had no size yet. */
  readonly frame: pc.CameraFrame | null;
  /**
   * Keep a copy of the colour drawn before transparent surfaces, which glazing transmits. Requested
   * only when a glazing set is drawn, since the copy costs a pass; it holds for a frame created later.
   */
  requestSceneColor(): void;
  /** GPU bytes held by the probe's cubemap and atlas. */
  readonly residentBytes: number;
  /** A render look's ground beyond the tiles, or null. */
  readonly ground: pc.Entity | null;
  dispose(): void;
}

const TONE_MAPPING: Readonly<Record<TileLookV1['toneMapping'], number>> = {
  aces: pc.TONEMAP_ACES,
  aces2: pc.TONEMAP_ACES2,
  neutral: pc.TONEMAP_NEUTRAL,
  filmic: pc.TONEMAP_FILMIC,
  linear: pc.TONEMAP_LINEAR,
};

const colour = ([r, g, b]: Rgb): pc.Color => new pc.Color(r, g, b);

/** A linear colour as the sRGB-encoded colour a material's colour inputs take. */
const displayColour = ([r, g, b]: Rgb): pc.Color => {
  const encode = (c: number): number => (c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055);
  return new pc.Color(encode(r), encode(g), encode(b));
};

const faceDirection = cubeFaceDirection;

/** The sky the look describes, as linear RGB for a world direction. */
export function skyRadiance(look: TileLookV1, direction: readonly [number, number, number]): Rgb {
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

function gradientCubemap(device: pc.GraphicsDevice, look: TileLookV1): pc.Texture {
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

/** A high dynamic range cubemap from six faces of linear RGBA floats. */
function halfFloatCubemap(device: pc.GraphicsDevice, name: string, size: number, faces: readonly Float32Array[]): pc.Texture {
  const levels = faces.map((face) => {
    const half = new Uint16Array(face.length);
    for (let at = 0; at < face.length; at += 1) half[at] = pc.FloatPacking.float2Half(face[at]!);
    return half;
  });
  return new pc.Texture(device, {
    name,
    cubemap: true,
    width: size,
    height: size,
    format: pc.PIXELFORMAT_RGBA16F,
    mipmaps: false,
    minFilter: pc.FILTER_LINEAR,
    magFilter: pc.FILTER_LINEAR,
    addressU: pc.ADDRESS_CLAMP_TO_EDGE,
    addressV: pc.ADDRESS_CLAMP_TO_EDGE,
    levels: [levels as unknown as Uint8Array[]],
  });
}

/** The engine's shadow type for each filter a render look may choose. */
export const RENDER_SHADOW_TYPES: Readonly<Record<RenderLook['sun']['shadow']['filter'], number>> = {
  pcf1: pc.SHADOW_PCF1_32F,
  pcf3: pc.SHADOW_PCF3_32F,
  pcf5: pc.SHADOW_PCF5_32F,
  pcss: pc.SHADOW_PCSS_32F,
};

/** The sky texture and the image light's sources a look is drawn with, and what they hold on the GPU. */
interface SkyLight {
  readonly sky: pc.Texture;
  readonly lighting: pc.Texture;
  readonly atlas: pc.Texture;
  readonly residentBytes: number;
}

function tileSkyLight(device: pc.GraphicsDevice, look: TileLookV1): SkyLight {
  const sky = gradientCubemap(device, look);
  const lighting = pc.EnvLighting.generateLightingSource(sky, { size: look.environment.sourceSize * 2 });
  const atlas = pc.EnvLighting.generateAtlas(lighting, { size: look.environment.atlasSize });
  const residentBytes = 6 * look.environment.sourceSize ** 2 * 4
    + 6 * (look.environment.sourceSize * 2) ** 2 * 4 * 4 / 3
    + look.environment.atlasSize ** 2 * 4;
  return { sky, lighting, atlas, residentBytes };
}

/**
 * A render look's sky: the drawn sky at `sky.faceTexels`, and the image light prefiltered from the
 * same function at the probe's source size with the bounce ground and no disc (`sky.ts` says why).
 * Resident bytes count the drawn sky and the two light textures at half-float RGBA, the lighting
 * source with its mip chain.
 */
function renderSkyLight(device: pc.GraphicsDevice, look: RenderLook): SkyLight {
  const size = look.sky.faceTexels;
  const source = look.environment.sourceSize;
  const sky = halfFloatCubemap(device, 'generated-tile-sky', size, renderSkyFaces(look, size, false));
  const probe = halfFloatCubemap(device, 'generated-tile-sky-light', source, renderSkyFaces(look, source, true));
  const lighting = pc.EnvLighting.generateLightingSource(probe, { size: source * 2 });
  const atlas = pc.EnvLighting.generateAtlas(lighting, { size: look.environment.atlasSize });
  probe.destroy();
  const residentBytes = 6 * size ** 2 * 8 + 6 * (source * 2) ** 2 * 8 * 4 / 3 + look.environment.atlasSize ** 2 * 8;
  return { sky, lighting, atlas, residentBytes };
}

/** The camera frame's finish a render look states; a tile look states none and leaves the defaults. */
function finishFrame(frame: pc.CameraFrame, look: RenderLook): void {
  const post = look.post;
  frame.bloom.intensity = post.bloom === null ? 0 : post.bloom.intensity;
  if (post.bloom !== null) frame.bloom.blurLevel = post.bloom.blurLevel;
  frame.grading.enabled = true;
  frame.grading.brightness = post.grading.brightness;
  frame.grading.contrast = post.grading.contrast;
  frame.grading.saturation = post.grading.saturation;
  frame.grading.tint = colour(post.grading.tint);
  frame.colorEnhance.enabled = true;
  frame.colorEnhance.shadows = post.enhance.shadows;
  frame.colorEnhance.highlights = post.enhance.highlights;
  frame.colorEnhance.midtones = post.enhance.midtones;
  frame.colorEnhance.vibrance = post.enhance.vibrance;
  frame.colorEnhance.dehaze = post.enhance.dehaze;
  frame.vignette.intensity = post.vignette === null ? 0 : post.vignette.intensity;
  if (post.vignette !== null) {
    frame.vignette.inner = post.vignette.inner;
    frame.vignette.outer = post.vignette.outer;
    frame.vignette.curvature = post.vignette.curvature;
    frame.vignette.color = colour(post.vignette.colour);
  }
  frame.taa.enabled = post.taa;
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
    fogDensity: scene.fog.density,
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
  const fog = isRenderLook(look) ? look.fog : { kind: 'linear' as const, ...look.fog };
  if (fog.kind === 'linear') {
    scene.fog.type = pc.FOG_LINEAR;
    scene.fog.start = fog.startM;
    scene.fog.end = fog.endM;
  } else {
    scene.fog.type = pc.FOG_EXP2;
    scene.fog.density = fog.density;
  }
  scene.fog.color.copy(colour(fog.colour));
  component.clearColor = new pc.Color(...look.sky.horizon, 1);
  // An exponential fog has no end: the far plane reaches past the ground beyond the tiles instead.
  const reach = fog.kind === 'linear' ? fog.endM * 1.5 : Math.max(4000, (isRenderLook(look) && look.edge !== null ? look.edge.reachM : 0) * 1.5);
  component.farClip = Math.max(component.farClip, reach);

  const device = app.graphicsDevice;
  const { sky, lighting, atlas, residentBytes: probeBytes } = isRenderLook(look) ? renderSkyLight(device, look) : tileSkyLight(device, look);
  scene.envAtlas = atlas;
  scene.skybox = sky;
  scene.skyboxIntensity = look.environment.intensity;

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
    shadowType: isRenderLook(look)
      ? RENDER_SHADOW_TYPES[look.sun.shadow.filter]
      : look.sun.shadow.filter === 'pcf5' ? pc.SHADOW_PCF5_32F : pc.SHADOW_PCF3_32F,
  });
  if (isRenderLook(look) && look.sun.shadow.filter === 'pcss') sun.light!.penumbraSize = look.sun.shadow.penumbra;
  const [dx, dy, dz] = sunDirection(look);
  // A directional light shines down its local -Y axis.
  sun.setRotation(new pc.Quat().setFromDirections(new pc.Vec3(0, -1, 0), new pc.Vec3(dx, dy, dz)));
  app.root.addChild(sun);

  // A render look's ground beyond the tiles: a plane round the world's origin, below every
  // carriageway, so a world never stands on its tiles in a void.
  let ground: pc.Entity | null = null;
  let groundMesh: pc.Mesh | null = null;
  let groundMaterial: pc.StandardMaterial | null = null;
  if (isRenderLook(look) && look.edge !== null) {
    groundMaterial = new pc.StandardMaterial();
    groundMaterial.name = 'generated-tile:edge-ground';
    groundMaterial.diffuse = displayColour(look.edge.ground);
    groundMaterial.useMetalness = true;
    groundMaterial.metalness = 0;
    groundMaterial.gloss = 0;
    groundMaterial.update();
    groundMesh = pc.Mesh.fromGeometry(device, new pc.PlaneGeometry({ halfExtents: new pc.Vec2(look.edge.reachM, look.edge.reachM) }));
    ground = new pc.Entity('generated-tile:edge-ground');
    ground.addComponent('render', { meshInstances: [new pc.MeshInstance(groundMesh, groundMaterial)], castShadows: false, receiveShadows: true });
    ground.setPosition(0, -look.edge.dropM, 0);
    app.root.addChild(ground);
  }

  let frame: pc.CameraFrame | null = null;
  let disposed = false;
  let sceneColor = false;
  const createFrame = (): void => {
    if (disposed || frame !== null || device.width <= 0 || device.height <= 0) return;
    const created = new pc.CameraFrame(app, component);
    created.rendering.toneMapping = TONE_MAPPING[look.toneMapping];
    created.rendering.samples = 4;
    created.ssao.type = look.contactShadow.mode === 'combine' ? pc.SSAOTYPE_COMBINE : pc.SSAOTYPE_LIGHTING;
    created.ssao.radius = look.contactShadow.radiusM;
    created.ssao.intensity = look.contactShadow.intensity;
    created.ssao.samples = look.contactShadow.samples;
    created.ssao.power = look.contactShadow.power;
    created.ssao.minAngle = look.contactShadow.minAngleDeg;
    created.ssao.blurEnabled = look.contactShadow.blur;
    created.ssao.scale = look.contactShadow.scale;
    created.rendering.sceneColorMap = sceneColor;
    if (isRenderLook(look)) finishFrame(created, look);
    created.update();
    frame = created;
  };
  createFrame();
  device.on(pc.GraphicsDevice.EVENT_RESIZE, createFrame);

  return {
    look,
    sun,
    get frame() {
      return frame;
    },
    requestSceneColor() {
      if (sceneColor) return;
      sceneColor = true;
      if (frame !== null) {
        frame.rendering.sceneColorMap = true;
        frame.update();
      }
    },
    residentBytes: probeBytes,
    ground,
    dispose() {
      if (disposed) return;
      disposed = true;
      ground?.destroy();
      groundMesh?.destroy();
      groundMaterial?.destroy();
      device.off(pc.GraphicsDevice.EVENT_RESIZE, createFrame);
      frame?.destroy();
      frame = null;
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
      scene.fog.density = saved.fogDensity;
      scene.fog.color.copy(saved.fogColour);
      component.clearColor = saved.clearColour;
      component.toneMapping = saved.toneMapping;
      component.farClip = saved.farClip;
      for (const light of saved.lights) light.enabled = true;
    },
  };
}
