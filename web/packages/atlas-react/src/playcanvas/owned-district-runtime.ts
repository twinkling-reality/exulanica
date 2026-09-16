import type { NativeCharacterFrame } from './native-character-runtime.js';
import type {
  OwnedDistrict,
  DistrictInterpretation,
  DistrictSubject,
  DistrictRecipe,
  OwnedDistrictBuilding,
  OwnedDistrictMaterial,
} from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import { buildingRayDistance, pointInRing, ringArea, surfaceTriangles } from './district-surfaces.js';
import { sampleMotionPath } from './society-presentation.js';
import { PlayerAvatar } from './player-avatar.js';
import { abstractCharacter, syntheticCharacterStyle } from './character-shape.js';

export interface OwnedDistrictMetrics {
  readonly logicalBuildings: number;
  readonly logicalSidewalks: number;
  readonly drawCalls: number;
  readonly residentBytes: number;
  readonly visibleTiles: number;
}

export interface OwnedAuthoredEnvironmentInstance {
  readonly instanceId: string;
  /** Supplied only after pinned source and destination-frame resolution by composition. */
  readonly providerFeatureId?: string;
  readonly coordinateFrame?: 'flatiron-local-mm';
  readonly transform: {
    readonly xMm: number;
    readonly yMm: number;
    readonly zMm: number;
    readonly yawMicroradians: number;
    readonly scaleMilli: number;
  };
  readonly origin: { readonly role: string };
  readonly removed: boolean;
  readonly availability: string;
}

export interface OwnedSocietyState {
  readonly profile?: 'exulanica-society/v1' | 'exulanica-society/v2';
  readonly society_id?: string;
  readonly branch_id?: string;
  readonly input_seq?: number;
  readonly input_sha256?: string;
  readonly tick: number;
  readonly inhabitants: readonly {
    readonly id: string;
    readonly synthetic: true;
    readonly display_name?: string;
    readonly role?: string;
    readonly position_mm: readonly [number, number];
    readonly goal?: null | { readonly kind: 'visit' | 'rest'; readonly target_id: string; readonly reason: string };
    readonly action?: { readonly kind: 'idle' | 'move' | 'visit' | 'rest'; readonly status: 'active' | 'completed' | 'blocked'; readonly target_id: string | null; readonly remaining_ticks: number; readonly reason: string };
    readonly route?: null | { readonly node_ids: readonly string[]; readonly edge_index: number; readonly edge_progress_mm: number; readonly destination_node_id: string; readonly input_sha256: string };
    readonly motion_path_mm?: readonly (readonly [number, number])[];
    readonly explanation?: { readonly summary: string; readonly event_ids: readonly string[] };
  }[];
}

interface Batch {
  readonly positions: number[];
  readonly normals: number[];
  readonly indices: number[];
}

interface SocietyAnimation {
  readonly startedAtMs: number;
  readonly durationMs: number;
  readonly inhabitants: readonly {
    readonly id: string;
    readonly role: string;
    readonly ordinal: number;
    readonly from: readonly [number, number];
    readonly to: readonly [number, number];
    readonly path: readonly (readonly [number, number])[];
  }[];
}

const batch = (): Batch => ({ positions: [], normals: [], indices: [] });

function color(hex: string): pc.Color {
  const value = Number.parseInt(hex.slice(1), 16);
  return new pc.Color(
    ((value >> 16) & 255) / 255,
    ((value >> 8) & 255) / 255,
    (value & 255) / 255,
  );
}

function material(source: OwnedDistrictMaterial): pc.StandardMaterial {
  const result = new pc.StandardMaterial();
  const base = color(source.base);
  result.diffuse = new pc.Color(base.r*.60+.29,base.g*.60+.29,base.b*.60+.29);
  result.emissive = new pc.Color(base.r * 0.14, base.g * 0.14, base.b * 0.14);
  result.emissiveIntensity = 0.8;
  result.metalness = source.metalness_milli / 1000;
  result.gloss = 1 - source.roughness_milli / 1000;
  result.useMetalness = true;
  result.useSkybox = false;
  result.cull = pc.CULLFACE_BACK;
  result.update();
  return result;
}

function quad(
  target: Batch,
  a: readonly [number, number, number],
  b: readonly [number, number, number],
  c: readonly [number, number, number],
  d: readonly [number, number, number],
  normal: readonly [number, number, number],
): void {
  const first = target.positions.length / 3;
  target.positions.push(...a, ...b, ...c, ...d);
  for (let index = 0; index < 4; index += 1) target.normals.push(...normal);
  target.indices.push(first, first + 1, first + 2, first, first + 2, first + 3);
}

function addBox(
  target: Batch,
  centre: readonly [number, number, number],
  half: readonly [number, number, number],
): void {
  const [x, y, z] = centre;
  const [hx, hy, hz] = half;
  const l = x - hx;
  const r = x + hx;
  const b = y - hy;
  const t = y + hy;
  const n = z - hz;
  const f = z + hz;
  quad(target, [l, b, f], [r, b, f], [r, t, f], [l, t, f], [0, 0, 1]);
  quad(target, [r, b, n], [l, b, n], [l, t, n], [r, t, n], [0, 0, -1]);
  quad(target, [r, b, f], [r, b, n], [r, t, n], [r, t, f], [1, 0, 0]);
  quad(target, [l, b, n], [l, b, f], [l, t, f], [l, t, n], [-1, 0, 0]);
  quad(target, [l, t, f], [r, t, f], [r, t, n], [l, t, n], [0, 1, 0]);
  quad(target, [l, b, n], [r, b, n], [r, b, f], [l, b, f], [0, -1, 0]);
}

