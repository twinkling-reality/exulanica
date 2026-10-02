/**
 * What a world says it can do: the capability descriptors the server projects for one version.
 *
 * Speaks `GET /world/versions/{version_id}/capabilities?world_id=` (profile
 * `exulanica.world-capabilities/v1`, `exulanica/api/routes/capabilities.py`), and for making a
 * world, which needs no open world, `GET /worlds/capabilities` (`exulanica.world-creation/v1`). Each descriptor names
 * an operation by its route key ("METHOD /path/template"), whether the caller's grant permits it,
 * its state (`available`, `unavailable`, `unsupported`, `unknown`) with a code for any state but
 * available, whether it spends, its preview and its effects. The interface reads availability from
 * here and never guesses it; the descriptor is advice, and the operation itself still decides.
 *
 * The contract is additive: unknown members are ignored, and an unknown state is read as
 * `unknown` rather than refused, so a newer server never blanks the interface.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import { openWorldPath } from './world-scope.js';

export type DescriptorState = 'available' | 'unavailable' | 'unsupported' | 'unknown';

export interface CapabilityEffect {
  readonly on: string;
  readonly state: DescriptorState;
  readonly code: string | null;
}

export interface CapabilityDescriptor {
  /** The route key, e.g. "POST /world/versions/{version_id}/objects". */
  readonly operation: string;
  readonly bind: Readonly<Record<string, string>>;
  readonly permitted: boolean;
  readonly state: DescriptorState;
  readonly code: string | null;
  readonly subject: string | null;
  readonly preview: { readonly operation: string; readonly required: boolean } | null;
  readonly writes: boolean;
  readonly spends: boolean;
  readonly effects: readonly CapabilityEffect[];
  readonly dependencies: readonly CapabilityEffect[];
}

export interface WorldCapabilities extends OperationDescriptors {
  readonly worldId: string;
  readonly versionId: string;
  readonly kind: string;
  readonly societyHeld: boolean;
  readonly societyEngine: string | null;
}

const STATES: readonly DescriptorState[] = ['available', 'unavailable', 'unsupported', 'unknown'];

const record = (value: unknown, what: string): Record<string, unknown> => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`Invalid capability read: ${what}`);
  }
  return value as Record<string, unknown>;
};
const text = (value: unknown, what: string): string => {
  if (typeof value !== 'string' || value.length === 0) throw new TypeError(`Invalid capability read: ${what}`);
  return value;
};
const nullableText = (value: unknown): string | null => (typeof value === 'string' && value.length > 0 ? value : null);
const state = (value: unknown): DescriptorState =>
  (STATES as readonly unknown[]).includes(value) ? value as DescriptorState : 'unknown';

function parseEffect(value: unknown): CapabilityEffect {
  const row = record(value, 'effect');
  return Object.freeze({
    on: text(row['on'] ?? row['component'], 'effect subject'),
    state: state(row['state']),
    code: nullableText(row['code']),
  });
}

export function parseDescriptor(value: unknown): CapabilityDescriptor {
  const row = record(value, 'descriptor');
  const bindRow = row['bind'] === null || row['bind'] === undefined ? {} : record(row['bind'], 'bind');
  const bind: Record<string, string> = {};
  for (const [key, bound] of Object.entries(bindRow)) if (typeof bound === 'string') bind[key] = bound;
  const preview = row['preview'] === null || row['preview'] === undefined ? null : record(row['preview'], 'preview');
  return Object.freeze({
    operation: text(row['operation'], 'operation'),
    bind: Object.freeze(bind),
    permitted: row['permitted'] === true,
    state: state(row['state']),
    code: nullableText(row['code']),
    subject: nullableText(row['subject']),
    preview: preview === null ? null : Object.freeze({
      operation: text(preview['operation'], 'preview operation'),
      required: preview['required'] === true,
    }),
    writes: row['writes'] === true,
    spends: row['spends'] === true,
    effects: Object.freeze((Array.isArray(row['effects']) ? row['effects'] : []).map(parseEffect)),
    dependencies: Object.freeze((Array.isArray(row['dependencies']) ? row['dependencies'] : []).map(parseEffect)),
  });
}

export function parseWorldCapabilities(value: unknown): WorldCapabilities {
  const row = record(value, 'body');
  if (row['profile'] !== 'exulanica.world-capabilities/v1') {
    throw new TypeError('Invalid capability read: profile');
  }
  const society = row['society'] === null || row['society'] === undefined ? {} : record(row['society'], 'society');
  const operations = row['operations'];
  if (!Array.isArray(operations)) throw new TypeError('Invalid capability read: operations');
  return Object.freeze({
    worldId: text(row['world_id'], 'world id'),
    versionId: text(row['version_id'], 'version id'),
    kind: text(row['kind'], 'kind'),
    societyHeld: society['held'] === true,
    societyEngine: nullableText(society['engine']),
    operations: Object.freeze(operations.map(parseDescriptor)),
  });
}

/** Descriptors an action reads its availability from: one version's, a workspace's, or both. */
export interface OperationDescriptors {
  readonly operations: readonly CapabilityDescriptor[];
}

/** How one kind of world is made in this workspace now (`GET /worlds/capabilities`). */
export interface WorldKindCreation {
  readonly kind: string;
  readonly held: number;
  readonly limit: number | null;
  /** The create's descriptor; null for a kind no client makes. */
  readonly create: CapabilityDescriptor | null;
}

/**
 * Whether each kind of world can be made now (profile `exulanica.world-creation/v1`). The create
 * descriptors are the same shape as a version's, so an action reads them the same way.
 */
export interface WorkspaceCreation extends OperationDescriptors {
  readonly kinds: readonly WorldKindCreation[];
}

export function parseWorkspaceCreation(value: unknown): WorkspaceCreation {
  const row = record(value, 'body');
  if (row['profile'] !== 'exulanica.world-creation/v1') {
    throw new TypeError('Invalid creation read: profile');
  }
  if (!Array.isArray(row['kinds'])) throw new TypeError('Invalid creation read: kinds');
  const kinds = row['kinds'].map((entry): WorldKindCreation => {
    const kind = record(entry, 'kind');
    return Object.freeze({
      kind: text(kind['kind'], 'kind name'),
      held: typeof kind['held'] === 'number' ? kind['held'] : 0,
      limit: typeof kind['limit'] === 'number' ? kind['limit'] : null,
      create: kind['create'] === null || kind['create'] === undefined ? null : parseDescriptor(kind['create']),
    });
  });
  return Object.freeze({
    kinds: Object.freeze(kinds),
    operations: Object.freeze(kinds.flatMap((kind) => (kind.create === null ? [] : [kind.create]))),
  });
}

export interface CapabilitiesClientOptions extends TransportOptions {
  readonly worldId: string | null;
}

export class CapabilitiesClient {
  readonly #transport: Transport;
  readonly #worldId: string | null;

  constructor(options: CapabilitiesClientOptions) {
    this.#transport = new Transport(options);
    this.#worldId = options.worldId;
  }

  /** Whether each kind of world can be made in this workspace now. Needs no open world. */
  async creation(): Promise<WorkspaceCreation> {
    return parseWorkspaceCreation(await this.#transport.getJson<unknown>('/worlds/capabilities'));
  }

  async version(versionId: string): Promise<WorldCapabilities> {
    const path = openWorldPath(
      `/world/versions/${encodeURIComponent(versionId)}/capabilities`, this.#worldId, 'capabilities to read',
    );
    return parseWorldCapabilities(await this.#transport.getJson<unknown>(path));
  }
}
