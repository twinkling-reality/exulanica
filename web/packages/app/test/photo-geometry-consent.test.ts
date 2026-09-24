// @vitest-environment happy-dom
/**
 * Letting a depth model estimate shape from a photograph is a decision the person makes, and
 * these tests hold the three places that is visible in the browser: the tick that sends it, the
 * wording sent back with it, and the per-photograph state and stop control afterwards.
 *
 * The transport is scripted. Nothing here is acceptance of the real path; what it proves is what
 * this client sends and shows, which is the half a server test cannot see.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { adaptSnapshot } from '@exulanica/graph-client';
import { mountPersonalIntake, createPersonalIntakeSession } from '../src/composition/personal-intake.js';
import { HUMAN_ATTESTATION, sha256, type ModelRightOffer } from '../src/personal-admission-api.js';
import type { SavedWorldEntry, SavedWorldSourceAttachment } from '../src/world-entry-api.js';

const mocks = vi.hoisted(() => ({ media: new Map<string, unknown>() }));
vi.mock('../src/formation.js', () => ({ listBatches: async () => [], watchBatch: () => () => undefined }));
vi.mock('../src/source-media-api.js', () => ({ SourceMediaClient: class {
  async load() { return { catalog: mocks.media, issues: [], dispose: () => undefined }; }
} }));

const CAPTURE = '11111111-1111-4111-8111-111111111111';
/**
 * The depth offer as the server states it. The notice is deliberately not the product's sentence:
 * whatever the drawer shows and sends back must be this text, read from the response.
 */
const DEPTH_OFFER: ModelRightOffer = Object.freeze({
  role: 'depth', offered_with: 'review', label: 'Estimate 3D shape from these photos',
  short: '3D estimate', notice: 'Fixture notice for depth: the words the server states, and only those.',
  stop: 'Stop 3D estimates for this photo? Your photo, review and worlds stay. Estimates made from it '
    + 'stop showing, and none are made again unless you review it again and allow it.',
  stop_action: 'Stop 3D estimates for this photo', stop_confirm: 'Stop 3D estimates',
  destination: 'local-process',
  models: [{ provider: 'local', role: 'depth', model_id: 'Ruicheng/moge-2-vitl', revision: '39c4d5e' }],
});
const RIGHT = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const json = (body: unknown) => new Response(JSON.stringify(body));

const PLACED_SOURCE = Object.freeze({
  capture_id: CAPTURE,
  source_sha256: 'a'.repeat(64),
  attachment: { attachment_id: '55555555-5555-4555-8555-555555555555', entry_id: 'entry' },
  authorization: { authorization_id: 'auth', evidence_sha256: 'b'.repeat(64) },
  screening: { screening_id: 'screen', receipt_sha256: 'c'.repeat(64) },
  right: { right_id: RIGHT, receipt_sha256: 'd'.repeat(64) },
  model: {
    provider: 'local', role: 'depth', identifier: 'Ruicheng/moge-2-vitl',
    revision: '39c4d5e', destination: 'local-process',
  },
  artifact: {
    artifact_id: 'artifact', content_sha256: 'e'.repeat(64), byte_size: 3475644,
    container: 'opm/2', stage_version: 2, rung: 3, declared_metric: true,
    declared_fov_y_microdegrees: 32_333_896,
  },
});

