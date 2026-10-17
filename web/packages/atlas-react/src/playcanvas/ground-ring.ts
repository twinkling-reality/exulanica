/**
 * THE RING ON THE GROUND. The in-world design marks a chosen character with a ring at its feet
 * (DESIGN's specification 5.4 and ruling J21): a soft fill, a glow and a thin white line. Drawn in
 * the world rather than over it, so what stands in front of the feet (a wall, a bench, the
 * character's own legs) covers the ring as it covers the feet.
 *
 * - One flat quad on the ground, laid on the ground point it is given and moved by its transform
 *   alone; a new radius is a uniform, never new geometry.
 * - It is part of the interface, so it shows the design's own colours: under a camera frame (the
 *   look's HDR scene pass, then tone mapping and grading) it is drawn after them, on its own layer
 *   after the scene's (`RING_LAYER`), testing its depth itself against the scene's linear depth that
 *   the frame's depth prepass leaves (`uSceneDepthMap`). Where a frame draws no prepass, or there is
 *   no frame, it is drawn in the scene as any transparent surface is, with the depth test on and
 *   depth writing off. Either way it is covered by what is in front and covers nothing.
 * - The line's and the glow's widths are held in CSS pixels (from the screen-space rate of change of
 *   the distance to the centre, times the canvas's pixels per CSS pixel), so the ring reads the same
 *   near and far and on any screen.
 * - The glow is a band blurred by a Gaussian, as an SVG stroke under a blur filter draws it: strongest
 *   under the line and fading to nothing, with no flat plateau.
 * - A surface that writes no depth does not cover it. On a slope or a step part of the ring may sink
 *   into the ground; it is lifted a little above its point to keep it off level ground.
 * - The shader is GLSL. On a device that runs WebGPU the ring is not drawn (`drawn` is false).
 */
import * as pc from 'playcanvas';

/** The ring's look and placement, each a default a caller may replace (frame 05, spec 5.4). */
export const GROUND_RING = Object.freeze({
  /** The ring's colour for its fill and glow (`--live`), and its line's (white), as sRGB 0 to 1. A
   *  caller with the design's tokens passes `--live` read from them. */
  live: Object.freeze([0xbf / 255, 0xe9 / 255, 0xf0 / 255] as const),
  line: Object.freeze([1, 1, 1] as const),
  /** The line's width and the glow band's, in CSS pixels, and the glow's blur (a Gaussian's standard deviation). */
  linePx: 2.2,
  glowPx: 6,
  glowBlurPx: 3,
  /** The glow band's opacity before its blur, and the fill's at the ring's centre (it fades to none at the line). */
  glowAlpha: 0.5,
  fillAlpha: 0.24,
  /** How far the quad reaches past the ring, as a share of the radius, so the glow is never cut. */
  reachShare: 0.6,
  /** How far above its ground point the ring is laid, in metres, so it does not fight level ground. */
  liftMetres: 0.02,
  /** Drawn after tone mapping, how much nearer than the ring the scene must be to cover it: metres, and
   *  a share of the distance, so a depth read at the prepass's resolution never cuts it on level ground. */
  depthBiasMetres: 0.03,
  depthBiasShare: 0.002,
});

type Widened<T> = T extends number ? number : T extends readonly number[] ? { readonly [I in keyof T]: number } : T;
/** A ring's look: GROUND_RING's fields, each any value of its kind, so a caller's look need not be the default's. */
export type GroundRingLook = { readonly [K in keyof typeof GROUND_RING]: Widened<(typeof GROUND_RING)[K]> };

/** The layer the ring is drawn on after tone mapping: after every layer of the scene's own. */
export const RING_LAYER = 'exulanica-world-marks';

