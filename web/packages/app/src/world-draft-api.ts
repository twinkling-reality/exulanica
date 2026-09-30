/**
 * A world's specification drafted from a person's own words (`POST /worlds/specification/drafts`).
 *
 * The server answers with a proposal document, the same one an agent calling the API reads: the
 * preset and values an open model drafted, the verdict of the specification's own validation, a
 * sample town of the values, the parts of the words no value can say, or a refusal by name.
 * Nothing is made by drafting; making the world is `POST /worlds/generated` with the values the
 * person confirms. Parsed strictly: a field of the wrong shape is refused, never guessed.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';

/** How a sample town came out, as the server names it (`exulanica/world/specification_samples.py`). */
export const SAMPLE_STATUSES = ['sampled', 'refused', 'overran', 'busy', 'unavailable'] as const;
export type SampleStatus = typeof SAMPLE_STATUSES[number];

/** Why a description gave no proposal, as the server names it. */
export const DRAFT_REFUSALS = ['description_not_supported', 'not_drafted'] as const;
export type DraftRefusalCode = typeof DRAFT_REFUSALS[number];

export interface CountedKind {
  readonly key: string;
  /** The catalog's own word for the kind. */
  readonly label: string;
  readonly count: number;
}

export interface TownSample {
  readonly status: SampleStatus;
  readonly tiles: number | null;
  readonly people: number | null;
  readonly vehicles: number | null;
  readonly vehiclesRefused: string | null;
  readonly streets: readonly CountedKind[];
  readonly premises: readonly CountedKind[];
  readonly buildings: number | null;
  readonly refused: string | null;
}

export interface ValueRefusal {
  readonly code: string;
  readonly detail: string;
  readonly key: string | null;
  readonly value: number | string | null;
  readonly minimum: number | null;
  readonly maximum: number | null;
  readonly step: number | null;
  /** For values that disagree: the other key and its value, which narrowed this one's range. */
  readonly withKey: string | null;
  readonly withValue: number | string | null;
}

export interface DraftProposal {
  readonly preset: string;
  /** Every value a person may set, as `POST /worlds/generated` would be sent them. */
  readonly values: Readonly<Record<string, number | string>>;
  /** The values the words set to other than the preset's. */
  readonly setByWords: readonly string[];
  readonly fit: 'all' | 'part';
  readonly valid: boolean;
  readonly valueRefusal: ValueRefusal | null;
  readonly sample: TownSample | null;
}

export interface WorldDraft {
  /** The words as the person typed them. */
  readonly description: string;
  readonly proposal: DraftProposal | null;
  /** Each part of the words no value can say, in the person's own words. */
  readonly notSupported: readonly string[];
  readonly refusal: { readonly code: DraftRefusalCode; readonly detail: string } | null;
  readonly specificationVersion: number;
  readonly specificationSha256: string;
  readonly promptVersion: string;
  readonly modelId: string | null;
  /** The name a person reads for `modelId`, as the server serves it (`Manifest.model_name`). */
  readonly modelName: string | null;
}

type Row = Readonly<Record<string, unknown>>;

function row(value: unknown, what: string): Row {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`The server returned an invalid ${what}.`);
  }
  return value as Row;
}

function text(value: unknown, what: string): string {
  if (typeof value !== 'string') throw new TypeError(`The server returned an invalid ${what}.`);
  return value;
}

function whole(value: unknown, what: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    throw new TypeError(`The server returned an invalid ${what}.`);
  }
  return value;
}

function nullable<T>(value: unknown, read: (value: unknown, what: string) => T, what: string): T | null {
  return value === null ? null : read(value, what);
}

function list<T>(value: unknown, read: (value: unknown) => T, what: string): readonly T[] {
  if (!Array.isArray(value)) throw new TypeError(`The server returned an invalid ${what}.`);
  return value.map(read);
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], what: string): T {
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) {
    throw new TypeError(`The server returned an unknown ${what}.`);
  }
  return value as T;
}

function counted(value: unknown): CountedKind {
  const one = row(value, 'counted kind');
  return {
    key: text(one['key'], 'kind key'),
    label: text(one['label'], 'kind label'),
    count: whole(one['count'], 'kind count'),
  };
}

