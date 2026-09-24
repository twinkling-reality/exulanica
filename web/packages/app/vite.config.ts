import { defineConfig, searchForWorkspaceRoot, type Plugin } from 'vite';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { previewApiResponse } from './src/dev/preview-api.js';
import { societyRecordingPlugin } from './src/dev/society-recording.js';

const APP_ROOT = fileURLToPath(new URL('.', import.meta.url));
const NYC_ADMISSION_ID = '9d152259-13d1-5025-8f72-8bcb639a6438';
const NYC_PUBLICATION_ID = '6bc80ed2-934d-4db8-a8f0-907e62d0af31';
const NYC_PLACE_ID = 'd08f61bb-ef6d-4f5d-8bd8-a596da51f971';
const NYC_RENDER_ASSET_ID = '8fb48be4-f696-48aa-b551-cd80186479e3';
const NYC_PROVIDER_KEY = 'nyc-open-data';
const NYC_PROVIDER_ORIGINAL_ID = '5zhs-2jue';
const NYC_PROVIDER_REVISION = 'Sun, 13 Sep 2026 15:49:22 GMT';
const NYC_SOURCE_URL = 'https://data.cityofnewyork.us/resource/5zhs-2jue.geojson?'
  + new URLSearchParams({
    '$select': 'the_geom,name,bin,doitt_id',
    '$where': 'within_box(the_geom,40.745,-73.994,40.739,-73.986)',
    '$order': 'doitt_id',
    '$limit': '1000',
  });

interface PreviewNYCFeature {
  readonly id: string;
  readonly provider_feature_id: string;
  readonly bbox: readonly number[];
  readonly footprint: { readonly type: 'MultiPolygon'; readonly coordinates: unknown };
  readonly render_batch_id: number;
  readonly semantic_properties: { readonly bin: string | null; readonly name: string | null };
}

let previewNYCCatalog: Promise<Readonly<Record<string, unknown>>> | null = null;
const sha256 = (value: string): string => createHash('sha256').update(value).digest('hex');
const featureId = (providerFeatureId: string, sourceSha256: string): string => sha256(JSON.stringify({
  profile: 'exulanica.environment-provider-feature/v1',
  provider_feature_id: providerFeatureId,
  provider_key: NYC_PROVIDER_KEY,
  provider_original_id: NYC_PROVIDER_ORIGINAL_ID,
  provider_revision: NYC_PROVIDER_REVISION,
  source_sha256: sourceSha256,
})).slice(0, 32);

async function loadPreviewNYCCatalog(): Promise<Readonly<Record<string, unknown>>> {
  previewNYCCatalog ??= (async () => {
    const response = await fetch(NYC_SOURCE_URL, {
      headers: { Accept: 'application/vnd.geo+json' },
    });
    if (!response.ok) throw new Error(`NYC Open Data returned ${response.status}`);
    const source = await response.text();
    const document = JSON.parse(source) as { readonly features?: unknown };
    if (!Array.isArray(document.features)) throw new Error('NYC Open Data returned invalid GeoJSON');
    const sourceDigest = sha256(source);
    const features: PreviewNYCFeature[] = document.features.map((value, index) => {
      const feature = value as {
        readonly geometry?: { readonly type?: unknown; readonly coordinates?: unknown };
        readonly properties?: Readonly<Record<string, unknown>>;
      };
      const doitt = feature.properties?.['doitt_id'];
      const geometry = feature.geometry;
      if (typeof doitt !== 'string' || !/^[1-9][0-9]*$/.test(doitt) ||
          (geometry?.type !== 'Polygon' && geometry?.type !== 'MultiPolygon')) {
        throw new Error('NYC Open Data feature failed validation');
      }
      const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
      if (!Array.isArray(polygons)) throw new Error('NYC Open Data geometry failed validation');
      const integerPolygons = polygons.map((polygon) => {
        if (!Array.isArray(polygon)) throw new Error('NYC Open Data polygon failed validation');
        return polygon.map((ring) => {
          if (!Array.isArray(ring)) throw new Error('NYC Open Data ring failed validation');
          return ring.map((point) => {
            if (!Array.isArray(point) || point.length < 2 ||
                !Number.isFinite(Number(point[0])) || !Number.isFinite(Number(point[1]))) {
              throw new Error('NYC Open Data point failed validation');
            }
            return [Math.round(Number(point[0]) * 10_000_000), Math.round(Number(point[1]) * 10_000_000)];
          });
        });
      });
      const points = integerPolygons.flat(2) as number[][];
      const xs = points.map((point) => point[0]!);
      const ys = points.map((point) => point[1]!);
      const providerFeatureId = `doitt_id:${doitt}`;
      const name = feature.properties?.['name'];
      const bin = feature.properties?.['bin'];
      return {
        id: featureId(providerFeatureId, sourceDigest),
        provider_feature_id: providerFeatureId,
        bbox: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)],
        footprint: { type: 'MultiPolygon', coordinates: integerPolygons },
        render_batch_id: index,
        semantic_properties: {
          bin: typeof bin === 'string' && /^[1-5][0-9]{6}$/.test(bin) ? `bin:${bin}` : null,
          name: typeof name === 'string' && name.trim().length > 0 ? name.trim() : null,
        },
      };
    });
    return {
      admission_id: NYC_ADMISSION_ID,
      publication_id: NYC_PUBLICATION_ID,
      place_id: NYC_PLACE_ID,
      render_asset_id: NYC_RENDER_ASSET_ID,
      coordinate_scale: 10_000_000,
      geographic_frame: { name: 'nyc-open-data-crs84' },
      receipt_sha256: sha256(`preview-publication:${sourceDigest}`),
      receipt: {
        source_sha256: sourceDigest,
        source_receipt_sha256: sha256(`preview-source:${sourceDigest}`),
        render_sha256: sha256(`preview-render:${sourceDigest}`),
        render_receipt_sha256: sha256(`preview-render-receipt:${sourceDigest}`),
        index_sha256: sha256(`preview-index:${sourceDigest}`),
        index_receipt_sha256: sha256(`preview-index-receipt:${sourceDigest}`),
      },
      features,
    };
  })();
  return previewNYCCatalog;
}

