import type {
  IslandId,
  ResidencyAction,
  ResidencyRequest,
  ResidencyStage,
} from '@exulanica/atlas-core';

export type AssetAvailability =
  | 'available'
  | 'missing'
  | 'unavailable'
  | 'unsupported'
  | 'deleted';

export interface PhysicalAssetDescriptor {
  readonly islandId: IslandId;
  readonly stage: Exclude<ResidencyStage, 'stub'>;
  /** Stable authenticated API path, never a bearer URL. */
  readonly path: string;
  readonly availability: AssetAvailability;
  readonly expectedSha256: string | null;
  readonly expectedBytes: number | null;
  readonly fallback: ResidencyStage;
}

export type RangeOutcome = 'not-requested' | 'partial' | 'ignored';

export interface AssetBytes {
  readonly bytes: ArrayBuffer;
  readonly rangeOutcome: RangeOutcome;
  readonly acceptRanges: boolean;
  readonly contentRange: string | null;
}

export interface ResidencyPhysicalEvent {
  readonly requestId: string;
  readonly islandId: IslandId;
  readonly stage: ResidencyStage;
  readonly state:
    | 'fetching'
    | 'decoding'
    | 'uploading'
    | 'published'
    | 'cancelled'
    | 'stale'
    | 'released'
    | 'missing'
    | 'unavailable'
    | 'unsupported'
    | 'deleted'
    | 'failed'
    | 'context-lost'
    | 'context-restored';
  readonly detail: string | null;
  readonly rangeOutcome: RangeOutcome | null;
}

export interface PhysicalResidencyAdapter<Decoded, Uploaded> {
  fetch(descriptor: PhysicalAssetDescriptor, signal: AbortSignal): Promise<AssetBytes>;
  decode(bytes: ArrayBuffer, descriptor: PhysicalAssetDescriptor): Promise<Decoded> | Decoded;
  upload(decoded: Decoded, descriptor: PhysicalAssetDescriptor): Promise<Uploaded> | Uploaded;
  publish(islandId: IslandId, stage: ResidencyStage, uploaded: Uploaded): void;
  unpublish(islandId: IslandId, uploaded: Uploaded): void;
  disposeDecoded(decoded: Decoded): void;
  disposeUploaded(uploaded: Uploaded): void;
  settle(requestId: string, ok: boolean): void;
  onEvent(event: ResidencyPhysicalEvent): void;
  requireWorldIndex(reason: string): void;
}

interface Resident<Decoded, Uploaded> {
  readonly descriptor: PhysicalAssetDescriptor;
  readonly decoded: Decoded;
  uploaded: Uploaded | null;
}

interface InFlight {
  readonly islandId: IslandId;
  readonly generation: number;
  readonly controller: AbortController;
  readonly task: Promise<void>;
}

const descriptorKey = (islandId: IslandId, stage: ResidencyStage): string => `${islandId}:${stage}`;

/**
 * Executes logical residency actions as cancellable physical work. Publication is the last step,
 * after a generation check; a stale fetch can never become current even when abort arrives late.
 */
export class PhysicalResidencyRuntime<Decoded, Uploaded> {
  readonly #catalog = new Map<string, PhysicalAssetDescriptor>();
  readonly #adapter: PhysicalResidencyAdapter<Decoded, Uploaded>;
  readonly #generation = new Map<IslandId, number>();
  readonly #inFlight = new Map<string, InFlight>();
  readonly #tasks = new Set<Promise<void>>();
  readonly #resident = new Map<IslandId, Resident<Decoded, Uploaded>>();
  #destroyed = false;

