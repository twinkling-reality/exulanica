import type { LocalVec3 } from '../coords.js';
import type { ReconstructionRung } from '../rung.js';
import { moduleFormFailure, type WorldModuleForm } from './module-form.js';
import type { WorldModuleRole } from './module-role.js';

export type { WorldModuleRole } from './module-role.js';

/**
 * A module is a passive, inspectable building block. Intelligence belongs in the composer that
 * sees the whole world, not in hundreds of autonomous objects making local decisions.
 */
export type WorldCustomizationAxis =
  | 'geometry-variant'
  | 'material-family'
  | 'regional-accent'
  | 'detail-density'
  | 'atmosphere';

export type ModuleEvidenceRequirement =
  | 'none'
  | 'source-evidence'
  | 'reconstruction-asset';

export interface ModuleBounds {
  /** Foundational broad phase. Authored polygon/SDF bounds can replace it without changing IDs. */
  readonly radius: number;
  readonly height: number;
}

export interface ModuleSocket {
  readonly key: string;
  readonly local: LocalVec3;
  readonly yaw: number;
  readonly accepts: readonly WorldModuleRole[];
  readonly clearanceRadius: number;
}

export type ModuleCollisionContract =
  | { readonly kind: 'none' }
  | {
      readonly kind: 'circle';
      readonly radius: number;
      /** Collision never comes from points or splats. */
      readonly source: 'authored-proxy';
    }
  | {
      readonly kind: 'box';
      readonly halfWidth: number;
      readonly halfDepth: number;
      readonly source: 'authored-proxy';
    };

export interface ModuleNavigationContract {
  readonly surface: 'none' | 'walkable' | 'constrained';
  readonly maxSlopeDegrees: number;
  readonly minimumClearance: number;
  readonly requiredDestination: boolean;
}

export interface ModuleLodVariants {
  readonly stub: string;
  readonly proxy: string;
  readonly coarse: string;
  readonly full: string;
}

export interface ModuleAccessibilityContract {
  readonly interactive: boolean;
  /** Stable copy key. Null means the module inherits its semantic owner's accessible name. */
  readonly labelKey: string | null;
  readonly colorIsSoleCarrier: false;
}

export interface WorldModuleDefinition {
  readonly key: string;
  readonly version: number;
  readonly role: WorldModuleRole;
  readonly allowedRungs: 'any' | readonly ReconstructionRung[];
  readonly bounds: ModuleBounds;
  readonly sockets: readonly ModuleSocket[];
  readonly collision: ModuleCollisionContract;
  readonly navigation: ModuleNavigationContract;
  readonly lod: ModuleLodVariants;
  readonly accessibility: ModuleAccessibilityContract;
  readonly evidence: ModuleEvidenceRequirement;
  /** Safe semantic fallback, used when a renderer asset or old catalog entry is unavailable. */
  readonly fallbackKey: string | null;
  /**
   * The canonical module this one may stand in for, or null if it is itself canonical.
   *
   * A recipe names one canonical module per slot. The composer fills that slot from the canonical
   * and everything declaring itself a variant of it, so widening a world is a catalog edit rather
   * than a composer edit: nothing has to learn that a new module exists. A variant must be
   * substitutable, which the registry enforces rather than documents (same role, evidence
   * requirement and permitted rungs, and at least the canonical's sockets), so a recipe written
   * against the canonical cannot be broken by a variant it has never heard of.
   */
  readonly variantOf: string | null;
  /**
   * What this module is built as, or null to let the world style decide.
   *
   * Declaring a form is how a catalog entry carries its own visual meaning instead of leaving it
   * in a renderer branch. Null keeps the historical behaviour, where the active world style picks
   * one form for every module of a role at once.
   */
  readonly form: WorldModuleForm | null;
  readonly customization: readonly WorldCustomizationAxis[];
}

const KEY = /^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$/;

const finiteNonNegative = (value: number): boolean => Number.isFinite(value) && value >= 0;

function assertKey(value: string, label: string): void {
  if (!KEY.test(value)) throw new TypeError(`${label} must be a stable dotted key: ${value}`);
}

