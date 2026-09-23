// @vitest-environment happy-dom

import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import {
  COMPOSITION_BLOCKED_REASONS,
  CompositionContractError,
  CompositionRequestError,
  applyComposition,
  isCompositionBlockedReason,
  compositionRequestBody,
  parseCompositionPreview,
  previewComposition,
  type CompositionApplyRequest,
} from '../src/composition-preview-api.js';
import {
  COMPOSITION_BLOCKED_WORDS,
  describeReady,
  explainCompositionFailure,
} from '../src/ui/composition-preview.js';
import {
  WorldObjectsClient,
  WorldObjectsContractError,
  parseVersion,
  type AlternateVersion,
} from '../src/world-objects-api.js';

/**
 * Composition preview and apply at the wire, against the contract's own shapes.
 *
 * The transport here is a fetch that records the whole URL, so the world a request names is
 * checked as the server would read it: a starter world that omitted `?world_id=` would resolve in
 * the default world and answer as absent.
 */

const STARTER_WORLD = 'world:authored:5d1c0000-0000-4000-8000-000000000001';

/** One `GET /world/versions/{id}` body of a starter world with nothing added yet. */
const FIXTURE: Readonly<Record<string, unknown>> = Object.freeze({
  schema_version: 1,
  version_id: '0b6f0000-0000-4000-8000-000000000001',
  world_id: STARTER_WORLD,
  source_snapshot_id: '0b6f0000-0000-4000-8000-000000000002',
  parent_version_id: null,
  title: 'My world',
  origin: 'authored',
  style_version_id: null,
  state_sha256: '9'.repeat(64),
  edit_seq: 0,
  source_invalidated: false,
  created_by: '0b6f0000-0000-4000-8000-000000000003',
  created_at: '2026-09-22T12:00:00+00:00',
  objects: [],
  element_overrides: [],
  edits: [],
});

const base = (): AlternateVersion => parseVersion({ ...FIXTURE, world_id: STARTER_WORLD });

interface Sent {
  readonly method: string;
  readonly url: URL;
  readonly body: Record<string, unknown> | undefined;
}

function wire(answer: (sent: Sent) => Response) {
  const sent: Sent[] = [];
  const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const request: Sent = {
      method: init?.method ?? 'GET',
      url: new URL(String(url)),
      body: typeof init?.body === 'string'
        ? JSON.parse(init.body) as Record<string, unknown>
        : undefined,
    };
    sent.push(request);
    return answer(request);
  });
  return { sent, fetch: fetchImpl as unknown as typeof globalThis.fetch };
}

const json = (status: number, body: unknown): Response => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json' },
});

/** The contract's refusal body: exactly a code and a detail, the stable reason being the detail. */
const problem = (status: number, code: string, detail: string): Response =>
  json(status, { code, detail });

function readyAnswer(version: AlternateVersion, subjectId: string): Record<string, unknown> {
  return {
    availability: 'ready',
    blocked_reason: null,
    blocked_detail: null,
    source: {
      kind: 'reviewed_asset', asset_key: 'cc0.marker-cube',
      content_sha256: 'b'.repeat(64), bytes: 'available',
    },
    version: {
      authored_version_id: version.versionId,
      world_id: version.worldId,
      state_sha256: version.stateSha256,
      edit_seq: version.editSeq,
      source_snapshot_id: version.sourceSnapshotId,
      style_version_id: null,
    },
    would_change: {
      kind: 'add_object',
      subject_id: subjectId,
      document: { object_id: subjectId, removed: false },
      preserves: ['source_snapshot_id', 'style_version_id', 'other_subjects', 'prior_edits'],
    },
  };
}

const placement: CompositionApplyRequest = Object.freeze({
  source: { kind: 'reviewed_asset' as const, assetKey: 'cc0.marker-cube' },
  placement: {
    subjectId: 'object:lantern',
    regionId: 'region:starter',
    transform: { xMm: 1200, yMm: 0, zMm: -450, yawMicroradians: 785398, scaleMilli: 1000 },
    originRole: 'fictional' as const,
    behaviour: null,
  },
});

const ENTRY_ID = '99999999-9999-4999-8999-999999999999';

