import {
  atlasVec3,
  isNavigationPositionClear,
  localDirectionToAtlas,
  localToAtlas,
  type AtlasScene,
  type Island,
  type LocalVec3,
  type NavigationWorld,
  type OwnedDistrict,
} from '@exulanica/atlas-core';
import type { CameraHold, CameraState } from './controls.js';
import { worldViews, type WorldKind } from './world-kind.js';

/*
 * WHERE A WORLD PUTS THE CAMERA, AND WHAT HOLDS IT THERE.
 *
 * A view is a pose and a hold (`CameraHold` in controls.ts). The pose says where the camera is; the
 * hold says what keeps it there on the frames after: `ground` stands it on the world's walking
 * surface, `altitude` keeps the height the view gave it. Setting a pose without its hold is how a
 * city overview used to fall back to street height on the next frame: the controls grounded every
 * pose they were handed.
 */

/** The two city views a world with `worldViews(kind).cityViews` offers. */
export type CityView = 'overview' | 'street';

/** What each city view names: a view from above, and a stance on the street. */
export const CITY_VIEW_HOLD: Readonly<Record<CityView, CameraHold>> = Object.freeze({
  overview: 'altitude',
  street: 'ground',
});

export interface HeldView {
  readonly pose: CameraState;
  readonly hold: CameraHold;
}

/**
 * The pose and hold of a city view in this kind of world, or null where the kind offers no city
 * views (the app offers the controls only where this is not null, through `worldViews`).
 *
 * Street level is where the world stands a person on its ground (`groundEntry`), so it is always
 * inside the walkable field. The overview frames what the world is built around: a district's
 * buildings, or otherwise the walkable field and the regions on it.
 */
export function cityView(
  kind: WorldKind,
  view: CityView,
  scene: AtlasScene,
  navigationWorld: NavigationWorld,
): HeldView | null {
  if (!worldViews(kind).cityViews) return null;
  const pose = view === 'overview'
    ? overviewOf(kind, navigationWorld)
    : groundEntry(kind, scene, navigationWorld);
  return Object.freeze({ pose, hold: CITY_VIEW_HOLD[view] });
}

/** Where the session opens: the overview for a kind that opens from above, else its ground entry. */
export function worldStart(kind: WorldKind, scene: AtlasScene, navigationWorld: NavigationWorld): HeldView {
  return kind.aerialStart
    ? Object.freeze({ pose: overviewOf(kind, navigationWorld), hold: CITY_VIEW_HOLD.overview })
    : Object.freeze({ pose: groundEntry(kind, scene, navigationWorld), hold: CITY_VIEW_HOLD.street });
}

function overviewOf(kind: WorldKind, navigationWorld: NavigationWorld): CameraState {
  return kind.ground.form === 'owned-district'
    ? ownedDistrictOverviewCameraState(kind.ground.district.document)
    : fieldOverviewCameraState(navigationWorld);
}

/**
 * Where this kind of world stands a person on its ground: its spawn, its district's clear spawn,
 * its tile's stated start, or the first region's own viewpoint. Street level is this pose.
 */
export function groundEntry(kind: WorldKind, scene: AtlasScene, navigationWorld: NavigationWorld): CameraState {
  const ground = kind.ground;
  switch (ground.form) {
    case 'generated-tile':
      return { ...ground.tile.start };
    case 'owned-district':
      return ownedDistrictCameraState(navigationWorld, ground.district.document);
    case 'authored-endless':
    case 'authored-flat': {
      const spawn = ground.region.spawn;
      return {
        x: spawn.xMm / 1000,
        y: spawn.yMm / 1000 + navigationWorld.eyeHeight,
        z: spawn.zMm / 1000,
        yaw: spawn.yawMicroradians / 1_000_000,
        pitch: 0,
      };
    }
    case 'scene-regions':
      return initialAtlasCameraState(scene, navigationWorld);
  }
  throw new TypeError(`No ground entry for a world standing on ${(ground as { form: string }).form}`);
}

/**
 * Where a session opens.
 *
 * The upward framing is gone with the body it framed. This used to pitch the opening camera up at
 * the source veil hanging 3.45 metres over the region, which is the one thing that made an opening
 * shot point at empty air once the veil was removed. A region now opens level, looking at its own
 * ground, where its landmark stands.
 */
