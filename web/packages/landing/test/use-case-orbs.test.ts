// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { buildUseCases } from '../src/ui/use-cases.js';
import { createOrbState } from '../src/ui/use-case-orb-state.js';

let onIntersection: IntersectionObserverCallback | undefined;
const disconnect = vi.fn();
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance'] });
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback: IntersectionObserverCallback) { onIntersection = callback; }
    observe() {} disconnect = disconnect;
  });
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect = disconnect; });
});
afterEach(async () => {
  document.body.replaceChildren(); await Promise.resolve();
  delete document.documentElement.dataset.reducedMotion;
  vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); disconnect.mockClear();
});
const makeGL = () => {
  const mock = {
    VERTEX_SHADER: 35633, FRAGMENT_SHADER: 35632, COMPILE_STATUS: 35713, LINK_STATUS: 35714,
    ARRAY_BUFFER: 34962, STATIC_DRAW: 35044, FLOAT: 5126, COLOR_BUFFER_BIT: 16384, TRIANGLES: 4,
    createProgram: vi.fn(() => ({})), createShader: vi.fn(() => ({})), createBuffer: vi.fn((): WebGLBuffer | null => ({})),
    shaderSource: vi.fn(), compileShader: vi.fn(), getShaderParameter: vi.fn(() => true), attachShader: vi.fn(),
    linkProgram: vi.fn(), getProgramParameter: vi.fn(() => true), getAttribLocation: vi.fn(() => 0),
    getUniformLocation: vi.fn((_program: unknown, name: string) => ({ name })), useProgram: vi.fn(),
    bindBuffer: vi.fn(), bufferData: vi.fn(), enableVertexAttribArray: vi.fn(), vertexAttribPointer: vi.fn(),
    clearColor: vi.fn(), clear: vi.fn(), viewport: vi.fn(), uniform2f: vi.fn(), uniform1f: vi.fn(), drawArrays: vi.fn(),
    deleteShader: vi.fn(), deleteBuffer: vi.fn(), deleteProgram: vi.fn(), getExtension: vi.fn(() => null),
  };
  return { mock, context: mock as unknown as WebGLRenderingContext };
};
const mount = async () => {
  const host = buildUseCases(); document.body.append(host); await Promise.resolve();
  host.querySelectorAll('.use-case-orb').forEach(orb => vi.spyOn(orb, 'getBoundingClientRect').mockReturnValue({ left: 0, bottom: 200, width: 200, height: 200 } as DOMRect));
  vi.spyOn(host.querySelector('.use-case-directory')!, 'getBoundingClientRect').mockReturnValue({ left: 0, bottom: 400, width: 1000, height: 400 } as DOMRect);
  onIntersection?.([...host.querySelectorAll('.use-case-orb')].map(target => ({ target, isIntersecting: true }) as IntersectionObserverEntry), {} as IntersectionObserver);
  return host;
};

it('integrates one active clock, smooths emphasis, and never catches up after suspension', () => {
  const state = createOrbState([2.4, 6.8, 11.2]);
  state.advance(0); state.advance(30);
  const before = state.values.map(value => value.phase);
  state.select(1); state.advance(60);
  expect(state.values[1]!.emphasis).toBeGreaterThan(0);
  expect(state.values[0]!.emphasis).toBe(0);
  expect(state.values[1]!.phase - before[1]!).toBeGreaterThan(state.values[0]!.phase - before[0]!);
  const held = state.values.map(value => value.phase);
  state.suspend(); state.advance(10000);
  expect(state.values.map(value => value.phase)).toEqual(held);
  state.advance(20000);
  expect(state.values[1]!.phase - held[1]!).toBeLessThan(1 / 30);
});

it('uses one context and triangle, holds inactive and reduced poses, then releases every resource', async () => {
  const { mock, context } = makeGL();
  vi.stubGlobal('WebGLRenderingContext', class {});
  const getContext = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context);
  const host = await mount(); vi.advanceTimersByTime(100);
  expect(host.querySelector('.use-case-directory')?.getAttribute('data-orb-renderer')).toBe('webgl');
  expect(getContext).toHaveBeenCalledOnce();
  expect(getContext).toHaveBeenCalledWith('webgl', expect.objectContaining({ premultipliedAlpha: false }));
  expect(mock.createProgram).toHaveBeenCalledOnce(); expect(mock.createBuffer).toHaveBeenCalledOnce();
  expect(mock.bufferData.mock.calls[0]?.[1]).toEqual(new Float32Array([-1, -1, 3, -1, -1, 3]));
  expect(mock.drawArrays).toHaveBeenCalledWith(4, 0, 3);
  const resolution = mock.uniform2f.mock.calls.filter(call => (call[0] as { name: string }).name === 'uResolution');
  expect(resolution.length).toBeGreaterThan(3);
  host.inert = true; await Promise.resolve();
  const held = mock.drawArrays.mock.calls.length; vi.advanceTimersByTime(3000); expect(mock.drawArrays.mock.calls.length).toBe(held);
  host.inert = false; await Promise.resolve(); vi.advanceTimersByTime(100); expect(mock.drawArrays.mock.calls.length).toBeGreaterThan(held);
  document.documentElement.dataset.reducedMotion = 'true'; await Promise.resolve();
  const still = mock.drawArrays.mock.calls.length; vi.advanceTimersByTime(3000); expect(mock.drawArrays.mock.calls.length).toBe(still);
  host.querySelector<HTMLAnchorElement>('.use-case-destination')!.focus();
  const focused = mock.drawArrays.mock.calls.length; vi.advanceTimersByTime(1000); expect(mock.drawArrays.mock.calls.length).toBe(focused);
  host.remove(); await Promise.resolve();
  expect(mock.deleteShader).toHaveBeenCalledTimes(2); expect(mock.deleteProgram).toHaveBeenCalledOnce(); expect(mock.deleteBuffer).toHaveBeenCalledOnce();
  expect(disconnect).toHaveBeenCalledTimes(2); expect(vi.getTimerCount()).toBe(0);
});

it('keeps all journey links available when WebGL allocation fails', async () => {
  const { mock, context } = makeGL(); vi.stubGlobal('WebGLRenderingContext', class {});
  mock.createBuffer.mockReturnValue(null);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context);
  const host = await mount();
  expect(host.querySelector('.use-case-directory')?.classList.contains('has-category-orbs')).toBe(false);
  expect(host.querySelectorAll('.use-case-destination')).toHaveLength(3);
  expect(mock.deleteProgram).toHaveBeenCalledOnce(); expect(mock.deleteShader).toHaveBeenCalledTimes(2);
  expect(vi.getTimerCount()).toBe(0);
});
