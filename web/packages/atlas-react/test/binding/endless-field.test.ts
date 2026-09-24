// @vitest-environment happy-dom
/**
 * The real starter field: the face an endless starter draws, as the binding builds it.
 *
 * Its drawn half extent is the walk's recovery radius plus the camera's far clip, in cells no wider
 * than that far clip (world-field.ts, "THE ORDER OF THINGS THAT LIE ON THE WALKING FACE"). The far
 * clip is the composed world's, which `openAtmosphere` sets on the camera; read before that, the
 * camera still has the engine's default and the face is drawn to another size in other cells, with
 * nothing else in the binding changing. So this reads the face the binding built, not the helper.
 */
import { describe, expect, it } from 'vitest';
import * as pc from 'playcanvas';
import { COMPOSED_WORLD_ATMOSPHERE } from '../../src/playcanvas/atmosphere.js';
import { buildBinding } from './binding-harness.js';

/** 2 x (8144 m recovery + 1200 m far clip) / 1200 m cells, rounded up. */
const STARTER_FIELD_CELLS = 16;

describe('the field an endless starter draws', () => {
  it('reaches the recovery radius plus the composed world\'s far clip, in 16 cells a side', async () => {
    const { binding } = await buildBinding('authored-endless');
    try {
      const field = binding.app.root.findByName('atlas-world-field') as pc.Entity;
      const face = field.render!.meshInstances[0]!.mesh;
      const reach = COMPOSED_WORLD_ATMOSPHERE.farClip;
      const halfExtent = binding.navigationWorld.recoveryRadius + reach;
      expect(binding.camera.camera!.farClip).toBe(reach);
      expect(face.aabb.halfExtents.x).toBeCloseTo(halfExtent, 3);
      expect(face.aabb.halfExtents.z).toBeCloseTo(halfExtent, 3);
      expect(Math.ceil((2 * halfExtent) / reach)).toBe(STARTER_FIELD_CELLS);
      expect(face.vertexBuffer!.numVertices).toBe((STARTER_FIELD_CELLS + 1) ** 2);
    } finally {
      binding.destroy();
    }
  });
});
