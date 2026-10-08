import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { LibraryRefused } from '@exulanica/atlas-react/things';
import { openThingLibrary } from '../src/things-library.js';

/*
 * The page asks the workspace's own thing store only for a digest the shipped list lacks, by the
 * store's routes and the page's credentials; a 404 there is a look the workspace does not hold, and
 * any other failure is said as one.
 */

const hex = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
const ACCESS = { baseUrl: 'https://host.test/api', token: 'page-token' };
const PLANS = new TextEncoder().encode('{}');
const LIST = { profile: 'exulanica.thing-library/v1', kinds: [], looks: [], body_plans: { sha256: hex(PLANS) } };

function host(routes: Record<string, { status: number; body?: string }>) {
  const asked: { url: string; authorization: string | null }[] = [];
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    asked.push({ url, authorization: new Headers(init?.headers).get('Authorization') });
    if (url === `${ACCESS.baseUrl}/things/library`) return new Response(JSON.stringify(LIST), { status: 200 });
    const route = routes[url.slice(ACCESS.baseUrl.length)];
    if (route === undefined) return new Response('', { status: 404 });
    return new Response(route.body ?? '', { status: route.status });
  }) as typeof fetch;
  return { fetcher, asked };
}

describe('the page\'s thing library and the workspace\'s own looks', () => {
  it('reads a look the list lacks from GET /things/looks/{sha256}, with the page\'s credentials', async () => {
    const document = JSON.stringify({ look: 'own-look', version: 1 });
    const digest = hex(new TextEncoder().encode(document));
    const { fetcher, asked } = host({ [`/things/looks/${digest}`]: { status: 200, body: document } });
    const library = await openThingLibrary(ACCESS, fetcher);
    expect(await library.lookDocument({ key: 'own-look', version: 1, sha256: digest })).toEqual({ look: 'own-look', version: 1 });
    expect(asked.at(-1)).toEqual({ url: `${ACCESS.baseUrl}/things/looks/${digest}`, authorization: 'Bearer page-token' });
  });

  it('reads a 404 as a look the workspace does not hold, and says any other failure', async () => {
    const digest = 'a'.repeat(64);
    const absent = await openThingLibrary(ACCESS, host({}).fetcher);
    const refused = await absent.lookDocument({ key: 'gone', version: 1, sha256: digest }).catch((error: unknown) => error);
    expect(refused).toBeInstanceOf(LibraryRefused);
    expect((refused as LibraryRefused).reason).toBe('not_in_library');
    const failing = await openThingLibrary(ACCESS, host({ [`/things/looks/${digest}`]: { status: 503 } }).fetcher);
    const failed = await failing.lookDocument({ key: 'gone', version: 1, sha256: digest }).catch((error: unknown) => error);
    expect(failed).not.toBeInstanceOf(LibraryRefused);
    expect(String(failed)).toContain('HTTP 503');
  });

  it('reads a kind the list lacks from GET /things/kinds/{sha256}', async () => {
    const document = JSON.stringify({ kind: 'own-creature', version: 1 });
    const digest = hex(new TextEncoder().encode(document));
    const { fetcher } = host({ [`/things/kinds/${digest}`]: { status: 200, body: document } });
    const library = await openThingLibrary(ACCESS, fetcher);
    expect(await library.kindDocument({ key: 'own-creature', version: 1, sha256: digest })).toEqual({ kind: 'own-creature', version: 1 });
  });
});
