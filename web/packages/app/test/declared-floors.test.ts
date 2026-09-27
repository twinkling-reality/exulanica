import { describe, expect, it, vi } from 'vitest';
import type { MountedAtlas } from '../src/atlas.js';
import { withDeclaredFloors } from '../src/composition/declared-floors.js';

/*
 * The floor a world made from photographs declares is drawn with the Atlas and goes with it: each
 * remount disposes the last Atlas, and its floors' texture and materials must not outlive it.
 */

function mounted(order: string[]): MountedAtlas {
  return {
    binding: { name: 'binding' },
    worldKind: 'personal-regions',
    placements: [],
    dispose: () => { order.push('atlas'); },
  } as unknown as MountedAtlas;
}

describe('the declared floor lives as long as the Atlas it is drawn in', () => {
  it('draws the floor under the binding and destroys it before the binding on dispose', () => {
    const order: string[] = [];
    const atlas = mounted(order);
    const draw = vi.fn(() => ({ islandIds: [], destroy: () => { order.push('floors'); } }));
    const floor = { halfExtentMm: 12_000, elevationMm: 0 };
    const withFloors = withDeclaredFloors(atlas, floor, draw as never);
    expect(draw).toHaveBeenCalledWith(atlas.binding, floor);
    expect(withFloors.binding).toBe(atlas.binding);
    withFloors.dispose();
    expect(order).toEqual(['floors', 'atlas']);
  });

  it('draws nothing and changes nothing for a world that declares no floor', () => {
    const order: string[] = [];
    const atlas = mounted(order);
    const draw = vi.fn();
    expect(withDeclaredFloors(atlas, null, draw as never)).toBe(atlas);
    expect(draw).not.toHaveBeenCalled();
  });
});
