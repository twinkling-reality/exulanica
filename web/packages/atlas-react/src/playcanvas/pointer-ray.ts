/**
 * The ray from the displayed camera through a point of the page: what a click on the world picks
 * before the person looks around. It is cast in the same world frame as the binding's reticle ray
 * (`interactionRay`), whose origin carries the render origin the camera is drawn relative to.
 */
import * as pc from 'playcanvas';

/** What the ray needs of a world binding: its camera, its canvas and its reticle ray. */
export interface PointerRaySource {
  readonly camera: pc.Entity;
  readonly app: { readonly graphicsDevice: { readonly canvas: unknown } };
  interactionRay(): { origin: readonly [number, number, number]; direction: readonly [number, number, number] };
}

export type WorldRay = { readonly origin: readonly [number, number, number]; readonly direction: readonly [number, number, number] };

/** The ray through a page point, or null while the camera draws nothing there. */
export function pointerRay(source: PointerRaySource, clientX: number, clientY: number): WorldRay | null {
  const camera = source.camera.camera;
  const canvas = source.app.graphicsDevice.canvas;
  if (!camera || !(canvas instanceof HTMLCanvasElement)) return null;
  const rect = canvas.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  const x = clientX - rect.left;
  const y = clientY - rect.top;
  const near = camera.screenToWorld(x, y, camera.nearClip, new pc.Vec3());
  const far = camera.screenToWorld(x, y, camera.farClip, new pc.Vec3());
  const direction = far.clone().sub(near).normalize();
  // The reticle ray starts at the camera's position plus the render origin: the same offset here.
  const centre = source.interactionRay().origin;
  const at = source.camera.getPosition();
  const offset = [centre[0] - at.x, centre[1] - at.y, centre[2] - at.z] as const;
  return {
    origin: [near.x + offset[0], near.y + offset[1], near.z + offset[2]],
    direction: [direction.x, direction.y, direction.z],
  };
}