const entryBinding = () => ({
  entryId: ENTRY_ID,
  revision: 3,
  authoredVersionId: String(FIXTURE['version_id']),
  authoredStateSha256: String(FIXTURE['state_sha256']),
  authoredEditSeq: Number(FIXTURE['edit_seq']),
});

describe('the request names references and intent, never readiness', () => {
  it('sends a reviewed asset by key with the exact pose, in wire names and nothing else', () => {
    expect(compositionRequestBody(placement)).toEqual({
      source: { kind: 'reviewed_asset', asset_key: 'cc0.marker-cube' },
      placement: {
        subject_id: 'object:lantern',
        region_id: 'region:starter',
        transform: {
          x_mm: 1200, y_mm: 0, z_mm: -450, yaw_microradians: 785398, scale_milli: 1000,
        },
        origin_role: 'fictional',
        behaviour: null,
      },
    });
  });

  it('shapes an environment placement for the contract and refuses a mixed one before sending', () => {
    const environment = {
      source: {
        kind: 'environment_admission' as const,
        admissionId: 'admission', renderAssetId: 'render', publicationId: 'publication',
        selection: { kind: 'feature' as const, featureId: 'f'.repeat(32), renderBatchId: 3 },
      },
      placement: {
        ...placement.placement,
        behaviour: null,
        sourceAnchor: { frameName: 'utm-18n', coordinateScale: 100, coordinates: [1, 2] },
      },
    };
    const body = compositionRequestBody(environment);
    expect(body['source']).toEqual({
      kind: 'environment_admission', admission_id: 'admission', render_asset_id: 'render',
      publication_id: 'publication',
      selection: { kind: 'feature', feature_id: 'f'.repeat(32), render_batch_id: 3 },
    });
    const sentPlacement = body['placement'] as Record<string, unknown>;
    expect(sentPlacement['source_anchor']).toEqual({
      frame_name: 'utm-18n', coordinate_scale: 100, coordinates: [1, 2],
    });
    // Behaviour belongs to reviewed assets; the server refuses the field on any other kind.
    expect('behaviour' in sentPlacement).toBe(false);

    expect(() => compositionRequestBody({
      ...environment,
      placement: { ...environment.placement, behaviour: {
        behaviourKey: 'motion.bounded-path', behaviourVersion: 1, parameters: {},
      } },
    })).toThrow(CompositionRequestError);
    expect(() => compositionRequestBody({
      ...placement,
      placement: { ...placement.placement, sourceAnchor: environment.placement.sourceAnchor },
    })).toThrow(CompositionRequestError);
  });
});

