import { localToAtlas, localVec3, type Island, type IslandId } from '@exulanica/atlas-core';
import { opmPointInScene, validateScenePointMapPlacement, type PlacedScenePointMap } from './scene-point-maps.js';

type Vector = readonly [number, number, number];

/** An explicit camera presentation of the same Atlas, never a recovered walkable surface. */
export interface SceneInspectionView {
  readonly id: string;
  readonly sceneId: string;
  readonly islandId: IslandId;
  readonly kind: 'source-camera' | 'between-cameras';
  readonly artifactIds: readonly string[];
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
): readonly SceneInspectionView[] {
  const sources = maps.filter((map) => map.islandId === island.islandId).map((map) => {
    validateScenePointMapPlacement(map);
    const point = opmPointInScene(map, map.map.header.viewpoint.position);
    const position = localToAtlas(island.placement, localVec3(...point));
    return Object.freeze({
      id: `${map.sceneId}:camera:${map.artifactId}`,
      sceneId: map.sceneId,
      islandId: map.islandId,
      kind: 'source-camera' as const,
      artifactIds: Object.freeze([map.artifactId]),
      position: [position.x, position.y, position.z] as Vector,
      forward: directionInAtlas(island, map.sceneFromOpmRowMajor, [0, 0, -1]),
      up: directionInAtlas(island, map.sceneFromOpmRowMajor, [0, 1, 0]),
      fovYDeg: map.map.header.viewpoint.fovYDeg,
      sourceAspect: map.map.header.viewpoint.aspect,
    });
  });
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
      id: `${source.sceneId}:midpoint:${source.artifactIds[0]}:${next.artifactIds[0]}`,
      kind: 'between-cameras',
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
