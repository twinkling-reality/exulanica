/**
 * Where the API is, and how this session is credentialed.
 *
 * **There is no account system, and this file does not invent one.**
 * `exulanica/api/authorisation.py` says so plainly: bearer-token authentication against a table of
 * tokens the operator configures out of band, with no registration, no password, no expiry and
 * no refresh. A sign-in form here would be a product decision taken by a config module.
 *
 * **The token is never persisted.** Not in `localStorage`, not in `sessionStorage`, not in a
 * cookie, not in the URL. It is held in a closure for the life of the tab and handed to the
 * transport, which holds it in a private field and puts it in a header. Every place it could be
 * stored is a place a cross-site script could read it, and what it unlocks is somebody's entire
 * photograph library. The cost is that a reload asks again, which is the correct trade for a
 * credential with no expiry and no revocation path.
 *
 * `VITE_EXULANICA_TOKEN` exists for development only and is read from the build environment rather
 * than from the page. It is documented here rather than hidden because a developer who does not
 * know it exists cannot know to keep `.env.local` out of a commit.
 *
 * **The base URL is this page's own origin.** The dev server proxies `/api` to uvicorn, so the
 * browser makes same-origin requests and no CORS policy exists in development that would not
 * exist in production. It is resolved to an absolute URL here rather than passed as the bare
 * path `/api`, because `Transport` builds a `URL` and a `URL` needs a base: knowing that this
 * code runs in a page is the app's business and not the transport's, which has to keep working
 * in a test with no `location` at all.
 */

const API_PATH = '/api';
const PREVIEW_API_PATH = '/preview-api';
const PREVIEW_TOKEN = 'atlas-preview-read-only';
const PRODUCT_TITLE = 'Exulanica';
const PREVIEW_TITLE = 'Exulanica: synthetic read-only development preview';

/** Reconstruction review keeps originals in the inspector instead of world-space photo veils. */
export function sourcePresentation(): 'world' | 'inspection' {
  return import.meta.env['VITE_EXULANICA_SOURCE_PRESENTATION'] === 'inspection'
    ? 'inspection' : 'world';
}

export interface Credentials {
  readonly baseUrl: string;
  readonly token: string;
}

/** The development token, or null. Never read from the page, never written back to it. */
export function developmentToken(): string | null {
  const supplied = import.meta.env['VITE_EXULANICA_TOKEN'];
  return typeof supplied === 'string' && supplied.length > 0 ? supplied : null;
}

export function credentials(token: string): Credentials {
  return { baseUrl: `${window.location.origin}${API_PATH}`, token };
}

/**
 * Whether this page explicitly requested the synthetic development Atlas.
 *
 * `development` is an argument so the production refusal is unit-testable. The caller passes
 * Vite's compile-time `import.meta.env.DEV`; a production build cannot be put into preview mode
 * by adding a query parameter.
 */
export function isAtlasPreview(search: string, development: boolean): boolean {
  return development && new URLSearchParams(search).get('preview') === '1';
}

/** Keep preview provenance visible in browser chrome without adding permanent world chrome. */
export function applicationTitle(preview: boolean): string {
  return preview ? PREVIEW_TITLE : PRODUCT_TITLE;
}

/** Credentials for the Vite-only preview route. No user credential is read or persisted. */
export function previewCredentials(origin: string): Credentials {
  return { baseUrl: `${origin}${PREVIEW_API_PATH}`, token: PREVIEW_TOKEN };
}
