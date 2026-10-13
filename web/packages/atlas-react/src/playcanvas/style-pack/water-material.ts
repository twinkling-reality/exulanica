import * as pc from 'playcanvas';

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

  add(material: pc.StandardMaterial): void {
    if (this.#materials.has(material)) return;
    if (this.#materials.size === 0) this.app.on('update', this.#tick);
    this.#materials.add(material);
    material.setParameter('exuWaterTime', 0);
    material.shaderChunksVersion = '2.8';
    material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).set('normalMapPS', `
uniform float exuWaterTime;
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
    material.update();
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.app.off('update', this.#tick);
    this.#materials.clear();
  }
}
