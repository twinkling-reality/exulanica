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

/** A baked tile's name: lowercase words joined by single hyphens, as its committed file is named. */
const GENERATED_TILE_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const GENERATED_TILE_NAME_LIMIT = 64;

/**
 * The baked generated tile a development preview asked to evaluate, or null.
 *
 * DEVELOPMENT EVALUATION ONLY. A generated tile may not appear in any person's world until a
 * superseding governance ADR is accepted in writing. So a tile can be named only on the synthetic
 * preview route: `preview` is {@link isAtlasPreview}, which is false in every production build,
 * and a preview session never carries a workspace credential. A workspace world has no way to ask
 * for a tile, and a production build has no code that could load one.
 *
 * The name is a plain word, never a path: the development module resolves it to a committed file.
 */
export function generatedTileEvaluationName(search: string, preview: boolean): string | null {
  if (!preview) return null;
  const name = new URLSearchParams(search).get('tile');
  return name !== null && name.length <= GENERATED_TILE_NAME_LIMIT && GENERATED_TILE_NAME.test(name)
    ? name
    : null;
}

/** A city seed is a digest; a baked tile's key is a UUID. Neither is ever a path. */
const CITY_SEED = /^[0-9a-f]{64}$/;
const BAKED_TILE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const TILE_COORDINATE_LIMIT = 1_000_000;
const LOD_LIMIT = 64;
/** A pose is stated in the city frame, so its bounds are a city's, and a facing is a direction. */
const POSE_MM_LIMIT = 1_000_000_000;
const FACING_LIMIT = 1_000_000;

/**
 * Where a walk begins and which way it faces, stated by whoever defines the walk.
 *
 * Integer millimetres in the city frame and an integer direction, because a pose a record names must
 * be reproducible to the millimetre and a bearing in degrees needs a convention (from north or from
 * east, clockwise or anticlockwise) that two readers resolve differently. The city's own records
 * state facing the same way, as `facing_dx_mm` and `facing_dy_mm`, in a frame with x east and y
 * north. A pose is a fact about the WALK and not about the tile: two walks of one street begin in
 * different places and neither is more the tile's than the other.
 */
export interface WalkPose {
  readonly xMm: number;
  readonly yMm: number;
  readonly facingDx: number;
  readonly facingDy: number;
}

/** Which baked tile a walk asked the product route for: a key, or a coordinate in a city. */
export type BakedTileRequest =
  | { readonly kind: 'key'; readonly bakedTileId: string; readonly pose: WalkPose | null }
  | { readonly kind: 'coordinate'; readonly citySeed: string; readonly tileX: number; readonly tileY: number; readonly lod: number; readonly pose: WalkPose | null };

function whole(value: string | null, limit: number): number | null {
  if (value === null || !/^-?\d+$/.test(value)) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isSafeInteger(parsed) && Math.abs(parsed) <= limit ? parsed : null;
}

/**
 * The baked tile a development preview asked the product route for, or null.
 *
 * DEVELOPMENT ONLY, and for the same reason {@link generatedTileEvaluationName} is: a generated
 * tile may not appear in any person's world until a superseding governance ADR is accepted in
 * writing. The difference between the two is where the container comes from. A `tile` name is a
 * golden committed to this repository; a `city` and coordinate, or a `baked_tile` key, is a
 * container fetched from `/tiles` with this session's credential, because a baked corridor street
 * is never committed. The texture sets are the committed library either way, since no route serves
 * the published texture library yet.
 *
 * A key wins over a coordinate when a search carries both, so one reading is never ambiguous.
 */
export function bakedTileRequest(search: string, preview: boolean): BakedTileRequest | null {
  if (!preview) return null;
  const parameters = new URLSearchParams(search);
  const pose = walkPose(parameters);
  // A malformed pose refuses the whole request rather than falling back to the runtime's default: a
  // silent fallback is how a frame that is not reproducible ends up in a record looking like one
  // that is, and the picture would look perfectly fine.
  if (pose === 'malformed') return null;
  const key = parameters.get('baked_tile');
  if (key !== null) return BAKED_TILE_ID.test(key) ? { kind: 'key', bakedTileId: key, pose } : null;
  const citySeed = parameters.get('city');
  if (citySeed === null || !CITY_SEED.test(citySeed)) return null;
  const tileX = whole(parameters.get('tile_x'), TILE_COORDINATE_LIMIT);
  const tileY = whole(parameters.get('tile_y'), TILE_COORDINATE_LIMIT);
  const lod = parameters.get('lod') === null ? 0 : whole(parameters.get('lod'), LOD_LIMIT);
  if (tileX === null || tileY === null || lod === null || lod < 0) return null;
  return { kind: 'coordinate', citySeed, tileX, tileY, lod, pose };
}

/**
 * The pose a walk states, for any development route rather than only a baked tile's.
 *
 * The committed golden route needs this as much as the product route does: it is the only target a
 * check can exercise with no credential, so a pose that could not be stated there would leave the
 * "stated or default" distinction with no credential-free proof.
 */
export function statedWalkPose(search: string, preview: boolean): WalkPose | null | 'malformed' {
  if (!preview) return null;
  return walkPose(new URLSearchParams(search));
}

/** The four pose parameters, all of them or none: anything else is malformed and refuses the walk. */
function walkPose(parameters: URLSearchParams): WalkPose | null | 'malformed' {
  const keys = ['pose_x_mm', 'pose_y_mm', 'facing_dx', 'facing_dy'] as const;
  const given = keys.filter((key) => parameters.get(key) !== null);
  if (given.length === 0) return null;
  if (given.length !== keys.length) return 'malformed';
  const xMm = whole(parameters.get('pose_x_mm'), POSE_MM_LIMIT);
  const yMm = whole(parameters.get('pose_y_mm'), POSE_MM_LIMIT);
  const facingDx = whole(parameters.get('facing_dx'), FACING_LIMIT);
  const facingDy = whole(parameters.get('facing_dy'), FACING_LIMIT);
  if (xMm === null || yMm === null || facingDx === null || facingDy === null) return 'malformed';
  // A facing of no direction states nothing, so it is malformed rather than a default.
  if (facingDx === 0 && facingDy === 0) return 'malformed';
  return { xMm, yMm, facingDx, facingDy };
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
