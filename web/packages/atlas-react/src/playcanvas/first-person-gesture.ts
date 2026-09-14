import * as pc from 'playcanvas';
import { NativeCharacterActor } from './native-character-actor.js';
import { NativeCharacterPool, type CharacterByteLoader } from './native-character-pool.js';
import type { NativeCharacterAppearance, NativeCharacterDescriptor } from './native-character.js';

export interface FirstPersonGestureDescriptor {
  readonly character: NativeCharacterDescriptor;
  readonly clip: string;
  readonly durationSeconds: number;
  /** A presentation camera in the asset's metre frame, never a player/traversal override. */
  readonly eye: readonly [number, number, number];
  readonly hiddenNodes: readonly string[];
}

/** A camera-relative, one-shot view model. Never a world entity, collision body, or action gate. */
export class FirstPersonGesture {
  private readonly pool: NativeCharacterPool;
  private actor: NativeCharacterActor | null = null;
  private descriptor: FirstPersonGestureDescriptor | null = null;
  private request: AbortController | null = null;
  private elapsed: number | null = null;
  private disposed = false;
  private readonly resize: ResizeObserver;
  private constructor(private readonly app: pc.AppBase, private readonly camera: pc.Entity,
    private readonly canvas: HTMLCanvasElement, load: CharacterByteLoader, private readonly isAllowed: () => boolean) {
    this.pool = new NativeCharacterPool(app, load);
    this.resize = new ResizeObserver(() => this.resizeCanvas());
    this.resize.observe(canvas);
    app.autoRender = false;
    app.on('update', (dt: number) => {
      if (this.elapsed === null) return;
      if (!this.isAllowed()) { this.cancel(); return; }
      this.elapsed += dt;
      if (this.elapsed >= (this.descriptor?.durationSeconds ?? 0)) this.cancel();
    });
  }
  static async create(canvas: HTMLCanvasElement, load: CharacterByteLoader, isAllowed: () => boolean = () => true): Promise<FirstPersonGesture> {
    const device = await pc.createGraphicsDevice(canvas, { deviceTypes: ['webgl2'], antialias: true });
    const app = new pc.AppBase(canvas);
    const options = new pc.AppOptions();
    options.graphicsDevice = device;
    options.componentSystems = [pc.RenderComponentSystem, pc.CameraComponentSystem, pc.LightComponentSystem, pc.AnimComponentSystem];
    options.resourceHandlers = [pc.TextureHandler, pc.ContainerHandler];
    app.init(options);
    device.maxPixelRatio = 1;
    app.setCanvasResolution(pc.RESOLUTION_AUTO);
    app.scene.ambientLight = new pc.Color(.75, .77, .8);
    const camera = new pc.Entity('first-person-gesture-camera', app);
    camera.addComponent('camera', { clearColor: new pc.Color(0, 0, 0, 0), fov: 75, nearClip: .035, farClip: 5, toneMapping: pc.TONEMAP_ACES });
    app.root.addChild(camera);
    const light = new pc.Entity('first-person-gesture-light', app);
    light.addComponent('light', { type: 'directional', intensity: 1.1, color: new pc.Color(1, .97, .94) });
    light.setEulerAngles(35, 30, 0);
    app.root.addChild(light);
    const view = new FirstPersonGesture(app, camera, canvas, load, isAllowed);
    app.start();
    return view;
  }
  private resizeCanvas(): void {
    if (this.disposed) return;
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) this.app.graphicsDevice.resizeCanvas(rect.width, rect.height);
  }
  async prepare(descriptor: FirstPersonGestureDescriptor, appearance: NativeCharacterAppearance): Promise<void> {
    this.cancel();
    this.request?.abort();
    const request = new AbortController();
    this.request = request;
    if (!Number.isFinite(descriptor.durationSeconds) || descriptor.durationSeconds <= 0 || descriptor.durationSeconds > 5 ||
      descriptor.eye.length !== 3 || !descriptor.eye.every(Number.isFinite)) throw new Error('Invalid first-person presentation');
    const lease = await this.pool.acquire(descriptor.character.asset, request.signal);
    if (this.disposed || request.signal.aborted) { lease.release(); return; }
    const clipIndex = lease.inspection.clipNames.indexOf(descriptor.clip);
    if (clipIndex < 0 || descriptor.hiddenNodes.some(name => !lease.inspection.nodeNames.includes(name))) {
      lease.release(); throw new Error('This character does not support the requested gesture.');
    }
    let actor: NativeCharacterActor | null = null;
    try {
      actor = new NativeCharacterActor({ kind: 'player', playerId: 'local-viewer' }, descriptor.character,
        lease, this.app.root, () => ({ presence: this.disposed ? 'denied' : 'allowed', source: 'available' }), appearance);
      actor.update({ position: [0, 0, 0], yaw: 0, deltaSeconds: 0, discontinuity: true });
      for (const name of descriptor.hiddenNodes) {
        const node = actor.model.findByName(name);
        // Hide render components only; never disable the skeletal hierarchy.
        if (node instanceof pc.Entity) for (const render of node.findComponents('render') as pc.RenderComponent[]) render.enabled = false;
      }
      const track = (lease.asset.resource as pc.ContainerResource & { animations: pc.Asset[] }).animations[clipIndex]!.resource as pc.AnimTrack;
      const anim = actor.model.anim!;
      anim.loadStateGraph({ layers: [{ name: 'Base', states: [{ name: 'START' }, { name: 'reach', speed: 1, loop: false }],
        transitions: [{ from: 'START', to: 'reach' }] }], parameters: {} });
      anim.assignAnimation('reach', track);
      actor.root.enabled = false;
      anim.speed = 0;
    } catch (error) { if (actor) actor.destroy(); else lease.release(); throw error; }
    this.actor?.destroy();
    this.actor = actor;
    this.descriptor = descriptor;
    this.camera.setPosition(...descriptor.eye);
    this.camera.lookAt(descriptor.eye[0], descriptor.eye[1] - .12, descriptor.eye[2] + 1);
  }
  play(fieldOfView: number): boolean {
    if (this.disposed || !this.actor || !this.descriptor || !this.isAllowed()) return false;
    this.cancel();
    this.canvas.hidden = false;
    this.resizeCanvas();
    this.camera.camera!.fov = Math.max(60, Math.min(90, fieldOfView));
    this.actor.root.enabled = true;
    const anim = this.actor.model.anim!;
    anim.baseLayer!.play('reach');
    anim.baseLayer!.activeStateCurrentTime = 0;
    anim.speed = 1;
    anim.update(0);
    this.elapsed = 0;
    this.canvas.dataset['state'] = 'playing';
    this.app.autoRender = true;
    return true;
  }
  cancel(): void {
    this.elapsed = null;
    this.canvas.dataset['state'] = 'idle';
    this.canvas.hidden = true;
    this.app.autoRender = false;
    if (this.actor) { this.actor.root.enabled = false; this.actor.model.anim!.speed = 0; }
  }
  destroy(): void {
    if (this.disposed) return;
    this.cancel();
    this.disposed = true;
    this.request?.abort();
    this.resize.disconnect();
    this.actor?.destroy();
    this.pool.destroy();
    this.app.destroy();
  }
}
