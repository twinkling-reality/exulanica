/**
 * The kinds of place a world can be made of, and a kind drafted from a person's words, as the
 * server serves them (`GET /worlds/kinds` and `/worlds/kinds/drafts`; docs/world-kinds-contract.md,
 * "Storage and routes" and "A kind drafted from words"). Making a world of a kind is the saved
 * entries client's `makeOfKind`.
 *
 * The library lists the town, the kinds the product ships and the workspace's own, each with what
 * a person may change, and whether this caller may draft a new kind of place here (`drafting`,
 * optional: absent from a server that predates it, which then offers no drafting). A draft is
 * `drafting`, `ready` with the kept kind, or `refused` by name. The page reads these and restates
 * none of them; the server decides.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import townAdapterText from '../../../../assets/catalogs/world-kinds/library/town.v1.json?raw';

export const KINDS_PROFILE = 'exulanica.world-kinds/v1';

/**
 * The town's key in the library, read from the adapter the server lists it through: its presets
 * are the specification's, which the recipe cards already offer.
 */
export const TOWN_KIND: string = (JSON.parse(townAdapterText) as { kind: string }).kind;

/**
 * The longest description the kind drafter reads: the ceiling its prompt document states
 * (`exulanica/selection/kind-drafting.v*.json`, the one `kind_drafting.py` names), which
 * `world-kinds.test.ts` holds this to.
 */
export const KIND_DESCRIPTION_CHARACTERS = 1000;

/** A value a person may change in a kind: a number's range and step, or a key's choices. */
export interface KindParameter {
  readonly key: string;
  readonly label: string;
  readonly minimum: number | null;
  readonly maximum: number | null;
  readonly step: number | null;
  readonly choices: readonly string[] | null;
  readonly reason: string;
}

export interface KindPreset {
  readonly key: string;
  readonly label: string;
  readonly values: Readonly<Record<string, number | string>>;
}

export interface KindPart {
  readonly key: string;
  readonly label: string;
  readonly description: string;
}

/** One kind of place, in the words the server states. */
export interface WorldKind {
  readonly kind: string;
  readonly version: number;
  readonly sha256: string;
  readonly source: 'shipped' | 'workspace';
  readonly label: string;
  readonly summary: string;
  /** `authored`, `drafted`, `uploaded` or `imported`. */
  readonly origin: string;
  readonly parameters: readonly KindParameter[];
  readonly presets: readonly KindPreset[];
  readonly parts: readonly KindPart[];
}

export interface KindRefusal {
  readonly code: string;
  readonly meaning: string;
}

/** Whether this caller may draft a kind of place here, read before anything is typed. */
export interface KindDrafting {
  readonly offered: boolean;
  readonly code: string | null;
  /** Every code a draft's routes and its job answer with, each with its meaning. */
  readonly refusals: readonly KindRefusal[];
}

export interface KindLibrary {
  readonly kinds: readonly WorldKind[];
  /** Null where the server predates drafting: nothing is offered. */
  readonly drafting: KindDrafting | null;
}

export interface KindDraft {
  readonly draftId: string;
  readonly state: 'drafting' | 'ready' | 'refused';
  /** The words, held by the server only while it drafts; empty once it ended. */
  readonly description: string;
  readonly elapsedSeconds: number;
  /** When to ask again while drafting; null once it ended. */
  readonly pollAfterSeconds: number | null;
  readonly kind: WorldKind | null;
  /**
   * Why it ended without a kind: its code, its words, and the check that refused the drafted kind,
   * or null where no check did (the detail is then the drafter's own sentence).
   */
  readonly refusal: { readonly code: string; readonly detail: string; readonly check: string | null } | null;
  /** The drafting model's served name, never its identifier. */
  readonly modelName: string | null;
}

type Json = Readonly<Record<string, unknown>>;

function object(value: unknown, where: string): Json {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError(`The server returned an invalid ${where}.`);
  }
  return value as Json;
}

function list(value: unknown, where: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new TypeError(`The server returned an invalid ${where}.`);
  return value;
}

function text(value: unknown, where: string): string {
  if (typeof value !== 'string') throw new TypeError(`The server returned an invalid ${where}.`);
  return value;
}

function whole(value: unknown, where: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    throw new TypeError(`The server returned an invalid ${where}.`);
  }
  return value;
}

const maybe = <T>(value: unknown, read: (present: unknown) => T): T | null =>
  value === null || value === undefined ? null : read(value);