export interface GroundRing {
  /** Whether this device draws the ring at all (false on WebGPU). */
  readonly drawn: boolean;
  /** Whether it is drawn after tone mapping now (in the design's colours), rather than in the scene. */
  readonly afterToneMapping: boolean;
  /** The ring's entity, for a caller that checks where it stands. */
  readonly entity: pc.Entity;
  /** Lays the ring on `point` (world metres) with `radiusMetres`, and shows it. */
  place(point: { readonly x: number; readonly y: number; readonly z: number }, radiusMetres: number): void;
  hide(): void;
  dispose(): void;
}

const VERTEX_GLSL = /* glsl */ `
attribute vec3 aPosition;
uniform mat4 matrix_model;
uniform mat4 matrix_view;
uniform mat4 matrix_viewProjection;
// x the ring's radius, y how far the quad reaches from the centre, both metres.
uniform vec4 uRing;
varying vec2 vOffset;
// How far ahead of the eye the point is, metres, as the depth prepass states the scene's.
varying float vViewZ;
void main(void) {
  vOffset = aPosition.xz * uRing.y;
  vec4 world = matrix_model * vec4(vOffset.x, 0.0, vOffset.y, 1.0);
  vViewZ = -(matrix_view * world).z;
  gl_Position = matrix_viewProjection * world;
}
`;

/** The test against the scene's depth that a ring drawn after tone mapping makes for itself. */
const SCENE_DEPTH_GLSL = /* glsl */ `
uniform highp sampler2D uSceneDepthMap;
uniform vec4 uScreenSize;
// x metres, y a share of the distance
uniform vec2 uDepthBias;
void coveredByScene(void) {
  float scene = texture2D(uSceneDepthMap, gl_FragCoord.xy * uScreenSize.zw).r;
  if (scene < vViewZ - (uDepthBias.x + uDepthBias.y * vViewZ)) discard;
}
`;

const fragmentGlsl = (afterToneMapping: boolean): string => /* glsl */ `
precision highp float;
varying float vViewZ;
${afterToneMapping ? SCENE_DEPTH_GLSL : ''}
uniform vec4 uRing;
// x line px, y glow band px, z glow blur (standard deviation) px, w glow alpha; framebuffer pixels
uniform vec4 uWidths;
// rgb the glow and fill colour, a the fill's alpha at the centre
uniform vec4 uLive;
uniform vec3 uLine;
varying vec2 vOffset;
// The normal distribution's cumulative function, from erf (Abramowitz and Stegun 7.1.26).
float phi(float x) {
  float z = abs(x) * 0.70710678;
  float t = 1.0 / (1.0 + 0.3275911 * z);
  float e = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * exp(-z * z);
  return 0.5 * (1.0 + sign(x) * e);
}
vec4 over(vec4 top, vec4 under) {
  float a = top.a + under.a * (1.0 - top.a);
  vec3 rgb = a > 0.0 ? (top.rgb * top.a + under.rgb * under.a * (1.0 - top.a)) / a : vec3(0.0);
  return vec4(rgb, a);
}
void main(void) {
  ${afterToneMapping ? 'coveredByScene();' : ''}
  float d = length(vOffset);
  float perPixel = max(length(vec2(dFdx(d), dFdy(d))), 1e-6);
  float px = abs(d - uRing.x) / perPixel;
  float fill = d < uRing.x ? uLive.a * (1.0 - d / uRing.x) : 0.0;
  // The glow band convolved with the Gaussian; at the defaults 0.34 under the line, 0.24 at 3 px,
  // 0.08 at 6 px and 0.01 at 9 px.
  float band = uWidths.y * 0.5, sigma = max(uWidths.z, 1e-3);
  float glow = uWidths.w * (phi((px + band) / sigma) - phi((px - band) / sigma));
  float line = 1.0 - smoothstep(uWidths.x * 0.5 - 0.5, uWidths.x * 0.5 + 0.5, px);
  vec4 colour = over(vec4(uLine, line), over(vec4(uLive.rgb, glow), vec4(uLive.rgb, fill)));
  if (colour.a <= 0.002) discard;
  gl_FragColor = colour;
}
`;