function assertDefinition(definition: WorldModuleDefinition): void {
  assertKey(definition.key, 'module key');
  if (!Number.isSafeInteger(definition.version) || definition.version < 1) {
    throw new TypeError(`module version must be a positive safe integer: ${definition.key}`);
  }
  if (!finiteNonNegative(definition.bounds.radius) || !finiteNonNegative(definition.bounds.height)) {
    throw new TypeError(`module bounds must be finite and non-negative: ${definition.key}`);
  }
  if (
    !finiteNonNegative(definition.navigation.maxSlopeDegrees) ||
    definition.navigation.maxSlopeDegrees > 90 ||
    !finiteNonNegative(definition.navigation.minimumClearance)
  ) {
    throw new TypeError(`module navigation contract is invalid: ${definition.key}`);
  }
  const socketKeys = new Set<string>();
  for (const socket of definition.sockets) {
    assertKey(socket.key, `socket key on ${definition.key}`);
    if (socketKeys.has(socket.key)) {
      throw new TypeError(`duplicate socket ${socket.key} on ${definition.key}`);
    }
    socketKeys.add(socket.key);
    if (
      !Number.isFinite(socket.local.x) ||
      !Number.isFinite(socket.local.y) ||
      !Number.isFinite(socket.local.z) ||
      !Number.isFinite(socket.yaw) ||
      !finiteNonNegative(socket.clearanceRadius) ||
      socket.accepts.length === 0
    ) {
      throw new TypeError(`socket ${socket.key} on ${definition.key} is invalid`);
    }
  }
  if (definition.allowedRungs !== 'any') {
    const rungs = new Set(definition.allowedRungs);
    if (rungs.size !== definition.allowedRungs.length) {
      throw new TypeError(`module ${definition.key} repeats an allowed reconstruction rung`);
    }
  }
  const collision = definition.collision;
  if (
    (collision.kind === 'circle' && !finiteNonNegative(collision.radius)) ||
    (collision.kind === 'box' &&
      (!finiteNonNegative(collision.halfWidth) || !finiteNonNegative(collision.halfDepth)))
  ) {
    throw new TypeError(`module collision contract is invalid: ${definition.key}`);
  }
  for (const value of Object.values(definition.lod)) {
    if (value.length === 0) throw new TypeError(`module LOD variants must be named: ${definition.key}`);
  }
  const formFailure = moduleFormFailure(definition.role, definition.form);
  if (formFailure !== null) throw new TypeError(`module ${definition.key}: ${formFailure}`);
  if (definition.variantOf !== null) {
    assertKey(definition.variantOf, `variant target on ${definition.key}`);
    if (definition.variantOf === definition.key) {
      throw new TypeError(`module ${definition.key} cannot be a variant of itself`);
    }
  }
}

/** Why `candidate` may not stand in for `canonical`, or null when it may. */
function substitutionFailure(
  canonical: WorldModuleDefinition,
  candidate: WorldModuleDefinition,
): string | null {
  if (candidate.role !== canonical.role) return `role ${candidate.role} does not match ${canonical.role}`;
  if (candidate.evidence !== canonical.evidence) {
    return `evidence requirement ${candidate.evidence} does not match ${canonical.evidence}`;
  }
  const rungs = (value: WorldModuleDefinition): string =>
    value.allowedRungs === 'any' ? 'any' : [...value.allowedRungs].sort().join(',');
  if (rungs(candidate) !== rungs(canonical)) {
    return `permitted rungs ${rungs(candidate)} do not match ${rungs(canonical)}`;
  }
  if (
    candidate.navigation.surface !== canonical.navigation.surface ||
    candidate.navigation.requiredDestination !== canonical.navigation.requiredDestination
  ) {
    return 'navigation contract does not match';
  }
  for (const socket of canonical.sockets) {
    const replacement = candidate.sockets.find((value) => value.key === socket.key);
    if (replacement === undefined) return `socket ${socket.key} is missing`;
    const missing = socket.accepts.filter((role) => !replacement.accepts.includes(role));
    if (missing.length > 0) return `socket ${socket.key} stops accepting ${missing.join(', ')}`;
  }
  return null;
}

/** Immutable versioned catalog with attachment and fallback validation. */
export class WorldModuleRegistry {
  readonly version: number;
  readonly definitions: readonly WorldModuleDefinition[];
  readonly #byKey: ReadonlyMap<string, WorldModuleDefinition>;
  readonly #pools: ReadonlyMap<string, readonly WorldModuleDefinition[]>;