function addOctahedron(
  target: Batch,
  centre: readonly [number, number, number],
  radius: number,
): void {
  const [x, y, z] = centre;
  const points = [
    [x, y + radius, z],
    [x + radius, y, z],
    [x, y, z + radius],
    [x - radius, y, z],
    [x, y, z - radius],
    [x, y - radius, z],
  ] as const;
  const faces = [
    [0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1],
    [5, 2, 1], [5, 3, 2], [5, 4, 3], [5, 1, 4],
  ] as const;
  for (const face of faces) {
    const base = target.positions.length / 3;
    const a = points[face[0]];
    const b = points[face[1]];
    const c = points[face[2]];
    target.positions.push(...a, ...b, ...c);
    const ax = b[0] - a[0];
    const ay = b[1] - a[1];
    const az = b[2] - a[2];
    const bx = c[0] - a[0];
    const by = c[1] - a[1];
    const bz = c[2] - a[2];
    const nx = ay * bz - az * by;
    const ny = az * bx - ax * bz;
    const nz = ax * by - ay * bx;
    const length = Math.max(1e-6, Math.hypot(nx, ny, nz));
    for (let index = 0; index < 3; index += 1) {
      target.normals.push(nx / length, ny / length, nz / length);
    }
    target.indices.push(base, base + 1, base + 2);
  }
}

function addBuilding(
  target: Batch,
  building: OwnedDistrictBuilding,
  includeRoof = true,
): void {
  const height = building.height_cm / 100;
  for (const polygon of building.polygons) {
    polygon.forEach((sourceRing, ringIndex) => {
      // Consistent outward faces regardless of provider winding, including holes.
      const wantPositive = ringIndex === 0;
      const ring = (ringArea(sourceRing) > 0) === wantPositive ? sourceRing : [...sourceRing].reverse();
      for (let index = 1; index < ring.length; index++) {
        const [ax, az] = ring[index - 1]!, [bx, bz] = ring[index]!;
        const dx = (bx - ax) / 100, dz = (bz - az) / 100;
        const length = Math.hypot(dx, dz);
        if (length < 1e-8) continue;
        quad(target, [bx / 100, 0, bz / 100], [ax / 100, 0, az / 100],
          [ax / 100, height, az / 100], [bx / 100, height, bz / 100],
          [dz / length, 0, -dx / length]);
      }
    });
  }
  if (includeRoof) addFlatPolygon(target, building.polygons, height);
}

function addRoof(target: Batch, building: OwnedDistrictBuilding): void {
  const height = building.height_cm / 100 + 0.008;
  addFlatPolygon(target, building.polygons, height);
}

function addWindows(target: Batch, building: OwnedDistrictBuilding, recipe?: Extract<DistrictRecipe, { kind: 'facade-grid' }>): void {
  if (!recipe && building.name === null && building.render_batch_id % 9 !== 0) return;
  const height = building.height_cm / 100;
  for (const polygon of building.polygons) {
    const ring = polygon[0];
    if (ring === undefined) continue;
    for (let edge = 1; edge < ring.length; edge += 1) {
      const [ax, az] = ring[edge - 1]!.map((value) => value / 100) as [number, number];
      const [bx, bz] = ring[edge]!.map((value) => value / 100) as [number, number];
      const dx = bx - ax;
      const dz = bz - az;
      const length = Math.hypot(dx, dz);
      const columns = Math.floor(length / ((recipe?.bay_width_mm ?? 5500) / 1000));
      if (columns < 1) continue;
      const nx = -dz / length;
      const nz = dx / length;
      const floor = (recipe?.floor_height_mm ?? 4200) / 1000;
      const sill = (recipe?.sill_height_mm ?? 2700) / 1000;
      const windowHeight = (recipe?.window_height_mm ?? 1450) / 1000;
      const levels = Math.max(0, Math.floor((height - sill - windowHeight) / floor) + 1);
      for (let level = 0; level < levels; level += 1) {
        for (let column = 0; column < columns; column += 1) {
          const centre = (column + 0.5) / columns;
          const half = Math.min((recipe?.window_width_mm ?? 1240) / 2000 / length, 0.4 / columns);
          const y = sill + level * floor;
          // NYC rings are retained with provider winding; this offset follows their exterior.
          const front = (ringArea(ring) > 0 ? -1 : 1) * (recipe?.recess_mm ?? 55) / 1000;
          quad(
            target,
            [ax + dx * (centre - half) + nx * front, y, az + dz * (centre - half) + nz * front],
            [ax + dx * (centre + half) + nx * front, y, az + dz * (centre + half) + nz * front],
            [ax + dx * (centre + half) + nx * front, y + windowHeight, az + dz * (centre + half) + nz * front],
            [ax + dx * (centre - half) + nx * front, y + windowHeight, az + dz * (centre - half) + nz * front],
            [nx, 0, nz],
          );
        }
      }
    }
  }
}

function addFacadeBands(target: Batch, building: OwnedDistrictBuilding): void {
  if (building.render_batch_id % 3 !== 0 && building.name === null) return;
  const height = building.height_cm / 100;
  for (const polygon of building.polygons) {
    const ring = polygon[0];
    if (ring === undefined) continue;
    for (let edge = 1; edge < ring.length; edge += 1) {
      const [ax, az] = ring[edge - 1]!.map((value) => value / 100) as [number, number];
      const [bx, bz] = ring[edge]!.map((value) => value / 100) as [number, number];
      const dx = bx - ax;
      const dz = bz - az;
      const length = Math.max(Math.hypot(dx, dz), 1e-6);
      const nx = -dz / length;
      const nz = dx / length;
      const offset = -0.08;
      for (const y of [0.5, Math.max(1.2, height - 0.7)]) {
        quad(
          target,
          [ax + nx * offset, y, az + nz * offset],
          [bx + nx * offset, y, bz + nz * offset],
          [bx + nx * offset, y + 0.22, bz + nz * offset],
          [ax + nx * offset, y + 0.22, az + nz * offset],
          [nx, 0, nz],
        );
      }
    }
  }
}

