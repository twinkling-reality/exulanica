import * as pc from 'playcanvas';
import type { RenderWind } from '../generated-tile/look.js';

/**
 * Plants swaying in a look's wind (`RenderWind`), in their vertex positions.
 *
 * PRESENTATION ONLY: a sway moves what is drawn and its shadow, never a slot, a bound or a walk.
 *
 * A swaying piece bends from its foot: a vertex moves by the square of its height over the piece's own
 * height, so the foot stays where it stands and the top moves farthest. The top leans along the wind
 * by up to the wind's sway and back at the wind's pace, each piece at its own phase (drawn from where it
 * stands), and flutters across the wind by the wind's flutter at four times that pace. Gusts are a
 * smooth field, one gust scale across, carried downwind one gust scale for each sway: where a gust is
 * not, a piece sways by one less the gust share of its sway.
 *
 * The working replaces the engine's local position in its transform chunk (`transformCoreVS`), once
 * for each material, and runs where the chunk is GLSL: on WebGPU nothing sways.
 */

/** Whether plants sway on `device`: the working is written in GLSL alone. */
export const windRuns = (device: pc.GraphicsDevice): boolean => device.isWebGPU !== true;

/** The engine's own local position, which the wind's position wraps. */
const STOCK = 'vec3 getLocalPosition(vec3 vertexPosition) {';
/** The engine's own, renamed: present only in a chunk the wind has wrapped. */
const REST = 'vec3 exuWindRestPosition(vec3 vertexPosition) {';

const WIND_GLSL = /* glsl */ `
uniform vec4 exuWind;
uniform vec4 exuWindGust;
uniform float exuWindHeight;
float exuWindHash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}
float exuWindNoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(exuWindHash(i), exuWindHash(i + vec2(1.0, 0.0)), f.x), mix(exuWindHash(i + vec2(0.0, 1.0)), exuWindHash(i + vec2(1.0, 1.0)), f.x), f.y);
}
vec3 getLocalPosition(vec3 vertexPosition) {
    vec3 rest = exuWindRestPosition(vertexPosition);
    float reach = clamp(rest.y / max(exuWindHeight, 1e-3), 0.0, 1.0);
    mat4 model = getModelMatrix();
    vec2 at = model[3].xz;
    vec2 along = exuWind.xy;
    float time = exuWindGust.z;
    float phase = exuWindHash(floor(at * 8.0)) * 6.2831853;
    float gust = exuWindNoise(at * exuWindGust.x - along * (time * exuWind.w / 6.2831853));
    float bend = reach * reach * (1.0 - exuWindGust.y + exuWindGust.y * gust);
    float lean = 0.5 + 0.5 * sin(exuWind.w * time + phase);
    float flutter = sin(4.0 * exuWind.w * time + phase + dot(rest, vec3(17.0, 23.0, 29.0)));
    vec3 push = vec3(along.x, 0.0, along.y) * (exuWind.z * lean) + vec3(-along.y, 0.0, along.x) * (exuWindGust.w * flutter);
    return rest + inverse(mat3(model)) * (push * bend);
}
`;

/** `chunk` (the engine's transform chunk, or one already given the wind) with the wind's position in it. */
export function withWind(chunk: string): string {
  if (chunk.includes(REST)) return chunk;
  if (!chunk.includes(STOCK)) throw new TypeError('the transform chunk states no local position for the wind to wrap');
  return `${chunk.replace(STOCK, REST)}\n${WIND_GLSL}`;
}

/** The wind's still figures, as its working reads them: its direction, sway and pace; its gust and flutter. */
function stated(wind: RenderWind): { readonly wind: number[]; readonly gust: [number, number, number] } {
  return {
    wind: [Math.cos(wind.direction), Math.sin(wind.direction), wind.swayM, wind.pace],
    gust: [1 / wind.gustScaleM, wind.gustShare, wind.flutterM],
  };
}

/** The wind over one site: the materials of its swaying pieces, and the time they sway by. */
export class PlantWind {
  readonly #materials = new Set<pc.StandardMaterial>();
  readonly #figures: ReturnType<typeof stated>;
  #time = 0;
  #disposed = false;
  readonly #tick = (dt: number): void => {
    this.#time = (this.#time + Math.min(dt, 0.1)) % 3600;
    const [scale, share, flutter] = this.#figures.gust;
    for (const material of this.#materials) material.setParameter('exuWindGust', [scale, share, this.#time, flutter]);
  };

  constructor(private readonly app: pc.AppBase, wind: RenderWind) {
    this.#figures = stated(wind);
  }

  get animating(): boolean { return this.#materials.size > 0; }
  /** How many materials sway. */
  get materials(): number { return this.#materials.size; }

  /**
   * Sway a piece's material, the piece `heightM` tall in its own metres. Returns whether it sways:
   * false on a device the working is not written for, or where it already does.
   */
  add(material: pc.StandardMaterial, heightM: number): boolean {
    const device = this.app.graphicsDevice;
    if (this.#disposed || !windRuns(device) || this.#materials.has(material)) return false;
    const chunks = material.getShaderChunks(pc.SHADERLANGUAGE_GLSL);
    const held = chunks.get('transformCoreVS') as string | undefined;
    const plain = pc.ShaderChunks.get(device, pc.SHADERLANGUAGE_GLSL).get('transformCoreVS') as string | undefined;
    if (held === undefined && plain === undefined) throw new TypeError('the engine states no transform chunk to set the wind into');
    material.shaderChunksVersion = '2.8';
    chunks.set('transformCoreVS', withWind(held ?? plain!));
    const [scale, share, flutter] = this.#figures.gust;
    material.setParameter('exuWind', this.#figures.wind);
    material.setParameter('exuWindGust', [scale, share, this.#time, flutter]);
    material.setParameter('exuWindHeight', Math.max(heightM, 1e-3));
    material.update();
    if (this.#materials.size === 0) this.app.on('update', this.#tick);
    this.#materials.add(material);
    return true;
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    if (this.#materials.size > 0) this.app.off('update', this.#tick);
    this.#materials.clear();
  }
}