function parseKind(raw: unknown): WorldKind {
  const held = object(raw, 'kind of place');
  const source = held['source'];
  if (source !== 'shipped' && source !== 'workspace') throw new TypeError('The server returned an invalid kind source.');
  return Object.freeze({
    kind: text(held['kind'], 'kind key'),
    version: whole(held['version'], 'kind version'),
    sha256: text(held['sha256'], 'kind digest'),
    source,
    label: text(held['label'], 'kind label'),
    summary: text(held['summary'], 'kind summary'),
    origin: text(held['origin'], 'kind origin'),
    parameters: Object.freeze(list(held['parameters'], 'kind parameters').map((entry): KindParameter => {
      const parameter = object(entry, 'kind parameter');
      return Object.freeze({
        key: text(parameter['key'], 'parameter key'),
        label: text(parameter['label'], 'parameter label'),
        minimum: maybe(parameter['minimum'], (v) => whole(v, 'parameter minimum')),
        maximum: maybe(parameter['maximum'], (v) => whole(v, 'parameter maximum')),
        step: maybe(parameter['step'], (v) => whole(v, 'parameter step')),
        choices: maybe(parameter['choices'], (v) => Object.freeze(list(v, 'parameter choices').map((c) => text(c, 'choice')))),
        reason: text(parameter['reason'], 'parameter reason'),
      });
    })),
    presets: Object.freeze(list(held['presets'], 'kind presets').map((entry): KindPreset => {
      const preset = object(entry, 'kind preset');
      const values: Record<string, number | string> = {};
      for (const [key, value] of Object.entries(object(preset['values'], 'preset values'))) {
        values[key] = typeof value === 'string' ? value : whole(value, 'preset value');
      }
      return Object.freeze({ key: text(preset['key'], 'preset key'), label: text(preset['label'], 'preset label'), values: Object.freeze(values) });
    })),
    parts: Object.freeze(list(held['parts'], 'kind parts').map((entry): KindPart => {
      const part = object(entry, 'kind part');
      return Object.freeze({
        key: text(part['key'], 'part key'),
        label: text(part['label'], 'part label'),
        description: text(part['description'], 'part description'),
      });
    })),
  });
}

function parseRefusals(value: unknown): readonly KindRefusal[] {
  return Object.freeze(list(value, 'refusal list').map((entry) => {
    const refusal = object(entry, 'refusal');
    return Object.freeze({ code: text(refusal['code'], 'refusal code'), meaning: text(refusal['meaning'], 'refusal meaning') });
  }));
}

export function parseKindLibrary(raw: unknown): KindLibrary {
  const held = object(raw, 'kinds of place');
  if (held['profile'] !== KINDS_PROFILE) throw new TypeError('The server returned kinds of place of another profile.');
  const drafting = maybe(held['drafting'], (value): KindDrafting => {
    const said = object(value, 'drafting offer');
    if (typeof said['offered'] !== 'boolean') throw new TypeError('The server returned an invalid drafting offer.');
    return Object.freeze({
      offered: said['offered'],
      code: maybe(said['code'], (code) => text(code, 'drafting code')),
      refusals: parseRefusals(said['refusals']),
    });
  });
  return Object.freeze({ kinds: Object.freeze(list(held['kinds'], 'kinds').map(parseKind)), drafting });
}

export function parseKindDraft(raw: unknown): KindDraft {
  const held = object(raw, 'draft');
  const state = held['state'];
  if (state !== 'drafting' && state !== 'ready' && state !== 'refused') throw new TypeError('The server returned an invalid draft state.');
  return Object.freeze({
    draftId: text(held['draft_id'], 'draft id'),
    state,
    description: text(held['description'], 'draft description'),
    elapsedSeconds: whole(held['elapsed_seconds'], 'draft elapsed time'),
    pollAfterSeconds: maybe(held['poll_after_seconds'], (v) => whole(v, 'draft poll interval')),
    kind: maybe(held['kind'], parseKind),
    refusal: maybe(held['refusal'], (value) => {
      const refusal = object(value, 'draft refusal');
      return Object.freeze({
        code: text(refusal['code'], 'draft refusal code'),
        detail: text(refusal['detail'], 'draft refusal detail'),
        check: maybe(refusal['check'], (v) => text(v, 'draft refusal check')),
      });
    }),
    modelName: maybe(held['model_name'], (v) => text(v, 'model name')),
  });
}

export class WorldKindsClient {
  readonly #transport: Transport;

  constructor(options: TransportOptions) {
    this.#transport = new Transport(options);
  }

  async library(): Promise<KindLibrary> {
    return parseKindLibrary(await this.#transport.getJson<unknown>('/worlds/kinds'));
  }

  /** The caller's drafts the server still holds here, newest first. */
  async drafts(): Promise<readonly KindDraft[]> {
    const held = object(await this.#transport.getJson<unknown>('/worlds/kinds/drafts'), 'draft list');
    return Object.freeze(list(held['drafts'], 'drafts').map(parseKindDraft));
  }

  async startDraft(description: string): Promise<KindDraft> {
    return parseKindDraft(await this.#transport.postJson<unknown>('/worlds/kinds/drafts', { description }));
  }

  async draft(draftId: string): Promise<KindDraft> {
    return parseKindDraft(await this.#transport.getJson<unknown>(`/worlds/kinds/drafts/${encodeURIComponent(draftId)}`));
  }
}
