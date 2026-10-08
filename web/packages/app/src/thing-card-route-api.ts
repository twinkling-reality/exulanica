/**
 * A thing's card as the server serves it (`exulanica.thing-card/v1`): one thing or being of a
 * version's society of things, by the id the society gives it, read from
 * `GET /world/versions/{version_id}/society/things/{thing_id}?world_id=`, and the owner's choice
 * of how it is drawn, `POST .../society/things/{thing_id}/look`, which answers the card again.
 *
 * The reader takes only the fields the card shows and refuses any other shape: what it can do here
 * and what others can do with it (only what the society runs; the catalogs' own words), what it
 * holds, the look it wears and the looks it may wear, and the society's minute and record as the
 * card was read, which the look swap shows as its proof.
 */
import type { Credentials } from './config.js';
import { readOrigin, type OriginRecord } from './thing-card-api.js';

export const THING_CARD_PROFILE = 'exulanica.thing-card/v1';

/** A look by what the server names it with: a shipped one by key, version and digest, or the workspace's own by digest. */
export type CardLookReference =
  | { readonly source: 'shipped'; readonly key: string; readonly version: number; readonly sha256: string }
  | { readonly source: 'workspace'; readonly sha256: string };

/** One look the thing may be drawn as: its label, who made it and its licence. */
export interface CardLookOption {
  readonly ref: CardLookReference;
  readonly label: string;
  readonly authors: readonly string[];
  /** The licence's SPDX id, or null where the look's origin states none. */
  readonly licence: string | null;
}

export interface ThingCardRoute {
  readonly thingId: string;
  /** What it can do here, in the abilities catalog's words, in its kind's order. */
  readonly can: readonly string[];
  /** What others can do with it, in the offers catalog's words. */
  readonly offers: readonly string[];
  /** What it holds, by each held thing's kind label; null where this world's beings have no hands, or for an object. */
  readonly holding: readonly string[] | null;
  /** The look it wears now. */
  readonly look: {
    readonly ref: CardLookReference;
    readonly label: string;
    readonly origin: OriginRecord | null;
    readonly chosenByOwner: boolean;
  };
  /** Every look it may be drawn as, the one it wears included. */
  readonly looks: readonly CardLookOption[];
  /** The society's minute and the digest of its record as the card was read. */
  readonly society: { readonly tick: number; readonly stateSha256: string };
}

const DIGEST = /^[0-9a-f]{64}$/u;

const invalid = (what: string): never => { throw new Error(`Invalid thing card: ${what}`); };
const object = (value: unknown, what: string): Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : invalid(what);
const list = (value: unknown, what: string): readonly unknown[] => (Array.isArray(value) ? value : invalid(what));
const text = (value: unknown, what: string): string => (typeof value === 'string' && value.length > 0 ? value : invalid(what));
const digest = (value: unknown, what: string): string => (typeof value === 'string' && DIGEST.test(value) ? value : invalid(what));
const count = (value: unknown, what: string, least: number): number =>
  (Number.isSafeInteger(value) && (value as number) >= least ? value as number : invalid(what));

/** A look reference as the card states it: `{look, version, sha256}` or `{source: "workspace", sha256}`. */
function lookReference(value: Record<string, unknown>, what: string): CardLookReference {
  if (value['source'] === 'workspace') return { source: 'workspace', sha256: digest(value['sha256'], `${what} digest`) };
  if (value['source'] !== undefined && value['source'] !== 'shipped') invalid(`${what} source`);
  return {
    source: 'shipped',
    key: text(value['look'], `${what} key`),
    version: count(value['version'], `${what} version`, 1),
    sha256: digest(value['sha256'], `${what} digest`),
  };
}

/** The words of each entry of a list of `{key, words, module}`. */
const wordsOf = (value: unknown, what: string): string[] =>
  list(value, what).map((entry) => text(object(entry, what)['words'], `${what} words`));

/**
 * The worn look's origin record, or null where it states none or one this reader does not know (a
 * look the workspace keeps may carry an older record): the card then names the look without it.
 */