function addArchitecturalDetails(target: Batch, building: OwnedDistrictBuilding): void {
  const [west, north, east, south] = building.bbox_cm.map((value) => value / 100) as [
    number, number, number, number,
  ];
  const height = building.height_cm / 100;
  const width = east - west;
  const depth = south - north;
  if (height > 24 && building.render_batch_id % 2 === 0) {
    addBox(
      target,
      [(west + east) / 2, height + 0.9, (north + south) / 2],
      [Math.min(3.2, width * 0.18), 0.9, Math.min(2.8, depth * 0.18)],
    );
  }
  if (building.name === null) return;
  const ring = building.polygons[0]?.[0];
  if (ring === undefined || ring.length < 2) return;
  const [ax, az] = ring[0]!.map((value) => value / 100) as [number, number];
  const [bx, bz] = ring[1]!.map((value) => value / 100) as [number, number];
  const dx = bx - ax;
  const dz = bz - az;
  const length = Math.max(Math.hypot(dx, dz), 1e-6);
  const cx = (ax + bx) / 2;
  const cz = (az + bz) / 2;
  const tx = dx / length;
  const tz = dz / length;
  const nx = -tz;
  const nz = tx;
  const halfWidth = Math.min(1.3, length * 0.18);
  const offset = -0.1;
  quad(
    target,
    [cx - tx * halfWidth + nx * offset, 0.02, cz - tz * halfWidth + nz * offset],
    [cx + tx * halfWidth + nx * offset, 0.02, cz + tz * halfWidth + nz * offset],
    [cx + tx * halfWidth + nx * offset, 2.8, cz + tz * halfWidth + nz * offset],
    [cx - tx * halfWidth + nx * offset, 2.8, cz - tz * halfWidth + nz * offset],
    [nx, 0, nz],
  );
}

function sidewalkCentre(
  sidewalk: OwnedDistrict['sidewalks'][number],
): readonly [number, number] | null {
  const points = sidewalk.polygons[0]?.[0]?.slice(0, -1);
  if (points === undefined || points.length === 0) return null;
  let x = 0;
  let z = 0;
  for (const point of points) {
    x += point[0] / 100;
    z += point[1] / 100;
  }
  return [x / points.length, z / points.length];
}

function addFlatPolygon(
  target: Batch,
  polygons: OwnedDistrictBuilding['polygons'],
  height: number,
): void {
  for (const polygon of polygons) {
    for (const triangle of surfaceTriangles(polygon)) {
      const first = target.positions.length / 3;
      for (const [x, z] of triangle) {
        target.positions.push(x / 100, height, z / 100);
        target.normals.push(0, 1, 0);
      }
      target.indices.push(first, first + 1, first + 2);
    }
  }
}

function mesh(device: pc.GraphicsDevice, source: Batch): pc.Mesh | null {
  if (source.indices.length === 0) return null;
  const result = new pc.Mesh(device);
  result.setPositions(source.positions);
  result.setNormals(source.normals);
  result.setIndices(source.indices);
  result.update(pc.PRIMITIVE_TRIANGLES);
  return result;
}

function rayBox(
  origin: readonly [number, number, number],
  direction: readonly [number, number, number],
  minimum: readonly [number, number, number],
  maximum: readonly [number, number, number],
): number | null {
  let near = 0;
  let far = Number.POSITIVE_INFINITY;
  for (let axis = 0; axis < 3; axis += 1) {
    if (Math.abs(direction[axis]!) < 1e-9) {
      if (origin[axis]! < minimum[axis]! || origin[axis]! > maximum[axis]!) return null;
      continue;
    }
    const first = (minimum[axis]! - origin[axis]!) / direction[axis]!;
    const second = (maximum[axis]! - origin[axis]!) / direction[axis]!;
    near = Math.max(near, Math.min(first, second));
    far = Math.min(far, Math.max(first, second));
    if (near > far) return null;
  }
  return far >= 0 ? near : null;
}

function addGround(
  device: pc.GraphicsDevice,
  parent: pc.Entity,
  materialValue: pc.Material,
  boundsCm: readonly [number, number, number, number],
): pc.Mesh {
  const [west, north, east, south] = boundsCm.map((value) => value / 100) as [
    number, number, number, number,
  ];
  const source = batch();
  quad(
    source,
    [west, 0, north],
    [west, 0, south],
    [east, 0, south],
    [east, 0, north],
    [0, 1, 0],
  );
  const geometry = mesh(device, source);
  if (geometry === null) throw new Error('Owned district ground bounds produced no geometry');
  const ground = new pc.Entity('owned-district-visible-support');
  ground.addComponent('render', {
    meshInstances: [new pc.MeshInstance(geometry, materialValue, ground)],
    castShadows: false,
    receiveShadows: true,
  });
  parent.addChild(ground);
  return geometry;
}

/** PlayCanvas representation only. The document remains the world authority. */
export class OwnedDistrictRuntime {
  readonly root = new pc.Entity('owned-district');
  readonly authoredRoot = new pc.Entity('owned-district-authored-instances');
  readonly societyRoot = new pc.Entity('owned-district-society');
  readonly metrics: OwnedDistrictMetrics;
  private readonly meshes: pc.Mesh[] = [];
  private readonly materials: pc.Material[] = [];
  private authoredMeshes: pc.Mesh[] = [];
  private authoredMaterials: pc.Material[] = [];
  private societyMeshes: pc.Mesh[] = [];
  private societyMaterials: pc.Material[] = [];
  private readonly societyCharacters = new Map<string, PlayerAvatar>();
  private lastSocietyFrameMs=0;
  private nativeSocietyDiscontinuity=true;
  private settleSocietyUntilMs=0;
  private promotedInhabitant:string|null=null;
  private readonly societyPositions = new Map<string, readonly [number, number]>();
  private latestSociety: OwnedSocietyState | null = null;
  private lastObserver: readonly [number, number] | null = null;
  private societyScope = '';
  private societyTick = -1;
  private societyAnimation: SocietyAnimation | null = null;
  private destroyed = false;

