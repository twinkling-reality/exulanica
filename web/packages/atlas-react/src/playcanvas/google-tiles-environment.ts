import * as pc from 'playcanvas';
import { googleGltfMetadata, GoogleAttributionLedger, GoogleAttributionSurface } from './google-tiles-attribution.js';
import type { GoogleTilesConfig } from './google-tiles-config.js';
import {
  googleLocalFrame,
  IDENTITY_MATRIX,
  localTileTransform,
  multiplyMatrices,
  wgs84ToEcef,
  type GoogleLocalFrame,
  type Matrix4,
  type Triple,
} from './google-tiles-frame.js';
import { GoogleTilesProvider } from './google-tiles-provider.js';
import { GoogleTileRequestQueue, GoogleTileResidency } from './google-tiles-residency.js';

interface GoogleTileContent { readonly uri?: unknown; readonly url?: unknown }
interface GoogleBoundingVolume {
  readonly sphere?: unknown;
  readonly box?: unknown;
  readonly region?: unknown;
}
interface GoogleTile {
  readonly boundingVolume?: GoogleBoundingVolume;
  readonly geometricError?: unknown;
  readonly transform?: unknown;
  readonly content?: GoogleTileContent;
  readonly children?: unknown;
}
interface GoogleTileset { readonly root?: unknown }
interface RuntimeTile {
  readonly id: string;
  readonly source: GoogleTile;
  readonly transform: Matrix4;
  readonly children: readonly RuntimeTile[];
  readonly scope?: URL;
  externalRoot?: RuntimeTile;
}
interface LoadedTile<T> {
  readonly handle: T;
  readonly sourceTransform: Matrix4;
  readonly copyright: readonly string[];
}

export interface GoogleTileHost<T> {
  load(id: string, bytes: ArrayBuffer, signal: AbortSignal): Promise<T>;
  setTransform(handle: T, transform: Matrix4): void;
  setVisible(handle: T, visible: boolean): void;
  release(handle: T): void;
}

export interface GoogleTilesAttribution {
  update(visible: boolean, values: readonly string[]): void;
  destroy(): void;
}

export interface GoogleTilesEnvironmentOptions<T> {
  readonly config: GoogleTilesConfig;
  readonly host: GoogleTileHost<T>;
  readonly attribution: GoogleTilesAttribution;
  readonly provider?: GoogleTilesProvider;
  readonly invalidate?: () => void;
  readonly onUnavailable?: () => void;
  readonly maximumTiles?: number;
  readonly maximumResidentBytes?: number;
  readonly concurrency?: number;
}

/**
 * Visualization-only tile traversal. It exposes no picks, rays, geometry,
 * collision or geographic feature results to the rest of the application.
 */
export class GoogleTilesEnvironment<T> {
  readonly frame: GoogleLocalFrame;
  private readonly lifetime = new AbortController();
  private readonly provider: GoogleTilesProvider;
  private readonly queue: GoogleTileRequestQueue;
  private readonly residency: GoogleTileResidency<LoadedTile<T>>;
  private readonly pending = new Map<string, AbortController>();
  private readonly ledger = new GoogleAttributionLedger();
  private root: RuntimeTile | null = null;
  private desired = new Set<string>();
  private unavailable = false;
  private disposed = false;

  constructor(private readonly options: GoogleTilesEnvironmentOptions<T>) {
    this.frame = googleLocalFrame(
      options.config.longitude,
      options.config.latitude,
      options.config.altitude,
    );
    this.provider = options.provider ?? new GoogleTilesProvider(options.config);
    this.queue = new GoogleTileRequestQueue(options.concurrency ?? 6);
    this.residency = new GoogleTileResidency(
      options.maximumTiles ?? 48,
      options.maximumResidentBytes ?? 192 * 1024 * 1024,
      (resident) => {
        this.ledger.remove(this.tileIdForHandle(resident.handle));
        options.host.release(resident.handle);
      },
    );
  }

