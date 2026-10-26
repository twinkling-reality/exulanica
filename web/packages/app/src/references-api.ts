/**
 * Web notes for a draft, as the server serves its reference requests (`/worlds/references`;
 * docs/reference-notes-contract.md). A request is the person's words for one draft, sent as at most
 * a few web searches with every saved name replaced; a model writes notes in its own words from what
 * they found, each about one aspect. The notes are drafting input, never world content.
 *
 * - `capability` reads `GET /worlds/references`: whether a request may be made here, and why not by
 *   code; whether the person's own pictures and picture searches are offered; their recent requests.
 * - `request` posts one request; a repeated idempotency key answers the request it first made.
 * - `read` reads one of the caller's own requests: its steps as they happen, then its notes.
 * - `cancel` stops one; a finished one is answered as it stands.
 * - `pictures` reads what one of the caller's picture searches found, while the process holds them;
 *   `keep` keeps the one the person picks, with their answer.
 *
 * A refusal arrives as the transport's error with the server's code. The page reads these and
 * restates none of them; the server decides.
 */
import { Transport, type TransportOptions } from '@exulanica/graph-client';

/** A request ends as one of these; nothing more is asked of it. */
export const REFERENCE_FINISHED = Object.freeze(['complete', 'partial', 'failed', 'cancelled', 'withdrawn'] as const);
/** A request whose notes a drafter may take. */
export const REFERENCE_WITH_NOTES = Object.freeze(['complete', 'partial'] as const);

export type ReferencePurpose = 'world_draft' | 'kind' | 'look' | 'pieces' | 'things';

/** One step of a request as the page reads it: its name, its state and the facts it states (`sent`, `of`, `reason`, ...). */
export interface ReferenceStep {
  readonly step: string;
  /** waiting, running, done, skipped or missed. */
  readonly state: string;
  readonly reason: string | null;
  readonly facts: Readonly<Record<string, unknown>>;
}

/** One note, in the model's own words: the aspect it is about, by the aspect catalog's key, and its basis. */
export interface ReferenceNote {
  readonly aspect: string;
  readonly text: string;
  readonly basis: string;
}

/** Our record of one search: its source, outcome, how many results and the credits it reported. Never the query. */
export interface ReferenceSearch {
  readonly source: string;
  readonly outcome: string;
  readonly resultCount: number | null;
  readonly credits: number | null;
  readonly sentAt: string;
}

export interface ReferenceRequest {
  readonly referenceId: string;
  readonly purpose: string;
  readonly web: boolean;
  readonly status: string;
  readonly steps: readonly ReferenceStep[];
  readonly notes: readonly ReferenceNote[];
  /** The steps the bundle missed. */
  readonly missed: readonly string[];
  readonly failure: string | null;
  readonly searches: readonly ReferenceSearch[];
  readonly bundleSha256: string | null;
  readonly cancelRequested: boolean;
  readonly createdAt: string;
  readonly finishedAt: string | null;
}

/** Whether something is offered here, and why not by code. */
export interface ReferenceOffer {
  readonly offered: boolean;
  readonly code: string | null;
}

export interface ReferenceCapability {
  /** Whether this person may ask for a request here (the capability's state and their permission), and why not. */
  readonly ask: ReferenceOffer;
  /** The person's own pictures: offered, why not, and how many one request may name. */
  readonly pictures: ReferenceOffer & { readonly maximum: number };
  /** Picture searches for a creature: offered, why not, and the most words one holds. */
  readonly webPictures: ReferenceOffer & { readonly words: number };
  /** The caller's recent requests, newest first. */
  readonly requests: readonly ReferenceRequest[];
}

/** A picture a picture search found, shown from its own website. */
export interface HeldPicture {
  readonly n: number;
  readonly address: string;
  readonly website: string;
  readonly description: string | null;
}

export interface HeldPictures {
  readonly referenceId: string;
  readonly pictures: readonly HeldPicture[];
  readonly secondsLeft: number;
}

export type KeepAnswer = 'made_or_permitted' | 'licence_allows' | 'private_world_only';

