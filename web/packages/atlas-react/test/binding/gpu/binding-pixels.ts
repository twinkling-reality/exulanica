/**
 * The binding's GPU pixel scenes: the real `AtlasBinding.create` on a real WebGL2 device.
 *
 * Not a vitest file: vitest has no GPU. A browser page on the app's Vite server imports this
 * module by its `/@fs/` path and calls `renderBindingScenes`, which returns one SHA-256 per scene
 * over the exact `readPixels` bytes of a frame drawn at a fixed pose, and how many pixels differ
 * from the frame's own clear colour, so an empty frame cannot pass as a match.
 * `run_binding_pixels.mjs` drives it through headless Chrome inside the machine-wide GPU slot.
 *
 * What the digests are for: a change that is meant to move no pixel (moving code out of the
 * binding, for example) must leave every digest identical on the same machine and browser, and a
 * change that is meant to move pixels must move only the scenes it names. They are not portable
 * across GPUs or drivers; every retained run names the renderer it ran on.
 *
 * Every scene opens its own binding with reduced motion on and a fixed clock, so nothing that
 * animates can make two runs differ.
 */
import * as pc from 'playcanvas';
import { makeScene } from '@exulanica/atlas-core';
import { AtlasBinding, type AtlasBindingOptions } from '../../../src/playcanvas/atlas-binding.js';
import type { CameraState } from '../../../src/playcanvas/controls.js';
import { decodeOpm, type PointMap } from '../../../src/playcanvas/opm.js';
import { STARTER_REGION, worldOptions, type WorldKind } from '../world-kinds.js';

export const PIXEL_WIDTH = 480;
export const PIXEL_HEIGHT = 300;
/** The plate sweep's frame: large enough that the plate has an interior out to about 15 m. */
const PLATE_WIDTH = 640;
const PLATE_HEIGHT = 400;
/** The fixed clock every scene's frames run on, in milliseconds. */
const CLOCK_MS = 100_000;
/** Frames drawn before the one that is read, so everything resident has been through an update. */
const SETTLE_FRAMES = 4;

type Asset = 'cc0.marker-cube' | 'cc0.marker-plate' | 'cc0.marker-pillar';

export interface PixelScene {
  readonly name: string;
  readonly kind: WorldKind;
  /** Written over the start pose before the first frame. */
  readonly pose?: Partial<CameraState>;
  readonly map?: boolean;
  /**
   * Reviewed objects placed in the starter region, in its fixed-point units, after the world's
   * first frame, which is when the app's saved world delivers them.
   */
  readonly objects?: readonly { readonly asset: Asset; readonly xMm: number; readonly zMm: number }[];
  /** Open and close the Map after the objects are placed, as a person pressing M twice does. */
  readonly visitMap?: boolean;
}

/**
 * The scenes. The cube scenes use lane W's relative pose: 3 m south of the cube, facing north
 * and 0.25 rad down, at the arrival point and at 8 km.
 */
export const PIXEL_SCENES: readonly PixelScene[] = Object.freeze([
  { name: 'flat-starter', kind: 'authored-flat' },
  { name: 'endless-starter', kind: 'authored-endless' },
  { name: 'endless-starter-looking-up', kind: 'authored-endless', pose: { pitch: 0.35 } },
  {
    name: 'endless-cube-arrival', kind: 'authored-endless',
    objects: [{ asset: 'cc0.marker-cube', xMm: 0, zMm: 500 }],
    pose: { x: 0, z: 3.5, yaw: 0, pitch: -0.25 },
  },
  {
    name: 'endless-cube-after-map', kind: 'authored-endless', visitMap: true,
    objects: [{ asset: 'cc0.marker-cube', xMm: 0, zMm: 500 }],
    pose: { x: 0, z: 3.5, yaw: 0, pitch: -0.25 },
  },
  {
    name: 'endless-cube-8km', kind: 'authored-endless',
    objects: [{ asset: 'cc0.marker-cube', xMm: 0, zMm: -7_999_500 }],
    pose: { x: 0, z: -7996.5, yaw: 0, pitch: -0.25 },
  },
  {
    name: 'endless-plate', kind: 'authored-endless',
    objects: [{ asset: 'cc0.marker-plate', xMm: 0, zMm: 0 }],
    pose: { x: 0, z: 4, yaw: 0, pitch: -0.35 },
  },
  {
    name: 'flat-plate', kind: 'authored-flat',
    objects: [{ asset: 'cc0.marker-plate', xMm: 2000, zMm: 0 }],
    pose: { x: 0, z: 4, yaw: 0, pitch: -0.35 },
  },
  { name: 'estimate', kind: 'authored-with-estimate', pose: { x: 1.5, z: 1, yaw: 0, pitch: 0 } },
  { name: 'regions', kind: 'personal-regions' },
  { name: 'regions-map', kind: 'personal-regions', map: true },
  { name: 'district', kind: 'owned-district' },
]);

