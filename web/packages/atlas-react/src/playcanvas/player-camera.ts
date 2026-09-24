import type { OwnedDistrict } from '@exulanica/atlas-core';
import type { CameraState } from './controls.js';
import { buildingRayDistance } from './district-surfaces.js';

export type PlayerCameraMode = 'first-person' | 'third-person';

/**
 * Every number the follow camera has an opinion about, in one place.
 *
 * Framing is data rather than constants in the solver because it is the part most likely to be
 * retuned, and retuning should not mean editing geometry code. A caller that wants an
 * over-the-shoulder shot sets `lateralOffset`; one that wants a rigid boom sets `extendSeconds`
 * to zero. Nothing else has to change.
 */
export interface FollowCameraTuning {
  /** Boom length in metres before obstruction and ground clamping. */
  readonly distance: number;
  /**
   * Where the camera looks, as a fraction of standing height above the feet.
   *
   * The camera is placed by stepping backwards from this point and is then given the player's own
   * yaw and pitch, so whatever this resolves to is exactly what screen centre lands on. Aiming
   * above the head is not a framing preference, it is a bug: it points the reticle at empty air
   * and pushes the whole figure into the lower half of the frame.
   */
  readonly aimFraction: number;
  /** Closer than `portraitDistance` the shot is a portrait, so it frames the head instead. */
  readonly portraitAimFraction: number;
  readonly portraitDistance: number;
  /** Metres to the camera's right. Zero keeps the player on the screen's centre line. */
  readonly lateralOffset: number;
  /** The boom never drops closer than this to the ground under the person while looking up. */
  readonly groundClearance: number;
  /** Slack left between the near plane and a building the boom has backed into. */
  readonly collisionPadding: number;
  /**
   * How close the boom may be driven to the aim point by an obstruction.
   *
   * A facade can shorten the boom past the body, and a camera at zero sits inside the head looking
   * at the back of its own face. Stopping short of the body is half the answer; the caller hides
   * the avatar below `avatarFadeDistance` for the other half.
   */
  readonly minimumDistance: number;
  /** Below this resolved boom length the drawn player is in the way rather than in the shot. */
  readonly avatarFadeDistance: number;
  /**
   * How long the boom takes to reach back out after an obstruction clears.
   *
   * It collapses immediately, because a camera that eases into a wall shows the inside of one.
   * Coming back out is the half that reads as a snap if it is not smoothed.
   */
  readonly extendSeconds: number;
}

export const DEFAULT_FOLLOW_CAMERA: FollowCameraTuning = Object.freeze({
  distance: 3.8,
  aimFraction: 0.82,
  portraitAimFraction: 0.94,
  portraitDistance: 1.2,
  lateralOffset: 0,
  groundClearance: 0.25,
  collisionPadding: 0.3,
  minimumDistance: 0.35,
  avatarFadeDistance: 0.6,
  extendSeconds: 0.35,
});

const MINIMUM_DISTANCE = 0.65;
const MAXIMUM_DISTANCE = 6;

export function playerCameraAimHeight(
  groundY: number,
  standingHeight: number,
  requestedDistance: number,
  tuning: FollowCameraTuning = DEFAULT_FOLLOW_CAMERA,
): number {
  const fraction = requestedDistance < tuning.portraitDistance
    ? tuning.portraitAimFraction
    : tuning.aimFraction;
  return groundY + standingHeight * fraction;
}

/** Unit view direction for a pose, in the -Z-forward convention both candidate engines share. */
function viewForward(player: CameraState): readonly [number, number, number] {
  return [
    -Math.sin(player.yaw) * Math.cos(player.pitch),
    Math.sin(player.pitch),
    -Math.cos(player.yaw) * Math.cos(player.pitch),
  ];
}

/**
 * How far back the boom may reach from `start` before it meets a building or the ground.
 *
 * The ground is the level plane at `groundHeight`, the height of the surface the person stands
 * on; every ground third person is offered on is level where a person stands (`worldViews`). A
 * district's ground is y = 0, the default.
 */
export function resolveBoomDistance(
  start: readonly [number, number, number],
  direction: readonly [number, number, number],
  requestedDistance: number,
  district?: OwnedDistrict,
  tuning: FollowCameraTuning = DEFAULT_FOLLOW_CAMERA,
  groundHeight = 0,
): number {
  let distance = Math.max(MINIMUM_DISTANCE, Math.min(MAXIMUM_DISTANCE, requestedDistance));
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
        [start[0] + dx!, start[1], start[2] + dz!],
        direction,
      );
      if (hit !== null) {
        distance = Math.min(distance, Math.max(tuning.minimumDistance, hit - tuning.collisionPadding));
      }
    }
  }
  if (direction[1] < 0) {
    distance = Math.min(
      distance,
      Math.max(tuning.minimumDistance, (start[1] - groundHeight - tuning.groundClearance) / -direction[1]),
    );
  }
  return distance;
}

