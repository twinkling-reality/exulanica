/**
 * The binding characterisation harness: real `AtlasBinding.create` on PlayCanvas's null device.
 *
 * Everything but the GPU runs as it does in the app: the engine's scene graph, components,
 * lights, shader chunk registry and the binding's own collaborators. The suites beside this file
 * pin what the binding builds for each kind of world, the order of its work inside a frame and
 * at disposal, what an appearance or Map change does, how its movement locks compose and how it
 * drives a society. They describe the binding as it is, so a change that moves any of it shows
 * up as a diff to read, and a refactor that is meant to move nothing has to leave them alone.
 *
 * The world kinds themselves are in `world-kinds.ts`, which the GPU pixel scenes share.
 */
import { readFileSync } from 'node:fs';
import * as pc from 'playcanvas';
import { vi } from 'vitest';
import { makeScene } from '@exulanica/atlas-core';
import { AtlasBinding, type AtlasBindingOptions } from '../../src/playcanvas/atlas-binding.js';
import { decodeOpm, type PointMap } from '../../src/playcanvas/opm.js';
import { worldOptions as optionsWith, type WorldKind } from './world-kinds.js';

export {
  DISTRICT_DOCUMENT,
  PERSONAL_SCENE,
  STARTER_REGION,
  WORLD_KINDS,
  stubTileMount,
  type WorldKind,
} from './world-kinds.js';

/**
 * The committed `.opm` pin, decoded. Read relative to web/, where the suite runs: under
 * happy-dom, import.meta.url is not a file URL.
 */
export function fixtureMap(): PointMap {
  const bytes = readFileSync('packages/atlas-react/test/fixtures/python-writer.opm');
  return decodeOpm(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer);
}

export function worldOptions(kind: WorldKind): Partial<AtlasBindingOptions> {
  return optionsWith(kind, fixtureMap());
}

/** The Google reference is built with a fetch that refuses, so no request leaves the test. */
export function refuseNetwork(): void {
  vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('no network in the harness'); }));
}

export interface HarnessBinding {
  readonly binding: AtlasBinding;
  readonly canvas: HTMLCanvasElement;
  readonly overlay: HTMLElement;
}

export async function buildBinding(
  kind: WorldKind,
  extra: Partial<AtlasBindingOptions> = {},
): Promise<HarnessBinding> {
  if (kind === 'google-reference' || kind === 'authored-and-google') refuseNetwork();
  const canvas = document.createElement('canvas');
  const overlay = document.createElement('div');
  document.body.append(canvas, overlay);
  const binding = await AtlasBinding.create({
    canvas,
    overlayParent: overlay,
    deviceTypes: ['null'],
    scene: makeScene([], 1, 1),
    pointMaps: new Map(),
    ...worldOptions(kind),
    ...extra,
  } as AtlasBindingOptions);
  return { binding, canvas, overlay };
}

// -- reading what the binding built ----------------------------------------------------------------

const round = (value: number): number => Math.round(value * 1e6) / 1e6;
const triple = (v: pc.Vec3): readonly number[] => [round(v.x), round(v.y), round(v.z)];
const colour = (c: pc.Color): readonly number[] => [round(c.r), round(c.g), round(c.b), round(c.a)];

function materialKind(material: pc.Material | null): string {
  if (material === null) return 'none';
  const kind = material instanceof pc.StandardMaterial ? 'standard'
    : material instanceof pc.ShaderMaterial ? 'shader' : 'other';
  const named = material.name.length > 0 ? `${kind}:${material.name}` : kind;
  // The depth order of surfaces that lie on one another: written only where a material has one.
  return material.depthBias !== 0 || material.slopeDepthBias !== 0
    ? `${named}:offset ${material.depthBias}/${material.slopeDepthBias}` : named;
}

/**
 * One line per node, depth first: name, enabled, local transform, components and, for a render
 * component, its shadow flags and each mesh instance's shadow flags, culling and material.
 */
export function sceneGraph(node: pc.GraphNode, depth = 0): string[] {
  const entity = node as pc.Entity;
  const components = entity.c ? Object.keys(entity.c).sort().join(',') : '';
  let render = '';
  if (entity.render) {
    const instances = entity.render.meshInstances.map((instance) =>
      `${instance.castShadow ? 'C' : '-'}${instance.receiveShadow ? 'R' : '-'}${instance.cull ? 'F' : '-'}`
      + `:${materialKind(instance.material)}`);
    render = `|render ${entity.render.castShadows ? 'C' : '-'}${entity.render.receiveShadows ? 'R' : '-'}`
      + ` [${instances.join(' ')}]`;
  }
  const lines = [`${'  '.repeat(depth)}${node.name}|${entity.enabled}|`
    + `${triple(node.getLocalPosition()).join(',')}|${triple(node.getLocalEulerAngles()).join(',')}|`
    + `${triple(node.getLocalScale()).join(',')}|${components}${render}`];
  for (const child of node.children) lines.push(...sceneGraph(child, depth + 1));
  return lines;
}

