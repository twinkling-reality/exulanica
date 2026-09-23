import * as pc from 'playcanvas';
import {
  type WorldModuleFormKind,
  type WorldModuleInstance,
  type WorldTopologySnapshot,
} from '@exulanica/atlas-core';
import {
  DAWN_THEME,
  ORIGIN_LANDSCAPE,
  SURVEY_RELIEF,
  unitRgb,
  type PresentationTheme,
  type WorldArtProfile,
  type WorldArtProfileId,
} from '@exulanica/presentation';

/**
 * The forms this renderer draws.
 *
 * A hand-written list is a claim, not a check: the first version of this set named all six
 * registered forms, two of which nothing drew, and the test that compared it against the catalog
 * passed because both lists were wrong the same way. `world-module-form.test.ts` now builds each
 * of these and looks for geometry, so this set is verified rather than believed.
 *
 * No landmark form is here. The beacon and survey strata this file used to build were invented
 * shapes, and a landmark will come from a grammar record rather than from a renderer form.
 */
export const RENDERED_WORLD_MODULE_FORMS: ReadonlySet<WorldModuleFormKind> = Object.freeze(
  new Set<WorldModuleFormKind>([
    'living-buds',
    'survey-stakes',
  ]),
) as ReadonlySet<WorldModuleFormKind>;

export interface ComposedWorld {
  readonly entity: pc.Entity;
  readonly topology: WorldTopologySnapshot;
  readonly profileId: WorldArtProfileId;
  setTheme(theme: PresentationTheme): void;
  setProfile(profile: WorldArtProfile): void;
  setMapActive(active: boolean): void;
  /**
   * The colour this world's own sky shows at eye level, as the sky writes it, or null when it is
   * drawing no sky: a profile without one, the Map, or a render root that is off. Null means the
   * camera's clear colour is the sky. Fog is aimed at this so far ground meets the sky it is seen
   * against, and the rule lives here because the sky shader below is what it describes.
   */
  skyHorizonColour(): readonly [number, number, number] | null;
  destroy(): void;
}

interface ProfileLayer {
  readonly root: pc.Entity;
  readonly materials: readonly pc.Material[];
  readonly mapHidden: readonly pc.Entity[];
  readonly applyProfile: (profile: WorldArtProfile) => void;
}

interface MeshCatalog {
  readonly cube: pc.Mesh;
  readonly rock: pc.Mesh;
  readonly sky: pc.Mesh;
}

interface ShaderDesc {
  uniqueName: string;
  attributes?: Record<string, string>;
  vertexGLSL?: string;
  fragmentGLSL?: string;
}

/*
 * THE SKY IS A DIRECTION, NOT A PLACE.
 *
 * Its entity gives it an orientation and nothing else: the view's rotation turns it and the
 * view's translation is dropped, so the eye is at its centre wherever a person stands, and its
 * depth is the far plane, as the engine's own skybox writes it, so everything drawn at any
 * distance stands in front of it. Placed as a 540 metre sphere where the world opened, it was left
 * behind a short sprint from there and the sky became the camera's clear colour.
 */
const SKY_VERTEX_GLSL = /* glsl */ `
attribute vec3 aPosition;
uniform mat4 matrix_model;
uniform mat4 matrix_view;
uniform mat4 matrix_projection;
varying vec3 vDirection;

void main(void) {
    vDirection = normalize(aPosition);
    mat4 view = matrix_view;
    view[3][0] = view[3][1] = view[3][2] = 0.0;
    gl_Position = matrix_projection * view * vec4(mat3(matrix_model) * aPosition, 1.0);
    gl_Position.z = gl_Position.w - 1.0e-7;
}
`;

