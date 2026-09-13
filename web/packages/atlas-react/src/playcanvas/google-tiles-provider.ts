import type { GoogleTilesConfig } from './google-tiles-config.js';

export const GOOGLE_TILES_HOST = 'tile.googleapis.com';
export const GOOGLE_TILES_ROOT_PATH = '/v1/3dtiles/root.json';
const GOOGLE_TILES_PATH_PREFIX = '/v1/3dtiles/';
const ALLOWED_QUERY_PARAMETERS = new Set(['key', 'session']);

export interface GoogleTilesResponse {
  readonly bytes: ArrayBuffer;
  readonly contentType: string;
  /** Runtime-only resolution scope. Never log, persist or expose it in UI. */
  readonly scope: URL;
}

export type GoogleTilesFetch = (input: string, init: RequestInit) => Promise<Response>;

export function admitGoogleTilesUrl(value: string | URL): URL {
  const url = value instanceof URL ? new URL(value.href) : new URL(value);
  if (
    url.protocol !== 'https:' ||
    url.hostname !== GOOGLE_TILES_HOST ||
    url.port !== '' ||
    url.username !== '' ||
    url.password !== '' ||
    url.hash !== '' ||
    !url.pathname.startsWith(GOOGLE_TILES_PATH_PREFIX)
  ) {
    throw new Error('Google tile URL rejected');
  }
  for (const key of url.searchParams.keys()) {
    if (!ALLOWED_QUERY_PARAMETERS.has(key)) throw new Error('Google tile URL rejected');
  }
  return url;
}

export function redactedGoogleTilesError(error: unknown): Error {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return new DOMException('Google tile request cancelled', 'AbortError');
  }
  return new Error('Google tile request failed');
}

/**
 * A request-scoped Google session. URLs never leave this object after fetching and
 * failures deliberately contain neither a URL, key, session nor response body.
 */
export class GoogleTilesProvider {
  private session: string | null = null;

  constructor(
    private readonly config: GoogleTilesConfig,
    private readonly fetcher: GoogleTilesFetch = fetch,
    private readonly maximumResponseBytes = 32 * 1024 * 1024,
  ) {
    if (!config.enabled || config.apiKey.length === 0) throw new Error('Google tiles are disabled');
    if (!Number.isSafeInteger(maximumResponseBytes) || maximumResponseBytes < 1) {
      throw new RangeError('Invalid Google tile response budget');
    }
  }

  async openRoot(signal: AbortSignal): Promise<unknown> {
    const root = new URL(`https://${GOOGLE_TILES_HOST}${GOOGLE_TILES_ROOT_PATH}`);
    root.searchParams.set('key', this.config.apiKey);
    const response = await this.request(root, signal);
    if (!response.contentType.includes('json')) throw new Error('Google root tileset unavailable');
    try {
      return JSON.parse(new TextDecoder().decode(response.bytes)) as unknown;
    } catch {
      throw new Error('Google root tileset unavailable');
    }
  }

  async fetchContent(uri: string, signal: AbortSignal, scope?: URL): Promise<GoogleTilesResponse> {
    return this.request(this.resolve(uri, scope), signal);
  }

  private resolve(uri: string, scope?: URL): URL {
    let candidate: URL;
    try {
      candidate = admitGoogleTilesUrl(new URL(
        uri,
        scope ?? `https://${GOOGLE_TILES_HOST}${GOOGLE_TILES_ROOT_PATH}`,
      ));
    } catch {
      throw new Error('Google tile URL rejected');
    }
    const suppliedSession = candidate.searchParams.get('session');
    if (suppliedSession !== null) {
      if (suppliedSession.length === 0 || (this.session !== null && suppliedSession !== this.session)) {
        throw new Error('Google tile URL rejected');
      }
      this.session = suppliedSession;
    } else if (this.session !== null) {
      candidate.searchParams.set('session', this.session);
    }
    candidate.searchParams.set('key', this.config.apiKey);
    return admitGoogleTilesUrl(candidate);
  }

  private async request(url: URL, signal: AbortSignal): Promise<GoogleTilesResponse> {
    signal.throwIfAborted();
    try {
      const response = await this.fetcher.call(globalThis, admitGoogleTilesUrl(url).href, {
        method: 'GET',
        signal,
        credentials: 'omit',
        redirect: 'error',
        referrerPolicy: 'origin',
        cache: 'default',
        headers: { Accept: 'application/json, model/gltf-binary;q=0.9' },
      });
      if (!response.ok || response.redirected) throw new Error();
      const declared = Number(response.headers.get('content-length'));
      if (Number.isFinite(declared) && declared > this.maximumResponseBytes) throw new Error();
      const reader = response.body?.getReader();
      if (reader === undefined) throw new Error();
      const chunks: Uint8Array[] = [];
      let total = 0;
      try {
        while (true) {
          const chunk = await reader.read();
          if (chunk.done) break;
          total += chunk.value.byteLength;
          if (total > this.maximumResponseBytes) throw new Error();
          chunks.push(chunk.value);
        }
      } finally {
        await reader.cancel();
      }
      const bytes = new Uint8Array(total);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
      }
      return Object.freeze({
        bytes: bytes.buffer,
        contentType: response.headers.get('content-type')?.toLowerCase() ?? '',
        scope: new URL(url.href),
      });
    } catch (error) {
      throw redactedGoogleTilesError(error);
    }
  }
}
