// What stands in a camera's way in the world drawn now: how far a ray runs before the scene's static
// meshes, and whether nothing stands between two points. The moment preview (front-door-preview.ts) frames
// History's pictures by it and the follow view (scene-follow.ts) frames a talking scene by it.
import { StaticMeshPicker } from '../../../web/packages/atlas-react/src/playcanvas/index.ts';

/**
 * How far a ray (render space, metres, a unit direction) runs before it meets what the scene draws,
 * or Infinity, up to `most` metres. Tested against the triangles of every visible static mesh, a low
 * wall or a bench as much as a building; skinned and instanced meshes (people, scattered plants, a
 * painted splat) are not tested.
 */
export function sceneHit(app: any): (origin: readonly [number, number, number], direction: readonly [number, number, number], most?: number) => number {
  const picker = new StaticMeshPicker();
  const instances = new Set<any>();
  for (const layer of app.scene?.layers?.layerList ?? []) {
    if (layer.name === 'UI' || layer.name === 'Skybox' || layer.name === 'Immediate') continue;
    for (const instance of layer.meshInstances ?? []) {
      if (instance.instancingCount > 0 || instance.gsplatInstance || instance.skinInstance) continue;
      instances.add(instance);
    }
  }
  return (origin, direction, most = Infinity) => {
    let nearest = Infinity;
    for (const instance of instances) {
      const hit = picker.pick(instance, origin, direction, Math.min(most, nearest));
      if (hit !== null && hit < nearest) nearest = hit;
    }
    return nearest;
  };
}

/**
 * Whether nothing the scene draws stands between `from` and `to` (render space, metres), short of
 * the last `own` metres before `to`, where the subject's own body is.
 */
export function sceneSight(hit: ReturnType<typeof sceneHit>, own: number): (from: { x: number; y: number; z: number }, to: { x: number; y: number; z: number }) => boolean {
  return (from, to) => {
    const along = [to.x - from.x, to.y - from.y, to.z - from.z] as const;
    const length = Math.hypot(...along);
    if (length <= own) return true;
    const limit = length - own;
    return !(hit([from.x, from.y, from.z], [along[0] / length, along[1] / length, along[2] / length], limit) < limit);
  };
}
