/**
 * THE RING ON THE GROUND. The in-world design marks a chosen character with a ring at its feet
 * (DESIGN's specification 5.4 and ruling J21): a soft fill, a glow and a thin white line. Drawn in
 * the world rather than over it, so what stands in front of the feet (a wall, a bench, the
 * character's own legs) covers the ring as it covers the feet.
 *
 * - One flat quad on the ground, laid on the ground point it is given and moved by its transform
 *   alone; a new radius is a uniform, never new geometry.
 * - A transparent material, drawn after the world's solid surfaces with the depth test on and depth
 *   writing off, so it is covered by what is in front and covers nothing.
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
});

export interface GroundRing {
  /** Whether this device draws the ring at all (false on WebGPU). */
  readonly drawn: boolean;
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
uniform mat4 matrix_viewProjection;
// x the ring's radius, y how far the quad reaches from the centre, both metres.
uniform vec4 uRing;
varying vec2 vOffset;
void main(void) {
  vOffset = aPosition.xz * uRing.y;
  gl_Position = matrix_viewProjection * matrix_model * vec4(vOffset.x, 0.0, vOffset.y, 1.0);
}
`;

const FRAGMENT_GLSL = /* glsl */ `
precision highp float;
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
function widths(look: typeof GROUND_RING, pixelRatio: number): Float32Array {
  return new Float32Array([look.linePx * pixelRatio, look.glowPx * pixelRatio, look.glowBlurPx * pixelRatio, look.glowAlpha]);
}

/** The ring's material: transparent, depth-tested, writing no depth, both sides. */
export function groundRingMaterial(look: typeof GROUND_RING = GROUND_RING, pixelRatio = 1): pc.ShaderMaterial {
  const material = new pc.ShaderMaterial({
    uniqueName: 'exulanica-ground-ring',
    attributes: { aPosition: pc.SEMANTIC_POSITION },
    vertexGLSL: VERTEX_GLSL,
    fragmentGLSL: FRAGMENT_GLSL,
  } as ShaderDesc);
  material.blendType = pc.BLEND_NORMAL;
  material.depthTest = true;
  material.depthWrite = false;
  material.cull = pc.CULLFACE_NONE;
  material.setParameter('uWidths', widths(look, pixelRatio));
  material.setParameter('uLive', new Float32Array([look.live[0], look.live[1], look.live[2], look.fillAlpha]));
  material.setParameter('uLine', new Float32Array([look.line[0], look.line[1], look.line[2]]));
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

/**
 * A ring on the ground under `parent` (the scene's root unless given), hidden until placed.
 * `invalidate` asks the renderer for a frame when the ring moves, for a scene drawn on demand.
 */
export function createGroundRing(
  app: pc.AppBase,
  { parent, invalidate, look = GROUND_RING }: { readonly parent?: pc.Entity; readonly invalidate?: () => void; readonly look?: typeof GROUND_RING } = {},
): GroundRing {
  const entity = new pc.Entity('ground-ring');
  entity.enabled = false;
  const drawn = app.graphicsDevice.isWebGPU !== true;
  let mesh: pc.Mesh | null = null;
  let material: pc.ShaderMaterial | null = null;
  const ring = new Float32Array([0, 0, 0, 0]);
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
    material.setParameter('uWidths', widths(look, ratio));
    if (entity.enabled) invalidate?.();
  };
  if (drawn) {
    mesh = unitQuad(device);
    material = groundRingMaterial(look, ratio);
    device.on(pc.GraphicsDevice.EVENT_RESIZE, resized);
    const instance = new pc.MeshInstance(mesh, material);
    instance.castShadow = false;
    instance.receiveShadow = false;
    entity.addComponent('render', { meshInstances: [instance], castShadows: false, receiveShadows: false });
  }
  (parent ?? app.root).addChild(entity);
  let at: readonly [number, number, number, number] | null = null;
  return {
    drawn,
    entity,
    place(point, radiusMetres) {
      if (!drawn || !(radiusMetres > 0)) return;
      const next = [point.x, point.y + look.liftMetres, point.z, radiusMetres] as const;
      const moved = at === null || next.some((value, index) => value !== at![index]) || !entity.enabled;
      if (!moved) return;
      if (at === null || at[3] !== radiusMetres) {
        ring[0] = radiusMetres;
        ring[1] = radiusMetres * (1 + look.reachShare);
        material!.setParameter('uRing', ring);
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
      entity.destroy();
      material?.destroy();
      mesh?.destroy();
    },
  };
}
