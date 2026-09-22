/**
 * A depth estimate from one of your own photographs, drawn where you put it in your own world.
 *
 * This is the renderer half of the photo point map composition kind. It reuses the machinery a
 * scene's unmeasured fan already uses (`createPointCloud` with `surface`, `enableSingleView`, the
 * per-frame relief flattening) and differs from it in four ways, each of which is a decision:
 *
 * **It hangs on the authored region root, not on an island.** An authored starter world has no
 * capture-backed island and no Atlas placement, so nothing here asks for one. The ground is the
 * region's own flat plane, which is why the print depth below is a closed form rather than the
 * hundred-step search a sampled navigation surface needs.
 *
 * **It is drawn and nothing else.** Nothing here touches navigation or collision. An estimate is a
 * model's reading of a room from one photograph; walking into it as though it were a wall would be
 * the renderer asserting a spatial fact nobody measured. A visitor passes through it.
 *
 * **An unavailable instance draws nothing.** Not a placeholder, not a box, not a grey card. The
 * whole reason this kind exists is that a person can stop it, and something drawn where their
 * estimate used to be would be the system keeping a shape of their home after they said no.
 *
 * **The bytes were verified before they got here.** This module takes a decoded `PointMap`. The
 * digest check against the descriptor that named it belongs to the geometry client, and a module
 * that accepted a URL would be a second, weaker door to the same bytes.
 */

import * as pc from 'playcanvas';
import type { PointMap } from './opm.js';
import {
  createPointCloud,
  reliefFor,
  singleViewDepths,
  type PointCloud,
} from './point-cloud.js';
import { defaultSemanticsFor } from './semantics.js';
import type { PresentationTheme } from '@exulanica/presentation';

/** Fixed-point placement, in the units the authored world stores and the server validates. */
export interface AuthoredTransform {
  readonly xMm: number;
  readonly yMm: number;
  readonly zMm: number;
  readonly yawMicroradians: number;
  readonly scaleMilli: number;
}

export interface AuthoredPointMapPlacement {
  readonly instanceId: string;
  /** Decoded and digest-verified by the caller. */
  readonly map: PointMap;
  readonly transform: AuthoredTransform;
  /** The attachment's verified viewer image, upright, to colour the surface with. */
  readonly photograph?: ImageBitmap;
}

export interface AuthoredPointMapVisual {
  readonly instanceId: string;
  readonly entity: pc.Entity;
  readonly cloud: PointCloud;
  /** The photograph's own camera, in world space, once the entity is in the scene graph. */
  readonly cameraWorld: pc.Vec3;
  /** The print plane's centre, in world space. */
  readonly printWorld: pc.Vec3;
  readonly parallaxPerUnit: number;
  readonly printDepth: number;
}

export interface AuthoredPointMaps {
  readonly visuals: readonly AuthoredPointMapVisual[];
  /** Flatten each relief for where the visitor is now. Call once per drawn frame. */
  frame(viewer: Readonly<{ x: number; y: number; z: number }>): void;
  setTheme(theme: PresentationTheme): void;
  destroy(): void;
}

export interface AuthoredPointMapOptions {
  readonly device: pc.GraphicsDevice;
  /** The authored region's root entity, already positioned at the region's ground elevation. */
  readonly root: pc.Entity;
  readonly placements: readonly AuthoredPointMapPlacement[];
  readonly theme?: PresentationTheme;
  readonly sizeGain?: number;
  readonly maxSizePx?: number;
}

/**
 * The deepest a print can stand, up to ``wanted``, without its lower edge going under flat ground.
 *
 * The scene-point-map path searches a sampled navigation surface for this because its ground is a
 * mesh. An authored region's ground is one horizontal plane at the region root's own origin, so
 * the answer is arithmetic: the frame's lower edge at depth d sits ``d * tan(fovY/2) * scale``
 * below the camera, and the camera sits ``eyeHeight`` above the plane.
 *
 * Returns 0 when the camera is at or below the ground, which draws the print flat against the
 * standpoint rather than buried: an estimate that cannot stand is still the person's placement,
 * and moving it is theirs to do.
 */
export function printDepthOnFlatGround(
  map: PointMap,
  eyeHeight: number,
  scale: number,
  wanted: number,
): number {
  const { fovYDeg } = map.header.viewpoint;
  // The container validator's own open range, not a test on the tangent. `Math.tan` of a right
  // angle is 1.6e16 rather than Infinity, so a 180 degree field passed a finite-tangent guard and
  // came back as a print 1e-16 deep. Nothing in the product can get here: `validate_opm` refuses
  // a field outside [1, 179) and the server refuses one outside the same range again. This is the
  // boundary restated where the arithmetic happens, so the arithmetic cannot be asked a question
  // it has no answer to.
  if (!(fovYDeg > 0) || !(fovYDeg < 179) || !(scale > 0)) return wanted;
  const tanY = Math.tan((fovYDeg * Math.PI) / 360);
  if (!(eyeHeight > 0)) return 0;
  return Math.min(wanted, eyeHeight / (tanY * scale));
}

