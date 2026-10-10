import * as pc from 'playcanvas';
import type { SurfacePattern } from '@exulanica/atlas-core';
import type { Rgb } from '../generated-tile/look.js';

/**
 * A surface's pattern, drawn in its colour.
 *
 * A pattern (`readSurfacePatterns`) is worked in the surface's colour chunk from where each point
 * of the surface is in the world, in metres, so it needs no texture image and no UV and is at
 * physical scale on every box, plane and roof: across the ground for a face that points up, and
 * along the wall and up it for any other. A pattern of lines (courses, boards, strokes, seams)
 * darkens the colour toward the pack's ink where the pack draws ink; a mottle or a ripple, and any
 * pattern where the pack draws none, darkens it toward the colour's own shade. It is worked before
 * the pack's shading is applied, so a toon pack bands it like any colour. Where a pattern would be finer than the picture
 * can show it fades out to the plain colour instead of shimmering.
 *
 * The chunk text is this module's, in GLSL and WGSL; the only values that reach it are a pattern's
 * whole numbers and an ink colour, written at fixed precision. Colour only: nothing is raised.
 */

/** How far up a face must point to be patterned across the ground: the same threshold an up swatch takes. */
const UP_THRESHOLD = 0.72;
/** Half the width of a joint or a seam, in metres. */
const JOINT_M = 0.008;
/** The shade a pattern darkens toward where the pack draws no ink: this share of the colour itself. */
const OWN_SHADE = 0.5;

/** The kinds that are lines (joints, board edges, streaks, seams), which a pack's ink draws; the others are shade. */
const LINE_KINDS: ReadonlySet<SurfacePattern['kind']> = new Set(['courses', 'boards', 'strokes', 'seams']);

const f = (value: number): string => value.toFixed(6);

/** The amount of pattern at a point, 0 to 1, as an expression over `uv` in metres. The same text in both languages but for their vector types. */
function amount(pattern: SurfacePattern, vec2: string): string {
  const a = f(pattern.periodAMm / 1000);
  const b = f(pattern.periodBMm / 1000);
  const joint = f(JOINT_M);
  switch (pattern.kind) {
    case 'courses':
      // Rows b high; each row's joints stand half a block along from the last row's.
      return `max(exuPatternLine(uv.y / ${b}, ${joint} / ${b}), exuPatternLine(uv.x / ${a} + 0.5 * (floor(uv.y / ${b}) - 2.0 * floor(floor(uv.y / ${b}) / 2.0)), ${joint} / ${a}))`;
    case 'boards':
      return `max(exuPatternLine(uv.x / ${a}, ${joint} / ${a}), 0.45 * exuPatternHash(${vec2}(floor(uv.x / ${a}), 7.0)) * exuPatternFade(uv.x / ${a}))`;
    case 'strokes':
      return `max(0.7 * exuPatternNoise(${vec2}(uv.x / ${a}, uv.y / (${a} * 12.0))) * exuPatternFade(uv.x / ${a}), exuPatternLine(uv.y / ${b}, 0.05))`;
    case 'seams':
      return `exuPatternLine(uv.x / ${a}, ${joint} / ${a})`;
    case 'ripples':
      return `(0.5 + 0.5 * sin(6.283185 * (uv.y / ${a} + 0.35 * sin(6.283185 * uv.x / (${a} * 3.1))))) * exuPatternFade(uv.y / ${a})`;
    case 'grain':
      // Patches with soft edges, not an even haze, and a finer mottle inside them.
      return `0.65 * smoothstep(0.3, 0.7, exuPatternNoise(uv / ${a})) * exuPatternFade(uv.x / ${a}) + 0.35 * exuPatternNoise(uv / (${a} * 0.23)) * exuPatternFade(uv.x / (${a} * 0.23))`;
  }
}

