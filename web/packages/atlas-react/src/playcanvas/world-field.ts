import * as pc from 'playcanvas';
import type { NavigationPose, NavigationWorld } from '@exulanica/atlas-core';
import {
  DAWN_THEME,
  ORIGIN_LANDSCAPE,
  unitRgb,
  worldSilhouetteTone,
  type PresentationTheme,
  type WorldArtProfile,
} from '@exulanica/presentation';

const AEROHEART_IDLE_CYCLE_MS = 5_200;

/** Access preference is the final authority over a profile's bounded ambient cadence. */
export function worldMotionSeconds(
  nowMs: number,
  idleCycleMs: number,
  reducedMotion: boolean,
): number {
  if (reducedMotion) return 0;
  const cycle = Number.isFinite(idleCycleMs) && idleCycleMs > 0
    ? idleCycleMs
    : AEROHEART_IDLE_CYCLE_MS;
  return nowMs * 0.001 * (AEROHEART_IDLE_CYCLE_MS / cycle);
}

interface ShaderDesc {
  uniqueName: string;
  attributes?: Record<string, string>;
  vertexGLSL?: string;
  fragmentGLSL?: string;
}

const VERTEX_GLSL = /* glsl */ `
attribute vec3 aPosition;
attribute vec3 aNormal;
uniform mat4 matrix_model;
uniform mat3 matrix_normal;
uniform mat4 matrix_viewProjection;
varying vec3 vWorld;
varying vec3 vNormal;

void main(void) {
    vec4 world = matrix_model * vec4(aPosition, 1.0);
    vWorld = world.xyz;
    vNormal = normalize(matrix_normal * aNormal);
    gl_Position = matrix_viewProjection * world;
}
`;

