/**
 * Where the API is, and how this session is credentialed.
 *
 * Browser accounts use the API's revocable HttpOnly session cookie. The client retains the
 * returned CSRF value only for the life of this page. Operator bearer tokens remain a development
 * path and are never persisted.
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

import {
  googleTilesConfig,
  type GoogleTilesConfig,
} from '@exulanica/atlas-react/playcanvas';
import {
  parseOwnedDistrict,
  parseDistrictInterpretation,
  districtInterpretationAvailability,
  type DistrictInterpretation,
  type OwnedDistrict,
} from '@exulanica/atlas-core';
import ownedDistrictAsset from '../../../../assets/owned-world/flatiron/flatiron-owned-district.json?url';
import districtInterpretationAsset from '../../../../assets/owned-world/flatiron-interpretation-v1/district-interpretation.json?url';

const API_PATH = '/api';
const PREVIEW_API_PATH = '/preview-api';
const PREVIEW_TOKEN = 'atlas-preview-read-only';
export const PREVIEW_NYC_OPEN_DATA_ADMISSION_ID = '9d152259-13d1-5025-8f72-8bcb639a6438';
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
  readonly csrfToken?: string;
}

/** The development token, or null. Never read from the page, never written back to it. */
export function developmentToken(): string | null {
  const supplied = import.meta.env['VITE_EXULANICA_TOKEN'];
  return typeof supplied === 'string' && supplied.length > 0 ? supplied : null;
}

export function credentials(token: string, csrfToken?: string): Credentials {
  return {
    baseUrl: `${window.location.origin}${API_PATH}`, token,
    ...(csrfToken === undefined ? {} : { csrfToken }),
  };
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

/** Optional visualization-only provider configuration. Never persisted or logged. */
export function googlePhotorealisticTiles(): GoogleTilesConfig {
  return googleTilesConfig(import.meta.env);
}

export async function ownedDistrict(options: {
  readonly preview?: boolean;
  readonly currentDependencies?: Readonly<Record<string, string>>;
} = {}): Promise<{
  readonly document: OwnedDistrict;
  readonly residentBytes: number;
  readonly interpretation?: DistrictInterpretation;
}> {
  const response = await fetch(ownedDistrictAsset, { credentials: 'same-origin' });
  if (!response.ok) throw new Error(`Owned district unavailable: HTTP ${response.status}`);
  const bytes = await response.arrayBuffer();
  const document = parseOwnedDistrict(JSON.parse(new TextDecoder().decode(bytes)));
  const previewFixture = import.meta.env.DEV && options.preview === true;
  if (!previewFixture && options.currentDependencies === undefined) {
    return Object.freeze({ document, residentBytes: bytes.byteLength });
  }
  const derived = await fetch(districtInterpretationAsset, { credentials: 'same-origin' });
  if (!derived.ok) throw new Error(`District interpretation unavailable: HTTP ${derived.status}`);
  const derivedBytes = await derived.arrayBuffer();
  const hash = async (value: ArrayBuffer): Promise<string> =>
    Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', value)),
      b => b.toString(16).padStart(2, '0')).join('');
  const interpretation = await parseDistrictInterpretation(
    JSON.parse(new TextDecoder().decode(derivedBytes)), document, {
      baseArtifactSha256: await hash(bytes),
      sha256: text => hash(new TextEncoder().encode(text).buffer),
    },
  );
  // Development fixtures establish local visual mechanics only. Authenticated callers must
  // supply current dependency resolution; a retained artifact is never a live rights grant.
  const current = previewFixture
    ? Object.fromEntries(interpretation.source_dependencies.map(source => [source.sha256, 'available']))
    : options.currentDependencies!;
  const unavailable = districtInterpretationAvailability(interpretation, current);
  if (unavailable.length) throw new Error('District interpretation dependencies are unavailable');
  return Object.freeze({ document, interpretation,
    residentBytes: bytes.byteLength + derivedBytes.byteLength });
}

/** One explicitly admitted NYC Open Data source. Empty means the semantic workflow is unavailable. */
export function nycOpenDataAdmissionId(
  environment: Readonly<Record<string, unknown>> = import.meta.env,
): string | null {
  const value = environment['VITE_NYC_OPEN_DATA_ADMISSION_ID'];
  return typeof value === 'string' &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
    ? value.toLowerCase()
    : null;
}

/** Credentials for the Vite-only preview route. No user credential is read or persisted. */
export function previewCredentials(origin: string): Credentials {
  return { baseUrl: `${origin}${PREVIEW_API_PATH}`, token: PREVIEW_TOKEN };
}
