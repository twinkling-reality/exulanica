import { describe, expect, it } from 'vitest';
import { playerCameraPosition } from '../src/playcanvas/player-camera.js';
import type { OwnedDistrict } from '@exulanica/atlas-core';
const player = {x:0,y:1.62,z:0,yaw:0,pitch:0};
describe('player camera presentation', () => {
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