function fragmentGlsl(regionCapacity: number, traceCapacity: number): string {
  return /* glsl */ `
precision highp float;

varying vec3 vWorld;
varying vec3 vNormal;
uniform vec3 view_position;
uniform vec3 uGround;
uniform vec3 uSurface;
uniform vec3 uAtmosphere;
uniform vec3 uTraceColour;
uniform vec3 uPaper;
uniform vec3 uInk;
/** 0 = reflective-tide, 1 = paper-contour. Authored by the profile, never by a profile ID. */
uniform float uSurfaceForm;
uniform float uSurfacePresence;
uniform vec4 uField;
uniform vec4 uRegions[${regionCapacity}];
uniform vec4 uTraceA[${traceCapacity}];
uniform vec4 uTraceB[${traceCapacity}];
uniform vec2 uCounts;
uniform float uMapMode;
uniform vec2 uRenderOrigin;
uniform float uTime;

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
               mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}

/**
 * One contour of the authored relief.
 *
 * Perspective compresses world-space lines toward the horizon, so the line widens with view
 * distance: the near field keeps crisp separate contours to walk against, and the far field
 * thickens into continuous tone instead of aliasing into speckle.
 */
float contourInk(float relief, float viewDistance) {
    float lines = relief * 11.0;
    float f = fract(lines);
    float toLine = min(f, 1.0 - f) * 2.0;
    float width = 0.09 + smoothstep(10.0, 130.0, viewDistance) * 0.52;
    return 1.0 - smoothstep(0.0, width, toLine);
}

vec2 segmentProjection(vec2 p, vec2 a, vec2 b) {
    vec2 ab = b - a;
    float t = clamp(dot(p - a, ab) / max(dot(ab, ab), 0.0001), 0.0, 1.0);
    vec2 normal = normalize(vec2(-ab.y, ab.x) + vec2(0.0001));
    vec2 centre = a + ab * t + normal * sin(t * 3.14159265) * min(1.8, length(ab) * 0.025);
    return vec2(length(p - centre), t);
}

void main(void) {
    vec2 p = vWorld.xz + uRenderOrigin;
    vec2 local = p - uField.xy;
    vec3 normal = normalize(vNormal);
    vec3 toEye = normalize(view_position - vWorld);
    float viewDistance = distance(vWorld, view_position);
    float grazing = 1.0 - max(0.0, dot(normal, toEye));
    float fresnel = pow(grazing, 2.6);
    float slow = noise(p * 0.018 + vec2(uTime * 0.006, -uTime * 0.004));
    float crossing = noise(p * 0.055 + vec2(-uTime * 0.012, uTime * 0.008));
    float drift = sin(p.x * 0.052 + p.y * 0.019 + slow * 4.8 + uTime * 0.026) * 0.5 + 0.5;
    float crossDrift = sin(p.x * -0.031 + p.y * 0.071 + crossing * 3.6 - uTime * 0.018) * 0.5 + 0.5;
    float fine = sin((p.x + p.y) * 0.28 + slow * 5.0 + uTime * 0.04) * 0.5 + 0.5;
    float opticalBody = slow * 0.44 + crossing * 0.22 + drift * 0.22 + crossDrift * 0.12;
    vec3 deep = mix(uGround, uSurface, 0.22 + opticalBody * 0.34);
    vec3 reflectedAir = mix(uSurface, uAtmosphere, 0.45 + slow * 0.24);
    vec3 colour = mix(deep, reflectedAir, 0.14 + fresnel * 0.58);
    float interference = abs(drift - crossDrift);
    float glimmer = smoothstep(0.76, 0.98, interference * 0.62 + fine * 0.38);
    colour += mix(uSurface, uAtmosphere, 0.62) * glimmer * 0.14 * (1.0 - uMapMode);

    // A paper-contour world walks on a sheet, not on a reflective tide.
    //
    // The relief is sampled WITHOUT uTime. A tide is supposed to flow, so the fields above carry
    // time; contours are not allowed to. A ground that slides on its own cannot answer "did I
    // move", which is the only question this surface exists to answer: drifting contours make a
    // still camera and a walking one look identical.
    float relief = noise(p * 0.018) * 0.62 + noise(p * 0.055) * 0.38;
    if (uSurfaceForm > 0.5) {
        vec3 sheet = mix(uPaper, uSurface, 0.05 + relief * 0.07);
        float contour = contourInk(relief, viewDistance);
        // Paper fibre in world space. Near the feet this is the only high-frequency reference a
        // person has, and it is what turns walking into visible movement rather than a still image.
        float fibre = noise(p * vec2(1.45, 0.46)) * 0.58 + noise(p * vec2(0.46, 1.45)) * 0.42;
        sheet = mix(sheet, uInk, contour * 0.30 * uSurfacePresence);
        sheet *= 1.0 - (fibre - 0.5) * 0.05 * uSurfacePresence;
        colour = mix(colour, sheet, 1.0 - uMapMode);
    }

    // Map is a cartographic exposure of the same reflective medium.
    vec3 mapField = mix(uGround, uSurface, 0.28);
    colour = mix(colour, mapField, uMapMode * 0.86);

    for (int i = 0; i < ${regionCapacity}; i++) {
        if (float(i) >= uCounts.x) break;
        vec4 region = uRegions[i];
        vec2 delta = p - region.xy;
        float d = length(delta);
        float presence = 1.0 - smoothstep(region.z * 0.8, region.z + 18.0, d);
        float wave = abs(sin(d * 0.31 - uTime * 0.18 + float(i) * 1.7));
        float memoryRipple = smoothstep(0.94, 1.0, wave) * presence;
        float basin = exp(-d * 0.055) * presence;
        // Contact shading. On paper this is what tells a person a memory region SITS on the
        // surface rather than floating above an undefined space.
        vec3 contact = mix(uSurface, uInk, uSurfaceForm * 0.72);
        float contactWeight = mix(0.09, 0.20 * uSurfacePresence, uSurfaceForm);
        colour = mix(colour, contact, basin * contactWeight + memoryRipple * 0.045);
        float mapDiamond = abs(delta.x) + abs(delta.y);
        float mapNode = 1.0 - smoothstep(0.48, 1.18, mapDiamond);
        colour = mix(colour, uTraceColour, mapNode * uMapMode * 0.94);
    }

    for (int i = 0; i < ${traceCapacity}; i++) {
        if (float(i) >= uCounts.y) break;
        vec2 projected = segmentProjection(p, uTraceA[i].xy, uTraceB[i].xy);
        float trace = 1.0 - smoothstep(0.075, 0.22 + uTraceA[i].z * 0.16, projected.x);
        float traveller = exp(-pow(fract(projected.y - uTime * 0.035) - 0.5, 2.0) * 210.0);
        // A relationship segment reads as an arbitrary road or light stripe at eye height.
        // Expose the same confirmed topology only in Map, where its endpoints and overview
        // context make it legible as a relationship rather than as decorative ground geometry.
        float strength = (0.79 + uTraceA[i].z * 0.12 + traveller * 0.34) * uMapMode;
        colour = mix(colour, uTraceColour, trace * strength);
    }

    float radial = length(local);
    float fieldDissolve = smoothstep(uField.z, uField.w, radial);
    // A reflective tide is meant to disappear into haze almost immediately at eye height. A sheet
    // of paper is not: at 1.62 eye height the tide's dissolve is already 84% complete ten units
    // ahead, which is why a discarded floor and a held floor looked identical. Paper holds its
    // surface out to roughly 25 units, then fades to a soft edge instead of a stacked band.
    float distanceDissolve = smoothstep(
        mix(26.0, 90.0, uSurfaceForm), mix(108.0, 420.0, uSurfaceForm), viewDistance);
    float horizonDissolve = smoothstep(
        mix(0.48, 0.90, uSurfaceForm), mix(0.96, 0.999, uSurfaceForm), grazing);
    float atmosphere = max(fieldDissolve * 0.78, max(distanceDissolve, horizonDissolve));
    float mapAtmosphere = horizonDissolve * uMapMode;
    colour = mix(colour, uAtmosphere, max(atmosphere * (1.0 - uMapMode), mapAtmosphere));
    gl_FragColor = vec4(colour, 1.0);
}
`;
}

