// @vitest-environment happy-dom
// A moment's hidden preview waits frame by frame (tools/previews/world-workspace/front-door-preview.ts framesDrawn): on
// each animation frame, or after the recipe's retry where the browser draws none, as it draws none for a page in a
// background tab, so a picture asked while the person is on another tab is still drawn, at the old pace.
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../../tools/previews/world-workspace/scene-sight.ts', () => ({ sceneHit: () => null, sceneSight: () => null }));
vi.mock('../src/composition/world-pictures.ts', () => ({ frameJpeg: async () => null, takeFrame: async () => null }));

/** What these tests use of the preview module, which sits outside this package. */
interface Preview { framesDrawn(binding: { invalidate(): void }, count: number): Promise<void> }
// A joined path: the test runner still finds the file, and the type checker leaves the preview module out of the program.
const preview = async (): Promise<Preview> => import('../../../../tools/previews/world-workspace/' + 'front-door-preview.ts') as never;

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('a moment preview waiting frame by frame', () => {
  it('steps on each animation frame while the page draws', async () => {
    vi.useFakeTimers();
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => frames.push(callback));
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    const { framesDrawn } = await preview();
    const binding = { invalidate: vi.fn() };
    let done = false;
    void framesDrawn(binding, 2).then(() => { done = true; });
    frames.shift()!(16);
    frames.shift()!(33);
    await vi.advanceTimersByTimeAsync(0);
    expect(done).toBe(true);
    expect(binding.invalidate).toHaveBeenCalledTimes(2);
  });

  it('steps after the recipe\'s retry where the browser draws no frame, as for a page in a background tab', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('requestAnimationFrame', () => 1);
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    const { framesDrawn } = await preview();
    const binding = { invalidate: vi.fn() };
    let done = false;
    void framesDrawn(binding, 2).then(() => { done = true; });
    await vi.advanceTimersByTimeAsync(499);
    expect(binding.invalidate).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(binding.invalidate).toHaveBeenCalledTimes(2);
    expect(done).toBe(false);
    await vi.advanceTimersByTimeAsync(500);
    expect(done).toBe(true);
  });
});