/** `ShaderDesc` is documented but not exported from the engine's type surface, so it is restated. */
interface ShaderDesc {
  uniqueName: string;
  attributes?: Record<string, string>;
  vertexGLSL?: string;
  fragmentGLSL?: string;
}

/** The ring's widths for the shader, in framebuffer pixels at `pixelRatio` framebuffer pixels a CSS pixel. */
function widths(look: GroundRingLook, pixelRatio: number): Float32Array {
  return new Float32Array([look.linePx * pixelRatio, look.glowPx * pixelRatio, look.glowBlurPx * pixelRatio, look.glowAlpha]);
}

/**
 * The ring's material: transparent, writing no depth, both sides. In the scene it is depth-tested;
 * after tone mapping, where no depth buffer of the scene's is bound, it tests the scene's depth itself.
 */
export function groundRingMaterial(look: GroundRingLook = GROUND_RING, pixelRatio = 1, afterToneMapping = false): pc.ShaderMaterial {
  const material = new pc.ShaderMaterial({
    uniqueName: afterToneMapping ? 'exulanica-ground-ring-after-tone-mapping' : 'exulanica-ground-ring',
    attributes: { aPosition: pc.SEMANTIC_POSITION },
    vertexGLSL: VERTEX_GLSL,
    fragmentGLSL: fragmentGlsl(afterToneMapping),
  } as ShaderDesc);
  material.name = afterToneMapping ? 'ground-ring:after-tone-mapping' : 'ground-ring:in-scene';
  material.blendType = pc.BLEND_NORMAL;
  material.depthTest = !afterToneMapping;
  material.depthWrite = false;
  material.cull = pc.CULLFACE_NONE;
  material.setParameter('uWidths', widths(look, pixelRatio));
  material.setParameter('uLive', new Float32Array([look.live[0], look.live[1], look.live[2], look.fillAlpha]));
  material.setParameter('uLine', new Float32Array([look.line[0], look.line[1], look.line[2]]));
  if (afterToneMapping) material.setParameter('uDepthBias', new Float32Array([look.depthBiasMetres, look.depthBiasShare]));
  material.update();
  return material;
}

/** A unit quad in the ground's plane, from -1 to 1 along x and z, both faces. */
function unitQuad(device: pc.GraphicsDevice): pc.Mesh {
  const mesh = new pc.Mesh(device);
  mesh.setPositions([-1, 0, -1, 1, 0, -1, 1, 0, 1, -1, 0, 1]);
  mesh.setIndices([0, 2, 1, 0, 3, 2]);
  mesh.update(pc.PRIMITIVE_TRIANGLES);
  return mesh;
}

/** The layer after the scene's that `camera` draws the ring on after tone mapping, made once per scene. */
function ringLayer(app: pc.AppBase, camera: pc.CameraComponent): pc.Layer {
  let layer = app.scene.layers.getLayerByName(RING_LAYER);
  if (layer === null) {
    layer = new pc.Layer({ name: RING_LAYER, transparentSortMode: pc.SORTMODE_BACK2FRONT });
    app.scene.layers.push(layer);
  }
  if (!camera.layers.includes(layer.id)) camera.layers = [...camera.layers, layer.id];
  return layer;
}

/** Whether `camera` draws through a frame whose depth prepass leaves the scene's linear depth. */
function frameLeavesDepth(camera: pc.CameraComponent, device: pc.GraphicsDevice): boolean {
  const frame = camera.framePasses[0] as { readonly prePass?: unknown } | undefined;
  return device.textureFloatRenderable && frame?.prePass != null;
}

/**
 * A ring on the ground under `parent` (the scene's root unless given), hidden until placed.
 * `invalidate` asks the renderer for a frame when the ring moves, for a scene drawn on demand.
 * With `camera`, the ring is drawn after that camera's tone mapping wherever its frame leaves the
 * scene's depth, checked before every frame drawn; without one, it is always drawn in the scene.
 */
