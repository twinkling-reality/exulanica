// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, adaptSnapshot } from '@exulanica/graph-client';
import { initialFormationState } from '@exulanica/formation';
import { mountPersonalIntake, createPersonalIntakeSession } from '../src/composition/personal-intake.js';
import { sha256, HUMAN_ATTESTATION } from '../src/personal-admission-api.js';
import type {
  SavedWorldEntry,
  SavedWorldPreviousSourceAttachment,
  SavedWorldSourceAttachment,
  SourceAttachmentRequest,
  SourceDetachRequest,
  SourceRebindRequest,
} from '../src/world-entry-api.js';

const mocks = vi.hoisted(() => ({
  watch: vi.fn(), disposeMedia: vi.fn(), media: new Map<string, unknown>(),
}));
vi.mock('../src/formation.js', () => ({ listBatches: async () => [], watchBatch: (...args: unknown[]) => mocks.watch(...args) }));
vi.mock('../src/source-media-api.js', () => ({ SourceMediaClient: class {
  async load() { return { catalog: mocks.media, issues: [], dispose: mocks.disposeMedia }; }
} }));
const ids = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'];
const key = 'a'.repeat(64), subject = '33333333-3333-4333-8333-333333333333';
const json = (body: unknown) => new Response(JSON.stringify(body));
function fixture(count = 2) {
  let uploaded = false, linked = false, interrupted = false;
  let viewerAvailable = false;
  let regions = true;
  const posts: { path: string; body: any }[] = [];
  const savedRequests: any[] = [];
  const captureIds = Array.from({ length: count }, (_, i) => ids[i] ?? `00000000-0000-4000-8000-${String(i).padStart(12, '0')}`);
  const files = [new File(['fixture HEIC bytes'], 'a.heic'), new File(['fixture JPEG bytes'], 'b.jpg'),
    ...Array.from({ length: count - 2 }, (_, i) => new File([`history ${i}`], `history-${i}.jpg`))];
  const snapshot = () => adaptSnapshot({ state_version: 1, entities: [], occurrences: [], proposals: [],
    scene_groups: [], reconstruction_scenes: [], never_same: [], deleted_entity_ids: [],
    review_sources: uploaded ? captureIds.map((id, i) => ({ kind: 'admitted_capture' as const, capture_id: id,
      evidence_span_id: `span-${i}`, captured_at: null, media_type: 'image/jpeg',
      state: viewerAvailable ? 'available' as const : 'unavailable_asset' as const,
      reason: viewerAvailable ? null : 'Fixture viewer unavailable',
      evidence_path: viewerAvailable ? `/evidence/span-${i}/masked` : null,
      content_sha256: viewerAvailable ? 'd'.repeat(64) : null,
      person_review_state: 'screened' as const, person_regions: [],
    })) : [],
  });
  const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const path = new URL(String(input)).pathname;
    if (path === '/personal-admission' && init.method === 'GET') return json({
      sources: uploaded ? await Promise.all(files.map(async (f, i) => ({ capture_id: captureIds[i], sha256: await sha256(await f.arrayBuffer()), bytes: f.size, media_type: 'image/jpeg', authority: null }))) : [],
      requests: savedRequests,
    });
    if (path === '/intake') {
      uploaded = true;
      return json({ batch_id: 'upload', queued_job_id: 'upload-job', refused: [{ filename: 'bad.jpg', reason: 'not_an_image', detail: 'Fixture rejection' }],
        accepted: await Promise.all(files.slice(0, 2).map(async (f, i) => ({ capture_id: captureIds[i], blob_sha256: await sha256(await f.arrayBuffer()), filename: f.name, status: 'ingested' }))) });
    }
    if (init.method === 'POST') {
      const body = JSON.parse(String(init.body)); posts.push({ path, body });
      if (path === '/personal-admission') {
        if (!interrupted) { interrupted = true; throw new Error('Admission response interrupted'); }
        const result = { request_id: body.request_id, operation: 'admission', batch_id: 'admitted', queued_job_id: 'job', receipts: body.members.map((m: any) => ({
          capture_id: m.capture_id, authorization_id: 'auth', screening_id: 'screen', eligibility_state: body.operation === 'detect' ? 'detection-only' : 'eligible',
        })) }; savedRequests.push(result); return json(result);
      }
      if (path === '/identity/subjects/link') { linked = true; return json({ subject_id: subject }); }
      return json({});
    }
    if (path.startsWith('/person-regions/')) return json({ capture_id: path.split('/').at(-1), review_state: 'screened',
      regions: regions ? [{ region_key: key, action: linked ? 'confirmed' : 'detected', shape: 'box', silhouette: { kind: 'polygon', points: [[0, 0], [100, 0], [0, 100]] },
        part: 'arm', detector_id: 'scripted-detector', confidence: 'low', confirmed_by: null,
        subject_id: linked ? subject : null, state: 'unknown', masked: true, name_permitted: false }] : [] });
    throw new Error(`Unexpected fixture request: ${path}`);
  });
  const make = (
    session = createPersonalIntakeSession(),
    overrides: Partial<Parameters<typeof mountPersonalIntake>[0]> = {},
  ) => mountPersonalIntake({
    credentials: { baseUrl: 'https://fixture.test', token: 'fixture-token', fetch }, session,
    snapshot: snapshot(), media: undefined, reloadSnapshot: async () => snapshot(),
    refreshWorld: vi.fn(async () => undefined), storage: window.sessionStorage,
    ...overrides,
  });
  return {
    files, posts, make, captureIds, savedRequests,
    setUploaded: () => { uploaded = true; },
    seedReviewed: (ineligible: readonly string[] = []) => {
      uploaded = true;
      viewerAvailable = true;
      savedRequests.push({
        request_id: 'reviewed-request', operation: 'review', batch_id: 'reviewed',
        queued_job_id: 'reviewed-job', receipts: captureIds.map((capture_id) => ({
          capture_id, authorization_id: 'current-auth', screening_id: 'current-screen',
          eligibility_state: ineligible.includes(capture_id) ? 'detection-only' : 'eligible',
        })),
      });
    },
    noRegions: () => { regions = false; },
    recordNewReview: (captureId: string) => {
      savedRequests.push({
        request_id: `review-again-${captureId}`, operation: 'review', batch_id: 'reviewed-again',
        queued_job_id: 'reviewed-again-job', receipts: [{
          capture_id: captureId, authorization_id: 'new-auth', screening_id: 'new-screen',
          eligibility_state: 'eligible',
        }],
      });
    },
  };
}
/** Text a person reads without opening a Details disclosure. */
function visibleText(node: Element): string {
  const copy = node.cloneNode(true) as Element;
  copy.querySelectorAll('details').forEach((details) => details.remove());
  return copy.textContent ?? '';
}
const uuidPattern = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/;
function button(root: HTMLElement, text: string) { return [...root.querySelectorAll('button')].find(b => b.textContent === text)!; }
function input(root: HTMLElement, label: string) { return root.querySelector(`[aria-label="${label}"]`) as HTMLInputElement; }
function attachButton(root: HTMLElement) {
  return root.querySelector<HTMLButtonElement>('.photo-attach-action')!;
}
const settle = async (root: HTMLElement) => { await vi.waitFor(() => expect(root.querySelector('fieldset')!.disabled).toBe(false)); };
afterEach(() => {
  document.body.replaceChildren();
  window.sessionStorage.clear();
  mocks.media.clear();
  vi.clearAllMocks();
});