  constructor(
    private readonly device: pc.GraphicsDevice,
    parent: pc.Entity,
    readonly district: OwnedDistrict,
    sourceBytes: number,
    readonly interpretation?: DistrictInterpretation,
  ) {
    if (interpretation && interpretation.district_id !== district.district_id) throw new Error('District interpretation binding mismatch');
    parent.addChild(this.root);
    parent.addChild(this.authoredRoot);
    parent.addChild(this.societyRoot);
    const asphalt = new pc.StandardMaterial();
    asphalt.diffuse = new pc.Color(0.43, 0.465, 0.49);
    asphalt.emissive = new pc.Color(0.028, 0.032, 0.03);
    asphalt.emissiveIntensity = 0.32;
    asphalt.gloss = 0.12;
    asphalt.metalness = 0.04;
    asphalt.useMetalness = true;
    asphalt.update();
    this.materials.push(asphalt);
    this.meshes.push(addGround(device, this.root, asphalt, district.bounds_cm));

    const sidewalkBatch = batch();
    for (const sidewalk of district.sidewalks) {
      addFlatPolygon(sidewalkBatch, sidewalk.polygons, 0.025);
    }
    const sidewalkMesh = mesh(device, sidewalkBatch);
    if (sidewalkMesh !== null) {
      const sidewalkMaterial = new pc.StandardMaterial();
      sidewalkMaterial.diffuse = new pc.Color(0.76, 0.76, 0.71);
      sidewalkMaterial.emissive = new pc.Color(0.025, 0.023, 0.019);
      sidewalkMaterial.emissiveIntensity = 0.15;
      sidewalkMaterial.gloss = 0.1;
      sidewalkMaterial.update();
      const sidewalks = new pc.Entity('owned-sidewalks');
      sidewalks.addComponent('render', {
        meshInstances: [new pc.MeshInstance(sidewalkMesh, sidewalkMaterial, sidewalks)],
        castShadows: false,
        receiveShadows: true,
      });
      this.meshes.push(sidewalkMesh);
      this.materials.push(sidewalkMaterial);
      this.root.addChild(sidewalks);
    }

    const batches = district.materials.map(() => batch());
    const roofBatch = batch();
    const windowsBatch = batch();
    const facadeBandBatch = batch();
    const architecturalDetailBatch = batch();
    for (const building of district.buildings) {
      addBuilding(batches[building.material % batches.length]!, building, false);
      addRoof(roofBatch, building);
      const facade = interpretation?.subjects.find(subject => subject.recipe.kind === 'facade-grid' && subject.recipe.feature_id === building.id);
      if (!interpretation || facade?.recipe.kind === 'facade-grid') addWindows(windowsBatch, building, facade?.recipe.kind === 'facade-grid' ? facade.recipe : undefined);
      if (!interpretation) {
        addFacadeBands(facadeBandBatch, building);
        addArchitecturalDetails(architecturalDetailBatch, building);
      } else {
        const roof = interpretation.subjects.find(subject => subject.recipe.kind === 'roof-parapet' && subject.recipe.feature_id === building.id);
        if (roof?.recipe.kind === 'roof-parapet') {
          // Parapet face follows every source ring; no invented rooftop equipment.
          const parapet = { ...building, height_cm: (roof.recipe.height_mm + roof.recipe.parapet_height_mm) / 10 };
          const wallBatch = batch(); addBuilding(wallBatch, parapet, false);
          for (let i = 1; i < wallBatch.positions.length; i += 3) if (wallBatch.positions[i] === 0) wallBatch.positions[i] = roof.recipe.height_mm / 1000;
          const start = facadeBandBatch.positions.length / 3;
          facadeBandBatch.positions.push(...wallBatch.positions); facadeBandBatch.normals.push(...wallBatch.normals); facadeBandBatch.indices.push(...wallBatch.indices.map(i => i + start));
        }
      }
    }
    let drawCalls = sidewalkMesh === null ? 1 : 2;
    for (let index = 0; index < batches.length; index += 1) {
      const geometry = mesh(device, batches[index]!);
      if (geometry === null) continue;
      const surface = material(district.materials[index]!);
      const entity = new pc.Entity(`owned-buildings-${index}`);
      entity.addComponent('render', {
        meshInstances: [new pc.MeshInstance(geometry, surface, entity)],
        castShadows: true,
        receiveShadows: true,
      });
      this.meshes.push(geometry);
      this.materials.push(surface);
      this.root.addChild(entity);
      drawCalls += 1;
    }
    const roofMesh = mesh(device, roofBatch);
    if (roofMesh !== null) {
      const roofMaterial = new pc.StandardMaterial();
      roofMaterial.diffuse = new pc.Color(0.18, 0.195, 0.19);
      roofMaterial.emissive = new pc.Color(0.008, 0.009, 0.008);
      roofMaterial.gloss = 0.14;
      roofMaterial.update();
      const roofs = new pc.Entity('owned-building-roofs');
      roofs.addComponent('render', {
        meshInstances: [new pc.MeshInstance(roofMesh, roofMaterial, roofs)],
        castShadows: true,
        receiveShadows: true,
      });
      this.meshes.push(roofMesh);
      this.materials.push(roofMaterial);
      this.root.addChild(roofs);
      drawCalls += 1;
    }
    const windowsMesh = mesh(device, windowsBatch);
    if (windowsMesh !== null) {
      const windowsMaterial = new pc.StandardMaterial();
      windowsMaterial.diffuse = new pc.Color(0.25, 0.34, 0.39);
      windowsMaterial.emissive = new pc.Color(0.15, 0.19, 0.23);
      windowsMaterial.emissiveIntensity = 0.3;
      windowsMaterial.gloss = 0.72;
      windowsMaterial.cull = pc.CULLFACE_NONE;
      windowsMaterial.update();
      const windows = new pc.Entity('owned-building-memory-windows');
      windows.addComponent('render', {
        meshInstances: [new pc.MeshInstance(windowsMesh, windowsMaterial, windows)],
        castShadows: false,
      });
      this.meshes.push(windowsMesh);
      this.materials.push(windowsMaterial);
      this.root.addChild(windows);
      drawCalls += 1;
    }
    const facadeBandsMesh = mesh(device, facadeBandBatch);
    if (facadeBandsMesh !== null) {
      const facadeBandMaterial = new pc.StandardMaterial();
      facadeBandMaterial.diffuse = new pc.Color(0.12, 0.135, 0.13);
      facadeBandMaterial.emissive = new pc.Color(0.006, 0.007, 0.006);
      facadeBandMaterial.gloss = 0.22;
      facadeBandMaterial.update();
      const facadeBands = new pc.Entity('owned-building-cornices');
      facadeBands.addComponent('render', {
        meshInstances: [new pc.MeshInstance(facadeBandsMesh, facadeBandMaterial, facadeBands)],
        castShadows: true,
      });
      this.meshes.push(facadeBandsMesh);
      this.materials.push(facadeBandMaterial);
      this.root.addChild(facadeBands);
      drawCalls += 1;
    }
    const architecturalDetailsMesh = mesh(device, architecturalDetailBatch);
    if (architecturalDetailsMesh !== null) {
      const architecturalDetailMaterial = new pc.StandardMaterial();
      architecturalDetailMaterial.diffuse = new pc.Color(0.115, 0.13, 0.125);
      architecturalDetailMaterial.emissive = new pc.Color(0.008, 0.009, 0.008);
      architecturalDetailMaterial.gloss = 0.34;
      architecturalDetailMaterial.update();
      const architecturalDetails = new pc.Entity('owned-building-architectural-details');
      architecturalDetails.addComponent('render', {
        meshInstances: [
          new pc.MeshInstance(
            architecturalDetailsMesh,
            architecturalDetailMaterial,
            architecturalDetails,
          ),
        ],
        castShadows: true,
      });
      this.meshes.push(architecturalDetailsMesh);
      this.materials.push(architecturalDetailMaterial);
      this.root.addChild(architecturalDetails);
      drawCalls += 1;
    }

    const trunks = batch();
    const foliage = batch();
    const lamps = batch();
    (interpretation ? [] : district.sidewalks).forEach((sidewalk, index) => {
      const centre = sidewalkCentre(sidewalk);
      if (centre === null) return;
      const [x, z] = centre;
      addBox(trunks, [x, 1.05, z], [0.12, 1.05, 0.12]);
      addOctahedron(foliage, [x, 2.85, z], 1.15 + (index % 3) * 0.12);
      if (index % 2 === 0) {
        addBox(lamps, [x + 1.4, 1.65, z + 0.6], [0.045, 1.65, 0.045]);
        addBox(lamps, [x + 1.4, 3.32, z + 0.6], [0.16, 0.12, 0.16]);
      }
    });
    const streetDetails = [
      {
        name: 'owned-street-tree-trunks',
        source: trunks,
        diffuse: new pc.Color(0.16, 0.105, 0.065),
        emissive: new pc.Color(0.008, 0.004, 0.002),
      },
      {
        name: 'owned-street-tree-canopies',
        source: foliage,
        diffuse: new pc.Color(0.18, 0.34, 0.25),
        emissive: new pc.Color(0.008, 0.018, 0.012),
      },
      {
        name: 'owned-street-lamps',
        source: lamps,
        diffuse: new pc.Color(0.2, 0.19, 0.16),
        emissive: new pc.Color(0.26, 0.18, 0.08),
      },
    ] as const;
    for (const detail of streetDetails) {
      const geometry = mesh(device, detail.source);
      if (geometry === null) continue;
      const surface = new pc.StandardMaterial();
      surface.diffuse = detail.diffuse;
      surface.emissive = detail.emissive;
      surface.emissiveIntensity = detail.name === 'owned-street-lamps' ? 0.75 : 0.12;
      surface.gloss = detail.name === 'owned-street-tree-canopies' ? 0.08 : 0.24;
      surface.update();
      const entity = new pc.Entity(detail.name);
      entity.addComponent('render', {
        meshInstances: [new pc.MeshInstance(geometry, surface, entity)],
        castShadows: true,
        receiveShadows: true,
      });
      this.meshes.push(geometry);
      this.materials.push(surface);
      this.root.addChild(entity);
      drawCalls += 1;
    }
    if (interpretation) {
      const civic = batch();
      for (const subject of interpretation.subjects) {
        if (!subject.permitted_uses.includes('render')) continue;
        const recipe = subject.recipe;
        if (recipe.kind === 'rest-pad') {
          const [x, z] = recipe.position_mm.map(v => v / 1000);
          const radius = recipe.radius_mm / 1000;
          for (let i = 0; i < 24; i++) {
            const a = i * Math.PI / 12, b = (i + 1) * Math.PI / 12;
            quad(civic, [x! + Math.cos(a) * radius, .008, z! + Math.sin(a) * radius],
              [x! + Math.cos(b) * radius, .008, z! + Math.sin(b) * radius],
              [x! + Math.cos(b) * radius * .75, .008, z! + Math.sin(b) * radius * .75],
              [x! + Math.cos(a) * radius * .75, .008, z! + Math.sin(a) * radius * .75], [0, 1, 0]);
          }
        } else if (recipe.kind === 'entrance-marker') {
          const [x, z] = recipe.position_mm.map(v => v / 1000);
          // A thin upright arrival marker, not a door or supported interior.
          addBox(civic, [x!, recipe.height_mm / 2000, z!], [recipe.width_mm / 2000, recipe.height_mm / 2000, .025]);
        }
      }
      const civicMesh = mesh(device, civic);
      if (civicMesh) {
        const mat = new pc.StandardMaterial(); mat.diffuse = new pc.Color(.22, .54, .58); mat.emissive = new pc.Color(.07, .16, .17); mat.cull = pc.CULLFACE_NONE; mat.update();
        const entity = new pc.Entity('interpreted-civic-markers');
        entity.addComponent('render', {meshInstances:[new pc.MeshInstance(civicMesh, mat, entity)],castShadows:false,receiveShadows:true});
        this.root.addChild(entity); this.meshes.push(civicMesh); this.materials.push(mat); drawCalls++;
      }
    }
    this.metrics = Object.freeze({
      logicalBuildings: district.buildings.length,
      logicalSidewalks: district.sidewalks.length,
      drawCalls,
      residentBytes: sourceBytes,
      visibleTiles: 1,
    });
  }

