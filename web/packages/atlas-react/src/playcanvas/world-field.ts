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
  /**
   * Show or clear the placement confirm landing on the authored walking face.
   *
   * Distinct from {@link setMapGroundPose}: that marker is the visitor’s Map attention.
   * This one is the already-computed place pose held through confirmation before commit.
   */
  setPlacementLandingPose(pose: NavigationPose | null): void;
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

/**
 * An authored ground with no perimeter: it states an elevation and nothing a rectangle could be
 * drawn from. It is still an authored starter, so it is still the floor objects are placed on.
 */
export interface EndlessAuthoredGroundSupport {
  readonly kind: 'endless';
  readonly elevation: number;
  /**
   * How far the camera sees, in metres: its far clip. The drawn face reaches this far past the
   * farthest point a walk can stand, and no farther, because its size is its depth precision.
   */
  readonly reach: number;
}

/**
 * Which of the two supports this is. By the presence of `kind`, because the bounded shape has no
 * such field: it predates grounds that could be endless, and its callers build it without one.
 */
function isEndlessAuthoredGroundSupport(
  support: AuthoredGroundSupport | EndlessAuthoredGroundSupport,
): support is EndlessAuthoredGroundSupport {
  return 'kind' in support && support.kind === 'endless';
}

/**
 * The walking face of an endless authored ground: a flat grid at the authored elevation.
 *
 * `halfExtent` is how far the drawn surface reaches, which is not an edge the ground has. It is
 * sized by the caller past everything the camera can see from anywhere a walk can reach, so the
 * grid's own border is always behind the far clip and the fog, and never reads as a place.
 *
 * The grid's cells are no wider than `cellSize`, which the caller sets to the camera's reach.
 * One quad across the whole extent was tried first: its depth, interpolated from corners
 * kilometres away, missed its own plane by more than any small offset, so an object lying on the
 * face lost to it at some poses (see the depth order below). Cells as wide as the view hold it.
 */
export function endlessAuthoredGroundSurface(
  elevation: number,
  halfExtent: number,
  cellSize: number,
): MeshGeometryData {
  if (!Number.isFinite(elevation) || !Number.isFinite(halfExtent) || halfExtent <= 0) {
    throw new Error(
      'an endless authored ground needs a finite elevation and a positive drawn reach',
    );
  }
  if (!Number.isFinite(cellSize) || cellSize <= 0) {
    throw new Error('an endless authored ground needs a positive cell size');
  }
  const cells = Math.ceil((2 * halfExtent) / cellSize);
  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];
  for (let row = 0; row <= cells; row += 1) {
    for (let column = 0; column <= cells; column += 1) {
      positions.push(
        -halfExtent + (2 * halfExtent * column) / cells,
        elevation,
        -halfExtent + (2 * halfExtent * row) / cells,
      );
      normals.push(0, 1, 0);
    }
  }
  for (let row = 0; row < cells; row += 1) {
    for (let column = 0; column < cells; column += 1) {
      const corner = row * (cells + 1) + column;
      const across = corner + 1;
      const far = corner + cells + 2;
      const down = corner + cells + 1;
      indices.push(corner, far, across, corner, down, far);
    }
  }
  return Object.freeze({
    positions: Object.freeze(positions),
    normals: Object.freeze(normals),
    indices: Object.freeze(indices),
  });
}

/**
 * Metres between scale marks on an authored walking face.
 *
 * One metre is a body-scale interval a person can count against the player figure and against
 * placed objects. It is not scenery: the marks stay inside the walking face and invent nothing
 * beyond the authored rectangle.
 */
export const AUTHORED_GROUND_SCALE_SPACING_M = 1;

