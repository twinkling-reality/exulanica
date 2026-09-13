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
  result.diffuse = color(source.base);
  result.metalness = source.metalness_milli / 1000;
  result.gloss = 1 - source.roughness_milli / 1000;
  result.useMetalness = true;
  result.useSkybox = true;
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

function addBuilding(target: Batch, building: OwnedDistrictBuilding): void {
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
    const roofCentre = target.positions.length / 3;
    target.positions.push(cx, height, cz);
    target.normals.push(0, 1, 0);
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
      const roofA = target.positions.length / 3;
      target.positions.push(d[0], height, d[2], c[0], height, c[2]);
      target.normals.push(0, 1, 0, 0, 1, 0);
      target.indices.push(roofCentre, roofA, roofA + 1);
    }
  }
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

function addGround(
  device: pc.GraphicsDevice,
  parent: pc.Entity,
  materialValue: pc.Material,
): pc.Mesh {
  const ground = new pc.Entity('owned-district-visible-support');
  const geometry = pc.createBox(device, {
    halfExtents: new pc.Vec3(340, 0.2, 334),
  });
  ground.addComponent('render', {
    meshInstances: [new pc.MeshInstance(geometry, materialValue, ground)],
    castShadows: false,
    receiveShadows: true,
  });
  ground.setPosition(0, -0.2, 0);
  parent.addChild(ground);
  return geometry;
}

/** PlayCanvas representation only. The document remains the world authority. */
export class OwnedDistrictRuntime {
  readonly root = new pc.Entity('owned-district');
  readonly metrics: OwnedDistrictMetrics;
  private readonly meshes: pc.Mesh[] = [];
  private readonly materials: pc.Material[] = [];
  private destroyed = false;

  constructor(
    device: pc.GraphicsDevice,
    parent: pc.Entity,
    readonly district: OwnedDistrict,
    sourceBytes: number,
  ) {
    parent.addChild(this.root);
    const asphalt = new pc.StandardMaterial();
    asphalt.diffuse = new pc.Color(0.055, 0.075, 0.09);
    asphalt.gloss = 0.18;
    asphalt.metalness = 0.08;
    asphalt.useMetalness = true;
    asphalt.update();
    this.materials.push(asphalt);
    this.meshes.push(addGround(device, this.root, asphalt));

    const sidewalkBatch = batch();
    for (const sidewalk of district.sidewalks) {
      addFlatPolygon(sidewalkBatch, sidewalk.polygons, 0.025);
    }
    const sidewalkMesh = mesh(device, sidewalkBatch);
    if (sidewalkMesh !== null) {
      const sidewalkMaterial = new pc.StandardMaterial();
      sidewalkMaterial.diffuse = new pc.Color(0.58, 0.6, 0.57);
      sidewalkMaterial.gloss = 0.15;
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
    for (const building of district.buildings) {
      addBuilding(batches[building.material % batches.length]!, building);
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
    this.metrics = Object.freeze({
      logicalBuildings: district.buildings.length,
      logicalSidewalks: district.sidewalks.length,
      drawCalls,
      residentBytes: sourceBytes,
      visibleTiles: 1,
    });
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.root.destroy();
    for (const value of this.meshes) value.destroy();
    for (const value of this.materials) value.destroy();
  }
}
