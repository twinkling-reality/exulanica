import * as pc from 'playcanvas';
import type { StylePackSwatch } from '@exulanica/atlas-core';
import type { SiteSlot } from '../generated-site/site-drawing.js';
import type { TileLook } from '../generated-tile/look.js';
import {
  castsShadow, drawBucket, setTangents, surfaceUv, unavailableUv,
  TileTextureUploads, type PreparedTextureSet, type TileTextureResolution,
} from '../generated-tile/texture-materials.js';
import { applyUp } from './swatch-material.js';

const PLACEMENT = { textureSetId: '', repeatSizeMillionths: 1_000_000, rotationUrad: 0, offsetUMm: 0, offsetVMm: 0 };

/** Millimetres along the declared frame; thickness faces use a nondegenerate physical projection. */
export function siteSurfaceMm(slot: SiteSlot, pointMm: readonly number[], normal: readonly number[]): readonly [number, number] {
  const angle = slot.yawQuarterTurns * Math.PI / 2;
  const across = [Math.cos(angle), -Math.sin(angle), 0];
  const forward = [Math.sin(angle), Math.cos(angle), 0];
  const dot = (a: readonly number[], b: readonly number[]): number => a.reduce((sum, value, i) => sum + value * b[i]!, 0);
  const delta = pointMm.map((value, i) => value - slot.positionMm[i]!);
  const horizontal = Math.abs(normal[2]!) > 0.5;
  if (slot.uvFrame !== undefined) {
    const frame = slot.uvFrame;
    const u = frame.uAxisMm.map(value => value / 1000), v = frame.vAxisMm.map(value => value / 1000);
    if (Math.abs(dot(normal, u)) < 0.5 && Math.abs(dot(normal, v)) < 0.5) {
      const offset = pointMm.map((value, i) => value - frame.originMm[i]!);
      return [dot(offset, u), v[2]! === 0 ? dot(offset, v) : -dot(offset, v)];
    }
  }
  if (horizontal || slot.primitive === 'plane' || slot.family === 'roof') {
    return [dot(delta, across) + slot.boxMm[0] / 2, dot(delta, forward) + slot.boxMm[1] / 2];
  }
  const side = Math.abs(dot(normal, across)) > 0.5;
  return [side ? dot(delta, forward) + slot.boxMm[1] / 2 : dot(delta, across) + slot.boxMm[0] / 2,
    slot.boxMm[2] - delta[2]!];
}

/** A copy of the drawn mesh with physical UVs. Positions, indices and bounds are unchanged. */
export function siteTextureMesh(device: pc.GraphicsDevice, original: pc.Mesh, slot: SiteSlot, resolution: TileTextureResolution, look: TileLook, node: pc.GraphNode, root: pc.GraphNode): pc.Mesh {
  const positions: number[] = [], normals: number[] = [], indices: number[] = [], uvs: number[] = [];
  original.getPositions(positions);
  original.getNormals(normals);
  original.getIndices(indices);
  const matrix = new pc.Mat4().mul2(root.getWorldTransform().clone().invert(), node.getWorldTransform());
  const point = new pc.Vec3(), direction = new pc.Vec3();
  for (let i = 0; i < positions.length; i += 3) {
    matrix.transformPoint(point.set(positions[i]!, positions[i + 1]!, positions[i + 2]!), point);
    matrix.transformVector(direction.set(normals[i]!, normals[i + 1]!, normals[i + 2]!), direction).normalize();
    const [s, t] = siteSurfaceMm(slot, [point.x * 1000, -point.z * 1000, point.y * 1000], [direction.x, -direction.z, direction.y]);
    uvs.push(...(resolution.state === 'available'
      ? surfaceUv(s, t, PLACEMENT, resolution.set.entry)
      : unavailableUv(s, t, look, slot.primitive === 'plane' ? 'horizontal' : 'vertical')));
  }
  const mesh = new pc.Mesh(device);
  mesh.setPositions(positions);
  mesh.setNormals(normals);
  mesh.setUvs(0, uvs);
  mesh.setVertexStream(pc.SEMANTIC_TANGENT, setTangents(positions, normals, uvs, indices), 4);
  mesh.setIndices(indices);
  mesh.update(pc.PRIMITIVE_TRIANGLES);
  return mesh;
}

export interface SiteTextureMetrics {
  readonly transferredBytes: number;
  readonly decodedTextureBytes: number;
  readonly unavailableSurfaces: number;
}

/** Owns only the site dressing's uploads and mesh copies; never alters canonical geometry or walking. */
export class SiteTextures {
  readonly uploads: TileTextureUploads;
  readonly #restored: (() => void)[] = [];
  readonly #materials: pc.StandardMaterial[] = [];
  readonly #resolutions = new Map<string, TileTextureResolution>();
  #unavailable = 0;
  #disposed = false;

  constructor(private readonly device: pc.GraphicsDevice, private readonly look: TileLook,
    private readonly prepared: ReadonlyMap<string, PreparedTextureSet> = new Map()) {
    this.uploads = new TileTextureUploads(device, look);
  }

  /** Wear a texture set; returns whether what it now wears needs the scene's colour copied, which none does. */
  wear(instance: pc.MeshInstance, slot: SiteSlot, setId: string, up: StylePackSwatch | null, root: pc.GraphNode): boolean {
    let resolution = this.#resolutions.get(setId);
    if (resolution === undefined) {
      resolution = this.uploads.adopt(this.prepared.get(setId) ?? { state: 'refused', setId, reason: `No prepared texture set ${setId}` });
      this.#resolutions.set(setId, resolution);
    }
    const original = instance.mesh, material = instance.material, shadow = instance.castShadow, bucket = instance.drawBucket;
    const mesh = siteTextureMesh(this.device, original, slot, resolution, this.look, instance.node, root);
    instance.mesh = mesh;
    let worn = resolution.material;
    if (up !== null && resolution.state === 'available') {
      worn = worn.clone();
      applyUp(worn, up.srgb8);
      worn.update();
      this.#materials.push(worn);
    }
    instance.material = worn;
    if (resolution.state === 'available') {
      instance.castShadow = shadow && castsShadow(resolution.set);
      const nextBucket = drawBucket(resolution.set);
      if (nextBucket !== null) instance.drawBucket = nextBucket;
    } else this.#unavailable += 1;
    this.#restored.push(() => {
      instance.mesh = original; instance.material = material; instance.castShadow = shadow; instance.drawBucket = bucket;
      mesh.destroy();
    });
    // Glazing is blended over what lies behind it and needs no copy of the scene's colour.
    return false;
  }

  metrics(): SiteTextureMetrics {
    return { transferredBytes: this.uploads.transferredBytes, decodedTextureBytes: this.uploads.decodedTextureBytes, unavailableSurfaces: this.#unavailable };
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    for (const restore of this.#restored.reverse()) restore();
    for (const material of this.#materials) material.destroy();
    this.uploads.destroy();
  }
}
