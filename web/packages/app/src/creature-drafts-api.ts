/**
 * A creature from a person's words, as the server serves its drafts (`POST /things/creatures`,
 * `GET /things/creatures/drafts`, `/drafts/{draft_id}` and `/offered`; docs/things-contract.md,
 * "Drafting a creature from words").
 *
 * Before anyone types, the offer says whether this workspace may ask here, and why not by code, the
 * model a draft asks first and the most a draft may be charged, how long a draft's calls take by the
 * record its timeout rests on, and every code a draft may end with; every draft says what it spent.
 * The stand read (`GET /world/versions/{id}/society/stand`) says where a creature put down at a
 * point would stand, so the page marks that spot before it is made.
 * A draft is `queued` or `running`, then `kept` (naming the kind made and its sketch, each by digest,
 * and the model that drafted it), `refused` (the check's code, the field and the code's fixed
 * sentence), `failed` or `cancelled` (why, by code), or `erased` (kept, and erased since). The page
 * reads these and restates none of them; the server decides.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';

export const CREATURE_DRAFT_PROFILE = 'exulanica.creature-draft/v1';
export const CREATURE_OFFER_PROFILE = 'exulanica.creature-offer/v1';
export const CREATURE_DRAFTS_PROFILE = 'exulanica.creature-drafts/v1';
export const SOCIETY_STAND_PROFILE = 'exulanica.society-stand/v1';
/** The longest words for one creature: one plain line, as the drafter's form states its own. */
export const CREATURE_WORDS_CHARACTERS = 400;

export type CreatureDraftStatus = 'queued' | 'running' | 'kept' | 'refused' | 'failed' | 'cancelled' | 'erased';
const STATUSES: readonly CreatureDraftStatus[] = ['queued', 'running', 'kept', 'refused', 'failed', 'cancelled', 'erased'];

/** Whether a workspace may ask for a creature here, read before anything is typed. */
export interface CreatureOffer {
  readonly offered: boolean;
  /** Why not, by code; null when it may. */
  readonly code: string | null;
  /** How long one call of the creature drafter takes, from the record its timeout rests on. */
  readonly timing: { readonly typicalSeconds: number; readonly longestSeconds: number; readonly timeoutSeconds: number };
  /** The model a draft asks first, by the name a person reads; null or absent from a server that names none. */
  readonly model?: { readonly modelId: string; readonly name: string | null } | null;
  /** The most one draft may be charged, a decimal string of dollars; null or absent where the server states none. */
  readonly priceUsdAtMost?: string | null;
}

/** Where a being put down at a point would stand: the walking node its society would take it in at. */
export interface SocietyStand {
  readonly nodeId: string;
  /** East and south in the region's frame, millimetres; a node holds no height. */
  readonly positionMm: readonly [number, number];
}

/** A thing's document reference: a key, a version and a digest. */
export interface DocumentReference {
  readonly key: string;
  readonly version: number;
  readonly sha256: string;
}

export interface CreatureDraft {
  readonly draftId: string;
  readonly status: CreatureDraftStatus;
  /** The creature's label once kept, the model's words for it. */
  readonly label: string | null;
  /** The kind made, once kept: placed by its digest alone. */
  readonly kind: DocumentReference | null;
  readonly look: DocumentReference | null;
  readonly model: { readonly modelId: string; readonly name: string | null } | null;
  /** Why it was refused: the code, the field of the drafter's form, and the code's fixed sentence. */
  readonly refusal: { readonly code: string; readonly field: string | null; readonly detail: string } | null;
  /** Why it failed or was cancelled, by code. */
  readonly failure: string | null;
  /** What its calls were charged, a decimal string of dollars, as the server recorded them; null or absent where it records none. */
  readonly spentUsd?: string | null;
  /** How its creature's made look stands once one is asked (`look_job.status`: queued, staged, made, ...); null or absent before. */
  readonly lookStatus?: string | null;
}

type Json = Readonly<Record<string, unknown>>;

function object(value: unknown, where: string): Json {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError(`The server returned an invalid ${where}.`);
  }
  return value as Json;
}

function text(value: unknown, where: string): string {
  if (typeof value !== 'string') throw new TypeError(`The server returned an invalid ${where}.`);
  return value;
}

function whole(value: unknown, where: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new TypeError(`The server returned an invalid ${where}.`);
  }
  return value;
}

const maybe = <T>(value: unknown, read: (present: unknown) => T): T | null =>
  value === null || value === undefined ? null : read(value);

const DIGEST = /^[0-9a-f]{64}$/u;
const DOLLARS = /^\d+\.\d{8}$/u;

function dollars(value: unknown, where: string): string {
  if (typeof value !== 'string' || !DOLLARS.test(value)) throw new TypeError(`The server returned an invalid ${where}.`);
  return value;
}

function model(value: unknown, where: string): { readonly modelId: string; readonly name: string | null } {
  const held = object(value, where);
  return Object.freeze({
    modelId: text(held['model_id'], `${where} id`),
    name: maybe(held['name'], (name) => text(name, `${where} name`)),
  });
}

function reference(value: unknown, field: 'kind' | 'look', where: string): DocumentReference {
  const held = object(value, where);
  const sha256 = text(held['sha256'], `${where} digest`);
  if (!DIGEST.test(sha256)) throw new TypeError(`The server returned an invalid ${where} digest.`);
  return Object.freeze({ key: text(held[field], `${where} key`), version: whole(held['version'], `${where} version`), sha256 });
}