export interface KeptPicture {
  readonly pictureId: string;
  readonly address: string;
  readonly website: string;
  readonly answer: string;
  readonly licence: string | null;
  readonly referenceId: string | null;
  readonly keptAt: string;
}

type Json = Readonly<Record<string, unknown>>;

const invalid = (where: string): never => { throw new TypeError(`The server returned an invalid ${where}.`); };
const object = (value: unknown, where: string): Json =>
  (typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Json : invalid(where));
const text = (value: unknown, where: string): string => (typeof value === 'string' && value !== '' ? value : invalid(where));
const flag = (value: unknown, where: string): boolean => (typeof value === 'boolean' ? value : invalid(where));
const whole = (value: unknown, where: string): number =>
  (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : invalid(where));
const list = (value: unknown, where: string): readonly unknown[] => (Array.isArray(value) ? value : invalid(where));
const maybe = <T>(value: unknown, read: (present: unknown) => T): T | null =>
  (value === null || value === undefined ? null : read(value));

function step(value: unknown): ReferenceStep {
  const held = object(value, 'reference step');
  const { step: name, state, reason, ...facts } = held;
  return Object.freeze({
    step: text(name, 'reference step name'),
    state: text(state, 'reference step state'),
    reason: maybe(reason, (present) => text(present, 'reference step reason')),
    facts: Object.freeze({ ...facts }),
  });
}

function note(value: unknown): ReferenceNote {
  const held = object(value, 'reference note');
  return Object.freeze({
    aspect: text(held['aspect'], 'reference note aspect'),
    text: text(held['text'], 'reference note'),
    basis: text(held['basis'], 'reference note basis'),
  });
}

function search(value: unknown): ReferenceSearch {
  const held = object(value, 'reference search');
  return Object.freeze({
    source: text(held['source'], 'reference search source'),
    outcome: text(held['outcome'], 'reference search outcome'),
    resultCount: maybe(held['result_count'], (present) => whole(present, 'reference search result count')),
    credits: maybe(held['credits'], (present) => whole(present, 'reference search credits')),
    sentAt: text(held['sent_at'], 'reference search time'),
  });
}

/** One request as the server states it; any other shape is refused. */
export function parseReferenceRequest(value: unknown): ReferenceRequest {
  const held = object(value, 'reference request');
  return Object.freeze({
    referenceId: text(held['reference_id'], 'reference id'),
    purpose: text(held['purpose'], 'reference purpose'),
    web: flag(held['web'], 'reference web'),
    status: text(held['status'], 'reference status'),
    steps: Object.freeze(list(held['steps'], 'reference steps').map(step)),
    notes: Object.freeze(list(held['notes'], 'reference notes').map(note)),
    missed: Object.freeze(list(held['missed'], 'reference missed steps').map((missed) => text(missed, 'reference missed step'))),
    failure: maybe(held['failure'], (present) => text(present, 'reference failure')),
    searches: Object.freeze(list(held['searches'], 'reference searches').map(search)),
    bundleSha256: maybe(held['bundle_sha256'], (present) => text(present, 'reference bundle digest')),
    cancelRequested: flag(held['cancel_requested'], 'reference stop'),
    createdAt: text(held['created_at'], 'reference time'),
    finishedAt: maybe(held['finished_at'], (present) => text(present, 'reference end time')),
  });
}

function offer(value: unknown, where: string): ReferenceOffer {
  const held = object(value, where);
  return { offered: flag(held['offered'], where), code: maybe(held['code'], (present) => text(present, `${where} code`)) };
}

/** The capability read as the server states it: the ask is offered only where its state is available and the person may make it. */
export function parseReferenceCapability(value: unknown): ReferenceCapability {
  const held = object(value, 'references read');
  const capability = object(list(held['capabilities'], 'references capabilities')[0], 'references capability');
  const permitted = flag(capability['permitted'], 'references permission');
  const available = text(capability['state'], 'references capability state') === 'available';
  const pictures = object(held['pictures'], 'pictures offer');
  const webPictures = object(held['web_pictures'], 'picture search offer');
  return Object.freeze({
    ask: Object.freeze({
      offered: permitted && available,
      code: !permitted ? 'references_not_permitted' : maybe(capability['code'], (present) => text(present, 'references capability code')),
    }),
    pictures: Object.freeze({ ...offer(pictures, 'pictures offer'), maximum: whole(pictures['maximum'], 'pictures maximum') }),
    webPictures: Object.freeze({ ...offer(webPictures, 'picture search offer'), words: whole(webPictures['words'], 'picture search words') }),
    requests: Object.freeze(list(held['references'], 'reference requests').map(parseReferenceRequest)),
  });
}