describe('preview and apply through the version client', () => {
  it('previews with the base it read and the world it belongs to, and no entry binding', async () => {
    const version = base();
    const { sent, fetch } = wire(() => json(200, readyAnswer(version, 'object:lantern')));
    const client = new WorldObjectsClient({
      baseUrl: 'https://exulanica.test', token: 'token', fetch,
      worldId: STARTER_WORLD, savedEntry: entryBinding,
    });
    const preview = await previewComposition(client, version, placement);

    expect(sent).toHaveLength(1);
    expect(sent[0]!.method).toBe('POST');
    expect(sent[0]!.url.pathname)
      .toBe(`/world/versions/${version.versionId}/compositions/preview`);
    expect(sent[0]!.url.searchParams.get('world_id')).toBe(STARTER_WORLD);
    // Preview refuses a saved-entry binding, and nothing here may claim readiness.
    expect(Object.keys(sent[0]!.body!).sort()).toEqual(['base_state_sha256', 'placement', 'source']);
    expect(sent[0]!.body!['base_state_sha256']).toBe(version.stateSha256);
    expect(preview.availability).toBe('ready');
    expect(preview.version.worldId).toBe(STARTER_WORLD);
    expect(preview.wouldChange.subjectId).toBe('object:lantern');
  });

  it('names the version’s own world when the client was given none', async () => {
    const version = base();
    const { sent, fetch } = wire(() => json(200, readyAnswer(version, 'object:lantern')));
    const client = new WorldObjectsClient({ baseUrl: 'https://exulanica.test', token: 'token', fetch });
    await previewComposition(client, version, placement);
    expect(sent[0]!.url.searchParams.get('world_id')).toBe(STARTER_WORLD);
  });

  it('applies the same request with the base and entry binding, and advances the entry', async () => {
    const version = base();
    const { sent, fetch } = wire(() => json(201, { ...FIXTURE, world_id: STARTER_WORLD }));
    const advanced = vi.fn(async () => undefined);
    const client = new WorldObjectsClient({
      baseUrl: 'https://exulanica.test', token: 'token', fetch,
      worldId: STARTER_WORLD, savedEntry: entryBinding, onSavedEntryAdvanced: advanced,
    });
    const result = await applyComposition(client, version, placement);

    expect(result.kind).toBe('recorded');
    expect(sent[0]!.url.pathname).toBe(`/world/versions/${version.versionId}/compositions/apply`);
    expect(sent[0]!.url.searchParams.get('world_id')).toBe(STARTER_WORLD);
    expect(sent[0]!.body).toEqual({
      ...compositionRequestBody(placement),
      base_state_sha256: version.stateSha256,
      saved_entry: {
        entry_id: ENTRY_ID,
        base_revision: 3,
        authored_state_sha256: version.stateSha256,
        authored_edit_seq: version.editSeq,
      },
    });
    expect(advanced).toHaveBeenCalledOnce();
  });

  it('turns a stale base refusal into a re-read of the version, never an overwrite', async () => {
    const version = base();
    const { sent, fetch } = wire((request) => request.method === 'POST'
      ? problem(409, 'composition_blocked', 'stale_base')
      : json(200, { ...FIXTURE, world_id: STARTER_WORLD, state_sha256: 'd'.repeat(64) }));
    const client = new WorldObjectsClient({
      baseUrl: 'https://exulanica.test', token: 'token', fetch, worldId: STARTER_WORLD,
    });
    const result = await applyComposition(client, version, placement);
    expect(result.kind).toBe('stale');
    expect(result.kind === 'stale' ? result.current.stateSha256 : null).toBe('d'.repeat(64));
    expect(sent.map((item) => item.method)).toEqual(['POST', 'GET']);
    expect(sent[1]!.url.searchParams.get('world_id')).toBe(STARTER_WORLD);
  });

  it('passes every other refusal through with its code, and says it in words', async () => {
    const version = base();
    const { fetch } = wire(() => problem(409, 'composition_blocked', 'asset_bytes_unavailable'));
    const client = new WorldObjectsClient({ baseUrl: 'https://exulanica.test', token: 'token', fetch });
    const failure = await applyComposition(client, version, placement).then(
      () => null,
      (error: unknown) => error,
    );
    expect(failure).toBeInstanceOf(ApiError);
    const words = explainCompositionFailure(failure, 'apply');
    expect(words.code).toBe('asset_bytes_unavailable');
    expect(words.happened).toBe(COMPOSITION_BLOCKED_WORDS.asset_bytes_unavailable.happened);
    expect(words.outcome).toBe('unchanged');
  });
});

/**
 * A 3D estimate from a photo is composed on routes of its own, which also require
 * `admission.read`; the generic pair refuses the kind. The client picks the route from the body.
 */
