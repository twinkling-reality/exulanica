import { afterEach, describe, expect, it, vi } from 'vitest';
import { listBatches } from '../src/formation.js';

afterEach(() => vi.unstubAllGlobals());

describe('formation batch authentication', () => {
  it('uses the account cookie without sending an empty bearer credential', async () => {
    const fetch = vi.fn(async (_input: string | URL | Request, init: RequestInit = {}) => {
      expect(init.headers).toEqual({});
      expect(init.credentials).toBe('include');
      return new Response(JSON.stringify([]), { status: 200 });
    });
    vi.stubGlobal('fetch', fetch);

    await expect(listBatches({ baseUrl: 'https://fixture.test', token: '' })).resolves.toEqual([]);
    expect(fetch).toHaveBeenCalledOnce();
  });

  it('preserves bearer authentication for workspace clients', async () => {
    const fetch = vi.fn(async (_input: string | URL | Request, init: RequestInit = {}) => {
      expect(init.headers).toEqual({ authorization: 'Bearer workspace-token' });
      expect(init.credentials).toBe('include');
      return new Response(JSON.stringify([]), { status: 200 });
    });
    vi.stubGlobal('fetch', fetch);

    await expect(listBatches({ baseUrl: 'https://fixture.test', token: 'workspace-token' }))
      .resolves.toEqual([]);
  });
});