export interface PixelDigest {
  readonly scene: string;
  readonly sha256: string;
  /** Pixels differing from the camera's clear colour by more than 3 levels in any channel. */
  readonly drawnPixels: number;
  /**
   * Distinct colours down the centre column's top fifth, which is sky in every scene looking at
   * the horizon: one colour is a flat clear colour, more is a drawn sky's gradient.
   */
  readonly skyColours: number;
  readonly width: number;
  readonly height: number;
}

async function sha256(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes.slice());
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function reviewedAsset(base: string, asset: Asset): Promise<{ bytes: ArrayBuffer; sha256: string }> {
  const response = await fetch(`${base}/packages/graph-client/test/fixtures/${asset}.glb`);
  if (!response.ok) throw new Error(`${asset}: ${response.status}`);
  const bytes = await response.arrayBuffer();
  return { bytes, sha256: await sha256(new Uint8Array(bytes)) };
}

/** One frame, drawn and read in the same task: the app renders only when asked. */
function readFrame(binding: AtlasBinding): Uint8Array {
  const gl = (binding.device as unknown as { gl: WebGL2RenderingContext }).gl;
  binding.app.render();
  const previous = gl.getParameter(gl.READ_FRAMEBUFFER_BINDING);
  gl.bindFramebuffer(gl.READ_FRAMEBUFFER, null);
  const pixels = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
  gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  gl.bindFramebuffer(gl.READ_FRAMEBUFFER, previous);
  return pixels;
}

function skyColours(pixels: Uint8Array, width: number, height: number): number {
  const seen = new Set<number>();
  const column = Math.floor(width / 2);
  for (let y = 0; y < Math.floor(height / 5); y += 1) {
    const i = (y * width + column) * 4;
    seen.add((pixels[i]! << 16) | (pixels[i + 1]! << 8) | pixels[i + 2]!);
  }
  return seen.size;
}

function drawnPixels(pixels: Uint8Array, clear: pc.Color): number {
  const encode = (value: number): number => Math.round(Math.min(1, Math.max(0, value)) * 255);
  const [r, g, b] = [encode(clear.r), encode(clear.g), encode(clear.b)];
  let drawn = 0;
  for (let i = 0; i < pixels.length; i += 4) {
    if (Math.abs(pixels[i]! - r) > 3 || Math.abs(pixels[i + 1]! - g) > 3 || Math.abs(pixels[i + 2]! - b) > 3) drawn += 1;
  }
  return drawn;
}

export interface RenderedScene extends PixelDigest {
  /** Top-down RGBA rows, for a caller that wants to look. */
  readonly pixels: Uint8Array;
}

/**
 * Draw one scene. `base` is the `/@fs/` URL of the worktree's `web` directory, from which the
 * committed `.opm` pin and reviewed meshes are fetched.
 */
