import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import {
  EnvironmentSelectionClient,
  parseEnvironmentCatalog,
} from '../src/environment-selection-api.js';
import { parseVersion } from '../src/world-objects-api.js';

const VERSION = JSON.parse(readFileSync(
  new URL('../../graph-client/test/fixtures/world-objects.json', import.meta.url),
  'utf8',
)) as Record<string, unknown>;
const ADMISSION = '12345678-1234-4123-8123-123456789abc';
const PUBLICATION = '22345678-1234-4123-8123-123456789abc';
const RENDER = '32345678-1234-4123-8123-123456789abc';
const hash = (digit: string): string => digit.repeat(64);
const catalogBody = {
  admission_id: ADMISSION,
  publication_id: PUBLICATION,
  place_id: '42345678-1234-4123-8123-123456789abc',
  index_asset_id: '52345678-1234-4123-8123-123456789abc',
  render_asset_id: RENDER,
  geographic_frame: { name: 'nyc-open-data-crs84' },
  coordinate_scale: 10_000_000,
  receipt_sha256: hash('6'),
  receipt: {
    source_sha256: hash('1'),
    source_receipt_sha256: hash('2'),
    index_sha256: hash('3'),
    index_receipt_sha256: hash('4'),
    render_sha256: hash('5'),
    render_receipt_sha256: hash('7'),
  },
  features: [{
    id: '0123456789abcdef0123456789abcdef',
    provider_feature_id: 'doitt_id:2327',
    kind: 'building',
    bbox: [-739904139, 407238475, -739902608, 407239894],
    label: null,
    render_batch_id: 0,
    footprint: { type: 'MultiPolygon', coordinates: [[[
      [-739904139, 407238475], [-739902608, 407238475],
      [-739902608, 407239894], [-739904139, 407238475],
    ]]] },
    semantic_properties: { bin: 'bin:1006070', name: null },
  }],
};

function subject(responses: Response[]) {
  const calls: { path: string; body: Record<string, unknown> | null }[] = [];
  const fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({
      path: new URL(String(url)).pathname,
      body: typeof init?.body === 'string'
        ? JSON.parse(init.body) as Record<string, unknown> : null,
    });
    return responses.shift()!;
  });
  return {
    calls,
    client: new EnvironmentSelectionClient({
      baseUrl: 'https://example.test',
      token: 'token',
      fetch: fetch as unknown as typeof globalThis.fetch,
    }),
  };
}

describe('NYC environment selection API', () => {
  it('reads independent identity, footprint, BIN, and exact publication digests', () => {
    const parsed = parseEnvironmentCatalog(catalogBody);
    expect(parsed.features[0]).toMatchObject({
      providerFeatureId: 'doitt_id:2327',
      bin: 'bin:1006070',
      renderBatchId: 0,
    });
    expect(parsed.sourceSha256).toBe(hash('1'));
    expect(parsed.renderSha256).toBe(hash('5'));
    expect(parsed.indexSha256).toBe(hash('3'));
  });

  it('binds a feature placement to the exact publication and user-chosen fictional role', async () => {
    const response = structuredClone(VERSION);
    response['environment_instances'] = [];
    const { client, calls } = subject([
      new Response(JSON.stringify(response), { status: 201 }),
    ]);
    const catalog = parseEnvironmentCatalog(catalogBody);
    const result = await client.add(parseVersion(VERSION), catalog, {
      instanceId: 'nyc-open-data:doitt_id-2327',
      feature: catalog.features[0]!,
      sourceAnchor: [-739903374, 407239184],
      regionId: 'region-a',
      transform: { xMm: 10, yMm: 0, zMm: 20, yawMicroradians: 0, scaleMilli: 1000 },
      originRole: 'fictional',
    });
    expect(result.kind).toBe('recorded');
    expect(calls[0]!.path).toContain('/environment-instances');
    expect(calls[0]!.body).toMatchObject({
      admission_id: ADMISSION,
      render_asset_id: RENDER,
      publication_id: PUBLICATION,
      origin_role: 'fictional',
      selection: {
        kind: 'feature',
        feature_id: '0123456789abcdef0123456789abcdef',
        render_batch_id: 0,
      },
    });
  });

  it('reloads the current version after stale CAS without retrying the edit', async () => {
    const { client, calls } = subject([
      new Response(JSON.stringify({ code: 'stale_structural_base', detail: 'stale' }), {
        status: 409, headers: { 'content-type': 'application/json' },
      }),
      new Response(JSON.stringify(VERSION), { status: 200 }),
    ]);
    const result = await client.undo(parseVersion(VERSION));
    expect(result.kind).toBe('stale');
    expect(calls).toHaveLength(2);
    expect(calls[1]!.path).toContain(`/world/versions/${VERSION['version_id'] as string}`);
  });

  it('captures the selected binding and role in a deterministic preview, then applies exactly it', async () => {
    const response = structuredClone(VERSION);
    response['environment_instances'] = [];
    const { client, calls } = subject([
      new Response(JSON.stringify(response), { status: 201 }),
    ]);
    const parsed = parseVersion(VERSION);
    const selected = parseEnvironmentCatalog(catalogBody);
    const proposal = client.deterministicPlace(parsed, selected, {
      instanceId: 'nyc-open-data:doitt_id-2327',
      feature: selected.features[0]!,
      sourceAnchor: [-739903374, 407239184],
      regionId: 'region-a',
      transform: { xMm: 10, yMm: 0, zMm: 20, yawMicroradians: 0, scaleMilli: 1000 },
      originRole: 'personal',
    });

    expect(calls).toHaveLength(0);
    expect(proposal.originRole).toBe('personal');
    await client.apply(proposal);
    expect(calls[0]!.body).toMatchObject({
      base_state_sha256: VERSION['state_sha256'],
      admission_id: ADMISSION,
      publication_id: PUBLICATION,
      render_asset_id: RENDER,
      origin_role: 'personal',
      selection: {
        feature_id: '0123456789abcdef0123456789abcdef',
        render_batch_id: 0,
      },
    });
  });

  it('serializes mutations so two applies cannot race on one held base', async () => {
    let releaseFirst!: (value: Response) => void;
    const first = new Promise<Response>((resolve) => { releaseFirst = resolve; });
    let calls = 0;
    const fetch = vi.fn(() => {
      calls += 1;
      return calls === 1
        ? first
        : Promise.resolve(new Response(JSON.stringify(VERSION), { status: 200 }));
    });
    const client = new EnvironmentSelectionClient({
      baseUrl: 'https://example.test',
      token: 'token',
      fetch: fetch as unknown as typeof globalThis.fetch,
    });
    const held = parseVersion(VERSION);

    const one = client.undo(held);
    const two = client.undo(held);
    await Promise.resolve();
    expect(fetch).toHaveBeenCalledTimes(1);
    releaseFirst(new Response(JSON.stringify(VERSION), { status: 200 }));
    await one;
    await two;
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