/** Which lit end chunk the device builds programs with. */
export function endChunk(device: pc.GraphicsDevice): 'display-space' | 'engine' {
  const chunk = pc.ShaderChunks.get(device, pc.SHADERLANGUAGE_GLSL).get('endPS');
  const toneMap = chunk.indexOf('toneMap(');
  const fog = chunk.search(/fog_color|addFog\(/u);
  return fog > toneMap ? 'display-space' : 'engine';
}

function lights(root: pc.Entity): readonly object[] {
  return (root.findComponents('light') as pc.LightComponent[]).map((light) => ({
    entity: light.entity.name,
    type: light.type,
    colour: colour(light.color),
    intensity: round(light.intensity),
    castShadows: light.castShadows,
    shadowDistance: round(light.shadowDistance),
    normalOffsetBias: round(light.normalOffsetBias),
    shadowBias: round(light.shadowBias),
    shadowResolution: light.shadowResolution,
    shadowType: light.shadowType,
    numCascades: light.numCascades,
    euler: triple(light.entity.getLocalEulerAngles()),
  }));
}

/** What the binding decided for one world, as plain data. */
export function describeBuiltWorld(binding: AtlasBinding): Record<string, unknown> {
  const internals = binding as unknown as {
    atmosphere: { displaySpaceFog: boolean };
    renderOriginState: { origin: { x: number; y: number; z: number } };
    controls: { config: Record<string, number>; enabled: boolean };
  };
  const camera = binding.camera.camera!;
  const scene = binding.app.scene;
  const navigation = binding.navigationWorld;
  const surface = navigation.surface;
  const sample = (x: number, z: number): number | null => {
    const at = surface?.sample(x, z) ?? null;
    return at === null ? null : round(at.height);
  };
  return {
    camera: {
      fov: round(camera.fov), near: round(camera.nearClip), far: round(camera.farClip),
      clear: colour(camera.clearColor), toneMapping: camera.toneMapping,
    },
    scene: {
      ambient: colour(scene.ambientLight), exposure: round(scene.exposure),
      fog: {
        type: scene.fog.type, colour: colour(scene.fog.color),
        start: round(scene.fog.start), end: round(scene.fog.end),
      },
      skybox: scene.skybox !== null,
    },
    lights: lights(binding.app.root),
    endChunk: endChunk(binding.device),
    displaySpaceFog: internals.atmosphere.displaySpaceFog,
    maxPixelRatio: round(binding.device.maxPixelRatio),
    navigation: {
      centre: [round(navigation.centre.x), round(navigation.centre.z)],
      fieldRadius: round(navigation.fieldRadius),
      recoveryRadius: round(navigation.recoveryRadius),
      eyeHeight: round(navigation.eyeHeight),
      regions: navigation.regions.length,
      surface: surface === undefined ? null : {
        origin: sample(0, 0), at100m: sample(100, 0), at8100m: sample(0, -8100), at8200m: sample(0, -8200),
      },
    },
    start: { ...binding.controls.state },
    controls: { ...internals.controls.config, enabled: internals.controls.enabled },
    renderOrigin: [internals.renderOriginState.origin.x, internals.renderOriginState.origin.y,
      internals.renderOriginState.origin.z],
    roots: {
      renderRoot: binding.renderRoot.enabled,
      environmentRoot: binding.environmentRoot.children.map((child) => child.name),
    },
    composedWorld: {
      profile: binding.composedWorld.profileId,
      skyHorizon: binding.composedWorld.skyHorizonColour()?.map(round) ?? null,
      topologyInstances: binding.topology.instances.length,
    },
    present: {
      ownedDistrict: binding.ownedDistrict !== null,
      generatedTile: binding.generatedTile !== null,
      googleTiles: binding.googleTiles !== null,
      authoredSociety: binding.authoredSociety !== null,
      authoredPointMaps: binding.authoredPointMaps !== null,
      overlay: binding.overlay !== null,
      mapOverlay: binding.mapOverlay !== null,
      motes: binding.motes.count,
    },
  };
}

// -- recording what happens, in order --------------------------------------------------------------

/**
 * Replace methods on one object with wrappers that note `label.method` in `log`, then call
 * through. Instance properties shadow the prototype, so a private method is wrapped the same way.
 * A name that is not a method is refused, so a renamed collaborator fails here instead of
 * silently recording nothing.
 */
export function record(log: string[], target: object, label: string, methods: readonly string[]): void {
  const holder = target as Record<string, unknown>;
  for (const method of methods) {
    const original = holder[method];
    if (typeof original !== 'function') throw new TypeError(`${label}.${method} is not a method`);
    holder[method] = function (this: unknown, ...args: unknown[]) {
      log.push(`${label}.${method}`);
      return (original as (...a: unknown[]) => unknown).apply(this, args);
    };
  }
}
