/**
 * GPU pixel scenes for the data view, run in a real browser against a real WebGL2 device.
 *
 * Not a vitest file: vitest has no GPU. A page served by the app's Vite server imports this module
 * by its `/@fs/` path and calls `renderBaselineScenes()`, which returns one SHA-256 per scene over
 * the exact `readPixels` bytes. This file uses only APIs that also exist on main before the data
 * view lane (`staticMeshRepresentation`, `RepresentationRuntime`, `createPointCloud`, `decodeOpm`),
 * so the same file, copied into a checkout of main, yields main's digests for comparison.
 * `data-view-pixels.ts` holds the checks only the lane can run.
 */
import * as pc from 'playcanvas';
import * as core from '@exulanica/atlas-core';
import type { RepresentationSubject } from '@exulanica/atlas-core';
import { createPointCloud } from '../../src/playcanvas/point-cloud.js';
import { decodeOpm, type PointMap } from '../../src/playcanvas/opm.js';
import { staticMeshRepresentation } from '../../src/playcanvas/representation-binding.js';
import { RepresentationRuntime } from '../../src/playcanvas/representation-runtime.js';

export const PIXEL_WIDTH = 320;
export const PIXEL_HEIGHT = 240;

export interface PixelDigest {
  readonly scene: string;
  readonly sha256: string;
  /** Pixels that differ from the clear colour, so an empty frame cannot pass as a match. */
  readonly drawnPixels: number;
  /** For a surface scene, whether the map was actually drawn as a surface. */
  readonly surfaceBuilt?: boolean;
}

export interface PixelStage {
  readonly app: pc.AppBase;
  readonly device: pc.GraphicsDevice;
  readonly canvas: HTMLCanvasElement;
  readonly camera: pc.Entity;
  readonly root: pc.Entity;
  destroy(): void;
}

const CLEAR = [0.79, 0.85, 0.88] as const;

export async function createStage(): Promise<PixelStage> {
  const canvas = document.createElement('canvas');
  canvas.width = PIXEL_WIDTH;
  canvas.height = PIXEL_HEIGHT;
  canvas.style.cssText = `position:fixed;left:0;top:0;width:${PIXEL_WIDTH}px;height:${PIXEL_HEIGHT}px;visibility:hidden`;
  document.body.append(canvas);
  const device = await pc.createGraphicsDevice(canvas, {
    deviceTypes: ['webgl2'], antialias: false, depth: true, stencil: false,
    preserveDrawingBuffer: true,
  } as Parameters<typeof pc.createGraphicsDevice>[1]);
  device.maxPixelRatio = 1;
  const app = new pc.AppBase(canvas);
  const options = new pc.AppOptions();
  options.graphicsDevice = device;
  options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
  options.resourceHandlers = [];
  app.init(options);
  app.setCanvasFillMode(pc.FILLMODE_NONE);
  app.setCanvasResolution(pc.RESOLUTION_FIXED, PIXEL_WIDTH, PIXEL_HEIGHT);
  app.autoRender = false;
  const camera = new pc.Entity('pixel-camera');
  camera.addComponent('camera', {
    fov: 60, nearClip: 0.08, farClip: 400,
    clearColor: new pc.Color(CLEAR[0], CLEAR[1], CLEAR[2], 1),
  });
  if (camera.camera) camera.camera.toneMapping = pc.TONEMAP_ACES;
  camera.setPosition(0, 2.5, 7);
  camera.lookAt(0, 1, -1);
  app.root.addChild(camera);
  const light = new pc.Entity('pixel-light');
  light.addComponent('light', { type: 'directional', color: new pc.Color(1, 0.96, 0.9), intensity: 1.4 });
  light.setEulerAngles(45, 30, 0);
  app.root.addChild(light);
  app.scene.ambientLight = new pc.Color(0.64, 0.69, 0.74);
  const root = new pc.Entity('pixel-root');
  app.root.addChild(root);
  return {
    app, device, canvas, camera, root,
    destroy() { app.destroy(); canvas.remove(); },
  };
}

/** Draw a few frames and hash the result. The frames settle shader compilation and uploads. */
export async function digestStage(stage: PixelStage, scene: string, frames = 3): Promise<PixelDigest> {
  for (let i = 0; i < frames; i += 1) {
    stage.app.update(0);
    stage.app.render();
  }
  const gl = (stage.device as unknown as { gl: WebGL2RenderingContext }).gl;
  const pixels = new Uint8Array(PIXEL_WIDTH * PIXEL_HEIGHT * 4);
  gl.readPixels(0, 0, PIXEL_WIDTH, PIXEL_HEIGHT, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  return { scene, sha256: await sha256(pixels), drawnPixels: drawnPixels(pixels) };
}

export async function sha256(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes as unknown as ArrayBuffer);
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
}

