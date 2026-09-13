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
  readonly authoredRoot = new pc.Entity('owned-district-authored-instances');
  readonly societyRoot = new pc.Entity('owned-district-society');
  readonly metrics: OwnedDistrictMetrics;
  private readonly meshes: pc.Mesh[] = [];
  private readonly materials: pc.Material[] = [];
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

  setSociety(state: OwnedSocietyState, visibleCap = 24): number {
    for (const child of [...this.societyRoot.children]) child.destroy();
    const visible = state.inhabitants
      .filter((inhabitant) => inhabitant.synthetic === true)
      .slice(0, Math.max(0, Math.min(visibleCap, 24)));
    const source = batch();
    for (const inhabitant of visible) {
      const [x, z] = inhabitant.position_mm;
      const cx = x / 1000;
      const cz = z / 1000;
      const radius = 0.28;
      const base = source.positions.length / 3;
      source.positions.push(
        cx - radius, 0, cz - radius,
        cx + radius, 0, cz - radius,
        cx + radius, 0, cz + radius,
        cx - radius, 0, cz + radius,
        cx, 1.72, cz,
      );
      source.normals.push(
        0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0,
      );
      source.indices.push(
        base, base + 1, base + 4,
        base + 1, base + 2, base + 4,
        base + 2, base + 3, base + 4,
        base + 3, base, base + 4,
      );
    }
    const geometry = mesh(this.device, source);
    if (geometry === null) return 0;
    const surface = new pc.StandardMaterial();
    surface.diffuse = new pc.Color(0.82, 0.31, 0.16);
    surface.emissive = new pc.Color(0.18, 0.035, 0.012);
    surface.emissiveIntensity = 0.35;
    surface.gloss = 0.48;
    surface.update();
    const entity = new pc.Entity(`synthetic-inhabitants-tick-${state.tick}`);
    entity.addComponent('render', {
      meshInstances: [new pc.MeshInstance(geometry, surface, entity)],
      castShadows: true,
      receiveShadows: true,
    });
    this.meshes.push(geometry);
    this.materials.push(surface);
    this.societyRoot.addChild(entity);
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
    for (const value of this.meshes) value.destroy();
    for (const value of this.materials) value.destroy();
  }
}
