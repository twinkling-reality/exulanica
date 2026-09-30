/** Registered model decision roles and choices for one saved world. */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import {
  type ModelRef, type NamedModelRef, parseSocietyModels, type SocietyModels,
} from './society-models-api.js';
import { openWorldPath } from './world-scope.js';

export interface SignalSubject {
  readonly signalId: string;
  readonly junctionId: string;
  readonly label: string;
}

export interface SignalModel extends ModelRef {
  readonly name: string;
  readonly description: string;
  readonly mechanism: 'tool_call' | 'json_schema';
  readonly refusal: string | null;
}

export interface SignalChoice {
  readonly subjectId: string;
  readonly choiceSeq: number;
  readonly model: NamedModelRef | null;
  readonly effectiveSecond: number;
  readonly activeSecond: number | null;
  readonly runningModel: NamedModelRef | null;
  readonly runningChoiceSeq: number | null;
  readonly status: 'pending' | 'preparing' | 'active' | 'fixed';
  readonly refusal: string | null;
}

export interface SignalRole {
  readonly key: string;
  readonly subject: 'signal';
  readonly label: string;
  readonly available: boolean;
  readonly reason: string | null;
  readonly hostRefusal: string | null;
  readonly subjects: readonly SignalSubject[];
  readonly models: readonly SignalModel[];
  readonly choices: readonly SignalChoice[];
  readonly modelSubjectsMaximum: number;
}

export interface PersonRole {
  readonly key: string;
  readonly subject: 'person';
  readonly label: string;
  readonly available: boolean;
  readonly view: SocietyModels | null;
}

export type DecisionRoleView = SignalRole | PersonRole;

export interface WorldModels {
  readonly clockSecond: number;
  readonly roles: readonly DecisionRoleView[];
}

const invalid = (): never => { throw new Error('Invalid world models response'); };
const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : invalid();
const list = (value: unknown): readonly unknown[] => Array.isArray(value) ? value : invalid();
const text = (value: unknown): string => typeof value === 'string' && value.length > 0 ? value : invalid();
const count = (value: unknown): number => Number.isSafeInteger(value) && (value as number) >= 0 ? value as number : invalid();
const maybe = <T>(value: unknown, read: (held: unknown) => T): T | null => value === null ? null : read(value);
const flag = (value: unknown): boolean => typeof value === 'boolean' ? value : invalid();

function model(value: unknown): SignalModel {
  const row = object(value);
  const mechanism = row['mechanism'];
  return {
    provider: text(row['provider']), modelId: text(row['model_id']),
    name: text(row['name']), description: text(row['description']),
    mechanism: mechanism === 'tool_call' || mechanism === 'json_schema' ? mechanism : invalid(),
    refusal: maybe(row['refusal'], text),
  };
}

function signalRole(value: Record<string, unknown>): SignalRole {
  return {
    key: text(value['key']), subject: 'signal', label: text(value['label']),
    available: flag(value['available']), reason: maybe(value['reason'], text),
    hostRefusal: maybe(value['host_refusal'], text),
    subjects: list(value['subjects']).map((item) => {
      const row = object(item);
      return {
        signalId: text(row['signal_id']), junctionId: text(row['junction_id']),
        label: text(row['label']),
      };
    }),
    models: list(value['models']).map(model),
    choices: list(value['choices']).map((item) => {
      const row = object(item);
      const status = row['status'];
      const chosen = maybe(row['model'], (held): NamedModelRef => {
        const named = object(held);
        return {
          provider: text(named['provider']), modelId: text(named['model_id']),
          name: text(named['name']),
        };
      });
      return {
        subjectId: text(row['subject_id']), choiceSeq: count(row['choice_seq']),
        model: chosen, effectiveSecond: count(row['effective_second']),
        activeSecond: maybe(row['active_second'], count),
        runningModel: maybe(row['running_model'], (held): NamedModelRef => {
          const named = object(held);
          return {
            provider: text(named['provider']), modelId: text(named['model_id']),
            name: text(named['name']),
          };
        }),
        runningChoiceSeq: maybe(row['running_choice_seq'], count),
        status: status === 'pending' || status === 'preparing' || status === 'active' || status === 'fixed'
          ? status : invalid(),
        refusal: maybe(row['refusal'], text),
      };
    }),
    modelSubjectsMaximum: count(value['model_subjects_maximum']),
  };
}

export function parseWorldModels(value: unknown): WorldModels {
  const row = object(value);
  if (row['profile'] !== 'exulanica.world-models/v1') invalid();
  const roles = list(row['roles']).map((item): DecisionRoleView => {
    const role = object(item);
    if (role['subject'] === 'signal') return signalRole(role);
    if (role['subject'] === 'person') return {
      key: text(role['key']), subject: 'person', label: text(role['label']),
      available: flag(role['available']),
      view: maybe(role['view'], parseSocietyModels),
    };
    return invalid();
  });
  return { clockSecond: count(row['clock_second']), roles };
}

export class WorldModelsClient {
  readonly #transport: Transport;
  readonly #worldId: string | null;

  constructor(options: TransportOptions & { readonly worldId: string | null }) {
    this.#transport = new Transport(options);
    this.#worldId = options.worldId;
  }

  async read(versionId: string): Promise<WorldModels> {
    return this.#transport.getJson<unknown>(this.#path(versionId)).then(parseWorldModels);
  }

  async choose(
    versionId: string, roleKey: string, subjects: readonly string[], model: ModelRef | null,
    idempotencyKey: string = crypto.randomUUID(),
  ): Promise<void> {
    await this.#transport.postJson<unknown>(this.#path(versionId, roleKey), {
      idempotency_key: idempotencyKey,
      subjects,
      model: model === null ? null : { provider: model.provider, model_id: model.modelId },
    });
  }

  #path(versionId: string, roleKey?: string): string {
    const role = roleKey === undefined ? '' : `/${encodeURIComponent(roleKey)}`;
    return openWorldPath(
      `/world/versions/${encodeURIComponent(versionId)}/models${role}`, this.#worldId,
      'choice of who decides for this world',
    );
  }
}