describe('a 3D estimate from a photo goes to its own route', () => {
  const ATTACHMENT_ID = '77777777-7777-4777-8777-777777777777';
  const photo: CompositionApplyRequest = Object.freeze({
    source: { kind: 'photo_point_map' as const, entryId: ENTRY_ID, attachmentId: ATTACHMENT_ID },
    placement: {
      subjectId: 'point-map:kitchen',
      regionId: 'region:starter',
      transform: { xMm: 1200, yMm: 0, zMm: -450, yawMicroradians: 785398, scaleMilli: 1000 },
      originRole: 'personal' as const,
    },
  });

  /** The server's ready answer for this kind: the source names what resolved it. */
  function photoReady(version: AlternateVersion): Record<string, unknown> {
    const ready = readyAnswer(version, 'point-map:kitchen');
    return {
      ...ready,
      source: {
        kind: 'photo_point_map', entry_id: ENTRY_ID, attachment_id: ATTACHMENT_ID,
        content_sha256: 'c'.repeat(64), bytes: 'available',
        capture_id: '66666666-6666-4666-8666-666666666666',
        model: {
          destination: 'local-process', identifier: 'test/plane-depth', provider: 'local',
          revision: '1'.repeat(40), role: 'depth',
        },
        declared_metric: true, rung: 3,
      },
      would_change: {
        ...ready['would_change'] as Record<string, unknown>,
        kind: 'add_point_map',
        document: { instance_id: 'point-map:kitchen', removed: false },
      },
    };
  }

  it('previews on the estimate’s route and reads the answer as a placed estimate', async () => {
    const version = base();
    const { sent, fetch } = wire(() => json(200, photoReady(version)));
    const client = new WorldObjectsClient({
      baseUrl: 'https://exulanica.test', token: 'token', fetch, worldId: STARTER_WORLD,
    });
    const preview = await previewComposition(client, version, photo);

    expect(sent).toHaveLength(1);
    expect(sent[0]!.url.pathname)
      .toBe(`/world/versions/${version.versionId}/compositions/photo-point-maps/preview`);
    expect(sent[0]!.url.searchParams.get('world_id')).toBe(STARTER_WORLD);
    expect(sent[0]!.body).toEqual({
      ...compositionRequestBody(photo), base_state_sha256: version.stateSha256,
    });
    expect(preview.availability).toBe('ready');
    expect(preview.source.kind).toBe('photo_point_map');
    expect(preview.wouldChange.kind).toBe('add_point_map');
    expect(preview.source.identifiers).toMatchObject({
      entry_id: ENTRY_ID, attachment_id: ATTACHMENT_ID,
    });
  });

  it('applies on the estimate’s route with the entry binding, and no other kind goes there', async () => {
    const version = base();
    const { sent, fetch } = wire(() => json(201, { ...FIXTURE, world_id: STARTER_WORLD }));
    const client = new WorldObjectsClient({
      baseUrl: 'https://exulanica.test', token: 'token', fetch,
      worldId: STARTER_WORLD, savedEntry: entryBinding,
    });
    expect((await applyComposition(client, version, photo)).kind).toBe('recorded');
    expect((await applyComposition(client, version, placement)).kind).toBe('recorded');

    expect(sent.map((request) => request.url.pathname)).toEqual([
      `/world/versions/${version.versionId}/compositions/photo-point-maps/apply`,
      `/world/versions/${version.versionId}/compositions/apply`,
    ]);
    expect(sent[0]!.body).toEqual({
      ...compositionRequestBody(photo),
      base_state_sha256: version.stateSha256,
      saved_entry: {
        entry_id: ENTRY_ID,
        base_revision: 3,
        authored_state_sha256: version.stateSha256,
        authored_edit_seq: version.editSeq,
      },
    });
  });
});

describe('the preview document is the server’s, and only well-formed ones are read', () => {
  it('reads the contract’s blocked stale answer, with bytes not looked for', () => {
    const version = base();
    const preview = parseCompositionPreview({
      ...readyAnswer(version, 'object:lantern'),
      availability: 'blocked',
      blocked_reason: 'stale_base',
      blocked_detail: 'base_state_sha256 is not the stored state',
      source: { kind: 'reviewed_asset', asset_key: 'cc0.marker-cube', content_sha256: null, bytes: null },
    });
    expect(preview.blockedReason).toBe('stale_base');
    expect(preview.blockedDetail).toContain('stored state');
    expect(preview.source.bytes).toBeNull();
    expect(preview.source.identifiers).toEqual({ asset_key: 'cc0.marker-cube' });
  });

  it('refuses a ready document that also names a reason, and one with no reason at all', () => {
    const version = base();
    expect(() => parseCompositionPreview({
      ...readyAnswer(version, 'object:lantern'), blocked_reason: 'stale_base',
    })).toThrow(CompositionContractError);
    expect(() => parseCompositionPreview({
      ...readyAnswer(version, 'object:lantern'), availability: 'blocked',
    })).toThrow(CompositionContractError);
    expect(() => parseCompositionPreview({
      ...readyAnswer(version, 'object:lantern'), availability: 'maybe',
    })).toThrow(CompositionContractError);
  });

  it('says the rest of the world stays as it is only when the server listed it as preserved', () => {
    const ready = readyAnswer(base(), 'object:lantern');
    const change = ready['would_change'] as Record<string, unknown>;
    expect(describeReady(parseCompositionPreview(ready), 'Marker cube'))
      .toContain('Everything else in this world stays as it is.');
    expect(describeReady(
      parseCompositionPreview({ ...ready, would_change: { ...change, preserves: ['prior_edits'] } }),
      'Marker cube',
    )).not.toContain('Everything else');
  });

  it('keeps a code it does not know rather than dropping it', () => {
    const preview = parseCompositionPreview({
      ...readyAnswer(base(), 'object:lantern'),
      availability: 'blocked',
      blocked_reason: 'a_code_from_later',
    });
    expect(preview.blockedReason).toBe('a_code_from_later');
  });
});

