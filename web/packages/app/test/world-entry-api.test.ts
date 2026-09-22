import { describe, expect, it, vi } from 'vitest';
import {
  WorldEntryClient,
  automaticWorldEntry,
  requireMetadataOnlyEntryUpdate,
} from '../src/world-entry-api.js';

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
  source_attachments: [],
  created_by: '44444444-4444-4444-8444-444444444444',
  created_at: '2026-09-19T12:00:00Z',
  updated_at: '2026-09-19T12:00:00Z',
  ...overrides,
});

const attachmentWire = (overrides: Record<string, unknown> = {}) => ({
  attachment_id: '66666666-6666-4666-8666-666666666666',
  operation_id: '77777777-7777-4777-8777-777777777777',
  capture_id: '88888888-8888-4888-8888-888888888888',
  evidence_span_id: '99999999-9999-4999-8999-999999999999',
  source_sha256: 'd'.repeat(64),
  authorization_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  screening_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  role: 'reference',
  attached_entry_revision: 2,
  attached_by: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  attached_at: '2026-09-20T12:00:00Z',
  availability: 'available',
  unavailable_reason: null,
  viewer_sha256: 'e'.repeat(64),
  evidence_path: '/evidence/99999999-9999-4999-8999-999999999999/masked',
  ...overrides,
});

