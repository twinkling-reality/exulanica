/**
 * The behaviour registry, as the renderer's mirror of a reviewed server catalog.
 *
 * `docs/world-objects-contract.md` section 3 puts the authority in migration 0042's
 * `world_object_behaviour_registry`: a behaviour is a `behaviour_key` plus a `behaviour_version`
 * plus parameters, and "an unknown key, an unknown version, an unknown parameter, a missing
 * parameter, a wrong kind, and an out-of-range value all fail closed with `invalid_object_data`".
 *
 * So this file is NOT a second authority. It is the list of behaviours this renderer can actually
 * run, declared in the same vocabulary the server declares its own, and it exists because the
 * server can admit a behaviour a browser build has not shipped the code for. The contract draws
 * the line in one sentence: "the registry bounds the path, and the renderer owns the controls."
 * The bounds below are therefore copied from the seeded row and must not drift from it; the
 * trigger, stop and reset that act on them live in `bounded-motion.ts` and are not stored at all.
 *
 * **Everything fails closed, and the refusal carries words.** product-direction.md's first
 * milestone requires that unsupported behaviour "fails visibly", so `resolve` and `readParameters`
 * return a reason a status line can print rather than throwing or substituting a default. An
 * object whose behaviour this build cannot run is still a real object with verified geometry: the
 * caller is expected to draw it and report the refusal, not to hide the object behind it.
 *
 * **Parameter kinds mirror the server's three.** The contract says a parameter is "`integer` with
 * an inclusive minimum and maximum, `choice` over at least two values, or `toggle`". All three are
 * modelled here even though the one seeded behaviour uses only the first two, because a registry
 * that could not express the third would quietly reinterpret it the day one arrives.
 */

/** The parameter kinds migration 0042's registry rows may declare. */
export type BehaviourParameterDescriptor =
  | {
      readonly kind: 'integer';
      readonly minimum: number;
      readonly maximum: number;
      readonly default: number;
    }
  | {
      readonly kind: 'choice';
      readonly choices: readonly string[];
      readonly default: string;
    }
  | { readonly kind: 'toggle'; readonly default: boolean };

export type BehaviourParameters = Readonly<Record<string, number | string | boolean>>;

export interface BehaviourDefinition {
  readonly behaviourKey: string;
  readonly behaviourVersion: number;
  readonly summary: string;
  readonly parameters: Readonly<Record<string, BehaviourParameterDescriptor>>;
  /** Trigger, stop and reset. Owned by the runtime, named here so a surface cannot invent a fourth. */
  readonly controls: readonly ['trigger', 'stop', 'reset'];
  /** Reset returns the object to the transform its author placed, bit for bit. */
  readonly resetIsExact: true;
}

export type BehaviourResolution =
  | { readonly ok: true; readonly definition: BehaviourDefinition }
  | { readonly ok: false; readonly reason: string };

export type BehaviourParameterResolution =
  | {
      readonly ok: true;
      readonly parameters: BehaviourParameters;
      /** Parameter names moved onto a declared bound, in declaration order. Empty when none were. */
      readonly clamped: readonly string[];
    }
  | { readonly ok: false; readonly reason: string };

/** The one behaviour the first milestone names, and the one this renderer implements. */
export const BOUNDED_PATH_KEY = 'motion.bounded-path';
export const BOUNDED_PATH_VERSION = 1;

const KEY = /^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$/;

function assertDescriptor(name: string, descriptor: BehaviourParameterDescriptor, label: string): void {
  if (descriptor.kind === 'integer') {
    if (![descriptor.minimum, descriptor.maximum, descriptor.default].every(Number.isSafeInteger)) {
      throw new TypeError(`${label}.${name} bounds must be safe integers`);
    }
    if (descriptor.minimum > descriptor.maximum) throw new TypeError(`${label}.${name} range is inverted`);
    if (descriptor.default < descriptor.minimum || descriptor.default > descriptor.maximum) {
      throw new TypeError(`${label}.${name} default lies outside its own range`);
    }
    return;
  }
  if (descriptor.kind === 'choice') {
    // "choice over AT LEAST TWO values": a one-value choice is a constant wearing a control.
    if (descriptor.choices.length < 2 || new Set(descriptor.choices).size !== descriptor.choices.length) {
      throw new TypeError(`${label}.${name} must offer at least two distinct choices`);
    }
    if (!descriptor.choices.includes(descriptor.default)) {
      throw new TypeError(`${label}.${name} default is not one of its choices`);
    }
  }
}

