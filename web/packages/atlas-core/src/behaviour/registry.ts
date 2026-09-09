/**
 * The behaviour registry: what an authored object is allowed to do, declared once.
 *
 * product-direction.md's first milestone asks for "one interaction": trigger, stop and reset a
 * supported motion, with "unsupported behaviour fails visibly". Subsequent milestone 3 names the
 * general shape as "an explicit behavior registry, triggers, runtime state, restart rules, and
 * supported motion".
 *
 * So this is a registry with EXACTLY ONE ENTRY, and that is the point rather than a shortcut. A
 * registry with one behaviour and a refusal path for every other id is an honest statement about
 * what the runtime supports. A registry with a permissive fallback would let an object carry
 * `behaviourId: "walk"` and render as motionless while the interface said nothing, which is the
 * failure the milestone names. `resolve` therefore returns a REFUSAL rather than throwing or
 * substituting: the caller has a status line to write it into, and a thrown error at load time
 * would take the object's geometry down with its behaviour.
 *
 * Parameters are clamped to DECLARED ranges rather than validated against a hard-coded constant
 * buried in an evaluator. The range is part of the definition, the clamp reports what it changed,
 * and a value that is not a finite number is refused rather than silently corrected to a bound:
 * clamping `NaN` to `max` would invent an amplitude the author never wrote.
 *
 * Nothing here is metric. The amplitude is expressed in the region's display units, which
 * `display-frame.ts` places at walking scale and explicitly marks `metric: false`.
 */

/** The declared axes. A behaviour parameter naming anything else is unsupported, not clamped. */
export type MotionAxis = 'x' | 'y' | 'z';

export const MOTION_AXES: readonly MotionAxis[] = Object.freeze(['x', 'y', 'z']);

/** A closed interval and the value used when an author supplies none. */
export interface BehaviourRange {
  readonly min: number;
  readonly max: number;
  readonly fallback: number;
}

export interface BoundedMotionRanges {
  /** Peak displacement from the authored position, in region display units. */
  readonly amplitude: BehaviourRange;
  /** Seconds for one full there-and-back cycle. */
  readonly period: BehaviourRange;
}

export interface BehaviourDefinition {
  readonly behaviourId: string;
  readonly version: number;
  /** Stable copy key. The surface owns the words; the registry owns the identity. */
  readonly labelKey: string;
  readonly axes: readonly MotionAxis[];
  readonly ranges: BoundedMotionRanges;
  /** Trigger, stop and reset. Named here so a surface cannot offer a control the runtime lacks. */
  readonly controls: readonly ['trigger', 'stop', 'reset'];
  /** Reset returns the object to the transform its author placed, bit for bit. */
  readonly resetIsExact: true;
}

/** The parameters an authored object carries for the one supported behaviour. */
export interface BoundedMotionParameters {
  readonly axis: MotionAxis;
  readonly amplitude: number;
  readonly period: number;
}

export type BehaviourResolution =
  | { readonly ok: true; readonly definition: BehaviourDefinition }
  | { readonly ok: false; readonly reason: string };

export type BehaviourParameterResolution =
  | {
      readonly ok: true;
      readonly parameters: BoundedMotionParameters;
      /** Parameter names moved onto a declared bound, in declaration order. Empty when none were. */
      readonly clamped: readonly string[];
    }
  | { readonly ok: false; readonly reason: string };

/** The one supported behaviour. Its id is what a persisted object stores. */
export const BOUNDED_MOTION_ID = 'motion.bounded';

const BEHAVIOUR_ID = /^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$/;

function assertRange(range: BehaviourRange, label: string): void {
  if (![range.min, range.max, range.fallback].every((value) => Number.isFinite(value))) {
    throw new TypeError(`${label} range must be finite`);
  }
  if (range.min > range.max) throw new TypeError(`${label} range is inverted`);
  if (range.fallback < range.min || range.fallback > range.max) {
    throw new TypeError(`${label} fallback lies outside its own range`);
  }
}

function assertDefinition(definition: BehaviourDefinition): void {
  if (!BEHAVIOUR_ID.test(definition.behaviourId)) {
    throw new TypeError(`behaviour id must be a stable dotted key: ${definition.behaviourId}`);
  }
  if (!Number.isSafeInteger(definition.version) || definition.version < 1) {
    throw new TypeError(`behaviour version must be a positive safe integer: ${definition.behaviourId}`);
  }
  if (definition.labelKey.length === 0) {
    throw new TypeError(`behaviour ${definition.behaviourId} must carry a copy key`);
  }
  if (definition.axes.length === 0 || new Set(definition.axes).size !== definition.axes.length) {
    throw new TypeError(`behaviour ${definition.behaviourId} declares no distinct axes`);
  }
  assertRange(definition.ranges.amplitude, `${definition.behaviourId} amplitude`);
  assertRange(definition.ranges.period, `${definition.behaviourId} period`);
  if (definition.ranges.period.min <= 0) {
    throw new TypeError(`behaviour ${definition.behaviourId} must declare a positive minimum period`);
  }
}

