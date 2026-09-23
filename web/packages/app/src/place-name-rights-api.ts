/**
 * Where a place's saved name may go: the browser's half of `/place-name-rights`.
 *
 * A place's name reaches a hosted model only while the person who named it allows that use, asked
 * for each place. The server owns every word of it. Each use arrives with the exact notice the
 * person reads, and allowing sends that notice back unchanged: the server compares it with the
 * text it states now and refuses a grant against anything else, so this client cannot record a
 * decision about words nobody was shown. Nothing here composes a notice, names a model or decides
 * a state; it reads them, checks that they are what the server is known to send, and relays a
 * decision.
 *
 * **A state this client does not know is refused, not guessed.** Showing "allowed" for a state
 * added later would tell a person their name is going somewhere when it may not be, and showing
 * "not allowed" could hide that it is. Either is worse than saying the answer could not be read.
 */

import { ApiError, Transport, type TransportOptions } from '@exulanica/graph-client';

const PLACE_NAME_TIMEOUT_MS = 20_000;

/** What one model of a use means now. Mirrors `exulanica.consent.place_names.ModelState`. */
export type PlaceNameModelState =
  | 'allowed'
  | 'not_allowed'
  | 'withdrawn'
  | 'ended'
  | 'name_changed'
  | 'notice_changed';

/** What a use means now: a model state, or `models_changed`. Mirrors `UseState`. */
export type PlaceNameUseState = PlaceNameModelState | 'models_changed';

const USE_STATES: readonly PlaceNameUseState[] = [
  'allowed',
  'not_allowed',
  'withdrawn',
  'ended',
  'name_changed',
  'notice_changed',
  'models_changed',
];

export interface PlaceNameModel {
  readonly modelId: string;
  readonly provider: string;
  readonly role: string;
  readonly revision: string | null;
  readonly state: PlaceNameModelState;
}

export interface PlaceNameUse {
  /** The use's key, which is the model role it names. Sent back to allow or stop it. */
  readonly use: string;
  /** What the product asks this use's models to do, in the server's words. */
  readonly purpose: string;
  /** The exact words a person reads before allowing this use. Sent back verbatim to allow it. */
  readonly notice: string;
  /** The origin the name would travel to. */
  readonly destination: string;
  readonly models: readonly PlaceNameModel[];
  readonly state: PlaceNameUseState;
  readonly allowed: boolean;
  readonly since: string | null;
  readonly until: string | null;
  readonly changedAt: string | null;
}

export interface PlaceNameRights {
  readonly entityId: string;
  /** The place's current name. Null for a place that is unnamed, merged or deleted. */
  readonly name: string | null;
  readonly uses: readonly PlaceNameUse[];
}

/** The ways a request can fail that a person can act on, each said in words by the surface. */
export type PlaceNameFailure =
  | 'missing'
  | 'forbidden'
  | 'notice_changed'
  | 'not_yours'
  | 'unnamed'
  | 'not_offered'
  | 'busy'
  | 'unreadable'
  | 'unreachable';

export class PlaceNameUnavailable extends Error {
  constructor(
    readonly kind: PlaceNameFailure,
    readonly detail: string,
  ) {
    super(detail);
    this.name = 'PlaceNameUnavailable';
  }
}

/** The server's refusal codes that are also kinds here; any other 409 is unreadable to this client. */
const REFUSALS: ReadonlySet<string> = new Set([
  'notice_changed',
  'not_yours',
  'unnamed',
  'not_offered',
  'busy',
]);

function asUnavailable(error: unknown): PlaceNameUnavailable {
  if (error instanceof PlaceNameUnavailable) return error;
  if (error instanceof ApiError) {
    const detail = error.message;
    if (error.status === 404) return new PlaceNameUnavailable('missing', detail);
    if (error.status === 401 || error.status === 403) {
      return new PlaceNameUnavailable('forbidden', detail);
    }
    if (error.status === 409 && REFUSALS.has(error.code)) {
      return new PlaceNameUnavailable(error.code as PlaceNameFailure, detail);
    }
    return new PlaceNameUnavailable('unreadable', detail);
  }
  return new PlaceNameUnavailable('unreachable', 'The request did not reach Exulanica.');
}