/** One photograph, already uploaded and reviewed, with whatever depth rights a test asks for. */
function fixture(rights: 'none' | 'current' | 'ended' = 'none', placed = false) {
  const posts: { path: string; body: unknown }[] = [];
  const file = new File(['fixture JPEG bytes'], 'a.jpg');
  const saved: unknown[] = [{
    request_id: 'reviewed-request', operation: 'review', batch_id: 'reviewed',
    queued_job_id: 'reviewed-job',
    receipts: [{ capture_id: CAPTURE, authorization_id: 'auth', screening_id: 'screen', eligibility_state: 'eligible' }],
  }];
  let granted = rights;
  const modelRights = () => granted === 'none' ? [] : [{
    right_id: RIGHT, capture_id: CAPTURE, operation: 'model_processing',
    model: { provider: 'local', role: 'depth', model_id: 'Ruicheng/moge-2-vitl', revision: '39c4d5e' },
    destination: 'local-process', granted_at: '2026-09-22T10:00:00.000000Z',
    valid_until: '2099-01-01T12:00:00.000000Z', withdrawn: granted === 'ended',
    receipt_sha256: 'b'.repeat(64), state: granted === 'ended' ? 'ended' : 'current',
  }];
  const snapshot = () => adaptSnapshot({
    state_version: 1, entities: [], occurrences: [], proposals: [], scene_groups: [],
    reconstruction_scenes: [], never_same: [], deleted_entity_ids: [],
    review_sources: [{
      kind: 'admitted_capture' as const, capture_id: CAPTURE, evidence_span_id: 'span-0',
      captured_at: null, media_type: 'image/jpeg', state: 'available' as const, reason: null,
      evidence_path: '/evidence/span-0/masked', content_sha256: 'd'.repeat(64),
      person_review_state: 'screened' as const, person_regions: [],
    }],
  });
  const fetch = vi.fn(async (input: string | URL | Request, init: RequestInit = {}) => {
    const path = new URL(String(input)).pathname;
    if (path === '/personal-admission' && init.method === 'GET') {
      return json({
        sources: [{
          capture_id: CAPTURE, sha256: await sha256(await file.arrayBuffer()), bytes: file.size,
          media_type: 'image/jpeg', authority: null, model_rights: modelRights(),
        }],
        requests: saved,
        model_right_offers: [DEPTH_OFFER],
      });
    }
    if (init.method === 'POST') {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      posts.push({ path, body });
      if (path.endsWith('/withdraw')) { granted = 'ended'; return json({ right_id: RIGHT, state: 'ended', withdrawn: true }); }
      if (path === '/personal-admission') {
        const result = {
          request_id: body['request_id'], operation: 'admission', batch_id: 'admitted',
          queued_job_id: 'job', receipts: [{ capture_id: CAPTURE, authorization_id: 'auth', screening_id: 'screen', eligibility_state: 'eligible' }],
        };
        saved.push(result);
        return json(result);
      }
      return json({});
    }
    if (path.startsWith('/person-regions/')) {
      return json({ capture_id: CAPTURE, review_state: 'screened', regions: [] });
    }
    if (path.startsWith('/world/versions/')) {
      return json({
        schema_version: placed ? 3 : 1,
        version_id: '77777777-7777-4777-8777-777777777777',
        world_id: 'world:authored:starter',
        source_snapshot_id: '88888888-8888-4888-8888-888888888888',
        parent_version_id: null, title: 'My world', origin: 'authored',
        style_version_id: null, state_sha256: 'a'.repeat(64), edit_seq: placed ? 1 : 0,
        source_invalidated: false, created_by: 'actor', created_at: '2026-09-20T12:00:00Z',
        objects: [], element_overrides: [], environment_instances: [], edits: [],
        point_map_instances: placed ? [{
          instance_id: 'point-map:my-room',
          source: PLACED_SOURCE,
          region_id: 'region:starter',
          transform: {
            coordinate_space: 'region_local', coordinate_unit: 'millimetre',
            x_mm: 0, y_mm: 1650, z_mm: -1200, yaw_microradians: 0, scale_milli: 1000,
          },
          origin: { kind: 'authored', role: 'personal' },
          removed: false, availability: 'available', unavailable_reason: null,
          truth: 'Model estimate from one photograph, not measured, shows only what the camera '
            + 'saw, placed here by you.',
          scale: "Approximate size from one photograph; not measured. Shown at 1x the model's "
            + 'own estimate.',
          coverage: 'This shows only the surfaces that one camera saw. Nothing behind or beside '
            + 'them was filled in.',
        }] : [],
      });
    }
    throw new Error(`Unexpected fixture request: ${path}`);
  });
  return {
    posts, file, snapshot, granted: () => granted,
    make: (overrides: Partial<Parameters<typeof mountPersonalIntake>[0]> = {}) => mountPersonalIntake({
      credentials: { baseUrl: 'https://fixture.test', token: 'fixture-token', fetch },
      session: createPersonalIntakeSession(), snapshot: snapshot(), media: undefined,
      reloadSnapshot: async () => snapshot(), refreshWorld: vi.fn(async () => undefined),
      storage: window.sessionStorage, ...overrides,
    }),
  };
}