describe('words for failures that carry no verdict', () => {
  it('says each transport failure plainly and keeps the code for the details', () => {
    const cases: readonly [unknown, string][] = [
      [new ApiError(404, 'unknown_reference', 'no such world resource'), 'not available to this account'],
      [new ApiError(401, 'unauthenticated', 'sign in'), 'not allowed to change this world'],
      [new ApiError(422, 'http_422', 'Unprocessable Entity'), 'fault in this app'],
      [new ApiError(409, 'stale_saved_world_entry', 'moved'), 'changed elsewhere'],
      [new WorldObjectsContractError('saved_entry_conflict', 'moved'), 'changed elsewhere'],
      [new ApiError(409, 'composition_blocked', 'free text from an older server'), 'does not recognise'],
      // A durable-write refusal the contract names beside composition_blocked.
      [new ApiError(409, 'invalid_object_state', 'no atomic authored-input adapter'), 'refused this change'],
    ];
    for (const [error, words] of cases) {
      const said = explainCompositionFailure(error, 'apply');
      expect(`${said.happened} ${said.next}`, String(error)).toContain(words);
      expect(`${said.happened} ${said.next}`, String(error)).not.toMatch(/[a-z]_[a-z]/);
      expect(said.outcome).toBe('unchanged');
    }
    const lost = explainCompositionFailure(new TypeError('Failed to fetch'), 'apply');
    expect(lost.outcome).toBe('unknown');
    expect(lost.happened).toContain('not known');
    expect(explainCompositionFailure(new ApiError(502, 'http_502', 'Bad Gateway'), 'apply').outcome)
      .toBe('unknown');
  });

  it('has a sentence pair for every code the contract lists', () => {
    for (const code of COMPOSITION_BLOCKED_REASONS) {
      const words = COMPOSITION_BLOCKED_WORDS[code];
      expect(words.happened.length, code).toBeGreaterThan(0);
      expect(words.next.length, code).toBeGreaterThan(0);
      expect(`${words.happened} ${words.next}`, code).not.toMatch(/[a-z]_[a-z]/);
    }
  });
});

/**
 * The codes this client knows, against the codes the server declares.
 *
 * Read out of `exulanica/world/composition_preview.py` at run time rather than copied here: a
 * copied list is a second source of truth, and it would agree with itself while the server moved.
 * A code added there with no sentence here would otherwise reach a person as the generic refusal.
 */
describe('the blocked codes are the server’s own list', () => {
  const declaredByTheServer = (): readonly string[] => {
    const source = readFileSync(`${process.cwd()}/../exulanica/world/composition_preview.py`, 'utf8');
    const opens = source.indexOf('BLOCKED_REASONS: frozenset[str] = frozenset(');
    expect(opens, 'BLOCKED_REASONS is not declared where this test reads it').toBeGreaterThan(-1);
    const closes = source.indexOf('\n)\n', opens);
    expect(closes, 'the BLOCKED_REASONS literal does not end where this test reads it')
      .toBeGreaterThan(opens);
    return [...source.slice(opens, closes).matchAll(/"([a-z_]+)"/g)].map((match) => match[1]!);
  };

  it('reads a non-empty list out of the server source', () => {
    // The parse is checked before it is compared, so an empty read cannot pass as agreement.
    expect(declaredByTheServer().length).toBeGreaterThan(0);
  });

  it('knows exactly those codes, with a sentence for each', () => {
    const declared = declaredByTheServer();
    expect([...declared].sort()).toEqual([...COMPOSITION_BLOCKED_REASONS].sort());
    for (const code of declared) {
      expect(isCompositionBlockedReason(code), code).toBe(true);
    }
  });
});
