// What stands in a camera's way in the world drawn now: how far a ray runs before the scene's static
// meshes, and whether nothing stands between two points. The moment preview (front-door-preview.ts) frames
// History's pictures by it and the follow view (scene-follow.ts) frames a talking scene by it.
import { StaticMeshPicker } from '../../../web/packages/atlas-react/src/playcanvas/index.ts';

/**
 * How far past a box's faces a ray still asks for its mesh, metres: a ray that grazes a face is asked, as
 * the picker's own box test asks it.
 */
const BOX_GRAZE = 1e-6;

/**
 * How far a ray (render space, metres, a unit direction) runs before it meets what the scene draws,
 * or Infinity, up to `most` metres. Tested against the triangles of every visible static mesh, a low
 * wall or a bench as much as a building; skinned and instanced meshes (people, scattered plants, a
 * painted splat) are not tested. A ray asks the picker for a mesh only where its segment, out to the
 * nearest surface met so far, passes through the mesh's world box as it is now (a mesh moved or placed
 * since, by build mode or on its way, where it is drawn): a box it misses holds nothing nearer, so the
 * answer is the one asking every mesh gives, while most of a town's meshes are passed by a few
 * comparisons (a talking scene's framing casts about 1,500 rays past some 500 meshes).
 */
export function sceneHit(app: any, picker: Pick<StaticMeshPicker, 'pick'> = new StaticMeshPicker()): (origin: readonly [number, number, number], direction: readonly [number, number, number], most?: number) => number {
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
      const limit = Math.min(most, nearest);
      if (!segmentMeetsBox(instance.aabb, origin, direction, limit)) continue;
      const hit = picker.pick(instance, origin, direction, limit);
      if (hit !== null && hit < nearest) nearest = hit;
    }
    return nearest;
  };
}

/** A world box as a mesh instance holds it: its middle and how far it reaches from it on each axis. */
type Box = { readonly center: { readonly x: number; readonly y: number; readonly z: number }; readonly halfExtents: { readonly x: number; readonly y: number; readonly z: number } };

/** The span of the segment segmentMeetsBox is narrowing, metres along it: kept here so a test allocates nothing. */
let spanNear = 0, spanFar = 0;

/**
 * Whether the segment from `origin` along `direction` out to `limit` passes through `box`, its faces
 * widened by BOX_GRAZE.
 */
function segmentMeetsBox(box: Box, origin: readonly [number, number, number], direction: readonly [number, number, number], limit: number): boolean {
  spanNear = 0;
  spanFar = limit;
  const { center, halfExtents } = box;
  return withinSlab(origin[0], direction[0], center.x, halfExtents.x)
    && withinSlab(origin[1], direction[1], center.y, halfExtents.y)
    && withinSlab(origin[2], direction[2], center.z, halfExtents.z);
}

/** One axis of segmentMeetsBox: the span narrowed to where the segment lies between the box's two faces on it; false where none is left. */
function withinSlab(start: number, step: number, middle: number, reach: number): boolean {
  const least = middle - reach - BOX_GRAZE, greatest = middle + reach + BOX_GRAZE;
  if (step === 0) return start >= least && start <= greatest;
  const a = (least - start) / step, b = (greatest - start) / step;
  spanNear = Math.max(spanNear, Math.min(a, b));
  spanFar = Math.min(spanFar, Math.max(a, b));
  return spanNear <= spanFar;
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
