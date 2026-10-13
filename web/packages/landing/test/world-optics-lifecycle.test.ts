// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { mountWorldOptics } from '../src/ui/world-optics.js';
import * as native from '../src/ui/world-native-orbit.js';

class PendingImage {
  static instances: PendingImage[] = [];
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  src = '';
  constructor() { PendingImage.instances.push(this); }
}
class Observer {
  static instances: Observer[] = [];
  observe = vi.fn();
  disconnect = vi.fn();
  constructor() { Observer.instances.push(this); }
}
let frames: Map<number, FrameRequestCallback>;
let nextFrame: number;
let gl: Record<string, any>;
let mountNative: MockInstance<typeof native.mountNativeWorldOrbit>;
let media: MediaQueryList;
let addMedia: ReturnType<typeof vi.spyOn>;
let removeMedia: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  PendingImage.instances = []; Observer.instances = []; frames = new Map(); nextFrame = 0;
  vi.stubGlobal('Image', PendingImage);
  vi.stubGlobal('WebGLRenderingContext', class {});
  for (const name of ['ResizeObserver', 'IntersectionObserver', 'MutationObserver']) vi.stubGlobal(name, Observer);
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frames.set(++nextFrame, callback); return nextFrame; });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => { frames.delete(id); });
  media = Object.assign(new EventTarget(), { matches: false }) as MediaQueryList;
  vi.spyOn(window, 'matchMedia').mockReturnValue(media);
  addMedia = vi.spyOn(media, 'addEventListener');
  removeMedia = vi.spyOn(media, 'removeEventListener');
  gl = new Proxy({ getParameter: vi.fn(() => 4096), getShaderParameter: vi.fn(() => true), getProgramParameter: vi.fn(() => true) } as Record<string, any>, {
    get(target, property: string) {
      if (!(property in target)) target[property] = property === property.toUpperCase() ? 1 : vi.fn(() => ({}));
      return target[property];
    },
  });
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(((kind: string) => kind === 'webgl' ? gl : { drawImage: vi.fn() }) as any);
  mountNative = vi.spyOn(native, 'mountNativeWorldOrbit');
});
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function fixture() {
  const root = document.createElement('div');
  root.innerHTML = '<a class="orbit-item world-choice" data-orbit-index="0" data-scene-index="0"></a>';
  document.body.append(root);
  const owner = mountWorldOptics(root, ['one.jpg', 'two.jpg'])!;
  const canvas = root.querySelector('canvas')!;
  return { root, owner, canvas };
}

describe('world optics fallback ownership', () => {
  it.each(['image error', 'context loss'])('retains one fallback after %s and disposes its resources with the parent', failure => {
    const { root, owner, canvas } = fixture();
    if (failure === 'image error') PendingImage.instances[0]!.onerror!();
    else canvas.dispatchEvent(new Event('webglcontextlost'));
    expect(root.classList.contains('has-native-orbit')).toBe(true);
    expect(mountNative).toHaveBeenCalledTimes(1);
    const fallback = mountNative.mock.results[0]!.value;
    const disposeFallback = vi.spyOn(fallback, 'dispose');
    const redrawFallback = vi.spyOn(fallback, 'redraw');
    owner.redraw();
    expect(redrawFallback).toHaveBeenCalledOnce();
    PendingImage.instances.forEach(image => { image.onerror!(); image.onload!(); });
    canvas.dispatchEvent(new Event('webglcontextlost'));
    expect(mountNative).toHaveBeenCalledTimes(1);
    expect(gl.texImage2D).not.toHaveBeenCalled();
    owner.dispose(); owner.dispose();
    expect(disposeFallback).toHaveBeenCalledOnce();
    expect(frames.size).toBe(0);
    expect(Observer.instances.every(observer => observer.disconnect.mock.calls.length === 1)).toBe(true);
    expect(root.classList.contains('has-native-orbit')).toBe(false);
    for (const [type, listener] of addMedia.mock.calls) {
      expect(removeMedia.mock.calls.some(([removedType, removedListener]) => removedType === type && removedListener === listener)).toBe(true);
    }
    PendingImage.instances.forEach(image => { image.onerror!(); image.onload!(); });
    canvas.dispatchEvent(new Event('webglcontextlost'));
    owner.redraw();
    expect(mountNative).toHaveBeenCalledTimes(1);
    expect(redrawFallback).toHaveBeenCalledOnce();
    expect(frames.size).toBe(0);
  });
  it('ignores pending image failure and load after parent disposal before any fallback', () => {
    const { owner, canvas } = fixture();
    owner.dispose();
    PendingImage.instances.forEach(image => { image.onerror!(); image.onload!(); });
    canvas.dispatchEvent(new Event('webglcontextlost'));
    expect(mountNative).not.toHaveBeenCalled();
    expect(frames.size).toBe(0);
    expect(gl.texImage2D).not.toHaveBeenCalled();
  });
});
