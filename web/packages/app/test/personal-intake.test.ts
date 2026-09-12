// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { adaptSnapshot } from '@exulanica/graph-client';
import { initialFormationState } from '@exulanica/formation';
import { mountPersonalIntake, createPersonalIntakeSession } from '../src/composition/personal-intake.js';
import { sha256, HUMAN_ATTESTATION } from '../src/personal-admission-api.js';

const mocks = vi.hoisted(() => ({ watch: vi.fn(), disposeMedia: vi.fn() }));
vi.mock('../src/formation.js', () => ({ listBatches: async () => [], watchBatch: (...args: unknown[]) => mocks.watch(...args) }));
vi.mock('../src/source-media-api.js', () => ({ SourceMediaClient: class {
  async load() { return { catalog: new Map(), issues: [], dispose: mocks.disposeMedia }; }
} }));
const ids = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'];
const key = 'a'.repeat(64), subject = '33333333-3333-4333-8333-333333333333';
const json = (body: unknown) => new Response(JSON.stringify(body));
function fixture(count = 2) {
  let uploaded = false, linked = false, interrupted = false;
  let regions = true;
  const posts: { path: string; body: any }[] = [];
  const savedRequests: any[] = [];
  const captureIds = Array.from({ length: count }, (_, i) => ids[i] ?? `00000000-0000-4000-8000-${String(i).padStart(12, '0')}`);
  const files = [new File(['fixture HEIC bytes'], 'a.heic'), new File(['fixture JPEG bytes'], 'b.jpg'),
    ...Array.from({ length: count - 2 }, (_, i) => new File([`history ${i}`], `history-${i}.jpg`))];
  const snapshot = () => adaptSnapshot({ state_version: 1, entities: [], occurrences: [], proposals: [],
    scene_groups: [], reconstruction_scenes: [], never_same: [], deleted_entity_ids: [],
    review_sources: uploaded ? captureIds.map((id, i) => ({ kind: 'admitted_capture' as const, capture_id: id,
      evidence_span_id: `span-${i}`, captured_at: null, media_type: 'image/jpeg', state: 'unavailable_asset' as const,
      reason: 'Fixture viewer unavailable', evidence_path: null, content_sha256: null,
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
  const make = (session = createPersonalIntakeSession()) => mountPersonalIntake({
    credentials: { baseUrl: 'https://fixture.test', token: 'fixture-token', fetch }, session,
    snapshot: snapshot(), media: undefined, reloadSnapshot: async () => snapshot(),
    refreshWorld: vi.fn(async () => undefined), storage: window.sessionStorage,
  });
  return { files, posts, make, captureIds, savedRequests, setUploaded: () => { uploaded = true; }, noRegions: () => { regions = false; } };
}
function button(root: HTMLElement, text: string) { return [...root.querySelectorAll('button')].find(b => b.textContent === text)!; }
function input(root: HTMLElement, label: string) { return root.querySelector(`[aria-label="${label}"]`) as HTMLInputElement; }
const settle = async (root: HTMLElement) => { await vi.waitFor(() => expect(root.querySelector('fieldset')!.disabled).toBe(false)); };
afterEach(() => { document.body.replaceChildren(); window.sessionStorage.clear(); vi.clearAllMocks(); });

describe('mounted personal intake with scripted transport (not real-photo acceptance)', () => {
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
    button(mounted.root, 'Record human review and request eligible depth').click(); await settle(mounted.root);
    const review = f.posts.at(-1)!.body;
    expect(review.operation).toBe('review'); expect(review.attestation).toBe(HUMAN_ATTESTATION);
    expect(review.members.every((m: any) => m.review === 'confirmed-regions')).toBe(true);
    expect(mounted.root.textContent).toContain('Queued work is not completed depth');
    mounted.dispose();
    mounted.root.remove();
    window.sessionStorage.clear();
    const writes = f.posts.length;
    mounted = f.make(); document.body.append(mounted.root); await mounted.begin();
    expect(mounted.root.textContent).toContain(subject);
    expect(mounted.root.textContent).toContain(await sha256(await f.files[0]!.arrayBuffer()));
    expect(mounted.root.textContent).toContain('Queued work is not completed depth');
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