/*
 * THE ORDER OF THINGS THAT LIE ON THE WALKING FACE, IN THE DEPTH BUFFER.
 *
 * Objects rest on the walking face at its own elevation: a reviewed marker plate is a square of
 * no thickness lying there. Two surfaces at one depth tie, and the depth buffer then picks per
 * pixel, which is a plate that flickers as the camera moves or is not drawn at all. So the face
 * and its rim are drawn behind anything coplanar by a polygon offset (a constant in depth-buffer
 * units and a factor of the surface's own depth slope), and the metre marks lie on the face,
 * drawn behind by less: over the face and under whatever rests on it.
 *
 * MEASURED on WebGL2 (ANGLE Metal) over a camera sweep of 155 poses aimed at a plate: with no
 * offset, on the endless face, the plate's interior was drawn on 44 per cent of its area on
 * average over the poses where it had one, and not at all from 1.5 to 3 metres; with this offset
 * and the endless face drawn in cells no wider than its reach, it was drawn whole at every pose,
 * at the origin and at 8 km. The slope factor is what separates them: a constant alone, up to 64
 * units, left the plate as it was.
 *
 * WHY THE MARGIN GROWS WITH DISTANCE, AND WHAT THAT COSTS. This follows from the offset's
 * definition and was not measured separately. The slope term is the factor times the face's own
 * change in depth-buffer value per pixel, and a level face seen from eye height h changes by the
 * same amount per pixel row at every distance (near clip / (h x focal length in pixels)). Turned
 * back into the world, that is a margin under the face of about factor x distance / focal length:
 * with 900 rows and a 70 degree vertical field of view (focal length 643 px), 3 mm at 1 m, 3 cm at
 * 10 m, 31 cm at 100 m. Two things follow. A face lying just under the ground, and so behind it, is
 * drawn in front of it wherever it lies less than that margin below. And the offset carries the
 * ground's depth to the far plane at about h x focal length / factor, some 400 to 520 m for 720
 * to 900 rows at eye height, where the sky is drawn too (composed-world.ts writes it at the far
 * plane): the two tie there, and which is kept is decided by the order they are drawn in, not by
 * depth.
 */
const AUTHORED_FACE_DEPTH_OFFSET = 2;
const AUTHORED_MARK_DEPTH_OFFSET = 1;

export interface MeshGeometryData {
  readonly positions: readonly number[];
  readonly normals: readonly number[];
  readonly indices: readonly number[];
}

export interface AuthoredGroundGeometry {
  readonly surface: MeshGeometryData;
  readonly boundary: MeshGeometryData;
  /** Metre-spaced marks and origin axes on the walking face. */
  readonly scaleCue: MeshGeometryData;
}

function authoredRimWidth(halfWidth: number, halfDepth: number): number {
  return Math.min(0.32, halfWidth / 6, halfDepth / 6);
}

/**
 * Metre marks and stronger origin axes on the inner walking face.
 *
 * Regular strips give readable size. The axes through the region origin give orientation without
 * inventing a compass rose or any mark outside the authored support.
 */
