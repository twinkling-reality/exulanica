// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PersonalAdmissionApi, sha256, HUMAN_ATTESTATION, type PersonalAdmission } from '../src/personal-admission-api.js';
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const source = { capture_id: '11111111-1111-4111-8111-111111111111', sha256: 'a'.repeat(64), bytes: 42 };
const body: PersonalAdmission = {
  members: [{ ...source, review: 'not-reviewed' }], purpose: 'Reconstruct my place',
  authority: { account_authority_basis: 'Explicit fixture authority', authorized_at: '2026-09-12T10:00:00Z', valid_until: '2026-09-13T10:00:00Z' },
  recorded_at: '2026-09-12T10:00:01Z', operation: 'detect',
};
describe('original byte intake and dated admission', () => {
  it('sends unchanged HEIC/JPEG multipart bytes and binds receipts by digest, not filename', async () => {
    const files = [new File([new Uint8Array([0, 1, 2, 255])], 'same.heic', { type: 'image/heic' }),
      new File([new Uint8Array([255, 216, 255, 0])], 'same.heic', { type: 'image/jpeg' })];
    const digests = await Promise.all(files.map(async f => sha256(await f.arrayBuffer())));
    const fetch = vi.fn(async (_url: string | URL | Request, init: RequestInit = {}) => {
      expect(init.headers).toEqual({ authorization: 'Bearer fixture-token' });
      const parts = (init.body as FormData).getAll('files') as File[];
      expect(await parts[0]!.arrayBuffer()).toEqual(await files[0]!.arrayBuffer());
      expect(await parts[1]!.arrayBuffer()).toEqual(await files[1]!.arrayBuffer());
      return json({ batch_id: 'batch', queued_job_id: 'job', refused: [], accepted: [
        { capture_id: 'second', blob_sha256: digests[1], filename: 'same.heic', status: 'ingested' },
        { capture_id: 'first', blob_sha256: digests[0], filename: 'same.heic', status: 'unchanged' },
      ] });
    });
    const result = await new PersonalAdmissionApi({ baseUrl: 'https://fixture.test/', token: 'fixture-token', fetch }).upload(files);
    expect(result.accepted.map(s => [s.capture_id, s.sha256, s.bytes])).toEqual([
      ['second', digests[1], 4], ['first', digests[0], 4],
    ]);
    expect(fetch.mock.calls[0]![0]).toBe('https://fixture.test/intake');
  });
  it('shows rejected parts and refuses a receipt for different bytes', async () => {
    const file = new File(['not a photograph'], 'bad.jpg');
    const fetch = vi.fn(async () => json({ batch_id: 'batch', queued_job_id: null, accepted: [],
      refused: [{ filename: 'bad.jpg', reason: 'not_an_image', detail: 'Unrecognized bytes' }] }));
    const api = new PersonalAdmissionApi({ baseUrl: 'https://fixture.test', token: 't', fetch });
    expect((await api.upload([file])).refused[0]!.reason).toBe('not_an_image');
    fetch.mockImplementation(async () => json({ batch_id: 'b', accepted: [{ capture_id: 'x', blob_sha256: 'a'.repeat(64) }], refused: [] }));
    await expect(api.upload([file])).rejects.toThrow('does not match');
  });
  it('replays the identical dated body after interrupted admission without inventing human review', async () => {
    const requests: unknown[] = [];
    const fetch = vi.fn(async (_url: string | URL | Request, init: RequestInit = {}) => {
      requests.push(JSON.parse(String(init.body)));
      if (requests.length === 1) throw new Error('interrupted');
      return json({ batch_id: 'batch', queued_job_id: 'job', receipts: [] });
    });
    const api = new PersonalAdmissionApi({ baseUrl: 'https://fixture.test', token: 't', fetch });
    await expect(api.admit(body)).rejects.toThrow('interrupted');
    await api.requests.retry();
    expect(requests[0]).toEqual(expect.objectContaining(body));
    expect(requests[1]).toEqual(requests[0]);
    expect(requests[0]).not.toHaveProperty('attestation');
  });
  it('requires human choices and the exact attestation before review', async () => {
    const fetch = vi.fn();
    const api = new PersonalAdmissionApi({ baseUrl: 'https://fixture.test', token: 't', fetch });
    await expect(api.admit({ ...body, operation: 'review' })).rejects.toThrow('named human review');
    await expect(api.admit({ ...body, operation: 'review', reviewed_by_name: 'Fixture reviewer',
      attestation: HUMAN_ATTESTATION })).rejects.toThrow('named human review');
    expect(fetch).not.toHaveBeenCalled();
  });
});

afterEach(() => window.sessionStorage.clear());
