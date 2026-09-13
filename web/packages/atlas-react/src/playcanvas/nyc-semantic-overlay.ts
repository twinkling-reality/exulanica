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
  planeY = 0.08,
): NYCLocalFeature | null {
  if (Math.abs(direction[1]) < 1e-8) return null;
  const distance = (planeY - origin[1]) / direction[1];
  if (distance <= 0) return null;
  return featureAtLocalPoint(features, [
    origin[0] + direction[0] * distance,
    origin[2] + direction[2] * distance,
  ]);
}

/** Renderer for neutral footprint-only proxies. It owns no provider tile handle. */
export class NYCSemanticOverlay {
  readonly root = new pc.Entity('nyc-open-data-semantic-overlay');
  readonly features: readonly NYCLocalFeature[];
  private readonly material = new pc.StandardMaterial();

  constructor(
    device: pc.GraphicsDevice,
    parent: pc.Entity,
    features: readonly NYCLocalFeature[],
  ) {
    this.features = features;
    this.material.useLighting = false;
    this.material.emissive = new pc.Color(0.1, 0.82, 0.78);
    this.material.emissiveIntensity = 1;
    this.material.opacity = 0.42;
    this.material.blendType = pc.BLEND_NORMAL;
    this.material.depthWrite = false;
    this.material.cull = pc.CULLFACE_NONE;
    this.material.update();
    for (const feature of features) {
      for (const polygon of feature.localFootprint) {
        const ring = polygon[0];
        if (ring === undefined || ring.length < 4) continue;
        const geometry = new pc.Geometry();
        geometry.positions = ring.slice(0, -1).flatMap((point) => [point[0], 0.08, point[1]]);
        geometry.indices = Array.from({ length: ring.length - 3 }, (_, index) =>
          [0, index + 1, index + 2]).flat();
        const entity = new pc.Entity(`nyc-open-data:${feature.id}`);
        const mesh = pc.Mesh.fromGeometry(device, geometry);
        entity.addComponent('render', {
          meshInstances: [new pc.MeshInstance(mesh, this.material, entity)],
        });
        this.root.addChild(entity);
      }
    }
    parent.addChild(this.root);
  }

  pick(origin: readonly [number, number, number], direction: readonly [number, number, number]):
    NYCLocalFeature | null {
    return featureAlongReticle(this.features, origin, direction);
  }

  destroy(): void {
    this.root.destroy();
    this.material.destroy();
  }
}
