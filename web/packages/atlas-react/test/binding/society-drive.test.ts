// @vitest-environment happy-dom
/**
 * How the binding drives a society, frame by frame.
 *
 * The binding holds no society of its own. Each frame it tells the crowd where the person stands
 * and what time it is (the far future under reduced motion, which settles every walk), hands the
 * native character runtime the crowd's frames, and once a second publishes what is drawn on the
 * canvas and announces a change in who is nearby. These pin that drive for a saved world's
 * authored region and for an owned district, which share it.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AtlasBinding } from '../../src/playcanvas/atlas-binding.js';
import type { OwnedSocietyState } from '../../src/playcanvas/society/types.js';
import { buildBinding } from './binding-harness.js';

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

const society = (count: number, at: (i: number) => readonly [number, number]): OwnedSocietyState => ({
  profile: 'exulanica-society/v2',
  society_id: 'society',
  branch_id: 'branch',
  tick: 1,
  inhabitants: Array.from({ length: count }, (_, i) => ({
    id: `person-${i}`,
    synthetic: true as const,
    position_mm: at(i),
    motion_path_mm: [[at(i)[0], 0], at(i)] as const,
  })),
});

interface Drive {
  readonly nearby: (readonly number[])[];
  readonly ticks: number[];
  readonly native: number[];
}

function spy(binding: AtlasBinding, crowd: { refreshNearby: unknown; tickSociety: unknown }): Drive {
  const drive: Drive = { nearby: [], ticks: [], native: [] };
  const target = crowd as unknown as Record<string, (...a: unknown[]) => unknown>;
  const refresh = target.refreshNearby!.bind(crowd);
  const tick = target.tickSociety!.bind(crowd);
  target.refreshNearby = (at: unknown) => { drive.nearby.push([...(at as number[])]); return refresh(at); };
  target.tickSociety = (now: unknown) => { drive.ticks.push(now as number); return tick(now); };
  (binding as unknown as { nativeCharacters: unknown }).nativeCharacters = {
    syncFrames: (frames: readonly unknown[]) => { drive.native.push(frames.length); },
    destroy: () => undefined,
  };
  return drive;
}

describe('the society drive', () => {
  it('tells a saved world\'s crowd where the person stands and what time it is, every frame', async () => {
    const { binding, canvas } = await buildBinding('authored-endless');
    try {
      const crowd = binding.authoredSociety!;
      crowd.setSociety(society(3, (i) => [i * 1500, 2000]), [0, 4]);
      const drive = spy(binding, crowd);
      const changes: number[] = [];
      canvas.addEventListener('society-nearby-change', () => { changes.push(1); });
      binding.update(1 / 60, 10_500);
      binding.update(1 / 60, 10_516);
      expect(drive.nearby).toEqual([[0, 4], [0, 4]]);
      expect(drive.ticks).toEqual([10_500, 10_516]);
      expect(drive.native).toEqual([3, 3]);
      // Nothing is published inside one second.
      expect(canvas.dataset.societyRendered).toBeUndefined();
      binding.update(1 / 60, 11_004);
      expect(canvas.dataset.societyRendered).toBe('3');
      expect(canvas.dataset.societyNearby).toBe('3');
      expect(changes).toEqual([1]);
      // The same people nearby the next second: published again, not announced again.
      binding.update(1 / 60, 12_004);
      expect(changes).toEqual([1]);
      binding.setReducedMotion(true);
      binding.update(1 / 60, 12_020);
      expect(drive.ticks.at(-1)).toBe(Number.MAX_SAFE_INTEGER);
    } finally {
      binding.destroy();
    }
  });

  it('drives an owned district\'s crowd the same way and publishes its drawing once a second', async () => {
    const { binding, canvas } = await buildBinding('owned-district');
    try {
      const crowd = binding.ownedDistrict!;
      crowd.setSociety(society(4, (i) => [i * 1500, 2000]), [0, 0]);
      const drive = spy(binding, crowd);
      binding.update(1 / 60, 20_500);
      expect(drive.nearby).toEqual([[0, 0]]);
      expect(drive.ticks).toEqual([20_500]);
      expect(canvas.dataset.actualDrawCalls).toBeUndefined();
      binding.update(1 / 60, 21_001);
      // `engine` is the engine's own stamp on its canvas; every other key is the binding's.
      expect(Object.keys(canvas.dataset).filter((key) => key !== 'engine').sort()).toEqual([
        'actualDrawCalls', 'characterTextureBytes', 'displayCameraPosition', 'ownedGeometryBytes',
        'playerPosition', 'societyNearby', 'societyRendered',
      ]);
      expect(canvas.dataset.societyRendered).toBe('4');
      expect(JSON.parse(canvas.dataset.playerPosition!)).toEqual([
        binding.controls.state.x, binding.controls.state.y, binding.controls.state.z,
      ]);
    } finally {
      binding.destroy();
    }
  });

  it('builds no crowd where there is no society to hold: a world of regions, a tile, a reference', async () => {
    for (const kind of ['personal-regions', 'generated-tile', 'google-reference'] as const) {
      const { binding } = await buildBinding(kind);
      try {
        expect(binding.authoredSociety).toBeNull();
        expect(binding.ownedDistrict).toBeNull();
      } finally {
        binding.destroy();
      }
    }
  });
});