/**
 * The entity transform one authored placement asks for: T R_y S, and nothing else.
 *
 * Yaw only. A placed estimate is a photograph's own view standing in a room, and pitch or roll
 * would tip a print whose whole geometry is defined from the camera that took it. The fixed-point
 * wire units are divided here, once, so no caller divides them again by a different thousand.
 */
export function authoredPlacementTransform(transform: AuthoredTransform): {
  readonly position: readonly [number, number, number];
  readonly yawDegrees: number;
  readonly scale: number;
} {
  return {
    position: [transform.xMm / 1000, transform.yMm / 1000, transform.zMm / 1000],
    yawDegrees: (transform.yawMicroradians / 1_000_000) * (180 / Math.PI),
    scale: transform.scaleMilli / 1000,
  };
}

/**
 * Place each estimate under ``root``.
 *
 * The transform is T R_y S, which is the whole of what an authored placement may say. The OPM
 * viewpoint is the source camera at the container's own origin, so the standpoint the person chose
 * IS the entity's position: no extra translation is composed, and none may be, because a
 * placement that moved the camera away from the origin would put the print somewhere the person
 * did not put it.
 */
export function createAuthoredPointMaps(options: AuthoredPointMapOptions): AuthoredPointMaps {
  const { device, root } = options;
  const visuals: AuthoredPointMapVisual[] = [];
  for (const placed of options.placements) {
    const entity = new pc.Entity(`authored-point-map:${placed.instanceId}`);
    const { position, yawDegrees, scale } = authoredPlacementTransform(placed.transform);
    entity.setLocalPosition(position[0], position[1], position[2]);
    entity.setLocalEulerAngles(0, yawDegrees, 0);
    entity.setLocalScale(scale, scale, scale);

    const cloud = createPointCloud({
      device,
      map: placed.map,
      semantics: defaultSemanticsFor(placed.map.header),
      ...(options.sizeGain === undefined ? {} : { sizeGain: options.sizeGain }),
      ...(options.maxSizePx === undefined ? {} : { maxSizePx: options.maxSizePx }),
      // One photograph's own view reads as its surface rather than as dots, which is the whole
      // difference between "a picture of my kitchen" and "some points".
      surface: true,
      ...(placed.photograph === undefined ? {} : { photograph: placed.photograph }),
      ...(options.theme === undefined ? {} : { theme: options.theme }),
    });
    const instance = new pc.MeshInstance(cloud.mesh, cloud.material, entity);
    entity.addComponent('render', { meshInstances: [instance] });
    root.addChild(entity);

    const depths = singleViewDepths(placed.map);
    const printDepth = printDepthOnFlatGround(placed.map, position[1], scale, depths.median);
    const eye = cloud.enableSingleView(printDepth);
    const cameraWorld = entity.getWorldTransform().transformPoint(
      new pc.Vec3(eye[0], eye[1], eye[2]),
      new pc.Vec3(),
    );
    const printWorld = entity.getWorldTransform().transformPoint(
      new pc.Vec3(eye[0], eye[1], eye[2] - printDepth),
      new pc.Vec3(),
    );
    visuals.push({
      instanceId: placed.instanceId,
      entity,
      cloud,
      cameraWorld,
      printWorld,
      // The same quantity the scene path measures: how fast parallax grows with distance walked.
      parallaxPerUnit: (1 / depths.nearest - 1 / depths.furthest) / scale,
      printDepth,
    });
  }

  return {
    visuals,
    frame(viewer) {
      for (const visual of visuals) {
        visual.cloud.setCaptureWorld(
          visual.cameraWorld.x,
          visual.cameraWorld.y,
          visual.cameraWorld.z,
        );
        const relief = reliefFor(
          visual.cameraWorld,
          visual.printWorld,
          viewer,
          visual.parallaxPerUnit,
        );
        visual.cloud.setRelief(relief.flatten, relief.behind);
      }
    },
    setTheme(theme) {
      for (const visual of visuals) visual.cloud.setTheme(theme);
    },
    destroy() {
      for (const visual of visuals) {
        visual.cloud.destroy();
        visual.entity.destroy();
      }
      visuals.length = 0;
    },
  };
}