const entry = (): SavedWorldEntry => ({
  entryId: '99999999-9999-4999-8999-999999999999',
  worldId: 'world:authored:starter', title: 'My world', sourceKind: 'authored',
  sourceSnapshotId: '88888888-8888-4888-8888-888888888888',
  sourceSnapshotSha256: 'c'.repeat(64),
  authoredScene: { schemaVersion: 1, kind: 'authored-starter', region: {
    regionId: 'region:starter', origin: 'authored',
    module: { key: 'region.authored-ground', version: 1 },
    ground: { kind: 'flat', halfWidthMm: 12000, halfDepthMm: 12000, elevationMm: 0 },
    spawn: { xMm: 0, yMm: 0, zMm: 4000, yawMicroradians: 0 },
  } },
  authoredVersionId: '77777777-7777-4777-8777-777777777777',
  authoredStateSha256: 'a'.repeat(64), authoredEditSeq: 0,
  currentAuthoredStateSha256: 'a'.repeat(64), currentAuthoredEditSeq: 0,
  styleVersionId: '66666666-6666-4666-8666-666666666666', revision: 2,
  availability: 'available', unavailableReason: null,
  sourceAttachments: [attachment()],
  createdAt: '2026-09-20T12:00:00Z', updatedAt: '2026-09-20T12:00:00Z',
});
const attachment = (): SavedWorldSourceAttachment => ({
  attachmentId: '55555555-5555-4555-8555-555555555555',
  operationId: '44444444-4444-4444-8444-444444444444',
  captureId: CAPTURE, evidenceSpanId: 'span-0', sourceSha256: 'f'.repeat(64),
  authorizationId: 'auth', screeningId: 'screen', role: 'reference',
  attachedEntryRevision: 2, attachedBy: CAPTURE, attachedAt: '2026-09-20T12:01:00Z',
  availability: 'available', unavailableReason: null, viewerSha256: 'e'.repeat(64),
  evidencePath: '/evidence/span-0/masked',
});

const settle = async (root: HTMLElement) =>
  vi.waitFor(() => expect(root.querySelector('fieldset')!.disabled).toBe(false));
const button = (root: HTMLElement, text: string) =>
  [...root.querySelectorAll('button')].find(b => b.textContent === text)!;
const field = (root: HTMLElement, label: string) =>
  root.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;

afterEach(() => {
  document.body.replaceChildren();
  window.sessionStorage.clear();
  mocks.media.clear();
  vi.clearAllMocks();
});

/** Drive step 4 to the point where Record human review would be accepted. */
async function readyToReview(root: HTMLElement, file: File): Promise<void> {
  const include = field(root, 'Include photograph 1 in this admission');
  if (!include.checked) { include.checked = true; include.dispatchEvent(new Event('change')); }
  field(root, 'Purpose of this use').value = 'Fixture place';
  field(root, 'Your account authority basis').value = 'Fixture operator permission';
  field(root, 'Authority valid until').value = '2099-01-01T12:00';
  field(root, 'Reviewer’s actual name').value = 'Scripted fixture, not a human';
  const originals = field(root, 'Reselect exact originals for local review');
  Object.defineProperty(originals, 'files', { value: [file], configurable: true });
  originals.dispatchEvent(new Event('change'));
  await settle(root);
  const photo = root.querySelector('img')!;
  Object.defineProperties(photo, { naturalWidth: { value: 100 }, naturalHeight: { value: 100 } });
  photo.dispatchEvent(new Event('load'));
  const choice = field(root, 'Human review of this photograph');
  choice.value = 'no-person';
  choice.dispatchEvent(new Event('change'));
  field(root, HUMAN_ATTESTATION).checked = true;
}

