/**
 * The society engines the server states, read from the backend engine table.
 *
 * `society-engines.generated.ts` carries `exulanica/world/society-engines.v1.json` byte for byte,
 * with the union of its engine profiles, so the browser never restates which engines exist, what
 * each can do or how many people it may hold. This module reads that text once, checks its shape,
 * and answers questions about one engine. An engine the table does not state is refused by name,
 * never read as one it resembles.
 */

import { SOCIETY_ENGINES_V1_JSON, type SocietyEngineProfile } from './society-engines.generated.js';

export type { SocietyEngineProfile };

/** Which state shape an engine writes, and so which reader parses it. */
export type SocietyStateFamily = 'legacy' | 'purposeful' | 'living';

export interface SocietyEngine {
  readonly engine: SocietyEngineProfile;
  /** Consumes ordered, authorised inputs, so its events carry an input and an order. */
  readonly takesInputs: boolean;
  readonly playback: boolean;
  readonly directedActions: boolean;
  readonly modelDecisions: boolean;
  /** The person whose world it lives in may send its people away and bring them back. */
  readonly presence: boolean;
  /** Can stand on a saved world's own ground. */
  readonly savedWorld: boolean;
  readonly stateFamily: SocietyStateFamily;
  readonly populationMinimum: number;
  readonly populationMaximum: number;
}

const FAMILIES: readonly SocietyStateFamily[] = ['legacy', 'purposeful', 'living'];

function row(value: unknown): SocietyEngine {
  const held = value as Readonly<Record<string, unknown>> | null;
  const population = (held?.['population'] ?? null) as Readonly<Record<string, unknown>> | null;
  const flags = ['takes_inputs', 'playback', 'directed_actions', 'model_decisions', 'presence', 'saved_world'];
  if (held === null || typeof held !== 'object' || typeof held['engine'] !== 'string' ||
      flags.some((flag) => typeof held[flag] !== 'boolean') ||
      !FAMILIES.includes(held['state_family'] as SocietyStateFamily) ||
      population === null || !Number.isSafeInteger(population['minimum']) ||
      !Number.isSafeInteger(population['maximum']) ||
      (population['minimum'] as number) < 1 ||
      (population['minimum'] as number) > (population['maximum'] as number)) {
    throw new Error('Invalid society engine table');
  }
  return Object.freeze({
    engine: held['engine'] as SocietyEngineProfile,
    takesInputs: held['takes_inputs'] as boolean,
    playback: held['playback'] as boolean,
    directedActions: held['directed_actions'] as boolean,
    modelDecisions: held['model_decisions'] as boolean,
    presence: held['presence'] as boolean,
    savedWorld: held['saved_world'] as boolean,
    stateFamily: held['state_family'] as SocietyStateFamily,
    populationMinimum: population['minimum'] as number,
    populationMaximum: population['maximum'] as number,
  });
}

function table(text: string): { readonly engines: readonly SocietyEngine[]; readonly defaultEngine: SocietyEngineProfile } {
  const document = JSON.parse(text) as Readonly<Record<string, unknown>>;
  if (document['profile'] !== 'exulanica.society-engines/v1' || !Array.isArray(document['engines'])) {
    throw new Error('Invalid society engine table');
  }
  const engines = Object.freeze(document['engines'].map(row));
  if (!engines.some((engine) => engine.engine === document['default_engine'])) {
    throw new Error('Invalid society engine table default');
  }
  return { engines, defaultEngine: document['default_engine'] as SocietyEngineProfile };
}

const TABLE = table(SOCIETY_ENGINES_V1_JSON);

/** Every engine, in the table's order. */
export const SOCIETY_ENGINES: readonly SocietyEngine[] = TABLE.engines;
/** The engine a society is created with when a request names none. */
export const DEFAULT_SOCIETY_ENGINE: SocietyEngineProfile = TABLE.defaultEngine;

/** The engine with this profile, or an error that names what was asked for. */
export function societyEngine(profile: unknown): SocietyEngine {
  const engine = SOCIETY_ENGINES.find((held) => held.engine === profile);
  if (engine === undefined) throw new Error(`Unknown society engine ${JSON.stringify(profile)}`);
  return engine;
}
