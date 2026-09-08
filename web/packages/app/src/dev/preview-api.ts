/** Pure request policy for the Vite-only Atlas preview endpoint. */

import { PREVIEW_GRAPH } from './preview-graph.js';
import { previewSource } from './preview-media.js';

export interface PreviewApiResponse {
  readonly statusCode: number;
  readonly body: unknown;
  readonly contentType?: string;
  readonly assetPath?: string;
}

export function previewApiResponse(method: string, requestUrl: string): PreviewApiResponse {
  if (method !== 'GET') {
    return {
      statusCode: 403,
      body: { code: 'preview_read_only', detail: 'The Atlas preview cannot write data.' },
    };
  }
  const missing: PreviewApiResponse = {
    statusCode: 404,
    body: { code: 'preview_route_not_found', detail: 'That resource is not part of the Atlas preview.' },
  };
  let path: string;
  try {
    path = new URL(requestUrl, 'http://atlas-preview.local').pathname;
  } catch {
    return missing;
  }
  if (method === 'GET' && path === '/graph') {
    return { statusCode: 200, body: PREVIEW_GRAPH };
  }
  if (method === 'GET' && path === '/formation') {
    return { statusCode: 200, body: [] };
  }
  const evidence = /^\/evidence\/([^/]+)(?:\/masked)?$/.exec(path);
  if (evidence !== null) {
    let evidenceRef: string;
    try {
      evidenceRef = decodeURIComponent(evidence[1]!);
    } catch {
      return missing;
    }
    if (!/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(evidenceRef)) return missing;
    // Both exact-original and current-view routes use this same synthetic photograph.
    // This preview has no consent resolver or masked derivative and asserts no live permission.
    const source = previewSource(evidenceRef);
    if (source?.available === true && source.assetPath !== null) {
      return {
        statusCode: 200,
        body: null,
        contentType: source.assetPath.endsWith('.jpg') ? 'image/jpeg' : 'image/png',
        assetPath: source.assetPath,
      };
    }
    return {
      statusCode: 404,
      body: {
        code: 'preview_evidence_unavailable',
        detail: 'This synthetic memory deliberately demonstrates unavailable source evidence.',
      },
    };
  }
  return missing;
}
