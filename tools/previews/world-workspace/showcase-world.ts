// The showcase worlds an installation serves (GET /worlds/showcase): the front door offers each one the workspace does
// not hold yet as a card of its picture and title, and a link opens one (`/?world=<key>`). Either way the server makes
// the caller's own copy of that made world from its showcase catalog, with no model call (POST /worlds/showcase/{key}),
// or answers the copy already held, and the page goes on to the copy's own address, where it opens as any saved world
// does.
import { accessHeaders, type Credentials } from '../../../web/packages/app/src/config.ts';
import { parseEntry, type SavedWorldEntry } from '../../../web/packages/app/src/world-entry-api.ts';
import { showcaseKey, worldAddress } from './front-door-routes.mjs';

/** How many more times a link or Open asks while its world is still being made: at most about a minute. */
const MAKING_ASKS = 8;
/** A showcase world's key, as its address names it. */
const KEY = /^[a-z][a-z0-9-]{0,63}$/u;
const DIGEST = /^[0-9a-f]{64}$/u;

/** A served showcase world the workspace does not hold yet, as the front door offers it. */
export interface ShowcaseOffer {
  readonly key: string;
  /** The made world's title, which its copy is given. */
  readonly title: string;
  /** Its card picture, held to the digest the catalog names, as an address this page shows; null where there is none. */
  readonly picture: string | null;
}

/** A served showcase world as the catalog states it, the fields the page reads. */
interface Served {
  readonly key: string;
  readonly title: string;
  readonly world_id: string;
  readonly picture: { readonly sha256: string; readonly media_type: string } | null;
}

const served = (one: unknown): one is Served => {
  const world = one as Partial<Served> | null;
  const picture = world?.picture;
  return typeof world?.key === 'string' && KEY.test(world.key) && typeof world.title === 'string' && world.title.trim() !== ''
    && typeof world.world_id === 'string'
    && (picture === null || (typeof picture?.sha256 === 'string' && DIGEST.test(picture.sha256) && typeof picture.media_type === 'string'));
};

async function digestOf(bytes: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await bytes.arrayBuffer());
  return [...new Uint8Array(digest)].map((n) => n.toString(16).padStart(2, '0')).join('');
}

/**
 * The served showcase worlds no world of `held` is a copy of, in the catalog's order: a copy is made under its showcase
 * world's identity, so a held copy's world id is the catalog's. Each card picture is read by its digest and shown only
 * where its bytes are that digest. None where the catalog cannot be read.
 */
export async function showcaseOffers(access: Credentials, held: readonly Pick<SavedWorldEntry, 'worldId'>[]): Promise<ShowcaseOffer[]> {
  const read = (path: string, cache: RequestCache) => fetch(access.baseUrl + path, { headers: accessHeaders(access), credentials: 'same-origin', cache });
  let worlds: unknown;
  try {
    const response = await read('/worlds/showcase', 'no-store');
    if (!response.ok) return [];
    worlds = ((await response.json()) as { worlds?: unknown } | null)?.worlds;
  } catch { return []; }
  const holds = new Set(held.map((one) => one.worldId));
  const offered = (Array.isArray(worlds) ? worlds : []).filter(served).filter((one) => !holds.has(one.world_id));
  return Promise.all(offered.map(async (one): Promise<ShowcaseOffer> => {
    let picture: string | null = null;
    if (one.picture !== null) {
      try {
        // The address names the bytes, so the browser may keep them as long as it likes.
        const response = await read(`/worlds/showcase/${encodeURIComponent(one.key)}/picture?sha256=${one.picture.sha256}`, 'default');
        const bytes = response.ok ? await response.blob() : null;
        if (bytes !== null && await digestOf(bytes) === one.picture.sha256) {
          picture = URL.createObjectURL(bytes.type === one.picture.media_type ? bytes : new Blob([bytes], { type: one.picture.media_type }));
        }
      } catch { picture = null; }
    }
    return { key: one.key, title: one.title, picture };
  }));
}

/**
 * The server's answer to asking for the caller's own copy of the showcase world `key`, or null where none came. A place
 * still being composed answers 503 with Retry-After; the server keeps the work, so asking again reads it.
 */
async function askForCopy(access: Credentials, key: string): Promise<Response | null> {
  const ask = () => fetch(`${access.baseUrl}/worlds/showcase/${encodeURIComponent(key)}`, {
    method: 'POST', body: '{}', credentials: 'same-origin', cache: 'no-store',
    headers: { ...accessHeaders(access, 'POST'), Accept: 'application/json', 'Content-Type': 'application/json' },
  }).catch(() => null);
  let response = await ask();
  for (let again = 0; response?.status === 503 && again < MAKING_ASKS; again += 1) {
    const wait = Math.min(Math.max(Number(response.headers.get('Retry-After')) || 2, 1), 10);
    await new Promise((done) => setTimeout(done, wait * 1000));
    response = await ask();
  }
  return response;
}

/**
 * The caller's own copy of the showcase world `key`, made as its link makes it, or the copy the workspace already
 * holds: its saved entry. Rejects where none was made, in the server's own words where it gave any.
 */
export async function makeShowcaseCopy(access: Credentials, key: string): Promise<SavedWorldEntry> {
  const response = await askForCopy(access, key);
  const body = response === null ? null : ((await response.json().catch(() => null)) as { entry?: unknown; detail?: unknown } | null);
  if (!response?.ok) {
    throw new Error(typeof body?.detail === 'string' && body.detail.trim() !== '' ? body.detail : 'This world could not be opened here.');
  }
  return parseEntry(body?.entry);
}

/** The address of the caller's copy of the showcase world `href` names, or null when it names none or none was made. */
export async function openShowcaseWorld(access: Credentials, href: string): Promise<string | null> {
  const key = showcaseKey(href);
  if (key === null) return null;
  const response = await askForCopy(access, key);
  if (!response?.ok) return null;
  const entryId = ((await response.json().catch(() => null)) as { entry?: { entry_id?: unknown } } | null)?.entry?.entry_id;
  return typeof entryId === 'string' ? worldAddress(entryId, new URL(href).origin) : null;
}
