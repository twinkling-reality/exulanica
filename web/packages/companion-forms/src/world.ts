/**
 * Candidate C: world-rendered.
 *
 * A real solid, lit by the same directional light, ambient haze, exposure and tone mapping the
 * Atlas binding sets, so the comparison is against the world the Companion would actually stand
 * in rather than against a studio render. Geometry is procedural: there is no glTF here, and that
 * is deliberate. The binding registers only TextureHandler and GSplatHandler, so the product
 * cannot load a container asset at all today, and a candidate that quietly assumed one would be
 * measuring a pipeline that does not exist.
 *
 * The honest limitation is the silhouette. The catalog is a set of 2D paths, and a solid has a
 * silhouette only from a given angle. A sphere reads as `circle` from anywhere and a capsule
 * reads as `capsule`, but `cloud`, `droplet`, `arch` and `lozenge` have no primitive, so a depth
 * axis either forks the catalog or ships a mesh per silhouette. That is a decision, not a bug,
 * and surfacing it is most of what this candidate is for.
 */

import * as pc from 'playcanvas';

import {
  companionAvatarBlueprint,
  DEFAULT_COMPANION,
  ORIGIN_LANDSCAPE,
  type CompanionAppearanceConfiguration,
  type CompanionBodyVariant,
  type CompanionOperationalState,
} from '@exulanica/presentation';

import type { CompanionForm } from './form.js';

/** How faithfully a primitive stands in for an authored path, from a fixed camera. */
type Fidelity = 'exact' | 'approximate' | 'unrepresentable';

interface Solid {
  readonly kind: 'sphere' | 'capsule' | 'box';
  readonly scale: readonly [number, number, number];
  readonly fidelity: Fidelity;
}

/**
 * The catalog, as solids. A silhouette whose outline a primitive reproduces from the bench camera
 * is exact; one it only suggests is approximate; one with no primitive at all is named as such
 * rather than quietly swapped for a sphere.
 */
export const SOLIDS: Readonly<Record<CompanionBodyVariant, Solid>> = Object.freeze({
  circle: { kind: 'sphere', scale: [1, 1, 1], fidelity: 'exact' },
  capsule: { kind: 'capsule', scale: [1, 1, 1], fidelity: 'exact' },
  bead: { kind: 'sphere', scale: [0.86, 1.06, 0.86], fidelity: 'exact' },
  pebble: { kind: 'sphere', scale: [1.04, 0.94, 0.98], fidelity: 'approximate' },
  squircle: { kind: 'box', scale: [0.92, 0.92, 0.92], fidelity: 'approximate' },
  cloud: { kind: 'sphere', scale: [1.1, 0.82, 0.95], fidelity: 'unrepresentable' },
  droplet: { kind: 'sphere', scale: [0.95, 1.05, 0.95], fidelity: 'unrepresentable' },
  arch: { kind: 'capsule', scale: [1, 0.92, 1], fidelity: 'unrepresentable' },
  lozenge: { kind: 'box', scale: [0.9, 0.9, 0.9], fidelity: 'unrepresentable' },
});

const unitRgb = (hex: string): [number, number, number] => [
  Number.parseInt(hex.slice(1, 3), 16) / 255,
  Number.parseInt(hex.slice(3, 5), 16) / 255,
  Number.parseInt(hex.slice(5, 7), 16) / 255,
];

const colorOf = (hex: string): pc.Color => {
  const [r, g, b] = unitRgb(hex);
  return new pc.Color(r, g, b);
};

