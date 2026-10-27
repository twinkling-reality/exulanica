/**
 * Browser account session: the server-resolved HttpOnly cookie, and nothing stored here.
 *
 * `GET /api/auth/session` returns the membership, workspace, and CSRF token the cookie
 * already holds. This module never writes credentials to storage. Cookie-authenticated
 * writes still require that CSRF token and an exact origin.
 */

import { toApiError } from '@exulanica/graph-client';

export interface BrowserAccountSession {
  readonly userId: string;
  readonly actor: string;
  readonly workspaceId: string;
  readonly expiresAt: string;
  readonly csrfToken: string;
}

/**
 * How a signed-out browser may come in, as the server states it beside its refusal (`sign_in`):
 * Google, and a guest entry that asks for a code, takes none, or is off. Null where the answer
 * states none (a server older than the field), and the page then judges by the status as before.
 */
export interface SignInModes {
  readonly google: boolean;
  readonly guest: 'code' | 'open' | 'off';
}

/**
 * A signed-out answer: how a browser may come in (`signIn`), and the day this host keeps what is made on it until
 * (`hostKeepsUntil`, `YYYY-MM-DD`), where the server states them.
 */
export type BrowserAccountState =
  | { readonly kind: 'authenticated'; readonly session: BrowserAccountSession }
  | { readonly kind: 'signed-out'; readonly signIn?: SignInModes | null; readonly hostKeepsUntil?: string | null }
  | { readonly kind: 'unavailable'; readonly signIn?: SignInModes | null; readonly hostKeepsUntil?: string | null };

const nonempty = (value: unknown): value is string => typeof value === 'string' && value.length > 0;

/** Reads only the server-resolved HttpOnly session. It never stores account or CSRF data. */
export async function readBrowserAccount(
  fetcher: typeof globalThis.fetch = globalThis.fetch.bind(globalThis),
): Promise<BrowserAccountState> {
  const response = await fetcher('/api/auth/session', {
    method: 'GET', credentials: 'include', headers: { accept: 'application/json' },
  });
  if (response.status === 401 || response.status === 503) {
    const kind = response.status === 401 ? 'signed-out' : 'unavailable';
    // The sign-in modes and the host's day only where the answer states them.
    const body = await answerBody(response);
    const signIn = signInModes(body);
    const kept = hostKeepsUntil(body);
    return { kind, ...(signIn === null ? {} : { signIn }), ...(kept === null ? {} : { hostKeepsUntil: kept }) };
  }
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

/** A signed-out answer's body, or null where it is not an object that reads. */
async function answerBody(response: Response): Promise<Readonly<Record<string, unknown>> | null> {
  try {
    const body: unknown = await response.json();
    return body !== null && typeof body === 'object' && !Array.isArray(body) ? body as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

/** The sign-in modes a signed-out answer states, or null where it states none or none that reads. */
function signInModes(body: Readonly<Record<string, unknown>> | null): SignInModes | null {
  const modes = body?.['sign_in'];
  if (modes === null || modes === undefined || typeof modes !== 'object' || Array.isArray(modes)) return null;
  const { google, guest } = modes as Record<string, unknown>;
  if (typeof google !== 'boolean' || (guest !== 'code' && guest !== 'open' && guest !== 'off')) return null;
  return Object.freeze({ google, guest });
}

/** The day a signed-out answer states this host keeps what is made on it until (`YYYY-MM-DD`), or null. */
function hostKeepsUntil(body: Readonly<Record<string, unknown>> | null): string | null {
  const day = body?.['host_keeps_until'];
  return typeof day === 'string' && /^\d{4}-\d{2}-\d{2}$/u.test(day) ? day : null;
}

/**
 * Enter as a guest (`POST /api/auth/guest`, same origin): with the code where the server asks for
 * one. Its answer sets the session cookie; a refusal throws as an `ApiError` by its code
 * (`guest_entry_code_wrong`, `guest_entries_exhausted` with `retry_after_seconds`, `guest_entry_off`,
 * `guest_entry_unavailable`, `origin_not_permitted`).
 */
export async function enterAsGuest(
  code: string | null,
  fetcher: typeof globalThis.fetch = globalThis.fetch.bind(globalThis),
): Promise<void> {
  const response = await fetcher('/api/auth/guest', {
    method: 'POST', credentials: 'include',
    headers: { accept: 'application/json', 'content-type': 'application/json' },
    body: JSON.stringify(code === null ? {} : { code }),
  });
  if (!response.ok) throw await toApiError(response);
}
