import { localToAtlas, localVec3, type Island, type IslandId } from '@exulanica/atlas-core';
import type { RecoveredCameraCalibration, RecoveredCameraRecord } from '@exulanica/graph-client';
import { opmPointInScene, validateScenePointMapPlacement, validateSceneTransform, type PlacedScenePointMap } from './scene-point-maps.js';

type Vector = readonly [number, number, number];

/** Accepted pose identity, independent of depth or trained artifact availability. */
export interface RecoveredSceneCamera extends RecoveredCameraRecord {
  readonly sceneId: string;
  readonly islandId: IslandId;
  readonly captureId: string;
  readonly ordinal: number;
  readonly poseReceiptSha256: string;
}

export function validateRecoveredSceneCamera(value: RecoveredSceneCamera): void {
  validateSceneTransform(value.sceneFromCameraRowMajor, 1);
  const c = value.calibration;
  if (!Number.isSafeInteger(c.width) || !Number.isSafeInteger(c.height) || c.width <= 0 || c.height <= 0
    || ![c.fx, c.fy, c.cx, c.cy].every(Number.isFinite) || c.fx <= 0 || c.fy <= 0
    || !c.parameters.every(Number.isFinite) || !c.model
    || !Number.isSafeInteger(value.ordinal) || value.ordinal < 0 || !value.captureId
    || !/^[0-9a-f]{64}$/u.test(value.poseReceiptSha256)
    || !['pinhole', 'pinhole-approximation'].includes(value.projection)) {
    throw new TypeError('Recovered camera calibration or accepted pose identity is invalid');
  }
}

/** Actual pinhole calibration with vertical pixel fit; wider canvases expose more horizontally. */
export function calibratedCameraFrustum(c: RecoveredCameraCalibration, canvasAspect: number, near: number) {
  const halfWidth = canvasAspect * c.height / 2;
  return {
    left: (c.width / 2 - c.cx - halfWidth) * near / c.fx,
    right: (c.width / 2 - c.cx + halfWidth) * near / c.fx,
    bottom: (c.cy - c.height) * near / c.fy,
    top: c.cy * near / c.fy,
  };
}

/** An explicit camera presentation of the same Atlas, never a recovered walkable surface. */
export interface SceneInspectionView {
  readonly id: string;
  readonly sceneId: string;
  readonly islandId: IslandId;
  readonly kind: 'source-camera' | 'between-cameras';
  readonly artifactIds: readonly string[];
  readonly captureIds: readonly string[];
  readonly poseReceiptSha256: string | null;
  readonly calibration: RecoveredCameraCalibration | null;
  readonly projection: 'pinhole' | 'pinhole-approximation' | 'opm-estimate' | 'interpolated';
  readonly position: Vector;
  readonly forward: Vector;
  readonly up: Vector;
  readonly fovYDeg: number;
  readonly sourceAspect: number;
}

function unit(v: Vector): Vector | null {
  const length = Math.hypot(...v);
  return length < 1e-8 ? null : [v[0] / length, v[1] / length, v[2] / length];
}

function directionInAtlas(island: Island, m: readonly number[], v: Vector): Vector {
  const x = m[0]! * v[0] + m[1]! * v[1] + m[2]! * v[2];
  const y = m[4]! * v[0] + m[5]! * v[1] + m[6]! * v[2];
  const z = m[8]! * v[0] + m[9]! * v[1] + m[10]! * v[2];
  const c = Math.cos(island.placement.yaw);
  const s = Math.sin(island.placement.yaw);
  return unit([c * x + s * z, y, -s * x + c * z])!;
}

