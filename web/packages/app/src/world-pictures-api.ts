// The pictures of a world's History (exulanica/api/routes/world_pictures.py, migration 0221): a
// picture of each moment and a portrait of each look, drawn once by a page and kept by the server.
// A name keeps its first picture; a page that raced another is answered with the one kept, which
// this client returns as if its own were kept, so a caller shows the same picture as every page.
import { ApiError, Transport, toApiError, type TransportOptions } from '@exulanica/graph-client';
import { worldPath } from './world-scope.js';

/** A kept picture as a read serves it: the digest that fetches it, and its size. */
export interface HistoryPicture {
  readonly sha256: string;
  readonly width: number;
  readonly height: number;
}

/** What `GET /world/portraits` answers. */
export const PORTRAITS_PROFILE = 'exulanica.world-look-portraits/v1';
/** The most looks one read asks (LOOKS_ASKED_AT_MOST). */
export const LOOKS_ASKED_AT_MOST = 64;

const DIGEST = /^[0-9a-f]{64}$/;

export function parseHistoryPicture(raw: unknown): HistoryPicture {
  const held = raw as Record<string, unknown> | null;
  const width = held?.['width'], height = held?.['height'], sha256 = held?.['sha256'];
  if (typeof sha256 !== 'string' || !DIGEST.test(sha256) || typeof width !== 'number' || typeof height !== 'number'
    || !Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0) {
    throw new TypeError('The server returned an invalid History picture.');
  }
  return Object.freeze({ sha256, width, height });
}

export class HistoryPicturesClient {
  readonly #transport: Transport;
  readonly #options: TransportOptions;

  constructor(options: TransportOptions) {
    this.#options = options;
    this.#transport = new Transport(options);
  }

  /** The kept portraits of `looks` (look digests) in the world by `recipe`: each, or null. */
  async portraits(worldId: string, looks: readonly string[], recipe: string): Promise<ReadonlyMap<string, HistoryPicture | null>> {
    const asked = [...new Set(looks)];
    if (asked.length === 0) return new Map();
    if (asked.length > LOOKS_ASKED_AT_MOST || asked.some((look) => !DIGEST.test(look))) {
      throw new TypeError(`A portraits read asks 1 to ${LOOKS_ASKED_AT_MOST} look digests.`);
    }
    const body = await this.#transport.getJson<Record<string, unknown>>(
      worldPath('/world/portraits', worldId), { looks: asked.join(','), recipe },
    );
    if (body['profile'] !== PORTRAITS_PROFILE || typeof body['portraits'] !== 'object' || body['portraits'] === null) {
      throw new TypeError('The server returned invalid portraits.');
    }
    const served = body['portraits'] as Record<string, unknown>;
    return new Map(asked.map((look) => [look, served[look] == null ? null : parseHistoryPicture(served[look])]));
  }

  /** A kept History picture's bytes in the world, by its digest (`GET /world/pictures/{sha256}`). */
  async picture(worldId: string, sha256: string): Promise<Blob> {
    const response = await this.#transport.getBytes(worldPath(`/world/pictures/${encodeURIComponent(sha256)}`, worldId));
    return response.blob();
  }

  /** Keep `picture` as the moment's picture by `recipe`; the one kept already if another page was first. */
  async putMomentPicture(
    worldId: string, versionId: string, momentId: string, recipe: string, picture: Blob,
  ): Promise<HistoryPicture> {
    const path = `/world/versions/${encodeURIComponent(versionId)}/history/moments/${encodeURIComponent(momentId)}/picture`;
    return this.#put(path, { world_id: worldId, recipe }, picture);
  }

  /** Keep `picture` as the look's portrait in the world by `recipe`; the one kept already if another page was first. */
  async putPortrait(worldId: string, lookSha256: string, recipe: string, picture: Blob): Promise<HistoryPicture> {
    return this.#put('/world/portraits', { world_id: worldId, look_sha256: lookSha256, recipe }, picture);
  }

  async #put(path: string, query: Record<string, string>, picture: Blob): Promise<HistoryPicture> {
    const url = new URL(`${this.#options.baseUrl.replace(/\/+$/, '')}${path}`);
    for (const [name, value] of Object.entries(query)) url.searchParams.set(name, value);
    // Transport sends JSON only; the body here is the picture itself, typed as it is.
    const headers: Record<string, string> = { 'content-type': picture.type };
    // No bearer header lets the API resolve its account cookie; an empty one would refuse it.
    if (this.#options.token) headers['authorization'] = `Bearer ${this.#options.token}`;
    if (this.#options.csrfToken) headers['x-csrf-token'] = this.#options.csrfToken;
    const response = await (this.#options.fetch ?? globalThis.fetch.bind(globalThis))(url.toString(), {
      method: 'PUT', headers, body: picture, credentials: 'include', signal: this.#options.signal ?? null,
    });
    if (response.ok) return parseHistoryPicture(await response.json());
    const error = await toApiError(response);
    // Another page kept one first: that is the picture every page shows.
    if (error instanceof ApiError && error.code === 'picture_kept' && error.extensions['kept'] !== undefined) {
      return parseHistoryPicture(error.extensions['kept']);
    }
    throw error;
  }
}