const SKY_FRAGMENT_GLSL = /* glsl */ `
precision highp float;
varying vec3 vDirection;
uniform vec3 uSky;
uniform vec3 uHaze;
uniform vec3 uSun;
uniform vec3 uCloud;
uniform vec3 uWarm;
uniform vec3 uGold;
uniform vec3 uLift;
/** 0 = layered-horizon, 1 = diffuse-canvas. Authored by the profile, never by a profile ID. */
uniform float uAtmosphereForm;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float colourMass(vec2 point, vec2 centre, vec2 radius) {
    vec2 q = (point - centre) / radius;
    return exp(-dot(q, q) * 1.65);
}

void main(void) {
    vec3 d = normalize(vDirection);
    if (uAtmosphereForm > 0.5) {
        // The supplied poster language: one light canvas with colour entering from beyond the
        // frame, never a stacked sky/haze/ground horizon.
        vec2 p = vec2(d.x, d.y);
        float coral = colourMass(p, vec2(-1.02, 0.04), vec2(0.86, 0.72));
        float gold = colourMass(p, vec2(0.12, -0.98), vec2(1.02, 0.68));
        float cool = colourMass(p, vec2(0.92, 0.58), vec2(0.88, 0.72));
        float lift = colourMass(p, vec2(-0.16, 1.02), vec2(0.86, 0.64));
        // Both physical surfaces meet at paper-white. Colour belongs to the outer field, so the
        // horizon cannot reappear as a differently coloured horizontal band.
        float edgeField = smoothstep(0.035, 0.30, abs(d.y));
        coral *= edgeField;
        gold *= edgeField;
        cool *= edgeField;
        lift *= edgeField;
        vec3 colour = uCloud;
        colour = mix(colour, uWarm, coral * 0.29);
        colour = mix(colour, uGold, gold * 0.24);
        colour = mix(colour, uSky, cool * 0.23);
        colour = mix(colour, uLift, lift * 0.18);
        float grain = hash(floor((p + d.z) * 920.0));
        colour += (grain - 0.5) * 0.012;
        gl_FragColor = vec4(colour, 1.0);
        return;
    }
    float height = smoothstep(-0.025, 0.88, d.y);
    vec3 colour = mix(uHaze, uSky, height);

    // The lower atmosphere is a volume, not a backdrop boundary. Keeping a broad haze shelf at
    // eye level gives the ground material room to converge to this exact colour.
    float horizonShelf = 1.0 - smoothstep(0.0, 0.24, abs(d.y));
    colour = mix(colour, uHaze, horizonShelf * 0.34);

    float cloudA = sin(d.x * 18.0 + d.z * 7.0 + sin(d.z * 23.0) * 0.75);
    float cloudB = sin(d.z * 31.0 - d.x * 9.0);
    float cloud = smoothstep(0.72, 1.45, cloudA + cloudB * 0.34);
    cloud *= smoothstep(0.05, 0.24, d.y) * (1.0 - smoothstep(0.52, 0.78, d.y));
    colour = mix(colour, uCloud, cloud * 0.075);

    // A very broad polar-light bow gives the sky depth without creating another destination.
    float bow = 1.0 - abs(length(d.xz - vec2(0.18, -0.08)) - 0.72);
    bow = smoothstep(0.955, 0.992, bow) * smoothstep(0.12, 0.52, d.y);
    colour += mix(uCloud, uSun, 0.35) * bow * 0.032;

    vec3 sunDirection = normalize(vec3(-0.62, 0.42, -0.72));
    float sunFacing = max(0.0, dot(d, sunDirection));
    float sunDisc = smoothstep(0.99915, 0.99972, sunFacing);
    float sunHaze = pow(sunFacing, 18.0) * 0.075 + pow(sunFacing, 95.0) * 0.16;
    colour += uSun * (sunDisc * 0.56 + sunHaze);

    gl_FragColor = vec4(colour, 1.0);
}
`;

function color(hex: string): pc.Color {
  const [r, g, b] = unitRgb(hex);
  return new pc.Color(r, g, b);
}

