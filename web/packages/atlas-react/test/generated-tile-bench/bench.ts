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
import { TileTextureLibrary, surfaceUv, type TileMaterialReference } from '../../src/playcanvas/generated-tile/texture-materials.js';
import { buildSurfaceMesh } from '../../src/playcanvas/generated-tile/surface-mesh.js';
import { applyTileEnvironment, type TileEnvironment } from '../../src/playcanvas/generated-tile/environment.js';
import {
  CORNICE, DOOR, KERB_FACE_Z, KERB_HEIGHT_M, WALL, WALL_Z,
  calibrationWall, testStreet, type TestStreetSets, type TestSurface,
} from './test-street.js';

declare const __TEXTURE_ROOT__: string;

const EYE_M = 1.62;
const UNIT_SCALE: TileMaterialReference = { textureSetId: '', uvScaleMillionths: 1_000_000, uvRotationUrad: 0 };

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
    const frame = this.environment!.frame;
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
    const frame = this.environment!.frame;
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
    const frame = this.environment!.frame;
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