/** What a picture search holds, as the server states it. */
export function parseHeldPictures(value: unknown): HeldPictures {
  const held = object(value, 'held pictures');
  return Object.freeze({
    referenceId: text(held['reference_id'], 'held pictures reference'),
    pictures: Object.freeze(list(held['pictures'], 'held pictures').map((picture) => {
      const one = object(picture, 'held picture');
      return Object.freeze({
        n: whole(one['n'], 'held picture place'),
        address: text(one['address'], 'held picture address'),
        website: text(one['website'], 'held picture website'),
        description: maybe(one['description'], (present) => text(present, 'held picture words')),
      });
    })),
    secondsLeft: whole(held['seconds_left'], 'held pictures time'),
  });
}

export function parseKeptPicture(value: unknown): KeptPicture {
  const held = object(value, 'kept picture');
  return Object.freeze({
    pictureId: text(held['picture_id'], 'kept picture id'),
    address: text(held['address'], 'kept picture address'),
    website: text(held['website'], 'kept picture website'),
    answer: text(held['answer'], 'kept picture answer'),
    licence: maybe(held['licence'], (present) => text(present, 'kept picture licence')),
    referenceId: maybe(held['reference_id'], (present) => text(present, 'kept picture reference')),
    keptAt: text(held['kept_at'], 'kept picture time'),
  });
}

/** Whether a request has ended: nothing more is asked of it. */
export const referenceFinished = (request: ReferenceRequest): boolean =>
  (REFERENCE_FINISHED as readonly string[]).includes(request.status);

/** Whether a finished request's notes may be handed to a drafter: it ended complete or partial, with notes. */
export const referenceHasNotes = (request: ReferenceRequest): boolean =>
  (REFERENCE_WITH_NOTES as readonly string[]).includes(request.status) && request.notes.length > 0;

export class ReferencesClient {
  readonly #transport: Transport;

  constructor(options: TransportOptions) {
    this.#transport = new Transport(options);
  }

  async capability(): Promise<ReferenceCapability> {
    return parseReferenceCapability(await this.#transport.getJson<unknown>('/worlds/references'));
  }

  /** Ask for web notes about `description` for one draft of `purpose`; one key per request, so a retry asks once. */
  async request({ purpose, description, idempotencyKey, webPictures = false }: {
    readonly purpose: ReferencePurpose;
    readonly description: string;
    readonly idempotencyKey: string;
    readonly webPictures?: boolean;
  }): Promise<ReferenceRequest> {
    return parseReferenceRequest(await this.#transport.postJson<unknown>('/worlds/references', {
      purpose, description, web: true, idempotency_key: idempotencyKey, ...(webPictures ? { web_pictures: true } : {}),
    }));
  }

  async read(referenceId: string): Promise<ReferenceRequest> {
    return parseReferenceRequest(await this.#transport.getJson<unknown>(`/worlds/references/${encodeURIComponent(referenceId)}`));
  }

  async cancel(referenceId: string): Promise<ReferenceRequest> {
    return parseReferenceRequest(await this.#transport.postJson<unknown>(`/worlds/references/${encodeURIComponent(referenceId)}/cancel`, {}));
  }

  async pictures(referenceId: string): Promise<HeldPictures> {
    return parseHeldPictures(await this.#transport.getJson<unknown>(`/worlds/references/${encodeURIComponent(referenceId)}/pictures`));
  }

  async keep(referenceId: string, n: number, answer: KeepAnswer, licence: string | null = null): Promise<KeptPicture> {
    return parseKeptPicture(await this.#transport.postJson<unknown>(
      `/worlds/references/${encodeURIComponent(referenceId)}/pictures/${n}/keep`,
      { answer, ...(licence === null ? {} : { licence }) },
    ));
  }
}
