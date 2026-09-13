interface QueuedJob<T> {
  readonly controller: AbortController;
  readonly run: (signal: AbortSignal) => Promise<T>;
  readonly resolve: (value: T) => void;
  readonly reject: (reason: unknown) => void;
}

/** Bounded, cancellable runtime work. It has no persistence or speculative scheduler. */
export class GoogleTileRequestQueue {
  private active = 0;
  private readonly waiting: QueuedJob<unknown>[] = [];
  private readonly activeControllers = new Set<AbortController>();
  private disposed = false;

  constructor(readonly concurrency = 6) {
    if (!Number.isSafeInteger(concurrency) || concurrency < 1) {
      throw new RangeError('Invalid Google tile concurrency');
    }
  }

  get activeCount(): number { return this.active; }
  get queuedCount(): number { return this.waiting.length; }

  enqueue<T>(run: (signal: AbortSignal) => Promise<T>, parentSignal: AbortSignal): Promise<T> {
    if (this.disposed) return Promise.reject(new DOMException('Google tile queue disposed', 'AbortError'));
    const controller = new AbortController();
    const abort = (): void => controller.abort();
    parentSignal.addEventListener('abort', abort, { once: true });
    return new Promise<T>((resolve, reject) => {
      const job: QueuedJob<T> = {
        controller,
        run,
        resolve: (value) => {
          parentSignal.removeEventListener('abort', abort);
          resolve(value);
        },
        reject: (reason) => {
          parentSignal.removeEventListener('abort', abort);
          reject(reason);
        },
      };
      this.waiting.push(job as QueuedJob<unknown>);
      controller.signal.addEventListener('abort', () => {
        const index = this.waiting.indexOf(job as QueuedJob<unknown>);
        if (index >= 0) {
          this.waiting.splice(index, 1);
          job.reject(new DOMException('Google tile request cancelled', 'AbortError'));
        }
      }, { once: true });
      if (parentSignal.aborted) controller.abort();
      this.pump();
    });
  }

  private pump(): void {
    while (!this.disposed && this.active < this.concurrency) {
      const job = this.waiting.shift();
      if (job === undefined) return;
      if (job.controller.signal.aborted) continue;
      this.active++;
      this.activeControllers.add(job.controller);
      void job.run(job.controller.signal).then(job.resolve, job.reject).finally(() => {
        this.active--;
        this.activeControllers.delete(job.controller);
        this.pump();
      });
    }
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const job of this.waiting.splice(0)) {
      job.controller.abort();
      job.reject(new DOMException('Google tile queue disposed', 'AbortError'));
    }
    for (const controller of this.activeControllers) controller.abort();
  }
}

interface Resident<T> {
  readonly value: T;
  readonly bytes: number;
  touched: number;
}

/** Runtime-only LRU. Eviction releases the renderer resource immediately. */
export class GoogleTileResidency<T> {
  private readonly entries = new Map<string, Resident<T>>();
  private clock = 0;
  private heldBytes = 0;

  constructor(
    readonly maximumTiles: number,
    readonly maximumBytes: number,
    private readonly release: (value: T) => void,
  ) {
    if (!Number.isSafeInteger(maximumTiles) || maximumTiles < 1 ||
        !Number.isSafeInteger(maximumBytes) || maximumBytes < 1) {
      throw new RangeError('Invalid Google tile residency budget');
    }
  }

  get size(): number { return this.entries.size; }
  get bytes(): number { return this.heldBytes; }
  has(id: string): boolean { return this.entries.has(id); }

  get(id: string): T | undefined {
    const resident = this.entries.get(id);
    if (resident !== undefined) resident.touched = ++this.clock;
    return resident?.value;
  }

  put(id: string, value: T, bytes: number): void {
    if (!Number.isSafeInteger(bytes) || bytes < 0 || bytes > this.maximumBytes) {
      this.release(value);
      throw new Error('Google tile exceeds runtime residency budget');
    }
    this.delete(id);
    this.entries.set(id, { value, bytes, touched: ++this.clock });
    this.heldBytes += bytes;
    this.evict();
  }

  delete(id: string): void {
    const resident = this.entries.get(id);
    if (resident === undefined) return;
    this.entries.delete(id);
    this.heldBytes -= resident.bytes;
    this.release(resident.value);
  }

  retain(ids: ReadonlySet<string>): void {
    for (const id of [...this.entries.keys()]) {
      if (!ids.has(id)) this.delete(id);
    }
  }

  clear(): void {
    for (const id of [...this.entries.keys()]) this.delete(id);
  }

  private evict(): void {
    while (this.entries.size > this.maximumTiles || this.heldBytes > this.maximumBytes) {
      let oldest: [string, Resident<T>] | undefined;
      for (const entry of this.entries) {
        if (oldest === undefined || entry[1].touched < oldest[1].touched) oldest = entry;
      }
      if (oldest === undefined) return;
      this.delete(oldest[0]);
    }
  }
}
