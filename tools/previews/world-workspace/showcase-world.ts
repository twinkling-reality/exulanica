// A showcase world opened from a link (`/?world=<key>`): the server makes the caller's own copy of that made world from
// its installation's showcase catalog, with no model call (POST /worlds/showcase/{key}), or answers the copy already
// held, and the page goes on to the copy's own address, where it opens as any saved world does.
import { accessHeaders, type Credentials } from '../../../web/packages/app/src/config.ts';
import { showcaseKey, worldAddress } from './front-door-routes.mjs';

/** How many more times a link asks while its world is still being made: at most about a minute. */
const MAKING_ASKS = 8;

/** The address of the caller's copy of the showcase world `href` names, or null when it names none or none was made. */
export async function openShowcaseWorld(access: Credentials, href: string): Promise<string | null> {
  const key = showcaseKey(href);
  if (key === null) return null;
  const ask = () => fetch(`${access.baseUrl}/worlds/showcase/${encodeURIComponent(key)}`, {
    method: 'POST', body: '{}', credentials: 'same-origin', cache: 'no-store',
    headers: { ...accessHeaders(access, 'POST'), Accept: 'application/json', 'Content-Type': 'application/json' },
  }).catch(() => null);
  let response = await ask();
  // A place still being composed answers 503 with Retry-After; the server keeps the work, so asking again reads it.
  for (let again = 0; response?.status === 503 && again < MAKING_ASKS; again += 1) {
    const wait = Math.min(Math.max(Number(response.headers.get('Retry-After')) || 2, 1), 10);
    await new Promise((done) => setTimeout(done, wait * 1000));
    response = await ask();
  }
  if (!response?.ok) return null;
  const entryId = ((await response.json().catch(() => null)) as { entry?: { entry_id?: unknown } } | null)?.entry?.entry_id;
  return typeof entryId === 'string' ? worldAddress(entryId, new URL(href).origin) : null;
}
