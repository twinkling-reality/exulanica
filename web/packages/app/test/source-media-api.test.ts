import { describe, expect, it, vi } from 'vitest';
import { SourceMediaClient } from '../src/source-media-api.js';

const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status,
  headers: { 'content-type': 'application/json' },
});

const source = (overrides: Record<string, unknown> = {}) => ({
  source_id: 'source-1',
  slot_key: 'hero-memory',
  region_id: 'region-a',
  capture_ids: ['capture-1'],
  state: 'available',
  reason: null,
  evidence_span_id: 'span-1',
  evidence_path: '/evidence/span-1',
  modality: 'frame_region',
  media_type: 'image/jpeg',
  byte_size: 2,
  width: 800,
  height: 600,
  captured_at: '2026-08-30T10:00:00Z',
  captured_at_uncertainty_ms: 0,
  asset_reference: {
    href: '/evidence/span-1',
    authorization: 'workspace-bearer',
    provenance: { source_id: 'source-1', evidence_span_id: 'span-1' },
  },
  ...overrides,
});

describe('production source media boundary', () => {
  it('fetches available bytes with bearer authorization and revokes its blob URL', async () => {
    const requests: { path: string; init: RequestInit }[] = [];
    const revoke = vi.fn();
    const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
      const path = new URL(String(input)).pathname;
      requests.push({ path, init });
      if (path.endsWith('/graph/sources')) return json([]);
      if (path.endsWith('/world/source-media')) return json([source()]);
      return new Response(new Uint8Array([0xff, 0xd8]), {
        status: 200, headers: { 'content-type': 'image/jpeg' },
      });
    });
    const client = new SourceMediaClient({
      baseUrl: 'https://exulanica.test/api', token: 'private-token', fetch,
      createObjectURL: () => 'blob:source-1', revokeObjectURL: revoke,
    });
    const session = await client.load('#7c71b5');
    expect(session.catalog.get('span-1')).toMatchObject({
      available: true, url: 'blob:source-1', evidenceRef: 'span-1',
      regionId: 'region-a', captureIds: ['capture-1'],
    });
    expect(requests.map((request) => request.path)).toEqual([
      '/api/graph/sources', '/api/world/source-media', '/api/evidence/span-1',
    ]);
    expect((requests[1]!.init.headers as Record<string, string>).authorization)
      .toBe('Bearer private-token');
    session.dispose();
    session.dispose();
    expect(revoke).toHaveBeenCalledOnce();
  });

  it('keeps missing, unavailable, and unauthorized sources distinct without replacement art', async () => {
    const values = [
      source({
        source_id: 'missing', state: 'missing_evidence', evidence_span_id: null,
        evidence_path: null, asset_reference: null, reason: 'no evidence was recorded',
      }),
      source({
        source_id: 'unavailable', evidence_span_id: 'span-2', state: 'unavailable_asset',
        evidence_path: null, asset_reference: null, reason: 'capture was purged',
      }),
      source({ source_id: 'unauthorized', evidence_span_id: 'span-3', evidence_path: '/evidence/span-3',
        asset_reference: {
          href: '/evidence/span-3', authorization: 'workspace-bearer',
          provenance: { source_id: 'unauthorized', evidence_span_id: 'span-3' },
        } }),
    ];
    const fetch = vi.fn(async (input: string | URL | Request) => {
      const path = new URL(String(input)).pathname;
      if (path.endsWith('/graph/sources')) return json([]);
      if (path.endsWith('/world/source-media')) return json(values);
      return json({ code: 'not_authenticated', detail: 'token expired' }, 401);
    });
    const session = await new SourceMediaClient({
      baseUrl: 'https://exulanica.test/api', token: 't', fetch,
      createObjectURL: () => 'never', revokeObjectURL: vi.fn(),
    }).load('#7c71b5');
    expect(session.issues.map((issue) => issue.state)).toEqual([
      'missing_evidence', 'unavailable_asset', 'unauthorized',
    ]);
    expect(session.catalog.get('span-2')).toMatchObject({ available: false, url: null });
    expect(session.catalog.get('span-3')?.alt).toContain('not authorized');
  });

  it('rejects remote or mismatched asset references before fetching bytes', async () => {
    const fetch = vi.fn(async (input: string | URL | Request) => new URL(String(input)).pathname.endsWith('/graph/sources') ? json([]) : json([source({
      evidence_path: 'https://assets.example.test/private.jpg',
      asset_reference: {
        href: 'https://assets.example.test/private.jpg',
        authorization: 'workspace-bearer',
        provenance: { source_id: 'source-1', evidence_span_id: 'span-1' },
      },
    })]));
    const session = await new SourceMediaClient({
      baseUrl: 'https://exulanica.test/api', token: 't', fetch,
      createObjectURL: () => 'never', revokeObjectURL: vi.fn(),
    }).load('#7c71b5');
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(session.issues[0]).toMatchObject({ state: 'error' });
    expect(session.catalog.get('span-1')).toMatchObject({ available: false, url: null });
  });

  it('surfaces list loading failures instead of fabricating an empty successful catalog', async () => {
    const client = new SourceMediaClient({
      baseUrl: 'https://exulanica.test/api', token: 't',
      fetch: vi.fn(async () => { throw new TypeError('network offline'); }),
    });
    await expect(client.load('#7c71b5')).rejects.toThrow('network offline');
  });
});