export function parseCreatureOffer(raw: unknown): CreatureOffer {
  const held = object(raw, 'creature offer');
  if (held['profile'] !== CREATURE_OFFER_PROFILE) throw new TypeError('The server returned a creature offer of another profile.');
  if (typeof held['offered'] !== 'boolean') throw new TypeError('The server returned an invalid creature offer.');
  const timing = object(held['timing'], 'creature offer timing');
  return Object.freeze({
    offered: held['offered'],
    code: maybe(held['code'], (code) => text(code, 'creature offer code')),
    timing: Object.freeze({
      typicalSeconds: whole(timing['call_p50_seconds'], 'typical call time'),
      longestSeconds: whole(timing['call_longest_seconds'], 'longest call time'),
      timeoutSeconds: whole(timing['call_timeout_seconds'], 'call timeout'),
    }),
    model: maybe(held['model'], (value) => model(value, 'creature offer model')),
    priceUsdAtMost: maybe(held['price'], (value) => dollars(object(value, 'creature price')['usd_at_most'], 'creature price')),
  });
}

/** The stand read's answer: where to stand, or null where the society has no open walking node there. */
export function parseSocietyStand(raw: unknown): SocietyStand | null {
  const held = object(raw, 'society stand');
  if (held['profile'] !== SOCIETY_STAND_PROFILE) throw new TypeError('The server returned a society stand of another profile.');
  return maybe(held['stand'], (value) => {
    const stand = object(value, 'society stand');
    const position = stand['position_mm'];
    if (!Array.isArray(position) || position.length !== 2 || !position.every(Number.isInteger)) {
      throw new TypeError('The server returned an invalid society stand position.');
    }
    return Object.freeze({ nodeId: text(stand['node_id'], 'society stand node'), positionMm: Object.freeze([position[0], position[1]]) as readonly [number, number] });
  });
}

export function parseCreatureDraft(raw: unknown): CreatureDraft {
  const held = object(raw, 'creature draft');
  if (held['profile'] !== CREATURE_DRAFT_PROFILE) throw new TypeError('The server returned a creature draft of another profile.');
  const status = held['status'];
  if (typeof status !== 'string' || !(STATUSES as readonly string[]).includes(status)) {
    throw new TypeError('The server returned an invalid creature draft status.');
  }
  return Object.freeze({
    draftId: text(held['draft_id'], 'creature draft id'),
    status: status as CreatureDraftStatus,
    label: maybe(held['label'], (value) => text(value, 'creature label')),
    kind: maybe(held['kind'], (value) => reference(value, 'kind', 'creature kind')),
    look: maybe(held['look'], (value) => reference(value, 'look', 'creature look')),
    model: maybe(held['model'], (value) => model(value, 'creature model')),
    refusal: maybe(held['refusal'], (value) => {
      const refusal = object(value, 'creature refusal');
      return Object.freeze({
        code: text(refusal['code'], 'creature refusal code'),
        field: maybe(refusal['field'], (field) => text(field, 'creature refusal field')),
        detail: text(refusal['detail'], 'creature refusal sentence'),
      });
    }),
    failure: maybe(held['failure'], (value) => text(value, 'creature failure code')),
    spentUsd: maybe(held['spend'], (value) => dollars(object(value, 'creature spend')['spent_usd'], 'creature spend')),
    lookStatus: maybe(held['look_job'], (value) => text(object(value, 'creature look job')['status'], 'creature look job status')),
  });
}

/** Whether a draft has ended, kept or not: nothing more is asked of it. */
export const draftEnded = (draft: CreatureDraft): boolean => draft.status !== 'queued' && draft.status !== 'running';

export class CreatureDraftsClient {
  readonly #transport: Transport;

  constructor(options: TransportOptions) {
    this.#transport = new Transport(options);
  }

  async offer(): Promise<CreatureOffer> {
    return parseCreatureOffer(await this.#transport.getJson<unknown>('/things/creatures/offered'));
  }

  /** The caller's drafts, newest first: a reload finds one still running. */
  async drafts(): Promise<readonly CreatureDraft[]> {
    const held = object(await this.#transport.getJson<unknown>('/things/creatures/drafts'), 'creature draft list');
    if (held['profile'] !== CREATURE_DRAFTS_PROFILE) throw new TypeError('The server returned creature drafts of another profile.');
    const drafts = held['drafts'];
    if (!Array.isArray(drafts)) throw new TypeError('The server returned an invalid creature draft list.');
    return Object.freeze(drafts.map(parseCreatureDraft));
  }

  async ask(words: string): Promise<CreatureDraft> {
    return parseCreatureDraft(await this.#transport.postJson<unknown>('/things/creatures', { words }));
  }

  async draft(draftId: string): Promise<CreatureDraft> {
    return parseCreatureDraft(await this.#transport.getJson<unknown>(`/things/creatures/drafts/${encodeURIComponent(draftId)}`));
  }

  /** Where a creature put down at a point of the region's frame would stand in the version's society, or null. */
  async stand(versionId: string, worldId: string, at: { readonly xMm: number; readonly zMm: number }): Promise<SocietyStand | null> {
    const query = new URLSearchParams({ world_id: worldId, x_mm: String(Math.round(at.xMm)), z_mm: String(Math.round(at.zMm)) });
    return parseSocietyStand(await this.#transport.getJson<unknown>(`/world/versions/${encodeURIComponent(versionId)}/society/stand?${query}`));
  }
}