export async function renderScene(scene: PixelScene, base: string, opm: PointMap): Promise<RenderedScene> {
  const canvas = document.createElement('canvas');
  canvas.style.cssText = `position:fixed;left:0;top:0;width:${PIXEL_WIDTH}px;height:${PIXEL_HEIGHT}px`;
  const overlay = document.createElement('div');
  document.body.append(canvas, overlay);
  const binding = await AtlasBinding.create({
    canvas,
    overlayParent: overlay,
    deviceTypes: ['webgl2'],
    scene: makeScene([], 1, 1),
    pointMaps: new Map(),
    maxPixelRatio: 1,
    reducedMotion: true,
    overlay: false,
    ...worldOptions(scene.kind, opm),
  } as AtlasBindingOptions);
  try {
    binding.app.autoRender = false;
    binding.app.resizeCanvas(PIXEL_WIDTH, PIXEL_HEIGHT);
    binding.update(1 / 60, CLOCK_MS - 16);
    for (const [index, placed] of (scene.objects ?? []).entries()) {
      const { bytes, sha256: digest } = await reviewedAsset(base, placed.asset);
      await binding.objects.place({
        objectId: `pixel-object-${index}`,
        islandId: STARTER_REGION,
        asset: { assetKey: placed.asset, mediaType: 'model/gltf-binary', contentSha256: digest, byteSize: bytes.byteLength },
        transform: { xMm: placed.xMm, yMm: 0, zMm: placed.zMm, yawMicroradians: 3_141_593, scaleMilli: 1000 },
        behaviour: null,
      }, bytes);
    }
    if (scene.visitMap === true) {
      binding.setMapMode(true);
      binding.update(1 / 60, CLOCK_MS - 8);
      binding.setMapMode(false);
    }
    if (scene.map === true) binding.setMapMode(true);
    Object.assign(binding.controls.state, scene.pose ?? {});
    for (let frame = 0; frame < SETTLE_FRAMES; frame += 1) {
      binding.update(1 / 60, CLOCK_MS + frame * 16);
      binding.app.render();
    }
    binding.update(1 / 60, CLOCK_MS + SETTLE_FRAMES * 16);
    const bottomUp = readFrame(binding);
    const width = binding.device.width;
    const height = binding.device.height;
    const pixels = new Uint8Array(bottomUp.length);
    for (let y = 0; y < height; y += 1) {
      pixels.set(bottomUp.subarray((height - 1 - y) * width * 4, (height - y) * width * 4), y * width * 4);
    }
    return {
      scene: scene.name,
      sha256: await sha256(pixels),
      drawnPixels: drawnPixels(pixels, binding.camera.camera!.clearColor),
      skyColours: skyColours(pixels, width, height),
      width,
      height,
      pixels,
    };
  } finally {
    binding.destroy();
    canvas.remove();
    overlay.remove();
  }
}

/** Every scene, in order, as digests. */
export async function renderBindingScenes(base: string, only?: readonly string[]): Promise<PixelDigest[]> {
  const response = await fetch(`${base}/packages/atlas-react/test/fixtures/python-writer.opm`);
  const opm = decodeOpm(await response.arrayBuffer());
  const out: PixelDigest[] = [];
  for (const scene of PIXEL_SCENES) {
    if (only !== undefined && !only.includes(scene.name)) continue;
    const { pixels: _pixels, ...digest } = await renderScene(scene, base, opm);
    out.push(digest);
  }
  return out;
}

/** How much of a marker plate lying on a ground is drawn, over a sweep of camera poses. */
export interface PlateSweep {
  readonly ground: string;
  readonly poses: number;
  /** Poses at which the plate's footprint has an interior (it is not a sliver). */
  readonly measured: number;
  /** Smallest share of the interior where the plate changes the frame at all. */
  readonly drawnMin: number;
  /** Smallest share of the interior drawn exactly as the plate alone, with no ground behind it. */
  readonly cleanMin: number;
  /** Poses at which less than 99 per cent of the interior is drawn clean. */
  readonly underWhole: number;
}

/**
 * Place a reviewed marker plate at (xMm, zMm) on a starter ground and walk the camera back from
 * 1.5 m to 40 m in 0.25 m steps at eye height, aimed at the plate's centre. At each pose, four
 * frames drawn and read in one task: as drawn, without the plate, the plate with the ground
 * field hidden, and neither. The plate's footprint is where the last two differ, less its edge
 * (every pixel must have its four neighbours in it too, so antialiasing does not count). A plate
 * that ties with the ground it lies on is partly or wholly missing at some poses.
 */
