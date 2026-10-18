/**
 * THE PAINTED SPLAT IN DISPLAY SPACE. A painted world's gaussian splat holds the colours its trainer
 * saw on screen. Every look draws through a camera frame: an HDR scene pass, then exposure, a tone
 * curve, grading, bloom and vignette. A splat drawn inside the scene pass goes through all of them and
 * comes out paler and softer than the trainer's own renders.
 *
 * - The splats under the roots are drawn on their own layer after the scene's (`SPLAT_DISPLAY_LAYER`,
 *   right after the Immediate layer), which the camera frame's after pass draws into the final target
 *   after its compose. Their colours reach the screen as the trainer drew them: no exposure, no tone
 *   curve, no grading, and the output gamma the engine's own splat renderer uses when it tone maps
 *   nothing (the painted colour is written as it is to a gamma target).
 * - No depth buffer of the scene's is bound in that pass, so each splat fragment tests its depth
 *   itself against the scene's linear depth that the frame's depth prepass leaves (`uSceneDepthMap`),
 *   and is dropped where the scene is nearer by more than a bias (metres plus a share of the
 *   distance, `SPLAT_DISPLAY`). The layout's depth-only copies (splat-occlusion.ts) and people write
 *   that depth, so walls and people still cover the splats behind them.
 * - Before that, each splat is tested whole once, in the vertex stage: the scene's depth is read on a
 *   three by three grid across the splat's footprint on screen (three sigma of its largest scale), and
 *   the splat is not drawn at all where every read is nearer than the splat's nearest point by more
 *   than the bias. A splat seen partly between nearer things keeps its fragments and their own test.
 *   A splat wider on screen than `vertexCullMaxPixels` is not tested whole (a gap narrower than the
 *   grid's spacing could be missed), nor is any splat under an orthographic camera.
 * - The engine draws every splat of one layer, for one camera, with one shared material made from the
 *   scene's splat material. The display layer's material is given its own shader code (the output
 *   colour and the depth test) when the engine makes it, and again before any frame in which the
 *   engine has copied the scene's code over it. Splats on other layers keep the engine's code.
 * - Where the camera's frame draws no depth prepass, or the device cannot render the float depth it
 *   writes, or it runs WebGPU (the code is GLSL), the splats stay where they were, in the scene. This
 *   is checked before every frame drawn.
 * - Fog: the trainer drew none, so by default the splats take none (`fog`). With fog on, it is added
 *   as the engine adds it to a splat, without the tone curve.
 * - A camera that does not draw the display layer does not see the splats while they are on it.
 */
import * as pc from 'playcanvas';

/** How the splats are drawn after tone mapping, each a default a caller may replace for its world. */
export interface SplatDisplayLook {
  /** How much nearer than a splat the scene must be to cover it, in metres. */
  readonly depthBiasMetres: number;
  /** And as a share of the splat's distance, so a depth read at the prepass's resolution does not cut
   *  splats lying on a surface seen at a grazing angle. */
  readonly depthBiasShare: number;
  /** Whether the scene's fog is added to the splats, as the engine adds it, without the tone curve. */
  readonly fog: boolean;
  /** Whether a splat entirely behind the scene is dropped whole in the vertex stage, so its fragments
   *  never run their own test. */
  readonly vertexCull: boolean;
  /** The widest footprint radius on screen, in pixels, of a splat dropped whole; wider ones are left
   *  to the test of each fragment. */
  readonly vertexCullMaxPixels: number;
}

export const SPLAT_DISPLAY: SplatDisplayLook = Object.freeze({
  depthBiasMetres: 0.05,
  depthBiasShare: 0.002,
  fog: false,
  vertexCull: true,
  vertexCullMaxPixels: 24,
});

/** The layer the splats are drawn on after tone mapping: right after the Immediate layer. */
export const SPLAT_DISPLAY_LAYER = 'exulanica-painted-splats';

/** The uniform holding the depth bias: x metres, y a share of the distance. */
export const SPLAT_DISPLAY_BIAS_UNIFORM = 'splatDisplay_depthBias';

/** The uniform for the whole-splat test: x 1 when on (a perspective camera), y its widest radius in pixels. */
export const SPLAT_DISPLAY_CULL_UNIFORM = 'splatDisplay_vertexCull';

export interface SplatDisplay {
  /** Whether the splats are drawn after tone mapping now, rather than in the scene. */
  readonly active: boolean;
  /** How many splat components it moves. */
  readonly splats: number;
  /** Takes in splat components added under the roots since. */
  refresh(): void;
  /** Puts every splat back on its own layers and removes the display layer once no one uses it. */
  dispose(): void;
}

/**
 * The splat's colour as it goes to the target: the painted (gamma) colour as it is to a gamma
 * target, decoded for a linear one, with fog (when asked for) added in linear light. The engine's own
 * chunk, with its tone curve left out.
 */
