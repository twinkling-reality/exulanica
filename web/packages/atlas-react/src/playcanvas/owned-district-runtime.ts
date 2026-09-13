import type {
  OwnedDistrict,
  OwnedDistrictBuilding,
  OwnedDistrictMaterial,
} from '@exulanica/atlas-core';
import * as pc from 'playcanvas';

export interface OwnedDistrictMetrics {
  readonly logicalBuildings: number;
  readonly logicalSidewalks: number;
  readonly drawCalls: number;
  readonly residentBytes: number;
  readonly visibleTiles: number;
}

export interface OwnedAuthoredEnvironmentInstance {
  readonly instanceId: string;
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
  readonly tick: number;
  readonly inhabitants: readonly {
    readonly id: string;
    readonly synthetic: true;
    readonly role?: string;
    readonly position_mm: readonly [number, number];
  }[];
}

interface Batch {
  readonly positions: number[];
  readonly normals: number[];
  readonly indices: number[];
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
  result.diffuse = base;
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
    const ring = polygon[0];
    if (ring === undefined || ring.length < 4) continue;
    let cx = 0;
    let cz = 0;
    for (const [x, z] of ring.slice(0, -1)) {
      cx += x / 100;
      cz += z / 100;
    }
    cx /= ring.length - 1;
    cz /= ring.length - 1;
    const roofCentre = includeRoof ? target.positions.length / 3 : -1;
    if (includeRoof) {
      target.positions.push(cx, height, cz);
      target.normals.push(0, 1, 0);
    }
    for (let index = 1; index < ring.length; index += 1) {
      const [ax, az] = ring[index - 1]!;
      const [bx, bz] = ring[index]!;
      const a: [number, number, number] = [ax / 100, 0, az / 100];
      const b: [number, number, number] = [bx / 100, 0, bz / 100];
      const c: [number, number, number] = [bx / 100, height, bz / 100];
      const d: [number, number, number] = [ax / 100, height, az / 100];
      const dx = b[0] - a[0];
      const dz = b[2] - a[2];
      const length = Math.max(Math.hypot(dx, dz), 1e-6);
      quad(target, a, b, c, d, [-dz / length, 0, dx / length]);
      if (includeRoof) {
        const roofA = target.positions.length / 3;
        target.positions.push(d[0], height, d[2], c[0], height, c[2]);
        target.normals.push(0, 1, 0, 0, 1, 0);
        target.indices.push(roofCentre, roofA, roofA + 1);
      }
    }
  }
}

function addRoof(target: Batch, building: OwnedDistrictBuilding): void {
  const height = building.height_cm / 100 + 0.008;
  addFlatPolygon(target, building.polygons, height);
}

