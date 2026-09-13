import * as pc from 'playcanvas';

export type SemanticPoint = readonly [number, number];
export type SemanticRing = readonly SemanticPoint[];
export type SemanticFootprint = readonly (readonly SemanticRing[])[];

export interface NYCSemanticFeature {
  readonly id: string;
  readonly providerFeatureId: string;
  readonly bbox: readonly [number, number, number, number];
  readonly footprint: SemanticFootprint;
  readonly renderBatchId: number;
  readonly name: string | null;
  readonly bin: string | null;
}

export interface NYCLocalFeature extends NYCSemanticFeature {
  readonly localFootprint: SemanticFootprint;
}

export interface GeographicLocalFrame {
  readonly longitude: number;
  readonly latitude: number;
  readonly altitude: number;
}

const WGS84_A = 6_378_137;
const WGS84_E2 = 6.6943799901413165e-3;

function ecef(longitude: number, latitude: number, altitude: number): readonly [number, number, number] {
  const lon = longitude * Math.PI / 180;
  const lat = latitude * Math.PI / 180;
  const sinLat = Math.sin(lat);
  const radius = WGS84_A / Math.sqrt(1 - WGS84_E2 * sinLat * sinLat);
  return [
    (radius + altitude) * Math.cos(lat) * Math.cos(lon),
    (radius + altitude) * Math.cos(lat) * Math.sin(lon),
    (radius * (1 - WGS84_E2) + altitude) * sinLat,
  ];
}

/** Convert independently sourced CRS84 integers into east/up/south local metres. */
export function crs84IntegerToLocal(
  longitude: number,
  latitude: number,
  coordinateScale: number,
  frame: GeographicLocalFrame,
): readonly [number, number] {
  if (![longitude, latitude, coordinateScale, frame.longitude, frame.latitude, frame.altitude]
    .every(Number.isFinite) || !Number.isSafeInteger(longitude) ||
    !Number.isSafeInteger(latitude) || !Number.isSafeInteger(coordinateScale) ||
    coordinateScale <= 0) {
    throw new RangeError('Invalid CRS84 semantic coordinate');
  }
  const origin = ecef(frame.longitude, frame.latitude, frame.altitude);
  const point = ecef(longitude / coordinateScale, latitude / coordinateScale, 0);
  const lon = frame.longitude * Math.PI / 180;
  const lat = frame.latitude * Math.PI / 180;
  const delta = [point[0] - origin[0], point[1] - origin[1], point[2] - origin[2]];
  const east = -Math.sin(lon) * delta[0]! + Math.cos(lon) * delta[1]!;
  const up = Math.cos(lat) * Math.cos(lon) * delta[0]!
    + Math.cos(lat) * Math.sin(lon) * delta[1]! + Math.sin(lat) * delta[2]!;
  const south = Math.sin(lat) * Math.cos(lon) * delta[0]!
    + Math.sin(lat) * Math.sin(lon) * delta[1]! - Math.cos(lat) * delta[2]!;
  if (![east, up, south].every(Number.isFinite)) throw new RangeError('Invalid local coordinate');
  return [east, south];
}

export function localizeNYCFeatures(
  features: readonly NYCSemanticFeature[],
  coordinateScale: number,
  frame: GeographicLocalFrame,
): readonly NYCLocalFeature[] {
  return Object.freeze(features.map((feature) => Object.freeze({
    ...feature,
    localFootprint: Object.freeze(feature.footprint.map((polygon) =>
      Object.freeze(polygon.map((ring) => Object.freeze(ring.map((point) =>
        crs84IntegerToLocal(point[0], point[1], coordinateScale, frame))))))),
  })));
}