  async attach(): Promise<void> {
    if (this.disposed || this.root !== null || this.unavailable) return;
    try {
      const value = await this.queue.enqueue(
        (signal) => this.provider.openRoot(signal),
        this.lifetime.signal,
      );
      this.lifetime.signal.throwIfAborted();
      this.root = runtimeTile(parseTileset(value).root, 'root', IDENTITY_MATRIX);
      this.options.invalidate?.();
    } catch {
      if (!this.lifetime.signal.aborted) {
        this.unavailable = true;
        this.options.attribution.update(false, []);
        this.options.onUnavailable?.();
      }
    }
  }

  update(camera: Triple, viewportHeight = 800, fieldOfViewDegrees = 60): void {
    if (this.disposed || this.root === null || this.unavailable) return;
    if (![...camera, viewportHeight, fieldOfViewDegrees].every(Number.isFinite) ||
        viewportHeight <= 0 || fieldOfViewDegrees <= 0 || fieldOfViewDegrees >= 180) {
      throw new Error('Invalid Google tile view');
    }
    const selected = new Map<string, RuntimeTile>();
    try {
      selectTiles(
        this.root,
        camera,
        viewportHeight,
        fieldOfViewDegrees,
        selected,
        this.frame,
        this.residency.maximumTiles,
      );
    } catch {
      this.unavailable = true;
      this.options.attribution.update(false, []);
      this.options.onUnavailable?.();
      return;
    }
    this.desired = new Set(selected.keys());

    for (const [id, controller] of this.pending) {
      if (!this.desired.has(id)) {
        controller.abort();
        this.pending.delete(id);
      }
    }
    this.residency.retain(this.desired);
    for (const [id, tile] of selected) {
      const resident = this.residency.get(id);
      if (resident !== undefined) {
        this.options.host.setTransform(
          resident.handle,
          localTileTransform(this.frame, resident.sourceTransform),
        );
        this.options.host.setVisible(resident.handle, true);
        this.ledger.setVisible(id, resident.copyright, true);
      } else if (!this.pending.has(id)) {
        this.load(tile);
      }
    }
    const values = this.ledger.values();
    this.options.attribution.update(this.residency.size > 0, values);
  }

  private load(tile: RuntimeTile): void {
    const uri = tileUri(tile.source);
    if (uri === null) return;
    const controller = new AbortController();
    this.pending.set(tile.id, controller);
    const signal = AbortSignal.any([this.lifetime.signal, controller.signal]);
    void this.queue.enqueue((requestSignal) =>
      this.provider.fetchContent(uri, requestSignal, tile.scope), signal).then(async (response) => {
      signal.throwIfAborted();
      if (response.contentType.includes('json') || looksLikeJson(response.bytes)) {
        const nested = parseTileset(JSON.parse(new TextDecoder().decode(response.bytes)) as unknown);
        tile.externalRoot = runtimeTile(
          nested.root,
          `${tile.id}/external`,
          tile.transform,
          response.scope,
        );
        this.options.invalidate?.();
        return;
      }
      const metadata = googleGltfMetadata(response.bytes);
      const handle = await this.options.host.load(tile.id, response.bytes, signal);
      if (signal.aborted || this.disposed || !this.desired.has(tile.id)) {
        this.options.host.release(handle);
        return;
      }
      const loaded = Object.freeze({
        handle,
        sourceTransform: tile.transform,
        copyright: metadata.copyright,
      });
      this.rememberHandle(handle, tile.id);
      this.residency.put(tile.id, loaded, response.bytes.byteLength);
      this.options.host.setTransform(handle, localTileTransform(this.frame, tile.transform));
      this.options.host.setVisible(handle, true);
      this.ledger.setVisible(tile.id, metadata.copyright, true);
      this.options.attribution.update(true, this.ledger.values());
      this.options.invalidate?.();
    }).catch(() => {
      if (!signal.aborted) this.options.onUnavailable?.();
    }).finally(() => {
      if (this.pending.get(tile.id) === controller) this.pending.delete(tile.id);
    });
  }

  /*
   * Handles are renderer-owned opaque values. This weak association exists only
   * for teardown attribution and cannot expose provider or geographic identity.
   */
  private readonly handleIds = new Map<T, string>();
  private rememberHandle(handle: T, id: string): void { this.handleIds.set(handle, id); }
  private tileIdForHandle(handle: T): string {
    const id = this.handleIds.get(handle) ?? '';
    this.handleIds.delete(handle);
    return id;
  }

