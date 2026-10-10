/**
 * What a generated world may be made from, as the server serves it: `GET /worlds/specification`.
 *
 * One document states every value a world's specification holds (its key, the grammar's own
 * parameter name; its words, kind, unit and range; the reason for the range), the presets (each a
 * point in that range: the value of every adjustable parameter), the bounds a world is also held
 * to and every refusal by name. The page renders it, and an open model drafting a specification for
 * a person reads the same document; the server's gate (`town_recipe`) decides.
 *
 * `refusalOf` states, before anything is sent, the refusal the server's gate would give values the
 * document's ranges do not admit, by the same codes and in the same words: a key the document does
 * not offer, a value outside its range, off its step or of another kind, and two values the
 * document does not admit together (a value's `requires`: while another lies in a stated span, its
 * range narrows). `effectiveRange` is a number's range with the values chosen so far, which a page
 * offers so its controls never offer a pair the document refuses. Both read only the served
 * document and restate none of it. The server stays the authority: values that pass here can still
 * be refused, by name, when no candidate generates a world from them.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';

export const SPECIFICATION_PROFILE = 'exulanica.world-specification/v1';

/** While `when` lies from `from` to `to`, the value stating this lies from `minimum` to `maximum`. */
export interface SpecificationRequirement {
  readonly when: string;
  readonly from: number;
  readonly to: number;
  readonly minimum: number;
  readonly maximum: number;
  readonly reason: string;
}

/** One value a world's specification states. */
export interface SpecificationValue {
  readonly key: string;
  readonly label: string;
  readonly kind: 'integer' | 'choice';
  /** The grammar's unit: `mm`, `count`, `key` and the like. */
  readonly unit: string;
  readonly adjustable: boolean;
  /** A number's range: from `minimum` to `maximum` in steps of `step`. */
  readonly minimum: number | null;
  readonly maximum: number | null;
  readonly step: number | null;
  /** A key's range. */
  readonly choices: readonly string[] | null;
  /** Each choice in words, in the choices' order, where the server states them; else null. */
  readonly choiceLabels: readonly string[] | null;
  /** The one value a fixed range holds; null for an adjustable one. */
  readonly value: number | string | null;
  /** When another value narrows this one's range, and why. */
  readonly requires: readonly SpecificationRequirement[];
  readonly reason: string;
}

/** A named point in the document's range. */
export interface SpecificationPreset {
  readonly key: string;
  readonly label: string;
  readonly values: Readonly<Record<string, number | string>>;
  readonly tiles: number;
}

export interface SpecificationRefusalKind {
  readonly code: string;
  readonly status: number;
  readonly meaning: string;
}

export interface WorldSpecification {
  readonly grammar: { readonly grammarId: string; readonly grammarVersion: number };
  readonly values: readonly SpecificationValue[];
  readonly presets: readonly SpecificationPreset[];
  readonly refusals: readonly SpecificationRefusalKind[];
  /**
   * The most people a world's society holds: the least maximum any ground states, or null where
   * none states one (a town is peopled by its own homes and admitted by the cost of its minute).
   * Then the most generated worlds a workspace holds.
   */
  readonly mostPeople: number | null;
  readonly generatedWorldsPerWorkspace: number | null;
}

/** A refusal the server's gate gives, by its code, naming the key and the range it broke. */
export interface SpecificationRefusal {
  readonly code: 'specification_value_unknown' | 'specification_value_out_of_range' | 'specification_values_disagree';
  readonly key: string;
  readonly detail: string;
}

type Json = Record<string, unknown>;

function object(value: unknown, where: string): Json {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError(`The server returned an invalid ${where}.`);
  }
  return value as Json;
}

function text(value: unknown, where: string): string {
  if (typeof value !== 'string' || value.length === 0) throw new TypeError(`The server returned an invalid ${where}.`);
  return value;
}

function whole(value: unknown, where: string): number {
  if (!Number.isSafeInteger(value)) throw new TypeError(`The server returned an invalid ${where}.`);
  return value as number;
}