  setAuthoredInstances(instances: readonly OwnedAuthoredEnvironmentInstance[]): void {
    for (const child of [...this.authoredRoot.children]) child.destroy();
    for (const held of this.authoredMeshes) held.destroy();
    for (const held of this.authoredMaterials) held.destroy();
    this.authoredMeshes = [];
    this.authoredMaterials = [];
    for (const instance of instances) {
      if (instance.removed || instance.availability !== 'available') continue;
      if (instance.coordinateFrame !== 'flatiron-local-mm' || instance.providerFeatureId === undefined) continue;
      const building = this.district.buildings.find(
        (candidate) => candidate.id === instance.providerFeatureId,
      );
      if (building === undefined) continue;
      const [west, north, east, south] = building.bbox_cm;
      const cx = (west + east) / 2;
      const cz = (north + south) / 2;
      const local: OwnedDistrictBuilding = {
        ...building,
        polygons: building.polygons.map((polygon) => polygon.map((ring) => ring.map(
          ([x, z]) => [x - cx, z - cz] as const,
        ))),
      };
      const source = batch();
      addBuilding(source, local);
      const geometry = mesh(this.device, source);
      if (geometry === null) continue;
      const surface = new pc.StandardMaterial();
      surface.diffuse = instance.origin.role === 'fictional'
        ? new pc.Color(0.12, 0.34, 0.4)
        : new pc.Color(0.74, 0.66, 0.55);
      surface.emissive = instance.origin.role === 'fictional'
        ? new pc.Color(0.05, 0.58, 0.68)
        : new pc.Color(0.08, 0.04, 0.02);
      surface.emissiveIntensity = instance.origin.role === 'fictional' ? 0.55 : 0.12;
      surface.metalness = 0.22;
      surface.gloss = 0.72;
      surface.useMetalness = true;
      surface.update();
      const entity = new pc.Entity(`authored-${instance.instanceId}`);
      entity.addComponent('render', {
        meshInstances: [new pc.MeshInstance(geometry, surface, entity)],
        castShadows: true,
        receiveShadows: true,
      });
      entity.setLocalPosition(
        instance.transform.xMm / 1000,
        instance.transform.yMm / 1000,
        instance.transform.zMm / 1000,
      );
      entity.setEulerAngles(0, instance.transform.yawMicroradians * 180 / Math.PI / 1_000_000, 0);
      entity.setLocalScale(
        instance.transform.scaleMilli / 1000,
        instance.transform.scaleMilli / 1000,
        instance.transform.scaleMilli / 1000,
      );
      if (instance.origin.role === 'fictional') {
        const lanternMesh = pc.createCone(this.device, {
          baseRadius: 4,
          peakRadius: 0,
          height: 10,
        });
        const lantern = new pc.Entity('authored-fantasy-sky-lantern');
        lantern.addComponent('render', {
          meshInstances: [new pc.MeshInstance(lanternMesh, surface, lantern)],
          castShadows: false,
        });
        lantern.setLocalPosition(0, building.height_cm / 100 + 8, 0);
        entity.addChild(lantern);
        this.authoredMeshes.push(lanternMesh);
      }
      this.authoredMeshes.push(geometry);
      this.authoredMaterials.push(surface);
      this.authoredRoot.addChild(entity);
    }
  }

