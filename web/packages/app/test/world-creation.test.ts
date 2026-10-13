// @vitest-environment happy-dom
import { readFileSync } from 'node:fs';
import { afterEach, expect, it, vi } from 'vitest';
import { buildWorldCreation } from '../src/composition/world-creation.js';
import { ApiError } from '@exulanica/graph-client';
import { parseWorldDraftOffer, parseWorldMakingDraft } from '../src/world-making-api.js';

const served = JSON.parse(readFileSync('../tests/snapshots/world-drafts.served.json', 'utf8'));
const offer = parseWorldDraftOffer(served.offer);
const ready = parseWorldMakingDraft(served.ready_place);
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const button = (words: string) => [...document.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.includes(words))!;
afterEach(() => { document.body.replaceChildren(); vi.useRealTimers(); vi.restoreAllMocks(); });

it('returns from setup with the description intact and rechecks availability', async () => {
  const absent = { ...offer, offered: false, code: 'provider_credential_absent', detail: null };
  const readOffer = vi.fn().mockResolvedValueOnce(absent).mockResolvedValue(offer);
  const start = vi.fn();
  const handle = buildWorldCreation({ readOffer, start, read: vi.fn(), open: vi.fn(), onClose: vi.fn(), setupURL: '/docs/self-hosting' });
  handle.show(); await flush();
  const field = document.querySelector('textarea')!;
  field.value = 'A floating observatory'; field.dispatchEvent(new Event('input'));
  field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true, cancelable: true }));
  expect(document.querySelector('[aria-label="AI connection"]')).not.toBeNull();
  expect(document.querySelector('textarea')?.value).toBe('A floating observatory');
  expect(document.querySelector('a')?.getAttribute('href')).toBe('/docs/self-hosting');
  document.querySelector('textarea')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })); await flush();
  expect(handle.root.open).toBe(true);
  expect(document.querySelector('textarea')?.value).toBe('A floating observatory');
  expect(button('Create world').disabled).toBe(false);
  expect(readOffer).toHaveBeenCalledTimes(2);
  expect(start).not.toHaveBeenCalled();
  handle.remove();
});

it('submits once, follows the served draft, and opens its saved result', async () => {
  vi.useFakeTimers();
  const started = parseWorldMakingDraft(served.started);
  vi.setSystemTime(new Date(offer.operation!.document['read_at'] as string));
  vi.spyOn(crypto, 'randomUUID').mockReturnValue(served.started.request_id);
  const start = vi.fn(async () => started);
  const read = vi.fn(async () => ready);
  const open = vi.fn(async () => undefined);
  const handle = buildWorldCreation({ readOffer: async () => offer, start, read, open, onClose: vi.fn() });
  handle.show(); await flush();
  const field = document.querySelector('textarea')!;
  field.value = 'A floating observatory'; field.dispatchEvent(new Event('input'));
  const enter = () => field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true, cancelable: true }));
  enter(); enter(); await flush();
  expect(start).toHaveBeenCalledOnce();
  expect(start).toHaveBeenCalledWith('A floating observatory', {
    idempotencyKey: started.requestId, operation: offer.operation, maximumUsd: offer.operation!.maximumUsd,
  });
  expect(document.querySelector('.world-sentence-status')!.textContent).toContain('Waiting to start');
  await vi.advanceTimersByTimeAsync((started.pollAfterSeconds ?? 1) * 1000); await flush();
  expect(read).toHaveBeenCalledWith(started.draftId);
  expect(button('Open world').hidden).toBe(false);
  expect(button('Create world').hidden).toBe(true);
  button('Open world').click(); await flush();
  expect(open).toHaveBeenCalledWith(ready.entry);
  handle.remove();
});

it('keeps editable input through a missing route and a failed recheck, then restores it', async () => {
  const readOffer = vi.fn().mockRejectedValueOnce(new ApiError(404, 'http_404', 'Not Found'))
    .mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValue(offer);
  const memory = { value: 'An observatory above the clouds' };
  const start = vi.fn();
  const handle = buildWorldCreation({ readOffer, start, read: vi.fn(), open: vi.fn(), onClose: vi.fn(), descriptionMemory: memory });
  handle.show(); await flush();
  expect(handle.root.textContent).toContain('update the API');
  const field = document.querySelector('textarea')!;
  expect(field.value).toBe(memory.value);
  field.value = 'A forest observatory'; field.dispatchEvent(new Event('input', { bubbles: true }));
  button('Try again').click(); await flush();
  expect(handle.root.textContent).toContain('Check your connection');
  expect(document.querySelector('textarea')!.value).toBe('A forest observatory');
  button('Try again').click(); await flush();
  expect(document.querySelector('textarea')!.value).toBe('A forest observatory');
  expect(button('Create world').disabled).toBe(false);
  expect(start).not.toHaveBeenCalled();
  handle.remove();
});

it.each([
  [new ApiError(401, 'unauthenticated', 'unauthenticated'), 'sign in again'],
  [new ApiError(403, 'not_permitted', 'not permitted'), 'not permitted'],
  [new TypeError('The server returned an invalid draft offer.'), 'versions match'],
])('keeps offer refusal meanings distinct', async (error, words) => {
  const handle = buildWorldCreation({ readOffer: async () => { throw error; }, start: vi.fn(), read: vi.fn(), open: vi.fn(), onClose: vi.fn() });
  handle.show(); await flush();
  expect(handle.root.textContent).toContain(words);
  expect(document.querySelector('textarea')).not.toBeNull();
  handle.remove();
});

it('restores an unresolved request after the dialog closes without overwriting its words or ceiling', async () => {
  const now = Date.now();
  const quote = {
    profile: 'exulanica.world-draft-operation/v1', basis: 'full_context_reservation_ceiling',
    estimate_is_expected_spend: false, maximum_usd: '0.73123456',
    read_at: new Date(now).toISOString(), expires_at: new Date(now + 60_000).toISOString(),
    document_sha256: 'a'.repeat(64),
  };
  const original = parseWorldDraftOffer({ ...served.offer, operation: quote });
  const later = parseWorldDraftOffer({ ...served.offer, operation: { ...quote, maximum_usd: '1.25000000' } });
  const memory: import('../src/world-making-api.js').WorldMakingMemory = { pending: null };
  const start = vi.fn().mockRejectedValue(new TypeError('Disconnected'));
  const settings = { readOffer: async () => original, start, memory, read: vi.fn(), open: vi.fn(), onClose: vi.fn() };
  const first = buildWorldCreation(settings);
  first.show(); await flush();
  const field = document.querySelector('textarea')!;
  field.value = 'A floating observatory'; field.dispatchEvent(new Event('input'));
  button('Create world').click(); await flush();
  first.remove();
  const second = buildWorldCreation({ ...settings, readOffer: async () => later, descriptionMemory: { value: 'unrelated previous field' } });
  second.show(); await flush();
  expect(document.querySelector('textarea')!.value).toBe('A floating observatory');
  expect(document.querySelector('textarea')!.readOnly).toBe(true);
  expect(document.querySelector('.world-sentence-spend')!.textContent).toContain('US$0.73123456');
  expect(start).toHaveBeenCalledOnce();
  button('Check request').click(); await flush();
  expect(start.mock.calls[1]).toEqual(start.mock.calls[0]);
  second.remove();
});
