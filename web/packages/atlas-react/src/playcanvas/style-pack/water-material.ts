import * as pc from 'playcanvas';
import type { RenderWater } from '../generated-tile/look.js';

/** The ripples' clock, declared by whichever of the two chunks the shader includes first. */
const WATER_TIME_GLSL = '#ifndef EXU_WATER_TIME\n#define EXU_WATER_TIME\nuniform float exuWaterTime;\n#endif';

/**
 * The ripples: two octaves of drifting value noise whose slope tilts the water, each turned to the
 * other (radians from east toward south), its cell in metres, the tilt it gives and its drift in
 * cells a second along its own axes. Noise has no lattice: two cosines crossing make one, and the
 * sun's highlight picks out each crossing as a regular grid of dots. Chosen by eye on a pool seen
 * across a site; not measured properties of water.
 */
const RIPPLE_OCTAVES = [
  { angle: 0.6, cellM: 2.4, tilt: 0.07, drift: [0.1, 0.04] },
  { angle: 2.2, cellM: 0.9, tilt: 0.045, drift: [-0.06, 0.12] },
] as const;

/**
 * How many noise cells an octave may cross in one pixel before it fades: from the first figure it
 * starts to flatten and by the second it is gone (a cell under about 7 and 2.5 pixels). Finer
 * noise aliases into glitter that crawls as the eye moves; past it, far water is smooth and the sun
 * lies on it as a soft glow. Chosen by eye; not measured.
 */
const RIPPLE_FADE_CELLS_PER_PIXEL = [0.15, 0.4] as const;

const figure = (value: number): string => value.toFixed(4);
const [FADE_FROM, FADE_TO] = RIPPLE_FADE_CELLS_PER_PIXEL.map(figure);
/**
 * Each octave's lines of a shader: where the water lies in its cells, then the slope there turned
 * back to the world and faded where its cells are finer than the picture.
 */
const octaveLines = (time: string, declare: (name: string) => string, vec2: string): string => RIPPLE_OCTAVES.map((octave, i) => {
  const [c, s] = [Math.cos(octave.angle), Math.sin(octave.angle)];
  const k = 1 / octave.cellM;
  return [
    `    ${declare(`q${i}`)} = ${vec2}(vPositionW.x * ${figure(c * k)} + vPositionW.z * ${figure(-s * k)}, vPositionW.x * ${figure(s * k)} + vPositionW.z * ${figure(c * k)}) + ${vec2}(${figure(octave.drift[0])}, ${figure(octave.drift[1])}) * ${time};`,
    `    ${declare(`g${i}`)} = exuRippleSlope(q${i}) * (${figure(octave.tilt)} * (1.0 - smoothstep(${FADE_FROM}, ${FADE_TO}, max(fwidth(q${i}.x), fwidth(q${i}.y)))));`,
    `    tilt -= ${vec2}(${figure(c)} * g${i}.x + ${figure(s)} * g${i}.y, ${figure(-s)} * g${i}.x + ${figure(c)} * g${i}.y);`,
  ].join('\n');
}).join('\n');

/** The ripple's noise: an integer hash of a cell, and the slope of smooth value noise at a point, in cells. */
const RIPPLE_NOISE_GLSL = `
float exuRippleHash(ivec2 c) {
    uint v = uint(c.x) * 73856093u ^ uint(c.y) * 19349663u;
    v ^= v >> 16; v *= 0x7feb352du; v ^= v >> 15; v *= 0x846ca68bu; v ^= v >> 16;
    return float(v) * (1.0 / 4294967295.0);
}
vec2 exuRippleSlope(vec2 q) {
    ivec2 i = ivec2(floor(q));
    vec2 f = fract(q);
    vec2 u = f * f * (3.0 - 2.0 * f);
    vec2 du = 6.0 * f * (1.0 - f);
    float a = exuRippleHash(i), b = exuRippleHash(i + ivec2(1, 0)), c = exuRippleHash(i + ivec2(0, 1)), d = exuRippleHash(i + ivec2(1, 1));
    float k = a - b - c + d;
    return du * vec2(b - a + k * u.y, c - a + k * u.x);
}`;
const RIPPLE_NOISE_WGSL = `
fn exuRippleHash(c: vec2i) -> f32 {
    var v: u32 = (bitcast<u32>(c.x) * 73856093u) ^ (bitcast<u32>(c.y) * 19349663u);
    v = v ^ (v >> 16u); v = v * 0x7feb352du; v = v ^ (v >> 15u); v = v * 0x846ca68bu; v = v ^ (v >> 16u);
    return f32(v) / 4294967295.0;
}
fn exuRippleSlope(q: vec2f) -> vec2f {
    let i = vec2i(floor(q));
    let f = fract(q);
    let u = f * f * (3.0 - 2.0 * f);
    let du = 6.0 * f * (1.0 - f);
    let a = exuRippleHash(i);
    let b = exuRippleHash(i + vec2i(1, 0));
    let c = exuRippleHash(i + vec2i(0, 1));
    let d = exuRippleHash(i + vec2i(1, 1));
    let k = a - b - c + d;
    return du * vec2f(b - a + k * u.y, c - a + k * u.x);
}`;

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