interface WireModel {
  readonly model: {
    readonly provider: string;
    readonly role: string;
    readonly model_id: string;
    readonly revision: string | null;
  };
  readonly state: string;
}

interface WireUse {
  readonly use: string;
  readonly purpose: string;
  readonly notice: string;
  readonly destination: string;
  readonly models: readonly WireModel[];
  readonly state: string;
  readonly allowed: boolean;
  readonly since: string | null;
  readonly until: string | null;
  readonly changed_at: string | null;
}

interface WireRights {
  readonly entity_id: string;
  readonly name: string | null;
  readonly uses: readonly WireUse[];
}

function known(state: string): PlaceNameUseState {
  if (!(USE_STATES as readonly string[]).includes(state)) {
    throw new PlaceNameUnavailable('unreadable', `an unknown place name state: ${state}`);
  }
  return state as PlaceNameUseState;
}

/** The wire's words renamed, every state checked, and the result frozen. */
export function rightsOf(wire: WireRights): PlaceNameRights {
  return Object.freeze({
    entityId: wire.entity_id,
    name: wire.name,
    uses: Object.freeze(wire.uses.map((use): PlaceNameUse => {
      const state = known(use.state);
      if (use.allowed !== (state === 'allowed')) {
        throw new PlaceNameUnavailable('unreadable', 'a use says it is allowed and is not');
      }
      return Object.freeze({
        use: use.use,
        purpose: use.purpose,
        notice: use.notice,
        destination: use.destination,
        models: Object.freeze(use.models.map((model): PlaceNameModel => {
          const modelState = known(model.state);
          if (modelState === 'models_changed') {
            throw new PlaceNameUnavailable('unreadable', 'a model state names a whole use');
          }
          return Object.freeze({
            modelId: model.model.model_id,
            provider: model.model.provider,
            role: model.model.role,
            revision: model.model.revision,
            state: modelState,
          });
        })),
        state,
        allowed: use.allowed,
        since: use.since,
        until: use.until,
        changedAt: use.changed_at,
      });
    })),
  });
}

/** Everything the control needs from the server, and nothing it could decide by itself. */
export interface PlaceNameRightsSource {
  load(entityId: string): Promise<PlaceNameRights>;
  allow(entityId: string, use: string, notice: string): Promise<PlaceNameRights>;
  stop(entityId: string, use: string): Promise<PlaceNameRights>;
}

export class PlaceNameRightsClient implements PlaceNameRightsSource {
  readonly #options: TransportOptions;

  constructor(options: TransportOptions) {
    // `signal` is dropped: each request sets its own deadline, built per request, because a
    // signal made once would start counting at construction and expire every later request.
    const { signal: _unused, ...rest } = options;
    this.#options = rest;
  }

  #transport(): Transport {
    return new Transport({ ...this.#options, signal: AbortSignal.timeout(PLACE_NAME_TIMEOUT_MS) });
  }

  async load(entityId: string): Promise<PlaceNameRights> {
    try {
      return rightsOf(await this.#transport().getJson<WireRights>(this.#path(entityId)));
    } catch (error) {
      throw asUnavailable(error);
    }
  }

  async allow(entityId: string, use: string, notice: string): Promise<PlaceNameRights> {
    try {
      return rightsOf(await this.#transport().postJson<WireRights>(
        `${this.#path(entityId)}/grants`,
        { use, notice },
      ));
    } catch (error) {
      throw asUnavailable(error);
    }
  }

  async stop(entityId: string, use: string): Promise<PlaceNameRights> {
    try {
      return rightsOf(await this.#transport().postJson<WireRights>(
        `${this.#path(entityId)}/withdrawals`,
        { use },
      ));
    } catch (error) {
      throw asUnavailable(error);
    }
  }

  #path(entityId: string): string {
    return `/place-name-rights/${encodeURIComponent(entityId)}`;
  }
}
