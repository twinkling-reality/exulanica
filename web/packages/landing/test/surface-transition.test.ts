// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { createSurfaceTransition, titleCamera } from '../src/ui/surface-transition.js';

function fixture(reduced = false, withLandscape = false) {
  const pending: {
    complete(): void;
    cancel: ReturnType<typeof vi.fn>;
    frames: Keyframe[];
    options: number | KeyframeAnimationOptions | undefined;
  }[] = [];
  const panes = {
    title: document.createElement('section'),
    purpose: document.createElement('section'),
    capabilities: document.createElement('section'),
  };
  const landscape = document.createElement('div');
  const wordmark = document.createElement('h1');
  wordmark.id = 'title-wordmark';
  wordmark.getBoundingClientRect = () => new DOMRect(240, 300, 720, 110);
  panes.title.append(wordmark);
  panes.title.getBoundingClientRect = () => new DOMRect(0, 0, 1200, 800);
  for (const pane of [...Object.values(panes), landscape]) {
    pane.animate = vi.fn((frames: Keyframe[] | PropertyIndexedKeyframes | null,
      options?: number | KeyframeAnimationOptions) => {
      let complete!: () => void;
      let reject!: () => void;
      const finished = new Promise<Animation>((resolve, rejectPromise) => {
        complete = () => resolve({} as Animation);
        reject = () => rejectPromise(new Error('cancelled'));
      });
      const cancel = vi.fn(reject);
      pending.push({ complete, cancel, frames: frames as Keyframe[], options });
      return { finished, cancel } as unknown as Animation;
    });
  }
  return {
    panes, pending, landscape,
    transition: createSurfaceTransition(panes, () => reduced, withLandscape ? landscape : undefined),
  };
}

