/**
 * The looks chosen for the things of a version's society (`GET /world/versions/{id}/thing-looks`,
 * THINGS's look choice store): the latest choice for each thing, by its society id, with the
 * author's id where it was placed. A thing with no choice is absent and wears its kind's first look.
 * Every look listed is one the shipped library holds at that digest and fits the thing's kind,
 * which the store refuses otherwise; the library still holds each to its digest when it reads it.
 */

import { Transport, type TransportOptions } from '@exulanica/graph-client';
import type { Named } from '@exulanica/atlas-react/things';
import { openWorldPath } from './world-scope.js';

export const THING_LOOK_CHOICES_PROFILE = 'exulanica.thing-look-choices/v1';

export interface ThingLookChoice {
  /** The thing's society id: a placed being's or object's, or a visitor's arrival thing id. */
  readonly thingId: string;
  /** The author's id for a placed thing, or null for one that crossed in. */
  readonly placedId: string | null;
  readonly look: Named;
  readonly chosenBy: 'owner' | 'crossing';
  readonly chosenAt: string;
}

const DIGEST = /^[0-9a-f]{64}$/u;

function text(value: unknown, what: string): string {
  if (typeof value !== 'string' || value === '') throw new TypeError(`A look choice needs ${what}`);
  return value;
}

/** Read the store's answer for `versionId`, refusing one for another version or of another shape. */
export function parseThingLookChoices(value: unknown, versionId: string): readonly ThingLookChoice[] {
  const body = typeof value === 'object' && value !== null ? value as Record<string, unknown> : {};
  if (body['profile'] !== THING_LOOK_CHOICES_PROFILE) throw new TypeError('The look choices are not exulanica.thing-look-choices/v1');
  if (body['version_id'] !== versionId) throw new TypeError('The look choices are another version\'s');
  if (!Array.isArray(body['looks'])) throw new TypeError('The look choices are not a list');
  const seen = new Set<string>();
  return Object.freeze(body['looks'].map((row: unknown) => {
    const entry = typeof row === 'object' && row !== null ? row as Record<string, unknown> : {};
    const look = typeof entry['look'] === 'object' && entry['look'] !== null ? entry['look'] as Record<string, unknown> : {};
    const thingId = text(entry['thing_id'], 'a thing id');
    if (seen.has(thingId)) throw new TypeError('A thing has two look choices');
    seen.add(thingId);
    const placedId = entry['placed_id'] === null ? null : text(entry['placed_id'], 'a placed id or null');
    const version = look['version'];
    const sha256 = look['sha256'];
    if (typeof version !== 'number' || !Number.isInteger(version) || version < 1) throw new TypeError('A chosen look needs a version');
    if (typeof sha256 !== 'string' || !DIGEST.test(sha256)) throw new TypeError('A chosen look needs its SHA-256');
    const chosenBy = entry['chosen_by'];
    if (chosenBy !== 'owner' && chosenBy !== 'crossing') throw new TypeError('A look choice needs who chose it');
    return Object.freeze({
      thingId, placedId,
      look: Object.freeze({ key: text(look['look'], 'a look'), version, sha256 }),
      chosenBy, chosenAt: text(entry['chosen_at'], 'when it was chosen'),
    });
  }));
}

export interface ThingLooksClientOptions extends TransportOptions {
  /** The open world the version belongs to; null where none is open, which sends nothing. */
  readonly worldId: string | null;
}

export class ThingLooksClient {
  readonly #transport: Transport;
  readonly #worldId: string | null;

  constructor(options: ThingLooksClientOptions) {
    this.#transport = new Transport(options);
    this.#worldId = options.worldId;
  }

  /** The looks chosen for `versionId`'s things, by thing id. */
  async read(versionId: string): Promise<ReadonlyMap<string, ThingLookChoice>> {
    const path = openWorldPath(`/world/versions/${encodeURIComponent(versionId)}/thing-looks`, this.#worldId, 'the looks chosen for this world\'s things');
    const choices = parseThingLookChoices(await this.#transport.getJson<unknown>(path), versionId);
    return new Map(choices.map((choice) => [choice.thingId, choice]));
  }
}
