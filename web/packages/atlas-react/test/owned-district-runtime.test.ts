// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import {
  OwnedDistrictRuntime,
  type OwnedSocietyState,
} from '../src/playcanvas/owned-district-runtime.js';
import type { OwnedDistrict } from '@exulanica/atlas-core';

function setup() {
  const canvas = document.createElement('canvas');
  const device = new pc.NullGraphicsDevice(canvas);
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem];
  app.init(options);
  const district: OwnedDistrict = {
    profile: 'exulanica.owned-district/v1',
    district_id: 'test',
    name: 'Test',
    seed: 1,
    bounds_cm: [-1000, -1000, 1000, 1000],
    materials: [
      {
        name: 'stone',
        base: '#778899',
        roughness_milli: 800,
        metalness_milli: 0,
      },
    ],
    buildings: [],
    sidewalks: [],
    source_records: [],
  };
  return {
    runtime: new OwnedDistrictRuntime(device, app.root, district, 100),
    app,
  };
}
const population = (tick: number): OwnedSocietyState => ({
  tick,
  inhabitants: Array.from({ length: 128 }, (_, i) => ({
    id: `person-${i}`,
    synthetic: true,
    role: 'baker',
    position_mm: [i * 1000, 0],
  })),
});
describe('owned runtime population representation', () => {
  /*
   * A walker heading straight down +Z settles at a facing of pi, the worst case for a transform
   * readback: PlayCanvas decomposes that rotation as (180, 0, 180), so the frame used to carry
   * yaw 0 and the character was drawn walking backwards.
   */
  it('hands the native frame the facing the solver resolved, not a transform readback', () => {
    const { runtime, app } = setup();
    const at = (z: number): OwnedSocietyState => ({
      profile: 'exulanica-society/v2',
      society_id: 'society',
      branch_id: 'branch',
      tick: z,
      inhabitants: [{
        id: 'walker',
        synthetic: true,
        position_mm: [0, z * 1000],
        motion_path_mm: [[0, (z - 1) * 1000], [0, z * 1000]],
      }],
    } as unknown as OwnedSocietyState);
    runtime.setSociety(at(0));
    for (let step = 1; step <= 10; step += 1) {
      runtime.setSociety(at(step));
      runtime.tickSociety(Number.MAX_SAFE_INTEGER);
    }
    const [frame] = runtime.nativeCharacterFrames(1 / 60, false);
    expect(frame?.position).toEqual([0, 0, 10]);
    expect(Math.abs(frame!.yaw)).toBeGreaterThan(Math.PI - 0.05);
    runtime.destroy();
    app.destroy();
  });

  it('clears unavailable residents and cannot repopulate from retained state', () => {
    const { runtime, app } = setup();
    runtime.setSociety(population(0), 24, [0, 0]);
    runtime.setSociety(population(1), 24, [0, 0]);
    runtime.revealInhabitant('person-0');
    runtime.clearSociety();
    runtime.clearSociety();
    runtime.tickSociety(performance.now() + 3000);
    runtime.refreshNearby([127, 0]);
    expect(runtime.visibleInhabitantIds).toEqual([]);
    expect(runtime.drawnInhabitantCount).toBe(0);
    expect(runtime.nativeCharacterFrames(0, false)).toEqual([]);
    expect(runtime.pickInhabitant([0, 1, -2], [0, 0, 1])).toBeNull();
    expect(runtime.societyAnimating).toBe(false);
    expect(runtime.societyRoot.children).toHaveLength(0);
    expect(runtime.setSociety(population(2), 24, [0, 0])).toBe(24);
    runtime.destroy();
    app.destroy();
  });
  it('caps display without truncating population and refreshes subjects around a new observer', () => {
    const { runtime, app } = setup();
    const state = population(0);
    expect(runtime.setSociety(state, 100, [0, 0])).toBe(24);
    expect(state.inhabitants).toHaveLength(128);
    expect(runtime.visibleInhabitantIds).toContain('person-0');
    runtime.refreshNearby([127, 0]);
    expect(runtime.visibleInhabitantIds).toContain('person-127');
    expect(runtime.visibleInhabitantIds).not.toContain('person-0');
    expect(runtime.pickInhabitant([127, 1, -2], [0, 0, 1])).toBe('person-127');
    runtime.destroy();
    app.destroy();
  });
  it('picks the interpolated subject along the recorded corner and resets across branches', () => {
    const { runtime, app } = setup();
    const state: OwnedSocietyState = {
      profile: 'exulanica-society/v2',
      society_id: 'society',
      branch_id: 'branch',
      tick: 0,
      inhabitants: [
        {
          id: 'subject',
          synthetic: true,
          position_mm: [0, 0],
          motion_path_mm: [[0, 0]],
        },
      ],
    };
    runtime.setSociety(state);
    runtime.setSociety({
      ...state,
      tick: 1,
      inhabitants: [
        {
          id: 'subject',
          synthetic: true,
          position_mm: [20000, 10000],
          motion_path_mm: [
            [0, 0],
            [0, 10000],
            [20000, 10000],
          ],
        },
      ],
    });
    runtime.tickSociety(performance.now() + 925);
    expect(runtime.pickInhabitant([5, 1, 8], [0, 0, 1])).toBe('subject');
    runtime.setSociety({
      ...state,
      branch_id: 'other',
      tick: 2,
      inhabitants: [
        {
          id: 'subject',
          synthetic: true,
          position_mm: [100000, 0],
          motion_path_mm: [
            [0, 0],
            [100000, 0],
          ],
        },
      ],
    });
    expect(runtime.pickInhabitant([100, 1, -2], [0, 0, 1])).toBe('subject');
    runtime.destroy();
    app.destroy();
  });
  it('groups exact co-location and promotes the selected stable subject without moving anyone', () => {
    const { runtime, app } = setup();
    const state: OwnedSocietyState = {
      tick: 0,
      inhabitants: [
        { id: 'a', synthetic: true, position_mm: [0, 0] },
        { id: 'b', synthetic: true, position_mm: [0, 0] },
      ],
    };
    runtime.setSociety(state);
    expect(runtime.visibleInhabitantIds).toEqual(['a', 'b']);
    expect(runtime.drawnInhabitantCount).toBe(1);
    expect(runtime.pickInhabitant([0, 1, -2], [0, 0, 1])).toBe('a');
    runtime.revealInhabitant('b');
    expect(runtime.pickInhabitant([0, 1, -2], [0, 0, 1])).toBe('b');
    expect(state.inhabitants.map((p) => p.position_mm)).toEqual([
      [0, 0],
      [0, 0],
    ]);
    runtime.setSociety({
      tick: 1,
      inhabitants: [
        state.inhabitants[0]!,
        { ...state.inhabitants[1]!, position_mm: [1000, 0] },
      ],
    });
    expect(runtime.drawnInhabitantCount).toBe(2);
    runtime.destroy();
    app.destroy();
  });
});