  constructor(
    descriptors: readonly PhysicalAssetDescriptor[],
    adapter: PhysicalResidencyAdapter<Decoded, Uploaded>,
  ) {
    this.#adapter = adapter;
    for (const descriptor of descriptors) {
      const key = descriptorKey(descriptor.islandId, descriptor.stage);
      if (this.#catalog.has(key)) throw new TypeError(`duplicate physical residency asset: ${key}`);
      if (!descriptor.path.startsWith('/') || descriptor.path.includes('://')) {
        throw new TypeError('physical asset path must be a local authenticated API path');
      }
      if (
        descriptor.expectedSha256 !== null &&
        !/^[0-9a-f]{64}$/.test(descriptor.expectedSha256)
      ) {
        throw new TypeError('physical asset SHA-256 must be lowercase hexadecimal');
      }
      this.#catalog.set(key, Object.freeze({ ...descriptor }));
    }
  }

  execute(actions: readonly ResidencyAction[]): void {
    if (this.#destroyed) throw new Error('physical residency runtime is destroyed');
    for (const action of actions) {
      if (action.type === 'load') this.#load(action.request);
      else if (action.type === 'cancel') this.#cancel(action.requestId, action.islandId);
      else this.#release(action.islandId, action.to, `release:${action.islandId}:${action.to}`);
    }
  }

  async whenIdle(): Promise<void> {
    while (this.#tasks.size > 0) {
      await Promise.all([...this.#tasks]);
    }
  }

  contextLost(): void {
    if (this.#destroyed) return;
    for (const [requestId, value] of this.#inFlight) this.#cancel(requestId, value.islandId);
    for (const [islandId, resident] of this.#resident) {
      if (resident.uploaded === null) continue;
      this.#adapter.unpublish(islandId, resident.uploaded);
      this.#adapter.disposeUploaded(resident.uploaded);
      resident.uploaded = null;
      this.#event(`context:${islandId}`, islandId, resident.descriptor.stage, 'context-lost', null);
    }
  }

  async contextRestored(): Promise<void> {
    if (this.#destroyed) return;
    try {
      for (const [islandId, resident] of this.#resident) {
        if (resident.uploaded !== null) continue;
        const uploaded = await this.#adapter.upload(resident.decoded, resident.descriptor);
        if (this.#destroyed || this.#resident.get(islandId) !== resident) {
          this.#adapter.disposeUploaded(uploaded);
          continue;
        }
        resident.uploaded = uploaded;
        this.#adapter.publish(islandId, resident.descriptor.stage, uploaded);
        this.#event(
          `context:${islandId}`,
          islandId,
          resident.descriptor.stage,
          'context-restored',
          null,
        );
      }
    } catch (error) {
      this.#adapter.requireWorldIndex(
        `renderer resources could not be restored: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }

  destroy(): void {
    if (this.#destroyed) return;
    this.#destroyed = true;
    for (const [requestId, value] of this.#inFlight) this.#cancel(requestId, value.islandId);
    for (const [islandId, resident] of this.#resident) {
      if (resident.uploaded !== null) {
        this.#adapter.unpublish(islandId, resident.uploaded);
        this.#adapter.disposeUploaded(resident.uploaded);
      }
      this.#adapter.disposeDecoded(resident.decoded);
    }
    this.#resident.clear();
  }

  #load(request: ResidencyRequest): void {
    const descriptor = this.#catalog.get(descriptorKey(request.islandId, request.to));
    if (descriptor === undefined) {
      this.#event(request.requestId, request.islandId, request.to, 'missing', 'no published asset');
      this.#adapter.settle(request.requestId, false);
      return;
    }
    if (descriptor.availability !== 'available') {
      this.#event(
        request.requestId,
        request.islandId,
        request.to,
        descriptor.availability,
        `honest fallback to ${descriptor.fallback}`,
      );
      this.#adapter.settle(request.requestId, false);
      return;
    }
    const generation = (this.#generation.get(request.islandId) ?? 0) + 1;
    this.#generation.set(request.islandId, generation);
    const controller = new AbortController();
    const task = this.#runLoad(request, descriptor, generation, controller.signal).finally(() => {
      this.#tasks.delete(task);
      const active = this.#inFlight.get(request.requestId);
      if (active?.generation === generation) this.#inFlight.delete(request.requestId);
    });
    this.#tasks.add(task);
    this.#inFlight.set(request.requestId, {
      islandId: request.islandId,
      generation,
      controller,
      task,
    });
  }

  async #runLoad(
    request: ResidencyRequest,
    descriptor: PhysicalAssetDescriptor,
    generation: number,
    signal: AbortSignal,
  ): Promise<void> {
    let decoded: Decoded | null = null;
    let uploaded: Uploaded | null = null;
    try {
      this.#event(request.requestId, request.islandId, request.to, 'fetching', null);
      const fetched = await this.#adapter.fetch(descriptor, signal);
      if (!this.#current(request, generation)) {
        this.#event(request.requestId, request.islandId, request.to, 'stale', null, fetched.rangeOutcome);
        return;
      }
      if (descriptor.expectedBytes !== null && fetched.bytes.byteLength !== descriptor.expectedBytes) {
        throw new Error(
          `asset length ${fetched.bytes.byteLength} does not match ${descriptor.expectedBytes}`,
        );
      }
      this.#event(
        request.requestId,
        request.islandId,
        request.to,
        'decoding',
        null,
        fetched.rangeOutcome,
      );
      decoded = await this.#adapter.decode(fetched.bytes, descriptor);
      if (!this.#current(request, generation)) {
        this.#adapter.disposeDecoded(decoded);
        decoded = null;
        this.#event(request.requestId, request.islandId, request.to, 'stale', null);
        return;
      }
      this.#event(request.requestId, request.islandId, request.to, 'uploading', null);
      uploaded = await this.#adapter.upload(decoded, descriptor);
      if (!this.#current(request, generation)) {
        this.#adapter.disposeUploaded(uploaded);
        this.#adapter.disposeDecoded(decoded);
        uploaded = null;
        decoded = null;
        this.#event(request.requestId, request.islandId, request.to, 'stale', null);
        return;
      }
      const prior = this.#resident.get(request.islandId);
      this.#adapter.publish(request.islandId, request.to, uploaded);
      this.#resident.set(request.islandId, { descriptor, decoded, uploaded });
      decoded = null;
      uploaded = null;
      if (prior !== undefined) this.#disposeResident(request.islandId, prior);
      this.#event(request.requestId, request.islandId, request.to, 'published', null);
      this.#adapter.settle(request.requestId, true);
    } catch (error) {
      if (uploaded !== null) this.#adapter.disposeUploaded(uploaded);
      if (decoded !== null) this.#adapter.disposeDecoded(decoded);
      const cancelled = signal.aborted || !this.#current(request, generation);
      this.#event(
        request.requestId,
        request.islandId,
        request.to,
        cancelled ? 'cancelled' : 'failed',
        cancelled ? null : error instanceof Error ? error.message : String(error),
      );
      if (!cancelled) this.#adapter.settle(request.requestId, false);
    }
  }

  #current(request: ResidencyRequest, generation: number): boolean {
    return !this.#destroyed &&
      this.#generation.get(request.islandId) === generation &&
      this.#inFlight.get(request.requestId)?.generation === generation;
  }

  #cancel(requestId: string, islandId: IslandId): void {
    const active = this.#inFlight.get(requestId);
    if (active === undefined) return;
    active.controller.abort();
    this.#generation.set(islandId, active.generation + 1);
    this.#inFlight.delete(requestId);
    this.#event(requestId, islandId, 'stub', 'cancelled', null);
    this.#adapter.settle(requestId, false);
  }

  #release(islandId: IslandId, to: ResidencyStage, requestId: string): void {
    for (const [id, value] of this.#inFlight) {
      if (value.islandId === islandId) this.#cancel(id, islandId);
    }
    const resident = this.#resident.get(islandId);
    if (resident === undefined) return;
    this.#resident.delete(islandId);
    this.#disposeResident(islandId, resident);
    this.#event(requestId, islandId, to, 'released', null);
  }

  #disposeResident(islandId: IslandId, resident: Resident<Decoded, Uploaded>): void {
    if (resident.uploaded !== null) {
      this.#adapter.unpublish(islandId, resident.uploaded);
      this.#adapter.disposeUploaded(resident.uploaded);
    }
    this.#adapter.disposeDecoded(resident.decoded);
  }

  #event(
    requestId: string,
    islandId: IslandId,
    stage: ResidencyStage,
    state: ResidencyPhysicalEvent['state'],
    detail: string | null,
    rangeOutcome: RangeOutcome | null = null,
  ): void {
    this.#adapter.onEvent(Object.freeze({
      requestId, islandId, stage, state, detail, rangeOutcome,
    }));
  }
}

export interface AuthenticatedAssetFetchOptions {
  readonly baseUrl: string;
  readonly token: string;
  readonly fetch?: typeof globalThis.fetch;
  readonly range?: readonly [start: number, end: number];
}

/** Authenticated fetch with observed, not assumed, Range behavior and optional integrity check. */
export async function fetchAuthenticatedAsset(
  descriptor: PhysicalAssetDescriptor,
  signal: AbortSignal,
  options: AuthenticatedAssetFetchOptions,
): Promise<AssetBytes> {
  const base = options.baseUrl.replace(/\/+$/, '');
  const headers: Record<string, string> = {};
  // An explicit empty bearer is not the absence of a bearer. The API correctly refuses it and
  // never falls back to an account cookie, so account sessions must omit this header entirely.
  if (options.token) headers['authorization'] = `Bearer ${options.token}`;
  if (options.range !== undefined) {
    headers['range'] = `bytes=${options.range[0]}-${options.range[1]}`;
  }
  const response = await (options.fetch ?? globalThis.fetch.bind(globalThis))(
    `${base}${descriptor.path}`,
    { method: 'GET', headers, signal, credentials: 'include' },
  );
  if (!response.ok) throw new Error(`asset fetch failed with HTTP ${response.status}`);
  const bytes = await response.arrayBuffer();
  if (descriptor.expectedSha256 !== null) {
    const digest = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes));
    const actual = [...digest].map((value) => value.toString(16).padStart(2, '0')).join('');
    if (actual !== descriptor.expectedSha256) throw new Error('asset SHA-256 does not match');
  }
  const contentRange = response.headers.get('content-range');
  return Object.freeze({
    bytes,
    rangeOutcome: options.range === undefined
      ? 'not-requested'
      : response.status === 206 && contentRange !== null
        ? 'partial'
        : 'ignored',
    acceptRanges: response.headers.get('accept-ranges')?.toLowerCase() === 'bytes',
    contentRange,
  });
}