function createMaterial(
  hex: string,
  options: {
    readonly lit?: boolean;
    readonly emissive?: string;
    readonly emissiveIntensity?: number;
    readonly metalness?: number;
    readonly gloss?: number;
    readonly opacity?: number;
    readonly fog?: boolean;
  } = {},
): pc.StandardMaterial {
  const material = new pc.StandardMaterial();
  material.useLighting = options.lit ?? true;
  material.diffuse.copy(color(hex));
  material.emissive.copy(color(options.emissive ?? '#000000'));
  material.emissiveIntensity = options.emissiveIntensity ?? 0;
  material.metalness = options.metalness ?? 0;
  material.gloss = options.gloss ?? 0.16;
  material.opacity = options.opacity ?? 1;
  material.blendType = material.opacity < 1 ? pc.BLEND_NORMAL : pc.BLEND_NONE;
  material.depthWrite = material.opacity >= 0.72;
  material.cull = pc.CULLFACE_BACK;
  material.useFog = options.fog ?? true;
  material.update();
  return material;
}

function createSkyMaterial(profile: WorldArtProfile): pc.ShaderMaterial {
  const material = new pc.ShaderMaterial({
    uniqueName: `exulanica-origin-sky:${profile.profileId}`,
    attributes: { aPosition: pc.SEMANTIC_POSITION },
    vertexGLSL: SKY_VERTEX_GLSL,
    fragmentGLSL: SKY_FRAGMENT_GLSL,
  } as ShaderDesc);
  material.setParameter('uSky', new Float32Array(unitRgb(profile.palette.sky)));
  material.setParameter('uHaze', new Float32Array(unitRgb(profile.palette.haze)));
  material.setParameter('uSun', new Float32Array(unitRgb(profile.palette.sun)));
  material.setParameter('uCloud', new Float32Array(unitRgb(profile.palette.paper)));
  material.setParameter('uWarm', new Float32Array(unitRgb(profile.palette.brass)));
  material.setParameter('uGold', new Float32Array(unitRgb(profile.palette.path)));
  material.setParameter('uLift', new Float32Array(unitRgb(profile.palette.terrainLift)));
  material.setParameter('uAtmosphereForm', profile.field.atmosphere === 'diffuse-canvas' ? 1 : 0);
  material.cull = pc.CULLFACE_FRONT;
  material.depthWrite = false;
  material.blendType = pc.BLEND_NONE;
  material.update();
  return material;
}

function updateSkyMaterial(material: pc.ShaderMaterial, profile: WorldArtProfile): void {
  material.setParameter('uSky', new Float32Array(unitRgb(profile.palette.sky)));
  material.setParameter('uHaze', new Float32Array(unitRgb(profile.palette.haze)));
  material.setParameter('uSun', new Float32Array(unitRgb(profile.palette.sun)));
  material.setParameter('uCloud', new Float32Array(unitRgb(profile.palette.paper)));
  material.setParameter('uWarm', new Float32Array(unitRgb(profile.palette.brass)));
  material.setParameter('uGold', new Float32Array(unitRgb(profile.palette.path)));
  material.setParameter('uLift', new Float32Array(unitRgb(profile.palette.terrainLift)));
  material.setParameter('uAtmosphereForm', profile.field.atmosphere === 'diffuse-canvas' ? 1 : 0);
  material.update();
}

function updateMaterial(
  material: pc.StandardMaterial,
  hex: string,
  options: {
    readonly emissive?: string;
    readonly emissiveIntensity?: number;
    readonly metalness?: number;
    readonly gloss?: number;
    readonly opacity?: number;
  } = {},
): void {
  material.diffuse.copy(color(hex));
  material.emissive.copy(color(options.emissive ?? '#000000'));
  material.emissiveIntensity = options.emissiveIntensity ?? 0;
  material.metalness = options.metalness ?? 0;
  material.gloss = options.gloss ?? 0.16;
  material.opacity = options.opacity ?? 1;
  material.blendType = material.opacity < 1 ? pc.BLEND_NORMAL : pc.BLEND_NONE;
  material.depthWrite = material.opacity >= 0.72;
  material.update();
}

