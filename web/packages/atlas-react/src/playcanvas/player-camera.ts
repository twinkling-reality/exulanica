import type { OwnedDistrict } from '@exulanica/atlas-core';
import type { CameraState } from './controls.js';
import { buildingRayDistance } from './district-surfaces.js';

export type PlayerCameraMode = 'first-person' | 'third-person';

/** Camera boom only; the caller retains the authoritative player pose. */
export function playerCameraPosition(
  player: CameraState,
  mode: PlayerCameraMode,
  district?: OwnedDistrict,
  requestedDistance = 3.8,
): readonly [number, number, number] {
  if (mode === 'first-person') return [player.x, player.y, player.z];
  const forward = [
    -Math.sin(player.yaw) * Math.cos(player.pitch),
    Math.sin(player.pitch),
    -Math.cos(player.yaw) * Math.cos(player.pitch),
  ];
  const start = [
    player.x,
    player.y +
      (requestedDistance < 1.2 ? -0.03 : requestedDistance < 3 ? -0.6 : 0.25),
    player.z,
  ];
  const direction = [-forward[0]!, -forward[1]!, -forward[2]!];
  let distance = Math.max(0.65, Math.min(6, requestedDistance));
  // Four padded parallel probes stop the near plane clipping a building corner.
  for (const building of district?.buildings ?? []) {
    for (const [dx, dz] of [
      [0, 0],
      [0.25, 0],
      [-0.25, 0],
      [0, 0.25],
      [0, -0.25],
    ]) {
      const hit = buildingRayDistance(
        building,
        [start[0]! + dx!, start[1]!, start[2]! + dz!],
        direction,
      );
      if (hit !== null) distance = Math.min(distance, Math.max(0, hit - 0.3));
    }
  }
  if (direction[1]! < 0)
    distance = Math.min(
      distance,
      Math.max(0, (start[1]! - 0.25) / -direction[1]!),
    );
  return [
    start[0]! + direction[0]! * distance,
    start[1]! + direction[1]! * distance,
    start[2]! + direction[2]! * distance,
  ];
}