/**
 * Camera boom only; the caller retains the authoritative player pose.
 *
 * `aimHeight` defaults to the player's own eye line, which is never above the head. Callers that
 * know the drawn body pass `playerCameraAimHeight` instead.
 */
export function playerCameraPosition(
  player: CameraState,
  mode: PlayerCameraMode,
  district?: OwnedDistrict,
  requestedDistance = DEFAULT_FOLLOW_CAMERA.distance,
  aimHeight?: number,
  tuning: FollowCameraTuning = DEFAULT_FOLLOW_CAMERA,
  resolvedDistance?: number,
  groundHeight = 0,
): readonly [number, number, number] {
  if (mode === 'first-person') return [player.x, player.y, player.z];
  const forward = viewForward(player);
  const right: readonly [number, number, number] = [Math.cos(player.yaw), 0, -Math.sin(player.yaw)];
  const start: readonly [number, number, number] = [
    player.x + right[0] * tuning.lateralOffset,
    aimHeight ?? player.y,
    player.z + right[2] * tuning.lateralOffset,
  ];
  const direction: readonly [number, number, number] = [-forward[0]!, -forward[1]!, -forward[2]!];
  const distance = resolvedDistance
    ?? resolveBoomDistance(start, direction, requestedDistance, district, tuning, groundHeight);
  return [
    start[0] + direction[0] * distance,
    start[1] + direction[1] * distance,
    start[2] + direction[2] * distance,
  ];
}

/**
 * The follow camera across frames.
 *
 * The only state it keeps is the boom length. Smoothing the aim point instead would drag the
 * player off the centre line during travel, which is a look, not a fix; smoothing the length
 * removes the one artefact a rigid boom actually has, the pop back out after a corner clears.
 */
export class FollowCamera {
  private extended: number | null = null;

  /** The boom length actually in use, after obstruction and smoothing. */
  get distance(): number {
    return this.extended ?? DEFAULT_FOLLOW_CAMERA.distance;
  }

  /** Whether the drawn player would be in the way rather than in the shot at this boom length. */
  occludesPlayer(tuning: FollowCameraTuning = DEFAULT_FOLLOW_CAMERA): boolean {
    return this.extended !== null && this.extended < tuning.avatarFadeDistance;
  }

  reset(): void {
    this.extended = null;
  }

  solve(
    player: CameraState,
    mode: PlayerCameraMode,
    options: {
      readonly district?: OwnedDistrict;
      readonly requestedDistance?: number;
      readonly aimHeight?: number;
      /** Height of the ground under the person; a district's, y = 0, by default. */
      readonly groundHeight?: number;
      readonly tuning?: FollowCameraTuning;
      readonly dt?: number;
      readonly reducedMotion?: boolean;
    } = {},
  ): readonly [number, number, number] {
    const tuning = options.tuning ?? DEFAULT_FOLLOW_CAMERA;
    if (mode === 'first-person') {
      this.extended = null;
      return [player.x, player.y, player.z];
    }
    const requested = options.requestedDistance ?? tuning.distance;
    const forward = viewForward(player);
    const right: readonly [number, number, number] = [Math.cos(player.yaw), 0, -Math.sin(player.yaw)];
    const start: readonly [number, number, number] = [
      player.x + right[0] * tuning.lateralOffset,
      options.aimHeight ?? player.y,
      player.z + right[2] * tuning.lateralOffset,
    ];
    const direction: readonly [number, number, number] = [-forward[0]!, -forward[1]!, -forward[2]!];
    const target = resolveBoomDistance(start, direction, requested, options.district, tuning, options.groundHeight);
    const dt = options.dt ?? 0;
    const smoothing = options.reducedMotion === true ? 0 : tuning.extendSeconds;
    if (this.extended === null || target <= this.extended || smoothing <= 0 || !(dt > 0)) {
      // Collapse the instant something is in the way; there is no comfortable way to ease into a wall.
      this.extended = target;
    } else {
      this.extended += (target - this.extended) * (1 - Math.exp(-dt / smoothing));
    }
    return playerCameraPosition(
      player, mode, options.district, requested, options.aimHeight, tuning, this.extended,
    );
  }
}