  /** Release the unavailable population without inventing an authoritative snapshot. */
  clearSociety(): void {
    this.latestSociety = null;
    this.societyAnimation = null;
    this.settleSocietyUntilMs = 0;
    this.lastObserver = null;
    this.promotedInhabitant = null;
    this.societyScope = '';
    this.societyTick = -1;
    this.nativeSocietyDiscontinuity = true;
    this.societyPositions.clear();
    for (const character of this.societyCharacters.values()) character.destroy();
    this.societyCharacters.clear();
    for (const value of this.societyMeshes) value.destroy();
    for (const value of this.societyMaterials) value.destroy();
    this.societyMeshes = [];
    this.societyMaterials = [];
  }

  setSociety(
    state: OwnedSocietyState,
    visibleCap = 24,
    observer?: readonly [number, number],
  ): number {
    this.latestSociety = state;
    this.lastObserver = observer ?? null;
    const scope = `${state.society_id ?? 'preview'}:${state.branch_id ?? ''}`;
    if(scope!==this.societyScope){for(const character of this.societyCharacters.values())character.destroy();this.societyCharacters.clear();}
    const consecutive = scope === this.societyScope && state.tick === this.societyTick + 1;
    this.nativeSocietyDiscontinuity ||= !consecutive;
    this.societyScope = scope;
    this.societyTick = state.tick;
    // Picking follows only currently visible display positions, never a stale capped subset.
    this.societyPositions.clear();
    const visible = [...state.inhabitants]
      .filter((inhabitant) => inhabitant.synthetic === true)
      .sort((a, b) => observer === undefined ? 0 :
        Math.hypot(a.position_mm[0] / 1000 - observer[0], a.position_mm[1] / 1000 - observer[1]) -
        Math.hypot(b.position_mm[0] / 1000 - observer[0], b.position_mm[1] / 1000 - observer[1]))
      .slice(0, Math.max(0, Math.min(visibleCap, 24)));
    const visibleIds=new Set(visible.map(person=>person.id));
    for(const [id,character] of this.societyCharacters)if(!visibleIds.has(id)){character.destroy();this.societyCharacters.delete(id);}
    const animated = visible.map((inhabitant, ordinal) => {
      const role=inhabitant.role??'inhabitant';
      let character=this.societyCharacters.get(inhabitant.id);
      if(!character){character=new PlayerAvatar(this.device,this.societyRoot,{name:`synthetic:${inhabitant.id}`,detail:'mid',representation:abstractCharacter({kind:'synthetic-inhabitant',societyId:state.society_id??'preview',branchId:state.branch_id??'preview',inhabitantId:inhabitant.id},'mid',syntheticCharacterStyle(inhabitant.id))});this.societyCharacters.set(inhabitant.id,character);}
      const to = [
        inhabitant.position_mm[0] / 1000,
        inhabitant.position_mm[1] / 1000,
      ] as const;
      const candidatePath = inhabitant.motion_path_mm?.map(([x, z]) => [x / 1000, z / 1000] as const);
      // Legacy snapshots have no supported path. Do not fabricate travel between endpoints.
      const path = state.profile === 'exulanica-society/v2' && consecutive && candidatePath?.length
        ? candidatePath : [to];
      const from = path[0]!;
      this.societyPositions.set(inhabitant.id, from);
      character.update({x:from[0],y:character.body.heightMm/1000*.89,z:from[1],yaw:0,pitch:0},0,0,1/60,true,true,0);
      return { id: inhabitant.id, role, ordinal, from, to, path };
    });
    this.societyAnimation = animated.some(person=>person.path.length>1) ? {
      startedAtMs: performance.now(),
      durationMs: 1_850,
      inhabitants: animated,
    } : null;
    this.applyCoincidentVisibility();
    this.lastSocietyFrameMs=performance.now();
    return visible.length;
  }

