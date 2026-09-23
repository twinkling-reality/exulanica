/**
 * Opening a citation, which is the promise the whole product reduces to.
 *
 * **Bytes, not a URL.** `ExulanicaClient` answers a citation with bytes and offers no URL to point
 * an element at. The client's own comment says why: the bearer token is in a header on every
 * call and an `<img src>` request would not carry it, so the only ways to make a plain URL work
 * are to put the token in the query string or to move authentication into a cookie. The first
 * puts somebody's photograph library behind a value that ends up in a proxy log. The second is a
 * session mechanism this API does not have. So the bytes are fetched with the header and wrapped
 * in a blob URL.
 *
 * **The cache is keyed by the handle and bounded.** A blob URL holds its bytes alive until it is
 * revoked, so an unbounded cache over a photograph library is a memory leak measured in
 * megabytes per citation. Least-recently-opened is evicted and revoked, and `dispose` revokes
 * everything, because a blob URL that outlives the view holding it is a copy of a photograph in
 * a place the deletion path cannot reach.
 *
 * **A failure is reported, never substituted.** A citation that cannot be resolved renders as a
 * stated failure. A placeholder image in its place would be a claim that the evidence exists and
 * looks like that.
 */

import type { EvidenceHandle } from '@exulanica/graph-client';
import { ApiError } from '@exulanica/graph-client';

/** How many originals are held at once. Each is a few megabytes of decoded photograph. */
const MAX_HELD = 24;

/**
 * What this cache needs, which is one method rather than the whole client.
 *
 * `ExulanicaClient` satisfies it structurally, so nothing at the call site changes. Narrowing it
 * means a test of the caching and eviction rules needs a function returning a blob rather than a
 * transport, and it means this module cannot quietly grow a second reason to hold a client.
 */
export interface EvidenceSource {
  evidenceBytes(handle: EvidenceHandle): Promise<Blob>;
}

export type OpenedEvidence =
  | { readonly ok: true; readonly url: string; readonly type: string }
  | { readonly ok: false; readonly reason: string };

export class EvidenceCache {
  readonly #source: EvidenceSource;
  /** Insertion-ordered, which is what makes the eviction below least-recently-opened. */
  readonly #held = new Map<EvidenceHandle, { url: string; type: string }>();
  /**
   * Reads under way, so opening the same photograph again before the first read lands shares it.
   * Two reads of one handle would make two URLs, and the second would replace the first in `held`
   * where nothing revokes it: the photograph's bytes kept alive for the life of the page.
   */
  readonly #reading = new Map<EvidenceHandle, Promise<OpenedEvidence>>();
  /** Moved on by `dispose`, so a read that lands afterwards makes no URL for its bytes. */
  #generation = 0;

  constructor(source: EvidenceSource) {
    this.#source = source;
  }

  async open(handle: EvidenceHandle): Promise<OpenedEvidence> {
    const existing = this.#held.get(handle);
    if (existing !== undefined) {
      // Re-inserted so it counts as recently opened. Without this the cache evicts by first use
      // rather than by last, and the photograph the user keeps returning to is the one that goes.
      this.#held.delete(handle);
      this.#held.set(handle, existing);
      return { ok: true, url: existing.url, type: existing.type };
    }
    const reading = this.#reading.get(handle);
    if (reading !== undefined) return reading;
    const read = this.#read(handle, this.#generation).finally(() => {
      if (this.#reading.get(handle) === read) this.#reading.delete(handle);
    });
    this.#reading.set(handle, read);
    return read;
  }

  async #read(handle: EvidenceHandle, generation: number): Promise<OpenedEvidence> {
    let blob: Blob;
    try {
      blob = await this.#source.evidenceBytes(handle);
    } catch (error) {
      return { ok: false, reason: describe(error) };
    }
    if (generation !== this.#generation) {
      // The view that asked is gone, so nothing will ever revoke a URL made now.
      return { ok: false, reason: 'the view that asked for this evidence was closed' };
    }

    const entry = { url: URL.createObjectURL(blob), type: blob.type };
    this.#held.set(handle, entry);
    this.#evict();
    return { ok: true, url: entry.url, type: entry.type };
  }

  dispose(): void {
    for (const entry of this.#held.values()) URL.revokeObjectURL(entry.url);
    this.#held.clear();
    this.#reading.clear();
    this.#generation += 1;
  }

  #evict(): void {
    while (this.#held.size > MAX_HELD) {
      const oldest = this.#held.keys().next();
      if (oldest.done === true) return;
      const entry = this.#held.get(oldest.value);
      if (entry !== undefined) URL.revokeObjectURL(entry.url);
      this.#held.delete(oldest.value);
    }
  }
}

/**
 * Why a citation did not open, in the words the API used.
 *
 * The API answers a failure with a code, and the code is the thing worth reporting: a tombstoned
 * address and a missing one are different facts and the user is entitled to the difference. 410
 * in particular means the user deleted it, which is not an error.
 */
function describe(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 410) return 'this evidence was deleted';
    if (error.isNotFound) return 'this evidence is not available to this session';
    if (error.isUnauthenticated) return 'this session is no longer authenticated';
    return `${error.code}: ${error.message}`;
  }
  return error instanceof Error ? error.message : 'the request failed';
}