const ownedEntry = (
  sourceAttachments: readonly SavedWorldSourceAttachment[] = [],
  revision = 1,
): SavedWorldEntry => ({
  entryId: '99999999-9999-4999-8999-999999999999',
  worldId: 'world:authored:starter', title: 'My world', sourceKind: 'authored',
  sourceSnapshotId: '88888888-8888-4888-8888-888888888888',
  sourceSnapshotSha256: 'c'.repeat(64),
  authoredScene: {
    schemaVersion: 1, kind: 'authored-starter', region: {
      regionId: 'region:starter', origin: 'authored',
      module: { key: 'region.authored-ground', version: 1 },
      ground: { kind: 'flat', halfWidthMm: 12000, halfDepthMm: 12000, elevationMm: 0 },
      spawn: { xMm: 0, yMm: 0, zMm: 4000, yawMicroradians: 0 },
    },
  },
  authoredVersionId: '77777777-7777-4777-8777-777777777777',
  authoredStateSha256: 'a'.repeat(64), authoredEditSeq: 0,
  currentAuthoredStateSha256: 'a'.repeat(64), currentAuthoredEditSeq: 0,
  styleVersionId: '66666666-6666-4666-8666-666666666666', revision,
  availability: 'available', unavailableReason: null, sourceAttachments,
  createdAt: '2026-09-20T12:00:00Z', updatedAt: '2026-09-20T12:00:00Z',
});

const reference = (captureId: string, span: string): SavedWorldSourceAttachment => ({
  attachmentId: '55555555-5555-4555-8555-555555555555',
  operationId: '44444444-4444-4444-8444-444444444444',
  captureId, evidenceSpanId: span, sourceSha256: 'f'.repeat(64),
  authorizationId: 'current-auth', screeningId: 'current-screen', role: 'reference',
  attachedEntryRevision: 2, attachedBy: '11111111-1111-4111-8111-111111111111',
  attachedAt: '2026-09-20T12:01:00Z', availability: 'available',
  unavailableReason: null, viewerSha256: 'e'.repeat(64), evidencePath: `/evidence/${span}/masked`,
});

const removedReference = (
  captureId: string, span: string,
): SavedWorldPreviousSourceAttachment => ({
  attachmentId: '55555555-5555-4555-8555-555555555555',
  operationId: '44444444-4444-4444-8444-444444444444',
  captureId, evidenceSpanId: span, sourceSha256: 'f'.repeat(64),
  authorizationId: 'current-auth', screeningId: 'current-screen',
  attachedEntryRevision: 2, attachedAt: '2026-09-20T12:01:00Z',
  detachOperationId: '66666666-6666-4666-8666-666666666666', detachedEntryRevision: 3,
  detachedAt: '2026-09-21T12:00:00Z', availability: 'available', unavailableReason: null,
});

function viewer(span: string) {
  mocks.media.set(span, {
    evidenceRef: span, title: 'Reviewed source', capturedLabel: 'Capture date unavailable',
    url: `blob:${span}`, available: true, accent: '#777777', alt: 'Authorized reviewed source',
  });
}