export interface WorldField {
  readonly entity: pc.Entity;
  setTheme(theme: PresentationTheme): void;
  setProfile(profile: WorldArtProfile): void;
  setMapGroundPose(pose: NavigationPose | null): void;
  setRenderOrigin(x: number, z: number): void;
  setReducedMotion(reduced: boolean): void;
  update(nowMs: number): void;
  destroy(): void;
}

/** Exact visible support authored by a source-independent region descriptor. */
export interface AuthoredGroundSupport {
  readonly halfWidth: number;
  readonly halfDepth: number;
  readonly elevation: number;
}

export interface MeshGeometryData {
  readonly positions: readonly number[];
  readonly normals: readonly number[];
  readonly indices: readonly number[];
}

export interface AuthoredGroundGeometry {
  readonly surface: MeshGeometryData;
  readonly boundary: MeshGeometryData;
}

/**
 * Build the finite support stated by an authored-region descriptor.
 *
 * The upper face ends at the exact authored bounds. A narrow top rim and vertical fascia make
 * that limit readable from inside the region and in Map, without inventing scenery beyond it.
 */
export function authoredGroundGeometry(support: AuthoredGroundSupport): AuthoredGroundGeometry {
  const { halfWidth, halfDepth, elevation } = support;
  if (
    !Number.isFinite(halfWidth) || halfWidth <= 0 ||
    !Number.isFinite(halfDepth) || halfDepth <= 0 ||
    !Number.isFinite(elevation)
  ) throw new Error('authored ground support must have finite positive extents and elevation');

  const rimWidth = Math.min(0.32, halfWidth / 6, halfDepth / 6);
  const innerWidth = halfWidth - rimWidth;
  const innerDepth = halfDepth - rimWidth;
  const surface = Object.freeze({
    positions: Object.freeze([
      -innerWidth, elevation, -innerDepth,
      innerWidth, elevation, -innerDepth,
      innerWidth, elevation, innerDepth,
      -innerWidth, elevation, innerDepth,
    ]),
    normals: Object.freeze([
      0, 1, 0,
      0, 1, 0,
      0, 1, 0,
      0, 1, 0,
    ]),
    indices: Object.freeze([0, 2, 1, 0, 3, 2]),
  });

  const fasciaBottom = elevation - Math.min(0.22, Math.min(halfWidth, halfDepth) / 12);
  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];
  const quad = (
    a: readonly [number, number, number],
    b: readonly [number, number, number],
    c: readonly [number, number, number],
    d: readonly [number, number, number],
    normal: readonly [number, number, number],
  ): void => {
    const offset = positions.length / 3;
    positions.push(...a, ...b, ...c, ...d);
    for (let index = 0; index < 4; index += 1) normals.push(...normal);
    indices.push(offset, offset + 2, offset + 1, offset, offset + 3, offset + 2);
  };

  // Top rim, ordered as four non-overlapping strips inside the authored rectangle.
  quad(
    [-halfWidth, elevation, -halfDepth], [halfWidth, elevation, -halfDepth],
    [halfWidth, elevation, -innerDepth], [-halfWidth, elevation, -innerDepth], [0, 1, 0],
  );
  quad(
    [-halfWidth, elevation, innerDepth], [halfWidth, elevation, innerDepth],
    [halfWidth, elevation, halfDepth], [-halfWidth, elevation, halfDepth], [0, 1, 0],
  );
  quad(
    [-halfWidth, elevation, -innerDepth], [-innerWidth, elevation, -innerDepth],
    [-innerWidth, elevation, innerDepth], [-halfWidth, elevation, innerDepth], [0, 1, 0],
  );
  quad(
    [innerWidth, elevation, -innerDepth], [halfWidth, elevation, -innerDepth],
    [halfWidth, elevation, innerDepth], [innerWidth, elevation, innerDepth], [0, 1, 0],
  );
  // Vertical fascia uses the same structural material as the rim and exposes the finite support.
  quad(
    [-halfWidth, fasciaBottom, -halfDepth], [halfWidth, fasciaBottom, -halfDepth],
    [halfWidth, elevation, -halfDepth], [-halfWidth, elevation, -halfDepth], [0, 0, -1],
  );
  quad(
    [halfWidth, fasciaBottom, halfDepth], [-halfWidth, fasciaBottom, halfDepth],
    [-halfWidth, elevation, halfDepth], [halfWidth, elevation, halfDepth], [0, 0, 1],
  );
  quad(
    [-halfWidth, fasciaBottom, halfDepth], [-halfWidth, fasciaBottom, -halfDepth],
    [-halfWidth, elevation, -halfDepth], [-halfWidth, elevation, halfDepth], [-1, 0, 0],
  );
  quad(
    [halfWidth, fasciaBottom, -halfDepth], [halfWidth, fasciaBottom, halfDepth],
    [halfWidth, elevation, halfDepth], [halfWidth, elevation, -halfDepth], [1, 0, 0],
  );

  return Object.freeze({
    surface,
    boundary: Object.freeze({
      positions: Object.freeze(positions),
      normals: Object.freeze(normals),
      indices: Object.freeze(indices),
    }),
  });
}

