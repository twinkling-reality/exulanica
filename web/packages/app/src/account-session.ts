import { toApiError } from '@exulanica/graph-client';

export interface BrowserAccountSession {
  readonly userId: string;
  readonly actor: string;
  readonly workspaceId: string;
  readonly expiresAt: string;
  readonly csrfToken: string;
}

export type BrowserAccountState =
  | { readonly kind: 'authenticated'; readonly session: BrowserAccountSession }
  | { readonly kind: 'signed-out' }
  | { readonly kind: 'unavailable' };

const nonempty = (value: unknown): value is string => typeof value === 'string' && value.length > 0;

/** Reads only the server-resolved HttpOnly session. It never stores account or CSRF data. */
export async function readBrowserAccount(
  fetcher: typeof globalThis.fetch = globalThis.fetch.bind(globalThis),
): Promise<BrowserAccountState> {
  const response = await fetcher('/api/auth/session', {
    method: 'GET', credentials: 'include', headers: { accept: 'application/json' },
  });
  if (response.status === 401) return { kind: 'signed-out' };
  if (response.status === 503) return { kind: 'unavailable' };
  if (!response.ok) throw await toApiError(response);
  const value = await response.json() as Record<string, unknown>;
  const fields = ['user_id', 'actor', 'workspace_id', 'expires_at', 'csrf_token'] as const;
  if (!fields.every(field => nonempty(value[field])) || !Number.isFinite(Date.parse(value.expires_at as string))) {
    throw new Error('Invalid account session response');
  }
  return { kind: 'authenticated', session: Object.freeze({
    userId: value.user_id as string, actor: value.actor as string,
    workspaceId: value.workspace_id as string, expiresAt: value.expires_at as string,
    csrfToken: value.csrf_token as string,
  }) };
}
