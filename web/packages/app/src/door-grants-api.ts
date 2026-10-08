/**
 * What each program let into a world says it is, in its own words (`GET /door/grants?world_id=`):
 * every grant issued in the world, newest first, with the `declared` its program gave at its last
 * hello (`{name, maker, mind?}`), or null where it gave none. An outside agent's mark names it by
 * that name (`composition/thing-marks.ts`); the words are the program's own, so they are set as
 * text only, and a grant that says nothing leaves its visitor's pill saying `agent`.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import { openWorldPath } from './world-scope.js';

export const DOOR_GRANTS_PATH = '/door/grants';

/** What a program says it is, as its last hello said: words for a person reading a mark or card. */
export interface DeclaredSelf {
  readonly name: string;
  readonly maker: string;
  readonly mind: string | null;
}

export interface DoorGrant {
  readonly grantId: string;
  readonly bridge: string;
  readonly declared: DeclaredSelf | null;
}

const record = (value: unknown): Readonly<Record<string, unknown>> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};

function words(value: unknown, what: string): string {
  if (typeof value !== 'string' || value.trim() === '') throw new TypeError(`A grant's declaration needs ${what} in words`);
  return value;
}

function declaredOf(value: unknown): DeclaredSelf | null {
  if (value === null || value === undefined) return null;
  const held = record(value);
  const mind = held['mind'];
  return Object.freeze({
    name: words(held['name'], 'a name'),
    maker: words(held['maker'], 'a maker'),
    mind: mind === null || mind === undefined ? null : words(mind, 'a mind'),
  });
}

/** Read the world's grants, refusing a row that does not name its grant and bridge. */
export function parseDoorGrants(value: unknown): readonly DoorGrant[] {
  const rows = record(value)['grants'];
  if (!Array.isArray(rows)) throw new TypeError('The world\'s grants are not a list');
  return Object.freeze(rows.map((row: unknown) => {
    const entry = record(row);
    return Object.freeze({
      grantId: words(entry['grant_id'], 'its id'),
      bridge: words(entry['bridge'], 'its bridge'),
      declared: declaredOf(entry['declared']),
    });
  }));
}

export interface DoorGrantsClientOptions extends TransportOptions {
  /** The open world whose grants are read; null where none is open, which sends nothing. */
  readonly worldId: string | null;
}

export class DoorGrantsClient {
  readonly #transport: Transport;
  readonly #worldId: string | null;

  constructor(options: DoorGrantsClientOptions) {
    this.#transport = new Transport(options);
    this.#worldId = options.worldId;
  }

  /** The world's grants, by grant id. */
  async read(): Promise<ReadonlyMap<string, DoorGrant>> {
    const path = openWorldPath(DOOR_GRANTS_PATH, this.#worldId, 'the programs let into this world');
    const grants = parseDoorGrants(await this.#transport.getJson<unknown>(path));
    return new Map(grants.map((grant) => [grant.grantId, grant]));
  }
}