/** The colour chunk that draws `pattern`, darkening toward `ink` (linear) or, with none, toward the colour's own shade. */
export function patternChunks(pattern: SurfacePattern, ink: Rgb | null): { readonly glsl: string; readonly wgsl: string } {
  const strength = f(pattern.strengthPermille / 1000);
  // Ink draws lines. A mottle and a ripple are shade, not line: drawn toward ink they blotch a toon pack's ground.
  const inked = ink !== null && LINE_KINDS.has(pattern.kind);
  const toward = (vec3: string): string => (inked ? `${vec3}(${ink.map(f).join(', ')})` : `dAlbedo * ${f(OWN_SHADE)}`);
  return {
    glsl: `
uniform vec3 material_diffuse;
float exuPatternHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float exuPatternNoise(vec2 p) {
\tvec2 i = floor(p);
\tvec2 t = fract(p);
\tt = t * t * (3.0 - 2.0 * t);
\treturn mix(mix(exuPatternHash(i), exuPatternHash(i + vec2(1.0, 0.0)), t.x), mix(exuPatternHash(i + vec2(0.0, 1.0)), exuPatternHash(i + vec2(1.0, 1.0)), t.x), t.y);
}
float exuPatternFade(float t) { return clamp(1.0 - fwidth(t) * 2.0, 0.0, 1.0); }
float exuPatternLine(float t, float w) {
\tfloat d = min(fract(t), 1.0 - fract(t));
\tfloat fw = fwidth(t);
\treturn (1.0 - smoothstep(w, w + max(fw, 0.0001), d)) * clamp(1.0 - fw * 2.0, 0.0, 1.0);
}
void getAlbedo() {
\tdAlbedo = material_diffuse.rgb;
\t#ifdef STD_DIFFUSE_TEXTURE
\t\tdAlbedo *= {STD_DIFFUSE_TEXTURE_DECODE}(texture2DBias({STD_DIFFUSE_TEXTURE_NAME}, {STD_DIFFUSE_TEXTURE_UV}, textureBias)).{STD_DIFFUSE_TEXTURE_CHANNEL};
\t#endif
\tvec3 n = abs(normalize(vNormalW));
\tvec2 uv = n.y > ${f(UP_THRESHOLD)} ? vPositionW.xz : (n.x > n.z ? vec2(vPositionW.z, vPositionW.y) : vec2(vPositionW.x, vPositionW.y));
\tfloat exuPattern = ${amount(pattern, 'vec2')};
\tdAlbedo = mix(dAlbedo, ${toward('vec3')}, clamp(exuPattern, 0.0, 1.0) * ${strength});
}
`,
    wgsl: `
uniform material_diffuse: vec3f;
fn exuPatternHash(p: vec2f) -> f32 { return fract(sin(dot(p, vec2f(127.1, 311.7))) * 43758.5453); }
fn exuPatternNoise(p: vec2f) -> f32 {
\tlet i: vec2f = floor(p);
\tvar t: vec2f = fract(p);
\tt = t * t * (3.0 - 2.0 * t);
\treturn mix(mix(exuPatternHash(i), exuPatternHash(i + vec2f(1.0, 0.0)), t.x), mix(exuPatternHash(i + vec2f(0.0, 1.0)), exuPatternHash(i + vec2f(1.0, 1.0)), t.x), t.y);
}
fn exuPatternFade(t: f32) -> f32 { return clamp(1.0 - fwidth(t) * 2.0, 0.0, 1.0); }
fn exuPatternLine(t: f32, w: f32) -> f32 {
\tlet d: f32 = min(fract(t), 1.0 - fract(t));
\tlet fw: f32 = fwidth(t);
\treturn (1.0 - smoothstep(w, w + max(fw, 0.0001), d)) * clamp(1.0 - fw * 2.0, 0.0, 1.0);
}
fn getAlbedo() {
\tdAlbedo = uniform.material_diffuse.rgb;
\t#ifdef STD_DIFFUSE_TEXTURE
\t\tdAlbedo = dAlbedo * {STD_DIFFUSE_TEXTURE_DECODE}(textureSampleBias({STD_DIFFUSE_TEXTURE_NAME}, {STD_DIFFUSE_TEXTURE_NAME}Sampler, {STD_DIFFUSE_TEXTURE_UV}, uniform.textureBias)).{STD_DIFFUSE_TEXTURE_CHANNEL};
\t#endif
\tlet n: vec3f = abs(normalize(vNormalW));
\tlet uv: vec2f = select(select(vec2f(vPositionW.x, vPositionW.y), vec2f(vPositionW.z, vPositionW.y), n.x > n.z), vPositionW.xz, n.y > ${f(UP_THRESHOLD)});
\tlet exuPattern: f32 = ${amount(pattern, 'vec2f')};
\tdAlbedo = mix(dAlbedo, ${toward('vec3f')}, clamp(exuPattern, 0.0, 1.0) * ${strength});
}
`,
  };
}

/** Give a material a pattern in its colour. Call it before the look's shading is applied or after: the two set different chunks. */
export function applyPattern(material: pc.StandardMaterial, pattern: SurfacePattern, ink: Rgb | null): void {
  const chunks = patternChunks(pattern, ink);
  material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).set('diffusePS', chunks.glsl);
  material.getShaderChunks(pc.SHADERLANGUAGE_WGSL).set('diffusePS', chunks.wgsl);
  material.update();
}
