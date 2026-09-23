// @vitest-environment happy-dom
/**
 * What `destroy` takes down, and in what order.
 *
 * Some of the order is load-bearing: authored objects hold borrowed representation handles and
 * are released while the registry is still live, so they go first; the application goes last,
 * after every collaborator that holds engine resources. The canvas's dataset keys the binding
 * wrote are removed, so a remount reads nothing stale. These pin the observed order per world
 * kind and those two properties by name.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AtlasBinding } from '../../src/playcanvas/atlas-binding.js';
import { WORLD_KINDS, buildBinding, record } from './binding-harness.js';

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

/** Wrap every collaborator's teardown that exists for this world. */
function instrument(binding: AtlasBinding, log: string[]): void {
  const internals = binding as unknown as Record<string, object | null>;
  const wrap = (target: object | null | undefined, label: string, method: string): void => {
    if (target !== null && target !== undefined) record(log, target, label, [method]);
  };
  wrap(binding.objects, 'objects', 'destroy');
  wrap(binding.authoredPointMaps, 'authoredPointMaps', 'destroy');
  wrap(binding.representation, 'representation', 'destroy');
  wrap(internals.playerAvatar, 'playerAvatar', 'destroy');
  wrap(binding.ownedDistrict, 'ownedDistrict', 'destroy');
  wrap(binding.authoredSociety, 'authoredSociety', 'destroy');
  wrap(binding.generatedTile, 'generatedTile', 'dispose');
  wrap(binding.googleTiles, 'googleTiles', 'dispose');
  wrap(binding.controls, 'controls', 'destroy');
  wrap(binding.overlay, 'overlay', 'destroy');
  wrap(binding.mapOverlay, 'mapOverlay', 'destroy');
  wrap(binding.motes, 'motes', 'destroy');
  wrap(binding.field, 'field', 'destroy');
  wrap(binding.composedWorld, 'composedWorld', 'destroy');
  wrap(binding.regionMass, 'regionMass', 'destroy');
  wrap(binding.regionRelief, 'regionRelief', 'destroy');
  wrap(binding.segmentOverlay, 'segmentOverlay', 'destroy');
  for (const [index, visual] of binding.islands.entries()) wrap(visual.cloud, `islands[${index}].cloud`, 'destroy');
  (binding as unknown as { nativeCharacters: unknown }).nativeCharacters = {
    syncFrames: () => undefined,
    destroy: () => { log.push('nativeCharacters.destroy'); },
  };
  wrap(binding.app, 'app', 'destroy');
}

/** The dataset keys the binding writes on its canvas while it runs. */
const BINDING_DATASET_KEYS = [
  'cameraMode', 'ownedGeometryBytes', 'characterTextureBytes', 'actualDrawCalls',
  'playerPosition', 'displayCameraPosition', 'societyRendered', 'societyNearby',
];

describe('what destroy takes down, in order', () => {
  for (const kind of WORLD_KINDS) {
    it(`destroys ${kind} in the pinned order`, async () => {
      const { binding } = await buildBinding(kind);
      const log: string[] = [];
      instrument(binding, log);
      binding.update(1 / 60, 10_000);
      binding.destroy();
      await expect(`${log.join('\n')}\n`).toMatchFileSnapshot(`pins/destroy-${kind}.txt`);
      // Released while the representation registry is still live, and the engine last.
      expect(log[0]).toBe('objects.destroy');
      expect(log.indexOf('objects.destroy')).toBeLessThan(log.indexOf('representation.destroy'));
      expect(log.at(-1)).toBe('app.destroy');
    });
  }

  it('removes every dataset key it wrote on the canvas', async () => {
    const { binding, canvas } = await buildBinding('owned-district');
    // A frame that crosses a second boundary writes the district's once-a-second keys.
    binding.update(1 / 60, 10_000);
    binding.update(1 / 60, 11_000);
    binding.setCameraMode('third-person');
    const written = BINDING_DATASET_KEYS.filter((key) => canvas.dataset[key] !== undefined);
    // The control: without it an empty list would pass the removal check below trivially.
    expect(written).toEqual(expect.arrayContaining([
      'cameraMode', 'ownedGeometryBytes', 'actualDrawCalls', 'playerPosition', 'societyRendered',
    ]));
    binding.destroy();
    expect(BINDING_DATASET_KEYS.filter((key) => canvas.dataset[key] !== undefined)).toEqual([]);
  });
});
