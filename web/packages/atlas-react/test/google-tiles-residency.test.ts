import { describe, expect, it, vi } from 'vitest';
import {
  GoogleTileRequestQueue,
  GoogleTileResidency,
} from '../src/playcanvas/google-tiles-residency.js';

describe('Google tile runtime bounds', () => {
  it('bounds concurrency and cancels queued and active work on disposal', async () => {
    const queue = new GoogleTileRequestQueue(2);
    let active = 0;
    let peak = 0;
    const started: number[] = [];
    const jobs = [0, 1, 2, 3].map((id) => queue.enqueue(async (signal) => {
      active++;
      peak = Math.max(peak, active);
      started.push(id);
      await new Promise<void>((_resolve, reject) =>
        signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
      active--;
      return id;
    }, new AbortController().signal));
    await Promise.resolve();
    expect(started).toEqual([0, 1]);
    expect(peak).toBe(2);
    expect(queue.queuedCount).toBe(2);
    queue.dispose();
    await Promise.allSettled(jobs);
    expect(queue.queuedCount).toBe(0);
    expect(queue.activeCount).toBe(0);
  });

  it('evicts least-recent runtime resources by count and bytes', () => {
    const release = vi.fn();
    const residency = new GoogleTileResidency<string>(2, 10, release);
    residency.put('a', 'A', 4);
    residency.put('b', 'B', 4);
    residency.get('a');
    residency.put('c', 'C', 4);
    expect(residency.has('a')).toBe(true);
    expect(residency.has('b')).toBe(false);
    expect(residency.has('c')).toBe(true);
    expect(residency.bytes).toBe(8);
    residency.clear();
    expect(release).toHaveBeenCalledTimes(3);
    expect(residency.size).toBe(0);
  });

  it('rejects a single resource larger than the runtime budget', () => {
    const release = vi.fn();
    const residency = new GoogleTileResidency<string>(2, 10, release);
    expect(() => residency.put('large', 'L', 11)).toThrow('runtime residency budget');
    expect(release).toHaveBeenCalledWith('L');
  });
});