describe('mounted personal intake with scripted transport (not real-photo acceptance)', () => {
  it('removes a reference only after a plain confirmation and keeps it listed as previously in this world', async () => {
    const f = fixture();
    f.seedReviewed();
    viewer('span-0');
    let activeEntry = ownedEntry([reference(f.captureIds[0]!, 'span-0')], 2);
    const detachSources = vi.fn(async (request: SourceDetachRequest) => {
      activeEntry = {
        ...activeEntry, revision: request.baseRevision + 1, sourceAttachments: [],
        previousSourceAttachments: [removedReference(f.captureIds[0]!, 'span-0')],
      };
      return activeEntry;
    });
    const rebindSources = vi.fn();
    const mounted = f.make(createPersonalIntakeSession(), {
      getEntry: () => activeEntry, entryClient: { detachSources, rebindSources },
    });
    document.body.append(mounted.root);
    await mounted.begin();
    const card = mounted.root.querySelector('.attached-reference')!;
    expect(visibleText(card)).toContain('In this world');
    // Reference cards host no composition control.
    expect(mounted.root.querySelector('.composition-preview-control')).toBeNull();
    expect(button(mounted.root, 'Preview composition')).toBeUndefined();

    button(mounted.root, 'Remove from this world').click();
    expect(mounted.root.textContent).toContain(
      'Remove this photo from this world? The photo stays in your library.',
    );
    expect(detachSources).not.toHaveBeenCalled();
    button(mounted.root, 'Keep in this world').click();
    expect(mounted.root.querySelector('.photo-reference-confirm')).toBeNull();
    expect(detachSources).not.toHaveBeenCalled();

    button(mounted.root, 'Remove from this world').click();
    button(mounted.root, 'Remove').click();
    await settle(mounted.root);
    expect(detachSources).toHaveBeenCalledOnce();
    expect(detachSources.mock.calls[0]![0]).toMatchObject({
      kind: 'detach', entryId: ownedEntry().entryId, baseRevision: 2,
      authoredVersionId: ownedEntry().authoredVersionId,
      authoredStateSha256: ownedEntry().authoredStateSha256, authoredEditSeq: 0,
      styleVersionId: ownedEntry().styleVersionId,
      attachmentIds: ['55555555-5555-4555-8555-555555555555'],
    });
    expect(mounted.root.querySelector('.photo-reference-count')?.textContent).toBe('0 photos');
    expect(visibleText(mounted.root.querySelector('.photo-reference-notice')!)).toBe(
      'Removed from this world. The photo is still in your library.',
    );
    const previous = mounted.root.querySelector('.photo-previous')!;
    expect(previous.hasAttribute('hidden')).toBe(false);
    expect(visibleText(previous)).toContain('Previously in this world');
    expect(visibleText(previous)).toContain('Photograph 1');
    expect(button(mounted.root, 'Add back').disabled).toBe(false);
    expect(rebindSources).not.toHaveBeenCalled();
    mounted.dispose();
  });

  it('sends Add back through a new human review and never adds a photo back on its own', async () => {
    const f = fixture();
    f.seedReviewed();
    viewer('span-0');
    let activeEntry = ownedEntry([], 3);
    activeEntry = {
      ...activeEntry, previousSourceAttachments: [removedReference(f.captureIds[0]!, 'span-0')],
    };
    const rebindSources = vi.fn(async (request: SourceRebindRequest) => {
      activeEntry = {
        ...activeEntry, revision: request.baseRevision + 1,
        sourceAttachments: [{
          ...reference(f.captureIds[0]!, 'span-0'),
          attachmentId: '77777777-7777-4777-8777-777777777777',
          authorizationId: 'new-auth', screeningId: 'new-screen',
        }],
        previousSourceAttachments: [],
      };
      return activeEntry;
    });
    const mounted = f.make(createPersonalIntakeSession(), {
      getEntry: () => activeEntry, entryClient: { detachSources: vi.fn(), rebindSources },
    });
    document.body.append(mounted.root);
    await mounted.begin();
    expect(visibleText(mounted.root.querySelector('.photo-previous')!)).toContain(
      'Adding it back starts with a new review of the photo.',
    );

    // Only the review this membership already pinned exists, so Add back opens the review.
    button(mounted.root, 'Add back').click();
    expect(rebindSources).not.toHaveBeenCalled();
    expect(mounted.root.querySelector<HTMLDetailsElement>('.photo-review-workflow')!.open)
      .toBe(true);
    expect(input(mounted.root, 'Include photograph 1 in this admission').checked).toBe(true);
    expect(input(mounted.root, 'Include photograph 2 in this admission').checked).toBe(false);
    expect(input(mounted.root, 'Photograph to review').value).toBe(f.captureIds[0]);
    expect(visibleText(mounted.root.querySelector('.photo-reference-notice')!))
      .toContain('needs a new review before it can be added back');

    // Recording the new review adds nothing back by itself.
    f.recordNewReview(f.captureIds[0]!);
    button(mounted.root, 'Reload sources and proposals').click();
    await settle(mounted.root);
    expect(rebindSources).not.toHaveBeenCalled();
    expect(mounted.root.querySelector('.photo-reference-count')?.textContent).toBe('0 photos');
    expect(visibleText(mounted.root.querySelector('.photo-previous')!)).toContain(
      'A new review is recorded. Choose Add back to use this photo in this world again.',
    );

    button(mounted.root, 'Add back').click();
    await settle(mounted.root);
    expect(rebindSources).toHaveBeenCalledOnce();
    expect(rebindSources.mock.calls[0]![0]).toMatchObject({
      kind: 'rebind', entryId: ownedEntry().entryId, baseRevision: 3,
      sources: [{ captureId: f.captureIds[0], evidenceSpanId: 'span-0' }],
    });
    expect(mounted.root.querySelector('.photo-reference-count')?.textContent).toBe('1 photo');
    expect(mounted.root.querySelector('.photo-previous')!.hasAttribute('hidden')).toBe(true);
    expect(visibleText(mounted.root.querySelector('.photo-reference-notice')!)).toBe(
      'Added back to this world with its new review.',
    );
    mounted.dispose();
  });

  it('explains refusals in words, keeps the code in Details and retries an unanswered change exactly', async () => {
    const f = fixture();
    f.seedReviewed();
    f.recordNewReview(f.captureIds[0]!);
    const activeEntry = {
      ...ownedEntry([reference(f.captureIds[1]!, 'span-1')], 3),
      previousSourceAttachments: [removedReference(f.captureIds[0]!, 'span-0')],
    };
    const refreshEntry = vi.fn(async () => activeEntry);
    const rebindSources = vi.fn(async (_request: SourceRebindRequest): Promise<SavedWorldEntry> => {
      throw new ApiError(422, 'review_required', 'adding a photograph back needs a new human review');
    });
    let detachCalls = 0;
    const detachSources = vi.fn(async (_request: SourceDetachRequest): Promise<SavedWorldEntry> => {
      detachCalls += 1;
      if (detachCalls === 1) throw new TypeError('Failed to fetch');
      if (detachCalls === 2) throw new ApiError(409, 'stale_saved_world_entry', 'changed elsewhere');
      return activeEntry;
    });
    const mounted = f.make(createPersonalIntakeSession(), {
      getEntry: () => activeEntry, refreshEntry, entryClient: { detachSources, rebindSources },
    });
    document.body.append(mounted.root);
    await mounted.begin();
    const noticeArea = () => mounted.root.querySelector('.photo-reference-notice')!;

    button(mounted.root, 'Add back').click();
    await settle(mounted.root);
    expect(rebindSources).toHaveBeenCalledOnce();
    expect(visibleText(noticeArea())).toContain(
      'This photo needs a new review before it can be added back. Nothing was added.',
    );
    expect(visibleText(noticeArea())).not.toContain('review_required');
    expect(noticeArea().querySelector('details')?.textContent).toContain('review_required');
    expect(button(mounted.root, 'Retry the interrupted photo change').hidden).toBe(true);

    button(mounted.root, 'Remove from this world').click();
    button(mounted.root, 'Remove').click();
    await settle(mounted.root);
    expect(visibleText(noticeArea())).toContain('Retry sends exactly the same request');
    expect(button(mounted.root, 'Retry the interrupted photo change').hidden).toBe(false);
    const first = detachSources.mock.calls[0]![0];

    button(mounted.root, 'Retry the interrupted photo change').click();
    await settle(mounted.root);
    expect(detachSources.mock.calls[1]![0]).toEqual(first);
    expect(refreshEntry).toHaveBeenCalledWith(activeEntry.entryId);
    expect(visibleText(noticeArea())).toContain(
      'This world changed somewhere else before your change was saved, so nothing changed.',
    );
    expect(noticeArea().querySelector('details')?.textContent).toContain('stale_saved_world_entry');
    expect(button(mounted.root, 'Retry the interrupted photo change').hidden).toBe(true);
    expect(visibleText(mounted.root.querySelector('.photo-collection')!)).not.toMatch(uuidPattern);
    mounted.dispose();
  });

  it('adds one reviewed photo directly without touching the admission selection', async () => {
    const f = fixture();
    f.seedReviewed();
    viewer('span-1');
    let activeEntry = ownedEntry([], 1);
    const attachSources = vi.fn(async (request: SourceAttachmentRequest) => {
      activeEntry = ownedEntry([reference(request.sources[0]!.captureId, 'span-1')], 2);
      return activeEntry;
    });
    const mounted = f.make(createPersonalIntakeSession(), {
      getEntry: () => activeEntry, attachSources,
    });
    document.body.append(mounted.root);
    await mounted.begin();
    const ready = mounted.root.querySelector('.photo-ready')!;
    expect(ready.hasAttribute('hidden')).toBe(false);
    expect(ready.querySelectorAll('.ready-reference')).toHaveLength(2);
    expect(input(mounted.root, 'Include photograph 2 in this admission').checked).toBe(false);

    const second = [...ready.querySelectorAll<HTMLElement>('.ready-reference')]
      .find((card) => card.textContent?.includes('Photograph 2'))!;
    second.querySelector<HTMLButtonElement>('button')!.click();
    await settle(mounted.root);
    expect(attachSources).toHaveBeenCalledOnce();
    expect(attachSources.mock.calls[0]![0]).toMatchObject({
      entryId: ownedEntry().entryId, baseRevision: 1,
      sources: [{ captureId: f.captureIds[1], evidenceSpanId: 'span-1' }],
    });
    expect(input(mounted.root, 'Include photograph 2 in this admission').checked).toBe(false);
    expect(mounted.root.querySelectorAll('.ready-reference')).toHaveLength(1);
    expect(mounted.root.querySelector('.photo-reference-count')?.textContent).toBe('1 photo');
    mounted.dispose();
  });

  it('describes recorded reviews in words and keeps receipt identities inside Details', async () => {
    const f = fixture();
    f.seedReviewed([f.captureIds[1]!]);
    f.savedRequests.push({
      request_id: 'stale-request', operation: 'admission', batch_id: 'stale-batch',
      queued_job_id: 'stale-job', receipts: [{
        capture_id: f.captureIds[1], authorization_id: 'stale-auth', screening_id: 'stale-screen',
        eligibility_state: 'blocked-or-stale',
      }],
    });
    const mounted = f.make();
    document.body.append(mounted.root);
    await mounted.begin();
    const receipts = mounted.root.querySelector('[aria-label="Personal admission receipts"]')!;
    expect(visibleText(receipts)).toContain('Photograph 1: reviewed and ready to keep with a world.');
    expect(visibleText(receipts)).toContain(
      'Photograph 2: not ready; its review is missing or out of date.',
    );
    expect(visibleText(receipts)).not.toContain('blocked-or-stale');
    expect(visibleText(receipts)).not.toMatch(uuidPattern);
    expect(receipts.querySelector('details')?.textContent).toContain('stale-screen');
    mounted.dispose();
  });

  it('attaches only an explicitly selected eligible reference and retains the exact interrupted request', async () => {
    const f = fixture();
    f.seedReviewed();
    let activeEntry = ownedEntry();
    const failedAttach = vi.fn(async (_request: SourceAttachmentRequest) => {
      throw new Error('Attachment response interrupted');
    });
    let mounted = f.make(createPersonalIntakeSession(), {
      getEntry: () => activeEntry,
      attachSources: failedAttach,
    });
    document.body.append(mounted.root);
    await mounted.begin();
    expect(mounted.root.querySelector('.photo-collection')).not.toBeNull();
    expect(mounted.root.textContent).toContain('No reference photos yet');
    expect(attachButton(mounted.root).disabled).toBe(true);
    const selected = input(mounted.root, 'Include photograph 1 in this admission');
    selected.checked = true;
    selected.dispatchEvent(new Event('change'));
    expect(attachButton(mounted.root).textContent).toBe('Attach 1 selected photo');
    attachButton(mounted.root).click();
    await settle(mounted.root);
    expect(failedAttach).toHaveBeenCalledOnce();
    const retained = failedAttach.mock.calls[0]![0];
    expect(retained).toMatchObject({
      entryId: ownedEntry().entryId,
      baseRevision: 1,
      authoredVersionId: ownedEntry().authoredVersionId,
      authoredStateSha256: ownedEntry().authoredStateSha256,
      authoredEditSeq: 0,
      styleVersionId: ownedEntry().styleVersionId,
      sources: [{ captureId: f.captureIds[0], evidenceSpanId: 'span-0' }],
    });
    expect(retained.operationId).toMatch(/^[0-9a-f-]{36}$/);
    expect(button(mounted.root, 'Retry exact interrupted attachment').hidden).toBe(false);

    mounted.dispose();
    mounted.root.remove();
    const otherEntry = {
      ...ownedEntry(), entryId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    };
    mounted = f.make(createPersonalIntakeSession(), { getEntry: () => otherEntry });
    document.body.append(mounted.root);
    await mounted.begin();
    expect(button(mounted.root, 'Retry exact interrupted attachment').hidden).toBe(true);
    mounted.dispose();
    mounted.root.remove();

    const attachment: SavedWorldSourceAttachment = {
      attachmentId: '55555555-5555-4555-8555-555555555555',
      operationId: retained.operationId,
      captureId: f.captureIds[0]!, evidenceSpanId: 'span-0',
      sourceSha256: 'f'.repeat(64),
      authorizationId: '44444444-4444-4444-8444-444444444444',
      screeningId: '33333333-3333-4333-8333-333333333333',
      role: 'reference', attachedEntryRevision: 2,
      attachedBy: '22222222-2222-4222-8222-222222222222',
      attachedAt: '2026-09-20T12:01:00Z', availability: 'available',
      unavailableReason: null, viewerSha256: 'e'.repeat(64),
      evidencePath: '/evidence/span-0/masked',
    };
    const retriedAttach = vi.fn(async () => {
      activeEntry = ownedEntry([attachment], 2);
      return activeEntry;
    });
    mocks.media.set('span-0', {
      evidenceRef: 'span-0', title: 'Reviewed source', capturedLabel: 'Capture date unavailable',
      url: 'blob:authorized-viewer', available: true, accent: '#777777',
      alt: 'Authorized reviewed source',
    });
    mounted = f.make(createPersonalIntakeSession(), {
      getEntry: () => activeEntry,
      attachSources: retriedAttach,
    });
    document.body.append(mounted.root);
    await mounted.begin();
    button(mounted.root, 'Retry exact interrupted attachment').click();
    await settle(mounted.root);
    expect(retriedAttach).toHaveBeenCalledWith(retained);
    expect(mounted.root.textContent).toContain('attached as project references');
    expect(mounted.root.textContent).toContain('Reference photograph 1');
    expect(mounted.root.querySelector('.photo-reference-count')?.textContent).toBe('1 photo');
    expect(attachButton(mounted.root).textContent).toBe('Selected photos already attached');
    expect(attachButton(mounted.root).disabled).toBe(true);
    expect(mounted.root.textContent).toContain(`original SHA-256 ${attachment.sourceSha256}`);
    expect(mounted.root.querySelector<HTMLImageElement>(
      '[aria-label="Attached reference photographs"] img',
    )?.src).toBe('blob:authorized-viewer');
    mounted.dispose();
  });

  it('reads the live same-page entry cursor when the explicit attachment is submitted', async () => {
    const f = fixture();
    f.seedReviewed();
    let activeEntry = ownedEntry();
    const attachSources = vi.fn(async (_request: SourceAttachmentRequest) => ({
      ...activeEntry, revision: activeEntry.revision + 1,
    }));
    const mounted = f.make(createPersonalIntakeSession(), {
      getEntry: () => activeEntry,
      attachSources,
    });
    document.body.append(mounted.root);
    await mounted.begin();
    const selected = input(mounted.root, 'Include photograph 1 in this admission');
    selected.checked = true;
    selected.dispatchEvent(new Event('change'));
    activeEntry = {
      ...activeEntry,
      title: 'Renamed in this page',
      revision: 2,
      authoredStateSha256: 'b'.repeat(64),
      authoredEditSeq: 1,
      currentAuthoredStateSha256: 'b'.repeat(64),
      currentAuthoredEditSeq: 1,
    };
    attachButton(mounted.root).click();
    await settle(mounted.root);
    expect(attachSources).toHaveBeenCalledWith(expect.objectContaining({
      baseRevision: 2,
      authoredStateSha256: 'b'.repeat(64),
      authoredEditSeq: 1,
    }));
    mounted.dispose();
  });

  it('refuses a mixed selection instead of silently dropping unattachable photographs', async () => {
    const f = fixture();
    f.seedReviewed([f.captureIds[1]!]);
    const attachSources = vi.fn(async () => ownedEntry());
    const activeEntry = ownedEntry([], 2);
    const mounted = f.make(createPersonalIntakeSession(), {
      getEntry: () => activeEntry, attachSources,
    });
    document.body.append(mounted.root);
    await mounted.begin();
    for (const index of [1, 2]) {
      const selected = input(mounted.root, `Include photograph ${index} in this admission`);
      selected.checked = true;
      selected.dispatchEvent(new Event('change'));
    }
    expect(mounted.root.textContent).toContain('1 needs completed review or current viewer access');
    attachButton(mounted.root).click();
    await settle(mounted.root);
    expect(attachSources).not.toHaveBeenCalled();
    expect(mounted.root.textContent).toContain('nothing was attached');
    mounted.dispose();
  });

  it('marks an already attached selection as part of this world and offers no duplicate action', async () => {
    const f = fixture();
    f.seedReviewed();
    const alreadyAttached: SavedWorldSourceAttachment = {
      attachmentId: '55555555-5555-4555-8555-555555555555',
      operationId: '44444444-4444-4444-8444-444444444444',
      captureId: f.captureIds[1]!, evidenceSpanId: 'span-1', sourceSha256: 'f'.repeat(64),
      authorizationId: '33333333-3333-4333-8333-333333333333',
      screeningId: '22222222-2222-4222-8222-222222222222', role: 'reference',
      attachedEntryRevision: 2, attachedBy: '11111111-1111-4111-8111-111111111111',
      attachedAt: '2026-09-20T12:01:00Z', availability: 'available',
      unavailableReason: null, viewerSha256: 'e'.repeat(64),
      evidencePath: '/evidence/span-1/masked',
    };
    const attachSources = vi.fn(async () => ownedEntry());
    const mounted = f.make(createPersonalIntakeSession(), {
      getEntry: () => ownedEntry([alreadyAttached], 2), attachSources,
    });
    document.body.append(mounted.root);
    await mounted.begin();
    const selected = input(mounted.root, 'Include photograph 2 in this admission');
    selected.checked = true;
    selected.dispatchEvent(new Event('change'));
    expect(mounted.root.textContent).toContain('1 already in this world');
    expect(attachButton(mounted.root).textContent).toBe('Selected photos already attached');
    expect(attachButton(mounted.root).disabled).toBe(true);
    expect(attachSources).not.toHaveBeenCalled();
    mounted.dispose();
  });

  it('refreshes a stale entry cursor and makes the explicit attachment action available again', async () => {
    const f = fixture();
    f.seedReviewed();
    let activeEntry = ownedEntry();
    const refreshEntry = vi.fn(async () => {
      activeEntry = ownedEntry([], 2);
      return activeEntry;
    });
    const mounted = f.make(createPersonalIntakeSession(), {
      getEntry: () => activeEntry,
      attachSources: vi.fn(async () => {
        throw new ApiError(409, 'stale_saved_world_entry', 'changed elsewhere');
      }),
      refreshEntry,
    });
    document.body.append(mounted.root);
    await mounted.begin();
    const selected = input(mounted.root, 'Include photograph 1 in this admission');
    selected.checked = true;
    selected.dispatchEvent(new Event('change'));
    attachButton(mounted.root).click();
    await settle(mounted.root);
    expect(refreshEntry).toHaveBeenCalledWith(ownedEntry().entryId);
    expect(mounted.root.textContent).toContain('world changed before the references were attached');
    expect(button(mounted.root, 'Retry exact interrupted attachment').hidden).toBe(true);
    expect(attachButton(mounted.root).disabled).toBe(false);
    mounted.dispose();
  });

  it('reopens an unavailable reference without blocking the saved world workflow', async () => {
    const f = fixture();
    f.seedReviewed();
    const unavailable: SavedWorldSourceAttachment = {
      attachmentId: '55555555-5555-4555-8555-555555555555',
      operationId: '44444444-4444-4444-8444-444444444444',
      captureId: f.captureIds[0]!, evidenceSpanId: 'span-0', sourceSha256: 'f'.repeat(64),
      authorizationId: '33333333-3333-4333-8333-333333333333',
      screeningId: '22222222-2222-4222-8222-222222222222', role: 'reference',
      attachedEntryRevision: 2, attachedBy: '11111111-1111-4111-8111-111111111111',
      attachedAt: '2026-09-20T12:01:00Z', availability: 'unavailable',
      unavailableReason: 'authorization_expired', viewerSha256: null, evidencePath: null,
    };
    let activeEntry = ownedEntry([{ ...unavailable,
      availability: 'available', unavailableReason: null,
      viewerSha256: 'e'.repeat(64), evidencePath: '/evidence/span-0/masked',
    }], 2);
    const refreshEntry = vi.fn(async () => {
      activeEntry = ownedEntry([unavailable], 2);
      return activeEntry;
    });
    const mounted = f.make(createPersonalIntakeSession(), {
      getEntry: () => activeEntry, refreshEntry,
    });
    document.body.append(mounted.root);
    await mounted.begin();
    expect(mounted.root.textContent).toContain('Reference photograph 1');
    expect(mounted.root.textContent).toContain(
      'In this world, but the permission to use it has ended',
    );
    expect(mounted.root.querySelector('[aria-label="Attached reference photographs"] img')).toBeNull();
    expect(mounted.root.querySelector('fieldset')?.disabled).toBe(false);
    expect(refreshEntry).toHaveBeenCalled();
    mounted.dispose();
  });

  it('shows proposals and a rejection, restores an interrupted exact request, links across photos and records explicit review', async () => {
    mocks.watch.mockImplementation(() => vi.fn());
    const f = fixture();
    let mounted = f.make(); document.body.append(mounted.root); await mounted.begin();
    const uploadInput = input(mounted.root, 'Original HEIC or JPEG photographs');
    Object.defineProperty(uploadInput, 'files', { value: f.files });
    button(mounted.root, 'Upload originals').click(); await settle(mounted.root);
    expect(mounted.root.textContent).toContain('Fixture rejection');
    expect(mounted.root.textContent).toContain('A proposal, not a decision');
    input(mounted.root, 'Purpose of this use').value = 'Fixture place';
    input(mounted.root, 'Your account authority basis').value = 'Fixture operator permission';
    input(mounted.root, 'Authority valid until').value = '2099-01-01T12:00';
    button(mounted.root, 'Authorize personal admission and request detection').click(); await settle(mounted.root);
    expect(mounted.root.textContent).toContain('Admission response interrupted');
    const pending = f.posts[0]!.body;
    mounted.dispose(); mounted.root.remove();
    mounted = f.make(); document.body.append(mounted.root); await mounted.begin();
    expect(button(mounted.root, 'Retry exact interrupted admission').hidden).toBe(false);
    button(mounted.root, 'Retry exact interrupted admission').click(); await settle(mounted.root);
    expect(f.posts[1]!.body).toEqual(pending);
    expect(f.posts[1]!.body.attestation).toBeUndefined();
    const selectRegion = () => {
      const select = input(mounted.root, 'Select region for same-person linking'); select.checked = true; select.dispatchEvent(new Event('change'));
    };
    selectRegion();
    const source = input(mounted.root, 'Photograph to review'); source.value = ids[1]!; source.dispatchEvent(new Event('change'));
    selectRegion();
    button(mounted.root, 'Link selected regions as one person').click(); await settle(mounted.root);
    expect(f.posts.filter(p => p.path === '/identity/subjects/link')).toEqual([{ path: '/identity/subjects/link', body: {
      request_id: expect.any(String), regions: ids.map(capture_id => ({ capture_id, region_key: key })),
    } }]);
    expect(f.posts.some(p => p.path === '/person-subjects')).toBe(false);
    input(mounted.root, 'Purpose of this use').value = 'Fixture place';
    input(mounted.root, 'Your account authority basis').value = 'Fixture operator permission';
    input(mounted.root, 'Authority valid until').value = '2099-01-01T12:00';
    input(mounted.root, 'Reviewer’s actual name').value = 'Scripted fixture, not a human';
    Object.defineProperty(input(mounted.root, 'Reselect exact originals for local review'), 'files', { value: f.files });
    input(mounted.root, 'Reselect exact originals for local review').dispatchEvent(new Event('change')); await settle(mounted.root);
    for (const id of ids) {
      source.value = id; source.dispatchEvent(new Event('change'));
      const photo = mounted.root.querySelector('img')!;
      Object.defineProperties(photo, { naturalWidth: { value: 100 }, naturalHeight: { value: 100 } });
      photo.dispatchEvent(new Event('load'));
      const choice = input(mounted.root, 'Human review of this photograph'); choice.value = 'confirmed-regions'; choice.dispatchEvent(new Event('change'));
    }
    const attest = input(mounted.root, HUMAN_ATTESTATION); expect(attest.checked).toBe(false); attest.checked = true;
    button(mounted.root, 'Record human review').click(); await settle(mounted.root);
    const review = f.posts.at(-1)!.body;
    expect(review.operation).toBe('review'); expect(review.attestation).toBe(HUMAN_ATTESTATION);
    expect(review.members.every((m: any) => m.review === 'confirmed-regions')).toBe(true);
    expect(mounted.root.textContent).toContain('Photograph 1: reviewed and ready to keep with a world.');
    mounted.dispose();
    mounted.root.remove();
    window.sessionStorage.clear();
    const writes = f.posts.length;
    mounted = f.make(); document.body.append(mounted.root); await mounted.begin();
    expect(mounted.root.textContent).toContain(subject);
    expect(mounted.root.textContent).toContain(await sha256(await f.files[0]!.arrayBuffer()));
    expect(mounted.root.textContent).toContain('Photograph 1: reviewed and ready to keep with a world.');
    expect(input(mounted.root, HUMAN_ATTESTATION).checked).toBe(false);
    expect(input(mounted.root, 'Human review of this photograph').value).toBe('');
    expect(mounted.root.textContent).toContain('0 of 2 saved photographs selected');
    expect(f.posts).toHaveLength(writes);
    mounted.dispose();
  });
  it('keeps unavailable detection and zero regions separate from a no-person attestation', async () => {
    const f = fixture(); f.setUploaded(); f.noRegions();
    const mounted = f.make(); document.body.append(mounted.root); await mounted.begin();
    expect(mounted.root.textContent).toContain('does not establish a human no-person attestation');
    expect(input(mounted.root, 'Human review of this photograph').value).toBe('');
    expect(input(mounted.root, HUMAN_ATTESTATION).checked).toBe(false);
    expect(f.posts).toEqual([]);
    Object.defineProperty(input(mounted.root, 'Reselect exact originals for local review'), 'files', {
      value: [new File(['different bytes'], 'a.heic')],
    });
    input(mounted.root, 'Reselect exact originals for local review').dispatchEvent(new Event('change')); await settle(mounted.root);
    expect(mounted.root.querySelector('img')).toBeNull();
    expect(input(mounted.root, 'Human review of this photograph').disabled).toBe(true);
    mounted.dispose();
  });
  it('renders the server unavailable-detector note without inventing completed detection', async () => {
    mocks.watch.mockImplementation((_options, batch, onState) => {
      onState({ ...initialFormationState(batch), stream: 'live', note: 'Person detector unavailable: no provider configured.' });
      return vi.fn();
    });
    const f = fixture(); const mounted = f.make(); document.body.append(mounted.root); await mounted.begin();
    Object.defineProperty(input(mounted.root, 'Original HEIC or JPEG photographs'), 'files', { value: f.files });
    button(mounted.root, 'Upload originals').click(); await settle(mounted.root);
    expect(mounted.root.textContent).toContain('Person detector unavailable: no provider configured.');
    expect(input(mounted.root, HUMAN_ATTESTATION).checked).toBe(false);
    mounted.dispose();
  });
  it('selects a small exact admission from 201 saved photographs and recovers selection, retry and prior receipts', async () => {
    const f = fixture(201); f.setUploaded();
    f.savedRequests.push({ request_id: 'old-request', operation: 'admission', batch_id: 'prior-batch', queued_job_id: 'prior-job',
      receipts: [{ capture_id: ids[1], authorization_id: 'prior-authority', screening_id: 'prior-screen', eligibility_state: 'blocked-or-stale' }] });
    let mounted = f.make(); document.body.append(mounted.root); await mounted.begin();
    expect(mounted.root.textContent).toContain('0 of 201 saved photographs selected');
    for (const i of [1, 201]) {
      const checkbox = input(mounted.root, `Include photograph ${i} in this admission`);
      checkbox.checked = true; checkbox.dispatchEvent(new Event('change'));
    }
    mounted.dispose(); mounted.root.remove();
    mounted = f.make(); document.body.append(mounted.root); await mounted.begin();
    expect(mounted.root.textContent).toContain('2 of 201 saved photographs selected');
    expect(mounted.root.textContent).toContain('prior-screen');
    input(mounted.root, 'Purpose of this use').value = 'Selected fixture pair';
    input(mounted.root, 'Your account authority basis').value = 'Fixture operator permission';
    input(mounted.root, 'Authority valid until').value = '2099-01-01T12:00';
    button(mounted.root, 'Authorize personal admission and request detection').click(); await settle(mounted.root);
    const pending = f.posts.at(-1)!.body;
    expect(pending.members).toEqual(await Promise.all([0, 200].map(async i => ({ capture_id: f.captureIds[i],
      sha256: await sha256(await f.files[i]!.arrayBuffer()), bytes: f.files[i]!.size, review: 'not-reviewed' }))));
    expect(input(mounted.root, 'Include photograph 2 in this admission').disabled).toBe(true);
    mounted.dispose(); mounted.root.remove();
    mounted = f.make(); document.body.append(mounted.root); await mounted.begin();
    button(mounted.root, 'Retry exact interrupted admission').click(); await settle(mounted.root);
    expect(f.posts.at(-1)!.body).toEqual(pending);
    expect(mounted.root.textContent).toContain('prior-screen');
    expect(mounted.root.textContent).toContain('2 of 201 saved photographs selected');
    // A subsequent upload starts with only its accepted photographs, not the historical selection.
    Object.defineProperty(input(mounted.root, 'Original HEIC or JPEG photographs'), 'files', { value: f.files.slice(0, 2) });
    button(mounted.root, 'Upload originals').click(); await settle(mounted.root);
    expect(mounted.root.textContent).toContain('2 of 201 saved photographs selected');
    expect(input(mounted.root, 'Include photograph 201 in this admission').checked).toBe(false);
    expect(input(mounted.root, 'Include photograph 2 in this admission').checked).toBe(true);
    mounted.dispose();
  });
  it('limits admission membership to 200 while preserving access to a larger saved inventory', async () => {
    const f = fixture(201); f.setUploaded();
    const mounted = f.make(); document.body.append(mounted.root); await mounted.begin();
    for (let i = 1; i <= 201; i++) {
      const checkbox = input(mounted.root, `Include photograph ${i} in this admission`);
      checkbox.checked = true; checkbox.dispatchEvent(new Event('change'));
    }
    expect(mounted.root.textContent).toContain('200 of 201 saved photographs selected');
    expect(mounted.root.textContent).toContain('An admission can contain at most 200 photographs');
    expect(input(mounted.root, 'Include photograph 201 in this admission').checked).toBe(false);
    expect(f.posts).toEqual([]);
    mounted.dispose();
  });
});


it('keeps preview intake read-only and closes its reading workflow with Escape', async () => {
  const fetch = vi.fn();
  const mounted = mountPersonalIntake({ preview: true,
    credentials: { baseUrl: 'https://fixture.test', token: 'fixture-token', fetch },
    session: createPersonalIntakeSession(), snapshot: adaptSnapshot({ state_version: 1, entities: [], occurrences: [], proposals: [], scene_groups: [], reconstruction_scenes: [], never_same: [], deleted_entity_ids: [] }),
    media: undefined, reloadSnapshot: vi.fn(), refreshWorld: vi.fn(),
  });
  document.body.replaceChildren(mounted.root);
  const workflow = mounted.root.querySelector<HTMLDetailsElement>('.photo-review-workflow')!;
  workflow.open = true;
  await mounted.begin();
  expect(fetch).not.toHaveBeenCalled();
  expect(mounted.root.querySelector('fieldset')?.disabled).toBe(true);
  expect(mounted.root.textContent).toContain('require an authenticated workspace');
  workflow.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  expect(workflow.open).toBe(false);
  expect(document.activeElement).toBe(workflow.querySelector(':scope > summary'));
  mounted.dispose();
});