export function worldFieldBufferShape(world: NavigationWorld): {
  readonly regionCapacity: number;
  readonly traceCapacity: number;
  readonly regionFloats: number;
  readonly traceFloats: number;
} {
  return Object.freeze({
    regionCapacity: Math.max(1, world.regions.length),
    traceCapacity: Math.max(1, world.traces.length),
    regionFloats: world.regions.length * 4,
    traceFloats: world.traces.length * 8,
  });
}

function createLandscapeMesh(
  device: pc.GraphicsDevice,
  world: NavigationWorld,
  halfExtent: number,
  segments = 160,
): pc.Mesh {
  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];
  for (let zIndex = 0; zIndex <= segments; zIndex += 1) {
    const localZ = -halfExtent + (zIndex / segments) * halfExtent * 2;
    for (let xIndex = 0; xIndex <= segments; xIndex += 1) {
      const localX = -halfExtent + (xIndex / segments) * halfExtent * 2;
      const sample = world.surface.sample(world.centre.x + localX, world.centre.z + localZ);
      const height = sample?.height ?? 0;
      const normal = sample?.normal ?? { x: 0, y: 1, z: 0 };
      positions.push(localX, height, localZ);
      normals.push(normal.x, normal.y, normal.z);
    }
  }
  const stride = segments + 1;
  for (let zIndex = 0; zIndex < segments; zIndex += 1) {
    for (let xIndex = 0; xIndex < segments; xIndex += 1) {
      const a = zIndex * stride + xIndex;
      const b = a + 1;
      const c = a + stride;
      const d = c + 1;
      indices.push(a, c, b, b, c, d);
    }
  }
  const geometry = new pc.Geometry();
  geometry.positions = positions;
  geometry.normals = normals;
  geometry.indices = indices;
  return pc.Mesh.fromGeometry(device, geometry);
}

