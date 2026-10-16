import * as pc from 'playcanvas';
import type { LandSurfaces } from '@exulanica/atlas-core';

/**
 * The look of a site's near land where it is not lawn: sand by the sea, planting on banks too steep
 * to mow, rock on faces too steep to hold soil, as the land's own surfaces state them
 * (`assets/catalogs/landform/landform-surface.v1.json`, the bands worn on near land).
 *
 * THE COLOUR CHUNK IS WRAPPED, NOT REPLACED, as the ground finish wraps it (`../style-pack/ground-finish.ts`):
 * the material's colour function (a pack's swatch or texture, a pattern, the finish's tone and wet
 * band) is renamed and called first, and each band is then mixed over the colour it made. The slope
 * is read from the land's own surface (`dVertexNormalW`, the smooth normal of the mesh), never from
 * a normal map, so a textured pack does not speckle the edges; every threshold is moved by noise in
 * the world's metres at two scales, so a band's edge wanders as it does on a hillside and never
 * follows the one-metre grid the land is sampled on.
 *
 * GLSL ONLY, as the finish is: on a WebGPU device the near land wears its base ground alone.
 * PRESENTATION ONLY: nothing here changes where the land is or where anyone walks.
 */

const BASE = 'void exuLandBase() {';
const ALBEDO = 'void getAlbedo() {';
/** Says a colour chunk already carries the land's bands. */
const MARK = '// exulanica: land surfaces';

const f = (value: number): string => (Number.isInteger(value) ? `${value}.0` : String(value));

/**
 * The land's bands set after a colour chunk, or null where the chunk has no one colour function.
 * Every band's height is above the sea's level: `datumMm` is how far above the sea the scene's own
 * level 0 lies (a floating island's level, for land drawn in a frame that stands on it), none for
 * land drawn in the sea's frame.
 */
export function withLandSurfaces(chunk: string, surfaces: LandSurfaces, sea: boolean, datumMm = 0): string | null {
  if (chunk.includes(MARK)) return chunk;
  if (chunk.split(ALBEDO).length !== 2) return null;
  const { noise } = surfaces;
  const bands = surfaces.bands.filter((band) => band.near && (!band.needsSea || sea)).map((band) => {
    const bySlope = band.slopePermille === null ? '1.0'
      : `smoothstep(${f(band.slopePermille[0])} * moved, ${f(band.slopePermille[1])} * moved, slope)`;
    let byHeight = '1.0';
    if (band.heightMm !== null) {
      const [comeIn, wholeFrom, wholeTo, goneBy] = band.heightMm;
      const rising = wholeFrom > comeIn ? `smoothstep(${f(comeIn)} * moved, ${f(wholeFrom)} * moved, h)` : `step(${f(comeIn)} * moved, h)`;
      const falling = goneBy > wholeTo ? `(1.0 - smoothstep(${f(wholeTo)} * moved, ${f(goneBy)} * moved, h))` : `step(h, ${f(wholeTo)} * moved)`;
      byHeight = `${rising} * ${falling}`;
    }
    const [r, g, b] = band.linear;
    return `\t// ${band.key}\n\tdAlbedo = mix(dAlbedo, vec3(${f(r)}, ${f(g)}, ${f(b)}), ${bySlope} * ${byHeight});`;
  });
  return `${chunk.replace(ALBEDO, BASE)}
${MARK}
float exuLandHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float exuLandNoise(vec2 p) {
\tvec2 i = floor(p);
\tvec2 t = fract(p);
\tt = t * t * (3.0 - 2.0 * t);
\treturn mix(mix(exuLandHash(i), exuLandHash(i + vec2(1.0, 0.0)), t.x), mix(exuLandHash(i + vec2(0.0, 1.0)), exuLandHash(i + vec2(1.0, 1.0)), t.x), t.y);
}
void getAlbedo() {
\texuLandBase();
\tfloat up = clamp(abs(dVertexNormalW.y), 0.02, 1.0);
\tfloat slope = sqrt(max(1.0 - up * up, 0.0)) / up * 1000.0;
\tvec2 p = vPositionW.xz;
\tfloat shift = (2.0 * exuLandNoise(p / ${f(noise.broadM)}) - 1.0) * ${f(1 - noise.fineShare)} + (2.0 * exuLandNoise(p / ${f(noise.fineM)} + vec2(17.0, 3.0)) - 1.0) * ${f(noise.fineShare)};
\tfloat moved = 1.0 + ${f(noise.jitter)} * shift;
\tfloat h = vPositionW.y * 1000.0${datumMm === 0 ? '' : ` + ${f(datumMm)}`};
${bands.join('\n')}
}
`;
}

/**
 * A copy of `material` wearing the land's bands over its own colour, or null where they cannot be
 * set: a WebGPU device, or a colour chunk with no one colour function. The caller owns the copy.
 * `datumMm` is how far above the sea the scene's level 0 lies, as `withLandSurfaces` takes it.
 */
export function landSurfaceMaterial(device: pc.GraphicsDevice, material: pc.Material, surfaces: LandSurfaces, sea: boolean, datumMm = 0): pc.StandardMaterial | null {
  if (device.isWebGPU === true || !(material instanceof pc.StandardMaterial)) return null;
  const held = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).get('diffusePS') as string | undefined;
  const plain = pc.ShaderChunks.get(device, pc.SHADERLANGUAGE_GLSL).get('diffusePS') as string | undefined;
  const chunk = held ?? plain;
  const wrapped = chunk === undefined ? null : withLandSurfaces(chunk, surfaces, sea, datumMm);
  if (wrapped === null) return null;
  const copy = material.clone();
  copy.name = `site-land:surfaces:${material.name}`;
  copy.shaderChunksVersion = '2.8';
  copy.getShaderChunks(pc.SHADERLANGUAGE_GLSL).set('diffusePS', wrapped);
  copy.update();
  return copy;
}