function sample(value: unknown): TownSample {
  const one = row(value, 'sample town');
  return {
    status: oneOf(one['status'], SAMPLE_STATUSES, 'sample status'),
    tiles: nullable(one['tiles'], whole, 'sample tiles'),
    people: nullable(one['people'], whole, 'sample people'),
    vehicles: nullable(one['vehicles'], whole, 'sample vehicles'),
    vehiclesRefused: nullable(one['vehicles_refused'], text, 'sample vehicle refusal'),
    streets: list(one['streets'], counted, 'sample streets'),
    premises: list(one['premises'], counted, 'sample premises'),
    buildings: nullable(one['buildings'], whole, 'sample buildings'),
    refused: nullable(one['refused'], text, 'sample refusal'),
  };
}

function valueRefusal(value: unknown): ValueRefusal {
  const one = row(value, 'value refusal');
  return {
    code: text(one['code'], 'value refusal code'),
    detail: text(one['detail'], 'value refusal detail'),
    key: nullable(one['key'], text, 'refused key'),
    value: nullable(one['value'], (value, what) => (
      typeof value === 'string' ? value : whole(value, what)), 'refused value'),
    minimum: nullable(one['minimum'], whole, 'refused minimum'),
    maximum: nullable(one['maximum'], whole, 'refused maximum'),
    step: nullable(one['step'], whole, 'refused step'),
    withKey: nullable(one['with_key'] ?? null, text, 'narrowing key'),
    withValue: nullable(one['with_value'] ?? null, (value, what) => (
      typeof value === 'string' ? value : whole(value, what)), 'narrowing value'),
  };
}

function proposal(value: unknown): DraftProposal {
  const one = row(value, 'proposal');
  const values = row(one['values'], 'proposed values');
  const valid = one['valid'];
  if (typeof valid !== 'boolean') throw new TypeError('The server returned an invalid verdict.');
  const refused = nullable(one['value_refusal'], valueRefusal, 'value refusal');
  const sampled = nullable(one['sample'], sample, 'sample town');
  // A valid proposal carries no refusal and a sample; a refused one carries its refusal only.
  if (valid !== (refused === null) || (sampled !== null && !valid)) {
    throw new TypeError('The server returned a proposal whose verdict and sample disagree.');
  }
  return {
    preset: text(one['preset'], 'preset'),
    values: Object.fromEntries(
      Object.entries(values).map(([key, value]) => [key,
        typeof value === 'string' ? value : whole(value, `value of ${key}`)]),
    ),
    setByWords: list(one['set_by_words'], (key) => text(key, 'key set by the words'), 'keys'),
    fit: oneOf(one['fit'], ['all', 'part'] as const, 'fit'),
    valid,
    valueRefusal: refused,
    sample: sampled,
  };
}

/** A drafting answer as the server serves it; a field of the wrong shape is refused. */
export function parseWorldDraft(value: unknown): WorldDraft {
  const body = row(value, 'world draft');
  const drafted = nullable(body['proposal'], proposal, 'proposal');
  const refusal = body['refusal'] === null ? null : (() => {
    const one = row(body['refusal'], 'draft refusal');
    return {
      code: oneOf(one['code'], DRAFT_REFUSALS, 'draft refusal'),
      detail: text(one['detail'], 'draft refusal detail'),
    };
  })();
  if ((drafted === null) === (refusal === null)) {
    throw new TypeError('A world draft carries a proposal or a refusal, and only one.');
  }
  return {
    description: text(body['description'], 'description'),
    proposal: drafted,
    notSupported: list(body['not_supported'], (phrase) => text(phrase, 'phrase'), 'phrases'),
    refusal,
    specificationVersion: whole(body['specification_version'], 'specification version'),
    specificationSha256: text(body['specification_sha256'], 'specification digest'),
    promptVersion: text(body['prompt_version'], 'prompt version'),
    modelId: nullable(body['model_id'], text, 'model'),
    modelName: nullable(body['model_name'], text, 'model name'),
  };
}

/** The drafting route's client. */
export class WorldDraftClient {
  readonly #transport: Transport;

  constructor(options: TransportOptions) {
    this.#transport = new Transport(options);
  }

  /** Draft a specification from `description`; nothing is made. */
  async draft(description: string): Promise<WorldDraft> {
    return parseWorldDraft(
      await this.#transport.postJson<unknown>('/worlds/specification/drafts', { description }),
    );
  }
}