async function requestBody(request: import('node:http').IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.from(chunk));
  return JSON.parse(Buffer.concat(chunks).toString('utf8')) as unknown;
}

const previewApi: Plugin = {
  name: 'exulanica-atlas-preview-api',
  configureServer(server) {
    server.middlewares.use('/preview-api', async (request, response) => {
      const path = new URL(request.url ?? '/', 'http://atlas-preview.local').pathname;
      if (request.method === 'GET' &&
          path === `/environment-resources/sources/${NYC_ADMISSION_ID}/features`) {
        try {
          response.setHeader('cache-control', 'no-store');
          response.setHeader('content-type', 'application/json; charset=utf-8');
          response.end(JSON.stringify(await loadPreviewNYCCatalog()));
        } catch (error) {
          response.statusCode = 502;
          response.end(JSON.stringify({
            code: 'nyc_open_data_unavailable',
            detail: error instanceof Error ? error.message : String(error),
          }));
        }
        return;
      }
      if (request.method === 'POST' && path === '/selection/ask') {
        const body = await requestBody(request) as {
          readonly question?: unknown;
          readonly city_context?: { readonly admission_id?: unknown; readonly feature_id?: unknown };
        };
        const catalog = await loadPreviewNYCCatalog();
        const features = catalog['features'] as readonly PreviewNYCFeature[];
        const feature = body.city_context?.admission_id === NYC_ADMISSION_ID
          ? features.find((held) => held.id === body.city_context?.feature_id)
          : undefined;
        response.setHeader('cache-control', 'no-store');
        response.setHeader('content-type', 'application/json; charset=utf-8');
        if (feature === undefined) {
          response.statusCode = 422;
          response.end(JSON.stringify({
            code: 'city_context_required',
            detail: 'Select an NYC Open Data footprint before asking about the city.',
          }));
          return;
        }
        const label = feature.semantic_properties.name ?? 'an unnamed NYC building footprint';
        const doitt = feature.provider_feature_id.replace('doitt_id:', '');
        const bin = feature.semantic_properties.bin?.replace('bin:', '') ?? 'not supplied';
        response.end(JSON.stringify({
          answer: { clauses: [
            {
              text: `${label} is the selected official NYC BUILDING footprint. `
                + `Its NYC Open Data identifiers are DOITT_ID ${doitt} and BIN ${bin}.`,
              type: 'meta',
              citations: [],
              value_refs: [],
            },
            {
              text: 'Unified place retrieval found no confirmed memory links in this preview, '
                + 'so no memory is claimed to belong to the selected building.',
              type: 'meta',
              citations: [],
              value_refs: [],
            },
          ] },
          plan: null,
          selection: null,
          citations: {},
          abstained: null,
          deterministic: true,
          repaired: false,
          execution: { prompt_version: 'preview-nyc-open-data-1', calls: [] },
        }));
        return;
      }
      const decision = previewApiResponse(request.method ?? 'GET', request.url ?? '/');
      response.setHeader('cache-control', 'no-store');
      response.statusCode = decision.statusCode;
      if (decision.assetPath !== undefined) {
        response.setHeader('content-type', decision.contentType ?? 'application/octet-stream');
        response.end(await readFile(resolve(APP_ROOT, 'public', decision.assetPath)));
        return;
      }
      response.setHeader('content-type', 'application/json; charset=utf-8');
      response.end(JSON.stringify(decision.body));
    });
  },
};

/**
 * The authenticated surface.
 *
 * The API is reached through a dev proxy rather than by naming its origin in the client, so the
 * browser makes same-origin requests and no CORS policy has to exist for development that would
 * not exist in production. `EXULANICA_API_URL` moves it; the default is the port the deployment
 * guide's uvicorn command uses.
 */
export default defineConfig({
  build: { target: 'es2022' },
  plugins: [societyRecordingPlugin(resolve(APP_ROOT, '../../..')), previewApi],
  server: {
    // The workspace, plus the committed character containers the development preview fetches.
    fs: { allow: [searchForWorkspaceRoot(APP_ROOT), resolve(APP_ROOT, '../../../assets/characters')] },
    proxy: {
      '/__character': { target: process.env['EXULANICA_CHARACTER_BUILDER_URL'] ?? 'http://127.0.0.1:5196', rewrite: path => path.replace(/^\/__character/, '') },
      '/api': {
        target: process.env['EXULANICA_API_URL'] ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
});
