/**
 * TEST-ONLY BENCH for the generated tile runtime's materials and look. Served by its own Vite
 * config in this directory, never by the app, never built.
 *
 * It draws the committed texture sets on hand-built test geometry under the tile look, and it
 * measures the look targets from rendered pixels: the normal map's sign, fog onset, the probe and
 * contact shadowing. Every measurement pumps frames synchronously, so it works while the Browser
 * pane is hidden. `window.bench` is the automation surface.
 */

import * as pc from 'playcanvas';
import { parseTextureSetManifest, textureSetBlobPath, type TextureSetManifest } from '@exulanica/atlas-core';
import { TILE_LOOK_V1, validateTileLook, type TileLook } from '../../src/playcanvas/generated-tile/look.js';
import { TileTextureLibrary, castsShadow, drawBucket, surfaceUv, type TileMaterialReference } from '../../src/playcanvas/generated-tile/texture-materials.js';
import { buildSurfaceMesh } from '../../src/playcanvas/generated-tile/surface-mesh.js';
import { applyTileEnvironment, type TileEnvironment } from '../../src/playcanvas/generated-tile/environment.js';
import {
  CORNICE, DOOR, KERB_FACE_Z, KERB_HEIGHT_M, WALL, WALL_Z,
  calibrationWall, testStreet, type TestStreetSets, type TestSurface,
} from './test-street.js';
import { testCutoutSet } from './test-cutout.js';
import { TEST_BACKING_DEPTH_M, backingTexels, testGlazingSet } from './test-glazing.js';
import { testDecalSet } from './test-decal.js';
import type { DecodedTextureSet } from '@exulanica/atlas-core';

declare const __TEXTURE_ROOT__: string;

const EYE_M = 1.62;
const UNIT_SCALE: TileMaterialReference = {
  textureSetId: '', repeatSizeMillionths: 1_000_000, rotationUrad: 0, offsetUMm: 0, offsetVMm: 0,
};

type Pose = { readonly position: readonly [number, number, number]; readonly target: readonly [number, number, number] };

interface Region { readonly name: string; readonly world: readonly [number, number, number]; readonly half: number }

const luminance = (r: number, g: number, b: number): number => 0.2126 * r + 0.7152 * g + 0.0722 * b;

function pearson(a: Float64Array, b: Float64Array): number {
  let ma = 0; let mb = 0;
  for (let i = 0; i < a.length; i += 1) { ma += a[i]!; mb += b[i]!; }
  ma /= a.length; mb /= b.length;
  let ab = 0; let aa = 0; let bb = 0;
  for (let i = 0; i < a.length; i += 1) {
    const da = a[i]! - ma; const db = b[i]! - mb;
    ab += da * db; aa += da * da; bb += db * db;
  }
  return ab / Math.sqrt(aa * bb);
}

export class Bench {
  readonly root = new pc.Entity('bench-root');
  private surfaces: pc.Entity[] = [];
  private meshes: pc.Mesh[] = [];
  environment: TileEnvironment | null = null;
  look: TileLook = TILE_LOOK_V1;
  drawnSets: readonly string[] = [];

  private constructor(
    readonly app: pc.AppBase,
    readonly canvas: HTMLCanvasElement,
    readonly camera: pc.Entity,
    readonly manifest: TextureSetManifest,
    readonly library: TileTextureLibrary,
    readonly setBytes: Map<string, number>,
  ) {}

