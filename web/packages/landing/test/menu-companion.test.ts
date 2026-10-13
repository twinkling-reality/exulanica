// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { createMenuCompanion } from '../src/ui/menu-companion.js';

afterEach(() => { vi.restoreAllMocks(); document.body.replaceChildren(); });

function scene(reduced = false) {
  const media = new EventTarget() as MediaQueryList;
  Object.defineProperty(media, 'matches', { value: reduced, writable: true });
  vi.spyOn(window, 'matchMedia').mockReturnValue(media);
  const frames = new Map<number, FrameRequestCallback>();
  let id = 0, time = 0;
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => { frames.set(++id, callback); return id; });
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(key => { frames.delete(key); });
  const panel = document.createElement('div');
  const track = document.createElement('div');
  const row = document.createElement('a');
  row.href = '/about';
  panel.append(row, track); document.body.append(panel);
  vi.spyOn(track, 'getBoundingClientRect').mockReturnValue(new DOMRect(200, 100, 28, 140));
  vi.spyOn(row, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 110, 190, 44));
  const companion = createMenuCompanion(panel, [row], 'periwinkle');
  track.append(companion.root);
  const advance = (count: number) => {
    for (let i = 0; i < count; i++) {
      time += 16;
      const pending = [...frames.values()]; frames.clear();
      pending.forEach(callback => callback(time));
    }
  };
  const y = () => Number.parseFloat(companion.root.style.getPropertyValue('--companion-y'));
  return { companion, row, frames, advance, y, media };
}

it('wanders while idle, preserves position when attention changes, then settles beside the row', () => {
  const { companion, row, frames, advance, y } = scene();
  companion.setOpen(true);
  const start = y();
  advance(90);
  expect(y()).not.toBe(start);
  const beforeAttention = y();
  row.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }));
  expect(y()).toBe(beforeAttention);
  advance(1);
  expect(Math.abs(y() - beforeAttention)).toBeLessThan(2);
  advance(150);
  expect(y()).toBeCloseTo(20, 1);
  expect(frames.size).toBe(1);
  companion.setOpen(false);
  expect(frames.size).toBe(0);
});

it('places the companion without an animation loop under reduced motion, including preference changes', () => {
  const { companion, row, frames, y, media } = scene(true);
  companion.setOpen(true);
  row.focus();
  expect(y()).toBe(20);
  expect(frames.size).toBe(0);
  Object.assign(media, { matches: false }); media.dispatchEvent(new Event('change'));
  expect(frames.size).toBe(1);
  Object.assign(media, { matches: true }); media.dispatchEvent(new Event('change'));
  expect(frames.size).toBe(0);
  companion.setOpen(false);
});
