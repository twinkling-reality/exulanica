/**
 * What the thing card reads about a placed thing before the server serves its card: the parts of
 * its kind's and look's documents a person reads (the host's thing library, held to their digests)
 * and the look a version's thing wears (`GET /world/versions/{version_id}/thing-looks`).
 *
 * Each reader takes only the fields the card shows and refuses any other shape, so a document
 * that changes its meaning is never read as the old one.
 */
import type { Credentials } from './config.js';

/** `exulanica.origin/v1`: who made a thing's kind or look, from what, and under which licence. */
export interface OriginRecord {
  readonly class: 'authored' | 'drafted' | 'generated' | 'uploaded' | 'imported' | 'crossed';
  /** Who made it: this project, an account, a model by name, or an outside program. */
  readonly by: 'project' | 'account' | 'model' | 'program';
  readonly sources: readonly string[];
  readonly licence: {
    readonly spdx: string;
    readonly attribution: string | null;
    readonly shareAlike: boolean;
    readonly url: string | null;
  };
  readonly authors: readonly string[];
}

export interface KindFacts {
  readonly label: string;
  readonly summary: string;
  readonly class: 'being' | 'object';
  /** Who runs a being of this kind until somebody chooses: its decider kind, or null for an object. */
  readonly decidedBy: string | null;
  readonly origin: OriginRecord;
}

export interface LookFacts {
  readonly label: string;
  readonly origin: OriginRecord;
}

export interface LookReference {
  readonly key: string;
  readonly version: number;
  readonly sha256: string;
}

const CLASSES = ['authored', 'drafted', 'generated', 'uploaded', 'imported', 'crossed'] as const;
const BY = ['project', 'account', 'model', 'program'] as const;

const invalid = (what: string): never => { throw new Error(`Invalid ${what}`); };
const object = (value: unknown, what: string): Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : invalid(what);
const text = (value: unknown, what: string): string => (typeof value === 'string' && value.length > 0 ? value : invalid(what));
const maybeText = (value: unknown, what: string): string | null => (value === null ? null : text(value, what));
const oneOf = <T extends string>(value: unknown, allowed: readonly T[], what: string): T =>
  (allowed as readonly unknown[]).includes(value) ? value as T : invalid(what);

export function readOrigin(value: unknown): OriginRecord {
  const held = object(value, 'origin');
  if (held['profile'] !== 'exulanica.origin/v1') invalid('origin profile');
  const licence = object(held['licence'], 'origin licence');
  const sources = Array.isArray(held['sources']) ? held['sources'] : invalid('origin sources');
  const authors = Array.isArray(held['authors']) ? held['authors'] : invalid('origin authors');
  return {
    class: oneOf(held['class'], CLASSES, 'origin class'),
    by: oneOf(object(held['by'], 'origin by')['kind'], BY, 'origin by'),
    sources: sources.map((source) => {
      const entry = object(source, 'origin source');
      return text(entry['reference'] ?? entry['url'], 'origin source reference');
    }),
    licence: {
      spdx: text(licence['spdx'], 'licence'),
      attribution: maybeText(licence['attribution'] ?? null, 'licence attribution'),
      shareAlike: licence['share_alike'] === true,
      url: maybeText(licence['licence_url'] ?? null, 'licence url'),
    },
    authors: authors.map((author) => text(author, 'origin author')),
  };
}

export function readKindFacts(value: unknown): KindFacts {
  const held = object(value, 'thing kind');
  if (held['profile'] !== 'exulanica.thing-kind/v1') invalid('thing kind profile');
  const kindClass = oneOf(held['class'], ['being', 'object'] as const, 'thing kind class');
  const deciders = held['deciders'];
  return {
    label: text(held['label'], 'thing kind label'),
    summary: text(held['summary'], 'thing kind summary'),
    class: kindClass,
    decidedBy: kindClass === 'being' ? text(object(deciders, 'thing kind deciders')['default'], 'decider') : null,
    origin: readOrigin(held['origin']),
  };
}

export function readLookFacts(value: unknown): LookFacts {
  const held = object(value, 'look');
  if (held['profile'] !== 'exulanica.look/v1') invalid('look profile');
  return { label: text(held['label'], 'look label'), origin: readOrigin(held['origin']) };
}

/** The look each placed thing of a version wears now, by its placed id; absent means its kind's first. */
export function readThingLooks(value: unknown): ReadonlyMap<string, LookReference> {
  const held = object(value, 'thing looks');
  if (held['profile'] !== 'exulanica.thing-look-choices/v1') invalid('thing looks profile');
  const looks = Array.isArray(held['looks']) ? held['looks'] : invalid('thing looks list');
  const worn = new Map<string, LookReference>();
  for (const row of looks) {
    const entry = object(row, 'thing look');
    const placed = entry['placed_id'];
    if (placed === null) continue;
    const look = object(entry['look'], 'thing look reference');
    const version = look['version'];
    if (!Number.isSafeInteger(version) || (version as number) < 1) invalid('thing look version');
    const sha256 = text(look['sha256'], 'thing look digest');
    if (!/^[0-9a-f]{64}$/u.test(sha256)) invalid('thing look digest');
    worn.set(text(placed, 'placed id'), { key: text(look['look'], 'thing look key'), version: version as number, sha256 });
  }
  return worn;
}

export async function fetchThingLooks(
  access: Credentials, worldId: string, versionId: string, fetcher: typeof fetch = fetch,
): Promise<ReadonlyMap<string, LookReference>> {
  const response = await fetcher(
    `${access.baseUrl}/world/versions/${encodeURIComponent(versionId)}/thing-looks?world_id=${encodeURIComponent(worldId)}`,
    { headers: { Authorization: `Bearer ${access.token}` }, credentials: 'same-origin' },
  );
  if (!response.ok) throw new Error(`The looks of this world's things are unavailable: HTTP ${response.status}`);
  return readThingLooks(await response.json());
}