function freezeDefinition(source: BehaviourDefinition): BehaviourDefinition {
  return Object.freeze({
    ...source,
    axes: Object.freeze([...source.axes]),
    controls: Object.freeze([...source.controls]) as BehaviourDefinition['controls'],
    ranges: Object.freeze({
      amplitude: Object.freeze({ ...source.ranges.amplitude }),
      period: Object.freeze({ ...source.ranges.period }),
    }),
  });
}

function clampTo(range: BehaviourRange, value: number): number {
  return Math.min(range.max, Math.max(range.min, value));
}

/** Immutable versioned catalog of supported behaviours, with a refusal for everything else. */
export class BehaviourRegistry {
  readonly version: number;
  readonly definitions: readonly BehaviourDefinition[];
  readonly #byId: ReadonlyMap<string, BehaviourDefinition>;

  constructor(version: number, definitions: readonly BehaviourDefinition[]) {
    if (!Number.isSafeInteger(version) || version < 1) {
      throw new TypeError('behaviour catalog version must be a positive safe integer');
    }
    const byId = new Map<string, BehaviourDefinition>();
    for (const source of definitions) {
      assertDefinition(source);
      if (byId.has(source.behaviourId)) {
        throw new TypeError(`duplicate behaviour id: ${source.behaviourId}`);
      }
      byId.set(source.behaviourId, freezeDefinition(source));
    }
    this.version = version;
    this.definitions = Object.freeze([...byId.values()]);
    this.#byId = byId;
    Object.freeze(this);
  }

  has(behaviourId: string): boolean {
    return this.#byId.has(behaviourId);
  }

  /**
   * Look an id up, and say why when it is not there.
   *
   * The refusal names the supported ids because the alternative sentence a status line could
   * write is "that behaviour is not supported", which tells a person nothing about what is.
   */
  resolve(behaviourId: string): BehaviourResolution {
    const definition = this.#byId.get(behaviourId);
    if (definition !== undefined) return Object.freeze({ ok: true, definition });
    const supported = this.definitions.map((value) => value.behaviourId).join(', ');
    return Object.freeze({
      ok: false,
      reason:
        `“${behaviourId}” is not a supported behaviour. This build supports ${supported || 'no behaviours'}.`,
    });
  }

  /**
   * Read authored parameters against a definition's declared ranges.
   *
   * An unknown axis is a refusal, not a substitution: a bob the author wrote as vertical must
   * never quietly become horizontal. A number outside a declared bound IS clamped, and the names
   * of the clamped parameters come back so the confirmation surface can say what it changed
   * before anything is written.
   */
  readParameters(behaviourId: string, source: unknown): BehaviourParameterResolution {
    const resolved = this.resolve(behaviourId);
    if (!resolved.ok) return Object.freeze({ ok: false, reason: resolved.reason });
    const definition = resolved.definition;
    if (typeof source !== 'object' || source === null || Array.isArray(source)) {
      return Object.freeze({ ok: false, reason: 'Behaviour parameters must be an object.' });
    }
    const record = source as Record<string, unknown>;

    const axis = record['axis'];
    if (typeof axis !== 'string' || !definition.axes.includes(axis as MotionAxis)) {
      return Object.freeze({
        ok: false,
        reason:
          `“${String(axis)}” is not a supported motion axis. ` +
          `${definition.behaviourId} moves along ${definition.axes.join(', ')}.`,
      });
    }

    const clamped: string[] = [];
    const read = (key: 'amplitude' | 'period', range: BehaviourRange): number | null => {
      const raw = record[key];
      if (raw === undefined || raw === null) return range.fallback;
      if (typeof raw !== 'number' || !Number.isFinite(raw)) return null;
      const value = clampTo(range, raw);
      if (value !== raw) clamped.push(key);
      return value;
    };

    const amplitude = read('amplitude', definition.ranges.amplitude);
    if (amplitude === null) {
      return Object.freeze({ ok: false, reason: 'Behaviour amplitude must be a finite number.' });
    }
    const period = read('period', definition.ranges.period);
    if (period === null) {
      return Object.freeze({ ok: false, reason: 'Behaviour period must be a finite number.' });
    }

    return Object.freeze({
      ok: true,
      parameters: Object.freeze({ axis: axis as MotionAxis, amplitude, period }),
      clamped: Object.freeze(clamped),
    });
  }
}

/**
 * The shipped catalog. One behaviour, and the bounds it is allowed inside.
 *
 * The numbers are DECISIONS and they are here rather than in the evaluator so that changing what
 * an object may do is one edit to a declaration a test can read. A 2-unit amplitude is about the
 * reach of a standing person at the display frame's walking scale; half a second is the shortest
 * period that still reads as motion rather than a flicker, and twenty seconds the longest that
 * still reads as motion rather than as drift.
 */
export const BEHAVIOUR_REGISTRY = new BehaviourRegistry(1, [
  {
    behaviourId: BOUNDED_MOTION_ID,
    version: 1,
    labelKey: 'behaviour.motion.bounded',
    axes: MOTION_AXES,
    ranges: {
      amplitude: { min: 0, max: 2, fallback: 0.35 },
      period: { min: 0.5, max: 20, fallback: 4 },
    },
    controls: ['trigger', 'stop', 'reset'],
    resetIsExact: true,
  },
]);
