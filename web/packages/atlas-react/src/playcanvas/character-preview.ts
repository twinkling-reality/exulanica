import * as pc from 'playcanvas';
import { NativeCharacterActor } from './native-character-actor.js';
import { NativeCharacterPool, type CharacterByteLoader } from './native-character-pool.js';
import type { NativeCharacterAppearance, NativeCharacterDescriptor } from './native-character.js';

const INSPECTION_HEIGHT = 1.9;

/** Fixed metric framing makes body-height changes visible instead of zooming them away. */
export function characterInspectionFrame(zoom: number): {
  readonly position: readonly [number, number, number];
  readonly target: readonly [number, number, number];
  readonly verticalFovDegrees: number;
} {
  const safeZoom = Math.max(.8, Math.min(1.7, zoom));
  const targetHeight = INSPECTION_HEIGHT * .51 + Math.max(0, safeZoom - 1) * .52;
  return {
    position: [0, targetHeight + INSPECTION_HEIGHT * .03, INSPECTION_HEIGHT * 2.35 / safeZoom],
    target: [0, targetHeight, 0],
    verticalFovDegrees: 34,
  };
}

/** An independent inspection stage. It never moves or creates a world subject. */
export class CharacterPreview {
  private actor: NativeCharacterActor | null = null;
  private request: AbortController | null = null;
  private readonly pool: NativeCharacterPool;
  private readonly resize: ResizeObserver;
  private disposed = false;
  private visible = true;
  private yaw = 0;
  private zoom = 1;
  private reduced = false;
  private motion: 'idle' | 'walk' | 'run' = 'idle';

  private constructor(
    private readonly app: pc.AppBase,
    private readonly camera: pc.Entity,
    private readonly canvas: HTMLCanvasElement,
    load: CharacterByteLoader,
  ) {
    this.pool = new NativeCharacterPool(app, load);
    this.resize = new ResizeObserver(() => this.resizeCanvas());
    this.resize.observe(canvas);
    this.resizeCanvas();
  }

  static async create(canvas: HTMLCanvasElement, load: CharacterByteLoader): Promise<CharacterPreview> {
    const device = await pc.createGraphicsDevice(canvas, { deviceTypes: ['webgl2'], antialias: true });
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem, pc.AnimComponentSystem];
    options.resourceHandlers = [pc.TextureHandler, pc.ContainerHandler];
    app.init(options);
    device.maxPixelRatio = Math.min(window.devicePixelRatio, 1.5);
    app.setCanvasResolution(pc.RESOLUTION_AUTO);
    app.scene.ambientLight = new pc.Color(.6, .58, .64);
    const camera = new pc.Entity('character-inspection-camera');
    camera.addComponent('camera', { clearColor: new pc.Color(.922, .906, .937), fov: 34, nearClip: .05, farClip: 40, toneMapping: pc.TONEMAP_ACES });
    app.root.addChild(camera);
    const key = new pc.Entity('character-key-light');
    key.addComponent('light', { type: 'directional', intensity: .9, color: new pc.Color(1, .94, .9) });
    key.setEulerAngles(30, 20, 0);
    app.root.addChild(key);
    const fill = new pc.Entity('character-fill-light');
    fill.addComponent('light', { type: 'directional', intensity: .55, color: new pc.Color(.8, .86, 1) });
    fill.setEulerAngles(20, -150, 0);
    app.root.addChild(fill);
    const rim = new pc.Entity('character-rim-light');
    rim.addComponent('light', { type: 'directional', intensity: .18, color: new pc.Color(.88, .82, 1) });
    rim.setEulerAngles(-18, 168, 0);
    app.root.addChild(rim);
    const view = new CharacterPreview(app, camera, canvas, load);
    view.frame();
    app.start();
    return view;
  }

  private resizeCanvas(): void {
    if (this.disposed) return;
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) this.app.graphicsDevice.resizeCanvas(rect.width, rect.height);
    this.app.renderNextFrame = true;
  }
  private frame(): void {
    const frame = characterInspectionFrame(this.zoom);
    this.camera.setPosition(...frame.position);
    this.camera.lookAt(...frame.target);
    this.app.renderNextFrame = true;
  }
  async show(descriptor: NativeCharacterDescriptor, appearance: NativeCharacterAppearance): Promise<void> {
    this.request?.abort();
    const request = new AbortController();
    this.request = request;
    const lease = await this.pool.acquire(descriptor.asset, request.signal);
    if (this.disposed || request.signal.aborted) { lease.release(); return; }
    let actor: NativeCharacterActor;
    try {
      actor = new NativeCharacterActor({ kind: 'player', playerId: 'local-viewer' }, descriptor, lease,
        this.app.root, () => ({ presence: 'allowed', source: 'available' }), appearance);
    } catch (error) { lease.release(); throw error; }
    this.actor?.destroy();
    this.actor = actor;
    actor.update({ position: [0, 0, 0], yaw: this.yaw, deltaSeconds: 0, discontinuity: true }, this.visible);
    this.frame();
    this.setMotion(this.motion);
  }
  setAppearance(appearance: NativeCharacterAppearance): void {
    this.actor?.setAppearance(appearance);
    this.app.renderNextFrame = true;
  }
  rotate(radians: number): void {
    this.yaw = radians;
    this.actor?.root.setLocalEulerAngles(0, radians * 180 / Math.PI, 0);
    this.app.renderNextFrame = true;
  }
  setZoom(value: number): void { this.zoom = Math.max(.8, Math.min(1.7, value)); this.frame(); }
  setMotion(motion: 'idle' | 'walk' | 'run'): void {
    this.motion = motion;
    const anim = this.actor?.model.anim;
    if (anim) {
      anim.baseLayer!.play(this.reduced ? 'idle' : motion);
      anim.baseLayer!.activeStateCurrentTime = 0;
      anim.speed = this.reduced ? 0 : 1;
      anim.update(0);
    }
    this.app.renderNextFrame = true;
  }
  setReducedMotion(value: boolean): void {
    this.reduced = value;
    this.app.autoRender = this.visible && !value;
    this.setMotion(this.motion);
  }
  setVisible(value: boolean): void {
    this.visible = value;
    if (this.actor) this.actor.root.enabled = value;
    this.app.autoRender = value && !this.reduced;
    if (value) this.resizeCanvas();
  }
  destroy(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.request?.abort();
    this.resize.disconnect();
    this.actor?.destroy();
    this.pool.destroy();
    this.app.destroy();
  }
}