  static async create(canvas: HTMLCanvasElement): Promise<Bench> {
    const device = await pc.createGraphicsDevice(canvas, {
      // No preserved buffer: every read happens in the same task as the render it reads.
      deviceTypes: ['webgl2'], antialias: false, depth: true, stencil: false,
    });
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem];
    options.resourceHandlers = [pc.TextureHandler];
    app.init(options);
    app.autoRender = false;
    app.setCanvasFillMode(pc.FILLMODE_NONE);
    app.setCanvasResolution(pc.RESOLUTION_FIXED, 1440, 900);
    const camera = new pc.Entity('bench-camera');
    camera.addComponent('camera', { fov: 70, nearClip: 0.08, farClip: 1200 });
    app.root.addChild(camera);
    const manifestBytes = new Uint8Array(await (await fetch(`${__TEXTURE_ROOT__}/manifest.json`)).arrayBuffer());
    const manifest = parseTextureSetManifest(manifestBytes);
    const setBytes = new Map<string, number>();
    const library = new TileTextureLibrary(device, TILE_LOOK_V1, manifest, async (entry) => {
      const response = await fetch(`${__TEXTURE_ROOT__}/${textureSetBlobPath(entry)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      setBytes.set(entry.setId, bytes.byteLength);
      return bytes;
    });
    const bench = new Bench(app, canvas, camera, manifest, library, setBytes);
    app.root.addChild(bench.root);
    bench.environment = applyTileEnvironment(app, camera, bench.look);
    app.start();
    return bench;
  }

  get setIds(): readonly string[] { return this.manifest.sets.map((set) => set.setId); }

  resize(width: number, height: number): void {
    this.app.setCanvasResolution(pc.RESOLUTION_FIXED, width, height);
    this.app.graphicsDevice.setResolution(width, height);
  }

  clear(): void {
    for (const entity of this.surfaces) entity.destroy();
    for (const mesh of this.meshes) mesh.destroy();
    this.surfaces = [];
    this.meshes = [];
  }

  /** Replace the look (validated) and rebuild the environment and materials with it. */
  setLook(value: unknown): void {
    this.look = validateTileLook(value);
    this.environment?.dispose();
    this.environment = applyTileEnvironment(this.app, this.camera, this.look);
  }

  private async draw(surfaces: readonly TestSurface[], unlit?: pc.Material, library = this.library): Promise<void> {
    this.clear();
    const drawn = new Set<string>();
    for (const surface of surfaces) {
      let material: pc.Material;
      let uvOf: (s: number, t: number) => readonly [number, number];
      if (unlit !== undefined) {
        material = unlit;
        uvOf = () => [0, 0];
      } else {
        const resolved = await library.resolve(surface.setId);
        material = resolved.material;
        if (resolved.state === 'available') {
          drawn.add(surface.setId);
          const entry = resolved.set.entry;
          uvOf = (s, t) => surfaceUv(s, t, { ...UNIT_SCALE, textureSetId: surface.setId }, entry);
        } else {
          uvOf = (s, t) => [s / this.look.unavailable.tileMm, t / this.look.unavailable.tileMm];
        }
      }
      const mesh = buildSurfaceMesh(this.app.graphicsDevice, surface, uvOf);
      const entity = new pc.Entity(`bench:${surface.name}`);
      entity.addComponent('render', {
        meshInstances: [new pc.MeshInstance(mesh, material, entity)],
        castShadows: true,
        receiveShadows: true,
      });
      this.root.addChild(entity);
      this.surfaces.push(entity);
      this.meshes.push(mesh);
    }
    this.drawnSets = [...drawn].sort();
  }

  /** The test street, with `wall` on the facade. Horizontal sets are shown on the footway. */
  async showStreet(sets: Partial<TestStreetSets> = {}): Promise<void> {
    await this.draw(testStreet({
      wall: 'cc0.brick-running-bond',
      plinth: 'cc0.limestone-ashlar',
      door: 'cc0.storefront-metal',
      cornice: 'cc0.cast-concrete',
      footway: 'cc0.footway-paving',
      kerb: 'cc0.kerb-stone',
      carriageway: 'cc0.carriageway-asphalt',
      ...sets,
    }));
  }

  pose(pose: Pose, perspective = true): void {
    const component = this.camera.camera!;
    component.projection = perspective ? pc.PROJECTION_PERSPECTIVE : pc.PROJECTION_ORTHOGRAPHIC;
    this.camera.setPosition(...pose.position);
    this.camera.lookAt(...pose.target);
  }

  /** Standing on the footway, eye at 1.62 m, looking along and at the wall. */
  eyeLevel(name: 'wall' | 'kerb' | 'door' | 'cornice' | 'street' | 'footway'): Pose {
    const eye = KERB_HEIGHT_M + EYE_M;
    switch (name) {
      case 'wall': return { position: [-2.4, eye, 0.4], target: [0.6, 2.6, WALL_Z] };
      // From the carriageway: the junction at the kerb's foot is hidden from the footway above it.
      case 'kerb': return { position: [-2.0, EYE_M, -4.0], target: [0.4, 0.07, KERB_FACE_Z] };
      case 'door': return { position: [-0.6, eye, 0.8], target: [(DOOR.x0 + DOOR.x1) / 2, 1.2, WALL_Z + DOOR.depth] };
      case 'cornice': return { position: [-2.4, eye, 0.6], target: [0.6, CORNICE.y0, WALL_Z] };
      case 'street': return { position: [-14, eye, 1.0], target: [6, 2.2, 1.6] };
      case 'footway': return { position: [-1.5, eye, 0.6], target: [2.5, 0.15, 1.8] };
    }
  }

  /** The environment's camera frame; the bench canvas always has a size, so it exists. */
  private cameraFrame(): pc.CameraFrame {
    const frame = this.environment?.frame ?? null;
    if (frame === null) throw new Error('The bench has no camera frame: its canvas has no size');
    return frame;
  }

  pump(frames = 3): void {
    for (let i = 0; i < frames; i += 1) {
      this.app.update(1 / 60);
      this.app.render();
    }
  }

  get gl(): WebGL2RenderingContext {
    return (this.app.graphicsDevice as pc.WebglGraphicsDevice).gl as WebGL2RenderingContext;
  }

  /** The backbuffer, row 0 at the top. */
  pixels(): { readonly width: number; readonly height: number; readonly data: Uint8Array } {
    const gl = this.gl;
    const width = gl.drawingBufferWidth;
    const height = gl.drawingBufferHeight;
    const raw = new Uint8Array(width * height * 4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, raw);
    const data = new Uint8Array(raw.length);
    for (let row = 0; row < height; row += 1) {
      data.set(raw.subarray((height - 1 - row) * width * 4, (height - row) * width * 4), row * width * 4);
    }
    return { width, height, data };
  }

  private screen(world: readonly [number, number, number]): readonly [number, number] {
    const out = new pc.Vec3();
    this.camera.camera!.worldToScreen(new pc.Vec3(...world), out);
    // worldToScreen answers in CSS pixels of the canvas; the backbuffer may be larger.
    const scale = this.gl.drawingBufferWidth / this.canvas.clientWidth;
    return [out.x * scale, out.y * scale];
  }

  private regionMean(frame: ReturnType<Bench['pixels']>, region: Region): number {
    const [cx, cy] = this.screen(region.world);
    const half = region.half;
    let total = 0; let count = 0;
    for (let y = Math.round(cy - half); y <= Math.round(cy + half); y += 1) {
      for (let x = Math.round(cx - half); x <= Math.round(cx + half); x += 1) {
        if (x < 0 || y < 0 || x >= frame.width || y >= frame.height) continue;
        const at = (y * frame.width + x) * 4;
        total += luminance(frame.data[at]!, frame.data[at + 1]!, frame.data[at + 2]!);
        count += 1;
      }
    }
    if (count === 0) throw new Error(`${region.name} is off screen`);
    return total / count;
  }

  /**
   * The normal map's sign, from rendered pixels. The wall is one texture repeat filling an
   * orthographic view texel for texel; the sun is swung above and below (then right and left), and
   * the brightness difference is correlated with the height map's own slope. A positive
   * correlation means surfaces the relief tilts toward the light are the ones that brighten.
   */
  async measureNormalSign(setId: string): Promise<{ readonly setId: string; readonly vertical: number; readonly horizontal: number }> {
    const entry = this.manifest.byId.get(setId)!;
    const width = entry.width; const height = entry.height;
    this.resize(width, height);
    await this.draw([calibrationWall(setId, entry.extentUMm, entry.extentVMm)]);
    const component = this.camera.camera!;
    component.projection = pc.PROJECTION_ORTHOGRAPHIC;
    component.orthoHeight = entry.extentVMm / 2000;
    component.aspectRatioMode = pc.ASPECT_MANUAL;
    component.aspectRatio = entry.extentUMm / entry.extentVMm;
    const cx = entry.extentUMm / 2000; const cy = entry.extentVMm / 2000;
    this.camera.setPosition(cx, cy, -5);
    this.camera.lookAt(cx, cy, 0);
    const frame = this.cameraFrame();
    const ssao = frame.ssao.type;
    frame.ssao.type = pc.SSAOTYPE_NONE; frame.update();
    const sun = this.environment!.sun;
    const shine = (direction: readonly [number, number, number]): Float64Array => {
      const d = new pc.Vec3(...direction).normalize();
      sun.setRotation(new pc.Quat().setFromDirections(new pc.Vec3(0, -1, 0), d));
      this.pump(2);
      const { data } = this.pixels();
      const out = new Float64Array(width * height);
      for (let i = 0; i < out.length; i += 1) out[i] = luminance(data[i * 4]!, data[i * 4 + 1]!, data[i * 4 + 2]!);
      return out;
    };
    // Seen from -Z, the viewer's right is -X.
    const above = shine([0, -0.8, 0.6]); const below = shine([0, 0.8, 0.6]);
    const right = shine([0.8, 0, 0.6]); const left = shine([-0.8, 0, 0.6]);
    const bytes = new Uint8Array(await (await fetch(`${__TEXTURE_ROOT__}/${textureSetBlobPath(entry)}`)).arrayBuffer());
    const { decodeTextureSet } = await import('@exulanica/atlas-core');
    const relief = (await decodeTextureSet(bytes, entry)).maps.height;
    if (relief === undefined) throw new Error(`${entry.setId} ships no height map to measure the normal's sign against`);
    const h = (row: number, column: number): number =>
      relief[(((row % height) + height) % height) * width + (((column % width) + width) % width)]!;
    const n = (height - 4) * (width - 4);
    const dv = new Float64Array(n); const gv = new Float64Array(n);
    const du = new Float64Array(n); const gu = new Float64Array(n);
    let k = 0;
    for (let row = 2; row < height - 2; row += 1) {
      for (let column = 2; column < width - 2; column += 1) {
        const at = row * width + column;
        dv[k] = above[at]! - below[at]!;
        gv[k] = h(row + 1, column) - h(row - 1, column);
        du[k] = right[at]! - left[at]!;
        gu[k] = -(h(row, column + 1) - h(row, column - 1));
        k += 1;
      }
    }
    frame.ssao.type = ssao; frame.update();
    this.environment!.dispose();
    this.environment = applyTileEnvironment(this.app, this.camera, this.look);
    component.aspectRatioMode = pc.ASPECT_AUTO;
    component.projection = pc.PROJECTION_PERSPECTIVE;
    this.resize(1440, 900);
    return { setId, vertical: pearson(dv, gv), horizontal: pearson(du, gu) };
  }

  /**
   * Fog onset from pixels: one unlit target at each distance straight ahead, drawn with the look's
   * fog and with fog off. Onset is the nearest distance at which the two frames differ.
   */
  async measureFog(distances: readonly number[]): Promise<{ readonly distance: number; readonly difference: number }[]> {
    const unlit = new pc.StandardMaterial();
    unlit.useLighting = false; unlit.useSkybox = false;
    unlit.diffuse = new pc.Color(0, 0, 0); unlit.emissive = new pc.Color(0.05, 0.05, 0.05);
    unlit.update();
    const scene = this.app.scene;
    const results: { distance: number; difference: number }[] = [];
    const frame = this.cameraFrame();
    const ssao = frame.ssao.type;
    frame.ssao.type = pc.SSAOTYPE_NONE; frame.update();
    this.pose({ position: [0, EYE_M, 0], target: [0, EYE_M, 10] });
    for (const distance of distances) {
      const size = distance * 0.2;
      const target: TestSurface = {
        name: 'fog-target', setId: 'fog-target',
        positions: [size, EYE_M - size, distance, -size, EYE_M - size, distance, -size, EYE_M + size, distance, size, EYE_M + size, distance],
        normals: [0, 0, -1, 0, 0, -1, 0, 0, -1, 0, 0, -1],
        surfaceMm: [0, 0, 1, 0, 1, 1, 0, 1],
        indices: [0, 1, 2, 0, 2, 3],
      };
      await this.draw([target], unlit);
      const centre = { name: `fog-${distance}`, world: [0, EYE_M, distance] as const, half: 3 };
      scene.fog.type = pc.FOG_LINEAR;
      this.pump(2);
      const fogged = this.regionMean(this.pixels(), centre);
      scene.fog.type = pc.FOG_NONE;
      this.pump(2);
      const clear = this.regionMean(this.pixels(), centre);
      scene.fog.type = pc.FOG_LINEAR;
      results.push({ distance, difference: Math.round((fogged - clear) * 1000) / 1000 });
    }
    frame.ssao.type = ssao; frame.update();
    unlit.destroy();
    return results;
  }

  /** Contact shadowing: luminance at each junction with the occlusion on, over the same with it off. */
  contactProbes(): readonly { readonly pose: Pose; readonly regions: readonly Region[] }[] {
    const k = KERB_HEIGHT_M;
    return [
      { pose: this.eyeLevel('kerb'), regions: [
        { name: 'kerb: carriageway 30 mm from the kerb face', world: [0.4, 0, KERB_FACE_Z - 0.03], half: 2 },
        { name: 'kerb control: carriageway 1.5 m out', world: [0.4, 0, KERB_FACE_Z - 1.5], half: 2 },
      ] },
      { pose: this.eyeLevel('door'), regions: [
        // The far reveal: from this side of the opening, the near one is behind the wall's edge.
        { name: 'doorway: door 40 mm from the reveal', world: [DOOR.x1 - 0.04, k + 1.2, WALL_Z + DOOR.depth], half: 2 },
        { name: 'doorway: threshold 40 mm from the door', world: [(DOOR.x0 + DOOR.x1) / 2, k, WALL_Z + DOOR.depth - 0.04], half: 2 },
        { name: 'doorway control: plinth 1.5 m from the reveal', world: [DOOR.x0 - 1.5, k + 0.5, WALL_Z], half: 2 },
      ] },
      { pose: this.eyeLevel('cornice'), regions: [
        { name: 'cornice: wall 60 mm under the soffit', world: [0.6, CORNICE.y0 - 0.06, WALL_Z], half: 2 },
        { name: 'cornice control: wall 2.5 m under the soffit', world: [0.6, CORNICE.y0 - 2.5, WALL_Z], half: 2 },
      ] },
    ];
  }

  /** Pose for one probe and pin a marker over each sampled point, to check by eye what is sampled. */
  markContactProbe(index: number): readonly (readonly [number, number])[] {
    const probe = this.contactProbes()[index]!;
    this.pose(probe.pose);
    this.pump(3);
    document.querySelectorAll('.bench-mark').forEach((old) => old.remove());
    const scale = this.canvas.clientWidth / this.gl.drawingBufferWidth;
    return probe.regions.map((region) => {
      const [x, y] = this.screen(region.world);
      const mark = document.createElement("div");
      mark.className = "bench-mark";
      mark.title = region.name;
      mark.style.cssText = `position:absolute;left:${x * scale - 4}px;top:${y * scale - 4}px;width:8px;height:8px;border:2px solid #0f0;pointer-events:none`;
      document.body.append(mark);
      return [Math.round(x), Math.round(y)] as const;
    });
  }

  async measureContactShadow(): Promise<Record<string, { readonly on: number; readonly off: number; readonly ratio: number }>> {
    await this.showStreet();
    const frame = this.cameraFrame();
    const mode = frame.ssao.type;
    const probes = this.contactProbes();
    const out: Record<string, { on: number; off: number; ratio: number }> = {};
    for (const probe of probes) {
      this.pose(probe.pose);
      frame.ssao.type = mode; frame.update();
      this.pump(3);
      const on = this.pixels();
      frame.ssao.type = pc.SSAOTYPE_NONE; frame.update();
      this.pump(3);
      const off = this.pixels();
      for (const region of probe.regions) {
        const a = this.regionMean(on, region); const b = this.regionMean(off, region);
        out[region.name] = { on: Math.round(a * 10) / 10, off: Math.round(b * 10) / 10, ratio: Math.round((a / b) * 1000) / 1000 };
      }
    }
    frame.ssao.type = mode; frame.update();
    return out;
  }

  /** The probe: the metal door and the sky with the environment atlas, and without it. */
  async measureProbe(): Promise<Record<string, unknown>> {
    await this.showStreet();
    const scene = this.app.scene;
    this.pose(this.eyeLevel('door'));
    const door: Region = { name: 'door', world: [(DOOR.x0 + DOOR.x1) / 2, KERB_HEIGHT_M + 1.2, WALL_Z + DOOR.depth], half: 6 };
    const wall: Region = { name: 'wall', world: [DOOR.x1 + 0.6, 2.2, WALL_Z], half: 6 };
    this.pump(3);
    const withProbe = this.pixels();
    const atlas = scene.envAtlas; const skybox = scene.skybox;
    scene.envAtlas = null; scene.skybox = null;
    this.pump(3);
    const without = this.pixels();
    scene.envAtlas = atlas; scene.skybox = skybox;
    this.pump(1);
    const top = (frame: ReturnType<Bench['pixels']>): readonly number[] => {
      const at = (4 * frame.width + Math.floor(frame.width / 2)) * 4;
      return [frame.data[at]!, frame.data[at + 1]!, frame.data[at + 2]!];
    };
    return {
      doorWithProbe: this.regionMean(withProbe, door),
      doorWithout: this.regionMean(without, door),
      wallWithProbe: this.regionMean(withProbe, wall),
      wallWithout: this.regionMean(without, wall),
      skyTopWithProbe: top(withProbe),
      skyTopWithout: top(without),
    };
  }

  /**
   * Whether the height map earns its place: the same eye-level frames with parallax off and on, at
   * the physical factor (relief over extent) and at a multiple of it, compared pixel by pixel, with
   * the frame time of each.
   */
  async measureParallax(multiples: readonly number[]): Promise<Record<string, unknown>> {
    const results: Record<string, unknown> = {};
    const poses = ['wall', 'footway', 'door'] as const;
    const frames = async (library: TileTextureLibrary): Promise<{ readonly frames: Uint8Array[]; readonly times: unknown }> => {
      const out: Uint8Array[] = [];
      await this.draw(testStreet({
        wall: 'cc0.brick-running-bond', plinth: 'cc0.limestone-ashlar', door: 'cc0.storefront-metal',
        cornice: 'cc0.cast-concrete', footway: 'cc0.footway-paving', kerb: 'cc0.kerb-stone',
        carriageway: 'cc0.carriageway-asphalt',
      }), undefined, library);
      for (const pose of poses) {
        this.pose(this.eyeLevel(pose));
        this.pump(3);
        out.push(this.pixels().data);
      }
      this.pose(this.eyeLevel('wall'));
      return { frames: out, times: this.frameTimes(120) };
    };
    const baseline = await frames(this.library);
    results['off'] = baseline.times;
    for (const multiple of multiples) {
      const brick = this.manifest.byId.get('cc0.brick-running-bond')!;
      // Brick's relief is 12 mm over an 1800 mm tile.
      const factor = Math.min(1, (12 / brick.extentVMm) * multiple);
      const look = validateTileLook({ ...structuredClone(this.look), surface: { ...this.look.surface, parallax: true, parallaxFactor: factor } });
      const library = new TileTextureLibrary(this.app.graphicsDevice, look, this.manifest, async (entry) =>
        new Uint8Array(await (await fetch(`${__TEXTURE_ROOT__}/${textureSetBlobPath(entry)}`)).arrayBuffer()));
      const run = await frames(library);
      const differences = poses.map((pose, index) => {
        const a = baseline.frames[index]!; const b = run.frames[index]!;
        let sum = 0; let changed = 0; let max = 0;
        for (let i = 0; i < a.length; i += 4) {
          const d = Math.abs(luminance(a[i]!, a[i + 1]!, a[i + 2]!) - luminance(b[i]!, b[i + 1]!, b[i + 2]!));
          sum += d; max = Math.max(max, d); if (d >= 8) changed += 1;
        }
        const pixels = a.length / 4;
        return { pose, meanAbsLuminance: Math.round((sum / pixels) * 100) / 100, pixelsChangedBy8OrMore: Math.round((changed / pixels) * 10000) / 10000, max: Math.round(max) };
      });
      results[`x${multiple} factor ${factor.toFixed(5)}`] = { differences, times: run.times, extraBytes: library.decodedTextureBytes - this.library.decodedTextureBytes };
      this.clear();
      library.destroy();
    }
    await this.showStreet();
    return results;
  }

  /** The test-only leaf field as a cutout material, bound by the runtime's own class binding. */
  private async cutoutMaterial(discs?: number, setId?: string): Promise<{ readonly material: pc.StandardMaterial; readonly set: DecodedTextureSet }> {
    // A published set id measures the class on what the texture lane shipped; otherwise the test-only field.
    if (setId !== undefined) {
      const published = await this.library.resolve(setId);
      if (published.state !== 'available') throw new Error(`${setId} does not draw: ${published.reason}`);
      return { material: published.material, set: published.set };
    }
    const set = testCutoutSet(512, 2000, discs);
    const resolution = this.library.adopt({ state: 'decoded', setId: set.entry.setId, set, transferredBytes: 0 });
    if (resolution.state !== 'available') throw new Error(`the test cutout does not draw: ${resolution.reason}`);
    return { material: resolution.material, set };
  }

  /** For comparison only: the same material with the device's own averaged mip chain. */
  private plainMipMaterial(material: pc.StandardMaterial, set: DecodedTextureSet): { readonly material: pc.StandardMaterial; readonly texture: pc.Texture } {
    const texture = new pc.Texture(this.app.graphicsDevice, {
      name: 'bench:plain-mip-cutout', width: set.entry.width, height: set.entry.height, format: pc.PIXELFORMAT_SRGBA8,
      mipmaps: true, anisotropy: this.look.surface.anisotropy, addressU: pc.ADDRESS_REPEAT, addressV: pc.ADDRESS_REPEAT,
      minFilter: pc.FILTER_LINEAR_MIPMAP_LINEAR, magFilter: pc.FILTER_LINEAR, levels: [set.maps.base_color_coverage!],
    });
    const plain = material.clone() as pc.StandardMaterial;
    plain.diffuseMap = texture;
    plain.opacityMap = texture;
    plain.update();
    return { material: plain, texture };
  }

  /** A square of the test field, `size` metres, facing -Z (vertical) or +Y (horizontal), one repeat per extent. */
  private cutoutPlane(material: pc.Material, centre: readonly [number, number, number], size: number, facing: 'front' | 'up', extentMm: number, castShadows = true): pc.Entity {
    const h = size / 2;
    const [x, y, z] = centre;
    const corners = facing === 'front'
      ? [[x - h, y + h, z], [x + h, y + h, z], [x + h, y - h, z], [x - h, y - h, z]]
      : [[x - h, y, z - h], [x + h, y, z - h], [x + h, y, z + h], [x - h, y, z + h]];
    const normal = facing === 'front' ? [0, 0, -1] : [0, 1, 0];
    const mm = size * 1000;
    const mesh = buildSurfaceMesh(this.app.graphicsDevice, {
      positions: corners.flat(), normals: [...normal, ...normal, ...normal, ...normal],
      // Counter-clockwise seen from the side the normal points to, so the geometric front is that side.
      surfaceMm: [0, 0, mm, 0, mm, mm, 0, mm], indices: facing === 'front' ? [0, 1, 2, 0, 2, 3] : [0, 2, 1, 0, 3, 2],
    }, (s, t) => [s / extentMm, t / extentMm]);
    const entity = new pc.Entity('bench:cutout-plane');
    entity.addComponent('render', { meshInstances: [new pc.MeshInstance(mesh, material, entity)], castShadows, receiveShadows: true });
    this.root.addChild(entity);
    this.surfaces.push(entity);
    this.meshes.push(mesh);
    return entity;
  }

  private unlitMask(): pc.StandardMaterial {
    const mask = new pc.StandardMaterial();
    mask.useLighting = false; mask.useSkybox = false; mask.diffuse = new pc.Color(0, 0, 0); mask.emissive = new pc.Color(1, 0, 1);
    mask.cull = pc.CULLFACE_NONE; mask.update();
    return mask;
  }

  private static differs(a: Uint8Array, b: Uint8Array, at: number): boolean {
    return Math.abs(a[at]! - b[at]!) + Math.abs(a[at + 1]! - b[at + 1]!) + Math.abs(a[at + 2]! - b[at + 2]!) > 30;
  }

  /**
   * Cutout acceptance: silhouette coverage of a 4 m square of the test field seen face on at each
   * distance, as the share of its footprint's pixels the leaves cover. The footprint is the same square
   * drawn as an opaque mask; a pixel is covered where the cutout frame differs from the empty frame.
   * Measured with the runtime's coverage-keeping levels and, for comparison, with plain averaged levels.
   */
  async measureCutoutCoverage(distances: readonly number[], discs?: number, setId?: string): Promise<Record<string, unknown>> {
    this.clear();
    const { material, set } = await this.cutoutMaterial(discs, setId);
    const plain = this.plainMipMaterial(material, set);
    const mask = this.unlitMask();
    const centre = [0, 40, 0] as const;
    const plane = this.cutoutPlane(material, centre, 4, 'front', set.entry.extentUMm);
    const render = plane.render!;
    const out: Record<string, unknown> = { coveragePermille: (set.classParameters as { coveragePermille: number }).coveragePermille };
    for (const [label, drawn] of [['kept', material], ['plain', plain.material]] as const) {
      const rows: Record<string, unknown>[] = [];
      for (const distance of distances) {
        this.pose({ position: [0, 40, -distance], target: centre });
        plane.enabled = false; this.pump(4);
        const empty = this.pixels();
        plane.enabled = true; render.meshInstances[0]!.material = mask; this.pump(4);
        const footprintFrame = this.pixels();
        render.meshInstances[0]!.material = drawn; this.pump(4);
        const drawnFrame = this.pixels();
        let footprint = 0; let covered = 0;
        for (let at = 0; at < empty.data.length; at += 4) {
          if (!Bench.differs(footprintFrame.data, empty.data, at)) continue;
          footprint += 1;
          if (Bench.differs(drawnFrame.data, empty.data, at)) covered += 1;
        }
        rows.push({ distance, footprintPixels: footprint, coveredPixels: covered, coverage: Math.round((covered / footprint) * 10000) / 10000 });
      }
      out[label] = rows;
    }
    this.clear();
    mask.destroy(); plain.material.destroy(); plain.texture.destroy();
    return out;
  }

  /**
   * The shadow pass applies the same test: a horizontal 4 m square of the test field 2.5 m above lit
   * ground, the sun straight down, the ground under it seen obliquely from beside it. The share of
   * ground samples shadowed (closer to the opaque square's shadow than to open light), for the cutout
   * and for the same square drawn opaque.
   */
  async measureCutoutShadow(setId?: string): Promise<Record<string, unknown>> {
    this.clear();
    const { material, set } = await this.cutoutMaterial(undefined, setId);
    const ground = await this.library.resolve('cc0.footway-paving');
    const sun = this.environment!.sun;
    const rotation = sun.getRotation().clone();
    sun.setRotation(new pc.Quat().setFromEulerAngles(0, 0, 0));
    const opaque = material.clone() as pc.StandardMaterial;
    opaque.opacityMap = null; opaque.alphaTest = 0; opaque.update();
    const groundPlane = this.cutoutPlane(ground.material, [0, 0, 0], 16, 'up', 1800);
    groundPlane.name = 'bench:ground';
    const canopy = this.cutoutPlane(material, [0, 2.5, 0], 4, 'up', set.entry.extentUMm);
    this.pose({ position: [0, 1.3, -7], target: [0, 0, 0] });
    const samples: (readonly [number, number])[] = [];
    for (let i = 0; i < 40; i += 1) {
      for (let j = 0; j < 40; j += 1) {
        const [sx, sy] = this.screen([-1.6 + (3.2 * (i + 0.5)) / 40, 0.001, -1.6 + (3.2 * (j + 0.5)) / 40]);
        samples.push([Math.round(sx), Math.round(sy)]);
      }
    }
    const luma = (frame: ReturnType<Bench['pixels']>): number[] => samples.map(([x, y]) => {
      const at = (y * frame.width + x) * 4;
      return luminance(frame.data[at]!, frame.data[at + 1]!, frame.data[at + 2]!);
    });
    const render = canopy.render!;
    canopy.enabled = false; this.pump(6);
    const lit = luma(this.pixels());
    canopy.enabled = true; render.meshInstances[0]!.material = opaque; this.pump(6);
    const dark = luma(this.pixels());
    render.meshInstances[0]!.material = material; this.pump(6);
    const holed = luma(this.pixels());
    const share = (values: number[]): number => {
      let shadowed = 0;
      values.forEach((value, index) => { if (lit[index]! - value > (lit[index]! - dark[index]!) / 2) shadowed += 1; });
      return Math.round((shadowed / values.length) * 1000) / 1000;
    };
    const result = {
      coveragePermille: (set.classParameters as { coveragePermille: number }).coveragePermille,
      litMean: Math.round(lit.reduce((a, b) => a + b, 0) / lit.length),
      opaqueShadowMean: Math.round(dark.reduce((a, b) => a + b, 0) / dark.length),
      cutoutShadowedShare: share(holed),
      opaqueShadowedShare: share(dark),
    };
    sun.setRotation(rotation);
    this.clear();
    opaque.destroy();
    return result;
  }

  /**
   * Both faces are lit: the test field square seen from its back with the sun behind the viewer, so
   * light reaches the back face. Mean luminance of the covered pixels with two-sided lighting (the
   * binding) and, for comparison, without it, and of the front face with the sun on the far side.
   */
  async measureCutoutBackFace(setId?: string): Promise<Record<string, unknown>> {
    this.clear();
    const { material, set } = await this.cutoutMaterial(undefined, setId);
    const oneSided = material.clone() as pc.StandardMaterial;
    oneSided.twoSidedLighting = false; oneSided.update();
    const sun = this.environment!.sun;
    const rotation = sun.getRotation().clone();
    // Light travelling toward -Z and down: it reaches the +Z (back) face of a square facing -Z.
    sun.setRotation(new pc.Quat().setFromDirections(new pc.Vec3(0, -1, 0), new pc.Vec3(0, -0.5, -1).normalize()));
    const centre = [0, 40, 0] as const;
    const plane = this.cutoutPlane(material, centre, 4, 'front', set.entry.extentUMm);
    const render = plane.render!;
    const coveredMean = (position: readonly [number, number, number], drawn: pc.Material): number => {
      this.pose({ position, target: centre });
      plane.enabled = false; this.pump(4);
      const empty = this.pixels();
      plane.enabled = true; render.meshInstances[0]!.material = drawn; this.pump(4);
      const frame = this.pixels();
      let sum = 0; let count = 0;
      for (let at = 0; at < frame.data.length; at += 4) {
        if (!Bench.differs(frame.data, empty.data, at)) continue;
        sum += luminance(frame.data[at]!, frame.data[at + 1]!, frame.data[at + 2]!); count += 1;
      }
      return count === 0 ? -1 : Math.round((sum / count) * 10) / 10;
    };
    const result = {
      backLitTwoSided: coveredMean([0, 40, 6], material),
      backLitOneSided: coveredMean([0, 40, 6], oneSided),
      frontUnlitTwoSided: coveredMean([0, 40, -6], material),
    };
    sun.setRotation(rotation);
    this.clear();
    oneSided.destroy();
    return result;
  }

  /** The test-only clean glazing set as a material, bound by the runtime's class binding, with the scene colour copy on. */
  private async glazingMaterial(filmShare = 0, setId?: string): Promise<{ readonly material: pc.StandardMaterial; readonly set: DecodedTextureSet }> {
    // A published set id measures the class on what the texture lane shipped; otherwise the test-only glass.
    if (setId !== undefined) {
      const published = await this.library.resolve(setId);
      if (published.state !== 'available') throw new Error(`${setId} does not draw: ${published.reason}`);
      this.environment!.requestSceneColor();
      return { material: published.material, set: published.set };
    }
    const set = testGlazingSet(512, 2000, filmShare);
    const resolution = this.library.adopt({ state: 'decoded', setId: set.entry.setId, set, transferredBytes: 0 });
    if (resolution.state !== 'available') throw new Error(`the test glazing does not draw: ${resolution.reason}`);
    this.environment!.requestSceneColor();
    return { material: resolution.material, set };
  }

  /**
   * The test-only backing: a lit checker of 200 mm squares, its diffuse scaled by `level` (1 is the checker
   * in open light, as bright as the street; a shop interior is far dimmer), or matte black to see reflection alone.
   */
  private backingMaterials(level = 1): { readonly checker: pc.StandardMaterial; readonly black: pc.StandardMaterial; destroy(): void } {
    const texture = new pc.Texture(this.app.graphicsDevice, {
      name: 'bench:backing-checker', width: 256, height: 256, format: pc.PIXELFORMAT_SRGBA8, mipmaps: true,
      addressU: pc.ADDRESS_REPEAT, addressV: pc.ADDRESS_REPEAT, levels: [backingTexels(256, 4)],
    });
    const checker = new pc.StandardMaterial();
    checker.diffuseMap = texture; checker.diffuse = new pc.Color(level, level, level); checker.useMetalness = true; checker.metalness = 0; checker.gloss = 0.2; checker.cull = pc.CULLFACE_NONE; checker.update();
    const black = new pc.StandardMaterial();
    black.useLighting = false; black.useSkybox = false; black.diffuse = new pc.Color(0, 0, 0); black.emissive = new pc.Color(0, 0, 0); black.cull = pc.CULLFACE_NONE; black.update();
    return { checker, black, destroy() { checker.destroy(); black.destroy(); texture.destroy(); } };
  }

  /**
   * Glazing acceptance. A 2 m pane of test clean glass faces -Z at (0, 40, 0), with a test-only backing
   * square 20 m wide standing TEST_BACKING_DEPTH_M behind it. For each view: the pane's footprint (the
   * pane drawn as an opaque mask); frames with the backing seen through the pane (A), the backing
   * alone (C), and the pane over a matte black backing (R, reflection alone).
   * Reads through: correlation of luminance of A with C inside the footprint, and the contrast kept,
   * face on at each distance. Reflection by angle: the share of A's luminance that R, the reflection
   * alone, accounts for, at 4 m and each angle from the pane's normal.
   */
  async measureGlazing(distances: readonly number[], angles: readonly number[], backingLevel = 1, setId?: string): Promise<Record<string, unknown>> {
    this.clear();
    const { material, set } = await this.glazingMaterial(0, setId);
    const backing = this.backingMaterials(backingLevel);
    const mask = this.unlitMask();
    const centre = [0, 40, 0] as const;
    const pane = this.cutoutPlane(material, centre, 2, 'front', set.entry.extentUMm, castsShadow(set));
    const behind = this.cutoutPlane(backing.checker, [0, 40, TEST_BACKING_DEPTH_M], 20, 'front', 2000);
    const paneRender = pane.render!;
    const behindRender = behind.render!;
    const view = (position: readonly [number, number, number]) => {
      this.pose({ position, target: centre });
      pane.enabled = true; behind.enabled = false; paneRender.meshInstances[0]!.material = mask; this.pump(4);
      const masked = this.pixels();
      pane.enabled = false; this.pump(4);
      const empty = this.pixels();
      behind.enabled = true; behindRender.meshInstances[0]!.material = backing.checker; this.pump(4);
      const backingOnly = this.pixels();
      pane.enabled = true; paneRender.meshInstances[0]!.material = material; this.pump(4);
      const through = this.pixels();
      behindRender.meshInstances[0]!.material = backing.black; this.pump(4);
      const reflection = this.pixels();
      const footprint: number[] = [];
      for (let at = 0; at < empty.data.length; at += 4) if (Bench.differs(masked.data, empty.data, at)) footprint.push(at);
      const lum = (frame: ReturnType<Bench['pixels']>): Float64Array =>
        Float64Array.from(footprint, (at) => luminance(frame.data[at]!, frame.data[at + 1]!, frame.data[at + 2]!));
      return { footprint: footprint.length, through: lum(through), backingOnly: lum(backingOnly), reflection: lum(reflection) };
    };
    const mean = (values: Float64Array): number => values.reduce((a, b) => a + b, 0) / Math.max(1, values.length);
    const deviation = (values: Float64Array): number => {
      const m = mean(values);
      return Math.sqrt(values.reduce((a, b) => a + (b - m) ** 2, 0) / Math.max(1, values.length));
    };
    const round = (value: number, places = 3): number => Math.round(value * 10 ** places) / 10 ** places;
    const readsThrough = distances.map((distance) => {
      const frames = view([0, 40, -distance]);
      return {
        distance, footprintPixels: frames.footprint,
        correlation: round(pearson(frames.through, frames.backingOnly)),
        contrastKept: round(deviation(frames.through) / deviation(frames.backingOnly)),
        meanThrough: round(mean(frames.through), 1), meanBacking: round(mean(frames.backingOnly), 1), meanReflection: round(mean(frames.reflection), 1),
      };
    });
    const byAngle = angles.map((angle) => {
      const radians = (angle * Math.PI) / 180;
      const frames = view([Math.sin(radians) * 4, 40, -Math.cos(radians) * 4]);
      return {
        angle, footprintPixels: frames.footprint,
        reflectionShare: round(mean(frames.reflection) / mean(frames.through)),
        meanThrough: round(mean(frames.through), 1), meanReflection: round(mean(frames.reflection), 1), meanBacking: round(mean(frames.backingOnly), 1),
        correlationWithBacking: round(pearson(frames.through, frames.backingOnly)),
      };
    });
    this.clear();
    mask.destroy(); backing.destroy();
    return { backingDepthM: TEST_BACKING_DEPTH_M, backingLevel, readsThrough, byAngle };
  }

  /**
   * Glazing casts no shadow: the same scene as measureCutoutShadow with a pane of test glass, which casts
   * shadows exactly as the tile runtime decides for its class (castsShadow).
   */
  async measureGlazingShadow(setId?: string): Promise<Record<string, unknown>> {
    this.clear();
    const { material, set } = await this.glazingMaterial(0, setId);
    const ground = await this.library.resolve('cc0.footway-paving');
    const sun = this.environment!.sun;
    const rotation = sun.getRotation().clone();
    sun.setRotation(new pc.Quat().setFromEulerAngles(0, 0, 0));
    this.cutoutPlane(ground.material, [0, 0, 0], 16, 'up', 1800);
    const pane = this.cutoutPlane(material, [0, 2.5, 0], 4, 'up', set.entry.extentUMm, castsShadow(set));
    this.pose({ position: [0, 1.3, -7], target: [0, 0, 0] });
    const samples: (readonly [number, number])[] = [];
    for (let i = 0; i < 40; i += 1) {
      for (let j = 0; j < 40; j += 1) {
        const [sx, sy] = this.screen([-1.6 + (3.2 * (i + 0.5)) / 40, 0.001, -1.6 + (3.2 * (j + 0.5)) / 40]);
        samples.push([Math.round(sx), Math.round(sy)]);
      }
    }
    const luma = (frame: ReturnType<Bench['pixels']>): number[] => samples.map(([x, y]) => {
      const at = (y * frame.width + x) * 4;
      return luminance(frame.data[at]!, frame.data[at + 1]!, frame.data[at + 2]!);
    });
    pane.enabled = false; this.pump(6);
    const open = luma(this.pixels());
    pane.enabled = true; this.pump(6);
    const under = luma(this.pixels());
    const meanOpen = open.reduce((a, b) => a + b, 0) / open.length;
    const meanUnder = under.reduce((a, b) => a + b, 0) / under.length;
    sun.setRotation(rotation);
    this.clear();
    return { openMean: Math.round(meanOpen * 10) / 10, underPaneMean: Math.round(meanUnder * 10) / 10, darkenedBy: Math.round(((meanOpen - meanUnder) / meanOpen) * 1000) / 1000 };
  }

  /** A horizontal rectangle at height `y`, s along +X and t along -Z (left of s), one repeat per extent. */
  private groundRect(material: pc.Material, x0: number, x1: number, z0: number, z1: number, y: number, extentUMm: number, extentVMm: number, castShadows: boolean, bucket: number | null = null): pc.Entity {
    const mesh = buildSurfaceMesh(this.app.graphicsDevice, {
      positions: [x0, y, z1, x1, y, z1, x1, y, z0, x0, y, z0], normals: [0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0],
      surfaceMm: [0, 0, (x1 - x0) * 1000, 0, (x1 - x0) * 1000, (z1 - z0) * 1000, 0, (z1 - z0) * 1000],
      // Counter-clockwise seen from +Y.
      indices: [0, 1, 2, 0, 2, 3],
    }, (s, t) => [s / extentUMm, t / extentVMm]);
    const entity = new pc.Entity('bench:ground-rect');
    const instance = new pc.MeshInstance(mesh, material, entity);
    if (bucket !== null) instance.drawBucket = bucket;
    entity.addComponent('render', { meshInstances: [instance], castShadows, receiveShadows: true });
    this.root.addChild(entity);
    this.surfaces.push(entity);
    this.meshes.push(mesh);
    return entity;
  }

  /**
   * Decal acceptance: a test-only worn lane line lying on asphalt in the same plane, 250 mm wide and 75 m
   * long, walked for 30 m at eye level beside it. At each step, the line's pixels are where a reference
   * frame (the decal drawn with no depth test, so nothing can hide it) differs from the road alone; the
   * share of them where the decal as bound, and the same decal with no depth bias, match the reference.
   */
  async measureDecalWalk(steps: number, walkM: number): Promise<Record<string, unknown>> {
    this.clear();
    const set = testDecalSet();
    const resolution = this.library.adopt({ state: 'decoded', setId: set.entry.setId, set, transferredBytes: 0 });
    if (resolution.state !== 'available') throw new Error(`the test decal does not draw: ${resolution.reason}`);
    const decal = resolution.material;
    const unbiased = decal.clone() as pc.StandardMaterial;
    unbiased.depthBias = 0; unbiased.slopeDepthBias = 0; unbiased.update();
    const reference = decal.clone() as pc.StandardMaterial;
    reference.depthTest = false; reference.update();
    const road = await this.library.resolve('cc0.carriageway-asphalt');
    this.groundRect(road.material, -5, 70, -4, 4, 0, 2000, 2000, true);
    const line = this.groundRect(decal, -5, 70, -0.125, 0.125, 0, set.entry.extentUMm, set.entry.extentVMm, castsShadow(set), drawBucket(set));
    const render = line.render!;
    const eye = 1.62;
    const rows: { x: number; linePixels: number; bound: number; unbiased: number }[] = [];
    for (let step = 0; step <= steps; step += 1) {
      const x = (walkM * step) / steps;
      this.pose({ position: [x, eye, 1.2], target: [x + 12, 0, 0] });
      line.enabled = false; this.pump(2);
      const none = this.pixels();
      line.enabled = true; render.meshInstances[0]!.material = reference; this.pump(2);
      const ref = this.pixels();
      render.meshInstances[0]!.material = decal; this.pump(2);
      const bound = this.pixels();
      render.meshInstances[0]!.material = unbiased; this.pump(2);
      const plain = this.pixels();
      let pixels = 0; let boundOk = 0; let plainOk = 0;
      const close = (a: Uint8Array, b: Uint8Array, at: number): boolean =>
        Math.abs(a[at]! - b[at]!) + Math.abs(a[at + 1]! - b[at + 1]!) + Math.abs(a[at + 2]! - b[at + 2]!) <= 12;
      for (let at = 0; at < none.data.length; at += 4) {
        if (!Bench.differs(ref.data, none.data, at)) continue;
        pixels += 1;
        if (close(bound.data, ref.data, at)) boundOk += 1;
        if (close(plain.data, ref.data, at)) plainOk += 1;
      }
      rows.push({ x: Math.round(x * 100) / 100, linePixels: pixels, bound: Math.round((boundOk / pixels) * 10000) / 10000, unbiased: Math.round((plainOk / pixels) * 10000) / 10000 });
    }
    render.meshInstances[0]!.material = decal;
    this.clear();
    unbiased.destroy(); reference.destroy();
    const summary = (key: 'bound' | 'unbiased') => {
      const values = rows.map((row) => row[key]);
      return { min: Math.min(...values), mean: Math.round((values.reduce((a, b) => a + b, 0) / values.length) * 10000) / 10000, max: Math.max(...values), stepsBelow099: values.filter((value) => value < 0.99).length };
    };
    return { depthBias: decal.depthBias, slopeDepthBias: decal.slopeDepthBias, steps: rows.length, bound: summary('bound'), unbiased: summary('unbiased'), rows };
  }

  /** For screenshots: the test lane line on asphalt from eye level beside it, left drawn. */
  async showDecal(): Promise<void> {
    this.clear();
    const set = testDecalSet();
    const resolution = this.library.adopt({ state: 'decoded', setId: set.entry.setId, set, transferredBytes: 0 });
    if (resolution.state !== 'available') throw new Error(`the test decal does not draw: ${resolution.reason}`);
    const road = await this.library.resolve('cc0.carriageway-asphalt');
    this.groundRect(road.material, -5, 70, -4, 4, 0, 2000, 2000, true);
    this.groundRect(resolution.material, -5, 70, -0.125, 0.125, 0, set.entry.extentUMm, set.entry.extentVMm, castsShadow(set), drawBucket(set));
    this.pose({ position: [0, 1.62, 1.2], target: [12, 0, 0] });
    this.pump(6);
  }

  /** For screenshots: the pane and its test backing from 4 m at `angle` degrees off the pane's normal, left drawn. */
  async showGlazing(angle: number, filmShare = 0, setId?: string): Promise<void> {
    this.clear();
    const { material, set } = await this.glazingMaterial(filmShare, setId);
    const backing = this.backingMaterials();
    this.cutoutPlane(backing.checker, [0, 40, TEST_BACKING_DEPTH_M], 20, 'front', 2000);
    this.cutoutPlane(material, [0, 40, 0], 2, 'front', set.entry.extentUMm, castsShadow(set));
    const radians = (angle * Math.PI) / 180;
    this.pose({ position: [Math.sin(radians) * 4, 40, -Math.cos(radians) * 4], target: [0, 40, 0] });
    this.pump(6);
  }

  /** For screenshots: a 4 m square of the test field face on at `distance`, left drawn. */
  async showCutoutFaceOn(distance: number, discs?: number, setId?: string): Promise<void> {
    this.clear();
    const { material, set } = await this.cutoutMaterial(discs, setId);
    this.cutoutPlane(material, [0, 40, 0], 4, 'front', set.entry.extentUMm);
    this.pose({ position: [0, 40, -distance], target: [0, 40, 0] });
    this.pump(4);
  }

  /** For screenshots: the shadow scene of `measureCutoutShadow`, left drawn with the sun straight down. */
  async showCutoutShadow(setId?: string): Promise<void> {
    this.clear();
    const { material, set } = await this.cutoutMaterial(undefined, setId);
    const ground = await this.library.resolve('cc0.footway-paving');
    this.environment!.sun.setRotation(new pc.Quat().setFromEulerAngles(0, 0, 0));
    this.cutoutPlane(ground.material, [0, 0, 0], 16, 'up', 1800);
    this.cutoutPlane(material, [0, 2.5, 0], 4, 'up', set.entry.extentUMm);
    this.pose({ position: [0, 1.3, -7], target: [0, 0, 0] });
    this.pump(6);
  }

  /**
   * Presented frame times while the engine renders every frame and the camera walks along the
   * street at eye level, so the shadows, probe and occlusion are paid on every frame.
   *
   * The top-level percentiles use the app's own validation recorder's clock: the `frameupdate`
   * interval, which PlayCanvas takes from the animation frame timestamps. `frameEnd` is the
   * interval between `performance.now()` readings at `frameend`, which adds the jitter of the
   * frame's own script work; `work` is the script time from `frameupdate` to `frameend` (GPU time
   * is not in it).
   */
  async presentedFrameTimes(seconds: number): Promise<Record<string, unknown>> {
    const app = this.app;
    const presented: number[] = [];
    const intervals: number[] = [];
    const work: number[] = [];
    let last = -1;
    let started = -1;
    let drawCalls = 0;
    const eye = KERB_HEIGHT_M + EYE_M;
    let t = 0;
    const walk = (dt: number): void => {
      t += dt;
      const x = -12 + ((t * 1.65) % 24);
      this.camera.setPosition(x, eye, 0.8);
      this.camera.lookAt(x + 6, 2.2, 2.2);
    };
    const onUpdate = (ms: number): void => {
      if (last >= 0) presented.push(ms);
      started = performance.now();
    };
    const onEnd = (): void => {
      const now = performance.now();
      if (last >= 0) intervals.push(now - last);
      if (started >= 0) work.push(now - started);
      last = now;
      drawCalls = Math.max(drawCalls, app.stats.drawCalls.total);
    };
    app.on('update', walk);
    app.on('frameupdate', onUpdate);
    app.on('frameend', onEnd);
    app.autoRender = true;
    await new Promise((resolve) => setTimeout(resolve, seconds * 1000));
    app.autoRender = false;
    app.off('update', walk);
    app.off('frameupdate', onUpdate);
    app.off('frameend', onEnd);
    const summary = (values: number[]): Record<string, number> => {
      const sorted = [...values].sort((a, b) => a - b);
      const at = (q: number): number => Math.round(sorted[Math.min(sorted.length - 1, Math.round((sorted.length - 1) * q))]! * 100) / 100;
      return {
        frames: sorted.length, p50: at(0.5), p95: at(0.95), p99: at(0.99), max: at(1),
        over16_7: sorted.filter((value) => value > 16.7).length,
      };
    };
    const heap = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize;
    return {
      ...summary(presented),
      frameEnd: summary(intervals),
      work: summary(work),
      drawCalls,
      jsHeapMb: heap === undefined ? -1 : Math.round((heap / 1048576) * 100) / 100,
    };
  }

  /** Synchronous frame times: update, render, and a one-pixel read that waits for the GPU. */
  frameTimes(frames: number): { readonly p50: number; readonly p95: number; readonly max: number; readonly drawCalls: number } {
    const gl = this.gl;
    const pixel = new Uint8Array(4);
    const times: number[] = [];
    let drawCalls = 0;
    // The counter `app.stats.drawCalls.total` reads, which only the app's own tick copies out.
    const device = this.app.graphicsDevice as unknown as { _drawCallsPerFrame: number };
    for (let i = 0; i < frames; i += 1) {
      const start = performance.now();
      device._drawCallsPerFrame = 0;
      this.app.update(1 / 60);
      this.app.render();
      gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
      times.push(performance.now() - start);
      drawCalls = Math.max(drawCalls, device._drawCallsPerFrame);
    }
    times.sort((a, b) => a - b);
    const at = (q: number): number => Math.round(times[Math.min(times.length - 1, Math.floor(q * times.length))]! * 100) / 100;
    return { p50: at(0.5), p95: at(0.95), max: at(1), drawCalls };
  }

  stats(): Record<string, unknown> {
    return {
      look: `${this.look.id}@${this.look.version}`,
      drawnSets: this.drawnSets,
      decodedTextureBytes: this.library.decodedTextureBytes,
      probeBytes: this.environment?.residentBytes ?? 0,
      transferredSetBytes: [...this.setBytes.values()].reduce((a, b) => a + b, 0),
      wall: WALL,
    };
  }
}

declare global {
  interface Window { bench?: Bench; benchError?: string }
}

const canvas = document.getElementById('bench') as HTMLCanvasElement;
Bench.create(canvas).then(async (bench) => {
  window.bench = bench;
  await bench.showStreet();
  bench.pose(bench.eyeLevel('wall'));
  bench.pump(3);
  document.body.dataset.ready = 'true';
}).catch((error: unknown) => {
  window.benchError = error instanceof Error ? `${error.message}\n${error.stack ?? ''}` : String(error);
  document.body.dataset.ready = 'error';
});