export function authoredGroundScaleCue(
  support: AuthoredGroundSupport,
  rimWidth = authoredRimWidth(support.halfWidth, support.halfDepth),
): MeshGeometryData {
  const { halfWidth, halfDepth, elevation } = support;
  if (
    !Number.isFinite(halfWidth) || halfWidth <= 0 ||
    !Number.isFinite(halfDepth) || halfDepth <= 0 ||
    !Number.isFinite(elevation) ||
    !Number.isFinite(rimWidth) || rimWidth < 0
  ) throw new Error('authored ground support must have finite positive extents and elevation');

  const innerWidth = halfWidth - rimWidth;
  const innerDepth = halfDepth - rimWidth;
  if (!(innerWidth > AUTHORED_GROUND_SCALE_SPACING_M) || !(innerDepth > AUTHORED_GROUND_SCALE_SPACING_M)) {
    return Object.freeze({
      positions: Object.freeze([] as number[]),
      normals: Object.freeze([] as number[]),
      indices: Object.freeze([] as number[]),
    });
  }

  const y = elevation;
  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];
  const strip = (
    a: readonly [number, number, number],
    b: readonly [number, number, number],
    c: readonly [number, number, number],
    d: readonly [number, number, number],
  ): void => {
    const offset = positions.length / 3;
    positions.push(...a, ...b, ...c, ...d);
    for (let index = 0; index < 4; index += 1) normals.push(0, 1, 0);
    indices.push(offset, offset + 2, offset + 1, offset, offset + 3, offset + 2);
  };

  const halfMark = 0.018;
  const halfAxis = 0.04;
  const maxX = Math.floor(innerWidth / AUTHORED_GROUND_SCALE_SPACING_M) * AUTHORED_GROUND_SCALE_SPACING_M;
  const maxZ = Math.floor(innerDepth / AUTHORED_GROUND_SCALE_SPACING_M) * AUTHORED_GROUND_SCALE_SPACING_M;

  for (
    let x = -maxX;
    x <= maxX + AUTHORED_GROUND_SCALE_SPACING_M * 0.5;
    x += AUTHORED_GROUND_SCALE_SPACING_M
  ) {
    const half = Math.abs(x) < 1e-9 ? halfAxis : halfMark;
    const left = Math.max(-innerWidth, x - half);
    const right = Math.min(innerWidth, x + half);
    if (!(right > left)) continue;
    strip(
      [left, y, -innerDepth], [right, y, -innerDepth],
      [right, y, innerDepth], [left, y, innerDepth],
    );
  }
  for (
    let z = -maxZ;
    z <= maxZ + AUTHORED_GROUND_SCALE_SPACING_M * 0.5;
    z += AUTHORED_GROUND_SCALE_SPACING_M
  ) {
    // The origin axes are already drawn by the x-pass. Skip the z = 0 strip so the crossing
    // stays a single readable mark rather than a stacked double thickness.
    if (Math.abs(z) < 1e-9) continue;
    const half = halfMark;
    const near = Math.max(-innerDepth, z - half);
    const far = Math.min(innerDepth, z + half);
    if (!(far > near)) continue;
    strip(
      [-innerWidth, y, near], [innerWidth, y, near],
      [innerWidth, y, far], [-innerWidth, y, far],
    );
  }

  return Object.freeze({
    positions: Object.freeze(positions),
    normals: Object.freeze(normals),
    indices: Object.freeze(indices),
  });
}

/**
 * Build the finite support stated by an authored-region descriptor.
 *
 * The upper face ends at the exact authored bounds. A narrow top rim and vertical fascia make
 * that limit readable from inside the region and in Map, without inventing scenery beyond it.
 * Metre marks on the walking face give a body-scale size cue and origin orientation.
 */