/**
 * Cosmetic surface ripples in metre coordinates. The basin and its keep-out remain world data.
 *
 * It keeps the time of every water it moves: a pbr water's ripples bend its normal and, when the
 * look states a water finish, its colour comes from its depth (`add`); a water given the surface
 * finish (`ground-finish.ts`) drifts its light in any shading model and is told where the eye is,
 * for its sheen at a low angle (`animate`).
 */
export class WaterRipples {
  readonly #materials = new Set<pc.StandardMaterial>();
  readonly #finished = new Set<pc.StandardMaterial>();
  #time = 0;
  #disposed = false;
  readonly #tick = (dt: number): void => {
    this.#time = (this.#time + Math.min(dt, 0.1)) % 3600;
    for (const material of this.#materials) material.setParameter('exuWaterTime', this.#time);
    if (this.#finished.size === 0) return;
    const at = this.eye?.getPosition() ?? null;
    for (const material of this.#finished) {
      // Its own name: a pbr water's ripple chunk declares exuWaterTime in the same shader.
      material.setParameter('exuFinishTime', this.#time);
      if (at !== null) material.setParameter('exuFinishEye', [at.x, at.y, at.z]);
    }
  };

  constructor(private readonly app: pc.AppBase, private readonly eye: pc.Entity | null = null) {}
  get animating(): boolean { return this.#materials.size > 0; }

  /** Keep the time and the eye of a water given the surface finish, whatever its shading. */
  animate(material: pc.StandardMaterial): void {
    if (this.#finished.has(material)) return;
    this.#start(material);
    this.#finished.add(material);
  }

  #start(material: pc.StandardMaterial): void {
    if (this.#materials.has(material)) return;
    if (this.#materials.size === 0) this.app.on('update', this.#tick);
    this.#materials.add(material);
    material.setParameter('exuWaterTime', 0);
  }

  /**
   * Ripple a water material, and when a look states a water finish, finish it by depth as well.
   * The finish needs the camera frame's scene depth map. Returns whether the water is finished by
   * depth, which then owns its colour: the surface finish leaves such a water as it is. `ripples`
   * false gives the depth finish alone, with no ripple in the water's light: a sea or a lake seen
   * from afar.
   */
  add(material: pc.StandardMaterial, finish: RenderWater | null = null, { ripples = true }: { readonly ripples?: boolean } = {}): boolean {
    const finished = finish !== null && !this.app.graphicsDevice.isWebGPU;
    if (this.#materials.has(material) && !this.#finished.has(material)) return finished;
    this.#start(material);
    material.shaderChunksVersion = '2.8';
    // With a finish the clock is declared in either chunk, guarded; without one the chunk declares it.
    if (ripples) {
      material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).set('normalMapPS', `
${finished ? WATER_TIME_GLSL : 'uniform float exuWaterTime;'}
${RIPPLE_NOISE_GLSL}
void getNormal() {
    vec2 tilt = vec2(0.0);
${octaveLines('exuWaterTime', (name) => `vec2 ${name}`, 'vec2')}
    dNormalW = normalize(dVertexNormalW + vec3(tilt.x, 0.0, tilt.y));
}
`);
      material.getShaderChunks(pc.SHADERLANGUAGE_WGSL).set('normalMapPS', `
uniform exuWaterTime: f32;
${RIPPLE_NOISE_WGSL}
fn getNormal() {
    var tilt = vec2f(0.0);
${octaveLines('uniform.exuWaterTime', (name) => `let ${name}`, 'vec2f')}
    dNormalW = normalize(dVertexNormalW + vec3f(tilt.x, 0.0, tilt.y));
}
`);
    }
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
    return finished;
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.app.off('update', this.#tick);
    this.#materials.clear();
    this.#finished.clear();
  }
}
