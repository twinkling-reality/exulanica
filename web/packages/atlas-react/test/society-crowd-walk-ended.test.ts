// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { SocietyCrowd } from '../src/playcanvas/society/crowd.js';
import type { OwnedSocietyState } from '../src/playcanvas/society/types.js';
import { serveFixturePeople } from './served-people.js';

/* Whether a person's drawn walk for the latest state has ended, which a thing changing hands waits for. */

function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  serveFixturePeople(app);
  const root = new pc.Entity('society');
  app.root.addChild(root);
  return new SocietyCrowd(device, root);
}

const state = (tick: number, path: [number, number][]): OwnedSocietyState => ({
  profile: 'exulanica-society/v7', society_id: 'society', branch_id: 'branch', tick, movement_budget_mm_per_tick: 60000,
  inhabitants: [{ id: 'walker', synthetic: true, position_mm: path.at(-1)!, motion_path_mm: path }],
});

describe('a person\'s drawn walk', () => {
  it('has ended for someone standing, not while walking a minute\'s path, and again once walked', () => {
    const crowd = setup();
    crowd.set(state(1, [[0, 0]]), [0, 0], { intervalMs: 2000, nowMs: 0 });
    crowd.update(0);
    expect(crowd.walkEnded('walker')).toBe(true);
    // The next minute walks 3 m, spread over the presented minute.
    crowd.set(state(2, [[0, 0], [3000, 0]]), [0, 0], { intervalMs: 2000, nowMs: 1000 });
    crowd.update(1500);
    expect(crowd.walkEnded('walker')).toBe(false);
    crowd.update(10_000);
    expect(crowd.walkEnded('walker')).toBe(true);
    // Someone the crowd does not walk has nothing to wait for.
    expect(crowd.walkEnded('nobody')).toBe(true);
  });
});