export function createGroundRing(
  app: pc.AppBase,
  { parent, camera, invalidate, look = GROUND_RING }: {
    readonly parent?: pc.Entity;
    readonly camera?: pc.CameraComponent;
    readonly invalidate?: () => void;
    readonly look?: GroundRingLook;
  } = {},
): GroundRing {
  const entity = new pc.Entity('ground-ring');
  entity.enabled = false;
  const drawn = app.graphicsDevice.isWebGPU !== true;
  let mesh: pc.Mesh | null = null;
  let material: pc.ShaderMaterial | null = null;
  let afterMaterial: pc.ShaderMaterial | null = null;
  let instance: pc.MeshInstance | null = null;
  let layer: pc.Layer | null = null;
  let afterToneMapping = false;
  const ring = new Float32Array([0, 0, 0, 0]);
  const both = (name: string, value: Float32Array): void => {
    material?.setParameter(name, value);
    afterMaterial?.setParameter(name, value);
  };
  const device = app.graphicsDevice;
  // The canvas's framebuffer pixels a CSS pixel (the renderer caps the device's ratio), read again on resize.
  const pixelRatio = (): number => {
    const shown = device.canvas?.clientWidth ?? 0;
    return shown > 0 && device.width > 0 ? device.width / shown : 1;
  };
  let ratio = pixelRatio();
  const resized = (): void => {
    const next = pixelRatio();
    if (next === ratio || !material) return;
    ratio = next;
    both('uWidths', widths(look, ratio));
    if (entity.enabled) invalidate?.();
  };
  if (drawn) {
    mesh = unitQuad(device);
    material = groundRingMaterial(look, ratio);
    device.on(pc.GraphicsDevice.EVENT_RESIZE, resized);
    instance = new pc.MeshInstance(mesh, material);
    instance.castShadow = false;
    instance.receiveShadow = false;
    entity.addComponent('render', { meshInstances: [instance], castShadows: false, receiveShadows: false });
    if (camera !== undefined) {
      afterMaterial = groundRingMaterial(look, ratio, true);
      layer = ringLayer(app, camera);
    }
  }
  (parent ?? app.root).addChild(entity);
  // Before every frame drawn: after tone mapping where the camera's frame leaves the scene's depth.
  const choose = (): void => {
    if (instance === null || camera === undefined || layer === null) return;
    const next = frameLeavesDepth(camera, device);
    if (next === afterToneMapping) return;
    afterToneMapping = next;
    instance.material = next ? afterMaterial! : material!;
    entity.render!.layers = [next ? layer.id : pc.LAYERID_WORLD];
  };
  if (layer !== null) app.on('prerender', choose);
  let at: readonly [number, number, number, number] | null = null;
  return {
    drawn,
    entity,
    get afterToneMapping() { return afterToneMapping; },
    place(point, radiusMetres) {
      if (!drawn || !(radiusMetres > 0)) return;
      const next = [point.x, point.y + look.liftMetres, point.z, radiusMetres] as const;
      const moved = at === null || next.some((value, index) => value !== at![index]) || !entity.enabled;
      if (!moved) return;
      if (at === null || at[3] !== radiusMetres) {
        ring[0] = radiusMetres;
        ring[1] = radiusMetres * (1 + look.reachShare);
        both('uRing', ring);
      }
      at = next;
      entity.setPosition(next[0], next[1], next[2]);
      entity.enabled = true;
      invalidate?.();
    },
    hide() {
      if (!entity.enabled) return;
      entity.enabled = false;
      invalidate?.();
    },
    dispose() {
      if (drawn) device.off(pc.GraphicsDevice.EVENT_RESIZE, resized);
      if (layer !== null) app.off('prerender', choose);
      entity.destroy();
      material?.destroy();
      afterMaterial?.destroy();
      mesh?.destroy();
    },
  };
}