describe('permission for a 3D estimate from a personal photograph', () => {
  it('sends nothing about depth when the box is left alone, and the exact notice when it is ticked', async () => {
    const f = fixture();
    const mounted = f.make();
    document.body.append(mounted.root);
    await mounted.begin();
    await settle(mounted.root);
    const tick = field(mounted.root, 'Estimate 3D shape from these photos');
    expect(tick.checked).toBe(false);
    expect(mounted.root.textContent).toContain(DEPTH_OFFER.notice);

    // The control: a complete review with the box untouched grants nothing.
    await readyToReview(mounted.root, f.file);
    button(mounted.root, 'Record human review').click();
    await settle(mounted.root);
    const untouched = f.posts.at(-1)!.body as Record<string, unknown>;
    expect(untouched['operation']).toBe('review');
    expect(untouched['model_rights']).toBeUndefined();

    // The same review with the box ticked, which is the only difference.
    await readyToReview(mounted.root, f.file);
    tick.checked = true;
    tick.dispatchEvent(new Event('change'));
    expect(mounted.root.textContent).toContain('Allowed until');
    button(mounted.root, 'Record human review').click();
    await settle(mounted.root);
    const ticked = f.posts.at(-1)!.body as Record<string, unknown>;
    expect(ticked['model_rights']).toEqual([{
      role: 'depth',
      valid_until: new Date('2099-01-01T12:00').toISOString(),
      notice: DEPTH_OFFER.notice,
    }]);
    mounted.dispose();
  });

  it('takes both ticks back when the review they describe changes', async () => {
    const f = fixture();
    const mounted = f.make();
    document.body.append(mounted.root);
    await mounted.begin();
    await settle(mounted.root);
    await readyToReview(mounted.root, f.file);
    const tick = field(mounted.root, 'Estimate 3D shape from these photos');
    tick.checked = true;
    tick.dispatchEvent(new Event('change'));

    const choice = field(mounted.root, 'Human review of this photograph');
    choice.value = 'confirmed-regions';
    choice.dispatchEvent(new Event('change'));
    await settle(mounted.root);
    expect(field(mounted.root, HUMAN_ATTESTATION).checked).toBe(false);
    expect(tick.checked).toBe(false);
    mounted.dispose();
  });

  it('says in plain words whether a photograph allows a 3D estimate, and stops it on a confirmation', async () => {
    const f = fixture('current');
    const mounted = f.make({ getEntry: entry, entryClient: { detachSources: vi.fn(), rebindSources: vi.fn() } });
    document.body.append(mounted.root);
    await mounted.begin();
    await settle(mounted.root);
    const card = () => mounted.root.querySelector('.attached-reference')!;
    expect(card().textContent).toContain('3D estimate: allowed');

    button(mounted.root, 'Stop 3D estimates for this photo').click();
    await settle(mounted.root);
    // A stop is final, so the person reads what it costs before it is sent.
    expect(card().textContent).toContain('Your photo, review and worlds stay');
    expect(f.posts.some(p => p.path.endsWith('/withdraw'))).toBe(false);

    button(mounted.root, 'Stop 3D estimates').click();
    await settle(mounted.root);
    expect(f.posts.filter(p => p.path === `/personal-admission/model-rights/${RIGHT}/withdraw`)).toHaveLength(1);
    expect(card().textContent).toContain('3D estimate: stopped');
    expect(button(mounted.root, 'Stop 3D estimates for this photo')).toBeUndefined();
    mounted.dispose();
  });

  it('reads a photograph nobody allowed as not allowed rather than as stopped', async () => {
    const f = fixture();
    const mounted = f.make({ getEntry: entry, entryClient: { detachSources: vi.fn(), rebindSources: vi.fn() } });
    document.body.append(mounted.root);
    await mounted.begin();
    await settle(mounted.root);
    const card = mounted.root.querySelector('.attached-reference')!;
    expect(card.textContent).toContain('3D estimate: not allowed');
    expect(card.textContent).not.toContain('3D estimate: stopped');
    mounted.dispose();
  });
});

describe('a placed estimate in the photo drawer', () => {
  it('shows what it is, what permitted it, and the control that ends it', async () => {
    const f = fixture('current', true);
    const mounted = f.make({
      getEntry: entry, entryClient: { detachSources: vi.fn(), rebindSources: vi.fn() },
    });
    document.body.append(mounted.root);
    await mounted.begin();
    await settle(mounted.root);
    const panel = mounted.root.querySelector('.photo-geometry-inspector')!;
    expect(panel).not.toBeNull();
    const words = panel.textContent ?? '';
    expect(words).toContain('3D estimate from a photo');
    expect(words).toContain('not measured');
    expect(words).toContain('Ruicheng/moge-2-vitl@39c4d5e');
    expect(words).toContain('Showing in this world.');
    mounted.dispose();
  });

  it('shows no panel for a photograph nothing was placed from', async () => {
    const f = fixture('current', false);
    const mounted = f.make({
      getEntry: entry, entryClient: { detachSources: vi.fn(), rebindSources: vi.fn() },
    });
    document.body.append(mounted.root);
    await mounted.begin();
    await settle(mounted.root);
    expect(mounted.root.querySelector('.photo-geometry-inspector')).toBeNull();
    mounted.dispose();
  });
});