function drawnPixels(pixels: Uint8Array): number {
  const r = pixels[0]!; const g = pixels[1]!; const b = pixels[2]!;
  let count = 0;
  for (let i = 0; i < pixels.length; i += 4) {
    if (pixels[i] !== r || pixels[i + 1] !== g || pixels[i + 2] !== b) count += 1;
  }
  return count;
}

export interface BoxSpec {
  readonly id: string;
  readonly colour: readonly [number, number, number];
  readonly position: readonly [number, number, number];
  readonly halfExtents: readonly [number, number, number];
}

export const BOXES: readonly BoxSpec[] = [
  { id: 'pixel:box-a', colour: [0.72, 0.42, 0.34], position: [-1.6, 1, -1], halfExtents: [0.8, 1, 0.8] },
  { id: 'pixel:box-b', colour: [0.36, 0.52, 0.7], position: [1.4, 1.4, -2], halfExtents: [0.9, 1.4, 0.7] },
  { id: 'pixel:ground', colour: [0.62, 0.64, 0.6], position: [0, -0.05, -1], halfExtents: [6, 0.05, 6] },
];

export function boxSubject(spec: BoxSpec, changes: Partial<RepresentationSubject> = {}): RepresentationSubject {
  return {
    subjectId: spec.id, subjectKind: 'geometry-group', sceneId: null,
    frameId: 'pixel:render-metres', origin: 'generated', sourceRefs: [spec.id],
    availability: 'available', rendered: true, points: 'mesh-surface-samples',
    compatibleBlend: true,
    bounds: {
      frameId: 'pixel:render-metres', units: 'metres', origin: 'generated', basis: 'source-bounds',
      min: [-spec.halfExtents[0], -spec.halfExtents[1], -spec.halfExtents[2]],
      max: [spec.halfExtents[0], spec.halfExtents[1], spec.halfExtents[2]],
    },
    label: spec.id.slice('pixel:'.length), dataAvailable: true, unavailableReason: null,
    ...changes,
  };
}

/** One entity per box, each a static StandardMaterial triangle draw the data view may borrow. */
export function addBoxes(stage: PixelStage, specs: readonly BoxSpec[] = BOXES): Map<string, pc.MeshInstance> {
  const instances = new Map<string, pc.MeshInstance>();
  for (const spec of specs) {
    const material = new pc.StandardMaterial();
    material.diffuse = new pc.Color(...spec.colour);
    material.update();
    const mesh = pc.Mesh.fromGeometry(stage.device, new pc.BoxGeometry({
      halfExtents: new pc.Vec3(...spec.halfExtents),
    }));
    const entity = new pc.Entity(spec.id);
    entity.setPosition(...spec.position);
    const instance = new pc.MeshInstance(mesh, material, entity);
    entity.addComponent('render', { meshInstances: [instance] });
    stage.root.addChild(entity);
    instances.set(spec.id, instance);
  }
  return instances;
}

/** Register every box with a runtime at the given subjects, and apply its current intent. */
export function registerBoxes(
  stage: PixelStage,
  runtime: RepresentationRuntime,
  instances: ReadonlyMap<string, pc.MeshInstance>,
  subjects: ReadonlyMap<string, () => RepresentationSubject>,
): void {
  for (const [id, instance] of instances) {
    const subject = subjects.get(id);
    if (subject === undefined) continue;
    const draw = staticMeshRepresentation(stage.device, instance, subject);
    if (draw === null) throw new Error(`${id} was refused as a static mesh draw`);
    runtime.register(draw);
  }
  runtime.update();
}

export async function fixturePointMap(url: string) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`fixture ${url} returned ${response.status}`);
  return decodeOpm(await response.arrayBuffer());
}

/**
 * A dense single-photograph grid, built in memory in the container's planar layout: every point is
 * the unprojection of one cell of a 96 by 72 pinhole grid, so the surface path can rebuild it.
 */
