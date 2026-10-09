/**
 * The society engines the server states, read from the backend engine table.
 *
 * `society-engines.generated.ts` carries `exulanica/world/society-engines.v3.json` byte for byte,
 * with the union of its engine profiles, so the browser never restates which engines exist, what
 * each can do, how many people it may hold, which engine a new society over each kind of ground
 * is created with, or which one a saved world holding a thing its author placed takes on a host
 * that offers societies of things (the server states that one on each world entry). This module reads that text once, checks its shape, and answers questions
 * about one engine. An engine the table does not state is refused by name, never read as one it
 * resembles.
 */

import { SOCIETY_ENGINES_V3_JSON, type SocietyEngineProfile } from './society-engines.generated.js';

export type { SocietyEngineProfile };

/** Which state shape an engine writes, and so which reader parses it. */
export type SocietyStateFamily = 'legacy' | 'purposeful' | 'living' | 'things';

export interface SocietyEngine {
  readonly engine: SocietyEngineProfile;
  /** A new society may be created with it; a retired engine's stored societies still read. */
  readonly creatable: boolean;
  /** Consumes ordered, authorised inputs, so its events carry an input and an order. */
  readonly takesInputs: boolean;
  readonly playback: boolean;
  readonly directedActions: boolean;
  readonly modelDecisions: boolean;
  /** The world's owner may choose a model that decides for one of its people. */
  readonly ownerModelChoice: boolean;
  /** The person whose world it lives in may send its people away and bring them back. */
  readonly presence: boolean;
  /** Can stand on a saved world's own ground. */
  readonly savedWorld: boolean;
  readonly stateFamily: SocietyStateFamily;
  readonly populationMinimum: number;
  readonly populationMaximum: number;
}

const FAMILIES: readonly SocietyStateFamily[] = ['legacy', 'purposeful', 'living', 'things'];

/**
 * The kinds of ground a new society is created over, each with the engine the table names: an owned
 * district, a saved world's own ground, and a saved world whose own records state its walking
 * surfaces and homes (a town). Which grounds exist is the table's `creates`; a ground here the
 * table does not state, or one it states that is not here, is refused when the table is read.
 */
export type SocietyGroundKind = 'district' | 'saved_world' | 'town';
const GROUNDS: readonly SocietyGroundKind[] = ['district', 'saved_world', 'town'];
/** The grounds that are a saved world's own, whose engine must stand on a saved world. */
const SAVED_WORLD_GROUNDS: readonly SocietyGroundKind[] = ['saved_world', 'town'];

function row(value: unknown): SocietyEngine {
  const held = value as Readonly<Record<string, unknown>> | null;
  const population = (held?.['population'] ?? null) as Readonly<Record<string, unknown>> | null;
  const flags = ['creatable', 'takes_inputs', 'playback', 'directed_actions', 'model_decisions',
    'owner_model_choice', 'presence', 'saved_world'];
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
    creatable: held['creatable'] as boolean,
    takesInputs: held['takes_inputs'] as boolean,
    playback: held['playback'] as boolean,
    directedActions: held['directed_actions'] as boolean,
    modelDecisions: held['model_decisions'] as boolean,
    ownerModelChoice: held['owner_model_choice'] as boolean,
    presence: held['presence'] as boolean,
    savedWorld: held['saved_world'] as boolean,
    stateFamily: held['state_family'] as SocietyStateFamily,
    populationMinimum: population['minimum'] as number,
    populationMaximum: population['maximum'] as number,
  });
}

/**
 * The engine a saved world's new society takes instead of its ground's where its version holds a
 * thing its author placed and the host offers societies of things, over the society grounds named
 * (the society ground catalog's keys). The table's third version states it; the second does not.
 */
export interface HoldingThings {
  readonly engine: SocietyEngineProfile;
  readonly grounds: readonly string[];
}

export interface EngineTable {
  readonly engines: readonly SocietyEngine[];
  readonly defaultEngine: SocietyEngineProfile;
  readonly creates: Readonly<Record<SocietyGroundKind, SocietyEngineProfile>>;
  readonly holdingThings: HoldingThings | null;
}

const PROFILES = ['exulanica.society-engines/v2', 'exulanica.society-engines/v3'];

function holdingThings(value: unknown, engines: readonly SocietyEngine[]): HoldingThings {
  const held = value as Readonly<Record<string, unknown>> | null;
  const engine = engines.find((row) => row.engine === held?.['engine']);
  const grounds = held?.['grounds'];
  if (held === null || typeof held !== 'object' || engine === undefined || !engine.creatable ||
      !engine.savedWorld || engine.stateFamily !== 'things' || !Array.isArray(grounds) ||
      grounds.length === 0 || !grounds.every((ground) => typeof ground === 'string') ||
      grounds.join() !== [...new Set(grounds as string[])].sort().join()) {
    throw new Error('Invalid society engine table creates_holding_things');
  }
  return Object.freeze({ engine: engine.engine, grounds: Object.freeze([...(grounds as string[])]) });
}

/** Read one version of the engine table, the second or the third, as this module reads its own. */
export function readEngineTable(text: string): EngineTable {
  const document = JSON.parse(text) as Readonly<Record<string, unknown>>;
  if (!PROFILES.includes(document['profile'] as string) || !Array.isArray(document['engines'])) {
    throw new Error('Invalid society engine table');
  }
  const engines = Object.freeze(document['engines'].map(row));
  const creatable = (profile: unknown) => engines.find((engine) => engine.engine === profile && engine.creatable);
  if (creatable(document['default_engine']) === undefined) {
    throw new Error('Invalid society engine table default');
  }
  const stated = (document['creates'] ?? null) as Readonly<Record<string, { readonly engine?: unknown }>> | null;
  if (stated === null || typeof stated !== 'object' || Object.keys(stated).sort().join() !== GROUNDS.join()) {
    throw new Error('Invalid society engine table creates');
  }
  const creates = Object.fromEntries(GROUNDS.map((ground) => {
    const engine = creatable(stated[ground]?.engine);
    if (engine === undefined || (SAVED_WORLD_GROUNDS.includes(ground) && !engine.savedWorld)) {
      throw new Error(`Invalid society engine table creates.${ground}`);
    }
    return [ground, engine.engine];
  })) as Record<SocietyGroundKind, SocietyEngineProfile>;
  const holding = document['creates_holding_things'];
  if (holding !== undefined && document['profile'] !== 'exulanica.society-engines/v3') {
    throw new Error('Invalid society engine table creates_holding_things');
  }
  return {
    engines,
    defaultEngine: document['default_engine'] as SocietyEngineProfile,
    creates: Object.freeze(creates),
    holdingThings: holding === undefined ? null : holdingThings(holding, engines),
  };
}

const TABLE = readEngineTable(SOCIETY_ENGINES_V3_JSON);

/** Every engine, in the table's order. */
export const SOCIETY_ENGINES: readonly SocietyEngine[] = TABLE.engines;
/** The engine a society is created with when a request names none. */
export const DEFAULT_SOCIETY_ENGINE: SocietyEngineProfile = TABLE.defaultEngine;

/** The engine a new society over this kind of ground is created with, as the table states. */
export function engineCreatedOver(ground: SocietyGroundKind): SocietyEngineProfile {
  return TABLE.creates[ground];
}

/** The engine with this profile, or an error that names what was asked for. */
export function societyEngine(profile: unknown): SocietyEngine {
  const engine = SOCIETY_ENGINES.find((held) => held.engine === profile);
  if (engine === undefined) throw new Error(`Unknown society engine ${JSON.stringify(profile)}`);
  return engine;
}