export function initialAtlasCameraState(
  scene: AtlasScene,
  navigationWorld: NavigationWorld,
): CameraState {
  const first = scene.islands[0];
  if (first !== undefined && first.rung !== 4 && first.viewpointForwardLocal !== undefined) {
    // A reconstructed region arrives where its first photograph was taken, looking where that
    // camera looked. The display frame put the recovered cameras at eye height, so this is a
    // standing viewpoint, and the first frame is the first photograph's view of the geometry.
    return recoveredCameraState(first, first.viewpointLocal, first.viewpointForwardLocal);
  }
  return first === undefined
    ? {
        x: navigationWorld.centre.x,
        y: (navigationWorld.surface.sample(
          navigationWorld.centre.x,
          navigationWorld.centre.z + 10,
        )?.height ?? 0) + navigationWorld.eyeHeight,
        z: navigationWorld.centre.z + 10,
        yaw: 0,
        pitch: -0.085,
      }
    : (() => {
        const distance = Math.max(3.6, Math.min(4.4, first.footprintRadiusLocal * 0.22));
        const x = first.placement.position.x + Math.sin(first.placement.yaw) * distance;
        const z = first.placement.position.z + Math.cos(first.placement.yaw) * distance;
        const height = navigationWorld.surface.sample(x, z)?.height ?? 0;
        return { x, y: height + navigationWorld.eyeHeight, z, yaw: first.placement.yaw, pitch: -0.085 };
      })();
}

/**
 * How an overview frames a ground area: the district overview's framing, which every overview
 * shares so that a field is framed the way a district is. Distances in metres, as fractions of
 * the framed span or of the tallest building.
 */
const OVERVIEW_FRAMING = Object.freeze({
  /** The narrowest span framed, so a single small building or an empty field is not filled edge to edge. */
  minimumSpan: 80,
  /** The camera stands back this fraction of the span, and this fraction of that to one side. */
  standoff: 0.9,
  sideways: 0.28,
  /** Height: at least this, above the tallest building by this factor, and rising with the span. */
  minimumHeight: 65,
  aboveTallest: 1.18,
  heightPerSpan: 0.52,
  /** The point looked at: this fraction of the tallest building's height, capped. */
  aimFraction: 0.28,
  maximumAim: 24,
});

/** An overview of a ground area centred at (targetX, targetZ), `span` metres across. */
function framedOverview(targetX: number, targetZ: number, span: number, tallest: number): CameraState {
  const framing = OVERVIEW_FRAMING;
  const framed = Math.max(framing.minimumSpan, span);
  const horizontal = framed * framing.standoff;
  const x = targetX + horizontal * framing.sideways;
  const y = Math.max(framing.minimumHeight, tallest * framing.aboveTallest, framed * framing.heightPerSpan);
  const z = targetZ + horizontal;
  const targetY = Math.min(framing.maximumAim, tallest * framing.aimFraction);
  const dx = targetX - x;
  const dz = targetZ - z;
  return {
    x, y, z,
    yaw: Math.atan2(-dx, -dz),
    pitch: Math.atan2(targetY - y, Math.hypot(dx, dz)),
  };
}

/**
 * Frame the actual admitted district rather than assuming its local origin is Manhattan: its
 * buildings, or its own bounds when it has none.
 */
export function ownedDistrictOverviewCameraState(district: OwnedDistrict): CameraState {
  if (district.buildings.length === 0) {
    const [west, north, east, south] = district.bounds_cm.map((value) => value / 100) as [
      number, number, number, number,
    ];
    return framedOverview((west + east) / 2, (north + south) / 2, Math.max(east - west, south - north), 0);
  }
  const west = Math.min(...district.buildings.map((building) => building.bbox_cm[0] / 100));
  const north = Math.min(...district.buildings.map((building) => building.bbox_cm[1] / 100));
  const east = Math.max(...district.buildings.map((building) => building.bbox_cm[2] / 100));
  const south = Math.max(...district.buildings.map((building) => building.bbox_cm[3] / 100));
  const tallest = Math.max(...district.buildings.map((building) => building.height_cm / 100));
  return framedOverview((west + east) / 2, (north + south) / 2, Math.max(east - west, south - north), tallest);
}

/**
 * Frame the walkable field's centre and every region on it. The field's own radius is not the
 * span: an endless starter's field reaches kilometres, and an overview of that shows nothing.
 */
export function fieldOverviewCameraState(world: NavigationWorld): CameraState {
  let reach = 0;
  for (const region of world.regions) {
    reach = Math.max(reach, Math.hypot(region.centre.x - world.centre.x, region.centre.z - world.centre.z)
      + region.footprintRadius);
  }
  return framedOverview(world.centre.x, world.centre.z, 2 * reach, 0);
}

