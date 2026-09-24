// @vitest-environment happy-dom
/**
 * Each camera view a kind of world offers is one its binding carries out, and each view it
 * withholds is one the binding would ignore.
 *
 * `worldViews` decides which views the app offers. For every kind the app hands the binding, this
 * builds the real binding on the null device and asks it for each view. An offered view must move
 * the camera; a withheld one must leave the pose and the drawn camera exactly where they were,
 * which is why the app does not offer it. Turning the view and walking are offered in every world,
 * so turning must turn in every world, and walking assistance must walk exactly as far as holding
 * W does.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AtlasBinding } from '../../src/playcanvas/atlas-binding.js';
import { describeWorldKind, worldViews } from '../../src/playcanvas/world-kind.js';
import { WORLD_KINDS, buildBinding, worldOptions, type WorldKind } from './binding-harness.js';

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

const viewsOf = (kind: WorldKind) => worldViews(describeWorldKind(worldOptions(kind)));

/** Frames at 60 Hz on a clock of the binding's own. */
function frames(binding: AtlasBinding): (count: number) => void {
  let clock = 10_000;
  return (count) => {
    for (let frame = 0; frame < count; frame += 1) {
      clock += 16;
      binding.update(1 / 60, clock);
    }
  };
}

function pose(binding: AtlasBinding) {
  const { x, y, z, yaw, pitch } = binding.controls.state;
  return { x, y, z, yaw, pitch };
}

/** Where the drawn camera stands and which way it looks, in world metres. */
function drawn(binding: AtlasBinding): readonly number[] {
  const origin = (binding as unknown as { renderOriginState: { origin: { x: number; y: number; z: number } } })
    .renderOriginState.origin;
  const at = binding.camera.getPosition();
  const forward = binding.camera.forward;
  return [at.x + origin.x, at.y + origin.y, at.z + origin.z, forward.x, forward.y, forward.z];
}

/** How far the drawn camera stands from the person's eye, in metres. */
function reach(binding: AtlasBinding): number {
  const [x, y, z] = drawn(binding);
  const eye = binding.controls.state;
  return Math.hypot(x! - eye.x, y! - eye.y, z! - eye.z);
}

/** How far 1.5 s of walking carries the person, by assistance or by holding W. */
async function walked(kind: WorldKind, how: 'assistance' | 'key') {
  const { binding, canvas } = await buildBinding(kind);
  const run = frames(binding);
  try {
    run(3);
    const start = pose(binding);
    const navigation = binding.navigationWorld;
    const onField = Math.hypot(start.x - navigation.centre.x, start.z - navigation.centre.z)
      <= navigation.fieldRadius;
    if (how === 'assistance') binding.setWalkAssist('walk');
    else {
      canvas.tabIndex = 0;
      canvas.focus();
      window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyW' }));
    }
    run(90);
    const end = pose(binding);
    window.dispatchEvent(new KeyboardEvent('keyup', { code: 'KeyW' }));
    return { metres: Math.hypot(end.x - start.x, end.z - start.z), onField };
  } finally {
    binding.destroy();
  }
}

describe('the camera views each kind of world offers', () => {
  for (const kind of WORLD_KINDS) {
    it(`${kind}: offers the city views only where asking for them moves the camera`, async () => {
      const { binding } = await buildBinding(kind);
      const run = frames(binding);
      try {
        run(3);
        const before = pose(binding);
        const camera = drawn(binding);
        binding.setCityView('overview');
        const overview = pose(binding);
        binding.setCityView('street');
        const street = pose(binding);
        if (viewsOf(kind).cityViews) {
          // The binding sets each view it is asked for. What height the controls hold it at on
          // the frames after is theirs, and is not what this offers.
          expect(overview).not.toEqual(before);
          expect(street).not.toEqual(overview);
        } else {
          expect(overview).toEqual(before);
          expect(street).toEqual(before);
          run(3);
          expect(pose(binding)).toEqual(before);
          expect(drawn(binding)).toEqual(camera);
        }
      } finally {
        binding.destroy();
      }
    });

    it(`${kind}: offers the third-person camera and its framing only where they move the camera`, async () => {
      const { binding } = await buildBinding(kind);
      const run = frames(binding);
      try {
        run(3);
        // What the framing select does: third person, then the distance chosen.
        binding.setCameraMode('third-person');
        binding.setCameraFraming(0.85);
        run(240);
        const near = reach(binding);
        binding.setCameraFraming(6);
        run(240);
        const far = reach(binding);
        if (viewsOf(kind).thirdPerson) {
          expect(binding.cameraMode).toBe('third-person');
          expect(near).toBeCloseTo(0.85, 1);
          expect(far).toBeCloseTo(6, 1);
        } else {
          expect(binding.cameraMode).toBe('first-person');
          expect(near).toBeCloseTo(0, 6);
          expect(far).toBeCloseTo(0, 6);
        }
      } finally {
        binding.destroy();
      }
    });

    it(`${kind}: turns the view, and walking assistance walks as far as holding W`, async () => {
      const { binding } = await buildBinding(kind);
      const run = frames(binding);
      try {
        run(3);
        const yaw = binding.controls.state.yaw;
        const looking = drawn(binding).slice(3);
        binding.turnCamera(Math.PI / 2);
        run(2);
        expect(binding.controls.state.yaw).toBeCloseTo(yaw + Math.PI / 2, 9);
        expect(drawn(binding).slice(3)).not.toEqual(looking);
      } finally {
        binding.destroy();
      }
      const assisted = await walked(kind, 'assistance');
      const keyed = await walked(kind, 'key');
      expect(assisted.metres).toBeCloseTo(keyed.metres, 6);
      // A person who starts on the walkable field walks a real distance either way.
      if (assisted.onField) expect(assisted.metres).toBeGreaterThan(1);
    });
  }
});