export function createWorldForm(): CompanionForm {
  const element = document.createElement('div');
  element.className = 'form-canvas form-canvas-world';
  const canvas = document.createElement('canvas');
  element.append(canvas);

  let app: pc.AppBase | null = null;
  let body: pc.Entity | null = null;
  let eyes: pc.Entity | null = null;
  let thinking: pc.Entity | null = null;
  let material: pc.StandardMaterial | null = null;
  let eyeMaterial: pc.StandardMaterial | null = null;
  let meshes: Record<Solid['kind'], pc.Mesh> | null = null;
  let disposed = false;
  let running = false;
  const observers: ResizeObserver[] = [];
  let appearance: CompanionAppearanceConfiguration = DEFAULT_COMPANION;
  let state: CompanionOperationalState = 'resting';

  const applyAppearance = (): void => {
    if (body === null || material === null || eyeMaterial === null || meshes === null) return;
    const solid = SOLIDS[appearance.bodyVariant];
    const render = body.render;
    if (render !== undefined && render !== null) render.meshInstances[0]!.mesh = meshes[solid.kind];
    body.setLocalScale(solid.scale[0], solid.scale[1], solid.scale[2]);
    material.diffuse = colorOf(appearance.bodyColor);
    material.update();
    eyeMaterial.diffuse = colorOf(appearance.eyeColor);
    eyeMaterial.emissive = colorOf(appearance.eyeColor);
    eyeMaterial.update();

    // The eye pose is authored in the 240-unit blueprint box; map it onto the front of the solid.
    const pose = companionAvatarBlueprint(appearance).eyePose;
    const placed = [pose.left, pose.right];
    eyes?.children.forEach((eye, index) => {
      const [x, y, width, height] = placed[index]!;
      const cx = (x + width / 2 - 120) / 120;
      const cy = -(y + height / 2 - 120) / 120;
      (eye as pc.Entity).setLocalPosition(cx * 0.74, cy * 0.74, 0.82);
      (eye as pc.Entity).setLocalScale((width / 240) * 1.9, (height / 240) * 1.9, 0.16);
    });
  };

  const applyState = (): void => {
    const thinkingNow = state === 'working';
    body?.enabled !== undefined && (body.enabled = !thinkingNow);
    eyes?.enabled !== undefined && (eyes.enabled = !thinkingNow);
    thinking?.enabled !== undefined && (thinking.enabled = thinkingNow);
  };

  void (async () => {
    const device = await pc.createGraphicsDevice(canvas, { deviceTypes: ['webgl2'] });
    if (disposed) return;
    device.maxPixelRatio = Math.min(globalThis.devicePixelRatio ?? 1, 1.5);

    const created = new pc.AppBase(canvas);
    const appOptions = new pc.AppOptions();
    appOptions.graphicsDevice = device;
    appOptions.componentSystems = [
      pc.RenderComponentSystem,
      pc.CameraComponentSystem,
      pc.LightComponentSystem,
    ];
    appOptions.resourceHandlers = [];
    created.init(appOptions);
    created.setCanvasFillMode(pc.FILLMODE_NONE);
    created.setCanvasResolution(pc.RESOLUTION_AUTO);
    app = created;

    /*
     * The bench gives every candidate the same square box, so the solid has to fill it. With
     * FILLMODE_NONE the backing store does not follow CSS on its own, and a canvas whose buffer
     * disagrees with its box renders a stretched sphere, which would have the bench comparing an
     * aspect-ratio bug against two SVGs.
     */
    const resize = (): void => {
      const rect = element.getBoundingClientRect();
      const width = Math.max(1, Math.round(rect.width));
      const height = Math.max(1, Math.round(rect.height));
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      created.resizeCanvas(width, height);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    observers.push(observer);

    const palette = ORIGIN_LANDSCAPE.palette;
    const camera = new pc.Entity('form-camera');
    const [skyR, skyG, skyB] = unitRgb(palette.sky);
    camera.addComponent('camera', {
      fov: 34,
      nearClip: 0.05,
      farClip: 40,
      clearColor: new pc.Color(skyR, skyG, skyB, 1),
    });
    if (camera.camera !== undefined && camera.camera !== null) {
      camera.camera.toneMapping = pc.TONEMAP_ACES;
    }
    camera.setPosition(0, 0, 5.4);
    created.root.addChild(camera);

    const [hazeR, hazeG, hazeB] = unitRgb(palette.haze);
    created.scene.ambientLight = new pc.Color(hazeR * 0.58, hazeG * 0.58, hazeB * 0.58);
    created.scene.exposure = 1.06;

    const light = new pc.Entity('form-directional-light');
    const [sunR, sunG, sunB] = unitRgb(palette.sun);
    light.addComponent('light', {
      type: 'directional',
      color: new pc.Color(sunR, sunG, sunB),
      intensity: 1.65,
      // Shadows are off: one object casts onto nothing, and a 2048 map for that is a number the
      // bench would be measuring instead of the form.
      castShadows: false,
    });
    light.setEulerAngles(48, 132, 0);
    created.root.addChild(light);

    meshes = {
      sphere: pc.Mesh.fromGeometry(device, new pc.SphereGeometry({ radius: 1, latitudeBands: 32, longitudeBands: 48 })),
      capsule: pc.Mesh.fromGeometry(device, new pc.CapsuleGeometry({ radius: 0.78, height: 1.1, sides: 32 })),
      box: pc.Mesh.fromGeometry(device, new pc.BoxGeometry({ halfExtents: new pc.Vec3(0.86, 0.86, 0.86) })),
    };

    material = new pc.StandardMaterial();
    material.gloss = 0.42;
    material.metalness = 0;
    material.useMetalness = true;
    material.update();

    eyeMaterial = new pc.StandardMaterial();
    eyeMaterial.gloss = 0.1;
    eyeMaterial.update();

    body = new pc.Entity('companion-body');
    body.addComponent('render', { meshInstances: [new pc.MeshInstance(meshes.sphere, material)] });
    created.root.addChild(body);

    eyes = new pc.Entity('companion-eyes');
    for (const side of ['left', 'right']) {
      const eye = new pc.Entity(`companion-eye-${side}`);
      eye.addComponent('render', { meshInstances: [new pc.MeshInstance(meshes.sphere, eyeMaterial)] });
      eyes.addChild(eye);
    }
    created.root.addChild(eyes);

    thinking = new pc.Entity('companion-working');
    for (const offset of [-0.62, 0, 0.62]) {
      const dot = new pc.Entity('companion-working-dot');
      dot.addComponent('render', { meshInstances: [new pc.MeshInstance(meshes.sphere, material)] });
      dot.setLocalPosition(offset, 0, 0);
      dot.setLocalScale(offset === 0 ? 0.3 : 0.23, offset === 0 ? 0.3 : 0.23, offset === 0 ? 0.3 : 0.23);
      thinking.addChild(dot);
    }
    created.root.addChild(thinking);

    applyAppearance();
    applyState();
    if (running) created.start();
  })();

  return {
    dossier: {
      id: 'world',
      title: 'World-rendered',
      summary:
        'A lit solid under the Atlas directional light, haze, exposure and ACES tone mapping. '
        + 'Procedural geometry, because the binding cannot load a container asset today.',
      renderer:
        'A second renderer surface. The Companion is a screen-space DOM overlay by decision '
        + '(interaction-model.md 4.2), and the canvas sits behind the shell, so this needs either '
        + 'its own canvas or a reversal of that placement decision.',
      assets:
        'None as built, because the geometry is procedural. A hand-modelled Companion would need '
        + 'a container handler, which is not registered, plus a licence entry that '
        + 'docs/license-matrix.md does not currently have for avatar art.',
      accessibility:
        'Canvas content is invisible to screen readers, so the DOM lens stays the accessibility '
        + 'surface. Forced colours cannot reach it at all: a high-contrast user gets the lit '
        + 'render regardless, which flat and relief both avoid.',
      silhouettes:
        'Three of nine from the bench camera (circle, capsule, bead). Two approximate (pebble, '
        + 'squircle). Four have no primitive at all (cloud, droplet, arch, lozenge) and would '
        + 'need a mesh each.',
      workingState: 'Three lit spheres replace the body, which reads as objects rather than dots.',
    },
    element,
    setAppearance(next) {
      appearance = next;
      applyAppearance();
    },
    setState(next) {
      state = next;
      applyState();
    },
    start() {
      running = true;
      app?.start();
    },
    stop() {
      running = false;
      // PlayCanvas has no public pause; ticking a scene nobody is looking at is exactly the cost
      // this bench exists to measure, so the bench stops it by disposing between runs instead.
    },
    dispose() {
      disposed = true;
      running = false;
      for (const observer of observers) observer.disconnect();
      observers.length = 0;
      app?.destroy();
      app = null;
      element.replaceChildren();
    },
  };
}