const outputGlsl = (fog: boolean): string => /* glsl */ `
#include "tonemappingPS"
#include "decodePS"
#include "gammaPS"
#include "fogPS"
${fog ? '#if FOG != NONE && !defined(GSPLAT_NO_FOG)\n\t#define GSPLAT_FOG\n#endif' : ''}
// The splat centre's distance ahead of the eye, metres, for the fragment's test against the scene's depth.
varying float vSplatViewZ;
vec3 prepareOutputFromGamma(vec3 gammaColor, float depth) {
	vSplatViewZ = depth;
	vec3 color = gammaColor;
	#if GAMMA == NONE || defined(GSPLAT_FOG)
		color = decodeGamma(color);
	#endif
	#ifdef GSPLAT_FOG
		color = addFog(color, depth);
	#endif
	#if GAMMA != NONE && defined(GSPLAT_FOG)
		color = gammaCorrectOutput(color);
	#endif
	return color;
}
`;

/** The test against the scene's depth that a splat drawn after tone mapping makes for itself. */
const DEPTH_TEST_GLSL = /* glsl */ `
uniform highp sampler2D uSceneDepthMap;
uniform highp vec4 uScreenSize;
uniform highp vec2 ${SPLAT_DISPLAY_BIAS_UNIFORM};
varying float vSplatViewZ;
void modifySplatColor(vec2 gaussianUV, inout vec4 color) {
	highp float splat = vSplatViewZ;
	highp float scene = texture2D(uSceneDepthMap, gl_FragCoord.xy * uScreenSize.zw).r;
	if (scene < splat - (${SPLAT_DISPLAY_BIAS_UNIFORM}.x + ${SPLAT_DISPLAY_BIAS_UNIFORM}.y * splat)) discard;
}
`;

/**
 * The whole-splat test in the vertex stage. Only the display layer's material, which the engine makes
 * for its unified splat renderer, gets it: that renderer draws from a node at the origin, so a splat's
 * model centre is its world centre. The engine declares its own matrices after this code, so the view
 * projection is read here by the name every draw is given. A splat dropped has its alpha set to zero,
 * which the engine's vertex stage then refuses for all four corners alike.
 */
const VERTEX_CULL_GLSL = /* glsl */ `
uniform mat4 matrix_viewProjection;
uniform highp sampler2D uSceneDepthMap;
uniform highp vec4 uScreenSize;
uniform highp vec2 ${SPLAT_DISPLAY_BIAS_UNIFORM};
uniform highp vec2 ${SPLAT_DISPLAY_CULL_UNIFORM};
float splatDisplayReach;
void modifySplatCenter(inout vec3 center) {
}
void modifySplatRotationScale(vec3 originalCenter, vec3 modifiedCenter, inout vec4 rotation, inout vec3 scale) {
	splatDisplayReach = 3.0 * max(max(scale.x, scale.y), scale.z);
}
void modifySplatColor(vec3 center, inout vec4 color) {
	if (${SPLAT_DISPLAY_CULL_UNIFORM}.x < 0.5) return;
	vec4 clip = matrix_viewProjection * vec4(center, 1.0);
	if (clip.w <= splatDisplayReach) return;
	// The footprint's radius on screen, from the projection's scale along each screen axis.
	vec2 focal = vec2(
		length(vec3(matrix_viewProjection[0][0], matrix_viewProjection[1][0], matrix_viewProjection[2][0])),
		length(vec3(matrix_viewProjection[0][1], matrix_viewProjection[1][1], matrix_viewProjection[2][1])));
	vec2 radius = splatDisplayReach * focal / clip.w * 0.5;
	if (max(radius.x * uScreenSize.x, radius.y * uScreenSize.y) > ${SPLAT_DISPLAY_CULL_UNIFORM}.y) return;
	vec2 uv = clip.xy / clip.w * 0.5 + 0.5;
	highp float nearest = clip.w - splatDisplayReach;
	highp float covered = nearest - (${SPLAT_DISPLAY_BIAS_UNIFORM}.x + ${SPLAT_DISPLAY_BIAS_UNIFORM}.y * nearest);
	for (int i = -1; i <= 1; i++) {
		for (int j = -1; j <= 1; j++) {
			vec2 at = uv + vec2(float(i), float(j)) * radius;
			if (any(lessThan(at, vec2(0.0))) || any(greaterThan(at, vec2(1.0)))) return;
			if (textureLod(uSceneDepthMap, at, 0.0).r >= covered) return;
		}
	}
	color.a = 0.0;
}
`;

/** Gives the display layer's splat material its own output colour and depth tests, if it lacks them. */
function dress(material: pc.Material, output: string, bias: readonly number[], cull: readonly number[]): boolean {
  const chunks = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
  material.setParameter(SPLAT_DISPLAY_BIAS_UNIFORM, bias as number[]);
  material.setParameter(SPLAT_DISPLAY_CULL_UNIFORM, cull as number[]);
  if (chunks.get('gsplatOutputVS') === output && chunks.get('gsplatModifyPS') === DEPTH_TEST_GLSL
    && chunks.get('gsplatModifyVS') === VERTEX_CULL_GLSL) return false;
  chunks.set('gsplatOutputVS', output);
  chunks.set('gsplatModifyPS', DEPTH_TEST_GLSL);
  chunks.set('gsplatModifyVS', VERTEX_CULL_GLSL);
  material.update();
  return true;
}