describe('landing surface transitions', () => {
  it('moves the artwork through exactly the title camera and returns both to rest', async () => {
    const { pending, landscape, transition } = fixture(false, true);
    transition.show('title');
    const rest = landscape.style.transform;
    transition.show('purpose');
    expect(pending[2]?.frames[0]?.transform).toBe(pending[0]?.frames[0]?.transform);
    expect(pending[2]?.frames.at(-1)?.transform).toBe(pending[0]?.frames.at(-1)?.transform);
    expect(pending[2]?.options).toEqual(pending[0]?.options);
    const purpose = landscape.style.transform;
    pending.forEach((animation) => animation.complete());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(landscape.style.transform).toBe(purpose);
    transition.show('title');
    expect(pending[5]?.frames[0]?.transform).toBe(pending[4]?.frames[0]?.transform);
    expect(pending[5]?.frames.at(-1)?.transform).toBe(pending[4]?.frames.at(-1)?.transform);
    transition.finish();
    expect(landscape.style.transform).toBe(rest);
    expect(landscape.style.willChange).toBe('');
  });

  it('places direct routes at their measured camera and moves between measured destinations', () => {
    const { panes, pending, landscape, transition } = fixture(false, true);
    transition.show('purpose');
    const expectedPurpose = titleCamera('purpose',
      panes.title.querySelector('h1')!.getBoundingClientRect(), panes.title.getBoundingClientRect(),
      { width: window.innerWidth, height: window.innerHeight }).transform;
    expect(landscape.style.transform).toBe(expectedPurpose);
    expect(pending).toHaveLength(0);
    transition.show('capabilities');
    expect(pending[2]?.frames[0]?.transform).toBe(expectedPurpose);
    expect(pending[2]?.frames.at(-1)?.transform).toBe(landscape.style.transform);
    expect(landscape.style.transform).not.toBe(expectedPurpose);
    transition.finish();
  });

  it('refreshes a resized camera without animation and snaps artwork for reduced motion', () => {
    const { panes, pending, landscape, transition } = fixture(true, true);
    transition.show('purpose');
    const before = landscape.style.transform;
    panes.title.querySelector('h1')!.getBoundingClientRect = () => new DOMRect(300, 200, 600, 100);
    transition.refresh();
    expect(landscape.style.transform).not.toBe(before);
    expect(pending).toHaveLength(0);
    transition.show('title');
    expect(pending).toHaveLength(2);
    expect(landscape.style.transform).toBe('translate3d(0, 0, 0) scale(1)');
    transition.finish();
  });

  it('projects either upper wordmark destination exactly to the viewport centre', () => {
    const pane = { left: 0, top: 0, width: 1200, height: 800 };
    const wordmark = { left: 240, top: 300, width: 720, height: 110 };
    const viewport = { width: 1200, height: 800 };
    for (const destination of ['purpose', 'capabilities'] as const) {
      const camera = titleCamera(destination, wordmark, pane, viewport);
      expect(600 + camera.scale * (camera.target.x - 600) + camera.x).toBeCloseTo(600);
      expect(400 + camera.scale * (camera.target.y - 400) + camera.y).toBeCloseTo(400);
      expect(camera.target.y).toBeLessThan(wordmark.top);
      expect(camera.y).toBeGreaterThan(0);
      expect(Math.sign(camera.x)).toBe(destination === 'purpose' ? -1 : 1);
    }
  });

  it('returns through the same destination-specific camera position', async () => {
    for (const destination of ['purpose', 'capabilities'] as const) {
      const { pending, transition } = fixture();
      transition.show('title');
      transition.show(destination);
      const departure = pending[0]?.frames.at(-1)?.transform;
      pending.forEach((animation) => animation.complete());
      await new Promise((resolve) => setTimeout(resolve, 0));
      transition.show('title');
      expect(pending[3]?.frames[0]?.transform).toBe(departure);
    }
  });

  it('opens a direct information route immediately with one accessible surface', () => {
    const { panes, pending, transition } = fixture();
    transition.show('purpose');
    expect(pending).toHaveLength(0);
    expect(panes.purpose.hidden).toBe(false);
    expect(panes.title.hidden).toBe(true);
    expect(panes.capabilities.inert).toBe(true);
    expect(panes.purpose.getAttribute('aria-hidden')).toBe('false');
  });

  it('starts text with the camera and releases temporary compositor hints on completion', async () => {
    const { panes, pending, transition } = fixture();
    panes.title.style.willChange = 'contents';
    transition.show('title');
    transition.show('purpose');
    expect((pending[1]?.options as KeyframeAnimationOptions).delay).toBe(0);
    expect((pending[0]?.options as KeyframeAnimationOptions).duration).toBeLessThanOrEqual(600);
    expect(panes.title.style.willChange).toBe('transform, opacity');
    pending.forEach((animation) => animation.complete());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(panes.title.style.willChange).toBe('contents');
    expect(panes.purpose.style.willChange).toBe('');
  });

  it('does not measure the hidden title on initial entry or information-to-information navigation', () => {
    const { panes, transition } = fixture();
    const measure = vi.spyOn(panes.title, 'getBoundingClientRect');
    transition.show('purpose');
    transition.show('capabilities');
    expect(measure).not.toHaveBeenCalled();
    transition.finish();
    expect(panes.purpose.style.willChange).toBe('');
    expect(panes.capabilities.style.willChange).toBe('');
  });

  it('keeps departing scenery inert and removes it after the camera settles', async () => {
    const { panes, pending, transition } = fixture();
    transition.show('title');
    transition.show('purpose');
    expect(panes.title.hidden).toBe(false);
    expect(panes.title.inert).toBe(true);
    expect(panes.title.getAttribute('aria-hidden')).toBe('true');
    expect(panes.purpose.inert).toBe(false);
    pending.forEach((animation) => animation.complete());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(panes.title.hidden).toBe(true);
    expect(panes.purpose.hidden).toBe(false);
  });

  it('cancels interrupted navigation without an old completion hiding the new surface', async () => {
    const { panes, pending, transition } = fixture();
    transition.show('title');
    transition.show('purpose');
    transition.show('capabilities');
    expect(pending[0]?.cancel).toHaveBeenCalledOnce();
    expect(panes.title.hidden).toBe(true);
    pending.forEach((animation) => animation.complete());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(panes.capabilities.hidden).toBe(false);
    expect(panes.purpose.hidden).toBe(true);
    expect(panes.capabilities.inert).toBe(false);
  });

  it('uses only opacity with reduced motion and can settle an in-flight transition', () => {
    const { panes, pending, transition } = fixture(true);
    transition.show('title');
    transition.show('purpose');
    expect(pending.flatMap((animation) => animation.frames).every((frame) =>
      frame.transform === undefined)).toBe(true);
    transition.finish();
    expect(panes.title.hidden).toBe(true);
    expect(panes.purpose.hidden).toBe(false);
  });
});
