import * as pc from 'playcanvas';
import type { RenderShading } from './look.js';

/**
 * The shading models a render look may choose, as engine shader chunks this module writes.
 *
 * A look chooses a model by name and states its bounds; the chunk text is this module's, and the
 * only values that reach it are the validated numbers, written at fixed precision. So a style pack
 * can make a world toon or faceted, and can never supply shader code (the customization contract's
 * rule).
 *
 * - `pbr` leaves the engine's own lighting alone: no chunk is set.
 * - `toon` replaces the diffuse term with two lit bands: shade below `shadowEdge`, a first band at
 *   `bandShare` of full light up to `lightEdge`, full light above. Image light and shadows are the
 *   engine's, so shade keeps the sky's colour.
 * - `flat` takes each fragment's normal from the screen-space derivatives of its world position,
 *   which is the face's own normal: every triangle reads as one flat facet, whatever the mesh's
 *   normals say. The normal-map uniforms stay declared, so a material that names them still links.
 */

const f = (value: number): string => value.toFixed(4);

export interface ShadingChunks {
  readonly glsl: Readonly<Record<string, string>>;
  readonly wgsl: Readonly<Record<string, string>>;
}

export function shadingChunks(shading: RenderShading): ShadingChunks {
  if (shading.model === 'pbr') return { glsl: {}, wgsl: {} };
  if (shading.model === 'toon') {
    const toon = shading.toon;
    if (toon === null) throw new Error('A toon shading model states its bands');
    const half = toon.softness / 2;
    const a0 = f(Math.max(0, toon.shadowEdge - half));
    const a1 = f(Math.min(1, toon.shadowEdge + half));
    const b0 = f(Math.max(0, toon.lightEdge - half));
    const b1 = f(Math.min(1, toon.lightEdge + half));
    const share = f(toon.bandShare);
    const rest = f(1 - toon.bandShare);
    return {
      glsl: {
        lightDiffuseLambertPS: `
float getLightDiffuse(vec3 worldNormal, vec3 viewDir, vec3 lightDirNorm) {
\tfloat d = max(dot(worldNormal, -lightDirNorm), 0.0);
\treturn smoothstep(${a0}, ${a1}, d) * ${share} + smoothstep(${b0}, ${b1}, d) * ${rest};
}
`,
      },
      wgsl: {
        lightDiffuseLambertPS: `
fn getLightDiffuse(worldNormal: vec3f, viewDir: vec3f, lightDirNorm: vec3f) -> f32 {
\tlet d: f32 = max(dot(worldNormal, -lightDirNorm), 0.0);
\treturn smoothstep(${a0}, ${a1}, d) * ${share} + smoothstep(${b0}, ${b1}, d) * ${rest};
}
`,
      },
    };
  }
  return {
    glsl: {
      normalMapPS: `
#ifdef STD_NORMAL_TEXTURE
\tuniform float material_bumpiness;
#endif
#ifdef STD_NORMALDETAIL_TEXTURE
\tuniform float material_normalDetailMapBumpiness;
#endif
void getNormal() {
\tdNormalW = normalize(cross(dFdx(vPositionW), dFdy(vPositionW)));
}
`,
    },
    wgsl: {
      normalMapPS: `
#ifdef STD_NORMAL_TEXTURE
\tuniform material_bumpiness: f32;
#endif
#ifdef STD_NORMALDETAIL_TEXTURE
\tuniform material_normalDetailMapBumpiness: f32;
#endif
fn getNormal() {
\tdNormalW = normalize(cross(dpdx(vPositionW), dpdy(vPositionW)));
}
`,
    },
  };
}

/** Give a material the look's shading model. Returns whether any chunk was set. */
export function applyShading(material: pc.StandardMaterial, shading: RenderShading): boolean {
  const chunks = shadingChunks(shading);
  let changed = false;
  for (const [name, code] of Object.entries(chunks.glsl)) {
    material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).set(name, code);
    changed = true;
  }
  for (const [name, code] of Object.entries(chunks.wgsl)) {
    material.getShaderChunks(pc.SHADERLANGUAGE_WGSL).set(name, code);
    changed = true;
  }
  if (changed) material.update();
  return changed;
}