function parseValue(raw: unknown): SpecificationValue {
  const row = object(raw, 'specification value');
  const kind = row['kind'];
  if (kind !== 'integer' && kind !== 'choice') throw new TypeError('The server returned an unknown value kind.');
  const adjustable = row['adjustable'];
  if (typeof adjustable !== 'boolean') throw new TypeError('The server returned an invalid adjustable flag.');
  const choices = kind === 'choice' ? row['choices'] : null;
  if (choices !== null && (!Array.isArray(choices) || choices.length === 0)) {
    throw new TypeError('The server returned a choice with no choices.');
  }
  const labels = row['choice_labels'];
  if (labels !== undefined
    && (choices === null || !Array.isArray(labels) || labels.length !== (choices as unknown[]).length)) {
    throw new TypeError('The server returned choice labels that do not match the choices.');
  }
  const fixed = adjustable ? null : row['value'];
  if (!adjustable && typeof fixed !== 'string' && !Number.isSafeInteger(fixed)) {
    throw new TypeError('The server returned a fixed value that states no value.');
  }
  const requires = row['requires'];
  if (!Array.isArray(requires)) throw new TypeError('The server returned a value without its requirements.');
  return Object.freeze({
    key: text(row['key'], 'value key'),
    label: text(row['label'], 'value label'),
    kind,
    unit: text(row['unit'], 'value unit'),
    adjustable,
    minimum: kind === 'integer' ? whole(row['minimum'], 'value minimum') : null,
    maximum: kind === 'integer' ? whole(row['maximum'], 'value maximum') : null,
    step: kind === 'integer' ? whole(row['step'], 'value step') : null,
    choices: choices === null ? null : Object.freeze(choices.map((choice) => text(choice, 'choice'))),
    choiceLabels: labels === undefined
      ? null : Object.freeze((labels as unknown[]).map((label) => text(label, 'choice label'))),
    value: fixed as number | string | null,
    requires: Object.freeze(requires.map((raw) => {
      const item = object(raw, 'requirement');
      return Object.freeze({
        when: text(item['when'], 'requirement key'),
        from: whole(item['from'], 'requirement span'),
        to: whole(item['to'], 'requirement span'),
        minimum: whole(item['minimum'], 'requirement minimum'),
        maximum: whole(item['maximum'], 'requirement maximum'),
        reason: text(item['reason'], 'requirement reason'),
      });
    })),
    reason: text(row['reason'], 'value reason'),
  });
}

/** The served document, read strictly, or a `TypeError` naming what does not hold. */
export function parseWorldSpecification(raw: unknown): WorldSpecification {
  const body = object(raw, 'world specification');
  if (body['profile'] !== SPECIFICATION_PROFILE) {
    throw new TypeError(`The server's world specification is not ${SPECIFICATION_PROFILE}.`);
  }
  const grammar = object(body['grammar'], 'specification grammar');
  const values = body['values'];
  const presets = body['presets'];
  const refusals = body['refusals'];
  if (!Array.isArray(values) || !Array.isArray(presets) || !Array.isArray(refusals)) {
    throw new TypeError('The server returned a world specification without values, presets or refusals.');
  }
  const bounds = object(body['bounds'], 'specification bounds');
  const people = bounds['people'];
  if (!Array.isArray(people) || people.length === 0) {
    throw new TypeError('The server returned no bound on a world\'s people.');
  }
  const perWorkspace = bounds['generated_worlds_per_workspace'];
  return Object.freeze({
    grammar: Object.freeze({
      grammarId: text(grammar['grammar_id'], 'grammar'),
      grammarVersion: whole(grammar['grammar_version'], 'grammar version'),
    }),
    values: Object.freeze(values.map(parseValue)),
    presets: Object.freeze(presets.map((rawPreset) => {
      const row = object(rawPreset, 'preset');
      const stated = object(row['values'], 'preset values');
      return Object.freeze({
        key: text(row['key'], 'preset key'),
        label: text(row['label'], 'preset label'),
        values: Object.freeze(Object.fromEntries(Object.entries(stated).map(([key, value]) => {
          if (typeof value !== 'string' && !Number.isSafeInteger(value)) {
            throw new TypeError('The server returned a preset value that is not a number or a key.');
          }
          return [key, value as number | string];
        }))),
        tiles: whole(row['tiles'], 'preset tile count'),
      });
    })),
    refusals: Object.freeze(refusals.map((rawRefusal) => {
      const row = object(rawRefusal, 'refusal');
      return Object.freeze({
        code: text(row['code'], 'refusal code'),
        status: whole(row['status'], 'refusal status'),
        meaning: text(row['meaning'], 'refusal meaning'),
      });
    })),
    mostPeople: leastStated(people.map((row) => {
      const most = object(row, 'people bound')['most'];
      // A ground that states no maximum states null; anything else is a whole number or refused.
      return most === null ? null : whole(most, 'people bound');
    })),
    generatedWorldsPerWorkspace: perWorkspace === null ? null : whole(perWorkspace, 'generated world limit'),
  });
}