function assertDefinition(definition: BehaviourDefinition): void {
  const label = `${definition.behaviourKey}@${definition.behaviourVersion}`;
  if (!KEY.test(definition.behaviourKey)) {
    throw new TypeError(`behaviour key must be a stable dotted key: ${definition.behaviourKey}`);
  }
  if (!Number.isSafeInteger(definition.behaviourVersion) || definition.behaviourVersion < 1) {
    throw new TypeError(`behaviour version must be a positive safe integer: ${label}`);
  }
  const names = Object.keys(definition.parameters);
  if (names.length === 0) throw new TypeError(`behaviour ${label} declares no parameters`);
  for (const name of names) assertDescriptor(name, definition.parameters[name]!, label);
}

function freeze(source: BehaviourDefinition): BehaviourDefinition {
  return Object.freeze({
    ...source,
    controls: Object.freeze([...source.controls]) as BehaviourDefinition['controls'],
    parameters: Object.freeze(Object.fromEntries(
      Object.entries(source.parameters).map(([name, descriptor]) => [
        name,
        Object.freeze(descriptor.kind === 'choice'
          ? { ...descriptor, choices: Object.freeze([...descriptor.choices]) }
          : { ...descriptor }),
      ]),
    )),
  });
}

const identify = (key: string, version: number): string => `${key}@${version}`;

/** Immutable catalog of the behaviours this build can run, with a refusal for everything else. */
export class BehaviourRegistry {
  readonly definitions: readonly BehaviourDefinition[];
  readonly #byKey: ReadonlyMap<string, BehaviourDefinition>;

  constructor(definitions: readonly BehaviourDefinition[]) {
    const byKey = new Map<string, BehaviourDefinition>();
    for (const source of definitions) {
      assertDefinition(source);
      const id = identify(source.behaviourKey, source.behaviourVersion);
      if (byKey.has(id)) throw new TypeError(`duplicate behaviour: ${id}`);
      byKey.set(id, freeze(source));
    }
    this.definitions = Object.freeze([...byKey.values()]);
    this.#byKey = byKey;
    Object.freeze(this);
  }

  has(behaviourKey: string, behaviourVersion: number): boolean {
    return this.#byKey.has(identify(behaviourKey, behaviourVersion));
  }

  /**
   * Look one up, and say why when this build cannot run it.
   *
   * The key and the VERSION are both part of the identity, because the server's registry is keyed
   * on both and a version bump is how a reviewed behaviour changes its parameters. Resolving
   * `motion.bounded-path@2` against the version 1 implementation would run yesterday's motion on
   * today's numbers.
   */
  resolve(behaviourKey: string, behaviourVersion: number): BehaviourResolution {
    const definition = this.#byKey.get(identify(behaviourKey, behaviourVersion));
    if (definition !== undefined) return Object.freeze({ ok: true, definition });
    const supported = this.definitions
      .map((value) => identify(value.behaviourKey, value.behaviourVersion))
      .join(', ');
    return Object.freeze({
      ok: false,
      reason:
        `“${identify(behaviourKey, behaviourVersion)}” is not a behaviour this build can run. `
        + `It runs ${supported || 'no behaviours'}.`,
    });
  }

