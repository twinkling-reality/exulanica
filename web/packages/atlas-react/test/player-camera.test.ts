import { describe, expect, it } from 'vitest';
import { ownedDistrictOverviewCameraState } from '../src/playcanvas/camera-views.js';
import {
  DEFAULT_FOLLOW_CAMERA,
  FollowCamera,
  playerCameraAimHeight,
  playerCameraPosition,
} from '../src/playcanvas/player-camera.js';
import type { OwnedDistrict } from '@exulanica/atlas-core';
const player = {x:0,y:1.62,z:0,yaw:0,pitch:0};
describe('player camera presentation', () => {
  it('frames an owned district from its actual translated bounds', () => {
    const district = {
      buildings: [
        { bbox_cm: [10000, 20000, 20000, 30000], height_cm: 4000 },
        { bbox_cm: [30000, 40000, 50000, 60000], height_cm: 8000 },
      ],
    } as unknown as OwnedDistrict;
    const overview = ownedDistrictOverviewCameraState(district);
    expect(overview.x).toBeGreaterThan(250);
    expect(overview.z).toBeGreaterThan(600);
    expect(overview.y).toBeGreaterThan(90);
    expect(overview.pitch).toBeLessThan(0);
  });

  it('switches without mutating player pose', () => {
    const snapshot = {...player};
    expect(playerCameraPosition(player,'first-person')).toEqual([0,1.62,0]);
    expect(playerCameraPosition(player,'third-person')).toEqual([0,1.62,3.8]);
    expect(player).toEqual(snapshot);
  });
  it('shortens the boom before a building behind the player', () => {
    const district = {buildings:[{height_cm:1000,polygons:[[[[-500,200],[500,200],[500,400],[-500,400],[-500,200]]]]}]} as unknown as OwnedDistrict;
    const camera = playerCameraPosition(player,'third-person',district);
    expect(camera[2]).toBeLessThan(1.6);
    expect(camera[2]).toBeGreaterThan(1);
  });
  /*
   * The camera is placed by stepping back from the aim point and is then given the player's own
   * yaw and pitch, so the aim point is exactly what screen centre lands on. Aiming above the head
   * put the reticle in empty air and pushed the whole figure into the lower half of the frame.
   */
  it('aims at the body rather than over its head', () => {
    const standing = 1.82;
    const follow = playerCameraAimHeight(0, standing, 3.8);
    expect(follow).toBeLessThan(standing);
    expect(follow).toBeGreaterThan(standing / 2);
    const portrait = playerCameraAimHeight(0, standing, 0.85);
    expect(portrait).toBeGreaterThan(follow);
    expect(portrait).toBeLessThanOrEqual(standing);
    // The aim point is the boom origin, so the camera stays level with what it is looking at.
    const camera = playerCameraPosition(player, 'third-person', undefined, 3.8, follow);
    expect(camera[1]).toBeCloseTo(follow, 12);
    expect(camera[2]).toBeCloseTo(3.8, 12);
  });

  it('carries a raised ground plane through to the aim line', () => {
    expect(playerCameraAimHeight(4, 1.82, 3.8)).toBeCloseTo(4 + playerCameraAimHeight(0, 1.82, 3.8), 12);
  });

  it('keeps the camera above visible ground when looking up', () => {
    expect(playerCameraPosition({...player,pitch:1.4},'third-person')[1]).toBeGreaterThanOrEqual(.249);
  });

  /*
   * A boom that collapses against a corner and then snaps back out the instant it clears reads as
   * a cut. Collapsing has to stay immediate, or the camera eases into the wall it is avoiding.
   */
  it('collapses against an obstruction at once and reaches back out over time', () => {
    const district = {buildings:[{height_cm:1000,polygons:[[[[-500,200],[500,200],[500,400],[-500,400],[-500,200]]]]}]} as unknown as OwnedDistrict;
    const camera = new FollowCamera();
    const open = camera.solve(player, 'third-person', { dt: 1 / 60 })[2];
    expect(open).toBeCloseTo(DEFAULT_FOLLOW_CAMERA.distance, 12);

    const blocked = camera.solve(player, 'third-person', { district, dt: 1 / 60 })[2];
    expect(blocked).toBeLessThan(1.6);

    let reaching = camera.solve(player, 'third-person', { dt: 1 / 60 })[2];
    expect(reaching).toBeGreaterThan(blocked);
    expect(reaching).toBeLessThan(DEFAULT_FOLLOW_CAMERA.distance - 1);
    for (let frame = 0; frame < 240; frame += 1) {
      reaching = camera.solve(player, 'third-person', { dt: 1 / 60 })[2];
    }
    expect(reaching).toBeCloseTo(DEFAULT_FOLLOW_CAMERA.distance, 2);
  });

  it('keeps the boom rigid under reduced motion', () => {
    const district = {buildings:[{height_cm:1000,polygons:[[[[-500,200],[500,200],[500,400],[-500,400],[-500,200]]]]}]} as unknown as OwnedDistrict;
    const camera = new FollowCamera();
    camera.solve(player, 'third-person', { district, dt: 1 / 60, reducedMotion: true });
    const cleared = camera.solve(player, 'third-person', { dt: 1 / 60, reducedMotion: true })[2];
    expect(cleared).toBeCloseTo(DEFAULT_FOLLOW_CAMERA.distance, 12);
  });

  it('offers an over-the-shoulder offset without it being on', () => {
    expect(DEFAULT_FOLLOW_CAMERA.lateralOffset).toBe(0);
    const centred = playerCameraPosition(player, 'third-person');
    expect(centred[0]).toBeCloseTo(0, 12);
    const shouldered = playerCameraPosition(
      player, 'third-person', undefined, 3.8, undefined,
      { ...DEFAULT_FOLLOW_CAMERA, lateralOffset: 0.45 },
    );
    expect(shouldered[0]).toBeCloseTo(0.45, 12);
    expect(shouldered[2]).toBeCloseTo(centred[2], 12);
  });

  /*
   * A facade behind the player can shorten the boom past the body. At zero the camera sits inside
   * the head, looking at the back of its own face, so the boom stops short and the caller is told
   * the avatar is now in the way rather than in the shot.
   */
  it('never drives the boom inside the body, and says when the player is in the way', () => {
    const wall = {buildings:[{height_cm:4000,polygons:[[[[-2000,20],[2000,20],[2000,3000],[-2000,3000],[-2000,20]]]]}]} as unknown as OwnedDistrict;
    const camera = new FollowCamera();
    const pressed = camera.solve(player, 'third-person', { district: wall, dt: 1 / 60 });
    const boom = Math.hypot(pressed[0] - player.x, pressed[2] - player.z);
    expect(boom).toBeGreaterThanOrEqual(DEFAULT_FOLLOW_CAMERA.minimumDistance - 1e-9);
    expect(camera.distance).toBeCloseTo(DEFAULT_FOLLOW_CAMERA.minimumDistance, 12);
    expect(camera.occludesPlayer()).toBe(true);

    for (let frame = 0; frame < 240; frame += 1) camera.solve(player, 'third-person', { dt: 1 / 60 });
    expect(camera.occludesPlayer()).toBe(false);
  });

  it('keeps the player drawn at the closest framing the product offers', () => {
    const camera = new FollowCamera();
    camera.solve(player, 'third-person', { requestedDistance: 0.85, dt: 1 / 60 });
    expect(camera.distance).toBeCloseTo(0.85, 12);
    expect(camera.occludesPlayer()).toBe(false);
  });
});