function createMesh(device: pc.GraphicsDevice, data: MeshGeometryData): pc.Mesh {
  const geometry = new pc.Geometry();
  geometry.positions = [...data.positions];
  geometry.normals = [...data.normals];
  geometry.indices = [...data.indices];
  return pc.Mesh.fromGeometry(device, geometry);
}

interface AuthoredGroundMaterial {
  readonly material: pc.StandardMaterial;
  applyProfile(profile: WorldArtProfile): void;
}

function authoredGroundMaterial(profile: WorldArtProfile, boundary: boolean): AuthoredGroundMaterial {
  const material = new pc.StandardMaterial();
  material.useLighting = true;
  material.useFog = true;
  material.metalness = 0;
  material.gloss = boundary ? 0.08 : 0.14;
  const apply = (next: WorldArtProfile): void => {
    const [r, g, b] = unitRgb(
      boundary ? worldSilhouetteTone(next.palette) : next.palette.terrain,
    );
    material.diffuse.set(r, g, b);
    const [er, eg, eb] = unitRgb(boundary ? next.palette.stoneShadow : next.palette.terrainLift);
    material.emissive.set(er, eg, eb);
    material.emissiveIntensity = boundary ? 0.025 : 0.045;
    material.update();
  };
  apply(profile);
  return Object.freeze({ material, applyProfile: apply });
}

