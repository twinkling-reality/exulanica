// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mock = vi.hoisted(() => ({ update: (_dt: number) => {}, release: vi.fn(), destroy: vi.fn(),
  allowed: true, app: null as null | { autoRender: boolean }, actor: null as any }));
vi.mock('playcanvas', () => {
  class Entity {
    camera: any;
    constructor(public name: string) {}
    addComponent(kind: string, value: unknown) { if (kind === 'camera') this.camera = value; }
    addChild() {} setPosition() {} lookAt() {} setEulerAngles() {} findComponents() { return []; }
  }
  class App {
    autoRender = false; root = new Entity('root'); scene = {}; graphicsDevice = { resizeCanvas: vi.fn() };
    constructor() { mock.app = this; }
    init() {} setCanvasResolution() {} start() {} destroy() { mock.destroy(); }
    on(_name: string, fn: (dt: number) => void) { mock.update = fn; }
  }
  return { Entity, AppBase: App, AppOptions: class {}, Color: class {}, createGraphicsDevice: async () => ({}),
    RenderComponentSystem: class {}, CameraComponentSystem: class {}, LightComponentSystem: class {}, AnimComponentSystem: class {},
    TextureHandler: class {}, ContainerHandler: class {}, RESOLUTION_AUTO: 'auto', TONEMAP_ACES: 'aces' };
});
vi.mock('../src/playcanvas/native-character-pool.js', () => ({ NativeCharacterPool: class {
  acquire() { return Promise.resolve({ inspection: { clipNames: ['Interact'], nodeNames: ['head'] },
    asset: { resource: { animations: [{ resource: {} }] } }, release: mock.release }); }
  destroy() {}
} }));
vi.mock('../src/playcanvas/native-character-actor.js', () => ({ NativeCharacterActor: class {
  root = { enabled: true };
  model = { anim: { loadStateGraph: vi.fn(), assignAnimation: vi.fn(), baseLayer: { play: vi.fn(), activeStateCurrentTime: 0 }, speed: 0, update: vi.fn() }, findByName: () => null };
  constructor() { mock.actor = this; }
  update() {} destroy() { mock.release(); }
} }));
import { FirstPersonGesture, type FirstPersonGestureDescriptor } from '../src/playcanvas/first-person-gesture.js';

const descriptor = { character: {}, clip: 'Interact', durationSeconds: 1.26, eye: [0, 1.65, .2], hiddenNodes: ['head'] } as unknown as FirstPersonGestureDescriptor;
beforeEach(() => {
  vi.clearAllMocks();
  mock.allowed = true;
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
});
describe('first-person tool gesture', () => {
  it('plays once, ends without leaving an overlay, and restarts cleanly after interruption', async () => {
    const canvas = document.createElement('canvas');
    const view = await FirstPersonGesture.create(canvas, vi.fn(), () => mock.allowed);
    await view.prepare(descriptor, {});
    expect(view.play(75)).toBe(true);
    expect(canvas.hidden).toBe(false);
    mock.update(.5);
    expect(canvas.hidden).toBe(false);
    mock.update(.8);
    expect(canvas.hidden).toBe(true);
    expect(mock.app?.autoRender).toBe(false);
    view.play(75); mock.update(.3); view.cancel();
    expect(canvas.hidden).toBe(true);
    view.play(75);
    expect(mock.actor.model.anim.baseLayer.activeStateCurrentTime).toBe(0);
    view.destroy();
    expect(canvas.hidden).toBe(true);
    expect(mock.destroy).toHaveBeenCalledOnce();
  });
  it('skips and interrupts the presentation when camera, motion preference, or availability disallows it', async () => {
    const canvas = document.createElement('canvas');
    const view = await FirstPersonGesture.create(canvas, vi.fn(), () => mock.allowed);
    await view.prepare(descriptor, {});
    mock.allowed = false;
    expect(view.play(75)).toBe(false);
    mock.allowed = true; view.play(75);
    mock.allowed = false; mock.update(.1);
    expect(canvas.hidden).toBe(true);
    view.destroy();
  });
  it('refuses a missing source clip and releases the borrowed asset', async () => {
    const view = await FirstPersonGesture.create(document.createElement('canvas'), vi.fn());
    await expect(view.prepare({ ...descriptor, clip: 'Invented' }, {})).rejects.toThrow('does not support');
    expect(mock.release).toHaveBeenCalledOnce();
    expect(view.play(75)).toBe(false);
    view.destroy();
  });
});