function addPrimitive(
  parent: pc.Entity,
  name: string,
  mesh: pc.Mesh,
  material: pc.Material,
  position: readonly [number, number, number],
  scale: readonly [number, number, number],
  rotation: readonly [number, number, number] = [0, 0, 0],
): pc.Entity {
  const entity = new pc.Entity(name);
  entity.setLocalPosition(position[0], position[1], position[2]);
  entity.setLocalScale(scale[0], scale[1], scale[2]);
  entity.setLocalEulerAngles(rotation[0], rotation[1], rotation[2]);
  const instance = new pc.MeshInstance(mesh, material, entity);
  instance.castShadow = true;
  instance.receiveShadow = true;
  entity.addComponent('render', { meshInstances: [instance] });
  parent.addChild(entity);
  return entity;
}

/** Where the ground is under a point. Authored Atlas terrain unless a caller owns the ground. */
export type ComposedWorldGroundHeight = (x: number, z: number) => number;

/** The flat datum navigation stands on. */
const flatGroundHeight: ComposedWorldGroundHeight = () => 0;

function atInstance(
  root: pc.Entity,
  instance: WorldModuleInstance,
  groundHeight: ComposedWorldGroundHeight,
): pc.Entity {
  const group = new pc.Entity(instance.instanceId);
  group.setPosition(
    instance.transform.position.x,
    instance.transform.position.y + groundHeight(
      instance.transform.position.x,
      instance.transform.position.z,
    ),
    instance.transform.position.z,
  );
  group.setEulerAngles(0, (instance.transform.yaw * 180) / Math.PI, 0);
  root.addChild(group);
  return group;
}

/** The yaw of the region foundation the world opens on, or 0 for a world with none. */
function openingYaw(topology: WorldTopologySnapshot): number {
  return topology.instances.find((instance) => instance.role === 'region-foundation')?.transform.yaw ?? 0;
}

function addOriginEnvironment(
  root: pc.Entity,
  topology: WorldTopologySnapshot,
  meshes: MeshCatalog,
  shadow: pc.StandardMaterial,
  sky: pc.ShaderMaterial,
): pc.Entity {
  const yawDegrees = (openingYaw(topology) * 180) / Math.PI;
  const environment = new pc.Entity('origin-environment');
  root.addChild(environment);

  // Turned to the opening frame and nothing more: the shader draws it around the eye at the far
  // plane, so its entity has no position that means anything and is never culled by one.
  const skyEntity = new pc.Entity('origin-sky');
  skyEntity.setEulerAngles(0, yawDegrees, 0);
  const skyInstance = new pc.MeshInstance(meshes.sky, sky, skyEntity);
  skyInstance.cull = false;
  // Not an object, so it casts and receives no shadow. The render component's flags are the ones
  // the engine applies to its instances: set on the instance alone, the sky cast one, and its
  // 540 metre bounds stretched the sun's shadow depth range near the opening point.
  skyEntity.addComponent('render', {
    meshInstances: [skyInstance],
    castShadows: false,
    receiveShadows: false,
  });
  environment.addChild(skyEntity);

  // The origin profile has no decorative horizon geometry. The water/sky seam is the only
  // orientation line, leaving source-bearing memory silhouettes uncontested.
  void shadow;
  return environment;
}

/**
 * Realize passive topology as one authored landscape. Profile layers are built once and toggled,
 * so a visual preview cannot perturb identity, placement, navigation, collision, or evidence.
 */