  /** Interpolate display meshes only; authoritative endpoints remain the society snapshots. */
  tickSociety(nowMs: number): void {
    const animation = this.societyAnimation;
    if (animation === null) {
      if(nowMs<this.settleSocietyUntilMs){
        const dt=Math.max(.001,Math.min(.05,(nowMs-this.lastSocietyFrameMs)/1000));this.lastSocietyFrameMs=nowMs;
        for(const [id,character] of this.societyCharacters){const p=this.societyPositions.get(id)!;character.update({x:p[0],y:character.body.heightMm/1000*.89,z:p[1],yaw:0,pitch:0},0,0,dt,true,false,0);}
        this.applyCoincidentVisibility();
      }else this.settleSocietyUntilMs=0;
      return;
    }
    const linear = Math.max(0, Math.min(1, (nowMs - animation.startedAtMs) / animation.durationMs));
    const progress = linear * linear * (3 - 2 * linear);
    const dt=Math.max(.001,Math.min(.05,(nowMs-this.lastSocietyFrameMs)/1000));
    this.lastSocietyFrameMs=nowMs;
    for (const inhabitant of animation.inhabitants) {
      const position = sampleMotionPath(inhabitant.path, progress);
      const previous=this.societyPositions.get(inhabitant.id)??position;
      this.societyPositions.set(inhabitant.id, position);
      const character=this.societyCharacters.get(inhabitant.id);
      character?.update({x:position[0],y:character.body.heightMm/1000*.89,z:position[1],yaw:0,pitch:0},position[0]-previous[0],position[1]-previous[1],dt,true,nowMs===Number.MAX_SAFE_INTEGER,0);
    }
    this.applyCoincidentVisibility();
    if (linear >= 1) {this.societyAnimation = null;this.settleSocietyUntilMs=nowMs===Number.MAX_SAFE_INTEGER?0:nowMs+600;}
  }

  refreshNearby(observer: readonly [number, number]): void {
    if (this.societyAnimation || !this.latestSociety || (this.lastObserver && Math.hypot(observer[0] - this.lastObserver[0], observer[1] - this.lastObserver[1]) < 4)) return;
    this.setSociety(this.latestSociety, 24, observer);
  }

  /** GPU buffer residency, separate from the serialized source document byte count. */
  get characterTextureBytes():number{return [...this.societyCharacters.values()].reduce((bytes,character)=>bytes+character.textureResidentBytes,0);}
  get geometryResidentBytes(): number {
    return [...this.societyCharacters.values()].reduce((sum,character)=>sum+character.residentBytes,0)+[...this.meshes, ...this.authoredMeshes, ...this.societyMeshes].reduce((sum, mesh) => sum + (mesh.vertexBuffer?.numBytes ?? 0) + mesh.indexBuffer.reduce((bytes, buffer) => bytes + (buffer?.numBytes ?? 0), 0), 0);
  }

