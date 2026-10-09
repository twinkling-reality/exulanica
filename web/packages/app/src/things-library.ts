/**
 * The host's thing library, read with the page's credentials (THINGS's read-only routes).
 *
 * `GET /things/library` lists every kind and look the host serves and names each by the digest of
 * its bytes, with the body plans catalog's; `GET /things/library/{content_sha256}` answers one of
 * them: a kind or look as its canonical JSON, the catalog, or a look's container. Nothing 3D is
 * bundled with the page. The list is read once a page; every answer is held to its digest by
 * `ThingLibrary` before it is read.
 *
 * A kind or look the list does not hold may be the workspace's own (the thing store's
 * `GET /things/kinds/{sha256}`, `GET /things/looks/{sha256}` and its `/container`, and the drafted
 * body plan a held kind is drawn on, `GET /things/plans/{sha256}`): asked only for a digest the list
 * lacks, and a 404 there (absent, withdrawn or another workspace's) is not one.
 */
import { ThingLibrary, readThingLibrary, type HeldThings } from '@exulanica/atlas-react/things';
import { accessHeaders, type Credentials } from './config.js';

export const THING_LIBRARY_PATH = '/things/library';

const DIGEST = /^[0-9a-f]{64}$/u;

async function hostGet(access: Credentials, path: string, what: string, fetcher: typeof fetch): Promise<Response> {
  const response = await fetcher(`${access.baseUrl}${path}`, {
    headers: accessHeaders(access),
    credentials: 'same-origin',
  });
  if (!response.ok) throw new Error(`${what} unavailable: HTTP ${response.status}`);
  return response;
}

/** The workspace's own kinds and looks by digest; null for a 404, any other failure thrown. */
function heldThings(access: Credentials, fetcher: typeof fetch): HeldThings {
  const held = async (path: string, sha256: string, what: string): Promise<ArrayBuffer | null> => {
    if (!DIGEST.test(sha256)) throw new Error(`${what} is not named by a SHA-256`);
    const response = await fetcher(`${access.baseUrl}${path}`, {
      headers: accessHeaders(access),
      credentials: 'same-origin',
    });
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`${what} unavailable: HTTP ${response.status}`);
    return response.arrayBuffer();
  };
  return {
    kind: (sha256) => held(`/things/kinds/${sha256}`, sha256, 'A kind of this workspace'),
    look: (sha256) => held(`/things/looks/${sha256}`, sha256, 'A look of this workspace'),
    container: (sha256) => held(`/things/looks/${sha256}/container`, sha256, 'A look\'s container'),
    plan: (sha256) => held(`/things/plans/${sha256}`, sha256, 'A body plan of this workspace'),
  };
}

/** Read the host's thing library list, ready to fetch what it names by digest. */
export async function openThingLibrary(access: Credentials, fetcher: typeof fetch = fetch): Promise<ThingLibrary> {
  const list = readThingLibrary(await (await hostGet(access, THING_LIBRARY_PATH, 'The thing library', fetcher)).json());
  return new ThingLibrary(list, async (sha256) => {
    if (!DIGEST.test(sha256)) throw new Error('A thing library file is not named by a SHA-256');
    return (await hostGet(access, `${THING_LIBRARY_PATH}/${sha256}`, 'A thing library file', fetcher)).arrayBuffer();
  }, heldThings(access, fetcher));
}
