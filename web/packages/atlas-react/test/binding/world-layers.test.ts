// @vitest-environment happy-dom
/**
 * The memory layer switch is offered only where switching the layer off leaves a world drawn.
 *
 * For every kind the app hands the binding, this builds the real binding on the null device. Where
 * `worldLayers` withholds the switch, hiding the layer must leave no drawn mesh at all, which is
 * why offering it there blanks the world. Where it offers the switch, the world must have a ground
 * of its own (a district, a tile or a Google reference) drawn outside the layer, under the
 * environment root.
 */
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { describeWorldKind, worldLayers } from '../../src/playcanvas/world-kind.js';
import { WORLD_KINDS, buildBinding, worldOptions } from './binding-harness.js';

/** Names of the entities that draw a mesh, walking only enabled branches. */
function drawn(entity: pc.Entity): string[] {
  if (!entity.enabled) return [];
  const own = entity.render?.enabled && (entity.render.meshInstances?.length ?? 0) > 0 ? [entity.name] : [];
  return [...own, ...entity.children.flatMap((child) => child instanceof pc.Entity ? drawn(child) : [])];
}

describe('the memory layer switch each kind of world offers', () => {
  for (const kind of WORLD_KINDS) {
    it(`${kind}: offers it only where the world is still drawn without the layer`, async () => {
      const { binding } = await buildBinding(kind);
      try {
        binding.update(1 / 60, 10_016);
        binding.setMemoryLayerVisible(true);
        expect(drawn(binding.app.root).length).toBeGreaterThan(0);
        binding.setMemoryLayerVisible(false);
        if (worldLayers(describeWorldKind(worldOptions(kind))).memoryLayer) {
          // The world's own ground is drawn by its runtime into the environment root (a Google
          // reference adds its tiles there as they load, which the harness's refused network never
          // does), and the environment root stays drawn outside the layer.
          const own = [binding.ownedDistrict, binding.generatedTile, binding.googleTiles].filter((value) => value !== null);
          expect(own.length).toBe(1);
          expect(binding.environmentRoot.enabled).toBe(true);
          expect(binding.renderRoot.findOne((node) => node === binding.environmentRoot)).toBeNull();
        } else {
          expect(drawn(binding.app.root)).toEqual([]);
        }
      } finally {
        binding.destroy();
      }
    });
  }
});
