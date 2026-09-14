import { afterEach, describe, expect, it, vi } from 'vitest';
import { createLatestCharacterPreview } from '../src/ui/latest-character-preview.js';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function setup() {
  vi.useFakeTimers();
  const jobs: ReturnType<typeof deferred<string>>[] = [];
  const build = vi.fn(() => { const job = deferred<string>(); jobs.push(job); return job.promise; });
  const ready = vi.fn(), pending = vi.fn(), failed = vi.fn();
  return { jobs, build, ready, pending, failed,
    queue: createLatestCharacterPreview<number, string>({ build, ready, pending, failed }) };
}
afterEach(() => vi.useRealTimers());
describe('automatic character preview', () => {
  it('coalesces slider input and never starts concurrent builds or publishes a stale body', async () => {
    const { queue, build, ready, jobs } = setup();
    queue.request(1); queue.request(2); queue.request(3);
    await vi.advanceTimersByTimeAsync(399);
    expect(build).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(build).toHaveBeenCalledWith(3);
    queue.request(4); queue.request(5);
    await vi.advanceTimersByTimeAsync(400);
    expect(build).toHaveBeenCalledTimes(1);
    jobs[0]!.resolve('old');
    await vi.advanceTimersByTimeAsync(0);
    expect(ready).not.toHaveBeenCalled();
    expect(build).toHaveBeenLastCalledWith(5);
    jobs[1]!.resolve('new');
    await vi.advanceTimersByTimeAsync(0);
    expect(ready).toHaveBeenCalledWith('new');
  });
  it('invalidates an old result immediately, even before the new slider pause has elapsed', async () => {
    const { queue, ready, build, jobs } = setup();
    queue.request(1); await vi.advanceTimersByTimeAsync(400);
    queue.request(2); jobs[0]!.resolve('old');
    await vi.advanceTimersByTimeAsync(0);
    expect(ready).not.toHaveBeenCalled();
    expect(build).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(400);
    expect(build).toHaveBeenLastCalledWith(2);
  });
  it('drops results and queued edits after close or selecting another character, then accepts fresh edits', async () => {
    const { queue, build, ready, failed, jobs } = setup();
    queue.request(1); await vi.advanceTimersByTimeAsync(400);
    queue.request(2); queue.cancel();
    jobs[0]!.reject(new Error('old failure'));
    await vi.advanceTimersByTimeAsync(500);
    expect(build).toHaveBeenCalledTimes(1);
    expect(ready).not.toHaveBeenCalled(); expect(failed).not.toHaveBeenCalled();
    queue.request(3); await vi.advanceTimersByTimeAsync(400);
    jobs[1]!.resolve('fresh'); await vi.advanceTimersByTimeAsync(0);
    expect(ready).toHaveBeenCalledWith('fresh');
    queue.request(4); queue.dispose(); await vi.advanceTimersByTimeAsync(500);
    expect(build).toHaveBeenCalledTimes(2);
  });
  it('reports a current failure and allows the next edit to recover', async () => {
    const { queue, failed, ready, jobs } = setup();
    queue.request(1); await vi.advanceTimersByTimeAsync(400);
    const error = new Error('worker unavailable'); jobs[0]!.reject(error);
    await vi.advanceTimersByTimeAsync(0); expect(failed).toHaveBeenCalledWith(error);
    queue.request(2); await vi.advanceTimersByTimeAsync(400);
    jobs[1]!.resolve('recovered'); await vi.advanceTimersByTimeAsync(0);
    expect(ready).toHaveBeenCalledWith('recovered');
  });
});

it('queues reopened edits behind the outstanding worker request without a second active request', async () => {
  const { queue, build, ready, jobs } = setup();
  queue.request(1); await vi.advanceTimersByTimeAsync(400);
  queue.cancel();
  queue.request(2); await vi.advanceTimersByTimeAsync(400);
  expect(build).toHaveBeenCalledTimes(1);
  jobs[0]!.resolve('closed session'); await vi.advanceTimersByTimeAsync(0);
  expect(ready).not.toHaveBeenCalled();
  expect(build).toHaveBeenLastCalledWith(2);
  jobs[1]!.resolve('reopened session'); await vi.advanceTimersByTimeAsync(0);
  expect(ready).toHaveBeenCalledWith('reopened session');
});
