/**
 * The routes. Which requests the product makes, and what each answer becomes.
 *
 * Two routes: `GET /graph`, which is the whole world at one state version, and
 * `GET /evidence/{handle}`, which is the original bytes a citation resolves to. That is the
 * entire read surface, and it is short enough to check against the API by eye.
 *
 * The work each answer needs is elsewhere and this file only names it: `wire.ts` says what the
 * server sent, `snapshot.ts` turns that into the read model and records every gap, `islands.ts`
 * says what an island is. The read model did not have to change to make the transport real, which
 * is what the boundary was for.
 */

import { type IslandOf } from './islands.js';
import type { EvidenceHandle, GraphSnapshot, ResolvedEvidence } from './read-model.js';
import type { GraphSource } from './source.js';
import { adaptSnapshot } from './snapshot.js';
import { Transport, type TransportOptions } from './transport.js';
import { type GraphPayload, toMs } from './wire.js';

export interface ClientOptions extends TransportOptions {
  readonly islandOf?: IslandOf;
}

export class ExulanicaClient implements GraphSource {
  readonly #transport: Transport;
  readonly #islandOf: IslandOf | undefined;

  constructor(options: ClientOptions) {
    this.#transport = new Transport(options);
    // Held as the caller's OVERRIDE rather than resolved to a default here, because the default
    // is built from the payload's own grouping and there is no payload yet.
    this.#islandOf = options.islandOf;
  }

  /** The whole graph at one state version. What the index and turn generation run against. */
  async snapshot(): Promise<GraphSnapshot> {
    return adaptSnapshot(
      await this.#transport.getJson<GraphPayload>('/graph'),
      this.#islandOf,
    );
  }

  /**
   * The original media a citation resolves to, as bytes.
   *
   * Bytes rather than a URL, because the bearer token is in a header on every call and an
   * `<img src>` request would not carry it. The two ways to make a plain URL work are to put the
   * token in a query string, where it ends up in a proxy log holding somebody's photographs, or
   * to move authentication into a cookie, which is a session mechanism this API does not have.
   */
  async evidenceBytes(handle: EvidenceHandle): Promise<Blob> {
    // The masked view, not the original. This is the byte path behind the citation image in the
    // detail pane, which is a photograph shown to somebody looking at the screen; the server
    // returns the original when nobody in the frame is hidden, the masked derivative when
    // somebody is, and refuses outright when a mask is required and missing.
    //
    // `/evidence/{handle}` still exists and still resolves the exact bytes a citation names,
    // because those bytes are inside the span digest and an archived citation verifies against
    // them. That endpoint is for resolving evidence; this call is for showing a picture, and
    // until it was pointed here it was the last path by which an unconsented person reached a
    // viewer's screen.
    const response = await this.#transport.getBytes(`/evidence/${handle}/masked`);
    return response.blob();
  }

  /**
   * The `EvidenceResolver` the provenance panel takes.
   *
   * One request per handle, deliberately, rather than a batch endpoint that does not exist. A
   * batch endpoint is worth adding when a panel is measured to need one; adding it now would be
   * adding a route nothing calls.
   */
  async resolve(
    handles: readonly EvidenceHandle[],
  ): Promise<readonly ResolvedEvidence[]> {
    const items = await Promise.all(
      handles.map(async (handle) => {
        const response = await this.#transport.getBytes(`/evidence/${handle}`);
        return {
          handle,
          // The server says which modality this span is; it is not assumed from the shape of
          // the request. A frame region and a whole still image are different citations.
          modality: (response.headers.get('x-exulanica-modality') ??
            'still_image') as ResolvedEvidence['modality'],
          sourceKey: this.#transport.url(`/evidence/${handle}`),
          capturedAtMs: toMs(response.headers.get('x-exulanica-captured-at')),
          capturedAtUncertaintyMs: headerInt(
            response,
            'x-exulanica-captured-at-uncertainty-ms',
          ),
          region: null,
        } as ResolvedEvidence;
      }),
    );
    return items;
  }
}

/** A header carrying a whole number, or null. Absent and unreadable are the same answer here. */
function headerInt(response: Response, name: string): number | null {
  const raw = response.headers.get(name);
  if (raw === null) return null;
  const parsed = Number.parseInt(raw, 10);
  return Number.isNaN(parsed) ? null : parsed;
}