  /** Resolves shared subjects, independent of renderer batch IDs. */
  pickSubject(origin: readonly [number, number, number], direction: readonly [number, number, number]): DistrictSubject | null {
    if (!this.interpretation) return null;
    const building = this.pickBuilding(origin, direction);
    let nearest = building ? buildingRayDistance(building, origin, direction) ?? Infinity : Infinity;
    let selected = building ? this.interpretation.subjects.find(s => s.subject_id === building.id) ?? null : null;
    for (const subject of this.interpretation.subjects) {
      if (!subject.permitted_uses.includes('select')) continue;
      const recipe = subject.recipe;
      let distance: number | null = null;
      if (recipe.kind === 'entrance-marker') {
        const [x,z] = recipe.position_mm.map(v => v / 1000), half = recipe.width_mm / 2000;
        distance = rayBox(origin, direction, [x! - half, 0, z! - .025], [x! + half, recipe.height_mm / 1000, z! + .025]);
      } else if (recipe.kind === 'rest-pad' && Math.abs(direction[1]) > 1e-8) {
        const t = (.008 - origin[1]) / direction[1];
        const dx = origin[0] + direction[0] * t - recipe.position_mm[0] / 1000;
        const dz = origin[2] + direction[2] * t - recipe.position_mm[1] / 1000;
        if (t >= 0 && Math.hypot(dx,dz) <= recipe.radius_mm / 1000) distance = t;
      } else if (recipe.kind === 'source-footprint' && subject.kind === 'sidewalk' && Math.abs(direction[1]) > 1e-8) {
        const t = (.025 - origin[1]) / direction[1];
        const point = [(origin[0] + direction[0] * t) * 100, (origin[2] + direction[2] * t) * 100] as const;
        const sidewalk = this.district.sidewalks.find(s => s.id === recipe.feature_id);
        if (t >= 0 && sidewalk?.polygons.some(p => p[0] && pointInRing(point,p[0]) && !p.slice(1).some(r => pointInRing(point,r)))) distance = t;
      }
      if (distance !== null && distance < nearest) { nearest = distance; selected = subject; }
    }
    return selected;
  }

  get societyAnimating(): boolean { return this.societyAnimation !== null || this.settleSocietyUntilMs>0; }

  private applyCoincidentVisibility():void {
    const groups=new Map<string,string[]>();
    for(const [id,p] of this.societyPositions){const key=p.map(n=>n.toFixed(3)).join(':');const ids=groups.get(key)??[];ids.push(id);groups.set(key,ids);}
    for(const ids of groups.values()){
      const shown=ids.includes(this.promotedInhabitant??'')?this.promotedInhabitant:ids.slice().sort()[0];
      for(const id of ids){const character=this.societyCharacters.get(id);if(character)character.root.enabled=id===shown;}
    }
  }
  revealInhabitant(id:string):void {if(!this.societyPositions.has(id))return;this.promotedInhabitant=id;this.applyCoincidentVisibility();}
  get drawnInhabitantCount():number{return [...this.societyCharacters.values()].filter(character=>character.root.enabled&&!character.root.tags.has('native-character-hidden')).length;}
  coincidentInhabitants(id:string):readonly string[]{const p=this.societyPositions.get(id);return p?[...this.societyPositions].filter(([,q])=>Math.hypot(p[0]-q[0],p[1]-q[1])<.001).map(([key])=>key):[];}
  inhabitantRepresentation(id:string){return this.societyCharacters.get(id)?.representation??null;}

  nativeCharacterFrames(deltaSeconds:number,reducedMotion:boolean):readonly NativeCharacterFrame[]{
    const discontinuity=this.nativeSocietyDiscontinuity;this.nativeSocietyDiscontinuity=false;
    return [...this.societyCharacters.values()].map(character=>{
      const p=character.root.getLocalPosition();
      return {subject:character.representation.subject,parent:this.societyRoot,fallback:character.root,visible:character.root.enabled,position:[p.x,p.y,p.z],yaw:character.facing,deltaSeconds,reducedMotion,discontinuity};
    });
  }

  get visibleInhabitantIds(): readonly string[] { return [...this.societyPositions.keys()]; }

  /** Stable subject selection against the displayed avatar, with building occlusion. */
  pickInhabitant(origin: readonly [number, number, number], direction: readonly [number, number, number]): string | null {
    let nearest = Infinity;
    for (const building of this.district.buildings) nearest = Math.min(nearest, buildingRayDistance(building, origin, direction) ?? Infinity);
    let selected: string | null = null;
    for (const [id, [x, z]] of this.societyPositions) {
      if(!this.societyCharacters.get(id)?.root.enabled||this.societyCharacters.get(id)?.root.tags.has('native-character-hidden'))continue;
      const height=(this.societyCharacters.get(id)?.body.heightMm??1820)/1000;
      const distance = rayBox(origin, direction, [x - .34, 0, z - .34], [x + .34, height, z + .34]);
      if (distance !== null && distance < nearest) { nearest = distance; selected = id; }
    }
    return selected;
  }

  /** Exact semantic hit against admitted extruded footprints, independent of mesh names. */
  pickBuilding(
    origin: readonly [number, number, number],
    direction: readonly [number, number, number],
  ): OwnedDistrictBuilding | null {
    let selected: { building: OwnedDistrictBuilding; distance: number } | null = null;
    for (const building of this.district.buildings) {
      const distance = buildingRayDistance(building, origin, direction);
      if (distance !== null && (selected === null || distance < selected.distance)) selected = { building, distance };
    }
    return selected?.building ?? null;
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.clearSociety();
    this.root.destroy();
    this.authoredRoot.destroy();
    this.societyRoot.destroy();
    for (const value of this.authoredMeshes) value.destroy();
    for (const value of this.authoredMaterials) value.destroy();
    for (const value of this.meshes) value.destroy();
    for (const value of this.materials) value.destroy();
  }
}