/** A continuous low-frequency field: ground, soft region bodies, and confirmed semantic traces. */
export function createWorldField(
  device: pc.GraphicsDevice,
  world: NavigationWorld,
  initialProfile: WorldArtProfile = ORIGIN_LANDSCAPE,
  theme: PresentationTheme = DAWN_THEME,
  initiallyReducedMotion = false,
  authoredSupport?: AuthoredGroundSupport,
): WorldField {
  const entity = new pc.Entity('atlas-world-field');
  const buffers = worldFieldBufferShape(world);
  // The navigable/recovery radii remain visible in the material, but the physical draw surface
  // extends beyond the far clip so its square edge can never masquerade as a platform boundary.
  const visualHalfExtent = Math.max(2200, world.recoveryRadius * 4.8);
  // 220 segments is ~193k triangles for a surface whose relief, contours, regions and traces are
  // all computed per pixel. The mesh only has to carry the height field well enough that the
  // silhouette and the horizon read correctly, and 96 does that at a fifth of the geometry.
  const authoredGeometry = authoredSupport === undefined
    ? null
    : authoredGroundGeometry(authoredSupport);
  const mesh = authoredGeometry === null
    ? createLandscapeMesh(device, world, visualHalfExtent, 96)
    : createMesh(device, authoredGeometry.surface);
  const material = new pc.ShaderMaterial({
    uniqueName: `exulanica-grounded-world-field:${buffers.regionCapacity}:${buffers.traceCapacity}`,
    attributes: { aPosition: pc.SEMANTIC_POSITION, aNormal: pc.SEMANTIC_NORMAL },
    vertexGLSL: VERTEX_GLSL,
    fragmentGLSL: fragmentGlsl(buffers.regionCapacity, buffers.traceCapacity),
  } as ShaderDesc);
  material.cull = pc.CULLFACE_NONE;
  material.depthWrite = true;
  material.blendType = pc.BLEND_NONE;
  const authoredMaterial = authoredSupport === undefined
    ? null
    : authoredGroundMaterial(initialProfile, false);
  const boundaryMesh = authoredGeometry === null
    ? null
    : createMesh(device, authoredGeometry.boundary);
  const boundaryMaterial = authoredSupport === undefined
    ? null
    : authoredGroundMaterial(initialProfile, true);

  const regions = new Float32Array(buffers.regionCapacity * 4);
  for (let i = 0; i < world.regions.length; i += 1) {
    const region = world.regions[i]!;
    regions.set(
      [region.centre.x, region.centre.z, region.footprintRadius, region.dissolveStartRadius],
      i * 4,
    );
  }
  const traceA = new Float32Array(buffers.traceCapacity * 4);
  const traceB = new Float32Array(buffers.traceCapacity * 4);
  for (let i = 0; i < world.traces.length; i += 1) {
    const trace = world.traces[i]!;
    traceA.set([trace.start.x, trace.start.z, trace.strength, 0], i * 4);
    traceB.set([trace.end.x, trace.end.z, 0, 0], i * 4);
  }
  material.setParameter('uField', new Float32Array([
    world.centre.x,
    world.centre.z,
    world.fieldRadius,
    world.recoveryRadius,
  ]));
  material.setParameter('uRegions[0]', regions);
  material.setParameter('uTraceA[0]', traceA);
  material.setParameter('uTraceB[0]', traceB);
  material.setParameter('uCounts', new Float32Array([
    world.regions.length,
    world.traces.length,
  ]));
  material.setParameter('uMapMode', 0);
  material.setParameter('uRenderOrigin', new Float32Array([0, 0]));
  material.setParameter('uTime', 0);

  let idleCycleMs = initialProfile.ui.motion.idleCycleMs;
  let reducedMotion = initiallyReducedMotion;
  const setProfile = (profile: WorldArtProfile): void => {
    idleCycleMs = profile.ui.motion.idleCycleMs;
    if (authoredMaterial !== null && boundaryMaterial !== null) {
      authoredMaterial.applyProfile(profile);
      boundaryMaterial.applyProfile(profile);
      return;
    }
    material.setParameter('uGround', new Float32Array(unitRgb(profile.palette.terrain)));
    material.setParameter('uSurface', new Float32Array(unitRgb(profile.palette.terrainLift)));
    material.setParameter('uAtmosphere', new Float32Array(unitRgb(profile.palette.haze)));
    material.setParameter('uTraceColour', new Float32Array(unitRgb(profile.palette.path)));
    material.setParameter('uPaper', new Float32Array(unitRgb(profile.palette.paper)));
    material.setParameter('uInk', new Float32Array(unitRgb(worldSilhouetteTone(profile.palette))));
    material.setParameter('uSurfaceForm', profile.field.surface === 'paper-contour' ? 1 : 0);
    material.setParameter('uSurfacePresence', profile.field.surfacePresence);
    material.update();
  };
  setProfile(initialProfile);

  const fieldCentre = authoredSupport === undefined
    ? { x: world.centre.x, z: world.centre.z }
    : { x: 0, z: 0 };
  entity.setPosition(fieldCentre.x, authoredSupport === undefined ? -0.035 : 0, fieldCentre.z);
  const fieldInstance = new pc.MeshInstance(mesh, authoredMaterial?.material ?? material, entity);
  fieldInstance.castShadow = false;
  fieldInstance.receiveShadow = authoredSupport !== undefined;
  const boundaryInstance = boundaryMesh === null || boundaryMaterial === null
    ? null
    : new pc.MeshInstance(boundaryMesh, boundaryMaterial.material, entity);
  if (boundaryInstance !== null) {
    boundaryInstance.castShadow = false;
    boundaryInstance.receiveShadow = true;
  }
  entity.addComponent('render', {
    meshInstances: boundaryInstance === null ? [fieldInstance] : [fieldInstance, boundaryInstance],
  });
  if (entity.render !== undefined && entity.render !== null) {
    entity.render.castShadows = false;
    entity.render.receiveShadows = authoredSupport !== undefined;
  }

  const marker = new pc.Entity('atlas-map-user-marker');
  const markerGeometry = new pc.Geometry();
  markerGeometry.positions = [0, 0, -4.2, -2.1, 0, 0.8, 2.1, 0, 0.8];
  markerGeometry.indices = [0, 1, 2];
  const markerMesh = pc.Mesh.fromGeometry(device, markerGeometry);
  const markerMaterial = new pc.StandardMaterial();
  markerMaterial.useLighting = false;
  markerMaterial.cull = pc.CULLFACE_NONE;
  markerMaterial.emissiveIntensity = 1;
  markerMaterial.opacity = 0.24;
  markerMaterial.blendType = pc.BLEND_NORMAL;
  markerMaterial.depthWrite = false;

  const body = new pc.Entity('atlas-map-user-body');
  const bodyGeometry = new pc.Geometry();
  bodyGeometry.positions = [0, 0, -0.9, -0.48, 0, 0.55, 0.48, 0, 0.55];
  bodyGeometry.indices = [0, 1, 2];
  const bodyMesh = pc.Mesh.fromGeometry(device, bodyGeometry);
  const bodyMaterial = new pc.StandardMaterial();
  bodyMaterial.useLighting = false;
  bodyMaterial.cull = pc.CULLFACE_NONE;
  bodyMaterial.emissiveIntensity = 1;
  body.addComponent('render', {
    meshInstances: [new pc.MeshInstance(bodyMesh, bodyMaterial, body)],
  });
  body.setLocalPosition(0, 0.02, 0);
  marker.addChild(body);
  const setMarkerTheme = (next: PresentationTheme): void => {
    const [r, g, b] = unitRgb(next.focus);
    markerMaterial.diffuse.set(r, g, b);
    markerMaterial.emissive.set(r, g, b);
    bodyMaterial.diffuse.set(r, g, b);
    bodyMaterial.emissive.set(r, g, b);
    markerMaterial.update();
    bodyMaterial.update();
  };
  setMarkerTheme(theme);
  marker.addComponent('render', {
    meshInstances: [new pc.MeshInstance(markerMesh, markerMaterial, marker)],
  });
  marker.enabled = false;
  entity.addChild(marker);

  return {
    entity,
    setTheme(next) {
      setMarkerTheme(next);
    },
    setProfile,
    setMapGroundPose(pose) {
      marker.enabled = pose !== null;
      if (authoredSupport === undefined) material.setParameter('uMapMode', pose === null ? 0 : 1);
      if (pose === null) return;
      marker.setPosition(
        pose.position.x - fieldCentre.x,
        (authoredSupport?.elevation ?? 0) + 0.09,
        pose.position.z - fieldCentre.z,
      );
      marker.setEulerAngles(0, (pose.yaw * 180) / Math.PI, 0);
    },
    setRenderOrigin(x, z) {
      if (authoredSupport === undefined) {
        material.setParameter('uRenderOrigin', new Float32Array([x, z]));
      }
    },
    setReducedMotion(reduced) {
      reducedMotion = reduced;
    },
    update(nowMs) {
      if (authoredSupport === undefined) {
        material.setParameter('uTime', worldMotionSeconds(nowMs, idleCycleMs, reducedMotion));
      }
    },
    destroy() {
      markerMesh.destroy();
      bodyMesh.destroy();
      mesh.destroy();
      boundaryMesh?.destroy();
      material.destroy();
      authoredMaterial?.material.destroy();
      boundaryMaterial?.material.destroy();
      markerMaterial.destroy();
      bodyMaterial.destroy();
    },
  };
}
