/**
 * What a world says it can do: the capability descriptors the server projects for one version.
 *
 * Speaks `GET /world/versions/{version_id}/capabilities?world_id=` (profile
 * `exulanica.world-capabilities/v1`, `exulanica/api/routes/capabilities.py`). Each descriptor names
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

export interface WorldCapabilities {
  readonly worldId: string;
  readonly versionId: string;
  readonly kind: string;
  readonly societyHeld: boolean;
  readonly societyEngine: string | null;
  readonly operations: readonly CapabilityDescriptor[];
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

  async version(versionId: string): Promise<WorldCapabilities> {
    const path = openWorldPath(
      `/world/versions/${encodeURIComponent(versionId)}/capabilities`, this.#worldId, 'capabilities to read',
    );
    return parseWorldCapabilities(await this.#transport.getJson<unknown>(path));
  }
}
