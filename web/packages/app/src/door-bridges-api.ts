/**
 * The bridges this deployment's door offers the signed-in workspace, in words, and whether an AI
 * runs each (`GET /door/bridges`). A visitor's mark is decided from the entry of the bridge it
 * crossed through (`composition/thing-marks.ts`): an AI agent's bridge marks it AI, a game's names
 * where it came from, and a bridge the door does not list here is never guessed either way.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';

export const DOOR_BRIDGES_PATH = '/door/bridges';

/** One bridge as the door lists it. */
export interface DoorBridge {
  readonly bridge: string;
  readonly label: string;
  readonly game: string;
  /** Who runs its program: a shared game server, or the world's owner on their own machine. */
  readonly runBy: 'server' | 'owner';
  /** Whether what it brings in is run by an AI (an agent) rather than a person playing a game. */
  readonly ai: boolean;
}

function words(value: unknown, field: string): string {
  if (typeof value !== 'string' || value.trim() === '') throw new TypeError(`A door bridge needs ${field} in words`);
  return value;
}

/** Read the door's list, refusing an entry that does not say what it is and whether an AI runs it. */
export function parseDoorBridges(value: unknown): readonly DoorBridge[] {
  const rows = typeof value === 'object' && value !== null ? (value as { bridges?: unknown }).bridges : undefined;
  if (!Array.isArray(rows)) throw new TypeError('The door\'s bridges are not a list');
  return Object.freeze(rows.map((row: unknown) => {
    if (typeof row !== 'object' || row === null) throw new TypeError('A door bridge is not an entry');
    const entry = row as Record<string, unknown>;
    const runBy = entry['run_by'];
    if (runBy !== 'server' && runBy !== 'owner') throw new TypeError('A door bridge needs who runs it');
    if (typeof entry['ai'] !== 'boolean') throw new TypeError('A door bridge needs whether an AI runs it');
    return Object.freeze({
      bridge: words(entry['bridge'], 'its key'),
      label: words(entry['label'], 'a label'),
      game: words(entry['game'], 'its game'),
      runBy,
      ai: entry['ai'],
    });
  }));
}

export class DoorBridgesClient {
  readonly #transport: Transport;

  constructor(options: TransportOptions) {
    this.#transport = new Transport(options);
  }

  /** The bridges offered here, by key. */
  async read(): Promise<ReadonlyMap<string, DoorBridge>> {
    const bridges = parseDoorBridges(await this.#transport.getJson<unknown>(DOOR_BRIDGES_PATH));
    return new Map(bridges.map((bridge) => [bridge.bridge, bridge]));
  }
}
