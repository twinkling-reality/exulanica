import { atlasVec3 } from './coords.js';
import type { NavigationWorld, PolygonObstacle } from './navigation.js';

export interface OwnedDistrictBuilding {
  readonly id: string;
  readonly bin: string | null;
  readonly name: string | null;
  readonly construction_year: string | null;
  readonly height_cm: number;
  readonly material: number;
  readonly render_batch_id: number;
  readonly bbox_cm: readonly [number, number, number, number];
  readonly polygons: readonly (readonly (readonly (readonly [number, number])[])[])[];
}

export interface OwnedDistrictSidewalk {
  readonly id: string;
  readonly status: string | null;
  readonly bbox_cm: readonly [number, number, number, number];
  readonly polygons: readonly (readonly (readonly (readonly [number, number])[])[])[];
}

export interface OwnedDistrictMaterial {
  readonly name: string;
  readonly base: string;
  readonly roughness_milli: number;
  readonly metalness_milli: number;
}

export interface OwnedDistrict {
  readonly profile: 'exulanica.owned-district/v1';
  readonly district_id: string;
  readonly name: string;
  readonly seed: number;
  readonly bounds_cm: readonly [number, number, number, number];
  readonly materials: readonly OwnedDistrictMaterial[];
  readonly buildings: readonly OwnedDistrictBuilding[];
  readonly sidewalks: readonly OwnedDistrictSidewalk[];
  readonly frame?: {
    readonly name: string;
    readonly origin_crs84_e7: readonly [number, number];
    readonly axis_order: readonly ['east', 'south'];
    readonly horizontal_unit: 'centimetre';
    readonly coordinate_scale: 100;
    readonly altitude_reference: 'authored-flat-ground';
  };
  readonly source_records: readonly {
    readonly dataset_id: string;
    readonly provider_revision: string;
    readonly sha256: string;
    readonly attribution: string;
    readonly source_url?: string;
    readonly operation_rights: Readonly<Record<string, boolean>>;
  }[];
}

const isIntegerTuple = (value: unknown, length: number): value is readonly number[] =>
  Array.isArray(value) && value.length === length &&
  value.every((entry) => Number.isSafeInteger(entry));

/** Fail closed before any source-derived record reaches rendering or collision. */
export function parseOwnedDistrict(value: unknown): OwnedDistrict {
  if (value === null || typeof value !== 'object') throw new Error('Owned district is not an object');
  const district = value as Partial<OwnedDistrict>;
  if (
    district.profile !== 'exulanica.owned-district/v1' ||
    typeof district.district_id !== 'string' ||
    typeof district.name !== 'string' ||
    !Number.isSafeInteger(district.seed) ||
    !isIntegerTuple(district.bounds_cm, 4) ||
    !Array.isArray(district.materials) ||
    !Array.isArray(district.buildings) ||
    !Array.isArray(district.sidewalks) ||
    !Array.isArray(district.source_records)
  ) throw new Error('Owned district contract is incomplete');
  for (const source of district.source_records) {
    if (
      typeof source.dataset_id !== 'string' ||
      typeof source.provider_revision !== 'string' ||
      !/^[0-9a-f]{64}$/.test(source.sha256) ||
      typeof source.attribution !== 'string' ||
      source.operation_rights?.display !== true ||
      source.operation_rights?.persist !== true ||
      source.operation_rights?.modify !== true
    ) throw new Error('Owned district source record is not admitted for this runtime');
  }
  if (district.bounds_cm[0] >= district.bounds_cm[2] || district.bounds_cm[1] >= district.bounds_cm[3]) throw new Error('Invalid district bounds');
  if (district.frame !== undefined && (
    district.frame === null || !isIntegerTuple(district.frame.origin_crs84_e7, 2) ||
    JSON.stringify(district.frame.axis_order) !== '["east","south"]' ||
    district.frame.horizontal_unit !== 'centimetre' || district.frame.coordinate_scale !== 100 ||
    district.frame.altitude_reference !== 'authored-flat-ground'
  )) throw new Error('Invalid district frame');
  const ids = new Set<string>();
  for (const feature of [...district.buildings, ...district.sidewalks]) {
    if (!feature || typeof feature.id !== 'string' || ids.has(feature.id) ||
        !isIntegerTuple(feature.bbox_cm, 4) || !Array.isArray(feature.polygons) || !feature.polygons.length) throw new Error('Invalid district feature');
    ids.add(feature.id);
    const points: number[][] = [];
    for (const polygon of feature.polygons) {
      if (!Array.isArray(polygon) || !polygon.length) throw new Error('Invalid district polygon');
      for (const ring of polygon) {
        if (!Array.isArray(ring) || ring.length < 4 || JSON.stringify(ring[0]) !== JSON.stringify(ring[ring.length - 1])) throw new Error('Invalid district ring');
        for (const point of ring) {
          if (!isIntegerTuple(point, 2) || point.some(v => Math.abs(v) > 100_000_000)) throw new Error('Invalid district coordinate');
          points.push([...point]);
        }
      }
    }
    const box = [Math.min(...points.map(p => p[0]!)), Math.min(...points.map(p => p[1]!)), Math.max(...points.map(p => p[0]!)), Math.max(...points.map(p => p[1]!))];
    if (JSON.stringify(box) !== JSON.stringify(feature.bbox_cm)) throw new Error('Invalid district bounding box');
  }
  for (const building of district.buildings) {
    if (
      typeof building.id !== 'string' ||
      !building.id.startsWith('doitt_id:') ||
      !Number.isSafeInteger(building.height_cm) ||
      !Number.isSafeInteger(building.render_batch_id) ||
      building.height_cm < 0 ||
      !isIntegerTuple(building.bbox_cm, 4) ||
      !Array.isArray(building.polygons)
    ) throw new Error('Owned district building is invalid');
  }
  return Object.freeze(district as OwnedDistrict);
}

export function ownedDistrictNavigation(district: OwnedDistrict): NavigationWorld {
  const [west, north, east, south] = district.bounds_cm.map((value) => value / 100) as [
    number, number, number, number,
  ];
  const centre = atlasVec3((west + east) / 2, 0, (north + south) / 2);
  const polygonObstacles: PolygonObstacle[] = district.buildings.map((building) => ({
    id: building.id,
    rings: building.polygons.map((polygon) =>
      polygon[0]!.map(([x, z]) => atlasVec3(x / 100, 0, z / 100))),
  }));
  const surface = {
    sample: (x: number, z: number) =>
      x < west || x > east || z < north || z > south
        ? null
        : Object.freeze({ height: 0, normal: Object.freeze({ x: 0, y: 1, z: 0 }) }),
  };
  return Object.freeze({
    surface,
    eyeHeight: 1.62,
    cameraRadius: 0.34,
    centre,
    fieldRadius: Math.hypot(east - west, south - north) / 2,
    recoveryRadius: Math.hypot(east - west, south - north) / 2 + 2,
    maximumSlopeDegrees: 12,
    maximumStepHeight: 0.18,
    surfaceSampleSpacing: 0.25,
    regions: Object.freeze([]),
    obstacles: Object.freeze([]),
    polygonObstacles: Object.freeze(polygonObstacles),
    traces: Object.freeze([]),
  });
}
