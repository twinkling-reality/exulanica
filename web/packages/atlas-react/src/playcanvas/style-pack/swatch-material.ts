import * as pc from 'playcanvas';
import type { Srgb8, StylePackSwatch } from '@exulanica/atlas-core';
import type { RenderShading } from '../generated-tile/look.js';
import { applyShading } from '../generated-tile/shading.js';
import { linearRgb } from './preset-look.js';

/**
 * Materials from a pack's palette.
 *
 * A swatch is a colour (sRGB bytes, which is what a material's colour inputs take), a roughness, a
 * metalness and an emission share, all per mille; a swatch material draws a surface in that colour
 * with the look's shading model. An UP swatch colours the faces of the same surface that point up (a
 * roof, a sill, a coping) apart from its walls, by the face's own normal: the pack dresses a whole
 * texture set at once, and a town's tiles draw a building's walls and roof from one set.
 *
 * The chunk text is this module's, in GLSL and WGSL; the only values that reach it are a swatch's
 * bytes, converted to linear light at fixed precision.
 */

/** How far up a face must point to take the up swatch: about 44 degrees from level. */
const UP_THRESHOLD = 0.72;

const f = (value: number): string => value.toFixed(6);

/** The diffuse chunk that colours upward faces `up`, keeping a texture's detail where there is one. */
export function upChunks(up: Srgb8): { readonly glsl: string; readonly wgsl: string } {
  const [r, g, b] = linearRgb(up).map(f);
  return {
    glsl: `
uniform vec3 material_diffuse;
void getAlbedo() {
\tdAlbedo = material_diffuse.rgb;
\t#ifdef STD_DIFFUSE_TEXTURE
\t\tvec3 albedoTexture = {STD_DIFFUSE_TEXTURE_DECODE}(texture2DBias({STD_DIFFUSE_TEXTURE_NAME}, {STD_DIFFUSE_TEXTURE_UV}, textureBias)).{STD_DIFFUSE_TEXTURE_CHANNEL};
\t\tdAlbedo *= albedoTexture;
\t\tfloat detail = 0.55 + 0.9 * dot(albedoTexture, vec3(0.3333));
\t#else
\t\tfloat detail = 1.0;
\t#endif
\tfloat up = step(${f(UP_THRESHOLD)}, normalize(vNormalW).y);
\tdAlbedo = mix(dAlbedo, vec3(${r}, ${g}, ${b}) * detail, up);
}
`,
    wgsl: `
uniform material_diffuse: vec3f;
fn getAlbedo() {
\tdAlbedo = uniform.material_diffuse.rgb;
\t#ifdef STD_DIFFUSE_TEXTURE
\t\tvar albedoTexture: vec3f = {STD_DIFFUSE_TEXTURE_DECODE}(textureSampleBias({STD_DIFFUSE_TEXTURE_NAME}, {STD_DIFFUSE_TEXTURE_NAME}Sampler, {STD_DIFFUSE_TEXTURE_UV}, uniform.textureBias)).{STD_DIFFUSE_TEXTURE_CHANNEL};
\t\tdAlbedo = dAlbedo * albedoTexture;
\t\tlet detail: f32 = 0.55 + 0.9 * dot(albedoTexture, vec3f(0.3333));
\t#else
\t\tlet detail: f32 = 1.0;
\t#endif
\tlet up: f32 = step(${f(UP_THRESHOLD)}, normalize(vNormalW).y);
\tdAlbedo = mix(dAlbedo, vec3f(${r}, ${g}, ${b}) * detail, up);
}
`,
  };
}

/** Give a material an up swatch. */
export function applyUp(material: pc.StandardMaterial, up: Srgb8): void {
  const chunks = upChunks(up);
  material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).set('diffusePS', chunks.glsl);
  material.getShaderChunks(pc.SHADERLANGUAGE_WGSL).set('diffusePS', chunks.wgsl);
  material.update();
}

/** A surface drawn in one swatch, with an optional up swatch, in the look's shading model. */
export function swatchMaterial(swatch: StylePackSwatch, up: StylePackSwatch | null, shading: RenderShading, name: string): pc.StandardMaterial {
  const material = new pc.StandardMaterial();
  material.name = name;
  const [r, g, b] = swatch.srgb8;
  material.diffuse = new pc.Color(r / 255, g / 255, b / 255);
  material.useMetalness = true;
  material.metalness = swatch.metalness_permille / 1000;
  material.gloss = 1 - swatch.roughness_permille / 1000;
  if (swatch.emission_permille > 0) {
    const share = swatch.emission_permille / 1000;
    material.emissive = new pc.Color((r / 255) * share, (g / 255) * share, (b / 255) * share);
  }
  material.update();
  if (up !== null) applyUp(material, up.srgb8);
  applyShading(material, shading);
  return material;
}