export function authoredGroundGeometry(support: AuthoredGroundSupport): AuthoredGroundGeometry {
  const { halfWidth, halfDepth, elevation } = support;
  if (
    !Number.isFinite(halfWidth) || halfWidth <= 0 ||
    !Number.isFinite(halfDepth) || halfDepth <= 0 ||
    !Number.isFinite(elevation)
  ) throw new Error('authored ground support must have finite positive extents and elevation');

  const rimWidth = authoredRimWidth(halfWidth, halfDepth);
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
    scaleCue: authoredGroundScaleCue(support, rimWidth),
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

type AuthoredGroundMaterialKind = 'surface' | 'boundary' | 'scaleCue';

interface AuthoredGroundMaterial {
  readonly material: pc.StandardMaterial;
  applyProfile(profile: WorldArtProfile): void;
}

/**
 * Lit walking face and rim, or unlit metre marks.
 *
 * The surface stays lit and shadow-receiving so placed objects separate from the floor. The rim
 * takes the silhouette tone so the finite support reads against both sky clear-colour and the
 * walking face. Scale marks stay unlit from the ink tone so metre spacing remains countable under
 * any sun angle.
 */
function authoredGroundMaterial(
  profile: WorldArtProfile,
  kind: AuthoredGroundMaterialKind,
): AuthoredGroundMaterial {
  const material = new pc.StandardMaterial();
  material.useFog = true;
  material.metalness = 0;
  if (kind === 'scaleCue') {
    material.useLighting = false;
    material.gloss = 0;
    material.blendType = pc.BLEND_NORMAL;
    material.opacity = 0.88;
    material.depthWrite = false;
    material.depthBias = AUTHORED_MARK_DEPTH_OFFSET;
    material.slopeDepthBias = AUTHORED_MARK_DEPTH_OFFSET;
  } else {
    material.useLighting = true;
    // A slightly glossier walking face catches directional light; the rim stays matte so the
    // perimeter reads as structure rather than a second shine competing with objects.
    material.gloss = kind === 'boundary' ? 0.06 : 0.22;
    material.depthBias = AUTHORED_FACE_DEPTH_OFFSET;
    material.slopeDepthBias = AUTHORED_FACE_DEPTH_OFFSET;
  }
  const apply = (next: WorldArtProfile): void => {
    if (kind === 'scaleCue') {
      const [r, g, b] = unitRgb(worldSilhouetteTone(next.palette));
      material.diffuse.set(r, g, b);
      material.emissive.set(r, g, b);
      material.emissiveIntensity = 0.92;
    } else if (kind === 'boundary') {
      const [r, g, b] = unitRgb(worldSilhouetteTone(next.palette));
      material.diffuse.set(r, g, b);
      const [er, eg, eb] = unitRgb(next.palette.stoneShadow);
      material.emissive.set(er, eg, eb);
      material.emissiveIntensity = 0.03;
    } else {
      const [r, g, b] = unitRgb(next.palette.terrain);
      material.diffuse.set(r, g, b);
      // Keep emissive low so directional shadows from objects stay the dominant ground cue.
      const [er, eg, eb] = unitRgb(next.palette.terrainLift);
      material.emissive.set(er, eg, eb);
      material.emissiveIntensity = 0.018;
    }
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
  authoredSupport?: AuthoredGroundSupport | EndlessAuthoredGroundSupport,
): WorldField {
  /*
   * TWO QUESTIONS, ASKED SEPARATELY. "Is this an authored starter?" decides the walking face: its
   * lit, shadow-receiving material, where it sits, which uniforms exist, and what the map marks
   * are read against. "Does this ground have a rectangle?" decides only what draws a rectangle:
   * the rim, the fascia and the metre marks. Before a ground could be endless, both had the same
   * answer, so a single test for a support stood for both. An endless starter then took the
   * photo-world landscape shader, which never samples a shadow map, and nothing placed on it cast
   * a shadow: measured, forcing that path's receive flags changed no pixel at all.
   */
  const authoredStarter = authoredSupport !== undefined;
  const rectangle =
    authoredSupport === undefined || isEndlessAuthoredGroundSupport(authoredSupport)
      ? undefined
      : authoredSupport;
  const endless = authoredSupport !== undefined && isEndlessAuthoredGroundSupport(authoredSupport)
    ? authoredSupport
    : null;
  const authoredElevation = authoredSupport?.elevation ?? 0;
  const entity = new pc.Entity('atlas-world-field');
  const buffers = worldFieldBufferShape(world);
  // The navigable/recovery radii remain visible in the material, but the physical draw surface
  // extends beyond the far clip so its square edge can never masquerade as a platform boundary.
  // An endless face reaches exactly that far past the walk: at 4.8 times its recovery radius it
  // was one quad 78 km across, whose depth could not hold an object lying on it (see the depth
  // order above).
  const visualHalfExtent = endless !== null
    ? world.recoveryRadius + endless.reach
    : Math.max(2200, world.recoveryRadius * 4.8);
  // 220 segments is ~193k triangles for a surface whose relief, contours, regions and traces are
  // all computed per pixel. The mesh only has to carry the height field well enough that the
  // silhouette and the horizon read correctly, and 96 does that at a fifth of the geometry.
  const authoredGeometry = rectangle === undefined ? null : authoredGroundGeometry(rectangle);
  const mesh = authoredGeometry !== null
    ? createMesh(device, authoredGeometry.surface)
    : endless !== null
      ? createMesh(device, endlessAuthoredGroundSurface(authoredElevation, visualHalfExtent, endless.reach))
      : createLandscapeMesh(device, world, visualHalfExtent, 96);
  const material = new pc.ShaderMaterial({
    uniqueName: `exulanica-grounded-world-field:${buffers.regionCapacity}:${buffers.traceCapacity}`,
    attributes: { aPosition: pc.SEMANTIC_POSITION, aNormal: pc.SEMANTIC_NORMAL },
    vertexGLSL: VERTEX_GLSL,
    fragmentGLSL: fragmentGlsl(buffers.regionCapacity, buffers.traceCapacity),
  } as ShaderDesc);
  material.cull = pc.CULLFACE_NONE;
  material.depthWrite = true;
  material.blendType = pc.BLEND_NONE;
  const authoredMaterial = authoredStarter
    ? authoredGroundMaterial(initialProfile, 'surface')
    : null;
  const boundaryMesh = authoredGeometry === null
    ? null
    : createMesh(device, authoredGeometry.boundary);
  const boundaryMaterial = rectangle === undefined
    ? null
    : authoredGroundMaterial(initialProfile, 'boundary');
  const scaleCueMesh = authoredGeometry === null || authoredGeometry.scaleCue.indices.length === 0
    ? null
    : createMesh(device, authoredGeometry.scaleCue);
  const scaleCueMaterial = rectangle === undefined || scaleCueMesh === null
    ? null
    : authoredGroundMaterial(initialProfile, 'scaleCue');

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
    // Keyed on the walking face alone. Requiring the rim too would leave an endless ground, which
    // has none, on whatever appearance it was built with while the rest of the world moved on.
    if (authoredMaterial !== null) {
      authoredMaterial.applyProfile(profile);
      boundaryMaterial?.applyProfile(profile);
      scaleCueMaterial?.applyProfile(profile);
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

  const fieldCentre = authoredStarter
    ? { x: 0, z: 0 }
    : { x: world.centre.x, z: world.centre.z };
  // An authored walking face carries its elevation in its vertices and sits exactly where objects
  // are placed. The landscape's small drop keeps its contour field under anything drawn at zero.
  entity.setPosition(fieldCentre.x, authoredStarter ? 0 : -0.035, fieldCentre.z);
  const fieldInstance = new pc.MeshInstance(mesh, authoredMaterial?.material ?? material, entity);
  fieldInstance.castShadow = false;
  fieldInstance.receiveShadow = authoredStarter;
  const boundaryInstance = boundaryMesh === null || boundaryMaterial === null
    ? null
    : new pc.MeshInstance(boundaryMesh, boundaryMaterial.material, entity);
  if (boundaryInstance !== null) {
    boundaryInstance.castShadow = false;
    boundaryInstance.receiveShadow = true;
  }
  const scaleCueInstance = scaleCueMesh === null || scaleCueMaterial === null
    ? null
    : new pc.MeshInstance(scaleCueMesh, scaleCueMaterial.material, entity);
  if (scaleCueInstance !== null) {
    scaleCueInstance.castShadow = false;
    scaleCueInstance.receiveShadow = false;
  }
  const authoredInstances = [fieldInstance];
  if (boundaryInstance !== null) authoredInstances.push(boundaryInstance);
  if (scaleCueInstance !== null) authoredInstances.push(scaleCueInstance);
  entity.addComponent('render', {
    meshInstances: authoredInstances,
  });
  if (entity.render !== undefined && entity.render !== null) {
    entity.render.castShadows = false;
    entity.render.receiveShadows = authoredStarter;
  }
  // The render component's receiveShadows flag re-enables every instance; keep the scale marks
  // free of object shadows so metre spacing stays countable.
  if (scaleCueInstance !== null) scaleCueInstance.receiveShadow = false;

  const marker = new pc.Entity('atlas-map-user-marker');
  const markerGeometry = new pc.Geometry();
  markerGeometry.positions = [0, 0, -4.2, -2.1, 0, 0.8, 2.1, 0, 0.8];
  markerGeometry.indices = [0, 1, 2];
  const markerMesh = pc.Mesh.fromGeometry(device, markerGeometry);
  const markerMaterial = new pc.StandardMaterial();
  markerMaterial.useLighting = false;
  markerMaterial.cull = pc.CULLFACE_NONE;
  markerMaterial.emissiveIntensity = 1;
  // Map pose reads against the authored floor marks; keep it stronger than a decorative wash.
  markerMaterial.opacity = authoredStarter ? 0.55 : 0.24;
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

  // Placement confirm landing: a compact diamond + forward notch. Shape and accent colour keep it
  // apart from the Map triangle (`atlas-map-user-marker`), which uses the focus tone.
  const landing = new pc.Entity('atlas-placement-landing-marker');
  const landingGeometry = new pc.Geometry();
  landingGeometry.positions = [
    0, 0, -0.42, -0.28, 0, 0, 0, 0, 0.42, 0.28, 0, 0,
    0, 0, -0.58, -0.1, 0, -0.42, 0.1, 0, -0.42,
  ];
  landingGeometry.indices = [0, 1, 2, 0, 2, 3, 4, 5, 6];
  const landingMesh = pc.Mesh.fromGeometry(device, landingGeometry);
  const landingMaterial = new pc.StandardMaterial();
  landingMaterial.useLighting = false;
  landingMaterial.cull = pc.CULLFACE_NONE;
  landingMaterial.emissiveIntensity = 1;
  landingMaterial.opacity = authoredStarter ? 0.78 : 0.4;
  landingMaterial.blendType = pc.BLEND_NORMAL;
  landingMaterial.depthWrite = false;
  const setLandingTheme = (next: PresentationTheme): void => {
    const [r, g, b] = unitRgb(next.accent);
    landingMaterial.diffuse.set(r, g, b);
    landingMaterial.emissive.set(r, g, b);
    landingMaterial.update();
  };
  setLandingTheme(theme);
  landing.addComponent('render', {
    meshInstances: [new pc.MeshInstance(landingMesh, landingMaterial, landing)],
  });
  landing.enabled = false;
  entity.addChild(landing);

  return {
    entity,
    setTheme(next) {
      setMarkerTheme(next);
      setLandingTheme(next);
    },
    setProfile,
    setMapGroundPose(pose) {
      marker.enabled = pose !== null;
      if (!authoredStarter) material.setParameter('uMapMode', pose === null ? 0 : 1);
      if (pose === null) return;
      marker.setPosition(
        pose.position.x - fieldCentre.x,
        authoredElevation + 0.09,
        pose.position.z - fieldCentre.z,
      );
      marker.setEulerAngles(0, (pose.yaw * 180) / Math.PI, 0);
    },
    setPlacementLandingPose(pose) {
      landing.enabled = pose !== null;
      if (pose === null) return;
      landing.setPosition(
        pose.position.x - fieldCentre.x,
        authoredElevation + 0.05,
        pose.position.z - fieldCentre.z,
      );
      landing.setEulerAngles(0, (pose.yaw * 180) / Math.PI, 0);
    },
    setRenderOrigin(x, z) {
      if (!authoredStarter) {
        material.setParameter('uRenderOrigin', new Float32Array([x, z]));
      }
    },
    setReducedMotion(reduced) {
      reducedMotion = reduced;
    },
    update(nowMs) {
      if (!authoredStarter) {
        material.setParameter('uTime', worldMotionSeconds(nowMs, idleCycleMs, reducedMotion));
      }
    },
    destroy() {
      markerMesh.destroy();
      bodyMesh.destroy();
      landingMesh.destroy();
      mesh.destroy();
      boundaryMesh?.destroy();
      scaleCueMesh?.destroy();
      material.destroy();
      authoredMaterial?.material.destroy();
      boundaryMaterial?.material.destroy();
      scaleCueMaterial?.material.destroy();
      markerMaterial.destroy();
      bodyMaterial.destroy();
      landingMaterial.destroy();
    },
  };
}
