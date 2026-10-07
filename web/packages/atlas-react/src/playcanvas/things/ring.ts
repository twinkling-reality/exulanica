/**
 * The ring under a picked thing, and where a pick meets a thing.
 *
 * The ring is a flat band on the ground in the shell's signal colour (`--color-signal`), drawn
 * unlit and over the ground so it reads in any world's light: at a standing thing's feet, around an
 * object's footprint, under a floating light. Picking meets a figure's pick volume, a box in the
 * figure's root frame or a sphere, carried into the world by the root's transform.
 */

import * as pc from 'playcanvas';
import type { PickVolume } from './figures.js';

const SEGMENTS = 48;
/** The band's width, as a share of its radius. */
const BAND = 0.16;

function bandMesh(device: pc.GraphicsDevice): pc.Mesh {
  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];
  for (let i = 0; i <= SEGMENTS; i += 1) {
    const a = (i / SEGMENTS) * Math.PI * 2;
    const c = Math.cos(a), s = Math.sin(a);
    positions.push(c * (1 - BAND), 0, s * (1 - BAND), c, 0, s);
    normals.push(0, 1, 0, 0, 1, 0);
    if (i < SEGMENTS) {
      const k = i * 2;
      indices.push(k, k + 2, k + 1, k + 1, k + 2, k + 3);
    }
  }
  const mesh = new pc.Mesh(device);
  mesh.setPositions(positions);
  mesh.setNormals(normals);
  mesh.setIndices(indices);
  mesh.update(pc.PRIMITIVE_TRIANGLES);
  return mesh;
}

export class PickRing {
  readonly entity: pc.Entity;
  private readonly material: pc.StandardMaterial;
  private readonly mesh: pc.Mesh;
  private time = 0;

  constructor(device: pc.GraphicsDevice, colour: string) {
    this.mesh = bandMesh(device);
    this.material = new pc.StandardMaterial();
    this.material.useLighting = false;
    this.material.useFog = false;
    this.material.diffuse = new pc.Color(0, 0, 0);
    this.material.emissive = new pc.Color().fromString(colour);
    this.material.cull = pc.CULLFACE_NONE;
    this.material.depthBias = -1;
    this.material.slopeDepthBias = -1;
    this.material.update();
    this.entity = new pc.Entity('thing-pick-ring');
    this.entity.addComponent('render', { meshInstances: [new pc.MeshInstance(this.mesh, this.material)], castShadows: false, receiveShadows: false });
    this.entity.enabled = false;
  }

  /** Put the ring under `root` (a figure's root), `radius` metres, or take it away with null. */
  place(root: pc.Entity | null, radius: number): void {
    if (root === null) {
      this.entity.enabled = false;
      this.entity.parent?.removeChild(this.entity);
      return;
    }
    if (this.entity.parent !== root) {
      this.entity.parent?.removeChild(this.entity);
      root.addChild(this.entity);
    }
    this.entity.setLocalPosition(0, 0.012, 0);
    this.entity.setLocalScale(radius, 1, radius);
    this.entity.enabled = true;
  }

  /** A slow pulse, so the ring reads as a selection rather than part of the ground. */
  step(dt: number, reducedMotion: boolean): void {
    this.time += reducedMotion ? 0 : dt;
    const glow = 0.85 + 0.15 * Math.sin(this.time * 3.2);
    this.material.emissiveIntensity = glow;
    this.material.update();
  }

  destroy(): void {
    this.entity.destroy();
    this.material.destroy();
    this.mesh.destroy();
  }
}

/** The ground radius a ring takes around a pick volume. */
export function ringRadius(volume: PickVolume | null): number {
  if (volume === null) return 0.4;
  if (volume.kind === 'sphere') return Math.max(0.3, volume.radius);
  const w = (volume.max[0] - volume.min[0]) / 2, d = (volume.max[2] - volume.min[2]) / 2;
  return Math.max(0.35, Math.hypot(w, d) + 0.12);
}

const local = new pc.Vec3();
const direction = new pc.Vec3();
const inverse = new pc.Mat4();
const box = new pc.BoundingBox();
const ray = new pc.Ray();
const hit = new pc.Vec3();
const sphere = new pc.BoundingSphere();

/**
 * How far along a world ray (`origin`, unit `dir`) it meets `volume` of a figure rooted at `root`,
 * in world metres, or null. The ray is carried into the root's frame, where the volume is stated.
 */
export function rayMeets(root: pc.Entity, volume: PickVolume, origin: pc.Vec3, dir: pc.Vec3): number | null {
  inverse.copy(root.getWorldTransform()).invert();
  inverse.transformPoint(origin, local);
  inverse.transformVector(dir, direction);
  const scale = direction.length();
  if (!(scale > 0)) return null;
  direction.mulScalar(1 / scale);
  ray.set(local, direction);
  let met: boolean;
  if (volume.kind === 'box') {
    box.setMinMax(new pc.Vec3(...volume.min), new pc.Vec3(...volume.max));
    met = box.intersectsRay(ray, hit);
  } else {
    sphere.center.set(...volume.centre);
    sphere.radius = volume.radius;
    met = sphere.intersectsRay(ray, hit);
  }
  // Distances in the root's frame come back to the world's by the frame's own scale.
  return met ? hit.distance(local) / scale : null;
}
