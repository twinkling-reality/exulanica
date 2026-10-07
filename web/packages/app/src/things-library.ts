/**
 * The host's thing library, read with the page's credentials (THINGS's read-only routes).
 *
 * `GET /things/library` lists every kind and look the host serves and names each by the digest of
 * its bytes, with the body plans catalog's; `GET /things/library/{content_sha256}` answers one of
 * them: a kind or look as its canonical JSON, the catalog, or a look's container. Nothing 3D is
 * bundled with the page. The list is read once a page; every answer is held to its digest by
 * `ThingLibrary` before it is read.
 */
import { ThingLibrary, readThingLibrary } from '@exulanica/atlas-react/things';
import type { Credentials } from './config.js';

export const THING_LIBRARY_PATH = '/things/library';

const DIGEST = /^[0-9a-f]{64}$/u;

async function hostGet(access: Credentials, path: string, what: string, fetcher: typeof fetch): Promise<Response> {
  const response = await fetcher(`${access.baseUrl}${path}`, {
    headers: { Authorization: `Bearer ${access.token}` },
    credentials: 'same-origin',
  });
  if (!response.ok) throw new Error(`${what} unavailable: HTTP ${response.status}`);
  return response;
}

/** Read the host's thing library list, ready to fetch what it names by digest. */
export async function openThingLibrary(access: Credentials, fetcher: typeof fetch = fetch): Promise<ThingLibrary> {
  const list = readThingLibrary(await (await hostGet(access, THING_LIBRARY_PATH, 'The thing library', fetcher)).json());
  return new ThingLibrary(list, async (sha256) => {
    if (!DIGEST.test(sha256)) throw new Error('A thing library file is not named by a SHA-256');
    return (await hostGet(access, `${THING_LIBRARY_PATH}/${sha256}`, 'A thing library file', fetcher)).arrayBuffer();
  });
}