/** Deterministic clear spawn on visible owned support, never an invisible safety floor. */
export function ownedDistrictCameraState(
  world: NavigationWorld,
  district?: OwnedDistrict,
): CameraState {
  const landmark = district?.buildings
    .filter((building) => building.name !== null)
    .map((building) => {
      const width = Math.max(1, building.bbox_cm[2] - building.bbox_cm[0]);
      const depth = Math.max(1, building.bbox_cm[3] - building.bbox_cm[1]);
      const slenderness = Math.max(width, depth) / Math.min(width, depth);
      return { building, score: building.height_cm * slenderness };
    })
    .sort((a, b) => b.score - a.score || a.building.id.localeCompare(b.building.id))[0]?.building;
  if (landmark !== undefined) {
    const [west, north, east, south] = landmark.bbox_cm.map((value) => value / 100) as [
      number, number, number, number,
    ];
    const targetX = (west + east) / 2;
    const targetZ = (north + south) / 2;
    for (const [offsetX, offsetZ] of [
      [0, -45], [-38, -34], [38, -34], [-48, 34], [46, 36],
    ] as const) {
      const x = targetX + offsetX;
      const z = targetZ + offsetZ;
      const position = atlasVec3(x, world.eyeHeight, z);
      if (
        isNavigationPositionClear(world, position) &&
        world.surface.sample(x - 3, z) !== null &&
        world.surface.sample(x + 3, z) !== null &&
        world.surface.sample(x, z - 3) !== null &&
        world.surface.sample(x, z + 3) !== null
      ) {
        return {
          x,
          y: world.eyeHeight,
          z,
          yaw: Math.atan2(-(targetX - x), -(targetZ - z)),
          pitch: 0.08,
        };
      }
    }
  }
  const segmentDistance = (
    x: number,
    z: number,
    ax: number,
    az: number,
    bx: number,
    bz: number,
  ): number => {
    const dx = bx - ax;
    const dz = bz - az;
    const denominator = dx * dx + dz * dz;
    const t = denominator === 0
      ? 0
      : Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / denominator));
    return Math.hypot(x - (ax + dx * t), z - (az + dz * t));
  };
  let best: { x: number; z: number; score: number } | null = null;
  const extent = Math.min(340, Math.ceil(world.fieldRadius));
  for (let z = world.centre.z - extent; z <= world.centre.z + extent; z += 10) {
    for (let x = world.centre.x - extent; x <= world.centre.x + extent; x += 10) {
      const position = atlasVec3(x, world.eyeHeight, z);
      if (
        !isNavigationPositionClear(world, position) ||
        world.surface.sample(x - 8, z) === null ||
        world.surface.sample(x + 8, z) === null ||
        world.surface.sample(x, z - 8) === null ||
        world.surface.sample(x, z + 8) === null
      ) continue;
      let clearance = 60;
      for (const obstacle of world.polygonObstacles ?? []) {
        for (const ring of obstacle.rings) {
          for (let index = 1; index < ring.length; index += 1) {
            const a = ring[index - 1]!;
            const b = ring[index]!;
            clearance = Math.min(clearance, segmentDistance(x, z, a.x, a.z, b.x, b.z));
          }
        }
      }
      const score = clearance - Math.hypot(x - world.centre.x, z - world.centre.z) * 0.015;
      if (best === null || score > best.score) best = { x, z, score };
    }
  }
  if (best !== null) {
    const dx = world.centre.x - best.x;
    const dz = world.centre.z - best.z;
    return {
      x: best.x,
      y: world.eyeHeight,
      z: best.z,
      yaw: Math.atan2(-dx, -dz),
      pitch: -0.045,
    };
  }
  return {
    x: world.centre.x,
    y: world.eyeHeight,
    z: world.centre.z,
    yaw: 0,
    pitch: 0,
  };
}

/** The controls' pose at a recovered camera: forward is (-sin yaw, 0, -cos yaw), pitch positive up. */
export function recoveredCameraState(island: Island, viewpointLocal: LocalVec3, forwardLocal: LocalVec3): CameraState {
  const position = localToAtlas(island.placement, viewpointLocal);
  const forward = localDirectionToAtlas(island.placement, forwardLocal);
  const horizontal = Math.hypot(forward.x, forward.z);
  return {
    x: position.x,
    y: position.y,
    z: position.z,
    yaw: horizontal < 1e-9 ? island.placement.yaw : Math.atan2(-forward.x, -forward.z),
    pitch: Math.max(-1.3, Math.min(1.3, Math.atan2(forward.y, horizontal))),
  };
}