function inRing(point: SemanticPoint, ring: SemanticRing): boolean {
  let inside = false;
  for (let index = 0, prior = ring.length - 1; index < ring.length; prior = index++) {
    const a = ring[index]!;
    const b = ring[prior]!;
    if (((a[1] > point[1]) !== (b[1] > point[1])) &&
      point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

export function featureAtLocalPoint(
  features: readonly NYCLocalFeature[],
  point: SemanticPoint,
): NYCLocalFeature | null {
  for (const feature of features) {
    for (const polygon of feature.localFootprint) {
      if (polygon[0] !== undefined && inRing(point, polygon[0]) &&
        polygon.slice(1).every((hole) => !inRing(point, hole))) return feature;
    }
  }
  return null;
}

export function featureAlongReticle(
  features: readonly NYCLocalFeature[],
  origin: readonly [number, number, number],
  direction: readonly [number, number, number],
  planeY = 0.35,
): NYCLocalFeature | null {
  if (Math.abs(direction[1]) < 1e-8) return null;
  const distance = (planeY - origin[1]) / direction[1];
  if (distance <= 0) return null;
  const point: SemanticPoint = [
    origin[0] + direction[0] * distance,
    origin[2] + direction[2] * distance,
  ];
  return featureAtLocalPoint(features, point) ?? nearestFeature(features, point, 14);
}

function nearestFeature(
  features: readonly NYCLocalFeature[],
  point: SemanticPoint,
  maximumDistance: number,
): NYCLocalFeature | null {
  let nearest: { readonly feature: NYCLocalFeature; readonly distance: number } | null = null;
  for (const feature of features) {
    for (const polygon of feature.localFootprint) {
      for (const ring of polygon) {
        for (let index = 1; index < ring.length; index++) {
          const distance = pointToSegmentDistance(point, ring[index - 1]!, ring[index]!);
          if (distance <= maximumDistance && (nearest === null || distance < nearest.distance)) {
            nearest = { feature, distance };
          }
        }
      }
    }
  }
  return nearest?.feature ?? null;
}

function pointToSegmentDistance(point: SemanticPoint, a: SemanticPoint, b: SemanticPoint): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) return Math.hypot(point[0] - a[0], point[1] - a[1]);
  const t = Math.max(0, Math.min(1, (
    (point[0] - a[0]) * dx + (point[1] - a[1]) * dy
  ) / lengthSquared));
  return Math.hypot(point[0] - (a[0] + t * dx), point[1] - (a[1] + t * dy));
}

export interface FootprintLineGeometry {
  readonly primitive: 'lines';
  readonly positions: readonly number[];
  readonly indices: readonly number[];
}

/** Build explicit closed line edges for every exterior and interior ring, with no fill topology. */
export function footprintLineGeometry(
  footprint: SemanticFootprint,
  y = 0.35,
): FootprintLineGeometry {
  if (!Number.isFinite(y)) throw new RangeError('Invalid semantic outline height');
  const positions: number[] = [];
  const indices: number[] = [];
  for (const polygon of footprint) {
    for (const ring of polygon) {
      if (ring.length < 4 ||
        ring[0]![0] !== ring.at(-1)![0] ||
        ring[0]![1] !== ring.at(-1)![1]) {
        throw new Error('Semantic outline ring must be explicitly closed');
      }
      const first = positions.length / 3;
      const vertexCount = ring.length - 1;
      for (const point of ring.slice(0, -1)) positions.push(point[0], y, point[1]);
      for (let index = 0; index < vertexCount; index++) {
        indices.push(first + index, first + ((index + 1) % vertexCount));
      }
    }
  }
  return Object.freeze({
    primitive: 'lines' as const,
    positions: Object.freeze(positions),
    indices: Object.freeze(indices),
  });
}

/** Renderer for neutral footprint-only proxies. It owns no provider tile handle. */
export class NYCSemanticOverlay {
  readonly root = new pc.Entity('nyc-open-data-semantic-overlay');
  readonly features: readonly NYCLocalFeature[];
  private readonly material = new pc.StandardMaterial();
  private readonly meshes: pc.Mesh[] = [];
  private destroyed = false;

  constructor(
    device: pc.GraphicsDevice,
    parent: pc.Entity,
    features: readonly NYCLocalFeature[],
  ) {
    this.features = features;
    this.material.useLighting = false;
    this.material.emissive = new pc.Color(0.02, 0.62, 0.54);
    this.material.emissiveIntensity = 0.7;
    this.material.opacity = 0.65;
    this.material.blendType = pc.BLEND_NORMAL;
    this.material.depthWrite = false;
    this.material.depthTest = true;
    this.material.cull = pc.CULLFACE_NONE;
    this.material.update();
    const positions: number[] = [];
    const indices: number[] = [];
    for (const feature of features) {
      const geometry = footprintLineGeometry(feature.localFootprint);
      if (geometry.indices.length === 0) continue;
      const vertexOffset = positions.length / 3;
      positions.push(...geometry.positions);
      indices.push(...geometry.indices.map((index) => index + vertexOffset));
    }
    if (indices.length > 0) {
      const mesh = new pc.Mesh(device);
      mesh.setPositions(positions);
      mesh.setIndices(indices);
      mesh.update(pc.PRIMITIVE_LINES);
      this.meshes.push(mesh);
      this.root.addComponent('render', {
        meshInstances: [new pc.MeshInstance(mesh, this.material, this.root)],
      });
    }
    parent.addChild(this.root);
  }

  pick(origin: readonly [number, number, number], direction: readonly [number, number, number]):
    NYCLocalFeature | null {
    return featureAlongReticle(this.features, origin, direction);
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.root.destroy();
    for (const mesh of this.meshes) mesh.destroy();
    this.meshes.length = 0;
    this.material.destroy();
  }
}
