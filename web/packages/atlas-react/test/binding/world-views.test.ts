// @vitest-environment happy-dom
/**
 * Each camera view a kind of world offers is one its binding carries out, and each view it
 * withholds is one the binding would ignore.
 *
 * `worldViews` decides which views the app offers. For every kind the app hands the binding, this
 * builds the real binding on the null device and asks it for each view. An offered view must hold
 * what it names over the frames after it (an overview stays above and pans at its height, street
 * level stands on the walkable field); a withheld one must leave the pose and the drawn camera
 * exactly where they were, which is why the app does not offer it. Every kind opens on its field or
 * facing it, where walking moves the person. Turning the view and walking are offered in every
 * world, so turning must turn in every world, and walking assistance must walk exactly as far as
 * holding W does.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AtlasBinding } from '../../src/playcanvas/atlas-binding.js';
import { describeWorldKind, worldViews } from '../../src/playcanvas/world-kind.js';
import { DEFAULT_FOLLOW_CAMERA } from '../../src/playcanvas/player-camera.js';
import { FLAT_REGION } from './world-kinds.js';
import {
  FIRST_REGION, PERSONAL_SCENE, WORLD_KINDS, buildBinding, worldOptions, type WorldKind,
} from './binding-harness.js';

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
    it(`${kind}: offers the city views only where each holds what it names`, async () => {
      const { binding, canvas } = await buildBinding(kind);
      const run = frames(binding);
      try {
        run(3);
        const before = pose(binding);
        const camera = drawn(binding);
        if (!viewsOf(kind).cityViews) {
          binding.setCityView('overview');
          binding.setCityView('street');
          expect(pose(binding)).toEqual(before);
          run(3);
          expect(pose(binding)).toEqual(before);
          expect(drawn(binding)).toEqual(camera);
          return;
        }
        const navigation = binding.navigationWorld;
        const fromCentre = (at: { x: number; z: number }) =>
          Math.hypot(at.x - navigation.centre.x, at.z - navigation.centre.z);
        // Street level stands on the walkable field, and stays where it was set.
        binding.setCityView('street');
        const street = pose(binding);
        run(30);
        expect(pose(binding)).toEqual(street);
        const ground = navigation.surface.sample(street.x, street.z);
        expect(ground).not.toBeNull();
        expect(street.y).toBeCloseTo(ground!.height + navigation.eyeHeight, 6);
        expect(fromCentre(street)).toBeLessThanOrEqual(navigation.fieldRadius);
        // The overview is a view from above, and is still one thirty frames later.
        binding.setCityView('overview');
        const overview = pose(binding);
        expect(overview.y).toBeGreaterThan(street.y + 30);
        run(30);
        expect(pose(binding)).toEqual(overview);
        // A view from above is a camera, not a person standing: third person draws it from the eye.
        if (viewsOf(kind).thirdPerson) {
          binding.setCameraMode('third-person');
          run(30);
          expect(reach(binding)).toBeCloseTo(0, 6);
          binding.setCameraMode('first-person');
        }
        // It pans at its own height, and walking from it moves it.
        canvas.tabIndex = 0;
        canvas.focus();
        window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyW' }));
        run(60);
        window.dispatchEvent(new KeyboardEvent('keyup', { code: 'KeyW' }));
        const panned = pose(binding);
        expect(panned.y).toBe(overview.y);
        expect(Math.hypot(panned.x - overview.x, panned.z - overview.z)).toBeGreaterThan(1);
        // Asking for street level again stands on the ground again.
        binding.setCityView('street');
        run(3);
        expect(pose(binding).y).toBeCloseTo(street.y, 6);
      } finally {
        binding.destroy();
      }
    });

    it(`${kind}: lands on the ground after travelling to a region, even from an overview`, async () => {
      // The harness district is 20 metres square, and its navigation refuses travel to a region
      // 144 metres away, as it should; the Google kinds admit the regions.
      if (!viewsOf(kind).cityViews || kind === 'owned-district') return;
      const { binding } = await buildBinding(kind, { scene: PERSONAL_SCENE });
      const run = frames(binding);
      try {
        run(3);
        binding.setCityView('overview');
        expect(binding.controls.hold).toBe('altitude');
        expect(binding.navigateToIsland(FIRST_REGION, true).ok).toBe(true);
        run(120);
        const navigation = binding.navigationWorld;
        const arrived = pose(binding);
        expect(binding.controls.hold).toBe('ground');
        const ground = navigation.surface.sample(arrived.x, arrived.z);
        expect(arrived.y).toBeCloseTo(ground!.height + navigation.eyeHeight, 6);
      } finally {
        binding.destroy();
      }
    });

    it(`${kind}: opens on its field or facing it, where walking moves the person`, async () => {
      const { binding } = await buildBinding(kind);
      const run = frames(binding);
      try {
        run(3);
        const start = pose(binding);
        const navigation = binding.navigationWorld;
        const toCentre = [navigation.centre.x - start.x, navigation.centre.z - start.z] as const;
        const distance = Math.hypot(toCentre[0], toCentre[1]);
        if (distance > navigation.fieldRadius) {
          // Outside the field, the view looks at it: the heading to its centre is within 30
          // degrees of the heading the camera faces.
          const facing = [-Math.sin(start.yaw), -Math.cos(start.yaw)] as const;
          const cosine = (facing[0] * toCentre[0] + facing[1] * toCentre[1]) / distance;
          expect(cosine).toBeGreaterThan(Math.cos(Math.PI / 6));
        }
      } finally {
        binding.destroy();
      }
      const keyed = await walked(kind, 'key');
      expect(keyed.metres).toBeGreaterThan(1);
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

describe('the third-person camera on a ground that is not at y = 0', () => {
  it('keeps the boom above the ground the person stands on while they look up', async () => {
    const raised = { ...FLAT_REGION, ground: { ...FLAT_REGION.ground, elevationMm: 5000 } };
    const { binding } = await buildBinding('authored-flat', { authoredRegion: raised });
    const run = frames(binding);
    try {
      run(3);
      expect(binding.controls.state.y).toBeCloseTo(5 + binding.navigationWorld.eyeHeight, 6);
      binding.setCameraMode('third-person');
      binding.setCameraFraming(6);
      binding.controls.state.pitch = 1.2;
      run(240);
      const [, y] = drawn(binding);
      expect(reach(binding)).toBeGreaterThan(0.3);
      expect(y!).toBeGreaterThanOrEqual(5 + DEFAULT_FOLLOW_CAMERA.groundClearance - 1e-6);
    } finally {
      binding.destroy();
    }
  });
});
