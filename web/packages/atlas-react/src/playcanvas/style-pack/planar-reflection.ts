import * as pc from 'playcanvas';

/**
 * A real reflection of the world in level water: a second camera, the main camera mirrored in the
 * water's plane, draws the scene into a small texture each frame, and the water's materials add it
 * to their light, more at a low angle than looking straight down. It is an approximate reflection
 * of what is actually there, not a picture: nothing in it is painted, recorded or invented.
 *
 * Everything at or below the water is clipped out of the mirrored view by an oblique near plane,
 * so the water does not reflect itself and nothing under it shows. The reflection camera draws the
 * main camera's layers at the size the finish states (`reflection_size_px`); a finish that states
 * no strength draws none (`surface-finish.v1.json`).
 *
 * GLSL ONLY, as the finish: a caller makes none on a WebGPU device (`finishRuns`).
 */
export class PlanarReflection {
  readonly #entity: pc.Entity;
  readonly #texture: pc.Texture;
  readonly #target: pc.RenderTarget;
  readonly #materials = new Set<pc.StandardMaterial>();
  readonly #mirror = new pc.Mat4();
  readonly #reflected = new pc.Mat4();
  readonly #projection = new pc.Mat4();
  readonly #view = new pc.Mat4();
  readonly #projectionView = new pc.Mat4();
  readonly #inverseTranspose = new pc.Mat4();
  readonly #plane = new pc.Vec4();
  readonly #planeWorld: pc.Vec4;
  #disposed = false;
  readonly #update = (): void => this.#follow();

  constructor(private readonly app: pc.AppBase, private readonly source: pc.Entity, level: number, size: number, private readonly strength: number) {
    const camera = source.camera!;
    this.#texture = new pc.Texture(app.graphicsDevice, {
      name: 'site-planar-reflection', width: size, height: size, format: pc.PIXELFORMAT_RGBA8, mipmaps: false,
      minFilter: pc.FILTER_LINEAR, magFilter: pc.FILTER_LINEAR, addressU: pc.ADDRESS_CLAMP_TO_EDGE, addressV: pc.ADDRESS_CLAMP_TO_EDGE,
    });
    this.#target = new pc.RenderTarget({ colorBuffer: this.#texture, depth: true, samples: 1 });
    this.#entity = new pc.Entity('site-reflection-camera');
    this.#entity.addComponent('camera', {
      priority: camera.priority - 10, nearClip: camera.nearClip, farClip: camera.farClip, fov: camera.fov,
      renderTarget: this.#target, layers: [...camera.layers], clearColor: camera.clearColor, flipFaces: true,
      gammaCorrection: pc.GAMMA_SRGB, toneMapping: pc.TONEMAP_LINEAR,
    });
    app.root.addChild(this.#entity);
    // The mirror in the plane y = level, and that plane a little above it, kept by the mirrored view.
    this.#mirror.data[5] = -1;
    this.#mirror.data[13] = 2 * level;
    this.#planeWorld = new pc.Vec4(0, 1, 0, -level - 0.02);
    const reflection = this.#entity.camera!;
    reflection.calculateTransform = (out: pc.Mat4) => out.copy(this.#reflected);
    reflection.calculateProjection = (out: pc.Mat4) => out.copy(this.#projection);
    app.on('prerender', this.#update);
  }

  /** Add this reflection to a water material's light. */
  add(material: pc.StandardMaterial): void {
    if (this.#materials.has(material)) return;
    this.#materials.add(material);
    material.getShaderChunks(pc.SHADERLANGUAGE_GLSL).set('emissivePS', `
uniform vec3 material_emissive;
uniform float material_emissiveIntensity;
uniform sampler2D exuReflection;
uniform mat4 exuReflectionMatrix;
uniform vec3 exuReflectionEye;
uniform float exuReflectionStrength;
void getEmission() {
\tdEmission = material_emissive * material_emissiveIntensity;
\tvec4 projected = exuReflectionMatrix * vec4(vPositionW, 1.0);
\tvec2 uv = projected.xy / projected.w * 0.5 + 0.5;
\tvec3 seen = pow(texture2D(exuReflection, clamp(uv, vec2(0.001), vec2(0.999))).rgb, vec3(2.2));
\tfloat grazing = pow(1.0 - clamp(normalize(exuReflectionEye - vPositionW).y, 0.0, 1.0), 3.0);
\tdEmission += seen * exuReflectionStrength * (0.12 + 0.88 * grazing);
}
`);
    material.setParameter('exuReflection', this.#texture);
    material.setParameter('exuReflectionStrength', this.strength);
    material.setParameter('exuReflectionEye', [0, 1000, 0]);
    material.setParameter('exuReflectionMatrix', new pc.Mat4().data);
    material.update();
  }

  #follow(): void {
    if (this.#disposed) return;
    const camera = this.source.camera!;
    this.#reflected.mul2(this.#mirror, this.source.getWorldTransform());
    this.#entity.setPosition(this.#reflected.getTranslation());
    this.#view.copy(this.#reflected).invert();
    this.#projection.setPerspective(camera.fov, camera.aspectRatio, camera.nearClip, camera.farClip);
    // An oblique near plane on the water's plane: nothing at or under the water is in the mirrored view.
    this.#inverseTranspose.copy(this.#reflected).transpose();
    this.#inverseTranspose.transformVec4(this.#planeWorld, this.#plane);
    const p = this.#projection.data, plane = this.#plane;
    const qx = (Math.sign(plane.x) + p[8]!) / p[0]!, qy = (Math.sign(plane.y) + p[9]!) / p[5]!, qz = -1, qw = (1 + p[10]!) / p[14]!;
    const scale = 2 / (plane.x * qx + plane.y * qy + plane.z * qz + plane.w * qw);
    p[2] = plane.x * scale;
    p[6] = plane.y * scale;
    p[10] = plane.z * scale + 1;
    p[14] = plane.w * scale;
    this.#projectionView.mul2(this.#projection, this.#view);
    const eye = this.source.getPosition();
    for (const material of this.#materials) {
      material.setParameter('exuReflectionMatrix', this.#projectionView.data);
      material.setParameter('exuReflectionEye', [eye.x, eye.y, eye.z]);
    }
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.app.off('prerender', this.#update);
    this.#materials.clear();
    this.#entity.destroy();
    this.#target.destroy();
    this.#texture.destroy();
  }
}