/** Whether `camera` draws through a frame whose depth prepass leaves the scene's linear depth. */
function frameLeavesDepth(camera: pc.CameraComponent, device: pc.GraphicsDevice): boolean {
  const frame = camera.framePasses[0] as { readonly prePass?: unknown } | undefined;
  return device.isWebGPU !== true && device.textureFloatRenderable && frame?.prePass != null;
}

/** Each layer composition's display layer, held while any display uses it. */
const displayLayers = new WeakMap<pc.LayerComposition, { layer: pc.Layer; holders: number }>();

/** The display layer of `app`'s scene, made right after the Immediate layer if no one holds it yet. */
function holdDisplayLayer(app: pc.AppBase): pc.Layer {
  const layers = app.scene.layers;
  const held = displayLayers.get(layers);
  if (held !== undefined) {
    held.holders += 1;
    return held.layer;
  }
  const layer = layers.getLayerByName(SPLAT_DISPLAY_LAYER)
    ?? new pc.Layer({ name: SPLAT_DISPLAY_LAYER, transparentSortMode: pc.SORTMODE_BACK2FRONT });
  if (!layers.layerList.includes(layer)) {
    const immediate = layers.getLayerById(pc.LAYERID_IMMEDIATE);
    const after = immediate === null ? -1 : layers.getTransparentIndex(immediate);
    if (after < 0) layers.push(layer);
    else layers.insert(layer, after + 1);
  }
  displayLayers.set(layers, { layer, holders: 1 });
  return layer;
}

function releaseDisplayLayer(app: pc.AppBase, camera: pc.CameraComponent): void {
  const layers = app.scene.layers;
  const held = displayLayers.get(layers);
  if (held === undefined || (held.holders -= 1) > 0) return;
  displayLayers.delete(layers);
  for (const one of app.systems.camera?.cameras ?? [camera]) {
    if (one.layers.includes(held.layer.id)) one.layers = one.layers.filter((id) => id !== held.layer.id);
  }
  layers.remove(held.layer);
}

/**
 * Draws the splats under `root` (one entity or several) after `camera`'s tone mapping wherever its
 * frame leaves the scene's depth, checked before every frame drawn, until disposed.
 */
export function splatsAfterToneMapping(
  root: pc.Entity | readonly pc.Entity[],
  camera: pc.CameraComponent,
  { look = SPLAT_DISPLAY }: { readonly look?: SplatDisplayLook } = {},
): SplatDisplay {
  const roots: readonly pc.Entity[] = Array.isArray(root) ? root : [root as pc.Entity];
  const app = camera.system.app;
  const device = app.graphicsDevice;
  const system = app.systems.gsplat as (pc.GSplatComponentSystem & pc.EventHandler) | undefined;
  const layer = holdDisplayLayer(app);
  if (!camera.layers.includes(layer.id)) camera.layers = [...camera.layers, layer.id];
  // Each splat component's own layers, given back when it returns to the scene.
  const own = new Map<pc.GSplatComponent, readonly number[]>();
  const output = outputGlsl(look.fog);
  const bias = [look.depthBiasMetres, look.depthBiasShare];
  // Off under an orthographic camera, whose clip w is no distance.
  const cull = (): number[] => [
    look.vertexCull && camera.projection === pc.PROJECTION_PERSPECTIVE ? 1 : 0, look.vertexCullMaxPixels,
  ];
  let active = false;
  let disposed = false;

  const place = (component: pc.GSplatComponent, after: boolean): void => {
    const target = after ? [layer.id] : own.get(component)!;
    if (component.layers.length !== target.length || component.layers.some((id, index) => id !== target[index])) {
      component.layers = [...target];
    }
  };
  const refresh = (): void => {
    if (disposed) return;
    for (const component of roots.flatMap((one) => one.findComponents('gsplat') as pc.GSplatComponent[])) {
      if (own.has(component)) continue;
      own.set(component, [...component.layers]);
      place(component, active);
    }
  };
  // The engine made a splat material for a camera and layer: the display layer's gets its code.
  const created = (material: pc.Material, forCamera: pc.Camera, forLayer: pc.Layer): void => {
    if (forLayer === layer && forCamera === camera.camera) dress(material, output, bias, cull());
  };
  // Before every frame drawn: after tone mapping where the camera's frame leaves the scene's depth.
  const choose = (): void => {
    const next = frameLeavesDepth(camera, device);
    if (next !== active) {
      active = next;
      for (const component of own.keys()) place(component, active);
    }
    if (!active) return;
    const material = system?.getMaterial(camera.camera, layer);
    if (material) dress(material, output, bias, cull());
  };

  system?.on('material:created', created);
  app.on('prerender', choose);
  refresh();
  return {
    get active() { return active; },
    get splats() { return own.size; },
    refresh,
    dispose() {
      if (disposed) return;
      disposed = true;
      app.off('prerender', choose);
      system?.off('material:created', created);
      for (const component of own.keys()) place(component, false);
      own.clear();
      active = false;
      releaseDisplayLayer(app, camera);
    },
  };
}