/** Source cameras and consecutive midpoints use immutable member order, not a pleasing view search. */
export function sceneInspectionViews(
  island: Island,
  maps: readonly PlacedScenePointMap[],
  recovered: readonly RecoveredSceneCamera[] = [],
): readonly SceneInspectionView[] {
  const cameras = recovered.filter((camera) => camera.islandId === island.islandId)
    .sort((left, right) => left.ordinal - right.ordinal);
  const recoveredScenes = new Set(cameras.map((camera) => camera.sceneId));
  const sources: SceneInspectionView[] = cameras.map((camera) => {
    validateRecoveredSceneCamera(camera);
    const m = camera.sceneFromCameraRowMajor;
    const position = localToAtlas(island.placement, localVec3(m[3]!, m[7]!, m[11]!));
    return Object.freeze({
      id: `${camera.sceneId}:camera:${camera.captureId}`, sceneId: camera.sceneId,
      islandId: camera.islandId, kind: 'source-camera' as const,
      captureIds: Object.freeze([camera.captureId]), poseReceiptSha256: camera.poseReceiptSha256,
      artifactIds: Object.freeze(maps.filter((map) => map.sceneId === camera.sceneId && map.captureId === camera.captureId)
        .map((map) => map.artifactId)), calibration: camera.calibration, projection: camera.projection,
      position: [position.x, position.y, position.z] as Vector,
      forward: directionInAtlas(island, m, [0, 0, -1]), up: directionInAtlas(island, m, [0, 1, 0]),
      fovYDeg: 2 * Math.atan(camera.calibration.height / (2 * camera.calibration.fy)) * 180 / Math.PI,
      sourceAspect: camera.calibration.width / camera.calibration.height,
    });
  });
  sources.push(...maps.filter((map) => !recoveredScenes.has(map.sceneId)).filter((map) => map.islandId === island.islandId).map((map) => {
    validateScenePointMapPlacement(map);
    const point = opmPointInScene(map, map.map.header.viewpoint.position);
    const position = localToAtlas(island.placement, localVec3(...point));
    return Object.freeze({
      id: `${map.sceneId}:camera:${map.artifactId}`,
      sceneId: map.sceneId,
      islandId: map.islandId,
      kind: 'source-camera' as const,
      artifactIds: Object.freeze([map.artifactId]),
      captureIds: Object.freeze(map.captureId === undefined ? [] : [map.captureId]),
      poseReceiptSha256: null, calibration: null, projection: 'opm-estimate' as const,
      position: [position.x, position.y, position.z] as Vector,
      forward: directionInAtlas(island, map.sceneFromOpmRowMajor, [0, 0, -1]),
      up: directionInAtlas(island, map.sceneFromOpmRowMajor, [0, 1, 0]),
      fovYDeg: map.map.header.viewpoint.fovYDeg,
      sourceAspect: map.map.header.viewpoint.aspect,
    });
  }));
  const views: SceneInspectionView[] = [];
  for (let index = 0; index < sources.length; index += 1) {
    const source = sources[index]!;
    views.push(source);
    const next = sources[index + 1];
    if (next === undefined || next.sceneId !== source.sceneId) continue;
    const forward = unit(source.forward.map((v, i) => v + next.forward[i]!) as unknown as Vector);
    const upSeed = unit(source.up.map((v, i) => v + next.up[i]!) as unknown as Vector);
    // Opposing camera directions do not define an unambiguous intermediate viewing direction.
    if (forward === null || upSeed === null) continue;
    const dot = forward.reduce((sum, v, i) => sum + v * upSeed[i]!, 0);
    const up = unit(upSeed.map((v, i) => v - dot * forward[i]!) as unknown as Vector);
    if (up === null) continue;
    views.push(Object.freeze({
      ...source,
      id: `${source.sceneId}:midpoint:${source.captureIds[0] ?? source.artifactIds[0]}:${next.captureIds[0] ?? next.artifactIds[0]}`,
      kind: 'between-cameras',
      captureIds: Object.freeze([...source.captureIds, ...next.captureIds]),
      calibration: null, projection: 'interpolated',
      artifactIds: Object.freeze([...source.artifactIds, ...next.artifactIds]),
      position: source.position.map((v, i) => (v + next.position[i]!) / 2) as unknown as Vector,
      forward,
      up,
      fovYDeg: (source.fovYDeg + next.fovYDeg) / 2,
      sourceAspect: (source.sourceAspect + next.sourceAspect) / 2,
    }));
  }
  return Object.freeze(views);
}
