/**
 * Reflectance by angle for glazing.
 *
 * The texture proposal's glazing contract reflects with reflectance at normal incidence
 * ((n - 1) / (n + 1))^2, rising with angle, so that past about 70 degrees the sky's reflection takes
 * over from the view into the shop. PlayCanvas's own Schlick term scales its value at grazing incidence
 * by the reflectance at normal incidence (its F90 is max(gloss^2 * F0, F0)), which keeps a dielectric at
 * 0.04 at every angle, so a glazing material replaces that one shader function with Schlick's
 * approximation proper:
 *
 *   F = F0 + (F90 - F0) * (1 - cos(theta))^5,   F90 = max(gloss, F0)
 *
 * Smooth glass reaches nearly full reflectance at grazing incidence; a rough film reflects less there.
 * The same function sets how much of what lies behind the pane is transmitted, (1 - F), because the
 * transmission shading calls it. It keeps the engine function's name and parameters, and it replaces
 * nothing for any other class.
 */

/** The chunk this replaces, by the engine's name for it. */
export const GLAZING_FRESNEL_CHUNK = 'fresnelSchlickPS';

export const GLAZING_FRESNEL_GLSL = `
float pow5(float x) {
    float x2 = x * x;
    return x2 * x2 * x;
}

vec3 getFresnel(
        float cosTheta,
        float gloss,
        vec3 specularity
#if defined(LIT_IRIDESCENCE)
        , vec3 iridescenceFresnel,
        float iridescenceIntensity
#endif
    ) {
    float fresnel = pow5(1.0 - saturate(cosTheta));
    vec3 ret = specularity + (max(vec3(gloss), specularity) - specularity) * fresnel;
#if defined(LIT_IRIDESCENCE)
    return mix(ret, iridescenceFresnel, iridescenceIntensity);
#else
    return ret;
#endif
}

float getFresnelCC(float cosTheta) {
    float fresnel = pow5(1.0 - saturate(cosTheta));
    return 0.04 + (1.0 - 0.04) * fresnel;
}
`;

export const GLAZING_FRESNEL_WGSL = `
fn pow5(x: f32) -> f32 {
    let x2: f32 = x * x;
    return x2 * x2 * x;
}

fn getFresnel(
        cosTheta: f32,
        gloss: f32,
        specularity: vec3f
    #if defined(LIT_IRIDESCENCE)
        , iridescenceFresnel: vec3f,
        iridescenceIntensity: f32
    #endif
) -> vec3f {
    let fresnel: f32 = pow5(1.0 - saturate(cosTheta));
    let ret: vec3f = specularity + (max(vec3f(gloss), specularity) - specularity) * fresnel;
    #if defined(LIT_IRIDESCENCE)
        return mix(ret, iridescenceFresnel, iridescenceIntensity);
    #else
        return ret;
    #endif
}

fn getFresnelCC(cosTheta: f32) -> f32 {
    let fresnel: f32 = pow5(1.0 - saturate(cosTheta));
    return 0.04 + (1.0 - 0.04) * fresnel;
}
`;

/** Schlick's reflectance as the chunk computes it, for tests and measurements. */
export function glazingReflectance(cosTheta: number, gloss: number, f0: number): number {
  const fresnel = (1 - Math.min(1, Math.max(0, cosTheta))) ** 5;
  return f0 + (Math.max(gloss, f0) - f0) * fresnel;
}