function originOrNull(value: unknown): OriginRecord | null {
  if (value === null || value === undefined) return null;
  try {
    return readOrigin(value);
  } catch {
    return null;
  }
}

export function readThingCardRoute(value: unknown): ThingCardRoute {
  const held = object(value, 'card');
  if (held['profile'] !== THING_CARD_PROFILE) invalid('profile');
  const look = object(held['look'], 'look');
  const society = object(held['society'], 'society');
  const holding = held['holding'];
  return {
    thingId: text(held['thing_id'], 'thing id'),
    can: wordsOf(held['abilities'], 'ability'),
    offers: wordsOf(held['offers'], 'offer'),
    holding: holding === null ? null : list(holding, 'holding').map((entry) => text(object(entry, 'held thing')['label'], 'held thing label')),
    look: {
      ref: lookReference(look, 'look'),
      label: text(look['label'], 'look label'),
      origin: originOrNull(look['origin']),
      chosenByOwner: look['chosen_by_owner'] === true,
    },
    looks: list(held['looks'], 'looks').map((entry) => {
      const option = object(entry, 'look option');
      const licence = option['licence'];
      return {
        ref: lookReference(option, 'look option'),
        label: text(option['label'], 'look option label'),
        authors: list(option['authors'] ?? [], 'look option authors').map((author) => text(author, 'look option author')),
        licence: licence === null || licence === undefined ? null : text(object(licence, 'look option licence')['spdx'], 'look option licence'),
      };
    }),
    society: {
      tick: count(society['tick'], 'society minute', 0),
      stateSha256: digest(society['state_sha256'], 'society record digest'),
    },
  };
}

/** Whether two look references name the same look. */
export function sameLook(a: CardLookReference, b: CardLookReference): boolean {
  if (a.source === 'workspace' || b.source === 'workspace') return a.source === b.source && a.sha256 === b.sha256;
  return a.key === b.key && a.version === b.version && a.sha256 === b.sha256;
}

/** A look reference as the look route takes it. */
function lookBody(ref: CardLookReference): Record<string, unknown> {
  return ref.source === 'workspace'
    ? { source: 'workspace', sha256: ref.sha256 }
    : { look: ref.key, version: ref.version, sha256: ref.sha256 };
}

const cardPath = (access: Credentials, worldId: string, versionId: string, thingId: string, tail = ''): string =>
  `${access.baseUrl}/world/versions/${encodeURIComponent(versionId)}/society/things/${encodeURIComponent(thingId)}${tail}?world_id=${encodeURIComponent(worldId)}`;

/**
 * The thing's card, or null where the server has none for it (a version whose society is not a
 * society of things, or holds no such thing): the card then keeps what it reads elsewhere.
 */
export async function fetchThingCardRoute(
  access: Credentials, worldId: string, versionId: string, thingId: string, fetcher: typeof fetch = fetch,
): Promise<ThingCardRoute | null> {
  const response = await fetcher(cardPath(access, worldId, versionId, thingId), {
    headers: { Authorization: `Bearer ${access.token}` }, credentials: 'same-origin',
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`This thing's card is unavailable: HTTP ${response.status}`);
  return readThingCardRoute(await response.json());
}

/** What came of choosing a look: the card as the server answers it, or why it was refused, by code. */
export type LookChoiceOutcome =
  | { readonly chosen: true; readonly card: ThingCardRoute }
  | { readonly chosen: false; readonly code: string };

export async function chooseThingLook(
  access: Credentials, worldId: string, versionId: string, thingId: string, ref: CardLookReference, fetcher: typeof fetch = fetch,
): Promise<LookChoiceOutcome> {
  const response = await fetcher(cardPath(access, worldId, versionId, thingId, '/look'), {
    method: 'POST',
    headers: { Authorization: `Bearer ${access.token}`, 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ look: lookBody(ref) }),
  });
  if (response.ok) return { chosen: true, card: readThingCardRoute(await response.json()) };
  const body = await response.json().then((read: unknown) => read, () => null) as { code?: unknown } | null;
  const code = typeof body?.code === 'string' ? body.code : `http_${response.status}`;
  return { chosen: false, code };
}