function addWindows(target: Batch, building: OwnedDistrictBuilding): void {
  if (building.name === null && building.render_batch_id % 9 !== 0) return;
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
      const columns = Math.floor(length / 5.5);
      if (columns < 1) continue;
      const nx = -dz / length;
      const nz = dx / length;
      const levels = Math.min(18, Math.floor((height - 3) / 4.2));
      for (let level = 0; level < levels; level += 1) {
        for (let column = 0; column < columns; column += 1) {
          const centre = (column + 0.5) / columns;
          const half = Math.min(0.62 / length, 0.28 / columns);
          const y = 2.7 + level * 4.2;
          // NYC rings are retained with provider winding; this offset follows their exterior.
          const front = -0.055;
          quad(
            target,
            [ax + dx * (centre - half) + nx * front, y, az + dz * (centre - half) + nz * front],
            [ax + dx * (centre + half) + nx * front, y, az + dz * (centre + half) + nz * front],
            [ax + dx * (centre + half) + nx * front, y + 1.45, az + dz * (centre + half) + nz * front],
            [ax + dx * (centre - half) + nx * front, y + 1.45, az + dz * (centre - half) + nz * front],
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

function addInhabitant(target: Batch, x: number, z: number, ordinal: number): void {
  const stride = ordinal % 2 === 0 ? 0.055 : -0.055;
  addBox(target, [x - 0.105, 0.39 + stride, z], [0.075, 0.39, 0.09]);
  addBox(target, [x + 0.105, 0.39 - stride, z], [0.075, 0.39, 0.09]);
  addBox(target, [x, 1.08, z], [0.25, 0.34, 0.15]);
  addBox(target, [x, 1.43, z], [0.31, 0.08, 0.16]);
  addOctahedron(target, [x, 1.72, z], 0.2);
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
    const ring = polygon[0];
    if (ring === undefined || ring.length < 4) continue;
    let cx = 0;
    let cz = 0;
    for (const [x, z] of ring.slice(0, -1)) {
      cx += x / 100;
      cz += z / 100;
    }
    cx /= ring.length - 1;
    cz /= ring.length - 1;
    const centre = target.positions.length / 3;
    target.positions.push(cx, height, cz);
    target.normals.push(0, 1, 0);
    for (let index = 1; index < ring.length; index += 1) {
      const first = target.positions.length / 3;
      const [ax, az] = ring[index - 1]!;
      const [bx, bz] = ring[index]!;
      target.positions.push(ax / 100, height, az / 100, bx / 100, height, bz / 100);
      target.normals.push(0, 1, 0, 0, 1, 0);
      target.indices.push(centre, first, first + 1);
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

function inside(
  point: readonly [number, number],
  ring: readonly (readonly [number, number])[],
): boolean {
  let value = false;
  for (let index = 0, prior = ring.length - 1; index < ring.length; prior = index++) {
    const a = ring[index]!;
    const b = ring[prior]!;
    if (
      (a[1] > point[1]) !== (b[1] > point[1]) &&
      point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]
    ) value = !value;
  }
  return value;
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
  private societyMeshes: pc.Mesh[] = [];
  private societyMaterials: pc.Material[] = [];
  private destroyed = false;

  constructor(
    private readonly device: pc.GraphicsDevice,
    parent: pc.Entity,
    readonly district: OwnedDistrict,
    sourceBytes: number,
  ) {
    parent.addChild(this.root);
    parent.addChild(this.authoredRoot);
    parent.addChild(this.societyRoot);
    const asphalt = new pc.StandardMaterial();
    asphalt.diffuse = new pc.Color(0.255, 0.27, 0.265);
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
      sidewalkMaterial.diffuse = new pc.Color(0.69, 0.66, 0.59);
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
      addWindows(windowsBatch, building);
      addFacadeBands(facadeBandBatch, building);
      addArchitecturalDetails(architecturalDetailBatch, building);
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
      windowsMaterial.diffuse = new pc.Color(0.105, 0.16, 0.18);
      windowsMaterial.emissive = new pc.Color(0.19, 0.16, 0.105);
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
    district.sidewalks.forEach((sidewalk, index) => {
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
    for (const instance of instances) {
      if (instance.removed || instance.availability !== 'available') continue;
      const providerId = instance.instanceId.match(/doitt_id[-:]([1-9][0-9]*)/)?.[1];
      const building = this.district.buildings.find(
        (candidate) => candidate.id === `doitt_id:${providerId}`,
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
      entity.setPosition(
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
        lantern.setPosition(0, building.height_cm / 100 + 8, 0);
        entity.addChild(lantern);
        this.meshes.push(lanternMesh);
      }
      this.meshes.push(geometry);
      this.materials.push(surface);
      this.authoredRoot.addChild(entity);
    }
  }

  setSociety(
    state: OwnedSocietyState,
    visibleCap = 24,
    observer?: readonly [number, number],
  ): number {
    for (const child of [...this.societyRoot.children]) child.destroy();
    for (const held of this.societyMeshes) held.destroy();
    for (const held of this.societyMaterials) held.destroy();
    this.societyMeshes = [];
    this.societyMaterials = [];
    const visible = [...state.inhabitants]
      .filter((inhabitant) => inhabitant.synthetic === true)
      .sort((a, b) => observer === undefined ? 0 :
        Math.hypot(a.position_mm[0] / 1000 - observer[0], a.position_mm[1] / 1000 - observer[1]) -
        Math.hypot(b.position_mm[0] / 1000 - observer[0], b.position_mm[1] / 1000 - observer[1]))
      .slice(0, Math.max(0, Math.min(visibleCap, 24)));
    const roleOrder = ['baker', 'designer', 'gardener', 'student', 'steward', 'teacher'] as const;
    const batches = new Map<string, Batch>(roleOrder.map((role) => [role, batch()]));
    visible.forEach((inhabitant, ordinal) => {
      const [x, z] = inhabitant.position_mm;
      const role = roleOrder.includes(inhabitant.role as typeof roleOrder[number])
        ? inhabitant.role!
        : roleOrder[ordinal % roleOrder.length]!;
      addInhabitant(batches.get(role)!, x / 1000, z / 1000, ordinal);
    });
    const roleColors: Readonly<Record<string, pc.Color>> = {
      baker: new pc.Color(0.67, 0.42, 0.24),
      designer: new pc.Color(0.35, 0.43, 0.56),
      gardener: new pc.Color(0.3, 0.46, 0.3),
      student: new pc.Color(0.55, 0.37, 0.47),
      steward: new pc.Color(0.27, 0.43, 0.48),
      teacher: new pc.Color(0.48, 0.39, 0.27),
    };
    for (const role of roleOrder) {
      const geometry = mesh(this.device, batches.get(role)!);
      if (geometry === null) continue;
      const surface = new pc.StandardMaterial();
      surface.diffuse = roleColors[role]!;
      surface.emissive = new pc.Color(0.018, 0.012, 0.01);
      surface.emissiveIntensity = 0.18;
      surface.gloss = 0.28;
      surface.update();
      const entity = new pc.Entity(`synthetic-${role}-tick-${state.tick}`);
      entity.addComponent('render', {
        meshInstances: [new pc.MeshInstance(geometry, surface, entity)],
        castShadows: true,
        receiveShadows: true,
      });
      this.societyMeshes.push(geometry);
      this.societyMaterials.push(surface);
      this.societyRoot.addChild(entity);
    }
    return visible.length;
  }

  /** Exact semantic hit against admitted extruded footprints, independent of mesh names. */
  pickBuilding(
    origin: readonly [number, number, number],
    direction: readonly [number, number, number],
  ): OwnedDistrictBuilding | null {
    let selected: { building: OwnedDistrictBuilding; distance: number } | null = null;
    for (const building of this.district.buildings) {
      const [west, north, east, south] = building.bbox_cm.map((value) => value / 100) as [
        number, number, number, number,
      ];
      const distance = rayBox(
        origin,
        direction,
        [west, 0, north],
        [east, building.height_cm / 100, south],
      );
      if (distance === null || (selected !== null && distance >= selected.distance)) continue;
      const sampleDistance = distance + 0.01;
      const point: [number, number] = [
        (origin[0] + direction[0] * sampleDistance) * 100,
        (origin[2] + direction[2] * sampleDistance) * 100,
      ];
      const hit = building.polygons.some((polygon) => {
        const exterior = polygon[0];
        return exterior !== undefined && inside(point, exterior) &&
          polygon.slice(1).every((hole) => !inside(point, hole));
      });
      if (hit) selected = { building, distance };
    }
    return selected?.building ?? null;
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.root.destroy();
    this.authoredRoot.destroy();
    this.societyRoot.destroy();
    for (const value of this.societyMeshes) value.destroy();
    for (const value of this.societyMaterials) value.destroy();
    for (const value of this.meshes) value.destroy();
    for (const value of this.materials) value.destroy();
  }
}
