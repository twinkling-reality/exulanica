// @vitest-environment happy-dom
/**
 * The order of the binding's work inside one frame.
 *
 * `update` is documented as move, decide representation density, decide attention, then draw the
 * overlay from those decisions, and several steps depend on an earlier one in the same frame: the
 * placed estimates flatten against the camera only after the render origin has moved it, and the
 * overlay reads the focus the frame just resolved. These pin the observed order for a starter
 * world, a world of regions (whose first frame also moves the render origin and plans residency)
 * and an owned district, by wrapping each collaborator's methods and recording the calls.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AtlasBinding } from '../../src/playcanvas/atlas-binding.js';
import { buildBinding, record, type WorldKind } from './binding-harness.js';

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

/** Wrap everything `update` reaches that exists for this world, and the frame callbacks. */
function instrument(binding: AtlasBinding, log: string[]): void {
  const internals = binding as unknown as Record<string, object>;
  record(log, binding, 'binding', [
    'advanceDirectNavigation', 'updateAuthoredSociety', 'syncNativeCharacterFrames',
    'applyResidencyPresentation', 'settleProofLens', 'findCentredPhotograph', 'publishRepresentation',
  ]);
  record(log, binding.controls, 'controls', ['update']);
  record(log, internals.followCamera!, 'followCamera', ['solve']);
  record(log, binding.camera, 'camera', ['setPosition', 'setRotation']);
  record(log, binding.renderRoot, 'renderRoot', ['setPosition']);
  record(log, binding.environmentRoot, 'environmentRoot', ['setPosition']);
  record(log, binding.field, 'field', ['setRenderOrigin', 'update']);
  record(log, binding.objects, 'objects', ['update']);
  record(log, binding.motes, 'motes', ['update']);
  if (binding.overlay !== null) record(log, binding.overlay, 'overlay', ['update']);
  if (binding.mapOverlay !== null) record(log, binding.mapOverlay, 'mapOverlay', ['update']);
  if (binding.ownedDistrict !== null) {
    record(log, binding.ownedDistrict, 'ownedDistrict', ['refreshNearby', 'tickSociety', 'nativeCharacterFrames']);
  }
  if (binding.authoredSociety !== null) {
    record(log, binding.authoredSociety, 'authoredSociety', ['refreshNearby', 'tickSociety', 'nativeCharacterFrames']);
  }
  if (binding.googleTiles !== null) record(log, binding.googleTiles, 'googleTiles', ['update']);
  if (binding.authoredPointMaps !== null) record(log, binding.authoredPointMaps, 'authoredPointMaps', ['frame']);
  // A native character runtime as the app enables one: it only receives frames.
  (binding as unknown as { nativeCharacters: unknown }).nativeCharacters = {
    syncFrames: () => { log.push('nativeCharacters.syncFrames'); },
    destroy: () => undefined,
  };
  binding.onFrame = () => { log.push('onFrame'); };
}

async function framesOf(kind: WorldKind, frames: number): Promise<string[][]> {
  const { binding } = await buildBinding(kind);
  try {
    const log: string[] = [];
    instrument(binding, log);
    const out: string[][] = [];
    for (let frame = 0; frame < frames; frame += 1) {
      log.length = 0;
      // Frames 1 s apart, so the once-a-second steps run in every frame recorded.
      binding.update(1 / 60, 10_000 + frame * 1000);
      out.push([...log]);
    }
    return out;
  } finally {
    binding.destroy();
  }
}

describe('the order of work inside a frame', () => {
  for (const kind of ['authored-endless', 'authored-with-estimate', 'personal-regions', 'owned-district', 'google-reference'] as const) {
    it(`runs ${kind}'s first and second frames in the pinned order`, async () => {
      const [first, second] = await framesOf(kind, 2);
      const text = `first frame\n${first!.join('\n')}\n\nsecond frame\n${second!.join('\n')}\n`;
      await expect(text).toMatchFileSnapshot(`pins/frame-${kind}.txt`);
    });
  }

  it('moves the render origin before anything reads the camera in the first frame of a world of regions', async () => {
    const [first] = await framesOf('personal-regions', 1);
    const rebase = first!.indexOf('renderRoot.setPosition');
    // The control for the order claim below: the first frame of this world does rebase.
    expect(rebase).toBeGreaterThan(-1);
    expect(first!.indexOf('environmentRoot.setPosition')).toBeGreaterThan(rebase);
    expect(first!.indexOf('field.setRenderOrigin')).toBeGreaterThan(rebase);
    expect(first!.indexOf('objects.update')).toBeGreaterThan(rebase);
    expect(first!.indexOf('overlay.update')).toBeGreaterThan(rebase);
    expect(first!.at(-1)).toBe('onFrame');
  });

  it('moves before it draws: controls first, the frame report last', async () => {
    for (const kind of ['authored-endless', 'owned-district'] as const) {
      const [first] = await framesOf(kind, 1);
      expect(first!.indexOf('controls.update')).toBe(0);
      expect(first!.at(-1)).toBe('onFrame');
      expect(first!.indexOf('followCamera.solve')).toBeGreaterThan(first!.indexOf('controls.update'));
      expect(first!.indexOf('overlay.update')).toBeGreaterThan(first!.indexOf('field.update'));
    }
  });
});