  metrics(): Readonly<Record<string, number | boolean>> {
    return Object.freeze({
      activeRequests: this.queue.activeCount,
      queuedRequests: this.queue.queuedCount,
      residentTiles: this.residency.size,
      residentBytes: this.residency.bytes,
      unavailable: this.unavailable,
    });
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.lifetime.abort();
    for (const controller of this.pending.values()) controller.abort();
    this.pending.clear();
    this.queue.dispose();
    this.residency.clear();
    this.ledger.clear();
    this.options.attribution.update(false, []);
    this.options.attribution.destroy();
    this.root = null;
  }
}

function parseTileset(value: unknown): { readonly root: GoogleTile } {
  if (typeof value !== 'object' || value === null) throw new Error('Invalid Google tileset');
  const root = (value as GoogleTileset).root;
  if (typeof root !== 'object' || root === null) throw new Error('Invalid Google tileset');
  return { root: root as GoogleTile };
}

function parseMatrix(value: unknown): Matrix4 {
  if (value === undefined) return IDENTITY_MATRIX;
  if (!Array.isArray(value) || value.length !== 16 || !value.every(Number.isFinite)) {
    throw new Error('Invalid Google tile transform');
  }
  return value as unknown as Matrix4;
}

function runtimeTile(source: GoogleTile, id: string, parent: Matrix4, scope?: URL): RuntimeTile {
  const transform = multiplyMatrices(parent, parseMatrix(source.transform));
  const children = Array.isArray(source.children) ? source.children.map((value, index) => {
    if (typeof value !== 'object' || value === null) throw new Error('Invalid Google tile');
    return runtimeTile(value as GoogleTile, `${id}/${index}`, transform, scope);
  }) : [];
  return scope === undefined
    ? { id, source, transform, children }
    : { id, source, transform, children, scope };
}

function childrenOf(tile: RuntimeTile): readonly RuntimeTile[] {
  return tile.externalRoot === undefined ? tile.children : [tile.externalRoot];
}

function tileUri(tile: GoogleTile): string | null {
  const value = tile.content?.uri ?? tile.content?.url;
  if (value === undefined) return null;
  if (typeof value !== 'string' || value.length === 0) throw new Error('Invalid Google tile content');
  return value;
}

function looksLikeJson(bytes: ArrayBuffer): boolean {
  const prefix = new TextDecoder().decode(new Uint8Array(bytes, 0, Math.min(bytes.byteLength, 16))).trimStart();
  return prefix.startsWith('{');
}

function transformedPoint(matrix: Matrix4, point: Triple): Triple {
  const x = point[0], y = point[1], z = point[2];
  const w = matrix[3] * x + matrix[7] * y + matrix[11] * z + matrix[15];
  if (!Number.isFinite(w) || w === 0) throw new Error('Invalid Google tile bounds');
  return [
    (matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12]) / w,
    (matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13]) / w,
    (matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14]) / w,
  ];
}

