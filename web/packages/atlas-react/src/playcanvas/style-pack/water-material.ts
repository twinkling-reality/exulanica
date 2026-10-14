import * as pc from 'playcanvas';
import type { RenderWater } from '../generated-tile/look.js';

/** The ripples' clock, declared by whichever of the two chunks the shader includes first. */
const WATER_TIME_GLSL = '#ifndef EXU_WATER_TIME\n#define EXU_WATER_TIME\nuniform float exuWaterTime;\n#endif';

/*
 * A look's water finish: the water's own thickness gives its colour. Thickness is the scene depth
 * behind the surface (the camera frame's depth map, written by the contact-shadow prepass) minus
 * the surface's own depth. Light through it is absorbed per channel; what lies under shallow water
 * shows through; deep water turns to its body colour; a thin edge against a wall or a stone foams.
 * The surface is blended over the drawn scene with one transmittance (the mean of the three
 * channels), so no copy of the scene's colour is needed: with multisampling on a tile GPU that copy
 * alone cost 4 to 6 ms in the graphics lab. Reflection is the material's own environment specular.
 * GLSL only: on a WebGPU device the finish is not applied and the water keeps its ripples alone.
 */
const DEPTH_WATER_OPACITY = `
${WATER_TIME_GLSL}
#include "screenDepthPS"
uniform vec3 exuWaterShallow;
uniform vec3 exuWaterDeep;
uniform vec3 exuWaterAbsorb;
uniform vec4 exuWaterFinish; // x depth scale m, y foam width m
vec3 exuWaterBody;
float exuWaterHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float exuWaterNoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(exuWaterHash(i), exuWaterHash(i + vec2(1.0, 0.0)), f.x), mix(exuWaterHash(i + vec2(0.0, 1.0)), exuWaterHash(i + vec2(1.0, 1.0)), f.x), f.y);
}
void getOpacity() {
    vec2 screen = gl_FragCoord.xy * uScreenSize.zw;
    float thickness = max(getLinearScreenDepth(screen) - 1.0 / gl_FragCoord.w, 0.0);
    vec3 view = normalize(view_position - vPositionW);
    float depth = thickness * max(abs(view.y), 0.08);
    float through = dot(exp(-exuWaterAbsorb * thickness), vec3(1.0 / 3.0));
    vec3 body = mix(exuWaterShallow, exuWaterDeep, 1.0 - exp(-depth / exuWaterFinish.x));
    float noise = exuWaterNoise(vPositionW.xz * 2.2 + vec2(exuWaterTime * 0.3, -exuWaterTime * 0.2)) * 0.6
        + exuWaterNoise(vPositionW.xz * 6.0 - exuWaterTime * 0.5) * 0.4;
    float foam = exuWaterFinish.y <= 0.0 ? 0.0
        : clamp((1.0 - smoothstep(0.0, exuWaterFinish.y, depth)) * smoothstep(0.35, 0.75, noise + 0.25 * (1.0 - depth / exuWaterFinish.y)), 0.0, 1.0) * 0.85;
    dAlpha = 1.0 - through * (1.0 - foam);
    exuWaterBody = (body * (1.0 - through) * (1.0 - foam) + vec3(0.85, 0.9, 0.9) * foam) / max(dAlpha, 1e-3);
}
`;
const DEPTH_WATER_EMISSIVE = 'void getEmission() { dEmission = exuWaterBody; }';
const DEPTH_WATER_DIFFUSE = 'void getAlbedo() { dAlbedo = vec3(0.0); }';

/** Cosmetic surface ripples in metre coordinates. The basin and its keep-out remain world data. */
export class WaterRipples {
  readonly #materials = new Set<pc.StandardMaterial>();
  #time = 0;
  #disposed = false;
  readonly #tick = (dt: number): void => {
    this.#time = (this.#time + Math.min(dt, 0.1)) % 3600;
    for (const material of this.#materials) material.setParameter('exuWaterTime', this.#time);
  };

  constructor(private readonly app: pc.AppBase) {}
  get animating(): boolean { return this.#materials.size > 0; }

  /**
   * Ripple a water material, and when a look states a water finish, finish it by depth as well.
   * The finish needs the camera frame's scene depth map.
   */
  add(material: pc.StandardMaterial, finish: RenderWater | null = null): void {
    if (this.#materials.has(material)) return;
    if (this.#materials.size === 0) this.app.on('update', this.#tick);
    this.#materials.add(material);
    material.setParameter('exuWaterTime', 0);
    material.shaderChunksVersion = '2.8';
    // With a finish the clock is declared in either chunk, guarded; without one the chunk is as it was.
    const finished = finish !== null && !this.app.graphicsDevice.isWebGPU;
    material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).set('normalMapPS', `
${finished ? WATER_TIME_GLSL : 'uniform float exuWaterTime;'}
void getNormal() {
    float a = vPositionW.x * 2.1 + vPositionW.z * 1.3 + exuWaterTime * 0.75;
    float b = vPositionW.z * 3.2 - vPositionW.x * 0.8 - exuWaterTime * 0.48;
    dNormalW = normalize(dVertexNormalW + vec3(-0.042 * cos(a) + 0.008 * cos(b), 0.0, -0.026 * cos(a) - 0.032 * cos(b)));
}
`);
    material.getShaderChunks(pc.SHADERLANGUAGE_WGSL).set('normalMapPS', `
uniform exuWaterTime: f32;
fn getNormal() {
    let a: f32 = vPositionW.x * 2.1 + vPositionW.z * 1.3 + uniform.exuWaterTime * 0.75;
    let b: f32 = vPositionW.z * 3.2 - vPositionW.x * 0.8 - uniform.exuWaterTime * 0.48;
    dNormalW = normalize(dVertexNormalW + vec3f(-0.042 * cos(a) + 0.008 * cos(b), 0.0, -0.026 * cos(a) - 0.032 * cos(b)));
}
`);
    if (finished && finish !== null) {
      const glsl = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
      glsl.set('opacityPS', DEPTH_WATER_OPACITY);
      glsl.set('emissivePS', DEPTH_WATER_EMISSIVE);
      glsl.set('diffusePS', DEPTH_WATER_DIFFUSE);
      material.blendType = pc.BLEND_NORMAL;
      material.depthWrite = false;
      material.opacity = 1;
      material.emissive = new pc.Color(1, 1, 1);
      material.specularityFactor = finish.reflection;
      material.setParameter('exuWaterShallow', new Float32Array(finish.shallow));
      material.setParameter('exuWaterDeep', new Float32Array(finish.deep));
      material.setParameter('exuWaterAbsorb', new Float32Array(finish.absorption));
      material.setParameter('exuWaterFinish', new Float32Array([finish.depthScaleM, finish.foamWidthM, 0, 0]));
    }
    material.update();
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.app.off('update', this.#tick);
    this.#materials.clear();
  }
}