  /**
   * Read authored parameters against a definition's declared descriptors.
   *
   * An unknown parameter name, a wrong kind and an unknown choice are REFUSALS, matching the
   * server's own fail-closed list: a motion the author wrote as vertical must never quietly become
   * horizontal, and a parameter this build ignores is a parameter whose effect nobody can see. An
   * integer outside its declared bound is CLAMPED instead, and the names of what moved come back
   * so the confirmation surface can say what it changed before anything is written. A missing
   * parameter takes the declared default, which is what the registry rows carry them for.
   */
  readParameters(
    behaviourKey: string,
    behaviourVersion: number,
    source: unknown,
  ): BehaviourParameterResolution {
    const resolved = this.resolve(behaviourKey, behaviourVersion);
    if (!resolved.ok) return Object.freeze({ ok: false, reason: resolved.reason });
    const definition = resolved.definition;
    if (typeof source !== 'object' || source === null || Array.isArray(source)) {
      return Object.freeze({ ok: false, reason: 'Behaviour parameters must be an object.' });
    }
    const record = source as Record<string, unknown>;

    for (const name of Object.keys(record)) {
      if (!(name in definition.parameters)) {
        return Object.freeze({
          ok: false,
          reason: `“${name}” is not a parameter of ${identify(behaviourKey, behaviourVersion)}.`,
        });
      }
    }

    const clamped: string[] = [];
    const parameters: Record<string, number | string | boolean> = {};
    for (const [name, descriptor] of Object.entries(definition.parameters)) {
      const raw = record[name];
      if (raw === undefined || raw === null) {
        parameters[name] = descriptor.default;
        continue;
      }
      if (descriptor.kind === 'integer') {
        if (typeof raw !== 'number' || !Number.isSafeInteger(raw)) {
          return Object.freeze({ ok: false, reason: `“${name}” must be a whole number.` });
        }
        const value = Math.min(descriptor.maximum, Math.max(descriptor.minimum, raw));
        if (value !== raw) clamped.push(name);
        parameters[name] = value;
      } else if (descriptor.kind === 'choice') {
        if (typeof raw !== 'string' || !descriptor.choices.includes(raw)) {
          return Object.freeze({
            ok: false,
            reason: `“${String(raw)}” is not a supported ${name}. `
              + `${identify(behaviourKey, behaviourVersion)} offers ${descriptor.choices.join(', ')}.`,
          });
        }
        parameters[name] = raw;
      } else {
        if (typeof raw !== 'boolean') {
          return Object.freeze({ ok: false, reason: `“${name}” must be true or false.` });
        }
        parameters[name] = raw;
      }
    }

    return Object.freeze({
      ok: true,
      parameters: Object.freeze(parameters),
      clamped: Object.freeze(clamped),
    });
  }
}

/**
 * What this build can run, copied from migration 0042's seeded row.
 *
 * The numbers are NOT decisions made here. They are the reviewed bounds, and the comment is the
 * whole reason this constant is allowed to exist: the server refuses anything outside them with
 * `invalid_object_data`, so a browser that offered a wider range would be building a control whose
 * every extreme is a round trip to a refusal.
 *
 *   travel_mm            integer 100 to 10000, default 1000
 *   period_milliseconds  integer 500 to 60000, default 4000
 *   axis                 choice x | y | z, default x
 *   easing               choice linear | smooth, default smooth
 */
export const BEHAVIOUR_REGISTRY = new BehaviourRegistry([
  {
    behaviourKey: BOUNDED_PATH_KEY,
    behaviourVersion: BOUNDED_PATH_VERSION,
    summary:
      'Bounded reversing travel along one axis, with renderer trigger, stop and reset controls.',
    parameters: {
      travel_mm: { kind: 'integer', minimum: 100, maximum: 10_000, default: 1000 },
      period_milliseconds: { kind: 'integer', minimum: 500, maximum: 60_000, default: 4000 },
      axis: { kind: 'choice', choices: ['x', 'y', 'z'], default: 'x' },
      easing: { kind: 'choice', choices: ['linear', 'smooth'], default: 'smooth' },
    },
    controls: ['trigger', 'stop', 'reset'],
    resetIsExact: true,
  },
]);