function tileCentreAndRadius(
  tile: RuntimeTile,
  frame: GoogleLocalFrame,
): { readonly centre: Triple; readonly radius: number } | null {
  const sphere = tile.source.boundingVolume?.sphere;
  const box = tile.source.boundingVolume?.box;
  let centre: Triple;
  let radius = 0;
  if (Array.isArray(sphere) && sphere.length === 4 && sphere.every(Number.isFinite)) {
    centre = transformedPoint(tile.transform, [sphere[0], sphere[1], sphere[2]]);
    radius = Math.abs(sphere[3]);
  } else if (Array.isArray(box) && box.length === 12 && box.every(Number.isFinite)) {
    centre = transformedPoint(tile.transform, [box[0], box[1], box[2]]);
    radius = Math.hypot(...box.slice(3));
  } else if (
    Array.isArray(tile.source.boundingVolume?.region) &&
    tile.source.boundingVolume.region.length === 6 &&
    tile.source.boundingVolume.region.every(Number.isFinite)
  ) {
    const [west, south, east, north, minimumHeight, maximumHeight] =
      tile.source.boundingVolume.region;
    if (
      Math.abs(west) > Math.PI ||
      Math.abs(east) > Math.PI ||
      Math.abs(south) > Math.PI / 2 ||
      Math.abs(north) > Math.PI / 2 ||
      south > north ||
      minimumHeight > maximumHeight
    ) {
      throw new Error('Invalid Google tile bounds');
    }
    const longitudeSpan = east >= west ? east - west : east + 2 * Math.PI - west;
    const longitude = west + longitudeSpan / 2;
    const latitude = (south + north) / 2;
    const height = (minimumHeight + maximumHeight) / 2;
    centre = wgs84ToEcef(
      (longitude > Math.PI ? longitude - 2 * Math.PI : longitude) * 180 / Math.PI,
      latitude * 180 / Math.PI,
      height,
    );
    const horizontalRadius = 6_378_137 * Math.hypot(
      longitudeSpan * Math.cos(latitude),
      north - south,
    ) / 2;
    radius = Math.hypot(horizontalRadius, (maximumHeight - minimumHeight) / 2);
  } else {
    return null;
  }
  const local = localTileTransform(frame, [
    1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0,
    centre[0], centre[1], centre[2], 1,
  ]);
  return { centre: [local[12], local[13], local[14]], radius };
}

function tileDistance(tile: RuntimeTile, frame: GoogleLocalFrame, camera: Triple): number {
  const bounds = tileCentreAndRadius(tile, frame);
  if (bounds === null) return 0;
  return Math.max(1, Math.hypot(
    bounds.centre[0] - camera[0],
    bounds.centre[1] - camera[1],
    bounds.centre[2] - camera[2],
  ) - bounds.radius);
}

function tileCentreDistance(tile: RuntimeTile, frame: GoogleLocalFrame, camera: Triple): number {
  const bounds = tileCentreAndRadius(tile, frame);
  if (bounds === null) return Number.POSITIVE_INFINITY;
  return Math.hypot(
    bounds.centre[0] - camera[0],
    bounds.centre[1] - camera[1],
    bounds.centre[2] - camera[2],
  );
}

function selectTiles(
  root: RuntimeTile,
  camera: Triple,
  viewportHeight: number,
  fieldOfViewDegrees: number,
  selected: Map<string, RuntimeTile>,
  frame?: GoogleLocalFrame,
  maximumSelectedTiles = 48,
): void {
  const activeFrame = frame ?? googleLocalFrame(-74.006, 40.7128, 0);
  const queue: RuntimeTile[] = [root];
  let visited = 0;
  while (queue.length > 0 && selected.size < maximumSelectedTiles && visited < 4096) {
    queue.sort((left, right) => {
      const difference = tileCentreDistance(right, activeFrame, camera) -
        tileCentreDistance(left, activeFrame, camera);
      return difference === 0 ? right.id.localeCompare(left.id) : difference;
    });
    const tile = queue.pop()!;
    visited++;
    const children = childrenOf(tile);
    const error = typeof tile.source.geometricError === 'number' &&
      Number.isFinite(tile.source.geometricError) ? tile.source.geometricError : 0;
    const distance = tileDistance(tile, activeFrame, camera);
    const pixels = error * viewportHeight /
      (2 * Math.max(1, distance) * Math.tan(fieldOfViewDegrees * Math.PI / 360));
    if (tile.externalRoot !== undefined || (children.length > 0 && pixels > 16)) {
      // Keep one global camera-distance queue. A depth-first walk can exhaust the
      // residency budget inside a distant sibling before it reaches the viewer.
      queue.push(...children);
    } else if (tileUri(tile.source) !== null) {
      selected.set(tile.id, tile);
    }
  }
}

interface PlayCanvasTileHandle {
  readonly id: string;
  readonly asset: pc.Asset;
  readonly entity: pc.Entity;
}

const PLAYCANVAS_GLTF_TO_ECEF: Matrix4 = [
  1, 0, 0, 0,
  0, 0, 1, 0,
  0, -1, 0, 0,
  0, 0, 0, 1,
];

