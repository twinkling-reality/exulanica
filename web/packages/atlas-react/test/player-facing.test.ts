// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { PlayerAvatar } from '../src/playcanvas/player-avatar.js';

function stage() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  return { device, app };
}

/** Settle the solver on one camera-relative heading and report the facing it resolved. */
function settle(avatar: PlayerAvatar, headingYaw: number): number {
  const player = { x: 0, y: 1.62, z: 0, yaw: headingYaw, pitch: 0 };
  for (let frame = 0; frame < 90; frame += 1) {
    avatar.update(player, 0, 0, 1 / 60, true, false, 0, headingYaw);
  }
  return avatar.facing;
}

describe('the drawn character faces where the solver says', () => {
  it('reports every heading, including the rear half a transform readback destroys', () => {
    const { device, app } = stage();
    for (const degrees of [0, 45, 90, 91, 135, 179, 180, -135, -91, -45]) {
      const avatar = new PlayerAvatar(device, app.root, { name: `probe-${degrees}` });
      const heading = (degrees * Math.PI) / 180;
      const facing = settle(avatar, heading);
      const error = Math.atan2(Math.sin(facing - heading), Math.cos(facing - heading));
      expect(Math.abs((error * 180) / Math.PI)).toBeLessThan(0.5);
      avatar.destroy();
    }
    app.destroy();
  });

  /*
   * The regression this replaces: the native character frame took its yaw from
   * `root.getLocalEulerAngles().y`. PlayCanvas decomposes a pure Y rotation into the equivalent
   * (180, 180 - yaw, 180) triple once |yaw| passes a quarter turn, so that number is not the yaw
   * and the character was drawn mirrored, reaching a full reversal walking straight down -Z.
   */
  it('does not agree with the Euler readback past a quarter turn, which is the point', () => {
    const { device, app } = stage();
    const avatar = new PlayerAvatar(device, app.root, { name: 'probe' });
    const heading = (135 * Math.PI) / 180;
    const facing = settle(avatar, heading);
    expect((facing * 180) / Math.PI).toBeCloseTo(135, 0);
    expect(avatar.root.getLocalEulerAngles().y).toBeCloseTo(45, 0);
    avatar.destroy();
    app.destroy();
  });
});
