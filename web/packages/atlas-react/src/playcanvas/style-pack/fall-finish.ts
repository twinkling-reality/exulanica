import * as pc from 'playcanvas';
import type { RenderFallingWater } from '../generated-tile/look.js';

/**
 * A sheet of falling water, finished in its colour: whitened by the air in it, streaks drawn down it at
 * the look's pace, and foam where it lands. Colour only, in any shading model: a fall has no water behind it to colour by
 * depth, and no ripple normals. Its time is kept by `WaterRipples.animate` (`exuFinishTime`). The
 * figures are the look's (`RenderFallingWater`), else `FALLING_WATER_DEFAULTS`; the streak's two
 * octaves and the foam's breaking are this shader's own shape.
 *
 * GLSL for the WebGL2 device the page asks for. On a WebGPU device the fall keeps its pack's flat
 * colour, as every finish does there (`fallFinishRuns`).
 */
export const fallFinishRuns = (device: pc.GraphicsDevice): boolean => device.isWebGPU !== true;

const ALBEDO = 'void getAlbedo() {';
const BASE = 'void exuFallBase() {';
/** Says a chunk already carries the fall finish. */
const FALL_MARK = 'uniform vec4 exuFallShape;';

const FALL = `
uniform float exuFinishTime;
${FALL_MARK}
uniform vec4 exuFallMotion;
uniform vec4 exuFallFoam;
float exuFallHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float exuFallNoise(vec2 p) {
\tvec2 i = floor(p);
\tvec2 t = fract(p);
\tt = t * t * (3.0 - 2.0 * t);
\treturn mix(mix(exuFallHash(i), exuFallHash(i + vec2(1.0, 0.0)), t.x), mix(exuFallHash(i + vec2(0.0, 1.0)), exuFallHash(i + vec2(1.0, 1.0)), t.x), t.y);
}
void getAlbedo() {
\texuFallBase();
\tdAlbedo = mix(dAlbedo, exuFallFoam.rgb, exuFallFoam.w);
\tfloat across = dot(vPositionW.xz, exuFallMotion.xy) / exuFallShape.z;
\tfloat down = (vPositionW.y + exuFinishTime * exuFallMotion.z) / exuFallShape.w;
\tfloat streak = exuFallNoise(vec2(across, down)) * 0.65 + exuFallNoise(vec2(across * 2.3 + 7.0, down * 1.7 + 3.0)) * 0.35;
\tdAlbedo *= 1.0 + exuFallMotion.w * (2.0 * streak - 1.0);
\tfloat foamHeight = max(exuFallShape.y, 0.0001);
\tfloat foam = 1.0 - smoothstep(0.0, foamHeight, vPositionW.y - exuFallShape.x);
\tfloat broken = exuFallNoise(vec2(across * 1.5, (vPositionW.y - exuFinishTime * exuFallMotion.z * 0.2) / foamHeight * 2.0));
\tdAlbedo = mix(dAlbedo, exuFallFoam.rgb, clamp(foam * (0.6 + 0.4 * broken), 0.0, 1.0));
}
`;

/**
 * A colour chunk with the fall finish set after it: its colour function renamed and called first.
 * A chunk that carries it already is returned as it is; one with no colour function is refused,
 * since a finish set into nothing would silently draw none.
 */
export function withFallFinish(chunk: string): string {
  if (chunk.includes(FALL_MARK)) return chunk;
  if (chunk.split(ALBEDO).length !== 2) throw new TypeError('a colour chunk the fall finish cannot be set into: it has no one colour function');
  return chunk.replace(ALBEDO, BASE) + FALL;
}

/** Where a fall stands: the height it lands at, and whether its sheet runs across east and west. */
export interface FallPlace {
  readonly bottomM: number;
  /** True for a fall facing north or south, whose sheet runs east and west; false for east or west. */
  readonly acrossEast: boolean;
}

/**
 * Give a fall's material the fall finish. False, and nothing set, where the device draws no finish;
 * the caller then keeps the material's flat colour and keeps no time for it.
 */
export function applyFallFinish(device: pc.GraphicsDevice, material: pc.StandardMaterial, fall: RenderFallingWater, place: FallPlace): boolean {
  if (!fallFinishRuns(device)) return false;
  const chunks = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
  const held = (chunks.get('diffusePS') as string | undefined) ?? (pc.ShaderChunks.get(device, pc.SHADERLANGUAGE_GLSL).get('diffusePS') as string | undefined);
  if (held === undefined) throw new TypeError('the engine states no colour chunk to set the fall finish into');
  material.shaderChunksVersion = '2.8';
  chunks.set('diffusePS', withFallFinish(held));
  material.setParameter('exuFinishTime', 0);
  material.setParameter('exuFallShape', [place.bottomM, fall.foamHeightM, fall.streakWidthM, fall.streakLengthM]);
  material.setParameter('exuFallMotion', [place.acrossEast ? 1 : 0, place.acrossEast ? 0 : 1, fall.streakSpeedMps, fall.streakContrast]);
  material.setParameter('exuFallFoam', [...fall.foam, fall.aeration]);
  material.update();
  return true;
}