  constructor(version: number, definitions: readonly WorldModuleDefinition[]) {
    if (!Number.isSafeInteger(version) || version < 1) {
      throw new TypeError('module catalog version must be a positive safe integer');
    }
    const byKey = new Map<string, WorldModuleDefinition>();
    for (const source of definitions) {
      assertDefinition(source);
      if (byKey.has(source.key)) throw new TypeError(`duplicate module key: ${source.key}`);
      const definition = Object.freeze({
        ...source,
        bounds: Object.freeze({ ...source.bounds }),
        sockets: Object.freeze(source.sockets.map((socket) => Object.freeze({
          ...socket,
          accepts: Object.freeze([...socket.accepts]),
        }))),
        navigation: Object.freeze({ ...source.navigation }),
        collision: Object.freeze({ ...source.collision }),
        lod: Object.freeze({ ...source.lod }),
        accessibility: Object.freeze({ ...source.accessibility }),
        customization: Object.freeze([...source.customization]),
        form: source.form === null ? null : Object.freeze({
          ...source.form,
          parameters: Object.freeze({ ...source.form.parameters }),
        }),
        allowedRungs:
          source.allowedRungs === 'any'
            ? 'any'
            : Object.freeze([...source.allowedRungs]),
      });
      byKey.set(definition.key, definition);
    }
    for (const definition of byKey.values()) {
      if (definition.fallbackKey !== null && !byKey.has(definition.fallbackKey)) {
        throw new TypeError(
          `module ${definition.key} has unknown fallback ${definition.fallbackKey}`,
        );
      }
      if (definition.fallbackKey === definition.key) {
        throw new TypeError(`module ${definition.key} cannot fall back to itself`);
      }
    }
    for (const definition of byKey.values()) {
      const seen = new Set<string>([definition.key]);
      let cursor = definition.fallbackKey;
      while (cursor !== null) {
        if (seen.has(cursor)) throw new TypeError(`module fallback cycle includes ${cursor}`);
        seen.add(cursor);
        cursor = byKey.get(cursor)!.fallbackKey;
      }
    }
    /*
     * Variants stay one level deep on purpose. A chain would make the substitutable set of a slot
     * depend on traversal order, which is exactly the kind of thing that is fine until a catalog
     * grows and then is impossible to reason about.
     */
    const pools = new Map<string, WorldModuleDefinition[]>();
    for (const definition of byKey.values()) pools.set(definition.key, [definition]);
    for (const definition of byKey.values()) {
      if (definition.variantOf === null) continue;
      const canonical = byKey.get(definition.variantOf);
      if (canonical === undefined) {
        throw new TypeError(`module ${definition.key} varies unknown module ${definition.variantOf}`);
      }
      if (canonical.variantOf !== null) {
        throw new TypeError(
          `module ${definition.key} varies ${canonical.key}, which is itself a variant`,
        );
      }
      const failure = substitutionFailure(canonical, definition);
      if (failure !== null) {
        throw new TypeError(
          `module ${definition.key} cannot stand in for ${canonical.key}: ${failure}`,
        );
      }
      pools.get(canonical.key)!.push(definition);
      pools.delete(definition.key);
    }
    this.version = version;
    this.definitions = Object.freeze([...byKey.values()]);
    this.#byKey = byKey;
    // Canonical first, then variants by key, so a pool's order never depends on catalog order.
    this.#pools = new Map(
      [...pools].map(([key, pool]) => [
        key,
        Object.freeze([
          pool[0]!,
          ...pool.slice(1).sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0)),
        ]),
      ]),
    );
    Object.freeze(this);
  }

  /**
   * Every module that may fill a slot naming `key`, canonical first.
   *
   * A key that is itself a variant has no pool of its own: it is reachable only through the
   * canonical it stands in for, so a recipe cannot name a variant directly and quietly narrow
   * the world back down to one shape.
   */
  variantsOf(key: string): readonly WorldModuleDefinition[] {
    const pool = this.#pools.get(key);
    if (pool === undefined) return Object.freeze([this.get(key)]);
    return pool;
  }

  get(key: string): WorldModuleDefinition {
    const found = this.#byKey.get(key);
    if (found === undefined) throw new TypeError(`unknown world module: ${key}`);
    return found;
  }

  has(key: string): boolean {
    return this.#byKey.has(key);
  }

  assertAttachment(parentKey: string, socketKey: string, childKey: string): ModuleSocket {
    const parent = this.get(parentKey);
    const child = this.get(childKey);
    const socket = parent.sockets.find((candidate) => candidate.key === socketKey);
    if (socket === undefined) {
      throw new TypeError(`module ${parentKey} has no attachment socket ${socketKey}`);
    }
    if (!socket.accepts.includes(child.role)) {
      throw new TypeError(
        `socket ${parentKey}.${socketKey} does not accept role ${child.role} from ${childKey}`,
      );
    }
    return socket;
  }
}
