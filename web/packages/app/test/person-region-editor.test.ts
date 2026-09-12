// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PersonReviewApi } from '../src/person-review-api.js';
import { buildPersonReview } from '../src/ui/person-review.js';
import { buildPersonRegionEditor, imagePoint, PersonRegionDrafts, validateOutline } from '../src/ui/person-region-editor.js';

afterEach(() => { document.body.replaceChildren(); window.sessionStorage.clear(); });
const capture = 'c0ffee00-0000-4000-8000-000000000000';
function mounted(onAdd: Parameters<typeof buildPersonRegionEditor>[0]['onAdd'], drafts = new PersonRegionDrafts(), isCurrent = () => true) {
  const editor = { captureId: capture, source: { available: true, url: 'blob:generated-fixture', alt: 'GENERATED TEST IMAGE' }, drafts, isCurrent, onAdd };
  const root = buildPersonReview({ captureId: capture, reviewState: 'unscreened', regions: [], editor });
  document.body.append(root);
  const photo = root.querySelector('img')!;
  expect(photo, 'manual-region-authoring requires the mounted add editor').not.toBeNull();
  Object.defineProperties(photo, { naturalWidth: { value: 800 }, naturalHeight: { value: 400 } });
  photo.dispatchEvent(new Event('load'));
  const stage = root.querySelector('.person-region-editor-stage')!;
  vi.spyOn(stage, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 400, height: 400 } as DOMRect);
  const draw = () => {
    stage.dispatchEvent(new MouseEvent('pointerdown', { clientX: 40, clientY: 120, button: 0 }));
    stage.dispatchEvent(new MouseEvent('pointerup', { clientX: 200, clientY: 240, button: 0 }));
  };
  const submit = () => root.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
  return { root, draw, submit, stage };
}
const settle = async () => { await new Promise(resolve => setTimeout(resolve, 0)); };
describe('manual person authoring', () => {
  it('draws a missed person from an empty detector inventory through the authenticated API payload', async () => {
    const fetch = vi.fn(async () => new Response('{}', { status: 201 }));
    const api = new PersonReviewApi({ baseUrl: 'https://test.invalid/api', token: 'test-token', fetch });
    const { root, draw, submit } = mounted(region => api.add(capture, region));
    draw(); submit(); submit(); await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(root.textContent).toContain('Region saved'));
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toBe(`https://test.invalid/api/person-regions/${capture}/edits`);
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer test-token');
    const body = JSON.parse(String(init.body));
    expect(body.edits).toEqual([{ action: 'add', shape: 'box', region_key: expect.stringMatching(/^[a-f0-9]{64}$/u),
      silhouette: { kind: 'polygon', points: [[100000, 100000], [500000, 100000], [500000, 700000], [100000, 700000]] } }]);
    expect(root.textContent).toContain('Region saved');
    submit(); expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('uses the resized image layout in the submitted payload', async () => {
    const fetch = vi.fn(async () => new Response('{}', { status: 201 }));
    const api = new PersonReviewApi({ baseUrl: 'https://test.invalid/api', token: 't', fetch });
    const { stage, draw, submit } = mounted(region => api.add(capture, region));
    vi.mocked(stage.getBoundingClientRect).mockReturnValue({ left: 0, top: 0, width: 800, height: 400 } as DOMRect);
    draw(); submit(); await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const init = (fetch.mock.calls[0] as unknown as [unknown, RequestInit])[1];
    expect(JSON.parse(String(init.body)).edits[0].silhouette.points).toEqual([
      [50000, 300000], [250000, 300000], [250000, 600000], [50000, 600000],
    ]);
  });
  it('releases detached panels without clearing a newer panel callback', async () => {
    const drafts = new PersonRegionDrafts();
    const first = mounted(async () => {}, drafts);
    const previous = drafts.entries.get(capture)!.refresh;
    expect(previous).toBeTypeOf('function');
    first.root.remove();
    const second = mounted(async () => {}, drafts);
    const replacement = drafts.entries.get(capture)!.refresh;
    expect(replacement).not.toBe(previous);
    await settle();
    expect(drafts.entries.get(capture)!.refresh).toBe(replacement);
    second.root.remove(); await settle();
    expect(drafts.entries.get(capture)!.refresh).toBeUndefined();
  });
  it('maps resized photographs and rejects letterbox gestures', () => {
    expect(imagePoint(20, 60, { left: 0, top: 0, width: 200, height: 200 }, 800, 400)).toEqual([100000, 100000]);
    expect(imagePoint(20, 10, { left: 0, top: 0, width: 200, height: 200 }, 800, 400)).toBeNull();
    const call = vi.fn(async () => {});
    const { stage, submit } = mounted(call);
    stage.dispatchEvent(new MouseEvent('pointerdown', { clientX: 20, clientY: 10 }));
    stage.dispatchEvent(new MouseEvent('pointerup', { clientX: 200, clientY: 240 }));
    submit(); expect(call).not.toHaveBeenCalled();
  });
  it('rejects invalid outlines before any request', async () => {
    expect(() => validateOutline({ kind: 'polygon', points: [[0, 0], [1, 1], [2, 2]] })).toThrow(/area/u);
    const fetch = vi.fn();
    await expect(new PersonReviewApi({ baseUrl: 'https://test.invalid', token: 't', fetch }).add(capture,
      { region_key: 'a'.repeat(64), silhouette: { kind: 'polygon', points: [[0.5, 0], [1, 0], [1, 1]] } })).rejects.toThrow(/coordinates/u);
    expect(fetch).not.toHaveBeenCalled();
  });
  it('supports keyboard fields and explicit cancellation without a write', () => {
    const call = vi.fn(async () => {});
    const { root, submit } = mounted(call);
    root.querySelectorAll('input').forEach((field, i) => {
      field.value = ['100000', '100000', '500000', '700000'][i]!;
      field.dispatchEvent(new Event('input'));
    });
    [...root.querySelectorAll('button')].find(b => b.textContent === 'Cancel draft')!.click();
    expect(root.textContent).toContain('Draft cleared');
    submit(); expect(call).not.toHaveBeenCalled();
  });
  it('saves keyboard coordinates and preserves a server refusal for retry', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ detail: 'Edit refused' }), { status: 409, headers: { 'Content-Type': 'application/json' } }));
    const api = new PersonReviewApi({ baseUrl: 'https://test.invalid/api', token: 't', fetch });
    const { root, submit } = mounted(region => api.add(capture, region));
    root.querySelectorAll('input').forEach((field, i) => {
      field.value = ['0', '0', '400000', '800000'][i]!;
      field.dispatchEvent(new Event('input'));
    });
    submit(); await vi.waitFor(() => expect(root.textContent).toContain('Draft retained'));
    expect(root.querySelector('input')!.value).toBe('0');
    expect(fetch).toHaveBeenCalledTimes(1);
    submit(); await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    const bodies = fetch.mock.calls.map(call => JSON.parse(String((call as unknown as [unknown, RequestInit])[1].body)));
    expect(bodies[0].edits).toEqual(bodies[1].edits);
    expect(bodies[0].request_id).not.toEqual(bodies[1].request_id);
  });
  it('retains the draft and refusal through a capture switch while saving', async () => {
    let refuse!: (e: Error) => void;
    const drafts = new PersonRegionDrafts();
    let current = true;
    const onAdd = vi.fn(() => new Promise<void>((_, reject) => { refuse = reject; }));
    const first = mounted(onAdd, drafts, () => current);
    first.draw(); first.submit(); current = false; first.root.remove();
    const other = document.createElement('p'); other.textContent = 'Other photograph'; document.body.append(other);
    refuse(new Error('Server refused this edit.')); await settle();
    expect(other.textContent).toBe('Other photograph');
    first.submit(); expect(onAdd).toHaveBeenCalledTimes(1);
    current = true;
    const returned = mounted(onAdd, drafts);
    expect(returned.root.textContent).toContain('Server refused');
    expect(returned.root.querySelector('input')!.value).toBe('100000');
  });
  it('discloses unavailable authorized media and offers no save', () => {
    const node = buildPersonRegionEditor({ captureId: capture, source: null, drafts: new PersonRegionDrafts(), isCurrent: () => true, onAdd: vi.fn() });
    expect(node.textContent).toContain('unavailable'); expect(node.querySelector('button')).toBeNull();
  });
});

it('reopens a saved correction from the current outline with editable coordinates and the same region key', async () => {
  const drafts = new PersonRegionDrafts();
  const key = 'b'.repeat(64);
  const onAdd = vi.fn(async () => {});
  const correction = { region_key: key, silhouette: { kind: 'polygon' as const,
    points: [[100000, 100000], [500000, 100000], [500000, 700000], [100000, 700000]] } };
  const options = { captureId: capture, correction, drafts, source: { available: true, url: 'blob:fixture', alt: 'Synthetic fixture' },
    isCurrent: () => true, onAdd };
  const first = buildPersonRegionEditor(options); document.body.append(first);
  const photo = first.querySelector('img')!;
  Object.defineProperties(photo, { naturalWidth: { value: 800 }, naturalHeight: { value: 400 } });
  photo.dispatchEvent(new Event('load'));
  first.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
  await vi.waitFor(() => expect(first.textContent).toContain('Region saved'));
  first.remove();
  const next = buildPersonRegionEditor(options); document.body.append(next);
  expect(next.querySelector('input')!.disabled).toBe(false);
  expect(next.querySelector('input')!.value).toBe('100000');
  expect(onAdd).toHaveBeenCalledWith(correction);
});