/** The least of the figures stated, or null where none is. */
function leastStated(figures: readonly (number | null)[]): number | null {
  const stated = figures.filter((figure): figure is number => figure !== null);
  return stated.length === 0 ? null : Math.min(...stated);
}

/** The range in words, as the server's gate states it. */
export function rangeWords(value: SpecificationValue): string {
  if (value.kind === 'choice') return `one of ${value.choices!.join(', ')}`;
  if (!value.adjustable) return `${value.minimum} ${value.unit}, fixed`;
  return `${value.minimum} to ${value.maximum} ${value.unit} in steps of ${value.step}`;
}

/** The requirement of `value` that `values` bring into force, if any: the first that applies. */
function requirementIn(
  value: SpecificationValue,
  values: Readonly<Record<string, unknown>>,
): SpecificationRequirement | null {
  return value.requires.find((requirement) => {
    const other = values[requirement.when];
    return Number.isSafeInteger(other) && (other as number) >= requirement.from && (other as number) <= requirement.to;
  }) ?? null;
}

/** A number's range with the values chosen so far: its own, narrowed by a requirement in force. */
export function effectiveRange(
  value: SpecificationValue,
  values: Readonly<Record<string, unknown>>,
): { readonly minimum: number; readonly maximum: number; readonly step: number } {
  const requirement = requirementIn(value, values);
  return {
    minimum: requirement?.minimum ?? value.minimum!,
    maximum: requirement?.maximum ?? value.maximum!,
    step: value.step!,
  };
}

/**
 * The refusal the server's gate gives `values` against the document's ranges, or null when every
 * value lies inside its range and every pair is admitted together. Keys are checked in the order
 * the gate checks them, each against its own range first and then pairs in the document's order.
 */
export function refusalOf(
  specification: WorldSpecification,
  values: Readonly<Record<string, unknown>>,
): SpecificationRefusal | null {
  for (const key of Object.keys(values).sort()) {
    const stated = specification.values.find((value) => value.key === key && !isSpecificationField(value));
    const value = values[key];
    if (stated === undefined || !stated.adjustable) {
      return {
        code: 'specification_value_unknown',
        key,
        detail: stated === undefined
          ? `${key}: this schema states no value with that key`
          : `${key}: this schema fixes it at ${JSON.stringify(stated.value)}: ${stated.reason}`,
      };
    }
    const inside = stated.kind === 'choice'
      ? typeof value === 'string' && stated.choices!.includes(value)
      : Number.isSafeInteger(value)
        && (value as number) >= stated.minimum!
        && (value as number) <= stated.maximum!
        && ((value as number) - stated.minimum!) % stated.step! === 0;
    if (!inside) {
      return {
        code: 'specification_value_out_of_range',
        key,
        detail: `${key} (${stated.label.toLowerCase()}) is ${JSON.stringify(value)}; `
          + `this schema admits ${rangeWords(stated)}`,
      };
    }
  }
  for (const stated of specification.values) {
    for (const requirement of stated.requires) {
      const other = values[requirement.when];
      if (!Number.isSafeInteger(other) || (other as number) < requirement.from || (other as number) > requirement.to) continue;
      const chosen = values[stated.key];
      if (Number.isSafeInteger(chosen) && (chosen as number) >= requirement.minimum && (chosen as number) <= requirement.maximum) continue;
      const named = specification.values.find((value) => value.key === requirement.when);
      return {
        code: 'specification_values_disagree',
        key: stated.key,
        detail: `${stated.key} (${stated.label.toLowerCase()}) is ${JSON.stringify(chosen)} and `
          + `${requirement.when} (${named?.label.toLowerCase() ?? requirement.when}) is ${JSON.stringify(other)}; `
          + `with that value this schema admits ${requirement.minimum} to ${requirement.maximum} `
          + `${stated.unit} in steps of ${stated.step}: ${requirement.reason}`,
      };
    }
  }
  return null;
}

/** The specification's own fields (its grammar and version), which no request states. */
function isSpecificationField(value: SpecificationValue): boolean {
  return value.key === 'grammar_id' || value.key === 'grammar_version';
}

/** Reads the served document. */
export class WorldSpecificationClient {
  readonly #transport: Transport;

  constructor(options: TransportOptions) {
    this.#transport = new Transport(options);
  }

  async specification(): Promise<WorldSpecification> {
    return parseWorldSpecification(await this.#transport.getJson<unknown>('/worlds/specification'));
  }
}
