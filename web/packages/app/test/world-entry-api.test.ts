import { describe, expect, it, vi } from 'vitest';
import { WorldEntryClient, automaticWorldEntry } from '../src/world-entry-api.js';

const wire = (overrides: Record<string, unknown> = {}) => ({
  entry_id: '11111111-1111-4111-8111-111111111111',
  world_id: 'world:family-garden',
  title: 'Family garden',
  source_kind: 'personal',
  source_snapshot_id: '55555555-5555-4555-8555-555555555555',
  source_snapshot_sha256: 'c'.repeat(64),
  authored_scene: null,
  authored_version_id: '22222222-2222-4222-8222-222222222222',
  authored_state_sha256: 'a'.repeat(64),
  authored_edit_seq: 4,
  current_authored_state_sha256: 'a'.repeat(64),
  current_authored_edit_seq: 4,
  style_version_id: '33333333-3333-4333-8333-333333333333',
  revision: 1,
  availability: 'available',
  unavailable_reason: null,
  created_by: '44444444-4444-4444-8444-444444444444',
  created_at: '2026-09-19T12:00:00Z',
  updated_at: '2026-09-19T12:00:00Z',
  ...overrides,
});

describe('saved world entry client', () => {
  it('automatically resumes only one available returning-user entry', async () => {
    const fetch = vi.fn(async () => Response.json([wire()]));
    const entries = await new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    }).entries();
    expect(automaticWorldEntry(entries)?.title).toBe('Family garden');
    expect(automaticWorldEntry([entries[0]!, { ...entries[0]!, entryId: 'another' }])).toBeNull();
    expect(automaticWorldEntry([{ ...entries[0]!, availability: 'unavailable' }])).toBeNull();
  });

  it('creates only after an explicit personal-source bootstrap and pins both returned versions', async () => {
    const requests: { url: URL; body: Record<string, unknown> | null }[] = [];
    const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
      const url = new URL(String(input));
      const body = typeof init.body === 'string'
        ? JSON.parse(init.body) as Record<string, unknown>
        : null;
      requests.push({ url, body });
      if (url.pathname === '/world/styles/current') {
        return Response.json({
          current_topology_digest: 'topology-personal',
          current: { version_id: '33333333-3333-4333-8333-333333333333' },
        });
      }
      if (url.pathname === '/world/versions/bootstrap') {
        return Response.json({ version_id: '22222222-2222-4222-8222-222222222222' });
      }
      if (url.pathname === '/world-entries') return Response.json(wire(), { status: 201 });
      throw new Error(`unexpected ${url.pathname}`);
    });
    await new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    }).createFromPersonalSources('Family garden');
    expect(requests.slice(0, 2).map(({ url }) => url.searchParams.get('world_id')))
      .toEqual(['atlas:default', 'atlas:default']);
    expect(requests[1]?.body).toEqual({
      base_topology_digest: 'topology-personal', title: 'Family garden',
    });
    expect(requests[2]?.body).toMatchObject({
      source_kind: 'personal',
      authored_version_id: '22222222-2222-4222-8222-222222222222',
      style_version_id: '33333333-3333-4333-8333-333333333333',
    });
  });

  it('creates or reuses the authored starter and parses its exact bounded scene', async () => {
    const fetch = vi.fn(async (_input: string | URL | Request, init: RequestInit = {}) => {
      expect(JSON.parse(String(init.body))).toEqual({ title: 'My world' });
      return Response.json(wire({
        source_kind: 'authored',
        authored_scene: {
          schema_version: 1,
          kind: 'authored-starter',
          region: {
            region_id: 'region:starter',
            origin: 'authored',
            module: { key: 'region.authored-ground', version: 1 },
            ground: {
              kind: 'flat', half_width_mm: 12000, half_depth_mm: 12000, elevation_mm: 0,
            },
            spawn: { x_mm: 0, y_mm: 0, z_mm: 4000, yaw_microradians: 0 },
          },
        },
      }));
    });
    const entry = await new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    }).ensureStarter('My world');
    expect(entry.sourceKind).toBe('authored');
    expect(entry.authoredScene?.region).toMatchObject({
      regionId: 'region:starter',
      ground: { halfWidthMm: 12000, halfDepthMm: 12000, elevationMm: 0 },
      spawn: { zMm: 4000 },
    });
  });

  it('refuses an authored entry whose pinned scene is missing', async () => {
    const fetch = vi.fn(async () => Response.json([wire({
      source_kind: 'authored', authored_scene: null,
    })]));
    await expect(new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    }).entries()).rejects.toThrow('did not include its pinned authored scene');
  });

  it('saves a supported appearance change and reopens that exact style after reload', async () => {
    let held = wire();
    const calls: { method: string; body: Record<string, unknown> | null }[] = [];
    const fetch = vi.fn(async (_input: string | URL | Request, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      const body = typeof init.body === 'string'
        ? JSON.parse(init.body) as Record<string, unknown>
        : null;
      calls.push({ method, body });
      if (method === 'PUT') {
        held = wire({
          revision: 2,
          style_version_id: body!['style_version_id'],
          updated_at: '2026-09-19T12:01:00Z',
        });
        return Response.json(held);
      }
      return Response.json([held]);
    });
    const options = {
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    };
    const firstSession = new WorldEntryClient(options);
    const opened = (await firstSession.entries())[0]!;
    const saved = await firstSession.saveVersion(opened, {
      authoredVersionId: opened.authoredVersionId,
      authoredStateSha256: opened.authoredStateSha256,
      authoredEditSeq: opened.authoredEditSeq,
      styleVersionId: '55555555-5555-4555-8555-555555555555',
    });
    expect(saved.revision).toBe(2);

    const reloaded = (await new WorldEntryClient(options).entries())[0]!;
    expect(reloaded.styleVersionId).toBe('55555555-5555-4555-8555-555555555555');
    expect(calls.find((call) => call.method === 'PUT')?.body).toMatchObject({
      base_revision: 1,
      authored_version_id: opened.authoredVersionId,
      expected_authored_state_sha256: opened.authoredStateSha256,
      expected_authored_edit_seq: opened.authoredEditSeq,
      style_version_id: '55555555-5555-4555-8555-555555555555',
    });
  });

  it('renames through the exact saved cursor without moving it', async () => {
    let submitted: Record<string, unknown> | null = null;
    const fetch = vi.fn(async (_input: string | URL | Request, init: RequestInit = {}) => {
      submitted = JSON.parse(String(init.body)) as Record<string, unknown>;
      return Response.json(wire({ title: 'Quiet garden', revision: 2 }));
    });
    const base = parseFixture();
    const renamed = await new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    }).rename(base, 'Quiet garden');
    expect(renamed.title).toBe('Quiet garden');
    expect(submitted).toEqual({
      base_revision: base.revision,
      authored_version_id: base.authoredVersionId,
      expected_authored_state_sha256: base.authoredStateSha256,
      expected_authored_edit_seq: base.authoredEditSeq,
      style_version_id: base.styleVersionId,
      title: 'Quiet garden',
    });
  });

  it('refuses a second tab that saves from the revision both tabs originally opened', async () => {
    let revision = 1;
    const fetch = vi.fn(async (_input: string | URL | Request, init: RequestInit = {}) => {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      if (body['base_revision'] !== revision) {
        return Response.json({
          code: 'stale_saved_world_entry', detail: 'the saved world changed elsewhere',
        }, { status: 409 });
      }
      revision += 1;
      return Response.json(wire({ revision }));
    });
    const client = new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    });
    const openedInBothTabs = parseFixture();
    await client.saveVersion(openedInBothTabs, {
      authoredVersionId: openedInBothTabs.authoredVersionId,
      authoredStateSha256: openedInBothTabs.authoredStateSha256,
      authoredEditSeq: openedInBothTabs.authoredEditSeq,
      styleVersionId: openedInBothTabs.styleVersionId,
    });
    await expect(client.saveVersion(openedInBothTabs, {
      authoredVersionId: openedInBothTabs.authoredVersionId,
      authoredStateSha256: openedInBothTabs.authoredStateSha256,
      authoredEditSeq: openedInBothTabs.authoredEditSeq,
      styleVersionId: openedInBothTabs.styleVersionId,
    })).rejects.toMatchObject({ code: 'stale_saved_world_entry' });
  });

  it('keeps invalidated entries visible and explicitly unavailable', async () => {
    const fetch = vi.fn(async () => Response.json([wire({
      availability: 'unavailable', unavailable_reason: 'source_deleted',
    })]));
    const entry = (await new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    }).entries())[0]!;
    expect(entry).toMatchObject({ availability: 'unavailable', unavailableReason: 'source_deleted' });
  });

  it('adopts only the exact current authored cursor returned by the compared entry read', async () => {
    let submitted: Record<string, unknown> | null = null;
    const fetch = vi.fn(async (_input: string | URL | Request, init: RequestInit = {}) => {
      submitted = JSON.parse(String(init.body)) as Record<string, unknown>;
      return Response.json(wire({
        revision: 2,
        authored_state_sha256: 'b'.repeat(64),
        authored_edit_seq: 6,
        current_authored_state_sha256: 'b'.repeat(64),
        current_authored_edit_seq: 6,
      }));
    });
    const client = new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    });
    await client.adoptLatestAuthored({
      ...parseFixture(),
      availability: 'unavailable',
      unavailableReason: 'authored_version_changed',
      currentAuthoredStateSha256: 'b'.repeat(64),
      currentAuthoredEditSeq: 6,
    });
    expect(submitted).toMatchObject({
      base_revision: 1,
      expected_authored_state_sha256: 'b'.repeat(64),
      expected_authored_edit_seq: 6,
    });
  });
});

function parseFixture() {
  return {
    entryId: '11111111-1111-4111-8111-111111111111',
    worldId: 'world:family-garden',
    title: 'Family garden',
    sourceKind: 'personal' as const,
    sourceSnapshotId: '55555555-5555-4555-8555-555555555555',
    sourceSnapshotSha256: 'c'.repeat(64),
    authoredScene: null,
    authoredVersionId: '22222222-2222-4222-8222-222222222222',
    authoredStateSha256: 'a'.repeat(64),
    authoredEditSeq: 4,
    currentAuthoredStateSha256: 'a'.repeat(64),
    currentAuthoredEditSeq: 4,
    styleVersionId: '33333333-3333-4333-8333-333333333333',
    revision: 1,
    availability: 'available' as const,
    unavailableReason: null,
    createdAt: '2026-09-19T12:00:00Z',
    updatedAt: '2026-09-19T12:00:00Z',
  };
}