export function createComposedWorld(
  device: pc.GraphicsDevice,
  topology: WorldTopologySnapshot,
  initialProfile: WorldArtProfile = ORIGIN_LANDSCAPE,
  _theme: PresentationTheme = DAWN_THEME,
  /**
   * Where this world's ground actually is.
   *
   * The default is the flat datum at y = 0, which is the ground navigation stands on. There is no
   * authored terrain to follow: the undulating landscape that used to be the default was drawn by
   * nothing under an owned district and recorded by nothing anywhere, and sinking a memory by the
   * height of that surface left every Flatiron region between 0.74 and 1.39 metres below the
   * street. A caller that holds a measured ground passes it here.
   */
  groundHeight: ComposedWorldGroundHeight = flatGroundHeight,
): ComposedWorld {
  const entity = new pc.Entity('atlas-composed-world');
  const meshes: MeshCatalog = {
    cube: pc.Mesh.fromGeometry(device, new pc.BoxGeometry({ halfExtents: new pc.Vec3(0.5, 0.5, 0.5) })),
    rock: pc.Mesh.fromGeometry(device, new pc.SphereGeometry({ radius: 0.5, latitudeBands: 7, longitudeBands: 8 })),
    sky: pc.Mesh.fromGeometry(device, new pc.SphereGeometry({ radius: 1, latitudeBands: 24, longitudeBands: 48 })),
  };
  const layers = new Map<WorldArtProfileId, ProfileLayer>();

  const buildLayer = (profile: WorldArtProfile): ProfileLayer => {
    const root = new pc.Entity(`world-profile:${profile.profileId}`);
    const stone = createMaterial(profile.palette.stone, { gloss: 0.12 });
    const shadow = createMaterial(profile.palette.stoneShadow, { gloss: 0.08 });
    const brass = createMaterial(profile.palette.brass, { metalness: 0.62, gloss: 0.36 });
    const growth = createMaterial(profile.palette.terrainLift, { gloss: 0.34 });
    const glass = createMaterial(profile.palette.paper, {
      emissive: profile.palette.paper,
      emissiveIntensity: profile.material.emissiveStrength * 0.18,
      gloss: profile.material.gloss,
      opacity: profile.material.opacity,
    });
    glass.cull = pc.CULLFACE_NONE;
    const sky = createSkyMaterial(profile);
    const materials = Object.freeze<pc.Material[]>([stone, shadow, brass, growth, glass, sky]);
    entity.addChild(root);

    const mapHidden = profile.profileId === ORIGIN_LANDSCAPE.profileId
      ? [addOriginEnvironment(root, topology, meshes, shadow, sky)]
      : [];
    const details: pc.Entity[] = [];

    for (const instance of topology.instances) {
      // Foundations remain one continuous field. Evidence bodies are created by source-first-grove
      // so a missing photograph never gets replaced by decorative renderer geometry here.
      // A `landmark` instance draws nothing. The composer already gives one only to a region whose
      // real location is known; the beacon and survey strata this file used to stand there were
      // invented shapes, and a landmark will come from a grammar record, not a renderer loop.
      // `relationship-path` instances draw nothing here either: the inlay this file used to lay
      // was a row of blocks on the straight line between two layout positions.

      /*
       * Every region carries a required growth register, so gating it on one profile ID left the
       * origin world quietly drawing nothing for a module its own catalog says is there. That is
       * the same mistake the orientation register once had: the selector is the declared form, not
       * which style happens to be active.
       */
      if (instance.role === 'expansion-point') {
        const group = atInstance(root, instance, groundHeight);
        const expansion = instance.form?.kind ?? profile.geometry.expansion;
        const declared = instance.form?.parameters['count'];
        const count = declared === undefined
          ? (expansion === 'living-buds' ? 7 : 5)
          : Math.max(1, Math.min(12, Math.round(declared)));
        for (let index = 0; index < count; index += 1) {
          const angle = 0.35 + index * 1.08;
          const distance = 0.28 + index * 0.13;
          if (expansion === 'living-buds') {
            const bud = new pc.Entity(`living-bud:${index}`);
            group.addChild(bud);
            const x = Math.cos(angle) * distance;
            const z = Math.sin(angle) * distance;
            addPrimitive(bud, 'stem', meshes.cube, growth, [x, 0.14, z], [0.035, 0.28, 0.035]);
            addPrimitive(bud, 'leaf-left', meshes.rock, growth, [x - 0.07, 0.26, z], [0.13, 0.055, 0.07], [0, 0, -28]);
            addPrimitive(bud, 'leaf-right', meshes.rock, growth, [x + 0.07, 0.31, z], [0.13, 0.055, 0.07], [0, 0, 28]);
            addPrimitive(bud, 'signal', meshes.rock, index === 0 ? brass : glass, [x, 0.4, z], [0.07, 0.07, 0.07]);
            details.push(bud);
          } else {
            addPrimitive(group, `survey-stake:${index}`, meshes.cube, index === 0 ? brass : stone,
              [Math.cos(angle) * distance, 0.2, Math.sin(angle) * distance],
              [0.045, 0.4 + (index % 2) * 0.12, 0.045], [0, angle * 57.2958, 0]);
          }
        }
      }
    }
    const applyProfile = (next: WorldArtProfile): void => {
      updateMaterial(stone, next.palette.stone, { gloss: 0.34 });
      updateMaterial(shadow, next.palette.stoneShadow, { gloss: 0.28 });
      updateMaterial(brass, next.palette.brass, {
        emissive: next.palette.brass,
        emissiveIntensity: next.material.emissiveStrength * 0.34,
        metalness: 0.38,
        gloss: 0.64,
      });
      updateMaterial(growth, next.palette.terrainLift, { gloss: 0.32 });
      updateMaterial(glass, next.palette.paper, {
        emissive: next.palette.paper,
        emissiveIntensity: next.material.emissiveStrength * 0.18,
        gloss: next.material.gloss,
        opacity: next.material.opacity,
      });
      glass.cull = pc.CULLFACE_NONE;
      glass.update();
      updateSkyMaterial(sky, next);
      details.forEach((detail, index) => { detail.enabled = index % 7 < next.geometry.expansionCount; });
    };
    applyProfile(profile);
    return { root, materials, mapHidden, applyProfile };
  };

  layers.set(ORIGIN_LANDSCAPE.profileId, buildLayer(ORIGIN_LANDSCAPE));
  layers.set(SURVEY_RELIEF.profileId, buildLayer(SURVEY_RELIEF));
  let activeProfileId = initialProfile.profileId;
  let activeProfile = initialProfile;
  let mapActive = false;

  const setProfile = (profile: WorldArtProfile): void => {
    activeProfileId = layers.has(profile.profileId) ? profile.profileId : ORIGIN_LANDSCAPE.profileId;
    activeProfile = profile;
    for (const [id, layer] of layers) {
      layer.root.enabled = id === activeProfileId;
      if (id === activeProfileId) layer.applyProfile(profile);
      for (const hidden of layer.mapHidden) hidden.enabled = !mapActive;
    }
  };
  setProfile(initialProfile);

  return {
    entity,
    topology,
    get profileId() { return activeProfileId; },
    // UI exposure affects readable surfaces and semantic markers, not the landscape's identity.
    setTheme() {},
    setProfile,
    setMapActive(active) {
      mapActive = active;
      for (const layer of layers.values()) {
        for (const hidden of layer.mapHidden) hidden.enabled = !active;
      }
    },
    skyHorizonColour() {
      const sky = layers.get(activeProfileId)?.mapHidden[0]?.findByName('origin-sky') ?? null;
      // `enabled` is false when any ancestor is off, so a hidden layer, the Map and a disabled
      // render root all read as "no sky drawn" without this file knowing why.
      if (sky === null || !sky.enabled) return null;
      // What SKY_FRAGMENT_GLSL writes at d.y = 0: a diffuse canvas meets the horizon at paper, a
      // layered horizon at its haze shelf. Written raw, never tone-mapped.
      return unitRgb(activeProfile.field.atmosphere === 'diffuse-canvas'
        ? activeProfile.palette.paper
        : activeProfile.palette.haze);
    },
    destroy() {
      for (const layer of layers.values()) {
        for (const material of layer.materials) material.destroy();
      }
      meshes.cube.destroy();
      meshes.rock.destroy();
      meshes.sky.destroy();
    },
  };
}
