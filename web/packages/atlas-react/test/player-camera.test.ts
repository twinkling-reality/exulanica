import { describe, expect, it } from 'vitest';
import { ownedDistrictOverviewCameraState } from '../src/playcanvas/atlas-binding.js';
import { playerCameraPosition } from '../src/playcanvas/player-camera.js';
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
    expect(playerCameraPosition(player,'third-person')).toEqual([0,1.87,3.8]);
    expect(player).toEqual(snapshot);
  });
  it('shortens the boom before a building behind the player', () => {
    const district = {buildings:[{height_cm:1000,polygons:[[[[-500,200],[500,200],[500,400],[-500,400],[-500,200]]]]}]} as unknown as OwnedDistrict;
    const camera = playerCameraPosition(player,'third-person',district);
    expect(camera[2]).toBeLessThan(1.6);
    expect(camera[2]).toBeGreaterThan(1);
  });
  it('keeps the camera above visible ground when looking up', () => {
    expect(playerCameraPosition({...player,pitch:1.4},'third-person')[1]).toBeGreaterThanOrEqual(.249);
  });
});