describe('saved world entry client', () => {
  it('accepts reference metadata refreshes but refuses older or changed scene cursors', () => {
    const active = parseFixture();
    const metadata = {
      ...active, title: 'Renamed elsewhere', revision: 2,
      sourceAttachments: active.sourceAttachments,
    };
    expect(requireMetadataOnlyEntryUpdate(active, metadata)).toBe(metadata);
    expect(() => requireMetadataOnlyEntryUpdate(active, {
      ...active, revision: 2, authoredStateSha256: 'f'.repeat(64),
    })).toThrow('changed beyond its reference metadata');
    expect(() => requireMetadataOnlyEntryUpdate({ ...active, revision: 3 }, {
      ...active, revision: 2,
    })).toThrow('older saved world response');
    expect(active.authoredStateSha256).toBe('a'.repeat(64));
  });

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

  it('creates the starter with a ground that states it has no extent, and carries none', async () => {
    const fetch = vi.fn(async () => Response.json(wire({
      source_kind: 'authored',
      authored_scene: {
        schema_version: 1,
        kind: 'authored-starter',
        region: {
          region_id: 'region:starter',
          origin: 'authored',
          module: { key: 'region.authored-ground', version: 2 },
          ground: { kind: 'endless', elevation_mm: 0 },
          spawn: { x_mm: 0, y_mm: 0, z_mm: 4000, yaw_microradians: 0 },
        },
      },
    })));
    const entry = await new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    }).ensureStarter('My world');
    expect(entry.authoredScene?.region.module.version).toBe(2);
    expect(entry.authoredScene?.region.ground).toEqual({ kind: 'endless', elevationMm: 0 });
    expect(entry.authoredScene?.region.spawn).toMatchObject({ zMm: 4000 });
  });

  /*
   * The ground module version and the ground kind are one fact.
   *
   * Version 1 is a 24 metre rectangle and version 2 states no extent. Reading either alone would
   * let a server whose halves disagree be drawn as though they agreed, and on a ground with no
   * rectangle the spawn-containment refusal has nothing left to compare, so this is the check
   * that replaces it rather than a check that was added beside it.
   */
  it.each([
    ['a ground kind its module version does not state',
      { key: 'region.authored-ground', version: 2 },
      { kind: 'flat', half_width_mm: 12000, half_depth_mm: 12000, elevation_mm: 0 },
      'unsupported authored starter region'],
    ['an endless ground under the bounded module version',
      { key: 'region.authored-ground', version: 1 },
      { kind: 'endless', elevation_mm: 0 },
      'unsupported authored starter region'],
    ['a module version this browser has no ground for',
      { key: 'region.authored-ground', version: 3 },
      { kind: 'endless', elevation_mm: 0 },
      'unsupported authored starter region'],
    ['an endless ground that declares a horizontal extent anyway',
      { key: 'region.authored-ground', version: 2 },
      { kind: 'endless', elevation_mm: 0, half_width_mm: 12000 },
      'cannot declare a horizontal extent'],
  ])('refuses %s', async (_name, module, ground, message) => {
    const fetch = vi.fn(async () => Response.json([wire({
      source_kind: 'authored',
      authored_scene: {
        schema_version: 1,
        kind: 'authored-starter',
        region: {
          region_id: 'region:starter',
          origin: 'authored',
          module,
          ground,
          spawn: { x_mm: 0, y_mm: 0, z_mm: 4000, yaw_microradians: 0 },
        },
      },
    })]));
    await expect(new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    }).entries()).rejects.toThrow(message);
  });

  it('still refuses a spawn outside a ground that really does have edges', async () => {
    const fetch = vi.fn(async () => Response.json([wire({
      source_kind: 'authored',
      authored_scene: {
        schema_version: 1,
        kind: 'authored-starter',
        region: {
          region_id: 'region:starter',
          origin: 'authored',
          module: { key: 'region.authored-ground', version: 1 },
          ground: { kind: 'flat', half_width_mm: 12000, half_depth_mm: 12000, elevation_mm: 0 },
          spawn: { x_mm: 0, y_mm: 0, z_mm: 12001, yaw_microradians: 0 },
        },
      },
    })]));
    await expect(new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    }).entries()).rejects.toThrow('spawn is outside its ground');
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

  it('attaches selected reviewed references through the complete entry cursor', async () => {
    let submitted: Record<string, unknown> | null = null;
    const attachment = attachmentWire();
    const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
      expect(new URL(String(input)).pathname).toBe(
        '/world-entries/11111111-1111-4111-8111-111111111111/source-attachments',
      );
      submitted = JSON.parse(String(init.body)) as Record<string, unknown>;
      return Response.json(wire({ revision: 2, source_attachments: [attachment] }));
    });
    const base = parseFixture();
    const updated = await new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    }).attachSources({
      entryId: base.entryId,
      operationId: attachment.operation_id,
      baseRevision: base.revision,
      authoredVersionId: base.authoredVersionId,
      authoredStateSha256: base.authoredStateSha256,
      authoredEditSeq: base.authoredEditSeq,
      styleVersionId: base.styleVersionId,
      sources: [{
        captureId: attachment.capture_id,
        evidenceSpanId: attachment.evidence_span_id,
      }],
    });
    expect(submitted).toEqual({
      operation_id: attachment.operation_id,
      base_revision: base.revision,
      authored_version_id: base.authoredVersionId,
      authored_state_sha256: base.authoredStateSha256,
      authored_edit_seq: base.authoredEditSeq,
      style_version_id: base.styleVersionId,
      sources: [{
        capture_id: attachment.capture_id,
        evidence_span_id: attachment.evidence_span_id,
      }],
    });
    expect(updated).toMatchObject({
      revision: 2,
      sourceAttachments: [{
        attachmentId: attachment.attachment_id,
        sourceSha256: attachment.source_sha256,
        viewerSha256: attachment.viewer_sha256,
        availability: 'available',
      }],
    });
  });

  it('keeps the entry available when one attached reference becomes unavailable', async () => {
    const fetch = vi.fn(async () => Response.json([wire({
      source_attachments: [attachmentWire({
        availability: 'unavailable',
        unavailable_reason: 'authorization_expired',
        viewer_sha256: null,
        evidence_path: null,
      })],
    })]));
    const entry = (await new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    }).entries())[0]!;
    expect(entry.availability).toBe('available');
    expect(entry.sourceAttachments[0]).toMatchObject({
      availability: 'unavailable', unavailableReason: 'authorization_expired',
      viewerSha256: null, evidencePath: null,
    });
    expect(automaticWorldEntry([entry])).toBe(entry);
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

  it('removes and adds back references with the exact cursor and reads removed references', async () => {
    const requests: { path: string; body: Record<string, unknown> }[] = [];
    const removed = {
      attachment_id: '66666666-6666-4666-8666-666666666666',
      operation_id: '77777777-7777-4777-8777-777777777777',
      capture_id: '88888888-8888-4888-8888-888888888888',
      evidence_span_id: '99999999-9999-4999-8999-999999999999',
      source_sha256: 'd'.repeat(64),
      authorization_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      screening_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      attached_entry_revision: 2,
      attached_at: '2026-09-20T12:00:00Z',
      detach_operation_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
      detached_entry_revision: 3,
      detached_by: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      detached_at: '2026-09-21T12:00:00Z',
      availability: 'available',
      unavailable_reason: null,
    };
    const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
      const path = new URL(String(input)).pathname;
      requests.push({ path, body: JSON.parse(String(init.body)) as Record<string, unknown> });
      if (path.endsWith('/source-detachments')) {
        return Response.json(wire({ revision: 3, previous_source_attachments: [removed] }));
      }
      return Response.json(wire({
        revision: 4,
        source_attachments: [attachmentWire({ attached_entry_revision: 4 })],
        previous_source_attachments: [],
      }));
    });
    const client = new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private', fetch,
    });
    const base = parseFixture();
    const cursor = {
      entryId: base.entryId,
      baseRevision: 2,
      authoredVersionId: base.authoredVersionId,
      authoredStateSha256: base.authoredStateSha256,
      authoredEditSeq: base.authoredEditSeq,
      styleVersionId: base.styleVersionId,
    };
    const afterRemoval = await client.detachSources({
      ...cursor, kind: 'detach', operationId: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
      attachmentIds: [removed.attachment_id],
    });
    expect(afterRemoval.sourceAttachments).toEqual([]);
    expect(afterRemoval.previousSourceAttachments).toEqual([expect.objectContaining({
      attachmentId: removed.attachment_id, captureId: removed.capture_id,
      detachOperationId: removed.detach_operation_id, detachedEntryRevision: 3,
      availability: 'available', unavailableReason: null,
    })]);
    const afterReturn = await client.rebindSources({
      ...cursor, kind: 'rebind', baseRevision: 3,
      operationId: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
      sources: [{ captureId: removed.capture_id, evidenceSpanId: removed.evidence_span_id }],
    });
    expect(afterReturn.previousSourceAttachments).toEqual([]);
    expect(requests).toEqual([
      {
        path: `/world-entries/${base.entryId}/source-detachments`,
        body: {
          operation_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', base_revision: 2,
          authored_version_id: base.authoredVersionId,
          authored_state_sha256: base.authoredStateSha256,
          authored_edit_seq: base.authoredEditSeq, style_version_id: base.styleVersionId,
          selections: [{ attachment_id: removed.attachment_id }],
        },
      },
      {
        path: `/world-entries/${base.entryId}/source-rebinds`,
        body: {
          operation_id: 'ffffffff-ffff-4fff-8fff-ffffffffffff', base_revision: 3,
          authored_version_id: base.authoredVersionId,
          authored_state_sha256: base.authoredStateSha256,
          authored_edit_seq: base.authoredEditSeq, style_version_id: base.styleVersionId,
          sources: [{ capture_id: removed.capture_id, evidence_span_id: removed.evidence_span_id }],
        },
      },
    ]);

    await expect(client.detachSources({
      ...cursor, kind: 'detach', operationId: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
      attachmentIds: [removed.attachment_id, removed.attachment_id],
    })).rejects.toThrow('only once');
    expect(requests).toHaveLength(2);
    const invalid = new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private',
      fetch: vi.fn(async () => Response.json(wire({
        previous_source_attachments: [{ ...removed, availability: 'unavailable' }],
      }))),
    });
    await expect(invalid.entry(base.entryId)).rejects.toThrow('removed reference availability');
    const older = new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private',
      fetch: vi.fn(async () => Response.json(wire())),
    });
    expect((await older.entry(base.entryId)).previousSourceAttachments).toEqual([]);
  });

  it('carries a refusal code from a membership event to the caller', async () => {
    const client = new WorldEntryClient({
      baseUrl: 'https://exulanica.test', token: 'private',
      fetch: vi.fn(async () => Response.json({
        code: 'review_required', detail: 'adding a photograph back needs a new human review',
      }, { status: 422 })),
    });
    const base = parseFixture();
    await expect(client.rebindSources({
      kind: 'rebind', entryId: base.entryId, operationId: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
      baseRevision: 3, authoredVersionId: base.authoredVersionId,
      authoredStateSha256: base.authoredStateSha256, authoredEditSeq: base.authoredEditSeq,
      styleVersionId: base.styleVersionId,
      sources: [{ captureId: 'c', evidenceSpanId: 's' }],
    })).rejects.toMatchObject({ status: 422, code: 'review_required' });
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
    sourceAttachments: [],
    createdAt: '2026-09-19T12:00:00Z',
    updatedAt: '2026-09-19T12:00:00Z',
  };
}
