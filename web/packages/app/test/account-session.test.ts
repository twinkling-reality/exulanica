import { describe, expect, it, vi } from 'vitest';
import { readBrowserAccount } from '../src/account-session.js';

describe('browser account session', () => {
  it('accepts a server-resolved session and includes browser credentials', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      user_id: 'user', actor: 'actor', workspace_id: 'workspace',
      expires_at: '2026-09-14T00:00:00Z', csrf_token: 'csrf',
    }), { status: 200, headers: { 'content-type': 'application/json' } }));
    const result = await readBrowserAccount(fetcher as typeof fetch);
    expect(result).toMatchObject({ kind: 'authenticated', session: { csrfToken: 'csrf' } });
    expect(fetcher).toHaveBeenCalledWith('/api/auth/session', expect.objectContaining({ credentials: 'include' }));
  });

  it('distinguishes signed out from a host without account configuration', async () => {
    await expect(readBrowserAccount(async () => new Response(null, { status: 401 }))).resolves.toEqual({ kind: 'signed-out' });
    await expect(readBrowserAccount(async () => new Response(null, { status: 503 }))).resolves.toEqual({ kind: 'unavailable' });
  });

  it('rejects an incomplete successful response', async () => {
    await expect(readBrowserAccount(async () => new Response(JSON.stringify({ csrf_token: 'csrf' }), {
      status: 200, headers: { 'content-type': 'application/json' },
    }))).rejects.toThrow('Invalid account session');
  });
});