const imageBytes = new Uint8Array([0xff, 0xd8]);
async function admitted(overrides: Record<string, unknown> = {}) {
  const digest = await crypto.subtle.digest('SHA-256', imageBytes);
  return {
    kind: 'admitted_capture', capture_id: 'capture-1', evidence_span_id: 'span-1',
    state: 'available', reason: null, evidence_path: '/evidence/span-1/masked',
    media_type: 'image/jpeg', captured_at: null, person_regions: [], person_review_state: 'unscreened',
    content_sha256: [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join(''),
    ...overrides,
  };
}

describe('admitted sources before composition', () => {
  it('loads authenticated inventory without a world and clears every URL at session disposal', async () => {
    const row = await admitted();
    const revoke = vi.fn();
    const fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      expect((init?.headers as Record<string, string>).authorization).toBe('Bearer review-token');
      const path = new URL(String(input)).pathname;
      if (path.endsWith('/graph/sources')) return json([row]);
      if (path.endsWith('/world/source-media')) return json({ code: 'world_not_configured', detail: 'No world' }, 409);
      expect(path).toBe('/api/evidence/span-1/masked');
      return new Response(imageBytes, { headers: { 'content-type': 'image/jpeg' } });
    });
    const session = await new SourceMediaClient({ baseUrl: 'https://example.test/api', token: 'review-token', fetch,
      createObjectURL: () => 'blob:admitted', revokeObjectURL: revoke }).load('blue');
    expect(session.catalog.get('capture-1')).toMatchObject({ regionId: null, captureIds: ['capture-1'], available: true });
    session.dispose();
    session.dispose();
    expect(session.catalog.size).toBe(0);
    expect(revoke).toHaveBeenCalledOnce();
    expect(revoke).toHaveBeenCalledWith('blob:admitted');
  });

  it('deduplicates bytes by evidence while preserving topology aliases', async () => {
    const row = await admitted();
    const fetch = vi.fn(async (input: string | URL | Request) => {
      const path = new URL(String(input)).pathname;
      if (path.endsWith('/graph/sources')) return json([row]);
      if (path.endsWith('/world/source-media')) return json([source(), source({ source_id: 'second-slot' })]);
      return new Response(imageBytes, { headers: { 'content-type': 'image/jpeg' } });
    });
    const create = vi.fn(() => 'blob:shared');
    const session = await new SourceMediaClient({ baseUrl: 'https://example.test', token: 't', fetch,
      createObjectURL: create, revokeObjectURL: vi.fn() }).load('blue');
    expect(create).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledTimes(3);
    for (const key of ['capture-1', 'span-1', 'source-1', 'second-slot']) expect(session.catalog.get(key)?.url).toBe('blob:shared');
    expect(session.catalog.get('source-1')?.regionId).toBe('region-a');
  });

  it.each(['withdrawn', 'missing', 'changed', 'denied', 'cross-workspace'])('withholds %s source bytes', async (condition) => {
    const rows = condition === 'withdrawn' ? [] : [await admitted(condition === 'missing'
      ? { state: 'unavailable_asset', evidence_path: null, content_sha256: null } : {})];
    const create = vi.fn(() => 'never');
    const fetch = vi.fn(async (input: string | URL | Request) => {
      const path = new URL(String(input)).pathname;
      if (path.endsWith('/graph/sources')) return json(rows);
      if (path.endsWith('/world/source-media')) return json([]);
      if (condition === 'denied') return json({ code: 'not_authenticated', detail: 'Session expired' }, 401);
      if (condition === 'cross-workspace') return json({ code: 'not_found', detail: 'No evidence' }, 404);
      return new Response(new Uint8Array([0]), { headers: { 'content-type': 'image/jpeg' } });
    });
    const session = await new SourceMediaClient({ baseUrl: 'https://example.test', token: 't', fetch,
      createObjectURL: create, revokeObjectURL: vi.fn() }).load('blue');
    expect(create).not.toHaveBeenCalled();
    expect([...session.catalog.values()].every((entry) => !entry.available)).toBe(true);
    if (condition === 'withdrawn' || condition === 'missing') expect(fetch).toHaveBeenCalledTimes(2);
  });
});
