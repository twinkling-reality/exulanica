/**
 * Where a drawn island or a placed point map stands: a presentation transform written as PlayCanvas
 * local position, rotation and scale. Used by the binding (`atlas-binding.ts`) to place each island
 * and point map.
 */
import type { Island } from '@exulanica/atlas-core';
import * as pc from 'playcanvas';
import type { PlacedScenePointMap } from './scene-point-maps.js';

/**
 * The presentation transform, and only the presentation transform.
 *
 * Islands are never pitched or rolled, so the up vector stays globally shared. That is why this
 * writes a single yaw rather than a quaternion: a quaternion would make an illegal orientation
 * representable, and atlas-core deliberately does not offer one.
 */
export function applyPlacement(entity: pc.Entity, island: Island): void {
  const p = island.placement;
  entity.setLocalPosition(p.position.x, p.position.y, p.position.z);
  entity.setLocalEulerAngles(0, (p.yaw * 180) / Math.PI, 0);
  entity.setLocalScale(p.scale, p.scale, p.scale);
}

/** Convert the receipt's row-major affine transform into PlayCanvas local TRS. */
export function applyScenePointMapPlacement(entity: pc.Entity, value: PlacedScenePointMap): void {
  applySceneTransform(entity, value.sceneFromOpmRowMajor, value.localUnitsToSceneUnits);
}

/** A row-major affine transform as PlayCanvas local position, rotation and uniform scale. */
export function applySceneTransform(entity: pc.Entity, m: readonly number[], scale: number): void {
  const rotation = new pc.Mat4().set([
    m[0]! / scale, m[4]! / scale, m[8]! / scale, 0,
    m[1]! / scale, m[5]! / scale, m[9]! / scale, 0,
    m[2]! / scale, m[6]! / scale, m[10]! / scale, 0,
    0, 0, 0, 1,
  ]);
  entity.setLocalPosition(m[3]!, m[7]!, m[11]!);
  entity.setLocalRotation(new pc.Quat().setFromMat4(rotation));
  entity.setLocalScale(scale, scale, scale);
}