export async function plateSweep(
  base: string,
  opm: PointMap,
  kind: 'authored-endless' | 'authored-flat',
  xMm: number,
  zMm: number,
): Promise<PlateSweep> {
  const canvas = document.createElement('canvas');
  canvas.style.cssText = `position:fixed;left:0;top:0;width:${PLATE_WIDTH}px;height:${PLATE_HEIGHT}px`;
  const overlay = document.createElement('div');
  document.body.append(canvas, overlay);
  const binding = await AtlasBinding.create({
    canvas, overlayParent: overlay, deviceTypes: ['webgl2'], scene: makeScene([], 1, 1),
    pointMaps: new Map(), maxPixelRatio: 1, reducedMotion: true, overlay: false,
    ...worldOptions(kind, opm),
  } as AtlasBindingOptions);
  try {
    binding.app.autoRender = false;
    binding.app.resizeCanvas(PLATE_WIDTH, PLATE_HEIGHT);
    binding.update(1 / 60, CLOCK_MS);
    const { bytes, sha256: digest } = await reviewedAsset(base, 'cc0.marker-plate');
    await binding.objects.place({
      objectId: 'plate', islandId: STARTER_REGION,
      asset: { assetKey: 'cc0.marker-plate', mediaType: 'model/gltf-binary', contentSha256: digest, byteSize: bytes.byteLength },
      transform: { xMm, yMm: 0, zMm, yawMicroradians: 0, scaleMilli: 1000 }, behaviour: null,
    }, bytes);
    const plate = binding.app.root.findByName('authored-object:plate') as pc.Entity;
    const field = binding.field.entity;
    const differs = (a: Uint8Array, b: Uint8Array, i: number): boolean =>
      Math.abs(a[i]! - b[i]!) > 3 || Math.abs(a[i + 1]! - b[i + 1]!) > 3 || Math.abs(a[i + 2]! - b[i + 2]!) > 3;
    let poses = 0; let measured = 0; let drawnMin = 1; let cleanMin = 1; let underWhole = 0;
    for (let step = 0; step <= (40 - 1.5) / 0.25; step += 1) {
      const back = 1.5 + step * 0.25;
      const state = binding.controls.state;
      const eye = binding.navigationWorld.eyeHeight;
      state.x = xMm / 1000 + 0.3;
      state.z = zMm / 1000 + back;
      state.yaw = Math.atan2(0.3, back);
      state.pitch = -Math.atan2(eye, Math.hypot(0.3, back));
      binding.update(1 / 60, CLOCK_MS);
      const drawn = readFrame(binding);
      plate.enabled = false; const without = readFrame(binding); plate.enabled = true;
      field.enabled = false; const alone = readFrame(binding);
      plate.enabled = false; const empty = readFrame(binding); plate.enabled = true; field.enabled = true;
      const mask = new Uint8Array(PLATE_WIDTH * PLATE_HEIGHT);
      for (let k = 0; k < mask.length; k += 1) mask[k] = differs(alone, empty, k * 4) ? 1 : 0;
      let footprint = 0; let shown = 0; let clean = 0;
      for (let y = 1; y < PLATE_HEIGHT - 1; y += 1) {
        for (let x = 1; x < PLATE_WIDTH - 1; x += 1) {
          const k = y * PLATE_WIDTH + x;
          if (!mask[k] || !mask[k - 1] || !mask[k + 1] || !mask[k - PLATE_WIDTH] || !mask[k + PLATE_WIDTH]) continue;
          footprint += 1;
          if (differs(drawn, without, k * 4)) shown += 1;
          if (!differs(drawn, alone, k * 4)) clean += 1;
        }
      }
      poses += 1;
      if (footprint === 0) continue;
      measured += 1;
      drawnMin = Math.min(drawnMin, shown / footprint);
      cleanMin = Math.min(cleanMin, clean / footprint);
      if (clean / footprint < 0.99) underWhole += 1;
    }
    return { ground: `${kind}@${xMm},${zMm}`, poses, measured, drawnMin, cleanMin, underWhole };
  } finally {
    binding.destroy();
    canvas.remove();
    overlay.remove();
  }
}

/** The plate sweeps a run reports: the endless ground at its origin and at 8 km, the flat ground. */
export async function plateSweeps(base: string): Promise<PlateSweep[]> {
  const opm = decodeOpm(await (await fetch(`${base}/packages/atlas-react/test/fixtures/python-writer.opm`)).arrayBuffer());
  return [
    await plateSweep(base, opm, 'authored-endless', 0, 0),
    await plateSweep(base, opm, 'authored-endless', 0, -8_000_000),
    await plateSweep(base, opm, 'authored-flat', 2000, 0),
  ];
}
