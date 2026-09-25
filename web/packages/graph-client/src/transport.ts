/**
 * The HTTP transport. One place that knows the API exists, and one place that knows what a
 * failure means.
 *
 * Everything else in this package works on the read model, which is why this file is small and
 * why it is separate: `companion-runtime` and `world-index` build against types, not against
 * fetch, and a test of either needs no server.
 *
 * Three properties worth naming, because each is a decision rather than a default.
 *
 * **A failure carries its code, not its status.** The API answers every failure with
 * `{code, detail}`, and the code is the thing worth branching on: `unknown_reference` means the
 * same thing whether it arrived as a 404 from the evidence route or from an identity commit.
 * Callers that switch on a number end up encoding the router. A problem with more to say carries
 * further members, which `ApiError.extensions` keeps for the caller that knows them.
 *
 * **404 is not an error class of its own.** The API returns 404 for 'not there' and for "not
 * yours", deliberately and identically, so that the surface is not an existence oracle. A client
 * that distinguished them would be reconstructing the oracle the server refuses to be.
 *
 * **The bearer token is held here and nowhere else.** It is not on the read model, not on a
 * snapshot and not in a URL. A token in a query string ends up in a proxy log, and the corpus it
 * unlocks is somebody's photographs.
 */

/** The failure shape every route in the API answers with. */
export interface ApiProblem {
  readonly code: string;
  readonly detail: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    detail: string,
    /**
     * Every other member of the problem body, as the server sent it (RFC 9457 extension
     * members), such as the execution record of a Companion question a model error ended. Data
     * for a caller that knows the member, never a replacement for `code`.
     */
    readonly extensions: Readonly<Record<string, unknown>> = {},
  ) {
    super(`${code}: ${detail}`);
    this.name = 'ApiError';
  }

  /** True when the server declined to say whether the thing exists. See the module comment. */
  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isUnauthenticated(): boolean {
    return this.status === 401;
  }
}

export interface TransportOptions {
  readonly baseUrl: string;
  readonly token: string;
  /** Present only for an authenticated browser account session. Never persisted by this client. */
  readonly csrfToken?: string;
  /** Injectable so a test drives this without a server and without a global. */
  readonly fetch?: typeof globalThis.fetch;
  readonly signal?: AbortSignal;
}

export class Transport {
  readonly #baseUrl: string;
  readonly #token: string;
  readonly #csrfToken: string | undefined;
  readonly #fetch: typeof globalThis.fetch;
  readonly #signal: AbortSignal | undefined;

  constructor(options: TransportOptions) {
    // Trailing slashes are stripped once here rather than guarded at every call site.
    this.#baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.#token = options.token;
    this.#csrfToken = options.csrfToken;
    this.#fetch = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.#signal = options.signal;
  }

  async getJson<T>(path: string, query?: Record<string, string>): Promise<T> {
    const response = await this.#request('GET', path, query === undefined ? {} : { query });
    return (await response.json()) as T;
  }

  async postJson<T>(path: string, body: unknown): Promise<T> {
    const response = await this.#request('POST', path, { body });
    return (await response.json()) as T;
  }

  async putJson<T>(path: string, body: unknown): Promise<T> {
    const response = await this.#request('PUT', path, { body });
    return (await response.json()) as T;
  }

  /** Successful DELETE routes may deliberately return no response body. */
  async delete(path: string): Promise<void> {
    await this.#request('DELETE', path, {});
  }

  /**
   * Raw bytes, for evidence. Returns the response rather than the body so a caller can read the
   * content type, and so a large original can be streamed rather than buffered.
   */
  async getBytes(path: string, query?: Record<string, string>): Promise<Response> {
    return this.#request('GET', path, query === undefined ? {} : { query });
  }

  /**
   * Where a resource lives, as a string. Used to make the request below, and read once as a
   * label: `ResolvedEvidence.sourceKey` is the one caller outside `#request` and it says where an
   * original came from rather than being fetched. Nothing loads bytes from this string, and
   * nothing can: an `<img src>` pointed at one would arrive without the bearer header, which is
   * why evidence is read as bytes through `getBytes`.
   */
  url(path: string, query?: Record<string, string>): string {
    const url = new URL(`${this.#baseUrl}${path}`);
    for (const [key, value] of Object.entries(query ?? {})) url.searchParams.set(key, value);
    return url.toString();
  }

  async #request(
    method: string,
    path: string,
    options: { query?: Record<string, string>; body?: unknown },
  ): Promise<Response> {
    const url = this.url(path, options.query);
    const headers: Record<string, string> = {};
    // No bearer header permits the API to resolve its HttpOnly account cookie. Sending an
    // explicit empty bearer would correctly fail closed and prevent that cookie fallback.
    if (this.#token) headers['authorization'] = `Bearer ${this.#token}`;
    if (this.#csrfToken && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      headers['x-csrf-token'] = this.#csrfToken;
    }
    if (options.body !== undefined) headers['content-type'] = 'application/json';

    // Built up rather than declared with undefined members: `exactOptionalPropertyTypes` is on,
    // and a present-but-undefined body is not the same thing as an absent one.
    const init: RequestInit = {
      method, headers, signal: this.#signal ?? null, credentials: 'include',
    };
    if (options.body !== undefined) init.body = JSON.stringify(options.body);

    const response = await this.#fetch(url, init);
    if (response.ok) return response;
    throw await toApiError(response);
  }
}

/**
 * Turn a failed response into an `ApiError`, without trusting it to be JSON.
 *
 * A proxy, a gateway timeout or a crashed worker answers with HTML or with nothing, and a client
 * that assumed JSON would fail while reporting the failure. The status is always known, so it is
 * always reported, and the code degrades to a synthetic one rather than throwing a second error
 * on top of the first.
 */
export async function toApiError(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`;
  let detail = response.statusText || 'the request failed';
  let extensions: Record<string, unknown> = {};
  try {
    const body = (await response.json()) as Partial<ApiProblem> & Record<string, unknown>;
    if (typeof body.code === 'string') code = body.code;
    if (typeof body.detail === 'string') detail = body.detail;
    if (body !== null && typeof body === 'object' && !Array.isArray(body)) {
      const { code: _code, detail: _detail, ...rest } = body;
      extensions = rest;
    }
  } catch {
    // Not JSON. The status and statusText above are what there is, and they are enough to act on.
  }
  return new ApiError(response.status, code, detail, extensions);
}