export function playCanvasGltfTileTransform(transform: Matrix4): Matrix4 {
  return multiplyMatrices(transform, PLAYCANVAS_GLTF_TO_ECEF);
}

export class PlayCanvasGoogleTileHost implements GoogleTileHost<PlayCanvasTileHandle> {
  constructor(
    private readonly app: pc.AppBase,
    private readonly root: pc.Entity,
    private readonly createWrapper: (name: string) => pc.Entity = (name) => new pc.Entity(name),
  ) {}

  async load(id: string, bytes: ArrayBuffer, signal: AbortSignal): Promise<PlayCanvasTileHandle> {
    signal.throwIfAborted();
    const asset = new pc.Asset(`google-tile:${id}`, 'container', {
      url: `google-runtime/${encodeURIComponent(id)}.glb`,
      filename: `${encodeURIComponent(id)}.glb`,
      contents: bytes,
    });
    this.app.assets.add(asset);
    try {
      await new Promise<void>((resolve, reject) => {
        const complete = (): void => { cleanup(); resolve(); };
        const failed = (): void => { cleanup(); reject(new Error('Google tile decode failed')); };
        const aborted = (): void => { cleanup(); reject(new DOMException('Google tile decode cancelled', 'AbortError')); };
        const cleanup = (): void => {
          asset.off('load', complete);
          asset.off('error', failed);
          signal.removeEventListener('abort', aborted);
        };
        asset.once('load', complete);
        asset.once('error', failed);
        signal.addEventListener('abort', aborted, { once: true });
        this.app.assets.load(asset);
        if (signal.aborted) aborted();
      });
      signal.throwIfAborted();
      const content = (asset.resource as pc.ContainerResource).instantiateRenderEntity() as pc.Entity;
      const entity = this.createWrapper(`google-tile:${id}`);
      entity.enabled = false;
      entity.addChild(content);
      this.root.addChild(entity);
      return { id, asset, entity };
    } catch (error) {
      asset.unload();
      this.app.assets.remove(asset);
      throw error;
    }
  }

  setTransform(handle: PlayCanvasTileHandle, transform: Matrix4): void {
    const matrix = new pc.Mat4();
    matrix.set([...playCanvasGltfTileTransform(transform)]);
    handle.entity.setLocalPosition(matrix.getTranslation());
    handle.entity.setLocalEulerAngles(matrix.getEulerAngles());
    handle.entity.setLocalScale(matrix.getScale());
  }

  setVisible(handle: PlayCanvasTileHandle, visible: boolean): void {
    handle.entity.enabled = visible;
  }

  release(handle: PlayCanvasTileHandle): void {
    handle.entity.destroy();
    handle.asset.unload();
    this.app.assets.remove(handle.asset);
  }
}

export function createGoogleTilesEnvironment(
  app: pc.AppBase,
  renderRoot: pc.Entity,
  overlayParent: HTMLElement,
  config: GoogleTilesConfig,
  callbacks: { readonly invalidate: () => void; readonly unavailable: () => void },
): GoogleTilesEnvironment<PlayCanvasTileHandle> {
  const attribution = new GoogleAttributionSurface(overlayParent);
  Object.assign(attribution.root.style, {
    position: 'absolute',
    right: '0.75rem',
    bottom: '0.5rem',
    zIndex: '8',
    maxWidth: 'min(42rem, calc(100% - 1.5rem))',
    padding: '0.25rem 0.45rem',
    borderRadius: '0.25rem',
    color: '#fff',
    background: 'rgba(0, 0, 0, 0.72)',
    font: '11px/1.35 system-ui, sans-serif',
    pointerEvents: 'auto',
  });
  for (const link of Array.from(attribution.root.querySelectorAll('a'))) {
    Object.assign((link as HTMLElement).style, { color: 'inherit', marginLeft: '0.45rem' });
  }
  return new GoogleTilesEnvironment({
    config,
    host: new PlayCanvasGoogleTileHost(app, renderRoot),
    attribution,
    invalidate: callbacks.invalidate,
    onUnavailable: callbacks.unavailable,
  });
}