export function syntheticPointMap(): PointMap {
  const width = 96; const height = 72; const count = width * height;
  const fovYDeg = 50; const aspect = width / height;
  const tanY = Math.tan((fovYDeg * Math.PI) / 360); const tanX = tanY * aspect;
  const buffer = new ArrayBuffer(count * 20);
  const position = new Float32Array(buffer, 0, count * 3);
  const color = new Uint8Array(buffer, count * 12, count * 4);
  const tags = new Uint16Array(buffer, count * 16, count * 2);
  const min = [Infinity, Infinity, Infinity]; const max = [-Infinity, -Infinity, -Infinity];
  for (let row = 0; row < height; row += 1) {
    for (let column = 0; column < width; column += 1) {
      const i = row * width + column;
      const u = ((column + 0.5) / width) * 2 - 1;
      const v = 1 - ((row + 0.5) / height) * 2;
      const depth = 3 + 0.35 * Math.sin(u * 3) * Math.cos(v * 2);
      const xyz = [u * depth * tanX, v * depth * tanY, -depth];
      for (let axis = 0; axis < 3; axis += 1) {
        position[i * 3 + axis] = xyz[axis]!;
        min[axis] = Math.min(min[axis]!, position[i * 3 + axis]!);
        max[axis] = Math.max(max[axis]!, position[i * 3 + axis]!);
      }
      color[i * 4] = Math.round(255 * column / (width - 1));
      color[i * 4 + 1] = Math.round(255 * row / (height - 1));
      color[i * 4 + 2] = 140;
      color[i * 4 + 3] = 255;
    }
  }
  return {
    header: {
      format: 'exulanica-point-map', version: 2, pointCount: count, rung: 3, frame: 'local',
      up: '+Y', forward: '-Z', units: 'metres', metric: true,
      viewpoint: { position: [0, 0, 0], forward: [0, 0, -1], up: [0, 1, 0], fovYDeg, aspect },
      sourceImage: { width, height }, modelImage: { width, height },
      bounds: { min: min as [number, number, number], max: max as [number, number, number] },
      colorAlpha: 'confidence', segments: [], sections: [],
    } as unknown as PointMap['header'],
    buffer, position, color, tags,
    planarContiguous: true, packedByteOffset: 0, packedByteLength: count * 20,
  };
}

/** The personal point-map look at its existing settings: points, blended points and a surface. */
export async function pointMapScenes(opmUrl: string): Promise<PixelDigest[]> {
  const out: PixelDigest[] = [];
  for (const [prefix, map, position] of [
    // The fixture is a 2 m plane 4 m in front of its own camera; this puts it about 4 m from ours.
    ['point-map', await fixturePointMap(opmUrl), [0, 1.6, 7]],
    ['synthetic-map', syntheticPointMap(), [0, 1.2, 6.5]],
  ] as const) {
    for (const variant of [
      { name: `${prefix}-points`, options: {} },
      { name: `${prefix}-blend`, options: { blend: true } },
      { name: `${prefix}-surface`, options: { surface: true } },
    ] as const) {
      const stage = await createStage();
      const cloud = createPointCloud({ device: stage.device, map, semantics: [], ...variant.options });
      const entity = new pc.Entity(variant.name);
      entity.setPosition(position[0], position[1], position[2]);
      entity.addComponent('render', { meshInstances: [new pc.MeshInstance(cloud.mesh, cloud.material)] });
      stage.root.addChild(entity);
      out.push({ ...await digestStage(stage, variant.name), ...(variant.options.surface ? { surfaceBuilt: cloud.surface } : {}) });
      cloud.destroy();
      stage.destroy();
    }
  }
  return out;
}

/** The rendered end of the slider, on this checkout's own runtime and default intent. */
export async function renderedEndScene(): Promise<PixelDigest> {
  const stage = await createStage();
  const instances = addBoxes(stage);
  const runtime = new RepresentationRuntime();
  const subjects = new Map(BOXES.map(spec => [spec.id, () => boxSubject(spec)] as const));
  registerBoxes(stage, runtime, instances, subjects);
  runtime.setIntent(core.DEFAULT_REPRESENTATION_INTENT);
  const digest = await digestStage(stage, 'rendered-end-with-registered-subjects');
  runtime.destroy();
  stage.destroy();
  return digest;
}

/** The same boxes with no representation runtime at all: what the world draws on its own. */
export async function unregisteredScene(): Promise<PixelDigest> {
  const stage = await createStage();
  addBoxes(stage);
  const digest = await digestStage(stage, 'boxes-without-representation');
  stage.destroy();
  return digest;
}

export async function renderBaselineScenes(opmUrl: string): Promise<PixelDigest[]> {
  return [await unregisteredScene(), await renderedEndScene(), ...await pointMapScenes(opmUrl)];
}
